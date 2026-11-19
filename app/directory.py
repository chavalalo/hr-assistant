"""Directorio de empleados de solo lectura y sus dos herramientas.

Es el dueño del formato del id de empleado (``EMPLOYEE_ID_PATTERN``) y de la
normalización de textos (``normalize``): supervisor, revisor, modelo simulado
y caché los importan de aquí para que no haya copias distintas de la regla.
"""

import json
import re
import unicodedata
from pathlib import Path
from types import MappingProxyType

EMPLOYEE_ID_PATTERN = re.compile(r"\bEMP-\d{4}\b", re.IGNORECASE)


def normalize(text):
    """Normaliza un texto para comparar: sin acentos y en minúsculas.

    :param text: Texto original
    :type text: str
    :return: Texto normalizado
    :rtype: str
    """
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return without_marks.casefold().strip()


def _to_json(value):
    """Serializa a JSON conservando los acentos.

    :param value: Valor serializable
    :type value: object
    :return: Texto JSON
    :rtype: str
    """
    return json.dumps(value, ensure_ascii=False)


class EmployeeDirectory:
    """Directorio de empleados cargado una sola vez desde un archivo JSON.

    :param path: Ruta al archivo ``employees.json``
    :type path: str or pathlib.Path
    """

    def __init__(self, path):
        with Path(path).open(encoding="utf-8") as handle:
            records = json.load(handle)
        self._employees = tuple(
            MappingProxyType(dict(record)) for record in records
        )

    def get_employee(self, employee_id):
        """Busca un empleado por id.

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: El empleado en JSON o un texto que dice que no existe
        :rtype: str
        """
        wanted = str(employee_id).strip().upper()
        for employee in self._employees:
            if employee["id"].upper() == wanted:
                return _to_json(dict(employee))
        return f"No existe un empleado con id {employee_id}."

    def search_by_department(self, department):
        """Lista los empleados de un departamento.

        La comparación ignora mayúsculas y acentos.

        :param department: Nombre del departamento
        :type department: str
        :return: Lista de empleados en JSON o un texto si no hay ninguno
        :rtype: str
        """
        wanted = normalize(str(department))
        found = [
            dict(employee)
            for employee in self._employees
            if normalize(employee["department"]) == wanted
        ]
        if not found:
            return f"No hay empleados en el departamento {department}: []"
        return _to_json(found)

    def has_employee(self, employee_id):
        """Indica si existe un empleado con ese id (lo usa el revisor).

        :param employee_id: Id del empleado, por ejemplo ``EMP-0004``
        :type employee_id: str
        :return: ``True`` si el id está en el directorio
        :rtype: bool
        """
        wanted = str(employee_id).strip().upper()
        return any(employee["id"].upper() == wanted for employee in self._employees)

    def count(self):
        """Cuenta los empleados cargados (lo usa ``GET /ready``).

        :return: Número de empleados
        :rtype: int
        """
        return len(self._employees)

    def departments(self):
        """Devuelve los departamentos sin repetir y en orden de aparición.

        :return: Nombres de los departamentos
        :rtype: list[str]
        """
        names = []
        for employee in self._employees:
            if employee["department"] not in names:
                names.append(employee["department"])
        return names
