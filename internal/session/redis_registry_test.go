// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package session

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRedisRegistry_TrackSession_StoresAgentType(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track two sessions for different agent types
	err := reg.TrackSession(ctx, "sess-1", "runner_autopilot", "")
	require.NoError(t, err)

	err = reg.TrackSession(ctx, "sess-2", "simulator", "")
	require.NoError(t, err)

	// FindAgentType should return the correct type for each session
	agentType, ok, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.True(t, ok)
	assert.Equal(t, "runner_autopilot", agentType)

	agentType, ok, err = reg.FindAgentType(ctx, "sess-2")
	require.NoError(t, err)
	assert.True(t, ok)
	assert.Equal(t, "simulator", agentType)

	// Unknown session should return not-found
	_, ok, err = reg.FindAgentType(ctx, "nonexistent")
	require.NoError(t, err)
	assert.False(t, ok)
}

func TestRedisRegistry_ActiveAgentTypes_ReturnsOnlyTypesWithSessions(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Initially no active types
	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Empty(t, types)

	// Track sessions for runner and simulator
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "simulator", ""))

	types, err = reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Len(t, types, 2)
	assert.Contains(t, types, "runner_autopilot")
	assert.Contains(t, types, "simulator")
}

func TestRedisRegistry_UntrackSession_RemovesFromAgentTypeSet(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track two runner sessions
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "runner_autopilot", ""))

	// Remove one — runner should still be active
	require.NoError(t, reg.UntrackSession(ctx, "sess-1"))

	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Contains(t, types, "runner_autopilot")

	// Find should return not-found for untracked session
	_, ok, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.False(t, ok)

	// Remove the last runner session — runner should no longer be active
	require.NoError(t, reg.UntrackSession(ctx, "sess-2"))

	types, err = reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.NotContains(t, types, "runner_autopilot")
}

func TestRedisRegistry_ListSessions_ReturnsAllTrackedSessions(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track sessions across different agent types
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "runner_autopilot", ""))

	sessions, err := reg.ListSessions(ctx)
	require.NoError(t, err)
	assert.Len(t, sessions, 3)
	assert.ElementsMatch(t, []string{"sess-1", "sess-2", "sess-3"}, sessions)
}

func TestRedisRegistry_ListSessions_EmptyWhenNoSessions(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	sessions, err := reg.ListSessions(ctx)
	require.NoError(t, err)
	assert.Empty(t, sessions)
}

func TestRedisRegistry_Flush_ClearsAllData(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track sessions across multiple agent types
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "runner_autopilot", ""))

	// Flush everything
	_, err := reg.Flush(ctx)
	require.NoError(t, err)

	// All lookups should return empty
	_, ok, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.False(t, ok, "sess-1 should not be found after flush")

	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Empty(t, types, "no active agent types after flush")

	sessions, err := reg.ListSessions(ctx)
	require.NoError(t, err)
	assert.Empty(t, sessions, "no sessions after flush")
}

func TestRedisRegistry_Flush_IdempotentOnEmptyRegistry(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Flush with no data should not error
	count, err := reg.Flush(ctx)
	require.NoError(t, err)
	assert.Equal(t, 0, count)
}

func TestRedisRegistry_Reap_RemovesExpiredSessionsFromSets(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track 3 sessions: 2 runners, 1 simulator
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "simulator", ""))

	// Expire sess-1 and sess-3 by deleting their session keys (simulates TTL)
	client.Del(ctx, "test:session:sess-1")
	client.Del(ctx, "test:session:sess-3")

	// Reap should clean up the stale entries
	reaped, err := reg.Reap(ctx)
	require.NoError(t, err)
	assert.Equal(t, 2, reaped)

	// Runner should still be active (sess-2 is alive)
	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Contains(t, types, "runner_autopilot")

	// Simulator should be gone (all its sessions expired)
	assert.NotContains(t, types, "simulator")

	// sess-2 should still be findable
	at, ok, err := reg.FindAgentType(ctx, "sess-2")
	require.NoError(t, err)
	assert.True(t, ok)
	assert.Equal(t, "runner_autopilot", at)
}

func TestRedisRegistry_Reap_IdempotentOnEmptyRegistry(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	reaped, err := reg.Reap(ctx)
	require.NoError(t, err)
	assert.Equal(t, 0, reaped)
}

func TestRedisRegistry_Reap_NoStaleEntries(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))

	reaped, err := reg.Reap(ctx)
	require.NoError(t, err)
	assert.Equal(t, 0, reaped)

	// Both types should still be active
	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Len(t, types, 2)
}

func TestInMemoryRegistry_TrackSession_StoresAgentType(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))

	agentType, ok, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.True(t, ok)
	assert.Equal(t, "runner_autopilot", agentType)
}

func TestInMemoryRegistry_Flush_ReturnsCount(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))

	count, err := reg.Flush(ctx)
	require.NoError(t, err)
	assert.Equal(t, 2, count)
}

func TestRedisRegistry_Flush_ReturnsCount(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "runner_autopilot", ""))

	count, err := reg.Flush(ctx)
	require.NoError(t, err)
	assert.Equal(t, 3, count)
}

func TestRedisRegistry_BatchTrackSessions_RegistersAll(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Batch-track 5 sessions across 2 agent types
	sessions := []SessionTrackingEntry{
		{SessionID: "sess-1", AgentType: "runner_autopilot"},
		{SessionID: "sess-2", AgentType: "runner_autopilot"},
		{SessionID: "sess-3", AgentType: "simulator"},
		{SessionID: "sess-4", AgentType: "runner_autopilot"},
		{SessionID: "sess-5", AgentType: "simulator"},
	}

	err := reg.BatchTrackSessions(ctx, sessions)
	require.NoError(t, err)

	// All sessions should be findable
	for _, s := range sessions {
		agentType, ok, err := reg.FindAgentType(ctx, s.SessionID)
		require.NoError(t, err)
		assert.True(t, ok, "session %s should be found", s.SessionID)
		assert.Equal(t, s.AgentType, agentType)
	}

	// Both agent types should be active
	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Len(t, types, 2)
	assert.Contains(t, types, "runner_autopilot")
	assert.Contains(t, types, "simulator")
}

func TestRedisRegistry_BatchTrackSessions_EmptySlice(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Empty batch should be a no-op
	err := reg.BatchTrackSessions(ctx, nil)
	require.NoError(t, err)

	err = reg.BatchTrackSessions(ctx, []SessionTrackingEntry{})
	require.NoError(t, err)
}

func TestRedisRegistry_BatchTrackSessions_InteroperatesWithTrackSession(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Mix individual and batch tracking
	require.NoError(t, reg.TrackSession(ctx, "individual-1", "runner_autopilot", ""))

	err := reg.BatchTrackSessions(ctx, []SessionTrackingEntry{
		{SessionID: "batch-1", AgentType: "runner_autopilot"},
		{SessionID: "batch-2", AgentType: "simulator"},
	})
	require.NoError(t, err)

	// All 3 sessions should be findable
	sessions, err := reg.ListSessions(ctx)
	require.NoError(t, err)
	assert.Len(t, sessions, 3)

	// Untrack works normally after batch track
	require.NoError(t, reg.UntrackSession(ctx, "batch-1"))
	at, ok, err := reg.FindAgentType(ctx, "batch-1")
	require.NoError(t, err)
	assert.False(t, ok)
	assert.Empty(t, at)
}

func TestInMemoryRegistry_ActiveAgentTypes(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", ""))

	types, err := reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Len(t, types, 2)
	assert.Contains(t, types, "runner_autopilot")
	assert.Contains(t, types, "simulator")

	// Untrack runner → only simulator remains
	require.NoError(t, reg.UntrackSession(ctx, "sess-1"))
	types, err = reg.ActiveAgentTypes(ctx)
	require.NoError(t, err)
	assert.Len(t, types, 1)
	assert.Contains(t, types, "simulator")
}

// ---------------------------------------------------------------------------
// Redis registry: simulation ID tracking (parity with InMemory tests in
// service_test.go). These were missing and would not have caught the
// relayCallableResponse SimulationId bug since the relay uses the registry.
// ---------------------------------------------------------------------------

func TestRedisRegistry_TrackSessionWithSimulationID(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	err := reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc")
	require.NoError(t, err)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Equal(t, "sim-abc", simID)
}

func TestRedisRegistry_ListSimulations(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track sessions across two simulation IDs
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "runner_autopilot", "sim-xyz"))

	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Len(t, sims, 2)
	assert.ElementsMatch(t, []string{"sim-abc", "sim-xyz"}, sims)
}

func TestRedisRegistry_UntrackSession_CleansSimulation(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))

	// Untrack both sessions
	require.NoError(t, reg.UntrackSession(ctx, "sess-1"))
	require.NoError(t, reg.UntrackSession(ctx, "sess-2"))

	// FindSimulation should return empty for untracked sessions
	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)
}

func TestRedisRegistry_FindSimulation_NotTracked(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Unknown session should return empty string, not an error
	simID, err := reg.FindSimulation(ctx, "nonexistent")
	require.NoError(t, err)
	assert.Empty(t, simID)
}

func TestRedisRegistry_BackwardCompatNoSimulationID(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	// Track without simulation ID (backward compat)
	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", ""))

	// Agent type tracking should work as before
	agentType, ok, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.True(t, ok)
	assert.Equal(t, "runner_autopilot", agentType)

	// FindSimulation should return empty
	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)

	// ListSimulations should be empty
	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Empty(t, sims)
}

func TestRedisRegistry_Flush_ClearsSimulationData(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))

	_, err := reg.Flush(ctx)
	require.NoError(t, err)

	// Simulation data should be cleared
	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Empty(t, sims)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)
}

func TestRedisRegistry_SessionTTL_IsTenMinutes(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 2*time.Hour)

	require.NoError(t, reg.TrackSession(ctx, "ttl-sess-1", "runner_autopilot", ""))

	// Verify the session key has a TTL close to 2 hours
	ttl := s.TTL("test:session:ttl-sess-1")
	assert.Greater(t, ttl, 119*time.Minute, "TTL should be close to 2 hours")
	assert.LessOrEqual(t, ttl, 2*time.Hour, "TTL should not exceed 2 hours")
}

func TestRedisRegistry_BatchTrackSessions_WithSimulationID(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx := context.Background()
	reg := NewRedisSessionRegistry(client, "test", 1*time.Hour)

	entries := []SessionTrackingEntry{
		{SessionID: "sess-1", AgentType: "runner_autopilot", SimulationID: "sim-abc"},
		{SessionID: "sess-2", AgentType: "simulator", SimulationID: "sim-abc"},
		{SessionID: "sess-3", AgentType: "runner_autopilot", SimulationID: "sim-xyz"},
	}
	err := reg.BatchTrackSessions(ctx, entries)
	require.NoError(t, err)

	// All sessions should have correct simulation IDs
	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Equal(t, "sim-abc", simID)

	simID, err = reg.FindSimulation(ctx, "sess-3")
	require.NoError(t, err)
	assert.Equal(t, "sim-xyz", simID)

	// Both simulations should be listed
	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Len(t, sims, 2)
	assert.ElementsMatch(t, []string{"sim-abc", "sim-xyz"}, sims)
}
