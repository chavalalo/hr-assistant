"""Configuración del HR Assistant leída de variables de entorno.

La configuración es inmutable y se valida completa al construirse: un valor
inválido impide arrancar con un mensaje claro.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from app.auth import parse_api_keys
from app.costs import PriceTable
from app.errors import ConfigError

__all__ = ["ConfigError", "Settings"]

PRODUCT_DIR = Path(__file__).resolve().parents[1]
SUPPORTED_PROVIDERS = ("fake", "gateway")
GATEWAY_PROVIDER = "gateway"
CLOUDFLARE_VARIABLES = ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN")

DEFAULT_MODEL_PROVIDER = "fake"
DEFAULT_AGENT_MAX_STEPS = "3"
DEFAULT_MAX_QUESTION_CHARS = "2000"
DEFAULT_EMPLOYEES_PATH = "data/employees.json"
DEFAULT_SERVICE_NAME = "hr-assistant"
DEFAULT_SLO_P95_MS = "2000"
DEFAULT_LANGSMITH_TRACING = "false"
DEFAULT_HIDE_TEXT = "true"
DEFAULT_CF_GATEWAY_ID = "default"
DEFAULT_MODEL_SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
DEFAULT_MODEL_LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_ROUTING = "true"
DEFAULT_ROUTER_MAX_CHARS = "80"
DEFAULT_HISTORY_WINDOW = "6"
DEFAULT_MODEL_MAX_TOKENS = "300"
DEFAULT_MODEL_TEMPERATURE = "0"
DEFAULT_CACHE_TTL_SECONDS = "0"
DEFAULT_PRICES_PATH = "data/model_prices.json"
BOOLEAN_VALUES = {"true": True, "false": False}
SUPPORTED_ENVIRONMENTS = ("development", "production")
DEFAULT_ENVIRONMENT = "development"
DEFAULT_RATE_LIMIT_PER_MINUTE = "30"


def _positive_int(environ, name, default):
    """Lee una variable de entorno como entero mayor que cero.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión en texto
    :type default: str
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor que cero
    """
    raw = environ.get(name, default)
    try:
        value = int(str(raw).strip())
    except ValueError as error:
        raise ConfigError(
            f"{name} must be a positive integer, got {raw!r}"
        ) from error
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0, got {value}")
    return value


def _non_negative_int(environ, name, default):
    """Lee una variable de entorno como entero mayor o igual que cero.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión en texto
    :type default: str
    :return: El entero leído
    :rtype: int
    :raises ConfigError: Si el valor no es un entero mayor o igual que cero
    """
    raw = environ.get(name, default)
    try:
        value = int(str(raw).strip())
    except ValueError as error:
        raise ConfigError(
            f"{name} must be a non-negative integer, got {raw!r}"
        ) from error
    if value < 0:
        raise ConfigError(f"{name} must be 0 or greater, got {value}")
    return value


def _non_negative_float(environ, name, default):
    """Lee una variable de entorno como decimal mayor o igual que cero.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión en texto
    :type default: str
    :return: El decimal leído
    :rtype: float
    :raises ConfigError: Si el valor no es un número mayor o igual que cero
    """
    raw = environ.get(name, default)
    try:
        value = float(str(raw).strip())
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from error
    if math.isnan(value) or value < 0:
        raise ConfigError(f"{name} must be 0 or greater, got {value}")
    return value


def _non_empty(environ, name, default):
    """Lee una variable de entorno de texto que no puede quedar vacía.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión
    :type default: str
    :return: El texto sin espacios a los lados
    :rtype: str
    :raises ConfigError: Si el texto está vacío
    """
    value = str(environ.get(name, default)).strip()
    if not value:
        raise ConfigError(f"{name} must not be empty")
    return value


def _boolean(environ, name, default):
    """Lee una variable de entorno como ``true`` o ``false``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Valor por omisión en texto
    :type default: str
    :return: El booleano leído
    :rtype: bool
    :raises ConfigError: Si el valor no es ``true`` ni ``false``
    """
    raw = environ.get(name, default)
    value = BOOLEAN_VALUES.get(str(raw).strip().lower())
    if value is None:
        raise ConfigError(f"{name} must be 'true' or 'false', got {raw!r}")
    return value


def _service_name(environ):
    """Lee el nombre del servicio para el log.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: Nombre del servicio sin espacios a los lados
    :rtype: str
    :raises ConfigError: Si el nombre está vacío
    """
    name = str(environ.get("SERVICE_NAME", DEFAULT_SERVICE_NAME)).strip()
    if not name:
        raise ConfigError("SERVICE_NAME must not be empty")
    return name


def _tracing_enabled(environ):
    """Decide si se trazan corridas en LangSmith.

    Solo se trazan si ``LANGSMITH_TRACING`` vale ``true`` y existe la clave.
    La clave solo se consulta para saber si existe; nunca se guarda.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: ``True`` si las trazas están encendidas
    :rtype: bool
    :raises ConfigError: Si ``LANGSMITH_TRACING`` no es ``true`` ni ``false``
    """
    requested = _boolean(environ, "LANGSMITH_TRACING", DEFAULT_LANGSMITH_TRACING)
    has_key = bool(str(environ.get("LANGSMITH_API_KEY", "")).strip())
    return requested and has_key


def _environment(environ):
    """Lee el entorno de despliegue.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: ``development`` o ``production``
    :rtype: str
    :raises ConfigError: Si el valor no es uno de los entornos conocidos
    """
    raw = environ.get("ENVIRONMENT", DEFAULT_ENVIRONMENT)
    value = str(raw).strip().lower()
    if value not in SUPPORTED_ENVIRONMENTS:
        raise ConfigError(
            f"ENVIRONMENT must be one of {SUPPORTED_ENVIRONMENTS}, got {raw!r}"
        )
    return value


def _security_settings(environ):
    """Lee el entorno, los clientes con su clave y el límite de peticiones.

    Los errores de ``API_KEYS`` solo dicen la posición y el largo de la
    entrada; ``from None`` evita que la traza arrastre otra excepción.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: Campos ``environment``, ``api_clients``,
        ``rate_limit_per_minute`` y ``langsmith_tracing_requested``
    :rtype: dict
    :raises ConfigError: Si algún valor es inválido
    """
    try:
        clients = parse_api_keys(environ.get("API_KEYS", ""))
    except ConfigError as error:
        raise ConfigError(str(error)) from None
    return {
        "environment": _environment(environ),
        "api_clients": clients,
        "rate_limit_per_minute": _positive_int(
            environ, "RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        ),
        "langsmith_tracing_requested": _boolean(
            environ, "LANGSMITH_TRACING", DEFAULT_LANGSMITH_TRACING
        ),
    }


def _existing_file(environ, name, default):
    """Resuelve la ruta de un archivo de datos y comprueba que exista.

    Las rutas relativas se resuelven contra la carpeta ``product/``.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param name: Nombre de la variable
    :type name: str
    :param default: Ruta por omisión
    :type default: str
    :return: Ruta absoluta al archivo
    :rtype: pathlib.Path
    :raises ConfigError: Si el archivo no existe
    """
    path = Path(environ.get(name, default))
    if not path.is_absolute():
        path = PRODUCT_DIR / path
    path = path.resolve()
    if not path.is_file():
        raise ConfigError(f"{name} does not point to a file: {path}")
    return path


def _employees_path(environ):
    """Resuelve la ruta del archivo de empleados y comprueba que exista.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: Ruta absoluta al archivo de empleados
    :rtype: pathlib.Path
    :raises ConfigError: Si el archivo no existe
    """
    return _existing_file(environ, "EMPLOYEES_PATH", DEFAULT_EMPLOYEES_PATH)


def _cloudflare_settings(environ, provider):
    """Lee la cuenta, el gateway y el token de Cloudflare.

    Con ``gateway`` las tres variables son obligatorias. Los mensajes de error
    solo nombran la variable: nunca muestran su valor.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :param provider: Proveedor del modelo ya validado
    :type provider: str
    :return: Campos ``cf_account_id``, ``cf_gateway_id`` y ``cf_api_token``
    :rtype: dict
    :raises ConfigError: Si falta una variable y el proveedor es ``gateway``
    """
    defaults = {"CF_GATEWAY_ID": DEFAULT_CF_GATEWAY_ID}
    values = {
        name: str(environ.get(name, defaults.get(name, ""))).strip()
        for name in CLOUDFLARE_VARIABLES
    }
    if provider == GATEWAY_PROVIDER:
        for name, value in values.items():
            if not value:
                raise ConfigError(f"{name} is required when MODEL_PROVIDER=gateway")
    return {name.lower(): value for name, value in values.items()}


def _model_settings(environ):
    """Lee los modelos, sus precios y las palancas de costo.

    :param environ: Variables de entorno
    :type environ: Mapping[str, str]
    :return: Campos de modelos, palancas y ruta de precios
    :rtype: dict
    :raises ConfigError: Si un valor es inválido o un modelo no tiene precio
    """
    models = {
        "MODEL_SMALL": _non_empty(environ, "MODEL_SMALL", DEFAULT_MODEL_SMALL),
        "MODEL_LARGE": _non_empty(environ, "MODEL_LARGE", DEFAULT_MODEL_LARGE),
    }
    prices_path = _existing_file(environ, "PRICES_PATH", DEFAULT_PRICES_PATH)
    try:
        prices = PriceTable.load(prices_path)
    except (OSError, ValueError) as error:
        raise ConfigError(
            f"PRICES_PATH is not a valid prices file: {error}"
        ) from error
    for name, model in models.items():
        if model not in prices:
            raise ConfigError(f"{name} has no price in PRICES_PATH: {model!r}")
    return {
        "model_small": models["MODEL_SMALL"],
        "model_large": models["MODEL_LARGE"],
        "routing": _boolean(environ, "ROUTING", DEFAULT_ROUTING),
        "router_max_chars": _positive_int(
            environ, "ROUTER_MAX_CHARS", DEFAULT_ROUTER_MAX_CHARS
        ),
        "history_window": _non_negative_int(
            environ, "HISTORY_WINDOW", DEFAULT_HISTORY_WINDOW
        ),
        "model_max_tokens": _positive_int(
            environ, "MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS
        ),
        "model_temperature": _non_negative_float(
            environ, "MODEL_TEMPERATURE", DEFAULT_MODEL_TEMPERATURE
        ),
        "cache_ttl_seconds": _non_negative_int(
            environ, "CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS
        ),
        "prices_path": prices_path,
    }


@dataclass(frozen=True)
class Settings:  # pylint: disable=too-many-instance-attributes
    """Configuración inmutable de la aplicación.

    :param model_provider: Proveedor del modelo (``fake`` o ``gateway``)
    :type model_provider: str
    :param agent_max_steps: Tope de vueltas del bucle del agente
    :type agent_max_steps: int
    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :param employees_path: Ruta absoluta al archivo de empleados
    :type employees_path: pathlib.Path
    :param service_name: Campo ``service`` del log
    :type service_name: str
    :param slo_p95_ms: Meta de latencia p95 en milisegundos
    :type slo_p95_ms: int
    :param hide_inputs: No mandar entradas a LangSmith
    :type hide_inputs: bool
    :param hide_outputs: No mandar salidas a LangSmith
    :type hide_outputs: bool
    :param tracing_enabled: Trazas encendidas (``LANGSMITH_TRACING`` y clave)
    :type tracing_enabled: bool
    :param cf_account_id: Cuenta de Cloudflare
    :type cf_account_id: str
    :param cf_gateway_id: Gateway de AI Gateway
    :type cf_gateway_id: str
    :param cf_api_token: Token de Cloudflare (secreto: no sale en ``repr``)
    :type cf_api_token: str
    :param model_small: Modelo barato
    :type model_small: str
    :param model_large: Modelo capaz
    :type model_large: str
    :param routing: Enrutamiento por pregunta encendido
    :type routing: bool
    :param router_max_chars: Preguntas más largas van al modelo capaz
    :type router_max_chars: int
    :param history_window: Mensajes de historial que se mandan al modelo
    :type history_window: int
    :param model_max_tokens: Tope de tokens de salida por llamada
    :type model_max_tokens: int
    :param model_temperature: Temperatura del modelo
    :type model_temperature: float
    :param cache_ttl_seconds: Vida de la caché del gateway (0: apagada)
    :type cache_ttl_seconds: int
    :param prices_path: Ruta absoluta al archivo de precios
    :type prices_path: pathlib.Path
    :param environment: ``development`` o ``production``
    :type environment: str
    :param api_clients: Clientes con su clave (secreto: no sale en ``repr``)
    :type api_clients: tuple[app.auth.ApiClient, ...]
    :param rate_limit_per_minute: Peticiones por cliente por minuto
    :type rate_limit_per_minute: int
    :param langsmith_tracing_requested: ``LANGSMITH_TRACING`` vale ``true``,
        haya o no clave de LangSmith
    :type langsmith_tracing_requested: bool
    """

    model_provider: str
    agent_max_steps: int
    max_question_chars: int
    employees_path: Path
    service_name: str = DEFAULT_SERVICE_NAME
    slo_p95_ms: int = int(DEFAULT_SLO_P95_MS)
    hide_inputs: bool = True
    hide_outputs: bool = True
    tracing_enabled: bool = False
    cf_account_id: str = ""
    cf_gateway_id: str = DEFAULT_CF_GATEWAY_ID
    cf_api_token: str = field(default="", repr=False)
    model_small: str = DEFAULT_MODEL_SMALL
    model_large: str = DEFAULT_MODEL_LARGE
    routing: bool = True
    router_max_chars: int = int(DEFAULT_ROUTER_MAX_CHARS)
    history_window: int = int(DEFAULT_HISTORY_WINDOW)
    model_max_tokens: int = int(DEFAULT_MODEL_MAX_TOKENS)
    model_temperature: float = float(DEFAULT_MODEL_TEMPERATURE)
    cache_ttl_seconds: int = int(DEFAULT_CACHE_TTL_SECONDS)
    prices_path: Path = PRODUCT_DIR / DEFAULT_PRICES_PATH
    environment: str = DEFAULT_ENVIRONMENT
    api_clients: tuple = field(default=(), repr=False)
    rate_limit_per_minute: int = int(DEFAULT_RATE_LIMIT_PER_MINUTE)
    langsmith_tracing_requested: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "Settings":
        """Construye la configuración a partir de variables de entorno.

        :param environ: Variables de entorno (por ejemplo ``os.environ``)
        :type environ: Mapping[str, str]
        :return: Configuración validada
        :rtype: Settings
        :raises ConfigError: Si algún valor es inválido
        """
        provider = environ.get("MODEL_PROVIDER", DEFAULT_MODEL_PROVIDER).strip()
        if provider not in SUPPORTED_PROVIDERS:
            raise ConfigError(
                f"MODEL_PROVIDER must be one of {SUPPORTED_PROVIDERS}, "
                f"got {provider!r}"
            )
        return cls(
            model_provider=provider,
            agent_max_steps=_positive_int(
                environ, "AGENT_MAX_STEPS", DEFAULT_AGENT_MAX_STEPS
            ),
            max_question_chars=_positive_int(
                environ, "MAX_QUESTION_CHARS", DEFAULT_MAX_QUESTION_CHARS
            ),
            employees_path=_employees_path(environ),
            service_name=_service_name(environ),
            slo_p95_ms=_positive_int(environ, "SLO_P95_MS", DEFAULT_SLO_P95_MS),
            hide_inputs=_boolean(environ, "HIDE_INPUTS", DEFAULT_HIDE_TEXT),
            hide_outputs=_boolean(environ, "HIDE_OUTPUTS", DEFAULT_HIDE_TEXT),
            tracing_enabled=_tracing_enabled(environ),
            **_cloudflare_settings(environ, provider),
            **_model_settings(environ),
            **_security_settings(environ),
        )
