"""Métricas en memoria de este proceso: operativas, de negocio y de seguridad.

Son contadores que se pierden al reiniciar: no guardan preguntas, respuestas
ni datos de empleados.
"""

import math
import threading
from collections import deque

from app.costs import COST_DECIMALS

LATENCY_WINDOW = 1000
SERVER_ERROR_STATUS = 500
BLOCKED_INPUTS = "blocked_inputs"
PII_REDACTIONS = "pii_redactions"
OUTPUT_BLOCKED = "output_blocked"
ACCESS_DENIED = "access_denied"
SECURITY_COUNTERS = (BLOCKED_INPUTS, PII_REDACTIONS, OUTPUT_BLOCKED, ACCESS_DENIED)
SUPERVISOR_RULE = "rule"
SUPERVISOR_MODEL = "model"
SUPERVISOR_COUNTERS = (SUPERVISOR_RULE, SUPERVISOR_MODEL)


def _empty_tally():
    """Contador nuevo de un especialista o un cliente.

    :return: ``requests`` en 0 y ``cost_usd`` en 0.0
    :rtype: dict
    """
    return {"requests": 0, "cost_usd": 0.0}


def _rounded_tallies(tallies):
    """Copia los contadores por nombre con el costo redondeado.

    :param tallies: Contadores por nombre
    :type tallies: dict[str, dict]
    :return: Copia con ``cost_usd`` redondeado a ``COST_DECIMALS``
    :rtype: dict[str, dict]
    """
    return {
        name: {
            "requests": tally["requests"],
            "cost_usd": round(tally["cost_usd"], COST_DECIMALS),
        }
        for name, tally in sorted(tallies.items())
    }


def nearest_rank(sorted_values, percentile):
    """Calcula un percentil por rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor
    :type sorted_values: list[float]
    :param percentile: Percentil entre 0 y 100
    :type percentile: float
    :return: El valor del percentil, o ``0.0`` si no hay valores
    :rtype: float
    """
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(percentile / 100 * len(sorted_values)))
    return float(sorted_values[rank - 1])


class Metrics:  # pylint: disable=too-many-instance-attributes
    """Cuenta peticiones, errores, latencias, tokens y costo de este proceso.

    ``snapshot`` conserva el formato de la sesión 2; ``GET /metrics`` le agrega
    el costo acumulado de ``cost_usd()``, ``business()`` (por especialista, por
    cliente y supervisor), ``security()``, ``cache()`` y ``fallbacks()``. Cada
    contador se lee y se escribe bajo el mismo candado.

    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param window: Cuántas latencias recientes se guardan
    :type window: int
    """

    def __init__(self, slo_p95_ms, window=LATENCY_WINDOW):
        self._slo_p95_ms = slo_p95_ms
        self._latencies = deque(maxlen=window)
        self._requests = 0
        self._errors = 0
        self._tokens = {"input": 0, "output": 0}
        self._cost_usd = 0.0
        self._security = dict.fromkeys(SECURITY_COUNTERS, 0)
        self._cache = {"hits": 0, "misses": 0}
        self._fallbacks = 0
        self._by_specialist = {}
        self._by_client = {}
        self._supervisor = dict.fromkeys(SUPERVISOR_COUNTERS, 0)
        self._lock = threading.Lock()

    def record_request(self, latency_ms, status):
        """Registra una petición terminada.

        :param latency_ms: Latencia en milisegundos
        :type latency_ms: float
        :param status: Código HTTP de la respuesta
        :type status: int
        """
        with self._lock:
            self._requests += 1
            if status >= SERVER_ERROR_STATUS:
                self._errors += 1
            self._latencies.append(float(latency_ms))

    def add_tokens(self, input_tokens, output_tokens):
        """Suma los tokens de una corrida del agente.

        :param input_tokens: Tokens de entrada
        :type input_tokens: int
        :param output_tokens: Tokens de salida
        :type output_tokens: int
        """
        with self._lock:
            self._tokens["input"] += input_tokens
            self._tokens["output"] += output_tokens

    def add_cost(self, cost_usd):
        """Suma el costo en USD de una respuesta.

        :param cost_usd: Costo de la respuesta
        :type cost_usd: float
        """
        with self._lock:
            self._cost_usd += cost_usd

    def add_security(self, counter, amount=1):
        """Suma a un contador de seguridad.

        :param counter: Uno de ``SECURITY_COUNTERS``
        :type counter: str
        :param amount: Cuánto sumar (``pii_redactions`` suma valores ocultados)
        :type amount: int
        :raises KeyError: Si el contador no existe
        """
        with self._lock:
            self._security[counter] += amount

    def security(self):
        """Devuelve los contadores de seguridad de este proceso.

        :return: ``blocked_inputs``, ``pii_redactions``, ``output_blocked`` y
            ``access_denied``
        :rtype: dict[str, int]
        """
        with self._lock:
            return dict(self._security)

    def record_cache(self, hit):
        """Cuenta una consulta a la caché de respuestas.

        :param hit: ``True`` si hubo acierto; ``False`` si fue un fallo
        :type hit: bool
        """
        with self._lock:
            self._cache["hits" if hit else "misses"] += 1

    def cache(self):
        """Devuelve aciertos, fallos y tasa de aciertos de la caché.

        :return: ``hits``, ``misses`` y ``hit_rate`` (0.0 sin consultas)
        :rtype: dict
        """
        with self._lock:
            hits = self._cache["hits"]
            misses = self._cache["misses"]
        total = hits + misses
        return {
            "hits": hits,
            "misses": misses,
            "hit_rate": hits / total if total else 0.0,
        }

    def add_fallback(self):
        """Cuenta una respuesta del modelo de respaldo."""
        with self._lock:
            self._fallbacks += 1

    def fallbacks(self):
        """Devuelve cuántas respuestas dio el modelo de respaldo.

        :return: Respuestas del modelo de respaldo
        :rtype: int
        """
        with self._lock:
            return self._fallbacks

    def record_answer(self, client, outcome, supervisor=None):
        """Suma una respuesta ``200`` de ``POST /ask`` (también las de caché).

        En una sola toma del candado suma tokens, costo total, la petición y
        su costo por especialista y por cliente, y la decisión del supervisor.

        :param client: Nombre del cliente que preguntó
        :type client: str
        :param outcome: Resultado con ``specialist``, ``cost_usd``,
            ``input_tokens`` y ``output_tokens``
        :type outcome: app.pipeline.AskOutcome
        :param supervisor: ``rule`` o ``model`` si corrió el supervisor;
            ``None`` si no corrió (acierto de caché)
        :type supervisor: str or None
        :raises KeyError: Si ``supervisor`` no es uno de ``SUPERVISOR_COUNTERS``
        """
        cost = outcome.cost_usd
        with self._lock:
            self._tokens["input"] += outcome.input_tokens
            self._tokens["output"] += outcome.output_tokens
            self._cost_usd += cost
            for tallies, name in (
                (self._by_specialist, outcome.specialist),
                (self._by_client, client),
            ):
                tally = tallies.setdefault(name, _empty_tally())
                tally["requests"] += 1
                tally["cost_usd"] += cost
            if supervisor is not None:
                self._supervisor[supervisor] += 1

    def business(self):
        """Devuelve las métricas de negocio de este proceso.

        :return: ``by_specialist`` y ``by_client`` (``requests`` y
            ``cost_usd`` por nombre) y ``supervisor`` (``rule`` y ``model``)
        :rtype: dict
        """
        with self._lock:
            by_specialist = _rounded_tallies(self._by_specialist)
            by_client = _rounded_tallies(self._by_client)
            supervisor = dict(self._supervisor)
        return {
            "by_specialist": by_specialist,
            "by_client": by_client,
            "supervisor": supervisor,
        }

    def cost_usd(self):
        """Devuelve el costo acumulado de este proceso.

        :return: Costo en USD redondeado a ``COST_DECIMALS`` decimales
        :rtype: float
        """
        with self._lock:
            return round(self._cost_usd, COST_DECIMALS)

    def snapshot(self, pid):
        """Devuelve las métricas con el formato de ``GET /metrics``.

        :param pid: Id del proceso que reporta
        :type pid: int
        :return: Peticiones, tasa de error, percentiles, tokens y SLO
        :rtype: dict
        """
        with self._lock:
            latencies = sorted(self._latencies)
            requests = self._requests
            errors = self._errors
            tokens = dict(self._tokens)
        p95 = nearest_rank(latencies, 95)
        target = self._slo_p95_ms
        return {
            "pid": pid,
            "requests": requests,
            "error_rate": errors / requests if requests else 0.0,
            "latency_ms": {"p50": nearest_rank(latencies, 50), "p95": p95},
            "tokens": tokens,
            "slo": {"p95_ms_target": target, "met": p95 < target},
        }
