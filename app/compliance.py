"""Compliance como código: reglas de producción que se revisan al arrancar.

Con ``ENVIRONMENT=production`` el producto se niega a arrancar si alguna regla
falla. Los mensajes nombran la variable y la regla, nunca un valor.
"""

from app.errors import ConfigError

PRODUCTION = "production"
FAKE_PROVIDER = "fake"
MIN_API_KEY_CHARS = 16


def _model_violations(settings):
    """Revisa que producción no use el modelo simulado.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :return: Reglas que fallan
    :rtype: list[str]
    """
    if settings.model_provider == FAKE_PROVIDER:
        return ["MODEL_PROVIDER must not be 'fake' in production"]
    return []


def _api_key_violations(settings):
    """Revisa que haya clientes y que sus claves sean largas.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :return: Reglas que fallan; solo dicen la posición del cliente
    :rtype: list[str]
    """
    if not settings.api_clients:
        return ["API_KEYS must define at least one client in production"]
    return [
        f"API_KEYS entry {position} must have a key of at least "
        f"{MIN_API_KEY_CHARS} characters in production"
        for position, client in enumerate(settings.api_clients, start=1)
        if len(client.key) < MIN_API_KEY_CHARS
    ]


def _tracing_violations(settings):
    """Revisa que las trazas, si se piden, oculten entradas y salidas.

    Se usa lo pedido en ``LANGSMITH_TRACING`` aunque falte la clave de
    LangSmith, para fallar antes de que alguien la agregue.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :return: Reglas que fallan
    :rtype: list[str]
    """
    if not settings.langsmith_tracing_requested:
        return []
    found = []
    if not settings.hide_inputs:
        found.append("HIDE_INPUTS must be 'true' when tracing in production")
    if not settings.hide_outputs:
        found.append("HIDE_OUTPUTS must be 'true' when tracing in production")
    return found


def violations(settings):
    """Lista las reglas de producción que la configuración no cumple.

    En ``development`` no se exige nada.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :return: Una descripción por regla incumplida, sin valores
    :rtype: list[str]
    """
    if settings.environment != PRODUCTION:
        return []
    return (
        _model_violations(settings)
        + _api_key_violations(settings)
        + _tracing_violations(settings)
    )


def enforce(settings):
    """Impide arrancar si alguna regla de producción falla.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :raises app.config.ConfigError: Si hay reglas incumplidas
    """
    found = violations(settings)
    if found:
        raise ConfigError("compliance check failed: " + "; ".join(found))
