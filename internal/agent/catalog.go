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
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"golang.org/x/oauth2/google"
)

// AgentCard is a transparent wrapper around the A2A agent card JSON.
// The raw JSON is preserved so the gateway can proxy all fields losslessly.
// Only the fields the gateway needs are extracted into typed accessors.
type AgentCard struct {
	// Raw stores the complete, unmodified JSON from the agent.
	// MarshalJSON returns this directly, so /api/v1/agent-types
	// serves exactly what the agents provide.
	Raw json.RawMessage `json:"-"`

	// Extracted fields — used internally by the gateway.
	Name         string                 `json:"-"`
	URL          string                 `json:"-"`
	BaseURL      string                 `json:"-"` // Discovery base URL for orchestration pokes
	Version      string                 `json:"-"`
	Description  string                 `json:"-"`
	Capabilities map[string]interface{} `json:"-"`
}

// MarshalJSON returns the raw JSON unchanged, making the gateway a transparent proxy.
func (c AgentCard) MarshalJSON() ([]byte, error) {
	if c.Raw != nil {
		return []byte(c.Raw), nil
	}
	// Fallback for programmatically constructed cards (tests)
	return json.Marshal(struct {
		Name         string                 `json:"name"`
		Description  string                 `json:"description,omitempty"`
		Version      string                 `json:"version,omitempty"`
		URL          string                 `json:"url,omitempty"`
		Capabilities map[string]interface{} `json:"capabilities,omitempty"`
	}{
		Name:         c.Name,
		Description:  c.Description,
		Version:      c.Version,
		URL:          c.URL,
		Capabilities: c.Capabilities,
	})
}

// UnmarshalJSON stores the raw bytes and extracts only the fields the gateway needs.
func (c *AgentCard) UnmarshalJSON(data []byte) error {
	c.Raw = append(json.RawMessage{}, data...) // copy

	var extracted struct {
		Name         string                 `json:"name"`
		Description  string                 `json:"description"`
		Version      string                 `json:"version"`
		URL          string                 `json:"url"`
		Capabilities map[string]interface{} `json:"capabilities"`
	}
	if err := json.Unmarshal(data, &extracted); err != nil {
		return err
	}
	c.Name = extracted.Name
	c.Description = extracted.Description
	c.Version = extracted.Version
	c.URL = extracted.URL
	c.Capabilities = extracted.Capabilities
	return nil
}

// SetURL updates the URL in both the extracted field and the raw JSON.
func (c *AgentCard) SetURL(url string) {
	c.URL = url
	// Update the raw JSON too so it's consistent when proxied
	var m map[string]interface{}
	if err := json.Unmarshal(c.Raw, &m); err == nil {
		m["url"] = url
		if updated, err := json.Marshal(m); err == nil {
			c.Raw = updated
		}
	}
}

// OrchestrationBaseURL returns the base URL for orchestration pokes.
// Falls back to URL if BaseURL is not set.
func (c AgentCard) OrchestrationBaseURL() string {
	if c.BaseURL != "" {
		return c.BaseURL
	}
	return c.URL
}

// DispatchMode returns the dispatch mode from the n26:dispatch/1.0 extension.
// Returns "subscriber" if not specified.
func (c AgentCard) DispatchMode() string {
	exts, ok := c.Capabilities["extensions"].([]interface{})
	if !ok {
		return "subscriber"
	}
	for _, ext := range exts {
		m, ok := ext.(map[string]interface{})
		if !ok {
			continue
		}
		if m["uri"] == "n26:dispatch/1.0" {
			params, ok := m["params"].(map[string]interface{})
			if ok {
				if mode, ok := params["mode"].(string); ok {
					return mode
				}
			}
		}
	}
	return "subscriber"
}

// defaultCacheTTL is the default duration for which discovered agents are cached.
// 30 seconds balances freshness against the cost of fetching all agent cards.
const defaultCacheTTL = 30 * time.Second

// Catalog discovers agents by fetching their A2A AgentCards over HTTP.
// Results are cached for cacheTTL to avoid redundant network round-trips.
type Catalog struct {
	agentURLs []string
	client    *http.Client
	gcpClient *http.Client // Authenticated client for Agent Engine URLs

	// Cache fields — protected by cacheMu
	cacheMu      sync.RWMutex
	cachedAgents map[string]AgentCard
	cacheExpiry  time.Time
	cacheTTL     time.Duration
}

// newRetryableClient wraps an HTTP client with retry logic
// (5 retries, exponential backoff 500ms–5s). If httpClient is nil,
// a default client is used. This ensures both standard and AE agents
// get identical retry behavior.
func newRetryableClient(httpClient *http.Client) *http.Client {
	rc := retryablehttp.NewClient()
	if httpClient != nil {
		rc.HTTPClient = httpClient
	}
	rc.RetryMax = 5
	rc.RetryWaitMin = 500 * time.Millisecond
	rc.RetryWaitMax = 5 * time.Second
	rc.Logger = nil // Suppress default retry logs
	return rc.StandardClient()
}

// NewCatalogWithTTL creates a catalog with a custom cache TTL.
// Use this in tests to control cache behavior.
func NewCatalogWithTTL(agentURLs []string, ttl time.Duration) *Catalog {
	c := NewCatalog(agentURLs)
	c.cacheTTL = ttl
	return c
}

// NewCatalog creates a catalog that discovers agents from the given base URLs.
// Each URL should be the agent's base URL (e.g., http://localhost:8201).
// For standard A2A agents, appends /.well-known/agent-card.json.
// For Agent Engine agents, appends /a2a/v1/card and uses GCP auth.
func NewCatalog(agentURLs []string) *Catalog {
	// Create GCP-authenticated client for Agent Engine calls.
	gcpClient, err := google.DefaultClient(context.Background(),
		"https://www.googleapis.com/auth/cloud-platform",
	)
	if err != nil {
		log.Printf("Catalog: WARNING — failed to create GCP auth client: %v (AE card discovery will fail)", err)
	}

	var gcpRetryClient *http.Client
	if gcpClient != nil {
		gcpClient.Timeout = 10 * time.Second
		// Wrap the GCP client in retryablehttp for AE resilience.
		// The OAuth2 transport is preserved — retries happen around
		// HTTPClient.Do(), so each attempt includes fresh auth headers.
		gcpRetryClient = newRetryableClient(gcpClient)
	}

	return &Catalog{
		agentURLs: agentURLs,
		client:    newRetryableClient(nil),
		gcpClient: gcpRetryClient,
		cacheTTL:  defaultCacheTTL,
	}
}

// wellKnownPath is the A2A standard path for agent card discovery.
const wellKnownPath = "/.well-known/agent-card.json"

// aeCardPath is the Agent Engine card endpoint (AE doesn't serve well-known).
const aeCardPath = "/a2a/v1/card"

// isAgentEngineURL returns true if the URL points to a Vertex AI Agent Engine
// resource (contains aiplatform.googleapis.com and reasoningEngines).
func isAgentEngineURL(u string) bool {
	return strings.Contains(u, "aiplatform.googleapis.com") &&
		strings.Contains(u, "reasoningEngines")
}

// discoverResult holds the outcome of a single agent card fetch.
type discoverResult struct {
	card    AgentCard
	baseURL string
	err     error
}

// DiscoverAgents fetches AgentCards from each configured agent URL concurrently.
// Results are cached for cacheTTL. Unreachable agents are logged and skipped
// (not fatal unless none are found).
func (c *Catalog) DiscoverAgents() (map[string]AgentCard, error) {
	if len(c.agentURLs) == 0 {
		return nil, fmt.Errorf("no agent URLs configured (check AGENT_URLS env var)")
	}

	// Fast path: return cached results if still valid (read lock).
	c.cacheMu.RLock()
	if c.cachedAgents != nil && time.Now().Before(c.cacheExpiry) {
		agents := c.cachedAgents
		c.cacheMu.RUnlock()
		return agents, nil
	}
	c.cacheMu.RUnlock()

	// Slow path: acquire write lock and double-check.
	// This prevents thundering-herd: only one goroutine fetches,
	// others block on Lock() and get the cached result on double-check.
	c.cacheMu.Lock()
	defer c.cacheMu.Unlock()

	// Double-check: another goroutine may have refreshed while we waited.
	if c.cachedAgents != nil && time.Now().Before(c.cacheExpiry) {
		return c.cachedAgents, nil
	}

	return c.fetchAndCacheLocked()
}

// fetchAndCacheLocked performs the actual HTTP discovery and updates the cache.
// Caller MUST hold c.cacheMu (write lock).
func (c *Catalog) fetchAndCacheLocked() (map[string]AgentCard, error) {
	results := make(chan discoverResult, len(c.agentURLs))
	var wg sync.WaitGroup

	for _, rawURL := range c.agentURLs {
		wg.Add(1)
		go func(baseURL string) {
			defer wg.Done()
			baseURL = strings.TrimRight(baseURL, "/")

			// Agent Engine uses /a2a/v1/card; standard A2A uses /.well-known/agent-card.json.
			cardPath := wellKnownPath
			isAE := isAgentEngineURL(baseURL)
			if isAE {
				cardPath = aeCardPath
			}
			cardURL := baseURL + cardPath

			// Use GCP-authenticated client for Agent Engine URLs.
			httpClient := c.client
			if isAE && c.gcpClient != nil {
				httpClient = c.gcpClient
			}

			card, err := c.fetchCard(cardURL, httpClient)
			if err != nil {
				results <- discoverResult{baseURL: baseURL, err: err}
				return
			}

			// Store the discovery base URL for orchestration routing.
			// The gateway's AGENT_URLS contains the internal/private URLs
			// for service-to-service communication.
			card.BaseURL = baseURL

			if isAE {
				// AE agents: always use the discovery base URL as-is.
				// The switchboard appends /a2a/v1/message:send for dispatches.
				card.SetURL(baseURL)
			} else if card.URL != "" {
				// Local/Cloud Run: preserve the card's A2A path (e.g.,
				// /a2a/simulator/) but replace the host with the internal
				// discovery URL. Cards may self-report public/IAP URLs
				// unreachable server-to-server.
				if origURL, err := url.Parse(card.URL); err == nil && origURL.Path != "" && origURL.Path != "/" {
					card.SetURL(strings.TrimRight(baseURL, "/") + origURL.Path)
				} else {
					card.SetURL(baseURL)
				}
			} else {
				card.SetURL(baseURL)
			}

			results <- discoverResult{card: card, baseURL: baseURL}
		}(rawURL)
	}

	// Close results channel after all goroutines complete.
	go func() {
		wg.Wait()
		close(results)
	}()

	agents := make(map[string]AgentCard)
	var lastErr error

	for r := range results {
		if r.err != nil {
			log.Printf("Catalog: skipping agent at %s — DISCOVERY_FAILURE: %v", r.baseURL, r.err)
			lastErr = r.err
			continue
		}
		if r.card.Name == "" {
			log.Printf("Catalog: skipping agent at %s — DISCOVERY_FAILURE: card has no name", r.baseURL)
			continue
		}
		// Concurrent discovery means duplicate names resolve nondeterministically
		// (unlike the sequential version which was last-wins-in-URL-order).
		// Log a warning so operators notice the config error.
		if existing, ok := agents[r.card.Name]; ok {
			log.Printf("Catalog: WARNING — duplicate agent name %q from %s (previously from %s)",
				r.card.Name, r.baseURL, existing.URL)
		}
		agents[r.card.Name] = r.card
		log.Printf("Catalog: Discovered agent %q from %s (dispatch=%s)",
			r.card.Name, r.baseURL, r.card.DispatchMode())
	}

	if len(agents) == 0 {
		if lastErr != nil {
			return nil, fmt.Errorf("failed to discover any agents: %w", lastErr)
		}
		return nil, fmt.Errorf("failed to discover any agents (all URLs reachable but returned no cards)")
	}

	// Cache the results. Caller holds c.cacheMu write lock.
	c.cachedAgents = agents
	c.cacheExpiry = time.Now().Add(c.cacheTTL)

	return agents, nil
}

// fetchCard fetches and parses an AgentCard from the given URL using the provided HTTP client.
func (c *Catalog) fetchCard(url string, httpClient *http.Client) (AgentCard, error) {
	resp, err := httpClient.Get(url)
	if err != nil {
		return AgentCard{}, fmt.Errorf("fetch failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		// Read up to 512 bytes of the response body for error diagnostics.
		// This helps operators debug AE set_up() failures, auth issues, etc.
		errBody, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		if len(errBody) > 0 {
			return AgentCard{}, fmt.Errorf("unexpected status %d: %s", resp.StatusCode, string(errBody))
		}
		return AgentCard{}, fmt.Errorf("unexpected status %d", resp.StatusCode)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return AgentCard{}, fmt.Errorf("read body failed: %w", err)
	}

	var card AgentCard
	if err := json.Unmarshal(body, &card); err != nil {
		return AgentCard{}, fmt.Errorf("invalid JSON: %w", err)
	}

	return card, nil
}
