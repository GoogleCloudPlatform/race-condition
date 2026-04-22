/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 */

import { Injectable } from '@angular/core';
import { DEMO_CONFIG, PRECONFIGURED_ROUTES } from '../../../../../demo-config';
import type { ChatAgent } from '../../../../../types';
import {
  SECURE_AGENT_PROMPT,
  UNSECURE_AGENT_PROMPT,
} from '../../../../../../constants';
import { simulationState } from '../../../../../simulation-state';
import type { AgentScreenComponent } from '../agent-screen.component';

@Injectable()
export class AgentDemoSessionService {
  async runDemoLifecycle(host: AgentScreenComponent): Promise<void> {
    void host.demoService.cachedMessagesToggle();

    host.stopCachedDataStream();

    host.onSimFinished();
    host.resetSimulationStatistics();

    host.removeAllActiveAgents();

    host.gateway.removeCurrentSimulationId();

    host.showSimPanel = false;
    host.currentDemoCachedRunCount = 0;

    window.dispatchEvent(new CustomEvent('sim:fixError'));
    window.dispatchEvent(new CustomEvent('sim:removeRunnerThoughts'));

    if (host.errorMessageInterval) clearInterval(host.errorMessageInterval);

    host.isSecuringAgent = false;
    host.gateway.resetDemoChatPipelineState();
    host.chatDisplay.clearForDemoReset();
    host.chatMessages = [];
    host.cdr.markForCheck();

    window.dispatchEvent(new CustomEvent('hud:removeAllPaths'));

    host.resetCounter = host.demoService.reset();

    window.dispatchEvent(new CustomEvent('sim:reset'));

    if (host.agents['tick_agent']) host.agents['tick_agent'] = null;

    const activeDemoKey = host.demoService.activeDemo();
    const activeDemo = DEMO_CONFIG[activeDemoKey];

    host.isExpanded = activeDemoKey !== 'Sandbox';
    host.tabBtnWide = false;
    host.activeTab = 'agent';

    host.isSecurityDemo = activeDemo.isSecurityDemo || false;
    host.isBuildAgentsDemo = activeDemo.isBuildAgentsDemo || false;
    host.isIntentToInfrastructureDemo = activeDemo.isIntentToInfrastructureDemo || false;
    host.activeDemoHasRecordingConfig = !!activeDemo.recordingConfig;
    if (!host.activeDemoHasRecordingConfig) {
      host.runCachedMessages = false;
      host.stopCachedDataStream();
    }

    host.cachedMessageTimeScale = activeDemo.recordingConfig
      ? host.clampSnapCachedMessageTimeScale(activeDemo.recordingConfig.timeScale ?? 1)
      : 1;

    host.filterSettings.showLoadSkills = host.isBuildAgentsDemo;
    host.gateway.setFilterSettings({ showLoadSkills: host.filterSettings.showLoadSkills });

    await host.onInitAgent(activeDemo.agent);

    if (host.demoService.activeDemo() !== activeDemoKey) return;

    Object.entries(host.agents).forEach(([agentType, guid]) => {
      if (activeDemo.agent !== agentType && guid) {
        host.gateway.removeAgent(guid);
        host.agents[agentType] = null;
      }
    });

    host.isAgentWorking = false;

    host.currentAgent = {
      agentType: activeDemo.agent as ChatAgent,
      sessionId: host.agents[activeDemo.agent] as string,
    };

    if (activeDemoKey === '5b') {
      window.dispatchEvent(new CustomEvent('sim:giveRunnerThoughts'));
      host.applyDemoSessionCloudAssistShell(true);
      host.scheduleSegmentThumbsLayout();
    }

    if (activeDemoKey === '7b') {
      host.applyDemoSessionSecureShell(true);
      host.scheduleSegmentThumbsLayout();

      if (!host.runCachedMessages) {
        host.isSecuringAgent = true;
        host.gateway.sendBroadcast(
          SECURE_AGENT_PROMPT,
          [host.agents[host.currentAgent!.agentType] as string],
          true,
        );
      }
    } else if (activeDemoKey === '7a') {
      host.applyDemoSessionSecureShell(false);
      host.scheduleSegmentThumbsLayout();

      if (!host.runCachedMessages) {
        host.isSecuringAgent = true;
        host.gateway.sendBroadcast(
          UNSECURE_AGENT_PROMPT,
          [host.agents[host.currentAgent!.agentType] as string],
          true,
        );
      }
    }

    if (activeDemoKey !== 'Sandbox' && activeDemo.placeholderRoutes) {
      const routeJson = PRECONFIGURED_ROUTES[activeDemo.placeholderRoutes] as {
        route_data?: unknown;
      };
      const geojson = routeJson.route_data ?? routeJson;

      window.dispatchEvent(new CustomEvent('gateway:routeGeojson', { detail: { geojson } }));
    }

    if (activeDemo.placeholderAgentMessage) {
      const message = {
        ...activeDemo.placeholderAgentMessage,
        guid: host.currentAgent!.sessionId,
        speaker: host.currentAgent!.agentType as string,
      };

      host.chatMessages = [message];
      host.chatDisplay.processMessageForDisplay(host, message);
    }

    if (activeDemo.promptPlaceholder) {
      if (host.chatTextAreaRef) {
        host.chatTextAreaRef.nativeElement.value = activeDemo.promptPlaceholder;
      }
      host.chatInput = activeDemo.promptPlaceholder;
      if (host.chatTextAreaRef) {
        host.autoResize();
      }
    } else {
      if (host.chatTextAreaRef) {
        host.chatTextAreaRef.nativeElement.value = '';
      }
      host.chatInput = '';
      if (host.chatTextAreaRef) {
        host.autoResize();
      }
    }

    simulationState.deactivate();
    host.cdr.markForCheck();
  }
}
