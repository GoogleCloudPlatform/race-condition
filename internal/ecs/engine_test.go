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

package ecs

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestMovementSystemWithBoost(t *testing.T) {
	world := NewWorld()
	registry := world.registry

	entity := registry.CreateEntity()
	pos := &Position{X: 0, Y: 0}
	vel := &Velocity{VX: 10, VY: 0}
	boost := &Boost{Multiplier: 2.0, Duration: 1.0}
	registry.AddComponent(entity, pos)
	registry.AddComponent(entity, vel)
	registry.AddComponent(entity, boost)

	moveSystem := &MovementSystem{Registry: registry}
	world.AddSystem(moveSystem)

	// Update with dt = 0.5. Expected movement: 10 * 2.0 * 0.5 = 10
	world.Update(0.5)
	assert.Equal(t, 10.0, pos.X)
	assert.Equal(t, 0.5, boost.Duration)

	// Update with dt = 0.5. Expected movement: 10 * 2.0 * 0.5 = 10. Total X = 20
	world.Update(0.5)
	assert.Equal(t, 20.0, pos.X)
	assert.Equal(t, 0.0, boost.Duration)

	// Update with dt = 0.5. Boost expired. Expected movement: 10 * 1.0 * 0.5 = 5. Total X = 25
	world.Update(0.5)
	assert.Equal(t, 25.0, pos.X)
}

type MockSystem struct {
	priority int
	name     string
}

func (s *MockSystem) Priority() int     { return s.priority }
func (s *MockSystem) Update(dt float64) {}

func TestSystemRegistry(t *testing.T) {
	world := NewWorld()

	s1 := &MockSystem{priority: 10, name: "System1"}
	s2 := &MockSystem{priority: 5, name: "System2"}
	s3 := &MockSystem{priority: 15, name: "System3"}

	world.AddSystem(s1)
	world.AddSystem(s2)
	world.AddSystem(s3)

	systems := world.Systems()
	assert.Len(t, systems, 3)

	// Verified ordered by priority (descending or ascending? plan says ordered.
	// Let's assume ascending priority, usually high priority runs later or earlier.
	// Common pattern: high priority value runs earlier.
	assert.Equal(t, s3, systems[0]) // priority 15
	assert.Equal(t, s1, systems[1]) // priority 10
	assert.Equal(t, s2, systems[2]) // priority 5
}

func TestMovementSystem(t *testing.T) {
	world := NewWorld()
	registry := world.registry

	entity := registry.CreateEntity()
	pos := &Position{X: 0, Y: 0}
	vel := &Velocity{VX: 10, VY: 20}
	registry.AddComponent(entity, pos)
	registry.AddComponent(entity, vel)

	moveSystem := &MovementSystem{Registry: registry}
	world.AddSystem(moveSystem)

	// Update with dt = 1.0
	world.Update(1.0)

	assert.Equal(t, 10.0, pos.X)
	assert.Equal(t, 20.0, pos.Y)

	// Update with dt = 0.5
	world.Update(0.5)
	assert.Equal(t, 15.0, pos.X)
	assert.Equal(t, 30.0, pos.Y)
}
