"""Pruebas de ``app.main``: rutas de salud, métricas y página web."""

import os
import uuid

import pytest


def test_health_reports_ok_and_the_process_id(make_client):
    response = make_client().get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "pid": os.getpid()}


def test_home_page_has_the_form_and_never_uses_inner_html(make_client):
    response = make_client().get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    for test_id in ("question", "send", "answer"):
        assert f'data-testid="{test_id}"' in response.text
    assert "innerHTML" not in response.text


def test_metrics_endpoint_has_exactly_the_specified_keys(make_observed_client):
    response = make_observed_client().get("/metrics")

    assert response.status_code == 200
    metrics = response.json()
    assert set(metrics) == {
        "pid", "requests", "error_rate", "latency_ms", "tokens", "slo", "cost_usd"
    }
    assert metrics["cost_usd"] == 0.0
    assert metrics["pid"] == os.getpid()
    assert set(metrics["latency_ms"]) == {"p50", "p95"}
    assert set(metrics["tokens"]) == {"input", "output"}
    assert set(metrics["slo"]) == {"p95_ms_target", "met"}
    assert uuid.UUID(response.headers["X-Request-ID"])


def test_ask_reports_and_logs_the_model_route_and_cost_without_the_question(
    make_cost_client, read_log, log_stream
):
    question = "¿Quién es EMP-0004?"

    response = make_cost_client().post(
        "/ask", json={"question": question}, headers={"X-Request-ID": "cost-log"}
    )

    body = response.json()
    assert response.status_code == 200
    assert set(body) == {
        "answer", "steps", "tools_used", "input_tokens", "output_tokens",
        "request_id", "model", "route", "cached_calls", "cost_usd",
    }
    run = next(line for line in read_log() if line["event"] == "agent_run")
    assert run["model"] == body["model"] == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert run["route"] == body["route"] == "simple"
    assert run["cached_calls"] == body["cached_calls"] == 0
    assert run["cost_usd"] == body["cost_usd"]
    assert run["history_sent"] == 0
    assert question not in log_stream.getvalue()


def test_metrics_add_up_the_cost_of_every_answer(make_cost_client):
    client = make_cost_client()

    first = client.post("/ask", json={"question": "¿Quién es EMP-0004?"}).json()
    second = client.post("/ask", json={"question": "Compara Finanzas"}).json()
    metrics = client.get("/metrics").json()

    assert second["cost_usd"] > 0
    assert metrics["cost_usd"] == pytest.approx(
        first["cost_usd"] + second["cost_usd"]
    )
