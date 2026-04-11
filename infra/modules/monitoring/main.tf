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

resource "google_monitoring_notification_channel" "email" {
  display_name = "${title(var.environment)} Team Email"
  type         = "email"
  project      = var.project_id

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "redis_memory" {
  display_name = "Redis Memory Pressure (>80%)"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Memory usage ratio exceeds 80%"
    condition_threshold {
      filter          = "resource.type = \"redis_instance\" AND metric.type = \"redis.googleapis.com/stats/memory/usage_ratio\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Redis memory usage has exceeded 80%. Check for memory leaks or excessive key growth. Triage: run `redis-cli INFO memory` on the instance and review `used_memory_peak` vs `maxmemory`. Consider flushing stale keys or scaling the instance tier."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_uptime_check_config" "gateway_health" {
  count = var.domain_suffix != "" ? 1 : 0

  display_name = "Gateway Health (${var.environment})"
  project      = var.project_id
  timeout      = "10s"
  period       = "60s"

  http_check {
    path         = "/healthz"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = "gateway.${var.domain_suffix}"
    }
  }
}

resource "google_monitoring_alert_policy" "gateway_uptime" {
  count = var.domain_suffix != "" ? 1 : 0

  display_name = "Gateway Unreachable (${var.environment})"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Gateway uptime check failing"
    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.gateway_health[0].uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "120s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.project_id"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "The gateway health check is failing. This likely indicates VPC connectivity issues (e.g., Redis unreachable) or a service crash. Triage: check gateway Cloud Run logs for Redis connection errors, verify VPC subnet and NAT health."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "nat_egress_zero" {
  display_name = "Cloud NAT Egress Zero (${var.environment})"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "NAT sent bytes dropped to zero"
    condition_absent {
      filter   = "resource.type = \"nat_gateway\" AND metric.type = \"router.googleapis.com/nat/sent_bytes_count\""
      duration = "600s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_RATE"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Cloud NAT has reported zero egress bytes for 10 minutes. This may indicate a VPC networking failure preventing Cloud Run services from reaching external endpoints or other Cloud Run services via .run.app URLs. Triage: check Cloud NAT status, verify VPC routes, and inspect Cloud Run service logs for connection timeouts."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "redis_connections" {
  display_name = "Redis High Connection Count (>8000)"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Connected clients exceeds 8000"
    condition_threshold {
      filter          = "resource.type = \"redis_instance\" AND metric.type = \"redis.googleapis.com/clients/connected\""
      comparison      = "COMPARISON_GT"
      threshold_value = 8000
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]

  documentation {
    content   = "Redis connected clients have exceeded 8000 (80% of the 10,000-connection design target). Triage: check for connection leaks in application services using `redis-cli CLIENT LIST`. Review gateway and agent connection pooling settings. If legitimate load, consider scaling the Redis tier."
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "1800s"
  }
}
