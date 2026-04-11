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
	"reflect"
)

type Entity uint64

type Registry struct {
	nextID     Entity
	entities   map[Entity]bool
	components map[reflect.Type]map[Entity]interface{}
	version    uint64
	viewCache  map[string]cachedView
}

type cachedView struct {
	version  uint64
	entities []Entity
}

func NewRegistry() *Registry {
	return &Registry{
		entities:   make(map[Entity]bool),
		components: make(map[reflect.Type]map[Entity]interface{}),
		viewCache:  make(map[string]cachedView),
	}
}

func (r *Registry) CreateEntity() Entity {
	id := r.nextID
	r.entities[id] = true
	r.nextID++
	return id
}

func (r *Registry) AddComponent(e Entity, c interface{}) {
	t := reflect.TypeOf(c)
	if _, ok := r.components[t]; !ok {
		r.components[t] = make(map[Entity]interface{})
	}
	r.components[t][e] = c
	r.version++
}

func (r *Registry) GetComponent(e Entity, target interface{}) interface{} {
	t := reflect.TypeOf(target)
	if storage, ok := r.components[t]; ok {
		return storage[e]
	}
	return nil
}

func (r *Registry) RemoveComponent(e Entity, target interface{}) {
	t := reflect.TypeOf(target)
	if storage, ok := r.components[t]; ok {
		delete(storage, e)
		r.version++
	}
}

func (r *Registry) Count() int {
	return len(r.entities)
}

// View returns a slice of entities that have all the specified component types.
// Optimized with a version-based cache.
func (r *Registry) View(targets ...interface{}) []Entity {
	if len(targets) == 0 {
		return nil
	}

	// Create cache key
	cacheKey := ""
	for _, target := range targets {
		cacheKey += reflect.TypeOf(target).String() + "|"
	}

	if cached, ok := r.viewCache[cacheKey]; ok && cached.version == r.version {
		return cached.entities
	}

	var smallestStorage map[Entity]interface{}
	var smallestType reflect.Type

	for _, target := range targets {
		t := reflect.TypeOf(target)
		storage, ok := r.components[t]
		if !ok {
			return nil
		}
		if smallestStorage == nil || len(storage) < len(smallestStorage) {
			smallestStorage = storage
			smallestType = t
		}
	}

	result := make([]Entity, 0, len(smallestStorage))
	for e := range smallestStorage {
		hasAll := true
		for _, target := range targets {
			t := reflect.TypeOf(target)
			if t == smallestType {
				continue
			}
			if _, ok := r.components[t][e]; !ok {
				hasAll = false
				break
			}
		}
		if hasAll {
			result = append(result, e)
		}
	}

	r.viewCache[cacheKey] = cachedView{
		version:  r.version,
		entities: result,
	}

	return result
}

// System defines the interface for logic that operates on entities/components.
type System interface {
	Priority() int
	Update(dt float64)
}

// World orchestrates the simulation, managing systems and the entity registry.
type World struct {
	registry *Registry
	systems  []System
}

func NewWorld() *World {
	return &World{
		registry: NewRegistry(),
		systems:  []System{},
	}
}

func (w *World) AddSystem(s System) {
	w.systems = append(w.systems, s)
	// Sort systems by priority (highest first)
	for i := len(w.systems) - 1; i > 0; i-- {
		if w.systems[i].Priority() > w.systems[i-1].Priority() {
			w.systems[i], w.systems[i-1] = w.systems[i-1], w.systems[i]
		} else {
			break
		}
	}
}

func (w *World) Systems() []System {
	return w.systems
}

func (w *World) Update(dt float64) {
	for _, system := range w.systems {
		system.Update(dt)
	}
}
