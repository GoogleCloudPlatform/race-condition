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

variable "zone_name" {
  description = "Name of the DNS managed zone resource"
  type        = string
}

variable "dns_name" {
  description = "DNS name for the managed zone (must end with trailing dot)"
  type        = string
}

variable "description" {
  description = "Description for the managed zone"
  type        = string
  default     = "Managed DNS zone"
}

variable "environment" {
  description = "Environment label (e.g., dev, prod-a, prod-b)"
  type        = string
}
