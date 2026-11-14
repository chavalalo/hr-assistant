"""Pruebas de ``app.directory``: las dos herramientas de solo lectura."""

import json


def test_get_employee_returns_the_employee_as_json(directory):
    result = directory.get_employee("EMP-0004")

    assert json.loads(result)["name"] == "Jorge Díaz"
    assert "Jorge Díaz" in result


def test_unknown_employee_is_reported(directory):
    result = directory.get_employee("EMP-9999")

    assert "No existe un empleado con id EMP-9999." in result


def test_department_search_ignores_case_and_accents(directory):
    result = directory.search_by_department("tecnologia")

    for name in ("Ana López", "Marta Ruiz", "Jorge Díaz"):
        assert name in result
    assert "Sofía Gómez" not in result
