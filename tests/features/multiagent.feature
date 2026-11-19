Feature: A team of agents answers each question
  As an HR person
  I want a supervisor to send each question to the right specialist
  So that employee and policy questions get grounded, cheap and resilient answers

  Scenario: An employee question goes through guard, supervisor, directory and reviewer
    Given the multi-agent HR assistant is running
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 200
    And the "directory" specialist answered by the route "rule:employee"
    And the agents that ran are "guard, supervisor, directory, reviewer"
    And the answer mentions "Jorge Díaz"

  Scenario: A vacation question is answered by the policy specialist
    Given the multi-agent HR assistant is running
    When I ask "¿Cuántos días de vacaciones me tocan?"
    Then the response status is 200
    And the "policy" specialist answered by the route "rule:policy"
    And the tools used are "search_policy"
    And the answer mentions "12 días hábiles"

  Scenario: A repeated question without history comes from the cache for free
    Given the multi-agent HR assistant is running with "ANSWER_CACHE_TTL_SECONDS" set to "300"
    When I ask "¿Qué puesto tiene EMP-0005?"
    And I ask again "¿qué  puesto tiene emp-0005?"
    Then the second answer is the first one, from the cache and with cost 0
    And the metrics count 1 cache hit and 1 cache miss
    And both answers wrote an agent_run line

  Scenario: When the large model is down the small one answers
    Given the multi-agent HR assistant is running with "FAKE_UNAVAILABLE_MODELS" set to "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    When I ask "Compara a los empleados de Finanzas"
    Then the response status is 200
    And the fallback model "@cf/meta/llama-3.1-8b-instruct-fast" answered
    And the metrics count 1 fallback

  Scenario: When both models are down the API answers 502
    Given the multi-agent HR assistant is running with "FAKE_UNAVAILABLE_MODELS" set to "@cf/meta/llama-3.1-8b-instruct-fast,@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    When I ask "¿Quién es EMP-0004?"
    Then the response status is 502
    And the body is "model unavailable" with its request id
