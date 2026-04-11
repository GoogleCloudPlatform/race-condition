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

// Package auth contains shared OIDC helpers used by services that
// invoke other Google-fronted services (Cloud Run, IAP, Agent Engine).
//
// Race Condition runs in two auth modes:
//
//   - IAP mode (dev/prod): the gateway sits behind Identity-Aware Proxy
//     and per-user OIDC tokens are minted with audience=IAP_CLIENT_ID.
//   - Cloud Run IAM mode (OSS): no IAP brand exists; service-to-service
//     calls authenticate against Cloud Run's roles/run.invoker check
//     using OIDC tokens whose audience is the target service's URL.
//
// ResolveAudience picks the right audience for either mode without
// requiring callers to branch on env vars themselves.
package auth

import "os"

// ResolveAudience returns the OIDC audience to use when invoking a
// downstream Google-fronted service. IAP_CLIENT_ID wins when set
// (dev/prod IAP-fronted gateway). Otherwise the fallbackURL is used,
// which for OSS Cloud Run IAM mode is the .run.app URL of the target
// service.
//
// An empty return value means "do not attach an OIDC token" -- callers
// (e.g. middleware.AttachOIDCToken) treat this as a no-op.
func ResolveAudience(fallbackURL string) string {
	if iap := os.Getenv("IAP_CLIENT_ID"); iap != "" {
		return iap
	}
	return fallbackURL
}
