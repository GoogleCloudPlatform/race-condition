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

# agents/utils/tests/test_prompt_builder.py
from collections import OrderedDict

from agents.utils.prompt_builder import PromptBuilder


class TestPromptBuilder:
    def test_build_joins_sections(self):
        b = PromptBuilder(OrderedDict(role="# Role", tools="# Tools"))
        assert b.build() == "# Role\n\n# Tools"

    def test_override_replaces_section(self):
        b = PromptBuilder(OrderedDict(role="# Role", workflow="# V1"))
        b2 = b.override(workflow="# V2")
        assert "# V2" in b2.build()
        assert "# V1" not in b2.build()

    def test_override_is_immutable(self):
        b = PromptBuilder(OrderedDict(role="# Role", workflow="# V1"))
        b.override(workflow="# V2")
        assert "# V1" in b.build()

    def test_override_adds_new_section(self):
        b = PromptBuilder(OrderedDict(role="# Role"))
        b2 = b.override(memory="# Memory")
        assert "# Memory" in b2.build()
        assert "# Role" in b2.build()

    def test_override_preserves_order(self):
        b = PromptBuilder(OrderedDict(role="# Role", tools="# Tools", workflow="# Workflow"))
        b2 = b.override(tools="# NewTools")
        parts = b2.build().split("\n\n")
        assert parts == ["# Role", "# NewTools", "# Workflow"]

    def test_static_joins_named_keys(self):
        b = PromptBuilder(OrderedDict(role="# Role", rules="# Rules", tools="# Tools"))
        assert b.static("role", "rules") == "# Role\n\n# Rules"

    def test_static_ignores_missing_keys(self):
        b = PromptBuilder(OrderedDict(role="# Role"))
        assert b.static("role", "missing") == "# Role"

    def test_dynamic_excludes_static_keys(self):
        b = PromptBuilder(OrderedDict(role="# Role", rules="# Rules", tools="# Tools"))
        provider = b.dynamic(exclude=("role", "rules"))
        # Provider is a callable; test with a mock ReadonlyContext
        from unittest.mock import MagicMock

        ctx = MagicMock()
        import asyncio
        from typing import cast, Coroutine, Any

        result = asyncio.run(cast(Coroutine[Any, Any, str], provider(ctx)))
        assert result == "# Tools"
        assert "# Role" not in result

    def test_build_skips_empty_sections(self):
        b = PromptBuilder(OrderedDict(role="# Role", empty="", tools="# Tools"))
        assert b.build() == "# Role\n\n# Tools"

    def test_sections_property_returns_copy(self):
        b = PromptBuilder(OrderedDict(role="# Role"))
        s = b.sections
        s["injected"] = "bad"
        assert "injected" not in b.sections
