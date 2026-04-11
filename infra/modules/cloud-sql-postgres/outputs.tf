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

output "instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.postgres.name
}

output "connection_name" {
  description = "Cloud SQL connection name (project:region:instance)"
  value       = google_sql_database_instance.postgres.connection_name
}

output "private_ip_address" {
  description = "Private IP address of the Cloud SQL instance"
  value       = google_sql_database_instance.postgres.private_ip_address
}

output "database_name" {
  description = "Name of the agent_memory database"
  value       = google_sql_database.agent_memory.name
}

output "password_secret_id" {
  description = "Secret Manager secret ID for the database password"
  value       = google_secret_manager_secret.db_password.secret_id
}
