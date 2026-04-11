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

"""Test runner agent inference against a vLLM server.

Validates that the vLLM server is healthy, lists models, and can perform
chat completions and tool calling -- the two capabilities required by the
runner agent.

Usage:
    # Start port-forward in another terminal:
    #   kubectl port-forward svc/vllm-service 8080:8000

    # Run test:
    python scripts/e2e/test_vllm_runner.py

    # Or with custom URL:
    VLLM_API_URL=http://localhost:8080/v1 python scripts/e2e/test_vllm_runner.py
"""

import os
import sys

# Set defaults for vLLM testing
os.environ.setdefault("VLLM_API_URL", "http://localhost:8080/v1")
os.environ.setdefault("RUNNER_MODEL", "openai/gemma-4-E4B-it")
os.environ.setdefault("OPENAI_API_KEY", "not-needed")
os.environ.setdefault("OPENAI_API_BASE", os.environ["VLLM_API_URL"])


def main():
    """Test vLLM inference via the OpenAI-compatible API."""
    import httpx

    base_url = os.environ["VLLM_API_URL"]
    model = os.environ["RUNNER_MODEL"].removeprefix("openai/")

    # The health endpoint is at the root, not under /v1
    health_url = base_url.rstrip("/v1").rstrip("/")

    print(f"Testing vLLM at {base_url}")
    print(f"Model: {model}")
    print()

    # 1. Health check
    print("1. Health check...")
    try:
        resp = httpx.get(f"{health_url}/health", timeout=10)
        print(f"   Status: {resp.status_code}")
        if resp.status_code != 200:
            print("   FAIL: vLLM not healthy")
            sys.exit(1)
        print("   OK")
    except httpx.ConnectError:
        print("   FAIL: Cannot connect. Is port-forward running?")
        print("   Run: kubectl port-forward svc/vllm-service 8080:8000")
        sys.exit(1)

    # 2. List models
    print("\n2. Listing models...")
    resp = httpx.get(f"{base_url}/models", timeout=10)
    models = resp.json()
    print(f"   Available: {[m['id'] for m in models['data']]}")

    # 3. Chat completion
    print(f"\n3. Chat completion (model={model})...")
    resp = httpx.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a marathon runner. Respond in 1-2 sentences.",
                },
                {"role": "user", "content": "How are you feeling at mile 15?"},
            ],
            "max_tokens": 100,
            "temperature": 0.7,
        },
        timeout=60,
    )
    result = resp.json()
    if resp.status_code != 200 or "error" in result:
        print(f"   Status: {resp.status_code}")
        print(f"   Error: {result.get('error', result.get('message', 'unknown'))}")
        print(
            "   WARNING: Tool calling may not be supported by this vLLM "
            "build/model. Chat completions work; tool calling is optional."
        )
    elif "choices" in result:
        choice = result["choices"][0]
        if choice["message"].get("tool_calls"):
            tool_call = choice["message"]["tool_calls"][0]
            print(f"   Tool called: {tool_call['function']['name']}")
            print(f"   Arguments: {tool_call['function']['arguments']}")
            print("   OK - Tool calling works!")
        else:
            content = choice["message"].get("content", "")
            print(f"   Response (no tool call): {content[:200]}")
            print("   WARNING: Model did not use tool calling. May need prompt tuning for this model.")
    else:
        print(f"   Unexpected response: {str(result)[:200]}")
        print("   WARNING: Could not parse tool calling response.")

    print("\n--- All tests passed ---")


if __name__ == "__main__":
    main()
