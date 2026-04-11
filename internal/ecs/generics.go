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

import "reflect"

// AddComponent adds a typed component to an entity with compile-time type safety.
// This is the generic equivalent of Registry.AddComponent().
func AddComponent[T any](r *Registry, e Entity, c *T) {
	t := reflect.TypeOf(c)
	if _, ok := r.components[t]; !ok {
		r.components[t] = make(map[Entity]interface{})
	}
	r.components[t][e] = c
	r.version++
}

// GetComponent retrieves a typed component from an entity.
// Returns nil if the entity does not have the component.
// This is the generic equivalent of Registry.GetComponent().
func GetComponent[T any](r *Registry, e Entity) *T {
	var zero T
	t := reflect.TypeOf(&zero)
	if storage, ok := r.components[t]; ok {
		if c, ok := storage[e]; ok {
			return c.(*T)
		}
	}
	return nil
}

// RemoveComponent removes a typed component from an entity.
// This is the generic equivalent of Registry.RemoveComponent().
func RemoveComponent[T any](r *Registry, e Entity) {
	var zero T
	t := reflect.TypeOf(&zero)
	if storage, ok := r.components[t]; ok {
		delete(storage, e)
		r.version++
	}
}
