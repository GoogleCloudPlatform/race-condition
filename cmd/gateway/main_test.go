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
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestHealthCheck(t *testing.T) {
	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/health", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp map[string]interface{}
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "ok", resp["status"])
	assert.Equal(t, "gateway", resp["service"])
}

func TestAgentTypes(t *testing.T) {
	// Start a mock agent card server
	card := agent.AgentCard{
		Name:        "Test Runner",
		Description: "A test agent",
		Version:     "1.0.0",
		URL:         "http://localhost:9999",
	}
	cardJSON, _ := json.Marshal(card)
	cardServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer cardServer.Close()

	h := hub.NewHub()
	catalog := agent.NewCatalog([]string{cardServer.URL})
	router := setupRouter(h, nil, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/agent-types", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp map[string]agent.AgentCard
	err := json.Unmarshal(w.Body.Bytes(), &resp)
	assert.NoError(t, err)
	assert.Equal(t, "Test Runner", resp["Test Runner"].Name)
}

func TestSessionManagement(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	// Track a dummy session
	err := reg.TrackSession(context.Background(), "session-1", "test-gw", "")
	assert.NoError(t, err)

	router := setupRouter(h, nil, nil, reg, "test-gw", nil, nil)

	// Test List Sessions
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/sessions", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var sessions []string
	err = json.Unmarshal(w.Body.Bytes(), &sessions)
	assert.NoError(t, err)
	assert.Contains(t, sessions, "session-1")

	// Test Flush Sessions
	w = httptest.NewRecorder()
	req, _ = http.NewRequest("POST", "/api/v1/sessions/flush", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	// Verify flushed
	sessions, _ = reg.ListSessions(context.Background())
	assert.Empty(t, sessions)
}

func TestOrchestrationPush(t *testing.T) {
	// 1. Mock Agent Endpoint — serves card AND handles orchestration pokes
	receivedPoke := false
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/agent-card.json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		case r.Method == "POST" && r.URL.Path == "/orchestration":
			receivedPoke = true
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))
	defer agentServer.Close()

	// Update card URL to point to itself
	card.URL = agentServer.URL
	cardJSON, _ = json.Marshal(card)

	h := hub.NewHub()
	catalog := agent.NewCatalog([]string{agentServer.URL})

	// Wire a real switchboard so DispatchToAgent can route the poke.
	mr := miniredis.RunT(t)
	rc := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rc.Close()
	sb := hub.NewSwitchboardWithRegistry(rc, "test-gw", h, catalog, nil)
	router := setupRouter(h, sb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	// 3. Send Push Event
	pushPayload := map[string]interface{}{
		"message": map[string]interface{}{
			"data": []byte(`{"origin": {"id": "runner_autopilot", "type": "agent"}, "session_id": "s1"}`),
		},
	}
	body, _ := json.Marshal(pushPayload)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/orchestration/push", bytes.NewBuffer(body))
	router.ServeHTTP(w, req)

	// Wait for async dispatch
	time.Sleep(1 * time.Second)

	assert.Equal(t, 200, w.Code)
	assert.True(t, receivedPoke)
}

func TestOrchestrationPush_SessionBleed(t *testing.T) {
	// 1. Mock Agent Endpoint
	receivedPoke := false
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/agent-card.json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		case r.Method == "POST" && r.URL.Path == "/orchestration":
			receivedPoke = true
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))
	defer agentServer.Close()

	// Update card URL
	card.URL = agentServer.URL
	cardJSON, _ = json.Marshal(card)

	h := hub.NewHub()
	catalog := agent.NewCatalog([]string{agentServer.URL})

	mr := miniredis.RunT(t)
	rc := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rc.Close()
	sb := hub.NewSwitchboardWithRegistry(rc, "test-gw", h, catalog, nil)
	router := setupRouter(h, sb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	// 3. Send Push Event with a nested payload that has a different sessionID
	// Wrap it in a Wrapper structure like Pub/Sub usually does.
	pushPayload := map[string]interface{}{
		"message": map[string]interface{}{
			"data": []byte(`{
				"session_id": "top-level-session",
				"origin": {
					"id": "runner_autopilot",
					"type": "agent"
				},
				"payload": "eyJzZXNzaW9uSWQiOiAibmVzdGVkLW1hbGljaW91cy1zZXNzaW9uLWlkIn0="
			}`),
		},
	}
	body, _ := json.Marshal(pushPayload)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/orchestration/push", bytes.NewBuffer(body))
	router.ServeHTTP(w, req)

	// Wait for async dispatch
	time.Sleep(1 * time.Second)

	assert.Equal(t, 200, w.Code)
	assert.True(t, receivedPoke)
}

// Spawn is a gateway-only operation: it tracks the session in the registry
// and returns the ID. No message is sent to the agent.
func TestBatchSpawn_TracksSessionOnly(t *testing.T) {
	// 1. Mock Agent Endpoint
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/agent-card.json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		default:
			http.NotFound(w, r)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	// Spawn a single runner_autopilot session
	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 1},
		},
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for async dispatch
	select {
	case <-mockSb.Done:
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for PokeAgent")
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)

	// Spawn uses PokeAgent (/orchestration poke, NOT message/send)
	// and BatchEnqueueOrchestration (Redis pipeline for spawn queues)
	assert.True(t, mockSb.PokeAgentCalled,
		"Spawn must use PokeAgent to notify dispatcher via /orchestration")
	assert.Equal(t, "runner_autopilot", mockSb.PokeAgentType,
		"PokeAgent must target the spawned agent type")
	assert.True(t, mockSb.BatchEnqueueCalled,
		"Spawn must use BatchEnqueueOrchestration (Redis pipeline)")
	assert.Len(t, mockSb.BatchEnqueueItems, 1,
		"Should have 1 queue item for 1 spawned session")
	assert.Contains(t, mockSb.BatchEnqueueItems[0].Queue, "simulation:spawns:runner_autopilot:",
		"Spawn queue must be sharded: simulation:spawns:{agentType}:{shard}")
	assert.False(t, mockSb.PublishOrchestrationCalled,
		"Spawn must NOT use PublishOrchestration (broadcast)")
	assert.False(t, mockSb.DispatchToAgentCalled,
		"Spawn must NOT use DispatchToAgent (A2A JSON-RPC)")
}

// Regression: WebSocket connections must NOT trigger spawn events.
// Spawning is an explicit user action via POST /api/v1/spawn only.
func TestWebSocketConnect_DoesNotSpawn(t *testing.T) {
	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{}
	server := httptest.NewServer(setupRouter(h, mockSb, nil, session.NewInMemorySessionService(), "test-gw", nil, nil))
	defer server.Close()

	// Connect WebSocket with agentType=simulator
	wsURL := "ws" + server.URL[4:] + "/ws?sessionId=test-ws&agentType=simulator"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	assert.NoError(t, err)
	defer ws.Close()

	// Give async goroutines time to fire (if any)
	time.Sleep(500 * time.Millisecond)

	assert.False(t, mockSb.EnqueueCalled,
		"WebSocket connect must NOT enqueue spawn events")
	assert.False(t, mockSb.DispatchToAgentCalled,
		"WebSocket connect must NOT dispatch to agents")
	assert.False(t, mockSb.PublishOrchestrationCalled,
		"WebSocket connect must NOT publish orchestration events")
}

func TestDispatchEvent_NilSwitchboard(t *testing.T) {
	// Should not panic when switchboard is nil
	dispatchEvent(nil, "runner_autopilot", map[string]string{"type": "test"})
}

func TestDispatchEvent_TargetedDispatch(t *testing.T) {
	mockSb := &MockSwitchboard{}
	dispatchEvent(mockSb, "runner_autopilot", map[string]string{"type": "test"})
	assert.True(t, mockSb.DispatchToAgentCalled)
	assert.Equal(t, "runner_autopilot", mockSb.DispatchAgentType)
	assert.False(t, mockSb.PublishOrchestrationCalled)
}

func TestDispatchEvent_BroadcastWhenNoAgentType(t *testing.T) {
	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
	dispatchEvent(mockSb, "", map[string]string{"type": "test"})
	assert.True(t, mockSb.PublishOrchestrationCalled)
	assert.False(t, mockSb.DispatchToAgentCalled)
}

func TestHandleBinaryMessage_InvalidProto(t *testing.T) {
	mockSb := &MockSwitchboard{}
	// Send garbage bytes -- should not panic, just log
	handleBinaryMessage(context.Background(), "test-session", []byte("not-a-proto"), mockSb, nil)
	assert.False(t, mockSb.BroadcastCalled)
}

func TestHandleBinaryMessage_NonBroadcastType(t *testing.T) {
	mockSb := &MockSwitchboard{}
	wrapper := &gateway.Wrapper{
		Type:      "narrative",
		RequestId: "req-456",
		Payload:   []byte(`{"text": "hello"}`),
	}
	wrapperData, _ := proto.Marshal(wrapper)
	handleBinaryMessage(context.Background(), "test-session", wrapperData, mockSb, nil)
	assert.False(t, mockSb.BroadcastCalled)
	assert.False(t, mockSb.PublishOrchestrationCalled)
}

func TestHandleBinaryMessage_NilSwitchboard(t *testing.T) {
	br := &gateway.BroadcastRequest{Payload: []byte(`{}`)}
	brData, _ := proto.Marshal(br)
	wrapper := &gateway.Wrapper{Type: "broadcast", Payload: brData}
	wrapperData, _ := proto.Marshal(wrapper)
	// Should not panic with nil switchboard
	handleBinaryMessage(context.Background(), "test-session", wrapperData, nil, nil)
}

func TestHandleBinaryMessage_TargetedDispatchWithRegistry(t *testing.T) {
	// When a registry is provided and sessions are tracked, broadcast should
	// use DispatchToAgent (targeted) instead of PublishOrchestration (fan-out).
	reg := session.NewInMemorySessionService()
	// Track two sessions of the same type — should deduplicate to one dispatch
	_ = reg.TrackSession(context.Background(), "sess-planner-1", "planner", "")
	_ = reg.TrackSession(context.Background(), "sess-planner-2", "planner", "")

	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}

	br := &gateway.BroadcastRequest{
		Payload:          []byte(`{"text":"hello"}`),
		TargetSessionIds: []string{"sess-planner-1", "sess-planner-2"},
	}
	brData, _ := proto.Marshal(br)
	wrapper := &gateway.Wrapper{Type: "broadcast", Payload: brData}
	wrapperData, _ := proto.Marshal(wrapper)

	handleBinaryMessage(context.Background(), "test-session", wrapperData, mockSb, reg)

	// Wait for async goroutine
	time.Sleep(200 * time.Millisecond)

	// Should use targeted dispatch, not broadcast
	assert.True(t, mockSb.DispatchToAgentCalled,
		"Should dispatch to specific agent type via DispatchToAgent")
	assert.Equal(t, "planner", mockSb.DispatchAgentType,
		"Should dispatch to planner (the type that owns the target sessions)")
	assert.False(t, mockSb.PublishOrchestrationCalled,
		"Should NOT use PublishOrchestration (fan-out) when sessions are found")
}

func TestHandleBinaryMessage_TargetedDispatchUnknownSession(t *testing.T) {
	// When target sessions are not found in the registry, fall back to broadcast.
	reg := session.NewInMemorySessionService()
	// No sessions tracked — all targets will be "not found"

	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}

	br := &gateway.BroadcastRequest{
		Payload:          []byte(`{"text":"hello"}`),
		TargetSessionIds: []string{"unknown-sess-1"},
	}
	brData, _ := proto.Marshal(br)
	wrapper := &gateway.Wrapper{Type: "broadcast", Payload: brData}
	wrapperData, _ := proto.Marshal(wrapper)

	handleBinaryMessage(context.Background(), "test-session", wrapperData, mockSb, reg)

	// Wait for async goroutine
	time.Sleep(200 * time.Millisecond)

	// Should fall back to broadcast since no sessions were found
	assert.True(t, mockSb.PublishOrchestrationCalled,
		"Should fall back to PublishOrchestration when no sessions found in registry")
	assert.False(t, mockSb.DispatchToAgentCalled,
		"Should NOT use DispatchToAgent when sessions are unknown")
}

func TestHealthCheck_RedisOffline(t *testing.T) {
	h := hub.NewHub()
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()
	sb := hub.NewSwitchboardWithRegistry(rdb, "test-gw", h, nil, nil)
	mr.Close()

	router := setupRouter(h, sb, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/health", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	infra := resp["infra"].(map[string]interface{})
	assert.Equal(t, "offline", infra["redis"])
}

func TestHealthCheck_NilSwitchboard(t *testing.T) {
	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/health", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	var resp map[string]interface{}
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	infra := resp["infra"].(map[string]interface{})
	assert.Equal(t, "unknown", infra["redis"])
}

func TestBatchSpawn_CountLessThanOne(t *testing.T) {
	h := hub.NewHub()
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	catalog := agent.NewCatalog([]string{agentServer.URL})
	mockSb := &MockSwitchboard{}
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": -1},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "count must be")
}

func TestBatchSpawn_UnknownAgentType(t *testing.T) {
	h := hub.NewHub()
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	catalog := agent.NewCatalog([]string{agentServer.URL})
	mockSb := &MockSwitchboard{}
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "nonexistent-agent", "count": 1},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)
	assert.Contains(t, w.Body.String(), "unknown agent type")
}

func TestBatchSpawn_NilCatalog(t *testing.T) {
	h := hub.NewHub()
	mockSb := &MockSwitchboard{}
	router := setupRouter(h, mockSb, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 1},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusInternalServerError, w.Code)
	assert.Contains(t, w.Body.String(), "catalog service not initialized")
}

func TestSessionCreate_WithMockSwitchboard(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
	router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agentType": "runner_autopilot",
		"userId":    "test-user",
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/sessions", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusCreated, w.Code)
	assert.True(t, mockSb.EnqueueCalled)
	assert.Contains(t, mockSb.EnqueueQueue, "simulation:spawns:runner_autopilot:",
		"Single-session spawn queue must be sharded: simulation:spawns:{agentType}:{shard}")
}

func TestFlush_ReturnsCount(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	ctx := context.Background()

	// Track some sessions
	require.NoError(t, reg.TrackSession(ctx, "s1", "runner_autopilot", ""))
	require.NoError(t, reg.TrackSession(ctx, "s2", "simulator", ""))

	router := setupRouter(h, nil, nil, reg, "test-gw", nil, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/sessions/flush", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "flushed", resp["status"])
	assert.Equal(t, float64(2), resp["count"])
}

func TestConfigEndpoint(t *testing.T) {
	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/config", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Body.String(), "max_runners")
}

func TestWebSocketBroadcast_ContextNotCancelled(t *testing.T) {
	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
	server := httptest.NewServer(setupRouter(h, mockSb, nil, session.NewInMemorySessionService(), "test-gw", nil, nil))
	defer server.Close()

	wsURL := "ws" + server.URL[4:] + "/ws?sessionId=test-ws"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	assert.NoError(t, err)
	defer ws.Close()

	br := &gateway.BroadcastRequest{
		Payload:          []byte(`{"text": "Plan a marathon"}`),
		TargetSessionIds: []string{"planner-1"},
	}
	brData, _ := proto.Marshal(br)

	wrapper := &gateway.Wrapper{
		Type:      "broadcast",
		RequestId: "req-123",
		Payload:   brData,
	}
	wrapperData, _ := proto.Marshal(wrapper)

	err = ws.WriteMessage(websocket.BinaryMessage, wrapperData)
	assert.NoError(t, err)

	// Wait for async orchestration call
	select {
	case <-mockSb.Done:
		// success
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for PublishOrchestration - Context was likely cancelled by Gin")
	}

	assert.True(t, mockSb.BroadcastCalled, "Should have called Broadcast for internal fan-out")
	assert.True(t, mockSb.PublishOrchestrationCalled, "Should have called PublishOrchestration for agent fan-out")
}

func TestHandleBinaryMessage_A2UIAction(t *testing.T) {
	// Setup: track a session so the registry can route the action
	reg := session.NewInMemorySessionService()
	_ = reg.TrackSession(context.Background(), "test-session-123", "planner_with_eval", "")

	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}

	// Create an A2UIAction payload
	action := &gateway.A2UIAction{
		SessionId:  "test-session-123",
		ActionName: "run_simulation",
	}
	actionBytes, _ := proto.Marshal(action)

	// Wrap in a Wrapper with type "a2ui_action"
	wrapper := &gateway.Wrapper{
		Type:      "a2ui_action",
		RequestId: "req-001",
		Payload:   actionBytes,
	}
	msg, _ := proto.Marshal(wrapper)

	handleBinaryMessage(context.Background(), "client-1", msg, mockSb, reg)

	// Wait for async goroutine dispatch
	time.Sleep(100 * time.Millisecond)

	// Verify: switchboard received a targeted dispatch to "planner_with_eval"
	assert.True(t, mockSb.DispatchToAgentCalled,
		"Should dispatch A2UI action to the agent that owns the session")
	assert.Equal(t, "planner_with_eval", mockSb.DispatchAgentType,
		"Should dispatch to planner_with_eval (the type that owns test-session-123)")
}

func TestHandleBinaryMessage_A2UIAction_UnknownSession(t *testing.T) {
	// When the session is not found in the registry, no dispatch should occur
	reg := session.NewInMemorySessionService()
	// No sessions tracked

	mockSb := &MockSwitchboard{}

	action := &gateway.A2UIAction{
		SessionId:  "unknown-session",
		ActionName: "run_simulation",
	}
	actionBytes, _ := proto.Marshal(action)

	wrapper := &gateway.Wrapper{
		Type:      "a2ui_action",
		RequestId: "req-002",
		Payload:   actionBytes,
	}
	msg, _ := proto.Marshal(wrapper)

	handleBinaryMessage(context.Background(), "client-1", msg, mockSb, reg)

	time.Sleep(100 * time.Millisecond)

	assert.False(t, mockSb.DispatchToAgentCalled,
		"Should NOT dispatch when session is not in registry")
}

func TestHandleBinaryMessage_A2UIAction_NilRegistry(t *testing.T) {
	// When there is no registry, the handler should not panic
	mockSb := &MockSwitchboard{}

	action := &gateway.A2UIAction{
		SessionId:  "test-session-123",
		ActionName: "run_simulation",
	}
	actionBytes, _ := proto.Marshal(action)

	wrapper := &gateway.Wrapper{
		Type:      "a2ui_action",
		RequestId: "req-003",
		Payload:   actionBytes,
	}
	msg, _ := proto.Marshal(wrapper)

	handleBinaryMessage(context.Background(), "client-1", msg, mockSb, nil)

	time.Sleep(100 * time.Millisecond)

	assert.False(t, mockSb.DispatchToAgentCalled,
		"Should NOT dispatch when registry is nil")
}

func TestBatchSpawn_PokesOncePerAgentType(t *testing.T) {
	// Spawning 5 runner_autopilots should produce exactly 1 PokeAgent call for "runner_autopilot",
	// not 5 (the current bug). Agents consume spawn events from their Redis
	// queue — the poke just wakes them up.
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 5},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for async pokes
	select {
	case <-mockSb.Done:
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for PokeAgent")
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)
	assert.True(t, mockSb.PokeAgentCalled)
	assert.Equal(t, 1, mockSb.PokeAgentCallCount,
		"Should poke runner_autopilot exactly once, not once per session")
	assert.Equal(t, []string{"runner_autopilot"}, mockSb.PokeAgentTypes,
		"Should only poke the runner_autopilot agent type")
}

func TestBatchSpawn_PokesPerSessionForCallableAgents(t *testing.T) {
	// Callable agents have no Redis queue listener. The gateway must poke
	// once per session so each spawn event is delivered via HTTP.
	cardJSON := []byte(`{
		"name": "planner_with_memory",
		"version": "1.0.0",
		"capabilities": {
			"extensions": [
				{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}
			]
		}
	}`)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "planner_with_memory", "count": 5},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for all 5 pokes
	for i := 0; i < 5; i++ {
		select {
		case <-mockSb.Done:
		case <-time.After(2 * time.Second):
			t.Fatalf("Timeout waiting for PokeAgent call %d", i+1)
		}
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)
	assert.Equal(t, 5, mockSb.PokeAgentCallCount,
		"Callable agents must be poked once per session, not once per type")
}

func TestBatchSpawn_MixedSubscriberAndCallable(t *testing.T) {
	// Subscriber agents get 1 poke per type.
	// Callable agents get 1 poke per session.
	// Mix: 3 subscriber + 2 callable = 1 + 2 = 3 pokes.
	subscriberCard := []byte(`{"name":"runner_autopilot","version":"1.0.0"}`)
	callableCard := []byte(`{
		"name":"planner_with_memory","version":"1.0.0",
		"capabilities":{"extensions":[
			{"uri":"n26:dispatch/1.0","params":{"mode":"callable"}}
		]}
	}`)

	makeServer := func(card []byte) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(card)
			}
		}))
	}
	subSrv := makeServer(subscriberCard)
	defer subSrv.Close()
	callSrv := makeServer(callableCard)
	defer callSrv.Close()

	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}
	catalog := agent.NewCatalog([]string{subSrv.URL, callSrv.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 3},
			{"agentType": "planner_with_memory", "count": 2},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for 3 pokes (1 subscriber + 2 callable)
	for i := 0; i < 3; i++ {
		select {
		case <-mockSb.Done:
		case <-time.After(2 * time.Second):
			t.Fatalf("Timeout waiting for PokeAgent call %d", i+1)
		}
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)
	assert.Equal(t, 3, mockSb.PokeAgentCallCount,
		"Expected 1 (subscriber) + 2 (callable) = 3 pokes")

	// Verify the callable pokes carry distinct session IDs
	callableSessions := map[string]bool{}
	for _, ev := range mockSb.PokeAgentEvents {
		sid, _ := ev["sessionId"].(string)
		payload, _ := ev["payload"].(map[string]string)
		if payload != nil && payload["agentType"] == "planner_with_memory" {
			callableSessions[sid] = true
		}
	}
	assert.Equal(t, 2, len(callableSessions),
		"Each callable poke should carry a unique session ID")
}

func TestBatchSpawn_PokesEachAgentTypeOnce(t *testing.T) {
	// Spawning 3 runner_autopilots + 2 simulators should produce exactly 2 PokeAgent calls.
	makeServer := func(name string) *httptest.Server {
		card := agent.AgentCard{Name: name, Version: "1.0.0"}
		cardJSON, _ := json.Marshal(card)
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			}
		}))
	}
	runnerSrv := makeServer("runner_autopilot")
	defer runnerSrv.Close()
	simSrv := makeServer("simulator")
	defer simSrv.Close()

	h := hub.NewHub()
	go h.Run()

	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}
	catalog := agent.NewCatalog([]string{runnerSrv.URL, simSrv.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 3},
			{"agentType": "simulator", "count": 2},
		},
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for both pokes
	for i := 0; i < 2; i++ {
		select {
		case <-mockSb.Done:
		case <-time.After(2 * time.Second):
			t.Fatalf("Timeout waiting for PokeAgent call %d", i+1)
		}
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)
	assert.Equal(t, 2, mockSb.PokeAgentCallCount,
		"Should poke exactly 2 agent types (runner_autopilot + simulator), not 5 sessions")
	assert.ElementsMatch(t, []string{"runner_autopilot", "simulator"}, mockSb.PokeAgentTypes,
		"Should poke each agent type exactly once")
}

func TestEnvironmentReset_FlushAll(t *testing.T) {
	// When no targets are specified, all three subsystems should be flushed.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	ctx := context.Background()

	// Track some sessions so Flush returns a count
	require.NoError(t, reg.TrackSession(ctx, "s1", "runner", ""))
	require.NoError(t, reg.TrackSession(ctx, "s2", "simulator", ""))

	mockSb := &MockSwitchboard{FlushQueuesCount: 3}

	// Use miniredis for session_map scanning
	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	// Seed some session_map keys to verify map flush
	rdb.Set(ctx, "session_map:abc", "data1", 0)
	rdb.Set(ctx, "session_map:def", "data2", 0)

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "reset", resp["status"])

	results := resp["results"].(map[string]interface{})

	// Sessions were flushed
	sessResult := results["sessions"].(map[string]interface{})
	assert.Equal(t, true, sessResult["flushed"])
	assert.Equal(t, float64(2), sessResult["count"])

	// Queues were flushed
	queueResult := results["queues"].(map[string]interface{})
	assert.Equal(t, true, queueResult["flushed"])
	assert.Equal(t, float64(3), queueResult["count"])

	// Maps were flushed
	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, true, mapResult["flushed"])
	assert.Equal(t, float64(2), mapResult["count"])

	// Verify FlushQueues was called on switchboard
	assert.True(t, mockSb.FlushQueuesCalled)

	// Verify environment_reset event was broadcast
	assert.True(t, mockSb.BroadcastCalled, "Should broadcast environment_reset event")
	var wrapper gateway.Wrapper
	require.NoError(t, proto.Unmarshal(mockSb.BroadcastData, &wrapper))
	assert.Equal(t, "environment_reset", wrapper.Type)
	assert.Equal(t, "environment_reset", wrapper.Event)

	// Verify session_map keys were deleted from Redis
	keys, _ := rdb.Keys(ctx, "session_map:*").Result()
	assert.Empty(t, keys, "All session_map keys should be deleted")
}

func TestEnvironmentReset_SelectiveTargets(t *testing.T) {
	// When specific targets are provided, only those subsystems should be flushed.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	ctx := context.Background()

	require.NoError(t, reg.TrackSession(ctx, "s1", "runner", ""))

	mockSb := &MockSwitchboard{FlushQueuesCount: 1}

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	// Seed a session_map key that should NOT be deleted
	rdb.Set(ctx, "session_map:keep", "data", 0)

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	// Only flush sessions and queues, not maps
	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{"sessions", "queues"},
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "reset", resp["status"])

	results := resp["results"].(map[string]interface{})

	// Sessions were flushed
	sessResult := results["sessions"].(map[string]interface{})
	assert.Equal(t, true, sessResult["flushed"])

	// Queues were flushed
	queueResult := results["queues"].(map[string]interface{})
	assert.Equal(t, true, queueResult["flushed"])

	// Maps were NOT flushed
	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, false, mapResult["flushed"])
	assert.Equal(t, float64(0), mapResult["count"])

	// session_map key should still exist
	keys, _ := rdb.Keys(ctx, "session_map:*").Result()
	assert.Len(t, keys, 1, "session_map keys should NOT be deleted when maps not targeted")
}

func TestEnvironmentReset_EmptyTargetsFlushesAll(t *testing.T) {
	// Empty targets array should behave the same as no body (flush all).
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{FlushQueuesCount: 0}

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{},
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Equal(t, "reset", resp["status"])

	// All three should be flushed
	results := resp["results"].(map[string]interface{})
	sessResult := results["sessions"].(map[string]interface{})
	assert.Equal(t, true, sessResult["flushed"])
	queueResult := results["queues"].(map[string]interface{})
	assert.Equal(t, true, queueResult["flushed"])
	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, true, mapResult["flushed"])
}

func TestEnvironmentReset_UnknownTarget(t *testing.T) {
	// Unknown target names should be rejected with 400.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{}
	router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{"sessions", "nonexistent"},
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusBadRequest, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.Contains(t, resp["error"], "nonexistent")

	// Verify allowed targets are returned in the error
	allowed := resp["allowed"].([]interface{})
	assert.ElementsMatch(t, []interface{}{"sessions", "queues", "maps", "pubsub"}, allowed)
}

func TestEnvironmentReset_NilRedis(t *testing.T) {
	// When rdb is nil (no Redis), maps flush should gracefully report 0.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{FlushQueuesCount: 0}

	router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))

	results := resp["results"].(map[string]interface{})
	mapResult := results["maps"].(map[string]interface{})
	assert.Equal(t, true, mapResult["flushed"])
	assert.Equal(t, float64(0), mapResult["count"])
}

func TestEnvironmentReset_PublishesSimulationBroadcast(t *testing.T) {
	// Environment reset must publish to simulation:broadcast so dispatchers
	// can clear their in-memory sessions and cancel in-flight tasks.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{FlushQueuesCount: 0}

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	// Verify gateway:broadcast was called (existing behavior)
	assert.True(t, mockSb.BroadcastCalled,
		"Should broadcast environment_reset on gateway:broadcast for WebSocket clients")

	// Verify simulation:broadcast was also called (new behavior)
	assert.True(t, mockSb.PublishOrchestrationCalled,
		"Should publish environment_reset on simulation:broadcast for agent dispatchers")
	assert.Equal(t, "simulation:broadcast", mockSb.PublishOrchestrationChannel,
		"PublishOrchestration must target simulation:broadcast channel")

	// Verify the event payload
	assert.NotNil(t, mockSb.LastEvent)
	assert.Equal(t, "environment_reset", mockSb.LastEvent["type"],
		"Event type must be environment_reset")
	assert.NotEmpty(t, mockSb.LastEvent["eventId"],
		"Event must have an eventId for deduplication")
}

func TestEnvironmentReset_PubSubTarget(t *testing.T) {
	// The "pubsub" target should trigger PubSub subscription drain.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{FlushQueuesCount: 0}

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{"pubsub"},
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset",
		bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))

	results := resp["results"].(map[string]interface{})
	pubsubResult := results["pubsub"].(map[string]interface{})
	assert.Equal(t, true, pubsubResult["flushed"])
}

func TestEnvironmentReset_PubSubTargetInAllowedList(t *testing.T) {
	// "pubsub" must be in the allowed targets list for validation.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{}
	router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"targets": []string{"pubsub", "sessions"},
	})

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset",
		bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Should NOT be rejected -- pubsub is a valid target
	assert.Equal(t, http.StatusOK, w.Code)
}

func TestEnvironmentReset_PokesAgentsFromSnapshot(t *testing.T) {
	// Bug fix: reset must poke agents that WERE active before flush,
	// not query ActiveAgentTypes after sessions are already deleted.
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	ctx := context.Background()

	// Track sessions for two agent types
	require.NoError(t, reg.TrackSession(ctx, "s1", "simulator", ""))
	require.NoError(t, reg.TrackSession(ctx, "s2", "planner", ""))

	mockSb := &MockSwitchboard{FlushQueuesCount: 0}

	mr := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: mr.Addr()})
	defer rdb.Close()

	router := setupRouter(h, mockSb, nil, reg, "test-gw", rdb, nil)

	w := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/api/v1/environment/reset", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	// The critical assertion: agents must be poked even though sessions
	// were already flushed by the time the notification is sent.
	assert.True(t, mockSb.PokeAgentCalled,
		"Must poke agents using pre-flush snapshot, not post-flush registry query")
	assert.GreaterOrEqual(t, mockSb.PokeAgentCallCount, 2,
		"Should poke at least the 2 agent types that had active sessions")
	assert.ElementsMatch(t, []string{"simulator", "planner"}, mockSb.PokeAgentTypes,
		"Should poke exactly the agent types from the pre-flush snapshot")
}

func TestBatchSpawnWithSimulationID(t *testing.T) {
	// Spawning with a simulation_id should tag all sessions and include it in the response.
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	go h.Run()

	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, reg, "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": "runner_autopilot", "count": 2},
		},
		"simulation_id": "sim-xyz",
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	// Wait for async poke
	select {
	case <-mockSb.Done:
	case <-time.After(2 * time.Second):
		t.Fatal("Timeout waiting for PokeAgent")
	}
	time.Sleep(100 * time.Millisecond)

	assert.Equal(t, 200, w.Code)

	// Parse response and verify simulation_id is in each session entry
	var resp struct {
		Sessions []struct {
			SessionID    string `json:"sessionId"`
			AgentType    string `json:"agentType"`
			SimulationID string `json:"simulationId"`
		} `json:"sessions"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	require.Len(t, resp.Sessions, 2)
	for _, s := range resp.Sessions {
		assert.Equal(t, "sim-xyz", s.SimulationID,
			"Each spawned session should include the simulation_id in response")
		assert.Equal(t, "runner_autopilot", s.AgentType)
	}

	// Verify sessions are tagged in the registry
	for _, s := range resp.Sessions {
		simID, err := reg.FindSimulation(context.Background(), s.SessionID)
		require.NoError(t, err)
		assert.Equal(t, "sim-xyz", simID,
			"Session should be tracked with simulation_id in registry")
	}

	// Verify simulation_id is included in spawn event payloads
	require.True(t, mockSb.BatchEnqueueCalled)
	for _, item := range mockSb.BatchEnqueueItems {
		evt, ok := item.Data.(map[string]interface{})
		require.True(t, ok)
		payload, ok := evt["payload"].(map[string]string)
		require.True(t, ok)
		assert.Equal(t, "sim-xyz", payload["simulation_id"],
			"Spawn event payload should include simulation_id (snake_case for Python consumers)")
	}
}

func TestSessionCreateWithSimulationID(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
	router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

	body, _ := json.Marshal(map[string]interface{}{
		"agentType":     "runner_autopilot",
		"userId":        "test-user",
		"simulation_id": "sim-abc",
	})
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/sessions", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	router.ServeHTTP(w, req)

	assert.Equal(t, http.StatusCreated, w.Code)

	var resp struct {
		SessionID string `json:"sessionId"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))

	// Verify the session is tracked with simulation_id
	simID, err := reg.FindSimulation(context.Background(), resp.SessionID)
	require.NoError(t, err)
	assert.Equal(t, "sim-abc", simID,
		"Session should be tracked with simulation_id in registry")

	// Cross-boundary contract: verify the spawn event payload uses snake_case
	// keys that match the Python dispatcher consumer (agents/utils/dispatcher.py).
	require.True(t, mockSb.EnqueueCalled)
	evt, ok := mockSb.LastEvent["payload"].(map[string]string)
	require.True(t, ok, "spawn event payload must be map[string]string")
	assert.Equal(t, "sim-abc", evt["simulation_id"],
		"Single-session spawn event payload must use snake_case 'simulation_id' for Python consumers")
	_, hasCamel := evt["simulationId"]
	assert.False(t, hasCamel,
		"Spawn event payload must NOT contain camelCase 'simulationId' — Python reads 'simulation_id'")
}

// TestSpawnEventPayload_CrossBoundaryContract is a dedicated contract test that
// verifies the spawn event payloads produced by both the single-session
// (POST /api/v1/sessions) and batch-spawn (POST /api/v1/spawn) handlers use
// snake_case keys matching what the Python dispatcher expects.
//
// This test exists to catch Go→Python boundary mismatches (camelCase vs
// snake_case) that silently break simulation_id tracking.
func TestSpawnEventPayload_CrossBoundaryContract(t *testing.T) {
	t.Run("single_session_uses_snake_case", func(t *testing.T) {
		h := hub.NewHub()
		reg := session.NewInMemorySessionService()
		mockSb := &MockSwitchboard{Done: make(chan bool, 1)}
		router := setupRouter(h, mockSb, nil, reg, "test-gw", nil, nil)

		body, _ := json.Marshal(map[string]interface{}{
			"agentType":     "runner_autopilot",
			"userId":        "test-user",
			"simulation_id": "sim-contract-1",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/v1/sessions", bytes.NewBuffer(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		require.Equal(t, http.StatusCreated, w.Code)

		// Wait for async enqueue
		select {
		case <-mockSb.Done:
		case <-time.After(2 * time.Second):
			t.Fatal("Timeout waiting for enqueue")
		}

		require.True(t, mockSb.EnqueueCalled, "EnqueueOrchestration must be called")
		require.NotNil(t, mockSb.LastEvent, "LastEvent must be captured")

		payload, ok := mockSb.LastEvent["payload"].(map[string]string)
		require.True(t, ok, "payload must be map[string]string")

		// Contract: Python dispatcher reads payload.get("simulation_id")
		assert.Equal(t, "sim-contract-1", payload["simulation_id"],
			"Spawn event payload MUST use 'simulation_id' (snake_case)")
		_, hasCamel := payload["simulationId"]
		assert.False(t, hasCamel,
			"Spawn event payload MUST NOT contain 'simulationId' (camelCase)")
	})

	t.Run("batch_spawn_uses_snake_case", func(t *testing.T) {
		h := hub.NewHub()
		reg := session.NewInMemorySessionService()
		mockSb := &MockSwitchboard{Done: make(chan bool, 10)}

		card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
		cardJSON, _ := json.Marshal(card)
		agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			}
		}))
		defer agentServer.Close()

		catalog := agent.NewCatalog([]string{agentServer.URL})
		router := setupRouter(h, mockSb, catalog, reg, "test-gw", nil, nil)

		body, _ := json.Marshal(map[string]interface{}{
			"agents": []map[string]interface{}{
				{"agentType": "runner_autopilot", "count": 2},
			},
			"simulation_id": "sim-contract-2",
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)

		// Wait for async poke
		select {
		case <-mockSb.Done:
		case <-time.After(2 * time.Second):
			t.Fatal("Timeout waiting for PokeAgent")
		}
		time.Sleep(100 * time.Millisecond)

		require.Equal(t, 200, w.Code)
		require.True(t, mockSb.BatchEnqueueCalled, "BatchEnqueueOrchestration must be called")

		for i, item := range mockSb.BatchEnqueueItems {
			evt, ok := item.Data.(map[string]interface{})
			require.True(t, ok, "item %d: event must be map[string]interface{}", i)

			payload, ok := evt["payload"].(map[string]string)
			require.True(t, ok, "item %d: payload must be map[string]string", i)

			// Contract: Python dispatcher reads payload.get("simulation_id")
			assert.Equal(t, "sim-contract-2", payload["simulation_id"],
				"item %d: batch spawn payload MUST use 'simulation_id' (snake_case)", i)
			_, hasCamel := payload["simulationId"]
			assert.False(t, hasCamel,
				"item %d: batch spawn payload MUST NOT contain 'simulationId' (camelCase)", i)
		}
	})
}

func TestListSimulations(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	mockSb := &MockSwitchboard{Done: make(chan bool, 10)}

	// Setup agent server
	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, reg, "test-gw", nil, nil)

	// Spawn sessions with two different simulation IDs
	for _, simID := range []string{"sim-alpha", "sim-beta"} {
		body, _ := json.Marshal(map[string]interface{}{
			"agents": []map[string]interface{}{
				{"agentType": "runner_autopilot", "count": 1},
			},
			"simulation_id": simID,
		})
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
		req.Header.Set("Content-Type", "application/json")
		router.ServeHTTP(w, req)
		require.Equal(t, 200, w.Code)
	}

	// GET /api/v1/simulations
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/simulations", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp struct {
		Simulations []string `json:"simulations"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.ElementsMatch(t, []string{"sim-alpha", "sim-beta"}, resp.Simulations)
}

func TestListSimulations_EmptyRegistry(t *testing.T) {
	h := hub.NewHub()
	reg := session.NewInMemorySessionService()
	router := setupRouter(h, nil, nil, reg, "test-gw", nil, nil)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/simulations", nil)
	router.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)

	var resp struct {
		Simulations []string `json:"simulations"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	assert.NotNil(t, resp.Simulations, "Should return empty array, not null")
	assert.Empty(t, resp.Simulations)
}

// --- MAX_RUNNERS enforcement tests ---

func TestBatchSpawn_ExceedsMaxRunners_Capped(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "5")

	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	mockSb := &MockSwitchboard{Done: make(chan bool, 5)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body := `{"agents":[{"agentType":"runner_autopilot","count":10}]}`
	req := httptest.NewRequest("POST", "/api/v1/spawn", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	// Should succeed with capped count, not 422.
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (capped), got %d: %s", w.Code, w.Body.String())
	}
	// Verify only 5 sessions were spawned (capped from 10).
	var resp struct {
		Sessions []struct{ SessionID string } `json:"sessions"`
	}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	if len(resp.Sessions) != 5 {
		t.Errorf("expected 5 capped sessions, got %d", len(resp.Sessions))
	}
}

func TestBatchSpawn_WithinMaxRunners(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "20")

	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	mockSb := &MockSwitchboard{Done: make(chan bool, 5)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body := `{"agents":[{"agentType":"runner_autopilot","count":10}]}`
	req := httptest.NewRequest("POST", "/api/v1/spawn", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", w.Code, w.Body.String())
	}
}

func TestBatchSpawn_DefaultMaxRunners(t *testing.T) {
	// Unset MAX_RUNNERS — default should be 100.
	t.Setenv("MAX_RUNNERS", "")

	card := agent.AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)
	agentServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		}
	}))
	defer agentServer.Close()

	h := hub.NewHub()
	mockSb := &MockSwitchboard{Done: make(chan bool, 101)}
	catalog := agent.NewCatalog([]string{agentServer.URL})
	router := setupRouter(h, mockSb, catalog, session.NewInMemorySessionService(), "test-gw", nil, nil)

	body := `{"agents":[{"agentType":"runner_autopilot","count":300}]}`
	req := httptest.NewRequest("POST", "/api/v1/spawn", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	// Should succeed with capped count (300 -> 100).
	if w.Code != http.StatusOK {
		t.Fatalf("expected 200 (capped at default 100), got %d: %s", w.Code, w.Body.String())
	}
}

func TestConfigEndpoint_MaxRunners(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "42")

	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)

	req := httptest.NewRequest("GET", "/config", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", w.Code)
	}

	var resp map[string]interface{}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatalf("failed to parse response: %v", err)
	}
	maxR, ok := resp["max_runners"]
	if !ok {
		t.Fatal("max_runners not found in /config response")
	}
	if int(maxR.(float64)) != 42 {
		t.Errorf("expected max_runners=42, got %v", maxR)
	}
}

func TestMaxRunners_ClampedToUpperBound(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "5000")

	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)

	req := httptest.NewRequest("GET", "/config", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	if int(resp["max_runners"].(float64)) != 1000 {
		t.Errorf("expected max_runners clamped to 1000, got %v", resp["max_runners"])
	}
}

func TestMaxRunners_InvalidFallsBackToDefault(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "abc")

	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)

	req := httptest.NewRequest("GET", "/config", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	if int(resp["max_runners"].(float64)) != 100 {
		t.Errorf("expected default max_runners=100, got %v", resp["max_runners"])
	}
}

func TestMaxRunners_ZeroFallsBackToDefault(t *testing.T) {
	t.Setenv("MAX_RUNNERS", "0")

	h := hub.NewHub()
	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)

	req := httptest.NewRequest("GET", "/config", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	var resp map[string]interface{}
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))
	if int(resp["max_runners"].(float64)) != 100 {
		t.Errorf("expected default max_runners=100 for zero input, got %v", resp["max_runners"])
	}
}

// TestGlobalObserver_TextFrameUnsubscribe_DemoSwitch exercises the exact
// frontend demo-switch path end-to-end through the gateway WebSocket handler:
//
//  1. Connect as global observer (no sessionId) — mirrors frontend's AgentGateway
//  2. Send subscribe_simulation text frame — mirrors subscribeSimulation()
//  3. Verify subscription works (receive sim messages via Phase 1)
//  4. Send unsubscribe_simulation text frame — mirrors the fix in removeCurrentSimulationId()
//  5. Verify messages from old sim are filtered
//  6. Subscribe to new sim — mirrors the new demo's subscribeSimulation()
//  7. Verify only new sim messages arrive, old sim messages don't leak
//
// This covers: WS text frame → gateway reader → HandleTextMessage → Hub Run()
// → processRemoteMessage Phase 1 filter — the full path from frontend to routing.
func TestGlobalObserver_TextFrameUnsubscribe_DemoSwitch(t *testing.T) {
	h := hub.NewHub()
	go h.Run()

	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	server := httptest.NewServer(router)
	defer server.Close()

	wsURL := "ws" + server.URL[4:]

	// Step 1: Connect as global observer (no sessionId, no simulationId)
	// — this is how the frontend's AgentGateway connects.
	ws, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws", nil)
	require.NoError(t, err)
	defer ws.Close()

	// Use a goroutine reader to avoid gorilla/websocket read-after-timeout
	// issues. All messages are drained into a channel for safe assertion.
	msgCh := make(chan []byte, 64)
	go func() {
		for {
			_, data, err := ws.ReadMessage()
			if err != nil {
				close(msgCh)
				return
			}
			msgCh <- data
		}
	}()

	time.Sleep(100 * time.Millisecond)

	// Step 2: Subscribe to "sim-demo1" via text frame
	err = ws.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-demo1"}`))
	require.NoError(t, err)
	time.Sleep(100 * time.Millisecond)

	// Step 3: Verify subscription works — send a sim-demo1 message
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "tick_event",
		SimulationId: "sim-demo1",
		SessionId:    "simulator-session-1",
	})
	select {
	case msg := <-msgCh:
		var received gateway.Wrapper
		require.NoError(t, proto.Unmarshal(msg, &received))
		assert.Equal(t, "sim-demo1", received.SimulationId)
	case <-time.After(1 * time.Second):
		t.Fatal("Timed out waiting for sim-demo1 message while subscribed")
	}

	// Step 4: Unsubscribe from sim-demo1 via text frame
	// — this is the fix: frontend now sends this on demo switch.
	err = ws.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"unsubscribe_simulation","simulation_id":"sim-demo1"}`))
	require.NoError(t, err)
	time.Sleep(100 * time.Millisecond)

	// Step 5: Verify sim-demo1 messages are now filtered
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "tick_event",
		SimulationId: "sim-demo1",
		SessionId:    "simulator-session-1",
	})
	select {
	case msg := <-msgCh:
		t.Fatalf("Global observer received sim-demo1 message AFTER unsubscribe (leak!): %x", msg[:20])
	case <-time.After(300 * time.Millisecond):
		// Good — message was correctly filtered
	}

	// Step 6: Subscribe to "sim-demo2" (new demo)
	err = ws.WriteMessage(websocket.TextMessage,
		[]byte(`{"type":"subscribe_simulation","simulation_id":"sim-demo2"}`))
	require.NoError(t, err)
	time.Sleep(100 * time.Millisecond)

	// Step 7a: Send sim-demo1 (old sim — should be filtered) then sim-demo2 (new sim)
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "post_race_event",
		SimulationId: "sim-demo1",
		SessionId:    "simulator-session-1",
	})
	time.Sleep(100 * time.Millisecond) // let the filtered message NOT arrive

	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "tick_event",
		SimulationId: "sim-demo2",
		SessionId:    "simulator-session-2",
	})

	// Step 7b: Only sim-demo2 should arrive
	select {
	case msg := <-msgCh:
		var received2 gateway.Wrapper
		require.NoError(t, proto.Unmarshal(msg, &received2))
		assert.Equal(t, "sim-demo2", received2.SimulationId,
			"Should receive sim-demo2, not leaked sim-demo1 post_race_event")
	case <-time.After(1 * time.Second):
		t.Fatal("Timed out waiting for sim-demo2 message after re-subscribing")
	}
}

func TestAutoSubscribe_SimulationIdQueryParam(t *testing.T) {
	h := hub.NewHub()
	go h.Run()

	router := setupRouter(h, nil, nil, session.NewInMemorySessionService(), "test-gw", nil, nil)
	server := httptest.NewServer(router)
	defer server.Close()

	wsURL := "ws" + server.URL[4:]

	// Connect with simulationId query param — should auto-subscribe
	ws, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=auto-sub-client&simulationId=sim-auto", nil)
	require.NoError(t, err)
	defer ws.Close()

	// Connect without simulationId — should NOT receive simulation messages
	wsOther, _, err := websocket.DefaultDialer.Dial(wsURL+"/ws?sessionId=no-sub-client", nil)
	require.NoError(t, err)
	defer wsOther.Close()

	time.Sleep(100 * time.Millisecond)

	// Send a message for sim-auto targeted at a non-existent session
	// so only simulation routing delivers it
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-auto",
		SessionId:    "nonexistent-session",
	})

	// Auto-subscribed client should receive it
	_ = ws.SetReadDeadline(time.Now().Add(1 * time.Second))
	_, msg, err := ws.ReadMessage()
	assert.NoError(t, err, "Auto-subscribed client should receive sim-auto message")
	assert.NotEmpty(t, msg)

	// Other client should NOT receive it
	_ = wsOther.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	_, _, err = wsOther.ReadMessage()
	assert.Error(t, err, "Non-subscribed client should NOT receive sim-auto message")
}
