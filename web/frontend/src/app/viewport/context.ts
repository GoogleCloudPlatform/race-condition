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
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { SSAOPass } from 'three/examples/jsm/postprocessing/SSAOPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { LUTPass } from 'three/examples/jsm/postprocessing/LUTPass.js';

/**
 * Shared mutable state passed to every sub-module function.
 * The Angular component creates one instance and holds it for its lifetime.
 */
export class Context {
  // ── Core THREE ────────────────────────────────────────────────────────────
  renderer!: THREE.WebGLRenderer;
  scene!: THREE.Scene;
  camera!: THREE.PerspectiveCamera;
  controls!: OrbitControls;
  timer = new THREE.Timer();
  textureLoader = new THREE.TextureLoader();
  animFrameId!: number;

  // ── Camera follow ─────────────────────────────────────────────────────────
  cameraFollow: {
    mesh: THREE.Object3D;
    offset: THREE.Vector3;
    autoRotate: boolean;
    damping?: number;
    /** Optional delayed lerp from autoRotate orbit position to a fixed offset. */
    offsetTransition?: {
      delay: number; // seconds before the lerp begins
      duration: number; // lerp duration in seconds
      elapsed: number; // total ticked time since followMesh was called
      toOffset: THREE.Vector3; // desired final offset
      fromOffset: THREE.Vector3; // captured from live camera position when delay fires
      started: boolean; // whether the capture + lerp phase has begun
      releaseDelay: number; // seconds after lerp completes before autoRotate resumes (0 = never)
    };
  } | null = null;
  /** Meshes to raycast against for camera occlusion avoidance. */
  occlusionMeshes: THREE.Mesh[] = [];
  /** True while the user is dragging to pivot the camera. */
  userDragging = false;

  // ── Window light-up (intro effect) ───────────────────────────────────────
  /** Every Windows_Emission mesh with its final assigned material and cached world Z. */
  windowMeshes: Array<{
    mesh: THREE.Mesh;
    originalMaterial: THREE.Material;
    worldZ: number;
    litTarget: number; // 0 = dark, 1 = lit — lerped toward by tickCameraIntro
  }> = [];

  // ── Camera intro ──────────────────────────────────────────────────────────
  cameraIntro: {
    active: boolean;
    elapsed: number;
    duration: number;
    spline: THREE.CatmullRomCurve3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
    /** Normalised intro time (0-1) when window light-up begins. */
    windowLightStartT: number;
    /** Normalised intro time (0-1) when all windows are fully lit. */
    windowLightEndT: number;
    windowMinZ: number;
    windowMaxZ: number;
    /** Sorted index pointer — advances as the Z threshold sweeps through. */
    windowLightIndex: number;
    onComplete?: () => void;
  } | null = null;

  // ── Camera pan ────────────────────────────────────────────────────────────
  cameraPan: {
    active: boolean;
    elapsed: number;
    duration: number;
    fromPosition: THREE.Vector3;
    toPosition: THREE.Vector3;
    fromTarget: THREE.Vector3;
    toTarget: THREE.Vector3;
    onComplete?: () => void;
  } | null = null;

  // ── Lights ────────────────────────────────────────────────────────────────
  dirLight!: THREE.DirectionalLight;
  ambient!: THREE.AmbientLight;

  // ── Post-processing ───────────────────────────────────────────────────────
  composer!: EffectComposer;
  depthRT!: THREE.WebGLRenderTarget;
  fxaaPass!: ShaderPass;
  depthOutlinePass!: ShaderPass;
  ssaoPass!: SSAOPass;
  bloomPass!: UnrealBloomPass;
  lutPass!: LUTPass;
  vignettePass!: ShaderPass;

  // ── Scene materials / objects ─────────────────────────────────────────────
  heightFogMaterial!: THREE.ShaderMaterial;
  heightFogLightUpMaterial!: THREE.ShaderMaterial;
  windowMaterialArray: THREE.ShaderMaterial[] = [];
  foilageMaterial!: THREE.MeshStandardMaterial;
  roadsMaterial!: THREE.ShaderMaterial;
  roadsGlowMaterial!: THREE.MeshStandardMaterial;
  skyMaterial!: THREE.ShaderMaterial;
  skyMesh!: THREE.Mesh;
  mountainMaterial!: THREE.MeshBasicMaterial;
  ground!: THREE.Mesh;
  ferrisWheel!: THREE.Mesh;
  particleMaterial: THREE.ShaderMaterial | null = null;
  causticsParticleMaterial: THREE.ShaderMaterial | null = null;
  medicalParticleMaterial: THREE.ShaderMaterial | null = null;
  sphereMaterial: THREE.ShaderMaterial | null = null;
  causticsCylinderMaterial: THREE.ShaderMaterial | null = null;
  medicalCylinderMaterial: THREE.ShaderMaterial | null = null;
  toiletCylinderMaterial: THREE.ShaderMaterial | null = null;
  crowdParticleMaterial: THREE.ShaderMaterial | null = null;
  confettiMesh: THREE.Mesh | null = null;
  zonesMaterialArray: THREE.ShaderMaterial[] = [];

  // ── Start zone pulse animations ───────────────────────────────────────────
  startZoneAnimations: Array<{
    mesh:                 THREE.Mesh;
    material:             THREE.ShaderMaterial | null;
    fromColor:            THREE.Color;
    elapsed:              number;
    pulseDuration:        number;
    pulseCount:           number;
    fromScale:            number;
    toScale:              number;
    lastPulseIndex:       number;
    fromVignetteColor:    THREE.Color;
    fromVignetteDarkness: number;
    restoring:             boolean;
    restoreElapsed:        number;
    restoreDuration:       number;
    restoreFromDarkness:   number;
    onComplete?:          () => void;
  }> = [];
  raceStartState: boolean = false;

  // ── Zone detection ────────────────────────────────────────────────────────
  runners: THREE.Mesh[] = [];
  zones: Array<{
    mesh: THREE.Mesh;
    material: THREE.ShaderMaterial;
    radius: number;
  }> = [];

  // ── Route ─────────────────────────────────────────────────────────────────
  currentRoute: THREE.Mesh | null = null;
  oldRoute: THREE.Mesh | null = null;
  currentRouteGoal: THREE.Mesh | null = null;
  runnerRoute: THREE.Mesh | null = null;
  /** Pre-baked evenly-spaced positions along the runner route for constant-speed interpolation. */
  runnerRouteLUT: THREE.Vector3[] = [];
  drawRoute: THREE.Mesh | null = null;
  routeStripeTexture: THREE.Texture | null = null;
  routeCanvasTexture: THREE.CanvasTexture | null = null;
  routeRunnerTexture: THREE.Texture | null = null;
  routeCompleteTexture: THREE.Texture | null = null;
  trafficjamCanvasTexture: THREE.CanvasTexture | null = null;
  trafficjamCanvas: HTMLCanvasElement | null = null;
  /** Closed-road suppress strokes on maskMap1; replayed after route lightmap redraws clear the canvas. */
  closedTrafficSegmentMasks: Array<{ id: string; worldPoints: Array<{ x: number; z: number }> }> = [];
  routeDraw: {
    active: boolean;
    elapsed: number;
    duration: number;
    full: number;
    onComplete?: () => void;
  } | null = null;
  routeLightFade: { active: boolean; elapsed: number; duration: number } | null = null;
  outroRunnerArray: THREE.Mesh[] = [];
  errorState: boolean = false;

  // ── Icon picking ──────────────────────────────────────────────────────────
  iconPickMeshes: THREE.Mesh[] = [];
  hoveredIcon: THREE.Mesh | null = null;

  // ── Icon textures (loaded lazily on first initRoute / addWarning call) ────
  iconCircleTexture: THREE.Texture | null = null;
  iconCircleFilledTexture: THREE.Texture | null = null;
  iconLineTexture: THREE.Texture | null = null;
  warningTexture: THREE.Texture | null = null;
  iconDiamondTexture: THREE.Texture | null = null;

  // ── Debug (Tweakpane — only created when ?debug=true) ────────────────────
  debug: boolean = false;
  tweakpane: any = null;
  tpStyleEl: HTMLStyleElement | null = null;
}
