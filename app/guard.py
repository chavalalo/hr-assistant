"""Guardián de entrada: prompt injection y datos personales.

Corre antes que cualquier modelo. Si la pregunta o un mensaje ``user`` del
historial intenta cambiar las instrucciones, el rol o sacar el prompt del
sistema, lanza ``InputBlocked``. Si no, reemplaza la PII de la pregunta y de
todo el historial. Nunca escribe el texto que revisa.
"""

import re
from dataclasses import dataclass

from app.directory import normalize
from app.pii import merge_types, redact

USER_ROLE = "user"
BLOCK_REASON = "prompt_injection"

# Frases comparadas sin acentos ni mayúsculas, con cualquier espacio entre
# palabras. La lista es corta a propósito para evitar falsos positivos.
INJECTION_PHRASES = (
    r"\b(?:ignora|olvida)\s+(?:\w+\s+){0,2}instrucciones\b",
    r"\b(?:ignore|forget)\s+(?:(?:all|the|your|any)\s+)?(?:previous|prior)\s+"
    r"instructions\b",
    r"\brevela\s+(?:\w+\s+){0,2}prompt\b",
    r"\bprompt\s+del\s+sistema\b",
    r"\bsystem\s+prompt\b",
    r"\bactua\s+como\b",
    r"\bact\s+as\b",
    r"\bmodo\s+desarrollador\b",
    r"\bdeveloper\s+mode\b",
    r"\bjailbreak",
)
INJECTION_PATTERNS = tuple(re.compile(phrase) for phrase in INJECTION_PHRASES)


class InputBlocked(Exception):
    """La entrada pide ignorar instrucciones, cambiar de rol o ver el prompt.

    El mensaje es fijo: nunca lleva el texto de la persona.

    :param reason: Motivo del bloqueo para el ``audit``
    :type reason: str
    """

    def __init__(self, reason=BLOCK_REASON):
        super().__init__("request blocked by input policy")
        self.reason = reason


@dataclass(frozen=True)
class GuardResult:
    """Entrada limpia que sigue hacia el supervisor.

    :param question: Pregunta con la PII reemplazada
    :type question: str
    :param history: Historial con la PII reemplazada
    :type history: list[dict]
    :param types: Tipos de PII ocultados, sin repetir y ordenados
    :type types: tuple[str, ...]
    :param count: Cuántos valores se ocultaron
    :type count: int
    """

    question: str
    history: list
    types: tuple = ()
    count: int = 0


def is_injection(text):
    """Indica si un texto contiene una frase de prompt injection.

    :param text: Texto de la persona
    :type text: str
    :return: ``True`` si alguna frase aparece
    :rtype: bool
    """
    folded = normalize(str(text))
    return any(pattern.search(folded) for pattern in INJECTION_PATTERNS)


def inspect(question, history):
    """Revisa la entrada: bloquea prompt injection y redacta la PII.

    Solo la pregunta y los mensajes ``user`` pueden bloquear; los mensajes
    ``assistant`` los escribió el producto. Todos se redactan.

    :param question: Pregunta original
    :type question: str
    :param history: Historial original con ``role`` y ``content``
    :type history: list[dict]
    :return: Entrada limpia con los tipos y el conteo de PII
    :rtype: GuardResult
    :raises InputBlocked: Si hay prompt injection
    """
    user_texts = [question] + [
        message["content"] for message in history if message["role"] == USER_ROLE
    ]
    if any(is_injection(text) for text in user_texts):
        raise InputBlocked()
    cleaned_question = redact(question)
    cleaned_history = []
    redactions = [cleaned_question]
    for message in history:
        cleaned = redact(message["content"])
        redactions.append(cleaned)
        cleaned_history.append({**message, "content": cleaned.text})
    return GuardResult(
        question=cleaned_question.text,
        history=cleaned_history,
        types=merge_types(*(item.types for item in redactions)),
        count=sum(item.count for item in redactions),
    )
