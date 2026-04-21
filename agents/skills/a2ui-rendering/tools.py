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

"""A2UI v0.8.0 validation tool for the ADK agent framework.

Validates A2UI payloads against the v0.8.0 specification: component types,
required properties, typed value wrappers, ID uniqueness, and reference
resolution.
"""

import json
import logging
from typing import Any

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# A2UI v0.8.0 catalog constants
# ---------------------------------------------------------------------------

VALID_TYPES: set[str] = {
    "Text",
    "Image",
    "Icon",
    "Video",
    "AudioPlayer",
    "Row",
    "Column",
    "List",
    "Card",
    "Tabs",
    "Modal",
    "Divider",
    "Button",
    "TextField",
    "CheckBox",
    "Slider",
    "MultipleChoice",
    "DateTimeInput",
}

REQUIRED_PROPS: dict[str, list[str]] = {
    "Text": ["text"],
    "Image": ["url"],
    "Icon": ["name"],
    "Video": ["url"],
    "AudioPlayer": ["url"],
    "Button": ["child", "action"],
    "TextField": ["label"],
    "CheckBox": ["label"],
    "Slider": ["value"],
    "MultipleChoice": ["selections"],
    "Card": ["child"],
    "Modal": ["entryPointChild", "contentChild"],
    "Tabs": ["tabItems"],
    "Row": ["children"],
    "Column": ["children"],
    "List": ["children"],
}

# Properties that must use typed string wrappers (literalString or path)
STRING_PROPS: set[str] = {"text", "url", "name", "label", "description"}

# Properties that must use typed boolean wrappers (literalBoolean or path)
BOOLEAN_PROPS: set[str] = {"autoplay", "primary"}

# Container types that require children with explicitList format
CONTAINER_TYPES: set[str] = {"Row", "Column", "List"}

# Valid top-level A2UI message type keys
VALID_MESSAGE_TYPES: set[str] = {
    "beginRendering",
    "surfaceUpdate",
    "dataModelUpdate",
    "deleteSurface",
}


# ---------------------------------------------------------------------------
# Violation helper
# ---------------------------------------------------------------------------


def _violation(
    component_id: str,
    field: str,
    message: str,
) -> dict[str, str]:
    """Create a structured violation dict."""
    return {
        "component_id": component_id,
        "field": field,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_typed_wrapper(
    component_id: str,
    prop_name: str,
    prop_value: Any,
    violations: list[dict[str, str]],
) -> None:
    """Validate that a property uses the correct typed value wrapper."""
    if prop_name in STRING_PROPS:
        if not isinstance(prop_value, dict) or ("literalString" not in prop_value and "path" not in prop_value):
            violations.append(
                _violation(
                    component_id,
                    prop_name,
                    f"Property '{prop_name}' must use a typed wrapper "
                    f'({{"literalString": "..."}} or {{"path": "..."}}) '
                    f"instead of a raw value.",
                )
            )
    elif prop_name in BOOLEAN_PROPS:
        if not isinstance(prop_value, dict) or ("literalBoolean" not in prop_value and "path" not in prop_value):
            violations.append(
                _violation(
                    component_id,
                    prop_name,
                    f"Property '{prop_name}' must use a typed wrapper "
                    f'({{"literalBoolean": ...}} or {{"path": "..."}}) '
                    f"instead of a raw value.",
                )
            )


def _validate_children_format(
    component_id: str,
    comp_type: str,
    props: dict[str, Any],
    violations: list[dict[str, str]],
) -> None:
    """Validate that container children use explicitList format."""
    if comp_type not in CONTAINER_TYPES:
        return
    children = props.get("children")
    if children is None:
        return
    if isinstance(children, list):
        violations.append(
            _violation(
                component_id,
                "children",
                f"Container '{comp_type}' must use "
                f'{{"children": {{"explicitList": [...]}}}} '
                f"instead of a raw array. Wrap with explicitList.",
            )
        )
    elif isinstance(children, dict):
        if "explicitList" not in children:
            violations.append(
                _violation(
                    component_id,
                    "children",
                    f"Container '{comp_type}' children dict must contain an 'explicitList' key.",
                )
            )


def _collect_referenced_ids(
    component_id: str,
    comp_type: str,
    props: dict[str, Any],
    refs: list[tuple[str, str, str]],
) -> None:
    """Collect all component ID references for resolution checking.

    Each entry in *refs* is (component_id, field_name, referenced_id).
    """
    # child (Card, Modal entryPointChild/contentChild)
    for field in ("child", "entryPointChild", "contentChild"):
        val = props.get(field)
        if isinstance(val, str):
            refs.append((component_id, field, val))

    # children.explicitList
    children = props.get("children")
    if isinstance(children, dict):
        explicit = children.get("explicitList")
        if isinstance(explicit, list):
            for ref_id in explicit:
                if isinstance(ref_id, str):
                    refs.append((component_id, "children.explicitList", ref_id))

    # tabItems[].child
    tab_items = props.get("tabItems")
    if isinstance(tab_items, list):
        for i, item in enumerate(tab_items):
            if isinstance(item, dict):
                child_ref = item.get("child")
                if isinstance(child_ref, str):
                    refs.append((component_id, f"tabItems[{i}].child", child_ref))


def _validate_surface_update(
    data: dict[str, Any],
) -> list[dict[str, str]]:
    """Validate a surfaceUpdate message's components array."""
    violations: list[dict[str, str]] = []

    surface_update = data.get("surfaceUpdate", {})
    components = surface_update.get("components", [])

    if not isinstance(components, list):
        violations.append(_violation("", "surfaceUpdate.components", "components must be an array."))
        return violations

    # Pass 1: collect IDs, validate types, required props, wrappers, children
    seen_ids: dict[str, int] = {}
    all_ids: set[str] = set()
    refs: list[tuple[str, str, str]] = []

    for entry in components:
        if not isinstance(entry, dict):
            violations.append(_violation("", "component", "Each component entry must be an object."))
            continue

        comp_id = entry.get("id", "")
        component_def = entry.get("component", {})

        if not isinstance(component_def, dict) or not component_def:
            violations.append(_violation(comp_id, "component", "Missing or empty component definition."))
            continue

        # ID uniqueness
        if comp_id in seen_ids:
            violations.append(
                _violation(
                    comp_id,
                    "id",
                    f"Duplicate component ID '{comp_id}'. IDs must be unique within a surfaceUpdate.",
                )
            )
        seen_ids[comp_id] = seen_ids.get(comp_id, 0) + 1
        all_ids.add(comp_id)

        # Component type
        comp_type = next(iter(component_def), None)
        if comp_type not in VALID_TYPES:
            violations.append(
                _violation(
                    comp_id,
                    "component",
                    f"Unknown component type '{comp_type}'. Valid types: {sorted(VALID_TYPES)}.",
                )
            )
            continue

        props = component_def.get(comp_type, {})
        if not isinstance(props, dict):
            props = {}

        # Required properties
        required = REQUIRED_PROPS.get(comp_type, [])
        for req_prop in required:
            if req_prop not in props:
                violations.append(
                    _violation(
                        comp_id,
                        req_prop,
                        f"Component '{comp_type}' requires property '{req_prop}'.",
                    )
                )

        # Typed value wrappers
        for prop_name, prop_value in props.items():
            _validate_typed_wrapper(comp_id, prop_name, prop_value, violations)

        # Children format
        _validate_children_format(comp_id, comp_type, props, violations)

        # Collect references for resolution check
        _collect_referenced_ids(comp_id, comp_type, props, refs)

    # Pass 2: resolve references
    for source_id, field, ref_id in refs:
        if ref_id not in all_ids:
            violations.append(
                _violation(
                    source_id,
                    field,
                    f"Reference '{ref_id}' does not resolve to any component ID in this surfaceUpdate.",
                )
            )

    return violations


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------


# [START a2ui_validation_tool]
async def validate_and_emit_a2ui(
    payload: str,
    tool_context: ToolContext,
) -> dict:
    """Validate an A2UI v0.8.0 JSON payload and return it for rendering.

    Args:
        payload: A JSON string containing a valid A2UI v0.8.0 message
            (surfaceUpdate, beginRendering, dataModelUpdate, or deleteSurface).
        tool_context: ADK tool context (unused but required by framework).

    Returns:
        On success: {"status": "success", "a2ui": <validated_payload>}
        On failure: {"status": "error", "violations": [...], "suggestion": "..."}
            Each violation is a dict with "component_id", "field", and "message" keys.
    """
    # 1. JSON parsing — detect concatenated objects and unwrap {"a2ui": ...}
    try:
        decoder = json.JSONDecoder()
        stripped = payload.strip()
        data, end_idx = decoder.raw_decode(stripped)
        trailing = stripped[end_idx:].strip()
        if trailing:
            # Distinguish genuine concatenated JSON ({...}{...}) from a
            # mechanical model emission slip (extra brace, dangling text).
            # Only the former is a real "two messages in one call" bug we
            # want to surface to the model. The latter just causes the model
            # to retry identically (planner_with_memory's "9-card storm") or
            # give up and emit text only (planner_with_eval). See
            # docs/plans/2026-04-19-a2ui-validator-lenient-trailing-garbage-design.md.
            try:
                decoder.raw_decode(trailing)
            except (json.JSONDecodeError, ValueError):
                # Trailing content is not a parseable JSON object — drop it
                # silently and proceed with the first valid object.
                logger.warning(
                    "A2UI validator: ignoring %d bytes of trailing garbage after valid JSON object: %r",
                    len(trailing),
                    trailing[:80],
                )
            else:
                return {
                    "status": "error",
                    "violations": [
                        _violation(
                            "",
                            "payload",
                            "Multiple JSON objects detected. Combine all routes "
                            "into a single surfaceUpdate with one components array. "
                            "Call validate_and_emit_a2ui once per message type.",
                        ),
                    ],
                    "suggestion": (
                        "Build ONE surfaceUpdate containing ALL route cards in a "
                        "single flat components array. Do NOT concatenate separate "
                        "JSON objects."
                    ),
                }
    except (json.JSONDecodeError, TypeError) as exc:
        return {
            "status": "error",
            "violations": [
                _violation("", "payload", f"Invalid JSON: {exc}"),
            ],
            "suggestion": "Provide a valid JSON string.",
        }

    if not isinstance(data, dict):
        return {
            "status": "error",
            "violations": [
                _violation("", "payload", "Payload must be a JSON object."),
            ],
            "suggestion": "Wrap your payload in a JSON object.",
        }

    # Unwrap {"a2ui": {...}} wrapper if present (common LLM mistake —
    # the wrapper is the tool's *output* format, not its input format).
    if "a2ui" in data and isinstance(data["a2ui"], dict) and len(data) == 1:
        data = data["a2ui"]

    # 2. Message type dispatch
    detected_type = None
    for msg_type in VALID_MESSAGE_TYPES:
        if msg_type in data:
            detected_type = msg_type
            break

    if detected_type is None:
        return {
            "status": "error",
            "violations": [
                _violation(
                    "",
                    "message_type",
                    f"No recognized A2UI message type found. Expected one of: {sorted(VALID_MESSAGE_TYPES)}.",
                ),
            ],
            "suggestion": ("Include one of: beginRendering, surfaceUpdate, dataModelUpdate, or deleteSurface."),
        }

    # 3. For surfaceUpdate, run full component validation
    violations: list[dict[str, str]] = []
    if detected_type == "surfaceUpdate":
        violations = _validate_surface_update(data)

    if violations:
        return {
            "status": "error",
            "violations": violations,
            "suggestion": ("Fix the listed violations to produce a valid A2UI v0.8.0 payload."),
        }

    logger.debug("A2UI payload validated successfully (type=%s)", detected_type)

    return {
        "status": "success",
        "a2ui": data,
    }
# [END a2ui_validation_tool]
