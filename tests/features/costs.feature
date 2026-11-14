Feature: Cheaper answers without worse answers
  As the person who pays for the model
  I want each question routed to the right model and every answer priced
  So that I can lower the cost without lowering the quality

  Scenario: A short simple question goes to the small model and costs more than zero
    Given the priced HR assistant is running
    When I ask "¿Quién es EMP-0004?" with the request id "cost-simple"
    Then the response status is 200
    And the answer used the model "@cf/meta/llama-3.1-8b-instruct-fast" with the route "simple"
    And the answer costs more than zero

  Scenario: A question with a keyword goes to the large model with its reason
    Given the priced HR assistant is running
    When I ask "Compara a los empleados de Finanzas" with the request id "cost-keyword"
    Then the answer used the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast" with the route "keyword:compara"

  Scenario: A question longer than the router limit goes to the large model
    Given the priced HR assistant is running with "ROUTER_MAX_CHARS" set to "20"
    When I ask "¿Quién es EMP-0004 en el directorio?" with the request id "cost-long"
    Then the answer used the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast" with the route "long_question"

  Scenario: With routing turned off every question goes to the large model
    Given the priced HR assistant is running with "ROUTING" set to "false"
    When I ask "¿Quién es EMP-0004?" with the request id "cost-off"
    Then the answer used the model "@cf/meta/llama-3.3-70b-instruct-fp8-fast" with the route "routing_off"
    And the answer costs more than zero

  Scenario: Only the last messages of the history reach the model
    Given the priced HR assistant is running with a spy model and a history window of 2
    When I ask "Hola" after a history of 4 messages
    Then the model received only the last 2 history messages and the question
    And the agent_run line says 2 history messages were sent

  Scenario: When the gateway fails the API answers 502 with the request id
    Given the HR assistant uses a gateway that fails
    When I ask "¿Quién es EMP-0004?" with the request id "cost-502"
    Then the response status is 502
    And the body is "model unavailable" with the request id "cost-502"
    And the log has a "ModelUnavailable" error without the token or the account id

  Scenario: A gateway cache hit counts as a cached call and costs nothing
    Given the HR assistant uses a gateway that answers from its cache
    When I ask "Hola" with the request id "cost-cache"
    Then the response status is 200
    And the answer has 1 cached call and costs 0
    And the answer still reports the tokens of the gateway
