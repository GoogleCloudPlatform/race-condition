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

import asyncio
import time
import os
import argparse
import logging
from dotenv import load_dotenv
from agents.utils.communication import SimulationA2AClient

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("A2AStressTest")

load_dotenv()


async def benchmark_a2a(count: int, concurrency: int = 10):
    """
    Benchmark the A2A communication mechanism.

    Args:
        count: Total number of A2A calls to perform.
        concurrency: Number of concurrent calls to handle.
    """
    client = SimulationA2AClient()

    print(f"🚀 Starting A2A Stress Test: {count} total calls, max {concurrency} concurrent.")
    print(f"📡 Registry: {os.getenv('GATEWAY_URL', 'http://localhost:8101')}")

    semaphore = asyncio.Semaphore(concurrency)

    async def bounded_call(i: int):
        async with semaphore:
            start = time.perf_counter()
            try:
                # We target the 'runner_autopilot' agent which is standard in this simulation
                response = await client.call_agent("runner_autopilot", f"Stress test ping {i}")
                latency = time.perf_counter() - start
                if response:
                    return {"status": "success", "response": response}, latency
                else:
                    return {"status": "error", "error": "Empty response from agent"}, latency
            except Exception as e:
                latency = time.perf_counter() - start
                return {"status": "error", "error": str(e)}, latency

    tasks = [bounded_call(i) for i in range(count)]

    overall_start = time.perf_counter()
    results_with_latency = await asyncio.gather(*tasks)
    overall_end = time.perf_counter()

    overall_duration = overall_end - overall_start

    success_latencies = [lat for r, lat in results_with_latency if r.get("status") == "success"]
    errors = [r for r, lat in results_with_latency if r.get("status") != "success"]

    print("\n" + "=" * 40)
    print("      A2A STRESS TEST RESULTS")
    print("=" * 40)
    print(f"Total Calls:      {count}")
    print(f"Total Duration:   {overall_duration:.2f}s")
    print(f"Throughput:       {count / overall_duration:.2f} calls/sec")
    print(f"Success Count:    {len(success_latencies)}")
    print(f"Error Count:      {len(errors)}")

    if success_latencies:
        print("-" * 20)
        print(f"Min Latency:      {min(success_latencies) * 1000:.2f}ms")
        print(f"Max Latency:      {max(success_latencies) * 1000:.2f}ms")
        print(f"Avg Latency:      {sum(success_latencies) / len(success_latencies) * 1000:.2f}ms")

        # Calculate P95/P99 if we have enough data
        success_latencies.sort()
        p95 = success_latencies[min(int(len(success_latencies) * 0.95), len(success_latencies) - 1)]
        p99 = success_latencies[min(int(len(success_latencies) * 0.99), len(success_latencies) - 1)]
        print(f"P95 Latency:      {p95 * 1000:.2f}ms")
        print(f"P99 Latency:      {p99 * 1000:.2f}ms")
    print("=" * 40)

    if errors:
        print("\n❌ Sample Errors:")
        for e in errors[:5]:
            print(f"- {e.get('error', 'Unknown Error')[:100]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A2A Inter-Agent Stress Test")
    parser.add_argument("--count", type=int, default=50, help="Total number of A2A calls")
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent calls")
    args = parser.parse_args()

    asyncio.run(benchmark_a2a(args.count, args.concurrency))
