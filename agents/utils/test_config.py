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
import pytest
from agents.utils.config import require, optional


def test_require():
    # Set a test variable
    os.environ["TEST_REQUIRED_VAR"] = "value"
    try:
        assert require("TEST_REQUIRED_VAR") == "value"
    finally:
        del os.environ["TEST_REQUIRED_VAR"]

    # Test ValueError on missing variable
    with pytest.raises(ValueError) as excinfo:
        require("NON_EXISTENT_VAR")
    assert "CRITICAL ERROR" in str(excinfo.value)
    assert "NON_EXISTENT_VAR" in str(excinfo.value)


def test_optional():
    # Set a test variable
    os.environ["TEST_OPTIONAL_VAR"] = "value"
    try:
        assert optional("TEST_OPTIONAL_VAR", "default") == "value"
    finally:
        del os.environ["TEST_OPTIONAL_VAR"]

    # Test default value on missing variable
    assert optional("MISSING_OPTIONAL_VAR", "default_val") == "default_val"
