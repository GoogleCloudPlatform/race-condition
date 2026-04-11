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

"""Self-contained tests for embedding_backfill._to_pgvector_text.

Pinned invariant: asyncpg cannot encode a Python list as TEXT, so the
embedding vector must be passed to UPDATE ... = $1::vector as the
pgvector text format ('[v1,v2,...]').

Runs with no test framework or external deps:
  python modules/cloud-sql-postgres/embedding_backfill_test.py
"""

from __future__ import annotations

import sys
from pathlib import Path


# Import the helper directly from the source file. embedding_backfill.py
# defers asyncpg and google-genai imports into main() so this module is
# import-safe in environments without those installed (e.g., test runs).
sys.path.insert(0, str(Path(__file__).parent))
from embedding_backfill import _to_pgvector_text  # noqa: E402


def test_short_vector_is_bracketed_csv() -> None:
    got = _to_pgvector_text([0.1, 0.2, 0.3])
    assert got.startswith("[") and got.endswith("]"), got
    assert "," in got, got
    assert " " not in got, "pgvector accepts spaces but we omit them for compactness"


def test_single_element() -> None:
    assert _to_pgvector_text([1.0]) == "[1.0]"


def test_three_elements_exact_format() -> None:
    assert _to_pgvector_text([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"


def test_negative_and_scientific() -> None:
    # repr(float(...)) keeps full precision; pgvector accepts scientific notation.
    got = _to_pgvector_text([-1.5e-10, 2.0])
    assert got.startswith("[-1.5e-10,") or got.startswith("[-1.5e-010,"), got
    assert got.endswith(",2.0]"), got


def test_full_dimension_3072() -> None:
    # Real-world size: gemini-embedding-001 returns 3072-dim vectors.
    vec = [0.001 * i for i in range(3072)]
    got = _to_pgvector_text(vec)
    assert got.startswith("[0.0,0.001,0.002,"), got[:60]
    # 3072 elements + 3071 commas + 2 brackets = at least 6145 chars.
    assert len(got) > 6000, len(got)


if __name__ == "__main__":
    tests = [name for name in dir() if name.startswith("test_")]
    fails: list[str] = []
    for name in tests:
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            print(f"FAIL  {name}: {e}")
            fails.append(name)
    if fails:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")
