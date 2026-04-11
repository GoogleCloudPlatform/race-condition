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

"""AlloyDB assets for planner_with_memory.

This package contains:
- ``schema.sql``: Full DDL for all three tables (regulations, planned_routes,
  simulation_records).
- ``LEGISLATION.txt``: Raw regulation text for RAG seeding.
- ``seed_regulations.sql``: Idempotent INSERT of regulation chunks.
- ``seed_routes.py``: Python script to seed planned_routes from JSON seeds.
"""
