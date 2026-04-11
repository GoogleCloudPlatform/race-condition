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

"""Memory Manager for Planner With Memory Agent.

Manages Memory Bank integration with custom topics.
Enables cross-session learning.
"""

import os
from typing import TYPE_CHECKING

from google.adk.memory import VertexAiMemoryBankService

if TYPE_CHECKING:
    from google.adk.agents.callback_context import CallbackContext


# ============================================================================
# MEMORY SERVICE
# ============================================================================


def create_memory_service(
    project: str | None = None,
    location: str | None = None,
    agent_engine_id: str | None = None,
) -> VertexAiMemoryBankService | None:
    """Create a VertexAiMemoryBankService."""
    project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = location or (
        os.environ.get("AGENT_ENGINE_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    )
    agent_engine_id = agent_engine_id or os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")

    if not project or not agent_engine_id:
        return None

    return VertexAiMemoryBankService(
        project=project,
        location=location,
        agent_engine_id=agent_engine_id,
    )


# [START auto_save_memories]
async def auto_save_memories(callback_context: "CallbackContext") -> None:
    """Automatically save session to Memory Bank after agent responds."""
    memory_service = getattr(callback_context._invocation_context, "memory_service", None)

    if not memory_service:
        agent_engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID", "")
        if not agent_engine_id:
            return

        try:
            memory_service = create_memory_service()
        except Exception as e:
            print(f"Warning: Failed to create memory service: {e}")
            return

    if not memory_service:
        return

    try:
        await memory_service.add_session_to_memory(callback_context._invocation_context.session)
    except Exception as e:
        print(f"Warning: Failed to save memories: {e}")


# [END auto_save_memories]
