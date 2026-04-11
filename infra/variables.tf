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

# =============================================================================
# Required Variables
# =============================================================================

variable "project_id" {
  description = "GCP project ID for the OSS deployment"
  type        = string
}

variable "region" {
  description = "GCP region for all resources"
  type        = string
  default     = "us-central1"
}

# =============================================================================
# Feature Toggles
# =============================================================================

variable "enable_alloydb" {
  description = "Use AlloyDB instead of Cloud SQL PostgreSQL (more expensive, more features)"
  type        = bool
  default     = false
}

variable "enable_gke" {
  description = "Deploy GKE cluster for runner_gke workloads (GPU support)"
  type        = bool
  default     = false
}

variable "enable_runner_cloudrun" {
  description = "Deploy LLM-powered runner as a Cloud Run service. Used by CI/CD deploy scripts to gate the runner_cloudrun Docker build and Cloud Run service deployment."
  type        = bool
  default     = false
}

variable "enable_maps_api_key" {
  description = "Create Maps API key in Secret Manager (requires Maps/Places/Weather API access)"
  type        = bool
  default     = false
}

variable "enable_monitoring" {
  description = "Deploy Cloud Monitoring alerts and uptime checks"
  type        = bool
  default     = false
}

# =============================================================================
# IAM
# =============================================================================

variable "developers" {
  description = "List of developer principals (format: user:email@domain)"
  type        = list(string)
  default     = []
}

variable "agent_engine_sa_users" {
  description = "Additional principals that can act as the Agent Engine SA"
  type        = list(string)
  default     = []
}

# =============================================================================
# Database
# =============================================================================

variable "db_initial_password" {
  description = "Initial password for the database (Cloud SQL or AlloyDB)"
  type        = string
  sensitive   = true
}

# =============================================================================
# Monitoring (when enabled)
# =============================================================================

variable "alert_email" {
  description = "Email address for monitoring alert notifications"
  type        = string
  default     = ""
}
