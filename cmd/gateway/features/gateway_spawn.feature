Feature: Batch Spawn API
  As a tester UI client
  I need to spawn multiple agent sessions in a single HTTP request
  So the gateway orchestrates them without requiring per-agent WebSocket connections

  Scenario: Spawn a single agent session
    Given the gateway is running with the simulator in the catalog
    When I spawn 1 "simulator" agent
    Then the response status should be 200
    And the spawn response should contain 1 session
    And each spawned session should have a valid UUID and agent type "simulator"

  Scenario: Spawn multiple sessions of the same agent type
    Given the gateway is running with the simulator in the catalog
    When I spawn 3 "simulator" agents
    Then the response status should be 200
    And the spawn response should contain 3 sessions
    And each spawned session should have a valid UUID and agent type "simulator"

  Scenario: Batch spawn across multiple agent types
    Given the gateway is running with multiple agents in the catalog
    When I batch spawn agents:
      | agentType | count |
      | simulator | 2     |
      | planner   | 1     |
    Then the response status should be 200
    And the spawn response should contain 3 sessions

  Scenario: Spawn with invalid agent type returns error
    Given the gateway is running with the simulator in the catalog
    When I spawn 1 "nonexistent" agent
    Then the response status should be 400

  Scenario: Spawn with zero count returns error
    Given the gateway is running with the simulator in the catalog
    When I spawn 0 "simulator" agents
    Then the response status should be 400
