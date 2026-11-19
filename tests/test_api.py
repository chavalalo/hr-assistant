"""Pruebas de ``app.main``: rutas de salud, métricas y página web."""

import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.directory import EmployeeDirectory
from app.llm import FakeModel
from app.main import create_app

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "employees.json"
# Debe coincidir con la clave que pone ``conftest.py``.
TEST_API_KEY = "tester-key-0123456789"


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
        "pid", "requests", "error_rate", "latency_ms", "tokens", "slo", "cost_usd",
        "by_specialist", "by_client", "security", "cache", "fallbacks", "supervisor",
    }
    assert metrics["cost_usd"] == 0.0
    assert set(metrics["security"]) == {
        "blocked_inputs", "pii_redactions", "output_blocked", "access_denied"
    }
    assert metrics["cache"] == {"hits": 0, "misses": 0, "hit_rate": 0.0}
    assert set(metrics["supervisor"]) == {"rule", "model"}
    assert metrics["fallbacks"] == 0
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
        "specialist", "agents", "supervisor_route", "pii_redacted", "cached",
        "fallback",
    }
    run = next(line for line in read_log() if line["event"] == "agent_run")
    assert run["model"] == body["model"] == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert run["route"] == body["route"] == "simple"
    assert run["cached_calls"] == body["cached_calls"] == 0
    assert run["cost_usd"] == body["cost_usd"]
    assert run["history_sent"] == 0
    assert question not in log_stream.getvalue()


class BreakableDirectory(EmployeeDirectory):
    """Directorio real que se puede romper después de arrancar la aplicación."""

    broken = False

    def count(self):
        """Falla como un archivo perdido cuando la prueba lo rompe."""
        if self.broken:
            raise OSError("employees.json is gone")
        return super().count()


def test_ready_checks_its_data_without_a_key_and_reports_a_broken_one(directory):
    breakable = BreakableDirectory(DATA_PATH)
    settings = Settings.from_env({"API_KEYS": f"tester:{TEST_API_KEY}"})
    app = create_app(
        settings=settings,
        model=FakeModel(directory.departments()),
        directory=breakable,
    )
    client = TestClient(app)

    ready = client.get("/ready")
    breakable.broken = True
    not_ready = client.get("/ready")

    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"directory": "ok", "policies": "ok", "prices": "ok"},
    }
    assert not_ready.status_code == 503
    assert not_ready.json() == {
        "status": "not_ready",
        "checks": {"directory": "error", "policies": "ok", "prices": "ok"},
    }
    assert "employees.json" not in not_ready.text


def test_dashboard_is_public_and_carries_no_data_or_key(make_client):
    client = make_client()
    client.post("/ask", json={"question": "¿Quién es EMP-0004?"})
    client.headers.pop("X-API-Key")

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    test_ids = (
        "dashboard", "dashboard-key", "dashboard-requests", "dashboard-error-rate",
        "dashboard-p95", "dashboard-cost", "dashboard-cache-hit-rate",
        "dashboard-specialists", "dashboard-clients", "dashboard-security",
    )
    for test_id in test_ids:
        assert f'data-testid="{test_id}"' in response.text
    assert "sessionStorage" in response.text
    assert "Sin permiso para ver métricas" in response.text
    assert "innerHTML" not in response.text
    assert TEST_API_KEY not in response.text
    assert "Jorge" not in response.text


def test_metrics_add_up_the_cost_of_every_answer(make_cost_client):
    client = make_cost_client()

    first = client.post("/ask", json={"question": "¿Quién es EMP-0004?"}).json()
    second = client.post("/ask", json={"question": "Compara Finanzas"}).json()
    metrics = client.get("/metrics").json()

    assert second["cost_usd"] > 0
    assert metrics["cost_usd"] == pytest.approx(
        first["cost_usd"] + second["cost_usd"]
    )
