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

resource "google_secret_manager_secret" "iap_client_id" {
  secret_id = "iap-oauth2-client-id"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "iap_client_id_v1" {
  secret      = google_secret_manager_secret.iap_client_id.id
  secret_data = var.iap_oauth2_client_id
}

resource "google_secret_manager_secret" "iap_client_secret" {
  secret_id = "iap-oauth2-client-secret"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "iap_client_secret_v1" {
  secret      = google_secret_manager_secret.iap_client_secret.id
  secret_data = var.iap_oauth2_client_secret
}

resource "google_secret_manager_secret_iam_member" "compute_sa_client_id_accessor" {
  secret_id = google_secret_manager_secret.iap_client_id.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.compute_sa
}

resource "google_secret_manager_secret_iam_member" "compute_sa_client_secret_accessor" {
  secret_id = google_secret_manager_secret.iap_client_secret.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.compute_sa
}
