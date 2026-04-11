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

variable "project_number" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "backend_writers" {
  description = "List of users with developer access (format: user:email@domain)"
  type        = list(string)
  default     = []
}

variable "frontend_writers" {
  description = "Frontend developers with AlloyDB-only access (format: user:email@domain)"
  type        = list(string)
  default     = []
}

variable "maps_mcp_users" {
  description = "Users with Maps MCP access"
  type        = list(string)
  default     = []
}

variable "code_project_number" {
  description = "Project number of the code/management project (for cross-project Cloud Build SA)"
  type        = string
  default     = ""  # falls back to var.project_number when empty
}

variable "agent_engine_sa_users" {
  description = "Additional principals that can act as the agent engine SA"
  type        = list(string)
  default     = []
}

variable "agent_platform_users" {
  description = "Users granted Vertex AI Agent Platform access (Agent Registry, Agent Identity, MCP Servers, Endpoints)"
  type        = list(string)
  default     = []
}
