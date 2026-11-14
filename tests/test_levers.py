"""Pruebas de ``app.levers``: enrutador por regla y ventana de historial."""

from app.config import Settings
from app.levers import choose_model, trim_history

SMALL = "@cf/meta/llama-3.1-8b-instruct-fast"
LARGE = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"


def test_keywords_are_found_regardless_of_accents_and_case():
    settings = Settings.from_env({})
    cases = {
        "¿POR QUÉ hay tantos en Ventas?": "keyword:por que",
        "Resume el área de Finanzas": "keyword:resume",
        "Dame un resumen de Finanzas": "keyword:resume",
        "Comparación de Ventas y Finanzas": "keyword:compara",
        "Explica quién es EMP-0004": "keyword:explica",
        "Analiza Finanzas": "keyword:analiza",
        "Lista a todos los de Ventas": "keyword:todos",
    }

    for question, reason in cases.items():
        route = choose_model(question, settings)
        assert (route.model, route.reason) == (LARGE, reason), question


def test_question_at_the_char_limit_stays_small_and_one_more_goes_large():
    settings = Settings.from_env({"ROUTER_MAX_CHARS": "10"})

    at_limit = choose_model("a" * 10, settings)
    over_limit = choose_model("a" * 11, settings)

    assert (at_limit.model, at_limit.reason) == (SMALL, "simple")
    assert (over_limit.model, over_limit.reason) == (LARGE, "long_question")


def test_keyword_inside_another_word_keeps_the_small_model():
    settings = Settings.from_env({})

    route = choose_model("¿Quién conoce los métodos de pago?", settings)

    assert (route.model, route.reason) == (SMALL, "simple")


def test_history_window_keeps_only_the_last_messages():
    history = [{"role": "user", "content": f"m{index}"} for index in range(4)]

    assert trim_history(history, 0) == history[:0]
    assert trim_history(history, 2) == history[-2:]
    assert trim_history(history, 4) == history
    assert trim_history(history, 10) == history
