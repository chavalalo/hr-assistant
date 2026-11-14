"""Pruebas de ``app.metrics``: percentiles, ventana, errores y SLO."""

from app.metrics import Metrics


def test_empty_metrics_report_zeros_and_meet_the_slo():
    snapshot = Metrics(slo_p95_ms=2000).snapshot(42)

    assert snapshot == {
        "pid": 42,
        "requests": 0,
        "error_rate": 0.0,
        "latency_ms": {"p50": 0.0, "p95": 0.0},
        "tokens": {"input": 0, "output": 0},
        "slo": {"p95_ms_target": 2000, "met": True},
    }


def test_percentiles_use_nearest_rank_and_p95_equal_to_target_is_not_met():
    metrics = Metrics(slo_p95_ms=95)
    for latency in range(1, 101):
        metrics.record_request(float(latency), 200)

    snapshot = metrics.snapshot(1)

    assert snapshot["latency_ms"] == {"p50": 50.0, "p95": 95.0}
    assert snapshot["slo"] == {"p95_ms_target": 95, "met": False}


def test_latency_window_keeps_only_the_most_recent_requests():
    metrics = Metrics(slo_p95_ms=2000, window=3)
    for latency in (5000.0, 5000.0, 10.0, 20.0, 30.0):
        metrics.record_request(latency, 200)

    snapshot = metrics.snapshot(1)

    assert snapshot["requests"] == 5
    assert snapshot["latency_ms"] == {"p50": 20.0, "p95": 30.0}
    assert snapshot["slo"]["met"] is True


def test_error_rate_counts_only_server_errors_and_tokens_add_up():
    metrics = Metrics(slo_p95_ms=2000)
    for status in (200, 404, 500, 503):
        metrics.record_request(1.0, status)
    metrics.add_tokens(10, 3)
    metrics.add_tokens(5, 2)

    snapshot = metrics.snapshot(1)

    assert snapshot["requests"] == 4
    assert snapshot["error_rate"] == 0.5
    assert snapshot["tokens"] == {"input": 15, "output": 5}
