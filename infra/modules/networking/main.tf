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

resource "google_compute_network" "main_vpc" {
  name                    = var.vpc_name
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "serverless_subnet" {
  name                     = "serverless-subnet"
  ip_cidr_range            = var.serverless_subnet_cidr
  region                   = var.region
  network                  = google_compute_network.main_vpc.id
  project                  = var.project_id
  purpose                  = "PRIVATE"
  private_ip_google_access = true
}

resource "google_compute_global_address" "private_ip_alloc" {
  name          = "private-ip-alloc"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_ip_prefix_length
  network       = google_compute_network.main_vpc.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.main_vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
}

resource "google_compute_network_attachment" "re_psc_attachment" {
  name                  = "psc-re-attachment"
  region                = var.region
  connection_preference = "ACCEPT_AUTOMATIC"
  subnetworks           = [google_compute_subnetwork.serverless_subnet.id]
  project               = var.project_id
}

resource "google_project_iam_member" "re_service_agent_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "ai_platform_service_agent_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:service-${var.project_number}@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "google_apis_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:${var.project_number}@cloudservices.gserviceaccount.com"
}

resource "google_compute_router" "router" {
  name    = "nat-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.main_vpc.id
}

# Grant Service Networking service agent the servicenetworking.serviceAgent role.
# Required for Private Services Access (VPC peering for Redis/AlloyDB).
resource "google_project_iam_member" "service_networking_agent" {
  project = var.project_id
  role    = "roles/servicenetworking.serviceAgent"
  member  = "serviceAccount:service-${var.project_number}@service-networking.iam.gserviceaccount.com"
}

resource "google_compute_router_nat" "nat" {
  name                               = "cloud-nat"
  project                            = var.project_id
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
