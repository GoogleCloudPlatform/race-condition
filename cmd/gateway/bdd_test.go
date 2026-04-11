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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/cucumber/godog"
	"github.com/GoogleCloudPlatform/race-condition/internal/agent"
	"github.com/GoogleCloudPlatform/race-condition/internal/hub"
	"github.com/GoogleCloudPlatform/race-condition/internal/session"
	"github.com/redis/go-redis/v9"
)

// testContext holds shared state between step definitions.
type testContext struct {
	router             http.Handler
	resp               *httptest.ResponseRecorder
	respBody           map[string]interface{}
	reg                session.DistributedRegistry
	agentServer        *httptest.Server
	agentPoked         bool
	agentURLs          []string
	callableReceived   []byte          // Body received by callable mock
	callableDispatched bool            // Whether callable endpoint was hit
	switchboard        hub.Switchboard // Switchboard for dispatch-mode BDD tests
}

func (tc *testContext) theGatewayIsRunning() error {
	h := hub.NewHub()
	tc.reg = session.NewInMemorySessionService()

	var catalog *agent.Catalog
	if len(tc.agentURLs) > 0 {
		catalog = agent.NewCatalog(tc.agentURLs)
	}

	// The push handler delegates dispatch to the switchboard, so we must
	// always provide one. Reuse tc.switchboard if already wired (callable
	// tests), otherwise create a minimal one backed by miniredis.
	sb := tc.switchboard
	if sb == nil && catalog != nil {
		s, _ := miniredis.Run()
		client := redis.NewClient(&redis.Options{Addr: s.Addr()})
		sb = hub.NewSwitchboardWithRegistry(client, "test-gw", h, catalog, nil)
	}

	tc.router = setupRouter(h, sb, catalog, tc.reg, "test-gw", nil, nil)
	return nil
}

func (tc *testContext) iSendAGETRequestTo(path string) error {
	tc.resp = httptest.NewRecorder()
	req, _ := http.NewRequest("GET", path, nil)
	tc.router.ServeHTTP(tc.resp, req)

	// Parse JSON body
	tc.respBody = make(map[string]interface{})
	_ = json.Unmarshal(tc.resp.Body.Bytes(), &tc.respBody)
	return nil
}

func (tc *testContext) iSendAPOSTRequestTo(path string) error {
	tc.resp = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", path, nil)
	tc.router.ServeHTTP(tc.resp, req)

	tc.respBody = make(map[string]interface{})
	_ = json.Unmarshal(tc.resp.Body.Bytes(), &tc.respBody)
	return nil
}

func (tc *testContext) theResponseStatusShouldBe(code int) error {
	if tc.resp.Code != code {
		return fmt.Errorf("expected status %d, got %d", code, tc.resp.Code)
	}
	return nil
}

func (tc *testContext) theJSONResponseShouldHaveEqualTo(key, value string) error {
	got, ok := tc.respBody[key]
	if !ok {
		return fmt.Errorf("key %q not found in response", key)
	}
	if fmt.Sprintf("%v", got) != value {
		return fmt.Errorf("expected %q = %q, got %q", key, value, got)
	}
	return nil
}

func (tc *testContext) theJSONResponseAtShouldExist(key string) error {
	if _, ok := tc.respBody[key]; !ok {
		return fmt.Errorf("key %q not found in response", key)
	}
	return nil
}

func (tc *testContext) aSessionIsTracked(sessionID string) error {
	return tc.reg.TrackSession(context.Background(), sessionID, "test-agent", "")
}

func (tc *testContext) theJSONResponseShouldContain(value string) error {
	body := tc.resp.Body.String()
	if !bytes.Contains([]byte(body), []byte(value)) {
		return fmt.Errorf("response body does not contain %q", value)
	}
	return nil
}

func (tc *testContext) listingSessionsReturnsAnEmptyList() error {
	sessions, err := tc.reg.ListSessions(context.Background())
	if err != nil {
		return err
	}
	if len(sessions) != 0 {
		return fmt.Errorf("expected 0 sessions, got %d", len(sessions))
	}
	return nil
}

func (tc *testContext) agentIsRegisteredAtAMockEndpoint(agentType string) error {
	tc.agentPoked = false
	card := fmt.Sprintf(`{"name": "%s", "version": "1.0.0"}`, agentType)

	tc.agentServer = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/agent-card.json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(card))
		case r.Method == "POST" && r.URL.Path == "/orchestration":
			tc.agentPoked = true
			w.WriteHeader(http.StatusOK)
		default:
			http.NotFound(w, r)
		}
	}))

	tc.agentURLs = []string{tc.agentServer.URL}
	return tc.theGatewayIsRunning()
}

func (tc *testContext) aPushEventArrivesForAgentType(agentType string) error {
	innerData := fmt.Sprintf(`{"origin": {"id": "%s", "type": "agent"}, "session_id": "s1"}`, agentType)

	// If a switchboard is wired (callable dispatch tests), route through it.
	// This exercises the dispatch-mode routing in DispatchToAgent.
	if tc.switchboard != nil {
		var event map[string]interface{}
		_ = json.Unmarshal([]byte(innerData), &event)
		return tc.switchboard.DispatchToAgent(context.Background(), agentType, event)
	}

	// Otherwise, use the HTTP push endpoint (subscriber tests)
	pushPayload := map[string]interface{}{
		"message": map[string]interface{}{
			"data": []byte(innerData),
		},
	}
	body, _ := json.Marshal(pushPayload)

	tc.resp = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/orchestration/push", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	tc.router.ServeHTTP(tc.resp, req)
	return nil
}

func (tc *testContext) theMockAgentEndpointReceivesTheOrchestrationPayload() error {
	// Switchboard dispatches asynchronously via goroutines
	time.Sleep(1 * time.Second)
	if !tc.agentPoked {
		return fmt.Errorf("agent endpoint was not poked")
	}
	return nil
}

func (tc *testContext) agentIsRegisteredAsCallableAtAMockEndpoint(agentType string) error {
	tc.callableDispatched = false
	tc.callableReceived = nil
	cardData := fmt.Sprintf(`{"name": "%s", "version": "1.0.0", "capabilities": {"extensions": [{"uri": "n26:dispatch/1.0", "params": {"mode": "callable"}}]}}`, agentType)

	tc.agentServer = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/.well-known/agent-card.json":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(cardData))
		case r.Method == "POST":
			body, _ := io.ReadAll(r.Body)
			tc.callableReceived = body
			tc.callableDispatched = true
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"jsonrpc":"2.0","id":"1","result":{"kind":"task","id":"t1","context_id":"c1","status":{"state":"completed"}}}`))
		default:
			http.NotFound(w, r)
		}
	}))

	tc.agentURLs = []string{tc.agentServer.URL}

	// Wire a real switchboard with miniredis for callable dispatch
	s, _ := miniredis.Run()
	client := redis.NewClient(&redis.Options{Addr: s.Addr()})
	catalog := agent.NewCatalog(tc.agentURLs)
	h := hub.NewHub()
	tc.switchboard = hub.NewSwitchboardWithRegistry(client, "bdd-gw", h, catalog, nil)

	return tc.theGatewayIsRunning()
}

func (tc *testContext) theMockCallableEndpointReceivesAnOrchestrationPoke() error {
	// Give async dispatch time to complete
	time.Sleep(2 * time.Second)

	if !tc.callableDispatched {
		return fmt.Errorf("callable endpoint was not dispatched to")
	}

	// Local callable agents now receive /orchestration pokes (raw JSON events)
	// instead of A2A message/send. Verify it's NOT JSON-RPC wrapped.
	var event map[string]interface{}
	if err := json.Unmarshal(tc.callableReceived, &event); err != nil {
		return fmt.Errorf("callable received invalid JSON: %v", err)
	}

	if _, hasJsonRPC := event["jsonrpc"]; hasJsonRPC {
		return fmt.Errorf("local callable should receive orchestration poke, not JSON-RPC message/send")
	}
	if _, hasMethod := event["method"]; hasMethod {
		return fmt.Errorf("local callable should receive raw event, not JSON-RPC method call")
	}
	return nil
}

func (tc *testContext) theGatewayIsRunningWithTheSimulatorInTheCatalog() error {
	simCard := `{"name": "simulator", "url": "http://localhost:8202", "version": "1.0.0"}`
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/agent-card.json" {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(simCard))
		} else {
			http.NotFound(w, r)
		}
	}))
	// Note: server leaked in BDD context; acceptable for test scope
	tc.agentURLs = []string{srv.URL}
	return tc.theGatewayIsRunning()
}

func (tc *testContext) theGatewayIsRunningWithMultipleAgentsInTheCatalog() error {
	makeCardServer := func(name, url string) *httptest.Server {
		card := fmt.Sprintf(`{"name": "%s", "url": "%s", "version": "1.0.0"}`, name, url)
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/.well-known/agent-card.json" {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(card))
			} else {
				http.NotFound(w, r)
			}
		}))
	}
	simSrv := makeCardServer("simulator", "http://localhost:8202")
	planSrv := makeCardServer("planner", "http://localhost:8204")
	tc.agentURLs = []string{simSrv.URL, planSrv.URL}
	return tc.theGatewayIsRunning()
}

func (tc *testContext) iSpawnNAgents(count int, agentType string) error {
	body, _ := json.Marshal(map[string]interface{}{
		"agents": []map[string]interface{}{
			{"agentType": agentType, "count": count},
		},
	})
	tc.resp = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	tc.router.ServeHTTP(tc.resp, req)

	tc.respBody = make(map[string]interface{})
	_ = json.Unmarshal(tc.resp.Body.Bytes(), &tc.respBody)
	return nil
}

func (tc *testContext) iBatchSpawnAgents(table *godog.Table) error {
	var agents []map[string]interface{}
	for i, row := range table.Rows {
		if i == 0 { // skip header
			continue
		}
		count := 1
		if _, err := fmt.Sscanf(row.Cells[1].Value, "%d", &count); err != nil {
			count = 1
		}
		agents = append(agents, map[string]interface{}{
			"agentType": row.Cells[0].Value,
			"count":     count,
		})
	}

	body, _ := json.Marshal(map[string]interface{}{"agents": agents})
	tc.resp = httptest.NewRecorder()
	req, _ := http.NewRequest("POST", "/api/v1/spawn", bytes.NewBuffer(body))
	req.Header.Set("Content-Type", "application/json")
	tc.router.ServeHTTP(tc.resp, req)

	tc.respBody = make(map[string]interface{})
	_ = json.Unmarshal(tc.resp.Body.Bytes(), &tc.respBody)
	return nil
}

func (tc *testContext) theSpawnResponseShouldContainNSessions(expected int) error {
	sessions, ok := tc.respBody["sessions"].([]interface{})
	if !ok {
		return fmt.Errorf("response does not contain 'sessions' array, got: %v", tc.respBody)
	}
	if len(sessions) != expected {
		return fmt.Errorf("expected %d sessions, got %d", expected, len(sessions))
	}
	return nil
}

func (tc *testContext) eachSpawnedSessionShouldHaveAValidUUIDAndAgentType(expectedType string) error {
	sessions, ok := tc.respBody["sessions"].([]interface{})
	if !ok {
		return fmt.Errorf("response does not contain 'sessions' array")
	}
	for i, s := range sessions {
		session, ok := s.(map[string]interface{})
		if !ok {
			return fmt.Errorf("session %d is not a map", i)
		}
		sid, ok := session["sessionId"].(string)
		if !ok || len(sid) < 8 {
			return fmt.Errorf("session %d missing valid sessionId: %v", i, session["sessionId"])
		}
		at, ok := session["agentType"].(string)
		if !ok || at != expectedType {
			return fmt.Errorf("session %d: expected agentType %q, got %q", i, expectedType, at)
		}
	}
	return nil
}

func InitializeScenario(ctx *godog.ScenarioContext) {
	tc := &testContext{}

	ctx.Step(`^the gateway is running$`, tc.theGatewayIsRunning)
	ctx.Step(`^I send a GET request to "([^"]*)"$`, tc.iSendAGETRequestTo)
	ctx.Step(`^I send a POST request to "([^"]*)"$`, tc.iSendAPOSTRequestTo)
	ctx.Step(`^the response status should be (\d+)$`, tc.theResponseStatusShouldBe)
	ctx.Step(`^the JSON response should have "([^"]*)" equal to "([^"]*)"$`, tc.theJSONResponseShouldHaveEqualTo)
	ctx.Step(`^the JSON response at "([^"]*)" should exist$`, tc.theJSONResponseAtShouldExist)
	ctx.Step(`^a session "([^"]*)" is tracked$`, tc.aSessionIsTracked)
	ctx.Step(`^the JSON response should contain "([^"]*)"$`, tc.theJSONResponseShouldContain)
	ctx.Step(`^listing sessions returns an empty list$`, tc.listingSessionsReturnsAnEmptyList)
	ctx.Step(`^agent "([^"]*)" is registered at a mock endpoint$`, tc.agentIsRegisteredAtAMockEndpoint)
	ctx.Step(`^a push event arrives for agent type "([^"]*)"$`, tc.aPushEventArrivesForAgentType)
	ctx.Step(`^the mock agent endpoint receives the orchestration payload$`, tc.theMockAgentEndpointReceivesTheOrchestrationPayload)
	ctx.Step(`^agent "([^"]*)" is registered as a callable agent at a mock endpoint$`, tc.agentIsRegisteredAsCallableAtAMockEndpoint)
	ctx.Step(`^the mock callable endpoint receives an orchestration poke$`, tc.theMockCallableEndpointReceivesAnOrchestrationPoke)
	ctx.Step(`^the gateway is running with the simulator in the catalog$`, tc.theGatewayIsRunningWithTheSimulatorInTheCatalog)
	ctx.Step(`^the gateway is running with multiple agents in the catalog$`, tc.theGatewayIsRunningWithMultipleAgentsInTheCatalog)
	ctx.Step(`^I spawn (\d+) "([^"]*)" agents?$`, tc.iSpawnNAgents)
	ctx.Step(`^I batch spawn agents:$`, tc.iBatchSpawnAgents)
	ctx.Step(`^the spawn response should contain (\d+) sessions?$`, tc.theSpawnResponseShouldContainNSessions)
	ctx.Step(`^each spawned session should have a valid UUID and agent type "([^"]*)"$`, tc.eachSpawnedSessionShouldHaveAValidUUIDAndAgentType)
}

func TestBDD(t *testing.T) {
	suite := godog.TestSuite{
		ScenarioInitializer: InitializeScenario,
		Options: &godog.Options{
			Format:   "pretty",
			Paths:    []string{"features"},
			TestingT: t,
		},
	}

	if suite.Run() != 0 {
		t.Fatal("BDD tests failed")
	}
}
