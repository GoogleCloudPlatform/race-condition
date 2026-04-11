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

"""Tests for perf_diagnostic utilities."""

import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_latency_bucket_empty():
    from scripts.bench.perf_diagnostic import LatencyBucket

    b = LatencyBucket("test")
    assert b.count == 0
    assert b.percentile(50) == 0.0
    assert b.percentile(99) == 0.0


def test_latency_bucket_samples():
    from scripts.bench.perf_diagnostic import LatencyBucket

    b = LatencyBucket("test")
    for i in range(1, 101):
        b.add(float(i))
    assert b.count == 100
    assert b.percentile(50) == 50.0
    assert b.percentile(99) == 99.0
    assert b.percentile(100) == 100.0


def test_latency_bucket_report_contains_name():
    from scripts.bench.perf_diagnostic import LatencyBucket

    b = LatencyBucket("my-metric")
    b.add(1.0)
    b.add(2.0)
    report = b.report()
    assert "my-metric" in report
    assert "count=2" in report


def test_auth_headers_with_token():
    from scripts.bench.perf_diagnostic import auth_headers

    h = auth_headers("tok123")
    assert h == {"Authorization": "Bearer tok123"}


def test_auth_headers_without_token():
    from scripts.bench.perf_diagnostic import auth_headers

    h = auth_headers(None)
    assert h == {}


def test_ws_extra_headers_with_token():
    from scripts.bench.perf_diagnostic import ws_extra_headers

    h = ws_extra_headers("tok123")
    assert h == {"Authorization": "Bearer tok123"}


def test_ws_extra_headers_without_token():
    from scripts.bench.perf_diagnostic import ws_extra_headers

    h = ws_extra_headers(None)
    assert h is None


def test_phase_result_fields():
    from scripts.bench.perf_diagnostic import PhaseResult

    r = PhaseResult(name="test", success=True, duration=1.5, details={"k": "v"})
    assert r.name == "test"
    assert r.success is True
    assert r.duration == 1.5
    assert r.details == {"k": "v"}
    assert r.error == ""


# ---------------------------------------------------------------------------
# Task 2: Phase 1 -- Health Check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phase_health_success():
    """phase_health returns success when gateway responds 200."""
    from scripts.bench.perf_diagnostic import phase_health

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await phase_health(None)

    assert result.success is True
    assert result.name == "health"
    assert "http_latency_p50" in result.details


@pytest.mark.asyncio
async def test_phase_health_failure():
    """phase_health returns failure when gateway is unreachable."""
    from scripts.bench.perf_diagnostic import phase_health

    mock_session = AsyncMock()
    mock_session.get = MagicMock(side_effect=ConnectionError("refused"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await phase_health(None)

    assert result.success is False
    assert "unreachable" in result.error.lower() or "refused" in result.error.lower()


# ---------------------------------------------------------------------------
# Task 3: Phase 2 -- WebSocket Stability (LB timeout detection logic)
# ---------------------------------------------------------------------------


def test_lb_timeout_detection_logic():
    """Verify LB timeout is detected when connection drops at ~30s."""
    # The detection condition: 25 < connection_held < 35 and drop_reason != "completed"
    # This tests the pure logic, not the async WS connection.

    def detect_lb_timeout(connection_held: float, drop_reason: str) -> bool:
        return 25 < connection_held < 35 and drop_reason != "completed"

    # Drop at 28s -- should detect LB timeout
    assert detect_lb_timeout(28.0, "server closed") is True
    # Drop at 30s -- should detect LB timeout
    assert detect_lb_timeout(30.0, "connection reset") is True
    # Drop at 34s -- should detect LB timeout
    assert detect_lb_timeout(34.0, "EOF") is True
    # Completed normally at 30s -- should NOT detect
    assert detect_lb_timeout(30.0, "completed") is False
    # Drop at 10s -- too early, not LB timeout
    assert detect_lb_timeout(10.0, "server closed") is False
    # Drop at 50s -- too late, not LB timeout
    assert detect_lb_timeout(50.0, "server closed") is False
    # Full hold at 90s completed -- should NOT detect
    assert detect_lb_timeout(90.0, "completed") is False


# ---------------------------------------------------------------------------
# Task 4: Phase 3 -- Protobuf helpers
# ---------------------------------------------------------------------------


def test_build_broadcast_message():
    """build_broadcast creates valid protobuf Wrapper."""
    from scripts.bench.perf_diagnostic import build_broadcast_message

    from gen_proto.gateway import gateway_pb2

    data = build_broadcast_message("Plan a marathon", ["sess-1"])
    assert isinstance(data, bytes)
    w = gateway_pb2.Wrapper()
    w.ParseFromString(data)
    assert w.type == "broadcast"
    assert w.event == "broadcast"
    assert "sess-1" in w.destination


def test_build_broadcast_message_multiple_targets():
    """build_broadcast includes all target session IDs in destination."""
    from scripts.bench.perf_diagnostic import build_broadcast_message

    from gen_proto.gateway import gateway_pb2

    data = build_broadcast_message("Go", ["s1", "s2", "s3"])
    w = gateway_pb2.Wrapper()
    w.ParseFromString(data)
    assert list(w.destination) == ["s1", "s2", "s3"]

    # Verify inner BroadcastRequest
    br = gateway_pb2.BroadcastRequest()
    br.ParseFromString(w.payload)
    assert list(br.target_session_ids) == ["s1", "s2", "s3"]
    inner = json.loads(br.payload)
    assert inner["text"] == "Go"


def test_parse_tool_event_tool_end():
    """parse_tool_event extracts tool name from tool_end events."""
    from scripts.bench.perf_diagnostic import parse_tool_event

    from gen_proto.gateway import gateway_pb2

    w = gateway_pb2.Wrapper(
        type="json",
        event="tool_end",
        session_id="s1",
        payload=json.dumps({"tool_name": "advance_tick", "result": {"tick": 5}}).encode(),
    )
    result = parse_tool_event(w)
    assert result is not None
    tool_name, data, sid = result
    assert tool_name == "advance_tick"
    assert sid == "s1"


def test_parse_tool_event_non_tool():
    """parse_tool_event returns None for non-tool events."""
    from scripts.bench.perf_diagnostic import parse_tool_event

    from gen_proto.gateway import gateway_pb2

    w = gateway_pb2.Wrapper(type="json", event="model_start")
    assert parse_tool_event(w) is None


def test_parse_tool_event_no_tool_name():
    """parse_tool_event returns None when payload has no tool_name."""
    from scripts.bench.perf_diagnostic import parse_tool_event

    from gen_proto.gateway import gateway_pb2

    w = gateway_pb2.Wrapper(
        type="json",
        event="tool_end",
        payload=json.dumps({"some_other": "data"}).encode(),
    )
    assert parse_tool_event(w) is None


# ---------------------------------------------------------------------------
# Task 5: Diagnostic Report
# ---------------------------------------------------------------------------


def test_print_final_report_no_crash(capsys):
    """print_final_report runs without error for various inputs."""
    from scripts.bench.perf_diagnostic import PhaseResult, print_final_report

    phases = [
        PhaseResult("health", True, 0.5, {"http_latency_p50": 0.1}),
        PhaseResult(
            "ws_stability",
            True,
            90.0,
            {
                "lb_timeout_detected": False,
                "connection_held": 90.0,
            },
        ),
        PhaseResult(
            "simulation",
            True,
            120.0,
            {
                "total_events": 500,
                "tick_count": 10,
                "tick_latency_p50": 5.0,
                "tick_latency_p99": 12.0,
                "connection_drops": 0,
            },
        ),
    ]
    print_final_report(phases)
    captured = capsys.readouterr()
    assert "PERFORMANCE DIAGNOSTIC REPORT" in captured.out
    assert "Verdict" in captured.out


def test_print_final_report_with_issues(capsys):
    """print_final_report identifies LB timeout and connection drops."""
    from scripts.bench.perf_diagnostic import PhaseResult, print_final_report

    phases = [
        PhaseResult("health", True, 0.5, {}),
        PhaseResult(
            "ws_stability",
            False,
            30.0,
            {
                "lb_timeout_detected": True,
                "connection_held": 29.5,
            },
        ),
        PhaseResult(
            "simulation",
            False,
            60.0,
            {
                "connection_drops": 3,
                "tick_latency_p99": 45.0,
                "tick_latency_p50": 2.0,
            },
        ),
    ]
    print_final_report(phases)
    captured = capsys.readouterr()
    assert "GCLB" in captured.out or "timeout" in captured.out.lower()
    assert "drop" in captured.out.lower()


# ---------------------------------------------------------------------------
# Task 6: CLI Entry Point
# ---------------------------------------------------------------------------


def test_cli_help():
    """CLI --help exits cleanly."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "scripts.bench.perf_diagnostic", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "diagnostic" in result.stdout.lower() or "performance" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Task 7: Import Smoke Test
# ---------------------------------------------------------------------------


def test_import_smoke():
    """Module imports without error and exports expected symbols."""
    import scripts.bench.perf_diagnostic as mod

    assert hasattr(mod, "main")
    assert hasattr(mod, "run_diagnostic")
    assert hasattr(mod, "phase_health")
    assert hasattr(mod, "phase_ws_stability")
    assert hasattr(mod, "phase_simulation")
    assert hasattr(mod, "print_final_report")
    assert hasattr(mod, "build_broadcast_message")
    assert hasattr(mod, "parse_tool_event")
