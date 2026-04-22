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
  # Tag every labelable resource (Cloud Run, Cloud SQL, Redis, Pub/Sub, etc.)
  # for cost attribution and demo-asset cleanup. Per-resource `labels` blocks
  # in modules (e.g. pubsub topics with `purpose=`) merge with these; the
  # combined set is exposed by the provider as `effective_labels`.
  default_labels = var.labels
}

provider "google-beta" {
  project        = var.project_id
  region         = var.region
  default_labels = var.labels
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

  depends_on = [module.project_apis]
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

  depends_on = [module.project_apis]
}

module "redis" {
  source                    = "./modules/redis"
  project_id                = var.project_id
  region                    = var.region
  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  tier                      = "BASIC"
  memory_size_gb            = 1

  depends_on = [module.project_apis]
}

module "pubsub" {
  source           = "./modules/pubsub"
  project_id       = var.project_id
  project_number   = module.project_apis.project_number
  region           = var.region
  compute_sa_email = module.iam.compute_sa_email

  depends_on = [module.project_apis]
}

module "model_armor" {
  source     = "./modules/model-armor"
  project_id = var.project_id

  depends_on = [module.project_apis]
}

# =============================================================================
# Database -- Cloud SQL PostgreSQL (default) or AlloyDB (opt-in)
# =============================================================================

# Generate a strong default DB password when the operator does not supply
# var.db_initial_password. The value lives in TF state, so re-applies are
# idempotent (no password churn). Both database modules persist whichever
# password is chosen into Secret Manager.
resource "random_password" "db_initial" {
  length      = 32
  special     = false # alphanumeric -- safe in cloud-sql-postgres local-exec PGPASSWORD interpolation
  min_lower   = 4
  min_upper   = 4
  min_numeric = 4
}

locals {
  db_password = coalesce(var.db_initial_password, random_password.db_initial.result)
}

module "cloud_sql_postgres" {
  count = var.enable_alloydb ? 0 : 1

  source                    = "./modules/cloud-sql-postgres"
  project_id                = var.project_id
  project_number            = module.project_apis.project_number
  region                    = var.region
  vpc_id                    = module.networking.vpc_id
  private_vpc_connection_id = module.networking.private_vpc_connection_id
  compute_sa                = module.iam.compute_sa
  agent_engine_sa_email     = module.iam.agent_engine_sa_email
  iam_users                 = var.developers
  initial_password          = local.db_password

  depends_on = [module.project_apis]
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
  initial_password          = local.db_password
  cpu_count                 = 2

  depends_on = [module.project_apis]
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

  depends_on = [module.project_apis]
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

# =============================================================================
# Cloud Run services + IAM (gated by enable_services)
#
# Two-pass apply pattern: the Phase 1 base-infra apply runs with
# enable_services=false. After image builds finish, the Phase 2 services
# apply runs with enable_services=true and image_tags populated. This
# avoids a chicken-and-egg between Cloud Run services and image tags.
# =============================================================================

locals {
  database_ip = var.enable_alloydb ? (
    length(module.alloydb) > 0 ? module.alloydb[0].ip_address : ""
    ) : (
    length(module.cloud_sql_postgres) > 0 ? module.cloud_sql_postgres[0].private_ip_address : ""
  )

  database_secret_id = var.enable_alloydb ? (
    length(module.alloydb) > 0 ? module.alloydb[0].password_secret_id : ""
    ) : (
    length(module.cloud_sql_postgres) > 0 ? module.cloud_sql_postgres[0].password_secret_id : ""
  )
}

module "cloud_run_services" {
  count = var.enable_services ? 1 : 0

  source = "./modules/cloud-run-services"

  project_id          = var.project_id
  region              = var.region
  compute_sa_email    = module.iam.compute_sa_email
  vpc_network_name    = module.networking.vpc_name
  vpc_subnet_name     = module.networking.serverless_subnet_name
  image_tags          = var.image_tags
  redis_host          = module.redis.host
  redis_port          = module.redis.port
  database_ip         = local.database_ip
  database_secret_id  = local.database_secret_id
  orchestration_topic = module.pubsub.topic_name
  telemetry_topic     = module.pubsub.telemetry_topic_name
  embedding_backend   = var.embedding_backend
  agent_urls          = var.agent_urls

  depends_on = [
    module.project_apis,
    module.redis,
    module.pubsub,
    module.networking,
    module.iam,
  ]
}

module "cloud_run_iam" {
  count = var.enable_services ? 1 : 0

  source = "./modules/cloud-run-iam"

  project_id                 = var.project_id
  region                     = var.region
  service_names              = module.cloud_run_services[0].service_names
  agent_engine_sa_email      = module.iam.agent_engine_sa_email
  compute_sa_email           = module.iam.compute_sa_email
  public_uis_unauthenticated = var.public_uis_unauthenticated
}
