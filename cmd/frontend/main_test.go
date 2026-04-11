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
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func init() {
	gin.SetMode(gin.TestMode)
}

func TestFrontendHealth(t *testing.T) {
	r := setupRouter("")

	t.Run("Root health", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/health", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), `"status":"ok"`)
		assert.Contains(t, w.Body.String(), `"service":"frontend"`)
	})

	t.Run("Frontend group health", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/frontend/health", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), `"service":"frontend"`)
	})
}

func TestFrontendConfigJS(t *testing.T) {
	r := setupRouter("")

	t.Run("Root config.js", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/config.js", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Equal(t, "application/javascript", w.Header().Get("Content-Type"))
		assert.Contains(t, w.Body.String(), "window.ENV")
		assert.Contains(t, w.Body.String(), "NG_APP_GATEWAY_URL")
	})

	t.Run("Frontend group config.js", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/frontend/config.js", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), "NG_APP_GATEWAY_URL")
		assert.Contains(t, w.Body.String(), "NG_APP_GATEWAY_ADDR")
		assert.Contains(t, w.Body.String(), `"/ws"`)
	})
}

func TestFrontendWSProxy_ForwardsBinaryFrames(t *testing.T) {
	// Backend WS server: echoes binary frames back
	wsServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		upgrader := websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer conn.Close()
		// Send a binary message to the client
		_ = conn.WriteMessage(websocket.BinaryMessage, []byte("hello from backend"))
		// Read one message and echo it back
		msgType, msg, err := conn.ReadMessage()
		if err != nil {
			return
		}
		_ = conn.WriteMessage(msgType, msg)
	}))
	defer wsServer.Close()

	t.Setenv("GATEWAY_INTERNAL_URL", wsServer.URL)

	r := setupRouter("")
	server := httptest.NewServer(r)
	defer server.Close()

	wsURL := "ws" + server.URL[4:] + "/ws"
	dialer := websocket.Dialer{}
	conn, _, err := dialer.Dial(wsURL, nil)
	require.NoError(t, err, "WebSocket dial failed")
	defer conn.Close()

	// Should receive the backend's binary message
	msgType, msg, err := conn.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, websocket.BinaryMessage, msgType)
	assert.Equal(t, []byte("hello from backend"), msg)

	// Send a binary message to the backend, should get echo
	err = conn.WriteMessage(websocket.BinaryMessage, []byte("ping"))
	require.NoError(t, err)

	msgType, msg, err = conn.ReadMessage()
	require.NoError(t, err)
	assert.Equal(t, websocket.BinaryMessage, msgType)
	assert.Equal(t, []byte("ping"), msg)
}

func TestFrontendAPIProxy_ForwardsRequest(t *testing.T) {
	var receivedPath, receivedMethod string
	apiServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedPath = r.URL.Path
		receivedMethod = r.Method
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(map[string]string{"proxied": "true"})
	}))
	defer apiServer.Close()

	t.Setenv("GATEWAY_INTERNAL_URL", apiServer.URL)

	r := setupRouter("")

	t.Run("Root API proxy", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/v1/sessions", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), "proxied")
		assert.Equal(t, "/api/v1/sessions", receivedPath)
		assert.Equal(t, "GET", receivedMethod)
	})

	t.Run("Frontend group API proxy", func(t *testing.T) {
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("POST", "/frontend/api/v1/sessions", nil)
		r.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Equal(t, "/api/v1/sessions", receivedPath)
		assert.Equal(t, "POST", receivedMethod)
	})
}

func TestFrontendDevProxy_ForwardsUnmatchedRequests(t *testing.T) {
	devServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("<html>dev server: " + r.URL.Path + "</html>"))
	}))
	defer devServer.Close()

	t.Setenv("FRONTEND_DEV_URL", devServer.URL)

	r := setupRouter("")
	// Use a real HTTP server so httputil.ReverseProxy can use CloseNotifier
	bffServer := httptest.NewServer(r)
	defer bffServer.Close()

	t.Run("Root path proxied to dev server", func(t *testing.T) {
		resp, err := http.Get(bffServer.URL + "/some/page")
		require.NoError(t, err)
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)

		assert.Equal(t, http.StatusOK, resp.StatusCode)
		assert.Contains(t, string(body), "dev server: /some/page")
	})

	t.Run("Frontend prefixed path proxied to dev server", func(t *testing.T) {
		resp, err := http.Get(bffServer.URL + "/frontend/some/page")
		require.NoError(t, err)
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)

		assert.Equal(t, http.StatusOK, resp.StatusCode)
		assert.Contains(t, string(body), "dev server: /some/page")
	})

	t.Run("API routes still proxy to gateway not dev server", func(t *testing.T) {
		apiServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_ = json.NewEncoder(w).Encode(map[string]string{"from": "gateway"})
		}))
		defer apiServer.Close()

		t.Setenv("GATEWAY_INTERNAL_URL", apiServer.URL)

		r2 := setupRouter("")
		w := httptest.NewRecorder()
		req, _ := http.NewRequest("GET", "/api/v1/sessions", nil)
		r2.ServeHTTP(w, req)

		assert.Equal(t, http.StatusOK, w.Code)
		assert.Contains(t, w.Body.String(), "gateway")
	})
}

func TestFrontendRedirect(t *testing.T) {
	r := setupRouter("")
	w := httptest.NewRecorder()
	req, _ := http.NewRequest("GET", "/frontend", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, http.StatusMovedPermanently, w.Code)
	assert.Equal(t, "/frontend/", w.Header().Get("Location"))
}
