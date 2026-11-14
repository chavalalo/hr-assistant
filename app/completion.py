"""Respuesta de un modelo de lenguaje, común al simulado y al de gateway."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    """Respuesta de un modelo con su conteo de tokens.

    :param text: Texto devuelto por el modelo (un objeto JSON)
    :type text: str
    :param input_tokens: Tokens de entrada consumidos
    :type input_tokens: int
    :param output_tokens: Tokens de salida generados
    :type output_tokens: int
    :param cached: ``True`` si el gateway respondió desde su caché (no cuesta)
    :type cached: bool
    """

    text: str
    input_tokens: int
    output_tokens: int
    cached: bool = False
