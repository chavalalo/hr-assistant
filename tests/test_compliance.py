"""Pruebas de ``app.compliance``: reglas de producción revisadas al arrancar."""

import pytest

from app.compliance import enforce, violations
from app.config import ConfigError, Settings

KEY_OF_15 = "short-secret-15"
KEY_OF_16 = "longer-secret-16"


def test_development_requires_nothing():
    settings = Settings.from_env(
        {
            "ENVIRONMENT": "development",
            "MODEL_PROVIDER": "fake",
            "LANGSMITH_TRACING": "true",
            "HIDE_INPUTS": "false",
        }
    )

    assert not violations(settings)
    enforce(settings)


def test_production_with_safe_settings_has_no_violations(gateway_environ):
    settings = Settings.from_env(
        {
            **gateway_environ,
            "ENVIRONMENT": "production",
            "API_KEYS": f"ops:{KEY_OF_16}",
            "LANGSMITH_TRACING": "true",
            "HIDE_INPUTS": "true",
            "HIDE_OUTPUTS": "true",
        }
    )

    assert not violations(settings)
    enforce(settings)


def test_production_reports_every_broken_rule_without_values():
    settings = Settings.from_env(
        {
            "ENVIRONMENT": "production",
            "MODEL_PROVIDER": "fake",
            "API_KEYS": f"ops:{KEY_OF_15}",
            "LANGSMITH_TRACING": "true",
            "HIDE_OUTPUTS": "false",
        }
    )

    found = violations(settings)
    with pytest.raises(ConfigError) as caught:
        enforce(settings)

    assert len(found) == 3
    for name in ("MODEL_PROVIDER", "API_KEYS", "HIDE_OUTPUTS"):
        assert name in str(caught.value)
    assert KEY_OF_15 not in str(caught.value)
    assert KEY_OF_15 not in " ".join(found)
