"""Costura del sistema multi-agente para ``POST /ask``.

Cada pregunta pasa por: guardián -> caché -> supervisor -> especialista (con
respaldo) -> revisor. Este módulo arma el resultado (``AskOutcome``) con los
tokens y el costo de todas las llamadas, escribe ``audit`` y ``agent_run`` y
suma las métricas.

Trazas: la petición es el run raíz ``request`` y cada agente es su propio run
dentro de él (``agent.guard``, ``agent.supervisor``, ``agent.directory`` o
``agent.policy`` y ``agent.reviewer``), con ``request_id``, ``client`` y, desde
que el supervisor decide, ``specialist`` en los metadatos. El run raíz y los de
guardián, supervisor y revisor no tienen entradas y su salida es un resumen
(tipos, conteos y decisiones): el texto de la persona nunca llega a la traza
por ellos. El especialista recibe solo texto ya redactado.
"""

from dataclasses import dataclass, field
from functools import partial
from typing import Any

from app.agent import STOPPED_ANSWER
from app.cache import normalize_question
from app.costs import COST_DECIMALS
from app.gateway import ModelUnavailable
from app.guard import USER_ROLE, InputBlocked, inspect
from app.levers import choose_model, trim_history
from app.metrics import (
    BLOCKED_INPUTS,
    OUTPUT_BLOCKED,
    PII_REDACTIONS,
    SUPERVISOR_MODEL,
    SUPERVISOR_RULE,
)
from app.pii import redact
from app.resilience import run_with_fallback
from app.reviewer import BLOCK_REASON as REVIEW_BLOCK_REASON
from app.reviewer import employee_ids, mentions_unknown_employee, review
from app.specialists import Grounding, ground_policy
from app.supervisor import POLICY, ROUTE_POLICY, RULE_ROUTES
from app.tracing import TRACE_REQUEST, agent_trace_name, run_traced

LOCATION_INPUT = "input"
LOCATION_OUTPUT = "output"
AGENT_GUARD = "guard"
AGENT_SUPERVISOR = "supervisor"
AGENT_REVIEWER = "reviewer"
AGENT_CACHE = "cache"
AUDIT_ARG_MAX_CHARS = 200
POLICY_BLOCK_REASON = "ungrounded_policy_number"


@dataclass(frozen=True)
class GuardedInput:
    """Entrada ya revisada por el guardián.

    :param question: Pregunta, con la PII reemplazada por marcadores
    :type question: str
    :param history: Historial completo, con la PII reemplazada
    :type history: list[dict]
    :param pii_types: Tipos de PII ocultados en la entrada
    :type pii_types: tuple[str, ...]
    """

    question: str
    history: list
    pii_types: tuple = ()


@dataclass(frozen=True)
class ReviewedAnswer:
    """Respuesta ya revisada por el revisor.

    :param answer: Respuesta final
    :type answer: str
    :param pii_types: Tipos de PII ocultados en la salida
    :type pii_types: tuple[str, ...]
    :param blocked: ``True`` si se reemplazó por el mensaje de verificación
    :type blocked: bool
    """

    answer: str
    pii_types: tuple = ()
    blocked: bool = False


@dataclass(frozen=True)
class CachedAnswer:
    """Lo que guarda la caché de respuestas: solo la respuesta y su origen.

    :param answer: Respuesta ya revisada
    :type answer: str
    :param specialist: ``directory`` o ``policy``
    :type specialist: str
    :param supervisor_route: Motivo del supervisor
    :type supervisor_route: str
    :param model: Modelo que contestó
    :type model: str
    :param route: Motivo del enrutador de costo
    :type route: str
    """

    answer: str
    specialist: str
    supervisor_route: str
    model: str
    route: str


@dataclass(frozen=True)
class SpecialistRun:
    """Corrida de un especialista.

    :param result: Resultado del bucle del agente
    :type result: app.agent.AgentResult
    :param model: Modelo que contestó
    :type model: str
    :param fallback: ``True`` si contestó el modelo de respaldo
    :type fallback: bool
    """

    result: Any
    model: str
    fallback: bool = False


@dataclass
class AskOutcome:  # pylint: disable=too-many-instance-attributes
    """Resultado de una pregunta: la respuesta y lo que se registra de ella.

    ``input_tokens``, ``output_tokens``, ``cached_calls`` y ``cost_usd`` suman
    supervisor y especialista; ``steps`` y ``tools_used`` son del especialista.

    :param answer: Respuesta final
    :type answer: str
    :param steps: Vueltas del especialista
    :type steps: int
    :param tools_used: Herramientas del especialista, en orden
    :type tools_used: list[str]
    :param input_tokens: Tokens de entrada
    :type input_tokens: int
    :param output_tokens: Tokens de salida
    :type output_tokens: int
    :param model: Modelo que contestó
    :type model: str
    :param route: Motivo del enrutador de costo
    :type route: str
    :param cost_usd: Costo en USD
    :type cost_usd: float
    :param cached_calls: Llamadas respondidas desde la caché del gateway
    :type cached_calls: int
    :param specialist: ``directory`` o ``policy``
    :type specialist: str
    :param agents: Agentes que corrieron, en orden
    :type agents: list[str]
    :param supervisor_route: Motivo del supervisor
    :type supervisor_route: str
    :param pii_redacted: Tipos de PII ocultados, sin repetir y ordenados
    :type pii_redacted: list[str]
    :param cached: ``True`` si salió de la caché de respuestas
    :type cached: bool
    :param fallback: ``True`` si contestó el modelo de respaldo
    :type fallback: bool
    :param stopped: Por qué terminó el especialista
    :type stopped: str
    :param tool_calls: Herramientas con sus argumentos, para el ``audit``
    :type tool_calls: list[dict]
    :param history_sent: Mensajes de historial que se mandaron al modelo
    :type history_sent: int
    :param output_blocked: ``True`` si el revisor reemplazó la respuesta
    :type output_blocked: bool
    """

    answer: str
    steps: int
    tools_used: list
    input_tokens: int
    output_tokens: int
    model: str
    route: str
    cost_usd: float
    cached_calls: int
    specialist: str
    agents: list
    supervisor_route: str
    pii_redacted: list = field(default_factory=list)
    cached: bool = False
    fallback: bool = False
    stopped: str = "answer"
    tool_calls: list = field(default_factory=list)
    history_sent: int = 0
    output_blocked: bool = False

    def response_fields(self):
        """Campos de la respuesta de ``POST /ask`` (sin ``request_id``).

        :return: Valores por nombre de campo
        :rtype: dict
        """
        return {
            "answer": self.answer,
            "steps": self.steps,
            "tools_used": list(self.tools_used),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
            "route": self.route,
            "cached_calls": self.cached_calls,
            "cost_usd": self.cost_usd,
            "specialist": self.specialist,
            "agents": list(self.agents),
            "supervisor_route": self.supervisor_route,
            "pii_redacted": list(self.pii_redacted),
            "cached": self.cached,
            "fallback": self.fallback,
        }


def _audit_args(args):
    """Redacta y recorta los argumentos de una herramienta para el log.

    Los argumentos los escribe el modelo y pueden copiar un dato personal que
    vio antes (por ejemplo, un correo de ``get_employee``): cada texto pasa
    por ``app.pii.redact`` antes de recortarse, así el log solo lleva
    marcadores como ``[EMAIL]`` y nunca el valor.

    :param args: Argumentos con que se llamó la herramienta
    :type args: dict
    :return: Argumentos con los textos redactados y recortados a
        ``AUDIT_ARG_MAX_CHARS``
    :rtype: dict
    """
    return {
        key: (
            redact(value).text[:AUDIT_ARG_MAX_CHARS]
            if isinstance(value, str)
            else value
        )
        for key, value in args.items()
    }


def _guard_summary(guarded):
    """Salida de la traza ``agent.guard``: solo tipos y conteos.

    :param guarded: Entrada ya revisada por el guardián
    :type guarded: GuardedInput
    :return: Tipos de PII ocultados y mensajes de historial
    :rtype: dict
    """
    return {
        "pii_types": list(guarded.pii_types),
        "history_messages": len(guarded.history),
    }


def _decision_summary(decision):
    """Salida de la traza ``agent.supervisor``: especialista y motivo.

    :param decision: Decisión del supervisor
    :type decision: app.supervisor.Decision
    :return: Especialista, motivo y llamadas al modelo
    :rtype: dict
    """
    return {
        "specialist": decision.specialist,
        "supervisor_route": decision.route,
        "model_calls": len(decision.completions),
    }


def _review_summary(reviewed):
    """Salida de la traza ``agent.reviewer``: tipos, bloqueo y largo.

    :param reviewed: Respuesta ya revisada
    :type reviewed: ReviewedAnswer
    :return: Tipos de PII ocultados, si se bloqueó y largo de la respuesta
    :rtype: dict
    """
    return {
        "pii_types": list(reviewed.pii_types),
        "output_blocked": reviewed.blocked,
        "answer_chars": len(reviewed.answer),
    }


def _outcome_summary(outcome):
    """Salida del run raíz ``request``: conteos, modelo y costo, sin texto.

    :param outcome: Resultado de la pregunta
    :type outcome: AskOutcome
    :return: Especialista, agentes, motivo, tokens, costo y banderas
    :rtype: dict
    """
    return {
        "specialist": outcome.specialist,
        "agents": list(outcome.agents),
        "supervisor_route": outcome.supervisor_route,
        "model": outcome.model,
        "steps": outcome.steps,
        "input_tokens": outcome.input_tokens,
        "output_tokens": outcome.output_tokens,
        "cost_usd": outcome.cost_usd,
        "pii_redacted": list(outcome.pii_redacted),
        "cached": outcome.cached,
        "fallback": outcome.fallback,
    }


def _supervisor_kind(outcome):
    """Quién decidió el especialista, para el contador ``supervisor``.

    :param outcome: Resultado de la pregunta
    :type outcome: AskOutcome
    :return: ``rule``, ``model`` (también ``model_invalid``) o ``None`` si el
        supervisor no corrió (acierto de caché)
    :rtype: str or None
    """
    if AGENT_SUPERVISOR not in outcome.agents:
        return None
    if outcome.supervisor_route in RULE_ROUTES:
        return SUPERVISOR_RULE
    return SUPERVISOR_MODEL


def _sum_tokens(completions):
    """Suma tokens y llamadas cacheadas de varias llamadas al modelo.

    :param completions: Llamadas al modelo
    :type completions: Iterable[app.completion.Completion]
    :return: Tokens de entrada, de salida y llamadas cacheadas
    :rtype: tuple[int, int, int]
    """
    input_tokens = output_tokens = cached_calls = 0
    for completion in completions:
        input_tokens += completion.input_tokens
        output_tokens += completion.output_tokens
        cached_calls += 1 if completion.cached else 0
    return input_tokens, output_tokens, cached_calls


@dataclass(frozen=True)
class PipelineDependencies:  # pylint: disable=too-many-instance-attributes
    """Dependencias ya construidas del pipeline.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :param models: Modelos por nombre (``MODEL_SMALL`` y ``MODEL_LARGE``)
    :type models: dict[str, app.llm.LanguageModel]
    :param prices: Tabla de precios por modelo
    :type prices: app.costs.PriceTable
    :param supervisor: Supervisor que elige el especialista
    :type supervisor: app.supervisor.Supervisor
    :param specialists: Especialistas por nombre
    :type specialists: dict[str, app.agent.Agent]
    :param directory: Directorio de empleados (lo usa el revisor)
    :type directory: app.directory.EmployeeDirectory
    :param tracer: Tracer de la corrida
    :type tracer: app.tracing.NoopTracer or app.tracing.LangSmithTracer
    :param logger: Log JSON
    :type logger: app.logs.JsonLogger
    :param metrics: Métricas del proceso
    :type metrics: app.metrics.Metrics
    :param policies: Libro de políticas (lo usan el especialista ``policy``
        y el revisor)
    :type policies: app.policies.PolicyBook
    :param answer_cache: Caché de respuestas; ``None`` si está apagada
        (``ANSWER_CACHE_TTL_SECONDS=0``)
    :type answer_cache: app.cache.AnswerCache or None
    """

    settings: object
    models: dict
    prices: object
    supervisor: object
    specialists: dict
    directory: object
    tracer: object
    logger: object
    metrics: object
    policies: object
    answer_cache: object = None


class AskPipeline:
    """Orquesta los agentes de una pregunta.

    :param dependencies: Dependencias ya construidas
    :type dependencies: PipelineDependencies
    """

    def __init__(self, dependencies):
        self._deps = dependencies

    def answer(self, request_id, client, payload):
        """Responde una pregunta pasando por todos los agentes.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param payload: Cuerpo de ``POST /ask`` (``question`` y ``history``)
        :type payload: pydantic.BaseModel
        :return: Respuesta y datos de la corrida
        :rtype: AskOutcome
        :raises app.gateway.ModelUnavailable: Si ningún modelo contesta
        """
        deps = self._deps
        history = [message.model_dump() for message in payload.history]
        with deps.tracer.context(request_id, client=client):
            outcome = run_traced(
                deps.tracer,
                TRACE_REQUEST,
                partial(self._run, request_id, client, payload.question, history),
                _outcome_summary,
            )
        self._record(request_id, client, payload, outcome)
        return outcome

    def _run(self, request_id, client, question, history):
        """Cuerpo del run raíz: guardián, caché y, si no hay acierto, agentes.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param question: Pregunta original
        :type question: str
        :param history: Historial original
        :type history: list[dict]
        :return: Resultado de la pregunta
        :rtype: AskOutcome
        :raises app.guard.InputBlocked: Si hay prompt injection
        :raises app.gateway.ModelUnavailable: Si ningún modelo contesta
        """
        guarded = run_traced(
            self._deps.tracer,
            agent_trace_name(AGENT_GUARD),
            partial(self._guard, request_id, client, question, history),
            _guard_summary,
        )
        outcome = self._cache_lookup(guarded)
        if outcome is None:
            outcome = self._answer_with_agents(request_id, client, guarded)
            self._cache_store(guarded, outcome)
        return outcome

    def _answer_with_agents(self, request_id, client, guarded):
        """Supervisor, especialista y revisor; arma tokens y costo.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param guarded: Entrada ya revisada por el guardián
        :type guarded: GuardedInput
        :return: Resultado de la pregunta
        :rtype: AskOutcome
        :raises app.gateway.ModelUnavailable: Si ningún modelo contesta
        """
        deps = self._deps
        decision = run_traced(
            deps.tracer,
            agent_trace_name(AGENT_SUPERVISOR),
            partial(deps.supervisor.route, guarded.question),
            _decision_summary,
        )
        route = choose_model(guarded.question, deps.settings)
        history = trim_history(guarded.history, deps.settings.history_window)
        grounding = self._ground(decision, guarded.question)
        # La política consultada en código va primero, antes del historial.
        messages = (
            list(grounding.messages)
            + history
            + [{"role": USER_ROLE, "content": guarded.question}]
        )
        # Desde aquí los runs llevan también el especialista en sus metadatos.
        with deps.tracer.context(
            request_id, client=client, specialist=decision.specialist
        ):
            run = self._run_specialist(
                deps.specialists[decision.specialist], messages, route.model
            )
            tool_calls = list(grounding.tool_calls) + list(run.result.tool_calls)
            reviewed = run_traced(
                deps.tracer,
                agent_trace_name(AGENT_REVIEWER),
                partial(
                    self._review,
                    request_id,
                    client,
                    run.result.answer,
                    guarded.question,
                    self._policy_texts(decision, tool_calls),
                ),
                _review_summary,
            )
        tokens = _sum_tokens(
            list(decision.completions) + list(run.result.completions)
        )
        return AskOutcome(
            answer=reviewed.answer,
            steps=run.result.steps,
            tools_used=grounding.tools_used + list(run.result.tools_used),
            input_tokens=tokens[0],
            output_tokens=tokens[1],
            model=run.model,
            route=route.reason,
            cached_calls=tokens[2],
            cost_usd=self._cost(decision, run),
            specialist=decision.specialist,
            agents=[
                AGENT_GUARD,
                AGENT_SUPERVISOR,
                decision.specialist,
                AGENT_REVIEWER,
            ],
            supervisor_route=decision.route,
            pii_redacted=sorted(set(guarded.pii_types) | set(reviewed.pii_types)),
            fallback=run.fallback,
            stopped=run.result.stopped,
            tool_calls=tool_calls,
            history_sent=len(history),
            output_blocked=reviewed.blocked,
        )

    def _ground(self, decision, question):
        """Consulta en código la política si el supervisor eligió por regla.

        Solo con ``supervisor_route == "rule:policy"``: el modelo recibe el
        texto de la política antes de su primera llamada.

        :param decision: Decisión del supervisor
        :type decision: app.supervisor.Decision
        :param question: Pregunta ya redactada por el guardián
        :type question: str
        :return: Mensajes y llamadas de la consulta; vacío si no aplica
        :rtype: app.specialists.Grounding
        """
        if decision.route != ROUTE_POLICY:
            return Grounding()
        return ground_policy(self._deps.policies, question)

    def _policy_texts(self, decision, tool_calls):
        """Textos de políticas que el revisor usa para anclar las cifras.

        :param decision: Decisión del supervisor
        :type decision: app.supervisor.Decision
        :param tool_calls: Herramientas de la petición: las de código y las
            del bucle del especialista
        :type tool_calls: list[dict]
        :return: Textos consultados (tupla vacía si no hubo ninguno) para
            ``policy``; ``None`` para ``directory``
        :rtype: tuple[str, ...] or None
        """
        if decision.specialist != POLICY:
            return None
        return self._deps.policies.consulted_texts(tool_calls)

    def _cost(self, decision, run):
        """Costo de la pregunta: supervisor (modelo pequeño) más especialista.

        :param decision: Decisión del supervisor con sus llamadas
        :type decision: app.supervisor.Decision
        :param run: Corrida del especialista con el modelo que contestó
        :type run: SpecialistRun
        :return: Costo en USD
        :rtype: float
        """
        prices = self._deps.prices
        total = prices.cost(
            self._deps.settings.model_small, decision.completions
        ) + prices.cost(run.model, run.result.completions)
        return round(total, COST_DECIMALS)

    def _guard(self, request_id, client, question, history):
        """Guardián de entrada.

        Bloquea prompt injection con ``InputBlocked`` antes de llamar a
        cualquier modelo y redacta la PII de la pregunta y del historial. El
        ``audit`` lleva solo motivo, tipos y conteo: nunca el texto.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param question: Pregunta original
        :type question: str
        :param history: Historial original
        :type history: list[dict]
        :return: Entrada revisada
        :rtype: GuardedInput
        :raises app.guard.InputBlocked: Si hay prompt injection
        """
        deps = self._deps
        try:
            result = inspect(question, history)
        except InputBlocked as blocked:
            deps.logger.emit(
                "audit",
                request_id,
                client=client,
                action="input_blocked",
                reason=blocked.reason,
            )
            deps.metrics.add_security(BLOCKED_INPUTS)
            raise
        self._audit_pii(request_id, client, LOCATION_INPUT, result)
        return GuardedInput(
            question=result.question,
            history=result.history,
            pii_types=tuple(result.types),
        )

    def _audit_pii(self, request_id, client, location, redaction):
        """Escribe el ``audit`` de PII y suma el contador, si hubo PII.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param location: ``input`` u ``output``
        :type location: str
        :param redaction: Resultado con ``types`` y ``count``
        :type redaction: app.guard.GuardResult or app.reviewer.Review
        """
        if not redaction.count:
            return
        self._deps.logger.emit(
            "audit",
            request_id,
            client=client,
            action="pii_redacted",
            location=location,
            types=list(redaction.types),
            count=redaction.count,
        )
        self._deps.metrics.add_security(PII_REDACTIONS, redaction.count)

    def _cache_key(self, guarded):
        """Llave de la caché si la pregunta puede usarla.

        Aplica solo con la caché encendida, sin historial y sin PII en la
        entrada.

        :param guarded: Entrada ya revisada por el guardián
        :type guarded: GuardedInput
        :return: Pregunta normalizada o ``None`` si no aplica la caché
        :rtype: str or None
        """
        if self._deps.answer_cache is None:
            return None
        if guarded.history or guarded.pii_types:
            return None
        return normalize_question(guarded.question)

    def _cache_lookup(self, guarded):
        """Busca la respuesta en la caché de respuestas.

        Solo con ``ANSWER_CACHE_TTL_SECONDS > 0``, sin historial y sin PII; un
        acierto devuelve ``agents: ["guard", "cache"]``, costo, pasos y tokens
        en 0 y ``cached: True``. Una consulta sin acierto cuenta como fallo.

        :param guarded: Entrada ya revisada por el guardián
        :type guarded: GuardedInput
        :return: Resultado desde la caché o ``None`` si no hay acierto
        :rtype: AskOutcome or None
        """
        key = self._cache_key(guarded)
        if key is None:
            return None
        entry = self._deps.answer_cache.get(key)
        self._deps.metrics.record_cache(hit=entry is not None)
        if entry is None:
            return None
        return AskOutcome(
            answer=entry.answer,
            steps=0,
            tools_used=[],
            input_tokens=0,
            output_tokens=0,
            model=entry.model,
            route=entry.route,
            cached_calls=0,
            cost_usd=0.0,
            specialist=entry.specialist,
            agents=[AGENT_GUARD, AGENT_CACHE],
            supervisor_route=entry.supervisor_route,
            cached=True,
        )

    def _cache_store(self, guarded, outcome):
        """Guarda una respuesta candidata en la caché de respuestas.

        Solo respuestas con ``stopped == "answer"``, sin bloqueo del revisor y
        sin respaldo.

        :param guarded: Entrada ya revisada por el guardián
        :type guarded: GuardedInput
        :param outcome: Resultado recién calculado
        :type outcome: AskOutcome
        """
        key = self._cache_key(guarded)
        if key is None:
            return
        if (
            outcome.stopped != STOPPED_ANSWER
            or outcome.output_blocked
            or outcome.fallback
        ):
            return
        self._deps.answer_cache.put(
            key,
            CachedAnswer(
                answer=outcome.answer,
                specialist=outcome.specialist,
                supervisor_route=outcome.supervisor_route,
                model=outcome.model,
                route=outcome.route,
            ),
        )

    def _run_specialist(self, agent, messages, model_name):
        """Corre el especialista con el modelo elegido por el enrutador.

        Si el modelo sigue caído (después de los reintentos del gateway) y
        ``MODEL_FALLBACK=true``, lo repite una vez con el otro modelo y marca
        ``fallback=True``.

        :param agent: Especialista elegido
        :type agent: app.agent.Agent
        :param messages: Historial recortado y pregunta, ya redactados
        :type messages: list[dict]
        :param model_name: Modelo que eligió el enrutador de costo
        :type model_name: str
        :return: Resultado del especialista y modelo que contestó
        :rtype: SpecialistRun
        :raises app.gateway.ModelUnavailable: Si ningún modelo contesta
        """
        models = self._deps.models

        def run(name):
            if name not in models:
                raise ModelUnavailable("the model is not configured")
            return agent.run(messages, model=models[name])

        attempt = run_with_fallback(run, model_name, self._deps.settings)
        if attempt.fallback:
            self._deps.metrics.add_fallback()
        return SpecialistRun(
            result=attempt.value, model=attempt.model, fallback=attempt.fallback
        )

    # pylint: disable-next=too-many-arguments,too-many-positional-arguments
    def _review(self, request_id, client, answer, question="", policy_texts=None):
        """Revisor de salida.

        Redacta la PII de la respuesta, reemplaza las que citan ids
        ``EMP-dddd`` inexistentes que la persona no escribió en su pregunta
        (ids inventados), ancla las cifras de ``policy`` a los textos
        consultados y recorta a ``MAX_ANSWER_CHARS``. El ``audit`` lleva solo
        tipos, conteo y motivo: nunca la respuesta.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param answer: Respuesta del especialista
        :type answer: str
        :param question: Pregunta ya redactada por el guardián
        :type question: str
        :param policy_texts: Textos de las políticas consultadas; ``None`` si
            el especialista no es ``policy``
        :type policy_texts: tuple[str, ...] or None
        :return: Respuesta revisada
        :rtype: ReviewedAnswer
        """
        deps = self._deps
        result = review(
            answer,
            deps.directory,
            deps.settings.max_answer_chars,
            question=question,
            policy_texts=policy_texts,
        )
        self._audit_pii(request_id, client, LOCATION_OUTPUT, result)
        if result.blocked:
            deps.logger.emit(
                "audit",
                request_id,
                client=client,
                action="output_blocked",
                reason=self._block_reason(answer, question, policy_texts),
            )
            deps.metrics.add_security(OUTPUT_BLOCKED)
        return ReviewedAnswer(
            answer=result.answer,
            pii_types=tuple(result.types),
            blocked=result.blocked,
        )

    def _block_reason(self, answer, question, policy_texts):
        """Motivo del bloqueo del revisor, para el ``audit``.

        El revisor revisa primero los ids inventados; si no los hay y la
        respuesta es de ``policy``, el bloqueo fue por una cifra que no está en
        las políticas consultadas.

        :param answer: Respuesta del especialista
        :type answer: str
        :param question: Pregunta ya redactada por el guardián
        :type question: str
        :param policy_texts: Textos de las políticas consultadas o ``None``
        :type policy_texts: tuple[str, ...] or None
        :return: ``unknown_employee_id`` o ``ungrounded_policy_number``
        :rtype: str
        """
        if policy_texts is None or mentions_unknown_employee(
            redact(answer).text, self._deps.directory, employee_ids(question)
        ):
            return REVIEW_BLOCK_REASON
        return POLICY_BLOCK_REASON

    def _record(self, request_id, client, payload, outcome):
        """Escribe ``audit`` por herramienta y ``agent_run``; suma métricas.

        Solo conteos, tipos, modelo y costo: nunca el texto de la pregunta ni
        de la respuesta. Se llama solo con respuestas ``200`` (también las de
        caché): suma tokens, costo, peticiones y costo por especialista y por
        cliente, y quién decidió el especialista (``rule`` o ``model``). La
        caché y el respaldo ya se cuentan donde ocurren (``_cache_lookup`` y
        ``_run_specialist``).

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente que pregunta
        :type client: str
        :param payload: Cuerpo de ``POST /ask``
        :type payload: pydantic.BaseModel
        :param outcome: Resultado de la pregunta
        :type outcome: AskOutcome
        """
        deps = self._deps
        for call in outcome.tool_calls:
            deps.logger.emit(
                "audit",
                request_id,
                client=client,
                action="tool_call",
                tool=call["tool"],
                args=_audit_args(call["args"]),
            )
        deps.logger.emit(
            "agent_run",
            request_id,
            question_chars=len(payload.question),
            history_messages=len(payload.history),
            steps=outcome.steps,
            tools=list(outcome.tools_used),
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            stopped=outcome.stopped,
            client=client,
            model=outcome.model,
            route=outcome.route,
            history_sent=outcome.history_sent,
            cached_calls=outcome.cached_calls,
            cost_usd=outcome.cost_usd,
            specialist=outcome.specialist,
            agents=list(outcome.agents),
            supervisor_route=outcome.supervisor_route,
            pii_types=list(outcome.pii_redacted),
            cached=outcome.cached,
            fallback=outcome.fallback,
        )
        deps.metrics.record_answer(client, outcome, _supervisor_kind(outcome))
