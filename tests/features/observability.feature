Feature: Observability of every request
  As a support person
  I want every request to carry an id, a JSON log line and metrics
  So that I can answer with data what happened with request X

  Scenario: Every response carries a generated request id
    Given the observed HR assistant is running
    When I check the health endpoint
    Then the response carries a generated request id

  Scenario: The client request id is kept
    Given the observed HR assistant is running
    When I ask about EMP-0004 with the request id "demo-123"
    Then the request id "demo-123" is in the header and in the body

  Scenario: A request id with spaces is replaced
    Given the observed HR assistant is running
    When I check the health endpoint with the request id "bad id with spaces"
    Then the response carries a generated request id

  Scenario: A request id that is too long is replaced
    Given the observed HR assistant is running
    When I check the health endpoint with a request id of 200 characters
    Then the response carries a generated request id

  Scenario: Asking writes request, agent_run and audit lines without personal text
    Given the observed HR assistant is running
    When I ask about EMP-0004 with the request id "demo-log"
    Then the log has the events "audit, agent_run, request" for the request id "demo-log"
    And the agent_run line counts the question, 2 steps and the tool "get_employee"
    And the audit line records the tool call to "get_employee" for "EMP-0004"
    And no log line contains the question or the answer

  Scenario: An unexpected error returns 500 without internal details
    Given the observed HR assistant is running with a model that fails
    When I ask about EMP-0004 with the request id "demo-err"
    Then the response status is 500
    And the body says "internal error" with the request id "demo-err"
    And the log has an error line of type "RuntimeError" without the error message

  Scenario: Metrics report requests, latency, tokens and the SLO after a question
    Given the observed HR assistant is running
    When I ask about EMP-0004 with the request id "demo-metrics"
    And I read the metrics
    Then the metrics count 1 request and an error rate of 0.0
    And the metrics tokens match the tokens of the answer
    And the SLO target is 2000 ms and it is met

  Scenario: The SLO is not met when requests are slower than the target
    Given the observed HR assistant has an SLO of 100 ms and a model that takes 500 ms per call
    When I ask about EMP-0004 with the request id "demo-slow"
    And I read the metrics
    Then the latency p95 is 1000.0 ms
    And the SLO is not met

  Scenario: The home page shows the request id of each answer
    Given the observed HR assistant is running
    When I open the home page
    Then the page shows the request id and never uses innerHTML
