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

// Package ecs provides a lightweight Entity Component System for the simulation.
//
// The ECS pattern separates data (Components) from logic (Systems), enabling
// high-performance simulation of thousands of concurrent runners. Entities are
// simple IDs; Components are plain structs attached to entities; Systems
// operate on entities that match a set of component types.
//
// # Core Types
//
//   - Entity: A unique ID (uint64) representing a simulation actor.
//   - Registry: Stores entity-component associations with a version-cached View query.
//   - World: Orchestrates Systems, executing them in priority order each tick.
//
// # Generic API (Go 1.18+)
//
// Type-safe generic helpers are available in generics.go:
//
//	ecs.AddComponent(registry, entity, &Position{X: 10, Y: 20})
//	pos := ecs.GetComponent[Position](registry, entity) // *Position
//	ecs.RemoveComponent[Position](registry, entity)
//
// These are fully interoperable with the reflect-based Registry methods.
//
// # Performance
//
// The Registry uses a version-based view cache. Queries that match the same
// component types are cached until the registry version changes (any add/remove).
// The View query optimizes by iterating the smallest matching component storage.
package ecs
