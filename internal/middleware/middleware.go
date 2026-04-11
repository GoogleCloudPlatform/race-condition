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

// Package middleware provides shared HTTP middleware for all Go services.
package middleware

import (
	"context"
	"encoding/json"
	"fmt"
	"html/template"
	"log"
	"net/http"

	"github.com/gin-gonic/gin"
	"google.golang.org/api/idtoken"
)

// CORS returns a gin middleware that sets CORS headers.
// If allowedOrigin is empty, defaults to "*".
func CORS(allowedOrigin string) gin.HandlerFunc {
	return func(c *gin.Context) {
		origin := allowedOrigin
		if origin == "" {
			origin = "*"
		}
		c.Writer.Header().Set("Access-Control-Allow-Origin", origin)
		c.Writer.Header().Set("Access-Control-Allow-Methods",
			"GET, POST, OPTIONS, PUT, DELETE")
		c.Writer.Header().Set("Access-Control-Allow-Headers",
			"Content-Type, Content-Length, Accept-Encoding, "+
				"X-CSRF-Token, Authorization")
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(204)
			return
		}
		c.Next()
	}
}

// RenderConfigJS produces a safe `window.ENV = {...};` JS snippet.
// All values are JS-escaped to prevent XSS via string injection.
func RenderConfigJS(vars map[string]string) string {
	safe := make(map[string]string, len(vars))
	for k, v := range vars {
		safe[k] = template.JSEscapeString(v)
	}
	data, _ := json.Marshal(safe)
	return fmt.Sprintf("window.ENV = %s;", string(data))
}

// ConfigJSHandler returns a gin handler that serves window.ENV config.
// Values are safely JSON-encoded to prevent XSS.
func ConfigJSHandler(vars map[string]string) gin.HandlerFunc {
	js := RenderConfigJS(vars)
	return func(c *gin.Context) {
		c.Header("Content-Type", "application/javascript")
		c.String(200, js)
	}
}

// newTokenSource is the function used to create OIDC token sources.
// It is a variable to allow replacement in tests.
var newTokenSource = idtoken.NewTokenSource

// AttachOIDCToken fetches a Google OIDC token for the given audience
// and sets the Authorization header on the request. Returns any error.
// This is a no-op if audience is empty.
func AttachOIDCToken(ctx context.Context, header http.Header, audience string) {
	if audience == "" {
		return
	}
	tokenSource, err := newTokenSource(ctx, audience)
	if err != nil {
		log.Printf("OIDC: Failed to create token source for %s: %v", audience, err)
		return
	}
	token, err := tokenSource.Token()
	if err != nil {
		log.Printf("OIDC: Failed to get token for %s: %v", audience, err)
		return
	}
	header.Set("Authorization", "Bearer "+token.AccessToken)
}
