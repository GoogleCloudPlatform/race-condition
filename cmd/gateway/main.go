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
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/config"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/GoogleCloudPlatform/race-condition/internal/middleware"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/gorilla/websocket"
	"github.com/redis/go-redis/v9"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// newRedisOptions returns production Redis client options with right-sized pool
// configuration. PoolSize=50 balances connection usage against the Memorystore
// connection budget; the gateway uses Redis pipeline batching, so fewer
// concurrent connections are needed than the raw operation count suggests.
// ConnMaxIdleTime=5m releases idle connections back to the pool to prevent
// connection hoarding during quiet periods between simulations.
func newRedisOptions(addr string) *redis.Options {
	return &redis.Options{
		Addr:            addr,
		PoolSize:        50,
		MinIdleConns:    10,
		PoolTimeout:     10 * time.Second,
		ConnMaxIdleTime: 5 * time.Minute,
	}
}

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true // Allow all origins for dev
	},
}

// dispatchEvent routes an event through the switchboard.
// When agentType is specified, it dispatches only to that agent.
// When agentType is empty, it broadcasts to all agents.
func dispatchEvent(sb hub.Switchboard, agentType string, event interface{}) {
	if sb == nil {
		log.Printf("DISPATCH: no switchboard available, skipping")
		return
	}
	if agentType != "" {
		if err := sb.DispatchToAgent(context.Background(), agentType, event); err != nil {
			log.Printf("DISPATCH: targeted dispatch to %s failed: %v", agentType, err)
		}
	} else {
		if err := sb.PublishOrchestration(context.Background(), "simulation:broadcast", event); err != nil {
			log.Printf("DISPATCH: broadcast failed: %v", err)
		}
	}
}

func handleBinaryMessage(ctx context.Context, sid string, message []byte, sb hub.Switchboard, reg session.DistributedRegistry) {
	log.Printf("GATEWAY: Received binary message from session [%s] (size: %d bytes)", sid, len(message))
	var wrapper gateway.Wrapper
	if err := proto.Unmarshal(message, &wrapper); err == nil {
		log.Printf("GATEWAY: Parsed Wrapper msg. Type=%s, Event=%s", wrapper.Type, wrapper.Event)
		// Gateway handles: broadcast, tool_call, narrative
		if wrapper.Type == "broadcast" {
			log.Printf("GATEWAY: Processing broadcast intent")
			// 1. Internal fan-out to other Gateway instances
			if sb != nil {
				if err := sb.Broadcast(ctx, &wrapper); err != nil {
					log.Printf("GATEWAY: broadcast error: %v", err)
				}
			}

			// 2. Orchestration fan-out to Python agents
			var broadcastReq gateway.BroadcastRequest
			if err := proto.Unmarshal(wrapper.Payload, &broadcastReq); err == nil {
				log.Printf("GATEWAY: Successfully unmarshaled BroadcastRequest (targets: %v)", broadcastReq.TargetSessionIds)
				event := map[string]interface{}{
					"type":    "broadcast",
					"eventId": wrapper.RequestId,
					"payload": map[string]interface{}{
						"data":    string(broadcastReq.Payload),
						"targets": broadcastReq.TargetSessionIds,
					},
				}

				// Session-targeted dispatch: look up which agent types own the
				// target sessions and dispatch only to those types. This prevents
				// broadcasting to all active agents when only specific agents
				// should receive the message.
				go func() {
					if reg == nil || len(broadcastReq.TargetSessionIds) == 0 {
						// Fallback: no registry or no targets → broadcast to all
						dispatchEvent(sb, "", event)
						return
					}
					dispatched := make(map[string]bool)
					for _, targetSID := range broadcastReq.TargetSessionIds {
						agentType, found, err := reg.FindAgentType(context.Background(), targetSID)
						if err != nil || !found {
							log.Printf("GATEWAY: Session %s not found in registry, skipping", targetSID)
							continue
						}
						if dispatched[agentType] {
							continue // already dispatched to this agent type
						}
						dispatched[agentType] = true
						log.Printf("GATEWAY: Targeted dispatch to %s for session %s", agentType, targetSID)
						dispatchEvent(sb, agentType, event)
					}
					if len(dispatched) == 0 {
						log.Printf("GATEWAY: No agent types found for targets, falling back to broadcast")
						dispatchEvent(sb, "", event)
					}
				}()
			} else {
				log.Printf("GATEWAY: Failed to unmarshal BroadcastRequest: %v", err)
			}
		}
		if wrapper.Type == "a2ui_action" {
			log.Printf("GATEWAY: Processing A2UI action")
			var action gateway.A2UIAction
			if err := proto.Unmarshal(wrapper.Payload, &action); err == nil {
				log.Printf("GATEWAY: A2UI action=%s for session=%s", action.ActionName, action.SessionId)
				event := map[string]interface{}{
					"type":      "a2ui_action",
					"eventId":   wrapper.RequestId,
					"sessionId": action.SessionId,
					"payload": map[string]interface{}{
						"actionName": action.ActionName,
						"sessionId":  action.SessionId,
					},
				}
				go func() {
					if reg == nil {
						log.Printf("GATEWAY: No registry, cannot route A2UI action")
						return
					}
					agentType, found, err := reg.FindAgentType(context.Background(), action.SessionId)
					if err != nil || !found {
						log.Printf("GATEWAY: Session %s not found in registry for A2UI action", action.SessionId)
						return
					}
					log.Printf("GATEWAY: Dispatching A2UI action to %s", agentType)
					dispatchEvent(sb, agentType, event)
				}()
			} else {
				log.Printf("GATEWAY: Failed to unmarshal A2UIAction: %v", err)
			}
		}
		// Future: Handle tool_call and narrative from here if needed
	} else {
		log.Printf("GATEWAY: Failed to unmarshal Wrapper proto: %v", err)
	}
}

func setupRouter(h *hub.Hub, sb hub.Switchboard, catalog *agent.Catalog, reg session.DistributedRegistry, gatewayID string, rdb *redis.Client, drainer hub.PubSubDrainer) *gin.Engine {
	r := gin.Default()

	r.Use(middleware.CORS(os.Getenv("CORS_ALLOWED_ORIGINS")))

	// Parse MAX_RUNNERS limit (default 100, clamped to [1, 1000]).
	// Local dev default: 100. GCP deployments set MAX_RUNNERS=1000 via .env.dev.
	// This is read once at startup; changes require a gateway restart.
	maxRunners := 100
	if v := os.Getenv("MAX_RUNNERS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil && n >= 1 {
			maxRunners = n
			if maxRunners > 1000 {
				maxRunners = 1000
			}
		} else {
			log.Printf("WARNING: invalid MAX_RUNNERS=%q (must be integer 1-1000), using default %d", v, maxRunners)
		}
	}

	r.GET("/health", func(c *gin.Context) {
		redisStatus := "online"
		if sb != nil {
			if err := sb.Ping(c.Request.Context()); err != nil {
				redisStatus = "offline"
			}
		} else {
			redisStatus = "unknown"
		}

		pubsubStatus := "online"
		pubsubHost := os.Getenv("PUBSUB_EMULATOR_HOST")
		conn, err := net.DialTimeout("tcp", pubsubHost, 1*time.Second)
		if err != nil {
			pubsubStatus = "offline"
		} else {
			conn.Close()
		}

		c.JSON(http.StatusOK, gin.H{
			"status":  "ok",
			"service": "gateway",
			"infra": gin.H{
				"redis":  redisStatus,
				"pubsub": pubsubStatus,
			},
		})
	})

	// Strict health probe for uptime checks and load balancer readiness.
	// Returns 503 when Redis is unreachable (unlike /health which is informational).
	r.GET("/healthz", func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 1*time.Second)
		defer cancel()
		if rdb == nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"status": "unhealthy",
				"reason": "redis client not initialized",
			})
			return
		}
		if err := rdb.Ping(ctx).Err(); err != nil {
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"status": "unhealthy",
				"reason": "redis unreachable",
			})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "healthy"})
	})

	r.GET("/config", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{
			"max_runners": maxRunners,
		})
	})

	// Agent Discovery API
	r.GET("/api/v1/agent-types", func(c *gin.Context) {
		agents, err := catalog.DiscoverAgents()
		if err != nil {
			log.Printf("AGENT_DISCOVERY_ERROR: %v", err)
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "failed to discover any agents. Check AGENT_URLS and ensure agents are running."})
			return
		}
		c.JSON(http.StatusOK, agents)
	})

	// Session Management API
	r.GET("/api/v1/sessions", func(c *gin.Context) {
		sessions, err := reg.ListSessions(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, sessions)
	})

	r.POST("/api/v1/sessions", func(c *gin.Context) {
		var req struct {
			AgentType    string `json:"agentType" binding:"required"`
			UserID       string `json:"userId" binding:"required"`
			SimulationID string `json:"simulation_id"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		// Generate a unique UUID for the session
		sessionID := uuid.NewString()

		// Track the session in the registry with its agent type and optional simulation
		if err := reg.TrackSession(c.Request.Context(), sessionID, req.AgentType, req.SimulationID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to track session: " + err.Error()})
			return
		}

		// Publish a JSON orchestration event for the Python agents
		event := map[string]interface{}{
			"type":      "spawn_agent",
			"sessionId": sessionID,
			"eventId":   uuid.NewString(),
			"payload": map[string]string{
				"agentType":     req.AgentType,
				"userId":        req.UserID,
				"simulation_id": req.SimulationID,
			},
		}

		queue := hub.SpawnQueueName(req.AgentType, sessionID, hub.DefaultSpawnShards)
		if err := sb.EnqueueOrchestration(c.Request.Context(), queue, event); err != nil {
			// Try to untrack if orchestration fails to avoid ghost sessions
			_ = reg.UntrackSession(c.Request.Context(), sessionID)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to enqueue orchestration event: " + err.Error()})
			return
		}

		c.JSON(http.StatusCreated, gin.H{
			"status":    "pending",
			"sessionId": sessionID,
			"message":   "spawn event published to orchestration channel",
		})
	})

	r.POST("/api/v1/sessions/flush", func(c *gin.Context) {
		count, err := reg.Flush(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, gin.H{"status": "flushed", "count": count})
	})

	// Environment Reset API — selectively flush sessions, queues, and maps
	r.POST("/api/v1/environment/reset", func(c *gin.Context) {
		var req struct {
			Targets []string `json:"targets"`
		}
		// Parse optional JSON body; empty body or missing targets = flush all
		_ = c.ShouldBindJSON(&req)

		flushAll := len(req.Targets) == 0
		targetSet := make(map[string]bool)
		knownTargets := map[string]bool{"sessions": true, "queues": true, "maps": true, "pubsub": true}
		for _, t := range req.Targets {
			if !knownTargets[t] {
				c.JSON(http.StatusBadRequest, gin.H{
					"error":   fmt.Sprintf("unknown reset target %q", t),
					"allowed": []string{"sessions", "queues", "maps", "pubsub"},
				})
				return
			}
			targetSet[t] = true
		}

		type flushResult struct {
			Flushed bool `json:"flushed"`
			Count   int  `json:"count"`
		}
		results := map[string]*flushResult{
			"sessions": {Flushed: false, Count: 0},
			"queues":   {Flushed: false, Count: 0},
			"maps":     {Flushed: false, Count: 0},
			"pubsub":   {Flushed: false, Count: 0},
		}

		ctx := c.Request.Context()

		// Snapshot active agent types BEFORE flushing so we can notify them
		// after the flush completes. Without this, PublishOrchestration queries
		// the registry post-flush and gets an empty list, so callable agents
		// (Agent Engine on GCP) never learn about the reset.
		var preFlushAgents []string
		if reg != nil {
			var err error
			preFlushAgents, err = reg.ActiveAgentTypes(ctx)
			if err != nil {
				log.Printf("RESET: snapshot ActiveAgentTypes failed (agents may not be notified): %v", err)
			}
		}

		// Flush sessions
		if flushAll || targetSet["sessions"] {
			count, err := reg.Flush(ctx)
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": "sessions flush failed: " + err.Error()})
				return
			}
			results["sessions"].Flushed = true
			results["sessions"].Count = count
		}

		// Flush queues
		if flushAll || targetSet["queues"] {
			if sb != nil {
				count, err := sb.FlushQueues(ctx)
				if err != nil {
					c.JSON(http.StatusInternalServerError, gin.H{"error": "queues flush failed: " + err.Error()})
					return
				}
				results["queues"].Flushed = true
				results["queues"].Count = count
			} else {
				results["queues"].Flushed = true
				results["queues"].Count = 0
			}
		}

		// Flush session maps (SCAN and DEL session_map:* keys)
		if flushAll || targetSet["maps"] {
			mapCount := 0
			if rdb != nil {
				var cursor uint64
				for {
					keys, nextCursor, err := rdb.Scan(ctx, cursor, "session_map:*", 100).Result()
					if err != nil {
						c.JSON(http.StatusInternalServerError, gin.H{"error": "maps flush scan failed: " + err.Error()})
						return
					}
					if len(keys) > 0 {
						if err := rdb.Del(ctx, keys...).Err(); err != nil {
							c.JSON(http.StatusInternalServerError, gin.H{"error": "maps flush delete failed: " + err.Error()})
							return
						}
						mapCount += len(keys)
					}
					cursor = nextCursor
					if cursor == 0 {
						break
					}
				}
			}
			results["maps"].Flushed = true
			results["maps"].Count = mapCount
		}

		// Flush PubSub subscriptions (seek to now)
		if flushAll || targetSet["pubsub"] {
			if drainer != nil {
				count, err := drainer.Drain(ctx)
				if err != nil {
					log.Printf("RESET: pubsub drain error (non-fatal): %v", err)
				}
				results["pubsub"].Flushed = err == nil || count > 0
				results["pubsub"].Count = count
			} else {
				results["pubsub"].Flushed = true
				results["pubsub"].Count = 0
			}
		}

		// Broadcast environment_reset event
		if sb != nil {
			resetWrapper := &gateway.Wrapper{
				Timestamp: time.Now().UTC().Format(time.RFC3339),
				Type:      "environment_reset",
				Event:     "environment_reset",
				Origin: &gateway.Origin{
					Type: "system",
					Id:   gatewayID,
				},
			}
			if err := sb.Broadcast(ctx, resetWrapper); err != nil {
				log.Printf("RESET: broadcast error: %v", err)
			}

			// Publish to simulation:broadcast via Redis Pub/Sub for subscriber-mode
			// agents listening on the channel. Callable agents get explicit pokes below.
			simNotification := map[string]interface{}{
				"type":    "environment_reset",
				"eventId": fmt.Sprintf("reset-%d", time.Now().UnixNano()),
			}
			if err := sb.PublishOrchestration(ctx, "simulation:broadcast", simNotification); err != nil {
				log.Printf("RESET: simulation broadcast error: %v", err)
			}

			// Explicitly poke each agent that was active before the flush.
			// PublishOrchestration's session-aware routing returns empty post-flush,
			// so this ensures callable agents (Agent Engine) receive the reset.
			for _, agentType := range preFlushAgents {
				if err := sb.PokeAgent(ctx, agentType, simNotification); err != nil {
					log.Printf("RESET: poke %s failed: %v", agentType, err)
				}
			}
		}

		c.JSON(http.StatusOK, gin.H{
			"status":  "reset",
			"results": results,
		})
	})

	// Simulations Listing API
	r.GET("/api/v1/simulations", func(c *gin.Context) {
		if reg == nil {
			c.JSON(http.StatusOK, gin.H{"simulations": []string{}})
			return
		}
		sims, err := reg.ListSimulations(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if sims == nil {
			sims = []string{}
		}
		c.JSON(http.StatusOK, gin.H{"simulations": sims})
	})
	// Batch Spawn API — spawn N sessions across multiple agent types
	r.POST("/api/v1/spawn", func(c *gin.Context) {
		var req struct {
			Agents []struct {
				AgentType string `json:"agentType" binding:"required"`
				Count     int    `json:"count" binding:"required"`
			} `json:"agents" binding:"required,dive"`
			SimulationID string `json:"simulation_id"`
		}
		if err := c.ShouldBindJSON(&req); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}

		// Refresh catalog and validagent types synchronously for spawn request
		if catalog == nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "agent catalog service not initialized"})
			return
		}

		agents, err := catalog.DiscoverAgents()
		if err != nil {
			log.Printf("SPAWN: discovery failed: %v", err)
			c.JSON(http.StatusServiceUnavailable, gin.H{
				"error":   "failed to discover agents required for spawning",
				"details": err.Error(),
			})
			return
		}

		for _, a := range req.Agents {
			if a.Count < 1 {
				c.JSON(http.StatusBadRequest, gin.H{"error": fmt.Sprintf("count must be >= 1 for agent %q", a.AgentType)})
				return
			}
			if _, found := agents[a.AgentType]; !found {
				c.JSON(http.StatusBadRequest, gin.H{
					"error":      fmt.Sprintf("unknown agent type %q", a.AgentType),
					"available":  getAgentKeys(agents),
					"suggestion": "ensure the agent is running and its URL is correct in AGENT_URLS",
				})
				return
			}
		}

		// Enforce MAX_RUNNERS limit: silently cap counts to fit within the limit.
		totalRequested := 0
		for _, a := range req.Agents {
			totalRequested += a.Count
		}
		if totalRequested > maxRunners {
			log.Printf("Spawn request for %d runners exceeds MAX_RUNNERS=%d, capping", totalRequested, maxRunners)
			// Proportionally scale down each agent type's count.
			remaining := maxRunners
			for i := range req.Agents {
				if i == len(req.Agents)-1 {
					req.Agents[i].Count = remaining
				} else {
					scaled := req.Agents[i].Count * maxRunners / totalRequested
					if scaled < 1 {
						scaled = 1
					}
					req.Agents[i].Count = scaled
					remaining -= scaled
				}
			}
			if remaining < 1 {
				req.Agents[len(req.Agents)-1].Count = 1
			}
		}

		type spawnedSession struct {
			SessionID    string `json:"sessionId"`
			AgentType    string `json:"agentType"`
			SimulationID string `json:"simulationId,omitempty"`
		}

		// Phase 1: Collect all sessions and events up front.
		var sessions []spawnedSession
		var trackEntries []session.SessionTrackingEntry
		var queueItems []hub.QueueItem

		for _, a := range req.Agents {
			for i := 0; i < a.Count; i++ {
				sessionID := uuid.NewString()

				sessions = append(sessions, spawnedSession{
					SessionID:    sessionID,
					AgentType:    a.AgentType,
					SimulationID: req.SimulationID,
				})
				trackEntries = append(trackEntries, session.SessionTrackingEntry{
					SessionID:    sessionID,
					AgentType:    a.AgentType,
					SimulationID: req.SimulationID,
				})

				event := map[string]interface{}{
					"type":      "spawn_agent",
					"sessionId": sessionID,
					"eventId":   uuid.NewString(),
					"payload": map[string]string{
						"agentType":     a.AgentType,
						"simulation_id": req.SimulationID,
					},
				}
				queueItems = append(queueItems, hub.QueueItem{
					Queue: hub.SpawnQueueName(a.AgentType, sessionID, hub.DefaultSpawnShards),
					Data:  event,
				})
			}
		}

		// Phase 2: Batch-track all sessions in one Redis pipeline (was N round-trips).
		if err := reg.BatchTrackSessions(c.Request.Context(), trackEntries); err != nil {
			log.Printf("SPAWN: batch track failed: %v", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to track sessions: " + err.Error()})
			return
		}

		// Phase 3: Batch-enqueue all spawn events in one Redis pipeline (was N round-trips).
		// Uses context.Background() so enqueue completes even if the HTTP client disconnects.
		// PokeAgent (HTTP) runs per-agent-type in a background goroutine.
		if sb != nil {
			if err := sb.BatchEnqueueOrchestration(context.Background(), queueItems); err != nil {
				log.Printf("SPAWN: batch enqueue failed, untracking sessions: %v", err)
				// Untrack all sessions to avoid ghost entries that never get spawned.
				for _, entry := range trackEntries {
					_ = reg.UntrackSession(c.Request.Context(), entry.SessionID)
				}
				c.JSON(http.StatusInternalServerError, gin.H{"error": "failed to enqueue spawn events: " + err.Error()})
				return
			}
			// Poke agents to deliver spawn events.
			// Subscriber agents consume spawn events from their Redis queue,
			// so one poke per type is sufficient as a wake-up signal.
			// Callable agents have no Redis queue listener — they receive
			// events solely via HTTP. Each spawn event must be delivered
			// individually (one poke per session).
			poked := make(map[string]bool)
			for i, s := range sessions {
				card := agents[s.AgentType]
				isCallable := card.DispatchMode() == "callable"

				if !isCallable && poked[s.AgentType] {
					continue // subscriber: already poked this type
				}
				poked[s.AgentType] = true

				go func(evt map[string]interface{}, agentType string) {
					if err := sb.PokeAgent(context.Background(), agentType, evt); err != nil {
						log.Printf("SPAWN: poke error for %s: %v", agentType, err)
					}
				}(queueItems[i].Data.(map[string]interface{}), s.AgentType)
			}
		}

		c.JSON(http.StatusOK, gin.H{"sessions": sessions})
	})

	// Pub/Sub Push Orchestration Endpoint
	r.POST("/api/v1/orchestration/push", func(c *gin.Context) {
		var pushReq struct {
			Message struct {
				Data []byte `json:"data"`
			} `json:"message"`
		}
		if err := c.ShouldBindJSON(&pushReq); err != nil {
			c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		// Parse the inner event strictly as a gateway.Wrapper
		var wrapper gateway.Wrapper

		// Use protojson to unmarshal since Pub/Sub push payloads are usually JSON encoded
		if err := protojson.Unmarshal(pushReq.Message.Data, &wrapper); err != nil {
			log.Printf("ORCHESTRATION_PUSH: Failed to parse as Wrapper proto: %v", err)
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid event format, expected Wrapper schema"})
			return
		}

		var agentType string
		if wrapper.Origin != nil {
			agentType = wrapper.Origin.Id
			if agentType == "" {
				agentType = wrapper.Origin.Type
			}
		}

		sessionID := wrapper.SessionId
		if wrapper.Origin != nil && wrapper.Origin.SessionId != "" {
			sessionID = wrapper.Origin.SessionId
		}

		if agentType == "" {
			log.Printf("ORCHESTRATION_PUSH: No agentType in Wrapper origin, skipping poke. Data: %s", string(pushReq.Message.Data))
			c.Status(http.StatusOK)
			return
		}

		log.Printf("ORCHESTRATION_PUSH: Dispatching for agent [%s] session [%s]", agentType, sessionID)

		// Create a legacy event map to pass to dispatchEvent (for agent consumption)
		var event map[string]interface{}
		if err := json.Unmarshal(pushReq.Message.Data, &event); err != nil {
			log.Printf("ORCHESTRATION_PUSH: Failed to unmarshal as generic JSON for dispatch: %v", err)
			c.JSON(http.StatusBadRequest, gin.H{"error": "invalid fallback json content"})
			return
		}

		// Delegate dispatch to the switchboard, which handles dispatch-mode
		// routing: subscriber agents get /orchestration pokes, callable agents
		// get A2A message/send with retries and optional GCP auth.
		dispatchEvent(sb, agentType, event)

		c.Status(http.StatusOK)
	})
	r.GET("/ws", func(c *gin.Context) {
		sessionID := c.Query("sessionId")
		simulationID := c.Query("simulationId")

		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			log.Printf("WS Upgrade error: %v", err)
			return
		}

		h.Register(sessionID, conn, simulationID)

		// Reader loop
		go func(conn *websocket.Conn, sid string) {
			defer func() {
				// Safe even if writePump already self-unregistered —
				// Run() treats duplicate unregisters as no-ops.
				h.Unregister(sid, conn)
			}()

			for {
				messageType, message, err := conn.ReadMessage()
				if err != nil {
					break
				}
				if messageType == websocket.BinaryMessage {
					handleBinaryMessage(context.Background(), sessionID, message, sb, reg)
				}
				if messageType == websocket.TextMessage {
					// Route text messages through Hub for simulation subscription handling.
					// The Hub handles subscribe_simulation/unsubscribe_simulation messages.
					h.HandleTextMessage(conn, message)
				}
			}
		}(conn, sessionID)
	})

	return r
}

func getAgentKeys(m map[string]agent.AgentCard) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}

func main() {
	config.Load()
	port := config.Optional("PORT", config.Optional("GATEWAY_PORT", "8101"))
	if err := config.ValidatePort(port); err != nil {
		log.Fatalf("❌ Invalid PORT: %v", err)
	}

	// Distributed Setup
	redisAddr := config.Require("REDIS_ADDR")
	rdb := redis.NewClient(newRedisOptions(redisAddr))

	// Initialize core services with Redis-backed subscription store.
	// RemoteWorkers=16 provides 4x throughput over the default (4) for
	// processing inbound Redis pub/sub messages during 1000-runner simulations.
	subStore := hub.NewRedisSubscriptionStore(rdb)
	h := hub.NewHub(hub.WithSubscriptionStore(subStore), hub.WithRemoteWorkers(16))

	gatewayID := config.Optional("HOSTNAME", "local-gw")

	reg := session.NewRedisSessionRegistry(rdb, "n26", 2*time.Hour)

	agentURLsRaw := config.Optional("AGENT_URLS", "")
	var agentURLs []string
	if agentURLsRaw != "" {
		for _, u := range strings.Split(agentURLsRaw, ",") {
			u = strings.TrimSpace(u)
			if u != "" {
				agentURLs = append(agentURLs, u)
			}
		}
	}
	catalog := agent.NewCatalog(agentURLs)
	sb := hub.NewSwitchboardWithRegistry(rdb, gatewayID, h, catalog, reg)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start background workers
	go h.Run()
	go func() {
		if err := sb.Start(ctx); err != nil && err != context.Canceled {
			log.Printf("Switchboard error: %v", err)
		}
	}()

	// Start background reaper for stale session cleanup
	reapInterval := config.Optional("REAP_INTERVAL", "30m")
	reapDur, err := time.ParseDuration(reapInterval)
	if err != nil {
		log.Fatalf("❌ Invalid REAP_INTERVAL %q: %v", reapInterval, err)
	}
	log.Printf("Registry reaper started (interval: %s)", reapDur)
	go func() {
		ticker := time.NewTicker(reapDur)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				reaped, err := reg.Reap(ctx)
				if err != nil {
					log.Printf("Registry reaper error: %v", err)
				} else if reaped > 0 {
					log.Printf("Registry reaper: pruned %d stale session(s)", reaped)
				}
			}
		}
	}()

	// PubSub Drainer: on GCP (no emulator), drain subscriptions during reset.
	var drainer hub.PubSubDrainer
	pubsubProject := config.Optional("PUBSUB_PROJECT_ID", "")
	pubsubResetSubs := config.Optional("PUBSUB_RESET_SUBS", "")
	if os.Getenv("PUBSUB_EMULATOR_HOST") == "" && pubsubProject != "" && pubsubResetSubs != "" {
		var subs []string
		for _, s := range strings.Split(pubsubResetSubs, ",") {
			s = strings.TrimSpace(s)
			if s != "" {
				subs = append(subs, s)
			}
		}
		drainer = hub.NewGCPPubSubDrainer(pubsubProject, subs)
		log.Printf("PubSub drainer configured for %d subscription(s) in project %s", len(subs), pubsubProject)
	} else {
		drainer = &hub.NoOpDrainer{}
		log.Printf("PubSub drainer disabled (emulator mode or no PUBSUB_RESET_SUBS configured)")
	}

	r := setupRouter(h, sb, catalog, reg, gatewayID, rdb, drainer)

	srv := &http.Server{
		Addr:    ":" + port,
		Handler: r,
	}

	// Start server in a goroutine
	go func() {
		log.Printf("Gateway starting on port %s (ID: %s)", port, gatewayID)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Failed to run gateway: %v", err)
		}
	}()

	// Wait for interrupt signal for graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("Gateway shutting down gracefully...")

	// Cancel background workers first
	cancel()

	// Give outstanding requests 10 seconds to complete
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Fatalf("Gateway forced shutdown: %v", err)
	}
	log.Println("Gateway exited cleanly")
}
