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
# Core Outputs
# =============================================================================

output "project_id" {
  description = "GCP project ID"
  value       = var.project_id
}

output "region" {
  description = "GCP region"
  value       = var.region
}

output "project_number" {
  description = "GCP project number"
  value       = module.project_apis.project_number
}

output "artifact_registry_url" {
  description = "Artifact Registry URL for Docker images"
  value       = module.project_apis.artifact_registry_url
}

# =============================================================================
# Networking
# =============================================================================

output "vpc_id" {
  description = "VPC network ID"
  value       = module.networking.vpc_id
}

output "vpc_name" {
  description = "VPC network name"
  value       = module.networking.vpc_name
}

# =============================================================================
# Redis
# =============================================================================

output "redis_host" {
  description = "Redis instance host"
  value       = module.redis.host
}

output "redis_port" {
  description = "Redis instance port"
  value       = module.redis.port
}

# =============================================================================
# Database
# =============================================================================

output "database_type" {
  description = "Database type in use (cloud-sql or alloydb)"
  value       = var.enable_alloydb ? "alloydb" : "cloud-sql"
}

output "database_ip" {
  description = "Database private IP address"
  value = var.enable_alloydb ? (
    length(module.alloydb) > 0 ? module.alloydb[0].ip_address : null
    ) : (
    length(module.cloud_sql_postgres) > 0 ? module.cloud_sql_postgres[0].private_ip_address : null
  )
}

output "database_connection_name" {
  description = "Cloud SQL connection name (only for Cloud SQL)"
  value       = !var.enable_alloydb && length(module.cloud_sql_postgres) > 0 ? module.cloud_sql_postgres[0].connection_name : null
}

output "database_password_secret_id" {
  description = "Secret Manager secret ID for database password"
  value = var.enable_alloydb ? (
    length(module.alloydb) > 0 ? module.alloydb[0].password_secret_id : null
    ) : (
    length(module.cloud_sql_postgres) > 0 ? module.cloud_sql_postgres[0].password_secret_id : null
  )
}

# =============================================================================
# Pub/Sub
# =============================================================================

output "pubsub_topic" {
  description = "Pub/Sub orchestration topic name"
  value       = module.pubsub.topic_name
}

# =============================================================================
# IAM
# =============================================================================

output "compute_sa_email" {
  description = "Compute service account email"
  value       = module.iam.compute_sa_email
}

output "agent_engine_sa_email" {
  description = "Agent Engine service account email"
  value       = module.iam.agent_engine_sa_email
}

# =============================================================================
# Optional: GKE
# =============================================================================

output "gke_cluster_name" {
  description = "GKE cluster name (when enabled)"
  value       = var.enable_gke && length(module.gke_runner) > 0 ? "runner-cluster" : null
}

# =============================================================================
# Feature Toggles (for downstream tooling)
# =============================================================================

output "features" {
  description = "Map of enabled features"
  value = {
    alloydb         = var.enable_alloydb
    gke             = var.enable_gke
    runner_cloudrun = var.enable_runner_cloudrun
    maps_api_key    = var.enable_maps_api_key
    monitoring      = var.enable_monitoring
  }
}
