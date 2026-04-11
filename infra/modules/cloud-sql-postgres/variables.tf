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
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "instance_name" {
  description = "Cloud SQL instance name"
  type        = string
  default     = "race-condition-postgres"
}

variable "database_version" {
  description = "PostgreSQL version"
  type        = string
  default     = "POSTGRES_16"
}

variable "tier" {
  description = "Machine tier for Cloud SQL instance"
  type        = string
  default     = "db-custom-1-3840"
}

variable "disk_size" {
  description = "Disk size in GB"
  type        = number
  default     = 10
}

variable "disk_type" {
  description = "Disk type (PD_SSD or PD_HDD)"
  type        = string
  default     = "PD_SSD"
}

variable "availability_type" {
  description = "Availability type (ZONAL or REGIONAL)"
  type        = string
  default     = "ZONAL"
}

variable "deletion_protection" {
  description = "Whether to enable deletion protection on the instance"
  type        = bool
  default     = false
}

variable "vpc_id" {
  description = "VPC network ID for private IP"
  type        = string
}

variable "private_vpc_connection_id" {
  description = "Private VPC connection ID (for depends_on)"
  type        = string
}

variable "compute_sa" {
  description = "Compute service account member string (serviceAccount:email)"
  type        = string
}

variable "agent_engine_sa_email" {
  description = "Agent Engine service account email for IAM database access"
  type        = string
}

variable "iam_users" {
  description = "List of IAM users for database access (format: user:email@domain)"
  type        = list(string)
  default     = []
}

variable "initial_password" {
  description = "Initial password for the postgres user"
  type        = string
  sensitive   = true
}
