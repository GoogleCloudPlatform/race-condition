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

Feature: Session Management
  As a simulation operator
  I need the gateway to manage agent sessions
  So that I can track and control simulation participants

  Scenario: List sessions returns tracked sessions
    Given the gateway is running
    And a session "sess-A" is tracked
    When I send a GET request to "/api/v1/sessions"
    Then the response status should be 200
    And the JSON response should contain "sess-A"

  Scenario: Flush clears all sessions
    Given the gateway is running
    And a session "sess-B" is tracked
    When I send a POST request to "/api/v1/sessions/flush"
    Then the response status should be 200
    And listing sessions returns an empty list
