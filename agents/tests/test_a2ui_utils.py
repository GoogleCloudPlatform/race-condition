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
from agents.utils.a2ui import (
    create_payload,
    wrap_string,
    Surface,
    text_props,
    video_props,
)


def test_create_payload_v080_standard():
    """Verify that create_payload produces a strictly compliant v0.8.0 payload."""
    payload_str = create_payload("Video", {"url": wrap_string("test.mp4")})
    assert "```a2ui" not in payload_str

    # Parse JSON
    data = json.loads(payload_str)

    # MUST use nested component wrapper
    assert "id" in data
    assert "component" in data
    assert "Video" in data["component"]
    # MUST use structured properties
    assert data["component"]["Video"]["url"]["literalString"] == "test.mp4"


def test_create_payload_markdown_wrapped():
    """Verify that create_payload optionally wraps in Markdown fences."""
    payload_str = create_payload("Video", {"url": wrap_string("test.mp4")}, wrap_markdown=True)
    assert "```a2ui" in payload_str
    assert "```" in payload_str


def test_surface_creation():
    """Verify Surface class produces a valid surfaceUpdate message."""
    s = Surface(surface_id="s1")
    t1 = s.add("Text", text_props("Hello"))
    v1 = s.add("Video", video_props("video.mp4"))

    payload = s.to_json()
    assert "surfaceUpdate" in payload
    assert payload["surfaceUpdate"]["surfaceId"] == "s1"
    assert len(payload["surfaceUpdate"]["components"]) == 2

    # Check Text
    text_comp = payload["surfaceUpdate"]["components"][0]
    assert text_comp["id"] == t1
    assert text_comp["component"]["Text"]["text"]["literalString"] == "Hello"

    # Check Video
    video_comp = payload["surfaceUpdate"]["components"][1]
    assert video_comp["id"] == v1
    assert video_comp["component"]["Video"]["url"]["literalString"] == "video.mp4"


def test_surface_to_payload():
    """Verify that Surface.to_payload wraps correctly."""
    s = Surface()
    s.add("Text", text_props("Hello"))

    # Default: clean JSON
    payload_str = s.to_payload()
    assert "```a2ui" not in payload_str
    assert "surfaceUpdate" in payload_str

    # Optional: Markdown wrapped
    wrapped_str = s.to_payload(wrap_markdown=True)
    assert "```a2ui" in wrapped_str
    assert "```" in wrapped_str
