Feature: Validate questions and history
  The API rejects invalid input with 422 and never stores the history:
  the client sends it on every request.

  Scenario: An empty question is rejected
    Given the HR assistant is running
    When I send an empty question
    Then the response status is 422

  Scenario: A question longer than the limit is rejected
    Given the HR assistant is running with a question limit of 50 characters
    When I send a question of 51 characters
    Then the response status is 422

  Scenario: A history with an unknown role is rejected
    Given the HR assistant is running
    When I ask "¿Quién es EMP-0004?" with a history message from role "system"
    Then the response status is 422

  Scenario: The history comes from the client and is not stored
    Given the HR assistant is running with a recording model
    When I ask "¿Quién es EMP-0004?" with a previous turn in the history
    Then the response status is 200
    And the model received the previous turn before the question
    When I ask "¿Quién es EMP-0004?" without history
    Then the model received only the new question
