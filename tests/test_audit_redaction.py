"""El log de auditoría ``tool_call`` nunca guarda datos personales del modelo.

Hallazgo 4 de la revisión de qa-style: los argumentos de una herramienta los
escribe el modelo y pueden traer un correo o un teléfono que vio antes.
"""

import json

from app.agent import TOOL_RESULT_PREFIX
from app.completion import Completion
from app.pii import redact
from app.pipeline import AUDIT_ARG_MAX_CHARS

LEAKED_EMAIL = "ana.lopez@example.com"
LEAKED_PHONE = "55 1234 5678"
# El correo y el teléfono van al principio: recortar no basta para ocultarlos.
LEAKED_DEPARTMENT = (
    f"Ventas, avisar a {LEAKED_EMAIL} o al {LEAKED_PHONE} " + "x" * 300
)
QUESTION = "¿Quién trabaja en Ventas?"


class LeakyToolModel:  # pylint: disable=too-few-public-methods
    """Modelo espía que pide una herramienta con PII en sus argumentos.

    En la primera vuelta pide ``search_by_department`` con un correo y un
    teléfono; cuando recibe el resultado de la herramienta, responde.
    """

    def __init__(self):
        self.calls = []

    def complete(self, messages):
        """Anota los mensajes y pide la herramienta o responde.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Pedido de herramienta o respuesta final en JSON
        :rtype: app.completion.Completion
        """
        self.calls.append([dict(message) for message in messages])
        last = messages[-1]["content"]
        if last.startswith(TOOL_RESULT_PREFIX):
            text = json.dumps({"answer": "No encontré empleados."})
        else:
            text = json.dumps(
                {
                    "tool": "search_by_department",
                    "args": {"department": LEAKED_DEPARTMENT},
                }
            )
        return Completion(text=text, input_tokens=10, output_tokens=5)


def test_tool_call_audit_redacts_and_trims_model_arguments(
    make_observed_client, read_log, log_stream
):
    """El ``args`` de ``tool_call`` lleva marcadores y no el correo ni el teléfono."""
    model = LeakyToolModel()
    client = make_observed_client(model=model)

    response = client.post("/ask", json={"question": QUESTION})

    assert response.status_code == 200
    assert model.calls, "el modelo espía debe haber sido llamado"
    tool_calls = [
        record for record in read_log() if record.get("action") == "tool_call"
    ]
    assert len(tool_calls) == 1
    logged = tool_calls[0]["args"]["department"]
    assert logged == redact(LEAKED_DEPARTMENT).text[:AUDIT_ARG_MAX_CHARS]
    assert "[EMAIL]" in logged
    assert "[PHONE]" in logged
    raw_log = log_stream.getvalue()
    assert LEAKED_EMAIL not in raw_log
    assert LEAKED_PHONE not in raw_log
