"""Caché de respuestas en memoria del proceso, con vida (TTL) y tope.

Se usa solo con preguntas sin historial y sin PII (lo decide el pipeline). La
llave es la pregunta normalizada: minúsculas, sin acentos y con los espacios
colapsados. Cuando se llena sale la entrada más vieja. Un candado protege la
estructura porque FastAPI atiende varias peticiones a la vez.
"""

import threading
from collections import OrderedDict

from app.directory import normalize


def normalize_question(question):
    """Normaliza una pregunta para usarla como llave de la caché.

    Usa ``app.directory.normalize`` (sin acentos y en minúsculas) y además
    colapsa los espacios.

    :param question: Pregunta ya revisada por el guardián
    :type question: str
    :return: Pregunta en minúsculas, sin acentos y con espacios colapsados
    :rtype: str
    """
    return " ".join(normalize(str(question)).split())


class AnswerCache:
    """Caché de respuestas con vida y número máximo de entradas.

    :param ttl_seconds: Segundos que una respuesta sigue vigente
    :type ttl_seconds: float
    :param max_entries: Entradas máximas; al pasarse sale la más vieja
    :type max_entries: int
    :param clock: Reloj con ``monotonic()`` (inyectado para las pruebas)
    :type clock: app.clock.Clock
    :raises ValueError: Si ``max_entries`` no es mayor que cero
    """

    def __init__(self, ttl_seconds, max_entries, clock):
        if max_entries <= 0:
            raise ValueError("max_entries must be greater than 0")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        """Devuelve el valor vigente de una llave.

        Una entrada vencida se borra y cuenta como si no existiera.

        :param key: Llave (pregunta normalizada)
        :type key: str
        :return: Valor guardado o ``None`` si no hay o ya venció
        :rtype: object or None
        """
        now = self._clock.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if now - stored_at >= self._ttl:
                del self._entries[key]
                return None
            return value

    def put(self, key, value):
        """Guarda un valor; si la caché está llena, sale la entrada más vieja.

        :param key: Llave (pregunta normalizada)
        :type key: str
        :param value: Valor a guardar
        :type value: object
        """
        now = self._clock.monotonic()
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = (now, value)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self):
        """Número de entradas guardadas (vigentes o no).

        :return: Entradas en la caché
        :rtype: int
        """
        with self._lock:
            return len(self._entries)
