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
	"fmt"
	"log"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

// SessionTrackingEntry holds a session-to-agent-type mapping for batch operations.
type SessionTrackingEntry struct {
	SessionID    string
	AgentType    string
	SimulationID string
}

// RedisSessionRegistry implements DistributedRegistry using Redis.
// Data model:
//   - {prefix}:session:{sessionID} → agentType (individual lookup, with TTL)
//   - {prefix}:agent-sessions:{agentType} → SET of sessionIDs (reverse index)
//   - {prefix}:active-agents → SET of agent types with ≥1 session
type RedisSessionRegistry struct {
	client *redis.Client
	prefix string
	ttl    time.Duration
}

// NewRedisSessionRegistry creates a new Redis-backed session registry.
func NewRedisSessionRegistry(client *redis.Client, prefix string, ttl time.Duration) *RedisSessionRegistry {
	return &RedisSessionRegistry{
		client: client,
		prefix: prefix,
		ttl:    ttl,
	}
}

func (r *RedisSessionRegistry) sessionKey(sessionID string) string {
	return fmt.Sprintf("%s:session:%s", r.prefix, sessionID)
}

func (r *RedisSessionRegistry) agentSessionsKey(agentType string) string {
	return fmt.Sprintf("%s:agent-sessions:%s", r.prefix, agentType)
}

func (r *RedisSessionRegistry) activeAgentsKey() string {
	return fmt.Sprintf("%s:active-agents", r.prefix)
}

func (r *RedisSessionRegistry) simulationSessionsKey(simID string) string {
	return fmt.Sprintf("%s:simulation:%s:sessions", r.prefix, simID)
}

func (r *RedisSessionRegistry) sessionSimulationKey(sessionID string) string {
	return fmt.Sprintf("%s:session:%s:simulation", r.prefix, sessionID)
}

func (r *RedisSessionRegistry) activeSimulationsKey() string {
	return fmt.Sprintf("%s:active-simulations", r.prefix)
}

// TrackSession maps a session to an agent type and maintains reverse indexes.
func (r *RedisSessionRegistry) TrackSession(ctx context.Context, sessionID string, agentType string, simulationID string) error {
	pipe := r.client.Pipeline()
	pipe.Set(ctx, r.sessionKey(sessionID), agentType, r.ttl)
	pipe.SAdd(ctx, r.agentSessionsKey(agentType), sessionID)
	pipe.SAdd(ctx, r.activeAgentsKey(), agentType)
	if simulationID != "" {
		pipe.SAdd(ctx, r.simulationSessionsKey(simulationID), sessionID)
		pipe.Expire(ctx, r.simulationSessionsKey(simulationID), r.ttl*2) // 2x session TTL for safety
		pipe.Set(ctx, r.sessionSimulationKey(sessionID), simulationID, r.ttl)
		pipe.SAdd(ctx, r.activeSimulationsKey(), simulationID)
	}
	_, err := pipe.Exec(ctx)
	return err
}

// BatchTrackSessions registers multiple sessions in a single Redis pipeline,
// reducing round-trips from N to 1 during spawn bursts.
func (r *RedisSessionRegistry) BatchTrackSessions(ctx context.Context, sessions []SessionTrackingEntry) error {
	if len(sessions) == 0 {
		return nil
	}
	pipe := r.client.Pipeline()
	for _, s := range sessions {
		pipe.Set(ctx, r.sessionKey(s.SessionID), s.AgentType, r.ttl)
		pipe.SAdd(ctx, r.agentSessionsKey(s.AgentType), s.SessionID)
		pipe.SAdd(ctx, r.activeAgentsKey(), s.AgentType)
		if s.SimulationID != "" {
			pipe.SAdd(ctx, r.simulationSessionsKey(s.SimulationID), s.SessionID)
			pipe.Expire(ctx, r.simulationSessionsKey(s.SimulationID), r.ttl*2)
			pipe.Set(ctx, r.sessionSimulationKey(s.SessionID), s.SimulationID, r.ttl)
			pipe.SAdd(ctx, r.activeSimulationsKey(), s.SimulationID)
		}
	}
	_, err := pipe.Exec(ctx)
	return err
}

// FindAgentType returns the agent type for a session.
func (r *RedisSessionRegistry) FindAgentType(ctx context.Context, sessionID string) (string, bool, error) {
	val, err := r.client.Get(ctx, r.sessionKey(sessionID)).Result()
	if err == redis.Nil {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	return val, true, nil
}

// ActiveAgentTypes returns agent types that have at least one active session.
func (r *RedisSessionRegistry) ActiveAgentTypes(ctx context.Context) ([]string, error) {
	return r.client.SMembers(ctx, r.activeAgentsKey()).Result()
}

// FindSimulation returns the simulation ID for a given session.
func (r *RedisSessionRegistry) FindSimulation(ctx context.Context, sessionID string) (string, error) {
	val, err := r.client.Get(ctx, r.sessionSimulationKey(sessionID)).Result()
	if err == redis.Nil {
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return val, nil
}

// ListSimulations returns all active simulation IDs from the active-simulations index SET.
// This is O(M) where M is the number of simulations, not O(N) over all Redis keys.
func (r *RedisSessionRegistry) ListSimulations(ctx context.Context) ([]string, error) {
	sims, err := r.client.SMembers(ctx, r.activeSimulationsKey()).Result()
	if err == redis.Nil {
		return nil, nil
	}
	return sims, err
}

// UntrackSession removes a session and updates reverse indexes.
func (r *RedisSessionRegistry) UntrackSession(ctx context.Context, sessionID string) error {
	// Look up agent type before deleting
	agentType, ok, err := r.FindAgentType(ctx, sessionID)
	if err != nil {
		return err
	}

	// Look up simulation ID before deleting
	simID, _ := r.FindSimulation(ctx, sessionID)

	pipe := r.client.Pipeline()
	pipe.Del(ctx, r.sessionKey(sessionID))
	pipe.Del(ctx, r.sessionSimulationKey(sessionID))

	if ok {
		pipe.SRem(ctx, r.agentSessionsKey(agentType), sessionID)
	}
	if simID != "" {
		pipe.SRem(ctx, r.simulationSessionsKey(simID), sessionID)
	}
	_, err = pipe.Exec(ctx)
	if err != nil {
		return err
	}

	// If the agent type set is now empty, remove from active-agents index
	if ok {
		count, err := r.client.SCard(ctx, r.agentSessionsKey(agentType)).Result()
		if err != nil {
			return err
		}
		if count == 0 {
			if err := r.client.SRem(ctx, r.activeAgentsKey(), agentType).Err(); err != nil {
				return err
			}
		}
	}

	// If the simulation set is now empty, clean it up and remove from active index
	if simID != "" {
		count, err := r.client.SCard(ctx, r.simulationSessionsKey(simID)).Result()
		if err != nil {
			return err
		}
		if count == 0 {
			pipe := r.client.Pipeline()
			pipe.Del(ctx, r.simulationSessionsKey(simID))
			pipe.SRem(ctx, r.activeSimulationsKey(), simID)
			if _, err := pipe.Exec(ctx); err != nil {
				return err
			}
		}
	}

	return nil
}

// ListSessions returns all tracked session IDs.
func (r *RedisSessionRegistry) ListSessions(ctx context.Context) ([]string, error) {
	var sessions []string
	prefix := r.prefix + ":session:"
	iter := r.client.Scan(ctx, 0, prefix+"*", 0).Iterator()
	for iter.Next(ctx) {
		key := iter.Val()
		sid := strings.TrimPrefix(key, prefix)
		// Skip sub-keys like session:{id}:simulation
		if strings.Contains(sid, ":") {
			continue
		}
		sessions = append(sessions, sid)
	}
	if err := iter.Err(); err != nil {
		return nil, err
	}
	return sessions, nil
}

// Flush clears all session mappings and indexes, returning the number of
// individual session keys removed.
func (r *RedisSessionRegistry) Flush(ctx context.Context) (int, error) {
	// Get all active agent types to clean up their sets
	types, err := r.client.SMembers(ctx, r.activeAgentsKey()).Result()
	if err != nil && err != redis.Nil {
		return 0, err
	}

	pipe := r.client.Pipeline()
	// Delete all agent-sessions sets
	for _, agentType := range types {
		pipe.Del(ctx, r.agentSessionsKey(agentType))
	}
	// Delete the active-agents index
	pipe.Del(ctx, r.activeAgentsKey())
	_, err = pipe.Exec(ctx)
	if err != nil {
		return 0, err
	}

	// Delete simulation keys
	simIter := r.client.Scan(ctx, 0, r.prefix+":simulation:*:sessions", 0).Iterator()
	for simIter.Next(ctx) {
		r.client.Del(ctx, simIter.Val())
	}
	r.client.Del(ctx, r.activeSimulationsKey())

	// Delete individual session keys (including :simulation sub-keys)
	count := 0
	prefix := r.prefix + ":session:"
	iter := r.client.Scan(ctx, 0, prefix+"*", 0).Iterator()
	for iter.Next(ctx) {
		key := iter.Val()
		if err := r.client.Del(ctx, key).Err(); err != nil {
			return count, err
		}
		// Only count primary session keys, not sub-keys
		sid := strings.TrimPrefix(key, prefix)
		if !strings.Contains(sid, ":") {
			count++
		}
	}
	if err := iter.Err(); err != nil {
		return count, err
	}
	return count, nil
}

// Reap prunes stale session entries from reverse index sets.
// When a session STRING key expires via TTL, the corresponding entries in
// agent-sessions SETs and active-agents SET are orphaned. Reap checks each
// entry and removes those whose session key no longer exists.
func (r *RedisSessionRegistry) Reap(ctx context.Context) (int, error) {
	types, err := r.client.SMembers(ctx, r.activeAgentsKey()).Result()
	if err != nil {
		if err == redis.Nil {
			return 0, nil
		}
		return 0, err
	}

	reaped := 0
	for _, agentType := range types {
		sessionIDs, err := r.client.SMembers(ctx, r.agentSessionsKey(agentType)).Result()
		if err != nil {
			if err == redis.Nil {
				continue
			}
			return reaped, err
		}
		if len(sessionIDs) == 0 {
			continue
		}

		// Pipeline EXISTS for all session IDs (single round-trip)
		pipe := r.client.Pipeline()
		existsCmds := make([]*redis.IntCmd, len(sessionIDs))
		for i, sid := range sessionIDs {
			existsCmds[i] = pipe.Exists(ctx, r.sessionKey(sid))
		}
		_, err = pipe.Exec(ctx)
		if err != nil {
			return reaped, err
		}

		// Collect stale entries
		var stale []interface{}
		for i, cmd := range existsCmds {
			if cmd.Val() == 0 {
				stale = append(stale, sessionIDs[i])
			}
		}
		if len(stale) > 0 {
			if err := r.client.SRem(ctx, r.agentSessionsKey(agentType), stale...).Err(); err != nil {
				return reaped, err
			}
			reaped += len(stale)
		}

		// If all sessions for this type are gone, remove the type
		remaining, err := r.client.SCard(ctx, r.agentSessionsKey(agentType)).Result()
		if err != nil {
			return reaped, err
		}
		if remaining == 0 {
			if err := r.client.SRem(ctx, r.activeAgentsKey(), agentType).Err(); err != nil {
				log.Printf("reap: failed to remove agent type %s from active set: %v", agentType, err)
			}
			if err := r.client.Del(ctx, r.agentSessionsKey(agentType)).Err(); err != nil {
				log.Printf("reap: failed to delete empty agent-sessions key for %s: %v", agentType, err)
			}
		}
	}

	// Also reap orphaned simulation entries
	simPattern := r.prefix + ":simulation:*:sessions"
	simPrefixLen := len(r.prefix + ":simulation:")
	simSuffixLen := len(":sessions")
	simIter := r.client.Scan(ctx, 0, simPattern, 0).Iterator()
	for simIter.Next(ctx) {
		simKey := simIter.Val()
		simID := simKey[simPrefixLen : len(simKey)-simSuffixLen]

		// Check each session in the simulation set
		sessionIDs, err := r.client.SMembers(ctx, simKey).Result()
		if err != nil {
			continue
		}

		var staleSimSessions []interface{}
		for _, sid := range sessionIDs {
			exists, err := r.client.Exists(ctx, r.sessionKey(sid)).Result()
			if err != nil {
				continue
			}
			if exists == 0 {
				staleSimSessions = append(staleSimSessions, sid)
				// Also clean up the session:simulation key
				r.client.Del(ctx, r.sessionSimulationKey(sid))
			}
		}
		if len(staleSimSessions) > 0 {
			r.client.SRem(ctx, r.simulationSessionsKey(simID), staleSimSessions...)
		}

		// If simulation set is now empty, remove it
		remaining, err := r.client.SCard(ctx, simKey).Result()
		if err != nil {
			continue
		}
		if remaining == 0 {
			r.client.Del(ctx, simKey)
			r.client.SRem(ctx, r.activeSimulationsKey(), simID)
		}
	}

	return reaped, nil
}
