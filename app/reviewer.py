"""Revisor de salida: PII, respuesta anclada al directorio y recorte.

En este orden: oculta la PII de la respuesta; si menciona un id ``EMP-dddd``
que no existe en el directorio y que la persona no escribió en su pregunta (un
id inventado por el modelo), la reemplaza por un mensaje fijo; al final la
recorta a ``MAX_ANSWER_CHARS``. Los ids se comparan sin distinguir
mayúsculas. Nunca escribe el texto que revisa.
"""

from dataclasses import dataclass

from app.directory import EMPLOYEE_ID_PATTERN
from app.pii import redact

UNVERIFIED_ANSWER = (
    "No pude verificar la respuesta con el directorio. Intenta de nuevo."
)
BLOCK_REASON = "unknown_employee_id"


@dataclass(frozen=True)
class Review:
    """Respuesta revisada y lo que hizo el revisor.

    :param answer: Respuesta final
    :type answer: str
    :param types: Tipos de PII ocultados, sin repetir y ordenados
    :type types: tuple[str, ...]
    :param count: Cuántos valores de PII se ocultaron
    :type count: int
    :param blocked: ``True`` si se reemplazó por el mensaje de verificación
    :type blocked: bool
    """

    answer: str
    types: tuple = ()
    count: int = 0
    blocked: bool = False


def employee_ids(text):
    """Extrae los ids ``EMP-dddd`` de un texto, normalizados en mayúsculas.

    :param text: Texto donde buscar
    :type text: str
    :return: Ids encontrados, sin repetir
    :rtype: frozenset[str]
    """
    return frozenset(
        match.group(0).upper() for match in EMPLOYEE_ID_PATTERN.finditer(text)
    )


def mentions_unknown_employee(text, directory, asked_ids=frozenset()):
    """Indica si el texto cita un id inventado: inexistente y no preguntado.

    Un id que no está en el directorio pero que la persona escribió en su
    pregunta no cuenta: la respuesta puede decir que no existe.

    :param text: Respuesta del especialista
    :type text: str
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param asked_ids: Ids de la pregunta, en mayúsculas
    :type asked_ids: frozenset[str]
    :return: ``True`` si algún id no está en el directorio ni en la pregunta
    :rtype: bool
    """
    return any(
        employee_id not in asked_ids and not directory.has_employee(employee_id)
        for employee_id in employee_ids(text)
    )


def review(answer, directory, max_chars, question=""):
    """Revisa la respuesta del especialista antes de mandarla.

    :param answer: Respuesta del especialista
    :type answer: str
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param max_chars: Largo máximo de la respuesta
    :type max_chars: int
    :param question: Pregunta de la persona, ya redactada por el guardián;
        sus ids ``EMP-dddd`` no cuentan como inventados
    :type question: str
    :return: Respuesta revisada
    :rtype: Review
    """
    cleaned = redact(answer)
    blocked = mentions_unknown_employee(
        cleaned.text, directory, employee_ids(question)
    )
    text = UNVERIFIED_ANSWER if blocked else cleaned.text
    return Review(
        answer=text[:max_chars],
        types=cleaned.types,
        count=cleaned.count,
        blocked=blocked,
    )
