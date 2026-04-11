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

Feature: Gateway Health
  As a platform operator
  I need the gateway health endpoint to report service status
  So that I can monitor the system reliably

  Scenario: Health probe returns OK
    Given the gateway is running
    When I send a GET request to "/health"
    Then the response status should be 200
    And the JSON response should have "status" equal to "ok"
    And the JSON response should have "service" equal to "gateway"

  Scenario: Health probe reports infrastructure status
    Given the gateway is running
    When I send a GET request to "/health"
    Then the response status should be 200
    And the JSON response at "infra" should exist
