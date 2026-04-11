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

# Serverless NEGs (one per Cloud Run service)
resource "google_compute_region_network_endpoint_group" "negs" {
  for_each              = var.services
  name                  = "${each.key}-neg-${each.value}"
  project               = var.project_id
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  cloud_run {
    service = each.value
  }
  lifecycle {
    create_before_destroy = true
  }
}

# Backend Services with IAP (one per service)
resource "google_compute_backend_service" "backends" {
  for_each    = var.services
  name        = "${each.key}-backend"
  project     = var.project_id
  port_name   = "http"
  protocol    = "HTTP"
  timeout_sec = 30

  backend {
    group = google_compute_region_network_endpoint_group.negs[each.key].id
  }

  iap {
    enabled              = true
    oauth2_client_id     = var.iap_oauth2_client_id
    oauth2_client_secret = var.iap_oauth2_client_secret
  }
}

# IAP Access Bindings (one per service)
resource "google_iap_web_backend_service_iam_binding" "iap_access" {
  for_each            = var.services
  project             = var.project_id
  web_backend_service = google_compute_backend_service.backends[each.key].name
  role                = "roles/iap.httpsResourceAccessor"

  members = concat(var.iap_access_members, [var.compute_sa])
}

# URL Map with per-service host rules
resource "google_compute_url_map" "url_map" {
  name            = "${var.environment}-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.backends["admin"].id

  dynamic "host_rule" {
    for_each = var.services
    content {
      hosts        = ["${host_rule.key}.${var.domain_suffix}"]
      path_matcher = host_rule.key
    }
  }

  dynamic "path_matcher" {
    for_each = var.services
    content {
      name            = path_matcher.key
      default_service = google_compute_backend_service.backends[path_matcher.key].id
    }
  }
}

# Multi-domain SSL Certificates
locals {
  cert_groups = {
    "a" = ["admin", "gateway", "tester"]
    "b" = ["dash", "frontend"]
  }
}

resource "google_compute_managed_ssl_certificate" "cert" {
  for_each = local.cert_groups
  name     = "${var.environment}-cert-${each.key}-fresh"
  project  = var.project_id

  managed {
    domains = [for svc in each.value : "${svc}.${var.domain_suffix}"]
  }
}

# HTTPS Proxy + LB
resource "google_compute_target_https_proxy" "https_proxy" {
  name             = "${var.environment}-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.url_map.id
  ssl_certificates = [for k, v in google_compute_managed_ssl_certificate.cert : v.id]
}

resource "google_compute_global_address" "lb_ip" {
  name    = "${var.environment}-lb-ip"
  project = var.project_id
}

resource "google_compute_global_forwarding_rule" "forwarding_rule" {
  name       = "${var.environment}-forwarding-rule"
  project    = var.project_id
  target     = google_compute_target_https_proxy.https_proxy.id
  port_range = "443"
  ip_address = google_compute_global_address.lb_ip.id
}

# Per-service DNS A records (all point to shared LB IP)
resource "google_dns_record_set" "service_records" {
  for_each     = var.services
  managed_zone = var.dns_zone_name
  project      = var.project_id
  name         = "${each.key}.${var.domain_suffix}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.lb_ip.address]
}
