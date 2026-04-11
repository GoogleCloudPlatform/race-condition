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

package auth

import "testing"

func TestResolveAudience_PrefersIAPClientID(t *testing.T) {
	t.Setenv("IAP_CLIENT_ID", "iap-aud-12345")

	got := ResolveAudience("https://gateway-fallback.run.app")

	if got != "iap-aud-12345" {
		t.Fatalf("expected IAP client id, got %q", got)
	}
}

func TestResolveAudience_FallsBackToURLWhenIAPUnset(t *testing.T) {
	t.Setenv("IAP_CLIENT_ID", "")

	got := ResolveAudience("https://gateway-fallback.run.app")

	if got != "https://gateway-fallback.run.app" {
		t.Fatalf("expected fallback URL, got %q", got)
	}
}

func TestResolveAudience_ReturnsEmptyWhenBothUnset(t *testing.T) {
	// Neither IAP nor a fallback URL configured. Caller treats empty as
	// "skip OIDC attachment" (existing AttachOIDCToken contract).
	t.Setenv("IAP_CLIENT_ID", "")

	got := ResolveAudience("")

	if got != "" {
		t.Fatalf("expected empty audience, got %q", got)
	}
}
