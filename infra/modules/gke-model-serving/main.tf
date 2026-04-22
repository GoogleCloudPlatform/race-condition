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

resource "google_compute_network" "model_serving" {
  name                    = var.vpc_name
  project                 = var.project_id
  auto_create_subnetworks = true
  mtu                     = 8896
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "gpu" {
  name          = "${var.name_prefix}-gpu"
  network       = google_compute_network.model_serving.id
  region        = var.region
  project       = var.project_id
  ip_cidr_range = "10.10.0.0/18"
}

resource "google_compute_subnetwork" "proxy" {
  name          = "${var.name_prefix}-proxy"
  network       = google_compute_network.model_serving.id
  region        = var.region
  project       = var.project_id
  ip_cidr_range = "172.16.0.0/26"
  purpose       = "REGIONAL_MANAGED_PROXY"
  role          = "ACTIVE"
}

resource "google_compute_firewall" "allow_icmp" {
  name        = "${var.name_prefix}-allow-icmp"
  network     = google_compute_network.model_serving.name
  project     = var.project_id
  description = "Allow ICMP from any source."
  direction   = "INGRESS"
  priority    = 1000

  allow {
    protocol = "icmp"
  }

  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow_internal" {
  name        = "${var.name_prefix}-allow-internal"
  network     = google_compute_network.model_serving.name
  project     = var.project_id
  description = "Allow all internal traffic within the network (e.g., instance-to-instance)."
  direction   = "INGRESS"
  priority    = 1000

  allow {
    protocol = "all"
  }

  source_ranges = ["172.16.0.0/12", "10.0.0.0/8"]
}

resource "google_storage_bucket" "model_storage" {
  name                        = "devkey-model-storage-${var.project_id}"
  project                     = var.project_id
  location                    = upper(var.region)
  uniform_bucket_level_access = true
}

resource "google_service_account" "gpu_reader" {
  account_id   = "gpu-reader-sa"
  display_name = "GPU Reader SA"
  description  = "Service account for GKE GPU workloads to read model weights from GCS"
  project      = var.project_id
}

resource "google_storage_bucket_iam_member" "gpu_reader_bucket_access" {
  bucket = google_storage_bucket.model_storage.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.gpu_reader.email}"
}

resource "google_storage_bucket_iam_member" "gke_node_bucket_access" {
  bucket = google_storage_bucket.model_storage.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:service-${var.project_number}@gcp-sa-gkenode.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "gpu_reader_workload_identity" {
  service_account_id = google_service_account.gpu_reader.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[default/default]"
}
