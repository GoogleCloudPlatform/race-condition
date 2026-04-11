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

"""Root conftest for the Race Condition OSS repo.

Provides mock GCP credentials so agent modules can be imported without
real Google Cloud credentials. This runs before test collection, which
is critical because several agent modules initialize the Vertex AI SDK
at import time.

Tests that make real GCP API calls should be marked with @pytest.mark.slow
and will be skipped in CI (pytest -m "not slow").
"""

import os
from unittest.mock import MagicMock, patch

# If no real credentials are configured, patch google.auth.default to
# return mock credentials.  This must happen at module level (before
# pytest collects test files) because agent __init__.py files trigger
# Vertex AI initialization during import.
_has_real_credentials = (
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    or os.environ.get("CLOUDSDK_CONFIG")
    # Running on GCE / Cloud Build / Workload Identity
    or os.path.exists("/run/secrets/kubernetes.io")
)

if not _has_real_credentials:
    _mock_creds = MagicMock()
    _mock_creds.token = "mock-token"
    _mock_creds.valid = True
    _mock_creds.project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project")

    _patcher = patch(
        "google.auth.default",
        return_value=(_mock_creds, _mock_creds.project_id),
    )
    _patcher.start()
    # Note: we intentionally never call _patcher.stop() -- the mock
    # must remain active for the entire test session since agent modules
    # cache the credentials at import time.
