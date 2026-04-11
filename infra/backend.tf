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

# =============================================================================
# Terraform Backend Configuration
# =============================================================================
#
# OSS deployments use a local backend by default. For team deployments,
# uncomment the GCS backend block and configure a bucket in your project.
#
# To create a state bucket:
#   gsutil mb -p YOUR_PROJECT_ID -l YOUR_REGION gs://YOUR_PROJECT_ID-terraform-state
#   gsutil versioning set on gs://YOUR_PROJECT_ID-terraform-state
# =============================================================================

# Default: local backend (single developer)
# terraform {
#   backend "gcs" {
#     bucket = "YOUR_PROJECT_ID-terraform-state"
#     prefix = "terraform/state/oss"
#   }
# }
