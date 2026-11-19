"""Pruebas de punta a punta de la página y del tablero del HR Assistant.

Cubren spec/04-production.md y la sección «Pruebas de punta a punta» de
spec/05-reto.md. Se corren con el producto vivo y el modelo simulado; la URL
base y la clave (``E2E_API_KEY``) las pone la verificación. La clave nunca se
escribe aquí.
"""

import os
import re

from playwright.sync_api import Locator, Page, expect

FIRST_QUESTION = "¿Quién es EMP-0001?"
SECOND_QUESTION = "¿En qué departamento trabaja EMP-0002?"
PERSONAL_EMAIL = "ana.perez.e2e@example.com"
EMAIL_QUESTION = f"¿Quién es EMP-0001? Respóndeme a {PERSONAL_EMAIL}"
VACATION_QUESTION = "¿Cuántos días de vacaciones me tocan?"
VACATION_POLICY_TEXT = "12 días hábiles"
REQUEST_ID_PATTERN = re.compile(r"\S{8,}")
HAS_DIGIT = re.compile(r"\d")
EMPTY_QUESTION_MESSAGE = "Escribe una pregunta antes de enviar."
INVALID_KEY_MESSAGE = "Clave inválida"
GENERIC_ERROR_MESSAGE = "No se pudo obtener una respuesta"
FORBIDDEN_METRICS_MESSAGE = "Sin permiso para ver métricas"
WRONG_KEY_SUFFIX = "-wrong"
DASHBOARD_NUMERIC_INDICATORS = (
    "dashboard-requests",
    "dashboard-error-rate",
    "dashboard-p95",
    "dashboard-cost",
    "dashboard-cache-hit-rate",
    "dashboard-clients",
    "dashboard-security",
)


def _api_key() -> str:
    """Devuelve la clave que pone la verificación.

    :return: Valor de ``E2E_API_KEY``
    :rtype: str
    """
    return os.environ["E2E_API_KEY"]


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright
    :type page: Page
    :param api_key: Clave que se escribe en ``data-testid="api-key"``
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _send(page: Page, question: str) -> None:
    """Escribe una pregunta en la página y la envía.

    :param page: Página de Playwright abierta en el producto
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def _ask_and_get_answer(page: Page, question: str) -> Locator:
    """Abre la página con clave, pregunta y devuelve la vuelta del asistente.

    Espera a que exista exactamente una vuelta ``assistant-answer``; así la
    aserción mira solo la respuesta y no la pregunta de la persona.

    :param page: Página de Playwright
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    :return: Localizador de la última vuelta del asistente
    :rtype: Locator
    """
    _open_with_key(page, _api_key())
    _send(page, question)
    answers = page.get_by_test_id("assistant-answer")
    expect(answers).to_have_count(1)
    return answers.last


def test_a_conversation_shows_each_answer_with_its_request_id(page: Page) -> None:
    """Dos preguntas seguidas muestran sus respuestas y ``request_id`` sin borrar
    la conversación anterior."""
    _open_with_key(page, _api_key())
    _send(page, FIRST_QUESTION)

    request_ids = page.get_by_test_id("request-id")
    expect(request_ids).to_have_count(1)
    expect(request_ids.first).to_contain_text(REQUEST_ID_PATTERN)
    conversation = page.get_by_test_id("answer")
    expect(conversation).to_contain_text("EMP-0001")
    expect(conversation).not_to_contain_text(GENERIC_ERROR_MESSAGE)

    _send(page, SECOND_QUESTION)

    expect(request_ids).to_have_count(2)
    expect(conversation).to_contain_text(FIRST_QUESTION)
    expect(conversation).to_contain_text(SECOND_QUESTION)


def test_sending_an_empty_question_shows_an_error_in_spanish(page: Page) -> None:
    """Una pregunta vacía muestra un mensaje de error en español y no llama a la API."""
    _open_with_key(page, _api_key())
    _send(page, "   ")

    expect(page.get_by_test_id("answer")).to_contain_text(EMPTY_QUESTION_MESSAGE)
    expect(page.get_by_test_id("request-id")).to_have_count(0)


def test_a_wrong_hidden_api_key_shows_invalid_key_message(page: Page) -> None:
    """El campo de clave oculta lo escrito y una clave equivocada muestra
    «Clave inválida»."""
    _open_with_key(page, _api_key() + WRONG_KEY_SUFFIX)

    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")
    _send(page, FIRST_QUESTION)
    expect(page.get_by_test_id("answer")).to_contain_text(INVALID_KEY_MESSAGE)


def test_an_email_in_the_question_is_not_shown_in_the_answer(page: Page) -> None:
    """La respuesta del asistente no muestra el correo que traía la pregunta."""
    answer = _ask_and_get_answer(page, EMAIL_QUESTION)

    expect(answer).not_to_contain_text(PERSONAL_EMAIL)
    expect(answer).not_to_contain_text(GENERIC_ERROR_MESSAGE)


def test_a_vacation_question_shows_the_vacation_policy(page: Page) -> None:
    """Una pregunta de vacaciones muestra la política («12 días hábiles»)."""
    answer = _ask_and_get_answer(page, VACATION_QUESTION)

    expect(answer).to_contain_text(VACATION_POLICY_TEXT)


def test_the_dashboard_shows_its_indicators_after_typing_the_key(page: Page) -> None:
    """El tablero muestra sus indicadores después de escribir la clave."""
    # Preparación: una pregunta para que haya datos por especialista.
    setup = page.request.post(
        "/ask",
        headers={"X-API-Key": _api_key()},
        data={"question": FIRST_QUESTION, "history": []},
    )
    assert setup.ok, f"la pregunta de preparación respondió {setup.status}"

    page.goto("/dashboard")
    expect(page.get_by_test_id("dashboard")).to_be_visible()
    dashboard_key = page.get_by_test_id("dashboard-key")
    expect(dashboard_key).to_have_attribute("type", "password")
    dashboard_key.fill(_api_key())
    dashboard_key.press("Enter")
    dashboard_key.blur()

    dashboard = page.get_by_test_id("dashboard")
    expect(page.get_by_test_id("dashboard-specialists")).to_contain_text("directory")
    for test_id in DASHBOARD_NUMERIC_INDICATORS:
        indicator = page.get_by_test_id(test_id)
        expect(indicator).to_be_visible()
        expect(indicator).to_contain_text(HAS_DIGIT)
    expect(dashboard).not_to_contain_text(INVALID_KEY_MESSAGE)
    expect(dashboard).not_to_contain_text(FORBIDDEN_METRICS_MESSAGE)
