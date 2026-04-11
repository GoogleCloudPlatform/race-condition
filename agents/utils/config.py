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

import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def load_env():
    """Load environment variables from .env file."""
    if not load_dotenv():
        logger.warning("⚠️  Warning: No .env file found. Using system environment variables.")


def require(key: str) -> str:
    """Return an environment variable or raise ValueError if missing."""
    val = os.getenv(key)
    if not val:
        error_msg = (
            f"❌ CRITICAL ERROR: Required configuration variable '{key}' is missing.\n"
            "Please ensure it is set in your .env file or environment.\n"
            "Check .env.example for required variables."
        )
        raise ValueError(error_msg)
    return val


def optional(key: str, default: str) -> str:
    """Return an environment variable or a default value if missing."""
    val = os.getenv(key)
    if not val:
        return default
    return val
