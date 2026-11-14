"""Pruebas de ``app.config``: valores por omisión y validación."""

from pathlib import Path

import pytest

from app.config import ConfigError, Settings

PRODUCT = Path(__file__).resolve().parents[1]


def test_default_settings_match_the_specification():
    settings = Settings.from_env({})

    assert settings.model_provider == "fake"
    assert settings.agent_max_steps == 3
    assert settings.max_question_chars == 2000
    expected = (PRODUCT / "data" / "employees.json").resolve()
    assert Path(settings.employees_path).resolve() == expected


def test_zero_max_steps_prevents_startup():
    with pytest.raises(ConfigError, match="AGENT_MAX_STEPS"):
        Settings.from_env({"AGENT_MAX_STEPS": "0"})


def test_non_numeric_question_limit_prevents_startup():
    with pytest.raises(ConfigError, match="MAX_QUESTION_CHARS"):
        Settings.from_env({"MAX_QUESTION_CHARS": "mucho"})


def test_unknown_model_provider_prevents_startup():
    with pytest.raises(ConfigError, match="MODEL_PROVIDER"):
        Settings.from_env({"MODEL_PROVIDER": "openai"})


def test_default_observability_settings_are_safe():
    settings = Settings.from_env({})

    assert settings.service_name == "hr-assistant"
    assert settings.slo_p95_ms == 2000
    assert settings.hide_inputs is True
    assert settings.hide_outputs is True
    assert settings.tracing_enabled is False


def test_invalid_slo_or_hide_flag_prevents_startup():
    with pytest.raises(ConfigError, match="SLO_P95_MS"):
        Settings.from_env({"SLO_P95_MS": "0"})
    with pytest.raises(ConfigError, match="HIDE_INPUTS"):
        Settings.from_env({"HIDE_INPUTS": "quizas"})


def test_settings_never_keep_the_langsmith_key():
    secret = "lsv2-very-secret-key"
    settings = Settings.from_env(
        {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": secret}
    )

    assert settings.tracing_enabled is True
    assert secret not in repr(settings)
    assert secret not in [str(value) for value in vars(settings).values()]


def test_default_cost_settings_match_the_specification():
    settings = Settings.from_env({})

    assert settings.cf_account_id == ""
    assert settings.cf_gateway_id == "default"
    assert settings.cf_api_token == ""
    assert settings.model_small == "@cf/meta/llama-3.1-8b-instruct-fast"
    assert settings.model_large == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert settings.routing is True
    assert settings.router_max_chars == 80
    assert settings.history_window == 6
    assert settings.model_max_tokens == 300
    assert settings.model_temperature == 0.0
    assert settings.cache_ttl_seconds == 0
    expected = (PRODUCT / "data" / "model_prices.json").resolve()
    assert Path(settings.prices_path).resolve() == expected


def test_gateway_without_any_cloudflare_variable_prevents_startup(gateway_environ):
    for name in ("CF_ACCOUNT_ID", "CF_GATEWAY_ID", "CF_API_TOKEN"):
        environ = dict(gateway_environ, **{name: ""})
        with pytest.raises(ConfigError, match=name) as error:
            Settings.from_env(environ)
        assert "tok-secret" not in str(error.value)


def test_settings_never_show_the_cloudflare_token(gateway_environ):
    settings = Settings.from_env(gateway_environ)

    assert settings.model_provider == "gateway"
    assert settings.cf_api_token == "tok-secret"
    assert "tok-secret" not in repr(settings)


def test_invalid_cost_settings_prevent_startup():
    invalid = {
        "HISTORY_WINDOW": "-1",
        "MODEL_TEMPERATURE": "abc",
        "ROUTER_MAX_CHARS": "0",
        "ROUTING": "maybe",
        "MODEL_SMALL": "@cf/unknown/model-without-price",
    }

    for name, value in invalid.items():
        with pytest.raises(ConfigError, match=name):
            Settings.from_env({name: value})
