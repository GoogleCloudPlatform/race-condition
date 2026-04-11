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

import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnInit,
  OnDestroy,
  ViewChild,
  NgZone,
} from '@angular/core';
import * as THREE from 'three';
import { CommonModule } from '@angular/common';

import { Context } from './context';
import { baseFog, lightOffset, MAP_CENTER_LAT, MAP_CENTER_LON } from './config';
import {
  initScene,
  initLights,
  initGround,
  initHorizon,
  initModel,
  panCameraTo,
  tickCameraPan,
  followMesh,
  swapFollowTarget,
  stopFollowMesh,
  tickCameraFollow,
  followZoom,
  startCameraIntro,
  tickCameraIntro,
} from './scene/scene';
import { initPostProcessing } from './scene/postprocessing';
import { simLog } from '../sim-logger';
import {
  tickRouteDraw,
  initRoute,
  showOldRoute,
  initRunnerRoute,
  setRaceComplete,
  initRunner,
  updateRunner,
  setRunnerColor,
  removeRoute,
  removeRunnerRoute,
  drawTrafficjamToTexture,
  drawRouteSuppressSegmentToTexture,
  drawTrafficjamSegmentToTexture,
  setError,
} from './route/route';
import {
  getWarning,
  getInfoIcon,
  getWaterZone,
  getMedicalZone,
  getCrowdZone,
  getToiletZone,
  getScreenSpacePosition,
  tickZones,
  removeZone,
  triggerStartZoneAnimation,
  tickStartZoneAnimations,
  getStartZone,
  AffectedIntersection,
  getTrafficZones,
  lngLatToWorld,
} from './route/icons';
import { initTweakpane, TweakpaneDebugApi } from './debug/tweakpane';
import { PerfMonitor } from './debug/perf-monitor';
import { initParticles } from './shaders/particle-shader';
import { createConfettiParticles } from './shaders/confetti-shader';
import { GLB_TRANSFORM } from '../glb-roads';
import { CatmullRomPathAdapter } from '../path';
import { MARATHON_DISTANCE_MI, RUNNER_SPEED_SCALE } from '../runner-sim-constants';
import { RunnerManager } from '../simulation';
import { Runner } from '../runner';
import { SimpleStationZone, StationZone } from '../water-station';
import { visualizeRoutePlan } from './viewport-utils';
import { roadSpline1, roadSpline2, roadSpline3 } from '../../constants';

const _labelWorldPos = new THREE.Vector3();

function perfMark(name: string): void {
  performance.mark(`perf:${name}:start`);
}

function perfMeasure(name: string): void {
  performance.mark(`perf:${name}:end`);
  performance.measure(`perf:${name}`, `perf:${name}:start`, `perf:${name}:end`);
}

@Component({
  selector: 'app-viewport-lookdev',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule],
  template: `
    <canvas #canvas></canvas>
    <div #introOverlay class="intro-overlay"></div>
    <div #runnerLabel class="runner-container">
      <div class="inner" *ngIf="!runnersHaveThoughts; else haveThoughts">
        <p class="emoji"></p>
        <div class="stats">
          <div class="stat-row">
            <p class="runner-position">Position #123</p>
            <p class="runner-id">Position #123</p>
          </div>
          <div class="stat-row">
            <p class="runner-pace">Pace: XX</p>
            <p class="runner-energy">Pace: XX</p>
          </div>
        </div>
      </div>
      <ng-template #haveThoughts>
        <div class="inner">
          <p class="emoji"></p>
          <div class="hasThoughts">
            <div class="stats">
              <div class="stat-row">
                <p class="runner-position">Position #123</p>
                <p class="runner-id">Position #123</p>
              </div>
              <div class="stat-row">
                <p class="runner-pace">Pace: XX</p>
                <p class="runner-energy">Pace: XX</p>
              </div>
            </div>
            <h3 class="runner-thought"></h3>
          </div>
        </div>
      </ng-template>
    </div>

    <div #iconTooltip class="icon-tooltip">
      <img class="icon-tooltip__icon" />

      <div class="icon-tooltip__information">
        <p class="icon-tooltip__sublabel"></p>
        <p class="icon-tooltip__label"></p>
      </div>
    </div>
  `,
  styleUrls: ['./viewport-lookdev.scss'],
})
export class ViewportComponent implements OnInit, OnDestroy {
  @ViewChild('canvas', { static: true }) canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('introOverlay', { static: true }) introOverlayRef!: ElementRef<HTMLDivElement>;
  @ViewChild('runnerLabel', { static: true }) runnerLabelRef!: ElementRef<HTMLDivElement>;
  @ViewChild('iconTooltip', { static: true }) iconTooltipRef!: ElementRef<HTMLDivElement>;

  private ctx = new Context();
  private mouseDirty = false;
  private perfMonitor: PerfMonitor | null = null;
  private readonly resizeHandler = (): void => this.onResize();
  private readonly clickHandler = (e: MouseEvent): void => this.onClick(e);

  private _destroyed = false;
  private _pointerDownPos: { x: number; y: number } | null = null;
  private _autoRotateResumeTimer: ReturnType<typeof setTimeout> | null = null;
  private _autoPanning = true;
  private _postFinishSequence = false;
  private _overviewTarget: THREE.Object3D | null = null;
  private _raceSupportVisible = true;
  private _entertainmentVisible = true;

  private readonly wheelHandler = (e: WheelEvent): void => {
    if (this.ctx.cameraFollow) {
      e.preventDefault();
      const scale = 1 + e.deltaY * 0.001;
      this.ctx.cameraFollow.offset.multiplyScalar(Math.max(0.1, scale));
    }
  };

  private readonly pointerDownHandler = (e: PointerEvent): void => {
    this._pointerDownPos = { x: e.clientX, y: e.clientY };
    if (this.ctx.cameraFollow) {
      this.ctx.userDragging = true;
    }
    if (this._postFinishSequence) {
      this.cancelPostFinishSequence();
    }
  };

  private readonly pointerUpHandler = (e: PointerEvent): void => {
    if (!this._pointerDownPos) return;
    const dx = e.clientX - this._pointerDownPos.x;
    const dy = e.clientY - this._pointerDownPos.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    this._pointerDownPos = null;
    this.ctx.userDragging = false;

    if (dist < 5) {
      this.followGuid = null;
      this._followLeaderActive = false;
      this.stopFollowMesh();
      window.dispatchEvent(new CustomEvent('viewport:followStopped'));
    } else if (this._postFinishSequence) {
      this.cancelPostFinishSequence();
    }
  };
  private pickPlane: THREE.Mesh | null = null;
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();
  private readonly mouseMoveHandler = (e: MouseEvent): void => this.onMouseMove(e);

  // ── Runner simulation fields ──────────────────────────────────────────────
  /** RunnerManager wrapping Runner objects (replaces bare THREE.Mesh map). */
  private runnerManager!: RunnerManager;
  /** CatmullRomPathAdapter created from the runner route LUT. */
  private lookdevPath: CatmullRomPathAdapter | null = null;
  /** Geodesic length in metres of the most recently imported route. */
  private importedLengthMi = 0;
  /** Station zones for collision detection (built from import data). */
  private importedStations: StationZone[] = [];
  // simDistanceIntegrator = SIM_SPEED/3600 = simulated hours per real second (here 0.1).
  // Matches default race grid: 12 ticks × 30 sim-min/tick = 6h sim; 10s wall between ticks (120s total) → 0.5 sim-h per 10s wall.
  private static readonly SIM_SPEED = 360;
  private simSpeedMultiplier = ViewportComponent.SIM_SPEED / 3600;
  // Backend velocity is normalized: real mph = velocity * SPEED_SCALE
  private static readonly SPEED_SCALE = 6.2137;
  private _simSpeedCalibrated = false;
  private _simRunnerMeshes: THREE.Mesh[] = [];
  /** Accumulator for periodic HUD sync (every 0.5s). */
  private simSyncAccum = 0;
  /**
   * Gateway `process_tick` payloads that arrived while `onAddSimRunner` was still awaiting
   * route/mesh setup. Merged on arrival, flushed after `addRunnerWithGuid`.
   */
  private _pendingGatewaySimUpdates = new Map<string, { velocity?: number; water?: number }>();
  /** Whether sim runners were active last frame (to detect transitions). */
  private hadSimRunners = false;
  /** Camera follow state (manual — set by hud:focusSimRunner, cleared by click). */
  private followGuid: string | null = null;

  /** GUID of the runner currently being followed by the camera. */
  private _followLeaderActive = true;
  /** Current route spline — stored for camera pans and runner route when sim starts. */
  private currentSpline: THREE.CatmullRomCurve3 | null = null;
  private nextPathId = 0;
  private importedPaths: {
    id: number;
    name: string;
    lengthMi: number;
    colorHex: string;
    waterStationCount: number;
  }[] = [];

  private currentFocusedIcon: any = null;
  private debugSplines: THREE.CatmullRomCurve3[] | null = null;

  protected runnersHaveThoughts: boolean = false;

  /** Cached runner HUD nodes; invalidated when template branch swaps (*ngIf) or nodes detach. */
  private _runnerLabelDom: {
    emoji: HTMLElement;
    position: HTMLElement;
    id: HTMLElement;
    pace: HTMLElement;
    energy: HTMLElement;
    thought: HTMLElement | null;
  } | null = null;

  constructor(private ngZone: NgZone) {
    window.addEventListener('gateway:routeGeojson', this.onRouteGeojson);
    window.addEventListener('hud:importPath', this.onImportPath);
  }

  ngOnInit(): void {
    this.ctx.debug = new URLSearchParams(window.location.search).get('debug') === 'true';
    initScene(this.ctx, this.canvasRef.nativeElement);
    initLights(this.ctx);
    initGround(this.ctx);
    initHorizon(this.ctx);

    this.runnerManager = new RunnerManager(this.ctx.scene);

    initParticles(this.ctx);

    initModel(this.ctx).then(async () => {
      initPostProcessing(this.ctx);

      if (this.ctx.debug) {
        this.debugSplines = [roadSpline1, roadSpline2, roadSpline3];
        const debugApi: TweakpaneDebugApi = {
          splines: this.debugSplines,
          debugRoute: (s) => this.debugRoute(s),
          debugStartRunners: (s) => this.debugStartRunners(s),
          debugSetRaceComplete: () => this.debugSetRaceComplete(),
          debugClearAllRoutes: () => this.debugClearAllRoutes(),
          debugAddInfoIcons: () => this.debugAddInfoIcons(),
          debugToggleError: () => this.debugToggleError(),
          debugStartCameraIntro: () => this.debugStartCameraIntro(),
          debugShowOldRoute: () => this.debugShowOldRoute(),
          //debugStartOutro: () => this.debugStartOutro(),
          debugConfetti: () => this.debugConfetti(),
          debugCameraTopView: () => this.cameraTopView(),
          debugCameraMidView: () => this.cameraMidView(),
          debugCameraCloseView: () => this.cameraCloseView(),
          debugCameraA: () => this.cameraA(),
          debugCameraB: () => this.cameraB(),
          debugCameraTopRoute: () => this.cameraTopRoute(),
          debugStartZone: () => this.debugStartZone(),
        };
        this.perfMonitor = new PerfMonitor();
        // Disable auto-reset so EffectComposer's multiple render passes
        // accumulate draw-call/triangle counts across the full frame.
        // PerfMonitor.tick() calls info.reset() manually after reading.
        this.ctx.renderer.info.autoReset = false;
        initTweakpane(
          this.ctx,
          debugApi,
          this.perfMonitor ?? undefined,
          () => this.runnerManager.getRunners().size,
          () => this._followLeaderActive,
        );

        // debug ground plane used solely for mouse-click raycasting.
        const pickGeo = new THREE.PlaneGeometry(100000, 100000);
        const pickMat = new THREE.MeshBasicMaterial({ visible: false, side: THREE.DoubleSide });
        this.pickPlane = new THREE.Mesh(pickGeo, pickMat);
        this.pickPlane.rotation.x = -Math.PI / 2;
        this.ctx.scene.add(this.pickPlane);
      }

      // Auto-capture via URL parameters
      const urlParams = new URLSearchParams(window.location.search);
      const perfCapture = urlParams.get('perfCapture');
      if (perfCapture && !this.perfMonitor) {
        console.warn('[PerfAutoCapture] perfCapture requires debug=true');
      }
      if (perfCapture && this.perfMonitor) {
        const duration = parseInt(perfCapture, 10) || 15000;
        const runners = parseInt(urlParams.get('perfRunners') ?? '100', 10);
        const label = urlParams.get('perfLabel') ?? 'auto';
        const follow = urlParams.has('perfFollow');
        this.startAutoCapture(duration, runners, label, follow).catch((err) =>
          console.error('[PerfAutoCapture] failed', err),
        );
      }

      this.canvasRef.nativeElement.addEventListener('click', this.clickHandler);
    });

    this.canvasRef.nativeElement.addEventListener('pointerdown', this.pointerDownHandler);
    this.canvasRef.nativeElement.addEventListener('pointerup', this.pointerUpHandler);
    this.canvasRef.nativeElement.addEventListener('wheel', this.wheelHandler, { passive: false });
    this.canvasRef.nativeElement.addEventListener('mousemove', this.mouseMoveHandler);
    window.addEventListener('resize', this.resizeHandler);
    window.addEventListener('hud:removeAllPaths', this.onRemoveAllPaths);
    window.addEventListener('hud:remove', this.onRemovePath);
    window.addEventListener('hud:addSimRunner', this.onAddSimRunner);
    window.addEventListener('hud:updateSimRunner', this.onUpdateSimRunner);
    window.addEventListener('hud:removeSimRunner', this.onRemoveSimRunner);
    window.addEventListener('hud:focusSimRunner', this.onFocusSimRunner);
    window.addEventListener('hud:followLeader', this.onFollowLeader);
    window.addEventListener('sim:raceStarted', this.onSimRaceStarted);
    window.addEventListener('sim:spawnRunners', this.onSimSpawnRunners);
    window.addEventListener('sim:runnerEvent', this.onSimRunnerEvent);
    window.addEventListener('sim:complete', this.onSimComplete);
    window.addEventListener('sim:finished', this.onSimFinished);
    window.addEventListener('sim:reset', this.onSimReset);
    window.addEventListener('hud:followRandomRunner', this.onFollowRandomRunner);
    window.addEventListener('sim:triggerError', () => this.setError(true));
    window.addEventListener('sim:fixError', () => this.setError(false));
    window.addEventListener('sim:playIntro', () => this.startCameraIntro());
    window.addEventListener('keydown', this.onKeyDown);
    window.addEventListener('gateway:trafficZones', this.onTrafficZones);

    window.addEventListener('sim:giveRunnerThoughts', () => this.onGiveRunnersThoughts());
    window.addEventListener('sim:removeRunnerThoughts', () => this.onRemoveRunnersThoughts());
    window.addEventListener('filter:changed', this.onFilterChanged);

    this.ngZone.runOutsideAngular(() => this.animate());
  }

  ngOnDestroy(): void {
    this._destroyed = true;
    this._runnerLabelDom = null;

    // Stop render loop
    cancelAnimationFrame(this.ctx.animFrameId);

    window.removeEventListener('keydown', this.onKeyDown);

    // Remove window resize listener
    this.canvasRef.nativeElement.removeEventListener('pointerdown', this.pointerDownHandler);
    this.canvasRef.nativeElement.removeEventListener('pointerup', this.pointerUpHandler);
    this.canvasRef.nativeElement.removeEventListener('wheel', this.wheelHandler);
    this.canvasRef.nativeElement.removeEventListener('mousemove', this.mouseMoveHandler);
    if (this._autoRotateResumeTimer) clearTimeout(this._autoRotateResumeTimer);
    window.removeEventListener('resize', this.resizeHandler);
    window.removeEventListener('hud:importPath', this.onImportPath);
    window.removeEventListener('gateway:routeGeojson', this.onRouteGeojson);
    window.removeEventListener('hud:removeAllPaths', this.onRemoveAllPaths);
    window.removeEventListener('hud:remove', this.onRemovePath);
    window.removeEventListener('hud:addSimRunner', this.onAddSimRunner);
    window.removeEventListener('hud:updateSimRunner', this.onUpdateSimRunner);
    window.removeEventListener('hud:removeSimRunner', this.onRemoveSimRunner);
    window.removeEventListener('hud:focusSimRunner', this.onFocusSimRunner);
    window.removeEventListener('hud:followLeader', this.onFollowLeader);
    window.removeEventListener('sim:raceStarted', this.onSimRaceStarted);
    window.removeEventListener('sim:spawnRunners', this.onSimSpawnRunners);
    window.removeEventListener('sim:runnerEvent', this.onSimRunnerEvent);
    window.removeEventListener('sim:complete', this.onSimComplete);
    window.removeEventListener('sim:finished', this.onSimFinished);
    window.removeEventListener('sim:reset', this.onSimReset);
    window.removeEventListener('hud:followRandomRunner', this.onFollowRandomRunner);
    window.removeEventListener('sim:triggerError', () => this.setError(true));
    window.removeEventListener('sim:fixError', () => this.setError(false));
    window.removeEventListener('sim:playIntro', () => this.startCameraIntro);
    window.removeEventListener('gateway:trafficZones', this.onTrafficZones);
    window.removeEventListener('sim:giveRunnerThoughts', this.onGiveRunnersThoughts);
    window.removeEventListener('sim:removeRunnerThoughts', this.onRemoveRunnersThoughts);
    window.removeEventListener('filter:changed', this.onFilterChanged);
    this.canvasRef.nativeElement.removeEventListener('click', this.clickHandler);
    if (this.pickPlane) {
      this.pickPlane.geometry.dispose();
      (this.pickPlane.material as THREE.Material).dispose();
    }

    // Dispose post-processing passes individually
    this.ctx.ssaoPass?.dispose();
    this.ctx.bloomPass?.dispose();
    this.ctx.lutPass?.dispose();
    this.ctx.depthOutlinePass?.dispose();
    this.ctx.vignettePass?.dispose();
    this.ctx.fxaaPass?.dispose();
    this.ctx.composer?.dispose();
    this.ctx.depthRT?.dispose();

    // Traverse scene — dispose geometry + all material textures + material.
    // Catches all dynamic objects: route tubes, icons, warnings, GLB meshes,
    // sky cylinder, mountains, ground, drawSplineToTexture CanvasTexture, etc.
    this.ctx.scene?.traverse((object) => {
      if (!(object instanceof THREE.Mesh) && !(object instanceof THREE.Sprite)) return;
      (object as THREE.Mesh).geometry?.dispose();
      const mats = Array.isArray(object.material)
        ? (object.material as THREE.Material[])
        : [object.material as THREE.Material];
      for (const mat of mats) {
        if (!mat) continue;
        for (const val of Object.values(mat as unknown as Record<string, unknown>)) {
          if (val instanceof THREE.Texture) val.dispose();
        }
        mat.dispose();
      }
    });
    this.ctx.scene?.clear();

    // Dispose route meshes that may have been scene.remove()'d and are
    // no longer reachable by the traversal above
    const disposeRouteMesh = (mesh: THREE.Mesh | null): void => {
      if (!mesh) return;
      mesh.geometry?.dispose();
      const mat = mesh.material as THREE.Material;
      for (const val of Object.values(mat as unknown as Record<string, unknown>)) {
        if (val instanceof THREE.Texture) val.dispose();
      }
      mat?.dispose();
    };
    disposeRouteMesh(this.ctx.currentRoute);
    disposeRouteMesh(this.ctx.oldRoute);
    disposeRouteMesh(this.ctx.runnerRoute);
    disposeRouteMesh(this.ctx.currentRouteGoal);

    // Dispose explicit material fields (double-dispose is safe in Three.js)
    (
      this.ctx.heightFogMaterial?.uniforms?.['emissiveMap']?.value as THREE.Texture | undefined
    )?.dispose();
    this.ctx.heightFogMaterial?.dispose();
    for (const mat of this.ctx.windowMaterialArray) mat?.dispose();
    this.ctx.skyMaterial?.dispose();
    this.ctx.mountainMaterial?.dispose();
    this.ctx.foilageMaterial?.dispose();
    this.ctx.roadsMaterial?.dispose();
    this.ctx.roadsGlowMaterial?.dispose();

    // Dispose explicit texture fields
    this.ctx.routeStripeTexture?.dispose();
    this.ctx.routeCanvasTexture?.dispose();
    this.ctx.iconLineTexture?.dispose();
    this.ctx.iconCircleTexture?.dispose();
    this.ctx.iconCircleFilledTexture?.dispose();
    this.ctx.warningTexture?.dispose();
    (this.ctx.lutPass?.lut as THREE.Texture | undefined)?.dispose();

    // Dispose directional light shadow map
    this.ctx.dirLight?.shadow?.map?.dispose();

    // Dispose controls and renderer (renderer last — invalidates GL context)
    this.ctx.controls?.dispose();
    this.ctx.renderer?.dispose();

    // Remove Tweakpane (only present when ?debug=true)
    this.ctx.tweakpane?.dispose();
    this.ctx.tpStyleEl?.remove();
  }

  private runnerLabelDom(root: HTMLDivElement): typeof this._runnerLabelDom {
    const c = this._runnerLabelDom;
    if (c && root.contains(c.emoji)) return c;
    const emoji = root.querySelector<HTMLElement>('.emoji');
    if (!emoji) {
      this._runnerLabelDom = null;
      return null;
    }
    this._runnerLabelDom = {
      emoji,
      position: root.querySelector('.runner-position')!,
      id: root.querySelector('.runner-id')!,
      pace: root.querySelector('.runner-pace')!,
      energy: root.querySelector('.runner-energy')!,
      thought: root.querySelector('.runner-thought'),
    };
    return this._runnerLabelDom;
  }

  private tickRunnerLabel(): void {
    const el = this.runnerLabelRef.nativeElement;
    const activeGuid = this.followGuid;
    if (!activeGuid || !this.ctx.cameraFollow) {
      el.style.display = 'none';
      return;
    }
    const world = _labelWorldPos;
    this.ctx.cameraFollow.mesh.getWorldPosition(world);
    world.project(this.ctx.camera);
    const x = (world.x * 0.5 + 0.5) * window.innerWidth;
    const y = (-world.y * 0.5 + 0.5) * window.innerHeight;
    const rx = Math.round(x * 100) / 100;
    const ry = Math.round(y * 100) / 100;
    el.style.display = 'flex';
    el.style.left = '0';
    el.style.top = '0';
    el.style.transform = `translate(-50%, calc(-100% - 12px)) translate3d(${rx}px, ${ry}px, 0)`;
    const dom = this.runnerLabelDom(el);
    if (!dom) return;

    const runner = this.runnerManager.getRunner(activeGuid!);
    const runnerThought = runner?.getThought() || '';
    const water = runner?.getWater() || 100;
    const pace = runner?.getPace() || '3:30';
    const place = runner?.getPlace([...this.runnerManager.getRunners().values()]) || '1000';

    dom.emoji.textContent =
      place === 1 ? '🥇' : place === 2 ? '🥈' : place === 3 ? '🥉' : `${runner?.getEmoji()}`;

    dom.position.textContent = `#${place}`; // '#8888'; //
    dom.id.textContent = `ID: ${activeGuid.split('-')[1].slice(0, 6)}`; // 'ID: 888888'; //
    dom.pace.textContent = `Pace: ${pace}`; //'Pace: 88:88'; //
    dom.energy.textContent = `Energy: ${water}%`; //'Energy: 88.88%'; //

    if (this.runnersHaveThoughts && dom.thought) dom.thought.textContent = runnerThought;
  }

  private async tickIconTooltip(): Promise<void> {
    const el = this.iconTooltipRef.nativeElement;
    const icon = this.ctx.hoveredIcon || this.currentFocusedIcon;
    if (!icon) {
      el.style.display = 'none';
      return;
    }

    let pos = await this.getHoveredIconScreenSpacePosition();

    if (!pos) {
      pos = await getScreenSpacePosition(this.ctx, icon);
    }

    if (!pos) return;

    const ICONS = {
      traffic: '/assets/images/traffic.png',
      water_station: '/assets/images/water.png',
      crowd_zone: '/assets/images/crowd.png',
      medical: '/assets/images/medical.png',
    };

    const label: string = icon.userData['label'] ?? '';
    const sublabel: string = icon.userData['sublabel'] ?? '';
    const iconType: string = icon.userData['type'] ?? '';

    (el.querySelector('.icon-tooltip__label') as HTMLElement).textContent = label;
    const sublabelEl = el.querySelector('.icon-tooltip__sublabel') as HTMLElement;

    (el.querySelector('.icon-tooltip__icon') as HTMLImageElement).src =
      ICONS[iconType as keyof typeof ICONS];

    sublabelEl.textContent = sublabel;
    sublabelEl.style.display = sublabel ? '' : 'none';

    el.style.display = 'flex';
    el.style.left = `${Math.round(pos.x * 100) / 100}px`;
    el.style.top = `${Math.round(pos.y * 100) / 100}px`;
  }

  /** Show/hide the route tubes based on selection and simulation state. */
  private updateRouteVisibility(): void {
    const runnersActive = this.runnerManager.hasRunners();
    if (this.ctx.currentRoute) {
      // Hide only the route tube mesh, not its children (water station / medical tent icons)
      const mat = this.ctx.currentRoute.material as THREE.Material;
      mat.visible = !runnersActive;
    }
  }

  private animate(): void {
    this.ctx.animFrameId = requestAnimationFrame(() => this.animate());
    this.ctx.timer.update();
    const delta = this.ctx.timer.getDelta();

    this.ctx.controls.update();

    // Keep directional light and shadow frustum centred on the orbit target
    this.ctx.dirLight.position.copy(this.ctx.controls.target).add(lightOffset);
    this.ctx.dirLight.target.position.copy(this.ctx.controls.target);

    this.updateFog();
    tickRouteDraw(this.ctx, delta);
    if (this.perfMonitor) perfMark('zoneCheck');
    tickZones(this.ctx, delta);
    if (this.perfMonitor) perfMeasure('zoneCheck');
    tickStartZoneAnimations(this.ctx, delta);
    tickCameraIntro(this.ctx, delta);
    tickCameraPan(this.ctx, delta);
    tickCameraFollow(this.ctx, delta);
    this.tickRunnerLabel();
    // this.debugTickRunnerLabel();
    this.tickIconTooltip();

    if (this.ctx.runnerRoute && this.ctx.debug) {
      for (let i = 0; i < this.ctx.runners.length; i++) {
        const runner = this.ctx.runners[i];
        if (runner.userData['guid']) continue;
        runner.userData['time'] += runner.userData['speed'] * delta;
        if (runner.userData['time'] >= 0.99999) {
          runner.userData['time'] = 0.99999;
        }
        this.updateRunner(runner, runner.userData['time']);
      }
    }

    // Hide route when runners appear, restore when they're gone
    const hasSimRunners = this.runnerManager.hasRunners();
    if (hasSimRunners !== this.hadSimRunners) {
      this.updateRouteVisibility();
    }
    this.hadSimRunners = hasSimRunners;

    // Advance sim runners
    if (this.runnerManager.hasRunners()) {
      // Advance all runners via Runner.tick() (backend-synced blending + station detection)
      if (this.perfMonitor) perfMark('runnerTick');
      this.runnerManager.tick(delta);
      if (this.perfMonitor) perfMeasure('runnerTick');

      // Position sim runner meshes using Runner.getT() as the authoritative time source
      if (this.perfMonitor) perfMark('runnerPosition');
      const lut = this.ctx.runnerRouteLUT;
      for (let i = 0; i < this._simRunnerMeshes.length; i++) {
        const mesh = this._simRunnerMeshes[i];
        if (mesh.userData['_finished']) continue;

        const guid = mesh.userData['guid'] as string;
        const runner = this.runnerManager.getRunner(guid);
        if (!runner) continue;

        const time = runner.getT();

        if (time >= 1 || runner.status === 'finished') {
          if (!mesh.userData['_finished']) {
            mesh.userData['_finished'] = true;
            mesh.visible = false;
            const ri = this.ctx.runners.indexOf(mesh);
            if (ri !== -1) this.ctx.runners.splice(ri, 1);
            simLog.log(
              'FINISH',
              guid,
              `completed race (t=${time.toFixed(4)} vel=${runner.getVelocity().toFixed(4)} pathLen=${runner.getPathLength().toFixed(1)})`,
            );
            if (this.followGuid === guid) {
              this._followLeaderActive = false;
              this.followGuid = null;
              this.startPostFinishSequence();
              window.dispatchEvent(new CustomEvent('viewport:followStopped'));
            }
          }
          continue;
        }
        mesh.userData['time'] = time;
        if (lut.length > 1) {
          const lt = time * (lut.length - 1);
          const idx = Math.floor(lt);
          const frac = lt - idx;
          const next = Math.min(idx + 1, lut.length - 1);
          mesh.position.lerpVectors(lut[idx], lut[next], frac);
          const rnd = mesh.userData['random'] as number;
          const freq = lut.length * 0.4;
          const multiplier = Math.min(time / 0.01, 1.0);
          mesh.position.y += Math.abs(Math.sin(time * freq * rnd)) * 20 * multiplier;
          const sideOffset = Math.cos(time * freq * rnd) * 20 * multiplier;
          if (next > idx) {
            const dx = lut[next].x - lut[idx].x;
            const dz = lut[next].z - lut[idx].z;
            const len = Math.sqrt(dx * dx + dz * dz) || 1;
            mesh.position.x += (-dz / len) * sideOffset;
            mesh.position.z += (dx / len) * sideOffset;
          }
        }
      }
      if (this.perfMonitor) perfMeasure('runnerPosition');

      if (
        !this._simAllFinished &&
        this._simRunnerMeshes.length > 0 &&
        this._simRunnerMeshes.every((m) => m.userData['_finished'])
      ) {
        this._simAllFinished = true;
        window.dispatchEvent(new CustomEvent('sim:finished'));
      }

      if (this._followLeaderActive && !this.ctx.cameraPan?.active) {
        let leaderMesh: THREE.Mesh | null = null;
        let bestTime = -1;
        for (const m of this._simRunnerMeshes) {
          if (m.userData['_finished']) continue;
          const guid = m.userData['guid'] as string;
          const r = this.runnerManager.getRunner(guid);
          const t = r?.getT() ?? 0;
          if (t > bestTime) {
            bestTime = t;
            leaderMesh = m;
          }
        }
        if (leaderMesh && !this.ctx.raceStartState) {
          const leaderGuid = leaderMesh.userData['guid'] as string;
          if (leaderGuid !== this.followGuid) {
            this.followGuid = leaderGuid;
            if (this.ctx.cameraFollow) {
              swapFollowTarget(this.ctx, leaderMesh);
            } else {
              followMesh(
                this.ctx,
                leaderMesh,
                new THREE.Vector3(-1000, 4000, 1000),
                this._autoPanning,
              );
            }
            simLog.log('CAMERA', leaderGuid, 'leader changed');
          }
        }
      }

      // Notify backend of mile boundary crossings
      // for (const info of this.runnerManager.getRunnerInfos()) {
      //   const newProgress = info.percentComplete / 100;
      //   const prevProgress = prevProgressMap.get(info.guid) ?? 0;
      //   const prevMile = Math.floor(prevProgress * 26.2);
      //   const newMile = Math.floor(newProgress * 26.2);
      //   if (newMile > prevMile && newMile > 0) {
      //     const sessionId = info.guid.startsWith('sim-') ? info.guid.slice(4) : info.guid;
      //     const distPayload = JSON.stringify({ event: 'distance_update', mile_delta: 1.0 });
      //     window.dispatchEvent(
      //       new CustomEvent('sim:broadcastToRunner', {
      //         detail: { sessionId, payload: distPayload },
      //       }),
      //     );
      //     this.logSimEvent(info.guid, 'out', `DISTANCE_UPDATE mile=${newMile}`);
      //   }
      // }

      // Sync progress to HUD every 0.5s
      this.simSyncAccum += delta;
      if (this.simSyncAccum >= 0.5) {
        this.simSyncAccum = 0;
        for (let i = 0; i < this._simRunnerMeshes.length; i++) {
          const mesh = this._simRunnerMeshes[i];
          const guid = mesh.userData['guid'] as string;
          const runner = this.runnerManager.getRunner(guid);
          const t = runner?.getT() ?? 0;
          const finished = !!mesh.userData['_finished'];
          let status: 'active' | 'finished' | 'did-not-finish' = 'active';
          if (finished && t >= 1) status = 'finished';
          else if (finished) status = 'did-not-finish';
          window.dispatchEvent(
            new CustomEvent('hud:updateSimRunner', {
              detail: {
                guid,
                velocity: runner?.getVelocity() ?? 0,
                water: runner?.getWater() ?? 100,
                progress: t,
                status,
              },
            }),
          );
        }
      }
    }

    // outro runners
    for (let i = 0; i < this.ctx.outroRunnerArray.length; i++) {
      const runner = this.ctx.outroRunnerArray[i];
      runner.userData['time'] += runner.userData['speed'] * delta;
      if (runner.userData['time'] >= 0.99999) {
        runner.userData['time'] = 0.99998;
        runner.userData['speed'] = 0;
        if (i == 0) {
          this.setConfetti(true);
        }
      }

      // speed up "Hero" runner
      if (i == 0 && runner.userData['time'] >= 0.75 && runner.userData['speed'] > 0) {
        runner.userData['speed'] = 0.024;
      }

      this.updateRunner(runner, runner.userData['time']);
    }

    if (this.ctx.ferrisWheel) {
      this.ctx.ferrisWheel.rotation.x += delta * 0.1;
    }
    if (this.ctx.roadsMaterial) {
      this.ctx.roadsMaterial.uniforms['emissiveMapOffset'].value.y -= delta * 0.05;
    }
    if (this.ctx.particleMaterial) {
      this.ctx.particleMaterial.uniforms['globalTime'].value += delta;
    }
    if (this.ctx.causticsParticleMaterial) {
      this.ctx.causticsParticleMaterial.uniforms['uTime'].value += delta * 0.4;
    }
    if (this.ctx.medicalParticleMaterial) {
      this.ctx.medicalParticleMaterial.uniforms['uTime'].value += delta * 0.4;
    }
    if (this.ctx.crowdParticleMaterial) {
      this.ctx.crowdParticleMaterial.uniforms['uTime'].value += delta * 0.4;
    }
    if (this.ctx.sphereMaterial) {
      this.ctx.sphereMaterial.uniforms['uTime'].value += delta;
    }
    if (this.ctx.causticsCylinderMaterial) {
      this.ctx.causticsCylinderMaterial.uniforms['uTime'].value += delta;
    }
    if (this.ctx.medicalCylinderMaterial) {
      this.ctx.medicalCylinderMaterial.uniforms['uTime'].value += delta;
    }
    if (this.ctx.routeRunnerTexture) {
      this.ctx.routeRunnerTexture.offset.x -= delta * 0.25;
    }
    if (this.ctx.routeCompleteTexture) {
      this.ctx.routeCompleteTexture.offset.x -= delta * 0.1;
    }
    if (this.ctx.routeStripeTexture) {
      this.ctx.routeStripeTexture.offset.x -= delta;
    }
    if (this.ctx.confettiMesh) {
      const uTime = (this.ctx.confettiMesh.material as THREE.ShaderMaterial).uniforms['uTime'];
      if (uTime.value >= 0) uTime.value += delta;
      const uAlpha = (this.ctx.confettiMesh.material as THREE.ShaderMaterial).uniforms['uAlpha'];
      if (uAlpha.value < 1) uAlpha.value += delta;
    }
    for (let i = 0; i < this.ctx.zonesMaterialArray.length; i++) {
      this.ctx.zonesMaterialArray[i].uniforms['uTime'].value += delta;
    }
    if (this.ctx.errorState) {
      this.ctx.vignettePass.uniforms['darkness'].value =
        0.75 + Math.sin(this.ctx.timer.getElapsed() * 4) * 0.15;
    }

    // Icon hover raycasting
    if (this.perfMonitor) perfMark('raycast');
    if (this.mouseDirty && this.ctx.iconPickMeshes.length > 0) {
      this.mouseDirty = false;
      this.raycaster.setFromCamera(this.mouse, this.ctx.camera);
      const hits = this.raycaster.intersectObjects(this.ctx.iconPickMeshes, false);
      const visibleHit = hits.find((h) => {
        let obj: THREE.Object3D | null = h.object;
        while (obj) {
          if (!obj.visible) return false;
          obj = obj.parent;
        }
        return true;
      });
      const hit = visibleHit ? (visibleHit.object as THREE.Mesh) : null;

      if (hit !== this.ctx.hoveredIcon) {
        this.ctx.hoveredIcon = hit;
        this.canvasRef.nativeElement.style.cursor = hit ? 'pointer' : '';
      }
    }
    if (this.perfMonitor) perfMeasure('raycast');

    if (this.ctx.composer) {
      // Capture depth to dedicated target before composer overwrites it
      if (this.perfMonitor) perfMark('depthPrePass');
      this.ctx.renderer.setRenderTarget(this.ctx.depthRT);
      this.ctx.renderer.render(this.ctx.scene, this.ctx.camera);
      this.ctx.renderer.setRenderTarget(null);
      if (this.perfMonitor) perfMeasure('depthPrePass');

      // Point DepthOutlinePass at the current readBuffer's depth texture.
      // The EffectComposer swaps read/write buffers between frames, so this
      // must be updated every frame to read the RenderPass scene depth.
      // this.ctx.depthOutlinePass.uniforms['tDepth'].value =
      //   (this.ctx.composer as any).readBuffer.depthTexture;

      // viewMatrixInverse must stay in sync with camera world matrix
      this.ctx.depthOutlinePass.uniforms['viewMatrixInverse'].value = this.ctx.camera.matrixWorld;

      if (this.perfMonitor) perfMark('composerRender');
      this.ctx.composer.render();
      if (this.perfMonitor) perfMeasure('composerRender');
    }

    this.perfMonitor?.tick(delta, this.ctx.renderer);
  }

  private onMouseMove(e: MouseEvent): void {
    this.mouseDirty = true;
    const canvas = this.canvasRef.nativeElement;
    const rect = canvas.getBoundingClientRect();
    this.mouse.set(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
  }

  private onClick(e: MouseEvent): void {
    // this.mouse is kept current by onMouseMove — reuse it directly.
    this.raycaster.setFromCamera(this.mouse, this.ctx.camera);

    if (this.currentFocusedIcon) this.currentFocusedIcon = null;

    // Icon pick meshes
    if (this.ctx.iconPickMeshes.length > 0) {
      const iconHits = this.raycaster
        .intersectObjects(this.ctx.iconPickMeshes, false)
        .filter((h) => {
          let obj: THREE.Object3D | null = h.object;
          while (obj) {
            if (!obj.visible) return false;
            obj = obj.parent;
          }
          return true;
        });
      if (iconHits.length > 0) {
        const position = new THREE.Vector3();
        iconHits[0].object.getWorldPosition(position).add(new THREE.Vector3(250, 0, -150));
        this.panCameraTo(position, new THREE.Vector3(1000, 500, 1000));
        this.currentFocusedIcon = iconHits[0].object;
        return;
      }
    }

    // ground-plane traffic jam painting (debug only)
    if (this.pickPlane) {
      const hits = this.raycaster.intersectObject(this.pickPlane);
      if (hits.length > 0) {
        const p = hits[0].point;
        drawTrafficjamToTexture(this.ctx, p.x, p.z, e.shiftKey ? 'white' : 'black');
      }
    }
  }

  private onResize(): void {
    const w = window.innerWidth,
      h = window.innerHeight;
    this.ctx.camera.aspect = w / h;
    this.ctx.camera.updateProjectionMatrix();
    this.ctx.renderer.setSize(w, h);
    this.ctx.renderer.setPixelRatio(window.devicePixelRatio);
    this.ctx.composer?.setSize(w, h);
    this.ctx.depthRT?.setSize(w, h);
    this.ctx.depthOutlinePass?.uniforms['resolution'].value.set(
      w * this.ctx.renderer.getPixelRatio(),
      h * this.ctx.renderer.getPixelRatio(),
    );
    this.ctx.fxaaPass?.uniforms['resolution'].value.set(
      1 / (w * this.ctx.renderer.getPixelRatio()),
      1 / (h * this.ctx.renderer.getPixelRatio()),
    );
    if (this.ctx.particleMaterial) {
      this.ctx.particleMaterial.uniforms['scale'].value = h;
    }
  }

  private updateFog(): void {
    const distanceNormalized = THREE.MathUtils.clamp(
      (this.ctx.controls.getDistance() / this.ctx.controls.maxDistance - 0.5) * 2,
      0,
      1,
    );
    (this.ctx.scene.fog as THREE.Fog).far = THREE.MathUtils.lerp(
      baseFog.far,
      20000,
      distanceNormalized,
    );
  }

  // ── Geo helpers ──────────────────────────────────────────────────────────────

  /** Convert lon/lat to the same world-space used by the GLB model. */
  private geoToWorld(lon: number, lat: number): THREE.Vector3 {
    const R = 6378137;
    const cx = ((MAP_CENTER_LON * Math.PI) / 180) * R;
    const cy = Math.log(Math.tan(Math.PI / 4 + (MAP_CENTER_LAT * Math.PI) / 180 / 2)) * R;
    const S = GLB_TRANSFORM.scale * 10;
    const mx = ((lon * Math.PI) / 180) * R;
    const my = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 180 / 2)) * R;
    return new THREE.Vector3(
      (mx - cx) * S + GLB_TRANSFORM.offsetX,
      0,
      -((my - cy) * S) + GLB_TRANSFORM.offsetZ,
    );
  }

  /** Resample a polyline to N evenly-spaced points by arc length. */
  private resamplePath(pts: THREE.Vector3[], count: number): THREE.Vector3[] {
    // Build cumulative distances
    const dists = [0];
    for (let i = 1; i < pts.length; i++) {
      dists.push(dists[i - 1] + pts[i].distanceTo(pts[i - 1]));
    }
    const totalLen = dists[dists.length - 1];
    if (totalLen === 0) return pts;

    const result: THREE.Vector3[] = [pts[0].clone()];
    let srcIdx = 0;
    for (let i = 1; i < count - 1; i++) {
      const targetDist = (i / (count - 1)) * totalLen;
      while (srcIdx < dists.length - 2 && dists[srcIdx + 1] < targetDist) srcIdx++;
      const segLen = dists[srcIdx + 1] - dists[srcIdx];
      const t = segLen > 0 ? (targetDist - dists[srcIdx]) / segLen : 0;
      result.push(pts[srcIdx].clone().lerp(pts[srcIdx + 1], t));
    }
    result.push(pts[pts.length - 1].clone());
    return result;
  }

  /** Log a simulation event to the HUD event feed. */
  private logSimEvent(guid: string, type: string, message: string): void {
    window.dispatchEvent(
      new CustomEvent('sim:eventLog', {
        detail: { guid, type, message, time: Date.now() },
      }),
    );
  }

  private syncHud(selectedId: number | null): void {
    window.dispatchEvent(
      new CustomEvent('hud:sync', {
        detail: { paths: [...this.importedPaths], selectedId },
      }),
    );
  }

  // ── Path import ────────────────────────────────────────────────────────────

  /** Handle gateway:routeGeojson — parse the FeatureCollection (with water stations) and dispatch hud:importPath. */
  private onRouteGeojson = (e: Event): void => {
    const fc = (e as CustomEvent).detail?.geojson;
    if (fc) visualizeRoutePlan(JSON.stringify(fc));
  };

  /** Handle gateway:trafficZones — place traffic-warning zone meshes at each affected intersection. */
  private onTrafficZones = async (e: Event): Promise<void> => {
    const { affectedIntersections, affectedSegments, closedSegments } = (e as CustomEvent)
      .detail as {
      affectedIntersections: AffectedIntersection[];
      affectedSegments: Array<{
        geometry?: {
          type?: string;
          coordinates?: [number, number][];
          properties?: { name: string };
        };
      }>;
      closedSegments?: Array<{
        geometry?: { type?: string; coordinates?: [number, number][] };
        properties?: { name: string };
      }>;
    };
    // if (!intersections?.length) return;

    for (const intersection of affectedIntersections ?? []) {
      this.updateTraffic(intersection, true);
    }

    for (const segment of affectedSegments ?? []) {
      await this.updateTrafficSegment(segment, true);
    }

    for (const segment of closedSegments ?? []) {
      await this.closeTrafficSegment(segment, true);
    }
  };

  private onImportPath = async (e: Event): Promise<void> => {
    const detail = (e as CustomEvent).detail as {
      coords: [number, number][];
      name: string;
      waterStations?: { id: number; mi: number; coords: [number, number] }[];
      medicalTents?: { id: number; mi: number; coords: [number, number] }[];
      crowdZones?: { id: number; mi: number; coords: [number, number] }[];
      showOldRoute?: boolean;
    };

    simLog.log(
      'PATH',
      detail.name,
      `coords=${detail.coords.length} waterStations=${detail.waterStations?.length ?? 0} medicalTents=${detail.medicalTents?.length ?? 0} crowdZones=${detail.crowdZones?.length ?? 0}`,
    );

    const rawPoints = detail.coords.map(([lon, lat]) => this.geoToWorld(lon, lat));
    if (rawPoints.length < 2) return;

    // Resample to ~200 evenly-spaced points — more points = tighter fit to roads.
    const points = this.resamplePath(rawPoints, 1000);

    // Tension near 1.0 keeps the spline tight to control points (no overshoot).
    const spline = new THREE.CatmullRomCurve3(points, false, 'catmullrom', 0.5);

    const rawWaterStationPoints = detail.waterStations?.map(({ coords: [lon, lat] }) =>
      this.geoToWorld(lon, lat),
    );
    const rawMedicalTentsPoints = detail.medicalTents?.map(({ coords: [lon, lat] }) =>
      this.geoToWorld(lon, lat),
    );
    const rawCrowdZonesPoints = detail.crowdZones?.map(({ coords: [lon, lat] }) =>
      this.geoToWorld(lon, lat),
    );

    // Station detection radius matches the rendered ground circle (PlaneGeometry 150x150 -> radius 75)
    const LOOKDEV_STATION_RADIUS = 75;
    this.importedStations = [];
    let stationIdx = 0;
    if (detail.waterStations) {
      for (const s of detail.waterStations) {
        this.importedStations.push(
          new SimpleStationZone(
            stationIdx++,
            'water_station',
            this.geoToWorld(s.coords[0], s.coords[1]),
            LOOKDEV_STATION_RADIUS,
            s.mi,
          ),
        );
      }
    }
    if (detail.medicalTents) {
      for (const s of detail.medicalTents) {
        this.importedStations.push(
          new SimpleStationZone(
            stationIdx++,
            'medical_tent',
            this.geoToWorld(s.coords[0], s.coords[1]),
            LOOKDEV_STATION_RADIUS,
            s.mi,
          ),
        );
      }
    }
    if (detail.crowdZones) {
      for (const s of detail.crowdZones) {
        this.importedStations.push(
          new SimpleStationZone(
            stationIdx++,
            'crowd_zone',
            this.geoToWorld(s.coords[0], s.coords[1]),
            LOOKDEV_STATION_RADIUS,
            s.mi,
          ),
        );
      }
    }

    // Store spline for runner route when simulation starts
    this.currentSpline = spline;

    // Compute route center and radius to frame the camera dynamically
    const bbox = new THREE.Box3();
    for (const p of spline.points) bbox.expandByPoint(p);
    const center = new THREE.Vector3();
    bbox.getCenter(center);
    const size = new THREE.Vector3();
    bbox.getSize(size);
    const radius = Math.max(size.x, size.z) * 0.5;
    // Camera offset: pull back and up proportional to route size
    const camOffset = new THREE.Vector3(-radius * 0.6, radius * 1.6, radius * 0.0);
    //await this.panCameraTo(center, camOffset);
    await this.panCameraTo(spline.points[0], new THREE.Vector3(-1000, 5000, 500), {
      speed: 1000,
      maxDuration: 5.0,
    });

    // Show the planning route only (white dotted line) — purple runner route starts when sim begins
    await this.initRoute(
      spline,
      rawWaterStationPoints,
      rawMedicalTentsPoints,
      rawCrowdZonesPoints,
      () => {
        this.stopFollowMesh();
        this.ctx.controls.autoRotate = this._autoPanning;
      },
    );

    await this.panCameraTo(center, camOffset, { speed: 500, maxDuration: 5.0 });

    // Re-apply current race-support and entertainment filter state to the freshly created zones.
    this.applyZoneVisibility();
    // After initRoute, the prior route becomes ctx.oldRoute (hidden by default); show it when requested.
    if (detail.showOldRoute !== false) {
      this.showOldRoute(true);
    }

    // Compute geodesic distance in miles
    const R_MI = 3958.8;
    let lengthMi = 0;
    for (let i = 1; i < detail.coords.length; i++) {
      const [lon1, lat1] = detail.coords[i - 1];
      const [lon2, lat2] = detail.coords[i];
      const dLat = ((lat2 - lat1) * Math.PI) / 180;
      const dLon = ((lon2 - lon1) * Math.PI) / 180;
      const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos((lat1 * Math.PI) / 180) *
          Math.cos((lat2 * Math.PI) / 180) *
          Math.sin(dLon / 2) ** 2;
      lengthMi += 2 * R_MI * Math.asin(Math.sqrt(a));
    }

    // Store length and reset path adapter (will be created lazily when runners are added)
    this.importedLengthMi = lengthMi;
    this.lookdevPath = null;

    // Track path for HUD sync
    const id = this.nextPathId++;
    this.importedPaths.push({
      id,
      name: detail.name || 'Route',
      lengthMi: Math.round(lengthMi),
      colorHex: '#4d96ff',
      waterStationCount: detail.waterStations?.length ?? 0,
    });
    this.syncHud(id);
  };

  // ── Simulation runner handlers ─────────────────────────────────────────────

  /** Handle sim:spawnRunners — same visual flow as debugStartRunners. */
  private onSimSpawnRunners = async (e: Event): Promise<void> => {
    const detail = (e as CustomEvent).detail as { sessionIds: string[]; targetGuid: string };
    if (this.currentSpline) {
      await this.initRunnerRoute(this.currentSpline);
    }
    if (!this.ctx.runnerRoute) return;

    if (!this.lookdevPath && this.ctx.runnerRouteLUT.length > 0) {
      this.lookdevPath = new CatmullRomPathAdapter(
        this.ctx.runnerRouteLUT,
        this.importedLengthMi,
        this.importedStations,
      );
    }
    if (!this.lookdevPath) return;

    // Pan camera to route start (same offset as debugStartRunners)
    const offset = new THREE.Vector3(1000, 4000, 1000);
    if (this.currentSpline) {
      await this.panCameraTo(this.currentSpline.points[0], offset);
    }

    this.runnerManager.simTargetGuid = detail.targetGuid;
    let firstRunnerMesh: THREE.Mesh | null = null;

    for (let i = 0; i < detail.sessionIds.length; i++) {
      const id = detail.sessionIds[i];
      const guid = `sim-${id}`;
      if (this.runnerManager.getRunner(guid)) continue;

      const mesh = await this.initRunner();
      const ri = this.ctx.runners.indexOf(mesh);
      if (ri !== -1) this.ctx.runners.splice(ri, 1);
      this.setRunnerColor(mesh, 0xffffff);
      const sidewaysOffset = ((mesh.userData['random'] as number) - 0.5) * 15;

      this.runnerManager.addRunnerWithGuid(
        guid,
        this.lookdevPath,
        {
          effectiveMph: Math.max(0.01, 0) * RUNNER_SPEED_SCALE,
          simDistanceIntegrator: this.simSpeedMultiplier,
        },
        '#ffffff',
        {
          mesh,
          sidewaysOffset,
        },
      );

      if (!firstRunnerMesh) firstRunnerMesh = mesh;
    }

    // Follow the first runner with auto-rotate (same as debugStartRunners)
    if (firstRunnerMesh) {
      this.followMesh(firstRunnerMesh, offset, this._autoPanning);
    }
  };

  private _firstRunnerAdded = false;
  private _simAllFinished = false;
  private _debugRaceActive = false;
  private _simGeneration = 0;

  private onAddSimRunner = async (e: Event): Promise<void> => {
    const detail = (e as CustomEvent).detail as {
      guid: string;
      color: string;
      velocity?: number;
      distanceMi?: number;
      progress?: number;
    };

    if (this.runnerManager.getRunner(detail.guid)) return;

    const isFirst = !this._firstRunnerAdded;
    if (isFirst) {
      this._firstRunnerAdded = true;
      this._simAllFinished = false;
      this._simGeneration++;
      this._pendingGatewaySimUpdates.clear();
      for (const mesh of this._simRunnerMeshes) {
        mesh.visible = false;
        this.ctx.scene.remove(mesh);
        const ri = this.ctx.runners.indexOf(mesh);
        if (ri !== -1) this.ctx.runners.splice(ri, 1);
      }
      this._simRunnerMeshes = [];
      this.runnerManager.dispose();
      this.runnerManager = new RunnerManager(this.ctx.scene);
      removeRunnerRoute(this.ctx);
      this.lookdevPath = null;
    }

    const gen = this._simGeneration;

    if (!this.ctx.runnerRoute && this.currentSpline) {
      await this.initRunnerRoute(this.currentSpline);
    }
    if (gen !== this._simGeneration) {
      removeRunnerRoute(this.ctx);
      return;
    }
    if (!this.ctx.runnerRoute) return;

    if (!this.lookdevPath && this.ctx.runnerRouteLUT.length > 0) {
      this.lookdevPath = new CatmullRomPathAdapter(
        this.ctx.runnerRouteLUT,
        this.importedLengthMi,
        this.importedStations,
      );
    }
    if (!this.lookdevPath) return;

    if (isFirst && this.currentSpline && !this.ctx.raceStartState) {
      const offset = new THREE.Vector3(1000, 4000, 1000);
      void this.panCameraTo(this.currentSpline.points[0], offset);
    }

    const mesh = await this.initRunner();
    this.setRunnerColor(mesh, 0xffffff);
    const sidewaysOffset = ((mesh.userData['random'] as number) - 0.5) * 15;

    const spawnVel = detail.velocity ?? 0;
    const mph = Math.max(0.01, spawnVel) * RUNNER_SPEED_SCALE;
    const rate = (mph / MARATHON_DISTANCE_MI) * this.simSpeedMultiplier;
    const pathLen = this.lookdevPath!.getTotalLength();
    if (pathLen <= 0) {
      simLog.log('ERROR', detail.guid, `pathLen is ${pathLen}, cannot spawn runner`);
      return;
    }
    const initialMi =
      detail.distanceMi ??
      (detail.progress != null ? detail.progress * MARATHON_DISTANCE_MI : undefined);
    this.runnerManager.addRunnerWithGuid(
      detail.guid,
      this.lookdevPath,
      {
        effectiveMph: mph,
        simDistanceIntegrator: this.simSpeedMultiplier,
        distanceMi: initialMi,
      },
      '#ffffff',
      {
        mesh,
        sidewaysOffset,
      },
    );
    mesh.userData['guid'] = detail.guid;
    this._simRunnerMeshes.push(mesh);
    simLog.log(
      'SPAWN',
      detail.guid,
      `vel=${spawnVel} mph=${mph.toFixed(2)} rate=${rate.toFixed(6)} pathLen=${pathLen.toFixed(1)}`,
    );
    const pending = this._pendingGatewaySimUpdates.get(detail.guid);
    if (pending) {
      this._pendingGatewaySimUpdates.delete(detail.guid);
      this.applyGatewaySimRunnerUpdate(detail.guid, pending);
    }
  };

  private mergePendingGatewaySimUpdate(
    guid: string,
    partial: { velocity?: number; water?: number },
  ): void {
    const cur = this._pendingGatewaySimUpdates.get(guid) ?? {};
    if (partial.velocity !== undefined) cur.velocity = partial.velocity;
    if (partial.water !== undefined) cur.water = partial.water;
    this._pendingGatewaySimUpdates.set(guid, cur);
  }

  /**
   * Apply gateway telemetry (velocity, water). Distance along the route is integrated
   * locally from effective velocity and simSpeedMultiplier — not snapped from the backend.
   */
  private applyGatewaySimRunnerUpdate(
    guid: string,
    detail: { velocity?: number; water?: number },
  ): void {
    const runner = this.runnerManager.getRunner(guid);
    if (!runner) return;

    if (detail.velocity !== undefined) {
      const prevNv = runner.getVelocity();
      this.runnerManager.setVelocity(guid, detail.velocity);
      this.runnerManager.setSimDistanceIntegrator(guid, this.simSpeedMultiplier);
      if (Math.abs(detail.velocity - prevNv) > 1e-4) {
        const mph = detail.velocity * RUNNER_SPEED_SCALE;
        const rate = (mph / MARATHON_DISTANCE_MI) * this.simSpeedMultiplier;
        simLog.log('VEL', guid, `mph=${mph.toFixed(3)} rate=${rate.toFixed(6)}`);
      }
    }

    if (detail.water !== undefined) {
      const prev = runner.getWater();
      this.runnerManager.setWater(guid, detail.water);
      if (Math.abs(detail.water - prev) > 0.1) {
        simLog.log('WATER', guid, `${prev.toFixed(1)} -> ${detail.water.toFixed(1)}`);
      }
    }
  }

  private onUpdateSimRunner = (e: Event): void => {
    const detail = (e as CustomEvent).detail as {
      guid: string;
      velocity?: number;
      water?: number;
      _fromGateway?: boolean;
    };

    // Only process events from the gateway — ignore our own HUD sync events
    // to prevent a velocity feedback loop (scaled velocity gets re-scaled).
    if (!detail._fromGateway) return;

    const runner = this.runnerManager.getRunner(detail.guid);
    if (!runner) {
      this.mergePendingGatewaySimUpdate(detail.guid, detail);
      return;
    }

    this._pendingGatewaySimUpdates.delete(detail.guid);
    this.applyGatewaySimRunnerUpdate(detail.guid, detail);
  };

  private onSimRunnerEvent = (e: Event): void => {
    const detail = (e as CustomEvent).detail as { guid: string; event: string };
    const runner = this.runnerManager.getRunner(detail.guid);
    if (!runner) return;
    const mesh = runner.getMesh();
    const mat = mesh.material as THREE.MeshStandardMaterial;

    // Flash color based on event type
    switch (detail.event) {
      case 'water_station':
        mat.emissive.set(0x00e4e4); // cyan
        break;
      case 'exhausted':
        mat.emissive.set(0xffd93d); // yellow
        break;
      case 'collapsed':
        mat.emissive.set(0xff4444); // red
        runner.freeze(true); // DNF
        return; // don't restore color for collapsed
    }
  };

  private onFocusSimRunner = (e: Event): void => {
    const guid = (e as CustomEvent).detail?.guid as string;
    const mesh = this._simRunnerMeshes.find((m) => m.userData['guid'] === guid);
    if (!mesh) return;

    this._followLeaderActive = false;
    this.followGuid = guid;
    if (this.ctx.cameraFollow) {
      swapFollowTarget(this.ctx, mesh);
    } else {
      followMesh(this.ctx, mesh, new THREE.Vector3(1000, 4000, 1000), this._autoPanning);
    }
  };

  private onRemoveSimRunner = (e: Event): void => {
    const guid = (e as CustomEvent).detail?.guid as string | undefined;
    if (!guid) return;
    this._pendingGatewaySimUpdates.delete(guid);
    this.runnerManager.removeRunner(guid);
  };

  private onFollowLeader = (): void => {
    this.followLeader();
  };

  private onFollowRandomRunner = (): void => {
    this.followRandomRunner();
  };

  private onRemoveAllPaths = (): void => {
    this.disposeRoutes();
    this.importedPaths = [];
    this.ctx.closedTrafficSegmentMasks = [];
    this.removeAllTrafficIcons();
    this.syncHud(null);
  };

  private removeAllTrafficIcons = () => {};

  private onSimRaceStarted = (e: Event): void => {
    const detail = (e as CustomEvent).detail as {
      speedMultiplier?: number;
      simDistanceIntegrator?: number;
      _debugRace?: boolean;
    };
    this._debugRaceActive = !!detail?._debugRace;
    const speedMul = detail?.speedMultiplier ?? 1;
    const integrator = detail?.simDistanceIntegrator;
    const base =
      typeof integrator === 'number' && integrator > 0 && Number.isFinite(integrator)
        ? integrator
        : ViewportComponent.SIM_SPEED / 3600;
    this.simSpeedMultiplier = base * speedMul;
    this._followLeaderActive = false;
    this._simAllFinished = false;

    if (this.ctx.cameraFollow) {
      stopFollowMesh(this.ctx);
    }

    if (this.ctx.oldRoute) {
      this.ctx.oldRoute.visible = false;
    }

    if (this.currentSpline) {
      const bbox = new THREE.Box3();
      for (const p of this.currentSpline.points) bbox.expandByPoint(p);
      const center = new THREE.Vector3();
      bbox.getCenter(center);
      const size = new THREE.Vector3();
      bbox.getSize(size);
      const radius = Math.max(size.x, size.z) * 0.5;
      const camOffset = new THREE.Vector3(-radius * 0.6, radius * 1.0, radius * 0.5);
      this.startOverviewSequence(center, camOffset);
    }

    for (const info of this.runnerManager.getRunnerInfos()) {
      this.runnerManager.setSimDistanceIntegrator(info.guid, this.simSpeedMultiplier);
    }
  };

  private onSimFinished = () => {
    for (const info of this.runnerManager.getRunnerInfos()) {
      const runner = this.runnerManager.getRunner(info.guid);
      if (!runner) continue;
      runner.freeze();
      const mesh = runner.getMesh();
      mesh.userData['_finished'] = true;
      mesh.visible = false;
      const ri = this.ctx.runners.indexOf(mesh);
      if (ri !== -1) this.ctx.runners.splice(ri, 1);
      window.dispatchEvent(
        new CustomEvent('hud:updateSimRunner', {
          detail: {
            guid: info.guid,
            velocity: 0,
            progress: info.percentComplete / 100,
            water: runner.getWater(),
          },
        }),
      );
    }
    this._followLeaderActive = false;
    this._firstRunnerAdded = false;
    stopFollowMesh(this.ctx);
    this.setRaceComplete();
  };

  private onSimComplete = (): void => {
    this._pendingGatewaySimUpdates.clear();
    this.runnerManager.dispose();
    this.runnerManager = new RunnerManager(this.ctx.scene);
    this._simRunnerMeshes = [];

    this.followGuid = null;
    this._followLeaderActive = false;
    this._firstRunnerAdded = false;
    this._simAllFinished = false;
    this._debugRaceActive = false;
    this.cancelPostFinishSequence();

    this.hadSimRunners = false;
    stopFollowMesh(this.ctx);
    this.updateRouteVisibility();
  };

  private onSimReset = (): void => {
    this._simGeneration++;
    import('../debug-race').then((m) => m.stopDebugRace());
    this._pendingGatewaySimUpdates.clear();
    this.runnerManager.dispose();
    this.runnerManager = new RunnerManager(this.ctx.scene);
    this._simRunnerMeshes = [];
    this._simSpeedCalibrated = false;
    this.simSpeedMultiplier = ViewportComponent.SIM_SPEED / 3600;
    simLog.clear();

    this.followGuid = null;
    this._followLeaderActive = false;
    this._firstRunnerAdded = false;
    this._simAllFinished = false;
    this._debugRaceActive = false;

    this.hadSimRunners = false;
    stopFollowMesh(this.ctx);
    this.clearAllRoutes();
    this.updateRouteVisibility();
  };

  private onRemovePath = (e: Event): void => {
    const id = (e as CustomEvent).detail?.id;
    this.importedPaths = this.importedPaths.filter((p) => p.id !== id);
    if (this.importedPaths.length === 0) {
      this.disposeRoutes();
    }
    this.syncHud(this.importedPaths.length > 0 ? this.importedPaths[0].id : null);
  };

  private disposeRoutes(): void {
    this.clearAllRoutes();
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  // Draws out a planned route
  public initRoute(
    spline: THREE.CatmullRomCurve3,
    waterStationPoints?: THREE.Vector3[],
    medicalTentsPoints?: THREE.Vector3[],
    crowdZonesPoints?: THREE.Vector3[],
    onDrawComplete?: () => void,
  ): Promise<void> {
    return initRoute(
      this.ctx,
      spline,
      waterStationPoints,
      medicalTentsPoints,
      crowdZonesPoints,
      onDrawComplete,
    );
  }

  // Shows the previous planned route if existing
  public showOldRoute(show: boolean) {
    return showOldRoute(this.ctx, show);
  }

  // Draws out a runner route
  public initRunnerRoute(spline: THREE.CatmullRomCurve3): Promise<void> {
    return initRunnerRoute(this.ctx, spline);
  }

  // Sets the race complete, solid gradient cycling the route
  public setRaceComplete(): Promise<void> {
    return setRaceComplete(this.ctx);
  }

  // Creates a single runner
  public initRunner(): Promise<THREE.Mesh> {
    return initRunner(this.ctx);
  }

  // Helper to clear routes
  public clearAllRoutes(): void {
    removeRoute(this.ctx);
    removeRunnerRoute(this.ctx);
  }

  public setRunnerColor(runner: THREE.Mesh, color: number): Promise<void> {
    return setRunnerColor(this.ctx, runner, color);
  }

  public updateRunner(runner: THREE.Mesh, normalizedPosition: number): Promise<void> {
    return updateRunner(this.ctx, runner, normalizedPosition);
  }

  // Takes a world position, draws to a texture mask to either block or unblock traffic
  public async updateTraffic(
    intersection: AffectedIntersection,
    blockTraffic: boolean,
  ): Promise<void> {
    const [lon, lat] = intersection.coordinates;
    const worldPosition = lngLatToWorld(lon, lat);

    return drawTrafficjamToTexture(
      this.ctx,
      worldPosition.x,
      worldPosition.z,
      blockTraffic ? 'white' : 'black',
    );
  }

  /** Paints a road segment (GeoJSON LineString) onto the traffic mask texture. */
  public async updateTrafficSegment(
    feature: {
      geometry?: { type?: string; coordinates?: [number, number][] };
      properties?: { name: string };
    },
    blockTraffic: boolean,
  ): Promise<void> {
    const geom = feature.geometry;
    if (!geom || geom.type !== 'LineString' || !geom.coordinates || geom.coordinates.length < 2) {
      return;
    }

    const worldPoints = geom.coordinates.map(([lon, lat]) => {
      const w = lngLatToWorld(lon, lat);
      return { x: w.x, z: w.z };
    });
    const cx = worldPoints.reduce((sum, p) => sum + p.x, 0) / worldPoints.length;
    const cz = worldPoints.reduce((sum, p) => sum + p.z, 0) / worldPoints.length;

    return drawTrafficjamSegmentToTexture(this.ctx, worldPoints, blockTraffic ? 'white' : 'black');
  }

  /** Paints a road segment (GeoJSON LineString) onto the traffic mask texture. */
  public async closeTrafficSegment(
    feature: {
      geometry?: { type?: string; coordinates?: [number, number][] };
      properties?: { name: string };
    },
    closeTraffic: boolean,
  ): Promise<void> {
    const geom = feature.geometry;
    if (!geom || geom.type !== 'LineString' || !geom.coordinates || geom.coordinates.length < 2) {
      return;
    }

    const worldPoints = geom.coordinates.map(([lon, lat]) => {
      const w = lngLatToWorld(lon, lat);
      return { x: w.x, z: w.z };
    });
    const cx = worldPoints.reduce((sum, p) => sum + p.x, 0) / worldPoints.length;
    const cz = worldPoints.reduce((sum, p) => sum + p.z, 0) / worldPoints.length;

    return drawRouteSuppressSegmentToTexture(
      this.ctx,
      worldPoints,
      closeTraffic ? 'white' : 'black',
    );
  }

  // Pans the camera to a target position with a offset, time is based on xz distance
  public panCameraTo(
    targetPosition: THREE.Vector3,
    cameraOffset: THREE.Vector3,
    options?: { speed?: number; minDuration?: number; maxDuration?: number },
  ): Promise<void> {
    return panCameraTo(this.ctx, targetPosition, cameraOffset, options);
  }

  // Makes the camera follow a mesh with an offset, until stopFollowMesh() is called
  public followMesh(
    mesh: THREE.Object3D,
    offset: THREE.Vector3,
    autoRotate = false,
    offsetTransition?: {
      delay: number;
      duration: number;
      toOffset: THREE.Vector3;
      releaseDelay?: number;
    },
    damping = 2,
  ): void {
    followMesh(this.ctx, mesh, offset, autoRotate, offsetTransition, damping);
  }

  public stopFollowMesh(): void {
    stopFollowMesh(this.ctx);
    this.ctx.controls.autoRotate = this._autoPanning;
  }

  /** Point the camera at the current race leader (highest % complete, still running). */
  public followLeader(): void {
    let leaderMesh: THREE.Mesh | null = null;
    let leaderTime = -1;
    for (const mesh of this._simRunnerMeshes) {
      if (mesh.userData['_finished']) continue;
      const guid = mesh.userData['guid'] as string;
      const r = this.runnerManager.getRunner(guid);
      const t = r?.getT() ?? 0;
      if (t > leaderTime) {
        leaderTime = t;
        leaderMesh = mesh;
      }
    }
    if (!leaderMesh) return;
    this.cancelPostFinishSequence();
    this._followLeaderActive = true;
    this.followGuid = leaderMesh.userData['guid'] as string;
    if (this.ctx.cameraFollow) {
      swapFollowTarget(this.ctx, leaderMesh);
    } else {
      followMesh(this.ctx, leaderMesh, new THREE.Vector3(-1000, 4000, 1000), this._autoPanning);
    }
  }

  /** Point the camera at a random runner that is still running. */
  public followRandomRunner(): void {
    const infos = this.runnerManager
      .getRunnerInfos()
      .filter((i) => i.status === 'running' && i.percentComplete < 100 && i.guid !== this.followGuid);
    if (infos.length === 0) return;
    const chosen = infos[Math.floor(Math.random() * infos.length)];
    const runner = this.runnerManager.getRunner(chosen.guid);
    if (!runner) return;
    this._followLeaderActive = false;
    this.followGuid = chosen.guid;
    if (this.ctx.cameraFollow) {
      swapFollowTarget(this.ctx, runner.getMesh());
    } else {
      followMesh(
        this.ctx,
        runner.getMesh(),
        new THREE.Vector3(-1000, 4000, 1000),
        this._autoPanning,
      );
    }
  }

  private onFilterChanged = (e: Event): void => {
    const detail = (e as CustomEvent).detail;

    if (detail.id === 'camera') {
      if (this.ctx.cameraFollow) {
        stopFollowMesh(this.ctx);
        this._followLeaderActive = false;
        this.followGuid = null;
        window.dispatchEvent(new CustomEvent('viewport:followStopped'));
      }
      this.cancelPostFinishSequence();
      switch (detail.index) {
        case 0:
          this.cameraA();
          break;
        case 1:
          this.cameraB();
          break;
        case 2:
          this.cameraTopRoute();
          break;
      }
    }

    if (detail.id === 'race-support') {
      this._raceSupportVisible = detail.active as boolean;
      this.applyZoneVisibility();
      if (!this._raceSupportVisible) {
        this.ctx.hoveredIcon = null;
        this.currentFocusedIcon = null;
      }
    }

    if (detail.id === 'entertainment') {
      this._entertainmentVisible = detail.active as boolean;
      this.applyZoneVisibility();
      if (!this._entertainmentVisible) {
        this.ctx.hoveredIcon = null;
        this.currentFocusedIcon = null;
      }
    }

    if (detail.id === 'panning') {
      this._autoPanning = detail.index === 0;
      this.ctx.controls.autoRotate = this._autoPanning;
      if (this.ctx.cameraFollow) {
        this.ctx.cameraFollow.autoRotate = this._autoPanning;
      }
    }
  };

  private startOverviewSequence(target: THREE.Vector3, offset: THREE.Vector3): void {
    this._postFinishSequence = true;
    if (this._overviewTarget) this.ctx.scene.remove(this._overviewTarget);
    this._overviewTarget = new THREE.Object3D();
    this._overviewTarget.position.copy(target);
    this.ctx.scene.add(this._overviewTarget);
    followMesh(this.ctx, this._overviewTarget, offset, false, undefined, 0.5);
    this.ctx.controls.enabled = true;
    this.ctx.controls.autoRotate = this._autoPanning;
  }

  private startPostFinishSequence(): void {
    if (!this.ctx.currentRouteGoal) return;

    const finishPos = new THREE.Vector3();
    this.ctx.currentRouteGoal.getWorldPosition(finishPos);

    const runnersCentroid = new THREE.Vector3();
    let runnerCount = 0;
    for (const m of this._simRunnerMeshes) {
      if (m.userData['_finished']) continue;
      runnersCentroid.add(m.position);
      runnerCount++;
    }

    let offset: THREE.Vector3;
    if (runnerCount > 0) {
      runnersCentroid.divideScalar(runnerCount);
      const dir = new THREE.Vector3().subVectors(finishPos, runnersCentroid);
      dir.y = 0;
      if (dir.lengthSq() < 1) dir.set(-1, 0, -1);
      dir.normalize();
      const side = new THREE.Vector3(dir.z, 0, -dir.x);
      offset = new THREE.Vector3()
        .addScaledVector(dir, 2700)
        .addScaledVector(side, 1350)
        .add(new THREE.Vector3(0, 3000, 0));
    } else {
      offset = new THREE.Vector3(-2700, 3000, 2700);
    }

    this.startOverviewSequence(finishPos, offset);
  }

  private cancelPostFinishSequence(): void {
    if (!this._postFinishSequence) return;
    this._postFinishSequence = false;
    stopFollowMesh(this.ctx);
    if (this._overviewTarget) {
      this.ctx.scene.remove(this._overviewTarget);
      this._overviewTarget = null;
    }
    this.ctx.controls.autoRotate = this._autoPanning;
  }

  /** Apply current race-support and entertainment filter visibility to all zone meshes. */
  private applyZoneVisibility(): void {
    for (const pick of this.ctx.iconPickMeshes) {
      const type = pick.userData['type'];
      const pin = pick.parent?.parent;
      if (!pin) continue;
      if (type === 'water_station' || type === 'medical') {
        pin.visible = this._raceSupportVisible;
      } else if (type === 'crowd_zone') {
        pin.visible = this._entertainmentVisible;
      }
    }
  }

  // Helpers, preset camera positions
  public cameraTopView(): void {
    this.panCameraTo(new THREE.Vector3(1000, 0, -1700), new THREE.Vector3(3200, 6300, 2000));
  }

  public cameraMidView(): void {
    this.panCameraTo(new THREE.Vector3(900, 0, -600), new THREE.Vector3(1500, 1300, 1600));
  }

  public cameraCloseView(): void {
    this.panCameraTo(new THREE.Vector3(420, 0, -380), new THREE.Vector3(-2700, 500, 1000));
  }

  public cameraA(): void {
    this.panCameraTo(new THREE.Vector3(-180, 0, 1400), new THREE.Vector3(-5000, 2500, -5600));
  }

  public cameraB(): void {
    this.panCameraTo(new THREE.Vector3(1700, 0, -1100), new THREE.Vector3(3200, 2900, 6200));
  }

  public cameraTopRoute(): void {
    this.panCameraTo(new THREE.Vector3(1600, 0, 400), new THREE.Vector3(-5200, 8500, 0));
  }

  // Gets a zone or warning object, you need to manually add these to the scene
  public getWarning(color: number): Promise<THREE.Mesh> {
    return getWarning(this.ctx, color);
  }

  public getInfoIcon(): Promise<THREE.Mesh> {
    return getInfoIcon(this.ctx);
  }

  public getWaterZone(): Promise<THREE.Mesh> {
    return getWaterZone(this.ctx);
  }

  public getMedicalZone(): Promise<THREE.Mesh> {
    return getMedicalZone(this.ctx);
  }

  public getCrowdZone(): Promise<THREE.Mesh> {
    return getCrowdZone(this.ctx);
  }

  public getToiletZone(): Promise<THREE.Mesh> {
    return getToiletZone(this.ctx);
  }

  // When removing a zone added by any of the above, pipe it through this function
  // so they get removed from runner<->zone collision checks.
  public removeZone(mesh: THREE.Mesh) {
    return removeZone(this.ctx, mesh);
  }

  public getTrafficZones(intersections: AffectedIntersection[]): Promise<THREE.Mesh[]> {
    return getTrafficZones(this.ctx, intersections);
  }

  // Gets the screen position of the hovered icon
  public getHoveredIconScreenSpacePosition(): Promise<THREE.Vector2> | null {
    if (this.ctx.hoveredIcon != null) {
      return getScreenSpacePosition(this.ctx, this.ctx.hoveredIcon);
    }
    return null;
  }

  // General helper to get screen space position of any mesh
  public getMeshScreenSpacePosition(mesh: THREE.Mesh): Promise<THREE.Vector2> | null {
    return getScreenSpacePosition(this.ctx, mesh);
  }

  // Sets the error state true or false, shows red vignette
  public setError(error: boolean) {
    return setError(this.ctx, error);
  }

  // Toggle to show or hide confetti
  public setConfetti(show: boolean): void {
    if (show) {
      if (!this.ctx.confettiMesh) {
        this.ctx.confettiMesh = createConfettiParticles();
        this.ctx.confettiMesh.position.set(0, 0, -800); // −Z is forward in camera space
        this.ctx.camera.add(this.ctx.confettiMesh);
      }
      (this.ctx.confettiMesh.material as THREE.ShaderMaterial).uniforms['uTime'].value = 0;
      (this.ctx.confettiMesh.material as THREE.ShaderMaterial).uniforms['uAlpha'].value = 0;
    } else {
      if (this.ctx.confettiMesh) {
        this.ctx.camera.remove(this.ctx.confettiMesh);
        this.ctx.confettiMesh = null;
      }
    }
  }

  private onKeyDown = (e: KeyboardEvent): void => {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (e.key === 'i' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      this.startCameraIntro();
    }
  };

  // Starts the intro
  public startCameraIntro(): Promise<void> {
    const overlay = this.introOverlayRef.nativeElement;
    // Disable transition, snap to fully visible, then re-enable it so the
    // fade-out plays from opacity:1 rather than from whatever it was before.
    overlay.style.transition = 'none';
    overlay.style.opacity = '1';
    requestAnimationFrame(() => {
      overlay.style.transition = '';
      overlay.style.opacity = '0';
    });
    return startCameraIntro(this.ctx);
  }

  // Starts the race
  public async startRaceSetupCamera(): Promise<void> {
    if (this.currentSpline) {
      // set the camera 7% down the spline, looking at the start
      const start = this.currentSpline.getPoint(0);
      const cameraPosition = this.currentSpline.getPoint(0.07);
      const offset = cameraPosition.sub(start).add(new THREE.Vector3(0, 1500, 0));

      this.ctx.camera.position.copy(start.clone().add(offset));
      this.ctx.controls.target.copy(start);
      this.ctx.controls.update();

      await new Promise((resolve) => setTimeout(resolve, 1000));

      // add the start zone
      const startZone = await getStartZone(this.ctx);
      startZone.position.copy(start);
      this.ctx.scene.add(startZone);

      triggerStartZoneAnimation(this.ctx, startZone, 3, 0.8, 1.5, async () => {
        this.ctx.scene.remove(startZone);
        this.ctx.raceStartState = true;

        // start the race here, debug for now
        const { startDebugRace, isDebugRaceRunning } = await import('../debug-race');
        startDebugRace(10);

        // wait and then allow the camera switch to follow a camera
        await new Promise((resolve) => setTimeout(resolve, 2000));
        this.ctx.raceStartState = false;
        this._followLeaderActive = true;
      });
    }
  }

  private onGiveRunnersThoughts() {
    this.runnersHaveThoughts = true;
  }
  private onRemoveRunnersThoughts() {
    this.runnersHaveThoughts = false;
  }

  // Starts the outro
  /*public startOutro() {
    return startOutro(this.ctx);
  }*/

  // ── Auto-capture ─────────────────────────────────────────────────────────────

  private async startAutoCapture(
    duration: number,
    runnerCount: number,
    label: string,
    follow: boolean,
  ): Promise<void> {
    // 1. Load route from debug spline #2 (standard benchmark route)
    const spline = this.debugSplines?.[1];
    if (!spline) {
      console.error('[PerfAutoCapture] No debug spline available');
      return;
    }
    await this.initRunnerRoute(spline);
    if (this._destroyed) return;

    // 2. Spawn runners via debug race
    const { startDebugRace, isDebugRaceRunning } = await import('../debug-race');
    startDebugRace(runnerCount);

    // 3. Wait for all runner meshes to spawn (poll with timeout)
    const deadline = Date.now() + 15000;
    while (this._simRunnerMeshes.length < runnerCount && Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 200));
    }
    if (this._destroyed) return;
    console.log(`[PerfAutoCapture] ${this._simRunnerMeshes.length}/${runnerCount} runners spawned`);

    // 4. Activate follow-leader if requested
    if (follow) {
      this._followLeaderActive = true;
    }

    // 5. Wait for runners to spread out on the route
    await new Promise((r) => setTimeout(r, 3000));
    if (this._destroyed) return;

    // 6. Start capture
    if (!this.perfMonitor) {
      console.warn('[PerfAutoCapture] perfMonitor gone before capture started');
      return;
    }
    const camera = follow ? 'follow-leader' : 'static';
    const source: 'debug-race' | 'backend' = isDebugRaceRunning() ? 'debug-race' : 'backend';
    console.log(
      `[PerfAutoCapture] Starting ${duration}ms capture: ${label} (${camera}, ${runnerCount} runners)`,
    );
    this.perfMonitor.startSample(duration, label, runnerCount, camera, source, (snapshot) => {
      // Copy to clipboard if available
      if (navigator.clipboard) {
        navigator.clipboard
          .writeText(JSON.stringify(snapshot, null, 2))
          .then(() => console.log('[PerfAutoCapture] Snapshot copied to clipboard'))
          .catch((err) => console.warn('[PerfAutoCapture] clipboard write failed', err));
      }
    });
  }

  // ── Debug ────────────────────────────────────────────────────────────────────
  public async debugRoute(spline: THREE.CatmullRomCurve3): Promise<void> {
    //await this.panCameraTo(new THREE.Vector3(1000,0,-1000), new THREE.Vector3(1000,5000,1000));
    //await this.panCameraTo(new THREE.Vector3(-430,0,-500), new THREE.Vector3(5500,6000,3000));
    await this.panCameraTo(spline.points[0], new THREE.Vector3(3000, 4000, 1000));

    // clear any existing runners
    for (let i = 0; i < this.ctx.runners.length; i++) {
      this.ctx.scene.remove(this.ctx.runners[i]);
    }

    await this.initRoute(spline);

    const offsetFar = new THREE.Vector3(1500, 6000, 0);
    this.followMesh(this.ctx.drawRoute as THREE.Object3D, offsetFar, this._autoPanning, {
      delay: 0.0,
      duration: 2.0,
      toOffset: offsetFar,
      releaseDelay: 1,
    });

    return;
  }

  public async debugStartRunners(spline: THREE.CatmullRomCurve3): Promise<void> {
    const offsetStart = new THREE.Vector3(1000, 2000, 1000);
    const offsetClose = new THREE.Vector3(200, 800, 800);

    // clear any existing runners
    for (let i = 0; i < this.ctx.runners.length; i++) {
      this.ctx.scene.remove(this.ctx.runners[i]);
    }
    this.ctx.runners.length = 0;
    // show route
    await this.initRunnerRoute(spline);

    const startZone = await getStartZone(this.ctx);
    startZone.position.copy(spline.points[0]);
    if (this.ctx.runnerRoute) {
      this.ctx.runnerRoute.add(startZone);
    }
    await this.panCameraTo(spline.points[0], offsetStart);

    await new Promise((resolve) => setTimeout(resolve, 1000));

    this.ctx.startZoneAnimations.length = 0;

    triggerStartZoneAnimation(this.ctx, startZone, 3, 0.8, 1.5, async () => {
      if (this.ctx.runnerRoute) {
        this.ctx.runnerRoute.remove(startZone);
      }

      // start runners
      const numOfRunners = 10;
      let fastestSpeed = 0;
      let fastestRunner = null;
      for (let i = 0; i < numOfRunners; i++) {
        const runner = await this.initRunner();
        runner.userData['time'] = 0;
        runner.userData['speed'] = 0.01 + Math.random() * 0.02;
        if (runner.userData['speed'] > fastestSpeed) {
          fastestSpeed = runner.userData['speed'];
          fastestRunner = runner;
        }
        this.setRunnerColor(runner, 0xffffff);
        this.ctx.runners.push(runner);
      }
      // follow fastest runner
      //this.followMesh(fastestRunner as THREE.Object3D, offsetStart, true);
      await new Promise((resolve) => setTimeout(resolve, 500));
      this.followMesh(fastestRunner as THREE.Object3D, offsetStart, this._autoPanning, {
        delay: 4.0,
        duration: 2.5,
        toOffset: offsetClose,
        releaseDelay: 1,
      });
    });
  }

  // ----

  public async debugStartZone(): Promise<void> {
    const toilet = await getToiletZone(this.ctx);
    toilet.position.set(-700, 0, 0);
    this.ctx.scene.add(toilet);

    if (this.currentSpline) {
      await this.startRaceSetupCamera();
    } else {
      const startZone = await getStartZone(this.ctx);
      startZone.position.set(-500, 0, 0);
      this.ctx.scene.add(startZone);

      triggerStartZoneAnimation(this.ctx, startZone, 3, 0.8, 1.5, async () => {
        this.ctx.scene.remove(startZone);
      });
    }
  }

  public async debugSetRaceComplete(): Promise<void> {
    // clear any existing runners
    for (let i = 0; i < this.ctx.runners.length; i++) {
      this.ctx.scene.remove(this.ctx.runners[i]);
    }
    return this.setRaceComplete();
  }

  public async debugClearAllRoutes(): Promise<void> {
    this.clearAllRoutes();
    this.stopFollowMesh();
    // clear any existing runners
    for (let i = 0; i < this.ctx.runners.length; i++) {
      this.ctx.scene.remove(this.ctx.runners[i]);
    }
  }

  public async debugAddInfoIcons(): Promise<void> {
    // add some dummy info icons
    for (let i = 0; i < 15; i++) {
      const info = await getInfoIcon(this.ctx);
      info.position.set(Math.random() * 10000 - 5000, 0, Math.random() * 10000 - 5000);
      this.ctx.scene.add(info);
    }
  }

  private errorState = false;

  public debugToggleError(): void {
    this.errorState = !this.errorState;
    this.setError(this.errorState);
  }

  public debugStartCameraIntro(): Promise<void> {
    return this.startCameraIntro();
  }

  /*public debugStartOutro(): Promise<void> {
    return this.startOutro();
  }*/

  public debugShowOldRoute(): void {
    this.showOldRoute(true);
  }

  public debugConfetti(): void {
    if (this.ctx.confettiMesh) {
      this.setConfetti(false);
    } else {
      this.setConfetti(true);
    }
  }
}
