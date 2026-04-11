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

variable "region" {
  type = string
}

variable "service_names" {
  description = "Map of service key -> Cloud Run service name (from cloud-run-services.service_names)."
  type        = map(string)
  # Required keys: gateway, runner_autopilot, runner_cloudrun, frontend
}

variable "agent_engine_sa_email" {
  description = "Reasoning Engine service account that invokes the gateway."
  type        = string
}

variable "compute_sa_email" {
  description = "Default compute SA used as the runtime identity for Cloud Run services."
  type        = string
}

variable "frontend_unauthenticated" {
  description = "If true, bind allUsers as roles/run.invoker on frontend (public demo)."
  type        = bool
  default     = true
}
