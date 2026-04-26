#!/usr/bin/env bash
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

# Unit tests for scripts/deploy.sh. Sources deploy.sh with DEPLOY_SH_NO_MAIN=1
# so helper functions load without firing the interactive prompts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SH="${SCRIPT_DIR}/deploy.sh"

PASS=0
FAIL=0

# Resolve <repo>/infra/variables.tf via git. Works for both the main
# checkout and any worktree, since `git rev-parse --show-toplevel`
# returns the worktree's own root. Override with DEPLOY_SH_TF_VARS_FILE
# if auto-detect ever drifts.
resolve_tf_vars_file() {
  if [[ -n "${DEPLOY_SH_TF_VARS_FILE:-}" ]]; then
    echo "$DEPLOY_SH_TF_VARS_FILE"
    return
  fi

  local repo_root
  repo_root=$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null) \
    || repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"

  if [[ -f "$repo_root/infra/variables.tf" ]]; then
    echo "$repo_root/infra/variables.tf"
    return
  fi

  return 1
}

# --- Test 1: region allowlist parity --------------------------------------
test_region_allowlist_matches_terraform() {
  local script_regions tf_regions tf_file
  if ! tf_file=$(resolve_tf_vars_file); then
    echo "SKIP test_region_allowlist_matches_terraform: TF variables.tf not found"
    return 0
  fi

  script_regions=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && \
                   allowed_regions | sort)

  # Parse the contains([...]) block under variable "region" {}.
  tf_regions=$(awk '
    /variable "region"/ {in_var=1}
    in_var && /contains\(\[/ {in_list=1; next}
    in_list && /\]/ {in_list=0; in_var=0}
    in_list {print}
  ' "$tf_file" | grep -oE '"[a-z0-9-]+"' | tr -d '"' | sort)

  if [[ -z "$tf_regions" ]]; then
    echo "FAIL test_region_allowlist_matches_terraform: parsed empty TF allowlist from $tf_file"
    return 1
  fi

  if [[ "$script_regions" == "$tf_regions" ]]; then
    echo "PASS test_region_allowlist_matches_terraform"
    return 0
  fi

  echo "FAIL test_region_allowlist_matches_terraform: drift detected"
  echo "  deploy.sh allowed_regions:"
  echo "$script_regions" | sed 's/^/    /'
  echo "  $tf_file variable \"region\" allowlist:"
  echo "$tf_regions" | sed 's/^/    /'
  return 1
}

# --- Test 2: build_submit_argv shape --------------------------------------
test_build_submit_argv_shape() {
  local actual expected
  actual=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && \
           build_submit_argv my-project us-east1)
  expected=$'gcloud\nbuilds\nsubmit\n--config=cloudbuild-bootstrap.yaml\n--project=my-project\n--region=us-east1\n--substitutions=_REGION=us-east1\n.'
  if [[ "$actual" == "$expected" ]]; then
    echo "PASS test_build_submit_argv_shape"
    return 0
  fi
  echo "FAIL test_build_submit_argv_shape: shape drift"
  diff <(echo "$expected") <(echo "$actual") || true
  return 1
}

# --- Test 3: required_apis pin --------------------------------------------
test_required_apis_list_is_complete() {
  # Pins the exact set of APIs that must be enabled BEFORE Cloud Build runs.
  local got want
  got=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && required_apis | sort | tr '\n' ',' )
  want="cloudbuild.googleapis.com,cloudresourcemanager.googleapis.com,compute.googleapis.com,iam.googleapis.com,run.googleapis.com,serviceusage.googleapis.com,"
  if [[ "$got" != "$want" ]]; then
    echo "FAIL: required_apis mismatch"
    echo "  got:  $got"
    echo "  want: $want"
    return 1
  fi
  echo "PASS test_required_apis_list_is_complete"
}

# --- Test 4: required_cloudbuild_sa_roles pin -----------------------------
test_required_cloudbuild_sa_roles_is_complete() {
  # Pins the IAM roles the cloudbuild SA needs to run TF apply.
  # roles/owner alone is INSUFFICIENT — these admin roles are required.
  local got want
  got=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && required_cloudbuild_sa_roles | sort | tr '\n' ',')
  want="roles/cloudbuild.builds.builder,roles/compute.networkAdmin,roles/iam.securityAdmin,roles/iam.serviceAccountAdmin,roles/owner,roles/resourcemanager.projectIamAdmin,roles/servicenetworking.networksAdmin,"
  if [[ "$got" != "$want" ]]; then
    echo "FAIL: required_cloudbuild_sa_roles mismatch"
    echo "  got:  $got"
    echo "  want: $want"
    return 1
  fi
  echo "PASS test_required_cloudbuild_sa_roles_is_complete"
}

# --- Test 5: preflight_api_enable_argv shape ------------------------------
test_preflight_argv_for_api_enable() {
  # Pin: preflight_api_enable_argv "myproj" "compute.googleapis.com" emits
  # the exact gcloud invocation deploy.sh will make.
  local argv
  argv=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && \
         preflight_api_enable_argv "myproj" "compute.googleapis.com" | tr '\n' ' ')
  local want="gcloud services enable compute.googleapis.com --project=myproj --quiet "
  if [[ "$argv" != "$want" ]]; then
    echo "FAIL: preflight_api_enable_argv mismatch"
    echo "  got:  $argv"
    echo "  want: $want"
    return 1
  fi
  echo "PASS test_preflight_argv_for_api_enable"
}

# --- Test 6: cloudbuild_sa_emails pin -------------------------------------
test_cloudbuild_sa_emails_covers_both_defaults() {
  # Pin: regional Cloud Build uses the COMPUTE default SA, global Cloud
  # Build uses the LEGACY cloudbuild SA. Preflight grants to BOTH so it
  # works regardless of which one a given project's Cloud Build resolves
  # to. Both must be emitted, in this order.
  local got want
  got=$(DEPLOY_SH_NO_MAIN=1 source "$DEPLOY_SH" && \
        cloudbuild_sa_emails "12345" | tr '\n' ',')
  want="12345-compute@developer.gserviceaccount.com,12345@cloudbuild.gserviceaccount.com,"
  if [[ "$got" != "$want" ]]; then
    echo "FAIL: cloudbuild_sa_emails mismatch"
    echo "  got:  $got"
    echo "  want: $want"
    return 1
  fi
  echo "PASS test_cloudbuild_sa_emails_covers_both_defaults"
}

# --- Runner ---------------------------------------------------------------
run() {
  local name="$1"
  if "$name"; then
    PASS=$((PASS + 1))
  else
    FAIL=$((FAIL + 1))
  fi
}

run test_region_allowlist_matches_terraform
run test_build_submit_argv_shape
run test_required_apis_list_is_complete
run test_required_cloudbuild_sa_roles_is_complete
run test_preflight_argv_for_api_enable
run test_cloudbuild_sa_emails_covers_both_defaults

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Results: ✅ $PASS passed, ❌ $FAIL failed"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
[[ $FAIL -eq 0 ]]
