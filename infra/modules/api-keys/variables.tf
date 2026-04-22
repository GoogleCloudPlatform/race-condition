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

variable "compute_sa" {
  description = "Compute SA member string"
  type        = string
}

variable "agent_engine_sa" {
  description = "Agent Engine SA member string"
  type        = string
}

variable "backend_writers" {
  description = "Developer users for secret accessor IAM"
  type        = list(string)
  default     = []
}

variable "maps_mcp_users" {
  description = "Maps MCP users for secret accessor IAM"
  type        = list(string)
  default     = []
}
