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

"""Frontmatter compliance check for all SKILL.md files under agents/.

Enforces Anthropic skill-authoring rules and the ADK Frontmatter schema:

* ``name`` is kebab-case and at most 64 characters.
* ``description`` is non-empty, at most 1024 characters, starts with
  ``"Use when"`` (case-insensitive), and is third-person (no I/you/we).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

_AGENTS_DIR = pathlib.Path(__file__).resolve().parents[1]
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FIRST_SECOND_PERSON = re.compile(
    r"\b(I|you|your|you're|you've|you'll|we|our|us|me|my)\b",
    re.IGNORECASE,
)


def _skill_md_files() -> list[pathlib.Path]:
    return sorted(_AGENTS_DIR.rglob("SKILL.md"))


def _parse_frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError(f"{path}: missing YAML frontmatter")
    _, fm, _body = text.split("---", 2)
    return yaml.safe_load(fm) or {}


@pytest.mark.parametrize(
    "skill_path",
    _skill_md_files(),
    ids=lambda p: str(p.relative_to(_AGENTS_DIR)),
)
def test_skill_frontmatter_is_compliant(skill_path: pathlib.Path) -> None:
    fm = _parse_frontmatter(skill_path)

    name = fm.get("name")
    assert isinstance(name, str) and name, f"{skill_path}: name required"
    assert len(name) <= 64, f"{skill_path}: name >64 chars"
    assert _NAME_PATTERN.match(name), (
        f"{skill_path}: name {name!r} must be kebab-case "
        "(lowercase a-z, 0-9, hyphens)"
    )

    desc = fm.get("description")
    assert isinstance(desc, str) and desc.strip(), (
        f"{skill_path}: description required"
    )
    assert len(desc) <= 1024, f"{skill_path}: description >1024 chars"

    desc_clean = " ".join(desc.split())
    assert desc_clean.lower().startswith("use when"), (
        f"{skill_path}: description must start with 'Use when' "
        f"(got: {desc_clean[:60]!r})"
    )
    match = _FIRST_SECOND_PERSON.search(desc_clean)
    assert match is None, (
        f"{skill_path}: description must be third-person, "
        f"found {match.group()!r} in {desc_clean[:80]!r}"
    )


@pytest.mark.parametrize(
    "skill_path",
    [
        _AGENTS_DIR / "planner" / "skills" / "insecure-financial-modeling" / "SKILL.md",
        _AGENTS_DIR / "planner" / "skills" / "secure-financial-modeling" / "SKILL.md",
    ],
    ids=["insecure", "secure"],
)
def test_financial_skills_delegate_a2ui_to_shared_skill(
    skill_path: pathlib.Path,
) -> None:
    """Financial skills must reference a2ui-rendering, not duplicate it.

    Inline A2UI structure rots when the shared protocol evolves. The fix
    is a cross-reference to the a2ui-rendering skill, which carries the
    canonical message structure, typed value wrappers, and component
    catalog.
    """
    body = skill_path.read_text(encoding="utf-8")
    inline_json_block = re.compile(
        r"```json\s.*?surfaceUpdate.*?```", re.DOTALL
    )
    assert inline_json_block.search(body) is None, (
        f"{skill_path}: inline A2UI surfaceUpdate JSON detected in a "
        "fenced code block; cross-reference the a2ui-rendering skill "
        "instead of duplicating the protocol."
    )
    assert "a2ui-rendering" in body, (
        f"{skill_path}: must cross-reference the a2ui-rendering skill."
    )


def test_a2ui_rendering_skill_body_is_concise() -> None:
    """The shared a2ui-rendering skill loads on every agent that uses A2UI;
    keep its body under 200 lines so the frequently-loaded budget is met.

    Heavier reference material (the 18-primitive catalog, full payload
    examples) lives in sibling files one level deep from SKILL.md.
    """
    skill = _AGENTS_DIR / "skills" / "a2ui-rendering" / "SKILL.md"
    body_lines = skill.read_text(encoding="utf-8").splitlines()
    assert len(body_lines) < 200, (
        f"{skill}: {len(body_lines)} lines; split heavy reference into "
        "sibling files (components.md, examples.md) one level deep "
        "from SKILL.md."
    )
