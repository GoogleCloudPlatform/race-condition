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

# Common env vars threaded into every Race Condition Cloud Run service.
# Mirrors scripts/deploy/deploy.py:build_env_vars()
# (the legacy gcloud-based deployer). Cross-service URLs (ADMIN_URL,
# DASH_URL, ...) are deliberately omitted: they cause TF dependency
# cycles between services. The Phase 4 Cloud Build orchestrator wires
# them after `terraform apply` completes via `gcloud run services
# update`, matching the behaviour of the legacy deploy.py.
data "google_project" "current" {
  project_id = var.project_id
}

locals {
  redis_addr = "${var.redis_host}:${var.redis_port}"

  # Cloud Run service URLs follow a deterministic pattern keyed on the
  # project number. We construct the runner URLs here so the gateway's
  # AGENT_URLS env var can include them without referencing the runner
  # resources directly (which would create a tf cycle: runners depend on
  # gateway.uri for GATEWAY_INTERNAL_URL).
  runner_autopilot_url = "https://runner-autopilot-${data.google_project.current.number}.${var.region}.run.app"
  runner_cloudrun_url  = "https://runner-cloudrun-${data.google_project.current.number}.${var.region}.run.app"

  common_env = [
    { name = "PROJECT_ID", value = var.project_id },
    { name = "GOOGLE_CLOUD_PROJECT", value = var.project_id },
    { name = "GOOGLE_CLOUD_LOCATION", value = "global" },
    { name = "GOOGLE_GENAI_USE_VERTEXAI", value = "true" },
    { name = "PUBSUB_PROJECT_ID", value = var.project_id },
    { name = "PUBSUB_TOPIC_ID", value = var.telemetry_topic },
    { name = "ORCHESTRATION_TOPIC_ID", value = var.orchestration_topic },
    { name = "REDIS_ADDR", value = local.redis_addr },
    { name = "REDIS_HOST", value = var.redis_host },
    { name = "REDIS_PORT", value = tostring(var.redis_port) },
    { name = "DATABASE_IP", value = var.database_ip },
    { name = "ALLOYDB_HOST", value = var.database_ip },
    { name = "EMBEDDING_BACKEND", value = var.embedding_backend },
    { name = "PYTHONPATH", value = "." },
    { name = "GIN_MODE", value = "release" },
  ]

  # Cloud Run agent extras (runner_autopilot, runner_cloudrun).
  agent_env = [
    { name = "DISPATCH_MODE", value = "subscriber" },
    { name = "REDIS_MAX_CONNECTIONS", value = "100" },
    { name = "REDIS_SESSION_MAX_CONNECTIONS", value = "100" },
    { name = "SESSION_STORE_OVERRIDE", value = "redis" },
  ]
}

# ---------------------------------------------------------------------------
# Gateway -- entry point invoked by AE agents and UI services
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "gateway" {
  project  = var.project_id
  location = var.region
  name     = "gateway"
  # OSS UX: allow `terraform destroy` and the enable_services flip-flop
  # in cloudbuild-bootstrap to actually run. With deletion_protection
  # left at the provider default (true), a single failed Cloud Build
  # leaves the project in a state that can't be recovered by re-running
  # the same build (Phase 7 build #21).
  deletion_protection = false

  template {
    service_account = var.compute_sa_email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["gateway"].max_instances
    }

    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image_tags["gateway"]

      resources {
        limits = {
          cpu    = var.service_sizing["gateway"].cpu
          memory = var.service_sizing["gateway"].memory
        }
      }

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      env {
        name  = "AGENT_NAME"
        value = "gateway"
      }
      env {
        name = "AGENT_URLS"
        # var.agent_urls is the comma-separated list of AE engine URLs collected
        # by the cloudbuild `collect-ae-urls` step. We also need the two Cloud
        # Run runner agents (runner_autopilot, runner_cloudrun) for spawn_runners
        # to find them. We can't reference google_cloud_run_v2_service.runner_*
        # .uri directly here because the runners depend on gateway.uri (for
        # GATEWAY_INTERNAL_URL), which would create a tf cycle. Cloud Run service
        # URLs follow a deterministic pattern -- `<service>-<projectnumber>.<region>.run.app`
        # -- so we compose them here without a resource cross-reference.
        # Without this the gateway only discovers the AE engines and
        # spawn_runners() fails with "unknown agent type runner_autopilot".
        value = join(",", compact([
          var.agent_urls,
          local.runner_autopilot_url,
          local.runner_cloudrun_url,
        ]))
      }
      env {
        name  = "MAX_RUNNERS"
        value = "100"
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }

      ports {
        container_port = 8080
      }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

# ---------------------------------------------------------------------------
# UI services (admin, dash, tester, frontend) -- invoked by browsers
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "admin" {
  project             = var.project_id
  location            = var.region
  name                = "admin"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["admin"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["admin"]
      resources {
        limits = {
          cpu    = var.service_sizing["admin"].cpu
          memory = var.service_sizing["admin"].memory
        }
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name  = "AGENT_NAME"
        value = "admin"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

resource "google_cloud_run_v2_service" "dash" {
  project             = var.project_id
  location            = var.region
  name                = "dash"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["dash"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["dash"]
      resources {
        limits = {
          cpu    = var.service_sizing["dash"].cpu
          memory = var.service_sizing["dash"].memory
        }
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name  = "AGENT_NAME"
        value = "dash"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

resource "google_cloud_run_v2_service" "tester" {
  project             = var.project_id
  location            = var.region
  name                = "tester"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["tester"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["tester"]
      resources {
        limits = {
          cpu    = var.service_sizing["tester"].cpu
          memory = var.service_sizing["tester"].memory
        }
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name  = "AGENT_NAME"
        value = "tester"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

resource "google_cloud_run_v2_service" "frontend" {
  project             = var.project_id
  location            = var.region
  name                = "frontend"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["frontend"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["frontend"]
      resources {
        limits = {
          cpu    = var.service_sizing["frontend"].cpu
          memory = var.service_sizing["frontend"].memory
        }
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name  = "AGENT_NAME"
        value = "frontend"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

# ---------------------------------------------------------------------------
# Cloud Run runner agents -- invoked by gateway via push subscription
# ---------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "runner_autopilot" {
  project             = var.project_id
  location            = var.region
  name                = "runner-autopilot"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["runner_autopilot"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["runner_autopilot"]
      resources {
        limits = {
          cpu    = var.service_sizing["runner_autopilot"].cpu
          memory = var.service_sizing["runner_autopilot"].memory
        }
      }
      dynamic "env" {
        for_each = concat(local.common_env, local.agent_env)
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      env {
        name  = "AGENT_NAME"
        value = "runner_autopilot"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}

resource "google_cloud_run_v2_service" "runner_cloudrun" {
  project             = var.project_id
  location            = var.region
  name                = "runner-cloudrun"
  deletion_protection = false

  template {
    service_account = var.compute_sa_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.service_sizing["runner_cloudrun"].max_instances
    }
    vpc_access {
      network_interfaces {
        network    = var.vpc_network_name
        subnetwork = var.vpc_subnet_name
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = var.image_tags["runner_cloudrun"]
      resources {
        limits = {
          cpu    = var.service_sizing["runner_cloudrun"].cpu
          memory = var.service_sizing["runner_cloudrun"].memory
        }
      }
      dynamic "env" {
        for_each = concat(local.common_env, local.agent_env)
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
      # AGENT_NAME explicitly set to runner_cloudrun (gotcha #3 in the
      # OSS deploy plan: prior bug had this defaulting to runner_gke).
      env {
        name  = "AGENT_NAME"
        value = "runner_cloudrun"
      }
      env {
        name  = "GATEWAY_INTERNAL_URL"
        value = google_cloud_run_v2_service.gateway.uri
      }
      env {
        name = "ALLOYDB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.database_secret_id
            version = "latest"
          }
        }
      }
      ports { container_port = 8080 }
    }
  }

  lifecycle {
    ignore_changes = [client, client_version]
  }
}
