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

import * as THREE from 'three';
import { SSAOPass } from 'three/examples/jsm/postprocessing/SSAOPass.js';
import { LUTCubeLoader } from 'three/examples/jsm/loaders/LUTCubeLoader.js';
import { Pane } from 'tweakpane';
import { Context } from '../context';
import { baseFog, lightOffset } from '../config';
import * as SceneModule from '../scene/scene';
import { PerfMonitor } from './perf-monitor';
import { isDebugRaceRunning } from '../../debug-race';

function readRootCssNumber(cssVar: string, fallback: number): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}

export interface TweakpaneDebugApi {
  splines: THREE.CatmullRomCurve3[];
  debugRoute: (spline: THREE.CatmullRomCurve3) => void;
  debugStartRunners: (spline: THREE.CatmullRomCurve3) => void;
  debugSetRaceComplete: () => void;
  debugClearAllRoutes: () => void;
  debugAddInfoIcons: () => void;
  debugToggleError: () => void;
  debugStartCameraIntro: () => void;
  debugShowOldRoute: () => void;
  //debugStartOutro:        () => void;
  debugConfetti: () => void;
  debugCameraTopView: () => void;
  debugCameraMidView: () => void;
  debugCameraCloseView: () => void;
  debugCameraA: () => void;
  debugCameraB: () => void;
  debugCameraTopRoute: () => void;
  debugStartZone: () => void;
}

// debug panel - delete later
export function initTweakpane(
  ctx: Context,
  debugApi?: TweakpaneDebugApi,
  perfMonitor?: PerfMonitor,
  getRunnerCount?: () => number,
  getFollowActive?: () => boolean,
): void {
  ctx.tweakpane = new Pane({ title: 'Look dev', expanded: false });
  const pane: any = ctx.tweakpane;

  ctx.tpStyleEl = document.createElement('style');
  ctx.tpStyleEl.textContent =
    '.tp-dfwv { top: 16px !important; left: 16px !important; right: auto !important; z-index: 9999 !important; }';
  document.head.appendChild(ctx.tpStyleEl);

  // ── PERFORMANCE ──────────────────────────────────────────
  if (perfMonitor) {
    const fPerf = pane.addFolder({ title: 'Performance', expanded: false });

    const perfParams = {
      get fps() {
        return perfMonitor!.fps;
      },
      get frameMs() {
        return perfMonitor!.frameTimeMs;
      },
      get drawCalls() {
        return perfMonitor!.drawCalls;
      },
      get triangles() {
        return perfMonitor!.triangles;
      },
      get textures() {
        return perfMonitor!.textures;
      },
      get geometries() {
        return perfMonitor!.geometries;
      },
      get runners() {
        return getRunnerCount ? getRunnerCount() : 0;
      },
    };

    fPerf.addBinding(perfParams, 'fps', {
      readonly: true,
      label: 'FPS',
      format: (v: number) => v.toFixed(1),
    });
    fPerf.addBinding(perfParams, 'frameMs', {
      readonly: true,
      label: 'Frame (ms)',
      format: (v: number) => v.toFixed(2),
    });
    fPerf.addBinding(perfParams, 'drawCalls', {
      readonly: true,
      label: 'Draw Calls',
      format: (v: number) => Math.round(v).toString(),
    });
    fPerf.addBinding(perfParams, 'triangles', {
      readonly: true,
      label: 'Triangles',
      format: (v: number) => Math.round(v).toLocaleString(),
    });
    fPerf.addBinding(perfParams, 'textures', {
      readonly: true,
      label: 'Textures',
      format: (v: number) => Math.round(v).toString(),
    });
    fPerf.addBinding(perfParams, 'geometries', {
      readonly: true,
      label: 'Geometries',
      format: (v: number) => Math.round(v).toString(),
    });
    fPerf.addBinding(perfParams, 'runners', {
      readonly: true,
      label: 'Runners',
      format: (v: number) => Math.round(v).toString(),
    });

    const captureParams = { label: 'baseline' };
    fPerf.addBinding(captureParams, 'label', { label: 'Label' });
    fPerf.addButton({ title: 'Capture (15s)' }).on('click', () => {
      if (perfMonitor!.isSampling) return;
      const runnerCount = getRunnerCount ? getRunnerCount() : 0;
      const camera = getFollowActive?.() ? 'follow-leader' : 'static';
      const source = isDebugRaceRunning() ? 'debug-race' : 'backend';
      perfMonitor!.startSample(15000, captureParams.label, runnerCount, camera, source);
    });
  }

  // ── UI ───────────────────────────────────────────────────
  const fUi = pane.addFolder({ title: 'UI', expanded: false });
  const uiScale = {
    value:
      parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--scale').trim()) ||
      1,
  };
  fUi
    .addBinding(uiScale, 'value', { min: 0, max: 10, step: 0.01, label: 'Scale (--scale)' })
    .on('change', ({ value }: { value: number }) => {
      document.documentElement.style.setProperty('--scale', String(value));
    });

  const uiContainerWidths = {
    agentScreen: readRootCssNumber('--agent-screen-container-width', 640),
    simulationPanel: readRootCssNumber('--simulation-panel-container-width', 493),
    filterMenu: readRootCssNumber('--filter-menu-container-width', 68),
    hud: readRootCssNumber('--hud-container-width', 760),
    viewportLookdev: readRootCssNumber('--viewport-lookdev-container-width', 640),
  };
  const uiContainerWidthRows: {
    key: keyof typeof uiContainerWidths;
    cssVar: string;
    label: string;
  }[] = [
    {
      key: 'agentScreen',
      cssVar: '--agent-screen-container-width',
      label: 'Agent screen (--agent-screen-container-width)',
    },
    {
      key: 'simulationPanel',
      cssVar: '--simulation-panel-container-width',
      label: 'Simulation panel (--simulation-panel-container-width)',
    },
    {
      key: 'filterMenu',
      cssVar: '--filter-menu-container-width',
      label: 'Filter menu (--filter-menu-container-width)',
    },
    { key: 'hud', cssVar: '--hud-container-width', label: 'HUD (--hud-container-width)' },
    {
      key: 'viewportLookdev',
      cssVar: '--viewport-lookdev-container-width',
      label: 'Viewport lookdev (--viewport-lookdev-container-width)',
    },
  ];
  for (const { key, cssVar, label } of uiContainerWidthRows) {
    fUi
      .addBinding(uiContainerWidths, key, { min: 0, max: 6336, step: 1, label })
      .on('change', ({ value }: { value: number }) => {
        document.documentElement.style.setProperty(cssVar, String(value));
      });
  }

  // ── CAMERA ───────────────────────────────────────────────
  const fCamera = pane.addFolder({ title: 'Camera', expanded: false });
  const panSpeed = { value: SceneModule.PAN_UNITS_PER_SECOND };
  fCamera
    .addBinding(panSpeed, 'value', { min: 100, max: 10000, step: 100, label: 'Transition Speed' })
    .on('change', ({ value }: { value: number }) => {
      SceneModule.setPanSpeed(value);
    });

  // ── POST PROCESSING ───────────────────────────────────────
  const fPP = pane.addFolder({ title: 'Post Processing', expanded: false });

  const fLUT = fPP.addFolder({ title: 'LUT', expanded: false });
  const lutEnabledBinding = fLUT.addBinding(ctx.lutPass, 'enabled', { label: 'Enabled' });
  fLUT.addBinding(ctx.lutPass, 'intensity', { min: 0, max: 1, label: 'Intensity' });
  const LUT_PARAMS = { lut: 'Lut_v05.lut.CUBE' };
  fLUT
    .addBinding(LUT_PARAMS, 'lut', {
      label: 'Preset',
      options: [
        { text: 'None', value: '' },
        { text: 'Load from disk...', value: '__custom__' },
        { text: 'Lut v05', value: 'Lut_v05.lut.CUBE' },
        { text: 'Lut_Brighter', value: 'Lut_Brighter.CUBE' },
        { text: 'Lut_Brighter_LowSaturation', value: 'Lut_Brighter_LowSaturation.CUBE' },
        { text: 'Lut_LowSaturation', value: 'Lut_LowSaturation.CUBE' },
      ],
    })
    .on('change', ({ value }: { value: any }) => {
      if (!value) {
        ctx.lutPass.enabled = false;
        lutEnabledBinding.refresh();
        return;
      }
      if (value === '__custom__') {
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.cube';
        fileInput.onchange = (e: Event) => {
          const file = (e.target as HTMLInputElement).files?.[0];
          if (!file) return;
          const reader = new FileReader();
          reader.onload = (ev) => {
            const result = (new LUTCubeLoader() as any).parse(ev.target!.result);
            ctx.lutPass.lut = result.texture3D;
            ctx.lutPass.enabled = true;
            lutEnabledBinding.refresh();
          };
          reader.readAsText(file);
        };
        fileInput.click();
        return;
      }
      new LUTCubeLoader().loadAsync(`/assets/luts/${value}`).then((result: any) => {
        if (!ctx.lutPass) return;
        ctx.lutPass.lut = result.texture3D;
        ctx.lutPass.enabled = true;
        lutEnabledBinding.refresh();
      });
    });
}
