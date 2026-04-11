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

package hub

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestHubSessionRouting(t *testing.T) {
	h := NewHub()
	go h.Run()

	// Setup a test server to handle WebSocket upgrade
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}

		sessionID := r.URL.Query().Get("sessionId")
		h.Register(sessionID, conn)
	}))
	defer server.Close()

	// Connect two clients with different sessions
	url1 := strings.Replace(server.URL, "http", "ws", 1) + "?sessionId=session1"
	url2 := strings.Replace(server.URL, "http", "ws", 1) + "?sessionId=session2"

	ws1, _, err := websocket.DefaultDialer.Dial(url1, nil)
	assert.NoError(t, err)
	defer ws1.Close()

	ws2, _, err := websocket.DefaultDialer.Dial(url2, nil)
	assert.NoError(t, err)
	defer ws2.Close()

	// Give a moment for registration
	time.Sleep(50 * time.Millisecond)

	// Send message to session1
	expectedPayload := map[string]interface{}{"msg": "hello session 1"}
	h.SendMessage("session1", "text", "narrative", expectedPayload)

	// Verify ws1 receives it
	_, msg1, err := ws1.ReadMessage()
	assert.NoError(t, err)

	var decoded1 GatewayMessage
	err = json.Unmarshal(msg1, &decoded1)
	assert.NoError(t, err)

	assert.Equal(t, "system", decoded1.Origin.Type)
	assert.Equal(t, "gateway", decoded1.Origin.ID)
	assert.ElementsMatch(t, []string{"session1"}, decoded1.Destination)
	assert.Equal(t, "text", decoded1.Type)
	assert.Equal(t, "narrative", decoded1.Event)
	assert.Equal(t, "success", decoded1.Status)

	// Check inner payload
	dataMap, ok := decoded1.Data.(map[string]interface{})
	assert.True(t, ok)
	assert.Equal(t, "hello session 1", dataMap["msg"])

	// Verify ws2 DOES NOT receive it (wait for timeout)
	_ = ws2.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
	_, _, err = ws2.ReadMessage()
	assert.Error(t, err)
}

func TestHubUnregister(t *testing.T) {
	h := NewHub()
	go h.Run()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}

		sessionID := r.URL.Query().Get("sessionId")
		h.Register(sessionID, conn)

		// If the "unregister" query param is set, unregister after a short delay
		if r.URL.Query().Get("unregister") == "true" {
			time.Sleep(50 * time.Millisecond)
			h.Unregister(sessionID, conn)
		}
	}))
	defer server.Close()

	// Connect a client that will be unregistered
	wsURL := strings.Replace(server.URL, "http", "ws", 1) + "?sessionId=sess-unreg&unregister=true"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	assert.NoError(t, err)
	defer ws.Close()

	// Wait for register + unregister to complete
	time.Sleep(150 * time.Millisecond)

	// Try to send a message to the unregistered session
	h.SendMessage("sess-unreg", "text", "test", map[string]string{"msg": "should not arrive"})

	// The client should NOT receive the message (timeout expected)
	_ = ws.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	_, _, err = ws.ReadMessage()
	assert.Error(t, err, "Expected timeout error because client was unregistered")
}

func TestHubBroadcast(t *testing.T) {
	h := NewHub()
	go h.Run()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool { return true },
		}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("all", conn)
	}))
	defer server.Close()

	wsURL := strings.Replace(server.URL, "http", "ws", 1)
	ws1, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err, "ws1 dial failed")
	defer ws1.Close()

	ws2, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err, "ws2 dial failed")
	defer ws2.Close()

	time.Sleep(50 * time.Millisecond)

	broadcastMsg := []byte("broadcast")
	h.broadcast <- broadcastMsg

	_, m1, err := ws1.ReadMessage()
	require.NoError(t, err, "ws1 read failed")
	_, m2, err := ws2.ReadMessage()
	require.NoError(t, err, "ws2 read failed")

	assert.Equal(t, broadcastMsg, m1)
	assert.Equal(t, broadcastMsg, m2)
}

func TestHubRemoteMessageRouting(t *testing.T) {
	h := NewHub()
	go h.Run()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		sessionID := r.URL.Query().Get("sessionId")
		h.Register(sessionID, conn)
	}))
	defer server.Close()

	wsURL := strings.Replace(server.URL, "http", "ws", 1)

	// Create three WebSocket clients
	// 1: Global observer (empty sessionId)
	wsGlobal, _, err := websocket.DefaultDialer.Dial(wsURL+"?sessionId=", nil)
	require.NoError(t, err, "global observer dial failed")
	defer wsGlobal.Close()

	// 2: Target session A
	wsA, _, err := websocket.DefaultDialer.Dial(wsURL+"?sessionId=A", nil)
	require.NoError(t, err, "session A dial failed")
	defer wsA.Close()

	// 3: Target session B (to test it DOES NOT receive A's messages)
	wsB, _, err := websocket.DefaultDialer.Dial(wsURL+"?sessionId=B", nil)
	require.NoError(t, err, "session B dial failed")
	defer wsB.Close()

	// 4: Target session C (to test it DOES receive broadcast messages)
	wsC, _, err := websocket.DefaultDialer.Dial(wsURL+"?sessionId=C", nil)
	require.NoError(t, err, "session C dial failed")
	defer wsC.Close()

	time.Sleep(100 * time.Millisecond)

	// Test 1: Targeted message to Session A
	targetedMsg := &gateway.Wrapper{
		Type:      "test_event",
		SessionId: "A",
	}
	h.HandleRemoteMessage(targetedMsg)

	// Global and A should receive it, B should timeout
	_ = wsGlobal.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msgGlobal1, err := wsGlobal.ReadMessage()
	assert.NoError(t, err, "Global observer should receive targeted messages")
	assert.NotEmpty(t, msgGlobal1)

	_ = wsA.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msgA1, err := wsA.ReadMessage()
	assert.NoError(t, err, "Session A should receive its targeted message")
	assert.NotEmpty(t, msgA1)

	_ = wsB.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
	_, _, err = wsB.ReadMessage()
	assert.Error(t, err, "Session B should NOT receive Session A's messages")

	// Test 2: Broadcast message (No Session ID)
	broadcastMsg := &gateway.Wrapper{
		Type: "broadcast_event",
	}
	h.HandleRemoteMessage(broadcastMsg)

	// Global, A, and C should receive it
	_ = wsGlobal.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msgGlobal2, err := wsGlobal.ReadMessage()
	assert.NoError(t, err)
	assert.NotEmpty(t, msgGlobal2)

	_ = wsA.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msgA2, err := wsA.ReadMessage()
	assert.NoError(t, err)
	assert.NotEmpty(t, msgA2)

	_ = wsC.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
	_, msgC2, err := wsC.ReadMessage()
	assert.NoError(t, err)
	assert.NotEmpty(t, msgC2)
}

func TestHubPublish_AppendsNewlineAndBroadcasts(t *testing.T) {
	h := NewHub()
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("pub-test", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond)

	// Publish should append a newline for NDJ support
	h.Publish([]byte(`{"event":"test"}`))

	_ = ws.SetReadDeadline(time.Now().Add(1 * time.Second))
	_, msg, err := ws.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, []byte(`{"event":"test"}`+"\n"), msg)
}

func TestHubBroadcastChannel_AcceptsMessages(t *testing.T) {
	h := NewHub()
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("chan-test", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond)

	// Use the Broadcast() channel accessor directly
	h.Broadcast() <- []byte("via-channel")

	_ = ws.SetReadDeadline(time.Now().Add(1 * time.Second))
	_, msg, err := ws.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, []byte("via-channel"), msg)
}

func TestHubSessionMsgChannel_DeliversToSession(t *testing.T) {
	h := NewHub()
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("sm-test", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond)

	// Use the SessionMsg() channel accessor directly
	h.SessionMsg() <- SessionMessage{SessionID: "sm-test", Data: []byte("session-payload")}

	_ = ws.SetReadDeadline(time.Now().Add(1 * time.Second))
	_, msg, err := ws.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, []byte("session-payload"), msg)
}

func TestHubUnregister_UnknownSessionIsNoOp(t *testing.T) {
	h := NewHub()
	go h.Run()
	time.Sleep(10 * time.Millisecond)

	// Unregistering from a nonexistent session should not panic or deadlock.
	// Use nil conn since the lookup will fail at the session level.
	h.Unregister("nonexistent-session", nil)

	// Give Run a moment to process
	time.Sleep(50 * time.Millisecond)
}

func TestHubSendMessage_UnmarshalableContent_DoesNotDeliverOrPanic(t *testing.T) {
	h := NewHub()
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("marshal-err", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond)

	// Pass an un-marshalable content (channel type) -- should not panic
	h.SendMessage("marshal-err", "test", "event", make(chan int))

	// The client should NOT receive anything (marshal failed, message not sent)
	_ = ws.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
	_, _, err = ws.ReadMessage()
	assert.Error(t, err, "Expected timeout -- no message should be delivered on marshal error")
}

func TestNewHubWithConfig_CustomBufferSizes(t *testing.T) {
	cfg := HubConfig{
		BroadcastBuffer:  10,
		SessionMsgBuffer: 5,
		RemoteMsgBuffer:  3,
		ClientSendBuffer: 1,
	}
	h := NewHubWithConfig(cfg)
	assert.NotNil(t, h)
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		h.Register("cfg-test", conn)
	}))
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond)

	// The hub should function with small buffers
	h.Publish([]byte("small-buf"))

	_ = ws.SetReadDeadline(time.Now().Add(1 * time.Second))
	_, msg, err := ws.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, []byte("small-buf\n"), msg)
}

// --- Simulation Subscription Tests ---

// simTestEnv encapsulates a Hub, test server, and tracking of server-side connections.
type simTestEnv struct {
	hub        *Hub
	server     *httptest.Server
	mu         sync.Mutex
	serverConn map[string]*websocket.Conn // sessionID -> server-side conn
}

// helperSetupSimHub creates a Hub, starts Run(), and returns a simTestEnv.
func helperSetupSimHub(t *testing.T) *simTestEnv {
	t.Helper()
	h := NewHub()
	go h.Run()

	env := &simTestEnv{
		hub:        h,
		serverConn: make(map[string]*websocket.Conn),
	}

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	env.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		sessionID := r.URL.Query().Get("sessionId")
		env.mu.Lock()
		env.serverConn[sessionID] = conn
		env.mu.Unlock()
		h.Register(sessionID, conn)
	}))
	t.Cleanup(func() { env.server.Close() })
	return env
}

// helperDial connects a WebSocket client with the given session ID and
// returns the client-side conn.
func helperDial(t *testing.T, env *simTestEnv, sessionID string) *websocket.Conn {
	t.Helper()
	wsURL := strings.Replace(env.server.URL, "http", "ws", 1) + "?sessionId=" + sessionID
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	t.Cleanup(func() { ws.Close() })
	return ws
}

// helperServerConn returns the server-side conn for a session, waiting briefly for registration.
func helperServerConn(t *testing.T, env *simTestEnv, sessionID string) *websocket.Conn {
	t.Helper()
	// Brief wait for the HTTP handler to store the conn
	time.Sleep(50 * time.Millisecond)
	env.mu.Lock()
	defer env.mu.Unlock()
	conn, ok := env.serverConn[sessionID]
	require.True(t, ok, "server-side conn not found for session %s", sessionID)
	return conn
}

// helperExpectBinaryMessage reads a binary message within a timeout and returns the raw bytes.
func helperExpectBinaryMessage(t *testing.T, ws *websocket.Conn, timeout time.Duration) []byte {
	t.Helper()
	_ = ws.SetReadDeadline(time.Now().Add(timeout))
	mt, data, err := ws.ReadMessage()
	require.NoError(t, err, "expected to receive a message")
	assert.Equal(t, websocket.BinaryMessage, mt)
	return data
}

// helperExpectNoMessage asserts no message is received within a timeout.
func helperExpectNoMessage(t *testing.T, ws *websocket.Conn, timeout time.Duration) {
	t.Helper()
	_ = ws.SetReadDeadline(time.Now().Add(timeout))
	_, _, err := ws.ReadMessage()
	assert.Error(t, err, "expected NO message (timeout)")
}

func TestSimulationSubscribe(t *testing.T) {
	env := helperSetupSimHub(t)
	wsClient := helperDial(t, env, "sess-sim-1")
	srvConn := helperServerConn(t, env, "sess-sim-1")
	time.Sleep(50 * time.Millisecond)

	// Subscribe to simulation "sim-xyz" via HandleTextMessage (using server-side conn)
	subMsg := `{"type":"subscribe_simulation","simulation_id":"sim-xyz"}`
	env.hub.HandleTextMessage(srvConn, []byte(subMsg))
	time.Sleep(50 * time.Millisecond)

	// Send a protobuf Wrapper with SimulationId "sim-xyz" targeted at a
	// different session so the client only receives it via simulation routing
	wrapper := &gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-xyz",
		SessionId:    "other-session",
	}
	env.hub.HandleRemoteMessage(wrapper)

	// Client should receive the message via simulation routing
	helperExpectBinaryMessage(t, wsClient, 500*time.Millisecond)
}

func TestSimulationUnsubscribe(t *testing.T) {
	env := helperSetupSimHub(t)
	wsClient := helperDial(t, env, "sess-sim-unsub")
	srvConn := helperServerConn(t, env, "sess-sim-unsub")
	time.Sleep(50 * time.Millisecond)

	// Subscribe
	env.hub.HandleTextMessage(srvConn, []byte(`{"type":"subscribe_simulation","simulation_id":"sim-abc"}`))
	time.Sleep(50 * time.Millisecond)

	// Unsubscribe
	env.hub.HandleTextMessage(srvConn, []byte(`{"type":"unsubscribe_simulation","simulation_id":"sim-abc"}`))
	time.Sleep(50 * time.Millisecond)

	// Send a wrapper for "sim-abc" targeted at a non-existent session
	// so that session-based broadcast doesn't deliver it
	wrapper := &gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-abc",
		SessionId:    "nonexistent-session",
	}
	env.hub.HandleRemoteMessage(wrapper)

	// Client should NOT receive the message (no session match, no sim subscription)
	helperExpectNoMessage(t, wsClient, 200*time.Millisecond)
}

func TestSimulationRoutingDoesNotAffectSessionRouting(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a client to session "sess-A"
	wsA := helperDial(t, env, "sess-A")
	// Connect a client to session "sess-B" (should NOT receive sess-A's messages)
	wsB := helperDial(t, env, "sess-B")
	time.Sleep(100 * time.Millisecond)

	// Send a Wrapper with empty SimulationId but targeted at sess-A via SessionId
	wrapper := &gateway.Wrapper{
		Type:      "session_event",
		SessionId: "sess-A",
	}
	env.hub.HandleRemoteMessage(wrapper)

	// sess-A should receive it via session routing
	helperExpectBinaryMessage(t, wsA, 500*time.Millisecond)

	// sess-B should NOT receive it
	helperExpectNoMessage(t, wsB, 200*time.Millisecond)
}

func TestMultipleSimulationSubscriptions(t *testing.T) {
	env := helperSetupSimHub(t)
	wsClient := helperDial(t, env, "sess-multi-sim")
	srvConn := helperServerConn(t, env, "sess-multi-sim")
	time.Sleep(50 * time.Millisecond)

	// Subscribe to two simulations
	env.hub.HandleTextMessage(srvConn, []byte(`{"type":"subscribe_simulation","simulation_id":"sim-1"}`))
	env.hub.HandleTextMessage(srvConn, []byte(`{"type":"subscribe_simulation","simulation_id":"sim-2"}`))
	time.Sleep(50 * time.Millisecond)

	// Send wrapper for sim-1 (targeted at non-existent session to isolate sim routing)
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "event_1",
		SimulationId: "sim-1",
		SessionId:    "other-session",
	})
	helperExpectBinaryMessage(t, wsClient, 500*time.Millisecond)

	// Send wrapper for sim-2
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "event_2",
		SimulationId: "sim-2",
		SessionId:    "other-session",
	})
	helperExpectBinaryMessage(t, wsClient, 500*time.Millisecond)
}

func TestHubRun_DropsMessageWhenClientBufferFull(t *testing.T) {
	cfg := HubConfig{
		BroadcastBuffer:  100,
		SessionMsgBuffer: 100,
		RemoteMsgBuffer:  100,
		ClientSendBuffer: 1, // tiny buffer to force drops
	}
	h := NewHubWithConfig(cfg)

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		sessionID := r.URL.Query().Get("session_id")
		h.Register(sessionID, conn)
	}))
	defer server.Close()

	go h.Run()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http") + "?session_id=sess-drop"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	require.NoError(t, err)
	defer ws.Close()

	time.Sleep(50 * time.Millisecond) // let registration complete

	// Fill the client buffer (size 1) then send more -- extras should be dropped.
	// Send via sessionMsg to target the specific session.
	for i := 0; i < 5; i++ {
		h.SessionMsg() <- SessionMessage{
			SessionID: "sess-drop",
			Data:      []byte(fmt.Sprintf("msg-%d", i)),
		}
	}

	// The hub should not block or panic; it drops messages silently.
	time.Sleep(100 * time.Millisecond)
}

func TestHubRemoteMessage_ConcurrentFanOut(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect 10 sessions
	clients := make([]*websocket.Conn, 10)
	for i := 0; i < 10; i++ {
		clients[i] = helperDial(t, env, fmt.Sprintf("session-%d", i))
	}
	time.Sleep(100 * time.Millisecond)

	// Send 100 broadcast remote messages concurrently
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			wrapper := &gateway.Wrapper{
				Timestamp: fmt.Sprintf("2026-01-01T00:00:%02dZ", n%60),
				Type:      "json",
				Payload:   []byte(fmt.Sprintf(`{"n":%d}`, n)),
				Origin:    &gateway.Origin{Type: "agent", Id: "test"},
			}
			env.hub.HandleRemoteMessage(wrapper)
		}(i)
	}
	wg.Wait()

	// Each client should receive all 100 messages (order may vary).
	// Read concurrently across clients to avoid sequential timeout accumulation.
	var readWg sync.WaitGroup
	counts := make([]int, 10)
	for i, ws := range clients {
		readWg.Add(1)
		go func(idx int, conn *websocket.Conn) {
			defer readWg.Done()
			for {
				_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
				_, _, err := conn.ReadMessage()
				if err != nil {
					break
				}
				counts[idx]++
			}
		}(i, ws)
	}
	readWg.Wait()
	for i, count := range counts {
		assert.Equal(t, 100, count, "Client %d should receive all 100 messages", i)
	}
}

func TestSimulationRouting_ScalesWithReverseIndex(t *testing.T) {
	env := helperSetupSimHub(t)

	// Subscribe 100 clients to different simulations
	conns := make([]*websocket.Conn, 100)
	for i := 0; i < 100; i++ {
		sid := fmt.Sprintf("session-%d", i)
		conns[i] = helperDial(t, env, sid)
		// Subscribe even-numbered to sim-A, odd to sim-B
		simID := "sim-A"
		if i%2 == 1 {
			simID = "sim-B"
		}
		serverConn := helperServerConn(t, env, sid)
		env.hub.SubscribeSimulation(serverConn, simID)
	}
	time.Sleep(100 * time.Millisecond) // Let subscriptions process

	// Send message for sim-A, targeting a non-existent session so only
	// simulation-based routing delivers it (not broadcast or session match).
	wrapper := &gateway.Wrapper{
		Timestamp:    "2026-01-01T00:00:00Z",
		Type:         "json",
		Payload:      []byte(`{"sim":"A"}`),
		Origin:       &gateway.Origin{Type: "agent", Id: "test"},
		SimulationId: "sim-A",
		SessionId:    "nonexistent-session",
	}
	env.hub.HandleRemoteMessage(wrapper)

	// Even clients should receive, odd should not
	for i := 0; i < 100; i++ {
		if i%2 == 0 {
			msg := helperExpectBinaryMessage(t, conns[i], 2*time.Second)
			assert.NotEmpty(t, msg, "Client %d (sim-A) should receive", i)
		} else {
			helperExpectNoMessage(t, conns[i], 200*time.Millisecond)
		}
	}
}

func TestHubRemoteMessage_UsesPreSerializedBytes(t *testing.T) {
	env := helperSetupSimHub(t)
	ws := helperDial(t, env, "session-raw")
	time.Sleep(50 * time.Millisecond)

	wrapper := &gateway.Wrapper{
		Timestamp: "2026-01-01T00:00:00Z",
		Type:      "json",
		SessionId: "session-raw",
		Payload:   []byte(`{"text":"raw-bytes-test"}`),
		Origin:    &gateway.Origin{Type: "agent", Id: "test", SessionId: "session-raw"},
	}

	// Pre-serialize (this is what Redis would have)
	rawBytes, err := proto.Marshal(wrapper)
	require.NoError(t, err)

	// Send with raw bytes — Hub should use these directly, not re-marshal
	env.hub.HandleRemoteMessage(wrapper, rawBytes)

	// Client should receive the exact pre-serialized bytes
	received := helperExpectBinaryMessage(t, ws, 2*time.Second)
	assert.Equal(t, rawBytes, received, "Hub must forward pre-serialized bytes, not re-marshal")
}

// --- Global Observer Simulation Filtering Tests ---

func TestGlobalObserver_SimSubscription_FiltersOtherSims(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer (empty session ID)
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	// Subscribe the global observer to sim-A
	env.hub.SubscribeSimulation(srvConn, "sim-A")
	time.Sleep(50 * time.Millisecond)

	// Send a message for sim-B (which the global observer is NOT subscribed to)
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-B",
		SessionId:    "some-session",
	})

	// Global observer should NOT receive this message (subscribed to sim-A, not sim-B)
	helperExpectNoMessage(t, wsGlobal, 200*time.Millisecond)
}

func TestGlobalObserver_NoSubscriptions_ReceivesAll(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer with NO subscriptions
	wsGlobal := helperDial(t, env, "")
	time.Sleep(50 * time.Millisecond)

	// Send a message with a simulationId
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-X",
		SessionId:    "some-session",
	})

	// Global observer with no subscriptions should still receive all messages (backward compat)
	helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
}

func TestGlobalObserver_ReceivesSystemMessages(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer and subscribe to sim-A
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	env.hub.SubscribeSimulation(srvConn, "sim-A")
	time.Sleep(50 * time.Millisecond)

	// Send a system message (no simulationId)
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:      "system_event",
		SessionId: "some-session",
	})

	// Global observer should still receive system messages (no simId = pass through)
	helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
}

func TestGlobalObserver_ReceivesSubscribedSimMessages(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer and subscribe to sim-A
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	env.hub.SubscribeSimulation(srvConn, "sim-A")
	time.Sleep(50 * time.Millisecond)

	// Send a message for sim-A
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-A",
		SessionId:    "some-session",
	})

	// Global observer should receive this message (subscribed to sim-A)
	helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
}

func TestGlobalObserver_UnsubscribedSim_IsFiltered(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer (empty session ID)
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	// Subscribe then unsubscribe from sim-gone
	env.hub.SubscribeSimulation(srvConn, "sim-gone")
	time.Sleep(50 * time.Millisecond)
	env.hub.UnsubscribeSimulation(srvConn, "sim-gone")
	time.Sleep(50 * time.Millisecond)

	// Send a message with simulation_id=sim-gone targeted at another session
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-gone",
		SessionId:    "other-session",
	})

	// Should NOT be delivered — client explicitly unsubscribed
	helperExpectNoMessage(t, wsGlobal, 200*time.Millisecond)
}

func TestGlobalObserver_UnsubscribedAll_StillReceivesSystemMessages(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer, subscribe then unsubscribe
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	env.hub.SubscribeSimulation(srvConn, "sim-A")
	time.Sleep(50 * time.Millisecond)
	env.hub.UnsubscribeSimulation(srvConn, "sim-A")
	time.Sleep(50 * time.Millisecond)

	// Send a system message (no simulation_id)
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:      "system_event",
		SessionId: "any-session",
	})

	// System messages should still be delivered (no simId = pass through)
	helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
}

func TestGlobalObserver_ResubscribeDifferentSim(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	// Subscribe to sim-old, unsubscribe, then subscribe to sim-new
	env.hub.SubscribeSimulation(srvConn, "sim-old")
	time.Sleep(50 * time.Millisecond)
	env.hub.UnsubscribeSimulation(srvConn, "sim-old")
	time.Sleep(50 * time.Millisecond)
	env.hub.SubscribeSimulation(srvConn, "sim-new")
	time.Sleep(50 * time.Millisecond)

	// sim-old should be filtered (verified separately)
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-old",
		SessionId:    "other-session",
	})
	// Small delay to let the filtered message NOT arrive
	time.Sleep(100 * time.Millisecond)

	// sim-new should be delivered
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-new",
		SessionId:    "other-session",
	})

	// Read the one message that should arrive (sim-new). If sim-old leaked
	// through, we would get it first and the assertion on SimulationId would
	// catch it.
	data := helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
	var received gateway.Wrapper
	require.NoError(t, proto.Unmarshal(data, &received))
	assert.Equal(t, "sim-new", received.SimulationId, "received message from wrong simulation")
}

func TestGlobalObserver_UnsubscribedAll_NewSimPassesThrough(t *testing.T) {
	env := helperSetupSimHub(t)

	// Connect a global observer, subscribe then unsubscribe from sim-A
	wsGlobal := helperDial(t, env, "")
	srvConn := helperServerConn(t, env, "")
	time.Sleep(50 * time.Millisecond)

	env.hub.SubscribeSimulation(srvConn, "sim-old")
	time.Sleep(50 * time.Millisecond)
	env.hub.UnsubscribeSimulation(srvConn, "sim-old")
	time.Sleep(50 * time.Millisecond)

	// sim-old should be blocked
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-old",
		SessionId:    "other-session",
	})
	// Small delay to let the blocked message NOT arrive
	time.Sleep(100 * time.Millisecond)

	// sim-new should pass through — client has no subscriptions, only a
	// blocklist for sim-old. New simulations must be visible so the frontend
	// can discover the simulation_id and subscribe.
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-new",
		SessionId:    "other-session",
	})

	data := helperExpectBinaryMessage(t, wsGlobal, 500*time.Millisecond)
	var received gateway.Wrapper
	require.NoError(t, proto.Unmarshal(data, &received))
	assert.Equal(t, "sim-new", received.SimulationId,
		"New simulation messages must pass through blocklist-only state")
}

// staleRedisStore is a SubscriptionStore that always returns a fixed set of
// sessions from Lookup, simulating stale Redis data after an unsubscribe.
type staleRedisStore struct {
	NullSubscriptionStore
	staleSessions []string
}

func (s *staleRedisStore) Lookup(_ context.Context, _ string) ([]string, error) {
	return s.staleSessions, nil
}

func TestWritePump_SelfUnregistersOnWriteFailure(t *testing.T) {
	env := helperSetupSimHub(t)

	_ = helperDial(t, env, "sess-write-fail")
	srvConn := helperServerConn(t, env, "sess-write-fail")

	// Close the underlying TCP connection on the server side to guarantee
	// the next write by writePump fails immediately. Closing only the
	// client-side WebSocket is insufficient because TCP buffering may
	// absorb one or more writes before the server detects the broken pipe.
	srvConn.UnderlyingConn().Close()

	// Send a message to force writePump to encounter the write failure
	// immediately (rather than waiting for the 54-second ping ticker).
	env.hub.HandleRemoteMessage(&gateway.Wrapper{
		Type:      "test_event",
		SessionId: "sess-write-fail",
	})

	// writePump detects the failure and self-unregisters asynchronously
	assert.Eventually(t, func() bool {
		env.hub.mu.RLock()
		_, exists := env.hub.clients["sess-write-fail"]
		env.hub.mu.RUnlock()
		return !exists
	}, 2*time.Second, 50*time.Millisecond,
		"Client should be unregistered after write failure")
}

func TestCrossInstance_StaleRedis_DoesNotDeliverAfterUnsubscribe(t *testing.T) {
	store := &staleRedisStore{staleSessions: []string{"sess-stale"}}
	h := NewHub(WithSubscriptionStore(store))
	go h.Run()

	upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		sessionID := r.URL.Query().Get("sessionId")
		h.Register(sessionID, conn)
	}))
	defer server.Close()

	wsURL := strings.Replace(server.URL, "http", "ws", 1)
	ws, _, err := websocket.DefaultDialer.Dial(wsURL+"?sessionId=sess-stale", nil)
	require.NoError(t, err)
	defer ws.Close()
	time.Sleep(50 * time.Millisecond)

	// Client is NOT subscribed to any simulation locally.
	// Redis stale data says "sess-stale" is subscribed to everything.
	// Send a sim message targeted at a non-existent session.
	h.HandleRemoteMessage(&gateway.Wrapper{
		Type:         "test_event",
		SimulationId: "sim-stale",
		SessionId:    "nonexistent",
	})

	// Client should NOT receive the message because they have no local
	// simulation subscription, even though Redis says they do.
	helperExpectNoMessage(t, ws, 200*time.Millisecond)
}
