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
  description = "Main VPC network ID"
  type        = string
}

variable "vpc_name" {
  description = "Main VPC network name"
  type        = string
}

variable "model_storage_bucket" {
  description = "GCS bucket name for model weights (from gke-model-serving module)"
  type        = string
}

variable "subnet_cidr" {
  type    = string
  default = "10.9.0.0/22"
}

variable "pod_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "service_cidr" {
  type    = string
  default = "10.21.0.0/20"
}

variable "cpu_min_nodes" {
  type    = number
  default = 7
}

variable "cpu_max_nodes" {
  type    = number
  default = 70
}

variable "gpu_min_nodes" {
  description = "Min GPU nodes (used when gpu_use_reservation is false)"
  type        = number
  default     = 0
}

variable "gpu_max_nodes" {
  description = "Max GPU nodes (used when gpu_use_reservation is false)"
  type        = number
  default     = 25
}

variable "gpu_zone" {
  description = "Specific zone for GPU nodes (e.g., us-central1-a). Defaults to {region}-a."
  type        = string
  default     = ""
}

variable "gpu_use_reservation" {
  description = "Use GPU reservations instead of flex-start autoscaling"
  type        = bool
  default     = false
}

variable "gpu_node_count" {
  description = "Fixed GPU node count (used when gpu_use_reservation is true)"
  type        = number
  default     = 50
}

variable "gpu_enable_gvnic" {
  description = "Enable gVNIC on GPU nodes"
  type        = bool
  default     = false
}
