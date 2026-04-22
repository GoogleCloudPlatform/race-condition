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

output "vpc_id" {
  value = google_compute_network.main_vpc.id
}

output "vpc_name" {
  value = google_compute_network.main_vpc.name
}

output "vpc_self_link" {
  value = google_compute_network.main_vpc.self_link
}

output "serverless_subnet_id" {
  value = google_compute_subnetwork.serverless_subnet.id
}

output "serverless_subnet_name" {
  value = google_compute_subnetwork.serverless_subnet.name
}

output "private_vpc_connection_id" {
  description = "ID of the private VPC connection (for depends_on in downstream modules)"
  value       = google_service_networking_connection.private_vpc_connection.id
}

output "nat_router_name" {
  value = google_compute_router_nat.nat.name
}

output "psc_network_attachment" {
  description = "PSC network attachment for Agent Engine (Reasoning Engine)"
  value       = google_compute_network_attachment.re_psc_attachment.id
}
