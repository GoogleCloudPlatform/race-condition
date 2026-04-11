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
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// Integration tests for the HTTP-based catalog discovery system.
// These validate the full discovery lifecycle including resilience,
// dispatch mode extraction, and multi-agent scenarios.

func TestIntegration_CatalogDiscovery_FullLifecycle(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Start 4 agents with different dispatch modes (mirrors real system)
	agents := []struct {
		name     string
		dispatch string
		version  string
	}{
		{"runner_autopilot", "subscriber", "1.0.0"},
		{"simulator", "callable", "1.0.0"},
		{"planner", "callable", "1.0.0"},
		{"debug", "callable", "1.0.0"},
	}

	var urls []string
	for _, a := range agents {
		card := AgentCard{
			Name:    a.name,
			Version: a.version,
			Capabilities: map[string]interface{}{
				"extensions": []interface{}{
					map[string]interface{}{
						"uri":    "n26:dispatch/1.0",
						"params": map[string]interface{}{"mode": a.dispatch},
					},
				},
			},
		}
		cardJSON, _ := json.Marshal(card)
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write(cardJSON)
			} else {
				http.NotFound(w, r)
			}
		}))
		t.Cleanup(srv.Close)
		urls = append(urls, srv.URL)
	}

	catalog := NewCatalog(urls)

	// First discovery
	discovered, err := catalog.DiscoverAgents()
	require.NoError(t, err)
	require.Len(t, discovered, 4, "Should discover all 4 agents")

	// Verify each agent's dispatch mode
	assert.Equal(t, "subscriber", discovered["runner_autopilot"].DispatchMode())
	assert.Equal(t, "callable", discovered["simulator"].DispatchMode())
	assert.Equal(t, "callable", discovered["planner"].DispatchMode())
	assert.Equal(t, "callable", discovered["debug"].DispatchMode())

	// Verify URLs are set (auto-populated since cards don't have explicit URLs)
	for _, a := range agents {
		card := discovered[a.name]
		assert.NotEmpty(t, card.URL, "Agent %s should have a URL", a.name)
		assert.Contains(t, card.URL, "127.0.0.1", "URL should be local")
	}

	// Second discovery should yield same results (idempotent)
	discovered2, err := catalog.DiscoverAgents()
	require.NoError(t, err)
	assert.Len(t, discovered2, 4, "Second discovery should find same agents")
}

func TestIntegration_CatalogDiscovery_GracefulDegradation(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// One healthy agent, one unreachable
	healthyCard := AgentCard{Name: "runner_autopilot", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(healthyCard)

	healthySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(healthySrv.Close)

	// Unreachable agent (closed port)
	catalog := NewCatalog([]string{"http://127.0.0.1:1", healthySrv.URL})
	discovered, err := catalog.DiscoverAgents()

	// Must NOT error — unreachable agents are logged and skipped
	require.NoError(t, err)
	assert.Len(t, discovered, 1, "Should discover only the healthy agent")
	assert.Contains(t, discovered, "runner_autopilot")
}

func TestIntegration_CatalogDiscovery_RetryResilience(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Agent that fails twice then succeeds (simulates slow startup)
	var attempts atomic.Int32
	card := AgentCard{
		Name:    "slow_starter",
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

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
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
	t.Cleanup(srv.Close)

	start := time.Now()
	catalog := NewCatalog([]string{srv.URL})
	discovered, err := catalog.DiscoverAgents()
	elapsed := time.Since(start)

	require.NoError(t, err)
	require.Len(t, discovered, 1)
	assert.Equal(t, "slow_starter", discovered["slow_starter"].Name)
	assert.Equal(t, "subscriber", discovered["slow_starter"].DispatchMode())
	assert.GreaterOrEqual(t, int(attempts.Load()), 3,
		"Should have retried at least twice before succeeding")
	t.Logf("Discovery with 2 retries took %v", elapsed)
}

func TestIntegration_CatalogDiscovery_EmptyURLList(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	catalog := NewCatalog([]string{})
	discovered, err := catalog.DiscoverAgents()

	require.Error(t, err)
	assert.Contains(t, err.Error(), "no agent URLs configured")
	assert.Empty(t, discovered, "Empty URL list should produce empty catalog")
}

func TestIntegration_CatalogDiscovery_NilURLList(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	catalog := NewCatalog(nil)
	discovered, err := catalog.DiscoverAgents()

	require.Error(t, err)
	assert.Contains(t, err.Error(), "no agent URLs configured")
	assert.Empty(t, discovered, "Nil URL list should produce empty catalog")
}

func TestIntegration_CatalogDiscovery_InvalidJSON(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Agent that returns garbage JSON
	badSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{not valid json`))
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(badSrv.Close)

	// Healthy agent alongside the bad one
	goodCard := AgentCard{Name: "good_agent", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(goodCard)
	goodSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(goodSrv.Close)

	catalog := NewCatalog([]string{badSrv.URL, goodSrv.URL})
	discovered, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Len(t, discovered, 1, "Bad JSON agent should be skipped")
	assert.Contains(t, discovered, "good_agent")
}

func TestIntegration_CatalogDiscovery_UsesDiscoveryURL(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Card that has an explicit URL different from the server it's served from.
	// The catalog should override the card's URL with the AGENT_URLS discovery
	// URL, because the gateway's AGENT_URLS contains the internal/private URL
	// for service-to-service communication. The card's self-reported URL may
	// be an IAP-fronted public URL that the gateway cannot reach.
	card := AgentCard{
		Name:    "remote_runner",
		Version: "2.0.0",
		URL:     "http://production.example.com/a2a/runner",
	}
	cardJSON, _ := json.Marshal(card)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	catalog := NewCatalog([]string{srv.URL})
	discovered, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	require.Contains(t, discovered, "remote_runner")
	assert.Equal(t, srv.URL+"/a2a/runner", discovered["remote_runner"].URL,
		"Card URL should use discovery host but preserve the A2A path")
	assert.Equal(t, srv.URL, discovered["remote_runner"].BaseURL,
		"BaseURL should be the discovery base URL for orchestration routing")
}

func TestIntegration_CatalogDiscovery_DuplicateNames(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Two servers serving cards with the same name — last one wins
	makeServer := func(name, version string) *httptest.Server {
		card := AgentCard{Name: name, Version: version}
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

	srv1 := makeServer("runner_autopilot", "1.0.0")
	t.Cleanup(srv1.Close)
	srv2 := makeServer("runner_autopilot", "2.0.0")
	t.Cleanup(srv2.Close)

	catalog := NewCatalog([]string{srv1.URL, srv2.URL})
	discovered, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	assert.Len(t, discovered, 1, "Duplicate names should result in one entry")
	assert.Contains(t, discovered, "runner_autopilot")
	t.Logf("Runner_autopilot version after dedup: %s", discovered["runner_autopilot"].Version)
}

func TestIntegration_CatalogDiscovery_CorrectPath(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Verify the catalog appends the correct well-known path
	var requestedPath string
	card := AgentCard{Name: "path_checker", Version: "1.0.0"}
	cardJSON, _ := json.Marshal(card)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requestedPath = r.URL.Path
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			w.WriteHeader(http.StatusNotFound)
			_, _ = fmt.Fprintf(w, "unexpected path: %s", r.URL.Path)
		}
	}))
	t.Cleanup(srv.Close)

	catalog := NewCatalog([]string{srv.URL})
	_, err := catalog.DiscoverAgents()
	require.NoError(t, err)

	assert.Equal(t, "/.well-known/agent-card.json", requestedPath,
		"Catalog must fetch from the A2A well-known path")
}

func TestIntegration_CatalogDiscovery_PreservesCardPath(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Card with a self-reported URL that includes an A2A path.
	// The catalog should preserve the path but replace the host with the
	// discovery base URL.
	card := AgentCard{
		Name:    "simulator",
		Version: "1.0.0",
		URL:     "http://public.example.com/a2a/simulator/",
	}
	cardJSON, _ := json.Marshal(card)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	catalog := NewCatalog([]string{srv.URL})
	discovered, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	require.Contains(t, discovered, "simulator")

	// URL should be discovery base + original path
	assert.Equal(t, srv.URL+"/a2a/simulator/", discovered["simulator"].URL,
		"Card URL should preserve the A2A path from the original card")
	// BaseURL should be the discovery base URL
	assert.Equal(t, srv.URL, discovered["simulator"].BaseURL,
		"BaseURL should be the discovery base URL for orchestration routing")
}

func TestIntegration_CatalogDiscovery_NoPathCardUsesBaseURL(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping integration test in short mode")
	}

	// Card with no path (or root-only path) should fall back to the base URL.
	card := AgentCard{
		Name:    "runner_autopilot",
		Version: "1.0.0",
		URL:     "http://some-host:8210/",
	}
	cardJSON, _ := json.Marshal(card)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write(cardJSON)
		} else {
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(srv.Close)

	catalog := NewCatalog([]string{srv.URL})
	discovered, err := catalog.DiscoverAgents()

	require.NoError(t, err)
	require.Contains(t, discovered, "runner_autopilot")

	// Root-only path "/" should fall back to using the base URL
	assert.Equal(t, srv.URL, discovered["runner_autopilot"].URL,
		"Card with root-only path should use base URL")
	assert.Equal(t, srv.URL, discovered["runner_autopilot"].BaseURL,
		"BaseURL should be set")
}
