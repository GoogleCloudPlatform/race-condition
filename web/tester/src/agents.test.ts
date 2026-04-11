/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchAgentTypes, createOrchestratedSession } from './agents'

describe('agents API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  describe('fetchAgentTypes', () => {
    it('fetches agent types from the gateway', async () => {
      const mockCatalog = {
        'runner_autopilot': { name: 'Runner Autopilot', description: 'Test runner autopilot' }
      }
      
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockCatalog
      } as Response)

      const result = await fetchAgentTypes('http://localhost:8101/ws')
      
      expect(fetch).toHaveBeenCalledWith('http://localhost:8101/api/v1/agent-types')
      expect(result).toEqual(mockCatalog)
    })

    it('throws error on failure', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        statusText: 'Internal Server Error'
      } as Response)

      await expect(fetchAgentTypes('http://localhost:8101/ws')).rejects.toThrow('Failed to fetch agent types: Internal Server Error')
    })
  })

  describe('createOrchestratedSession', () => {
    it('sends POST to create a session', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ sessionId: 'session-123' })
      } as Response)

      const result = await createOrchestratedSession('http://localhost:8101/ws', 'runner_autopilot', 'user-1')
      
      expect(fetch).toHaveBeenCalledWith('http://localhost:8101/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agentType: 'runner_autopilot', userId: 'user-1' })
      })
      expect(result).toBe('session-123')
    })
  })
})
