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

package agent

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestCatalog_DiscoverAgents(t *testing.T) {
	card := AgentCard{
		Name:        "mock_runner",
		Description: "A mock agent for testing",
		Version:     "1.0.0",
	}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})
	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Len(t, agents, 1)
	assert.Contains(t, agents, "mock_runner")
	assert.Equal(t, "mock_runner", agents["mock_runner"].Name)
}

func TestCatalog_DiscoverAgents_RetryOnFailure(t *testing.T) {
	var attempts atomic.Int32
	card := AgentCard{
		Name:        "flaky_agent",
		Description: "Returns 503 twice then succeeds",
		Version:     "1.0.0",
	}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/.well-known/agent-card.json" {
			http.NotFound(w, r)
			return
		}
		n := attempts.Add(1)
		if n <= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(cardJSON)
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})
	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Len(t, agents, 1)
	assert.Contains(t, agents, "flaky_agent")
	assert.GreaterOrEqual(t, int(attempts.Load()), 3, "Should have retried at least twice")
}

func TestCatalog_DiscoverAgents_SkipsUnreachable(t *testing.T) {
	goodCard := AgentCard{
		Name:        "good_agent",
		Description: "Always available",
		Version:     "1.0.0",
	}
	cardJSON, _ := json.Marshal(goodCard)

	goodServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer goodServer.Close()

	// Use a URL that will never connect (closed port)
	badURL := "http://127.0.0.1:1" // port 1 should be unreachable

	catalog := NewCatalog([]string{badURL, goodServer.URL})
	agents, err := catalog.DiscoverAgents()

	// Should NOT return error — unreachable agents are skipped
	require.NoError(t, err)
	assert.Len(t, agents, 1)
	assert.Contains(t, agents, "good_agent")
}

func TestCatalog_DiscoverAgents_SetsURLFromEndpoint(t *testing.T) {
	// Card has no URL set — catalog should set it from the fetch endpoint
	card := AgentCard{
		Name:    "auto_url_agent",
		Version: "1.0.0",
	}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})
	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	require.Contains(t, agents, "auto_url_agent")
	// URL should be set to the base URL we fetched from
	assert.Equal(t, server.URL, agents["auto_url_agent"].URL)
}

func TestCatalog_DiscoverAgents_MultipleAgents(t *testing.T) {
	makeServer := func(name string) *httptest.Server {
		card := AgentCard{
			Name:    name,
			Version: "1.0.0",
			Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "subscriber"},
					},
				},
			},
		}
		cardJSON, _ := json.Marshal(card)
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			} else {
				http.NotFound(w, r)
			}
		}))
	}

	runnerSrv := makeServer("runner_autopilot")
	defer runnerSrv.Close()
	simSrv := makeServer("simulator")
	defer simSrv.Close()
	plannerSrv := makeServer("planner")
	defer plannerSrv.Close()

	catalog := NewCatalog([]string{runnerSrv.URL, simSrv.URL, plannerSrv.URL})
	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Len(t, agents, 3)
	for _, name := range []string{"runner_autopilot", "simulator", "planner"} {
		assert.Contains(t, agents, name, fmt.Sprintf("Should discover %s", name))
		assert.Equal(t, "subscriber", agents[name].DispatchMode())
	}
}

// --- AE-specific tests ---

func TestIsAgentEngineURL(t *testing.T) {
	tests := []struct {
		name     string
		url      string
		expected bool
	}{
		{
			name:     "standard local URL",
			url:      "http://127.0.0.1:8201",
			expected: false,
		},
		{
			name:     "cloud run URL",
			url:      "https://runner-123456.us-central1.run.app",
			expected: false,
		},
		{
			name:     "agent engine URL",
			url:      "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456",
			expected: true,
		},
		{
			name:     "agent engine URL without reasoningEngines",
			url:      "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123",
			expected: false,
		},
		{
			name:     "partial match aiplatform only",
			url:      "https://aiplatform.googleapis.com/v1/something",
			expected: false,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, isAgentEngineURL(tt.url))
		})
	}
}

func TestCatalog_DiscoverAgents_AECardPath(t *testing.T) {
	card := AgentCard{
		Name:        "ae_simulator",
		Description: "Agent Engine simulator",
		Version:     "1.0.0",
	}
	cardJSON, _ := json.Marshal(card)

	var requestedPath string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestedPath = r.URL.Path
		// Serve the card at the AE card path suffix
		if strings.HasSuffix(r.URL.Path, "/a2a/v1/card") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	// Build a URL that triggers isAgentEngineURL by embedding keywords in the path.
	// isAgentEngineURL uses strings.Contains, so the keywords can be anywhere in the URL.
	aeURL := server.URL + "/aiplatform.googleapis.com/reasoningEngines/456"

	catalog := &Catalog{
		agentURLs: []string{aeURL},
		client:    newRetryableClient(nil),
		gcpClient: newRetryableClient(&http.Client{Timeout: 5 * time.Second}),
	}

	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Contains(t, agents, "ae_simulator")
	// Verify the AE card path was used, not the well-known path
	assert.Contains(t, requestedPath, "/a2a/v1/card")
	assert.NotContains(t, requestedPath, ".well-known")
}

func TestCatalog_DiscoverAgents_AERetry(t *testing.T) {
	var attempts atomic.Int32
	card := AgentCard{
		Name:        "flaky_ae_agent",
		Description: "Returns 503 twice then succeeds (AE path)",
		Version:     "1.0.0",
	}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !strings.HasSuffix(r.URL.Path, "/a2a/v1/card") {
			http.NotFound(w, r)
			return
		}
		n := attempts.Add(1)
		if n <= 2 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(cardJSON)
	}))
	defer server.Close()

	aeURL := server.URL + "/aiplatform.googleapis.com/reasoningEngines/789"

	// Build catalog with a retryable test client (simulates what NewCatalog
	// does for the real GCP client — wrapping in retryablehttp).
	catalog := &Catalog{
		agentURLs: []string{aeURL},
		client:    newRetryableClient(nil),
		gcpClient: newRetryableClient(&http.Client{Timeout: 5 * time.Second}),
	}

	agents, err := catalog.DiscoverAgents()

	// Without retries, this will fail because the first 2 attempts return 503.
	// With retries, it should succeed on the 3rd attempt.
	require.NoError(t, err)
	assert.Contains(t, agents, "flaky_ae_agent")
	assert.GreaterOrEqual(t, int(attempts.Load()), 3, "Should have retried at least twice for AE agent")
}

func TestCatalog_DiscoverAgents_ErrorBodyInLog(t *testing.T) {
	// Use 403 (non-retryable) so the response reaches fetchCard directly.
	// retryablehttp only retries on 429/500/502/503/504.
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
		_, _ = w.Write([]byte(`{"error": "set_up() failed: ModuleNotFoundError"}`))
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})
	_, err := catalog.DiscoverAgents()

	// Should fail (no agents discovered), and the error should contain
	// the response body text from the server
	require.Error(t, err)
	assert.Contains(t, err.Error(), "ModuleNotFoundError")
}

func TestCatalog_DiscoverAgents_ConcurrentFetch(t *testing.T) {
	// Create 5 agents with staggered delays to prove concurrent execution.
	// If sequential, total time > 5 * delay. If concurrent, total time ~ delay.
	const agentCount = 5
	const delay = 200 * time.Millisecond

	makeServer := func(name string) *httptest.Server {
		card := AgentCard{Name: name, Version: "1.0.0"}
		cardJSON, _ := json.Marshal(card)
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			time.Sleep(delay)
			if r.URL.Path == wellKnownPath {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			} else {
				http.NotFound(w, r)
			}
		}))
	}

	var urls []string
	for i := 0; i < agentCount; i++ {
		srv := makeServer(fmt.Sprintf("agent_%d", i))
		defer srv.Close()
		urls = append(urls, srv.URL)
	}

	catalog := NewCatalog(urls)
	start := time.Now()
	agents, err := catalog.DiscoverAgents()
	elapsed := time.Since(start)

	require.NoError(t, err)
	assert.Len(t, agents, agentCount)
	// If concurrent, should be ~delay (200ms) not 5*delay (1000ms).
	// Use 3*delay as threshold to be safe.
	maxExpected := time.Duration(agentCount-1) * delay
	assert.Less(t, elapsed, maxExpected,
		"Discovery should be concurrent, not sequential (took %v, threshold %v)", elapsed, maxExpected)
}

func TestCatalog_DiscoverAgents_AEURLOverride(t *testing.T) {
	// AE cards return their own URL, but the gateway should override it
	// with the AGENT_URLS base URL to prevent double /a2a/a2a paths.
	card := AgentCard{
		Name:    "ae_planner",
		Version: "1.0.0",
		URL:     "https://some-internal-ae-url/a2a",
	}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/a2a/v1/card") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	aeURL := server.URL + "/aiplatform.googleapis.com/reasoningEngines/999"
	catalog := &Catalog{
		agentURLs: []string{aeURL},
		client:    newRetryableClient(nil),
		gcpClient: newRetryableClient(&http.Client{Timeout: 5 * time.Second}),
	}

	agents, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	require.Contains(t, agents, "ae_planner")
	// URL should be the AGENT_URLS base, NOT the card's own URL
	assert.Equal(t, aeURL, agents["ae_planner"].URL,
		"AE card URL must not be path-mangled — should be the discovery base URL")
	assert.Equal(t, aeURL, agents["ae_planner"].BaseURL,
		"AE BaseURL should match the discovery URL")
}

func TestAgentCard_DispatchMode(t *testing.T) {
	tests := []struct {
		name     string
		card     AgentCard
		expected string
	}{
		{
			name: "subscriber mode from extension",
			card: AgentCard{Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "subscriber"},
					},
				},
			}},
			expected: "subscriber",
		},
		{
			name: "callable mode from extension",
			card: AgentCard{Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "callable"},
					},
				},
			}},
			expected: "callable",
		},
		{
			name:     "no extensions defaults to subscriber",
			card:     AgentCard{Capabilities: map[string]interface{}{}},
			expected: "subscriber",
		},
		{
			name:     "nil capabilities defaults to subscriber",
			card:     AgentCard{},
			expected: "subscriber",
		},
		{
			name: "other extension ignored, defaults to subscriber",
			card: AgentCard{Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "a2ui:json/1.0",
						"params": map[string]interface{}{"catalog": "standard"},
					},
				},
			}},
			expected: "subscriber",
		},
		{
			name: "dispatch extension among multiple extensions",
			card: AgentCard{Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "a2ui:json/1.0",
						"params": map[string]interface{}{"catalog": "standard"},
					},
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": "callable"},
					},
				},
			}},
			expected: "callable",
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.expected, tt.card.DispatchMode())
		})
	}
}

func TestAgentCard_OrchestrationBaseURL_ReturnsBaseURL(t *testing.T) {
	card := AgentCard{
		URL:     "http://localhost:8202/a2a/simulator/",
		BaseURL: "http://localhost:8202",
	}
	assert.Equal(t, "http://localhost:8202", card.OrchestrationBaseURL())
}

func TestAgentCard_OrchestrationBaseURL_FallsBackToURL(t *testing.T) {
	card := AgentCard{
		URL: "http://localhost:8202",
	}
	assert.Equal(t, "http://localhost:8202", card.OrchestrationBaseURL())
}

func TestCatalog_DiscoverAgents_CachesResults(t *testing.T) {
	// Two calls in quick succession should only hit the server once.
	var fetchCount atomic.Int32
	card := AgentCard{Name: "cached_agent", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == wellKnownPath {
			fetchCount.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})

	// First call — cache miss, should fetch
	agents1, err := catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Contains(t, agents1, "cached_agent")

	// Second call — should serve from cache, NOT fetch again
	agents2, err := catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Contains(t, agents2, "cached_agent")

	assert.Equal(t, int32(1), fetchCount.Load(),
		"Server should be hit exactly once; second call should use cache")
}

func TestCatalog_DiscoverAgents_CacheExpires(t *testing.T) {
	// Verifies: cache serves within TTL, then refreshes after TTL expires.
	var fetchCount atomic.Int32
	card := AgentCard{Name: "expiring_agent", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == wellKnownPath {
			fetchCount.Add(1)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	catalog := NewCatalogWithTTL([]string{server.URL}, 50*time.Millisecond)

	// First call — cache miss, fetches
	_, err := catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Equal(t, int32(1), fetchCount.Load())

	// Second call immediately — should be cached (count stays 1)
	_, err = catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Equal(t, int32(1), fetchCount.Load(),
		"Immediate second call should use cache, not fetch again")

	// Wait for TTL to expire
	time.Sleep(100 * time.Millisecond)

	// Third call — cache expired, should fetch again
	_, err = catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Equal(t, int32(2), fetchCount.Load(),
		"Server should be hit again after cache TTL expires")
}

func TestCatalog_DiscoverAgents_CacheConcurrentSafe(t *testing.T) {
	// Multiple goroutines calling DiscoverAgents concurrently should not race.
	var fetchCount atomic.Int32
	card := AgentCard{Name: "concurrent_agent", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == wellKnownPath {
			fetchCount.Add(1)
			time.Sleep(50 * time.Millisecond) // Simulate network latency
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	defer server.Close()

	catalog := NewCatalog([]string{server.URL})

	// Launch 10 concurrent callers
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			agents, err := catalog.DiscoverAgents()
			assert.NoError(t, err)
			assert.Contains(t, agents, "concurrent_agent")
		}()
	}
	wg.Wait()

	// With cache, server should be hit very few times (ideally 1).
	// Without singleflight, concurrent first-calls may hit 2-3 times max.
	// The key assertion is it should NOT be 10.
	assert.LessOrEqual(t, fetchCount.Load(), int32(3),
		"With caching, 10 concurrent calls should NOT produce 10 fetches")
}
