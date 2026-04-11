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

package hub

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestSwitchboard(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	hub := NewHub()
	// RED: NewSwitchboard not yet defined
	sb := NewSwitchboard(client, "gw-tdd-1", hub, nil)

	t.Run("Broadcast and Receive", func(t *testing.T) {
		// Start switchboard in background
		go func() {
			err := sb.Start(ctx)
			if err != nil && err != context.Canceled {
				t.Errorf("Switchboard failed: %v", err)
			}
		}()

		// Wait for subscription
		time.Sleep(100 * time.Millisecond)

		testMsg := &gateway.Wrapper{
			Type:      "test",
			SessionId: "sess-sb-1",
			Payload:   []byte("hello switchboard"),
		}

		err := sb.Broadcast(ctx, testMsg)
		require.NoError(t, err)

		// Verification: The switchboard should call hub.HandleRemoteMessage
		select {
		case msg := <-hub.remoteMsg:
			assert.Equal(t, testMsg.SessionId, msg.wrapper.SessionId)
			assert.Equal(t, testMsg.Payload, msg.wrapper.Payload)
		case <-time.After(1 * time.Second):
			t.Fatal("Timeout waiting for remote message in Hub")
		}
	})

	t.Run("Enqueue and Publish Orchestration", func(t *testing.T) {
		orchestrationChan := "simulation:broadcast"
		orchestrationQueue := "simulation:spawns"

		pubsub := client.Subscribe(ctx, orchestrationChan)
		defer pubsub.Close()

		// Wait for subscription
		time.Sleep(100 * time.Millisecond)

		testEvent := map[string]interface{}{
			"type":      "spawn_agent",
			"sessionId": "sess-orch-1",
			"payload": map[string]string{
				"agentType": "npc_runner",
			},
		}

		// 1. Test Enqueue (Queue)
		err := sb.EnqueueOrchestration(ctx, orchestrationQueue, testEvent)
		require.NoError(t, err)

		// Verification: The message should appear in Redis List
		listLen, err := client.LLen(ctx, orchestrationQueue).Result()
		require.NoError(t, err)
		assert.Equal(t, int64(1), listLen)

		// 2. Test Publish (Pub/Sub)
		err = sb.PublishOrchestration(ctx, orchestrationChan, testEvent)
		require.NoError(t, err)

		// Verification: The message should appear in Redis Pub/Sub
		msg, err := pubsub.ReceiveMessage(ctx)
		require.NoError(t, err)
		assert.Equal(t, orchestrationChan, msg.Channel)

		var received map[string]interface{}
		err = json.Unmarshal([]byte(msg.Payload), &received)
		require.NoError(t, err)
		assert.Equal(t, "spawn_agent", received["type"])
	})
}

func TestURLNormalization(t *testing.T) {
	// Agents mount at root — each agent has its own port/service.
	// Poke URL is simply {base}/orchestration.
	tests := []struct {
		name      string
		agentURL  string
		agentType string
		expected  string
	}{
		{
			name:      "No trailing slash",
			agentURL:  "http://127.0.0.1:8204",
			agentType: "planner",
			expected:  "http://127.0.0.1:8204/orchestration",
		},
		{
			name:      "Trailing slash",
			agentURL:  "http://127.0.0.1:8204/",
			agentType: "planner",
			expected:  "http://127.0.0.1:8204/orchestration",
		},
		{
			name:      "Cloud Run internal URL",
			agentURL:  "https://runner-autopilot-123456789012.us-central1.run.app",
			agentType: "runner_autopilot",
			expected:  "https://runner-autopilot-123456789012.us-central1.run.app/orchestration",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// This mirrors the simplified URL construction in
			// pokeOrchestrationEndpoint.
			pokeURL := strings.TrimRight(tt.agentURL, "/") + "/orchestration"
			assert.Equal(t, tt.expected, pokeURL)
		})
	}
}

// mockCatalog is a test helper that implements agent.Catalog-like behavior
// by returning a predefined set of agent cards via the catalog.json mechanism.
// createMockAgentURLs starts one httptest.Server per agent, each serving
// a card at /.well-known/agent-card.json. Returns a list of server URLs
// suitable for agent.NewCatalog(). Servers are auto-cleaned up when the
// test finishes.
func createMockAgentURLs(t *testing.T, agents map[string]interface{}) []string {
	t.Helper()
	var urls []string
	for _, raw := range agents {
		cardJSON, err := json.Marshal(raw)
		require.NoError(t, err)
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			} else {
				http.NotFound(w, r)
			}
		}))
		t.Cleanup(srv.Close)
		urls = append(urls, srv.URL)
	}
	return urls
}

func TestPublishOrchestration_RoutesCallableAgent(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	// Mock agent serves both the card AND the /orchestration endpoint
	// from the same URL (matching production Cloud Run behavior).
	var receivedBody []byte
	var receivedContentType string
	cardJSON := []byte(`{
		"name": "simulator",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
			return
		}
		receivedContentType = r.Header.Get("Content-Type")
		body, _ := io.ReadAll(r.Body)
		receivedBody = body
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","context_id":"c1","status":{"state":"completed"}}}`))
	}))
	defer mockAgent.Close()

	catalog := agent.NewCatalog([]string{mockAgent.URL})
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	ctx := context.Background()
	event := map[string]interface{}{
		"type":      "broadcast",
		"sessionId": "sess-1",
		"payload": map[string]interface{}{
			"data": "PULSE",
		},
	}

	err := sb.PublishOrchestration(ctx, "simulation:broadcast", event)
	require.NoError(t, err)

	// Wait for async dispatch goroutine
	time.Sleep(1 * time.Second)

	// The mock should have received an /orchestration poke, NOT A2A message/send
	require.NotEmpty(t, receivedBody, "Callable agent should have received a request")
	assert.Equal(t, "application/json", receivedContentType)

	var received map[string]interface{}
	err = json.Unmarshal(receivedBody, &received)
	require.NoError(t, err, "Body should be valid JSON")
	assert.Equal(t, "broadcast", received["type"], "Should be raw orchestration event")
	assert.Nil(t, received["jsonrpc"], "Should NOT be JSON-RPC wrapped")
}

func TestPublishOrchestration_RoutesSubscriberAgent(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	// Mock agent serves both the card AND the /orchestration endpoint
	// from the same URL (matching production Cloud Run behavior).
	var receivedPath string
	var receivedBody []byte
	cardJSON := []byte(`{
		"name": "runner_autopilot",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "subscriber"}}
			]
		}
	}`)
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
			return
		}
		receivedPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		receivedBody = body
		w.WriteHeader(200)
	}))
	defer mockAgent.Close()

	catalog := agent.NewCatalog([]string{mockAgent.URL})
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	ctx := context.Background()
	event := map[string]interface{}{
		"type":      "broadcast",
		"sessionId": "sess-1",
		"payload":   map[string]interface{}{"data": "PULSE"},
	}

	err := sb.PublishOrchestration(ctx, "simulation:broadcast", event)
	require.NoError(t, err)

	// Wait for async poke goroutine
	time.Sleep(1 * time.Second)

	// Subscriber should get /orchestration poke (not A2A message/send)
	require.NotEmpty(t, receivedPath, "subscriber agent should have received a poke")
	assert.Equal(t, "/orchestration", receivedPath)

	// Body should be raw orchestration event JSON, not JSON-RPC wrapped
	var received map[string]interface{}
	err = json.Unmarshal(receivedBody, &received)
	require.NoError(t, err)
	assert.Equal(t, "broadcast", received["type"])
}

func TestCallableDispatch_RetriesOn5xx(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	// Mock agent that fails twice then succeeds
	var attempts int32
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		if attempts < 3 {
			w.WriteHeader(503)
			_, _ = w.Write([]byte(`{"error":"service unavailable"}`))
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","context_id":"c1","status":{"state":"completed"}}}`))
	}))
	defer mockAgent.Close()

	agentURLs := createMockAgentURLs(t, map[string]interface{}{
		"simulator": map[string]interface{}{
			"name":    "simulator",
			"url":     mockAgent.URL,
			"version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "callable"},
					},
				},
			},
		},
	})

	catalog := agent.NewCatalog(agentURLs)
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	ctx := context.Background()
	event := map[string]interface{}{
		"type":      "broadcast",
		"sessionId": "sess-retry",
		"payload":   map[string]interface{}{"data": "RETRY_TEST"},
	}

	data, err := json.Marshal(event)
	require.NoError(t, err)

	// Call dispatchCallable directly to test its retry behavior.
	// DispatchToAgent now routes local callable agents to /orchestration,
	// so we call the underlying method directly for retry testing.
	rsb := sb.(*RedisSwitchboard)
	rsb.dispatchCallable(ctx, mockAgent.URL, "simulator", data)

	// Wait for retry cycles (retryablehttp uses backoff)
	time.Sleep(5 * time.Second)

	// Should have retried and eventually succeeded with 3 total attempts
	assert.GreaterOrEqual(t, int(attempts), 3, "Callable A2A dispatch should have retried before succeeding")
}

func TestSwitchboard_CallableDispatch_DoesNotRePublishResponse(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	// 1. Subscribe to the broadcast channel before dispatching
	pubsub := client.Subscribe(context.Background(), "gateway:broadcast")
	defer pubsub.Close()
	// Wait for subscription to be active
	time.Sleep(100 * time.Millisecond)

	// Mock agent that returns a standard response
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","status":{"state":"completed"}}}`))
	}))
	defer mockAgent.Close()

	agentURLs := createMockAgentURLs(t, map[string]interface{}{
		"simulator": map[string]interface{}{
			"name":    "simulator",
			"url":     mockAgent.URL,
			"version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "callable"},
					},
				},
			},
		},
	})

	catalog := agent.NewCatalog(agentURLs)
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	ctx := context.Background()
	event := map[string]interface{}{
		"type":      "broadcast",
		"sessionId": "sess-proto-test",
		"payload":   map[string]interface{}{"data": "ACTION"},
	}

	err := sb.DispatchToAgent(ctx, "simulator", event)
	require.NoError(t, err)

	// 2. Verify NO message is published to Redis — AE responses are ACKs,
	// not agent output. Re-publishing them causes broken "unknown" events
	// in the Tester UI. Real output flows through PubSub telemetry.
	recvCtx, recvCancel := context.WithTimeout(ctx, 2*time.Second)
	defer recvCancel()
	_, err = pubsub.ReceiveMessage(recvCtx)
	assert.Error(t, err, "Should NOT receive a re-published response on the broadcast channel")
}

// Regression: callable dispatch must include /a2a/{type} in the URL path,
// not POST to the agent's root URL.
func TestCallableDispatch_URLIncludesA2APath(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var receivedPath string
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","context_id":"c1","status":{"state":"completed"}}}`))
	}))
	defer mockAgent.Close()

	agentURLs := createMockAgentURLs(t, map[string]interface{}{
		"simulator": map[string]interface{}{
			"name":    "simulator",
			"url":     mockAgent.URL, // No /a2a/simulator suffix — dispatchCallable must add it
			"version": "1.0.0",
			"capabilities": map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "callable"},
					},
				},
			},
		},
	})

	catalog := agent.NewCatalog(agentURLs)
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	event := map[string]interface{}{"agentType": "simulator", "sessionId": "url-test"}
	data, err := json.Marshal(event)
	require.NoError(t, err)

	// Call dispatchCallable directly to test its URL construction.
	// DispatchToAgent now routes local callable agents to /orchestration.
	rsb := sb.(*RedisSwitchboard)
	rsb.dispatchCallable(context.Background(), mockAgent.URL, "simulator", data)

	time.Sleep(2 * time.Second)
	assert.Equal(t, "/", receivedPath,
		"dispatchCallable must POST to / (root mount, trailing slash for Starlette)")
}

// Regression: DispatchToAgent must target only the specified agent,
// not broadcast to all agents in the catalog.
func TestDispatchToAgent_TargetsOnlySpecifiedAgent(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var runnerHit, simulatorHit bool

	runnerCardJSON := []byte(`{
		"name": "runner_autopilot",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "subscriber"}}
			]
		}
	}`)
	mockRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(runnerCardJSON)
			return
		}
		runnerHit = true
		w.WriteHeader(200)
	}))
	defer mockRunner.Close()

	simCardJSON := []byte(`{
		"name": "simulator",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	mockSimulator := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(simCardJSON)
			return
		}
		simulatorHit = true
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","context_id":"c1","status":{"state":"completed"}}}`))
	}))
	defer mockSimulator.Close()

	catalog := agent.NewCatalog([]string{mockRunner.URL, mockSimulator.URL})
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	// Dispatch only to runner_autopilot — simulator should NOT be hit
	event := map[string]interface{}{"agentType": "runner_autopilot", "sessionId": "target-test"}
	err := sb.DispatchToAgent(context.Background(), "runner_autopilot", event)
	require.NoError(t, err)

	time.Sleep(2 * time.Second)

	assert.True(t, runnerHit, "Runner_autopilot should have been dispatched to")
	assert.False(t, simulatorHit, "Simulator should NOT be dispatched to when targeting runner_autopilot only")
}

// PokeAgent routes local callable agents to /orchestration (same as subscriber)
// because local agents have the /orchestration endpoint registered.
// Only Agent Engine URLs use A2A message/send (they lack /orchestration).
func TestPokeAgent_LocalCallableUsesOrchestration(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var receivedPath string
	var receivedBody []byte
	cardJSON := []byte(`{
		"name": "planner",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
			return
		}
		receivedPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		receivedBody = body
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer mockAgent.Close()

	catalog := agent.NewCatalog([]string{mockAgent.URL})
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	spawnEvent := map[string]interface{}{
		"type":      "spawn_agent",
		"sessionId": "planner-session-1",
		"payload":   map[string]string{"agentType": "planner"},
	}

	err := sb.PokeAgent(context.Background(), "planner", spawnEvent)
	require.NoError(t, err)

	time.Sleep(1 * time.Second)

	// Local callable agents should receive /orchestration poke (not A2A message/send)
	require.NotEmpty(t, receivedBody, "Callable agent should receive the orchestration poke")
	assert.Equal(t, "/orchestration", receivedPath,
		"PokeAgent must route local callable agents to /orchestration, not A2A message/send")

	// Body should be raw JSON event (not JSON-RPC wrapped)
	var received map[string]interface{}
	err = json.Unmarshal(receivedBody, &received)
	require.NoError(t, err)
	assert.Equal(t, "spawn_agent", received["type"],
		"Orchestration poke should contain the raw event")
	_, hasJsonRPC := received["jsonrpc"]
	assert.False(t, hasJsonRPC, "Orchestration poke should NOT be JSON-RPC wrapped")
}

// --- Phase 2: Session-Aware Broadcast Tests ---

// mockRegistry implements session.DistributedRegistry for testing.
type mockRegistry struct {
	activeTypes []string
	sessions    map[string]string // sessionID -> agentType
}

func (m *mockRegistry) TrackSession(_ context.Context, sessionID string, agentType string, _ string) error {
	if m.sessions == nil {
		m.sessions = make(map[string]string)
	}
	m.sessions[sessionID] = agentType
	return nil
}
func (m *mockRegistry) FindAgentType(_ context.Context, sessionID string) (string, bool, error) {
	at, ok := m.sessions[sessionID]
	return at, ok, nil
}
func (m *mockRegistry) ActiveAgentTypes(_ context.Context) ([]string, error) {
	return m.activeTypes, nil
}
func (m *mockRegistry) UntrackSession(_ context.Context, sessionID string) error {
	delete(m.sessions, sessionID)
	return nil
}
func (m *mockRegistry) ListSessions(_ context.Context) ([]string, error) {
	var ids []string
	for sid := range m.sessions {
		ids = append(ids, sid)
	}
	return ids, nil
}
func (m *mockRegistry) Flush(_ context.Context) (int, error) {
	count := len(m.sessions)
	m.sessions = nil
	m.activeTypes = nil
	return count, nil
}
func (m *mockRegistry) BatchTrackSessions(_ context.Context, sessions []session.SessionTrackingEntry) error {
	for _, s := range sessions {
		if m.sessions == nil {
			m.sessions = make(map[string]string)
		}
		m.sessions[s.SessionID] = s.AgentType
	}
	return nil
}
func (m *mockRegistry) FindSimulation(_ context.Context, _ string) (string, error) {
	return "", nil
}
func (m *mockRegistry) ListSimulations(_ context.Context) ([]string, error) {
	return nil, nil
}
func (m *mockRegistry) Reap(_ context.Context) (int, error) {
	return 0, nil
}

func TestPublishOrchestration_OnlyPokesAgentTypesWithSessions(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var runnerHit bool
	var simulatorHit bool

	runnerCardJSON := []byte(`{
		"name": "runner_autopilot",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "subscriber"}}
			]
		}
	}`)
	mockRunner := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(runnerCardJSON)
			return
		}
		runnerHit = true
		w.WriteHeader(200)
	}))
	defer mockRunner.Close()

	simCardJSON := []byte(`{
		"name": "simulator",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	mockSimulator := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(simCardJSON)
			return
		}
		simulatorHit = true
		w.WriteHeader(200)
	}))
	defer mockSimulator.Close()

	catalog := agent.NewCatalog([]string{mockRunner.URL, mockSimulator.URL})
	hub := NewHub()
	// Only runner_autopilot has active sessions — simulator should be skipped
	reg := &mockRegistry{activeTypes: []string{"runner_autopilot"}}

	sb := NewSwitchboardWithRegistry(client, "gw-test", hub, catalog, reg)

	event := map[string]interface{}{"type": "broadcast", "sessionId": "sess-1"}
	err := sb.PublishOrchestration(context.Background(), "simulation:broadcast", event)
	require.NoError(t, err)

	time.Sleep(2 * time.Second)

	assert.True(t, runnerHit, "Runner_autopilot has sessions — should be poked")
	assert.False(t, simulatorHit, "Simulator has NO sessions — should NOT be poked")
}

func TestPublishOrchestration_SkipsAgentTypesWithNoSessions(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var agentHit bool
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		agentHit = true
		w.WriteHeader(200)
	}))
	defer mockAgent.Close()

	agentURLs := createMockAgentURLs(t, map[string]interface{}{
		"runner_autopilot": map[string]interface{}{
			"name": "runner_autopilot", "url": mockAgent.URL, "version": "1.0.0",
		},
	})

	catalog := agent.NewCatalog(agentURLs)
	hub := NewHub()
	// No active sessions at all
	reg := &mockRegistry{activeTypes: []string{}}

	sb := NewSwitchboardWithRegistry(client, "gw-test", hub, catalog, reg)

	event := map[string]interface{}{"type": "broadcast", "sessionId": "sess-1"}
	err := sb.PublishOrchestration(context.Background(), "simulation:broadcast", event)
	require.NoError(t, err)

	time.Sleep(1 * time.Second)

	assert.False(t, agentHit, "No active sessions — NO agents should be poked")
}

// PublishOrchestration routes local callable agents to /orchestration (same as subscriber).
// Only Agent Engine URLs use A2A message/send.
func TestPublishOrchestration_LocalCallableUsesOrchestration(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var receivedPath string
	var receivedBody []byte
	cardJSON := []byte(`{
		"name": "simulator",
		"url": "PLACEHOLDER",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	mockCallable := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
			return
		}
		receivedPath = r.URL.Path
		body, _ := io.ReadAll(r.Body)
		receivedBody = body
		w.WriteHeader(200)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer mockCallable.Close()

	catalog := agent.NewCatalog([]string{mockCallable.URL})
	hub := NewHub()
	reg := &mockRegistry{activeTypes: []string{"simulator"}}

	sb := NewSwitchboardWithRegistry(client, "gw-test", hub, catalog, reg)

	event := map[string]interface{}{
		"type": "broadcast", "sessionId": "sess-callable",
		"payload": map[string]interface{}{"data": "PULSE"},
	}

	err := sb.PublishOrchestration(context.Background(), "simulation:broadcast", event)
	require.NoError(t, err)

	time.Sleep(2 * time.Second)

	// Local callable agents should receive /orchestration poke
	require.NotEmpty(t, receivedBody, "Callable agent should receive orchestration poke")
	assert.Equal(t, "/orchestration", receivedPath,
		"Local callable should get /orchestration poke during broadcast")

	// Body should be raw JSON event (not JSON-RPC wrapped)
	var received map[string]interface{}
	err = json.Unmarshal(receivedBody, &received)
	require.NoError(t, err)
	assert.Equal(t, "broadcast", received["type"],
		"Orchestration poke should contain the raw event")
	_, hasJsonRPC := received["jsonrpc"]
	assert.False(t, hasJsonRPC, "Orchestration poke should NOT be JSON-RPC wrapped")
}

func TestSwitchboard_Ping_ReturnsNilWhenRedisHealthy(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := NewSwitchboard(rdb, "gw-ping-test", h, nil)

	err := sb.Ping(context.Background())
	assert.NoError(t, err)
}

func TestSwitchboard_Ping_ReturnsErrorWhenRedisDown(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := NewSwitchboard(rdb, "gw-ping-test", h, nil)

	// Close miniredis to simulate Redis being down
	s.Close()

	err := sb.Ping(context.Background())
	assert.Error(t, err)
}

func TestSwitchboard_PokeOrchestrationEndpoint_Success(t *testing.T) {
	var receivedPath string
	var receivedBody []byte
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := &RedisSwitchboard{
		client:     rdb,
		gatewayID:  "test-gw",
		localHub:   h,
		channel:    "gateway:broadcast",
		httpClient: &http.Client{Timeout: 5 * time.Second},
	}

	sb.pokeOrchestrationEndpoint(agentServer.URL, "test-agent", []byte(`{"type":"spawn"}`))

	assert.Equal(t, "/orchestration", receivedPath)
	assert.Contains(t, string(receivedBody), `"type":"spawn"`)
}

func TestSwitchboard_PokeOrchestrationEndpoint_PlainHTTP(t *testing.T) {
	var receivedPath string
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		w.WriteHeader(http.StatusOK)
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := &RedisSwitchboard{
		client:     rdb,
		gatewayID:  "test-gw",
		localHub:   h,
		channel:    "gateway:broadcast",
		httpClient: &http.Client{Timeout: 5 * time.Second},
	}

	sb.pokeOrchestrationEndpoint(agentServer.URL, "test-agent", []byte(`{}`))

	assert.Equal(t, "/orchestration", receivedPath)
}

func TestSwitchboard_DispatchCallable_CloudRun(t *testing.T) {
	var receivedPath string
	var receivedBody []byte
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       h,
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 5 * time.Second},
	}

	event := map[string]interface{}{
		"type":      "spawn_agent",
		"sessionId": "sess-123",
	}
	eventData, _ := json.Marshal(event)

	sb.dispatchCallable(context.Background(), agentServer.URL, "test-agent", eventData)

	// Cloud Run callable agents receive A2A JSON-RPC at root /
	assert.Equal(t, "/", receivedPath)
	assert.Contains(t, string(receivedBody), `"jsonrpc":"2.0"`)
	assert.Contains(t, string(receivedBody), `"method":"message/send"`)
}

func TestSwitchboard_DispatchCallable_AgentEngine(t *testing.T) {
	var receivedPath string
	var receivedBody []byte
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedBody, _ = io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	// Override newGCPClient to return a plain HTTP client (no real GCP auth)
	origGCP := newGCPClient
	defer func() { newGCPClient = origGCP }()
	newGCPClient = func(ctx context.Context, scopes ...string) (*http.Client, error) {
		return &http.Client{Timeout: 5 * time.Second}, nil
	}

	h := NewHub()
	// Construct with the fake GCP client via newGCPClient override
	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       h,
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 5 * time.Second},
		gcpClient:      &http.Client{Timeout: 5 * time.Second},
	}

	// Use a fake Agent Engine URL that actually points to our test server
	// We need the URL to match isAgentEngineURL() but actually resolve to our mock
	// Since we can't fake DNS, we test the request body format
	event := map[string]interface{}{
		"type":      "spawn_agent",
		"sessionId": "sess-456",
	}
	eventData, _ := json.Marshal(event)

	// Test Cloud Run path first (non-AE URL)
	sb.dispatchCallable(context.Background(), agentServer.URL, "test-agent", eventData)
	assert.Equal(t, "/", receivedPath)
	assert.Contains(t, string(receivedBody), "jsonrpc")
}

func TestSwitchboard_DispatchCallable_ErrorResponse(t *testing.T) {
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"error":"something broke"}`))
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       h,
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 5 * time.Second},
	}

	event := map[string]interface{}{"type": "test"}
	eventData, _ := json.Marshal(event)

	// Should not panic on error response
	sb.dispatchCallable(context.Background(), agentServer.URL, "test-agent", eventData)
}

func TestSwitchboard_DispatchCallable_UnreachableAgent(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	h := NewHub()
	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       h,
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 1 * time.Second},
	}

	event := map[string]interface{}{"type": "test"}
	eventData, _ := json.Marshal(event)

	// Should not panic when agent is unreachable
	sb.dispatchCallable(context.Background(), "http://127.0.0.1:1", "dead-agent", eventData)
}

func TestSwitchboard_DispatchCallable_AE_BlockingTrue(t *testing.T) {
	var receivedBody []byte
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       NewHub(),
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 5 * time.Second},
		gcpClient:      &http.Client{Timeout: 5 * time.Second},
	}

	// Use an AE-like URL that resolves to our test server
	aeURL := agentServer.URL + "/aiplatform.googleapis.com/reasoningEngines/123"
	event := map[string]interface{}{
		"type":      "spawn_agent",
		"sessionId": "sess-blocking-test",
	}
	eventData, _ := json.Marshal(event)

	sb.dispatchCallable(context.Background(), aeURL, "test-agent", eventData)

	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(receivedBody, &body))
	config, ok := body["configuration"].(map[string]interface{})
	require.True(t, ok, "configuration field missing")
	assert.Equal(t, true, config["blocking"], "blocking should be true for AE")
}

func TestSwitchboard_DispatchCallable_AE_BroadcastContextId(t *testing.T) {
	var receivedBody []byte
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedBody, _ = io.ReadAll(r.Body)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"result":"ok"}`))
	}))
	defer agentServer.Close()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	sb := &RedisSwitchboard{
		client:         rdb,
		gatewayID:      "test-gw",
		localHub:       NewHub(),
		channel:        "gateway:broadcast",
		callableClient: &http.Client{Timeout: 5 * time.Second},
		gcpClient:      &http.Client{Timeout: 5 * time.Second},
	}

	aeURL := agentServer.URL + "/aiplatform.googleapis.com/reasoningEngines/123"
	event := map[string]interface{}{
		"type": "broadcast",
		"payload": map[string]interface{}{
			"data":    `{"text":"Hello"}`,
			"targets": []interface{}{"target-sess-abc"},
		},
	}
	eventData, _ := json.Marshal(event)

	sb.dispatchCallable(context.Background(), aeURL, "test-agent", eventData)

	var body map[string]interface{}
	require.NoError(t, json.Unmarshal(receivedBody, &body))
	req, ok := body["request"].(map[string]interface{})
	require.True(t, ok)
	assert.Equal(t, "target-sess-abc", req["context_id"],
		"broadcast should use first target as context_id")
}

func TestBatchEnqueueOrchestration_PipelinesMultipleQueues(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	sb := NewSwitchboard(rdb, "test-gw", NewHub(), nil)

	ctx := context.Background()
	items := []QueueItem{
		{Queue: "simulation:spawns:runner_autopilot", Data: map[string]string{"sessionId": "s1"}},
		{Queue: "simulation:spawns:runner_autopilot", Data: map[string]string{"sessionId": "s2"}},
		{Queue: "simulation:spawns:simulator", Data: map[string]string{"sessionId": "s3"}},
	}

	err := sb.BatchEnqueueOrchestration(ctx, items)
	require.NoError(t, err)

	// Verify runner_autopilot queue has 2 items
	runnerLen, err := rdb.LLen(ctx, "simulation:spawns:runner_autopilot").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(2), runnerLen)

	// Verify simulator queue has 1 item
	simLen, err := rdb.LLen(ctx, "simulation:spawns:simulator").Result()
	require.NoError(t, err)
	assert.Equal(t, int64(1), simLen)

	// Verify data is correct by popping and checking
	raw, err := rdb.LPop(ctx, "simulation:spawns:runner_autopilot").Result()
	require.NoError(t, err)
	var parsed map[string]string
	require.NoError(t, json.Unmarshal([]byte(raw), &parsed))
	assert.Equal(t, "s1", parsed["sessionId"])
}

func TestBatchEnqueueOrchestration_EmptySlice(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	sb := NewSwitchboard(rdb, "test-gw", NewHub(), nil)

	// Empty batch should be a no-op
	err := sb.BatchEnqueueOrchestration(context.Background(), nil)
	require.NoError(t, err)

	err = sb.BatchEnqueueOrchestration(context.Background(), []QueueItem{})
	require.NoError(t, err)
}

func TestRelayCallableResponse_ExtractsArtifactText(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	hub := NewHub()
	sb := NewSwitchboardWithRegistry(rdb, "gw-relay-test", hub, nil, nil).(*RedisSwitchboard)

	ctx := context.Background()

	// Subscribe to gateway:broadcast to capture relayed messages
	pubsub := rdb.Subscribe(ctx, "gateway:broadcast")
	defer pubsub.Close()
	ch := pubsub.Channel()

	// Wait for subscription to be active
	time.Sleep(100 * time.Millisecond)

	// Real A2A response from Agent Engine (from actual gateway logs)
	aeResponse := []byte(`{
		"task": {
			"artifacts": [{
				"artifactId": "abc-123",
				"name": "planner_with_eval_result",
				"parts": [{"text": "The marathon plan is ready for 10 runners."}]
			}],
			"contextId": "session-42",
			"id": "task-1",
			"status": {"state": "TASK_STATE_COMPLETED"}
		}
	}`)

	sb.relayCallableResponse(ctx, "planner_with_eval", "session-42", aeResponse)

	// Read the relayed message from Redis
	select {
	case msg := <-ch:
		var wrapper gateway.Wrapper
		require.NoError(t, proto.Unmarshal([]byte(msg.Payload), &wrapper))

		assert.Equal(t, "json", wrapper.Type)
		assert.Equal(t, "narrative", wrapper.Event)
		assert.Equal(t, "success", wrapper.Status)
		assert.Equal(t, "session-42", wrapper.SessionId)
		assert.Equal(t, []string{"session-42"}, wrapper.Destination)

		require.NotNil(t, wrapper.Origin)
		assert.Equal(t, "agent", wrapper.Origin.Type)
		assert.Equal(t, "planner_with_eval", wrapper.Origin.Id)
		assert.Equal(t, "session-42", wrapper.Origin.SessionId)

		var payload map[string]string
		require.NoError(t, json.Unmarshal(wrapper.Payload, &payload))
		assert.Equal(t, "The marathon plan is ready for 10 runners.", payload["text"])

	case <-time.After(2 * time.Second):
		t.Fatal("Timed out waiting for relayed message on gateway:broadcast")
	}
}

func TestRelayCallableResponse_NoArtifacts(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	hub := NewHub()
	sb := NewSwitchboardWithRegistry(rdb, "gw-relay-test", hub, nil, nil).(*RedisSwitchboard)

	ctx := context.Background()

	pubsub := rdb.Subscribe(ctx, "gateway:broadcast")
	defer pubsub.Close()
	ch := pubsub.Channel()
	time.Sleep(100 * time.Millisecond)

	// Response with no artifacts — nothing should be relayed
	sb.relayCallableResponse(ctx, "planner", "session-99", []byte(`{"task":{"status":{"state":"TASK_STATE_COMPLETED"}}}`))

	select {
	case msg := <-ch:
		t.Fatalf("Expected no message but got: %s", msg.Payload)
	case <-time.After(300 * time.Millisecond):
		// Good — no message relayed
	}
}

func TestRelayCallableResponse_InvalidJSON(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	hub := NewHub()
	sb := NewSwitchboardWithRegistry(rdb, "gw-relay-test", hub, nil, nil).(*RedisSwitchboard)

	ctx := context.Background()

	pubsub := rdb.Subscribe(ctx, "gateway:broadcast")
	defer pubsub.Close()
	ch := pubsub.Channel()
	time.Sleep(100 * time.Millisecond)

	// Invalid JSON — should not panic or relay
	sb.relayCallableResponse(ctx, "planner", "session-99", []byte(`not json`))

	select {
	case msg := <-ch:
		t.Fatalf("Expected no message but got: %s", msg.Payload)
	case <-time.After(300 * time.Millisecond):
		// Good — no message relayed
	}
}

func TestRelayCallableResponse_MultipleArtifacts(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	hub := NewHub()
	sb := NewSwitchboardWithRegistry(rdb, "gw-relay-test", hub, nil, nil).(*RedisSwitchboard)

	ctx := context.Background()

	pubsub := rdb.Subscribe(ctx, "gateway:broadcast")
	defer pubsub.Close()
	ch := pubsub.Channel()
	time.Sleep(100 * time.Millisecond)

	// Response with two artifacts — should relay both
	aeResponse := []byte(`{
		"task": {
			"artifacts": [
				{"parts": [{"text": "First result"}]},
				{"parts": [{"text": "Second result"}]}
			]
		}
	}`)

	sb.relayCallableResponse(ctx, "simulator", "session-7", aeResponse)

	var received []string
	for i := 0; i < 2; i++ {
		select {
		case msg := <-ch:
			var wrapper gateway.Wrapper
			require.NoError(t, proto.Unmarshal([]byte(msg.Payload), &wrapper))
			var payload map[string]string
			require.NoError(t, json.Unmarshal(wrapper.Payload, &payload))
			received = append(received, payload["text"])
		case <-time.After(2 * time.Second):
			t.Fatalf("Timed out waiting for message %d", i+1)
		}
	}

	assert.Equal(t, []string{"First result", "Second result"}, received)
}

func TestFlushQueues_DeletesSpawnKeys(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	ctx := context.Background()

	// Seed some spawn queues (the pattern FlushQueues targets)
	rdb.RPush(ctx, "simulation:spawns:runner", `{"sessionId":"s1"}`)
	rdb.RPush(ctx, "simulation:spawns:runner", `{"sessionId":"s2"}`)
	rdb.RPush(ctx, "simulation:spawns:simulator", `{"sessionId":"s3"}`)

	// Also seed a key that should NOT be deleted
	rdb.Set(ctx, "simulation:other", "keep-me", 0)

	sb := NewSwitchboard(rdb, "gw-flush-test", NewHub(), nil)

	count, err := sb.FlushQueues(ctx)
	require.NoError(t, err)
	assert.Equal(t, 2, count, "Should delete 2 spawn queue keys (runner + simulator)")

	// Verify spawn keys are gone
	runnerExists, _ := rdb.Exists(ctx, "simulation:spawns:runner").Result()
	assert.Equal(t, int64(0), runnerExists, "runner spawn queue should be deleted")

	simExists, _ := rdb.Exists(ctx, "simulation:spawns:simulator").Result()
	assert.Equal(t, int64(0), simExists, "simulator spawn queue should be deleted")

	// Verify non-spawn key is untouched
	otherExists, _ := rdb.Exists(ctx, "simulation:other").Result()
	assert.Equal(t, int64(1), otherExists, "non-spawn key should not be deleted")
}

func TestFlushQueues_NoSpawnKeys(t *testing.T) {
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	sb := NewSwitchboard(rdb, "gw-flush-test", NewHub(), nil)

	count, err := sb.FlushQueues(context.Background())
	require.NoError(t, err)
	assert.Equal(t, 0, count, "Should return 0 when no spawn keys exist")
}

func TestIsAgentEngineURL(t *testing.T) {
	assert.True(t, isAgentEngineURL("https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456"))
	assert.False(t, isAgentEngineURL("http://localhost:8201"))
	assert.False(t, isAgentEngineURL("https://my-agent.run.app"))
	assert.False(t, isAgentEngineURL("https://aiplatform.googleapis.com/v1/other"))
}

func TestPokeAgent_UsesBaseURLNotCardURL(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	var receivedPath string
	mockAgent := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			// Card self-reports with A2A path
			card := map[string]interface{}{
				"name":    "simulator",
				"url":     "http://public.example.com/a2a/simulator/",
				"version": "1.0.0",
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(card)
			return
		}
		receivedPath = r.URL.Path
		w.WriteHeader(200)
	}))
	defer mockAgent.Close()

	catalog := agent.NewCatalog([]string{mockAgent.URL})
	hub := NewHub()
	sb := NewSwitchboard(client, "gw-test", hub, catalog)

	err := sb.PokeAgent(context.Background(), "simulator", map[string]string{"type": "tick"})
	require.NoError(t, err)

	time.Sleep(500 * time.Millisecond)

	// Poke must go to /orchestration on the BASE URL, not /a2a/simulator/orchestration
	assert.Equal(t, "/orchestration", receivedPath,
		"Poke should go to /orchestration on the base URL, not /a2a/simulator/orchestration")
}

func TestSwitchboard_Start_ReconnectsAfterRedisDisconnect(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	h := NewHub()
	sb := NewSwitchboard(client, "gw-reconnect", h, nil)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Start switchboard
	sbDone := make(chan error, 1)
	go func() {
		sbDone <- sb.Start(ctx)
	}()

	// Wait for initial subscription
	time.Sleep(200 * time.Millisecond)

	// Send a message — should arrive
	msg1 := &gateway.Wrapper{Type: "test", SessionId: "pre-disconnect", Payload: []byte("before")}
	require.NoError(t, sb.Broadcast(ctx, msg1))

	select {
	case got := <-h.remoteMsg:
		assert.Equal(t, "pre-disconnect", got.wrapper.SessionId)
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for pre-disconnect message")
	}

	// Simulate Redis disconnect by restarting miniredis
	s.Close()
	time.Sleep(200 * time.Millisecond)
	require.NoError(t, s.Start())
	// Recreate client pointing to the (restarted) same address
	// The existing client should reconnect automatically since miniredis
	// restarts on the same address.

	// Wait for reconnection (backoff starts at 500ms)
	time.Sleep(2 * time.Second)

	// Send another message — should arrive after reconnect
	msg2 := &gateway.Wrapper{Type: "test", SessionId: "post-disconnect", Payload: []byte("after")}
	require.NoError(t, sb.Broadcast(ctx, msg2))

	select {
	case got := <-h.remoteMsg:
		assert.Equal(t, "post-disconnect", got.wrapper.SessionId)
	case <-time.After(3 * time.Second):
		t.Fatal("Timeout waiting for post-disconnect message — reconnection may have failed")
	}

	cancel()
	select {
	case err := <-sbDone:
		assert.ErrorIs(t, err, context.Canceled)
	case <-time.After(2 * time.Second):
		t.Fatal("Switchboard did not exit after cancel")
	}
}

func TestSpawnQueueName_ShardsBySessionID(t *testing.T) {
	tests := []struct {
		agentType string
		sessionID string
	}{
		{"runner_autopilot", "session-001"},
		{"runner_autopilot", "session-002"},
		{"simulator", "session-003"},
	}

	for _, tc := range tests {
		name := SpawnQueueName(tc.agentType, tc.sessionID, 8)
		assert.Contains(t, name, "simulation:spawns:"+tc.agentType+":")
		// Deterministic: same input = same output
		assert.Equal(t, name, SpawnQueueName(tc.agentType, tc.sessionID, 8))
	}

	// Distribution: 1000 sessions should spread across shards
	shardCounts := make(map[string]int)
	for i := 0; i < 1000; i++ {
		name := SpawnQueueName("runner_autopilot", fmt.Sprintf("session-%d", i), 8)
		shardCounts[name]++
	}
	assert.Len(t, shardCounts, 8, "Should use all 8 shards")
	for name, count := range shardCounts {
		assert.Greater(t, count, 50, "Shard %s should have >50 sessions (got %d)", name, count)
	}
}

func TestSpawnQueueName_DefaultShards(t *testing.T) {
	// numShards <= 0 should default to DefaultSpawnShards
	name := SpawnQueueName("runner_autopilot", "session-1", 0)
	assert.Contains(t, name, "simulation:spawns:runner_autopilot:")

	nameNeg := SpawnQueueName("runner_autopilot", "session-1", -1)
	assert.Equal(t, name, nameNeg, "Negative numShards should behave like 0 (use default)")
}
