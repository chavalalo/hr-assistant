"""Pruebas de ``app.reviewer``: la salida se limpia y se recorta."""

from app.reviewer import review


def test_reviewer_hides_personal_data_and_cuts_the_answer_to_the_limit(directory):
    answer = "Jorge Díaz (EMP-0004) atiende en jorge@example.com. " + "x" * 100

    cleaned = review(answer, directory, 1500)
    cut = review(answer, directory, 20)

    assert "jorge@example.com" not in cleaned.answer
    assert "[EMAIL]" in cleaned.answer
    assert "EMP-0004" in cleaned.answer
    assert list(cleaned.types) == ["email"]
    assert len(cut.answer) == 20
