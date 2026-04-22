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
	"log"
	"sync"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/gorilla/websocket"
	"google.golang.org/protobuf/proto"
)

// HubConfig holds tunable buffer sizes for the Hub.
// Zero values are replaced with defaults.
type HubConfig struct {
	BroadcastBuffer  int // Default: 100000
	SessionMsgBuffer int // Default: 100000
	RemoteMsgBuffer  int // Default: 100000
	ClientSendBuffer int // Default: 100000
	RemoteWorkers    int // Default: 4
}

const defaultBufferSize = 100000

// remoteMessage bundles a gateway.Wrapper with optional pre-serialized bytes.
// When raw is non-nil (e.g., bytes from Redis PubSub), Hub.Run() uses them
// directly instead of re-marshaling, eliminating a redundant proto.Marshal.
type remoteMessage struct {
	wrapper *gateway.Wrapper
	raw     []byte // pre-serialized protobuf from Redis; nil = must marshal
}

// simSubscriptionMsg carries a simulation subscription request through a channel.
type simSubscriptionMsg struct {
	client       *client
	simulationID string
}

// Hub maintains the set of active clients and routes messages to them.
// Patterned after agentic-citizen's reliable routing hub.
type Hub struct {
	// Map of sessionID to a map of active connections and their send buffers.
	clients    map[string]map[*client]bool
	broadcast  chan []byte
	sessionMsg chan SessionMessage
	register   chan *client
	unregister chan *client
	mu         sync.RWMutex
	remoteMsg  chan *remoteMessage
	config     HubConfig

	// Simulation subscription routing
	simSubscriptions map[*client]map[string]bool // client -> set of simulation IDs (allowlist)
	simToClients     map[string]map[*client]bool // simID -> set of clients (reverse index)
	simBlocked       map[*client]map[string]bool // client -> set of blocked simulation IDs
	simSubscribe     chan simSubscriptionMsg
	simUnsubscribe   chan simSubscriptionMsg
	connToClient     map[*websocket.Conn]*client // reverse index for text message handling

	// Cross-instance subscription persistence (Redis-backed)
	subStore SubscriptionStore
}

type client struct {
	hub              *Hub
	sessionID        string
	conn             *websocket.Conn
	send             chan *wsMessage
	autoSubscribeSim string // simulation ID to auto-subscribe on register (empty = none)
}

type wsMessage struct {
	mType int
	data  []byte
}

type Registration struct {
	SessionID string
	Conn      *websocket.Conn
}

type SessionMessage struct {
	SessionID string
	Data      []byte
}

// GatewayOrigin identifies the source of a message in the system.
type GatewayOrigin struct {
	Type      string `json:"type"`                 // "agent", "client", "system"
	ID        string `json:"id"`                   // "planner", "tester-ui", "gateway"
	SessionID string `json:"session_id,omitempty"` // UUID
}

// GatewayMessage is the standardized JSON format sent over WebSockets.
type GatewayMessage struct {
	Origin      GatewayOrigin          `json:"origin"`
	Destination []string               `json:"destination"` // Array of target session UUIDs. Empty means broadcast.
	Status      string                 `json:"status"`      // e.g., "success", "error", "info"
	Type        string                 `json:"type"`        // "text", "json", "a2ui"
	Event       string                 `json:"event"`       // e.g., "narrative", "model_start", "tool_call"
	Data        interface{}            `json:"data"`
	Metadata    map[string]interface{} `json:"metadata,omitempty"`
}

func bufSize(v, fallback int) int {
	if v > 0 {
		return v
	}
	return fallback
}

// HubOption is a functional option for configuring the Hub.
type HubOption func(*Hub)

// WithSubscriptionStore sets the cross-instance subscription store.
// When nil or not provided, a NullSubscriptionStore is used.
func WithSubscriptionStore(store SubscriptionStore) HubOption {
	return func(h *Hub) {
		if store != nil {
			h.subStore = store
		}
	}
}

// WithRemoteWorkers sets the number of goroutines that process inbound
// Redis messages before fan-out to WebSocket clients. Default is 4.
// Higher values improve throughput at 1000+ concurrent sessions.
func WithRemoteWorkers(n int) HubOption {
	return func(h *Hub) {
		if n > 0 {
			h.config.RemoteWorkers = n
		}
	}
}

// NewHub creates a Hub with default buffer sizes.
func NewHub(opts ...HubOption) *Hub {
	return NewHubWithConfig(HubConfig{}, opts...)
}

// NewHubWithConfig creates a Hub with the given buffer configuration.
func NewHubWithConfig(cfg HubConfig, opts ...HubOption) *Hub {
	h := &Hub{
		broadcast:        make(chan []byte, bufSize(cfg.BroadcastBuffer, defaultBufferSize)),
		sessionMsg:       make(chan SessionMessage, bufSize(cfg.SessionMsgBuffer, defaultBufferSize)),
		register:         make(chan *client),
		unregister:       make(chan *client),
		clients:          make(map[string]map[*client]bool),
		remoteMsg:        make(chan *remoteMessage, bufSize(cfg.RemoteMsgBuffer, defaultBufferSize)),
		config:           cfg,
		simSubscriptions: make(map[*client]map[string]bool),
		simToClients:     make(map[string]map[*client]bool),
		simBlocked:       make(map[*client]map[string]bool),
		simSubscribe:     make(chan simSubscriptionMsg),
		simUnsubscribe:   make(chan simSubscriptionMsg),
		connToClient:     make(map[*websocket.Conn]*client),
		subStore:         &NullSubscriptionStore{},
	}
	for _, opt := range opts {
		opt(h)
	}
	return h
}

func (h *Hub) HandleRemoteMessage(wrapper *gateway.Wrapper, rawBytes ...[]byte) {
	log.Printf("Hub: HandleRemoteMessage received (type=%s, event=%s, session=%s)", wrapper.Type, wrapper.Event, wrapper.SessionId)
	rm := &remoteMessage{wrapper: wrapper}
	if len(rawBytes) > 0 && rawBytes[0] != nil {
		rm.raw = rawBytes[0]
	}
	h.remoteMsg <- rm
}

// Register adds a WebSocket connection to the Hub for message routing.
// An optional simulationID triggers auto-subscription on registration,
// avoiding the race between Register and SubscribeSimulation.
func (h *Hub) Register(sessionID string, conn *websocket.Conn, simulationID ...string) {
	c := &client{
		hub:       h,
		sessionID: sessionID,
		conn:      conn,
		send:      make(chan *wsMessage, bufSize(h.config.ClientSendBuffer, defaultBufferSize)),
	}
	if len(simulationID) > 0 && simulationID[0] != "" {
		c.autoSubscribeSim = simulationID[0]
	}
	h.register <- c
	go c.writePump()
}

func (h *Hub) Unregister(sessionID string, conn *websocket.Conn) {
	h.mu.RLock()
	if conns, ok := h.clients[sessionID]; ok {
		for c := range conns {
			if c.conn == conn {
				h.mu.RUnlock()
				h.unregister <- c
				return
			}
		}
	}
	h.mu.RUnlock()
}

func (h *Hub) Broadcast() chan<- []byte {
	return h.broadcast
}

// Publish injects a raw payload into the broadcast stream.
// It automatically appends a newline for NDJ (Newline-Delimited JSON) support.
func (h *Hub) Publish(data []byte) {
	h.broadcast <- append(data, '\n')
}

func (h *Hub) SessionMsg() chan<- SessionMessage {
	return h.sessionMsg
}

func (h *Hub) Run() {
	// Start worker pool for remote message processing.
	// Workers read directly from h.remoteMsg, which acts as a work queue.
	numWorkers := h.config.RemoteWorkers
	if numWorkers <= 0 {
		numWorkers = 4
	}
	for i := 0; i < numWorkers; i++ {
		go func() {
			for rm := range h.remoteMsg {
				h.processRemoteMessage(rm)
			}
		}()
	}

	for {
		select {
		case c := <-h.register:
			h.mu.Lock()
			if h.clients[c.sessionID] == nil {
				h.clients[c.sessionID] = make(map[*client]bool)
			}
			h.clients[c.sessionID][c] = true
			h.connToClient[c.conn] = c

			// Process auto-subscription inline (same Run() tick) to avoid
			// the race between Register and SubscribeSimulation. We mutate
			// the maps directly since we hold the write lock.
			if c.autoSubscribeSim != "" {
				simID := c.autoSubscribeSim
				if h.simSubscriptions[c] == nil {
					h.simSubscriptions[c] = make(map[string]bool)
				}
				h.simSubscriptions[c][simID] = true
				if h.simToClients[simID] == nil {
					h.simToClients[simID] = make(map[*client]bool)
				}
				h.simToClients[simID][c] = true
				sessionID := c.sessionID
				go func() {
					ctx, cancel := context.WithTimeout(context.Background(), subscriptionTimeout)
					defer cancel()
					logSubscriptionError("Subscribe", h.subStore.Subscribe(ctx, simID, sessionID))
				}()
				log.Printf("Client auto-subscribed to simulation %s", simID)
			}
			h.mu.Unlock()
			log.Printf("Client registered for session %s", c.sessionID)

		case c := <-h.unregister:
			h.mu.Lock()
			if conns, ok := h.clients[c.sessionID]; ok {
				if _, ok := conns[c]; ok {
					delete(conns, c)
					close(c.send)
				}
				if len(conns) == 0 {
					delete(h.clients, c.sessionID)
				}
			}
			// Clean up reverse index entries for this client
			if subs, ok := h.simSubscriptions[c]; ok {
				for simID := range subs {
					if clients, ok := h.simToClients[simID]; ok {
						delete(clients, c)
						if len(clients) == 0 {
							delete(h.simToClients, simID)
						}
					}
				}
			}
			delete(h.simSubscriptions, c)
			delete(h.simBlocked, c)
			delete(h.connToClient, c.conn)
			sessionID := c.sessionID
			h.mu.Unlock()
			// Async Redis cleanup — non-blocking, non-fatal
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), subscriptionTimeout)
				defer cancel()
				logSubscriptionError("UnsubscribeAll", h.subStore.UnsubscribeAll(ctx, sessionID))
			}()
			log.Printf("Client unregistered from session %s", sessionID)

		case sub := <-h.simSubscribe:
			h.mu.Lock()
			if h.simSubscriptions[sub.client] == nil {
				h.simSubscriptions[sub.client] = make(map[string]bool)
			}
			h.simSubscriptions[sub.client][sub.simulationID] = true
			// Reverse index
			if h.simToClients[sub.simulationID] == nil {
				h.simToClients[sub.simulationID] = make(map[*client]bool)
			}
			h.simToClients[sub.simulationID][sub.client] = true
			// Clear blocklist — client is now in allowlist mode
			delete(h.simBlocked, sub.client)
			sessionID := sub.client.sessionID
			simID := sub.simulationID
			h.mu.Unlock()
			// Async Redis persistence — non-blocking, non-fatal
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), subscriptionTimeout)
				defer cancel()
				logSubscriptionError("Subscribe", h.subStore.Subscribe(ctx, simID, sessionID))
			}()
			log.Printf("Client subscribed to simulation %s", sub.simulationID)

		case unsub := <-h.simUnsubscribe:
			h.mu.Lock()
			if subs, ok := h.simSubscriptions[unsub.client]; ok {
				delete(subs, unsub.simulationID)
				if len(subs) == 0 {
					delete(h.simSubscriptions, unsub.client)
				}
			}
			// Reverse index
			if clients, ok := h.simToClients[unsub.simulationID]; ok {
				delete(clients, unsub.client)
				if len(clients) == 0 {
					delete(h.simToClients, unsub.simulationID)
				}
			}
			// Add to blocklist — prevents this sim's messages from leaking
			// through Phase 1 global observer delivery after unsubscribe.
			if h.simBlocked[unsub.client] == nil {
				h.simBlocked[unsub.client] = make(map[string]bool)
			}
			h.simBlocked[unsub.client][unsub.simulationID] = true
			sessionID := unsub.client.sessionID
			simID := unsub.simulationID
			h.mu.Unlock()
			// Async Redis cleanup — non-blocking, non-fatal
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), subscriptionTimeout)
				defer cancel()
				logSubscriptionError("Unsubscribe", h.subStore.Unsubscribe(ctx, simID, sessionID))
			}()
			log.Printf("Client unsubscribed from simulation %s", unsub.simulationID)

		case message := <-h.broadcast:
			h.mu.RLock()
			for _, conns := range h.clients {
				for c := range conns {
					select {
					case c.send <- &wsMessage{mType: websocket.TextMessage, data: message}:
					default:
						// Non-blocking: drop message for this specific client if buffer is full
						log.Printf("Hub: dropped broadcast for session %s (buffer full)", c.sessionID)
					}
				}
			}
			h.mu.RUnlock()

		case sm := <-h.sessionMsg:
			h.mu.RLock()
			if conns, ok := h.clients[sm.SessionID]; ok {
				for c := range conns {
					select {
					case c.send <- &wsMessage{mType: websocket.TextMessage, data: sm.Data}:
					default:
						log.Printf("Hub: dropped session message for session %s (buffer full)", c.sessionID)
					}
				}
			}
			h.mu.RUnlock()
		}
	}
}

// processRemoteMessage handles a single remote message fan-out.
// Called from worker pool goroutines — uses RLock since it only reads client maps.
func (h *Hub) processRemoteMessage(rm *remoteMessage) {
	// Use pre-serialized bytes when available (e.g., from Redis PubSub),
	// falling back to proto.Marshal only when raw bytes weren't provided.
	var data []byte
	if rm.raw != nil {
		data = rm.raw
	} else {
		var err error
		data, err = proto.Marshal(rm.wrapper)
		if err != nil {
			log.Printf("Hub: failed to marshal remote message: %v", err)
			return
		}
	}

	// Determine target sessions based on the protobuf Wrapper
	var targetSessions []string
	if len(rm.wrapper.Destination) > 0 {
		targetSessions = rm.wrapper.Destination
	} else if rm.wrapper.SessionId != "" {
		targetSessions = []string{rm.wrapper.SessionId}
	} else if rm.wrapper.Origin != nil && rm.wrapper.Origin.SessionId != "" {
		targetSessions = []string{rm.wrapper.Origin.SessionId}
	}

	// Track which clients already received this message to avoid double-delivery
	delivered := make(map[*client]bool)

	h.mu.RLock()

	// 1. Fan-out to global observers, respecting simulation subscriptions.
	if globalConns, ok := h.clients[""]; ok {
		simID := rm.wrapper.SimulationId
		for c := range globalConns {
			// If the message has a simulationId, apply subscription filtering:
			// 1. If client has active subscriptions → allowlist mode (only matching sims)
			// 2. If client has no subscriptions but has a blocklist → skip blocked sims
			// 3. If client has neither → deliver all (global observers)
			if simID != "" {
				if subs, hasSubs := h.simSubscriptions[c]; hasSubs && len(subs) > 0 {
					if !subs[simID] {
						continue // Allowlist mode: not subscribed to this sim
					}
				} else if blocked, hasBlocked := h.simBlocked[c]; hasBlocked && blocked[simID] {
					continue // Blocklist mode: this sim was explicitly unsubscribed
				}
			}
			select {
			case c.send <- &wsMessage{mType: websocket.BinaryMessage, data: data}:
				delivered[c] = true
			default:
				log.Printf("Hub: dropped remote message for global observer (buffer full)")
			}
		}
	}

	// 2. Route to targeted sessions (or broadcast to all if no target specified)
	if len(targetSessions) == 0 {
		// Broadcast to all active sessions (skip "" since we already sent to it)
		for sid, conns := range h.clients {
			if sid == "" {
				continue
			}
			for c := range conns {
				select {
				case c.send <- &wsMessage{mType: websocket.BinaryMessage, data: data}:
					delivered[c] = true
				default:
					log.Printf("Hub: dropped remote message for session %s (buffer full)", c.sessionID)
				}
			}
		}
	} else {
		// Targeted routing
		for _, sid := range targetSessions {
			if sid == "" {
				continue // Handled by global block
			}
			if conns, ok := h.clients[sid]; ok {
				for c := range conns {
					select {
					case c.send <- &wsMessage{mType: websocket.BinaryMessage, data: data}:
						delivered[c] = true
					default:
						log.Printf("Hub: dropped targeted remote message for session %s (buffer full)", c.sessionID)
					}
				}
			}
		}
	}

	// 3. Simulation-based routing: O(1) reverse index lookup by simulation_id
	if rm.wrapper.SimulationId != "" {
		if clients, ok := h.simToClients[rm.wrapper.SimulationId]; ok {
			for c := range clients {
				if !delivered[c] {
					select {
					case c.send <- &wsMessage{mType: websocket.BinaryMessage, data: data}:
						delivered[c] = true
					default:
						log.Printf("Hub: dropped sim-routed message for session %s (buffer full)", c.sessionID)
					}
				}
			}
		}

		// 3b. Cross-instance: query Redis for remote subscribers whose
		// sessions are locally connected but not in the local simToClients map
		// (they reconnected to this instance without re-subscribing locally).
		// Release RLock before the network call to avoid blocking
		// Register/Unregister operations during Redis latency spikes.
		simID := rm.wrapper.SimulationId
		h.mu.RUnlock()

		ctx, cancel := context.WithTimeout(context.Background(), subscriptionTimeout)
		remoteSessions, err := h.subStore.Lookup(ctx, simID)
		cancel()

		h.mu.RLock()
		if err == nil && len(remoteSessions) > 0 {
			for _, sid := range remoteSessions {
				if conns, ok := h.clients[sid]; ok {
					for c := range conns {
						if !delivered[c] {
							// Guard: only deliver if the client is locally subscribed
							// to this simulation. Redis data may be stale after an
							// async unsubscribe.
							if subs, hasSubs := h.simSubscriptions[c]; !hasSubs || !subs[simID] {
								continue
							}
							select {
							case c.send <- &wsMessage{mType: websocket.BinaryMessage, data: data}:
								delivered[c] = true
							default:
								log.Printf("Hub: dropped cross-instance sim message for session %s (buffer full)", c.sessionID)
							}
						}
					}
				}
			}
		}
	}

	h.mu.RUnlock()
}

// textFrameMsg is the JSON structure for subscription text frames.
type textFrameMsg struct {
	Type         string `json:"type"`
	SimulationID string `json:"simulation_id"`
}

// HandleTextMessage parses a JSON text frame from a WebSocket connection and
// routes subscription requests through the Hub's event loop channels.
// Must be called from a goroutine OTHER than Run() to avoid deadlock.
func (h *Hub) HandleTextMessage(conn *websocket.Conn, data []byte) {
	h.mu.RLock()
	c, ok := h.connToClient[conn]
	h.mu.RUnlock()
	if !ok {
		log.Printf("Hub: text message from unknown connection (ignored)")
		return
	}

	var msg textFrameMsg
	if err := json.Unmarshal(data, &msg); err != nil {
		log.Printf("Hub: failed to parse text message: %v", err)
		return
	}
	switch msg.Type {
	case "subscribe_simulation":
		if msg.SimulationID != "" {
			h.simSubscribe <- simSubscriptionMsg{client: c, simulationID: msg.SimulationID}
		}
	case "unsubscribe_simulation":
		if msg.SimulationID != "" {
			h.simUnsubscribe <- simSubscriptionMsg{client: c, simulationID: msg.SimulationID}
		}
	default:
		log.Printf("Hub: unknown text message type: %s", msg.Type)
	}
}

// SubscribeSimulation subscribes a client (identified by its WebSocket connection)
// to a simulation ID. Messages with a matching SimulationId will be delivered.
func (h *Hub) SubscribeSimulation(conn *websocket.Conn, simulationID string) {
	h.mu.RLock()
	c, ok := h.connToClient[conn]
	h.mu.RUnlock()
	if !ok || simulationID == "" {
		return
	}
	h.simSubscribe <- simSubscriptionMsg{client: c, simulationID: simulationID}
}

// UnsubscribeSimulation removes a client's subscription to a simulation ID.
func (h *Hub) UnsubscribeSimulation(conn *websocket.Conn, simulationID string) {
	h.mu.RLock()
	c, ok := h.connToClient[conn]
	h.mu.RUnlock()
	if !ok || simulationID == "" {
		return
	}
	h.simUnsubscribe <- simSubscriptionMsg{client: c, simulationID: simulationID}
}

func (c *client) writePump() {
	ticker := time.NewTicker(54 * time.Second)
	hubClosed := false // tracks whether Hub already closed our send channel
	defer func() {
		ticker.Stop()
		c.conn.Close()
		if !hubClosed {
			// Self-unregister: notify the Hub so it cleans up maps and
			// simulation subscriptions. Blocking send is safe here because
			// Run() loops forever and always drains unregister. The hubClosed
			// flag prevents sending when the Hub already initiated the
			// unregister (which closed c.send). Run() checks existence
			// before acting, so duplicate unregisters are no-ops.
			c.hub.unregister <- c
		}
	}()
	for {
		select {
		case message, ok := <-c.send:
			if !ok {
				// Hub closed the channel via Unregister.
				hubClosed = true
				_ = c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}

			_ = c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.conn.WriteMessage(message.mType, message.data); err != nil {
				return
			}
		case <-ticker.C:
			_ = c.conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// SendMessage sends a JSON-wrapped message to a specific session.
func (h *Hub) SendMessage(sessionID string, msgType string, event string, content interface{}) {
	msg := GatewayMessage{
		Origin: GatewayOrigin{
			Type: "system",
			ID:   "gateway",
		},
		Destination: []string{sessionID},
		Status:      "success",
		Type:        msgType,
		Event:       event,
		Data:        content,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		log.Printf("Failed to marshal hub message: %v", err)
		return
	}
	h.sessionMsg <- SessionMessage{
		SessionID: sessionID,
		Data:      data,
	}
}
