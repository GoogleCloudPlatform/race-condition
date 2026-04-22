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
# OSS Project -- Lightweight Single-Project Deployment
# =============================================================================
#
# This root module composes a minimal Race Condition deployment suitable for
# individual GCP projects. It reuses existing modules with smaller sizing
# defaults and feature toggles for optional components.
#
# Required:  project_id
# Optional:  enable_alloydb, enable_gke, enable_runner_cloudrun,
#            enable_maps_api_key, enable_monitoring
# =============================================================================

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

locals {
  # Build the API list dynamically based on feature toggles
  base_apis = [
    "agentregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "apikeys.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "generativelanguage.googleapis.com",
    "modelarmor.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "redis.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
  ]

  cloudsql_apis = var.enable_alloydb ? [] : ["sqladmin.googleapis.com"]
  alloydb_apis  = var.enable_alloydb ? ["alloydb.googleapis.com"] : []
  gke_apis      = var.enable_gke ? ["container.googleapis.com"] : []
  maps_apis = var.enable_maps_api_key ? [
    "mapstools.googleapis.com",
    "places.googleapis.com",
    "weather.googleapis.com",
  ] : []

  all_apis = concat(local.base_apis, local.cloudsql_apis, local.alloydb_apis, local.gke_apis, local.maps_apis)
}

# =============================================================================
# Core Infrastructure (always enabled)
# =============================================================================

module "project_apis" {
  source     = "./modules/project-apis"
  project_id = var.project_id
  region     = var.region
  services   = local.all_apis
}

module "networking" {
  source         = "./modules/networking"
  project_id     = var.project_id
  project_number = module.project_apis.project_number
  region         = var.region
}

module "iam" {
  source                = "./modules/iam"
  project_id            = var.project_id
  project_number        = module.project_apis.project_number
  region                = var.region
  backend_writers       = var.developers
  frontend_writers      = []
  maps_mcp_users        = var.enable_maps_api_key ? var.developers : []
  agent_engine_sa_users = var.agent_engine_sa_users
}

module "redis" {
  source                    = "./modules/redis"
  project_id                = var.project_id
  region                    = var.region
  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  tier                      = "BASIC"
  memory_size_gb            = 1
}

module "pubsub" {
  source           = "./modules/pubsub"
  project_id       = var.project_id
  project_number   = module.project_apis.project_number
  region           = var.region
  compute_sa_email = module.iam.compute_sa_email
}

module "model_armor" {
  source     = "./modules/model-armor"
  project_id = var.project_id

  depends_on = [module.project_apis]
}

# =============================================================================
# Database -- Cloud SQL PostgreSQL (default) or AlloyDB (opt-in)
# =============================================================================

module "cloud_sql_postgres" {
  count = var.enable_alloydb ? 0 : 1

  source                    = "./modules/cloud-sql-postgres"
  project_id                = var.project_id
  region                    = var.region
  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  compute_sa                = module.iam.compute_sa
  agent_engine_sa_email     = module.iam.agent_engine_sa_email
  iam_users                 = var.developers
  initial_password          = var.db_initial_password
}

module "alloydb" {
  count = var.enable_alloydb ? 1 : 0

  source                    = "./modules/alloydb"
  project_id                = var.project_id
  project_number            = module.project_apis.project_number
  region                    = var.region
  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  compute_sa                = module.iam.compute_sa
  agent_engine_sa_email     = module.iam.agent_engine_sa_email
  iam_users                 = var.developers
  initial_password          = var.db_initial_password
  cpu_count                 = 2
}

# =============================================================================
# Optional: GKE for runner_gke (GPU workloads)
# =============================================================================

module "gke_model_serving" {
  count = var.enable_gke ? 1 : 0

  source         = "./modules/gke-model-serving"
  project_id     = var.project_id
  project_number = module.project_apis.project_number
  region         = var.region
}

module "gke_runner" {
  count = var.enable_gke ? 1 : 0

  source               = "./modules/gke-runner"
  project_id           = var.project_id
  region               = var.region
  vpc_id               = module.networking.vpc_id
  vpc_name             = module.networking.vpc_name
  model_storage_bucket = module.gke_model_serving[0].model_storage_bucket
  cpu_min_nodes        = 1
  cpu_max_nodes        = 3
  gpu_min_nodes        = 0
  gpu_max_nodes        = 1

  depends_on = [module.project_apis]
}

# =============================================================================
# Optional: Maps API Key
# =============================================================================

module "api_keys" {
  count = var.enable_maps_api_key ? 1 : 0

  source          = "./modules/api-keys"
  project_id      = var.project_id
  compute_sa      = module.iam.compute_sa
  agent_engine_sa = module.iam.agent_engine_sa
  backend_writers = var.developers
  maps_mcp_users  = var.developers

  depends_on = [module.project_apis]
}

# =============================================================================
# Optional: Monitoring
# =============================================================================

module "monitoring" {
  count = var.enable_monitoring ? 1 : 0

  source      = "./modules/monitoring"
  project_id  = var.project_id
  environment = "oss"
  alert_email = var.alert_email
  # No domain_suffix -- OSS has no DNS. The monitoring module skips the
  # gateway uptime check when domain_suffix is empty, but still provisions
  # Redis memory, NAT egress, and Redis connection alerts.

  depends_on = [module.project_apis]
}
