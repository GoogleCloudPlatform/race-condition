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

import json
import uuid
from typing import Union, List, Optional, Dict, Any


def wrap_string(value: Union[str, Dict[str, str]]) -> Dict[str, str]:
    if isinstance(value, dict) and ("literalString" in value or "path" in value):
        return value
    return {"literalString": str(value)}


def wrap_number(value: Union[float, int, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(value, dict) and ("literalNumber" in value or "path" in value):
        return value
    if isinstance(value, dict):
        return {"literalNumber": 0.0}
    return {"literalNumber": float(value)}


def wrap_boolean(value: Union[bool, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(value, dict) and ("literalBoolean" in value or "path" in value):
        return value
    return {"literalBoolean": bool(value)}


def wrap_string_list(values: List[str]) -> Dict[str, List[str]]:
    return {"explicitList": values}


def create_payload(
    primitive: str,
    args: Dict[str, Any],
    component_id: Optional[str] = None,
    wrap_markdown: bool = False,
) -> str:
    """Helper for single-component blocks, still wrapped in component/id for compliance."""
    cid = component_id or f"c_{uuid.uuid4().hex[:8]}"
    payload = {"id": cid, "component": {primitive: args}}
    json_str = json.dumps(payload, indent=2)
    return f"```a2ui\n{json_str}\n```" if wrap_markdown else json_str


class Surface:
    """A collection of A2UI components forming a surfaceUpdate message."""

    def __init__(self, surface_id: Optional[str] = None):
        self.surface_id = surface_id or f"s_{uuid.uuid4().hex[:8]}"
        self.components = []

    def add(self, primitive: str, args: Dict[str, Any], component_id: Optional[str] = None) -> str:
        cid = component_id or f"c_{uuid.uuid4().hex[:8]}"
        self.components.append({"id": cid, "component": {primitive: args}})
        return cid

    def to_json(self) -> Dict[str, Any]:
        return {
            "surfaceUpdate": {
                "surfaceId": self.surface_id,
                "components": self.components,
            }
        }

    def to_payload(self, wrap_markdown: bool = False) -> str:
        json_str = json.dumps(self.to_json(), indent=2)
        return f"```a2ui\n{json_str}\n```" if wrap_markdown else json_str


def begin_rendering(root_id: str, surface_id: Optional[str] = None, wrap_markdown: bool = False) -> str:
    """Creates a beginRendering payload to signal the client to start rendering."""
    payload: Dict[str, Any] = {"beginRendering": {"root": root_id}}
    if surface_id:
        payload["surfaceId"] = surface_id
    json_str = json.dumps(payload, indent=2)
    return f"```a2ui\n{json_str}\n```" if wrap_markdown else json_str


def data_model_update(
    path: str,
    contents: Any,
    surface_id: Optional[str] = None,
    wrap_markdown: bool = False,
) -> str:
    """Creates a dataModelUpdate payload to modify the client's data model."""
    payload: Dict[str, Any] = {"dataModelUpdate": {"path": path, "contents": contents}}
    if surface_id:
        payload["surfaceId"] = surface_id
    json_str = json.dumps(payload, indent=2)
    return f"```a2ui\n{json_str}\n```" if wrap_markdown else json_str


# --- 18 Standard Catalog Primitive Property Builders ---


# 1. Text
def text_props(content: str, usageHint: str = "body") -> Dict[str, Any]:
    return {"text": wrap_string(content), "usageHint": usageHint}


# 2. Image
def image_props(url: str, fit: str = "contain", usageHint: str = "mediumFeature") -> Dict[str, Any]:
    return {"url": wrap_string(url), "fit": fit, "usageHint": usageHint}


# 3. Icon
def icon_props(name: str) -> Dict[str, Any]:
    return {"name": wrap_string(name)}


# 4. Video
def video_props(url: str, autoplay: bool = False) -> Dict[str, Any]:
    return {"url": wrap_string(url), "autoplay": wrap_boolean(autoplay)}


# 5. AudioPlayer
def audio_player_props(url: str, description: str = "") -> Dict[str, Any]:
    return {"url": wrap_string(url), "description": wrap_string(description)}


# 6. Row
def row_props(children: List[str], distribution: str = "start", alignment: str = "start") -> Dict[str, Any]:
    return {
        "children": wrap_string_list(children),
        "distribution": distribution,
        "alignment": alignment,
    }


# 7. Column
def column_props(children: List[str], distribution: str = "start", alignment: str = "start") -> Dict[str, Any]:
    return {
        "children": wrap_string_list(children),
        "distribution": distribution,
        "alignment": alignment,
    }


# 8. List (Vertical or Horizontal)
def list_props(children: List[str], direction: str = "vertical", alignment: str = "start") -> Dict[str, Any]:
    return {
        "children": wrap_string_list(children),
        "direction": direction,
        "alignment": alignment,
    }


# 9. Tabs
def tabs_props(tabs: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Each tab: { "id": "t1", "label": "Tab 1", "child": "c1" }
    return {"tabItems": [{"title": wrap_string(t["label"]), "child": t["child"]} for t in tabs]}


# 10. Card
def card_props(child: str) -> Dict[str, Any]:
    return {"child": child}


# 11. Modal
def modal_props(entryPointChild: str, contentChild: str) -> Dict[str, Any]:
    return {"entryPointChild": entryPointChild, "contentChild": contentChild}


# 12. Divider
def divider_props(axis: str = "horizontal") -> Dict[str, Any]:
    return {"axis": axis}


# 13. Button
def button_props(
    child: str,
    action_name: str,
    context: Optional[List[Dict[str, Any]]] = None,
    primary: bool = False,
    payload: Optional[Any] = None,
) -> Dict[str, Any]:
    action: Dict[str, Any] = {"name": action_name}
    if context:
        action["context"] = context
    if payload:
        action["payload"] = payload
    return {"child": child, "action": action, "primary": primary}


# 14. TextField
def text_field_props(
    label: str,
    path: Optional[str] = None,
    text: Optional[str] = None,
    textFieldType: str = "shortText",
) -> Dict[str, Any]:
    props = {"label": wrap_string(label), "textFieldType": textFieldType}
    if path:
        props["text"] = {"path": path}
    elif text:
        props["text"] = {"literalString": text}
    return props


# 15. CheckBox
def checkbox_props(label: str, path: Optional[str] = None, checked: Optional[bool] = None) -> Dict[str, Any]:
    val = {}
    if path:
        val = {"path": path}
    elif checked is not None:
        val = {"literalBoolean": checked}
    return {"label": wrap_string(label), "value": val}


# 16. Slider
def slider_props(
    path: Optional[str] = None,
    value: Optional[float] = None,
    min_val: float = 0.0,
    max_val: float = 100.0,
) -> Dict[str, Any]:
    val = {}
    if path:
        val = {"path": path}
    elif value is not None:
        val = {"literalNumber": value}
    return {"value": val, "minValue": min_val, "maxValue": max_val}


# 17. MultiChoice
def multi_choice_props(
    options: List[Dict[str, str]],
    path: Optional[str] = None,
    selections: Optional[List[str]] = None,
    max_allowed: int = 1,
) -> Dict[str, Any]:
    sel = {}
    if path:
        sel = {"path": path}
    elif selections is not None:
        sel = {"literalArray": selections}
    return {
        "options": [{"label": wrap_string(o["label"]), "value": o["value"]} for o in options],
        "selections": sel,
        "maxAllowedSelections": max_allowed,
    }


# 18. DateTimeInput
def date_time_input_props(
    path: Optional[str] = None,
    value: Optional[str] = None,
    enableDate: bool = True,
    enableTime: bool = True,
) -> Dict[str, Any]:
    val = {}
    if path:
        val = {"path": path}
    elif value:
        val = {"literalString": value}
    return {"value": val, "enableDate": enableDate, "enableTime": enableTime}
