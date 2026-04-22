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

package main

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/gen_proto/gateway"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/proto"
)

// MockSwitchboard for testing protocol handling
type MockSwitchboard struct {
	mu                            sync.Mutex
	BroadcastCalled               bool
	BroadcastData                 []byte
	PublishOrchestrationCalled    bool
	PublishOrchestrationChannel   string
	PublishOrchestrationCallCount int
	PublishOrchestrationEvents    []map[string]interface{}
	EnqueueCalled                 bool
	EnqueueQueue                  string
	BatchEnqueueCalled            bool
	BatchEnqueueItems             []hub.QueueItem
	DispatchToAgentCalled         bool
	DispatchAgentType             string
	PokeAgentCalled               bool
	PokeAgentType                 string
	PokeAgentCallCount            int
	PokeAgentTypes                []string
	PokeAgentEvents               []map[string]interface{}
	FlushQueuesCalled             bool
	FlushQueuesCount              int
	LastEvent                     map[string]interface{}
	Done                          chan bool
}

func (m *MockSwitchboard) Broadcast(ctx context.Context, wrapper *gateway.Wrapper) error {
	m.BroadcastCalled = true
	if data, err := proto.Marshal(wrapper); err == nil {
		m.BroadcastData = data
	}
	return nil
}

func (m *MockSwitchboard) EnqueueOrchestration(ctx context.Context, queue string, event interface{}) error {
	m.EnqueueCalled = true
	m.EnqueueQueue = queue
	if ev, ok := event.(map[string]interface{}); ok {
		m.LastEvent = ev
	}
	if m.Done != nil {
		m.Done <- true
	}
	return nil
}

func (m *MockSwitchboard) BatchEnqueueOrchestration(ctx context.Context, items []hub.QueueItem) error {
	m.BatchEnqueueCalled = true
	m.BatchEnqueueItems = items
	return nil
}

func (m *MockSwitchboard) PublishOrchestration(ctx context.Context, channel string, event interface{}) error {
	m.PublishOrchestrationCalled = true
	m.PublishOrchestrationChannel = channel
	m.PublishOrchestrationCallCount++
	if ev, ok := event.(map[string]interface{}); ok {
		m.LastEvent = ev
		m.PublishOrchestrationEvents = append(m.PublishOrchestrationEvents, ev)
	}
	if m.Done != nil {
		m.Done <- true
	}
	return nil
}

func (m *MockSwitchboard) DispatchToAgent(ctx context.Context, agentType string, event interface{}) error {
	m.DispatchToAgentCalled = true
	m.DispatchAgentType = agentType
	return nil
}

func (m *MockSwitchboard) PokeAgent(ctx context.Context, agentType string, event interface{}) error {
	m.mu.Lock()
	m.PokeAgentCalled = true
	m.PokeAgentType = agentType
	m.PokeAgentCallCount++
	m.PokeAgentTypes = append(m.PokeAgentTypes, agentType)
	if ev, ok := event.(map[string]interface{}); ok {
		m.PokeAgentEvents = append(m.PokeAgentEvents, ev)
	}
	m.mu.Unlock()
	if m.Done != nil {
		m.Done <- true
	}
	return nil
}

func (m *MockSwitchboard) FlushQueues(ctx context.Context) (int, error) {
	m.FlushQueuesCalled = true
	return m.FlushQueuesCount, nil
}

func (m *MockSwitchboard) Ping(ctx context.Context) error {
	return nil
}

func (m *MockSwitchboard) Start(ctx context.Context) error {
	return nil
}

func (m *MockSwitchboard) Channel() string {
	return "gateway:broadcast"
}

func TestHandleBinaryMessage_Broadcast(t *testing.T) {
	mockSb := &MockSwitchboard{Done: make(chan bool, 1)}

	// 1. Create a BroadcastRequest
	br := &gateway.BroadcastRequest{
		Payload:          []byte(`{"text": "Plan a marathon"}`),
		TargetSessionIds: []string{"planner-1"},
	}
	brData, _ := proto.Marshal(br)

	// 2. Wrap it in a Wrapper
	wrapper := &gateway.Wrapper{
		Type:      "broadcast",
		RequestId: "req-123",
		Payload:   brData,
	}
	wrapperData, _ := proto.Marshal(wrapper)

	// 3. Handle it
	handleBinaryMessage(context.Background(), "test-session", wrapperData, mockSb, nil)

	// Wait for async orchestration call
	select {
	case <-mockSb.Done:
		// success
	case <-time.After(500 * time.Millisecond):
		t.Fatal("Timeout waiting for PublishOrchestration")
	}

	// 4. Verify fanned out both locally and to orchestration
	assert.True(t, mockSb.BroadcastCalled, "Should have called Broadcast for internal fan-out")
	assert.True(t, mockSb.PublishOrchestrationCalled, "Should have called PublishOrchestration for agent fan-out")

	// 5. Verify orchestrated payload format
	assert.Equal(t, "broadcast", mockSb.LastEvent["type"])
	payload := mockSb.LastEvent["payload"].(map[string]interface{})
	assert.Equal(t, `{"text": "Plan a marathon"}`, payload["data"])
	assert.ElementsMatch(t, []string{"planner-1"}, payload["targets"])
}
