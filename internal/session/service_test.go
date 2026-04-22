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

package session

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestInMemorySessionService_AgentTypeTracking(t *testing.T) {
	ctx := context.Background()
	service := NewInMemorySessionService()

	t.Run("TrackSession_and_FindAgentType", func(t *testing.T) {
		err := service.TrackSession(ctx, "sess_1", "runner_autopilot", "")
		assert.NoError(t, err)

		agentType, found, err := service.FindAgentType(ctx, "sess_1")
		assert.NoError(t, err)
		assert.True(t, found)
		assert.Equal(t, "runner_autopilot", agentType)
	})

	t.Run("FindAgentType_missing", func(t *testing.T) {
		_, found, err := service.FindAgentType(ctx, "nonexistent")
		assert.NoError(t, err)
		assert.False(t, found)
	})

	t.Run("UntrackSession", func(t *testing.T) {
		_ = service.TrackSession(ctx, "sess_del", "simulator", "")
		err := service.UntrackSession(ctx, "sess_del")
		assert.NoError(t, err)

		_, found, _ := service.FindAgentType(ctx, "sess_del")
		assert.False(t, found)
	})

	t.Run("ListSessions", func(t *testing.T) {
		svc := NewInMemorySessionService()
		_ = svc.TrackSession(ctx, "s1", "runner_autopilot", "")
		_ = svc.TrackSession(ctx, "s2", "simulator", "")

		sessions, err := svc.ListSessions(ctx)
		assert.NoError(t, err)
		assert.Len(t, sessions, 2)
		assert.ElementsMatch(t, []string{"s1", "s2"}, sessions)
	})

	t.Run("Flush_clears_everything", func(t *testing.T) {
		svc := NewInMemorySessionService()
		_ = svc.TrackSession(ctx, "sess_a", "runner_autopilot", "sim-1")

		_, err := svc.Flush(ctx)
		assert.NoError(t, err)

		_, found, _ := svc.FindAgentType(ctx, "sess_a")
		assert.False(t, found)

		sessions, _ := svc.ListSessions(ctx)
		assert.Empty(t, sessions)

		sims, _ := svc.ListSimulations(ctx)
		assert.Empty(t, sims)
	})
}

func TestTrackSessionWithSimulationID(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	err := reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc")
	require.NoError(t, err)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Equal(t, "sim-abc", simID)
}

func TestListSimulations(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-3", "runner_autopilot", "sim-xyz"))

	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Len(t, sims, 2)
	assert.ElementsMatch(t, []string{"sim-abc", "sim-xyz"}, sims)
}

func TestUntrackSessionCleansSimulation(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))

	require.NoError(t, reg.UntrackSession(ctx, "sess-1"))
	require.NoError(t, reg.UntrackSession(ctx, "sess-2"))

	// Simulation entry removed when last session untracked
	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Empty(t, sims)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)
}

func TestTrackSessionWithoutSimulationID(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	err := reg.TrackSession(ctx, "sess-1", "runner_autopilot", "")
	require.NoError(t, err)

	agentType, found, err := reg.FindAgentType(ctx, "sess-1")
	require.NoError(t, err)
	assert.True(t, found)
	assert.Equal(t, "runner_autopilot", agentType)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)

	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Empty(t, sims)
}

func TestFlushClearsSimulationData(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	require.NoError(t, reg.TrackSession(ctx, "sess-1", "runner_autopilot", "sim-abc"))
	require.NoError(t, reg.TrackSession(ctx, "sess-2", "simulator", "sim-abc"))

	_, err := reg.Flush(ctx)
	require.NoError(t, err)

	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Empty(t, sims)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Empty(t, simID)
}

func TestBatchTrackSessionsWithSimulationID(t *testing.T) {
	ctx := context.Background()
	reg := NewInMemorySessionService()

	entries := []SessionTrackingEntry{
		{SessionID: "sess-1", AgentType: "runner_autopilot", SimulationID: "sim-abc"},
		{SessionID: "sess-2", AgentType: "simulator", SimulationID: "sim-abc"},
		{SessionID: "sess-3", AgentType: "runner_autopilot", SimulationID: "sim-xyz"},
	}
	err := reg.BatchTrackSessions(ctx, entries)
	require.NoError(t, err)

	simID, err := reg.FindSimulation(ctx, "sess-1")
	require.NoError(t, err)
	assert.Equal(t, "sim-abc", simID)

	simID, err = reg.FindSimulation(ctx, "sess-3")
	require.NoError(t, err)
	assert.Equal(t, "sim-xyz", simID)

	sims, err := reg.ListSimulations(ctx)
	require.NoError(t, err)
	assert.Len(t, sims, 2)
	assert.ElementsMatch(t, []string{"sim-abc", "sim-xyz"}, sims)
}
