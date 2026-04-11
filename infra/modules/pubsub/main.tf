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

resource "google_pubsub_topic" "specialist_orchestration" {
  name    = "specialist-orchestration"
  project = var.project_id

  labels = {
    purpose = "specialist-agent-orchestration"
  }
}

resource "google_pubsub_subscription" "gateway_push_orchestration" {
  name    = "gateway-push-orchestration"
  topic   = google_pubsub_topic.specialist_orchestration.name
  project = var.project_id

  # Use the internal Cloud Run URL to bypass IAP. The IAP-protected custom
  # domain (gateway.<domain_suffix>) requires OIDC audience=IAP_CLIENT_ID,
  # which is unreliable for PubSub push. The internal .run.app URL accepts
  # requests directly with standard OIDC authentication.
  push_config {
    push_endpoint = "https://gateway-${var.project_number}.${var.region}.run.app/api/v1/orchestration/push"

    oidc_token {
      service_account_email = var.compute_sa_email
      audience              = "https://gateway-${var.project_number}.${var.region}.run.app"
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
}

resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.compute_sa_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
