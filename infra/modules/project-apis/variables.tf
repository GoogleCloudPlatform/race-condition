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

variable "services" {
  description = "List of GCP APIs to enable"
  type        = list(string)
  default = [
    "agentregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "alloydb.googleapis.com",
    "apikeys.googleapis.com",
    "apphub.googleapis.com",
    "appoptimize.googleapis.com",
    "apptopology.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudaicompanion.googleapis.com",
    "cloudapiregistry.googleapis.com",
    "cloudasset.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "dns.googleapis.com",
    "documentai.googleapis.com",
    "edgecache.googleapis.com",
    "generativelanguage.googleapis.com",
    "geminicloudassist.googleapis.com",
    "iap.googleapis.com",
    "mapstools.googleapis.com",
    "modelarmor.googleapis.com",
    "monitoring.googleapis.com",
    "networksecurity.googleapis.com",
    "networkservices.googleapis.com",
    "observability.googleapis.com",
    "places.googleapis.com",
    "pubsub.googleapis.com",
    "recommender.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "storageinsights.googleapis.com",
    "vpcaccess.googleapis.com",
    "weather.googleapis.com",
  ]
}
