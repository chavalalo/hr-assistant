"""Pruebas de ``app.supervisor``: reglas antes que el modelo y su respaldo."""

from pathlib import Path

from app.completion import Completion
from app.gateway import ModelUnavailable
from app.policies import PolicyBook
from app.supervisor import Supervisor

POLICIES_PATH = Path(__file__).resolve().parents[1] / "data" / "policies.json"
NO_RULE = "Necesito ayuda"


class ScriptedModel:  # pylint: disable=too-few-public-methods
    """Modelo que responde un texto fijo (o falla) y cuenta sus llamadas."""

    def __init__(self, text=None, error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def complete(self, messages):  # pylint: disable=unused-argument
        """Devuelve el texto fijo o lanza el error configurado."""
        self.calls += 1
        if self.error is not None:
            raise self.error
        return Completion(text=self.text, input_tokens=3, output_tokens=2)


def supervisor_with(model, directory):
    """Supervisor con los departamentos y las políticas reales."""
    return Supervisor(
        model=model,
        departments=directory.departments(),
        policies=PolicyBook.load(POLICIES_PATH),
    )


def test_rules_win_in_order_and_unusable_model_replies_go_to_directory(directory):
    model = ScriptedModel('{"specialist": "policy"}')
    supervisor = supervisor_with(model, directory)
    broken = [
        supervisor_with(ScriptedModel("no es JSON"), directory),
        supervisor_with(ScriptedModel('{"specialist": "payroll"}'), directory),
        supervisor_with(ScriptedModel(error=ModelUnavailable("down")), directory),
    ]

    by_rule = [
        supervisor.route("¿EMP-0005 de Finanzas tiene vacaciones?"),
        supervisor.route("¿Finanzas tiene vacaciones?"),
        supervisor.route("¿Cuántos DÍAS DE DESCANSO tengo?"),
    ]
    rule_calls = model.calls
    by_model = supervisor.route(NO_RULE)
    fallbacks = [candidate.route(NO_RULE) for candidate in broken]

    assert [(item.specialist, item.route) for item in by_rule] == [
        ("directory", "rule:employee"),
        ("directory", "rule:department"),
        ("policy", "rule:policy"),
    ]
    assert rule_calls == 0
    assert (by_model.specialist, by_model.route) == ("policy", "model")
    assert len(by_model.completions) == 1
    for decision in fallbacks:
        assert (decision.specialist, decision.route) == ("directory", "model_invalid")
