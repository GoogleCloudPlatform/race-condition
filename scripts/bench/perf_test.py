#!/usr/bin/env python3
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

"""ADK Agent Performance Test — measures latency, tokens, and tool usage.

Runs multi-turn conversations against any ADK agent using InMemoryRunner
and captures OTel span telemetry for analysis.

Usage:
    uv run python scripts/bench/perf_test.py \\
        --agent agents.npc.runner_autopilot.agent \\
        --prompts "Start gun fired!" "Crowd cheering!" \\
        --runs 3 --label baseline --output results/runner_autopilot_baseline.json
"""

import argparse
import asyncio
import importlib
import json
import statistics
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# OTel MUST be set up before any ADK import — tracing hooks into module init.
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from google.adk.telemetry.setup import maybe_set_otel_providers, OTelHooks

exporter = InMemorySpanExporter()
maybe_set_otel_providers([OTelHooks(span_processors=[SimpleSpanProcessor(exporter)])])

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402


def load_agent(module_path: str):
    """Import agent module and return (root_agent, run_config or None)."""
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "root_agent"):
        raise AttributeError(f"{module_path} has no 'root_agent' attribute")
    # Check for an agent-specific RunConfig (e.g. RUNNER_RUN_CONFIG)
    run_config = None
    for attr_name in dir(mod):
        if attr_name.endswith("_RUN_CONFIG"):
            candidate = getattr(mod, attr_name)
            # Duck-type check for RunConfig
            if hasattr(candidate, "max_llm_calls"):
                run_config = candidate
                break
    return mod.root_agent, run_config


def extract_turn_spans(spans):
    """Extract model and tool call data from a list of OTel spans.

    Filters by span name prefix to avoid double-counting parent/child
    spans that share attributes.
    """
    model_calls = []
    tool_calls = []
    total_input_tokens = 0
    total_output_tokens = 0

    for span in sorted(spans, key=lambda s: s.start_time):
        attrs = dict(span.attributes) if span.attributes else {}
        duration = (span.end_time - span.start_time) / 1e9
        name = span.name or ""

        # LLM calls: span named "generate_content {model}"
        if name.startswith("generate_content"):
            model = attrs.get("gen_ai.request.model", "unknown")
            model_calls.append({"model": model, "latency_s": round(duration, 4)})
            total_input_tokens += attrs.get("gen_ai.usage.input_tokens", 0)
            total_output_tokens += attrs.get("gen_ai.usage.output_tokens", 0)

        # Tool calls: span named "execute_tool {tool_name}"
        if name.startswith("execute_tool"):
            tool_name = attrs.get("gen_ai.tool.name", name)
            tool_calls.append({"name": tool_name, "latency_s": round(duration, 4)})

    return model_calls, tool_calls, total_input_tokens, total_output_tokens


async def run_scenario(runner, prompts, run_id, run_config=None):
    """Run one full scenario (all turns) and return metrics."""
    session_id = f"perf_{run_id}_{uuid.uuid4().hex[:8]}"
    user_id = "perf_tester"

    await runner.session_service.create_session(
        user_id=user_id,
        session_id=session_id,
        app_name=runner.app_name,
    )

    exporter.clear()
    turns = []
    run_start = time.perf_counter()

    for turn_idx, prompt in enumerate(prompts, 1):
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

        # Snapshot span IDs before this turn
        pre_span_ids = {id(s) for s in exporter.get_finished_spans()}

        turn_start = time.perf_counter()
        error = None
        try:
            async for _event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content,
                run_config=run_config,
            ):
                pass  # Consume all events
        except Exception as exc:
            error = str(exc)

        turn_latency = time.perf_counter() - turn_start

        # Brief pause for span processors to flush
        await asyncio.sleep(0.1)

        # Isolate spans from this turn only
        all_spans = exporter.get_finished_spans()
        new_spans = [s for s in all_spans if id(s) not in pre_span_ids]

        model_calls, tool_calls, in_tok, out_tok = extract_turn_spans(new_spans)

        turn_data = {
            "turn": turn_idx,
            "prompt": prompt,
            "latency_s": round(turn_latency, 4),
            "model_calls": model_calls,
            "tool_calls": tool_calls,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
        }
        if error:
            turn_data["error"] = error

        turns.append(turn_data)

        status = "ERR" if error else "OK"
        print(
            f"    Turn {turn_idx} [{status}]: {turn_latency:.3f}s "
            f"({len(model_calls)} model, {len(tool_calls)} tool, "
            f"{in_tok} in/{out_tok} out tokens)"
        )
        for mc in model_calls:
            print(f"      LLM  {mc['model']}: {mc['latency_s']:.3f}s")
        for tc in tool_calls:
            print(f"      TOOL {tc['name']}: {tc['latency_s']:.3f}s")

    total_latency = time.perf_counter() - run_start
    return {
        "run_id": run_id,
        "total_latency_s": round(total_latency, 4),
        "turns": turns,
        "total_input_tokens": sum(t["input_tokens"] for t in turns),
        "total_output_tokens": sum(t["output_tokens"] for t in turns),
        "total_model_calls": sum(len(t["model_calls"]) for t in turns),
        "total_tool_calls": sum(len(t["tool_calls"]) for t in turns),
    }


def compute_summary(results):
    """Compute aggregate statistics across runs."""
    latencies = [r["total_latency_s"] for r in results]
    in_tokens = [r["total_input_tokens"] for r in results]
    out_tokens = [r["total_output_tokens"] for r in results]
    model_counts = [r["total_model_calls"] for r in results]
    tool_counts = [r["total_tool_calls"] for r in results]

    return {
        "avg_latency_s": round(statistics.mean(latencies), 4),
        "min_latency_s": round(min(latencies), 4),
        "max_latency_s": round(max(latencies), 4),
        "stddev_latency_s": (round(statistics.stdev(latencies), 4) if len(latencies) > 1 else 0),
        "avg_input_tokens": round(statistics.mean(in_tokens)),
        "avg_output_tokens": round(statistics.mean(out_tokens)),
        "avg_model_calls": round(statistics.mean(model_counts), 1),
        "avg_tool_calls": round(statistics.mean(tool_counts), 1),
    }


def print_summary(results, label):
    """Print human-readable summary to console."""
    s = compute_summary(results)

    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {label} ({len(results)} runs)")
    print(f"{'=' * 60}")
    print(
        f"  Latency  — avg: {s['avg_latency_s']:.3f}s, "
        f"min: {s['min_latency_s']:.3f}s, max: {s['max_latency_s']:.3f}s"
        + (f", stddev: {s['stddev_latency_s']:.3f}s" if s["stddev_latency_s"] else "")
    )
    print(f"  Input tokens  — avg: {s['avg_input_tokens']:.0f}")
    print(f"  Output tokens — avg: {s['avg_output_tokens']:.0f}")
    print(f"  Model calls   — avg: {s['avg_model_calls']:.1f}")
    print(f"  Tool calls    — avg: {s['avg_tool_calls']:.1f}")

    return s


async def main():
    parser = argparse.ArgumentParser(description="ADK Agent Performance Test")
    parser.add_argument(
        "--agent",
        required=True,
        help="Dotted module path (e.g. agents.npc.runner_autopilot.agent)",
    )
    parser.add_argument(
        "--prompts",
        required=True,
        nargs="+",
        help="Prompts to send as sequential turns",
    )
    parser.add_argument("--runs", type=int, default=3, help="Number of runs (default: 3)")
    parser.add_argument("--label", default="unlabeled", help="Label for this measurement")
    parser.add_argument("--output", help="JSON output file path")
    args = parser.parse_args()

    print(f"Loading agent: {args.agent}")
    agent, run_config = load_agent(args.agent)
    model = getattr(agent, "model", "N/A")
    print(f"Agent '{agent.name}' loaded (model: {model})")
    if run_config:
        print(f"  RunConfig: max_llm_calls={run_config.max_llm_calls}")

    runner = InMemoryRunner(agent=agent, app_name="perf_test")

    print(f"\nScenario: {len(args.prompts)} turns, {args.runs} runs, label='{args.label}'")
    for i, p in enumerate(args.prompts, 1):
        print(f"  Turn {i}: {p!r}")

    results = []
    for run_id in range(1, args.runs + 1):
        print(f"\n--- Run {run_id}/{args.runs} ---")
        run_data = await run_scenario(runner, args.prompts, run_id, run_config)
        results.append(run_data)
        print(f"  Total: {run_data['total_latency_s']:.3f}s")

    summary = print_summary(results, args.label)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "agent": args.agent,
            "label": args.label,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "prompts": args.prompts,
            "runs": results,
            "summary": summary,
        }
        output_path.write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
