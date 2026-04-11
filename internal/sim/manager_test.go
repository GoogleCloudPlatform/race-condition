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
	"sync"
	"testing"
)

func TestNewManager(t *testing.T) {
	m := NewManager()
	if m == nil {
		t.Fatal("NewManager returned nil")
	}
	if m.GetPhase() != PhaseConceptualization {
		t.Errorf("initial phase = %q, want %q", m.GetPhase(), PhaseConceptualization)
	}
}

func TestTransitionTo(t *testing.T) {
	m := NewManager()

	transitions := []Phase{
		PhasePlanning,
		PhaseDevelopment,
		PhaseTesting,
		PhaseDeployment,
		PhaseLive,
		PhaseAnalysis,
	}

	for _, phase := range transitions {
		m.TransitionTo(phase)
		if got := m.GetPhase(); got != phase {
			t.Errorf("after TransitionTo(%q): GetPhase() = %q", phase, got)
		}
	}
}

func TestConcurrentAccess(t *testing.T) {
	m := NewManager()
	var wg sync.WaitGroup

	// Concurrent writers
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			m.TransitionTo(PhaseLive)
		}()
	}

	// Concurrent readers
	for i := 0; i < 50; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = m.GetPhase()
		}()
	}

	wg.Wait()

	// All 50 writers set PhaseLive, so final state must be PhaseLive.
	if got := m.GetPhase(); got != PhaseLive {
		t.Errorf("after concurrent writes: GetPhase() = %q, want %q", got, PhaseLive)
	}
}
