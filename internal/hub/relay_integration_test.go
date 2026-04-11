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
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestNarrativeRelay(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// 1. Setup Redis (miniredis — no Docker required)
	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()

	// 2. Setup Hub and Switchboard
	h := NewHub()
	go h.Run()

	sb := NewSwitchboard(rdb, "test-gateway", h, nil)
	go func() {
		if err := sb.Start(ctx); err != nil && err != context.Canceled {
			t.Logf("Switchboard error: %v", err)
		}
	}()

	// 3. Setup Mock Client
	srv := httptest.NewServer(&HubHandler{hub: h})
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/ws?sessionId=test-session"
	dialer := websocket.DefaultDialer
	conn, _, err := dialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("Failed to dial WS: %v", err)
	}
	defer conn.Close()

	// Give registration a moment
	time.Sleep(100 * time.Millisecond)

	// 4. Simulate Agent publishing a JSON payload via Redis wrapper
	payloadJSON := `{"session_id":"test-session","text":"Hello from the agent!","emotion":"happy"}`

	wrapper := &gateway.Wrapper{
		Timestamp:   time.Now().Format(time.RFC3339),
		Type:        "json",
		Event:       "narrative",
		SessionId:   "test-session",
		Destination: []string{"test-session"},
		Payload:     []byte(payloadJSON),
	}
	wrapperData, _ := proto.Marshal(wrapper)

	// Publish to Switchboard channel
	if err := rdb.Publish(ctx, "gateway:broadcast", wrapperData).Err(); err != nil {
		t.Fatalf("Failed to publish to Redis: %v", err)
	}

	_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	mt, msg, err := conn.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, websocket.BinaryMessage, mt)

	var received gateway.Wrapper
	err = proto.Unmarshal(msg, &received)
	require.NoError(t, err)

	assert.Equal(t, "json", received.Type)
	assert.Equal(t, "narrative", received.Event)

	var dataMap map[string]interface{}
	err = json.Unmarshal(received.Payload, &dataMap)
	require.NoError(t, err)

	assert.Equal(t, "Hello from the agent!", dataMap["text"])
	assert.Equal(t, "happy", dataMap["emotion"])
}

// Mock Handler for Hub
type HubHandler struct {
	hub *Hub
}

func (h *HubHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	sessionID := r.URL.Query().Get("sessionId")
	upgrader := websocket.Upgrader{
		CheckOrigin: func(r *http.Request) bool { return true },
	}
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("Upgrade failed: %v", err)
		return
	}
	h.hub.Register(sessionID, conn)
}

func TestNarrativeRoutingTargeted(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	h := NewHub()
	go h.Run()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()
	sb := NewSwitchboard(rdb, "test-gw", h, nil)
	go func() {
		if err := sb.Start(ctx); err != nil && err != context.Canceled {
			t.Logf("Switchboard error: %v", err)
		}
	}()

	// Session A
	srvA := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
		conn, _ := upgrader.Upgrade(w, r, nil)
		h.Register("sess-A", conn)
	}))
	defer srvA.Close()
	wsURL_A := "ws" + srvA.URL[4:]
	connA, _, _ := websocket.DefaultDialer.Dial(wsURL_A, nil)
	defer connA.Close()

	// Session B
	srvB := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
		conn, _ := upgrader.Upgrade(w, r, nil)
		h.Register("sess-B", conn)
	}))
	defer srvB.Close()
	wsURL_B := "ws" + srvB.URL[4:]
	connB, _, _ := websocket.DefaultDialer.Dial(wsURL_B, nil)
	defer connB.Close()

	// Give time for Pub/Sub to settle
	time.Sleep(200 * time.Millisecond)

	// Publish narrative for Session A
	payloadJSON := `{"session_id":"sess-A","text":"Private Message for A"}`
	wrapper := &gateway.Wrapper{
		Type:        "json",
		Event:       "narrative",
		SessionId:   "sess-A",
		Destination: []string{"sess-A"},
		Payload:     []byte(payloadJSON),
	}
	_ = sb.Broadcast(ctx, wrapper)

	// Session A SHOULD receive it
	_ = connA.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, msgA, err := connA.ReadMessage()
	assert.NoError(t, err, "Session A should have received the narrative")
	assert.Contains(t, string(msgA), "Private Message for A")

	// Session B SHOULD NOT receive it (fan-out bug is fixed)
	_ = connB.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
	_, _, err = connB.ReadMessage()
	assert.Error(t, err, "Session B should NOT receive Session A's narrative (fan-out fixed)")
}

func TestGlobalObserverRelay(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	h := NewHub()
	go h.Run()

	s := miniredis.RunT(t)
	rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer rdb.Close()
	sb := NewSwitchboard(rdb, "test-gw", h, nil)
	go func() {
		if err := sb.Start(ctx); err != nil && err != context.Canceled {
			t.Logf("Switchboard error: %v", err)
		}
	}()

	// Anonymous Observer Session (no identity)
	srvA := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
		conn, _ := upgrader.Upgrade(w, r, nil)
		// Simulating the missing query param fallback fix where "" is passed
		h.Register("", conn)
	}))
	defer srvA.Close()
	wsURL_A := "ws" + srvA.URL[4:]
	connA, _, _ := websocket.DefaultDialer.Dial(wsURL_A, nil)
	defer connA.Close()

	// Give time for Pub/Sub to settle
	time.Sleep(200 * time.Millisecond)

	// Publish narrative for random session
	payloadJSON := `{"session_id":"some-random-runner","text":"Pulse message"}`
	wrapper := &gateway.Wrapper{
		Type:        "json",
		Event:       "narrative",
		SessionId:   "some-random-runner",
		Destination: []string{"some-random-runner"},
		Payload:     []byte(payloadJSON),
	}
	_ = sb.Broadcast(ctx, wrapper)

	// Observer SHOULD receive it even though it's not the destination
	_ = connA.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, msgA, err := connA.ReadMessage()
	assert.NoError(t, err, "Observer should have received the narrative")
	assert.Contains(t, string(msgA), "Pulse message")
}
