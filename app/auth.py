"""Claves por cliente: lectura de ``API_KEYS`` e identificación del cliente.

``API_KEYS`` tiene la forma ``cliente:clave,cliente2:clave2``. Ningún mensaje
de error, ``repr`` ni línea de log muestra una clave: solo la posición de la
entrada y su largo.
"""

import hmac
import re
from dataclasses import dataclass, field

from app.errors import ConfigError

ENTRY_SEPARATOR = ","
NAME_SEPARATOR = ":"
CLIENT_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


@dataclass(frozen=True)
class ApiClient:
    """Cliente autorizado a usar la API.

    :param name: Nombre del cliente; va en el log y en la traza
    :type name: str
    :param key: Clave del cliente (secreto: no sale en ``repr``)
    :type key: str
    """

    name: str
    key: str = field(repr=False)


def _malformed(position, entry):
    """Arma el error de una entrada inválida sin mostrar su valor.

    :param position: Posición de la entrada, desde 1
    :type position: int
    :param entry: Entrada tal como llegó
    :type entry: str
    :return: Error con la posición y el largo de la entrada
    :rtype: ConfigError
    """
    return ConfigError(
        f"API_KEYS entry {position} is malformed (length {len(entry)})"
    )


def _parse_entry(position, entry):
    """Convierte una entrada ``cliente:clave`` en un ``ApiClient``.

    :param position: Posición de la entrada, desde 1
    :type position: int
    :param entry: Entrada sin espacios a los lados
    :type entry: str
    :return: Cliente leído
    :rtype: ApiClient
    :raises ConfigError: Si falta ``:``, el cliente o la clave, o el nombre
        tiene caracteres no permitidos
    """
    name, separator, key = entry.partition(NAME_SEPARATOR)
    name, key = name.strip(), key.strip()
    valid = separator and key and CLIENT_NAME_PATTERN.fullmatch(name)
    if not valid:
        raise _malformed(position, entry)
    return ApiClient(name=name, key=key)


def parse_api_keys(raw):
    """Lee ``API_KEYS`` y valida cada entrada.

    Vacía o solo con espacios significa que no hay clientes.

    :param raw: Valor de ``API_KEYS``
    :type raw: str or None
    :return: Clientes en el orden en que llegaron
    :rtype: tuple[ApiClient, ...]
    :raises ConfigError: Si una entrada es inválida o hay clientes o claves
        repetidos; el mensaje dice la posición y el largo, nunca el valor
    """
    text = str(raw or "").strip()
    if not text:
        return ()
    clients = []
    names, keys = set(), set()
    for position, entry in enumerate(text.split(ENTRY_SEPARATOR), start=1):
        entry = entry.strip()
        client = _parse_entry(position, entry)
        if client.name in names or client.key in keys:
            raise ConfigError(
                f"API_KEYS entry {position} repeats a client or a key "
                f"(length {len(entry)})"
            )
        names.add(client.name)
        keys.add(client.key)
        clients.append(client)
    return tuple(clients)


def identify_client(header_value, clients):
    """Busca el cliente dueño de la clave recibida.

    Compara con ``hmac.compare_digest`` contra todas las claves, sin salir
    antes, para que el tiempo no dependa de cuál coincide.

    :param header_value: Valor del encabezado ``X-API-Key`` o ``None``
    :type header_value: str or None
    :param clients: Clientes autorizados
    :type clients: tuple[ApiClient, ...]
    :return: Nombre del cliente o ``None`` si la clave falta o no coincide
    :rtype: str or None
    """
    if not header_value:
        return None
    received = header_value.encode("utf-8")
    found = None
    for client in clients:
        if hmac.compare_digest(received, client.key.encode("utf-8")):
            found = client.name
    return found


def can_read_metrics(client, metrics_clients):
    """Decide si un cliente ya identificado puede leer ``GET /metrics``.

    Compara nombres de cliente, no claves: la clave ya se revisó antes.

    :param client: Nombre del cliente
    :type client: str
    :param metrics_clients: Clientes de ``METRICS_CLIENTS``; vacía: todos
    :type metrics_clients: tuple[str, ...]
    :return: ``True`` si puede leer las métricas
    :rtype: bool
    """
    if not metrics_clients:
        return True
    return client in metrics_clients
