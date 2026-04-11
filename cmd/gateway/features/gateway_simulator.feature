# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

Feature: Simulator Agent Integration
  As a simulation operator
  I need the gateway to discover and route to the simulator agent
  So that the simulator can orchestrate the race lifecycle

  Scenario: Simulator agent is discoverable via catalog
    Given the gateway is running with the simulator in the catalog
    When I send a GET request to "/api/v1/agent-types"
    Then the response status should be 200
    And the JSON response should contain "simulator"

  Scenario: Orchestration push reaches the simulator agent
    Given the gateway is running
    And agent "simulator" is registered at a mock endpoint
    When a push event arrives for agent type "simulator"
    Then the mock agent endpoint receives the orchestration payload
