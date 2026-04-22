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

output "service_urls" {
  description = "Map of service name -> .run.app URL."
  value = {
    gateway          = google_cloud_run_v2_service.gateway.uri
    admin            = google_cloud_run_v2_service.admin.uri
    dash             = google_cloud_run_v2_service.dash.uri
    frontend         = google_cloud_run_v2_service.frontend.uri
    tester           = google_cloud_run_v2_service.tester.uri
    runner_autopilot = google_cloud_run_v2_service.runner_autopilot.uri
    runner_cloudrun  = google_cloud_run_v2_service.runner_cloudrun.uri
  }
}

output "service_names" {
  description = "Map of service key -> Cloud Run service name (used by cloud-run-iam for service-level IAM bindings)."
  value = {
    gateway          = google_cloud_run_v2_service.gateway.name
    admin            = google_cloud_run_v2_service.admin.name
    dash             = google_cloud_run_v2_service.dash.name
    frontend         = google_cloud_run_v2_service.frontend.name
    tester           = google_cloud_run_v2_service.tester.name
    runner_autopilot = google_cloud_run_v2_service.runner_autopilot.name
    runner_cloudrun  = google_cloud_run_v2_service.runner_cloudrun.name
  }
}

output "gateway_url" {
  description = "Convenience accessor for the gateway URL."
  value       = google_cloud_run_v2_service.gateway.uri
}
