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

// Package agent provides agent catalog management for the simulation gateway.
//
// The gateway discovers available agents at startup by fetching their A2A
// AgentCards from /.well-known/agent-card.json endpoints. Agent base URLs
// are configured via the AGENT_URLS environment variable (comma-separated).
//
// Each AgentCard contains:
//
//   - Name and description for display in the dashboard.
//   - URL for the agent's A2A endpoint.
//   - Supported skills, transport modes, and capabilities.
//   - Dispatch mode via the n26:dispatch/1.0 extension.
//
// The catalog uses retryable HTTP requests (5 attempts, exponential backoff)
// so agents that are still starting up are discovered once they become
// available.
//
// Usage:
//
//	catalog := agent.NewCatalog([]string{
//	    "http://localhost:8210/a2a/runner_autopilot",
//	    "http://localhost:8202/a2a/simulator",
//	})
//	agents, err := catalog.DiscoverAgents()
//	// agents is map[string]AgentCard keyed by agent name
package agent
