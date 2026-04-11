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

import "os"

// ResolveAudience returns the OIDC audience for a downstream service:
// IAP_CLIENT_ID if set, otherwise fallbackURL. An empty return means
// "do not attach a token" (matches middleware.AttachOIDCToken's no-op).
func ResolveAudience(fallbackURL string) string {
	if iap := os.Getenv("IAP_CLIENT_ID"); iap != "" {
		return iap
	}
	return fallbackURL
}
