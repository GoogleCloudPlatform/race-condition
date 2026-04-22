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

resource "google_sql_database_instance" "postgres" {
  name                = var.instance_name
  project             = var.project_id
  region              = var.region
  database_version    = var.database_version
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.tier
    availability_type = var.availability_type
    disk_size         = var.disk_size
    disk_type         = var.disk_type
    edition           = "ENTERPRISE"

    ip_configuration {
      # Public IP enabled for Cloud SQL Auth Proxy access from Cloud Build
      # and Terraform runners (which lack VPC access). All connections go
      # through the proxy, which handles mTLS encryption. Cloud Run
      # services use the private IP via VPC for data-plane traffic.
      ipv4_enabled                                  = true
      private_network                               = var.vpc_id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }
  }

  depends_on = [var.private_vpc_connection_id]
}

resource "google_sql_database" "agent_memory" {
  name     = "agent_memory"
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
}

resource "google_sql_user" "postgres" {
  name     = "postgres"
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  password = var.initial_password
}

# IAM database user for Compute SA (Cloud Run services)
resource "google_sql_user" "compute_sa" {
  name     = trimsuffix(split(":", var.compute_sa)[1], ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

# IAM database user for Agent Engine SA
resource "google_sql_user" "agent_engine_sa" {
  name     = trimsuffix(var.agent_engine_sa_email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

# IAM database users for human developers
resource "google_sql_user" "iam_users" {
  for_each = toset(var.iam_users)

  name     = split(":", each.value)[1]
  instance = google_sql_database_instance.postgres.name
  project  = var.project_id
  type     = "CLOUD_IAM_USER"
}

# Grant Cloud SQL Client role to Compute SA
resource "google_project_iam_member" "compute_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = var.compute_sa
}

# Grant Cloud SQL Client role to Agent Engine SA
resource "google_project_iam_member" "agent_engine_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${var.agent_engine_sa_email}"
}

# Grant Cloud SQL Instance User role to Compute SA (for IAM auth)
resource "google_project_iam_member" "compute_cloudsql_instance_user" {
  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = var.compute_sa
}

# Grant Cloud SQL Instance User role to Agent Engine SA
resource "google_project_iam_member" "agent_engine_cloudsql_instance_user" {
  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${var.agent_engine_sa_email}"
}

# Store password in Secret Manager
resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "cloudsql-postgres-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = var.initial_password
}

resource "google_secret_manager_secret_iam_member" "compute_sa_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.compute_sa
}

resource "google_secret_manager_secret_iam_member" "agent_engine_sa_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.agent_engine_sa_email}"
}

# Grant the Cloud Build default compute SA access to the password secret.
# The schema-migration / seed-rules / embedding-backfill Cloud Build steps
# (defined in cloudbuild-bootstrap.yaml) read this secret to authenticate
# psql + asyncpg connections via cloud-sql-proxy.
resource "google_secret_manager_secret_iam_member" "cloudbuild_compute_sa_password_access" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.project_number}-compute@developer.gserviceaccount.com"
}

# NOTE: Schema migration, rule seeding, and embedding backfill are
# performed by dedicated Cloud Build steps (see cloudbuild-bootstrap.yaml
# in the backend repo) rather than TF null_resource provisioners. The
# hashicorp/terraform container is alpine-based and ships with neither
# psql nor cloud-sql-proxy, so local-exec here would fail. The Cloud
# Build steps reference schema_local.sql, seed_rules.sql, and
# embedding_backfill.py from this module's path.
