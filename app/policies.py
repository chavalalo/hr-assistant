"""Políticas de Recursos Humanos de solo lectura y la herramienta ``search_policy``.

Las políticas vienen de ``data/policies.json`` (copia de ``spec/policies.json``).
Las palabras clave se comparan sin acentos ni mayúsculas y con límite de
palabra, para que «remoto» no coincida dentro de otra palabra.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.directory import normalize

TOPICS_PREFIX = "Temas disponibles: "
TOPICS_SEPARATOR = ", "
SEARCH_POLICY_TOOL = "search_policy"


def phrase_pattern(phrase):
    """Compila una frase normalizada como patrón con límite de palabra.

    Las palabras se separan con ``\\s+`` para aceptar varios espacios.

    :param phrase: Frase original, con o sin acentos
    :type phrase: str
    :return: Patrón que busca la frase en un texto ya normalizado
    :rtype: re.Pattern
    """
    words = normalize(phrase).split()
    return re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"\b")


@dataclass(frozen=True)
class Policy:
    """Una política con su tema, sus palabras clave y su texto.

    :param topic: Tema, por ejemplo ``vacaciones``
    :type topic: str
    :param keywords: Palabras clave que la identifican
    :type keywords: tuple[str, ...]
    :param text: Texto de la política
    :type text: str
    """

    topic: str
    keywords: tuple
    text: str


def _parse_policy(position, raw):
    """Valida una entrada del archivo de políticas.

    :param position: Posición de la entrada, desde 1
    :type position: int
    :param raw: Objeto con ``topic``, ``keywords`` y ``text``
    :type raw: dict
    :return: Política validada
    :rtype: Policy
    :raises ValueError: Si falta un campo o no tiene el tipo esperado
    """
    if not isinstance(raw, dict):
        raise ValueError(f"policy {position} is not an object")
    topic, keywords, text = raw.get("topic"), raw.get("keywords"), raw.get("text")
    valid = (
        isinstance(topic, str)
        and topic.strip()
        and isinstance(text, str)
        and text.strip()
        and isinstance(keywords, list)
        and all(isinstance(keyword, str) and keyword.strip() for keyword in keywords)
    )
    if not valid:
        raise ValueError(f"policy {position} must have topic, keywords and text")
    return Policy(topic=topic.strip(), keywords=tuple(keywords), text=text)


class PolicyBook:
    """Libro de políticas cargado una sola vez.

    :param policies: Políticas en el orden del archivo
    :type policies: Sequence[Policy]
    :raises ValueError: Si no hay ninguna política
    """

    def __init__(self, policies):
        self._policies = tuple(policies)
        if not self._policies:
            raise ValueError("the policies file has no policies")
        self._patterns = tuple(
            (pattern, policy)
            for policy in self._policies
            for pattern in map(phrase_pattern, (policy.topic,) + policy.keywords)
        )

    @classmethod
    def load(cls, path):
        """Lee las políticas de un archivo JSON.

        :param path: Ruta al archivo ``policies.json``
        :type path: str or pathlib.Path
        :return: Libro de políticas
        :rtype: PolicyBook
        :raises OSError: Si el archivo no se puede leer
        :raises ValueError: Si el archivo no tiene el formato esperado
        """
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            raise ValueError("the policies file must be a list")
        return cls(
            _parse_policy(position, raw) for position, raw in enumerate(data, 1)
        )

    def topics(self):
        """Devuelve los temas en el orden del archivo.

        :return: Temas disponibles
        :rtype: list[str]
        """
        return [policy.topic for policy in self._policies]

    def count(self):
        """Cuenta las políticas cargadas (lo usa ``GET /ready``).

        :return: Número de políticas
        :rtype: int
        """
        return len(self._policies)

    def keywords(self):
        """Relaciona cada palabra clave (y cada tema) con su tema.

        :return: Tema por palabra clave, en el orden del archivo
        :rtype: dict[str, str]
        """
        found = {}
        for policy in self._policies:
            for keyword in (policy.topic,) + policy.keywords:
                found.setdefault(keyword, policy.topic)
        return found

    def find_topic(self, text):
        """Busca en un texto la primera palabra clave de una política.

        :param text: Texto donde buscar, por ejemplo la pregunta
        :type text: str
        :return: Tema de la política o ``None`` si ninguna aplica
        :rtype: str or None
        """
        folded = normalize(str(text))
        for pattern, policy in self._patterns:
            if pattern.search(folded):
                return policy.topic
        return None

    def search_policy(self, topic):
        """Herramienta del especialista ``policy``: el texto de un tema.

        Acepta el tema exacto o un texto con una palabra clave, sin importar
        acentos ni mayúsculas.

        :param topic: Tema pedido, por ejemplo ``vacaciones``
        :type topic: str
        :return: Texto de la política o la lista de temas disponibles
        :rtype: str
        """
        wanted = normalize(str(topic))
        for policy in self._policies:
            if normalize(policy.topic) == wanted:
                return policy.text
        found = self.find_topic(topic)
        for policy in self._policies:
            if policy.topic == found:
                return policy.text
        return TOPICS_PREFIX + TOPICS_SEPARATOR.join(self.topics())

    def consulted_texts(self, tool_calls):
        """Textos que devolvió ``search_policy`` en las llamadas de una petición.

        ``search_policy`` es pura: repetir la llamada con los mismos argumentos
        devuelve el mismo texto que recibió el modelo. Las demás herramientas
        se ignoran.

        :param tool_calls: Herramientas ejecutadas con sus argumentos
        :type tool_calls: Iterable[dict]
        :return: Textos consultados, en orden y sin repetir
        :rtype: tuple[str, ...]
        """
        texts = []
        for call in tool_calls:
            if call.get("tool") != SEARCH_POLICY_TOOL:
                continue
            text = self.search_policy(**call.get("args", {}))
            if text not in texts:
                texts.append(text)
        return tuple(texts)
