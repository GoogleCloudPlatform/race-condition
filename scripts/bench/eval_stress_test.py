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

"""Eval Performance Stress Test — measures latency and consistency of evaluate_plan.

Runs planner_with_eval end-to-end N times with the same prompt via InMemoryRunner.
Captures per-tool latency from OTel spans and evaluate_plan results from ADK events.
Produces a consolidated report with latency breakdown, score consistency, and
suggestion frequency analysis.

Usage:
    uv run python scripts/bench/eval_stress_test.py --runs 10
    uv run python scripts/bench/eval_stress_test.py --runs 5 --prompt "Plan a scenic marathon in Chicago"
    uv run python scripts/bench/eval_stress_test.py --runs 10 --output results/eval_stress.json --label baseline
"""

import argparse
import asyncio
import collections
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

AGENT_MODULE = "agents.planner_with_eval.agent"
DEFAULT_PROMPT = "Plan a marathon in Las Vegas for 10 runners"


def load_agent(module_path: str):
    """Import agent module and return (root_agent, run_config or None)."""
    mod = importlib.import_module(module_path)
    if not hasattr(mod, "root_agent"):
        raise AttributeError(f"{module_path} has no 'root_agent' attribute")
    run_config = None
    for attr_name in dir(mod):
        if attr_name.endswith("_RUN_CONFIG"):
            candidate = getattr(mod, attr_name)
            if hasattr(candidate, "max_llm_calls"):
                run_config = candidate
                break
    return mod.root_agent, run_config


def extract_tool_latencies(spans) -> dict[str, float]:
    """Extract per-tool-name latencies from OTel spans."""
    tool_latencies: dict[str, float] = {}
    for span in sorted(spans, key=lambda s: s.start_time):
        attrs = dict(span.attributes) if span.attributes else {}
        duration = (span.end_time - span.start_time) / 1e9
        name = span.name or ""

        if name.startswith("execute_tool"):
            tool_name = attrs.get("gen_ai.tool.name", name)
            tool_latencies[tool_name] = round(duration, 4)

    return tool_latencies


def extract_model_call_count(spans) -> int:
    """Count the number of LLM model calls from OTel spans."""
    count = 0
    for span in spans:
        name = span.name or ""
        if name.startswith("generate_content"):
            count += 1
    return count


def extract_eval_results(events) -> dict | None:
    """Extract evaluate_plan tool response from ADK events.

    Searches for function_response parts where the function name is
    evaluate_plan and extracts the result dict.
    """
    for event in events:
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if not part.function_response:
                continue
            if part.function_response.name == "evaluate_plan":
                response = part.function_response.response
                if isinstance(response, dict):
                    return response
    return None


async def run_single(runner, prompt: str, run_id: int, run_config=None) -> dict:
    """Run one full planner_with_eval scenario and return metrics."""
    session_id = f"eval_stress_{run_id}_{uuid.uuid4().hex[:8]}"
    user_id = "eval_stress_tester"

    await runner.session_service.create_session(
        user_id=user_id,
        session_id=session_id,
        app_name=runner.app_name,
    )

    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])

    # Snapshot span IDs before this run
    pre_span_ids = {id(s) for s in exporter.get_finished_spans()}

    run_start = time.perf_counter()
    events = []
    error = None
    try:
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=content,
            run_config=run_config,
        ):
            events.append(event)
    except Exception as exc:
        error = str(exc)

    total_latency = time.perf_counter() - run_start

    # Brief pause for span processors to flush
    await asyncio.sleep(0.1)

    # Isolate spans from this run only
    all_spans = exporter.get_finished_spans()
    new_spans = [s for s in all_spans if id(s) not in pre_span_ids]

    tool_latencies = extract_tool_latencies(new_spans)
    model_call_count = extract_model_call_count(new_spans)
    eval_result = extract_eval_results(events)

    run_data: dict = {
        "run_id": run_id,
        "total_latency_s": round(total_latency, 4),
        "tool_latencies": tool_latencies,
        "model_call_count": model_call_count,
        "eval_result": None,
    }

    if error:
        run_data["error"] = error

    if eval_result:
        run_data["eval_result"] = {
            "scores": eval_result.get("scores", {}),
            "overall_score": eval_result.get("overall_score"),
            "passed": eval_result.get("passed"),
            "eval_method": eval_result.get("eval_method"),
            "improvement_suggestions": eval_result.get("improvement_suggestions", []),
            "summary": eval_result.get("summary", ""),
        }

    # Print live progress
    status = "ERR" if error else "OK"
    eval_time = tool_latencies.get("evaluate_plan", 0)
    overall = eval_result.get("overall_score", "N/A") if eval_result else "N/A"
    passed = eval_result.get("passed", "N/A") if eval_result else "N/A"

    print(
        f"  [{status}] {total_latency:.1f}s total, evaluate_plan={eval_time:.1f}s, "
        f"model_calls={model_call_count}, overall_score={overall}, passed={passed}"
    )
    for tool_name, latency in sorted(tool_latencies.items()):
        print(f"    {tool_name}: {latency:.3f}s")

    return run_data


def _stats(values: list[float]) -> dict:
    """Compute avg/min/max/stddev for a list of floats."""
    if not values:
        return {"avg": 0, "min": 0, "max": 0, "stddev": 0}
    return {
        "avg": round(statistics.mean(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0,
    }


def compute_report(results: list[dict]) -> dict:
    """Compute consolidated report from all run results."""

    # --- Per-tool latency aggregation ---
    all_tool_names: set[str] = set()
    for r in results:
        all_tool_names.update(r["tool_latencies"].keys())

    tool_latency_stats = {}
    for tool_name in sorted(all_tool_names):
        values = [r["tool_latencies"].get(tool_name, 0) for r in results if tool_name in r["tool_latencies"]]
        tool_latency_stats[tool_name] = _stats(values)

    # Total run latency
    total_latency_stats = _stats([r["total_latency_s"] for r in results])

    # Model call count
    model_call_stats = _stats([float(r.get("model_call_count", 0)) for r in results])

    # Model call time (total - tools)
    model_time_values = []
    for r in results:
        tool_sum = sum(r["tool_latencies"].values())
        model_time_values.append(r["total_latency_s"] - tool_sum)
    model_time_stats = _stats(model_time_values)

    # --- Eval score aggregation ---
    eval_results = [r["eval_result"] for r in results if r.get("eval_result")]

    score_stats: dict = {}
    if eval_results:
        all_criteria = set()
        for er in eval_results:
            all_criteria.update(er.get("scores", {}).keys())

        for criterion in sorted(all_criteria):
            values = [er["scores"][criterion] for er in eval_results if criterion in er.get("scores", {})]
            score_stats[criterion] = _stats(values)

        overall_values = [er["overall_score"] for er in eval_results if er.get("overall_score") is not None]
        score_stats["overall_score"] = _stats(overall_values)

    # --- Pass rate ---
    pass_count = sum(1 for er in eval_results if er.get("passed"))
    eval_method_counts: dict[str, int] = collections.Counter(er.get("eval_method", "unknown") for er in eval_results)

    # --- Suggestion frequency ---
    suggestion_counts: dict[str, int] = collections.Counter()
    for er in eval_results:
        for suggestion in er.get("improvement_suggestions", []):
            # Normalize: take first 80 chars for grouping
            key = suggestion[:80].strip()
            suggestion_counts[key] += 1

    return {
        "num_runs": len(results),
        "num_successful": len(eval_results),
        "total_latency": total_latency_stats,
        "model_call_count": model_call_stats,
        "model_call_time": model_time_stats,
        "tool_latencies": tool_latency_stats,
        "scores": score_stats,
        "pass_rate": f"{pass_count}/{len(eval_results)}" if eval_results else "0/0",
        "eval_methods": dict(eval_method_counts),
        "suggestion_frequency": dict(suggestion_counts.most_common(20)),
    }


def print_report(report: dict, label: str):
    """Print human-readable consolidated report."""
    n = report["num_runs"]
    ok = report["num_successful"]

    print(f"\n{'=' * 70}")
    print(f"EVAL STRESS TEST: {label} ({ok}/{n} successful runs)")
    print(f"{'=' * 70}")

    # Latency table
    print("\nLATENCY (seconds)")
    print(f"  {'':30s} {'avg':>8s} {'min':>8s} {'max':>8s} {'stddev':>8s}")
    print(f"  {'-' * 62}")

    tl = report["total_latency"]
    print(f"  {'total_run':30s} {tl['avg']:8.1f} {tl['min']:8.1f} {tl['max']:8.1f} {tl['stddev']:8.1f}")

    mc = report["model_call_count"]
    print(f"  {'model_calls (count)':30s} {mc['avg']:8.1f} {mc['min']:8.1f} {mc['max']:8.1f} {mc['stddev']:8.1f}")

    mt = report["model_call_time"]
    print(f"  {'model_call_time':30s} {mt['avg']:8.1f} {mt['min']:8.1f} {mt['max']:8.1f} {mt['stddev']:8.1f}")

    for tool_name, stats in report["tool_latencies"].items():
        print(f"  {tool_name:30s} {stats['avg']:8.1f} {stats['min']:8.1f} {stats['max']:8.1f} {stats['stddev']:8.1f}")

    # Score table
    if report["scores"]:
        print("\nEVAL SCORES")
        print(f"  {'':30s} {'avg':>8s} {'min':>8s} {'max':>8s} {'stddev':>8s}")
        print(f"  {'-' * 62}")
        for criterion, stats in report["scores"].items():
            print(
                f"  {criterion:30s} {stats['avg']:8.2f} {stats['min']:8.2f} {stats['max']:8.2f} {stats['stddev']:8.2f}"
            )

    # Consistency
    print("\nEVAL CONSISTENCY")
    print(f"  passed: {report['pass_rate']}")
    for method, count in report["eval_methods"].items():
        print(f"  eval_method={method}: {count}/{ok}")

    # Suggestions
    if report["suggestion_frequency"]:
        print("\nSUGGESTION FREQUENCY (top 10)")
        for suggestion, count in list(report["suggestion_frequency"].items())[:10]:
            print(f"  [{count}/{ok}] {suggestion}...")


async def main():
    parser = argparse.ArgumentParser(
        description="Eval Performance Stress Test — latency and consistency of evaluate_plan"
    )
    parser.add_argument("--runs", type=int, default=10, help="Number of runs (default: 10)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to send")
    parser.add_argument("--label", default="eval-stress", help="Label for this measurement")
    parser.add_argument("--output", help="JSON output file path")
    args = parser.parse_args()

    print(f"Loading agent: {AGENT_MODULE}")
    agent, run_config = load_agent(AGENT_MODULE)
    model = getattr(agent, "model", "N/A")
    print(f"Agent '{agent.name}' loaded (model: {model})")
    if run_config:
        print(f"  RunConfig: max_llm_calls={run_config.max_llm_calls}")

    runner = InMemoryRunner(agent=agent, app_name="eval_stress_test")

    print(f"\nConfig: {args.runs} runs, label='{args.label}'")
    print(f"Prompt: {args.prompt!r}")
    print(f"\n{'=' * 70}")

    results = []
    for run_id in range(1, args.runs + 1):
        print(f"\n--- Run {run_id}/{args.runs} ---")
        run_data = await run_single(runner, args.prompt, run_id, run_config)
        results.append(run_data)

    report = compute_report(results)
    print_report(report, args.label)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_data = {
            "agent": AGENT_MODULE,
            "label": args.label,
            "prompt": args.prompt,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "runs": results,
            "report": report,
        }
        output_path.write_text(json.dumps(output_data, indent=2))
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
