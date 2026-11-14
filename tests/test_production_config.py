"""Pruebas de la configuración nueva de la sesión 4 en ``app.config``."""

import pytest

from app.config import ConfigError, Settings


def test_new_settings_default_to_development_without_clients_and_30_per_minute():
    settings = Settings.from_env({})
    blank = Settings.from_env({"API_KEYS": "   "})

    assert settings.environment == "development"
    assert isinstance(settings.api_clients, tuple)
    assert len(settings.api_clients) == 0
    assert settings.rate_limit_per_minute == 30
    assert isinstance(blank.api_clients, tuple)
    assert len(blank.api_clients) == 0


def test_unknown_environment_or_bad_rate_limit_stops_the_startup():
    broken = [
        {"ENVIRONMENT": "staging"},
        {"RATE_LIMIT_PER_MINUTE": "0"},
        {"RATE_LIMIT_PER_MINUTE": "many"},
    ]
    for environ in broken:
        with pytest.raises(ConfigError):
            Settings.from_env(environ)
