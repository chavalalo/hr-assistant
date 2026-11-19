"""Interfaz del modelo de lenguaje, modelo simulado y fábrica de modelos."""

import json
import re
import time
from typing import Protocol, Sequence

from app.agent import TOOL_RESULT_PREFIX
from app.completion import Completion
from app.directory import EMPLOYEE_ID_PATTERN, normalize
from app.gateway import GatewayModel, ModelUnavailable
from app.policies import phrase_pattern
from app.prompts import POLICY_PROMPT, SUPERVISOR_PROMPT
from app.resilience import RetryingModel

__all__ = [
    "Completion",
    "FakeModel",
    "GatewayModel",
    "LanguageModel",
    "UnavailableModel",
    "build_models",
    "count_words",
]

ANSWER_PREFIX = "Según el directorio: "
POLICY_ANSWER_PREFIX = "Según la política: "
HELP_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."
FAKE_MODEL_NAME = "fake"


class LanguageModel(Protocol):  # pylint: disable=too-few-public-methods
    """Interfaz común de los modelos: el agente solo conoce ``complete``."""

    def complete(self, messages: Sequence[dict]) -> Completion:
        """Genera la siguiente respuesta de la conversación.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta del modelo
        :rtype: Completion
        """


def _system_prompt(messages):
    """Devuelve el prompt de sistema del primer mensaje, si lo hay.

    :param messages: Mensajes con ``role`` y ``content``
    :type messages: Sequence[dict]
    :return: Contenido del mensaje ``system`` inicial o ``None``
    :rtype: str or None
    """
    if messages and messages[0].get("role") == "system":
        return messages[0].get("content")
    return None


def _tool_result(messages):
    """Devuelve el último resultado de herramienta de la conversación.

    :param messages: Mensajes con ``role`` y ``content``
    :type messages: Sequence[dict]
    :return: Contenido del último mensaje que empieza con
        ``TOOL_RESULT_PREFIX`` o ``None`` si no hay ninguno
    :rtype: str or None
    """
    for message in reversed(messages):
        content = str(message.get("content", ""))
        if content.startswith(TOOL_RESULT_PREFIX):
            return content
    return None


def count_words(text):
    """Cuenta palabras separadas por espacios, como aproximación de tokens.

    :param text: Texto a contar
    :type text: str
    :return: Número de palabras
    :rtype: int
    """
    return len(str(text).split())


class FakeModel:
    """Modelo simulado: decide con reglas fijas sobre el último mensaje.

    El nombre solo sirve para cobrarlo con el precio de ese modelo; dos
    modelos simulados con nombres distintos responden igual.

    :param departments: Departamentos que existen en los datos
    :type departments: Sequence[str]
    :param name: Nombre del modelo, como en la tabla de precios
    :type name: str
    """

    def __init__(self, departments, name=FAKE_MODEL_NAME, policy_keywords=None):
        self._departments = tuple(departments)
        self.name = name
        self._policy_patterns = tuple(
            (phrase_pattern(keyword), topic)
            for keyword, topic in dict(policy_keywords or {}).items()
        )

    def complete(self, messages):
        """Responde con un objeto JSON según las reglas del modelo simulado.

        El papel sale del prompt de sistema del primer mensaje: con
        ``SUPERVISOR_PROMPT`` clasifica la pregunta; con ``POLICY_PROMPT``
        responde como especialista de políticas; si no, como el de directorio.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta con los tokens contados por palabras
        :rtype: Completion
        """
        last = str(messages[-1]["content"]) if messages else ""
        system = _system_prompt(messages)
        if system == SUPERVISOR_PROMPT:
            decision = self._classify(last)
        elif system == POLICY_PROMPT and _tool_result(messages):
            # La política ya llegó en código: responde con ella sin pedirla.
            decision = self._decide(_tool_result(messages), POLICY_ANSWER_PREFIX)
        else:
            prefix = POLICY_ANSWER_PREFIX if system == POLICY_PROMPT else ANSWER_PREFIX
            decision = self._decide(last, prefix)
        text = json.dumps(decision, ensure_ascii=False)
        input_tokens = sum(count_words(message["content"]) for message in messages)
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=count_words(text),
        )

    def _classify(self, last):
        """Papel de supervisor: ``policy`` si hay palabra clave de política.

        :param last: Pregunta a clasificar
        :type last: str
        :return: Especialista elegido
        :rtype: dict
        """
        topic = self._find_policy_topic(last)
        return {"specialist": "policy" if topic else "directory"}

    def _decide(self, last, prefix=ANSWER_PREFIX):
        """Aplica las reglas en orden sobre el último mensaje.

        Resultado de herramienta, id de empleado, departamento, palabra clave de
        una política y, si nada aplica, el texto de ayuda.

        :param last: Contenido del último mensaje
        :type last: str
        :param prefix: Inicio de la respuesta con el resultado de la herramienta
        :type prefix: str
        :return: Pedido de herramienta o respuesta
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            return {"answer": prefix + last[len(TOOL_RESULT_PREFIX):]}
        match = EMPLOYEE_ID_PATTERN.search(last)
        if match:
            employee_id = match.group(0).upper()
            return {"tool": "get_employee", "args": {"employee_id": employee_id}}
        department = self._find_department(last)
        if department:
            return {
                "tool": "search_by_department",
                "args": {"department": department},
            }
        topic = self._find_policy_topic(last)
        if topic:
            return {"tool": "search_policy", "args": {"topic": topic}}
        return {"answer": HELP_ANSWER}

    def _find_policy_topic(self, text):
        """Busca en el texto una palabra clave de política.

        :param text: Texto donde buscar
        :type text: str
        :return: Tema de la política o ``None``
        :rtype: str or None
        """
        folded = normalize(text)
        for pattern, topic in self._policy_patterns:
            if pattern.search(folded):
                return topic
        return None

    def _find_department(self, text):
        """Busca en el texto un departamento conocido.

        :param text: Texto donde buscar
        :type text: str
        :return: El departamento encontrado o ``None``
        :rtype: str or None
        """
        folded = normalize(text)
        for department in self._departments:
            pattern = r"\b" + re.escape(normalize(department)) + r"\b"
            if re.search(pattern, folded):
                return department
        return None


class UnavailableModel:  # pylint: disable=too-few-public-methods
    """Modelo simulado caído: falla como el gateway, sin reintentos.

    Lo usa ``FAKE_UNAVAILABLE_MODELS`` para probar el respaldo sin red. El
    error no es ``retryable`` para que las verificaciones no esperen.

    :param name: Nombre del modelo, como en la tabla de precios
    :type name: str
    """

    def __init__(self, name):
        self.name = name

    def complete(self, messages):  # pylint: disable=unused-argument
        """Falla siempre como un gateway que no responde.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :raises app.gateway.ModelUnavailable: Siempre
        """
        raise ModelUnavailable("the model gateway request failed")


def build_models(
    settings, departments, http_client=None, policy_keywords=None, *, sleep=None
):
    """Construye el modelo barato y el capaz según la configuración.

    Con ``fake`` son dos modelos simulados con los nombres de ``MODEL_SMALL`` y
    ``MODEL_LARGE``; los de ``FAKE_UNAVAILABLE_MODELS`` fallan siempre. Con
    ``gateway`` son dos modelos reales de AI Gateway envueltos con reintentos
    (``MODEL_RETRIES`` y ``MODEL_RETRY_BACKOFF_SECONDS``).

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :param departments: Departamentos que existen en los datos
    :type departments: Sequence[str]
    :param http_client: Cliente HTTP para el gateway; si falta se crea uno
    :type http_client: httpx.Client or None
    :param policy_keywords: Tema por palabra clave de política, para el modelo
        simulado
    :type policy_keywords: Mapping[str, str] or None
    :param sleep: Espera entre reintentos del gateway; si falta, ``time.sleep``
    :type sleep: callable or None
    :return: Modelos por nombre
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider == "fake":
        unavailable = set(settings.fake_unavailable_models)
        return {
            name: (
                UnavailableModel(name)
                if name in unavailable
                else FakeModel(departments, name, policy_keywords)
            )
            for name in names
        }
    if settings.model_provider == "gateway":
        wait = sleep if sleep is not None else time.sleep
        return {
            name: RetryingModel(
                GatewayModel(name, settings, http_client),
                settings.model_retries,
                settings.model_retry_backoff_seconds,
                wait,
            )
            for name in names
        }
    raise ValueError(f"Unsupported model provider: {settings.model_provider}")
