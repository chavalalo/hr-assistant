"""Datos personales (PII): detección y reemplazo por marcadores.

Los patrones se aplican en un orden fijo (``email``, ``curp``, ``rfc``,
``card``, ``nss``, ``phone``) para que uno no se coma parte de otro. Los dígitos
separados por un espacio, punto o guion cuentan como una sola cifra: así un
número de 16 dígitos nunca se toma como teléfono ni como NSS. Los ids
``EMP-dddd`` nunca son PII. Nada de este módulo escribe los valores encontrados.
"""

import re
from dataclasses import dataclass

# Separador permitido entre dígitos de un mismo número.
_SEP = r"[ .\-]"
# Inicio y fin de una cifra: no hay otro dígito pegado ni tras un separador.
_START = rf"(?<!\d)(?<!\d{_SEP})"
_END = rf"(?!{_SEP}?\d)"

EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
CURP_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d(?![A-Za-z0-9])",
    re.IGNORECASE,
)
RFC_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
CARD_PATTERN = re.compile(rf"{_START}\d(?:[ \-]?\d){{12,18}}{_END}")
NSS_PATTERN = re.compile(rf"{_START}\d(?:{_SEP}?\d){{10}}{_END}")
PHONE_PATTERN = re.compile(
    rf"(?<!\+){_START}(?:\+?52{_SEP}?)?\d(?:{_SEP}?\d){{9}}{_END}"
)
CARD_MIN_DIGITS = 13
CARD_MAX_DIGITS = 19


def _digits(text):
    """Deja solo los dígitos de un texto.

    :param text: Texto con dígitos y separadores
    :type text: str
    :return: Solo los dígitos
    :rtype: str
    """
    return "".join(char for char in text if char.isdigit())


def passes_luhn(digits):
    """Revisa el dígito verificador de Luhn de un número de tarjeta.

    :param digits: Solo los dígitos del número
    :type digits: str
    :return: ``True`` si el número pasa la prueba de Luhn
    :rtype: bool
    """
    total = 0
    for position, char in enumerate(reversed(digits)):
        value = int(char)
        if position % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _is_card(match):
    """Acepta una cifra como tarjeta si tiene de 13 a 19 dígitos y pasa Luhn.

    :param match: Coincidencia del patrón de tarjeta
    :type match: re.Match
    :return: ``True`` si es una tarjeta
    :rtype: bool
    """
    digits = _digits(match.group(0))
    return CARD_MIN_DIGITS <= len(digits) <= CARD_MAX_DIGITS and passes_luhn(digits)


def _always(_match):
    """Acepta toda coincidencia (el patrón basta).

    :param _match: Coincidencia del patrón
    :type _match: re.Match
    :return: Siempre ``True``
    :rtype: bool
    """
    return True


# Orden fijo: tipo, patrón, marcador y validación extra.
RULES = (
    ("email", EMAIL_PATTERN, "[EMAIL]", _always),
    ("curp", CURP_PATTERN, "[CURP]", _always),
    ("rfc", RFC_PATTERN, "[RFC]", _always),
    ("card", CARD_PATTERN, "[CARD]", _is_card),
    ("nss", NSS_PATTERN, "[NSS]", _always),
    ("phone", PHONE_PATTERN, "[PHONE]", _always),
)


@dataclass(frozen=True)
class Redaction:
    """Texto con la PII reemplazada y lo que se ocultó.

    :param text: Texto con marcadores en lugar de los datos personales
    :type text: str
    :param types: Tipos ocultados, sin repetir y en orden alfabético
    :type types: tuple[str, ...]
    :param count: Cuántos valores se ocultaron
    :type count: int
    """

    text: str
    types: tuple = ()
    count: int = 0


def redact(text):
    """Reemplaza los datos personales de un texto por sus marcadores.

    :param text: Texto original
    :type text: str
    :return: Texto limpio, tipos ocultados y conteo
    :rtype: Redaction
    """
    found = []
    result = str(text)
    for rule in RULES:
        result = _apply(rule, result, found)
    return Redaction(text=result, types=tuple(sorted(set(found))), count=len(found))


def _apply(rule, text, found):
    """Aplica una regla de PII y anota el tipo de cada valor reemplazado.

    :param rule: Tipo, patrón, marcador y validación extra
    :type rule: tuple
    :param text: Texto donde buscar
    :type text: str
    :param found: Lista donde se anota el tipo de cada reemplazo
    :type found: list[str]
    :return: Texto con los valores de ese tipo reemplazados
    :rtype: str
    """
    kind, pattern, marker, accept = rule

    def replace(match):
        """Devuelve el marcador si la coincidencia es válida.

        :param match: Coincidencia del patrón
        :type match: re.Match
        :return: Marcador o el texto original
        :rtype: str
        """
        if not accept(match):
            return match.group(0)
        found.append(kind)
        return marker

    return pattern.sub(replace, text)


def merge_types(*groups):
    """Une varios grupos de tipos sin repetir y en orden alfabético.

    :param groups: Grupos de tipos
    :type groups: Iterable[str]
    :return: Tipos unidos
    :rtype: tuple[str, ...]
    """
    return tuple(sorted({kind for group in groups for kind in group}))
