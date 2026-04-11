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

# ---------------------------------------------------------------------------
# Model Armor — Project-level Floor Settings for Vertex AI
# ---------------------------------------------------------------------------
# Floor settings establish mandatory, project-wide baselines for all Gemini
# model interactions via Vertex AI's generateContent API. Any Model Armor
# templates created in-project must meet or exceed these thresholds.
# ---------------------------------------------------------------------------

resource "google_model_armor_floorsetting" "default" {
  parent   = "projects/${var.project_id}"
  location = "global"

  enable_floor_setting_enforcement = true
  integrated_services              = ["AI_PLATFORM"]

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      # HIGH is the most permissive setting that still keeps the PI
      # filter enabled. Both LOW_AND_ABOVE and MEDIUM_AND_ABOVE were
      # empirically too strict: the planner agent's forceful workflow
      # prompts (MUST / STRICT / EXACTLY ONCE / Do NOT) plus long
      # natural-language synthesis turns scored as low- and
      # medium-confidence prompt injection attempts and were blocked,
      # which broke the agent's terminal summary emission. HIGH still
      # blocks high-confidence injection attempts while allowing
      # legitimate forceful instructions through. If genuine injection
      # attempts are observed in the future, the right next step is to
      # add a custom Model Armor template per agent rather than tighten
      # this floor.
      confidence_level = "HIGH"
    }

    rai_settings {
      rai_filters {
        filter_type      = "DANGEROUS"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HARASSMENT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "HATE_SPEECH"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
      rai_filters {
        filter_type      = "SEXUALLY_EXPLICIT"
        confidence_level = "MEDIUM_AND_ABOVE"
      }
    }

    sdp_settings {
      basic_config {
        filter_enforcement = "ENABLED"
      }
    }

    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
  }

  ai_platform_floor_setting {
    inspect_and_block    = true
    enable_cloud_logging = true
  }
}
