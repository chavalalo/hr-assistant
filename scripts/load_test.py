"""Prueba de carga contra el HR Assistant (spec/05-reto.md, punto 9).

Uso::

    SMOKE_API_KEY=<clave> python scripts/load_test.py <url> \\
        [--requests 60] [--concurrency 10]

Manda ``--requests`` peticiones a ``POST /ask`` con ``--concurrency`` hilos,
alternando preguntas de directorio y de políticas. Reporta el conteo por código
de estado, p50, p95, peticiones por segundo y costo total.

La clave se lee solo de la variable ``SMOKE_API_KEY``, nunca de un argumento,
para que no quede en el historial de la terminal. Nunca se imprime.

Códigos de salida: 0 si no hubo ``5xx`` ni fallas de conexión, 1 si los hubo y
2 si el uso es incorrecto o falta la clave. Los ``429`` (límite por minuto) se
reportan pero no hacen fallar la prueba.
"""

import argparse
import math
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
API_KEY_HEADER = "X-API-Key"
DEFAULT_REQUESTS = 60
DEFAULT_CONCURRENCY = 10
# Render despierta el servicio dormido del plan gratuito en hasta un minuto
TIMEOUT_SECONDS = 90
OK_STATUS = 200
SERVER_ERROR_MIN = 500
# Etiqueta del conteo cuando no hubo respuesta HTTP (conexión, timeout)
NO_RESPONSE = "sin respuesta"
# Preguntas de directorio y de políticas para pasar por ambos especialistas
QUESTIONS = (
    "¿Quién es EMP-0004?",
    "¿Cuántos días de vacaciones me tocan?",
    "¿Quiénes trabajan en el departamento de Finanzas?",
    "¿Cuál es la política de trabajo remoto?",
    "Compara a los empleados del departamento de Tecnología",
)


def positive_int(text):
    """Convierte un argumento en entero mayor que 0.

    :param text: Valor recibido en la línea de comandos
    :type text: str
    :return: El entero
    :rtype: int
    :raises argparse.ArgumentTypeError: Si no es un entero mayor que 0
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError("debe ser un entero") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que 0")
    return value


def parse_args(args):
    """Lee los argumentos de la línea de comandos.

    :param args: Argumentos sin el nombre del programa
    :type args: list[str]
    :return: ``url``, ``requests`` y ``concurrency``
    :rtype: argparse.Namespace
    """
    parser = argparse.ArgumentParser(
        description="Prueba de carga contra POST /ask.",
        epilog=f"La clave se lee de la variable {KEY_VARIABLE}.",
    )
    parser.add_argument("url", help="URL base del servicio")
    parser.add_argument(
        "--requests",
        type=positive_int,
        default=DEFAULT_REQUESTS,
        help=f"peticiones en total (por omisión {DEFAULT_REQUESTS})",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=DEFAULT_CONCURRENCY,
        help=f"hilos en paralelo (por omisión {DEFAULT_CONCURRENCY})",
    )
    return parser.parse_args(args)


def send_one(client, url, key, index):
    """Manda una pregunta y mide su latencia.

    :param client: Cliente HTTP compartido entre hilos
    :type client: httpx.Client
    :param url: URL base del servicio, sin ``/`` final
    :type url: str
    :param key: Clave del cliente
    :type key: str
    :param index: Número de la petición; elige la pregunta
    :type index: int
    :return: Código de estado (o ``NO_RESPONSE``), latencia en ms y costo
    :rtype: tuple[int or str, float, float]
    """
    question = QUESTIONS[index % len(QUESTIONS)]
    start = time.perf_counter()
    try:
        response = client.post(
            f"{url}/ask",
            json={"question": question},
            headers={API_KEY_HEADER: key},
        )
    except httpx.HTTPError:
        # Sin el mensaje: podría incluir encabezados con la clave
        return NO_RESPONSE, (time.perf_counter() - start) * 1000, 0.0
    latency_ms = (time.perf_counter() - start) * 1000
    return response.status_code, latency_ms, response_cost(response)


def response_cost(response):
    """Lee ``cost_usd`` de una respuesta ``200``; cualquier otra cuesta 0.

    :param response: Respuesta de ``POST /ask``
    :type response: httpx.Response
    :return: Costo en USD
    :rtype: float
    """
    if response.status_code != OK_STATUS:
        return 0.0
    try:
        cost = response.json().get("cost_usd", 0.0)
    except (ValueError, AttributeError):
        return 0.0
    return float(cost) if isinstance(cost, (int, float)) else 0.0


def percentile(sorted_values, fraction):
    """Calcula un percentil por rango más cercano.

    :param sorted_values: Valores ordenados de menor a mayor, al menos uno
    :type sorted_values: list[float]
    :param fraction: Percentil entre 0 y 1 (0.95 para p95)
    :type fraction: float
    :return: El valor del percentil
    :rtype: float
    """
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


def run_load(url, key, total, concurrency):
    """Corre la carga con un grupo de hilos.

    :param url: URL base del servicio, sin ``/`` final
    :type url: str
    :param key: Clave del cliente
    :type key: str
    :param total: Peticiones en total
    :type total: int
    :param concurrency: Hilos en paralelo
    :type concurrency: int
    :return: Resultados por petición y segundos que tardó toda la carga
    :rtype: tuple[list[tuple], float]
    """
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        began = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(
                pool.map(lambda index: send_one(client, url, key, index), range(total))
            )
        elapsed = time.perf_counter() - began
    return results, elapsed


def is_failure(status):
    """Indica si un resultado hace fallar la prueba.

    :param status: Código de estado o ``NO_RESPONSE``
    :type status: int or str
    :return: ``True`` con ``5xx`` o sin respuesta
    :rtype: bool
    """
    return status == NO_RESPONSE or status >= SERVER_ERROR_MIN


def report(results, elapsed, concurrency):
    """Imprime el resumen de la carga.

    :param results: Código, latencia en ms y costo de cada petición
    :type results: list[tuple]
    :param elapsed: Segundos que tardó toda la carga
    :type elapsed: float
    :param concurrency: Hilos en paralelo
    :type concurrency: int
    :return: ``True`` si no hubo ``5xx`` ni fallas de conexión
    :rtype: bool
    """
    codes = Counter(status for status, _, _ in results)
    latencies = sorted(latency for _, latency, _ in results)
    total_cost = sum(cost for _, _, cost in results)
    print(f"peticiones: {len(results)}  concurrencia: {concurrency}")
    for status in sorted(codes, key=str):
        print(f"  {status}: {codes[status]}")
    print(f"p50_ms: {statistics.median(latencies):.1f}")
    print(f"p95_ms: {percentile(latencies, 0.95):.1f}")
    print(f"rps: {len(results) / elapsed:.1f}")
    print(f"costo_total_usd: {total_cost:.6f}")
    failures = sum(count for status, count in codes.items() if is_failure(status))
    if codes.get(429):
        print("Aviso: hubo 429 (límite por minuto); no cuentan como falla.")
    if failures:
        print(f"[FAIL] {failures} peticiones con 5xx o sin respuesta")
        return False
    print("[OK] ninguna petición con 5xx")
    return True


def main(args):
    """Corre la prueba de carga.

    :param args: Argumentos de la línea de comandos sin el nombre del programa
    :type args: list[str]
    :return: 0 si pasa, 1 si hubo ``5xx`` o fallas de conexión, 2 sin clave
    :rtype: int
    """
    options = parse_args(args)
    key = os.environ.get(KEY_VARIABLE, "")
    if not key:
        print(f"Uso: {KEY_VARIABLE}=<clave> python scripts/load_test.py <url>")
        return 2
    results, elapsed = run_load(
        options.url.rstrip("/"), key, options.requests, options.concurrency
    )
    return 0 if report(results, elapsed, options.concurrency) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
