"""Pruebas de punta a punta de la página del HR Assistant (spec/04-production.md).

Se corren con el producto vivo y el modelo simulado; la URL base y la clave
(``E2E_API_KEY``) las pone la verificación. La clave nunca se escribe aquí.
"""

import os
import re

from playwright.sync_api import Page, expect

FIRST_QUESTION = "¿Quién es EMP-0001?"
SECOND_QUESTION = "¿En qué departamento trabaja EMP-0002?"
REQUEST_ID_PATTERN = re.compile(r"\S{8,}")
EMPTY_QUESTION_MESSAGE = "Escribe una pregunta antes de enviar."
INVALID_KEY_MESSAGE = "Clave inválida"
WRONG_KEY_SUFFIX = "-wrong"


def _open_with_key(page: Page, api_key: str) -> None:
    """Abre la página y escribe la clave en su campo.

    :param page: Página de Playwright
    :type page: Page
    :param api_key: Clave que se escribe en ``data-testid="api-key"``
    :type api_key: str
    """
    page.goto("/")
    page.get_by_test_id("api-key").fill(api_key)


def _open_with_valid_key(page: Page) -> None:
    """Abre la página con la clave que pone la verificación.

    :param page: Página de Playwright
    :type page: Page
    """
    _open_with_key(page, os.environ["E2E_API_KEY"])


def _send(page: Page, question: str) -> None:
    """Escribe una pregunta en la página y la envía.

    :param page: Página de Playwright abierta en el producto
    :type page: Page
    :param question: Texto de la pregunta
    :type question: str
    """
    page.get_by_test_id("question").fill(question)
    page.get_by_test_id("send").click()


def test_asking_a_question_shows_the_answer_and_its_request_id(page: Page) -> None:
    """Una pregunta enviada con clave muestra la respuesta y su ``request_id``."""
    _open_with_valid_key(page)
    _send(page, FIRST_QUESTION)

    request_id = page.get_by_test_id("request-id")
    expect(request_id).to_have_count(1)
    expect(request_id).to_contain_text(REQUEST_ID_PATTERN)
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text("EMP-0001")
    expect(answer).not_to_contain_text("No se pudo obtener una respuesta")
    expect(answer).not_to_contain_text(INVALID_KEY_MESSAGE)


def test_sending_an_empty_question_shows_an_error_in_spanish(page: Page) -> None:
    """Una pregunta vacía muestra un mensaje de error en español y no llama a la API."""
    _open_with_valid_key(page)
    _send(page, "   ")

    expect(page.get_by_test_id("answer")).to_contain_text(EMPTY_QUESTION_MESSAGE)
    expect(page.get_by_test_id("request-id")).to_have_count(0)


def test_a_second_question_keeps_the_previous_conversation_on_screen(
    page: Page,
) -> None:
    """La segunda pregunta se agrega sin borrar la conversación anterior."""
    _open_with_valid_key(page)
    _send(page, FIRST_QUESTION)
    expect(page.get_by_test_id("request-id")).to_have_count(1)
    _send(page, SECOND_QUESTION)

    expect(page.get_by_test_id("request-id")).to_have_count(2)
    answer = page.get_by_test_id("answer")
    expect(answer).to_contain_text(FIRST_QUESTION)
    expect(answer).to_contain_text(SECOND_QUESTION)


def test_the_api_key_field_hides_what_is_typed(page: Page) -> None:
    """El campo de clave es de tipo contraseña."""
    page.goto("/")

    expect(page.get_by_test_id("api-key")).to_have_attribute("type", "password")


def test_a_wrong_api_key_shows_invalid_key_message(page: Page) -> None:
    """Una clave equivocada muestra «Clave inválida»."""
    _open_with_key(page, os.environ["E2E_API_KEY"] + WRONG_KEY_SUFFIX)
    _send(page, FIRST_QUESTION)

    expect(page.get_by_test_id("answer")).to_contain_text(INVALID_KEY_MESSAGE)
