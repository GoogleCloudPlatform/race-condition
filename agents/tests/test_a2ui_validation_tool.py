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

"""Tests for the A2UI v0.8.0 validation tool.

Validates that validate_and_emit_a2ui correctly accepts valid A2UI payloads
and rejects invalid ones with detailed violation reports.
"""

import importlib.util
import json
import pathlib
from unittest.mock import MagicMock

import pytest

# Load the tool module from hyphenated skill directory
_tools_path = pathlib.Path(__file__).parent.parent / "skills" / "a2ui-rendering" / "tools.py"
_spec = importlib.util.spec_from_file_location("a2ui_rendering_tools", _tools_path)
assert _spec is not None, f"Could not find module spec for {_tools_path}"
assert _spec.loader is not None, f"Module spec has no loader for {_tools_path}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
validate_and_emit_a2ui = _mod.validate_and_emit_a2ui


@pytest.fixture
def tool_context():
    """Pre-built ToolContext mock."""
    return MagicMock()


@pytest.mark.asyncio
async def test_valid_single_text_component(tool_context):
    """Valid Text component passes validation."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "text-1",
                        "component": {
                            "Text": {
                                "text": {"literalString": "Hello, World!"},
                            },
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "success"
    assert "a2ui" in result


@pytest.mark.asyncio
async def test_valid_card_with_column(tool_context):
    """Card > Column > 2 Texts passes validation."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "text-1",
                        "component": {
                            "Text": {"text": {"literalString": "Line 1"}},
                        },
                    },
                    {
                        "id": "text-2",
                        "component": {
                            "Text": {"text": {"literalString": "Line 2"}},
                        },
                    },
                    {
                        "id": "col-1",
                        "component": {
                            "Column": {
                                "children": {"explicitList": ["text-1", "text-2"]},
                            },
                        },
                    },
                    {
                        "id": "card-1",
                        "component": {
                            "Card": {"child": "col-1"},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "success"
    assert "a2ui" in result


@pytest.mark.asyncio
async def test_invalid_component_type(tool_context):
    """Unknown component type 'FancyWidget' fails with violation."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "fw-1",
                        "component": {
                            "FancyWidget": {"text": {"literalString": "Nope"}},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"
    assert any("FancyWidget" in v["message"] for v in result["violations"])


@pytest.mark.asyncio
async def test_duplicate_component_ids(tool_context):
    """Duplicate component IDs fail with 'duplicate' in message."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "dup",
                        "component": {
                            "Text": {"text": {"literalString": "First"}},
                        },
                    },
                    {
                        "id": "dup",
                        "component": {
                            "Text": {"text": {"literalString": "Second"}},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"
    assert any("duplicate" in v["message"].lower() for v in result["violations"])


@pytest.mark.asyncio
async def test_dangling_child_reference(tool_context):
    """Card with child referencing 'nonexistent' ID fails."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "card-1",
                        "component": {
                            "Card": {"child": "nonexistent"},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"
    assert any("nonexistent" in v["message"] for v in result["violations"])


@pytest.mark.asyncio
async def test_raw_string_instead_of_literal_wrapper(tool_context):
    """Text with raw string 'text' value fails with wrapper hint."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "text-1",
                        "component": {
                            "Text": {"text": "raw string"},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"
    violations_text = " ".join(v["message"] for v in result["violations"])
    assert "literalString" in violations_text or "typed wrapper" in violations_text


@pytest.mark.asyncio
async def test_invalid_json_input(tool_context):
    """Non-JSON input fails gracefully."""
    result = await validate_and_emit_a2ui(payload="not json at all", tool_context=tool_context)
    assert result["status"] == "error"
    assert "violations" in result


@pytest.mark.asyncio
async def test_begin_rendering_valid(tool_context):
    """Valid beginRendering message passes."""
    payload = json.dumps(
        {
            "beginRendering": {"root": "card-1"},
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "success"
    assert "a2ui" in result


@pytest.mark.asyncio
async def test_missing_surface_update_structure(tool_context):
    """Payload with no recognized message type fails."""
    payload = json.dumps({"random": "data"})
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_children_without_explicit_list(tool_context):
    """Column with raw array children fails with 'explicitList' hint."""
    payload = json.dumps(
        {
            "surfaceUpdate": {
                "components": [
                    {
                        "id": "t1",
                        "component": {
                            "Text": {"text": {"literalString": "Hi"}},
                        },
                    },
                    {
                        "id": "col-1",
                        "component": {
                            "Column": {"children": ["t1"]},
                        },
                    },
                ],
            },
            "surfaceId": "test",
        }
    )
    result = await validate_and_emit_a2ui(payload=payload, tool_context=tool_context)
    assert result["status"] == "error"
    assert any("explicitList" in v["message"] for v in result["violations"])
