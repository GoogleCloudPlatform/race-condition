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

resource "google_compute_subnetwork" "runner_gke" {
  name                     = "runner-gke-subnet"
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = var.vpc_id
  project                  = var.project_id
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "runner-pods"
    ip_cidr_range = var.pod_cidr
  }

  secondary_ip_range {
    range_name    = "runner-services"
    ip_cidr_range = var.service_cidr
  }
}

resource "google_container_cluster" "runner_cluster" {
  name     = "runner-cluster"
  location = var.region
  project  = var.project_id

  network    = var.vpc_name
  subnetwork = google_compute_subnetwork.runner_gke.name

  remove_default_node_pool = true
  initial_node_count       = 1

  release_channel {
    channel = "RAPID"
  }

  datapath_provider = "ADVANCED_DATAPATH"

  ip_allocation_policy {
    cluster_secondary_range_name  = "runner-pods"
    services_secondary_range_name = "runner-services"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  addons_config {
    http_load_balancing {
      disabled = false
    }
    horizontal_pod_autoscaling {
      disabled = false
    }
    dns_cache_config {
      enabled = true
    }
    gcs_fuse_csi_driver_config {
      enabled = true
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
    lustre_csi_driver_config {
      enabled = true
    }
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS", "DCGM"]
    managed_prometheus {
      enabled = true
    }
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  deletion_protection = true

  lifecycle {
    prevent_destroy = true
  }
}

# CPU Node Pool
resource "google_container_node_pool" "runner_cpu_pool" {
  name     = "runner-cpu-pool"
  cluster  = google_container_cluster.runner_cluster.name
  location = var.region
  project  = var.project_id

  autoscaling {
    min_node_count  = var.cpu_min_nodes
    max_node_count  = var.cpu_max_nodes
    location_policy = "ANY"
  }

  node_config {
    machine_type = "e2-standard-4"
    disk_size_gb = 50
    disk_type    = "pd-balanced"
    image_type   = "COS_CONTAINERD"

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    shielded_instance_config {
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

# GPU Node Pool (vLLM inference)
#
# Two modes:
#   - Flex-start (dev): autoscaling 0-N with NO_RESERVATION, cost-efficient
#   - Reservation (prod): fixed node_count with ANY_RESERVATION, guaranteed capacity
resource "google_container_node_pool" "runner_gpu_l4_pool" {
  provider = google-beta
  name     = "gpu-l4-pool"
  cluster  = google_container_cluster.runner_cluster.name
  location = var.region
  project  = var.project_id

  node_locations = [var.gpu_zone != "" ? var.gpu_zone : "${var.region}-a"]

  # Reservation mode: fixed node count, no autoscaling
  dynamic "autoscaling" {
    for_each = var.gpu_use_reservation ? [] : [1]
    content {
      min_node_count  = var.gpu_min_nodes
      max_node_count  = var.gpu_max_nodes
      location_policy = "ANY"
    }
  }
  node_count = var.gpu_use_reservation ? var.gpu_node_count : null

  node_config {
    machine_type = "g2-standard-4"

    guest_accelerator {
      type  = "nvidia-l4"
      count = 1

      gpu_driver_installation_config {
        gpu_driver_version = "DEFAULT"
      }
    }

    # GKE always sets disable-legacy-endpoints; include it to avoid drift.
    # Reservation mode additionally sets install-nvidia-driver.
    metadata = merge(
      { "disable-legacy-endpoints" = "true" },
      var.gpu_use_reservation ? { "install-nvidia-driver" = "true" } : {},
    )

    disk_size_gb = 100
    disk_type    = "pd-balanced"
    image_type   = "COS_CONTAINERD"

    # Flex-start: cost-efficient GPU provisioning (beta feature)
    flex_start       = var.gpu_use_reservation ? null : true
    max_run_duration = var.gpu_use_reservation ? null : "604800s"

    reservation_affinity {
      consume_reservation_type = var.gpu_use_reservation ? "ANY_RESERVATION" : "NO_RESERVATION"
    }

    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    dynamic "gvnic" {
      for_each = var.gpu_enable_gvnic ? [1] : []
      content {
        enabled = true
      }
    }

    service_account = google_service_account.runner_gke_sa.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    shielded_instance_config {
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Runner SA and IAM
resource "google_service_account" "runner_gke_sa" {
  account_id   = "runner-gke-sa"
  display_name = "Runner GKE SA"
  description  = "Service account for GKE runner workloads (Vertex AI, Pub/Sub, AR)"
  project      = var.project_id
}

resource "google_project_iam_member" "runner_gke_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_project_iam_member" "runner_gke_pubsub_subscriber" {
  project = var.project_id
  role    = "roles/pubsub.subscriber"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_project_iam_member" "runner_gke_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_project_iam_member" "runner_gke_ar_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_project_iam_member" "runner_gke_monitoring_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_project_iam_member" "runner_gke_logging_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}

resource "google_service_account_iam_member" "runner_gke_workload_identity" {
  service_account_id = google_service_account.runner_gke_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[runner/runner-gke]"
}

resource "google_storage_bucket_iam_member" "runner_gke_model_bucket_reader" {
  bucket = var.model_storage_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runner_gke_sa.email}"
}
