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

func TestGenericAddAndGet(t *testing.T) {
	r := NewRegistry()
	e := r.CreateEntity()

	pos := &Position{X: 10, Y: 20}
	AddComponent(r, e, pos)

	got := GetComponent[Position](r, e)
	assert.NotNil(t, got)
	assert.Equal(t, 10.0, got.X)
	assert.Equal(t, 20.0, got.Y)
}

func TestGenericGetMissing(t *testing.T) {
	r := NewRegistry()
	e := r.CreateEntity()

	got := GetComponent[Position](r, e)
	assert.Nil(t, got)
}

func TestGenericRemove(t *testing.T) {
	r := NewRegistry()
	e := r.CreateEntity()

	AddComponent(r, e, &Velocity{VX: 5, VY: 10})
	assert.NotNil(t, GetComponent[Velocity](r, e))

	RemoveComponent[Velocity](r, e)
	assert.Nil(t, GetComponent[Velocity](r, e))
}

func TestGenericInteropWithReflect(t *testing.T) {
	// Verify that generic and reflect-based APIs are interop-compatible
	r := NewRegistry()
	e := r.CreateEntity()

	// Add via generic
	AddComponent(r, e, &Position{X: 42, Y: 99})

	// Read via reflect-based API
	got := r.GetComponent(e, (*Position)(nil))
	assert.NotNil(t, got)
	assert.Equal(t, 42.0, got.(*Position).X)

	// Add via reflect-based API
	r.AddComponent(e, &Boost{Multiplier: 2.0, Duration: 5.0})

	// Read via generic
	boost := GetComponent[Boost](r, e)
	assert.NotNil(t, boost)
	assert.Equal(t, 2.0, boost.Multiplier)
}
