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

// Package sim manages the simulation lifecycle and phase transitions.
//
// The simulation proceeds through the following phases:
//
//   - conceptualization: Initial setup and configuration.
//   - planning: Route generation and event logistics via the planner agent.
//   - development: Iterative refinement of simulation parameters.
//   - testing: Validation of the simulation against expected behavior.
//   - deployment: Cloud deployment and service provisioning.
//   - live: Active simulation execution with real-time telemetry.
//   - analysis: Post-simulation data analysis and reporting.
//
// The Manager is safe for concurrent use. Phase transitions are protected
// by a read-write mutex and logged for observability.
//
// Usage:
//
//	mgr := sim.NewManager()
//	mgr.TransitionTo(sim.PhasePlanning)
//	current := mgr.GetPhase() // "planning"
package sim
