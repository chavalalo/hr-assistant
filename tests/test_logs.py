"""Pruebas de ``app.logs``: una línea JSON por evento con campos fijos."""

import io
import json

from app.logs import JsonLogger


def test_event_line_has_the_required_fields_and_utc_timestamp(clock):
    stream = io.StringIO()
    logger = JsonLogger(service="hr-assistant", clock=clock, stream=stream)
    clock.advance(0.25)

    logger.emit("request", "abc-1", method="GET", path="/health", status=200)

    assert json.loads(stream.getvalue()) == {
        "ts": "2026-01-15T10:30:00.250Z",
        "service": "hr-assistant",
        "event": "request",
        "request_id": "abc-1",
        "method": "GET",
        "path": "/health",
        "status": 200,
    }


def test_each_event_is_one_line_and_keeps_accents(clock):
    stream = io.StringIO()
    logger = JsonLogger(service="rh", clock=clock, stream=stream)

    logger.emit("audit", "r1", action="tool_call", tool="search_by_department",
                args={"department": "Tecnología"})
    logger.emit("agent_run", "r1", steps=2)

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["event"] for line in lines] == ["audit", "agent_run"]
    assert "Tecnología" in lines[0]
