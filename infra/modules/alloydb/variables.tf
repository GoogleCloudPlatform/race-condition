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

variable "vpc_id" {
  description = "VPC network ID for AlloyDB network config"
  type        = string
}

variable "private_vpc_connection_id" {
  description = "Private VPC connection ID (for depends_on)"
  type        = string
}

variable "cluster_id" {
  type    = string
  default = "am-cluster"
}

variable "instance_id" {
  type    = string
  default = "agent-memory"
}

variable "cpu_count" {
  type    = number
  default = 4
}

variable "initial_password" {
  description = "Initial password for the postgres user"
  type        = string
  sensitive   = true
}

variable "compute_sa" {
  description = "Compute SA member string for secret accessor IAM"
  type        = string
}

variable "agent_engine_sa_email" {
  description = "Agent Engine SA email for secret accessor IAM"
  type        = string
}

variable "project_number" {
  description = "GCP project number (for AlloyDB service agent IAM)"
  type        = string
}

variable "iam_users" {
  description = "List of user members for IAM database access (format: user:email@domain)"
  type        = list(string)
  default     = []
}
