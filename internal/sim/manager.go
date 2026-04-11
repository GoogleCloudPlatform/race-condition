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

package sim

import (
	"log"
	"sync"
)

// Phase represents a distinct stage in the simulation lifecycle.
type Phase string

const (
	PhaseConceptualization Phase = "conceptualization"
	PhasePlanning          Phase = "planning"
	PhaseDevelopment       Phase = "development"
	PhaseTesting           Phase = "testing"
	PhaseDeployment        Phase = "deployment"
	PhaseLive              Phase = "live"
	PhaseAnalysis          Phase = "analysis"
)

// Manager handles the simulation lifecycle and phase transitions.
type Manager struct {
	mu           sync.RWMutex
	currentPhase Phase
}

func NewManager() *Manager {
	return &Manager{
		currentPhase: PhaseConceptualization,
	}
}

func (m *Manager) GetPhase() Phase {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.currentPhase
}

func (m *Manager) TransitionTo(next Phase) {
	m.mu.Lock()
	defer m.mu.Unlock()
	log.Printf("Simulation transitioning from %s to %s", m.currentPhase, next)
	m.currentPhase = next
}
