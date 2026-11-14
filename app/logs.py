"""Log estructurado: una línea JSON por evento en la salida estándar."""

import json
import sys
import threading
from datetime import timezone


def format_timestamp(moment):
    """Da formato ISO 8601 en UTC con milisegundos y sufijo ``Z``.

    :param moment: Fecha y hora con zona
    :type moment: datetime.datetime
    :return: Texto como ``2026-01-15T10:30:00.250Z``
    :rtype: str
    """
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond // 1000:03d}Z"


class JsonLogger:
    """Escribe eventos como líneas JSON con ``ts``, ``service``, ``event`` e id.

    :param service: Nombre del servicio, campo ``service`` de cada línea
    :type service: str
    :param clock: Reloj inyectado para el campo ``ts``
    :type clock: app.clock.Clock
    :param stream: Destino del log; si falta se usa ``sys.stdout``
    :type stream: typing.TextIO or None
    """

    def __init__(self, service, clock, stream=None):
        self._service = service
        self._clock = clock
        self._stream = stream
        self._lock = threading.Lock()

    def emit(self, event, request_id, **fields):
        """Escribe un evento en una sola línea.

        :param event: Nombre del evento (``request``, ``agent_run``, ...)
        :type event: str
        :param request_id: Id de la petición
        :type request_id: str
        :param fields: Campos propios del evento
        :type fields: dict
        """
        record = {
            "ts": format_timestamp(self._clock.now()),
            "service": self._service,
            "event": event,
            "request_id": request_id,
        }
        record.update(fields)
        line = json.dumps(record, ensure_ascii=False, default=str)
        stream = self._stream if self._stream is not None else sys.stdout
        with self._lock:
            stream.write(line + "\n")
            stream.flush()
