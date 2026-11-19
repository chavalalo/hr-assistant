"""Trazas opcionales en LangSmith detrás de una interfaz mínima.

Sin trazas se usa ``NoopTracer``, que no importa ``langsmith`` ni abre
conexiones. La clave ``LANGSMITH_API_KEY`` la lee ``langsmith`` del entorno;
este módulo nunca la toca.

Una petición de ``POST /ask`` deja un run raíz ``request`` y, dentro, un run
por agente: ``agent.guard``, ``agent.supervisor``, ``agent.directory`` o
``agent.policy`` y ``agent.reviewer``. ``run_traced`` arma esos runs sin
entradas: la función trazada no recibe argumentos y su salida es un resumen
(tipos, conteos y decisiones), así el texto de la persona nunca llega a la
traza por el run raíz ni por el guardián.
"""

import contextlib

TRACE_REQUEST = "request"
TRACE_AGENT_PREFIX = "agent."
CHAIN_RUN_TYPE = "chain"


def trace_metadata(request_id, client=None, specialist=None):
    """Arma los metadatos de una traza.

    ``specialist`` solo aparece cuando ya se conoce (después del supervisor).

    :param request_id: Id de la petición
    :type request_id: str
    :param client: Nombre del cliente (nunca su clave)
    :type client: str or None
    :param specialist: Especialista elegido, si ya se eligió
    :type specialist: str or None
    :return: Metadatos ``request_id``, ``client`` y, si hay, ``specialist``
    :rtype: dict
    """
    metadata = {"request_id": request_id, "client": client}
    if specialist is not None:
        metadata["specialist"] = specialist
    return metadata


def agent_trace_name(agent):
    """Nombre de la traza de un agente.

    :param agent: Nombre del agente (``guard``, ``supervisor``...)
    :type agent: str
    :return: ``agent.<nombre>``
    :rtype: str
    """
    return TRACE_AGENT_PREFIX + agent


def run_traced(tracer, name, action, summarize=None):
    """Corre ``action`` como un run propio, sin entradas y con salida resumida.

    La función que se traza no recibe argumentos (la traza no tiene entradas)
    y devuelve ``summarize(valor)``; quien llama recibe el valor completo. Los
    errores siguen su camino sin cambios.

    :param tracer: Tracer con el método ``wrap(fn, name, run_type)``
    :type tracer: NoopTracer or LangSmithTracer
    :param name: Nombre del run, por ejemplo ``agent.guard``
    :type name: str
    :param action: Función sin argumentos que hace el trabajo
    :type action: callable
    :param summarize: Convierte el valor en la salida de la traza (solo
        tipos, conteos y decisiones); si falta, la salida es vacía
    :type summarize: callable or None
    :return: Lo que devuelve ``action``
    :rtype: object
    """
    holder = {}

    def traced_body():
        holder["value"] = action()
        return summarize(holder["value"]) if summarize is not None else {}

    tracer.wrap(traced_body, name, CHAIN_RUN_TYPE)()
    return holder["value"]


class NoopTracer:
    """Tracer que no hace nada: deja las funciones como están."""

    def wrap(self, fn, name, run_type):  # pylint: disable=unused-argument
        """Devuelve la misma función, sin envolver.

        :param fn: Función a trazar
        :type fn: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de corrida (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :return: La misma función
        :rtype: callable
        """
        return fn

    @contextlib.contextmanager
    # pylint: disable-next=unused-argument
    def context(self, request_id, client=None, specialist=None):
        """Contexto vacío para una petición.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente (nunca su clave)
        :type client: str or None
        :param specialist: Especialista elegido, si ya se eligió
        :type specialist: str or None
        :return: Generador del contexto
        :rtype: typing.Iterator[str]
        """
        yield request_id


class LangSmithTracer:
    """Tracer que manda las corridas a LangSmith con ``@traceable``.

    :param hide_inputs: Si es ``True`` no se mandan las entradas
    :type hide_inputs: bool
    :param hide_outputs: Si es ``True`` no se mandan las salidas
    :type hide_outputs: bool
    """

    def __init__(self, hide_inputs, hide_outputs):
        # Import local: solo se carga langsmith cuando las trazas están encendidas.
        import langsmith  # pylint: disable=import-outside-toplevel

        self._langsmith = langsmith
        self._client = langsmith.Client(
            hide_inputs=hide_inputs, hide_outputs=hide_outputs
        )

    def wrap(self, fn, name, run_type):
        """Envuelve una función como traza de LangSmith.

        :param fn: Función a trazar
        :type fn: callable
        :param name: Nombre de la traza
        :type name: str
        :param run_type: Tipo de corrida (``chain``, ``llm`` o ``tool``)
        :type run_type: str
        :return: La función envuelta
        :rtype: callable
        """
        decorator = self._langsmith.traceable(
            name=name, run_type=run_type, client=self._client
        )
        return decorator(fn)

    @contextlib.contextmanager
    def context(self, request_id, client=None, specialist=None):
        """Pone ``request_id``, cliente y especialista en los metadatos.

        Se puede anidar: el contexto interno (con ``specialist``) conserva el
        run padre, así los runs de los agentes quedan dentro de ``request``.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente (nunca su clave)
        :type client: str or None
        :param specialist: Especialista elegido, si ya se eligió
        :type specialist: str or None
        :return: Generador del contexto
        :rtype: typing.Iterator[str]
        """
        with self._langsmith.tracing_context(
            metadata=trace_metadata(request_id, client, specialist),
            enabled=True,
            client=self._client,
        ):
            yield request_id


def build_tracer(settings):
    """Elige el tracer según la configuración.

    :param settings: Configuración de la aplicación
    :type settings: app.config.Settings
    :return: ``LangSmithTracer`` si las trazas están encendidas; si no, ``NoopTracer``
    :rtype: NoopTracer or LangSmithTracer
    """
    if not settings.tracing_enabled:
        return NoopTracer()
    return LangSmithTracer(
        hide_inputs=settings.hide_inputs, hide_outputs=settings.hide_outputs
    )
