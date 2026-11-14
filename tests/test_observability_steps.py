"""Pasos de ``features/observability.feature``: id, log JSON y métricas."""

import uuid

from pytest_bdd import given, parsers, scenarios, then, when

from app.llm import FakeModel

scenarios("features/observability.feature")

QUESTION = "¿Quién es EMP-0004?"
SECRET = "secret detail about Jorge"


class FailingModel:  # pylint: disable=too-few-public-methods
    """Modelo que siempre truena con un mensaje que no debe salir al log."""

    def complete(self, messages):
        """Lanza un error inesperado."""
        raise RuntimeError(SECRET)


class SlowModel:  # pylint: disable=too-few-public-methods
    """Modelo simulado que hace avanzar el reloj fijo en cada llamada."""

    def __init__(self, model, clock, seconds):
        self._model = model
        self._clock = clock
        self._seconds = seconds

    def complete(self, messages):
        """Avanza el reloj y delega en el modelo simulado."""
        self._clock.advance(self._seconds)
        return self._model.complete(messages)


@given("the observed HR assistant is running", target_fixture="client")
def observed_assistant(make_observed_client):
    """Aplicación con reloj fijo, log en memoria y configuración por omisión."""
    return make_observed_client()


@given(
    "the observed HR assistant is running with a model that fails",
    target_fixture="client",
)
def observed_assistant_with_failing_model(make_observed_client):
    """Aplicación cuyo modelo lanza una excepción."""
    return make_observed_client(model=FailingModel())


@given(
    parsers.parse(
        "the observed HR assistant has an SLO of {slo:d} ms "
        "and a model that takes {millis:d} ms per call"
    ),
    target_fixture="client",
)
def observed_assistant_with_slow_model(
    make_observed_client, directory, clock, slo, millis
):
    """Aplicación con meta de latencia baja y un modelo lento."""
    model = SlowModel(FakeModel(directory.departments()), clock, millis / 1000)
    return make_observed_client({"SLO_P95_MS": str(slo)}, model=model)


@when("I check the health endpoint", target_fixture="response")
def check_health(client):
    """Pide ``GET /health`` sin encabezado de id."""
    return client.get("/health")


@when(
    parsers.parse('I check the health endpoint with the request id "{request_id}"'),
    target_fixture="response",
)
def check_health_with_id(client, request_id):
    """Pide ``GET /health`` con el id del cliente."""
    return client.get("/health", headers={"X-Request-ID": request_id})


@when(
    parsers.parse(
        "I check the health endpoint with a request id of {length:d} characters"
    ),
    target_fixture="response",
)
def check_health_with_long_id(client, length):
    """Pide ``GET /health`` con un id del cliente demasiado largo."""
    return client.get("/health", headers={"X-Request-ID": "a" * length})


@when(
    parsers.parse('I ask about EMP-0004 with the request id "{request_id}"'),
    target_fixture="response",
)
def ask_with_id(client, request_id):
    """Envía la pregunta fija con el id del cliente."""
    return client.post(
        "/ask", json={"question": QUESTION}, headers={"X-Request-ID": request_id}
    )


@when("I read the metrics", target_fixture="metrics")
def read_metrics(client):
    """Pide ``GET /metrics``."""
    response = client.get("/metrics")
    assert response.status_code == 200
    return response.json()


@when("I open the home page", target_fixture="response")
def open_home_page(client):
    """Pide la página web."""
    return client.get("/")


@then("the response carries a generated request id")
def response_has_generated_id(response):
    """El encabezado trae un UUID nuevo."""
    assert uuid.UUID(response.headers["X-Request-ID"])


@then(parsers.parse('the request id "{request_id}" is in the header and in the body'))
def request_id_in_header_and_body(response, request_id):
    """El id del cliente vuelve tal cual en el encabezado y en el cuerpo."""
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id


@then(
    parsers.parse(
        'the log has the events "{events}" for the request id "{request_id}"'
    )
)
def log_has_events(read_log, events, request_id):
    """Cada evento esperado aparece y todas sus líneas llevan el mismo id."""
    lines = [line for line in read_log() if line["request_id"] == request_id]
    expected = {event.strip() for event in events.split(",")}
    assert expected <= {line["event"] for line in lines}
    for line in lines:
        assert line["service"] == "hr-assistant"
        assert line["ts"].endswith("Z")
    request_line = next(line for line in lines if line["event"] == "request")
    assert request_line["method"] == "POST"
    assert request_line["path"] == "/ask"
    assert request_line["status"] == 200
    assert request_line["latency_ms"] == 0.0


@then(
    parsers.parse(
        'the agent_run line counts the question, {steps:d} steps '
        'and the tool "{tool}"'
    )
)
def agent_run_counts(read_log, response, steps, tool):
    """El evento ``agent_run`` solo lleva conteos."""
    run = next(line for line in read_log() if line["event"] == "agent_run")
    body = response.json()
    assert run["question_chars"] == len(QUESTION)
    assert run["history_messages"] == 0
    assert run["steps"] == steps
    assert run["tools"] == [tool]
    assert run["input_tokens"] == body["input_tokens"]
    assert run["output_tokens"] == body["output_tokens"]
    assert run["stopped"] == "answer"


@then(
    parsers.parse(
        'the audit line records the tool call to "{tool}" for "{employee_id}"'
    )
)
def audit_line_records_tool(read_log, tool, employee_id):
    """Hay un ``audit`` por la herramienta que llamó el agente."""
    audits = [line for line in read_log() if line["event"] == "audit"]
    assert len(audits) == 1
    assert audits[0]["action"] == "tool_call"
    assert audits[0]["tool"] == tool
    assert audits[0]["args"] == {"employee_id": employee_id}


@then("no log line contains the question or the answer")
def log_has_no_personal_text(log_stream, response):
    """Ni la pregunta ni la respuesta aparecen en el log."""
    text = log_stream.getvalue()
    assert QUESTION not in text
    assert response.json()["answer"] not in text
    assert "Jorge" not in text


@then(
    parsers.parse(
        'the body says "{detail}" with the request id "{request_id}"'
    )
)
def body_says_detail(response, detail, request_id):
    """El 500 tiene un cuerpo fijo con el id de la petición."""
    assert response.json() == {"detail": detail, "request_id": request_id}
    assert response.headers["X-Request-ID"] == request_id


@then(
    parsers.parse(
        'the log has an error line of type "{error_type}" without the error message'
    )
)
def log_has_error_line(read_log, log_stream, error_type):
    """El evento ``error`` lleva el tipo del error, nunca su mensaje."""
    errors = [line for line in read_log() if line["event"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error_type"] == error_type
    assert SECRET not in log_stream.getvalue()
    request_line = next(line for line in read_log() if line["event"] == "request")
    assert request_line["status"] == 500


@then(
    parsers.parse(
        "the metrics count {requests:d} request and an error rate of {rate:g}"
    )
)
def metrics_count(metrics, requests, rate):
    """Peticiones contadas antes de pedir las métricas y su tasa de error."""
    assert metrics["requests"] == requests
    assert metrics["error_rate"] == rate
    assert metrics["latency_ms"] == {"p50": 0.0, "p95": 0.0}


@then("the metrics tokens match the tokens of the answer")
def metrics_tokens_match(metrics, response):
    """Los tokens del proceso son los de la única pregunta."""
    body = response.json()
    assert metrics["tokens"] == {
        "input": body["input_tokens"],
        "output": body["output_tokens"],
    }


@then(parsers.parse("the SLO target is {target:d} ms and it is met"))
def slo_is_met(metrics, target):
    """Con latencia cero la meta por omisión se cumple."""
    assert metrics["slo"] == {"p95_ms_target": target, "met": True}


@then(parsers.parse("the latency p95 is {millis:g} ms"))
def latency_p95_is(metrics, millis):
    """La latencia sale del reloj inyectado, no del reloj del sistema."""
    assert metrics["latency_ms"]["p95"] == millis


@then("the SLO is not met")
def slo_is_not_met(metrics):
    """Un p95 arriba de la meta no cumple el SLO."""
    assert metrics["slo"]["met"] is False


@then("the page shows the request id and never uses innerHTML")
def page_shows_request_id(response):
    """La página pinta el id para soporte, siempre con ``textContent``."""
    assert response.status_code == 200
    assert "request_id" in response.text
    assert "Id de la petición" in response.text
    assert "innerHTML" not in response.text
