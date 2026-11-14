"""Pasos de ``features/security.feature``: clave, límite y compliance."""

import io

from pytest_bdd import given, parsers, scenarios, then, when

from app.config import ConfigError, Settings
from app.llm import FakeModel
from app.main import create_app
from app.tracing import NoopTracer

scenarios("features/security.feature")

QUESTION = {"question": "¿Quién es EMP-0004?"}
API_KEY_HEADER = "X-API-Key"
# Debe coincidir con la clave que pone ``conftest.py``.
VALID_KEY = "tester-key-0123456789"
LONG_KEY = "ops-key-abcdefghijklmnop"
SHORT_KEY = "short-secret-15"

PRODUCTION_BASE = {
    "ENVIRONMENT": "production",
    "MODEL_PROVIDER": "gateway",
    "CF_ACCOUNT_ID": "acc-123",
    "CF_GATEWAY_ID": "hr-gw",
    "CF_API_TOKEN": "tok-secret",
    "API_KEYS": f"ops:{LONG_KEY}",
    "HIDE_INPUTS": "true",
    "HIDE_OUTPUTS": "true",
}
PROBLEMS = {
    "the fake model": {"MODEL_PROVIDER": "fake"},
    "no API keys": {"API_KEYS": ""},
    "a key of 15 characters": {"API_KEYS": f"ops:{SHORT_KEY}"},
    "tracing that shows the inputs": {
        "LANGSMITH_TRACING": "true",
        "HIDE_INPUTS": "false",
    },
}


def without_key(client):
    """Quita la clave por omisión del cliente de prueba.

    :param client: Cliente HTTP de prueba
    :type client: fastapi.testclient.TestClient
    :return: El mismo cliente, ya sin ``X-API-Key``
    :rtype: fastapi.testclient.TestClient
    """
    client.headers.pop(API_KEY_HEADER, None)
    return client


@given("the secured HR assistant is running", target_fixture="client")
def secured_assistant(make_observed_client):
    """Aplicación con un cliente ``tester``, reloj fijo y log en memoria."""
    return make_observed_client()


@given(
    parsers.parse(
        "the secured HR assistant is running with a limit of {limit:d} "
        "requests per minute"
    ),
    target_fixture="client",
)
def secured_assistant_with_limit(make_observed_client, limit):
    """Aplicación con un límite de peticiones bajo."""
    return make_observed_client({"RATE_LIMIT_PER_MINUTE": str(limit)})


@when("I ask a question without an API key", target_fixture="response")
def ask_without_key(client):
    """Pregunta sin el encabezado ``X-API-Key``."""
    return without_key(client).post("/ask", json=QUESTION)


@when(
    parsers.parse('I ask a question with the API key "{key}"'),
    target_fixture="response",
)
def ask_with_key(client, key):
    """Pregunta con una clave que no es de ningún cliente."""
    return client.post("/ask", json=QUESTION, headers={API_KEY_HEADER: key})


@when("I ask a question with the valid API key", target_fixture="response")
def ask_with_valid_key(client):
    """Pregunta con la clave del cliente ``tester``."""
    return client.post("/ask", json=QUESTION)


@when("I read the metrics without an API key", target_fixture="response")
def metrics_without_key(client):
    """Pide ``GET /metrics`` sin clave."""
    return without_key(client).get("/metrics")


@when(
    parsers.parse("I ask {count:d} questions with the valid API key"),
    target_fixture="responses",
)
def ask_many(client, count):
    """Hace varias preguntas seguidas sin que avance el reloj."""
    return [client.post("/ask", json=QUESTION) for _ in range(count)]


@when(
    parsers.parse("the clock advances {seconds:d} seconds and I ask again"),
    target_fixture="response",
)
def advance_and_ask(client, clock, seconds):
    """Hace avanzar el reloj fijo y vuelve a preguntar."""
    clock.advance(seconds)
    return client.post("/ask", json=QUESTION)


@given(
    parsers.parse("a production environment with {problem}"),
    target_fixture="environ",
)
def production_environment(problem):
    """Entorno de producción correcto salvo por un problema."""
    return {**PRODUCTION_BASE, **PROBLEMS[problem]}


@when("the assistant starts", target_fixture="startup_error")
def assistant_starts(environ, directory, clock):
    """Intenta armar la aplicación y devuelve el error de arranque, si hay."""
    try:
        settings = Settings.from_env(environ)
        create_app(
            settings=settings,
            model=FakeModel(directory.departments()),
            directory=directory,
            clock=clock,
            log_stream=io.StringIO(),
            tracer=NoopTracer(),
        )
    except ConfigError as error:
        return error
    return None


@then(parsers.parse('the body says "{detail}"'))
def body_says(response, detail):
    """El cuerpo trae exactamente el mensaje esperado."""
    assert response.json() == {"detail": detail}


@then(
    parsers.parse(
        'the public paths "{paths}" answer 200 without a key'
    )
)
def public_paths_need_no_key(client, paths):
    """Las rutas públicas responden sin ``X-API-Key``."""
    without_key(client)
    for path in (item.strip() for item in paths.split(",")):
        assert client.get(path).status_code == 200, path


@then(
    parsers.parse(
        'the request, audit and agent_run lines name the client "{name}"'
    )
)
def lines_name_the_client(read_log, name):
    """El nombre del cliente va en ``request``, ``audit`` y ``agent_run``."""
    lines = read_log()
    for event in ("request", "audit", "agent_run"):
        matching = [line for line in lines if line["event"] == event]
        assert matching, event
        assert all(line["client"] == name for line in matching), event


@then("the API key appears nowhere in the log")
def key_not_in_log(log_stream):
    """Ni la clave ni su comienzo se escriben en el log."""
    text = log_stream.getvalue()
    assert VALID_KEY not in text
    assert VALID_KEY[:8] not in text


@then(parsers.parse('the statuses are "{statuses}"'))
def statuses_are(responses, statuses):
    """Los códigos HTTP de las preguntas, en orden."""
    expected = [int(status) for status in statuses.split(",")]
    assert [response.status_code for response in responses] == expected


@then(
    parsers.parse(
        'the last response says "{detail}" with a Retry-After of {seconds:d} seconds'
    )
)
def last_response_is_limited(responses, detail, seconds):
    """El 429 dice cuántos segundos faltan para volver a preguntar."""
    last = responses[-1]
    assert last.json() == {"detail": detail}
    assert last.headers["Retry-After"] == str(seconds)


@then(
    parsers.parse(
        'it refuses to start naming "{variable}" without showing the key'
    )
)
def refuses_to_start(startup_error, variable):
    """El error nombra la regla que falla, nunca un valor secreto."""
    assert isinstance(startup_error, ConfigError)
    message = str(startup_error)
    assert variable in message
    for secret in (LONG_KEY, SHORT_KEY, "tok-secret"):
        assert secret not in message
