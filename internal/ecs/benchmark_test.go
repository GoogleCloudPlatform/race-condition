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
)

func BenchmarkMovementSystem(b *testing.B) {
	world := NewWorld()
	reg := world.registry

	// Pre-create 100,000 entities
	for i := 0; i < 100000; i++ {
		e := reg.CreateEntity()
		reg.AddComponent(e, &Position{X: float64(i), Y: float64(i)})
		reg.AddComponent(e, &Velocity{VX: 1.0, VY: 1.0})
	}

	world.AddSystem(&MovementSystem{Registry: reg})

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		world.Update(0.016)
	}
}
