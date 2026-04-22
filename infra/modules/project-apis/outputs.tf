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

output "project_number" {
  value = data.google_project.project.number
}

output "staging_bucket" {
  value = google_storage_bucket.staging.name
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.cloudrun.repository_id}"
}

output "services" {
  description = "Map of enabled services for depends_on references"
  value       = google_project_service.services
}

output "apis_ready" {
  description = "Dependency anchor - all APIs enabled and propagated"
  value       = time_sleep.api_propagation.id
}
