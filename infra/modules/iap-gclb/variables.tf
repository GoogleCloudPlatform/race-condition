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

variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "environment" {
  description = "Environment name used in resource naming (e.g., dev, prod-a)"
  type        = string
}

variable "domain_suffix" {
  description = "Domain suffix (e.g., dev.keynote2026.cloud-demos.goog)"
  type        = string
}

variable "dns_zone_name" {
  description = "DNS managed zone name for A records"
  type        = string
}

variable "iap_oauth2_client_id" {
  type = string
}

variable "iap_oauth2_client_secret" {
  type      = string
  sensitive = true
}

variable "compute_sa" {
  description = "Compute SA member string for IAP access binding"
  type        = string
}

variable "iap_sa_email" {
  description = "IAP service identity email"
  type        = string
}

variable "iap_access_members" {
  description = "Members to grant IAP access (domains, SAs, users)"
  type        = list(string)
  default = [
    "domain:google.com",
    "domain:cloud-demos.goog",
    "domain:northkingdom.com",
  ]
}

variable "services" {
  description = "Map of service names to Cloud Run service names"
  type        = map(string)
  default = {
    "admin"    = "admin"
    "gateway"  = "gateway"
    "tester"   = "tester"
    "dash"     = "dash"
    "frontend" = "frontend"
  }
}
