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

import importlib.util
import logging
import os
import pathlib
import subprocess

from google.adk.skills import load_skill_from_dir
from google.adk.integrations.api_registry import ApiRegistry
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)

# Cached resolved key. None means "not yet resolved"; "" means "resolved but empty".
_resolved_maps_key: str | None = None


def _resolve_maps_key() -> str | None:
    """Resolve GOOGLE_MAPS_API_KEY: env var first, then Secret Manager.

    Resolution order:
    1. GOOGLE_MAPS_API_KEY env var (if non-empty)
    2. gcloud secrets versions access latest --secret=maps-api-key
    3. None (Maps tools disabled)

    Result is cached after first call.
    """
    global _resolved_maps_key
    if _resolved_maps_key is not None:
        return _resolved_maps_key or None

    # 1. Env var takes priority
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if key:
        _resolved_maps_key = key
        return key

    # 2. Try Secret Manager via gcloud CLI
    project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
    if project:
        try:
            result = subprocess.run(
                [
                    "gcloud",
                    "secrets",
                    "versions",
                    "access",
                    "latest",
                    "--secret=maps-api-key",
                    f"--project={project}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
            key = result.stdout.strip()
            if key:
                logger.info("Resolved GOOGLE_MAPS_API_KEY from Secret Manager")
                _resolved_maps_key = key
                return key
        except Exception:
            logger.debug("Secret Manager lookup failed; Maps MCP tools disabled")

    # 3. Not available
    _resolved_maps_key = ""
    return None


def header_provider(context):  # noqa: ANN001
    """Return headers for Maps API requests using API key auth."""
    maps_key = _resolve_maps_key()
    headers = {
        "X-Goog-Api-Key": maps_key or "",
        "Content-Type": "application/json",
    }
    return headers


class MapsApiRegistry(ApiRegistry):
    """ApiRegistry subclass that strips ADC headers to force API key auth."""

    def get_toolset(self, *args, **kwargs):  # noqa: ANN002, ANN003
        toolset = super().get_toolset(*args, **kwargs)
        conn = getattr(toolset, "_connection_params", None)
        headers = getattr(conn, "headers", None) if conn else None
        if headers:
            headers.pop("Authorization", None)  # type: ignore[union-attr]
            headers.pop("x-goog-user-project", None)  # type: ignore[union-attr]
        return toolset


def get_maps_tools() -> list:
    """Return Maps MCP toolset if configured, empty list otherwise.

    Requires both GOOGLE_CLOUD_PROJECT and GOOGLE_MAPS_API_KEY.
    Safe to call without either -- returns [] with a warning log.
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    maps_key = _resolve_maps_key()

    if not project_id or not maps_key:
        logger.warning(
            "Maps MCP tools disabled: GOOGLE_CLOUD_PROJECT=%s, GOOGLE_MAPS_API_KEY=%s",
            "set" if project_id else "unset",
            "set" if maps_key else "unset",
        )
        return []

    mcp_server_name = f"projects/{project_id}/locations/global/mcpServers/google-mapstools.googleapis.com-mcp"
    api_registry = MapsApiRegistry(
        api_registry_project_id=project_id,
        header_provider=header_provider,
    )
    return [api_registry.get_toolset(mcp_server_name=mcp_server_name)]


async def set_financial_modeling_mode(mode: str, tool_context: ToolContext) -> dict:
    """Toggle between secure and insecure financial modeling modes.

    Call this when the user asks to switch financial modeling modes.
    Valid modes: "secure", "insecure".

    Args:
        mode: Either "secure" or "insecure".
        tool_context: ADK tool context (injected automatically).

    Returns:
        dict with status and the active mode.
    """
    if mode not in ("secure", "insecure"):
        return {
            "status": "error",
            "message": (f"Invalid mode '{mode}'. Must be 'secure' or 'insecure'."),
        }
    tool_context.state["financial_modeling_mode"] = mode
    return {"status": "success", "financial_modeling_mode": mode}


def _load_additional_tools(skills_dir: pathlib.Path) -> list:
    """Load skill tool functions as callables for SkillToolset additional_tools.

    These tools become available to the LLM only after load_skill activates
    the owning skill. ADK wraps them as FunctionTools automatically and
    injects tool_context at call time.
    """
    tools = []

    # GIS tools
    gis_tools_path = skills_dir / "gis-spatial-engineering" / "scripts" / "tools.py"
    if gis_tools_path.exists():
        spec = importlib.util.spec_from_file_location("gis_tools", gis_tools_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for name in ["plan_marathon_route", "report_marathon_route"]:
                func = getattr(module, name, None)
                if func:
                    tools.append(func)

    # Race-director tools
    rd_tools_path = skills_dir / "race-director" / "scripts" / "tools.py"
    if rd_tools_path.exists():
        spec = importlib.util.spec_from_file_location("rd_tools", rd_tools_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for name in ["plan_marathon_event"]:
                func = getattr(module, name, None)
                if func:
                    tools.append(func)

    return tools


def get_tools() -> list:
    """Build the planner's tool list with lazy-loaded skills.

    Uses SkillToolset with UnsafeLocalCodeExecutor for run_skill_script
    support. Skill tools are passed as additional_tools to SkillToolset
    so they become available only after load_skill activates the owning skill.
    """
    from google.adk.code_executors.unsafe_local_code_executor import UnsafeLocalCodeExecutor

    skills_dir = pathlib.Path(__file__).parent / "skills"

    skills = []
    if skills_dir.exists():
        skills = [
            load_skill_from_dir(d)
            for d in sorted(skills_dir.iterdir())
            if d.is_dir() and not d.name.startswith("_") and (d / "SKILL.md").exists()
        ]

    additional_tools = _load_additional_tools(skills_dir)

    skill_toolset = SkillToolset(
        skills=skills,
        code_executor=UnsafeLocalCodeExecutor(),
        additional_tools=additional_tools,
    )

    tools = [
        skill_toolset,
        PreloadMemoryTool(),
        FunctionTool(func=set_financial_modeling_mode),
    ]

    tools.extend(get_maps_tools())

    return tools
