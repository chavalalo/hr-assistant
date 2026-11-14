"""Pruebas de ``app.auth``: lectura de ``API_KEYS`` e identificación del cliente."""

import pytest

from app.auth import identify_client, parse_api_keys
from app.config import ConfigError, Settings

BROKEN_SECRET = "secret-value-without-client"


def test_api_keys_are_parsed_into_named_clients():
    clients = parse_api_keys(" alpha:key-with:colon-123 , beta:second-key-4567 ")

    assert [client.name for client in clients] == ["alpha", "beta"]
    assert [client.key for client in clients] == [
        "key-with:colon-123",
        "second-key-4567",
    ]


def test_malformed_entry_reports_position_and_length_but_never_the_key():
    with pytest.raises(ConfigError) as caught:
        parse_api_keys(f"alpha:first-key-123,{BROKEN_SECRET}")

    message = str(caught.value)
    assert "entry 2" in message
    assert str(len(BROKEN_SECRET)) in message
    assert BROKEN_SECRET not in message
    assert caught.value.__cause__ is None


def test_entries_without_client_or_key_or_with_repeats_are_rejected():
    broken = [
        "alpha:",
        ":key-123",
        "alpha:key-1,,beta:key-2",
        "bad name!:key-123",
        "alpha:key-1,alpha:key-2",
        "alpha:same-key,beta:same-key",
    ]
    for raw in broken:
        with pytest.raises(ConfigError):
            parse_api_keys(raw)


def test_identify_client_accepts_only_a_known_key():
    clients = parse_api_keys("alpha:alpha-key-123,beta:beta-key-456")

    assert identify_client("beta-key-456", clients) == "beta"
    assert identify_client("beta-key-457", clients) is None
    assert identify_client("", clients) is None
    assert identify_client(None, clients) is None


def test_settings_repr_never_shows_the_api_keys():
    settings = Settings.from_env({"API_KEYS": "alpha:alpha-key-0123456789"})

    assert "alpha-key-0123456789" not in repr(settings)
