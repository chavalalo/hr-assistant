"""Pasos de ``features/ask.feature``: preguntas al asistente por la API."""

from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/ask.feature")


@given(
    parsers.parse("the HR assistant is running with a cap of {steps:d} steps"),
    target_fixture="client",
)
def running_assistant_with_cap(make_client, steps):
    """Aplicación con el bucle del agente limitado a ``steps`` vueltas."""
    return make_client({"AGENT_MAX_STEPS": str(steps)})


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask_question(client, question):
    """Envía la pregunta sin historial."""
    return client.post("/ask", json={"question": question})


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(response, text):
    """La respuesta contiene el texto, con sus acentos tal cual."""
    assert text in response.json()["answer"]


@then(parsers.parse('the answer is "{text}"'))
def answer_is(response, text):
    """La respuesta es exactamente el texto."""
    assert response.json()["answer"] == text


@then(parsers.parse('the tools used are "{tools}"'))
def tools_used_are(response, tools):
    """Las herramientas usadas, en orden y separadas por comas."""
    expected = [tool.strip() for tool in tools.split(",")]
    assert response.json()["tools_used"] == expected


@then("no tools were used")
def no_tools_used(response):
    """El agente respondió sin llamar herramientas."""
    assert response.json()["tools_used"] == []


@then(parsers.parse("the agent took {steps:d} steps"))
def agent_took_steps(response, steps):
    """Cantidad de llamadas al modelo en la petición."""
    body = response.json()
    assert body["steps"] == steps
    assert body["input_tokens"] > 0
    assert body["output_tokens"] > 0
