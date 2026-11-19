"""Pasos de ``features/policy_grounding.feature``: políticas ancladas al texto.

Reproducen el caso de producción de la adenda 2: el modelo real no pidió
``search_policy`` y respondió «5 días» cuando la política dice 12.
"""

import json
import re

from pytest_bdd import given, parsers, scenarios, then, when

from app.completion import Completion

scenarios("features/policy_grounding.feature")

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
VACATION_TEXT = "12 días hábiles a partir del primer año"


class NeverAsksForToolsModel:  # pylint: disable=too-few-public-methods
    """Modelo espía que siempre responde lo mismo y nunca pide herramientas.

    :param answer: Texto que va en ``{"answer": ...}``
    :type answer: str
    """

    def __init__(self, answer):
        self._text = json.dumps({"answer": answer}, ensure_ascii=False)
        self.calls = []

    def complete(self, messages):
        """Anota los mensajes y responde siempre con la misma respuesta.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta fija con tokens de ejemplo
        :rtype: app.completion.Completion
        """
        self.calls.append([dict(message) for message in messages])
        return Completion(text=self._text, input_tokens=10, output_tokens=5)


@given(
    parsers.parse(
        'the HR assistant runs with a model that never asks for tools '
        'and answers "{answer}"'
    ),
    target_fixture="client",
)
def assistant_with_lazy_model(make_observed_client, context, answer):
    """Aplicación cuyo único modelo responde sin consultar la política."""
    model = NeverAsksForToolsModel(answer)
    context["model"] = model
    return make_observed_client(model=model)


@when(parsers.parse('I ask "{question}"'), target_fixture="response")
def ask(client, question):
    """Envía la pregunta sin historial."""
    return client.post("/ask", json={"question": question})


@then(
    parsers.parse('the "{specialist}" specialist answered by the route "{route}"')
)
def specialist_answered(response, specialist, route):
    """El supervisor eligió al especialista por la regla de palabra clave."""
    body = response.json()
    assert (body["specialist"], body["supervisor_route"]) == (specialist, route)


@then(parsers.parse('the answer does not contain the number "{number}"'))
def answer_does_not_contain_number(response, number):
    """La cifra inventada no llega a la persona.

    Se comparan cifras completas: «5» no cuenta dentro de «15» ni de «25»,
    que sí están en la política de vacaciones.
    """
    assert number not in re.findall(r"\d+", response.json()["answer"])


@then(parsers.parse('the answer mentions "{text}"'))
def answer_mentions(response, text):
    """La respuesta contiene el texto, con sus acentos tal cual."""
    assert text in response.json()["answer"]


@then(parsers.parse('the tools used include "{tool}"'))
def tools_used_include(response, tool):
    """La política se consultó en código aunque el modelo no la pidió."""
    assert tool in response.json()["tools_used"]


@then(parsers.re(r"the metrics count (?P<count>\d+) blocked answers?"))
def metrics_count_blocked_answers(client, count):
    """El contador de respuestas bloqueadas refleja al revisor."""
    security = client.get("/metrics").json()["security"]
    assert security["output_blocked"] == int(count)


@then(
    "the first message after the system prompt is the vacation policy "
    "as a tool result"
)
def first_message_is_the_policy(context):
    """El modelo ya recibe la política en su primera llamada."""
    first_call = context["model"].calls[0]
    after_system = [m for m in first_call if m["role"] != "system"]
    content = after_system[0]["content"]
    assert content.startswith(TOOL_RESULT_PREFIX)
    assert VACATION_TEXT in content
