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
# Terraform Backend Configuration (partial -- bucket supplied at init time)
# =============================================================================
#
# Empty (partial) GCS backend declaration. The bucket and prefix are
# supplied at `terraform init` time via -backend-config flags so the
# same module checkout works across multiple OSS projects without
# editing this file.
#
# The Cloud Build orchestrator (cloudbuild-bootstrap.yaml in the OSS
# repo) creates the bucket if missing and invokes:
#   terraform init \
#     -backend-config="bucket=${PROJECT_ID}-tf-state" \
#     -backend-config="prefix=oss/state"
#
# Single-developer local deploys can skip remote state entirely with:
#   terraform init -backend=false
# which falls back to the local terraform.tfstate file. (Note: tests in
# tests/*.tftest.hcl already pass -backend=false implicitly.)
# =============================================================================

terraform {
  backend "gcs" {}
}
