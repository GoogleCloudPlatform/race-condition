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
	"log"
	"time"

	"github.com/redis/go-redis/v9"
)

const (
	// subscriptionTTL is the expiry applied to subscription keys in Redis.
	// Keys are refreshed on each Subscribe call.
	subscriptionTTL = 2 * time.Hour

	// subscriptionTimeout is the context timeout for individual Redis calls
	// from within the Hub's Run() loop to keep them non-blocking.
	subscriptionTimeout = 2 * time.Second
)

// SubscriptionStore persists simulation subscription state so that it
// survives WebSocket reconnections to different gateway instances.
type SubscriptionStore interface {
	// Subscribe registers a session as interested in a simulation's messages.
	Subscribe(ctx context.Context, simulationID, sessionID string) error

	// Unsubscribe removes a session's interest in a simulation.
	Unsubscribe(ctx context.Context, simulationID, sessionID string) error

	// UnsubscribeAll removes a session from all simulation subscriptions.
	// Called when a WebSocket disconnects.
	UnsubscribeAll(ctx context.Context, sessionID string) error

	// Lookup returns all session IDs subscribed to a simulation.
	Lookup(ctx context.Context, simulationID string) ([]string, error)
}

// fwdKey returns the Redis key for the forward index: sim → sessions.
func fwdKey(simulationID string) string {
	return "sim_sub:" + simulationID
}

// revKey returns the Redis key for the reverse index: session → sims.
func revKey(sessionID string) string {
	return "sim_sub_rev:" + sessionID
}

// RedisSubscriptionStore persists subscriptions in Redis SETs.
type RedisSubscriptionStore struct {
	client *redis.Client
}

// NewRedisSubscriptionStore creates a subscription store backed by Redis.
func NewRedisSubscriptionStore(client *redis.Client) *RedisSubscriptionStore {
	return &RedisSubscriptionStore{client: client}
}

// Subscribe adds sessionID to the simulation's subscriber set and maintains
// a reverse index for efficient UnsubscribeAll. Both keys get a TTL refresh.
func (s *RedisSubscriptionStore) Subscribe(ctx context.Context, simulationID, sessionID string) error {
	pipe := s.client.Pipeline()
	fk := fwdKey(simulationID)
	rk := revKey(sessionID)

	pipe.SAdd(ctx, fk, sessionID)
	pipe.Expire(ctx, fk, subscriptionTTL)
	pipe.SAdd(ctx, rk, simulationID)
	pipe.Expire(ctx, rk, subscriptionTTL)

	_, err := pipe.Exec(ctx)
	return err
}

// Unsubscribe removes sessionID from a single simulation's subscriber set.
func (s *RedisSubscriptionStore) Unsubscribe(ctx context.Context, simulationID, sessionID string) error {
	pipe := s.client.Pipeline()
	pipe.SRem(ctx, fwdKey(simulationID), sessionID)
	pipe.SRem(ctx, revKey(sessionID), simulationID)
	_, err := pipe.Exec(ctx)
	return err
}

// UnsubscribeAll reads the reverse index for sessionID, removes the session
// from every simulation's forward set, then deletes the reverse key.
func (s *RedisSubscriptionStore) UnsubscribeAll(ctx context.Context, sessionID string) error {
	rk := revKey(sessionID)

	// Read all simulations this session was subscribed to
	simIDs, err := s.client.SMembers(ctx, rk).Result()
	if err != nil {
		return err
	}

	if len(simIDs) == 0 {
		return nil
	}

	pipe := s.client.Pipeline()
	for _, simID := range simIDs {
		pipe.SRem(ctx, fwdKey(simID), sessionID)
	}
	pipe.Del(ctx, rk)
	_, err = pipe.Exec(ctx)
	return err
}

// Lookup returns all session IDs subscribed to a simulation.
func (s *RedisSubscriptionStore) Lookup(ctx context.Context, simulationID string) ([]string, error) {
	return s.client.SMembers(ctx, fwdKey(simulationID)).Result()
}

// NullSubscriptionStore is a no-op implementation for use when Redis is
// unavailable (local dev without docker) or in tests that don't care about
// cross-instance subscriptions.
type NullSubscriptionStore struct{}

func (n *NullSubscriptionStore) Subscribe(ctx context.Context, simulationID, sessionID string) error {
	return nil
}

func (n *NullSubscriptionStore) Unsubscribe(ctx context.Context, simulationID, sessionID string) error {
	return nil
}

func (n *NullSubscriptionStore) UnsubscribeAll(ctx context.Context, sessionID string) error {
	return nil
}

func (n *NullSubscriptionStore) Lookup(ctx context.Context, simulationID string) ([]string, error) {
	return nil, nil
}

// logSubscriptionError logs a subscription store error without blocking
// the Hub's event loop. Subscription store failures are non-fatal — the
// local in-memory maps continue to work for same-instance routing.
func logSubscriptionError(op string, err error) {
	if err != nil {
		log.Printf("Hub: SubscriptionStore.%s failed (non-fatal): %v", op, err)
	}
}
