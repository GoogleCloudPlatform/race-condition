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

package session

import (
	"context"
	"sync"

	"github.com/GoogleCloudPlatform/race-condition/internal/ecs"
)

// Session represents a mapping between an ECS entity and an agent session.
type Session struct {
	EntityID  ecs.Entity
	SessionID string
	AgentType string
}

// Service defines the interface for managing agent sessions.
type Service interface {
	Register(s Session)
	GetSession(e ecs.Entity) (string, bool)
	GetEntity(sessionID string) (ecs.Entity, bool)
}

// DistributedRegistry defines the interface for cross-gateway session tracking.
// All gateway instances are horizontally scaled behind a load balancer — any
// instance can handle any request. The registry maps sessions to agent types
// so the gateway can route broadcasts to only agent types with active sessions.
type DistributedRegistry interface {
	TrackSession(ctx context.Context, sessionID string, agentType string, simulationID string) error
	BatchTrackSessions(ctx context.Context, sessions []SessionTrackingEntry) error
	FindAgentType(ctx context.Context, sessionID string) (string, bool, error)
	ActiveAgentTypes(ctx context.Context) ([]string, error)
	UntrackSession(ctx context.Context, sessionID string) error
	ListSessions(ctx context.Context) ([]string, error)
	FindSimulation(ctx context.Context, sessionID string) (string, error)
	ListSimulations(ctx context.Context) ([]string, error)
	Flush(ctx context.Context) (int, error)
	Reap(ctx context.Context) (int, error)
}

// InMemorySessionService implements the Service interface using in-memory maps.
// This is used for local development to avoid SQLite file locking bottlenecks.
type InMemorySessionService struct {
	mu            sync.RWMutex
	entityToSess  map[ecs.Entity]string
	sessToEntity  map[string]ecs.Entity
	agentTypes    map[string]string          // sessionID -> agentType
	agentSessions map[string]map[string]bool // agentType -> set of sessionIDs
	sessionSim    map[string]string          // sessionID -> simulationID
	simSessions   map[string]map[string]bool // simulationID -> set of sessionIDs
}

func NewInMemorySessionService() *InMemorySessionService {
	return &InMemorySessionService{
		entityToSess:  make(map[ecs.Entity]string),
		sessToEntity:  make(map[string]ecs.Entity),
		agentTypes:    make(map[string]string),
		agentSessions: make(map[string]map[string]bool),
		sessionSim:    make(map[string]string),
		simSessions:   make(map[string]map[string]bool),
	}
}

func (s *InMemorySessionService) Register(sess Session) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.entityToSess[sess.EntityID] = sess.SessionID
	s.sessToEntity[sess.SessionID] = sess.EntityID
}

func (s *InMemorySessionService) GetSession(e ecs.Entity) (string, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	id, ok := s.entityToSess[e]
	return id, ok
}

func (s *InMemorySessionService) GetEntity(sessionID string) (ecs.Entity, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	e, ok := s.sessToEntity[sessionID]
	return e, ok
}

// DistributedRegistry implementation for InMemory (local dev consistency)

func (s *InMemorySessionService) TrackSession(ctx context.Context, sessionID, agentType, simulationID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.agentTypes[sessionID] = agentType
	if s.agentSessions[agentType] == nil {
		s.agentSessions[agentType] = make(map[string]bool)
	}
	s.agentSessions[agentType][sessionID] = true
	if simulationID != "" {
		s.sessionSim[sessionID] = simulationID
		if s.simSessions[simulationID] == nil {
			s.simSessions[simulationID] = make(map[string]bool)
		}
		s.simSessions[simulationID][sessionID] = true
	}
	return nil
}

func (s *InMemorySessionService) BatchTrackSessions(ctx context.Context, sessions []SessionTrackingEntry) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, sess := range sessions {
		s.agentTypes[sess.SessionID] = sess.AgentType
		if s.agentSessions[sess.AgentType] == nil {
			s.agentSessions[sess.AgentType] = make(map[string]bool)
		}
		s.agentSessions[sess.AgentType][sess.SessionID] = true
		if sess.SimulationID != "" {
			s.sessionSim[sess.SessionID] = sess.SimulationID
			if s.simSessions[sess.SimulationID] == nil {
				s.simSessions[sess.SimulationID] = make(map[string]bool)
			}
			s.simSessions[sess.SimulationID][sess.SessionID] = true
		}
	}
	return nil
}

func (s *InMemorySessionService) FindAgentType(ctx context.Context, sessionID string) (string, bool, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	at, ok := s.agentTypes[sessionID]
	return at, ok, nil
}

func (s *InMemorySessionService) ActiveAgentTypes(ctx context.Context) ([]string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var types []string
	for agentType, sessions := range s.agentSessions {
		if len(sessions) > 0 {
			types = append(types, agentType)
		}
	}
	return types, nil
}

func (s *InMemorySessionService) UntrackSession(ctx context.Context, sessionID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if agentType, ok := s.agentTypes[sessionID]; ok {
		delete(s.agentSessions[agentType], sessionID)
		if len(s.agentSessions[agentType]) == 0 {
			delete(s.agentSessions, agentType)
		}
	}
	delete(s.agentTypes, sessionID)
	// Clean up simulation mappings
	if simID, ok := s.sessionSim[sessionID]; ok {
		delete(s.simSessions[simID], sessionID)
		if len(s.simSessions[simID]) == 0 {
			delete(s.simSessions, simID)
		}
		delete(s.sessionSim, sessionID)
	}
	return nil
}

func (s *InMemorySessionService) ListSessions(ctx context.Context) ([]string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sessions := make([]string, 0, len(s.agentTypes))
	for sid := range s.agentTypes {
		sessions = append(sessions, sid)
	}
	return sessions, nil
}

func (s *InMemorySessionService) FindSimulation(ctx context.Context, sessionID string) (string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.sessionSim[sessionID], nil
}

func (s *InMemorySessionService) ListSimulations(ctx context.Context) ([]string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sims := make([]string, 0, len(s.simSessions))
	for simID := range s.simSessions {
		sims = append(sims, simID)
	}
	return sims, nil
}

func (s *InMemorySessionService) Flush(ctx context.Context) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	count := len(s.agentTypes)
	s.agentTypes = make(map[string]string)
	s.agentSessions = make(map[string]map[string]bool)
	s.entityToSess = make(map[ecs.Entity]string)
	s.sessToEntity = make(map[string]ecs.Entity)
	s.sessionSim = make(map[string]string)
	s.simSessions = make(map[string]map[string]bool)
	return count, nil
}

// Reap is a no-op for in-memory sessions since there is no TTL-based expiry.
func (s *InMemorySessionService) Reap(ctx context.Context) (int, error) {
	return 0, nil
}
