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

// Position component tracks the location of an entity in the simulation grid.
type Position struct {
	X, Y float64
}

// Velocity component tracks the speed and direction of an entity.
type Velocity struct {
	VX, VY float64
}

// RacingMetadata tracks simulation-specific runner state.
type RacingMetadata struct {
	Rank     int
	Progress float64 // 0.0 to 1.0
	Status   string  // e.g., "racing", "finished", "ready"
}

// Boost component applies temporary multipliers to speed.
type Boost struct {
	Multiplier float64
	Duration   float64 // Remaining time in seconds
}
