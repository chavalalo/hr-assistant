"""Métricas operativas en memoria de este proceso (no son estado de negocio)."""

import math
import threading
from collections import deque

from app.costs import COST_DECIMALS

LATENCY_WINDOW = 1000
SERVER_ERROR_STATUS = 500


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


class Metrics:
    """Cuenta peticiones, errores, latencias, tokens y costo de este proceso.

    ``snapshot`` conserva el formato de la sesión 2; ``GET /metrics`` le agrega
    el costo acumulado de ``cost_usd()``.

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
