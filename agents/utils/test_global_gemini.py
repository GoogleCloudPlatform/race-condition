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

"""Tests for GlobalGemini model-turn stall recovery.

Production incident: a planner_with_memory turn intermittently stalls after
``model_start`` -- the Gemini generation request goes in-flight and never
returns, hanging the whole multi-agent flow. The genai SDK only retries
``APIError`` responses with retriable status codes, NOT client-side stalls,
so a wedged stream hangs forever.

GlobalGemini.generate_content_async wraps the parent generator with a
per-chunk ``asyncio.wait_for``. A stall *before the first token* is safe to
restart, so it retries from scratch (bounded). A stall *mid-stream* cannot be
safely restarted (would duplicate output), so it re-raises.
"""

import asyncio
import os
from unittest import mock

import pytest
from google.adk.models.google_llm import Gemini


def _make_model(**overrides):
    """Construct a GlobalGemini with tiny timeouts for fast deterministic tests."""
    from agents.utils.global_gemini import GlobalGemini

    params = {
        "model": "gemini-3.5-flash",
        "first_token_timeout_s": 0.1,
        "stream_timeout_s": 0.1,
        "stall_retries": 2,
    }
    params.update(overrides)
    return GlobalGemini(**params)


async def _drain(agen):
    return [chunk async for chunk in agen]


@pytest.mark.asyncio
async def test_passthrough_yields_all_chunks_when_healthy():
    """A healthy parent stream is forwarded unchanged."""
    model = _make_model()

    async def fake_parent(self, llm_request, stream=False):
        yield "chunk-1"
        yield "chunk-2"

    with mock.patch.object(Gemini, "generate_content_async", new=fake_parent):
        out = await _drain(model.generate_content_async(object(), stream=False))

    assert out == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_retries_after_first_token_stall():
    """Stall before the first token -> abort and restart from scratch."""
    model = _make_model()
    calls = {"n": 0}

    async def fake_parent(self, llm_request, stream=False):
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(5)  # stall past first_token_timeout_s
            yield "never"
        else:
            yield "recovered"

    with mock.patch.object(Gemini, "generate_content_async", new=fake_parent):
        out = await _drain(model.generate_content_async(object(), stream=False))

    assert out == ["recovered"]
    assert calls["n"] == 2  # one stalled attempt + one successful retry


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries():
    """Every attempt stalls -> raise once retries are exhausted."""
    model = _make_model(stall_retries=2)
    calls = {"n": 0}

    async def fake_parent(self, llm_request, stream=False):
        calls["n"] += 1
        await asyncio.sleep(5)
        yield "never"

    with mock.patch.object(Gemini, "generate_content_async", new=fake_parent):
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            await _drain(model.generate_content_async(object(), stream=False))

    assert calls["n"] == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_midstream_stall_reraises_without_restart():
    """Stall after a token was yielded -> cannot restart, must re-raise."""
    model = _make_model()
    calls = {"n": 0}

    async def fake_parent(self, llm_request, stream=False):
        calls["n"] += 1
        yield "partial"
        await asyncio.sleep(5)  # stall past stream_timeout_s, mid-stream
        yield "never"

    collected = []
    with mock.patch.object(Gemini, "generate_content_async", new=fake_parent):
        with pytest.raises((asyncio.TimeoutError, TimeoutError)):
            async for chunk in model.generate_content_async(object(), stream=False):
                collected.append(chunk)

    assert collected == ["partial"]
    assert calls["n"] == 1  # no restart after partial output


def test_timeouts_and_retries_read_from_env():
    from agents.utils.global_gemini import GlobalGemini

    with mock.patch.dict(
        os.environ,
        {
            "GEMINI_MODEL_FIRST_TOKEN_TIMEOUT_S": "42.0",
            "GEMINI_MODEL_STREAM_TIMEOUT_S": "17.0",
            "GEMINI_MODEL_STALL_RETRIES": "5",
        },
    ):
        model = GlobalGemini(model="gemini-3.5-flash")

    assert model.first_token_timeout_s == 42.0
    assert model.stream_timeout_s == 17.0
    assert model.stall_retries == 5


def test_default_timeouts_are_generous():
    """Defaults must not abort healthy turns (eval ~20s, planning ~10s)."""
    from agents.utils.global_gemini import GlobalGemini

    model = GlobalGemini(model="gemini-3.5-flash")
    assert model.first_token_timeout_s >= 120.0
    assert model.stall_retries >= 1
