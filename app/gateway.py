"""Modelo real: Cloudflare Workers AI a través de AI Gateway.

El cliente HTTP se inyecta para que las pruebas usen ``httpx.MockTransport`` y
nunca llamen a la red. Ningún error lleva la URL, el cuerpo ni el token: la URL
contiene el id de la cuenta y el encabezado lleva el token.
"""

import json
import re

import httpx

from app.completion import Completion

GATEWAY_URL = (
    "https://gateway.ai.cloudflare.com/v1/{account}/{gateway}"
    "/workers-ai/v1/chat/completions"
)
GATEWAY_TIMEOUT_SECONDS = 30
CACHE_TTL_HEADER = "cf-aig-cache-ttl"
CACHE_STATUS_HEADER = "cf-aig-cache-status"
CACHE_HIT = "HIT"
CODE_FENCE_PATTERN = re.compile(r"^```[A-Za-z]*\s*(.*?)\s*```$", re.DOTALL)
SYSTEM_PROMPT = (
    "Eres el asistente de Recursos Humanos. Responde siempre con un solo objeto "
    "JSON y nada más. Para consultar el directorio pide una herramienta: "
    '{"tool": "get_employee", "args": {"employee_id": "EMP-0004"}} o '
    '{"tool": "search_by_department", "args": {"department": "Finanzas"}}. '
    "El resultado llega en un mensaje que empieza con "
    '"Resultado de la herramienta: ". Cuando tengas la respuesta, contesta '
    '{"answer": "<respuesta breve en español>"}. No inventes datos: usa solo lo '
    "que devuelven las herramientas."
)


class ModelUnavailable(RuntimeError):
    """El gateway no respondió o su respuesta no se pudo usar."""


def _as_json_text(content):
    """Convierte el texto del modelo en un objeto JSON para el agente.

    Quita las cercas de código; si el texto no es un objeto JSON se toma como
    respuesta final para no gastar vueltas del agente.

    :param content: Texto devuelto por el modelo
    :type content: str
    :return: Objeto JSON en texto
    :rtype: str
    """
    text = content.strip()
    match = CODE_FENCE_PATTERN.match(text)
    if match:
        text = match.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps({"answer": content.strip()}, ensure_ascii=False)


def _read_body(data):
    """Extrae el texto y los tokens de una respuesta de chat completions.

    :param data: Cuerpo JSON de la respuesta
    :type data: dict
    :return: Texto, tokens de entrada y tokens de salida
    :rtype: tuple[str, int, int]
    :raises KeyError: Si falta una llave
    :raises TypeError: Si el texto no es una cadena o el formato no es el esperado
    :raises ValueError: Si los tokens no son números
    """
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise TypeError("the model content is not text")
    usage = data["usage"]
    return content, int(usage["prompt_tokens"]), int(usage["completion_tokens"])


class GatewayModel:  # pylint: disable=too-few-public-methods
    """Modelo de Workers AI detrás de AI Gateway.

    :param name: Nombre del modelo en Workers AI
    :type name: str
    :param settings: Configuración con cuenta, gateway, token y palancas
    :type settings: app.config.Settings
    :param http_client: Cliente HTTP; si falta se crea uno con tiempo de espera
    :type http_client: httpx.Client or None
    """

    def __init__(self, name, settings, http_client=None):
        self.name = name
        self._settings = settings
        self._client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=GATEWAY_TIMEOUT_SECONDS)
        )
        self._url = GATEWAY_URL.format(
            account=settings.cf_account_id, gateway=settings.cf_gateway_id
        )

    def _headers(self):
        """Arma los encabezados: token y, si aplica, la vida de la caché.

        :return: Encabezados de la petición
        :rtype: dict
        """
        headers = {"Authorization": f"Bearer {self._settings.cf_api_token}"}
        if self._settings.cache_ttl_seconds > 0:
            headers[CACHE_TTL_HEADER] = str(self._settings.cache_ttl_seconds)
        return headers

    def _body(self, messages):
        """Arma el cuerpo con el prompt de sistema primero.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Cuerpo de la petición
        :rtype: dict
        """
        conversation = [{"role": "system", "content": SYSTEM_PROMPT}]
        conversation.extend(
            {"role": message["role"], "content": message["content"]}
            for message in messages
        )
        return {
            "model": self.name,
            "messages": conversation,
            "max_tokens": self._settings.model_max_tokens,
            "temperature": self._settings.model_temperature,
        }

    def complete(self, messages):
        """Pide la siguiente respuesta al gateway.

        :param messages: Mensajes con ``role`` y ``content``
        :type messages: Sequence[dict]
        :return: Respuesta con tokens reales y si vino de la caché
        :rtype: app.completion.Completion
        :raises ModelUnavailable: Ante error de red, estado no 2xx o respuesta
            sin el formato esperado
        """
        try:
            response = self._client.post(
                self._url,
                json=self._body(messages),
                headers=self._headers(),
                timeout=GATEWAY_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content, input_tokens, output_tokens = _read_body(response.json())
        except httpx.HTTPError:
            # Sin el error original: su texto puede traer la URL con la cuenta.
            raise ModelUnavailable("the model gateway request failed") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelUnavailable(
                "the model gateway returned an invalid response"
            ) from None
        cached = response.headers.get(CACHE_STATUS_HEADER) == CACHE_HIT
        return Completion(
            text=_as_json_text(content),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=cached,
        )
