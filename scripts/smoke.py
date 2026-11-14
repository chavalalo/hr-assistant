"""Prueba de humo contra el HR Assistant publicado (spec/04-production.md, punto 8).

Uso: ``SMOKE_API_KEY=<clave> python scripts/smoke.py https://<servicio>.onrender.com``

La clave se lee solo de la variable ``SMOKE_API_KEY``, nunca de un argumento,
para que no quede en el historial de la terminal. Nunca se imprime.
"""

import os
import sys

import httpx

KEY_VARIABLE = "SMOKE_API_KEY"
API_KEY_HEADER = "X-API-Key"
QUESTION = {"question": "¿Quién es EMP-0004?"}
# Render despierta el servicio dormido del plan gratuito en hasta un minuto
TIMEOUT_SECONDS = 90


def run_checks(url: str, key: str, client: httpx.Client) -> bool:
    """Comprueba ``/health``, ``/ask`` sin clave y ``/ask`` con clave.

    Imprime ``[OK]`` o ``[FAIL]`` por cada una con el código recibido, que dice
    la causa de una falla (401: la clave no coincide; 502: el modelo no responde).

    :param url: URL base del servicio, sin ``/`` final
    :type url: str
    :param key: Clave de un cliente
    :type key: str
    :param client: Cliente HTTP
    :type client: httpx.Client
    :return: ``True`` si las tres comprobaciones pasan
    :rtype: bool
    """
    checks = [
        ("GET /health", 200, client.get(f"{url}/health")),
        ("POST /ask sin clave", 401, client.post(f"{url}/ask", json=QUESTION)),
        (
            "POST /ask con clave",
            200,
            client.post(f"{url}/ask", json=QUESTION, headers={API_KEY_HEADER: key}),
        ),
    ]
    passed = True
    for name, expected, response in checks:
        ok = response.status_code == expected
        passed = passed and ok
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name} -> {response.status_code} (esperado {expected})")
    return passed


def main(args: list[str]) -> int:
    """Corre la prueba de humo.

    :param args: Argumentos de la línea de comandos sin el nombre del programa
    :type args: list[str]
    :return: 0 si todo pasa, 1 si algo falla, 2 si el uso es incorrecto
    :rtype: int
    """
    key = os.environ.get(KEY_VARIABLE, "")
    if len(args) != 1 or not key:
        print(f"Uso: {KEY_VARIABLE}=<clave> python scripts/smoke.py <url>")
        return 2
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            passed = run_checks(args[0].rstrip("/"), key, client)
    except httpx.HTTPError as error:
        # Solo el tipo de error: el mensaje podría incluir encabezados
        print(f"[FAIL] no se pudo conectar ({type(error).__name__})")
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
