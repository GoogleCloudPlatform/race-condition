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

variable "project_id" {
  type = string
}

variable "environment" {
  description = "Environment name for display names (e.g., dev, prod-a)"
  type        = string
}

variable "alert_email" {
  type = string
}

variable "domain_suffix" {
  description = "Domain suffix for uptime check (e.g., dev.keynote2026.cloud-demos.goog). When empty, the gateway uptime check and its alert are skipped."
  type        = string
  default     = ""
}
