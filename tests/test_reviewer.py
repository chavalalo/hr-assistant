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


# Adenda 2: las respuestas del especialista ``policy`` se anclan al texto de
# las políticas consultadas. ``policy_texts`` es opcional: ``None`` (o no
# pasarlo) significa que la respuesta no es de ``policy``.

VACATION_TEXT = (
    "Vacaciones: 12 días hábiles a partir del primer año, que aumentan 2 días "
    "por año hasta llegar a 20. Se piden con 15 días de anticipación en el "
    "portal de RH y la prima vacacional es de 25 %."
)
UNVERIFIED_POLICY = (
    "No pude verificar la respuesta con las políticas. Intenta de nuevo."
)


def review_policy(answer, directory, policy_texts):
    """Revisa una respuesta del especialista ``policy``.

    :param answer: Respuesta del especialista
    :type answer: str
    :param directory: Directorio de empleados
    :type directory: app.directory.EmployeeDirectory
    :param policy_texts: Textos de las políticas consultadas en la petición
    :type policy_texts: tuple[str, ...]
    :return: Respuesta revisada
    :rtype: app.reviewer.Review
    """
    return review(answer, directory, 1500, policy_texts=policy_texts)


def test_policy_answer_with_an_invented_number_is_replaced_by_the_policy(directory):
    # «5» aparece dentro de «15» y «25»: se comparan cifras completas.
    answer = "Tienes 5 días de vacaciones."

    result = review_policy(answer, directory, (VACATION_TEXT,))

    assert result.answer == VACATION_TEXT
    assert result.blocked is True


def test_policy_answer_with_numbers_found_in_the_policy_passes_unchanged(directory):
    answer = "Tienes 12 días hábiles y una prima vacacional de 25 %."

    result = review_policy(answer, directory, (VACATION_TEXT,))

    assert result.answer == answer
    assert result.blocked is False


def test_policy_answer_with_a_number_and_no_policy_read_is_not_verified(directory):
    answer = "Tienes 12 días de vacaciones."

    result = review_policy(answer, directory, ())

    assert result.answer == UNVERIFIED_POLICY
    assert result.blocked is True


def test_directory_answers_with_numbers_are_not_checked_against_policies(directory):
    answer = "Jorge Díaz (EMP-0004) tiene 5 personas a su cargo."

    result = review(answer, directory, 1500, question="¿Quién es EMP-0004?")

    assert result.answer == answer
    assert result.blocked is False
