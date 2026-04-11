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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/hashicorp/go-retryablehttp"
	"github.com/redis/go-redis/v9"
	"golang.org/x/oauth2/google"
	"google.golang.org/protobuf/proto"
)

// DefaultSpawnShards is the number of shards used for spawn queue distribution.
// Each agent type's spawn queue is split into this many sub-queues to prevent
// competing-consumer hotspots when multiple dispatcher instances BLPOP.
const DefaultSpawnShards = 8

// SpawnQueueName returns the sharded spawn queue name for a given session.
// Uses FNV-1a hash for deterministic, even distribution across shards.
func SpawnQueueName(agentType, sessionID string, numShards int) string {
	if numShards <= 0 {
		numShards = DefaultSpawnShards
	}
	h := fnv.New32a()
	h.Write([]byte(sessionID))
	shard := int(h.Sum32()) % numShards
	return fmt.Sprintf("simulation:spawns:%s:%d", agentType, shard)
}

// newGCPClient is the function used to create GCP-authenticated HTTP clients.
// It is a variable to allow replacement in tests.
var newGCPClient = func(ctx context.Context, scopes ...string) (*http.Client, error) {
	return google.DefaultClient(ctx, scopes...)
}

// QueueItem pairs a Redis queue name with a JSON-serializable payload
// for use in batch enqueue operations.
type QueueItem struct {
	Queue string
	Data  interface{}
}

// Switchboard handles distributed message fan-out.
type Switchboard interface {
	Broadcast(ctx context.Context, wrapper *gateway.Wrapper) error
	EnqueueOrchestration(ctx context.Context, queue string, event interface{}) error
	BatchEnqueueOrchestration(ctx context.Context, items []QueueItem) error
	PublishOrchestration(ctx context.Context, channel string, event interface{}) error
	DispatchToAgent(ctx context.Context, agentType string, event interface{}) error
	PokeAgent(ctx context.Context, agentType string, event interface{}) error
	FlushQueues(ctx context.Context) (int, error)
	Ping(ctx context.Context) error
	Start(ctx context.Context) error
	Channel() string
}

// RedisSwitchboard handles distributed message fan-out via Redis.
type RedisSwitchboard struct {
	client         *redis.Client
	gatewayID      string
	localHub       *Hub
	channel        string
	catalog        *agent.Catalog
	registry       session.DistributedRegistry // Session-aware routing
	httpClient     *http.Client                // Plain HTTP client for subscriber pokes
	callableClient *http.Client                // Retryable HTTP client for callable dispatch
	gcpClient      *http.Client                // Authenticated + retryable client for Agent Engine callable agents
	gcpClientErr   error
}

// NewSwitchboard creates a new distributed switchboard (backward compatible, no registry).
func NewSwitchboard(client *redis.Client, gatewayID string, localHub *Hub, catalog *agent.Catalog) Switchboard {
	return NewSwitchboardWithRegistry(client, gatewayID, localHub, catalog, nil)
}

// NewSwitchboardWithRegistry creates a distributed switchboard with session-aware routing.
func NewSwitchboardWithRegistry(client *redis.Client, gatewayID string, localHub *Hub, catalog *agent.Catalog, registry session.DistributedRegistry) Switchboard {
	// Create a retryable HTTP client for callable dispatch
	retryClient := retryablehttp.NewClient()
	retryClient.RetryMax = 3
	retryClient.RetryWaitMin = 500 * time.Millisecond
	retryClient.RetryWaitMax = 5 * time.Second
	retryClient.Logger = nil // Suppress retryablehttp's default logging
	callableHTTP := retryClient.StandardClient()
	callableHTTP.Timeout = 5 * time.Minute

	// Pre-create a GCP-authenticated HTTP client for Agent Engine calls.
	// This wraps the retryable transport with GCP OAuth.
	gcpClient, err := newGCPClient(context.Background(),
		"https://www.googleapis.com/auth/cloud-platform",
	)
	if err != nil {
		log.Printf("Switchboard: WARNING — failed to create GCP auth client: %v (Agent Engine auth disabled, falling back to plain callable client)", err)
	}
	if gcpClient != nil {
		// Agent Engine agents (especially planner_with_eval) execute
		// multi-step tool chains (evaluation pipeline,
		// inter-agent A2A calls) that take 1-3 minutes. The context
		// timeout in dispatchCallable is 5 minutes; the client timeout
		// must match or the client cancels the request prematurely.
		gcpClient.Timeout = 5 * time.Minute
	}

	return &RedisSwitchboard{
		client:    client,
		gatewayID: gatewayID,
		localHub:  localHub,
		channel:   "gateway:broadcast",
		catalog:   catalog,
		registry:  registry,
		httpClient: &http.Client{
			Timeout: 5 * time.Second,
		},
		callableClient: callableHTTP,
		gcpClient:      gcpClient,
		gcpClientErr:   err,
	}
}

// Ping checks the Redis connection.
func (s *RedisSwitchboard) Ping(ctx context.Context) error {
	return s.client.Ping(ctx).Err()
}

// Channel returns the broadcast channel name.
func (s *RedisSwitchboard) Channel() string {
	return s.channel
}

// FlushQueues scans for simulation:spawns:* keys and deletes them in a
// pipeline. Returns the number of queue keys deleted.
func (s *RedisSwitchboard) FlushQueues(ctx context.Context) (int, error) {
	var keys []string
	var cursor uint64
	for {
		var batch []string
		var err error
		batch, cursor, err = s.client.Scan(ctx, cursor, "simulation:spawns:*", 100).Result()
		if err != nil {
			return 0, fmt.Errorf("scanning spawn queues: %w", err)
		}
		keys = append(keys, batch...)
		if cursor == 0 {
			break
		}
	}

	if len(keys) == 0 {
		return 0, nil
	}

	pipe := s.client.Pipeline()
	for _, key := range keys {
		pipe.Del(ctx, key)
	}
	_, err := pipe.Exec(ctx)
	if err != nil {
		return 0, fmt.Errorf("deleting spawn queues: %w", err)
	}

	return len(keys), nil
}

// Start listens for remote broadcast messages with automatic reconnection.
// If the Redis subscription drops, it retries with exponential backoff
// to ensure cross-instance message delivery is not permanently lost.
func (s *RedisSwitchboard) Start(ctx context.Context) error {
	backoff := 500 * time.Millisecond
	maxBackoff := 30 * time.Second

	for {
		err := s.listenBroadcasts(ctx)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		log.Printf("Switchboard: Redis subscription lost: %v — reconnecting in %v", err, backoff)
		select {
		case <-time.After(backoff):
			backoff *= 2
			if backoff > maxBackoff {
				backoff = maxBackoff
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// listenBroadcasts subscribes to the Redis broadcast channel and forwards
// messages to the local Hub. Returns when the subscription fails or the
// channel closes.
func (s *RedisSwitchboard) listenBroadcasts(ctx context.Context) error {
	pubsub := s.client.Subscribe(ctx, s.channel)
	defer pubsub.Close()

	// Verify the subscription is active before entering the read loop
	if _, err := pubsub.Receive(ctx); err != nil {
		return fmt.Errorf("subscribe confirmation failed: %w", err)
	}
	log.Printf("Switchboard: subscribed to Redis channel %q", s.channel)

	ch := pubsub.Channel()
	for {
		select {
		case msg := <-ch:
			if msg == nil {
				return fmt.Errorf("Redis subscription channel closed")
			}
			rawBytes := []byte(msg.Payload)
			var wrapper gateway.Wrapper
			if err := proto.Unmarshal(rawBytes, &wrapper); err != nil {
				log.Printf("Switchboard: failed to unmarshal Redis broadcast: %v", err)
				continue
			}
			log.Printf("Switchboard: received Redis broadcast (type=%s, event=%s, session=%s), forwarding to Hub", wrapper.Type, wrapper.Event, wrapper.SessionId)
			// All messages flow as binary protobuf gateway.Wrapper
			// through HandleRemoteMessage.
			// UI clients decode protobuf directly (one format end-to-end).
			// Pass raw bytes to skip redundant proto.Marshal in Hub.Run().
			s.localHub.HandleRemoteMessage(&wrapper, rawBytes)
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

// Broadcast sends a message to all instances.
func (s *RedisSwitchboard) Broadcast(ctx context.Context, wrapper *gateway.Wrapper) error {
	data, err := proto.Marshal(wrapper)
	if err != nil {
		return err
	}
	return s.client.Publish(ctx, s.channel, data).Err()
}

// EnqueueOrchestration sends a JSON-encoded event to a Redis list for one-to-one delivery.
func (s *RedisSwitchboard) EnqueueOrchestration(ctx context.Context, queue string, event interface{}) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}
	return s.client.RPush(ctx, queue, data).Err()
}

// BatchEnqueueOrchestration sends multiple JSON-encoded events to Redis lists
// in a single pipeline, reducing round-trips from N to 1 during spawn bursts.
func (s *RedisSwitchboard) BatchEnqueueOrchestration(ctx context.Context, items []QueueItem) error {
	if len(items) == 0 {
		return nil
	}
	pipe := s.client.Pipeline()
	for _, item := range items {
		data, err := json.Marshal(item.Data)
		if err != nil {
			return err
		}
		pipe.RPush(ctx, item.Queue, data)
	}
	_, err := pipe.Exec(ctx)
	return err
}

// PublishOrchestration sends a JSON-encoded event to the orchestration Pub/Sub channel
// and dispatches to agents based on session-aware routing:
//   - If a registry is available, only agent types with active sessions are poked
//   - All agents receive /orchestration pokes (subscriber and callable alike)
//   - A2A message/send is reserved for targeted DispatchToAgent only
func (s *RedisSwitchboard) PublishOrchestration(ctx context.Context, channel string, event interface{}) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}

	// 1. Performance Path: Redis Pub/Sub (subscriber agents listen here)
	if err := s.client.Publish(ctx, channel, data).Err(); err != nil {
		log.Printf("Switchboard: Redis PublishOrchestration failed: %v", err)
	}

	// 2. Session-Aware Dispatch: only poke agent types with active sessions
	if s.catalog != nil {
		agents, err := s.catalog.DiscoverAgents()
		if err != nil {
			log.Printf("Switchboard: catalog discovery failed: %v", err)
			return nil
		}

		if s.registry != nil {
			// Session-aware: only dispatch to agent types that have active sessions
			activeTypes, err := s.registry.ActiveAgentTypes(ctx)
			if err != nil {
				log.Printf("Switchboard: ActiveAgentTypes failed: %v", err)
				return nil
			}
			for _, agentType := range activeTypes {
				card, ok := agents[agentType]
				if !ok || card.URL == "" {
					continue
				}
				// Route by URL type:
				//   - Agent Engine: A2A message/send (no /orchestration endpoint)
				//   - All local agents: HTTP poke to /orchestration via BaseURL
				if isAgentEngineURL(card.URL) {
					go s.dispatchCallable(ctx, card.URL, card.Name, data)
				} else {
					go s.pokeOrchestrationEndpoint(card.OrchestrationBaseURL(), card.Name, data)
				}
			}
		} else {
			for _, card := range agents {
				if card.URL == "" {
					continue
				}
				go s.pokeOrchestrationEndpoint(card.OrchestrationBaseURL(), card.Name, data)
			}
		}
	}

	return nil
}

// DispatchToAgent dispatches an orchestration event to a single agent by type.
// Uses dispatch-mode routing: subscriber agents get HTTP pokes, callable agents
// get A2A JSON-RPC message/send.
func (s *RedisSwitchboard) DispatchToAgent(ctx context.Context, agentType string, event interface{}) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}

	if s.catalog == nil {
		return fmt.Errorf("no catalog available for agent dispatch")
	}

	agents, err := s.catalog.DiscoverAgents()
	if err != nil {
		return fmt.Errorf("catalog discovery failed: %w", err)
	}

	card, ok := agents[agentType]
	if !ok || card.URL == "" {
		log.Printf("Switchboard: Agent %q not found in catalog or has no URL", agentType)
		return nil
	}

	if isAgentEngineURL(card.URL) {
		go s.dispatchCallable(ctx, card.URL, card.Name, data)
	} else {
		go s.pokeOrchestrationEndpoint(card.OrchestrationBaseURL(), card.Name, data)
	}

	return nil
}

// pokeOrchestrationEndpoint sends an HTTP POST to any agent's /orchestration
// endpoint, selecting the HTTP client based on URL:
//   - Local/Cloud Run: plain HTTP client
//   - Agent Engine (aiplatform.googleapis.com): GCP-authenticated client
func (s *RedisSwitchboard) pokeOrchestrationEndpoint(agentURL, agentType string, data []byte) {
	// Agents mount at root (each has its own port/service), so the
	// orchestration endpoint is directly at {base}/orchestration.
	pokeURL := strings.TrimRight(agentURL, "/") + "/orchestration"

	// Select HTTP client: GCP-authenticated for Agent Engine, plain for others
	client := s.httpClient
	if isAgentEngineURL(agentURL) && s.gcpClient != nil {
		client = s.gcpClient
	}

	log.Printf("Switchboard: Poking %s at %s", agentType, pokeURL)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "POST", pokeURL, bytes.NewBuffer(data))
	if err != nil {
		log.Printf("Switchboard: Failed to create request for %s: %v", agentType, err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		log.Printf("Switchboard: Poke failed for %s: %v", agentType, err)
		return
	}
	defer resp.Body.Close()
}

// PokeAgent dispatches an event to a single agent, routing by URL type:
//   - Agent Engine URLs: A2A message/send (Agent Engine has no /orchestration endpoint)
//   - All local agents (subscriber or callable): HTTP POST to /orchestration
//
// Local callable agents have /orchestration endpoints registered and their
// dispatcher correctly handles events like spawn_agent without invoking the
// LLM. Sending these as A2A message/send would cause the A2A executor to
// treat the event as a user message, triggering an unwanted LLM invocation.
func (s *RedisSwitchboard) PokeAgent(ctx context.Context, agentType string, event interface{}) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}

	if s.catalog == nil {
		return fmt.Errorf("no catalog available for agent poke")
	}

	agents, err := s.catalog.DiscoverAgents()
	if err != nil {
		return fmt.Errorf("catalog discovery failed: %w", err)
	}

	card, ok := agents[agentType]
	if !ok || card.URL == "" {
		log.Printf("Switchboard: Agent %q not found in catalog or has no URL", agentType)
		return nil
	}

	if isAgentEngineURL(card.URL) {
		go s.dispatchCallable(ctx, card.URL, card.Name, data)
	} else {
		go s.pokeOrchestrationEndpoint(card.OrchestrationBaseURL(), card.Name, data)
	}
	return nil
}

// dispatchCallable sends an A2A JSON-RPC message/send request to a callable agent.
// Uses the retryable HTTP client with exponential backoff.
// For Agent Engine URLs, uses GCP-authenticated client.
func (s *RedisSwitchboard) dispatchCallable(ctx context.Context, agentURL, agentType string, eventData []byte) {
	// Determine the A2A endpoint URL.
	// After catalog discovery, card.URL for non-AE agents includes the A2A
	// mount path (e.g., /a2a/simulator/). For AE agents, the URL is the
	// reasoning engine base URL. This method is only called for AE agents
	// in the current routing logic (isAgentEngineURL gate in callers).
	//   - Agent Engine: POST {base}/a2a/v1/message:send (Google API custom method pattern)
	//     Empirically verified: /a2a, /a2a/v1, /a2a/v1/ all return 404.
	//     Only /a2a/v1/message:send accepts POST (returns 400/200, not 404).
	//   - Non-AE (if ever reached): agentURL already contains the full A2A path
	a2aURL := strings.TrimRight(agentURL, "/")
	if isAgentEngineURL(agentURL) {
		a2aURL += "/a2a/v1/message:send"
	} else {
		a2aURL += "/"
	}

	// Extract event info for the message
	var event map[string]interface{}
	if err := json.Unmarshal(eventData, &event); err != nil {
		log.Printf("Switchboard: Failed to parse event for callable dispatch to %s: %v", agentType, err)
		return
	}

	sessionID, _ := event["sessionId"].(string)

	// Write session→simulation mapping to the agent-side Redis hash so
	// DashLogPlugin on the callable AE agent can resolve simulation_id.
	// Without this, callable dispatch bypasses the Python dispatcher entirely,
	// and simulation_registry.register() never runs — so all DashLogPlugin
	// events are emitted without simulation_id.
	if payload, ok := event["payload"].(map[string]interface{}); ok {
		if simID, ok := payload["simulation_id"].(string); ok && simID != "" && sessionID != "" {
			if err := s.client.Set(ctx, "simreg:session:"+sessionID, simID, 2*time.Hour).Err(); err != nil {
				log.Printf("Switchboard: Failed to write simreg for callable %s session %s: %v", agentType, sessionID, err)
			}
		}
	}

	// Fallback: for broadcast events, use the first target as session ID.
	// This ensures the A2A context_id matches the spawn session, providing
	// session continuity via VertexAiSessionService.
	if sessionID == "" {
		if payload, ok := event["payload"].(map[string]interface{}); ok {
			if targets, ok := payload["targets"].([]interface{}); ok && len(targets) > 0 {
				if t, ok := targets[0].(string); ok {
					sessionID = t
				}
			}
		}
	}

	// Construct request body based on agent type.
	// AE uses protobuf SendMessageRequest (proven via curl → HTTP 200):
	//   {request: {message_id, role: "ROLE_USER", content: [{text}]},
	//    configuration: {accepted_output_modes: ["text"]}}
	// Cloud Run uses standard A2A JSON-RPC envelope.
	var requestBody interface{}

	msgID := fmt.Sprintf("orch-%s-%d", sessionID, time.Now().UnixMilli())

	if isAgentEngineURL(agentURL) {
		// AE: SendMessageRequest proto (field is "request" not "message")
		// context_id is required — maps to session_id in VertexAiSessionService
		contextID := sessionID
		if contextID == "" {
			contextID = fmt.Sprintf("ctx-%d", time.Now().UnixMilli())
		}
		requestBody = map[string]interface{}{
			"request": map[string]interface{}{
				"role":       "ROLE_USER",
				"message_id": msgID,
				"context_id": contextID,
				"content": []map[string]interface{}{
					{"text": string(eventData)},
				},
			},
			"configuration": map[string]interface{}{
				"accepted_output_modes": []string{"text"},
				"blocking":              true,
			},
		}
	} else {
		// Cloud Run: standard A2A JSON-RPC
		requestBody = map[string]interface{}{
			"jsonrpc": "2.0",
			"method":  "message/send",
			"id":      fmt.Sprintf("%s-%s", agentType, sessionID),
			"params": map[string]interface{}{
				"message": map[string]interface{}{
					"role":      "user",
					"messageId": msgID,
					"parts": []map[string]interface{}{
						{
							"kind": "text",
							"text": string(eventData),
						},
					},
				},
			},
		}
	}

	body, err := json.Marshal(requestBody)
	if err != nil {
		log.Printf("Switchboard: Failed to marshal A2A request for %s: %v", agentType, err)
		return
	}

	// Select HTTP client: GCP-authenticated for Agent Engine, retryable for others
	httpClient := s.callableClient
	if isAgentEngineURL(agentURL) && s.gcpClient != nil {
		httpClient = s.gcpClient
	}

	log.Printf("Switchboard: Dispatching A2A message/send to callable %s at %s (session: %s)", agentType, a2aURL, sessionID)

	reqCtx, cancel := context.WithTimeout(ctx, 5*time.Minute)
	defer cancel()

	req, err := http.NewRequestWithContext(reqCtx, "POST", a2aURL, bytes.NewBuffer(body))
	if err != nil {
		log.Printf("Switchboard: Failed to create request for %s: %v", agentType, err)
		return
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		log.Printf("Switchboard: Callable dispatch failed for %s: %v", agentType, err)
		return
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		log.Printf("Switchboard: Callable %s returned HTTP %d: %s", agentType, resp.StatusCode, string(respBody))
		return
	}

	log.Printf("Switchboard: Callable %s dispatch OK (HTTP %d, %d bytes)", agentType, resp.StatusCode, len(respBody))

	// Relay AE response to the Hub so WebSocket clients (Tester UI) see it.
	// AE agents emit intermediate pulses (tool_start, model_start, narrative,
	// etc.) directly via Redis through the PSC-I network path. This relay
	// serves as a safety net for the FINAL response text only — it ensures
	// the A2A Task result reaches WebSocket clients even if the agent's
	// direct Redis pulse for the final response was lost or not emitted.
	if len(respBody) > 0 {
		s.relayCallableResponse(ctx, agentType, sessionID, respBody)
	}
}

// relayCallableResponse extracts text from an A2A SendMessageResponse and
// publishes it as a gateway.Wrapper to the Hub for WebSocket fan-out.
func (s *RedisSwitchboard) relayCallableResponse(ctx context.Context, agentType, sessionID string, body []byte) {
	var resp struct {
		Task struct {
			Artifacts []struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"artifacts"`
		} `json:"task"`
	}
	if err := json.Unmarshal(body, &resp); err != nil {
		log.Printf("Switchboard: Could not parse callable %s response for relay: %v", agentType, err)
		return
	}

	var texts []string
	for _, artifact := range resp.Task.Artifacts {
		for _, part := range artifact.Parts {
			if part.Text != "" {
				texts = append(texts, part.Text)
			}
		}
	}
	if len(texts) == 0 {
		return
	}

	// Look up the simulation UUID from the registry so the wrapper carries the
	// correct SimulationId for Hub simulation-based routing.  On Agent Engine
	// the sessionID is a numeric resource ID, not the simulation UUID.
	var simulationID string
	if s.registry != nil {
		if simID, err := s.registry.FindSimulation(ctx, sessionID); err == nil && simID != "" {
			simulationID = simID
		}
	}

	for _, text := range texts {
		payload, _ := json.Marshal(map[string]string{"text": text})
		wrapper := &gateway.Wrapper{
			Timestamp:    time.Now().Format(time.RFC3339Nano),
			Type:         "json",
			RequestId:    fmt.Sprintf("ae-relay-%s-%d", agentType, time.Now().UnixMilli()),
			SessionId:    sessionID,
			Payload:      payload,
			SimulationId: simulationID,
			Origin: &gateway.Origin{
				Type:      "agent",
				Id:        agentType,
				SessionId: sessionID,
			},
			Destination: []string{sessionID},
			Status:      "success",
			Event:       "narrative",
		}
		if err := s.Broadcast(ctx, wrapper); err != nil {
			log.Printf("Switchboard: Failed to relay callable %s response to Hub: %v", agentType, err)
		} else {
			log.Printf("Switchboard: Relayed callable %s response to Hub (session: %s, %d chars)", agentType, sessionID, len(text))
		}
	}
}

// isAgentEngineURL returns true if the URL points to a Vertex AI Agent Engine
// (Reasoning Engine) resource. Used to determine if GCP auth is needed.
func isAgentEngineURL(u string) bool {
	return strings.Contains(u, "aiplatform.googleapis.com") &&
		strings.Contains(u, "reasoningEngines")
}
