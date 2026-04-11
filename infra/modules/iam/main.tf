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

locals {
  compute_sa      = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
  build_sa        = "serviceAccount:${coalesce(var.code_project_number, var.project_number)}@cloudbuild.gserviceaccount.com"
  agent_engine_sa = "serviceAccount:agent-engine-sa@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_service_account" "agent_engine" {
  account_id   = "agent-engine-sa"
  display_name = "Race Condition Agent Engine (Reasoning Engine) Service Account"
  project      = var.project_id
}

resource "google_project_service_identity" "iap_sa" {
  provider = google-beta
  project  = var.project_id
  service  = "iap.googleapis.com"
}

# --- Compute SA Permissions ---

resource "google_project_iam_member" "iap_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_project_service_identity.iap_sa.email}"
}

resource "google_project_iam_member" "compute_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_ar_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_builds_builder" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.builder"
  member  = local.compute_sa
}

resource "google_project_iam_member" "compute_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = local.compute_sa
}

# --- Cross-project Cloud Build permissions ---

resource "google_project_iam_member" "build_ar_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = local.build_sa
}

resource "google_project_iam_member" "build_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = local.build_sa
}

resource "google_project_iam_member" "build_sa_viewer" {
  project = var.project_id
  role    = "roles/viewer"
  member  = local.build_sa
}

resource "google_project_iam_member" "build_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = local.build_sa
}

# --- Agent Engine Permissions ---

resource "google_project_iam_member" "agent_engine_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_viewer" {
  project = var.project_id
  role    = "roles/viewer"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_usage_consumer" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.agent_engine_sa
}

resource "google_service_account_iam_member" "agent_engine_sa_user" {
  for_each = toset(concat(
    [local.compute_sa, local.build_sa],
    var.agent_engine_sa_users,
  ))
  service_account_id = google_service_account.agent_engine.name
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}

# --- Cloud API Registry ---

resource "google_project_iam_member" "compute_api_registry_viewer" {
  project = var.project_id
  role    = "roles/cloudapiregistry.viewer"
  member  = local.compute_sa
}

resource "google_project_iam_member" "agent_engine_api_registry_viewer" {
  project = var.project_id
  role    = "roles/cloudapiregistry.viewer"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "developer_api_registry_viewer" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/cloudapiregistry.viewer"
  member   = each.value
}

# --- Developer Secret Manager Access ---

resource "google_project_iam_member" "developer_sm_viewer" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/secretmanager.viewer"
  member   = each.value
}

resource "google_project_iam_member" "developer_sm_accessor" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/secretmanager.secretAccessor"
  member   = each.value
}

# --- Maps MCP Users ---

resource "google_project_iam_member" "maps_mcp_api_registry_viewer" {
  for_each = toset(var.maps_mcp_users)
  project  = var.project_id
  role     = "roles/cloudapiregistry.viewer"
  member   = each.value
}

resource "google_project_iam_member" "maps_mcp_sm_viewer" {
  for_each = toset(var.maps_mcp_users)
  project  = var.project_id
  role     = "roles/secretmanager.viewer"
  member   = each.value
}

# --- AlloyDB Permissions ---

resource "google_project_iam_member" "compute_alloydb_admin" {
  project = var.project_id
  role    = "roles/alloydb.admin"
  member  = local.compute_sa
}

resource "google_project_iam_member" "developer_alloydb_client" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/alloydb.client"
  member   = each.value
}

resource "google_project_iam_member" "developer_alloydb_database_user" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/alloydb.databaseUser"
  member   = each.value
}

resource "google_project_iam_member" "developer_service_usage_consumer" {
  for_each = toset(var.backend_writers)
  project  = var.project_id
  role     = "roles/serviceusage.serviceUsageConsumer"
  member   = each.value
}

resource "google_project_iam_member" "frontend_alloydb_client" {
  for_each = toset(var.frontend_writers)
  project  = var.project_id
  role     = "roles/alloydb.client"
  member   = each.value
}

resource "google_project_iam_member" "frontend_alloydb_database_user" {
  for_each = toset(var.frontend_writers)
  project  = var.project_id
  role     = "roles/alloydb.databaseUser"
  member   = each.value
}

resource "google_project_iam_member" "frontend_service_usage_consumer" {
  for_each = toset(var.frontend_writers)
  project  = var.project_id
  role     = "roles/serviceusage.serviceUsageConsumer"
  member   = each.value
}

resource "google_project_iam_member" "agent_engine_alloydb_client" {
  project = var.project_id
  role    = "roles/alloydb.client"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_alloydb_database_user" {
  project = var.project_id
  role    = "roles/alloydb.databaseUser"
  member  = local.agent_engine_sa
}

resource "google_project_iam_member" "agent_engine_service_usage_consumer" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = local.agent_engine_sa
}

# --- Agent Platform Users (Agent Registry, Agent Identity, MCP Servers) ---
# Grants the IAM permissions required by the Vertex AI Agent Platform UI
# (`console.cloud.google.com/vertex-ai/agents/*`). Without these, the UI
# shows the "Ask your admin to enable required APIs" warning even when the
# APIs are enabled, because the surface checks the caller's IAM.

resource "google_project_iam_member" "agent_platform_user_aiplatform_user" {
  for_each = toset(var.agent_platform_users)
  project  = var.project_id
  role     = "roles/aiplatform.user"
  member   = each.value
}

resource "google_project_iam_member" "agent_platform_user_api_registry_viewer" {
  for_each = toset(var.agent_platform_users)
  project  = var.project_id
  role     = "roles/cloudapiregistry.viewer"
  member   = each.value
}

resource "google_project_iam_member" "agent_platform_user_service_usage_consumer" {
  for_each = toset(var.agent_platform_users)
  project  = var.project_id
  role     = "roles/serviceusage.serviceUsageConsumer"
  member   = each.value
}
