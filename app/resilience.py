"""Resiliencia ante fallas del modelo: reintentos con espera y respaldo.

``RetryingModel`` reintenta una llamada solo si el error es ``retryable``
(timeout, ``429`` o ``5xx``), esperando ``backoff * 2**i`` segundos antes del
reintento ``i``. La función de espera se inyecta para que las pruebas no
duerman. ``run_with_fallback`` repite el especialista **una vez** con el otro
modelo (``MODEL_SMALL`` <-> ``MODEL_LARGE``) cuando ``MODEL_FALLBACK=true``.
"""

from dataclasses import dataclass
from typing import Any

from app.gateway import ModelUnavailable

BACKOFF_BASE = 2


class RetryingModel:  # pylint: disable=too-few-public-methods
    """Envuelve un modelo y reintenta las fallas pasajeras.

    :param model: Modelo con ``complete(messages)`` y ``name``
    :type model: app.llm.LanguageModel
    :param retries: Reintentos después del primer intento (0: ninguno)
    :type retries: int
    :param backoff: Primera espera en segundos; se duplica en cada reintento
    :type backoff: float
    :param sleep: Función que espera los segundos dados
    :type sleep: callable
    """

    def __init__(self, model, retries, backoff, sleep):
        self._model = model
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep
        self.name = getattr(model, "name", None)

    def complete(self, messages):
        """Llama al modelo y reintenta si la falla es pasajera.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta del modelo
        :rtype: app.completion.Completion
        :raises app.gateway.ModelUnavailable: Si la falla no es pasajera o se
            acabaron los reintentos
        """
        attempt = 0
        while True:
            try:
                return self._model.complete(messages)
            except ModelUnavailable as error:
                if not error.retryable or attempt >= self._retries:
                    raise
                self._sleep(self._backoff * BACKOFF_BASE**attempt)
                attempt += 1


def other_model(model_name, settings):
    """Devuelve el modelo de respaldo: el otro de ``MODEL_SMALL``/``MODEL_LARGE``.

    :param model_name: Modelo que falló
    :type model_name: str
    :param settings: Configuración con ``model_small`` y ``model_large``
    :type settings: app.config.Settings
    :return: El otro modelo
    :rtype: str
    """
    if model_name == settings.model_large:
        return settings.model_small
    return settings.model_large


@dataclass(frozen=True)
class FallbackResult:
    """Resultado de correr algo con respaldo.

    :param value: Lo que devolvió la función
    :type value: object
    :param model: Modelo que contestó
    :type model: str
    :param fallback: ``True`` si contestó el modelo de respaldo
    :type fallback: bool
    """

    value: Any
    model: str
    fallback: bool = False


def run_with_fallback(run, model_name, settings):
    """Corre ``run`` con el modelo elegido y, si falla, una vez con el otro.

    :param run: Función que recibe el nombre del modelo y devuelve el resultado
    :type run: callable
    :param model_name: Modelo elegido por el enrutador de costo
    :type model_name: str
    :param settings: Configuración con ``model_fallback`` y los dos modelos
    :type settings: app.config.Settings
    :return: Resultado, modelo que contestó y si fue el de respaldo
    :rtype: FallbackResult
    :raises app.gateway.ModelUnavailable: Si el modelo falla y no hay respaldo,
        o si el respaldo también falla
    """
    try:
        return FallbackResult(value=run(model_name), model=model_name)
    except ModelUnavailable:
        backup = other_model(model_name, settings)
        if not settings.model_fallback or backup == model_name:
            raise
    return FallbackResult(value=run(backup), model=backup, fallback=True)
