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
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/redis/go-redis/v9"
)

// --- Shared Agent Mock ---

// pokeRecord captures what an agent mock received.
type pokeRecord struct {
	Path string
	Body []byte
}

// agentMock is a thread-safe mock HTTP server that records incoming pokes.
type agentMock struct {
	server   *httptest.Server
	mu       sync.Mutex
	pokes    []pokeRecord
	hitCount atomic.Int32
}

func newAgentMock() *agentMock {
	m := &agentMock{}
	m.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		m.mu.Lock()
		m.pokes = append(m.pokes, pokeRecord{Path: r.URL.Path, Body: body})
		m.mu.Unlock()
		m.hitCount.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	return m
}

func (m *agentMock) close()      { m.server.Close() }
func (m *agentMock) url() string { return m.server.URL }
func (m *agentMock) hits() int   { return int(m.hitCount.Load()) }

func (m *agentMock) getPokes() []pokeRecord {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := make([]pokeRecord, len(m.pokes))
	copy(result, m.pokes)
	return result
}

func (m *agentMock) reset() {
	m.mu.Lock()
	m.pokes = nil
	m.mu.Unlock()
	m.hitCount.Store(0)
}

// --- Shared Catalog Helper ---

// createTestAgentURLs starts one httptest.Server per agent, each serving
// a card at /.well-known/agent-card.json AND proxying all other requests
// to the corresponding agentMock. This is necessary because the Catalog's
// URL-rewriting logic rewrites card.URL to the discovery server's base URL,
// so poke requests (e.g. POST /orchestration) arrive at this server, not
// at the agentMock directly.
//
// mocksByName maps agent name -> *agentMock. Agents without an entry get
// 404 for non-card paths (backward-compatible with tests that don't need
// pokes).
//
// NOTE: agents is a map, and Go map iteration order is non-deterministic.
// Mocks MUST be keyed by name, not positional, to avoid flaky test failures
// where mock assignments are swapped.
func createTestAgentURLs(t *testing.T, agents map[string]interface{}, mocksByName map[string]*agentMock) []string {
	t.Helper()
	var urls []string
	for name, raw := range agents {
		cardJSON, err := json.Marshal(raw)
		if err != nil {
			t.Fatalf("createTestAgentURLs: failed to marshal: %v", err)
		}
		mock := mocksByName[name]
		// Capture for closure
		localCardJSON := cardJSON
		localMock := mock
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(localCardJSON)
				return
			}
			// Forward non-card requests to the agent mock so poke
			// recording works even after catalog URL-rewriting.
			if localMock != nil {
				localMock.server.Config.Handler.ServeHTTP(w, r)
				return
			}
			http.NotFound(w, r)
		}))
		t.Cleanup(srv.Close)
		urls = append(urls, srv.URL)
	}
	return urls
}

// --- Shared Redis Helper ---

// requireRedis connects to Docker Redis or skips the test.
// Uses REDIS_ADDR env or falls back to localhost:8102 (docker-compose.test.yml).
func requireRedis(t *testing.T) *redis.Client {
	t.Helper()
	addr := os.Getenv("REDIS_ADDR")
	if addr == "" {
		addr = "localhost:8102"
	}
	client := redis.NewClient(&redis.Options{Addr: addr})
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := client.Ping(ctx).Err(); err != nil {
		t.Skipf("Docker Redis not available at %s — run: docker compose -f docker-compose.test.yml up -d", addr)
	}
	client.FlushAll(ctx)
	return client
}

// --- Shared Gateway Stack ---

// testGatewayStack holds all components needed to exercise the full gateway.
type testGatewayStack struct {
	Hub         *hub.Hub
	Catalog     *agent.Catalog
	Registry    *session.RedisSessionRegistry
	Switchboard hub.Switchboard
	Router      http.Handler
}

// newTestGatewayStack creates a complete gateway stack wired with real Redis
// and session-aware routing. agentURLs are the base URLs for agent card
// discovery (e.g. from createTestAgentURLs).
func newTestGatewayStack(t *testing.T, rdb *redis.Client, agentURLs []string, prefix string) *testGatewayStack {
	t.Helper()
	h := hub.NewHub()
	go h.Run()
	catalog := agent.NewCatalog(agentURLs)
	reg := session.NewRedisSessionRegistry(rdb, prefix, 1*time.Hour)
	sb := hub.NewSwitchboardWithRegistry(rdb, prefix+"-gw", h, catalog, reg)
	router := setupRouter(h, sb, catalog, reg, prefix+"-gw", rdb, nil)
	return &testGatewayStack{
		Hub:         h,
		Catalog:     catalog,
		Registry:    reg,
		Switchboard: sb,
		Router:      router,
	}
}
