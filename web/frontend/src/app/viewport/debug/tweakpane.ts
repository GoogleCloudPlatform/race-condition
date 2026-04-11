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
import { PerfMonitor } from './perf-monitor';
import { isDebugRaceRunning } from '../../debug-race';

export interface TweakpaneDebugApi {
  splines:           THREE.CatmullRomCurve3[];
  debugRoute:        (spline: THREE.CatmullRomCurve3) => void;
  debugStartRunners: (spline: THREE.CatmullRomCurve3) => void;
  debugSetRaceComplete:   () => void;
  debugClearAllRoutes:    () => void;
  debugAddInfoIcons:      () => void;
  debugToggleError:       () => void;
  debugStartCameraIntro:  () => void;
  debugShowOldRoute:      () => void;
  //debugStartOutro:        () => void;
  debugConfetti:          () => void;
  debugCameraTopView:     () => void;
  debugCameraMidView:     () => void;
  debugCameraCloseView:   () => void;
  debugCameraA:           () => void;
  debugCameraB:           () => void;
  debugCameraTopRoute:    () => void;
  debugStartZone:         () => void;
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
  ctx.tpStyleEl.textContent = '.tp-dfwv { top: 16px !important; left: 16px !important; right: auto !important; z-index: 9999 !important; }';
  document.head.appendChild(ctx.tpStyleEl);

  // ── PERFORMANCE ──────────────────────────────────────────
  if (perfMonitor) {
    const fPerf = pane.addFolder({ title: 'Performance', expanded: true });

    const perfParams = {
      get fps() { return perfMonitor!.fps; },
      get frameMs() { return perfMonitor!.frameTimeMs; },
      get drawCalls() { return perfMonitor!.drawCalls; },
      get triangles() { return perfMonitor!.triangles; },
      get textures() { return perfMonitor!.textures; },
      get geometries() { return perfMonitor!.geometries; },
      get runners() { return getRunnerCount ? getRunnerCount() : 0; },
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

  // ── CAMERA ───────────────────────────────────────────────
  const fCamera = pane.addFolder({ title: 'Camera', expanded: false });
  fCamera.addBinding(ctx.camera, 'fov', { min: 10, max: 120, label: 'FOV' })
    .on('change', () => { ctx.camera.updateProjectionMatrix(); });
  fCamera.addBinding(ctx.controls, 'autoRotate', { label: 'Auto Rotate' });

  // ── LIGHTING ─────────────────────────────────────────────
  const fLight = pane.addFolder({ title: 'Lighting', expanded: false });
  fLight.addBinding(ctx.dirLight, 'intensity', { min: 0, max: 5, label: 'Dir Intensity' });
  fLight.addBinding(ctx.dirLight.shadow, 'intensity', { min: 0, max: 1, label: 'Shadow Intensity' });
  fLight.addBinding(ctx.ambient, 'intensity', { min: 0, max: 3, label: 'Ambient Intensity' });
  const dirLightColor = { color: '#' + ctx.dirLight.color.getHexString() };
  fLight.addBinding(dirLightColor, 'color', { label: 'Dir Light Color' })
    .on('change', ({ value }: { value: any }) => { ctx.dirLight.color.set(value); });
  const ambientColor = { color: '#' + ctx.ambient.color.getHexString() };
  fLight.addBinding(ambientColor, 'color', { label: 'Ambient Color' })
    .on('change', ({ value }: { value: any }) => { ctx.ambient.color.set(value); });
  fLight.addBinding(lightOffset, 'x', { min: -10000, max: 10000, label: 'Light Offset X' });
  fLight.addBinding(lightOffset, 'y', { min: 0,      max: 10000, label: 'Light Offset Y' });
  fLight.addBinding(lightOffset, 'z', { min: -10000, max: 10000, label: 'Light Offset Z' });

  // ── POST PROCESSING ───────────────────────────────────────
  const fPP = pane.addFolder({ title: 'Post Processing', expanded: false });

  const fSSAO = fPP.addFolder({ title: 'SSAO', expanded: false });
  fSSAO.addBinding(ctx.ssaoPass, 'kernelRadius', { min: 0, max: 1000,  label: 'Kernel Radius' });
  fSSAO.addBinding(ctx.ssaoPass, 'minDistance',  { min: 0, max: 1000, step: 1, label: 'Min Dist' });
  fSSAO.addBinding(ctx.ssaoPass, 'maxDistance',  { min: 0, max: 10000, label: 'Max Dist' });
  const SSAO_PARAMS = { debugMode: false };
  fSSAO.addBinding(SSAO_PARAMS, 'debugMode', { label: 'Debug SSAO' })
    .on('change', ({ value }: { value: any }) => {
      ctx.ssaoPass.output          = value ? SSAOPass.OUTPUT.SSAO : SSAOPass.OUTPUT.Default;
      ctx.bloomPass.enabled        = !value;
      ctx.depthOutlinePass.enabled = !value;
    });
  fSSAO.addBinding(ctx.ssaoPass, 'enabled', { label: 'Enabled' });

  const fBloom = fPP.addFolder({ title: 'Bloom', expanded: false });
  fBloom.addBinding(ctx.bloomPass, 'strength',  { min: 0, max: 3, label: 'Strength' });
  fBloom.addBinding(ctx.bloomPass, 'radius',    { min: 0, max: 1, label: 'Radius' });
  fBloom.addBinding(ctx.bloomPass, 'threshold', { min: 0, max: 1, label: 'Threshold' });
  fBloom.addBinding(ctx.bloomPass, 'enabled',   { label: 'Enabled' });

  const fOutline = fPP.addFolder({ title: 'Depth Outline', expanded: false });
  fOutline.addBinding(ctx.depthOutlinePass.uniforms['threshold'], 'value', { min: 0.01, max: 1.0, label: 'Threshold' });
  const outlineColorHigh = { color: '#' + (ctx.depthOutlinePass.uniforms['outlineColor'].value as THREE.Color).getHexString() };
  fOutline.addBinding(outlineColorHigh, 'color', { label: 'Color High' })
    .on('change', ({ value }: { value: any }) => { ctx.depthOutlinePass.uniforms['outlineColor'].value.set(value); });
  const outlineColorLow = { color: '#' + (ctx.depthOutlinePass.uniforms['outlineColorLow'].value as THREE.Color).getHexString() };
  fOutline.addBinding(outlineColorLow, 'color', { label: 'Color Low' })
    .on('change', ({ value }: { value: any }) => { ctx.depthOutlinePass.uniforms['outlineColorLow'].value.set(value); });
  fOutline.addBinding(ctx.depthOutlinePass.uniforms['heightFadeMin'], 'value', { min: 0, max: 1000, label: 'Fade Min' });
  fOutline.addBinding(ctx.depthOutlinePass.uniforms['heightFadeMax'], 'value', { min: 0, max: 1000, label: 'Fade Max' });
  fOutline.addBinding(ctx.depthOutlinePass, 'enabled', { label: 'Enabled' });

  const fLUT = fPP.addFolder({ title: 'LUT', expanded: false });
  const lutEnabledBinding = fLUT.addBinding(ctx.lutPass, 'enabled', { label: 'Enabled' });
  fLUT.addBinding(ctx.lutPass, 'intensity', { min: 0, max: 1, label: 'Intensity' });
  const LUT_PARAMS = { lut: 'Lut_v02.lut.CUBE' };
  fLUT.addBinding(LUT_PARAMS, 'lut', {
    label: 'Preset',
    options: [
      { text: 'None',              value: '' },
      { text: 'Load from disk...', value: '__custom__' },
      { text: 'Lut v05',           value: 'Lut_v05.lut.CUBE' },
      { text: 'Lut_Brighter',      value: 'Lut_Brighter.CUBE' },
      { text: 'Lut_Brighter_LowSaturation',  value: 'Lut_Brighter_LowSaturation.CUBE' },
      { text: 'Lut_LowSaturation',               value: 'Lut_LowSaturation.CUBE' },
    ],
  }).on('change', ({ value }: { value: any }) => {
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

  const fVignette = fPP.addFolder({ title: 'Vignette', expanded: false });
  fVignette.addBinding(ctx.vignettePass, 'enabled', { label: 'Enabled' });
  fVignette.addBinding(ctx.vignettePass.uniforms['offset'],   'value', { min: 0, max: 5, label: 'Offset' });
  fVignette.addBinding(ctx.vignettePass.uniforms['darkness'], 'value', { min: 0, max: 2, label: 'Darkness' });

  // ── COLORS ────────────────────────────────────────────────
  const fColors = pane.addFolder({ title: 'Colors', expanded: false });
  const fog = ctx.scene.fog as THREE.Fog;

  const fSky = fColors.addFolder({ title: 'Sky', expanded: false });
  const skyColorBottom = { color: '#' + ctx.skyMaterial.uniforms['colorBottom'].value.getHexString() };
  fSky.addBinding(skyColorBottom, 'color', { label: 'Color Bottom' })
    .on('change', ({ value }: { value: any }) => { ctx.skyMaterial.uniforms['colorBottom'].value.set(value); });
  const skyColorTop = { color: '#' + ctx.skyMaterial.uniforms['colorTop'].value.getHexString() };
  fSky.addBinding(skyColorTop, 'color', { label: 'Color Top' })
    .on('change', ({ value }: { value: any }) => { ctx.skyMaterial.uniforms['colorTop'].value.set(value); });
  const SKY_PARAMS = { scaleY: ctx.skyMesh.scale.y };
  fSky.addBinding(SKY_PARAMS, 'scaleY', { min: 0.1, max: 5, label: 'Scale Y' })
    .on('change', ({ value }: { value: any }) => { ctx.skyMesh.scale.y = value; });

  const fFog = fColors.addFolder({ title: 'Fog', expanded: false });
  fFog.addBinding(fog, 'near', { min: 0, max: 10000, label: 'Near' });
  fFog.addBinding(baseFog, 'far', { min: 0, max: 20000, label: 'Far' });
  const fogColor = { color: '#' + fog.color.getHexString() };
  fFog.addBinding(fogColor, 'color', { label: 'Fog Color' })
    .on('change', ({ value }: { value: any }) => {
      fog.color.set(value);
      (ctx.scene.background as THREE.Color).copy(fog.color);
    });

  const groundMat = ctx.ground.material as THREE.MeshStandardMaterial;
  const groundColor = { color: '#' + groundMat.color.getHexString() };
  fColors.addBinding(groundColor, 'color', { label: 'Ground Color' })
    .on('change', ({ value }: { value: any }) => { groundMat.color.set(value); });

  const fBuildings = fColors.addFolder({ title: 'Buildings', expanded: false });
  const buildingBaseColor = { color: '#' + ctx.heightFogMaterial.uniforms['baseColor'].value.getHexString() };
  fBuildings.addBinding(buildingBaseColor, 'color', { label: 'Base Color' })
    .on('change', ({ value }: { value: any }) => { ctx.heightFogMaterial.uniforms['baseColor'].value.set(value); });
  const buildingFogColor = { color: '#' + ctx.heightFogMaterial.uniforms['heightFogColor'].value.getHexString() };
  fBuildings.addBinding(buildingFogColor, 'color', { label: 'Height Fog Color' })
    .on('change', ({ value }: { value: any }) => { ctx.heightFogMaterial.uniforms['heightFogColor'].value.set(value); });
  fBuildings.addBinding(ctx.heightFogMaterial.uniforms['heightFogDensity'], 'value', { min: 0,     max: 1,    label: 'HFog Density' });
  fBuildings.addBinding(ctx.heightFogMaterial.uniforms['heightFogNear'],    'value', { min: -1000, max: 2000, label: 'HFog Near' });
  fBuildings.addBinding(ctx.heightFogMaterial.uniforms['heightFogFar'],     'value', { min: -1000, max: 2000, label: 'HFog Far' });
  const buildingEmissiveColor = { color: '#' + ctx.heightFogLightUpMaterial.uniforms['emissiveColor'].value.getHexString() };
  fBuildings.addBinding(buildingEmissiveColor, 'color', { label: 'Emissive Color' })
    .on('change', ({ value }: { value: any }) => { ctx.heightFogLightUpMaterial.uniforms['emissiveColor'].value.set(value); });
  fBuildings.addBinding(ctx.heightFogLightUpMaterial.uniforms['emissiveIntensity'], 'value', { min: 0, max: 3, label: 'Emissive Intensity' });

  const windowNames = ['Windows_1','Windows_2','Windows_3','Windows_4','Windows_5','Windows_6','Windows_7'];
  for (let i = 0; i < ctx.windowMaterialArray.length; i++) {
    const wm = ctx.windowMaterialArray[i];
    const fWin = fBuildings.addFolder({ title: windowNames[i], expanded: false });
    const wTop = { color: '#' + wm.uniforms['topColor'].value.getHexString() };
    fWin.addBinding(wTop, 'color', { label: 'Top Color' })
      .on('change', ({ value }: { value: any }) => { wm.uniforms['topColor'].value.set(value); });
    const wBot = { color: '#' + wm.uniforms['bottomColor'].value.getHexString() };
    fWin.addBinding(wBot, 'color', { label: 'Bottom Color' })
      .on('change', ({ value }: { value: any }) => { wm.uniforms['bottomColor'].value.set(value); });
    fWin.addBinding(wm.uniforms['heightFogNear'],    'value', { min: -1000, max: 2000, label: 'Fade Near' });
    fWin.addBinding(wm.uniforms['heightFogFar'],     'value', { min: -1000, max: 2000, label: 'Fade Far' });
    fWin.addBinding(wm.uniforms['heightFogDensity'], 'value', { min: 0, max: 1, label: 'Fade Density' });
    fWin.addBinding(wm.uniforms['normalFogDensity'], 'value', { min: 0, max: 1, label: 'Normal Fog Density' });
  }

  const fRoads = fColors.addFolder({ title: 'Roads', expanded: false });
  const roadColor = { color: '#' + (ctx.roadsMaterial.uniforms['color'].value as THREE.Color).getHexString() };
  fRoads.addBinding(roadColor, 'color', { label: 'Road Color' })
    .on('change', ({ value }: { value: any }) => { (ctx.roadsMaterial.uniforms['color'].value as THREE.Color).set(value); });
  const roadEmissiveColor = { color: '#' + (ctx.roadsMaterial.uniforms['emissive'].value as THREE.Color).getHexString() };
  fRoads.addBinding(roadEmissiveColor, 'color', { label: 'Traffic Emissive' })
    .on('change', ({ value }: { value: any }) => { (ctx.roadsMaterial.uniforms['emissive'].value as THREE.Color).set(value); });
  fRoads.addBinding(ctx.roadsMaterial.uniforms['emissiveIntensity'], 'value', { min: 0, max: 5, label: 'Traffic Emissive Intensity' });
  const maskColor2 = { color: '#' + (ctx.roadsMaterial.uniforms['maskColor2'].value as THREE.Color).getHexString() };
  fRoads.addBinding(maskColor2, 'color', { label: 'Traffic Jam Color' })
    .on('change', ({ value }: { value: any }) => { (ctx.roadsMaterial.uniforms['maskColor2'].value as THREE.Color).set(value); });
  fRoads.addBinding(ctx.roadsMaterial.uniforms['maskColor2Intensity'], 'value', { min: 0, max: 10, label: 'Traffic Jam Intensity' });
  fRoads.addBinding(ctx.roadsMaterial.uniforms['worldUvScale'], 'value', { min: 0, max: 0.001, step: 0.000001, label: 'World UV Scale' });
  const worldUvOffset = { x: 0, y: 0 };
  fRoads.addBinding(worldUvOffset, 'x', { min: -1, max: 1, step: 0.001, label: 'World UV Offset X' })
    .on('change', ({ value }: { value: number }) => { ctx.roadsMaterial.uniforms['worldUvOffset'].value.x = value; });
  fRoads.addBinding(worldUvOffset, 'y', { min: -1, max: 1, step: 0.001, label: 'World UV Offset Y' })
    .on('change', ({ value }: { value: number }) => { ctx.roadsMaterial.uniforms['worldUvOffset'].value.y = value; });
  const glowColor = { color: '#' + ctx.roadsGlowMaterial.emissive.getHexString() };
  fRoads.addBinding(glowColor, 'color', { label: 'Glow Color' })
    .on('change', ({ value }: { value: any }) => { ctx.roadsGlowMaterial.emissive.set(value); });
  fRoads.addBinding(ctx.roadsGlowMaterial, 'emissiveIntensity', { min: 0, max: 5, label: 'Glow Intensity' });
  const edgeFadeColor = { color: '#' + (ctx.roadsMaterial.uniforms['edgeFadeColor'].value as THREE.Color).getHexString() };
  fRoads.addBinding(edgeFadeColor, 'color', { label: 'Edge Fade Color' })
    .on('change', ({ value }: { value: any }) => { (ctx.roadsMaterial.uniforms['edgeFadeColor'].value as THREE.Color).set(value); });

  const foliageColor = { color: '#' + ctx.foilageMaterial.color.getHexString() };
  fColors.addBinding(foliageColor, 'color', { label: 'Foliage Color' })
    .on('change', ({ value }: { value: any }) => { ctx.foilageMaterial.color.set(value); });
  const mountainColor = { color: '#' + ctx.mountainMaterial.color.getHexString() };
  fColors.addBinding(mountainColor, 'color', { label: 'Mountain Color' })
    .on('change', ({ value }: { value: any }) => { ctx.mountainMaterial.color.set(value); });
  if (ctx.particleMaterial) {
    const particleColor = { color: '#' + (ctx.particleMaterial.uniforms['color'].value as THREE.Color).getHexString() };
    fColors.addBinding(particleColor, 'color', { label: 'Ambient Particle Color' })
      .on('change', ({ value }: { value: any }) => { (ctx.particleMaterial!.uniforms['color'].value as THREE.Color).set(value); });
  }

  if (debugApi) {
    const fDebug = pane.addFolder({ title: 'Debug', expanded: false });
    /*const labels = ['#1', '#2', '#3'];
    debugApi.splines.forEach((spline, i) => {
      fDebug.addButton({ title: `Plan Route – ${labels[i]}` })
        .on('click', () => debugApi.debugRoute(spline));
      fDebug.addButton({ title: `Start Race – ${labels[i]}` })
        .on('click', () => debugApi.debugStartRunners(spline));
    });*/
    fDebug.addButton({ title: 'Show Old Route' })
      .on('click', () => debugApi.debugShowOldRoute());
    fDebug.addButton({ title: 'Race Complete' })
      .on('click', () => debugApi.debugSetRaceComplete());
    fDebug.addButton({ title: 'Clear All Routes' })
      .on('click', () => debugApi.debugClearAllRoutes());
    fDebug.addButton({ title: 'Add Info Icons' })
      .on('click', () => debugApi.debugAddInfoIcons());
    fDebug.addButton({ title: 'Toggle Error' })
      .on('click', () => debugApi.debugToggleError());
    fDebug.addButton({ title: 'Intro' })
      .on('click', () => debugApi.debugStartCameraIntro());
    //fDebug.addButton({ title: 'Outro' })
    //  .on('click', () => debugApi.debugStartOutro());
    fDebug.addButton({ title: 'Toggle Confetti' })
      .on('click', () => debugApi.debugConfetti());
    fDebug.addButton({ title: 'Camera Top View' })
      .on('click', () => debugApi.debugCameraTopView());
    fDebug.addButton({ title: 'Camera Mid View' })
      .on('click', () => debugApi.debugCameraMidView());
    fDebug.addButton({ title: 'Camera Close View' })
      .on('click', () => debugApi.debugCameraCloseView());
    fDebug.addButton({ title: 'Camera A' })
      .on('click', () => debugApi.debugCameraA());
    fDebug.addButton({ title: 'Camera B' })
      .on('click', () => debugApi.debugCameraB());
    fDebug.addButton({ title: 'Camera Top Route' })
      .on('click', () => debugApi.debugCameraTopRoute());
    fDebug.addButton({ title: 'Start Zone' })
      .on('click', () => debugApi.debugStartZone());
  }
}
