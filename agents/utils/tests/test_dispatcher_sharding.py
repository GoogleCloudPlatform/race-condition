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

from agents.utils.dispatcher import spawn_queue_names, NUM_SPAWN_SHARDS


class TestSpawnQueueSharding:
    def test_returns_all_shard_queues(self):
        names = spawn_queue_names("runner_autopilot", num_shards=8)
        assert len(names) == 8
        for i, name in enumerate(names):
            assert name == f"simulation:spawns:runner_autopilot:{i}"

    def test_default_shard_count(self):
        names = spawn_queue_names("runner_autopilot")
        assert len(names) == NUM_SPAWN_SHARDS

    def test_different_agent_types(self):
        runner = spawn_queue_names("runner_autopilot")
        sim = spawn_queue_names("simulator")
        assert runner[0] != sim[0]
        assert "runner_autopilot" in runner[0]
        assert "simulator" in sim[0]
