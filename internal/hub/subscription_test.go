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
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func newTestRedisSubscriptionStore(t *testing.T) (*RedisSubscriptionStore, *miniredis.Miniredis) {
	t.Helper()
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	t.Cleanup(func() { client.Close() })
	store := NewRedisSubscriptionStore(client)
	return store, s
}

func TestRedisSubscriptionStore_SubscribeAndLookup(t *testing.T) {
	store, _ := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	// Subscribe session-1 to sim-A
	err := store.Subscribe(ctx, "sim-A", "session-1")
	require.NoError(t, err)

	// Subscribe session-2 to sim-A
	err = store.Subscribe(ctx, "sim-A", "session-2")
	require.NoError(t, err)

	// Lookup sim-A should return both
	sessions, err := store.Lookup(ctx, "sim-A")
	require.NoError(t, err)
	assert.ElementsMatch(t, []string{"session-1", "session-2"}, sessions)
}

func TestRedisSubscriptionStore_SubscribeIdempotent(t *testing.T) {
	store, _ := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	// Subscribe same session twice
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))

	sessions, err := store.Lookup(ctx, "sim-A")
	require.NoError(t, err)
	assert.Equal(t, []string{"session-1"}, sessions)
}

func TestRedisSubscriptionStore_Unsubscribe(t *testing.T) {
	store, _ := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	// Subscribe then unsubscribe
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-2"))

	err := store.Unsubscribe(ctx, "sim-A", "session-1")
	require.NoError(t, err)

	sessions, err := store.Lookup(ctx, "sim-A")
	require.NoError(t, err)
	assert.Equal(t, []string{"session-2"}, sessions)
}

func TestRedisSubscriptionStore_UnsubscribeAll(t *testing.T) {
	store, _ := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	// Subscribe session-1 to multiple simulations
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))
	require.NoError(t, store.Subscribe(ctx, "sim-B", "session-1"))
	require.NoError(t, store.Subscribe(ctx, "sim-C", "session-1"))

	// Also subscribe session-2 to sim-A (should survive)
	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-2"))

	// UnsubscribeAll for session-1
	err := store.UnsubscribeAll(ctx, "session-1")
	require.NoError(t, err)

	// sim-A should only have session-2
	sessions, err := store.Lookup(ctx, "sim-A")
	require.NoError(t, err)
	assert.Equal(t, []string{"session-2"}, sessions)

	// sim-B and sim-C should be empty
	sessionsB, err := store.Lookup(ctx, "sim-B")
	require.NoError(t, err)
	assert.Empty(t, sessionsB)

	sessionsC, err := store.Lookup(ctx, "sim-C")
	require.NoError(t, err)
	assert.Empty(t, sessionsC)
}

func TestRedisSubscriptionStore_LookupEmpty(t *testing.T) {
	store, _ := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	sessions, err := store.Lookup(ctx, "nonexistent-sim")
	require.NoError(t, err)
	assert.Empty(t, sessions)
}

func TestRedisSubscriptionStore_TTLIsSet(t *testing.T) {
	store, mr := newTestRedisSubscriptionStore(t)
	ctx := context.Background()

	require.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))

	// Check that forward key has a TTL set
	ttl := mr.TTL("sim_sub:sim-A")
	assert.Greater(t, ttl, time.Duration(0), "forward key should have TTL")
	assert.LessOrEqual(t, ttl, 2*time.Hour, "TTL should not exceed 2 hours")

	// Check that reverse key has a TTL set
	revTTL := mr.TTL("sim_sub_rev:session-1")
	assert.Greater(t, revTTL, time.Duration(0), "reverse key should have TTL")
	assert.LessOrEqual(t, revTTL, 2*time.Hour, "TTL should not exceed 2 hours")
}

func TestNullSubscriptionStore_NoOp(t *testing.T) {
	store := &NullSubscriptionStore{}
	ctx := context.Background()

	// All operations should succeed silently
	assert.NoError(t, store.Subscribe(ctx, "sim-A", "session-1"))
	assert.NoError(t, store.Unsubscribe(ctx, "sim-A", "session-1"))
	assert.NoError(t, store.UnsubscribeAll(ctx, "session-1"))

	sessions, err := store.Lookup(ctx, "sim-A")
	assert.NoError(t, err)
	assert.Empty(t, sessions)
}
