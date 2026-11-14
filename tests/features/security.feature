Feature: Production security
  Only clients with an API key can ask, nobody can flood the assistant,
  and production refuses to start with unsafe settings.

  Scenario: Asking without an API key is rejected
    Given the secured HR assistant is running
    When I ask a question without an API key
    Then the response status is 401
    And the body says "invalid or missing API key"

  Scenario: Asking with a wrong API key is rejected
    Given the secured HR assistant is running
    When I ask a question with the API key "not-the-right-key-123"
    Then the response status is 401
    And the body says "invalid or missing API key"

  Scenario: Health, the page and the docs need no key
    Given the secured HR assistant is running
    Then the public paths "/, /health, /docs, /openapi.json" answer 200 without a key

  Scenario: Metrics need a key
    Given the secured HR assistant is running
    When I read the metrics without an API key
    Then the response status is 401

  Scenario: The client name is logged and the key never is
    Given the secured HR assistant is running
    When I ask a question with the valid API key
    Then the response status is 200
    And the request, audit and agent_run lines name the client "tester"
    And the API key appears nowhere in the log

  Scenario: A client over the limit waits until the minute is over
    Given the secured HR assistant is running with a limit of 2 requests per minute
    When I ask 3 questions with the valid API key
    Then the statuses are "200, 200, 429"
    And the last response says "rate limit exceeded" with a Retry-After of 60 seconds
    When the clock advances 60 seconds and I ask again
    Then the response status is 200

  Scenario Outline: Production refuses to start with unsafe settings
    Given a production environment with <problem>
    When the assistant starts
    Then it refuses to start naming "<variable>" without showing the key

    Examples:
      | problem                          | variable       |
      | the fake model                   | MODEL_PROVIDER |
      | no API keys                      | API_KEYS       |
      | a key of 15 characters           | API_KEYS       |
      | tracing that shows the inputs    | HIDE_INPUTS    |
