"""Fixtures compartidas: arman la aplicación con dependencias inyectadas.

Ninguna prueba usa red ni servidor: todo pasa por ``create_app()`` y
``fastapi.testclient.TestClient``.
"""

import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))

# pylint: disable=wrong-import-position
from app.config import Settings  # noqa: E402
from app.directory import EmployeeDirectory  # noqa: E402
from app.llm import FakeModel  # noqa: E402
from app.main import create_app  # noqa: E402

DATA_PATH = PRODUCT / "data" / "employees.json"
START = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)

# Clave de prueba (16+ caracteres): no es un secreto real.
TEST_CLIENT = "tester"
TEST_API_KEY = "tester-key-0123456789"
API_KEY_HEADER = "X-API-Key"


def with_test_key(environ):
    """Agrega ``API_KEYS`` con el cliente de prueba si la prueba no lo da.

    Así las pruebas de las sesiones 1 a 3 siguen pasando sin tocar sus pasos.

    :param environ: Variables de entorno de la prueba o ``None``
    :type environ: dict or None
    :return: Copia de las variables con ``API_KEYS``
    :rtype: dict
    """
    values = dict(environ or {})
    values.setdefault("API_KEYS", f"{TEST_CLIENT}:{TEST_API_KEY}")
    return values


def keyed_client(app, **kwargs):
    """Cliente HTTP que manda la clave de prueba en cada petición.

    :param app: Aplicación FastAPI
    :type app: fastapi.FastAPI
    :return: Cliente con ``X-API-Key`` por omisión
    :rtype: fastapi.testclient.TestClient
    """
    return TestClient(app, headers={API_KEY_HEADER: TEST_API_KEY}, **kwargs)


@pytest.fixture
def directory():
    """Directorio real de empleados, leído de ``product/data/employees.json``."""
    return EmployeeDirectory(DATA_PATH)


@pytest.fixture
def fake_model(directory):
    """Modelo simulado que conoce los departamentos del directorio."""
    return FakeModel(directory.departments())


@pytest.fixture
def make_client(directory):
    """Fábrica de clientes HTTP con configuración y modelo a elección.

    :return: Función que recibe variables de entorno y un modelo opcional
    :rtype: callable
    """

    def _make(environ=None, model=None):
        settings = Settings.from_env(with_test_key(environ))
        chosen = model or FakeModel(directory.departments())
        app = create_app(settings=settings, model=chosen, directory=directory)
        return keyed_client(app)

    return _make


@pytest.fixture
def clock():
    """Reloj fijo en UTC que solo avanza cuando la prueba lo pide."""
    # Import local: si falta el módulo fallan solo las pruebas que lo usan.
    from app.clock import FixedClock  # pylint: disable=import-outside-toplevel

    return FixedClock(START)


@pytest.fixture
def log_stream():
    """Destino del log JSON en memoria, en lugar de la salida estándar."""
    return io.StringIO()


@pytest.fixture
def read_log(log_stream):
    """Lee el log escrito hasta ahora como una lista de objetos JSON.

    :return: Función sin argumentos que devuelve un dict por línea
    :rtype: callable
    """

    def _read():
        lines = log_stream.getvalue().splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    return _read


@pytest.fixture
def make_observed_client(directory, clock, log_stream):
    """Fábrica de clientes con reloj fijo, log en memoria y trazas apagadas.

    El cliente no relanza las excepciones del servidor, para poder ver el 500.

    :return: Función que recibe variables de entorno y un modelo opcional
    :rtype: callable
    """

    # Import local: si falta el módulo fallan solo las pruebas que lo usan.
    from app.tracing import NoopTracer  # pylint: disable=import-outside-toplevel

    def _make(environ=None, model=None):
        settings = Settings.from_env(with_test_key(environ))
        chosen = model or FakeModel(directory.departments())
        app = create_app(
            settings=settings,
            model=chosen,
            directory=directory,
            clock=clock,
            log_stream=log_stream,
            tracer=NoopTracer(),
        )
        return keyed_client(app, raise_server_exceptions=False)

    return _make


GATEWAY_ENVIRON = {
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "hr-gw",
    "CF_API_TOKEN": "tok-secret",
}


@pytest.fixture
def gateway_environ():
    """Variables de entorno de un gateway falso: cuenta, gateway y token de prueba.

    :return: Copia nueva de las variables para que cada prueba la amplíe
    :rtype: dict
    """
    return dict(GATEWAY_ENVIRON)


@pytest.fixture
def make_cost_client(directory, clock, log_stream):
    """Fábrica de clientes que construyen sus propios modelos y precios.

    No inyecta un único ``model``: ``create_app`` arma ``MODEL_SMALL`` y
    ``MODEL_LARGE`` (simulados o de gateway) salvo que la prueba pase ``models``.
    El ``http_client`` permite simular AI Gateway sin red.

    :return: Función que recibe variables de entorno, modelos y cliente HTTP
    :rtype: callable
    """

    # Import local: si falta el módulo fallan solo las pruebas que lo usan.
    from app.tracing import NoopTracer  # pylint: disable=import-outside-toplevel

    def _make(environ=None, models=None, http_client=None):
        settings = Settings.from_env(with_test_key(environ))
        app = create_app(
            settings=settings,
            directory=directory,
            models=models,
            http_client=http_client,
            clock=clock,
            log_stream=log_stream,
            tracer=NoopTracer(),
        )
        return keyed_client(app, raise_server_exceptions=False)

    return _make


# Pasos Gherkin compartidos por todos los escenarios.


@given("the HR assistant is running", target_fixture="client")
def running_assistant(make_client):
    """Aplicación con la configuración por omisión y el modelo simulado."""
    return make_client()


@then(parsers.parse("the response status is {status:d}"))
def response_status_is(response, status):
    """Comprueba el código HTTP de la última respuesta."""
    assert response.status_code == status
