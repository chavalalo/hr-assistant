Feature: Policy answers stay anchored to the policy text
  As an HR person
  I want the policy specialist to answer only with the numbers of the policy
  So that nobody gets told 5 vacation days when the policy says 12

  Scenario: A model that invents a number without reading the policy is corrected
    Given the HR assistant runs with a model that never asks for tools and answers "5 días"
    When I ask "Soy ana@example.com, ¿cuántos días de vacaciones tengo?"
    Then the response status is 200
    And the "policy" specialist answered by the route "rule:policy"
    And the answer does not contain the number "5"
    And the answer mentions "12 días hábiles"
    And the tools used include "search_policy"
    And the metrics count 1 blocked answer

  Scenario: The policy text reaches the model in code before it is asked
    Given the HR assistant runs with a model that never asks for tools and answers "Tienes 12 días hábiles de vacaciones."
    When I ask "¿Cuántos días de vacaciones tengo?"
    Then the response status is 200
    And the first message after the system prompt is the vacation policy as a tool result
    And the answer mentions "Tienes 12 días hábiles"
    And the metrics count 0 blocked answers
