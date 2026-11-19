"""Pasos de ``features/costs.feature``: enrutador, ventana, gateway y costo."""

import httpx
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/costs.feature")

SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
GATEWAY_PROMPT_TOKENS = 42
GATEWAY_COMPLETION_TOKENS = 7


def gateway_client(status, headers=None):
    """Cliente HTTP sin red que responde siempre lo mismo, como AI Gateway.

    :param status: Código HTTP de la respuesta
    :type status: int
    :param headers: Encabezados de la respuesta
    :type headers: dict or None
    :return: Cliente ``httpx`` con transporte simulado
    :rtype: httpx.Client
    """
    body = {
        "choices": [{"message": {"content": '{"answer": "Hola desde la caché"}'}}],
        "usage": {
            "prompt_tokens": GATEWAY_PROMPT_TOKENS,
            "completion_tokens": GATEWAY_COMPLETION_TOKENS,
        },
    }

    def handler(request):  # pylint: disable=unused-argument
        return httpx.Response(status, json=body, headers=headers or {})

    return httpx.Client(transport=httpx.MockTransport(handler))


@given("the priced HR assistant is running", target_fixture="client")
def priced_assistant(make_cost_client):
    """Aplicación con los dos modelos simulados y los precios por omisión."""
    return make_cost_client()


@given(
    parsers.parse('the priced HR assistant is running with "{name}" set to "{value}"'),
    target_fixture="client",
)
def priced_assistant_with(make_cost_client, name, value):
    """Aplicación con una variable de entorno cambiada."""
    return make_cost_client({name: value})


@given(
    parsers.parse(
        "the priced HR assistant is running with a spy model "
        "and a history window of {window:d}"
    ),
    target_fixture="client",
)
def priced_assistant_with_spy(make_cost_client, spy_model, window, context):
    """Aplicación cuyos dos modelos son el mismo espía."""
    context["spy"] = spy_model
    return make_cost_client(
        {"HISTORY_WINDOW": str(window)},
        models={SMALL: spy_model, LARGE: spy_model},
    )


@given("the HR assistant uses a gateway that fails", target_fixture="client")
def assistant_with_failing_gateway(make_cost_client, gateway_environ):
    """Aplicación con modelo real cuyo gateway responde 500."""
    return make_cost_client(gateway_environ, http_client=gateway_client(500))


@given(
    "the HR assistant uses a gateway that answers from its cache",
    target_fixture="client",
)
def assistant_with_cached_gateway(make_cost_client, gateway_environ):
    """Aplicación con caché encendida y un gateway que responde HIT."""
    environ = dict(gateway_environ, CACHE_TTL_SECONDS="300")
    http_client = gateway_client(200, {"cf-aig-cache-status": "HIT"})
    return make_cost_client(environ, http_client=http_client)


@when(
    parsers.parse('I ask "{question}" with the request id "{request_id}"'),
    target_fixture="response",
)
def ask(client, question, request_id):
    """Envía la pregunta con un id conocido."""
    return client.post(
        "/ask", json={"question": question}, headers={"X-Request-ID": request_id}
    )


@when(
    parsers.parse('I ask "{question}" after a history of {count:d} messages'),
    target_fixture="response",
)
def ask_with_history(client, question, count, context):
    """Envía la pregunta con un historial alternado de usuario y asistente."""
    history = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
        for index in range(count)
    ]
    context["history"] = history
    context["question"] = question
    return client.post("/ask", json={"question": question, "history": history})


@then(
    parsers.parse('the answer used the model "{model}" with the route "{route}"')
)
def answer_used_model(response, model, route):
    """La respuesta dice qué modelo eligió el enrutador y por qué."""
    body = response.json()
    assert body["model"] == model
    assert body["route"] == route


@then("the answer costs more than zero")
def answer_costs_more_than_zero(response):
    """Con pocas palabras el costo no se redondea a cero."""
    assert response.json()["cost_usd"] > 0


def is_supervisor_call(messages):
    """Dice si una llamada al modelo es la clasificación del supervisor.

    :param messages: Mensajes de una llamada
    :type messages: list[dict]
    :return: ``True`` si el primer mensaje es el prompt del supervisor
    :rtype: bool
    """
    # Import local: si falta el módulo fallan solo los pasos que lo usan.
    from app.prompts import SUPERVISOR_PROMPT  # pylint: disable=import-outside-toplevel

    return bool(messages) and messages[0] == {
        "role": "system",
        "content": SUPERVISOR_PROMPT,
    }


@then("the supervisor classified only the question, without the history")
def supervisor_classified_question(context):
    """Spec 05: «Hola» no tiene regla; la primera llamada es del supervisor."""
    # Import local: si falta el módulo fallan solo los pasos que lo usan.
    from app.prompts import SUPERVISOR_PROMPT  # pylint: disable=import-outside-toplevel

    assert context["spy"].calls[0] == [
        {"role": "system", "content": SUPERVISOR_PROMPT},
        {"role": "user", "content": context["question"]},
    ]


@then(
    parsers.parse(
        "the model received only the last {window:d} history messages and the question"
    )
)
def model_received_window(context, window):
    """La primera llamada del especialista lleva solo la ventana y la pregunta.

    Se ignora un posible prompt de sistema del especialista: lo que se prueba
    aquí es la ventana del historial de la sesión 3.
    """
    expected = context["history"][-window:] + [
        {"role": "user", "content": context["question"]}
    ]
    specialist_calls = [
        call for call in context["spy"].calls if not is_supervisor_call(call)
    ]
    first = [
        message for message in specialist_calls[0] if message["role"] != "system"
    ]
    assert first == expected


@then(
    parsers.parse("the agent_run line says {count:d} history messages were sent")
)
def agent_run_history_sent(read_log, count):
    """El log cuenta los mensajes de historial que sí se mandaron."""
    run = next(line for line in read_log() if line["event"] == "agent_run")
    assert run["history_sent"] == count


@then(parsers.parse('the body is "{detail}" with the request id "{request_id}"'))
def body_is_detail(response, detail, request_id):
    """El 502 tiene un cuerpo fijo con el id de la petición."""
    assert response.json() == {"detail": detail, "request_id": request_id}


@then(
    parsers.parse(
        'the log has a "{error_type}" error without the token or the account id'
    )
)
def log_has_gateway_error(read_log, log_stream, error_type):
    """El error queda registrado por tipo, sin secretos de Cloudflare."""
    errors = [line for line in read_log() if line["event"] == "error"]
    assert [line["error_type"] for line in errors] == [error_type]
    text = log_stream.getvalue()
    assert "tok-secret" not in text
    assert "acc-123" not in text


@then(parsers.parse("the answer has {count:d} cached calls and costs {cost:g}"))
def answer_is_cached(response, count, cost):
    """Cada llamada HIT se cuenta como cacheada y no cuesta.

    Spec 05: «Hola» no tiene regla, así que hay dos llamadas al gateway: la
    clasificación del supervisor y el especialista. La respuesta del gateway no
    es una clasificación válida, por eso el supervisor usa ``directory``.
    """
    body = response.json()
    assert body["cached_calls"] == count
    assert body["cost_usd"] == cost
    assert body["answer"] == "Hola desde la caché"
    assert body["supervisor_route"] == "model_invalid"
    assert body["specialist"] == "directory"


@then("the answer still reports the tokens of both gateway calls")
def answer_reports_gateway_tokens(response):
    """Los tokens suman supervisor y especialista aunque vengan de la caché."""
    body = response.json()
    assert body["input_tokens"] == 2 * GATEWAY_PROMPT_TOKENS
    assert body["output_tokens"] == 2 * GATEWAY_COMPLETION_TOKENS
