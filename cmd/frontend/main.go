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
	"net/http/httputil"
	"net/url"
	"strings"
	"time"

	"github.com/GoogleCloudPlatform/race-condition/internal/config"
	"github.com/GoogleCloudPlatform/race-condition/internal/middleware"
	"github.com/gin-gonic/gin"
	"github.com/koding/websocketproxy"
)

// gatewayClient is a shared HTTP client for proxying requests to the gateway.
// Reused across all requests for connection pooling.
var gatewayClient = &http.Client{
	Timeout: 30 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:        100,
		MaxIdleConnsPerHost: 20,
		IdleConnTimeout:     90 * time.Second,
	},
}

// setupRouter creates the frontend Gin engine with all routes.
// oidcAudience is the IAP client ID for OIDC token attachment (empty = no-op).
func setupRouter(oidcAudience string) *gin.Engine {
	r := gin.Default()

	r.Use(func(c *gin.Context) {
		log.Printf("Incoming Request: %s %s (Remote: %s)", c.Request.Method, c.Request.URL.Path, c.ClientIP())
		c.Next()
	})

	configHandler := middleware.ConfigJSHandler(map[string]string{
		"NG_APP_GATEWAY_URL":  "/ws",
		"NG_APP_GATEWAY_ADDR": "", // Relative
	})

	wsHandler := func(c *gin.Context) {
		backendURL := config.Optional("GATEWAY_INTERNAL_URL",
			config.Optional("GATEWAY_URL", "http://localhost:8101"))

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
			for key := range out {
				if strings.HasPrefix(strings.ToLower(key), "x-goog-iap-") {
					out.Del(key)
				}
			}
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

		for key, values := range c.Request.Header {
			if strings.EqualFold(key, "Host") || strings.EqualFold(key, "Authorization") || strings.HasPrefix(strings.ToLower(key), "x-goog-") {
				continue
			}
			for _, value := range values {
				req.Header.Add(key, value)
			}
		}

		middleware.AttachOIDCToken(c.Request.Context(), req.Header, oidcAudience)

		client := gatewayClient
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
			resp.Body = io.NopCloser(bytes.NewBuffer(body))
		}

		for key, values := range resp.Header {
			for _, value := range values {
				c.Header(key, value)
			}
		}
		c.DataFromReader(resp.StatusCode, resp.ContentLength, resp.Header.Get("Content-Type"), resp.Body, nil)
	}

	fg := r.Group("/frontend")
	{
		fg.GET("/health", func(c *gin.Context) {
			c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "frontend"})
		})
		fg.GET("/config.js", configHandler)
		fg.GET("/ws", wsHandler)
		fg.Any("/api/v1/*action", apiHandler)
	}

	r.GET("/config.js", configHandler)
	r.GET("/ws", wsHandler)
	r.Any("/api/v1/*action", apiHandler)

	r.NoRoute(func(c *gin.Context) {
		if c.Request.Method != "GET" {
			c.Status(http.StatusNotFound)
			return
		}

		path := c.Request.URL.Path

		devURL := config.Optional("FRONTEND_DEV_URL", "")
		if devURL != "" {
			target, err := url.Parse(devURL)
			if err != nil {
				log.Printf("Invalid FRONTEND_DEV_URL: %v", err)
				c.Status(http.StatusInternalServerError)
				return
			}
			proxy := httputil.NewSingleHostReverseProxy(target)
			proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
				log.Printf("Dev proxy error (is Angular running at %s?): %v", devURL, err)
				http.Error(w, "Frontend dev server unavailable", http.StatusBadGateway)
			}
			// Strip /frontend/ prefix before proxying to dev server
			if strings.HasPrefix(path, "/frontend/") {
				c.Request.URL.Path = strings.TrimPrefix(path, "/frontend")
			}
			proxy.ServeHTTP(c.Writer, c.Request)
			return
		}

		if strings.HasPrefix(path, "/frontend/") || path == "/frontend" {
			http.StripPrefix("/frontend", http.FileServer(http.Dir("./web/frontend/dist"))).ServeHTTP(c.Writer, c.Request)
			return
		}

		http.FileServer(http.Dir("./web/frontend/dist")).ServeHTTP(c.Writer, c.Request)
	})

	r.GET("/frontend", func(c *gin.Context) {
		c.Redirect(http.StatusMovedPermanently, "/frontend/")
	})

	r.GET("/health", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"status": "ok", "service": "frontend"})
	})

	return r
}

func main() {
	config.Load()
	port := config.Optional("PORT", "8080")
	if err := config.ValidatePort(port); err != nil {
		log.Fatalf("❌ Invalid PORT: %v", err)
	}

	oidcAudience := config.Optional("IAP_CLIENT_ID", "")

	r := setupRouter(oidcAudience)
	log.Printf("Frontend UI serving on port %s", port)
	if err := r.Run(":" + port); err != nil {
		log.Fatalf("Failed to run frontend server: %v", err)
	}
}
