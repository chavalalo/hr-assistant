"""Reloj inyectable: el único lugar del producto que lee la hora del sistema.

Las pruebas usan ``FixedClock`` para que la hora y las latencias sean
deterministas.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    """Interfaz del reloj que reciben el log y el middleware."""

    def now(self) -> datetime:
        """Devuelve la hora actual en UTC.

        :return: Fecha y hora con zona UTC
        :rtype: datetime.datetime
        """

    def monotonic(self) -> float:
        """Devuelve segundos de un reloj que nunca retrocede.

        :return: Segundos desde un punto arbitrario
        :rtype: float
        """

    def sleep(self, seconds: float) -> None:
        """Espera los segundos dados (la espera entre reintentos del modelo).

        :param seconds: Segundos que espera
        :type seconds: float
        """


class SystemClock:
    """Reloj real basado en la hora del sistema."""

    def now(self):
        """Devuelve la hora actual del sistema en UTC.

        :return: Fecha y hora con zona UTC
        :rtype: datetime.datetime
        """
        return datetime.now(timezone.utc)

    def monotonic(self):
        """Devuelve el reloj monotónico del sistema.

        :return: Segundos desde un punto arbitrario
        :rtype: float
        """
        return time.monotonic()

    def sleep(self, seconds):
        """Duerme el hilo actual.

        :param seconds: Segundos que espera
        :type seconds: float
        """
        time.sleep(seconds)


class FixedClock:
    """Reloj manual para pruebas: solo avanza cuando se le pide.

    :param start: Hora inicial; si no tiene zona se toma como UTC
    :type start: datetime.datetime
    """

    def __init__(self, start):
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        self._start = start.astimezone(timezone.utc)
        self._elapsed = 0.0

    def now(self):
        """Devuelve la hora inicial más el tiempo avanzado.

        :return: Fecha y hora con zona UTC
        :rtype: datetime.datetime
        """
        return self._start + timedelta(seconds=self._elapsed)

    def monotonic(self):
        """Devuelve los segundos avanzados desde que se creó el reloj.

        :return: Segundos avanzados
        :rtype: float
        """
        return self._elapsed

    def advance(self, seconds):
        """Hace avanzar el reloj.

        :param seconds: Segundos que avanza
        :type seconds: float
        """
        self._elapsed += seconds

    def sleep(self, seconds):
        """Simula una espera: solo avanza el reloj, nunca duerme.

        :param seconds: Segundos que avanza
        :type seconds: float
        """
        self.advance(seconds)
