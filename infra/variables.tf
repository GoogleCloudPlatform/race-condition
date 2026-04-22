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
  description = "GCP region for all resources. Curated allowlist of regions where Cloud Run + Memorystore + Cloud SQL + Vertex AI are all available."
  type        = string
  default     = "us-central1"

  validation {
    condition = contains([
      "us-central1",
      "us-east1",
      "us-east4",
      "us-west1",
      "europe-west1",
      "europe-west4",
      "asia-southeast1",
      "asia-northeast1",
    ], var.region)
    error_message = "var.region must be one of: us-central1, us-east1, us-east4, us-west1, europe-west1, europe-west4, asia-southeast1, asia-northeast1 (regions where Cloud Run, Memorystore, Cloud SQL, and Vertex AI all coexist)."
  }
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

variable "enable_services" {
  description = "Deploy Cloud Run services and IAM bindings. Set false for the Phase 1 base-infra apply (before image builds); set true for the Phase 2 services apply (after images are pushed)."
  type        = bool
  default     = false
}

# =============================================================================
# Cloud Run services (gated by enable_services)
# =============================================================================

variable "image_tags" {
  description = "Map of service name -> fully-qualified image URL with tag. Required keys when enable_services=true: gateway, admin, dash, frontend, tester, runner_autopilot, runner_cloudrun. Populated by the Phase 4 Cloud Build orchestrator after images are built."
  type        = map(string)
  default     = {}
}

variable "embedding_backend" {
  description = "Embedding strategy for planner_with_memory. 'vertex_ai' for OSS Cloud SQL deploys; 'alloydb_ai' for AlloyDB deploys."
  type        = string
  default     = "vertex_ai"
}

variable "agent_urls" {
  description = "Comma-separated bare agent URLs threaded into the gateway's AGENT_URLS env (e.g. https://ae1,https://ae2). The gateway parses these and discovers each agent's name from its /a2a/v1/card. Populated by the Phase 4 collect-ae-urls step."
  type        = string
  default     = ""
}

variable "frontend_unauthenticated" {
  description = "Bind allUsers as roles/run.invoker on the frontend Cloud Run service (true for the OSS public demo)."
  type        = bool
  default     = true
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
  description = "Optional explicit password. If null, a random 32-char alphanumeric password is generated and persisted in TF state + Secret Manager (via the cloud-sql-postgres module)."
  type        = string
  sensitive   = true
  default     = null
}

# =============================================================================
# Monitoring (when enabled)
# =============================================================================

variable "alert_email" {
  description = "Email address for monitoring alert notifications"
  type        = string
  default     = ""
}
