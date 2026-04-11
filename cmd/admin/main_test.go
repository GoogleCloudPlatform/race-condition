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
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/gin-gonic/gin"
	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func init() {
	gin.SetMode(gin.TestMode)
}

func TestHealthInfraEndpoint(t *testing.T) {
	emptyRegistry := ServiceRegistryResponse{Categories: defaultCategories}

	t.Run("Redis and PubSub offline when no clients initialized", func(t *testing.T) {
		checker := newPubSubHealthChecker()
		r := setupRouter(nil, checker, newAlloyDBHealthChecker(), emptyRegistry, nil)

		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/v1/health/infra", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), `"redis":"offline"`)
		assert.Contains(t, w.Body.String(), `"pubsub":"offline"`)
		assert.Contains(t, w.Body.String(), `"alloydb":"offline"`)
	})

	t.Run("Redis online when miniredis is running", func(t *testing.T) {
		s := miniredis.RunT(t)
		rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
		defer rdb.Close()

		checker := newPubSubHealthChecker()
		r := setupRouter(rdb, checker, newAlloyDBHealthChecker(), emptyRegistry, nil)

		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/v1/health/infra", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), `"redis":"online"`)
	})

	t.Run("Redis offline when miniredis is stopped", func(t *testing.T) {
		s := miniredis.RunT(t)
		rdb := redis.NewClient(&redis.Options{Addr: s.Addr()})
		defer rdb.Close()
		s.Close()

		checker := newPubSubHealthChecker()
		r := setupRouter(rdb, checker, newAlloyDBHealthChecker(), emptyRegistry, nil)

		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/v1/health/infra", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), `"redis":"offline"`)
	})
}

func TestAdminHealth(t *testing.T) {
	checker := newPubSubHealthChecker()
	r := setupRouter(nil, checker, newAlloyDBHealthChecker(), ServiceRegistryResponse{Categories: defaultCategories}, nil)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/health", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Body.String(), `"status":"ok"`)
	assert.Contains(t, w.Body.String(), `"service":"admin"`)
}

func TestAdminConfigJS(t *testing.T) {
	checker := newPubSubHealthChecker()
	r := setupRouter(nil, checker, newAlloyDBHealthChecker(), ServiceRegistryResponse{Categories: defaultCategories}, nil)

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/config.js", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/javascript")
	assert.Contains(t, w.Body.String(), "window.ENV")
	assert.Contains(t, w.Body.String(), "GATEWAY_URL")
}

func TestAdminNoRoute_SPAFallback(t *testing.T) {
	checker := newPubSubHealthChecker()
	r := setupRouter(nil, checker, newAlloyDBHealthChecker(), ServiceRegistryResponse{Categories: defaultCategories}, nil)

	t.Run("POST returns 404", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/unknown-path", nil)
		r.ServeHTTP(w, req)
		assert.Equal(t, http.StatusNotFound, w.Code)
	})

	t.Run("File extension returns 404", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/missing-file.js", nil)
		r.ServeHTTP(w, req)
		assert.Equal(t, http.StatusNotFound, w.Code)
	})

	t.Run("Assets path returns 404", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/assets/missing.css", nil)
		r.ServeHTTP(w, req)
		assert.Equal(t, http.StatusNotFound, w.Code)
	})
}

// --- AE Detection Tests ---

func TestIsAgentEngineURL(t *testing.T) {
	tests := []struct {
		name string
		url  string
		want bool
	}{
		{"AE URL", "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456", true},
		{"local URL", "http://127.0.0.1:8202", false},
		{"Cloud Run URL", "https://runner.dev.example.com", false},
		{"empty URL", "", false},
		{"partial AE URL - missing reasoningEngines", "https://aiplatform.googleapis.com/v1", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t, tt.want, isAgentEngineURL(tt.url))
		})
	}
}

func TestNewGCPClient(t *testing.T) {
	t.Run("returns without panicking", func(t *testing.T) {
		// In test environment without GCP credentials, should return nil gracefully
		client := newGCPClient()
		// We can't guarantee ADC is available in tests, so just verify
		// the function doesn't panic and returns a valid type or nil
		if client != nil {
			assert.IsType(t, &http.Client{}, client)
		}
	})
}

// --- Service Registry Tests ---

func TestResolveURL(t *testing.T) {
	t.Run("uses env var when set", func(t *testing.T) {
		os.Setenv("TEST_SVC_URL", "https://custom.example.com")
		defer os.Unsetenv("TEST_SVC_URL")
		assert.Equal(t, "https://custom.example.com", resolveURL("TEST_SVC", "9999"))
	})

	t.Run("falls back to localhost with port", func(t *testing.T) {
		os.Unsetenv("MISSING_URL")
		assert.Equal(t, "http://127.0.0.1:9999", resolveURL("MISSING", "9999"))
	})
}

func TestStaticServices(t *testing.T) {
	services := staticServices()

	t.Run("contains expected services", func(t *testing.T) {
		ids := make(map[string]bool)
		for _, s := range services {
			ids[s.ID] = true
		}
		assert.True(t, ids["admin"], "should include admin")
		assert.True(t, ids["gateway"], "should include gateway")
		assert.True(t, ids["redis"], "should include redis")
		assert.True(t, ids["pubsub"], "should include pubsub")
		assert.True(t, ids["alloydb"], "should include alloydb")
		assert.True(t, ids["dash"], "should include dash")
	})

	t.Run("non-browseable services are correct", func(t *testing.T) {
		for _, s := range services {
			switch s.ID {
			case "redis", "pubsub", "alloydb", "frontend-app":
				assert.False(t, s.Browseable, "%s should not be browseable", s.ID)
			case "gateway", "admin", "tester", "dash", "frontend-bff":
				assert.True(t, s.Browseable, "%s should be browseable", s.ID)
			}
		}
	})
}

func TestFrontendBFFInServiceRegistry(t *testing.T) {
	services := staticServices()
	var found bool
	for _, svc := range services {
		if svc.ID == "frontend-bff" {
			found = true
			assert.Equal(t, "Frontend BFF", svc.Name)
			assert.Equal(t, "frontend", svc.Category)
			assert.True(t, svc.Browseable)
			assert.Equal(t, "go", svc.Type)
			assert.Equal(t, "/health", svc.HealthPath)
			break
		}
	}
	assert.True(t, found, "frontend-bff service should be in static services")
}

func TestLoadAgentsFromGateway(t *testing.T) {
	t.Run("loads agents from gateway API", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			assert.Equal(t, "/api/v1/agent-types", r.URL.Path)
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{
				"planner": {
					"name": "planner",
					"description": "Plans marathon routes.",
					"url": "http://127.0.0.1:8204/a2a/planner/"
				},
				"simulator": {
					"name": "simulator",
					"description": "Orchestrates the race.",
					"url": "http://127.0.0.1:8202/a2a/simulator/"
				}
			}`))
		}))
		defer srv.Close()

		agents := loadAgentsFromGateway(srv.URL)
		assert.Len(t, agents, 2)

		agentMap := make(map[string]ServiceInfo)
		for _, a := range agents {
			agentMap[a.ID] = a
		}

		assert.Contains(t, agentMap, "planner")
		assert.Equal(t, "agent", agentMap["planner"].Category)
		assert.Equal(t, "Planner", agentMap["planner"].Name)
		assert.Equal(t, "Plans marathon routes.", agentMap["planner"].Description)
		assert.False(t, agentMap["planner"].Browseable)
		assert.Equal(t, "python", agentMap["planner"].Type)

		assert.Contains(t, agentMap, "simulator")
		assert.Equal(t, "Simulator", agentMap["simulator"].Name)
	})

	t.Run("returns nil when gateway URL is empty", func(t *testing.T) {
		agents := loadAgentsFromGateway("")
		assert.Nil(t, agents)
	})

	t.Run("returns nil when gateway is unreachable", func(t *testing.T) {
		agents := loadAgentsFromGateway("http://127.0.0.1:1")
		assert.Nil(t, agents)
	})

	t.Run("returns nil for invalid JSON", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte("not json"))
		}))
		defer srv.Close()
		agents := loadAgentsFromGateway(srv.URL)
		assert.Nil(t, agents)
	})

	t.Run("detects AE agents and sets type/healthPath", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{
				"simulator": {
					"name": "simulator",
					"description": "Orchestrates the race.",
					"url": "https://us-central1-aiplatform.googleapis.com/v1beta1/projects/123/locations/us-central1/reasoningEngines/456"
				},
				"runner_autopilot": {
					"name": "runner_autopilot",
					"description": "Runs the race.",
					"url": "http://127.0.0.1:8210/a2a/runner_autopilot/"
				}
			}`))
		}))
		defer srv.Close()

		agents := loadAgentsFromGateway(srv.URL)
		require.Len(t, agents, 2)

		agentMap := make(map[string]ServiceInfo)
		for _, a := range agents {
			agentMap[a.ID] = a
		}

		// AE agent should have type "ae" and card health path
		sim := agentMap["simulator"]
		assert.Equal(t, "ae", sim.Type)
		assert.Equal(t, "/a2a/v1/card", sim.HealthPath)
		assert.Contains(t, sim.URL, "aiplatform.googleapis.com")

		// Local agent should keep type "python" and /health path
		runner := agentMap["runner_autopilot"]
		assert.Equal(t, "python", runner.Type)
		assert.Equal(t, "/health", runner.HealthPath)
	})
}

func TestBuildServiceRegistry(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"planner": {
				"name": "planner",
				"description": "Plans routes.",
				"url": "http://127.0.0.1:8204/a2a/planner/"
			}
		}`))
	}))
	defer srv.Close()

	registry := buildServiceRegistry(srv.URL)

	t.Run("includes categories", func(t *testing.T) {
		assert.Len(t, registry.Categories, 5)
		catIDs := make([]string, len(registry.Categories))
		for i, c := range registry.Categories {
			catIDs[i] = c.ID
		}
		assert.Contains(t, catIDs, "agent")
		assert.Contains(t, catIDs, "core")
	})

	t.Run("merges static services with agents", func(t *testing.T) {
		ids := make(map[string]bool)
		for _, s := range registry.Services {
			ids[s.ID] = true
		}
		// Static services
		assert.True(t, ids["gateway"])
		assert.True(t, ids["redis"])
		// Dynamic agent
		assert.True(t, ids["planner"])
	})
}

func TestServicesEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	gatewaySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"planner": {
				"name": "planner",
				"description": "Plans marathon routes.",
				"url": "http://127.0.0.1:8204/a2a/planner/"
			}
		}`))
	}))
	defer gatewaySrv.Close()

	registry := buildServiceRegistry(gatewaySrv.URL)

	r := gin.New()
	r.GET("/api/v1/services", func(c *gin.Context) {
		c.JSON(http.StatusOK, registry)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/services", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var resp ServiceRegistryResponse
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &resp))

	assert.NotEmpty(t, resp.Categories)
	assert.NotEmpty(t, resp.Services)
}

// --- PubSub Lazy Health Checker Tests ---

func TestPubSubHealthChecker(t *testing.T) {
	t.Run("returns offline when env vars not configured", func(t *testing.T) {
		os.Unsetenv("PUBSUB_PROJECT_ID")
		os.Unsetenv("PROJECT_ID")
		os.Unsetenv("PUBSUB_TOPIC_ID")

		checker := newPubSubHealthChecker()
		assert.Equal(t, "offline", checker.Check())
	})

	t.Run("returns offline when connect func fails", func(t *testing.T) {
		os.Setenv("PUBSUB_PROJECT_ID", "test-project")
		os.Setenv("PUBSUB_TOPIC_ID", "test-topic")
		defer os.Unsetenv("PUBSUB_PROJECT_ID")
		defer os.Unsetenv("PUBSUB_TOPIC_ID")

		checker := newPubSubHealthChecker()
		// Override connect to simulate failure
		checker.connectFunc = func() (pubsubChecker, error) {
			return nil, assert.AnError
		}
		assert.Equal(t, "offline", checker.Check())
	})

	t.Run("retries and succeeds when service becomes available", func(t *testing.T) {
		os.Setenv("PUBSUB_PROJECT_ID", "test-project")
		os.Setenv("PUBSUB_TOPIC_ID", "test-topic")
		defer os.Unsetenv("PUBSUB_PROJECT_ID")
		defer os.Unsetenv("PUBSUB_TOPIC_ID")

		calls := 0
		checker := newPubSubHealthChecker()
		checker.connectFunc = func() (pubsubChecker, error) {
			calls++
			if calls == 1 {
				return nil, assert.AnError // First call fails
			}
			return &fakePubSubChecker{healthy: true}, nil // Second succeeds
		}

		// First check: connect fails → offline
		assert.Equal(t, "offline", checker.Check())
		// Second check: reconnect succeeds → online
		assert.Equal(t, "online", checker.Check())
	})

	t.Run("returns offline when connected service goes down", func(t *testing.T) {
		os.Setenv("PUBSUB_PROJECT_ID", "test-project")
		os.Setenv("PUBSUB_TOPIC_ID", "test-topic")
		defer os.Unsetenv("PUBSUB_PROJECT_ID")
		defer os.Unsetenv("PUBSUB_TOPIC_ID")

		fakeChecker := &fakePubSubChecker{healthy: true}
		checker := newPubSubHealthChecker()
		checker.connectFunc = func() (pubsubChecker, error) {
			return fakeChecker, nil
		}

		// First check: connected and healthy → online
		assert.Equal(t, "online", checker.Check())
		// Service goes down
		fakeChecker.healthy = false
		assert.Equal(t, "offline", checker.Check())
	})
}

// fakePubSubChecker implements the pubsubChecker interface for testing.
type fakePubSubChecker struct {
	healthy bool
}

func (f *fakePubSubChecker) CheckHealth(projectID, topicID string) error {
	if f.healthy {
		return nil
	}
	return assert.AnError
}

// --- AlloyDB Lazy Health Checker Tests ---

// mockPinger implements alloydbPinger for testing.
type mockPinger struct {
	err error
}

func (m *mockPinger) Ping(ctx context.Context) error {
	return m.err
}

func (m *mockPinger) Close(ctx context.Context) error {
	return nil
}

func TestAlloyDBHealthChecker_Online(t *testing.T) {
	checker := &alloydbHealthChecker{
		connectFunc: func(connStr string) (alloydbPinger, error) {
			return &mockPinger{}, nil
		},
	}
	status := checker.Check("postgresql://fake")
	if status != "online" {
		t.Errorf("expected online, got %s", status)
	}
}

func TestAlloyDBHealthChecker_Offline_ConnectFails(t *testing.T) {
	checker := &alloydbHealthChecker{
		connectFunc: func(connStr string) (alloydbPinger, error) {
			return nil, fmt.Errorf("connection refused")
		},
	}
	status := checker.Check("postgresql://fake")
	if status != "offline" {
		t.Errorf("expected offline, got %s", status)
	}
}

func TestAlloyDBHealthChecker_Offline_EmptyURL(t *testing.T) {
	checker := &alloydbHealthChecker{}
	status := checker.Check("")
	if status != "offline" {
		t.Errorf("expected offline, got %s", status)
	}
}

func TestAlloyDBHealthChecker_ReconnectsAfterFailure(t *testing.T) {
	callCount := 0
	checker := &alloydbHealthChecker{
		connectFunc: func(connStr string) (alloydbPinger, error) {
			callCount++
			if callCount == 1 {
				return &mockPinger{err: fmt.Errorf("ping failed")}, nil
			}
			return &mockPinger{}, nil
		},
	}
	s1 := checker.Check("postgresql://fake")
	if s1 != "offline" {
		t.Errorf("first check: expected offline, got %s", s1)
	}
	s2 := checker.Check("postgresql://fake")
	if s2 != "online" {
		t.Errorf("second check: expected online, got %s", s2)
	}
	if callCount != 2 {
		t.Errorf("expected 2 connect calls, got %d", callCount)
	}
}
func TestCheckServicesHealth(t *testing.T) {
	// Create a healthy test server
	healthySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}))
	defer healthySrv.Close()

	// Create an unhealthy test server
	unhealthySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer unhealthySrv.Close()

	services := []ServiceInfo{
		{ID: "svc-ok", URL: healthySrv.URL, HealthPath: "/health", Type: "go"},
		{ID: "svc-down", URL: unhealthySrv.URL, HealthPath: "/health", Type: "go"},
		{ID: "redis", URL: "n/a", HealthPath: "/", Type: "infra"},         // skipped
		{ID: "ext", URL: "http://ext", HealthPath: "/", Type: "external"}, // skipped
		{ID: "empty", URL: "", HealthPath: "/health", Type: "go"},         // skipped
	}

	results := checkServicesHealth(services, 2*time.Second, nil)

	assert.Equal(t, "online", results["svc-ok"])
	assert.Equal(t, "offline", results["svc-down"])
	assert.NotContains(t, results, "redis", "infra services should be skipped")
	assert.NotContains(t, results, "ext", "external services should be skipped")
	assert.NotContains(t, results, "empty", "empty URL services should be skipped")
}

func TestCheckServicesHealth_AEAgent(t *testing.T) {
	// AE agent mock -- responds to /a2a/v1/card
	aeSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/a2a/v1/card" {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"name":"simulator"}`))
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer aeSrv.Close()

	// Local agent mock -- responds to /health
	localSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	}))
	defer localSrv.Close()

	services := []ServiceInfo{
		{ID: "sim-ae", URL: aeSrv.URL, HealthPath: "/a2a/v1/card", Type: "ae"},
		{ID: "runner-local", URL: localSrv.URL, HealthPath: "/health", Type: "python"},
	}

	// Without gcpClient, AE agent uses plain client (still works against test server)
	results := checkServicesHealth(services, 2*time.Second, nil)
	assert.Equal(t, "online", results["sim-ae"])
	assert.Equal(t, "online", results["runner-local"])
}

func TestCheckServicesHealth_AEWithGCPClient(t *testing.T) {
	// AE mock that requires Authorization header
	aeSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/a2a/v1/card" && r.Header.Get("X-Test-Auth") != "" {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"name":"simulator"}`))
			return
		}
		w.WriteHeader(http.StatusUnauthorized)
	}))
	defer aeSrv.Close()

	// Create a "GCP client" with a custom transport that adds auth header
	gcpClient := &http.Client{
		Timeout: 2 * time.Second,
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			req.Header.Set("X-Test-Auth", "bearer-token")
			return http.DefaultTransport.RoundTrip(req)
		}),
	}

	services := []ServiceInfo{
		{ID: "sim-ae", URL: aeSrv.URL, HealthPath: "/a2a/v1/card", Type: "ae"},
	}

	// With gcpClient, AE agent gets authenticated request
	results := checkServicesHealth(services, 2*time.Second, gcpClient)
	assert.Equal(t, "online", results["sim-ae"])

	// Without gcpClient, AE agent gets 401
	resultsNoAuth := checkServicesHealth(services, 2*time.Second, nil)
	assert.Equal(t, "offline", resultsNoAuth["sim-ae"])
}

// roundTripFunc allows using a function as an http.RoundTripper for testing.
type roundTripFunc func(req *http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}

func TestHealthServicesEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	healthySrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer healthySrv.Close()

	registry := ServiceRegistryResponse{
		Categories: defaultCategories,
		Services: []ServiceInfo{
			{ID: "test-svc", URL: healthySrv.URL, HealthPath: "/health", Type: "go"},
		},
	}

	r := gin.New()
	r.GET("/api/v1/health/services", func(c *gin.Context) {
		health := checkServicesHealth(registry.Services, 2*time.Second, nil)
		c.JSON(http.StatusOK, health)
	})

	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/api/v1/health/services", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusOK, w.Code)

	var results map[string]string
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &results))
	assert.Equal(t, "online", results["test-svc"])
}
