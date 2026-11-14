"""Pruebas de ``app.costs``: precio por millón de tokens y llamadas cacheadas."""

import json

import pytest

from app.costs import PriceTable
from app.llm import Completion


@pytest.fixture
def prices(tmp_path):
    """Tabla de precios con valores redondos para calcular a mano."""
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "currency": "USD",
                "unit": "per million tokens",
                "models": {"round-model": {"input": 1.0, "output": 2.0}},
            }
        ),
        encoding="utf-8",
    )
    return PriceTable.load(path)


def test_cost_adds_up_only_the_calls_that_were_not_cached(prices):
    completions = [
        Completion(text="{}", input_tokens=1000, output_tokens=500),
        Completion(text="{}", input_tokens=2000, output_tokens=0),
        Completion(text="{}", input_tokens=5000, output_tokens=5000, cached=True),
    ]

    # (1000 * 1 + 500 * 2 + 2000 * 1) / 1_000_000; la llamada cacheada no cuesta.
    assert prices.cost("round-model", completions) == pytest.approx(0.004)


def test_model_without_a_price_is_reported(prices):
    completions = [Completion(text="{}", input_tokens=10, output_tokens=10)]

    with pytest.raises(KeyError, match="unknown-model"):
        prices.cost("unknown-model", completions)
