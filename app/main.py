"""API web sin estado del HR Assistant.

``create_app`` recibe sus dependencias para que las pruebas inyecten las suyas;
``app`` es la instancia que arranca uvicorn con la configuración del entorno.

Cada petición lleva un id (``X-Request-ID``), deja una línea JSON en el log y
se cuenta en las métricas del proceso. ``POST /ask`` y ``GET /metrics`` piden
la clave del cliente en ``X-API-Key`` y respetan su límite por minuto.
``POST /ask`` delega en ``app.pipeline.AskPipeline`` (guardián, caché,
supervisor, especialista y revisor) y responde 400 si el guardián bloquea la
entrada. ``GET /metrics`` responde 403 a los clientes fuera de
``METRICS_CLIENTS``. ``GET /dashboard`` sirve el tablero, sin datos ni clave:
la página pide la clave y lee ``/metrics`` desde el navegador.
"""

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import can_read_metrics, identify_client
from app.cache import AnswerCache
from app.clock import SystemClock
from app.compliance import enforce
from app.config import ConfigError, Settings
from app.costs import PriceTable
from app.directory import EmployeeDirectory
from app.gateway import ModelUnavailable
from app.guard import InputBlocked
from app.llm import build_models
from app.logs import JsonLogger
from app.metrics import ACCESS_DENIED, Metrics
from app.pipeline import AskPipeline, PipelineDependencies
from app.policies import PolicyBook
from app.ratelimit import RateLimiter
from app.specialists import build_specialists
from app.supervisor import Supervisor
from app.tracing import build_tracer

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"
DASHBOARD_PATH = STATIC_DIR / "dashboard.html"
REQUEST_ID_HEADER = "X-Request-ID"
API_KEY_HEADER = "X-API-Key"
RETRY_AFTER_HEADER = "Retry-After"
UNAUTHORIZED_STATUS = 401
UNAUTHORIZED_DETAIL = "invalid or missing API key"
RATE_LIMITED_STATUS = 429
RATE_LIMITED_DETAIL = "rate limit exceeded"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")
INTERNAL_ERROR_STATUS = 500
NOT_READY_STATUS = 503
READY_OK = "ok"
READY_ERROR = "error"
INTERNAL_ERROR_DETAIL = "internal error"
MODEL_UNAVAILABLE_STATUS = 502
MODEL_UNAVAILABLE_DETAIL = "model unavailable"
BLOCKED_STATUS = 400
BLOCKED_DETAIL = "request blocked by input policy"
FORBIDDEN_STATUS = 403
FORBIDDEN_DETAIL = "forbidden"


class HistoryMessage(BaseModel):
    """Mensaje previo de la conversación que guarda el navegador.

    :param role: ``user`` o ``assistant``
    :type role: str
    :param content: Texto del mensaje
    :type content: str
    """

    role: Literal["user", "assistant"]
    content: str


class AskResponse(BaseModel):
    """Respuesta de ``POST /ask``.

    :param answer: Respuesta en español
    :type answer: str
    :param steps: Vueltas que dio el agente
    :type steps: int
    :param tools_used: Herramientas usadas, en orden
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param request_id: Id de la petición, para pasarlo a soporte
    :type request_id: str
    :param model: Modelo que contestó
    :type model: str
    :param route: Motivo del enrutador
    :type route: str
    :param cached_calls: Llamadas respondidas desde la caché del gateway
    :type cached_calls: int
    :param cost_usd: Costo de la respuesta en USD (supervisor y especialista)
    :type cost_usd: float
    :param specialist: Especialista que respondió: ``directory`` o ``policy``
    :type specialist: str
    :param agents: Agentes que corrieron, en orden
    :type agents: list[str]
    :param supervisor_route: Motivo del supervisor
    :type supervisor_route: str
    :param pii_redacted: Tipos de dato personal ocultados, ordenados
    :type pii_redacted: list[str]
    :param cached: ``True`` si salió de la caché de respuestas
    :type cached: bool
    :param fallback: ``True`` si respondió el modelo de respaldo
    :type fallback: bool
    """

    answer: str
    steps: int
    tools_used: List[str]
    input_tokens: int
    output_tokens: int
    request_id: str
    model: str
    route: str
    cached_calls: int
    cost_usd: float
    specialist: str
    agents: List[str]
    supervisor_route: str
    pii_redacted: List[str]
    cached: bool
    fallback: bool


@dataclass(frozen=True)
class _Runtime:  # pylint: disable=too-many-instance-attributes
    """Dependencias ya construidas que usan las rutas.

    :param settings: Configuración con las palancas de costo
    :type settings: app.config.Settings
    :param models: Modelos por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``)
    :type models: dict[str, app.llm.LanguageModel]
    :param prices: Tabla de precios por modelo
    :type prices: app.costs.PriceTable
    :param directory: Directorio de empleados (``/ready``)
    :type directory: app.directory.EmployeeDirectory
    :param policies: Libro de políticas (``/ready``)
    :type policies: app.policies.PolicyBook
    :param pipeline: Agentes que responden las preguntas
    :type pipeline: app.pipeline.AskPipeline
    :param tracer: Tracer de la corrida
    :type tracer: app.tracing.NoopTracer or app.tracing.LangSmithTracer
    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    :param ask_request: Clase Pydantic del cuerpo de ``POST /ask``
    :type ask_request: type
    :param index_html: Página web
    :type index_html: str
    :param dashboard_html: Tablero de métricas (sin datos ni clave)
    :type dashboard_html: str
    :param limiter: Límite de peticiones por cliente
    :type limiter: app.ratelimit.RateLimiter
    """

    settings: Settings
    models: dict
    prices: PriceTable
    directory: EmployeeDirectory
    policies: PolicyBook
    pipeline: AskPipeline
    tracer: object
    logger: JsonLogger
    metrics: Metrics
    ask_request: type
    index_html: str
    dashboard_html: str
    limiter: RateLimiter


def _build_ask_request(max_question_chars):
    """Crea el modelo de la petición con el largo máximo configurado.

    :param max_question_chars: Largo máximo de la pregunta
    :type max_question_chars: int
    :return: Clase Pydantic de la petición
    :rtype: type
    """

    class AskRequest(BaseModel):
        """Cuerpo de ``POST /ask``.

        :param question: Pregunta de la persona
        :type question: str
        :param history: Vueltas anteriores enviadas por el cliente
        :type history: list[HistoryMessage]
        """

        question: str = Field(max_length=max_question_chars)
        history: List[HistoryMessage] = Field(default_factory=list)

        @field_validator("question")
        @classmethod
        def question_not_blank(cls, value):
            """Rechaza preguntas vacías o solo con espacios.

            :param value: Pregunta recibida
            :type value: str
            :return: La pregunta sin cambios
            :rtype: str
            :raises ValueError: Si la pregunta está vacía
            """
            if not value.strip():
                raise ValueError("question must not be empty")
            return value

    return AskRequest


def resolve_request_id(header_value):
    """Usa el id del cliente si es válido; si no, genera un UUID.

    Solo se aceptan letras, dígitos, ``.``, ``_`` y ``-``, hasta 128
    caracteres, para que el id no pueda inyectar nada en el log ni en los
    encabezados.

    :param header_value: Valor del encabezado ``X-Request-ID`` o ``None``
    :type header_value: str or None
    :return: Id de la petición
    :rtype: str
    """
    if header_value and REQUEST_ID_PATTERN.fullmatch(header_value):
        return header_value
    return str(uuid.uuid4())


def _check(probe):
    """Corre una comprobación de ``/ready`` sin dejar salir el error.

    :param probe: Función sin argumentos que devuelve un conteo
    :type probe: callable
    :return: ``ok`` si el conteo es mayor que cero; si no, ``error``
    :rtype: str
    """
    try:
        healthy = probe() > 0
    except Exception:  # pylint: disable=broad-exception-caught
        # Solo el estado: el mensaje puede traer rutas del servidor.
        healthy = False
    return READY_OK if healthy else READY_ERROR


def _readiness(runtime):
    """Revisa que los datos de los que depende ``/ask`` sigan disponibles.

    :param runtime: Dependencias ya construidas
    :type runtime: _Runtime
    :return: Estado por dato: ``directory``, ``policies`` y ``prices``
    :rtype: dict[str, str]
    """
    settings = runtime.settings

    def priced_models():
        models = (settings.model_small, settings.model_large)
        return sum(1 for model in models if runtime.prices.price(model))

    return {
        "directory": _check(runtime.directory.count),
        "policies": _check(runtime.policies.count),
        "prices": _check(priced_models),
    }


def _install_observability(application, clock, logger, metrics):
    """Agrega el middleware de id, log ``request``, métricas y errores 500.

    :param application: Aplicación FastAPI
    :type application: fastapi.FastAPI
    :param clock: Reloj inyectado para medir la latencia
    :type clock: app.clock.Clock
    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    """

    @application.middleware("http")
    async def observe_request(request: Request, call_next):
        """Asigna el id, mide la latencia y convierte errores en 500."""
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        start = clock.monotonic()
        try:
            response = await call_next(request)
        except Exception as error:  # pylint: disable=broad-exception-caught
            # Solo el tipo: el mensaje puede traer datos personales.
            logger.emit("error", request_id, error_type=type(error).__name__)
            response = JSONResponse(
                status_code=INTERNAL_ERROR_STATUS,
                content={"detail": INTERNAL_ERROR_DETAIL, "request_id": request_id},
            )
        latency_ms = round((clock.monotonic() - start) * 1000, 1)
        logger.emit(
            "request",
            request_id,
            client=getattr(request.state, "client", None),
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            latency_ms=latency_ms,
        )
        metrics.record_request(latency_ms, response.status_code)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


def _client_dependency(runtime):
    """Crea la dependencia que exige la clave y aplica el límite.

    Primero la clave (401) y después el límite (429). En el log solo va el
    nombre del cliente o el motivo del rechazo: nunca la clave.

    :param runtime: Dependencias ya construidas
    :type runtime: _Runtime
    :return: Dependencia de FastAPI que devuelve el nombre del cliente
    :rtype: callable
    """

    def require_client(request: Request):
        """Identifica al cliente por ``X-API-Key`` y revisa su límite.

        :param request: Petición en curso
        :type request: fastapi.Request
        :return: Nombre del cliente
        :rtype: str
        :raises fastapi.HTTPException: 401 sin clave válida; 429 sobre el límite
        """
        request_id = request.state.request_id
        header_value = request.headers.get(API_KEY_HEADER)
        client = identify_client(header_value, runtime.settings.api_clients)
        if client is None:
            reason = "invalid" if header_value else "missing"
            runtime.logger.emit("auth_rejected", request_id, reason=reason)
            raise HTTPException(
                status_code=UNAUTHORIZED_STATUS, detail=UNAUTHORIZED_DETAIL
            )
        request.state.client = client
        decision = runtime.limiter.check(client)
        if not decision.allowed:
            runtime.logger.emit(
                "rate_limited",
                request_id,
                client=client,
                retry_after=decision.retry_after,
            )
            raise HTTPException(
                status_code=RATE_LIMITED_STATUS,
                detail=RATE_LIMITED_DETAIL,
                headers={RETRY_AFTER_HEADER: str(decision.retry_after)},
            )
        return client

    return require_client


def _add_routes(application, runtime):
    """Registra las rutas de la API.

    ``/``, ``/dashboard``, ``/health`` y ``/ready`` son públicas; ``/ask`` y
    ``/metrics`` piden clave.

    :param application: Aplicación FastAPI
    :type application: fastapi.FastAPI
    :param runtime: Dependencias ya construidas
    :type runtime: _Runtime
    """
    ask_request = runtime.ask_request
    require_client = _client_dependency(runtime)

    @application.get("/", response_class=HTMLResponse)
    def home():
        """Sirve la página web."""
        return HTMLResponse(runtime.index_html)

    @application.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        """Sirve el tablero: HTML estático, sin datos ni clave.

        La página pide la clave y lee ``/metrics`` desde el navegador.
        """
        return HTMLResponse(runtime.dashboard_html)

    @application.get("/health")
    def health():
        """Informa que el proceso está vivo y su id."""
        return {"status": "ok", "pid": os.getpid()}

    @application.get("/ready")
    def ready():
        """Informa si el directorio, las políticas y los precios responden."""
        checks = _readiness(runtime)
        if all(value == READY_OK for value in checks.values()):
            return {"status": "ready", "checks": checks}
        return JSONResponse(
            status_code=NOT_READY_STATUS,
            content={"status": "not_ready", "checks": checks},
        )

    @application.get("/metrics")
    def metrics(request: Request, client: str = Depends(require_client)):
        """Devuelve las métricas de este proceso: operativas y de negocio.

        Agrega al formato de la sesión 2 el costo acumulado, ``by_specialist``,
        ``by_client``, ``security``, ``cache``, ``fallbacks`` y ``supervisor``.
        Orden: 401 -> 429 -> 403 si ``METRICS_CLIENTS`` no nombra al cliente.
        """
        request_id = request.state.request_id
        if not can_read_metrics(client, runtime.settings.metrics_clients):
            runtime.logger.emit(
                "audit",
                request_id,
                client=client,
                action="access_denied",
                path=request.url.path,
            )
            runtime.metrics.add_security(ACCESS_DENIED)
            return JSONResponse(
                status_code=FORBIDDEN_STATUS, content={"detail": FORBIDDEN_DETAIL}
            )
        runtime.logger.emit(
            "audit", request_id, client=client, action="metrics_read"
        )
        snapshot = runtime.metrics.snapshot(os.getpid())
        snapshot["cost_usd"] = runtime.metrics.cost_usd()
        snapshot.update(runtime.metrics.business())
        snapshot["security"] = runtime.metrics.security()
        snapshot["cache"] = runtime.metrics.cache()
        snapshot["fallbacks"] = runtime.metrics.fallbacks()
        return snapshot

    @application.post("/ask", response_model=AskResponse)
    def ask(
        payload: ask_request,
        request: Request,
        client: str = Depends(require_client),
    ):
        """Responde una pregunta; el historial lo manda el cliente."""
        request_id = request.state.request_id
        try:
            outcome = runtime.pipeline.answer(request_id, client, payload)
            return AskResponse(request_id=request_id, **outcome.response_fields())
        except InputBlocked:
            # El pipeline ya escribió el audit; el cuerpo nunca repite el texto.
            return JSONResponse(
                status_code=BLOCKED_STATUS,
                content={"detail": BLOCKED_DETAIL, "request_id": request_id},
            )
        except ModelUnavailable as error:
            # Solo el tipo: nunca la URL (con la cuenta) ni el token.
            runtime.logger.emit("error", request_id, error_type=type(error).__name__)
            return JSONResponse(
                status_code=MODEL_UNAVAILABLE_STATUS,
                content={"detail": MODEL_UNAVAILABLE_DETAIL, "request_id": request_id},
            )


def _load_policies(path):
    """Carga las políticas al arrancar.

    :param path: Ruta al archivo ``policies.json``
    :type path: pathlib.Path
    :return: Libro de políticas
    :rtype: app.policies.PolicyBook
    :raises app.config.ConfigError: Si el archivo no se puede leer o no tiene
        el formato esperado
    """
    try:
        return PolicyBook.load(path)
    except (OSError, ValueError):
        raise ConfigError("POLICIES_PATH is not a valid policies file") from None


def _resolve_models(settings, model, models, build):
    """Decide qué modelos usa la aplicación.

    :param settings: Configuración con ``MODEL_SMALL`` y ``MODEL_LARGE``
    :type settings: app.config.Settings
    :param model: Modelo único inyectado; se usa para ambas rutas
    :type model: app.llm.LanguageModel or None
    :param models: Modelos por nombre inyectados
    :type models: dict or None
    :param build: Función sin argumentos que construye los modelos
    :type build: callable
    :return: Modelos por nombre
    :rtype: dict[str, app.llm.LanguageModel]
    """
    if models is not None:
        return dict(models)
    if model is not None:
        return {settings.model_small: model, settings.model_large: model}
    return build()


def _build_answer_cache(settings, clock):
    """Crea la caché de respuestas si está encendida.

    :param settings: Configuración con ``ANSWER_CACHE_TTL_SECONDS`` y
        ``ANSWER_CACHE_MAX_ENTRIES``
    :type settings: app.config.Settings
    :param clock: Reloj que mide la vida de cada respuesta
    :type clock: app.clock.Clock
    :return: Caché o ``None`` si el TTL es 0
    :rtype: app.cache.AnswerCache or None
    """
    if settings.answer_cache_ttl_seconds <= 0:
        return None
    return AnswerCache(
        settings.answer_cache_ttl_seconds, settings.answer_cache_max_entries, clock
    )


# Las dependencias se inyectan por nombre para las pruebas.
# pylint: disable-next=too-many-arguments
def create_app(
    settings=None,
    model=None,
    directory=None,
    *,
    models=None,
    prices=None,
    http_client=None,
    clock=None,
    log_stream=None,
    tracer=None,
):
    """Arma la aplicación FastAPI con sus dependencias.

    :param settings: Configuración; si falta se lee del entorno
    :type settings: app.config.Settings or None
    :param model: Modelo único para ambas rutas; el costo sale del nombre que
        elige el enrutador
    :type model: app.llm.LanguageModel or None
    :param directory: Directorio de empleados; si falta se carga del archivo
    :type directory: app.directory.EmployeeDirectory or None
    :param models: Modelos por nombre; si faltan (y no hay ``model``) se
        construyen según la configuración
    :type models: dict[str, app.llm.LanguageModel] or None
    :param prices: Tabla de precios; si falta se carga de ``PRICES_PATH``
    :type prices: app.costs.PriceTable or None
    :param http_client: Cliente HTTP para AI Gateway; si falta se crea uno
    :type http_client: httpx.Client or None
    :param clock: Reloj para el log y la latencia; si falta, el del sistema
    :type clock: app.clock.Clock or None
    :param log_stream: Destino del log JSON; si falta, la salida estándar
    :type log_stream: typing.TextIO or None
    :param tracer: Tracer; si falta se elige según la configuración
    :type tracer: app.tracing.NoopTracer or app.tracing.LangSmithTracer or None
    :return: Aplicación lista para servir
    :rtype: fastapi.FastAPI
    :raises app.config.ConfigError: Si la configuración del entorno es inválida
        o, con ``ENVIRONMENT=production``, incumple una regla de compliance
    """
    settings = settings or Settings.from_env(os.environ)
    enforce(settings)
    directory = directory or EmployeeDirectory(settings.employees_path)
    policies = _load_policies(settings.policies_path)
    clock = clock if clock is not None else SystemClock()
    models = _resolve_models(
        settings,
        model,
        models,
        lambda: build_models(
            settings,
            directory.departments(),
            http_client,
            policies.keywords(),
            # Relojes de prueba viejos sin ``sleep``: se usa ``time.sleep``.
            sleep=getattr(clock, "sleep", None),
        ),
    )
    tracer = tracer if tracer is not None else build_tracer(settings)
    dependencies = PipelineDependencies(
        settings=settings,
        models=models,
        prices=prices if prices is not None else PriceTable.load(settings.prices_path),
        supervisor=Supervisor(
            model=models[settings.model_small],
            departments=directory.departments(),
            policies=policies,
        ),
        specialists=build_specialists(
            directory, policies, settings.agent_max_steps, tracer
        ),
        directory=directory,
        tracer=tracer,
        logger=JsonLogger(settings.service_name, clock, log_stream),
        metrics=Metrics(settings.slo_p95_ms),
        policies=policies,
        answer_cache=_build_answer_cache(settings, clock),
    )
    runtime = _Runtime(
        settings=settings,
        models=models,
        prices=dependencies.prices,
        directory=directory,
        policies=policies,
        pipeline=AskPipeline(dependencies),
        tracer=tracer,
        logger=dependencies.logger,
        metrics=dependencies.metrics,
        ask_request=_build_ask_request(settings.max_question_chars),
        index_html=INDEX_PATH.read_text(encoding="utf-8"),
        dashboard_html=DASHBOARD_PATH.read_text(encoding="utf-8"),
        limiter=RateLimiter(settings.rate_limit_per_minute, clock),
    )

    application = FastAPI(title="HR Assistant")
    _install_observability(application, clock, runtime.logger, runtime.metrics)
    _add_routes(application, runtime)
    return application


app = create_app()
