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

# Service-level IAM binding tests. Locks in:
#   - Gateway: invokable by both AE SA (for AE -> Cloud Run) and compute
#     SA (for Cloud Run -> Cloud Run, e.g. push subscriptions).
#   - Runners: invokable by compute SA (gateway pushes orchestration
#     messages to them via Pub/Sub push subscriptions).
#   - Frontend: optional allUsers binding gated by frontend_unauthenticated.

variables {
  project_id            = "test-project"
  region                = "us-central1"
  agent_engine_sa_email = "ae@test-project.iam.gserviceaccount.com"
  compute_sa_email      = "compute@test-project.iam.gserviceaccount.com"
  service_names = {
    gateway          = "gateway"
    runner_autopilot = "runner-autopilot"
    runner_cloudrun  = "runner-cloudrun"
    frontend         = "frontend"
  }
}

run "gateway_has_both_invoker_bindings" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service_iam_member.gateway_ae_invoker.member == "serviceAccount:ae@test-project.iam.gserviceaccount.com"
    error_message = "gateway must allow AE SA as run.invoker"
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.gateway_ae_invoker.role == "roles/run.invoker"
    error_message = "gateway AE binding must be roles/run.invoker"
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.gateway_compute_invoker.member == "serviceAccount:compute@test-project.iam.gserviceaccount.com"
    error_message = "gateway must allow compute SA as run.invoker"
  }
}

run "runners_invocable_by_compute_sa" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service_iam_member.runner_autopilot_compute.member == "serviceAccount:compute@test-project.iam.gserviceaccount.com"
    error_message = "runner_autopilot must allow compute SA as run.invoker (for gateway push subscription)"
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.runner_cloudrun_compute.member == "serviceAccount:compute@test-project.iam.gserviceaccount.com"
    error_message = "runner_cloudrun must allow compute SA as run.invoker"
  }
}

run "frontend_public_present_by_default" {
  command = plan

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.frontend_public) == 1
    error_message = "frontend allUsers binding must be present when frontend_unauthenticated=true (default)"
  }

  assert {
    condition     = google_cloud_run_v2_service_iam_member.frontend_public[0].member == "allUsers"
    error_message = "frontend public binding member must be allUsers"
  }
}

run "frontend_public_absent_when_disabled" {
  command = plan

  variables {
    frontend_unauthenticated = false
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.frontend_public) == 0
    error_message = "frontend allUsers binding must be absent when frontend_unauthenticated=false"
  }
}
