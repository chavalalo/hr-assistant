"""Interfaz del modelo de lenguaje, modelo simulado y fábrica de modelos."""

import json
import re
import unicodedata
from typing import Protocol, Sequence

from app.completion import Completion
from app.gateway import GatewayModel

__all__ = [
    "Completion",
    "FakeModel",
    "GatewayModel",
    "LanguageModel",
    "build_models",
    "count_words",
]

TOOL_RESULT_PREFIX = "Resultado de la herramienta: "
ANSWER_PREFIX = "Según el directorio: "
HELP_ANSWER = "Pregúntame por un empleado (EMP-0001) o un departamento."
EMPLOYEE_ID_PATTERN = re.compile(r"\bEMP-\d{4}\b", re.IGNORECASE)
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


def _fold(text):
    """Quita acentos y pasa a minúsculas para comparar textos.

    :param text: Texto original
    :type text: str
    :return: Texto normalizado
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(
        char for char in decomposed if not unicodedata.combining(char)
    ).casefold()


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

    def __init__(self, departments, name=FAKE_MODEL_NAME):
        self._departments = tuple(departments)
        self.name = name

    def complete(self, messages):
        """Responde con un objeto JSON según las reglas del modelo simulado.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta con los tokens contados por palabras
        :rtype: Completion
        """
        last = str(messages[-1]["content"]) if messages else ""
        text = json.dumps(self._decide(last), ensure_ascii=False)
        input_tokens = sum(count_words(message["content"]) for message in messages)
        return Completion(
            text=text,
            input_tokens=input_tokens,
            output_tokens=count_words(text),
        )

    def _decide(self, last):
        """Aplica las cuatro reglas en orden sobre el último mensaje.

        :param last: Contenido del último mensaje
        :type last: str
        :return: Pedido de herramienta o respuesta
        :rtype: dict
        """
        if last.startswith(TOOL_RESULT_PREFIX):
            return {"answer": ANSWER_PREFIX + last[len(TOOL_RESULT_PREFIX):]}
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
        return {"answer": HELP_ANSWER}

    def _find_department(self, text):
        """Busca en el texto un departamento conocido.

        :param text: Texto donde buscar
        :type text: str
        :return: El departamento encontrado o ``None``
        :rtype: str or None
        """
        folded = _fold(text)
        for department in self._departments:
            pattern = r"\b" + re.escape(_fold(department)) + r"\b"
            if re.search(pattern, folded):
                return department
        return None


def build_models(settings, departments, http_client=None):
    """Construye el modelo barato y el capaz según la configuración.

    Con ``fake`` son dos modelos simulados con los nombres de ``MODEL_SMALL`` y
    ``MODEL_LARGE``; con ``gateway`` son dos modelos reales de AI Gateway.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :param departments: Departamentos que existen en los datos
    :type departments: Sequence[str]
    :param http_client: Cliente HTTP para el gateway; si falta se crea uno
    :type http_client: httpx.Client or None
    :return: Modelos por nombre
    :rtype: dict[str, LanguageModel]
    :raises ValueError: Si el proveedor no está soportado
    """
    names = (settings.model_small, settings.model_large)
    if settings.model_provider == "fake":
        return {name: FakeModel(departments, name) for name in names}
    if settings.model_provider == "gateway":
        return {name: GatewayModel(name, settings, http_client) for name in names}
    raise ValueError(f"Unsupported model provider: {settings.model_provider}")
