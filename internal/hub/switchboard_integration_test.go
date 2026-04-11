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
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSwitchboard_Integration(t *testing.T) {
	s := miniredis.RunT(t)
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	defer client.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// 2. Setup multiple Switchboards and Hubs to simulate multiple Gateway instances
	hub1 := NewHub()
	sb1 := NewSwitchboardWithRegistry(client, "gw-1", hub1, nil, nil)

	hub2 := NewHub()
	sb2 := NewSwitchboardWithRegistry(client, "gw-2", hub2, nil, nil)

	// Start both switchboards
	go func() {
		if err := sb1.Start(ctx); err != nil && err != context.Canceled {
			t.Logf("sb1 error: %v", err)
		}
	}()
	go func() {
		if err := sb2.Start(ctx); err != nil && err != context.Canceled {
			t.Logf("sb2 error: %v", err)
		}
	}()

	// Wait for subscriptions to stabilize
	time.Sleep(200 * time.Millisecond)

	t.Run("Cross-Instance Broadcast", func(t *testing.T) {
		testMsg := &gateway.Wrapper{
			Type:      "broadcast",
			SessionId: "global-session",
			Payload:   []byte("sync data"),
		}

		// Subscribe BEFORE broadcasting to avoid race
		pubsub := client.Subscribe(ctx, sb1.Channel())
		defer pubsub.Close()

		// Wait for subscription to be registered in Redis
		time.Sleep(100 * time.Millisecond)

		// Instance 1 broadcasts
		err := sb1.Broadcast(ctx, testMsg)
		require.NoError(t, err)

		// Verification via pubsub
		msg, err := pubsub.ReceiveMessage(ctx)
		require.NoError(t, err)
		assert.Equal(t, sb1.Channel(), msg.Channel)
	})

	t.Run("Orchestration Routing", func(t *testing.T) {
		queue := "simulation:spawns:test_agent"
		event := map[string]interface{}{"id": "123", "type": "spawn"}

		err := sb1.EnqueueOrchestration(ctx, queue, event)
		require.NoError(t, err)

		// Verify list contains the message
		val, err := client.LPop(ctx, queue).Result()
		require.NoError(t, err)
		assert.Contains(t, val, "spawn")
		assert.Contains(t, val, "123")
	})
}
