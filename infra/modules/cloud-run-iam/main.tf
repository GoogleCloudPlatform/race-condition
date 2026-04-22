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

# Service-level IAM bindings for Cloud Run services.
#
# Replaces the `gcloud run services add-iam-policy-binding` shim that
# was previously in scripts/oss/templates/scripts/deploy/deploy.py.
#
# Defense in depth: the iam module ALSO grants project-level
# roles/run.invoker to the AE SA. Project-level grants have shown
# propagation timing issues for AE workloads on cold project bring-up,
# so this service-level grant is the authoritative one.

# ---------------------------------------------------------------------------
# Gateway: invoked by AE agents (planner, simulator) and by other Cloud
# Run services (push subscription delivery, frontend ingress).
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "gateway_ae_invoker" {
  project  = var.project_id
  location = var.region
  name     = var.service_names["gateway"]
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.agent_engine_sa_email}"
}

resource "google_cloud_run_v2_service_iam_member" "gateway_compute_invoker" {
  project  = var.project_id
  location = var.region
  name     = var.service_names["gateway"]
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.compute_sa_email}"
}

# ---------------------------------------------------------------------------
# Runners: invoked by the gateway via Pub/Sub push subscriptions
# (which are configured to use the compute SA as the OIDC identity).
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "runner_autopilot_compute" {
  project  = var.project_id
  location = var.region
  name     = var.service_names["runner_autopilot"]
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.compute_sa_email}"
}

resource "google_cloud_run_v2_service_iam_member" "runner_cloudrun_compute" {
  project  = var.project_id
  location = var.region
  name     = var.service_names["runner_cloudrun"]
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.compute_sa_email}"
}

# ---------------------------------------------------------------------------
# Public web UIs: frontend (end-user demo), admin (admin dashboard),
# dash (live telemetry), tester (manual A2A poke).
#
# Gated by var.public_uis_unauthenticated so production-like deployments
# can lock them down behind IAP or per-user OIDC instead.
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  count = var.public_uis_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_names["frontend"]
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "admin_public" {
  count = var.public_uis_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_names["admin"]
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "dash_public" {
  count = var.public_uis_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_names["dash"]
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "tester_public" {
  count = var.public_uis_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = var.service_names["tester"]
  role     = "roles/run.invoker"
  member   = "allUsers"
}
