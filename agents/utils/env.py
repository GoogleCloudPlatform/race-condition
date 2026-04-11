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

"""Project environment configuration for Vertex AI Agent Engine compatibility.

Vertex AI Agent Engine sets GOOGLE_CLOUD_PROJECT to the numeric Project ID,
which causes the google-cloud-aiplatform SDK's Initializer to hang. This module
provides a single function to normalize project environment variables at
module load time, replacing the copy-pasted boilerplate across all agents.
"""

import os
import sys


def configure_project_env(agent_label: str) -> None:
    """Configure GCP project environment variables for Vertex AI.

    Must be called at the top of each agent's agent.py, before any
    google-cloud imports. Reads PROJECT_ID or VERTEXAI_PROJECT and
    normalizes GOOGLE_CLOUD_PROJECT, VERTEXAI_PROJECT, and LiteLLM
    telemetry settings.

    Args:
        agent_label: Short identifier for log messages (e.g. "simulator").
    """
    pid = os.environ.get("PROJECT_ID") or os.environ.get("VERTEXAI_PROJECT")
    if pid:
        os.environ["GOOGLE_CLOUD_PROJECT"] = pid
        os.environ["VERTEXAI_PROJECT"] = pid
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        os.environ["LITELLM_TELEMETRY"] = "False"
        print(
            f"{agent_label.upper()}_INIT: Overrode GOOGLE_CLOUD_PROJECT with {pid}",
            file=sys.stderr,
        )
    else:
        print(
            f"{agent_label.upper()}_INIT: WARNING - Project ID not found in env. Keys: {list(os.environ.keys())}",
            file=sys.stderr,
        )
