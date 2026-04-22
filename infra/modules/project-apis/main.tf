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

data "google_project" "project" {
  project_id = var.project_id
}

resource "google_project_service" "services" {
  for_each           = toset(var.services)
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "time_sleep" "api_propagation" {
  depends_on      = [google_project_service.services]
  create_duration = "60s"
}

resource "google_storage_bucket" "staging" {
  depends_on = [time_sleep.api_propagation]

  name                        = "${var.project_id}-staging"
  project                     = var.project_id
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
}

resource "google_artifact_registry_repository" "cloudrun" {
  depends_on = [time_sleep.api_propagation]

  project       = var.project_id
  location      = var.region
  repository_id = "cloudrun"
  description   = "Cloud Run container registry"
  format        = "DOCKER"
}
