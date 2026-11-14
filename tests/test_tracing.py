"""Pruebas de ``app.tracing``: trazas opcionales sin red en las pruebas."""

import contextlib
import sys
import types
from dataclasses import dataclass, field

from app.config import Settings
from app.tracing import NoopTracer, build_tracer

TRACING_ON = {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test-key"}


def double(value):
    """Función de ejemplo que se envuelve con el tracer."""
    return value * 2


@dataclass
class LangsmithCalls:
    """Registro de las llamadas que recibe el doble de ``langsmith``."""

    clients: list = field(default_factory=list)
    traced: list = field(default_factory=list)
    contexts: list = field(default_factory=list)


def fake_langsmith():
    """Doble del paquete ``langsmith`` que registra cómo se usa.

    :return: Módulo falso con ``Client``, ``traceable`` y ``tracing_context``,
        y el registro de llamadas que recibe
    :rtype: tuple[types.ModuleType, LangsmithCalls]
    """
    module = types.ModuleType("langsmith")
    calls = LangsmithCalls()

    def client(**kwargs):
        calls.clients.append(kwargs)
        return object()

    def traceable(*args, **kwargs):
        calls.traced.append(kwargs)
        if args and callable(args[0]):
            return args[0]
        return lambda fn: fn

    @contextlib.contextmanager
    def tracing_context(**kwargs):
        calls.contexts.append(kwargs)
        yield

    module.Client = client
    module.traceable = traceable
    module.tracing_context = tracing_context
    return module, calls


def test_tracing_stays_off_and_never_imports_langsmith_without_a_key(monkeypatch):
    monkeypatch.setitem(sys.modules, "langsmith", None)
    settings = Settings.from_env({"LANGSMITH_TRACING": "true"})

    tracer = build_tracer(settings)

    assert settings.tracing_enabled is False
    assert isinstance(tracer, NoopTracer)


def test_noop_tracer_returns_the_same_function():
    tracer = NoopTracer()

    with tracer.context("demo-123"):
        wrapped = tracer.wrap(double, "double", "tool")

    assert wrapped is double


def test_langsmith_tracer_hides_text_and_tags_the_request_id(monkeypatch):
    langsmith, calls = fake_langsmith()
    monkeypatch.setitem(sys.modules, "langsmith", langsmith)

    tracer = build_tracer(Settings.from_env(TRACING_ON))
    wrapped = tracer.wrap(double, "double", "tool")
    with tracer.context("demo-123"):
        assert wrapped(2) == 4

    assert not isinstance(tracer, NoopTracer)
    assert any(
        kwargs.get("hide_inputs") is True and kwargs.get("hide_outputs") is True
        for kwargs in calls.clients
    )
    assert any(
        kwargs.get("name") == "double" and kwargs.get("run_type") == "tool"
        for kwargs in calls.traced
    )
    assert any(
        (kwargs.get("metadata") or {}).get("request_id") == "demo-123"
        for kwargs in calls.contexts
    )


def test_the_trace_metadata_names_the_client_but_never_a_key(monkeypatch):
    langsmith, calls = fake_langsmith()
    monkeypatch.setitem(sys.modules, "langsmith", langsmith)

    tracer = build_tracer(Settings.from_env(TRACING_ON))
    with tracer.context("demo-123", client="tester"):
        pass
    with NoopTracer().context("demo-123", client="tester"):
        pass

    assert calls.contexts[-1]["metadata"] == {
        "request_id": "demo-123",
        "client": "tester",
    }
