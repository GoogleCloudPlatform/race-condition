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

variable "project_number" {
  description = "GCP project number (for service agent IAM bindings)"
  type        = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "vpc_name" {
  description = "Name of the VPC network"
  type        = string
  default     = "race-condition-vpc"
}

variable "serverless_subnet_cidr" {
  description = "CIDR range for serverless subnet"
  type        = string
  default     = "10.8.0.0/22"
}

variable "private_ip_prefix_length" {
  description = "Prefix length for Private Services Access IP allocation"
  type        = number
  default     = 16
}
