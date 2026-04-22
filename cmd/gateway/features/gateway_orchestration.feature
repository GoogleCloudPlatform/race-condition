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

Feature: Orchestration Push
  As a simulation orchestrator
  I need the gateway to relay push events to agent endpoints
  So that agents can be poked to process queued work

  Scenario: Push event reaches agent endpoint
    Given the gateway is running
    And agent "runner_autopilot" is registered at a mock endpoint
    When a push event arrives for agent type "runner_autopilot"
    Then the mock agent endpoint receives the orchestration payload

  Scenario: Push event dispatches orchestration poke to local callable agent
    Given the gateway is running
    And agent "simulator" is registered as a callable agent at a mock endpoint
    When a push event arrives for agent type "simulator"
    Then the mock callable endpoint receives an orchestration poke

