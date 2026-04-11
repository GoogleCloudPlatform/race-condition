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

package middleware

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"golang.org/x/oauth2"
	"google.golang.org/api/idtoken"
)

func init() {
	gin.SetMode(gin.TestMode)
}

func TestCORS_DefaultAllowsAll(t *testing.T) {
	r := gin.New()
	r.Use(CORS(""))
	r.GET("/test", func(c *gin.Context) { c.String(200, "ok") })

	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, "*", w.Header().Get("Access-Control-Allow-Origin"))
	assert.Contains(t, w.Header().Get("Access-Control-Allow-Methods"), "GET")
	assert.Contains(t, w.Header().Get("Access-Control-Allow-Headers"), "Content-Type")
}

func TestCORS_RespectsConfiguredOrigin(t *testing.T) {
	r := gin.New()
	r.Use(CORS("https://example.com"))
	r.GET("/test", func(c *gin.Context) { c.String(200, "ok") })

	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, "https://example.com", w.Header().Get("Access-Control-Allow-Origin"))
}

func TestCORS_OptionsReturns204(t *testing.T) {
	r := gin.New()
	r.Use(CORS(""))
	r.GET("/test", func(c *gin.Context) { c.String(200, "ok") })

	w := httptest.NewRecorder()
	req := httptest.NewRequest("OPTIONS", "/test", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 204, w.Code)
}

func TestConfigJS_SafeEncoding(t *testing.T) {
	result := RenderConfigJS(map[string]string{
		"FOO": "bar",
		"XSS": "'; alert('pwned'); '",
	})
	assert.Contains(t, result, "window.ENV =")
	// Single quotes must be backslash-escaped to prevent JS string breakout.
	// JSEscapeString turns ' into \' so the raw sequence "'; " cannot appear.
	// Instead it becomes "\\'; " in the output (backslash-escaped single quote).
	assert.Contains(t, result, `\\'`)
	// Normal values pass through unescaped
	assert.Contains(t, result, `"FOO":"bar"`)
}

func TestConfigJS_EmptyMap(t *testing.T) {
	result := RenderConfigJS(map[string]string{})
	assert.Equal(t, "window.ENV = {};", result)
}

func TestConfigJSHandler_ServesJavascript(t *testing.T) {
	r := gin.New()
	r.GET("/config.js", ConfigJSHandler(map[string]string{"KEY": "value"}))

	w := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/config.js", nil)
	r.ServeHTTP(w, req)

	assert.Equal(t, 200, w.Code)
	assert.Contains(t, w.Header().Get("Content-Type"), "application/javascript")
	assert.Contains(t, w.Body.String(), "window.ENV =")
	assert.Contains(t, w.Body.String(), "KEY")
}

func TestAttachOIDCToken_EmptyAudience(t *testing.T) {
	header := make(http.Header)
	AttachOIDCToken(context.Background(), header, "")
	// With empty audience, no Authorization header should be set
	assert.Empty(t, header.Get("Authorization"))
}

// fakeTokenSource implements oauth2.TokenSource for testing.
type fakeTokenSource struct {
	token *oauth2.Token
	err   error
}

func (f *fakeTokenSource) Token() (*oauth2.Token, error) {
	return f.token, f.err
}

func TestAttachOIDCToken_Success(t *testing.T) {
	orig := newTokenSource
	defer func() { newTokenSource = orig }()

	newTokenSource = func(_ context.Context, _ string, _ ...idtoken.ClientOption) (oauth2.TokenSource, error) {
		return &fakeTokenSource{
			token: &oauth2.Token{AccessToken: "test-oidc-token"},
		}, nil
	}

	header := make(http.Header)
	AttachOIDCToken(context.Background(), header, "https://my-service.run.app")

	assert.Equal(t, "Bearer test-oidc-token", header.Get("Authorization"))
}

func TestAttachOIDCToken_TokenSourceCreationError(t *testing.T) {
	orig := newTokenSource
	defer func() { newTokenSource = orig }()

	newTokenSource = func(_ context.Context, _ string, _ ...idtoken.ClientOption) (oauth2.TokenSource, error) {
		return nil, errors.New("no credentials found")
	}

	header := make(http.Header)
	AttachOIDCToken(context.Background(), header, "https://my-service.run.app")

	// Should not set Authorization header when token source creation fails
	assert.Empty(t, header.Get("Authorization"))
}

func TestAttachOIDCToken_TokenFetchError(t *testing.T) {
	orig := newTokenSource
	defer func() { newTokenSource = orig }()

	newTokenSource = func(_ context.Context, _ string, _ ...idtoken.ClientOption) (oauth2.TokenSource, error) {
		return &fakeTokenSource{err: errors.New("token expired")}, nil
	}

	header := make(http.Header)
	AttachOIDCToken(context.Background(), header, "https://my-service.run.app")

	// Should not set Authorization header when token fetch fails
	assert.Empty(t, header.Get("Authorization"))
}
