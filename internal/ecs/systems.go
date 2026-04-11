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

// MovementSystem updates the Position of entities based on their Velocity.
type MovementSystem struct {
	Registry *Registry
}

func (s *MovementSystem) Priority() int {
	return 100 // High priority for physics
}

func (s *MovementSystem) Update(dt float64) {
	entities := s.Registry.View((*Position)(nil), (*Velocity)(nil))
	for _, e := range entities {
		pos := s.Registry.GetComponent(e, (*Position)(nil)).(*Position)
		vel := s.Registry.GetComponent(e, (*Velocity)(nil)).(*Velocity)

		multiplier := 1.0
		if b := s.Registry.GetComponent(e, (*Boost)(nil)); b != nil {
			boost := b.(*Boost)
			if boost.Duration > 0 {
				multiplier = boost.Multiplier
				boost.Duration -= dt
			}
		}

		pos.X += vel.VX * multiplier * dt
		pos.Y += vel.VY * multiplier * dt
	}
}
