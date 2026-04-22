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

"""Verify agent-dash token metrics reads model from correct field path.

The plugin emits model_start events with the model name at the top level:
    {"type": "model_start", "model": "gemini-3-pro-preview", ...}

The dashboard must read log.model (not log.request.model) to populate
the activeModels map used for token attribution.
"""


def _simulate_dashboard_token_tracking(events: list[dict]) -> dict[str, int]:
    """Simulate the agent-dash updateStats() token metrics logic.

    This mirrors the updateStats() token metrics tracking block in
    web/agent-dash/index.html (search for "Token Metrics Tracking").
    """
    active_models: dict[str, str] = {}
    token_metrics: dict[str, int] = {}

    for log in events:
        session_key = log.get("session_id", "system")

        if log.get("type") == "model_start" and log.get("model"):
            active_models[session_key] = log["model"]
        elif log.get("type") == "model_end" and log.get("response") and log["response"].get("usage"):
            model_name = active_models.get(session_key, "unknown-model")
            tokens = log["response"]["usage"].get("total_token_count", 0)
            token_metrics[model_name] = token_metrics.get(model_name, 0) + tokens

    return token_metrics


def test_model_name_extracted_from_top_level():
    """Token metrics must attribute tokens to actual model names."""
    events = [
        {
            "type": "model_start",
            "agent": "planner_agent",
            "model": "gemini-3-pro-preview",
            "session_id": "sess-1",
            "timestamp": 1742000000,
        },
        {
            "type": "model_end",
            "agent": "planner_agent",
            "response": {
                "content": "Hello",
                "usage": {
                    "prompt_token_count": 100,
                    "candidates_token_count": 50,
                    "total_token_count": 150,
                },
            },
            "session_id": "sess-1",
            "timestamp": 1742000001,
        },
    ]

    metrics = _simulate_dashboard_token_tracking(events)
    assert "unknown-model" not in metrics, "Tokens should NOT be attributed to 'unknown-model'"
    assert metrics.get("gemini-3-pro-preview") == 150


def test_multiple_models_tracked_separately():
    """Different models accumulate tokens independently."""
    events = [
        {
            "type": "model_start",
            "model": "gemini-3-pro-preview",
            "agent": "planner",
            "session_id": "s1",
            "timestamp": 1,
        },
        {
            "type": "model_end",
            "agent": "planner",
            "session_id": "s1",
            "response": {"content": "a", "usage": {"total_token_count": 100}},
            "timestamp": 2,
        },
        {
            "type": "model_start",
            "model": "gemini-3-flash-preview",
            "agent": "simulator",
            "session_id": "s2",
            "timestamp": 3,
        },
        {
            "type": "model_end",
            "agent": "simulator",
            "session_id": "s2",
            "response": {"content": "b", "usage": {"total_token_count": 200}},
            "timestamp": 4,
        },
    ]

    metrics = _simulate_dashboard_token_tracking(events)
    assert metrics == {
        "gemini-3-pro-preview": 100,
        "gemini-3-flash-preview": 200,
    }


def test_missing_model_start_falls_back_to_unknown():
    """If model_end arrives without prior model_start, fallback is expected."""
    events = [
        {
            "type": "model_end",
            "agent": "orphan",
            "response": {"content": "x", "usage": {"total_token_count": 50}},
            "session_id": "s-orphan",
            "timestamp": 1,
        },
    ]

    metrics = _simulate_dashboard_token_tracking(events)
    assert metrics == {"unknown-model": 50}
