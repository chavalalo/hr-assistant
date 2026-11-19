Feature: Ask the HR assistant
  HR staff ask questions about employees and the assistant answers
  using the read-only employee directory.

  Scenario: Ask about an employee by id
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer mentions "Jorge Díaz"
    And the tools used are "get_employee"
    And the agent took 2 steps

  Scenario: Ask about a department
    Given the HR assistant is running
    When I ask "¿Quiénes trabajan en Finanzas?"
    Then the response status is 200
    And the answer mentions "Sofía Gómez"
    And the tools used are "search_by_department"

  Scenario: Ask about an unknown employee
    Given the HR assistant is running
    When I ask "¿Quién es EMP-9999?"
    Then the response status is 200
    And the tools used are "get_employee"
    And the answer mentions "No existe un empleado con id EMP-9999"

  Scenario: Ask something unrelated
    Given the HR assistant is running
    When I ask "Hola, ¿cómo estás?"
    Then the response status is 200
    And the answer is "Pregúntame por un empleado (EMP-0001) o un departamento."
    And no tools were used
    And the agent took 1 steps
    And the model classified the question for the "directory" specialist

  Scenario: The step cap stops the loop
    Given the HR assistant is running with a cap of 1 steps
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the answer is "No pude completar la respuesta. Intenta con una pregunta más concreta."
    And the agent took 1 steps
