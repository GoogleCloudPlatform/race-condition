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

# agents/utils/test_env.py
import os
from unittest.mock import patch


class TestConfigureProjectEnv:
    def test_overrides_google_cloud_project_from_project_id(self):
        with patch.dict(os.environ, {"PROJECT_ID": "my-project"}, clear=False):
            os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            from agents.utils.env import configure_project_env

            configure_project_env("test_agent")
            assert os.environ["GOOGLE_CLOUD_PROJECT"] == "my-project"
            assert os.environ["VERTEXAI_PROJECT"] == "my-project"

    def test_overrides_from_vertexai_project_fallback(self):
        env = {"VERTEXAI_PROJECT": "vx-project"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PROJECT_ID", None)
            os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            from agents.utils.env import configure_project_env

            configure_project_env("test_agent")
            assert os.environ["GOOGLE_CLOUD_PROJECT"] == "vx-project"

    def test_noop_when_no_project_id(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROJECT_ID", None)
            os.environ.pop("VERTEXAI_PROJECT", None)
            os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
            from agents.utils.env import configure_project_env

            configure_project_env("test_agent")
            assert "GOOGLE_CLOUD_PROJECT" not in os.environ

    def test_sets_litellm_vars(self):
        with patch.dict(os.environ, {"PROJECT_ID": "p"}, clear=False):
            from agents.utils.env import configure_project_env

            configure_project_env("test_agent")
            assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"
            assert os.environ["LITELLM_TELEMETRY"] == "False"
