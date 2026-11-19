"""Supervisor: elige el especialista de cada pregunta.

Primero aplica reglas en código, sin llamar al modelo y en este orden: id de
empleado (``rule:employee``), departamento que existe (``rule:department``) y
palabra clave de una política (``rule:policy``). Si ninguna aplica, le pregunta
al modelo pequeño con ``SUPERVISOR_PROMPT`` y solo la pregunta (sin historial).
Si la respuesta no sirve o el modelo no responde, usa ``directory``.
"""

import json
from dataclasses import dataclass, field

from app.directory import EMPLOYEE_ID_PATTERN, normalize
from app.gateway import ModelUnavailable
from app.policies import phrase_pattern
from app.prompts import SUPERVISOR_PROMPT

DIRECTORY = "directory"
POLICY = "policy"
SPECIALISTS = (DIRECTORY, POLICY)
ROUTE_EMPLOYEE = "rule:employee"
ROUTE_DEPARTMENT = "rule:department"
ROUTE_POLICY = "rule:policy"
ROUTE_MODEL = "model"
ROUTE_MODEL_INVALID = "model_invalid"
RULE_ROUTES = (ROUTE_EMPLOYEE, ROUTE_DEPARTMENT, ROUTE_POLICY)


@dataclass(frozen=True)
class Decision:
    """Decisión del supervisor.

    :param specialist: ``directory`` o ``policy``
    :type specialist: str
    :param route: Motivo: ``rule:employee``, ``rule:department``,
        ``rule:policy``, ``model`` o ``model_invalid``
    :type route: str
    :param completions: Llamadas al modelo que hizo el supervisor (0 o 1),
        para sumar tokens y costo
    :type completions: tuple[app.completion.Completion, ...]
    """

    specialist: str
    route: str
    completions: tuple = field(default=())

    @property
    def by_rule(self):
        """Indica si se decidió con una regla, sin modelo.

        :return: ``True`` si el motivo es una regla
        :rtype: bool
        """
        return self.route in RULE_ROUTES


def _read_specialist(text):
    """Lee el especialista de la respuesta del modelo.

    :param text: Texto devuelto por el modelo
    :type text: str
    :return: ``directory``, ``policy`` o ``None`` si la respuesta no es válida
    :rtype: str or None
    """
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    specialist = value.get("specialist")
    return specialist if specialist in SPECIALISTS else None


class Supervisor:
    """Supervisor con reglas en código y el modelo pequeño de respaldo.

    :param model: Modelo pequeño con el método ``complete(messages)``
    :type model: app.llm.LanguageModel
    :param departments: Departamentos que existen en el directorio
    :type departments: Sequence[str]
    :param policies: Libro de políticas con sus palabras clave
    :type policies: app.policies.PolicyBook
    """

    def __init__(self, model, departments, policies):
        self._model = model
        self._departments = tuple(phrase_pattern(name) for name in departments)
        self._policies = policies

    def _rule(self, question):
        """Aplica las reglas en orden de precedencia.

        :param question: Pregunta (ya redactada por el guardián)
        :type question: str
        :return: Decisión por regla o ``None`` si ninguna aplica
        :rtype: Decision or None
        """
        if EMPLOYEE_ID_PATTERN.search(question):
            return Decision(DIRECTORY, ROUTE_EMPLOYEE)
        folded = normalize(question)
        if any(pattern.search(folded) for pattern in self._departments):
            return Decision(DIRECTORY, ROUTE_DEPARTMENT)
        if self._policies.find_topic(question) is not None:
            return Decision(POLICY, ROUTE_POLICY)
        return None

    def route(self, question):
        """Elige el especialista de una pregunta.

        :param question: Pregunta (ya redactada por el guardián)
        :type question: str
        :return: Especialista, motivo y llamadas al modelo
        :rtype: Decision
        """
        decision = self._rule(question)
        if decision is not None:
            return decision
        messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": question},
        ]
        try:
            completion = self._model.complete(messages)
        except ModelUnavailable:
            return Decision(DIRECTORY, ROUTE_MODEL_INVALID)
        specialist = _read_specialist(completion.text)
        if specialist is None:
            return Decision(DIRECTORY, ROUTE_MODEL_INVALID, (completion,))
        return Decision(specialist, ROUTE_MODEL, (completion,))
