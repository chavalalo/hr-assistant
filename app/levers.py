"""Palancas de costo en código: enrutador por regla y ventana de historial.

Son funciones puras: no llaman a la red ni a otro modelo.
"""

import re
from dataclasses import dataclass

from app.directory import normalize

ROUTE_ROUTING_OFF = "routing_off"
ROUTE_LONG_QUESTION = "long_question"
ROUTE_KEYWORD = "keyword:"
ROUTE_SIMPLE = "simple"
# Palabras ya normalizadas (sin acentos, en minúsculas) que piden el modelo capaz.
KEYWORDS = ("compara", "resume", "explica", "por que", "analiza", "todos")
KEYWORD_PATTERNS = tuple(
    (keyword, re.compile(r"\b" + r"\s+".join(map(re.escape, keyword.split()))))
    for keyword in KEYWORDS
)


@dataclass(frozen=True)
class Route:
    """Modelo elegido para una pregunta y el motivo.

    :param model: Nombre del modelo elegido
    :type model: str
    :param reason: Motivo: ``routing_off``, ``long_question``,
        ``keyword:<palabra>`` o ``simple``
    :type reason: str
    """

    model: str
    reason: str


def choose_model(question, settings):
    """Elige el modelo de una pregunta con una regla fija (palanca 1).

    Va al modelo capaz si el enrutamiento está apagado, si la pregunta pasa de
    ``ROUTER_MAX_CHARS`` o si tiene una palabra clave al inicio de una palabra;
    si no, al barato. Solo mira la pregunta, nunca el historial.

    :param question: Pregunta de la persona
    :type question: str
    :param settings: Configuración con modelos y palancas
    :type settings: app.config.Settings
    :return: Modelo elegido y motivo
    :rtype: Route
    """
    if not settings.routing:
        return Route(settings.model_large, ROUTE_ROUTING_OFF)
    if len(question) > settings.router_max_chars:
        return Route(settings.model_large, ROUTE_LONG_QUESTION)
    folded = normalize(question)
    for keyword, pattern in KEYWORD_PATTERNS:
        if pattern.search(folded):
            return Route(settings.model_large, ROUTE_KEYWORD + keyword)
    return Route(settings.model_small, ROUTE_SIMPLE)


def trim_history(history, window):
    """Deja solo los últimos ``window`` mensajes del historial (palanca 2).

    Con ``window`` igual a 0 no se manda historial (``history[-0:]`` lo
    devolvería completo).

    :param history: Mensajes previos de la conversación
    :type history: Sequence[dict]
    :param window: Cuántos mensajes conservar
    :type window: int
    :return: Los últimos mensajes, como lista nueva
    :rtype: list[dict]
    """
    if window <= 0:
        return []
    return list(history[-window:])
