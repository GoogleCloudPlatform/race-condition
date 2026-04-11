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
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"golang.org/x/sync/errgroup"

	pubsub "cloud.google.com/go/pubsub/v2/apiv1"
	"cloud.google.com/go/pubsub/v2/apiv1/pubsubpb"
	"github.com/GoogleCloudPlatform/race-condition/internal/config"
	"github.com/GoogleCloudPlatform/race-condition/internal/middleware"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5"
	"github.com/redis/go-redis/v9"
	"golang.org/x/oauth2/google"
	"google.golang.org/api/option"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// CategoryInfo defines a service grouping in the dashboard.
type CategoryInfo struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	Icon string `json:"icon"`
}

// ServiceInfo describes a service displayed on the admin dashboard.
type ServiceInfo struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	Category    string `json:"category"`
	Description string `json:"description"`
	URL         string `json:"url"`
	HealthPath  string `json:"healthPath"`
	Browseable  bool   `json:"browseable"`
	Type        string `json:"type"`
}

// ServiceRegistryResponse is the JSON payload for /api/v1/services.
type ServiceRegistryResponse struct {
	Categories []CategoryInfo `json:"categories"`
	Services   []ServiceInfo  `json:"services"`
}

// pubsubChecker abstracts PubSub health checking for testability.
type pubsubChecker interface {
	CheckHealth(projectID, topicID string) error
}

// grpcPubSubChecker wraps the real gRPC PubSub admin client.
type grpcPubSubChecker struct {
	client *pubsub.TopicAdminClient
}

func (g *grpcPubSubChecker) CheckHealth(projectID, topicID string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_, err := g.client.GetTopic(ctx, &pubsubpb.GetTopicRequest{
		Topic: fmt.Sprintf("projects/%s/topics/%s", projectID, topicID),
	})
	return err
}

// pubsubHealthChecker lazily connects to PubSub and retries on failure.
type pubsubHealthChecker struct {
	mu          sync.Mutex
	checker     pubsubChecker
	connectFunc func() (pubsubChecker, error)
}

func newPubSubHealthChecker() *pubsubHealthChecker {
	return &pubsubHealthChecker{
		connectFunc: defaultPubSubConnect,
	}
}

func defaultPubSubConnect() (pubsubChecker, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// The low-level apiv1 client does NOT respect PUBSUB_EMULATOR_HOST.
	// We must manually configure the endpoint and insecure transport.
	var opts []option.ClientOption
	emulatorHost := config.Optional("PUBSUB_EMULATOR_HOST", "")
	if emulatorHost != "" {
		opts = append(opts,
			option.WithEndpoint(emulatorHost),
			option.WithoutAuthentication(),
			option.WithGRPCDialOption(grpc.WithTransportCredentials(insecure.NewCredentials())),
		)
	}

	client, err := pubsub.NewTopicAdminClient(ctx, opts...)
	if err != nil {
		return nil, err
	}
	// Proactively create topic in emulator mode
	projectID := config.Optional("PUBSUB_PROJECT_ID", config.Optional("PROJECT_ID", ""))
	topicID := config.Optional("PUBSUB_TOPIC_ID", "")
	if emulatorHost != "" && topicID != "" {
		topicName := fmt.Sprintf("projects/%s/topics/%s", projectID, topicID)
		_, getErr := client.GetTopic(context.Background(), &pubsubpb.GetTopicRequest{Topic: topicName})
		if getErr != nil {
			log.Printf("Creating PubSub topic %s in emulator", topicID)
			if _, createErr := client.CreateTopic(context.Background(), &pubsubpb.Topic{Name: topicName}); createErr != nil {
				log.Printf("Warning: Failed to create topic %s: %v", topicID, createErr)
			}
		}
	}
	return &grpcPubSubChecker{client: client}, nil
}

// Check returns "online" or "offline" based on PubSub health.
// If the client is nil, it attempts to reconnect (lazy initialization).
func (p *pubsubHealthChecker) Check() string {
	projectID := config.Optional("PUBSUB_PROJECT_ID", config.Optional("PROJECT_ID", ""))
	topicID := config.Optional("PUBSUB_TOPIC_ID", "")
	if projectID == "" || topicID == "" {
		return "offline"
	}

	p.mu.Lock()
	defer p.mu.Unlock()

	// Lazy connect / reconnect
	if p.checker == nil {
		checker, err := p.connectFunc()
		if err != nil {
			log.Printf("PubSub connect failed (will retry next check): %v", err)
			return "offline"
		}
		p.checker = checker
	}

	// Health check
	if err := p.checker.CheckHealth(projectID, topicID); err != nil {
		// Connection may be stale; clear it so next check retries
		p.checker = nil
		return "offline"
	}
	return "online"
}

// alloydbPinger abstracts the database ping for testability.
type alloydbPinger interface {
	Ping(ctx context.Context) error
	Close(ctx context.Context) error
}

// alloydbHealthChecker lazily connects to AlloyDB and retries on failure.
// Follows the same pattern as pubsubHealthChecker.
type alloydbHealthChecker struct {
	mu          sync.Mutex
	conn        alloydbPinger
	connectFunc func(connStr string) (alloydbPinger, error)
}

func newAlloyDBHealthChecker() *alloydbHealthChecker {
	return &alloydbHealthChecker{
		connectFunc: defaultAlloyDBConnect,
	}
}

func defaultAlloyDBConnect(connStr string) (alloydbPinger, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	conn, err := pgx.Connect(ctx, connStr)
	if err != nil {
		return nil, err
	}
	return conn, nil
}

// Check returns "online" or "offline" based on AlloyDB health.
func (a *alloydbHealthChecker) Check(connStr string) string {
	if connStr == "" {
		return "offline"
	}

	a.mu.Lock()
	defer a.mu.Unlock()

	// Lazy connect / reconnect
	if a.conn == nil {
		conn, err := a.connectFunc(connStr)
		if err != nil {
			log.Printf("AlloyDB connect failed (will retry next check): %v", err)
			return "offline"
		}
		a.conn = conn
	}

	// Ping check
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	if err := a.conn.Ping(ctx); err != nil {
		a.conn.Close(context.Background())
		a.conn = nil
		return "offline"
	}
	return "online"
}

// newGCPClient returns an HTTP client with GCP Application Default Credentials.
// Uses OAuth2 access tokens (not ID tokens) with cloud-platform scope,
// matching the pattern in switchboard.go and catalog.go for AE communication.
// Returns nil if ADC is not available (e.g., local dev without gcloud auth).
func newGCPClient() *http.Client {
	client, err := google.DefaultClient(context.Background(),
		"https://www.googleapis.com/auth/cloud-platform",
	)
	if err != nil {
		log.Printf("GCP client unavailable (AE health checks disabled): %v", err)
		return nil
	}
	client.Timeout = 10 * time.Second
	return client
}

var defaultCategories = []CategoryInfo{
	{ID: "admin", Name: "Admin & System", Icon: "⚙️"},
	{ID: "core", Name: "Core Infrastructure", Icon: "🏗️"},
	{ID: "agent", Name: "AI Agents", Icon: "🤖"},
	{ID: "ui", Name: "Developer UIs", Icon: "🖥️"},
	{ID: "frontend", Name: "Frontend", Icon: "🌐"},
}

// isAgentEngineURL returns true if the URL points to a Vertex AI Agent Engine
// resource (contains aiplatform.googleapis.com and reasoningEngines).
func isAgentEngineURL(u string) bool {
	return strings.Contains(u, "aiplatform.googleapis.com") &&
		strings.Contains(u, "reasoningEngines")
}

// aeCardPath is the Agent Engine card endpoint used for health checks.
const aeCardPath = "/a2a/v1/card"

// defaultPortMap provides fallback ports for agents when env vars are not set.
var defaultPortMap = map[string]string{
	"planner":                "8204",
	"simulator":              "8202",
	"runner_autopilot":       "8210",
	"planner_with_eval":      "8205",
	"simulator_with_failure": "8206",
	"planner_with_memory":    "8209",
}

// staticServices returns the hardcoded non-agent services.
func staticServices() []ServiceInfo {
	return []ServiceInfo{
		{ID: "admin", Name: "Admin Dash", Category: "admin", Description: "Centralized health monitoring and service portal.", URL: resolveURL("ADMIN", "8000"), HealthPath: "/health", Browseable: true, Type: "go"},
		{ID: "gateway", Name: "Gateway", Category: "core", Description: "Primary API entry point and session router.", URL: resolveURL("GATEWAY", "8101"), HealthPath: "/health", Browseable: true, Type: "go"},
		{ID: "redis", Name: "Redis", Category: "core", Description: "Session state & orchestration store.", URL: "n/a", HealthPath: "/", Browseable: false, Type: "infra"},
		{ID: "pubsub", Name: "PubSub", Category: "core", Description: "Global telemetry bus emulator.", URL: "n/a", HealthPath: "/", Browseable: false, Type: "infra"},
		{ID: "alloydb", Name: "AlloyDB", Category: "core", Description: "Durable session state store (PostgreSQL-compatible).", URL: "n/a", HealthPath: "/", Browseable: false, Type: "infra"},
		{ID: "tester", Name: "Tester UI", Category: "ui", Description: "Manual A2UI component testing laboratory.", URL: resolveURL("TESTER", "8304"), HealthPath: "/health", Browseable: true, Type: "vite"},
		{ID: "dash", Name: "Telemetry Dash", Category: "ui", Description: "Pub/Sub telemetry log and agent activity stream.", URL: resolveURL("DASH", "8301"), HealthPath: "/health", Browseable: true, Type: "python"},
		{ID: "frontend-app", Name: "Primary Frontend", Category: "frontend", Description: "Main consumer-facing simulation interface.", URL: resolveURL("FRONTEND_APP", "8501"), HealthPath: "/health", Browseable: false, Type: "external"},
		{ID: "frontend-bff", Name: "Frontend BFF", Category: "frontend", Description: "Local BFF proxy mirroring cloud frontend service.", URL: resolveURL("FRONTEND_BFF", "8502"), HealthPath: "/health", Browseable: true, Type: "go"},
	}
}

// checkServicesHealth checks health endpoints for all services concurrently,
// using Cloud Run's internal networking (VPC) to bypass IAP.
// For AE agents (type "ae"), uses gcpClient with authenticated requests.
func checkServicesHealth(services []ServiceInfo, timeout time.Duration, gcpClient *http.Client) map[string]string {
	results := make(map[string]string)
	var mu sync.Mutex

	// Filter to only services with checkable health endpoints
	var checkable []ServiceInfo
	for _, svc := range services {
		if svc.Type == "external" || svc.Type == "infra" {
			continue
		}
		if svc.URL == "" || svc.URL == "n/a" {
			continue
		}
		checkable = append(checkable, svc)
	}

	g := new(errgroup.Group)
	g.SetLimit(10) // max concurrent health checks

	plainClient := &http.Client{Timeout: timeout}

	for _, svc := range checkable {
		svc := svc // capture
		g.Go(func() error {
			url := svc.URL + svc.HealthPath

			// Use GCP-authenticated client for AE agents
			c := plainClient
			if svc.Type == "ae" && gcpClient != nil {
				c = gcpClient
			}

			resp, err := c.Get(url)
			status := "offline"
			if err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					status = "online"
				}
			}

			mu.Lock()
			results[svc.ID] = status
			mu.Unlock()
			return nil // never fail the group
		})
	}

	_ = g.Wait()
	return results
}

// resolveURL builds a service URL from env vars with a port fallback.
func resolveURL(prefix, defaultPort string) string {
	envKey := prefix + "_URL"
	if v := config.Optional(envKey, ""); v != "" {
		return v
	}
	return "http://127.0.0.1:" + defaultPort
}

// loadAgentsFromGateway fetches the agent catalog from the gateway's HTTP API.
// This replaces the old loadAgentsFromCatalog that read from a static JSON file.
func loadAgentsFromGateway(gatewayURL string) []ServiceInfo {
	if gatewayURL == "" {
		log.Printf("Warning: GATEWAY_URL not set, cannot discover agents")
		return nil
	}

	url := strings.TrimRight(gatewayURL, "/") + "/api/v1/agent-types"
	resp, err := http.Get(url)
	if err != nil {
		log.Printf("Warning: Could not fetch agent catalog from %s: %v", url, err)
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Printf("Warning: Gateway returned %d for agent catalog", resp.StatusCode)
		return nil
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Printf("Warning: Could not read gateway response: %v", err)
		return nil
	}

	// Gateway returns map[string]AgentCard where the key is the agent name.
	// We only need name and description for the admin dashboard.
	var catalog map[string]json.RawMessage
	if err := json.Unmarshal(body, &catalog); err != nil {
		log.Printf("Warning: Could not parse agent catalog from gateway: %v", err)
		return nil
	}

	var agents []ServiceInfo
	for id := range catalog {
		// Extract just the fields we need
		var entry struct {
			Name        string `json:"name"`
			Description string `json:"description"`
			URL         string `json:"url"`
		}
		if err := json.Unmarshal(catalog[id], &entry); err != nil {
			log.Printf("Warning: Could not parse agent %s: %v", id, err)
			continue
		}

		name := entry.Name
		if name == "" {
			name = id
		}
		// Title-case the name for display
		if len(name) > 0 {
			name = strings.ToUpper(name[:1]) + name[1:]
		}

		prefix := strings.ToUpper(id)
		defaultPort := defaultPortMap[id]
		if defaultPort == "" {
			defaultPort = "0"
		}

		// Detect Agent Engine agents from their card URL.
		agentType := "python"
		healthPath := "/health"
		agentURL := resolveURL(prefix, defaultPort)

		if isAgentEngineURL(entry.URL) {
			agentType = "ae"
			healthPath = aeCardPath
			agentURL = strings.TrimRight(entry.URL, "/")
		}

		agents = append(agents, ServiceInfo{
			ID:          id,
			Name:        name,
			Category:    "agent",
			Description: entry.Description,
			URL:         agentURL,
			HealthPath:  healthPath,
			Browseable:  false,
			Type:        agentType,
		})
	}
	log.Printf("Discovered %d agents from gateway", len(agents))
	return agents
}

// buildServiceRegistry merges static services with dynamically loaded agents.
func buildServiceRegistry(gatewayURL string) ServiceRegistryResponse {
	services := staticServices()
	agents := loadAgentsFromGateway(gatewayURL)
	services = append(services, agents...)
	return ServiceRegistryResponse{
		Categories: defaultCategories,
		Services:   services,
	}
}

// setupRouter creates the admin Gin engine with all routes.
func setupRouter(rdb *redis.Client, psHealthChecker *pubsubHealthChecker, dbHealthChecker *alloydbHealthChecker, registry ServiceRegistryResponse, gcpClient *http.Client) *gin.Engine {
	r := gin.Default()

	r.Use(middleware.CORS(os.Getenv("CORS_ALLOWED_ORIGINS")))

	// API Routes (no prefix)
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "admin"})
	})

	r.GET("/api/v1/services", func(c *gin.Context) {
		c.JSON(http.StatusOK, registry)
	})

	r.GET("/api/v1/health/infra", func(c *gin.Context) {
		redisStatus := "offline"
		if rdb != nil {
			ctx, cancel := context.WithTimeout(c.Request.Context(), 1*time.Second)
			defer cancel()
			if err := rdb.Ping(ctx).Err(); err == nil {
				redisStatus = "online"
			}
		}

		pubsubStatus := psHealthChecker.Check()
		alloydbStatus := dbHealthChecker.Check(config.Optional("DATABASE_URL", ""))

		c.JSON(http.StatusOK, gin.H{
			"redis":   redisStatus,
			"pubsub":  pubsubStatus,
			"alloydb": alloydbStatus,
		})
	})

	r.GET("/api/v1/health/services", func(c *gin.Context) {
		health := checkServicesHealth(registry.Services, 3*time.Second, gcpClient)
		c.JSON(http.StatusOK, health)
	})

	r.GET("/config.js", middleware.ConfigJSHandler(map[string]string{
		"GATEWAY_URL":      config.Optional("GATEWAY_URL", ""),
		"SIMULATOR_URL":    config.Optional("SIMULATOR_URL", ""),
		"PLANNER_URL":      config.Optional("PLANNER_URL", ""),
		"TESTER_URL":       config.Optional("TESTER_URL", ""),
		"ADMIN_URL":        config.Optional("ADMIN_URL", ""),
		"DASH_URL":         config.Optional("DASH_URL", ""),
		"FRONTEND_APP_URL": config.Optional("FRONTEND_APP_URL", ""),
		"FRONTEND_BFF_URL": config.Optional("FRONTEND_BFF_URL", ""),
		"REDIS_URL":        "n/a",
		"PUBSUB_URL":       "n/a",
		"ALLOYDB_URL":      "n/a",
	}))

	// Static files sharing from dist root
	r.StaticFS("/assets", http.Dir("./web/admin-dash/dist/assets"))
	r.StaticFile("/favicon.ico", "./web/admin-dash/dist/favicon.ico")

	// Serve index.html for root and any unknown routes (SPA support)
	r.NoRoute(func(c *gin.Context) {
		if c.Request.Method != "GET" {
			c.Status(http.StatusNotFound)
			return
		}

		path := c.Request.URL.Path
		// If it looks like a file (has an extension) or is in /assets, and we are here, it's a 404
		if strings.Contains(path, ".") || strings.HasPrefix(path, "/assets/") {
			c.Status(http.StatusNotFound)
			return
		}

		c.File("./web/admin-dash/dist/index.html")
	})

	return r
}

// newAdminRedisOptions returns Redis client options tuned for admin's
// workload (health checks and registry queries only).
func newAdminRedisOptions(addr string) *redis.Options {
	return &redis.Options{
		Addr:         addr,
		PoolSize:     5,
		MinIdleConns: 1,
		PoolTimeout:  5 * time.Second,
	}
}

func main() {
	config.Load()
	port := config.Optional("PORT", config.Optional("ADMIN_PORT", "8000"))
	if err := config.ValidatePort(port); err != nil {
		log.Fatalf("❌ Invalid PORT: %v", err)
	}

	// Initialize Redis Client
	redisAddr := config.Optional("REDIS_ADDR", "")
	var rdb *redis.Client
	if redisAddr != "" {
		rdb = redis.NewClient(newAdminRedisOptions(redisAddr))
	}

	// Initialize PubSub Health Checker (lazy, self-healing)
	psHealthChecker := newPubSubHealthChecker()

	// Use internal URL for service-to-service agent catalog fetch.
	// The external GATEWAY_URL is IAP-protected and unreachable from Cloud Run.
	gatewayURL := config.Optional("GATEWAY_INTERNAL_URL",
		config.Optional("GATEWAY_URL", "http://127.0.0.1:8101"))
	registry := buildServiceRegistry(gatewayURL)
	gcpClient := newGCPClient()

	dbHealthChecker := newAlloyDBHealthChecker()
	r := setupRouter(rdb, psHealthChecker, dbHealthChecker, registry, gcpClient)
	log.Printf("Admin UI serving on port %s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Failed to run admin server: %v", err)
	}
}
