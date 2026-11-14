"""Trazas opcionales en LangSmith detrás de una interfaz mínima.

Sin trazas se usa ``NoopTracer``, que no importa ``langsmith`` ni abre
conexiones. La clave ``LANGSMITH_API_KEY`` la lee ``langsmith`` del entorno;
este módulo nunca la toca.
"""

import contextlib


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
    def context(self, request_id, client=None):  # pylint: disable=unused-argument
        """Contexto vacío para una petición.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente (nunca su clave)
        :type client: str or None
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
    def context(self, request_id, client=None):
        """Pone el ``request_id`` y el cliente en los metadatos de las trazas.

        :param request_id: Id de la petición
        :type request_id: str
        :param client: Nombre del cliente (nunca su clave)
        :type client: str or None
        :return: Generador del contexto
        :rtype: typing.Iterator[str]
        """
        with self._langsmith.tracing_context(
            metadata={"request_id": request_id, "client": client},
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
