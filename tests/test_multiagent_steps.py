"""Pasos de ``features/multiagent.feature``: supervisor, especialistas y caché."""

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("features/multiagent.feature")


@pytest.fixture
def answers():
    """Respuestas de la escena, en orden, para comparar la primera y la segunda."""
    return []


@given("the multi-agent HR assistant is running", target_fixture="client")
def multi_agent_assistant(make_cost_client):
    """Aplicación con los dos modelos simulados, reloj fijo y log en memoria."""
    return make_cost_client()


@given(
    parsers.parse(
        'the multi-agent HR assistant is running with "{name}" set to "{value}"'
    ),
    target_fixture="client",
)
def multi_agent_assistant_with(make_cost_client, name, value):
    """Aplicación con una variable de entorno cambiada."""
    return make_cost_client({name: value})


def post_question(client, question, answers):
    """Envía la pregunta sin historial y guarda la respuesta.

    :param client: Cliente HTTP de prueba
    :type client: fastapi.testclient.TestClient
    :param question: Pregunta
    :type question: str
    :param answers: Respuestas anteriores de la escena
    :type answers: list
    :return: Respuesta HTTP
    :rtype: httpx.Response
    """
    response = client.post("/ask", json={"question": question})
    answers.append(response)
    return response


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask(client, question, answers):
    """Envía la pregunta sin historial."""
    return post_question(client, question, answers)


@when(parsers.parse('I ask again "{question}"'), target_fixture="response")
def ask_again(client, question, answers):
    """Envía otra pregunta sin historial."""
    return post_question(client, question, answers)


@then(
    parsers.parse(
        'the "{specialist}" specialist answered by the route "{route}"'
    )
)
def specialist_answered(response, specialist, route):
    """El supervisor eligió al especialista por el motivo esperado."""
    body = response.json()
    assert body["specialist"] == specialist
    assert body["supervisor_route"] == route
    assert body["cached"] is False
    assert body["fallback"] is False


@then(parsers.parse('the agents that ran are "{agents}"'))
def agents_that_ran(response, agents):
    """Los agentes que corrieron, en orden."""
    expected = [agent.strip() for agent in agents.split(",")]
    assert response.json()["agents"] == expected


@then(parsers.parse('the tools used are "{tools}"'))
def tools_used_are(response, tools):
    """Las herramientas del especialista, en orden."""
    expected = [tool.strip() for tool in tools.split(",")]
    assert response.json()["tools_used"] == expected


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(response, text):
    """La respuesta contiene el texto, con sus acentos tal cual."""
    assert text in response.json()["answer"]


@then("the second answer is the first one, from the cache and with cost 0")
def second_answer_is_cached(answers):
    """El acierto repite la respuesta sin llamar a ningún modelo."""
    first, second = (response.json() for response in answers)
    assert first["cached"] is False
    assert second["cached"] is True
    for field in ("answer", "specialist", "supervisor_route", "model", "route"):
        assert second[field] == first[field], field
    assert second["agents"] == ["guard", "cache"]
    assert (second["cost_usd"], second["steps"]) == (0, 0)
    assert (second["input_tokens"], second["output_tokens"]) == (0, 0)
    assert second["tools_used"] == []


@then(
    parsers.parse("the metrics count {hits:d} cache hit and {misses:d} cache miss")
)
def metrics_count_cache(client, hits, misses):
    """La tasa de aciertos es aciertos entre consultas."""
    cache = client.get("/metrics").json()["cache"]
    assert cache == {"hits": hits, "misses": misses, "hit_rate": 0.5}


@then("both answers wrote an agent_run line")
def both_answers_logged(read_log):
    """El acierto también escribe ``agent_run`` para el reporte de costos."""
    runs = [line for line in read_log() if line["event"] == "agent_run"]
    assert [run["cached"] for run in runs] == [False, True]
    assert runs[1]["agents"] == ["guard", "cache"]


@then(parsers.parse('the fallback model "{model}" answered'))
def fallback_model_answered(response, model):
    """Respondió el otro modelo y la respuesta lo dice."""
    body = response.json()
    assert body["fallback"] is True
    assert body["model"] == model
    assert "Sofía Gómez" in body["answer"]


@then(parsers.parse("the metrics count {count:d} fallback"))
def metrics_count_fallbacks(client, count):
    """El contador de respaldos sube por cada respuesta del otro modelo."""
    assert client.get("/metrics").json()["fallbacks"] == count


@then(parsers.parse('the body is "{detail}" with its request id'))
def body_is_detail(response, detail):
    """El 502 conserva su cuerpo fijo con el id de la petición."""
    assert response.json() == {
        "detail": detail,
        "request_id": response.headers["X-Request-ID"],
    }
