/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * You may not use this file except in compliance with the License.
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

import { Injectable } from '@angular/core';
import { DEMO_CONFIG } from '../../../../../demo-config';
import {
  parseAgentGatewayMsgNdjsonInterFrameReplayMeta,
  parseAgentGatewayMsgNdjsonToInboundRecords,
  replayAgentGatewayMsgNdjsonText,
} from '../../../../../../../agent-gateway-message-dump';
import { agentGateway } from '../../../../../agent-gateway-updates';
import type { DemoService } from '../../../../DemoOverlay/demo.service';

/** Minimal host surface for NDJSON replay (avoids circular imports with AgentScreen). */
export interface AgentCachedGatewayReplayHost {
  demoService: DemoService;
  currentDemoCachedRunCount: number;
  cachedMessageTimeScale: number;
  onCachedReplayComplete(): void;
}

@Injectable()
export class AgentCachedGatewayReplayService {
  private cachedReplayStop?: () => void;
  private cachedCountdownTimer?: ReturnType<typeof setTimeout>;

  /**
   * Loads the active demo’s cached NDJSON stream and replays it into {@link agentGateway.handleMessage}.
   */
  async run(host: AgentCachedGatewayReplayHost): Promise<void> {
    this.stop();

    const activeDemoKey = host.demoService.activeDemo();
    const activeDemo = DEMO_CONFIG[activeDemoKey] as {
      agent?: string;
      recordingConfig?: { cachedMessageStreams: string[] };
    };

    const url =
      activeDemo.recordingConfig?.cachedMessageStreams[host.currentDemoCachedRunCount];
    if (url == null || url === '') {
      console.error('[AgentScreen] cached gateway replay: no stream URL for this run index');
      return;
    }

    let text: string;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(`${res.status} ${res.statusText}`);
      }
      text = await res.text();
      const ct = res.headers.get('content-type') ?? '';
      if (ct.includes('text/html') || text.trimStart().startsWith('<!')) {
        throw new Error(
          'Got HTML instead of NDJSON (SPA fallback). Ensure the file exists under public/.',
        );
      }
    } catch (e) {
      console.error('[AgentScreen] cached gateway dump fetch failed', url, e);
      return;
    }

    agentGateway.setReplayPrimaryAgentTypeHint(activeDemo.agent as string);
    agentGateway.beginNdjsonReplay();

    this.scheduleCachedCountdown(host, text);

    this.cachedReplayStop = replayAgentGatewayMsgNdjsonText(
      (e) => agentGateway.handleMessage(e),
      text,
      {
        encodeSemanticLine: (rec) => agentGateway.encodeInboundRecordForReplay(rec),
        intervalMs: 2000,
        useRecordedPerformanceTimestamps: true,
        getTimingScale: () => host.cachedMessageTimeScale,
        onComplete: () => {
          agentGateway.endNdjsonReplay();
          host.onCachedReplayComplete();
        },
      },
    );
  }

  /** Stops timed replay (same as the prior `stop2` callback). */
  stop(): void {
    this.clearCachedCountdownTimer();
    this.cachedReplayStop?.();
    this.cachedReplayStop = undefined;
    agentGateway.endNdjsonReplay();
  }

  private scheduleCachedCountdown(host: AgentCachedGatewayReplayHost, ndjsonText: string): void {
    this.clearCachedCountdownTimer();

    const records = parseAgentGatewayMsgNdjsonToInboundRecords(ndjsonText);
    let startIndex = records.findIndex(
      (r) => r.event === 'tool_end' && r.data['tool_name'] === 'process_tick',
    );
    if (startIndex < 0) {
      startIndex = records.findIndex(
        (r) => r.event === 'tool_end' && r.data['tool_name'] === 'fire_start_gun',
      );
    }
    if (startIndex <= 0) return;

    const meta = parseAgentGatewayMsgNdjsonInterFrameReplayMeta(ndjsonText, 2000);
    if (meta.delays.length < startIndex) return;

    const scale =
      host.cachedMessageTimeScale > 0 && Number.isFinite(host.cachedMessageTimeScale)
        ? host.cachedMessageTimeScale
        : 1;
    let cumulativeMs = 0;
    for (let i = 0; i < startIndex; i++) {
      const baseGap = meta.delays[i];
      const apply = meta.interFrameApplyTimingScale[i];
      cumulativeMs += apply ? baseGap / scale : baseGap;
    }

    const COUNTDOWN_LEAD_MS = 3000;
    const triggerInMs = Math.max(0, cumulativeMs - COUNTDOWN_LEAD_MS);
    this.cachedCountdownTimer = setTimeout(() => {
      this.cachedCountdownTimer = undefined;
      window.dispatchEvent(new Event('countdown:autoStart'));
    }, triggerInMs);
  }

  private clearCachedCountdownTimer(): void {
    if (this.cachedCountdownTimer !== undefined) {
      clearTimeout(this.cachedCountdownTimer);
      this.cachedCountdownTimer = undefined;
    }
  }
}
