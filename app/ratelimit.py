"""Límite de peticiones por cliente con ventana deslizante y reloj inyectado.

Solo se cuentan las peticiones aceptadas. La memoria es por proceso y queda
acotada: por cliente se guardan como mucho ``limit`` marcas de tiempo.
"""

import math
import threading
from collections import deque
from dataclasses import dataclass

DEFAULT_WINDOW_SECONDS = 60
MIN_RETRY_AFTER_SECONDS = 1


@dataclass(frozen=True)
class Decision:
    """Resultado de revisar una petición contra el límite.

    :param allowed: ``True`` si la petición puede seguir
    :type allowed: bool
    :param retry_after: Segundos enteros que faltan para poder preguntar (0 si
        se acepta)
    :type retry_after: int
    """

    allowed: bool
    retry_after: int = 0


class RateLimiter:
    """Ventana deslizante por cliente.

    :param limit: Peticiones aceptadas por cliente dentro de la ventana
    :type limit: int
    :param clock: Reloj inyectado; se usa ``clock.monotonic()``
    :type clock: app.clock.Clock
    :param window: Largo de la ventana en segundos
    :type window: float
    """

    def __init__(self, limit, clock, window=DEFAULT_WINDOW_SECONDS):
        self._limit = limit
        self._clock = clock
        self._window = window
        self._accepted = {}
        self._lock = threading.Lock()

    def check(self, client):
        """Cuenta la petición si cabe en el límite del cliente.

        :param client: Nombre del cliente
        :type client: str
        :return: Si se acepta y, si no, cuántos segundos faltan
        :rtype: Decision
        """
        with self._lock:
            now = self._clock.monotonic()
            accepted = self._accepted.setdefault(client, deque())
            while accepted and accepted[0] + self._window <= now:
                accepted.popleft()
            if len(accepted) < self._limit:
                accepted.append(now)
                return Decision(allowed=True)
            wait = math.ceil(accepted[0] + self._window - now)
            return Decision(
                allowed=False, retry_after=max(MIN_RETRY_AFTER_SECONDS, wait)
            )
