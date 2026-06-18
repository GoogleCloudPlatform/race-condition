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

variable "compute_sa_email" {
  description = "Service account email used as the runtime identity for all services."
  type        = string
}

variable "vpc_network_name" {
  description = "VPC network name (self-link short form, e.g. 'race-condition-vpc')."
  type        = string
}

variable "vpc_subnet_name" {
  description = "Serverless subnet name for Cloud Run direct VPC egress."
  type        = string
}

variable "image_tags" {
  description = "Map of service name -> fully-qualified image URL with tag."
  type        = map(string)
  # Required keys: gateway, admin, dash, frontend, tester, runner_autopilot, runner_cloudrun
}

variable "redis_host" {
  type = string
}

variable "redis_port" {
  type    = number
  default = 6379
}

variable "database_ip" {
  description = "Private IP of the Cloud SQL / AlloyDB instance."
  type        = string
}

variable "database_secret_id" {
  description = "Secret Manager secret ID holding the database password."
  type        = string
}

variable "orchestration_topic" {
  description = "Pub/Sub topic name for cross-cluster orchestration ingress."
  type        = string
}

variable "telemetry_topic" {
  description = "Pub/Sub topic name for agent telemetry."
  type        = string
  default     = "agent-telemetry"
}

variable "embedding_backend" {
  description = "Embedding strategy for planner_with_memory tools. 'vertex_ai' for OSS Cloud SQL deploys; 'alloydb_ai' for AlloyDB ai.embedding() deploys."
  type        = string
  default     = "vertex_ai"
}

variable "agent_urls" {
  description = "Comma-separated bare URLs for AE-deployed agents (gateway AGENT_URLS env, e.g. https://ae1,https://ae2). The gateway parses these and discovers each agent's name from its /a2a/v1/card. Populated by Phase 4.5 cloud-build collect-ae-urls step."
  type        = string
  default     = ""
}

# Right-sized per docs/plans/2026-04-16-oss-right-sizing-plan.md.
# OSS targets minimum cost: scale-to-zero, platform-minimum CPU/memory.
variable "service_sizing" {
  description = "Per-service CPU/memory/min_instances/max_instances. Right-sized for OSS cost."
  type = map(object({
    cpu           = string
    memory        = string
    min_instances = number
    max_instances = number
  }))
  # Off-path services stay scale-to-zero (min 0) and single-instance (max 1)
  # for OSS cost control. The gateway is the hub for the WebSocket, A2A
  # discovery, and orchestration, so it is warmed (min 1) and allowed to
  # scale modestly (max 3) to absorb concurrent sessions. Memory differs by
  # runtime: Go services stay at 512Mi; Python+ADK runners need 1Gi (Phase 7
  # build #20 surfaced 512Mi OOM-killing the Python container during startup
  # imports before the port-8080 health probe ever opened).
  default = {
    gateway          = { cpu = "1", memory = "512Mi", min_instances = 1, max_instances = 3 }
    admin            = { cpu = "1", memory = "512Mi", min_instances = 0, max_instances = 1 }
    tester           = { cpu = "1", memory = "512Mi", min_instances = 0, max_instances = 1 }
    frontend         = { cpu = "1", memory = "512Mi", min_instances = 0, max_instances = 1 }
    dash             = { cpu = "1", memory = "512Mi", min_instances = 0, max_instances = 1 }
    runner_autopilot = { cpu = "1", memory = "1Gi", min_instances = 0, max_instances = 1 }
    runner_cloudrun  = { cpu = "1", memory = "1Gi", min_instances = 0, max_instances = 1 }
  }
}
