"""Pruebas de ``app.policies``: búsqueda de temas en ``data/policies.json``."""

from pathlib import Path

from app.policies import PolicyBook

POLICIES_PATH = Path(__file__).resolve().parents[1] / "data" / "policies.json"


def test_topics_ignore_accents_and_case_and_unknown_topics_list_the_options():
    book = PolicyBook.load(POLICIES_PATH)

    unknown = book.search_policy("ascensos")

    assert book.find_topic("¿Puedo hacer TELETRABAJO?") == "home office"
    assert book.find_topic("¿Cuánta Prima Vacacional me dan?") == "vacaciones"
    assert book.find_topic("Hola, ¿cómo estás?") is None
    assert "12 días hábiles" in book.search_policy("vacaciones")
    assert unknown.startswith("Temas disponibles:")
    for topic in ("vacaciones", "home office", "horario", "permisos", "prestaciones"):
        assert topic in unknown
