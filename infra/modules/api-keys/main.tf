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

resource "google_apikeys_key" "marathon_planner" {
  name         = "marathon-planner-key"
  display_name = "Marathon Planner Key"
  project      = var.project_id

  restrictions {
    api_targets {
      service = "mapstools.googleapis.com"
    }
    api_targets {
      service = "places.googleapis.com"
    }
    api_targets {
      service = "weather.googleapis.com"
    }
  }
}

resource "google_secret_manager_secret" "maps_api_key" {
  secret_id = "maps-api-key"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "maps_api_key_v1" {
  secret      = google_secret_manager_secret.maps_api_key.id
  secret_data = google_apikeys_key.marathon_planner.key_string
}

resource "google_secret_manager_secret_iam_member" "compute_sa_maps_api_key_accessor" {
  secret_id = google_secret_manager_secret.maps_api_key.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.compute_sa
}

resource "google_secret_manager_secret_iam_member" "agent_engine_sa_maps_api_key_accessor" {
  secret_id = google_secret_manager_secret.maps_api_key.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.agent_engine_sa
}

resource "google_secret_manager_secret_iam_member" "developer_maps_api_key_accessor" {
  for_each  = toset(var.backend_writers)
  secret_id = google_secret_manager_secret.maps_api_key.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}

resource "google_secret_manager_secret_iam_member" "maps_mcp_user_maps_api_key_accessor" {
  for_each  = toset(var.maps_mcp_users)
  secret_id = google_secret_manager_secret.maps_api_key.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}
