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

// Package auth contains shared OIDC helpers for service-to-service calls.
//
// Two auth modes:
//   - IAP (dev/prod): audience = IAP_CLIENT_ID.
//   - Cloud Run IAM (OSS): audience = target service's .run.app URL.
package auth

import (
	"context"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"google.golang.org/api/idtoken"
)

// ResolveAudience returns the OIDC audience for a downstream service:
// IAP_CLIENT_ID if set, otherwise fallbackURL. An empty return means
// "do not attach a token" (matches middleware.AttachOIDCToken's no-op).
func ResolveAudience(fallbackURL string) string {
	if iap := os.Getenv("IAP_CLIENT_ID"); iap != "" {
		return iap
	}
	return fallbackURL
}

// IsCloudRunURL returns true for HTTPS URLs that aren't Agent Engine and aren't
// localhost. Treated as Cloud Run-style endpoints that require an OIDC ID token
// (audience = service URL) rather than an OAuth bearer.
func IsCloudRunURL(u string) bool {
	parsed, err := url.Parse(u)
	if err != nil || parsed.Scheme != "https" {
		return false
	}
	host := parsed.Hostname()
	if host == "localhost" || host == "127.0.0.1" {
		return false
	}
	// Agent Engine has its own OAuth-bearer auth path.
	if strings.Contains(host, "aiplatform.googleapis.com") && strings.Contains(parsed.Path, "reasoningEngines") {
		return false
	}
	return true
}

// AudienceFor returns the OIDC audience for an arbitrary URL: scheme + host
// only (no port, no path). This matches the audience format Cloud Run validates
// against an injected ID token. Returns empty string if the URL is unparseable.
func AudienceFor(u string) string {
	parsed, err := url.Parse(u)
	if err != nil || parsed.Host == "" {
		return ""
	}
	return parsed.Scheme + "://" + parsed.Host
}

// oidcClientCache caches per-audience OIDC HTTP clients to avoid repeated
// metadata-server lookups. Keyed by the resolved audience string.
var oidcClientCache sync.Map // map[string]*http.Client

// OIDCClient returns an *http.Client that auto-attaches a Google-signed ID
// token with the specified audience to every request. Cached per-audience.
// Returns nil if the underlying idtoken client cannot be constructed (e.g.,
// no Application Default Credentials available); callers should fall back to
// a plain client in that case.
//
// The returned client is intended for service-to-service calls into Cloud Run
// services secured by IAM (--no-allow-unauthenticated). Each request carries
// `Authorization: Bearer <id-token>` with `aud == audience`.
func OIDCClient(audience string) *http.Client {
	if audience == "" {
		return nil
	}
	if cached, ok := oidcClientCache.Load(audience); ok {
		return cached.(*http.Client)
	}
	client, err := idtoken.NewClient(context.Background(), audience)
	if err != nil {
		log.Printf("auth: WARNING — failed to create OIDC client for audience %q: %v (caller will fall back to unauthenticated)", audience, err)
		return nil
	}
	client.Timeout = 10 * time.Second
	oidcClientCache.Store(audience, client)
	return client
}
