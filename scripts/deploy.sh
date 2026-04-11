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

# scripts/deploy.sh -- interactive one-click deploy for Race Condition (OSS).
#
# Wraps cloudbuild-bootstrap.yaml in a Cloud-Shell-friendly UX:
#   1. Cost confirmation
#   2. Project selection (free-text or pick from gcloud)
#   3. Region selection (curated allowlist, must match TF variable "region")
#   4. Final confirmation
#   5. gcloud builds submit
#
# Two helper functions are factored out for unit testing in deploy_test.sh:
#   - allowed_regions       -- emits the curated region list, one per line
#   - build_submit_argv     -- emits the gcloud argv, one arg per line
# Both are pure (no side effects) and sourceable via DEPLOY_SH_NO_MAIN=1.

set -euo pipefail

# Sourceable for testing: emits the curated region allowlist, one per line.
# MUST stay in lockstep with code-infra/projects/oss/variables.tf's
# variable "region" validation block. deploy_test.sh enforces parity.
allowed_regions() {
  printf '%s\n' \
    us-central1 us-east1 us-east4 us-west1 \
    europe-west1 europe-west4 \
    asia-southeast1 asia-northeast1
}

# Sourceable for testing: emits the gcloud builds submit argv,
# one arg per line. Pure function, no side effects.
#
# Note: cloudbuild-bootstrap.yaml declares only _REGION and _STATE_BUCKET
# substitutions. PROJECT_ID flows in via --project, NOT a substitution.
# Passing an undeclared substitution makes Cloud Build reject the job.
build_submit_argv() {
  local project="$1" region="$2"
  printf '%s\n' \
    gcloud builds submit \
    --config=cloudbuild-bootstrap.yaml \
    --project="$project" \
    --region="$region" \
    --substitutions="_REGION=$region" \
    .
}

# Sourceable for testing: emits the APIs that must be enabled BEFORE Cloud
# Build can submit + run the bootstrap. TF's module.project_apis enables
# everything else at apply time, but we need this minimum set first.
required_apis() {
  printf '%s\n' \
    cloudbuild.googleapis.com \
    cloudresourcemanager.googleapis.com \
    compute.googleapis.com \
    iam.googleapis.com \
    run.googleapis.com \
    serviceusage.googleapis.com
}

# Sourceable for testing: emits the IAM roles the Cloud Build default SA
# needs to run TF apply. roles/owner alone is INSUFFICIENT — see Phase 7
# verification gotcha #23 in docs/plans/2026-04-17-oss-one-shot-deploy.md
# for the breakdown of why each role is required.
required_cloudbuild_sa_roles() {
  printf '%s\n' \
    roles/cloudbuild.builds.builder \
    roles/compute.networkAdmin \
    roles/iam.securityAdmin \
    roles/iam.serviceAccountAdmin \
    roles/owner \
    roles/resourcemanager.projectIamAdmin \
    roles/servicenetworking.networksAdmin
}

# Pure helper: emits the gcloud argv for enabling one API on one project.
# One arg per line so the test can pin the exact shape.
preflight_api_enable_argv() {
  local project="$1" api="$2"
  printf '%s\n' \
    gcloud services enable "$api" \
    --project="$project" \
    --quiet
}

# Sourceable for testing: emits the service account emails that need the
# required_cloudbuild_sa_roles bindings, given a project number.
#
# Why two SAs: regional Cloud Build (us-central1, eu-west1, etc.) defaults
# to the COMPUTE default SA (<PNUM>-compute@developer.gserviceaccount.com)
# while global Cloud Build uses the legacy CLOUDBUILD default SA
# (<PNUM>@cloudbuild.gserviceaccount.com). We grant to BOTH so the
# preflight is robust regardless of which one a given project's Cloud
# Build resolves to. The over-permission is small (idle service accounts
# don't pay cost) and the alternative — detecting which SA Cloud Build
# will use before submitting — has chicken-and-egg issues.
cloudbuild_sa_emails() {
  local pnum="$1"
  printf '%s\n' \
    "${pnum}-compute@developer.gserviceaccount.com" \
    "${pnum}@cloudbuild.gserviceaccount.com"
}

# Idempotently grants the Cloud Build default service accounts the roles
# they need to run the bootstrap, and enables the APIs the bootstrap
# consumes (TF will enable the rest at apply time). Safe to re-run.
preflight_project() {
  local project="$1"
  local pnum
  pnum=$(gcloud projects describe "$project" --format='value(projectNumber)') || {
    echo "ERROR: cannot describe project $project — wrong gcloud auth?" >&2
    return 1
  }

  echo "🔧 Pre-flight: enabling required APIs on $project ..."
  while IFS= read -r api; do
    echo "   - $api"
    gcloud services enable "$api" --project="$project" --quiet
  done < <(required_apis)

  echo "🔧 Pre-flight: granting Cloud Build SAs required roles ..."
  while IFS= read -r sa; do
    echo " SA: $sa"
    while IFS= read -r role; do
      echo "   - $role"
      gcloud projects add-iam-policy-binding "$project" \
        --member="serviceAccount:$sa" \
        --role="$role" \
        --condition=None \
        --quiet >/dev/null
    done < <(required_cloudbuild_sa_roles)
  done < <(cloudbuild_sa_emails "$pnum")
  echo "✅ Pre-flight complete."
}

# Test harness opt-out: don't run interactive flow when sourced.
[[ "${DEPLOY_SH_NO_MAIN:-0}" == "1" ]] && return 0

# Refuse to run non-interactively (select prompts misbehave on piped stdin).
if [[ ! -t 0 ]]; then
  echo "ERROR: deploy.sh requires an interactive TTY (Cloud Shell or local terminal)." >&2
  exit 1
fi

# --- Phase 1: cost confirmation ------------------------------------------
cat <<'EOF'
====================================================
💰 This deploy will provision GCP resources that incur cost.
💸 Base infrastructure: ~$91/month
   - 1GB Memorystore (Redis)
   - db-custom-1-3840 Cloud SQL
   - Cloud NAT egress
   Compute scales to zero when idle (min_instances=0).
💸 Per-simulation cost: ~$3-4 in Gemini API calls.
💸 Tip: use the runner_autopilot variant (deterministic, zero LLM
   calls) to develop and test without API costs.
📝 Tear down with: cd infra && terraform destroy
====================================================
EOF
read -p "Proceed? (y/n) " -n 1 -r REPLY
echo
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 1; }

# --- Phase 2: project selection ------------------------------------------
PROJECT_ID=""
echo ""
echo "📁 Project Selection:"
PS3="Choose: "
select OPT in "Enter project ID" "Pick from list (gcloud projects list)"; do
  case "$OPT" in
    "Enter project ID")
      read -p "Project ID: " PROJECT_ID
      break
      ;;
    "Pick from list (gcloud projects list)")
      mapfile -t PROJS < <(gcloud projects list --limit=20 --format="value(projectId)")
      if [[ ${#PROJS[@]} -eq 0 ]]; then
        echo "No projects accessible to current gcloud auth. Falling back to manual entry."
        read -p "Project ID: " PROJECT_ID
      else
        select PROJECT_ID in "${PROJS[@]}"; do
          [[ -n "$PROJECT_ID" ]] && break
        done
      fi
      break
      ;;
    *)
      echo "Invalid choice."
      ;;
  esac
done
[[ -n "$PROJECT_ID" ]] || { echo "ERROR: project ID is required" >&2; exit 1; }

# --- Phase 3: region selection -------------------------------------------
echo ""
echo "🌐 Region Selection:"
mapfile -t REGIONS < <(allowed_regions)
PS3="Choose: "
select REGION in "${REGIONS[@]}"; do
  [[ -n "$REGION" ]] && break
done

# --- Phase 4: final confirmation -----------------------------------------
echo ""
echo "===================================================="
echo "🚀 About to deploy:"
echo "   Project: $PROJECT_ID"
echo "   Region:  $REGION"
echo "===================================================="
read -p "Confirm? (y/n) " -n 1 -r REPLY
echo
[[ $REPLY =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 1; }

# --- Phase 5: submit -----------------------------------------------------
echo ""
preflight_project "$PROJECT_ID"
echo "📦 Submitting Cloud Build job..."
mapfile -t ARGV < <(build_submit_argv "$PROJECT_ID" "$REGION")
echo "Running: ${ARGV[*]}"
exec "${ARGV[@]}"
