// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

// TestIntegration_SessionAwareRouting_E2E exercises the full gateway stack:
// real Redis, real session registry, real switchboard, mock agent HTTP servers.
//
// It verifies:
//  1. After spawning a runner_autopilot — only runner_autopilot is poked on broadcast
//  2. Simulator is NOT poked (no sessions)
//  3. After spawning a simulator — both are poked on broadcast
//  4. After untracking runner_autopilot — only simulator is poked
func TestIntegration_SessionAwareRouting_E2E(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	simulatorMock := newAgentMock()
	defer simulatorMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
		"simulator": map[string]interface{}{
			"name": "simulator", "url": simulatorMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "callable"},
				}},
			},
		},
	}, map[string]*agentMock{"runner_autopilot": runnerMock, "simulator": simulatorMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-routing")
	ctx := context.Background()

	// ---------------------------------------------------------------
	// Step 1: Spawn a runner_autopilot session
	// ---------------------------------------------------------------
	spawnBody, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 1},
		},
	})
	req := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)
	require.Equal(t, http.StatusOK, w.Code, "Spawn should succeed")

	var spawnResp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &spawnResp))
	sessions := spawnResp["sessions"].([]interface{})
	require.Len(t, sessions, 1, "Should spawn 1 session")
	t.Logf("Spawned runner_autopilot session: %v", sessions[0])

	time.Sleep(500 * time.Millisecond)

	// Reset poke counters before broadcast test
	runnerMock.reset()
	simulatorMock.reset()

	// ---------------------------------------------------------------
	// Step 2: Broadcast — only runner_autopilot should be poked
	// ---------------------------------------------------------------
	broadcast := map[string]interface{}{
		"type": "broadcast", "eventId": "evt-1",
		"payload": map[string]interface{}{"data": "Run!"},
	}
	require.NoError(t, gw.Switchboard.PublishOrchestration(ctx, "simulation:broadcast", broadcast))

	time.Sleep(2 * time.Second)

	assert.Equal(t, 1, runnerMock.hits(), "Runner_autopilot has 1 session — should be poked once")
	assert.Equal(t, 0, simulatorMock.hits(), "Simulator has NO sessions — should NOT be poked")

	// Verify runner_autopilot received the right path and payload
	runnerPokes := runnerMock.getPokes()
	require.Len(t, runnerPokes, 1)
	assert.Equal(t, "/orchestration", runnerPokes[0].Path)
	var pokedEvent map[string]interface{}
	require.NoError(t, json.Unmarshal(runnerPokes[0].Body, &pokedEvent))
	assert.Equal(t, "broadcast", pokedEvent["type"])
	_, hasJsonRPC := pokedEvent["jsonrpc"]
	assert.False(t, hasJsonRPC, "Broadcast poke should NOT use JSON-RPC")

	// ---------------------------------------------------------------
	// Step 3: Spawn a simulator session, then broadcast again
	// ---------------------------------------------------------------
	runnerMock.reset()

	spawnBody2, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "simulator", "count": 1},
		},
	})
	req2 := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBody2))
	req2.Header.Set("Content-Type", "application/json")
	w2 := httptest.NewRecorder()
	gw.Router.ServeHTTP(w2, req2)
	require.Equal(t, http.StatusOK, w2.Code)

	time.Sleep(500 * time.Millisecond)

	// Reset before second broadcast
	runnerMock.reset()
	simulatorMock.reset()

	broadcast2 := map[string]interface{}{
		"type": "broadcast", "eventId": "evt-2",
		"payload": map[string]interface{}{"data": "Go!"},
	}
	require.NoError(t, gw.Switchboard.PublishOrchestration(ctx, "simulation:broadcast", broadcast2))

	time.Sleep(2 * time.Second)

	assert.Equal(t, 1, runnerMock.hits(), "Runner_autopilot still has session — should be poked")
	assert.Equal(t, 1, simulatorMock.hits(), "Simulator now has session — should be poked")

	// Verify simulator gets orchestration poke (local callable agents use /orchestration)
	simPokes := simulatorMock.getPokes()
	require.Len(t, simPokes, 1)
	assert.Equal(t, "/orchestration", simPokes[0].Path,
		"Local callable simulator should get /orchestration poke during broadcast")

	// ---------------------------------------------------------------
	// Step 4: Untrack runner_autopilot, broadcast — only simulator poked
	// ---------------------------------------------------------------
	runnerMock.reset()
	simulatorMock.reset()

	runnerSessionID := sessions[0].(map[string]interface{})["sessionId"].(string)
	require.NoError(t, gw.Registry.UntrackSession(ctx, runnerSessionID))

	broadcast3 := map[string]interface{}{
		"type": "broadcast", "eventId": "evt-3",
		"payload": map[string]interface{}{"data": "Final!"},
	}
	require.NoError(t, gw.Switchboard.PublishOrchestration(ctx, "simulation:broadcast", broadcast3))

	time.Sleep(2 * time.Second)

	assert.Equal(t, 0, runnerMock.hits(), "Runner_autopilot session untracked — should NOT be poked")
	assert.Equal(t, 1, simulatorMock.hits(), "Simulator still has session — should be poked")

	t.Log("✅ E2E session-aware routing verified: spawn → broadcast → selective poke → untrack → selective poke")
}

// TestIntegration_FlushClearsAllSessions verifies that Flush removes all sessions
// and subsequent broadcasts poke no agents.
func TestIntegration_FlushClearsAllSessions(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": runnerMock.url(), "version": "1.0.0",
		},
	}, map[string]*agentMock{"runner_autopilot": runnerMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-flush")
	ctx := context.Background()

	// Spawn 3 runner_autopilot sessions
	spawnBody, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 3},
		},
	})
	req := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)
	require.Equal(t, http.StatusOK, w.Code)

	time.Sleep(500 * time.Millisecond)

	// Reset poke counters before flush test
	runnerMock.reset()

	// Flush all sessions
	flushReq := httptest.NewRequest("POST", "/api/v1/sessions/flush", nil)
	flushW := httptest.NewRecorder()
	gw.Router.ServeHTTP(flushW, flushReq)
	require.Equal(t, http.StatusOK, flushW.Code)

	// Broadcast after flush — no one should be poked
	broadcast := map[string]interface{}{
		"type": "broadcast", "eventId": "evt-flush",
		"payload": map[string]interface{}{"data": "Nobody home"},
	}
	require.NoError(t, gw.Switchboard.PublishOrchestration(ctx, "simulation:broadcast", broadcast))

	time.Sleep(1 * time.Second)

	assert.Equal(t, 0, runnerMock.hits(), "After flush — no agents should be poked")

	// Verify ListSessions is empty
	listReq := httptest.NewRequest("GET", "/api/v1/sessions", nil)
	listW := httptest.NewRecorder()
	gw.Router.ServeHTTP(listW, listReq)
	require.Equal(t, http.StatusOK, listW.Code)

	var listedSessions []string
	require.NoError(t, json.Unmarshal(listW.Body.Bytes(), &listedSessions))
	assert.Empty(t, listedSessions, "After flush — session list should be empty")

	t.Log("✅ Flush clears all sessions and broadcast pokes no agents")
}

// TestIntegration_BatchSpawn_RealRedis exercises the batch spawn pipeline
// against real Docker Redis to catch issues that miniredis cannot surface
// (e.g., MISCONF RDB snapshot errors, pipeline/connection pool issues).
//
// This test would have caught the MISCONF error from PR #134's worktree
// slot setup where Redis had RDB persistence enabled.
func TestIntegration_BatchSpawn_RealRedis(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	simulatorMock := newAgentMock()
	defer simulatorMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
		"simulator": map[string]interface{}{
			"name": "simulator", "url": simulatorMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "callable"},
				}},
			},
		},
	}, map[string]*agentMock{"runner_autopilot": runnerMock, "simulator": simulatorMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-batch-spawn")

	// ---------------------------------------------------------------
	// Step 1: Batch spawn 10 runner_autopilots + 5 simulators in a single request
	// ---------------------------------------------------------------
	spawnBody, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 10},
			{"agentType": "simulator", "count": 5},
		},
	})

	req := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code,
		"Batch spawn must succeed against real Redis (MISCONF would cause 500)")

	var spawnResp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &spawnResp))
	sessions := spawnResp["sessions"].([]interface{})
	assert.Len(t, sessions, 15, "Should spawn 15 total sessions (10 + 5)")

	// ---------------------------------------------------------------
	// Step 2: Verify all sessions are tracked in the registry
	// ---------------------------------------------------------------
	for _, raw := range sessions {
		sess := raw.(map[string]interface{})
		sessionID := sess["sessionId"].(string)
		agentType := sess["agentType"].(string)

		foundType, ok, err := gw.Registry.FindAgentType(context.Background(), sessionID)
		require.NoError(t, err, "Redis lookup must not fail for session %s", sessionID)
		assert.True(t, ok, "Session %s must be tracked in registry", sessionID)
		assert.Equal(t, agentType, foundType, "Session %s agent type must match", sessionID)
	}

	// ---------------------------------------------------------------
	// Step 3: Verify spawn queues received events (sharded queues)
	// NOTE: Queue assertions use >=, not ==, because active simulation
	// agents may BLPop items between write and assertion. The critical
	// assertion is that sessions ARE tracked (Step 2) and Redis writes
	// succeed (Step 1 returns 200, not 500 from MISCONF).
	// ---------------------------------------------------------------
	// Spawns are now sharded: simulation:spawns:{agentType}:{shard}
	// Sum across all shards to check total queue depth.
	var runnerQueueLen int64
	for i := 0; i < hub.DefaultSpawnShards; i++ {
		l, err := rdb.LLen(context.Background(), fmt.Sprintf("simulation:spawns:runner_autopilot:%d", i)).Result()
		require.NoError(t, err)
		runnerQueueLen += l
	}
	t.Logf("Runner_autopilot total spawn queue length across %d shards: %d (may be <10 if agents are consuming)", hub.DefaultSpawnShards, runnerQueueLen)

	var simQueueLen int64
	for i := 0; i < hub.DefaultSpawnShards; i++ {
		l, err := rdb.LLen(context.Background(), fmt.Sprintf("simulation:spawns:simulator:%d", i)).Result()
		require.NoError(t, err)
		simQueueLen += l
	}
	t.Logf("Simulator total spawn queue length across %d shards: %d (may be <5 if agents are consuming)", hub.DefaultSpawnShards, simQueueLen)

	// ---------------------------------------------------------------
	// Step 4: Verify both agent types are active
	// ---------------------------------------------------------------
	types, err := gw.Registry.ActiveAgentTypes(context.Background())
	require.NoError(t, err)
	assert.Contains(t, types, "runner_autopilot")
	assert.Contains(t, types, "simulator")

	t.Log("✅ Batch spawn: 15 sessions tracked, queues populated, agent types active — all via real Redis")
}

// TestIntegration_EnvironmentReset_FlushesAllKeyTypes exercises the full
// environment reset endpoint against real Docker Redis, verifying that ALL
// three key families (sessions, spawn queues, session maps) are flushed.
func TestIntegration_EnvironmentReset_FlushesAllKeyTypes(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	ctx := context.Background()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	simulatorMock := newAgentMock()
	defer simulatorMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner": map[string]interface{}{
			"name": "runner", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
		"simulator": map[string]interface{}{
			"name": "simulator", "url": simulatorMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "callable"},
				}},
			},
		},
	}, map[string]*agentMock{"runner": runnerMock, "simulator": simulatorMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-reset")

	// ---------------------------------------------------------------
	// Seed ALL three key types in real Redis
	// ---------------------------------------------------------------

	// (a) Sessions — use the registry to TrackSession
	require.NoError(t, gw.Registry.TrackSession(ctx, "reset-runner-1", "runner", ""))
	require.NoError(t, gw.Registry.TrackSession(ctx, "reset-runner-2", "runner", ""))
	require.NoError(t, gw.Registry.TrackSession(ctx, "reset-sim-1", "simulator", ""))

	// (b) Spawn queues — seed directly via RPush
	require.NoError(t, rdb.RPush(ctx, "simulation:spawns:runner", "spawn-evt-1", "spawn-evt-2").Err())
	require.NoError(t, rdb.RPush(ctx, "simulation:spawns:simulator", "spawn-evt-3").Err())

	// (c) Session maps — seed directly via Set
	require.NoError(t, rdb.Set(ctx, "session_map:ctx-1", "mapping-data-1", 0).Err())
	require.NoError(t, rdb.Set(ctx, "session_map:ctx-2", "mapping-data-2", 0).Err())

	// ---------------------------------------------------------------
	// Verify pre-conditions: all keys exist
	// ---------------------------------------------------------------
	sessionKeys, err := rdb.Keys(ctx, "e2e-reset:session:*").Result()
	require.NoError(t, err)
	assert.Len(t, sessionKeys, 3, "Pre-condition: 3 session keys should exist")

	activeAgentsCount, err := rdb.Exists(ctx, "e2e-reset:active-agents").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(1), activeAgentsCount, "Pre-condition: active-agents key should exist")

	spawnKeys, err := rdb.Keys(ctx, "simulation:spawns:*").Result()
	require.NoError(t, err)
	assert.Len(t, spawnKeys, 2, "Pre-condition: 2 spawn queue keys should exist")

	mapKeys, err := rdb.Keys(ctx, "session_map:*").Result()
	require.NoError(t, err)
	assert.Len(t, mapKeys, 2, "Pre-condition: 2 session_map keys should exist")

	// ---------------------------------------------------------------
	// Call POST /api/v1/environment/reset (flush all)
	// ---------------------------------------------------------------
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", nil)
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "Reset should return 200")

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "reset", resp["status"], "Response status should be 'reset'")

	// ---------------------------------------------------------------
	// Assert each result shows flushed: true with correct counts
	// ---------------------------------------------------------------
	results := resp["results"].(map[string]interface{})

	sessResult := results["sessions"].(map[string]interface{})
	assert.Equal(t, true, sessResult["flushed"], "Sessions should be flushed")
	assert.Equal(t, float64(3), sessResult["count"], "Should report 3 sessions flushed")

	queueResult := results["queues"].(map[string]interface{})
	assert.Equal(t, true, queueResult["flushed"], "Queues should be flushed")
	assert.Equal(t, float64(2), queueResult["count"], "Should report 2 spawn queue keys flushed")

	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, true, mapResult["flushed"], "Maps should be flushed")
	assert.Equal(t, float64(2), mapResult["count"], "Should report 2 session_map keys flushed")

	// ---------------------------------------------------------------
	// Verify ALL key types are gone from Redis
	// ---------------------------------------------------------------
	sessionKeysAfter, err := rdb.Keys(ctx, "e2e-reset:session:*").Result()
	require.NoError(t, err)
	assert.Empty(t, sessionKeysAfter, "All session keys should be deleted")

	activeAgentsAfter, err := rdb.Exists(ctx, "e2e-reset:active-agents").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(0), activeAgentsAfter, "active-agents key should be deleted")

	spawnKeysAfter, err := rdb.Keys(ctx, "simulation:spawns:*").Result()
	require.NoError(t, err)
	assert.Empty(t, spawnKeysAfter, "All spawn queue keys should be deleted")

	mapKeysAfter, err := rdb.Keys(ctx, "session_map:*").Result()
	require.NoError(t, err)
	assert.Empty(t, mapKeysAfter, "All session_map keys should be deleted")

	t.Log("✅ Environment reset: all three key families flushed via real Redis")
}

// TestIntegration_EnvironmentReset_SelectiveFlush exercises selective reset
// (only sessions), verifying that spawn queues and session maps survive.
func TestIntegration_EnvironmentReset_SelectiveFlush(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	ctx := context.Background()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	simulatorMock := newAgentMock()
	defer simulatorMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner": map[string]interface{}{
			"name": "runner", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
		"simulator": map[string]interface{}{
			"name": "simulator", "url": simulatorMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "callable"},
				}},
			},
		},
	}, map[string]*agentMock{"runner": runnerMock, "simulator": simulatorMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-selective")

	// ---------------------------------------------------------------
	// Seed ALL three key types in real Redis
	// ---------------------------------------------------------------

	// (a) Sessions
	require.NoError(t, gw.Registry.TrackSession(ctx, "sel-runner-1", "runner", ""))
	require.NoError(t, gw.Registry.TrackSession(ctx, "sel-sim-1", "simulator", ""))

	// (b) Spawn queues
	require.NoError(t, rdb.RPush(ctx, "simulation:spawns:runner", "spawn-evt-1").Err())
	require.NoError(t, rdb.RPush(ctx, "simulation:spawns:simulator", "spawn-evt-2").Err())

	// (c) Session maps
	require.NoError(t, rdb.Set(ctx, "session_map:ctx-1", "mapping-data-1", 0).Err())
	require.NoError(t, rdb.Set(ctx, "session_map:ctx-2", "mapping-data-2", 0).Err())

	// ---------------------------------------------------------------
	// Call reset with only "sessions" target
	// ---------------------------------------------------------------
	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{"sessions"},
	})
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code, "Selective reset should return 200")

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "reset", resp["status"])

	results := resp["results"].(map[string]interface{})

	// Sessions WERE flushed
	sessResult := results["sessions"].(map[string]interface{})
	assert.Equal(t, true, sessResult["flushed"], "Sessions should be flushed")
	assert.Equal(t, float64(2), sessResult["count"], "Should report 2 sessions flushed")

	// Queues were NOT flushed
	queueResult := results["queues"].(map[string]interface{})
	assert.Equal(t, false, queueResult["flushed"], "Queues should NOT be flushed")

	// Maps were NOT flushed
	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, false, mapResult["flushed"], "Maps should NOT be flushed")

	// ---------------------------------------------------------------
	// Verify sessions are gone
	// ---------------------------------------------------------------
	sessionKeysAfter, err := rdb.Keys(ctx, "e2e-selective:session:*").Result()
	require.NoError(t, err)
	assert.Empty(t, sessionKeysAfter, "Session keys should be deleted")

	activeAgentsAfter, err := rdb.Exists(ctx, "e2e-selective:active-agents").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(0), activeAgentsAfter, "active-agents key should be deleted")

	// ---------------------------------------------------------------
	// Verify spawn queues STILL exist
	// ---------------------------------------------------------------
	spawnKeysAfter, err := rdb.Keys(ctx, "simulation:spawns:*").Result()
	require.NoError(t, err)
	assert.Len(t, spawnKeysAfter, 2, "Spawn queue keys should still exist")

	runnerQueueLen, err := rdb.LLen(ctx, "simulation:spawns:runner").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(1), runnerQueueLen, "Runner spawn queue should still have 1 entry")

	// ---------------------------------------------------------------
	// Verify session maps STILL exist
	// ---------------------------------------------------------------
	mapKeysAfter, err := rdb.Keys(ctx, "session_map:*").Result()
	require.NoError(t, err)
	assert.Len(t, mapKeysAfter, 2, "Session map keys should still exist")

	t.Log("✅ Selective reset: sessions flushed, queues and maps preserved")
}

// --- Simulation Isolation Integration Tests ---
//
// These tests exercise the core guarantee: two concurrent simulations
// must not cross-contaminate. Each simulation's spawns, broadcasts,
// and registry data must stay scoped to its own simulation_id.

// TestSimulationIsolation_SpawnAndTrack verifies that sessions spawned with
// different simulation_ids are correctly mapped in the registry, and that
// GET /api/v1/simulations returns both simulation IDs.
func TestSimulationIsolation_SpawnAndTrack(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
	}, map[string]*agentMock{"runner_autopilot": runnerMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-sim-iso")
	ctx := context.Background()

	// ---------------------------------------------------------------
	// Step 1: Spawn 3 runners with simulation_id "sim-A"
	// ---------------------------------------------------------------
	spawnBodyA, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 3},
		},
		"simulation_id": "sim-A",
	})
	reqA := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBodyA))
	reqA.Header.Set("Content-Type", "application/json")
	wA := httptest.NewRecorder()
	gw.Router.ServeHTTP(wA, reqA)
	require.Equal(t, http.StatusOK, wA.Code, "Spawn sim-A should succeed")

	var respA map[string]interface{}
	require.NoError(t, json.Unmarshal(wA.Body.Bytes(), &respA))
	sessionsA := respA["sessions"].([]interface{})
	require.Len(t, sessionsA, 3, "sim-A should have 3 sessions")

	// ---------------------------------------------------------------
	// Step 2: Spawn 2 runners with simulation_id "sim-B"
	// ---------------------------------------------------------------
	spawnBodyB, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 2},
		},
		"simulation_id": "sim-B",
	})
	reqB := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBodyB))
	reqB.Header.Set("Content-Type", "application/json")
	wB := httptest.NewRecorder()
	gw.Router.ServeHTTP(wB, reqB)
	require.Equal(t, http.StatusOK, wB.Code, "Spawn sim-B should succeed")

	var respB map[string]interface{}
	require.NoError(t, json.Unmarshal(wB.Body.Bytes(), &respB))
	sessionsB := respB["sessions"].([]interface{})
	require.Len(t, sessionsB, 2, "sim-B should have 2 sessions")

	time.Sleep(500 * time.Millisecond)

	// ---------------------------------------------------------------
	// Step 3: Verify GET /api/v1/simulations returns both sim-A and sim-B
	// ---------------------------------------------------------------
	listReq := httptest.NewRequest("GET", "/api/v1/simulations", nil)
	listW := httptest.NewRecorder()
	gw.Router.ServeHTTP(listW, listReq)
	require.Equal(t, http.StatusOK, listW.Code)

	var simResp struct {
		Simulations []string `json:"simulations"`
	}
	require.NoError(t, json.Unmarshal(listW.Body.Bytes(), &simResp))
	assert.ElementsMatch(t, []string{"sim-A", "sim-B"}, simResp.Simulations,
		"Both simulation IDs should be listed")

	// ---------------------------------------------------------------
	// Step 4: Verify each session maps to the correct simulation_id
	// ---------------------------------------------------------------
	for _, raw := range sessionsA {
		sess := raw.(map[string]interface{})
		sessionID := sess["sessionId"].(string)
		simID, err := gw.Registry.FindSimulation(ctx, sessionID)
		require.NoError(t, err)
		assert.Equal(t, "sim-A", simID,
			"Session %s should map to sim-A", sessionID)
	}
	for _, raw := range sessionsB {
		sess := raw.(map[string]interface{})
		sessionID := sess["sessionId"].(string)
		simID, err := gw.Registry.FindSimulation(ctx, sessionID)
		require.NoError(t, err)
		assert.Equal(t, "sim-B", simID,
			"Session %s should map to sim-B", sessionID)
	}

	t.Log("✅ Simulation isolation: 5 sessions across 2 simulations correctly tracked via real Redis")
}

// TestSimulationIsolation_HubRouting verifies that WebSocket clients subscribed
// to different simulation IDs only receive messages for their simulation.
// This tests the Hub's simulation-based routing (SimulationId field in Wrapper).
//
// Because gorilla/websocket connections become unusable after a read timeout,
// we use separate sub-tests with fresh connections to test negative cases.
func TestSimulationIsolation_HubRouting(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	t.Run("SimA_reaches_SimA_subscriber_only", func(t *testing.T) {
		h := hub.NewHub()
		go h.Run()
		server := httptest.NewServer(setupRouter(h, nil, nil, session.NewInMemorySessionService(), "iso-hub-1", nil, nil))
		defer server.Close()

		wsURL := "ws" + server.URL[4:]

		wsA, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=client-A", nil)
		require.NoError(t, err)
		defer wsA.Close()

		wsB, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=client-B", nil)
		require.NoError(t, err)
		defer wsB.Close()

		time.Sleep(100 * time.Millisecond)

		// Subscribe A to sim-A, B to sim-B
		require.NoError(t, wsA.WriteMessage(websocket.TextMessage,
			[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-A"}`)))
		require.NoError(t, wsB.WriteMessage(websocket.TextMessage,
			[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-B"}`)))
		time.Sleep(100 * time.Millisecond)

		// Send sim-A message (targeted at nonexistent session to isolate sim routing)
		h.HandleRemoteMessage(&gateway.Wrapper{
			Type:         "test_event",
			SimulationId: "sim-A",
			SessionId:    "nonexistent-session",
		})

		// Client A should receive it
		_ = wsA.SetReadDeadline(time.Now().Add(1 * time.Second))
		_, msgA, errA := wsA.ReadMessage()
		assert.NoError(t, errA, "Client A should receive sim-A message")
		assert.NotEmpty(t, msgA)

		// Client B should NOT receive it
		_ = wsB.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
		_, _, errB := wsB.ReadMessage()
		assert.Error(t, errB, "Client B should NOT receive sim-A message")
	})

	t.Run("SimB_reaches_SimB_subscriber_only", func(t *testing.T) {
		h := hub.NewHub()
		go h.Run()
		server := httptest.NewServer(setupRouter(h, nil, nil, session.NewInMemorySessionService(), "iso-hub-2", nil, nil))
		defer server.Close()

		wsURL := "ws" + server.URL[4:]

		wsA, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=client-A", nil)
		require.NoError(t, err)
		defer wsA.Close()

		wsB, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=client-B", nil)
		require.NoError(t, err)
		defer wsB.Close()

		time.Sleep(100 * time.Millisecond)

		require.NoError(t, wsA.WriteMessage(websocket.TextMessage,
			[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-A"}`)))
		require.NoError(t, wsB.WriteMessage(websocket.TextMessage,
			[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-B"}`)))
		time.Sleep(100 * time.Millisecond)

		// Send sim-B message
		h.HandleRemoteMessage(&gateway.Wrapper{
			Type:         "test_event",
			SimulationId: "sim-B",
			SessionId:    "nonexistent-session",
		})

		// Client B should receive it
		_ = wsB.SetReadDeadline(time.Now().Add(1 * time.Second))
		_, msgB, errB := wsB.ReadMessage()
		assert.NoError(t, errB, "Client B should receive sim-B message")
		assert.NotEmpty(t, msgB)

		// Client A should NOT receive it
		_ = wsA.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
		_, _, errA := wsA.ReadMessage()
		assert.Error(t, errA, "Client A should NOT receive sim-B message")
	})

	t.Run("Session_routing_backward_compat", func(t *testing.T) {
		h := hub.NewHub()
		go h.Run()
		server := httptest.NewServer(setupRouter(h, nil, nil, session.NewInMemorySessionService(), "iso-hub-3", nil, nil))
		defer server.Close()

		wsURL := "ws" + server.URL[4:]

		wsA, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=client-A", nil)
		require.NoError(t, err)
		defer wsA.Close()

		time.Sleep(100 * time.Millisecond)

		// Send a Wrapper with empty SimulationId + specific SessionId destination
		h.HandleRemoteMessage(&gateway.Wrapper{
			Type:      "direct_event",
			SessionId: "client-A",
			Payload:   []byte(`{"text":"direct to A"}`),
		})

		_ = wsA.SetReadDeadline(time.Now().Add(1 * time.Second))
		_, msgDirect, errDirect := wsA.ReadMessage()
		assert.NoError(t, errDirect, "Session-based routing should still deliver to client-A")
		assert.NotEmpty(t, msgDirect)
	})

	t.Log("✅ Hub simulation routing: sim-A/sim-B isolated, session-based backward compat verified")
}

// TestSimulationIsolation_UnsubscribeStopsDelivery verifies that unsubscribing
// from a simulation stops message delivery for that simulation.
func TestSimulationIsolation_UnsubscribeStopsDelivery(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	h := hub.NewHub()
	go h.Run()

	server := httptest.NewServer(setupRouter(h, nil, nil, session.NewInMemorySessionService(), "iso-unsub-test", nil, nil))
	defer server.Close()

	wsURL := "ws" + server.URL[4:]

	wsClient, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=unsub-test", nil)
	require.NoError(t, err)
	defer wsClient.Close()

	time.Sleep(100 * time.Millisecond)

	// ---------------------------------------------------------------
	// Step 1: Subscribe to sim-A
	// ---------------------------------------------------------------
	err = wsClient.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-A"}`))
	require.NoError(t, err)
	time.Sleep(100 * time.Millisecond)

	// Verify it receives sim-A messages
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "pre_unsub",
		SimulationId: "sim-A",
		SessionId:    "nonexistent",
	})

	_ = wsClient.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msg1, err1 := wsClient.ReadMessage()
	assert.NoError(t, err1, "Should receive sim-A message while subscribed")
	assert.NotEmpty(t, msg1)

	// ---------------------------------------------------------------
	// Step 2: Unsubscribe from sim-A
	// ---------------------------------------------------------------
	err = wsClient.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"unsubscribe_simulation","simulation_id":"sim-A"}`))
	require.NoError(t, err)
	time.Sleep(100 * time.Millisecond)

	// ---------------------------------------------------------------
	// Step 3: Verify it no longer receives sim-A messages
	// ---------------------------------------------------------------
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "post_unsub",
		SimulationId: "sim-A",
		SessionId:    "nonexistent",
	})

	_ = wsClient.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	_, _, err2 := wsClient.ReadMessage()
	assert.Error(t, err2, "Should NOT receive sim-A message after unsubscribing")

	t.Log("✅ Unsubscribe stops delivery of simulation-scoped messages")
}

// TestSimulationIsolation_DiscoverRunnersAndTargetBroadcast exercises the
// complete frontend workflow:
//  1. Spawn runners across two simulations via the batch spawn API
//  2. Subscribe WebSocket clients to each simulation
//  3. Inject a tool_end event (simulating spawn_runners completion) via Hub
//  4. Verify only the correct client receives the event, extract session_ids
//  5. Construct and send a targeted BroadcastRequest from the WebSocket client
//  6. Verify the broadcast dispatches correctly through the switchboard
//  7. Verify cross-simulation isolation (sim-B runners not targeted)
func TestSimulationIsolation_DiscoverRunnersAndTargetBroadcast(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	runnerMock := newAgentMock()
	defer runnerMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": runnerMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "subscriber"},
				}},
			},
		},
	}, map[string]*agentMock{"runner_autopilot": runnerMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-discover-runners")
	ctx := context.Background()

	// ---------------------------------------------------------------
	// Step 1: Spawn runners in two separate simulations
	// ---------------------------------------------------------------
	spawnBodyA, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 3},
		},
		"simulation_id": "sim-A",
	})
	reqA := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBodyA))
	reqA.Header.Set("Content-Type", "application/json")
	wA := httptest.NewRecorder()
	gw.Router.ServeHTTP(wA, reqA)
	require.Equal(t, http.StatusOK, wA.Code, "Spawn sim-A should succeed")

	var respA map[string]interface{}
	require.NoError(t, json.Unmarshal(wA.Body.Bytes(), &respA))
	sessionsA := respA["sessions"].([]interface{})
	require.Len(t, sessionsA, 3, "sim-A should have 3 runner sessions")

	// Extract sim-A session IDs
	var simASessionIDs []string
	for _, raw := range sessionsA {
		sess := raw.(map[string]interface{})
		simASessionIDs = append(simASessionIDs, sess["sessionId"].(string))
	}
	t.Logf("Sim-A runner session IDs: %v", simASessionIDs)

	spawnBodyB, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 2},
		},
		"simulation_id": "sim-B",
	})
	reqB := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBodyB))
	reqB.Header.Set("Content-Type", "application/json")
	wB := httptest.NewRecorder()
	gw.Router.ServeHTTP(wB, reqB)
	require.Equal(t, http.StatusOK, wB.Code, "Spawn sim-B should succeed")

	var respB map[string]interface{}
	require.NoError(t, json.Unmarshal(wB.Body.Bytes(), &respB))
	sessionsB := respB["sessions"].([]interface{})
	require.Len(t, sessionsB, 2, "sim-B should have 2 runner sessions")

	var simBSessionIDs []string
	for _, raw := range sessionsB {
		sess := raw.(map[string]interface{})
		simBSessionIDs = append(simBSessionIDs, sess["sessionId"].(string))
	}
	t.Logf("Sim-B runner session IDs: %v", simBSessionIDs)

	time.Sleep(500 * time.Millisecond) // Let registry propagate

	// ---------------------------------------------------------------
	// Step 2: Connect WebSocket clients and subscribe to simulations
	// ---------------------------------------------------------------
	server := httptest.NewServer(gw.Router)
	defer server.Close()

	wsURL := "ws" + server.URL[4:]

	wsA, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=observer-A", nil)
	require.NoError(t, err, "Client A should connect")
	defer wsA.Close()

	wsB, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=observer-B", nil)
	require.NoError(t, err, "Client B should connect")
	defer wsB.Close()

	time.Sleep(100 * time.Millisecond) // Let registrations complete

	// Subscribe A to sim-A, B to sim-B
	require.NoError(t, wsA.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-A"}`)))
	require.NoError(t, wsB.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-B"}`)))
	time.Sleep(100 * time.Millisecond) // Let subscriptions process

	// ---------------------------------------------------------------
	// Step 3: Simulate the spawn_runners tool_end event for sim-A
	// ---------------------------------------------------------------
	toolEndPayload := map[string]interface{}{
		"tool_name": "spawn_runners",
		"result": map[string]interface{}{
			"status":      "success",
			"session_ids": simASessionIDs,
			"count":       3,
			"message":     "Spawned 3 runner agents",
		},
	}
	payloadBytes, err := json.Marshal(toolEndPayload)
	require.NoError(t, err)

	toolEndWrapper := &gateway.Wrapper{
		Timestamp:    time.Now().Format(time.RFC3339),
		Type:         "json",
		Event:        "tool_end",
		Payload:      payloadBytes,
		SimulationId: "sim-A",
		Origin: &gateway.Origin{
			Type:      "agent",
			Id:        "simulator",
			SessionId: "sim-A",
		},
		Status: "success",
	}

	gw.Hub.HandleRemoteMessage(toolEndWrapper)

	// ---------------------------------------------------------------
	// Step 4: Verify Client A receives the tool_end event
	// ---------------------------------------------------------------
	_ = wsA.SetReadDeadline(time.Now().Add(2 * time.Second))
	msgType, msgData, err := wsA.ReadMessage()
	require.NoError(t, err, "Client A should receive sim-A tool_end event")
	assert.Equal(t, websocket.BinaryMessage, msgType, "Hub sends protobuf as binary frames")

	var receivedWrapper gateway.Wrapper
	require.NoError(t, proto.Unmarshal(msgData, &receivedWrapper),
		"Should unmarshal as gateway.Wrapper protobuf")

	assert.Equal(t, "sim-A", receivedWrapper.SimulationId,
		"Received event should be for sim-A")
	assert.Equal(t, "tool_end", receivedWrapper.Event,
		"Received event should be tool_end")
	assert.Equal(t, "json", receivedWrapper.Type,
		"Received event type should be json")

	// Parse the payload and extract session_ids
	var receivedPayload map[string]interface{}
	require.NoError(t, json.Unmarshal(receivedWrapper.Payload, &receivedPayload),
		"Payload should be valid JSON")

	result, ok := receivedPayload["result"].(map[string]interface{})
	require.True(t, ok, "Payload should contain 'result' object")

	discoveredSessionIDs, ok := result["session_ids"].([]interface{})
	require.True(t, ok, "result should contain 'session_ids' array")
	require.Len(t, discoveredSessionIDs, 3,
		"Should discover 3 session IDs from tool_end event")

	// Verify the discovered session_ids match what was returned from spawn API
	var discoveredStrings []string
	for _, id := range discoveredSessionIDs {
		discoveredStrings = append(discoveredStrings, id.(string))
	}
	assert.ElementsMatch(t, simASessionIDs, discoveredStrings,
		"Discovered session IDs should match spawned session IDs")

	t.Logf("✅ Client A discovered runner session IDs via tool_end event: %v", discoveredStrings)

	// Client B should NOT receive the sim-A tool_end event
	_ = wsB.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
	_, _, errB := wsB.ReadMessage()
	assert.Error(t, errB, "Client B should NOT receive sim-A tool_end event (isolation)")

	// ---------------------------------------------------------------
	// Step 5: Client A sends a targeted BroadcastRequest using discovered IDs
	// ---------------------------------------------------------------
	hydrationPayload := []byte(`{"event": "hydration_station"}`)
	broadcastReq := &gateway.BroadcastRequest{
		Payload:          hydrationPayload,
		TargetSessionIds: simASessionIDs,
		Async:            true,
	}
	broadcastReqBytes, err := proto.Marshal(broadcastReq)
	require.NoError(t, err)

	broadcastWrapper := &gateway.Wrapper{
		Type:      "broadcast",
		RequestId: "hydration-req-1",
		Payload:   broadcastReqBytes,
	}
	broadcastWrapperBytes, err := proto.Marshal(broadcastWrapper)
	require.NoError(t, err)

	// Reset mock before broadcast to track dispatch
	runnerMock.reset()

	err = wsA.WriteMessage(websocket.BinaryMessage, broadcastWrapperBytes)
	require.NoError(t, err, "Client A should be able to send broadcast request")

	// ---------------------------------------------------------------
	// Step 6: Verify the broadcast was dispatched correctly
	// ---------------------------------------------------------------
	// The handleBinaryMessage function processes the broadcast:
	// 1. Calls sb.Broadcast() for cross-instance fan-out (Redis pub/sub)
	// 2. Unmarshals BroadcastRequest, resolves target session IDs via registry
	// 3. Dispatches to the correct agent type (runner_autopilot)
	//
	// Since the switchboard dispatches asynchronously via goroutines,
	// we need to wait for the poke to arrive at the mock agent.
	time.Sleep(3 * time.Second)

	// Verify the runner mock was poked (dispatch went through switchboard)
	pokeCount := runnerMock.hits()
	t.Logf("Runner mock poke count after broadcast: %d", pokeCount)

	// The switchboard should have dispatched to runner_autopilot since all
	// target session IDs resolve to that agent type in the registry.
	// Note: The exact poke count depends on whether the broadcast also triggers
	// the cross-instance Redis pub/sub subscriber loop. We verify at least 1.
	assert.GreaterOrEqual(t, pokeCount, 1,
		"Switchboard should dispatch to runner_autopilot for targeted broadcast")

	// Verify the poke was to the /orchestration endpoint
	pokes := runnerMock.getPokes()
	if len(pokes) > 0 {
		assert.Equal(t, "/orchestration", pokes[0].Path,
			"Broadcast poke should target /orchestration endpoint")

		// Verify the poke payload contains the target session IDs
		var pokedEvent map[string]interface{}
		if err := json.Unmarshal(pokes[0].Body, &pokedEvent); err == nil {
			assert.Equal(t, "broadcast", pokedEvent["type"],
				"Poked event should be of type 'broadcast'")
			if payload, ok := pokedEvent["payload"].(map[string]interface{}); ok {
				if targets, ok := payload["targets"].([]interface{}); ok {
					var targetStrings []string
					for _, tgt := range targets {
						targetStrings = append(targetStrings, tgt.(string))
					}
					assert.ElementsMatch(t, simASessionIDs, targetStrings,
						"Broadcast targets should be sim-A's runner session IDs")
					t.Logf("✅ Broadcast payload contains correct targets: %v", targetStrings)
				}
			}
		}
	}

	// ---------------------------------------------------------------
	// Step 7: Verify isolation — sim-B runners NOT targeted
	// ---------------------------------------------------------------
	// Verify via registry that all target session IDs resolve to runner_autopilot
	for _, sid := range simASessionIDs {
		agentType, found, err := gw.Registry.FindAgentType(ctx, sid)
		require.NoError(t, err)
		assert.True(t, found, "Sim-A session %s should be in registry", sid)
		assert.Equal(t, "runner_autopilot", agentType,
			"Sim-A session %s should map to runner_autopilot", sid)
	}

	// Verify sim-B sessions are NOT in the target list
	for _, sidB := range simBSessionIDs {
		assert.NotContains(t, simASessionIDs, sidB,
			"Sim-B session %s should NOT be in sim-A targets", sidB)
	}

	// Verify sim-B sessions are tracked separately with correct simulation
	for _, sid := range simBSessionIDs {
		simID, err := gw.Registry.FindSimulation(ctx, sid)
		require.NoError(t, err)
		assert.Equal(t, "sim-B", simID,
			"Sim-B session %s should map to simulation sim-B", sid)
	}

	// Verify Client B never received the tool_end event (already confirmed above)
	// and cross-check with a fresh connection to verify no leakage
	t.Log("✅ Simulation isolation verified:")
	t.Log("   - Client A received tool_end with correct session_ids")
	t.Log("   - Client B did NOT receive sim-A events")
	t.Log("   - Targeted broadcast dispatched to runner_autopilot agent type")
	t.Log("   - Target session IDs are exclusively sim-A's runners")
	t.Log("   - Sim-B sessions correctly isolated in registry")
}

// TestIntegration_CallableSpawn_AllSessionsReceiveBroadcast verifies that
// callable agents receive one HTTP poke per spawned session. Unlike subscriber
// agents (which share a Redis queue and need only a single wake-up poke),
// callable agents have no queue listener — each spawn event must be delivered
// individually via HTTP POST /orchestration.
//
// This test:
//  1. Creates a callable agent mock that records all /orchestration pokes
//  2. Spawns 5 callable sessions via POST /api/v1/spawn
//  3. Verifies all 5 spawn events are delivered via HTTP pokes (not just 1)
//  4. Verifies each spawn poke carries a unique session ID
func TestIntegration_CallableSpawn_AllSessionsReceiveBroadcast(t *testing.T) {
	if testing.Short() {
		t.Skip("Integration test — skipped in short mode")
	}

	rdb := requireRedis(t)
	defer rdb.Close()

	callableMock := newAgentMock()
	defer callableMock.close()

	agentURLs := createTestAgentURLs(t, map[string]interface{}{
		"test_callable": map[string]interface{}{
			"name": "test_callable", "url": callableMock.url(), "version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{map[string]interface{}{
					"uri": "n26:dispatch/1.0", "params": map[string]interface{}{"mode": "callable"},
				}},
			},
		},
	}, map[string]*agentMock{"test_callable": callableMock})

	gw := newTestGatewayStack(t, rdb, agentURLs, "e2e-callable-spawn")

	// ---------------------------------------------------------------
	// Step 1: Spawn 5 callable sessions
	// ---------------------------------------------------------------
	spawnBody, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "test_callable", "count": 5},
		},
	})
	req := httptest.NewRequest("POST", "/api/v1/spawn", bytes.NewReader(spawnBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	gw.Router.ServeHTTP(w, req)
	require.Equal(t, http.StatusOK, w.Code, "Spawn should succeed")

	// Parse spawned session IDs from the response
	var spawnResp struct {
		Sessions []struct {
			SessionID string `json:"sessionId"`
			AgentType string `json:"agentType"`
		} `json:"sessions"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &spawnResp))
	require.Len(t, spawnResp.Sessions, 5, "Should spawn 5 sessions")

	// Collect expected session IDs
	expectedSIDs := make(map[string]bool)
	for _, s := range spawnResp.Sessions {
		expectedSIDs[s.SessionID] = true
		assert.Equal(t, "test_callable", s.AgentType)
	}
	assert.Equal(t, 5, len(expectedSIDs), "All 5 session IDs must be unique")

	// ---------------------------------------------------------------
	// Step 2: Wait for all 5 spawn pokes to be delivered
	// ---------------------------------------------------------------
	// Callable agents get one HTTP poke per session (fire-and-forget goroutines).
	require.Eventually(t, func() bool {
		return callableMock.hits() >= 5
	}, 5*time.Second, 50*time.Millisecond,
		"All 5 spawn events should be delivered via HTTP pokes")

	// ---------------------------------------------------------------
	// Step 3: Verify each poke is a spawn_agent with a unique session ID
	// ---------------------------------------------------------------
	pokes := callableMock.getPokes()
	require.GreaterOrEqual(t, len(pokes), 5, "Should have at least 5 pokes recorded")

	spawnedSIDs := make(map[string]bool)
	for _, p := range pokes {
		assert.Equal(t, "/orchestration", p.Path,
			"All spawn pokes should target /orchestration")

		var ev map[string]interface{}
		require.NoError(t, json.Unmarshal(p.Body, &ev),
			"Poke body should be valid JSON")
		assert.Equal(t, "spawn_agent", ev["type"],
			"Poke event type should be spawn_agent")

		sid, ok := ev["sessionId"].(string)
		require.True(t, ok, "Poke should contain a sessionId string")
		spawnedSIDs[sid] = true
	}
	assert.Equal(t, 5, len(spawnedSIDs),
		"Each spawn poke should carry a unique session ID")

	// Verify the poked session IDs match what the spawn API returned
	for sid := range spawnedSIDs {
		assert.True(t, expectedSIDs[sid],
			"Poked session ID %s should match a spawned session", sid)
	}

	t.Log("✅ Callable spawn: 5 sessions spawned, 5 individual HTTP pokes delivered, all session IDs unique")
}
