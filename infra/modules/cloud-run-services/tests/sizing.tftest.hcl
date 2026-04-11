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

# Right-sizing tests for the cloud-run-services module.
# Locks in the cost-control defaults from
# docs/plans/2026-04-16-oss-right-sizing-plan.md so a future edit can't
# silently regress OSS to dev's 2cpu/2Gi/min=1 sizing.

variables {
  project_id       = "test-project"
  region           = "us-central1"
  compute_sa_email = "compute@test-project.iam.gserviceaccount.com"
  vpc_subnet_name  = "test-subnet"
  vpc_network_name = "test-vpc"
  image_tags = {
    gateway          = "us-central1-docker.pkg.dev/test-project/race-condition/gateway:abc"
    admin            = "us-central1-docker.pkg.dev/test-project/race-condition/admin:abc"
    dash             = "us-central1-docker.pkg.dev/test-project/race-condition/dash:abc"
    frontend         = "us-central1-docker.pkg.dev/test-project/race-condition/frontend:abc"
    tester           = "us-central1-docker.pkg.dev/test-project/race-condition/tester:abc"
    runner_autopilot = "us-central1-docker.pkg.dev/test-project/race-condition/runner_autopilot:abc"
    runner_cloudrun  = "us-central1-docker.pkg.dev/test-project/race-condition/runner_cloudrun:abc"
  }
  redis_host          = "10.0.0.1"
  database_ip         = "10.0.0.2"
  database_secret_id  = "db-pw"
  orchestration_topic = "specialist-orchestration"
}

run "go_services_default_to_512mi_1cpu" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.gateway.template[0].containers[0].resources[0].limits["memory"] == "512Mi"
    error_message = "gateway memory must be 512Mi (right-sizing plan)"
  }

  assert {
    condition     = google_cloud_run_v2_service.gateway.template[0].containers[0].resources[0].limits["cpu"] == "1"
    error_message = "gateway cpu must be 1 (right-sizing plan)"
  }

  assert {
    condition     = google_cloud_run_v2_service.admin.template[0].containers[0].resources[0].limits["memory"] == "512Mi"
    error_message = "admin memory must be 512Mi (right-sizing plan)"
  }

  assert {
    condition     = google_cloud_run_v2_service.frontend.template[0].containers[0].resources[0].limits["memory"] == "512Mi"
    error_message = "frontend memory must be 512Mi (right-sizing plan)"
  }
}

# Phase 7 verification surfaced that the two Python runner services
# OOM-killed during ADK runtime startup at 512Mi (used 513 MiB before
# port 8080 ever opened, failing the Cloud Run health probe). Go
# services have a much smaller runtime footprint and stay safely
# under 512Mi, but anything carrying ADK + google-genai + a2a-sdk
# + agent code needs at least 1Gi to make startup. Matches the
# internal dev/prod sizing for these services.
run "python_runner_services_default_to_1gi" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.runner_autopilot.template[0].containers[0].resources[0].limits["memory"] == "1Gi"
    error_message = "runner_autopilot memory must be 1Gi -- 512Mi OOM-kills the container during Python+ADK startup before port 8080 opens (Phase 7 build #20)"
  }

  assert {
    condition     = google_cloud_run_v2_service.runner_cloudrun.template[0].containers[0].resources[0].limits["memory"] == "1Gi"
    error_message = "runner_cloudrun memory must be 1Gi -- 512Mi OOM-kills the container during Python+ADK startup before port 8080 opens (Phase 7 build #20)"
  }
}

run "all_services_capped_at_max_instances_1" {
  command = plan

  # OSS cost control: every service must cap at a single instance,
  # not just the runners. Pinned across all 7 Cloud Run services so
  # a future edit can't quietly raise gateway/admin/etc. back to 10.

  assert {
    condition     = google_cloud_run_v2_service.gateway.template[0].scaling[0].max_instance_count == 1
    error_message = "gateway max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.admin.template[0].scaling[0].max_instance_count == 1
    error_message = "admin max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.tester.template[0].scaling[0].max_instance_count == 1
    error_message = "tester max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.frontend.template[0].scaling[0].max_instance_count == 1
    error_message = "frontend max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.dash.template[0].scaling[0].max_instance_count == 1
    error_message = "dash max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.runner_autopilot.template[0].scaling[0].max_instance_count == 1
    error_message = "runner_autopilot max_instance_count must be 1 for OSS cost control"
  }

  assert {
    condition     = google_cloud_run_v2_service.runner_cloudrun.template[0].scaling[0].max_instance_count == 1
    error_message = "runner_cloudrun max_instance_count must be 1 for OSS cost control"
  }
}

run "all_services_default_min_instances_zero" {
  command = plan

  assert {
    condition     = google_cloud_run_v2_service.gateway.template[0].scaling[0].min_instance_count == 0
    error_message = "gateway must default to scale-to-zero"
  }

  assert {
    condition     = google_cloud_run_v2_service.runner_autopilot.template[0].scaling[0].min_instance_count == 0
    error_message = "runner_autopilot must default to scale-to-zero (was min=1 in dev)"
  }

  assert {
    condition     = google_cloud_run_v2_service.runner_cloudrun.template[0].scaling[0].min_instance_count == 0
    error_message = "runner_cloudrun must default to scale-to-zero (was min=1 in dev)"
  }

  assert {
    condition     = google_cloud_run_v2_service.admin.template[0].scaling[0].min_instance_count == 0
    error_message = "admin must default to scale-to-zero"
  }
}

run "gateway_threads_agent_urls_into_env" {
  command = plan

  variables {
    agent_urls = "planner=https://planner.example,simulator=https://sim.example"
  }

  assert {
    condition = length([
      for e in google_cloud_run_v2_service.gateway.template[0].containers[0].env :
      e if e.name == "AGENT_URLS" && e.value == "planner=https://planner.example,simulator=https://sim.example"
    ]) == 1
    error_message = "gateway must receive AGENT_URLS env var matching var.agent_urls"
  }
}

run "all_services_have_deletion_protection_disabled" {
  command = plan

  # OSS UX: every Cloud Run service must declare deletion_protection
  # = false so the cloudbuild-bootstrap enable_services flip-flop and
  # any user-driven `terraform destroy` can actually run. Without this,
  # a single failed Cloud Build leaves the project in a state that can
  # only be recovered by manual gcloud surgery (Phase 7 build #21).

  assert {
    condition     = google_cloud_run_v2_service.gateway.deletion_protection == false
    error_message = "gateway must declare deletion_protection = false (OSS UX, build #21 gotcha)"
  }
  assert {
    condition     = google_cloud_run_v2_service.admin.deletion_protection == false
    error_message = "admin must declare deletion_protection = false"
  }
  assert {
    condition     = google_cloud_run_v2_service.dash.deletion_protection == false
    error_message = "dash must declare deletion_protection = false"
  }
  assert {
    condition     = google_cloud_run_v2_service.tester.deletion_protection == false
    error_message = "tester must declare deletion_protection = false"
  }
  assert {
    condition     = google_cloud_run_v2_service.frontend.deletion_protection == false
    error_message = "frontend must declare deletion_protection = false"
  }
  assert {
    condition     = google_cloud_run_v2_service.runner_autopilot.deletion_protection == false
    error_message = "runner_autopilot must declare deletion_protection = false"
  }
  assert {
    condition     = google_cloud_run_v2_service.runner_cloudrun.deletion_protection == false
    error_message = "runner_cloudrun must declare deletion_protection = false"
  }
}

run "embedding_backend_defaults_to_vertex_ai" {
  command = plan

  assert {
    condition = length([
      for e in google_cloud_run_v2_service.gateway.template[0].containers[0].env :
      e if e.name == "EMBEDDING_BACKEND" && e.value == "vertex_ai"
    ]) == 1
    error_message = "EMBEDDING_BACKEND must default to vertex_ai for OSS Cloud SQL deploys"
  }
}
