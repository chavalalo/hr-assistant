"""Pasos de ``features/guardrails.feature``: guardián, revisor y mínimo privilegio."""

import json

from pytest_bdd import given, parsers, scenarios, then, when

from app.completion import Completion

scenarios("features/guardrails.feature")

SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
BLOCKED_DETAIL = "request blocked by input policy"
INVENTED_ANSWER_START = "El responsable del área es"
# Claves de prueba (16+ caracteres): no son secretos reales.
KEYS = {"tester": "tester-key-0123456789", "admin": "admin-key-0123456789"}


class InventingModel:  # pylint: disable=too-few-public-methods
    """Modelo simulado que contesta citando un id que la persona no escribió.

    :param invented_id: Id ``EMP-dddd`` que el modelo se inventa
    :type invented_id: str
    """

    def __init__(self, invented_id):
        self.invented_id = invented_id

    def complete(self, messages):
        """Responde siempre con el id inventado, sin pedir herramientas.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta final del especialista
        :rtype: app.completion.Completion
        """
        answer = f"{INVENTED_ANSWER_START} {self.invented_id}."
        text = json.dumps({"answer": answer}, ensure_ascii=False)
        return Completion(
            text=text, input_tokens=len(messages), output_tokens=len(text.split())
        )


def audits(read_log, action):
    """Líneas ``audit`` de una acción.

    :param read_log: Lector del log en memoria
    :type read_log: callable
    :param action: Acción buscada, por ejemplo ``pii_redacted``
    :type action: str
    :return: Líneas de esa acción
    :rtype: list[dict]
    """
    return [
        line
        for line in read_log()
        if line["event"] == "audit" and line["action"] == action
    ]


@given("the guarded HR assistant is running", target_fixture="client")
def guarded_assistant(make_cost_client):
    """Aplicación con los modelos simulados, reloj fijo y log en memoria."""
    return make_cost_client()


@given(
    "the guarded HR assistant is running with a spy model", target_fixture="client"
)
def guarded_assistant_with_spy(make_cost_client, spy_model, context):
    """Aplicación cuyos dos modelos son el mismo espía."""
    context["spy"] = spy_model
    return make_cost_client(models={SMALL: spy_model, LARGE: spy_model})


@given(
    parsers.parse(
        'the guarded HR assistant is running with a model that invents "{invented_id}"'
    ),
    target_fixture="client",
)
def guarded_assistant_with_inventing_model(make_cost_client, directory, invented_id):
    """Aplicación cuyo modelo cita un id que no está en el directorio."""
    assert not directory.has_employee(invented_id)
    model = InventingModel(invented_id)
    return make_cost_client(models={SMALL: model, LARGE: model})


@given(
    parsers.parse(
        'the guarded HR assistant is running for "{client_name}" '
        'and the metrics client "{metrics_client}"'
    ),
    target_fixture="client",
)
def guarded_assistant_with_metrics_client(
    make_observed_client, client_name, metrics_client
):
    """Dos clientes con clave; solo uno puede leer las métricas."""
    api_keys = ",".join(
        f"{name}:{KEYS[name]}" for name in (client_name, metrics_client)
    )
    return make_observed_client(
        {"API_KEYS": api_keys, "METRICS_CLIENTS": metrics_client}
    )


@when(parsers.parse('I send "{text}" in the {place}'), target_fixture="response")
def send_text(client, text, place, context):
    """Manda el texto como pregunta o como mensaje ``user`` del historial."""
    context["text"] = text
    if place == "question":
        payload = {"question": text}
    else:
        payload = {
            "question": "¿Quién es EMP-0004?",
            "history": [{"role": "user", "content": text}],
        }
    return client.post("/ask", json=payload, headers={"X-Request-ID": "guard-1"})


@when(
    parsers.parse('I ask about EMP-0001 mentioning "{value}"'),
    target_fixture="response",
)
def ask_with_personal_data(client, value):
    """Pregunta por un empleado e incluye un dato personal."""
    question = f"Mi dato es {value}, ¿quién es EMP-0001?"
    return client.post("/ask", json={"question": question})


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask(client, question):
    """Envía la pregunta sin historial."""
    return client.post("/ask", json={"question": question})


@when(parsers.parse('"{name}" reads the metrics'), target_fixture="response")
def reads_metrics(client, name):
    """Pide ``GET /metrics`` con la clave del cliente."""
    return client.get("/metrics", headers={"X-API-Key": KEYS[name]})


@then("the body says the request was blocked, with its request id")
def body_says_blocked(response):
    """El 400 del guardián trae un cuerpo fijo con el id de la petición."""
    assert response.json() == {"detail": BLOCKED_DETAIL, "request_id": "guard-1"}


@then("no model was called")
def no_model_was_called(context):
    """El guardián corta antes del supervisor y del especialista."""
    assert context["spy"].calls == []


@then("the audit records the blocked input without its text")
def audit_records_blocked_input(read_log, log_stream, context):
    """Queda el motivo y el cliente, nunca el texto de la persona."""
    blocked = audits(read_log, "input_blocked")
    assert len(blocked) == 1
    assert blocked[0]["reason"] == "prompt_injection"
    assert blocked[0]["client"] == "tester"
    assert context["text"] not in log_stream.getvalue()


@then(parsers.parse('the model saw "{marker}" and never "{value}"'))
def model_saw_marker(context, marker, value):
    """El modelo recibe el marcador en lugar del dato personal."""
    seen = " ".join(
        message["content"] for call in context["spy"].calls for message in call
    )
    assert marker in seen
    assert value not in seen


@then(
    parsers.parse('the answer reports the type "{kind}" without showing "{value}"')
)
def answer_reports_type(response, kind, value):
    """La respuesta dice qué tipos se ocultaron, sin el valor."""
    body = response.json()
    assert kind in body["pii_redacted"]
    assert body["pii_redacted"] == sorted(set(body["pii_redacted"]))
    assert value not in body["answer"]


@then(parsers.parse('the audit records {count:d} "{kind}" hidden in the input'))
def audit_records_pii(read_log, count, kind):
    """El audit lleva ubicación, tipos y conteo, nunca el valor."""
    hidden = [
        line
        for line in audits(read_log, "pii_redacted")
        if line["location"] == "input"
    ]
    assert len(hidden) == 1
    assert hidden[0]["types"] == [kind]
    assert hidden[0]["count"] == count
    assert hidden[0]["client"] == "tester"


@then(parsers.parse('the log never contains "{value}"'))
def log_never_contains(log_stream, value):
    """Ni el log ni el audit guardan el dato personal."""
    assert value not in log_stream.getvalue()


@then(parsers.parse('the answer is "{text}"'))
def answer_is(response, text):
    """La respuesta es exactamente el texto."""
    assert response.json()["answer"] == text


@then(parsers.parse('the audit records the blocked output for "{reason}"'))
def audit_records_blocked_output(read_log, log_stream, reason):
    """El revisor deja el motivo, sin el texto de la respuesta bloqueada."""
    blocked = audits(read_log, "output_blocked")
    assert len(blocked) == 1
    assert blocked[0]["reason"] == reason
    assert blocked[0]["client"] == "tester"
    assert INVENTED_ANSWER_START not in log_stream.getvalue()


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(response, text):
    """La respuesta contiene el texto, con sus acentos tal cual."""
    assert text in response.json()["answer"]


@then("the audit records no blocked output")
def audit_records_no_blocked_output(read_log):
    """Un id que escribió la persona no cuenta como inventado."""
    assert audits(read_log, "output_blocked") == []


@then(parsers.parse("the metrics count {count:d} blocked output"))
def metrics_count_blocked_output(client, count):
    """El contador de seguridad sube con cada respuesta reemplazada."""
    assert client.get("/metrics").json()["security"]["output_blocked"] == count


@then(parsers.parse('the body is exactly "{detail}"'))
def body_is_exactly(response, detail):
    """El cuerpo trae solo el detalle, sin datos del cliente."""
    assert response.json() == {"detail": detail}


@then(
    parsers.parse('the audit records "{action}" on "{path}" for "{client_name}"')
)
def audit_records_denied(read_log, action, path, client_name):
    """El acceso negado deja la ruta y el cliente."""
    denied = audits(read_log, action)
    assert len(denied) == 1
    assert denied[0]["path"] == path
    assert denied[0]["client"] == client_name


@then(parsers.parse('the audit records the metrics read of "{client_name}"'))
def audit_records_metrics_read(read_log, client_name):
    """La lectura permitida también queda en el audit."""
    readers = [line["client"] for line in audits(read_log, "metrics_read")]
    assert readers == [client_name]


@then(parsers.parse("the metrics count {count:d} denied access"))
def metrics_count_denied(client, count):
    """El contador de accesos negados lo lee un cliente con permiso."""
    metrics = client.get("/metrics", headers={"X-API-Key": KEYS["admin"]}).json()
    assert metrics["security"]["access_denied"] == count
