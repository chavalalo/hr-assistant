"""Pruebas de ``app.gateway``: la llamada a AI Gateway, sin red."""

import json

import httpx
import pytest

from app.config import Settings
from app.gateway import SYSTEM_PROMPT, GatewayModel, ModelUnavailable

MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
URL = (
    "https://gateway.ai.cloudflare.com/v1/acc-123/hr-gw"
    "/workers-ai/v1/chat/completions"
)
QUESTION = [{"role": "user", "content": "¿Quién es EMP-0004?"}]


def reply(content, headers=None, status=200, usage=True):
    """Respuesta del gateway con el formato de chat completions.

    :param content: Texto que devuelve el modelo
    :type content: str
    :param headers: Encabezados de la respuesta
    :type headers: dict or None
    :param status: Código HTTP
    :type status: int
    :param usage: Si la respuesta trae el conteo de tokens
    :type usage: bool
    :return: Respuesta HTTP simulada
    :rtype: httpx.Response
    """
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage:
        body["usage"] = {"prompt_tokens": 12, "completion_tokens": 5}
    return httpx.Response(status, json=body, headers=headers or {})


def gateway(environ, handler):
    """Modelo de gateway cuyo cliente HTTP responde con ``handler``."""
    settings = Settings.from_env(environ)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel(MODEL, settings, client)


def test_request_has_the_url_token_body_and_system_prompt(gateway_environ):
    sent = []

    def handler(request):
        sent.append(request)
        return reply('{"answer": "Es Jorge."}')

    environ = dict(gateway_environ, MODEL_MAX_TOKENS="120")
    completion = gateway(environ, handler).complete(QUESTION)

    request = sent[0]
    body = json.loads(request.content)
    assert str(request.url) == URL
    assert request.headers["authorization"] == "Bearer tok-secret"
    assert "cf-aig-cache-ttl" not in request.headers
    assert set(body) == {"model", "messages", "max_tokens", "temperature"}
    assert body["model"] == MODEL
    assert body["max_tokens"] == 120
    assert body["temperature"] == 0
    system = {"role": "system", "content": SYSTEM_PROMPT}
    assert body["messages"] == [system] + QUESTION
    assert json.loads(completion.text) == {"answer": "Es Jorge."}
    assert (completion.input_tokens, completion.output_tokens) == (12, 5)
    assert completion.cached is False


def test_cache_ttl_is_sent_and_a_hit_marks_the_call_as_cached(gateway_environ):
    sent = []

    def handler(request):
        sent.append(request)
        return reply('{"answer": "Es Jorge."}', {"cf-aig-cache-status": "HIT"})

    environ = dict(gateway_environ, CACHE_TTL_SECONDS="300")
    completion = gateway(environ, handler).complete(QUESTION)

    assert sent[0].headers["cf-aig-cache-ttl"] == "300"
    assert completion.cached is True
    assert (completion.input_tokens, completion.output_tokens) == (12, 5)


def test_every_gateway_failure_raises_model_unavailable(gateway_environ):
    def timeout(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    failures = {
        "server error": lambda request: reply("{}", status=500),
        "timeout": timeout,
        "invalid json": lambda request: httpx.Response(200, text="<html>oops"),
        "missing usage": lambda request: reply('{"answer": "x"}', usage=False),
    }

    for name, handler in failures.items():
        with pytest.raises(ModelUnavailable) as error:
            gateway(gateway_environ, handler).complete(QUESTION)
        assert "tok-secret" not in str(error.value), name


def test_code_fences_and_free_text_become_a_json_answer(gateway_environ):
    fenced = gateway(
        gateway_environ, lambda request: reply('```json\n{"answer": "Hola"}\n```')
    ).complete(QUESTION)
    free_text = gateway(
        gateway_environ, lambda request: reply("Hola, soy el asistente.")
    ).complete(QUESTION)

    assert json.loads(fenced.text) == {"answer": "Hola"}
    assert json.loads(free_text.text) == {"answer": "Hola, soy el asistente."}
