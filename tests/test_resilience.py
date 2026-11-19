"""Pruebas de ``app.resilience`` y del gateway: reintentos y token, sin red."""

import httpx
import pytest

from app.config import Settings
from app.gateway import GatewayModel, ModelUnavailable
from app.resilience import RetryingModel

MODEL = "@cf/meta/llama-3.1-8b-instruct-fast"
QUESTION = [{"role": "user", "content": "¿Quién es EMP-0004?"}]
AIG_TOKEN = "aig-secret-value-123"


def scripted_gateway(environ, statuses, sent):
    """Modelo de gateway cuyo cliente responde los códigos dados, en orden.

    :param environ: Variables de entorno del gateway
    :type environ: dict
    :param statuses: Códigos HTTP de cada llamada; el último se repite
    :type statuses: list[int]
    :param sent: Lista donde se guardan las peticiones enviadas
    :type sent: list
    :return: Modelo de gateway sin red
    :rtype: app.gateway.GatewayModel
    """

    def handler(request):
        sent.append(request)
        status = statuses[min(len(sent), len(statuses)) - 1]
        body = {
            "choices": [{"message": {"content": '{"answer": "Es Jorge."}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }
        return httpx.Response(status, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GatewayModel(MODEL, Settings.from_env(environ), client)


def test_retries_wait_longer_each_time_on_429_and_5xx_but_never_on_400(
    gateway_environ,
):
    waits, sent, sent_bad, sent_down = [], [], [], []
    recovers = RetryingModel(
        scripted_gateway(gateway_environ, [429, 503, 200], sent), 2, 0.5, waits.append
    )
    rejected = RetryingModel(
        scripted_gateway(gateway_environ, [400], sent_bad), 2, 0.5, waits.append
    )
    down = RetryingModel(
        scripted_gateway(gateway_environ, [500], sent_down), 2, 0.5, waits.append
    )

    completion = recovers.complete(QUESTION)
    assert waits == [0.5, 1.0]
    assert len(sent) == 3
    assert completion.input_tokens == 12
    with pytest.raises(ModelUnavailable):
        rejected.complete(QUESTION)
    assert len(sent_bad) == 1
    assert waits == [0.5, 1.0]
    with pytest.raises(ModelUnavailable):
        down.complete(QUESTION)
    assert len(sent_down) == 3


def test_aig_token_goes_in_its_header_and_never_in_an_error(gateway_environ):
    environ = dict(gateway_environ, CF_AIG_TOKEN=AIG_TOKEN)
    plain, sent, failed = [], [], []

    scripted_gateway(gateway_environ, [200], plain).complete(QUESTION)
    scripted_gateway(environ, [200], sent).complete(QUESTION)
    with pytest.raises(ModelUnavailable) as error:
        scripted_gateway(environ, [500], failed).complete(QUESTION)

    assert "cf-aig-authorization" not in plain[0].headers
    assert sent[0].headers["cf-aig-authorization"] == f"Bearer {AIG_TOKEN}"
    assert sent[0].headers["authorization"] == "Bearer tok-secret"
    assert AIG_TOKEN not in str(error.value)
    assert AIG_TOKEN not in repr(Settings.from_env(environ))
