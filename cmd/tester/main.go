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
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"

	"github.com/GoogleCloudPlatform/race-condition/internal/config"
	"github.com/GoogleCloudPlatform/race-condition/internal/middleware"
	"github.com/gin-gonic/gin"
	"github.com/koding/websocketproxy"
)

// setupRouter creates the tester Gin engine with all routes.
// oidcAudience is the IAP client ID for OIDC token attachment (empty = no-op).
func setupRouter(oidcAudience string) *gin.Engine {
	r := gin.Default()

	// Global request logger middleware
	r.Use(func(c *gin.Context) {
		log.Printf("Incoming Request: %s %s (Remote: %s)", c.Request.Method, c.Request.URL.Path, c.ClientIP())
		c.Next()
	})

	// Shared handler functions for dual registration (GCLB prefix + root)
	configHandler := middleware.ConfigJSHandler(map[string]string{
		"VITE_GATEWAY_URL": "/ws",
	})

	wsHandler := func(c *gin.Context) {
		backendURL := config.Optional("GATEWAY_INTERNAL_URL",
			config.Optional("GATEWAY_URL", "http://localhost:8101"))

		// Convert http to ws for the backend connection
		wsURLStr := strings.Replace(backendURL, "http://", "ws://", 1)
		wsURLStr = strings.Replace(wsURLStr, "https://", "wss://", 1)
		if !strings.HasSuffix(wsURLStr, "/ws") {
			wsURLStr = strings.TrimSuffix(wsURLStr, "/") + "/ws"
		}

		u, _ := url.Parse(wsURLStr)
		log.Printf("WebSocket Proxy: Initializing for %s", wsURLStr)
		proxy := websocketproxy.NewProxy(u)

		proxy.Director = func(incoming *http.Request, out http.Header) {
			out.Set("Host", u.Host)

			// Strip sensitive IAP headers
			for key := range out {
				if strings.HasPrefix(strings.ToLower(key), "x-goog-iap-") {
					out.Del(key)
				}
			}

			// Attach OIDC token for Cloud Run service-to-service auth
			middleware.AttachOIDCToken(incoming.Context(), out, oidcAudience)
		}

		proxy.ServeHTTP(c.Writer, c.Request)
	}

	apiHandler := func(c *gin.Context) {
		backendURL := config.Optional("GATEWAY_INTERNAL_URL",
			config.Optional("GATEWAY_URL", "http://localhost:8101"))

		action := c.Param("action")
		targetURL := strings.TrimSuffix(backendURL, "/") + "/api/v1" + action
		if c.Request.URL.RawQuery != "" {
			targetURL += "?" + c.Request.URL.RawQuery
		}

		log.Printf("Proxy Handler triggered for path: %s, target: %s", c.Request.URL.Path, targetURL)

		req, err := http.NewRequest(c.Request.Method, targetURL, c.Request.Body)
		if err != nil {
			log.Printf("Proxy Error: Failed to create request: %v", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to create proxy request: " + err.Error()})
			return
		}

		// Copy headers (excluding Host and Authorization)
		for key, values := range c.Request.Header {
			if strings.EqualFold(key, "Host") || strings.EqualFold(key, "Authorization") || strings.HasPrefix(strings.ToLower(key), "x-goog-") {
				continue
			}
			for _, value := range values {
				req.Header.Add(key, value)
			}
		}

		// Attach OIDC token for Cloud Run service-to-service auth
		middleware.AttachOIDCToken(c.Request.Context(), req.Header, oidcAudience)

		client := &http.Client{}
		resp, err := client.Do(req)
		if err != nil {
			log.Printf("Proxy Error: Client.Do failed: %v", err)
			c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to proxy request to gateway: " + err.Error()})
			return
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			body, _ := io.ReadAll(resp.Body)
			log.Printf("Proxy: Gateway returned status %d. Body: %s", resp.StatusCode, string(body))
			// Reset body for DataFromReader
			resp.Body = io.NopCloser(bytes.NewBuffer(body))
		}

		for key, values := range resp.Header {
			for _, value := range values {
				c.Header(key, value)
			}
		}
		c.DataFromReader(resp.StatusCode, resp.ContentLength, resp.Header.Get("Content-Type"), resp.Body, nil)
	}

	// Register under /tester/* prefix (GCLB path-based routing)
	tg := r.Group("/tester")
	{
		tg.GET("/health", func(c *gin.Context) {
			c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "tester"})
		})
		tg.GET("/config.js", configHandler)
		tg.GET("/ws", wsHandler)
		tg.Any("/api/v1/*action", apiHandler)
	}

	// Register at root level (direct Cloud Run domain access)
	r.GET("/config.js", configHandler)
	r.GET("/ws", wsHandler)
	r.Any("/api/v1/*action", apiHandler)

	// Helper to serve static files with no-cache for index.html
	serveStatic := func(c *gin.Context, prefix string, dir http.FileSystem) {
		if strings.HasSuffix(c.Request.URL.Path, "index.html") || c.Request.URL.Path == prefix+"/" || c.Request.URL.Path == prefix {
			c.Header("Cache-Control", "no-cache, no-store, must-revalidate")
			c.Header("Pragma", "no-cache")
			c.Header("Expires", "0")
		}
		if prefix != "" && prefix != "/" {
			http.StripPrefix(prefix, http.FileServer(dir)).ServeHTTP(c.Writer, c.Request)
		} else {
			http.FileServer(dir).ServeHTTP(c.Writer, c.Request)
		}
	}

	// Serve static files via NoRoute
	r.NoRoute(func(c *gin.Context) {
		if c.Request.Method != "GET" {
			c.Status(http.StatusNotFound)
			return
		}

		path := c.Request.URL.Path

		// Serve via /tester/ prefix (GCLB path-based routing)
		if strings.HasPrefix(path, "/tester/") || path == "/tester" {
			serveStatic(c, "/tester", http.Dir("./web/tester/dist"))
			return
		}

		// Serve at root (direct Cloud Run access via .run.app or own domain)
		serveStatic(c, "", http.Dir("./web/tester/dist"))
	})

	// Redirect /tester (no slash) to /tester/
	r.GET("/tester", func(c *gin.Context) {
		c.Redirect(http.StatusMovedPermanently, "/tester/")
	})

	// Root health check for Cloud Run probes
	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "tester"})
	})

	return r
}

func main() {
	config.Load()
	port := config.Optional("PORT", "8080")
	if err := config.ValidatePort(port); err != nil {
		log.Fatalf("❌ Invalid PORT: %v", err)
	}

	// OIDC audience is set via IAP_CLIENT_ID in cloud deployments.
	// Locally this is empty, so AttachOIDCToken is a no-op.
	oidcAudience := config.Optional("IAP_CLIENT_ID", "")

	r := setupRouter(oidcAudience)
	log.Printf("Tester UI serving on port %s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Failed to run tester server: %v", err)
	}
}
