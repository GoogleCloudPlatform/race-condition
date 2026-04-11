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

resource "google_alloydb_cluster" "cluster" {
  cluster_id      = var.cluster_id
  location        = var.region
  project         = var.project_id
  deletion_policy = "FORCE"

  network_config {
    network = var.vpc_id
  }

  initial_user {
    user     = "postgres"
    password = var.initial_password
  }
}

resource "google_alloydb_instance" "primary" {
  cluster       = google_alloydb_cluster.cluster.name
  instance_id   = var.instance_id
  instance_type = "PRIMARY"

  machine_config {
    cpu_count = var.cpu_count
  }

  network_config {
    enable_public_ip = true
  }

  database_flags = {
    "password.enforce_complexity" = "on"
    "alloydb.iam_authentication"  = "on"
  }

  client_connection_config {
    require_connectors = false
    ssl_config {
      ssl_mode = "ENCRYPTED_ONLY"
    }
  }
}

# Secret Manager: AlloyDB password
resource "google_secret_manager_secret" "db_password" {
  secret_id = "am-db-password"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = google_alloydb_cluster.cluster.initial_user[0].password
}

resource "google_secret_manager_secret_iam_member" "db_password_compute_accessor" {
  secret_id = google_secret_manager_secret.db_password.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.compute_sa
}

resource "google_secret_manager_secret_iam_member" "db_password_agent_engine_accessor" {
  secret_id = google_secret_manager_secret.db_password.secret_id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.agent_engine_sa_email}"
}

# Grant AlloyDB service agent Vertex AI access for google_ml_integration
# (auto-embeddings via gemini-embedding-001)
resource "google_project_iam_member" "alloydb_sa_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-alloydb.iam.gserviceaccount.com"
}

# IAM-based database users
locals {
  iam_user_emails = [
    for m in var.iam_users : trimprefix(m, "user:")
    if startswith(m, "user:")
  ]
}

resource "google_alloydb_user" "iam_developers" {
  for_each = toset(local.iam_user_emails)

  cluster   = google_alloydb_cluster.cluster.name
  user_id   = each.value
  user_type = "ALLOYDB_IAM_USER"

  lifecycle {
    ignore_changes = [database_roles]
  }

  depends_on = [google_alloydb_instance.primary]
}
