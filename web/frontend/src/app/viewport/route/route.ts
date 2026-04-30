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
import { Context } from '../context';
import {
  getStartGoal,
  getInfoIcon,
  getWaterZone,
  getMedicalZone,
  getCrowdZone,
  getPortableToiletZone,
} from './icons';
import { followMesh, stopFollowMesh, panCameraTo } from '../scene/scene';

// ── Main route ────────────────────────────────────────────────────────────────
/** Serializes initRoute so each import runs after the previous; overlapping calls must not skip _initRouteImpl or oldRoute is never set. */
let _initRouteChain: Promise<void> = Promise.resolve();

export function initRoute(
  ctx: Context,
  spline: THREE.CatmullRomCurve3,
  waterStationPoints?: THREE.Vector3[],
  rawMedicalTentsPoints?: THREE.Vector3[],
  rawCrowdZonesPoints?: THREE.Vector3[],
  rawPortableToiletsPoints?: THREE.Vector3[],
  onDrawComplete?: () => void,
): Promise<void> {
  const run = () =>
    _initRouteImpl(
      ctx,
      spline,
      waterStationPoints,
      rawMedicalTentsPoints,
      rawCrowdZonesPoints,
      rawPortableToiletsPoints,
      onDrawComplete,
    );
  const p = _initRouteChain.then(run, run);
  _initRouteChain = p.catch(() => {});
  return p;
}

async function _initRouteImpl(
  ctx: Context,
  spline: THREE.CatmullRomCurve3,
  waterStationPoints?: THREE.Vector3[],
  rawMedicalTentsPoints?: THREE.Vector3[],
  rawCrowdZonesPoints?: THREE.Vector3[],
  rawPortableToiletsPoints?: THREE.Vector3[],
  onDrawComplete?: () => void,
): Promise<void> {
  // Remove and dispose the previous old route
  if (ctx.oldRoute) {
    ctx.scene.remove(ctx.oldRoute);
    ctx.oldRoute.geometry?.dispose();
    (ctx.oldRoute.material as THREE.Material)?.dispose();
    ctx.oldRoute = null;
  }
  if (ctx.currentRoute) {
    ctx.oldRoute = ctx.currentRoute;
    for (let i = ctx.oldRoute.children.length - 1; i >= 0; i--) {
      ctx.oldRoute.remove(ctx.oldRoute.children[i]);
    }
    const oldMat = ctx.oldRoute.material as THREE.MeshStandardMaterial;
    oldMat.emissiveMap = null;
    oldMat.alphaMap = null;
    oldMat.emissiveIntensity = 1.0;
    oldMat.emissive = new THREE.Color(0x888888);
    oldMat.needsUpdate = true;
  }

  removeRunnerRoute(ctx);

  const splineLength = spline.getLength();
  const isKhum = ctx.sceneVariant === 'khum-airport';
  const routeTubeRadius = isKhum ? 3 : 12;
  const routeHeight = isKhum ? 6 : 15;
  const routeEmissiveIntensity = isKhum ? 5.0 : 20.0;

  ctx.routeStripeTexture = await ctx.textureLoader.loadAsync(
    '/assets/textures/dash_transparent.png',
  );
  ctx.routeStripeTexture.wrapT = ctx.routeStripeTexture.wrapS = THREE.RepeatWrapping;
  ctx.routeStripeTexture.offset.y = 0.5;
  ctx.routeStripeTexture.repeat.x = splineLength * 0.02;

  ctx.routeCompleteTexture = await ctx.textureLoader.loadAsync(
    '/assets/textures/next_gradient.jpg',
  );
  ctx.routeCompleteTexture.wrapT = ctx.routeCompleteTexture.wrapS = THREE.RepeatWrapping;

  const routeMaterial = new THREE.MeshStandardMaterial({
    alphaMap: ctx.routeStripeTexture,
    color: new THREE.Color(0x000000),
    emissive: new THREE.Color(0xffffff),
    emissiveMap: ctx.routeCompleteTexture,
    emissiveIntensity: routeEmissiveIntensity,
    fog: false,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  const segments = Math.round(splineLength * 0.05);
  const tubeGeometry = new THREE.TubeGeometry(spline, segments, routeTubeRadius, 3, false);
  tubeGeometry.scale(1, 0.5, 1);
  ctx.currentRoute = new THREE.Mesh(tubeGeometry, routeMaterial);
  ctx.currentRoute.position.y = routeHeight;
  ctx.currentRoute.renderOrder = 2;
  ctx.currentRoute.geometry.setDrawRange(0, 0);
  ctx.scene.add(ctx.currentRoute);

  // Start / goal ground markers
  const start = await getStartGoal(ctx);
  start.position.copy(spline.points[0]).add(new THREE.Vector3(0, 10, 0));
  ctx.currentRoute.add(start);
  ctx.currentRouteGoal = await getStartGoal(ctx);
  ctx.currentRouteGoal.position
    .copy(spline.points[spline.points.length - 1])
    .add(new THREE.Vector3(0, 10, 0));
  ctx.currentRouteGoal.visible = false;
  ctx.currentRoute.add(ctx.currentRouteGoal);

  ctx.drawRoute = new THREE.Mesh(new THREE.IcosahedronGeometry(100));
  ctx.drawRoute.visible = false;
  ctx.drawRoute.position.copy(spline.points[0]);
  ctx.currentRoute.add(ctx.drawRoute);

  // Clean up old zones and their pick meshes before creating new ones
  for (const zone of ctx.zones) {
    zone.mesh.traverse((child: any) => {
      const idx = ctx.iconPickMeshes.indexOf(child);
      if (idx !== -1) ctx.iconPickMeshes.splice(idx, 1);
    });
  }
  ctx.zones = [];
  ctx.zonesMaterialArray = [];

  // Place imported water station and medical tent icons along the route
  if (waterStationPoints?.length) {
    for (const pos of waterStationPoints) {
      const icon = await getWaterZone(ctx);
      icon.position.copy(pos);
      icon.position.y = 0;
      ctx.currentRoute.add(icon);
    }
  }
  if (rawMedicalTentsPoints?.length) {
    for (const pos of rawMedicalTentsPoints) {
      const icon = await getMedicalZone(ctx);
      icon.position.copy(pos);
      icon.position.y = 0;
      ctx.currentRoute.add(icon);
    }
  }
  if (rawCrowdZonesPoints?.length) {
    for (const pos of rawCrowdZonesPoints) {
      const icon = await getCrowdZone(ctx);
      icon.position.copy(pos);
      icon.position.y = 0;
      ctx.currentRoute.add(icon);
    }
  }
  if (rawPortableToiletsPoints?.length) {
    for (const pos of rawPortableToiletsPoints) {
      const icon = await getPortableToiletZone(ctx);
      icon.position.copy(pos);
      icon.position.y = 0;
      ctx.currentRoute.add(icon);
    }
  }

  // Lights up the path
  drawSplineToTexture(ctx, spline);

  animateInRoute(ctx, splineLength, onDrawComplete);
}

export function removeRoute(ctx: Context): void {
  _initRouteChain = Promise.resolve();
  if (ctx.currentRoute) {
    ctx.currentRoute.traverse((child: any) => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        for (const m of mats) m?.dispose();
      }
    });
    ctx.scene.remove(ctx.currentRoute);
    ctx.currentRoute = null;
    ctx.currentRouteGoal = null;
  }
  if (ctx.oldRoute) {
    ctx.scene.remove(ctx.oldRoute);
    ctx.oldRoute.geometry?.dispose();
    (ctx.oldRoute.material as THREE.Material)?.dispose();
    ctx.oldRoute = null;
  }
  ctx.zones = [];
  ctx.zonesMaterialArray = [];
  if (ctx.heightFogLightUpMaterial) {
    ctx.heightFogLightUpMaterial.uniforms['routeMap'].value = null;
    ctx.heightFogLightUpMaterial.uniforms['routeLightUp'].value = 0;
  }
  if (ctx.ground) {
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveMap = null;
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveIntensity = 0;
    (ctx.ground.material as THREE.MeshStandardMaterial).needsUpdate = true;
  }
  if (ctx.roadsMaterial) {
    ctx.roadsMaterial.uniforms['maskMap1'].value = null;
  }
  ctx.closedTrafficSegmentMasks = [];
  ctx.routeCanvasTexture?.dispose();
  ctx.routeCanvasTexture = null;
  ctx.routeLightFade = null;
}

export function showOldRoute(ctx: Context, show: boolean): void {
  if (ctx.oldRoute) {
    ctx.oldRoute.visible = show;
  }
}

async function addDebugZones(
  ctx: Context,
  spline: THREE.CatmullRomCurve3,
  route: THREE.Mesh,
): Promise<void> {
  // Water station icons at 33 % and 67 % along the spline, for testing
  const wi1 = Math.round(spline.points.length * 0.33);
  const wi2 = Math.round(spline.points.length * 0.67);
  const water1 = await getWaterZone(ctx);
  water1.position.copy(spline.points[wi1]);
  water1.position.y = 0;
  route.add(water1);
  const water2 = await getWaterZone(ctx);
  water2.position.copy(spline.points[wi2]);
  water2.position.y = 0;
  route.add(water2);

  // Medical zones at 15 % and 50 % along the spline, for testing
  const mi1 = Math.round(spline.points.length * 0.15);
  const mi2 = Math.round(spline.points.length * 0.5);
  const medcial1 = await getMedicalZone(ctx);
  medcial1.position.copy(spline.points[mi1]);
  medcial1.position.y = 0;
  route.add(medcial1);
  const medcial2 = await getMedicalZone(ctx);
  medcial2.position.copy(spline.points[mi2]);
  medcial2.position.y = 0;
  route.add(medcial2);

  // Crowd zones at 10 % and 90 % along the spline, for testing
  const ci1 = Math.round(spline.points.length * 0.25);
  const ci2 = Math.round(spline.points.length * 0.9);
  const crowd1 = await getCrowdZone(ctx);
  crowd1.position.copy(spline.points[ci1]);
  crowd1.position.y = 0;
  route.add(crowd1);
  const crowd2 = await getCrowdZone(ctx);
  crowd2.position.copy(spline.points[ci2]);
  crowd2.position.y = 0;
  route.add(crowd2);
}

// ── Runner route ──────────────────────────────────────────────────────────────

let _initRunnerRoutePromise: Promise<void> | null = null;

let _runnerRouteGeneration = 0;

export function initRunnerRoute(ctx: Context, spline: THREE.CatmullRomCurve3): Promise<void> {
  if (_initRunnerRoutePromise) return _initRunnerRoutePromise;
  _initRunnerRoutePromise = _initRunnerRouteImpl(ctx, spline).finally(() => {
    _initRunnerRoutePromise = null;
  });
  return _initRunnerRoutePromise;
}

async function _initRunnerRouteImpl(ctx: Context, spline: THREE.CatmullRomCurve3): Promise<void> {
  removeRunnerRoute(ctx);
  const gen = _runnerRouteGeneration;

  const splineLength = spline.getLength();

  ctx.routeRunnerTexture = await ctx.textureLoader.loadAsync('/assets/textures/race_gradient.jpg');
  if (gen !== _runnerRouteGeneration) return;
  ctx.routeRunnerTexture.wrapT = ctx.routeRunnerTexture.wrapS = THREE.RepeatWrapping;
  ctx.routeRunnerTexture.repeat.x = splineLength * 0.001;

  const runnerRouteMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(0x888888),
    emissive: new THREE.Color(0xba00ff),
    emissiveIntensity: 5.0,
    emissiveMap: ctx.routeRunnerTexture,
    fog: false,
    depthWrite: false,
    transparent: true,
    opacity: 0.5,
  });

  const segments = Math.round(splineLength * 0.05);
  const tubeGeometry = new THREE.TubeGeometry(spline, segments, 8, 3, false);
  tubeGeometry.scale(1, 0.5, 1);
  ctx.runnerRoute = new THREE.Mesh(tubeGeometry, runnerRouteMaterial);
  ctx.runnerRoute.position.y = 10;
  ctx.runnerRoute.renderOrder = 1;
  ctx.scene.add(ctx.runnerRoute);

  const start = await getStartGoal(ctx, true);
  if (gen !== _runnerRouteGeneration) {
    removeRunnerRoute(ctx);
    return;
  }
  start.position.copy(spline.points[0]).add(new THREE.Vector3(0, 10, 0));
  ctx.runnerRoute.add(start);

  const end = await getStartGoal(ctx);
  if (gen !== _runnerRouteGeneration) {
    removeRunnerRoute(ctx);
    return;
  }
  end.position.copy(spline.points[spline.points.length - 1]).add(new THREE.Vector3(0, 10, 0));
  ctx.runnerRoute.add(end);

  const DENSE_SAMPLES = 10000;
  const LUT_SIZE = 1000;

  const densePoints: THREE.Vector3[] = [];
  for (let i = 0; i <= DENSE_SAMPLES; i++) {
    densePoints.push(spline.getPoint(i / DENSE_SAMPLES));
  }

  const denseArcLengths: number[] = [0];
  for (let i = 1; i <= DENSE_SAMPLES; i++) {
    denseArcLengths.push(denseArcLengths[i - 1] + densePoints[i].distanceTo(densePoints[i - 1]));
  }
  const totalLength = denseArcLengths[DENSE_SAMPLES];

  ctx.runnerRouteLUT = [];
  const lutTmp = new THREE.Vector3();
  let di = 0;
  for (let i = 0; i <= LUT_SIZE; i++) {
    const targetLen = (i / LUT_SIZE) * totalLength;
    while (di < DENSE_SAMPLES - 1 && denseArcLengths[di + 1] < targetLen) di++;
    const segLen = denseArcLengths[di + 1] - denseArcLengths[di];
    const frac = segLen > 0 ? (targetLen - denseArcLengths[di]) / segLen : 0;
    lutTmp.lerpVectors(densePoints[di], densePoints[di + 1], frac);
    ctx.runnerRouteLUT.push(lutTmp.clone().add(ctx.runnerRoute!.position));
  }

  // Lights up the path
  drawSplineToTexture(ctx, spline);
}

export function removeRunnerRoute(ctx: Context): void {
  _runnerRouteGeneration++;
  _initRunnerRoutePromise = null;
  if (ctx.runnerRoute) {
    ctx.runnerRoute.traverse((child: any) => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        const mats = Array.isArray(child.material) ? child.material : [child.material];
        for (const m of mats) m?.dispose();
      }
    });
    ctx.scene.remove(ctx.runnerRoute);
    ctx.runnerRoute = null;
  }
  ctx.runnerRouteLUT = [];
  ctx.routeDraw = null;
  if (ctx.heightFogLightUpMaterial) {
    ctx.heightFogLightUpMaterial.uniforms['routeMap'].value = null;
    ctx.heightFogLightUpMaterial.uniforms['routeLightUp'].value = 0;
  }
  if (ctx.ground) {
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveMap = null;
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveIntensity = 0;
    (ctx.ground.material as THREE.MeshStandardMaterial).needsUpdate = true;
  }
  if (ctx.roadsMaterial) {
    ctx.roadsMaterial.uniforms['maskMap1'].value = null;
  }
  ctx.routeCanvasTexture?.dispose();
  ctx.routeCanvasTexture = null;
  ctx.routeLightFade = null;
}

export async function setRaceComplete(ctx: Context): Promise<void> {
  if (ctx.runnerRoute) {
    ctx.routeCompleteTexture = await ctx.textureLoader.loadAsync(
      '/assets/textures/next_gradient.jpg',
    );
    ctx.routeCompleteTexture.wrapT = ctx.routeCompleteTexture.wrapS = THREE.RepeatWrapping;
    (ctx.runnerRoute.material as THREE.MeshStandardMaterial).emissive = new THREE.Color(0xffffff);
    (ctx.runnerRoute.material as THREE.MeshStandardMaterial).emissiveMap = ctx.routeCompleteTexture;
    (ctx.runnerRoute.material as THREE.MeshStandardMaterial).emissiveIntensity = 15;
  }
  if (ctx.heightFogLightUpMaterial) {
    ctx.heightFogLightUpMaterial.uniforms['routeMap'].value = null;
  }
  if (ctx.ground) {
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveIntensity = 0;
  }
}

// ── Runner ─────────────────────────────────────────────────────────────────────

// Reusable vectors – allocated once to avoid GC pressure each frame.
const routePosition = new THREE.Vector3();
const routeDirection = new THREE.Vector3();
const routeBinormal = new THREE.Vector3();
const routeNormal = new THREE.Vector3();
const routeUp = new THREE.Vector3(0, 1, 0);
const routeMinOffset = new THREE.Vector3(0, 10, 0);
const routeLookAt = new THREE.Vector3();

export async function initRunner(ctx: Context): Promise<THREE.Mesh> {
  const runnerGeometry = new THREE.IcosahedronGeometry(8, 2);
  const mat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(0x000000),
    depthWrite: false,
    emissive: new THREE.Color(0xffffff),
    emissiveIntensity: 2.0,
    fog: false,
  });
  const runner = new THREE.Mesh(runnerGeometry, mat);
  runner.userData['random'] = Math.random();
  runner.userData['offset'] = new THREE.Vector3();
  runner.castShadow = false;
  runner.receiveShadow = false;
  ctx.scene.add(runner);
  ctx.runners.push(runner);
  return runner;
}

export function removeRunner(ctx: Context, runner: THREE.Mesh): void {
  ctx.scene.remove(runner);
  const idx = ctx.runners.indexOf(runner);
  if (idx !== -1) ctx.runners.splice(idx, 1);
}

export async function updateRunner(
  ctx: Context,
  runner: THREE.Mesh,
  normalizedPosition: number,
): Promise<void> {
  if (ctx.runnerRoute == null) return;
  normalizedPosition = Math.max(0, Math.min(1, normalizedPosition));
  const geometry = ctx.runnerRoute.geometry as THREE.TubeGeometry;
  geometry.parameters.path.getPointAt(normalizedPosition, routePosition);
  routePosition.add(ctx.runnerRoute.position);

  // Interpolate binormal along the tube segments for smooth rotation.
  const segments = geometry.binormals.length;
  const pickt = normalizedPosition * segments;
  const pick = Math.floor(pickt);
  const pickNext = Math.min(pick + 1, segments - 1);

  routeBinormal
    .subVectors(geometry.binormals[pickNext], geometry.binormals[pick])
    .multiplyScalar(pickt - pick)
    .add(geometry.binormals[pick]);

  geometry.parameters.path.getTangentAt(normalizedPosition, routeDirection);

  const multiplier = Math.min(normalizedPosition / 0.01, 1.0);
  const frequency = segments * 0.4;
  const offsetUp =
    20 *
    Math.abs(Math.sin(normalizedPosition * frequency * runner.userData['random'])) *
    multiplier;
  const offsetSide =
    20 * Math.cos(normalizedPosition * frequency * runner.userData['random']) * multiplier;

  routeNormal.copy(routeBinormal).cross(routeDirection);
  routePosition.add(routeMinOffset).add(routeUp.clone().multiplyScalar(offsetUp));
  routePosition.add(routeBinormal.clone().multiplyScalar(offsetSide));
  routePosition.add(runner.userData['offset']);
  routeLookAt.copy(routePosition).add(routeDirection.multiplyScalar(10));

  runner.lookAt(routeLookAt);
  runner.position.copy(routePosition);
}

export async function setRunnerColor(
  ctx: Context,
  runner: THREE.Mesh,
  color: number,
): Promise<void> {
  const material = runner.material as THREE.MeshStandardMaterial;
  material.emissive = new THREE.Color(color);
}

// ── Outro animation ───────────────────────────────────────────────────────────
/*
export async function startOutro(ctx: Context) {
  const outroSpline = new THREE.CatmullRomCurve3(
    [
      new THREE.Vector3(-3500, 0, -2480),
      new THREE.Vector3(-2500, 0, -2480),
      new THREE.Vector3(-1500, 0, -2480),
      new THREE.Vector3(-500, 0, -2450),
      new THREE.Vector3(-100, 15, -2430),
      new THREE.Vector3(100, 75, -2410),
      new THREE.Vector3(350, 25, -2400),
      new THREE.Vector3(880, 0, -2350),
      new THREE.Vector3(650, 0, -1900),
      new THREE.Vector3(500, 0, -1400),
      new THREE.Vector3(465, 0, -900),
      new THREE.Vector3(465, 0, 0),
      new THREE.Vector3(465, 0, 1000),
      new THREE.Vector3(465, 0, 2000),
      new THREE.Vector3(475, 0, 3000),
      new THREE.Vector3(485, 0, 3500),
    ],
    false,
    'catmullrom',
    0.5,
  );

  // clear any existing runners
  for (let i = 0; i < ctx.outroRunnerArray.length; i++) {
    const r = ctx.outroRunnerArray[i];
    ctx.scene.remove(r);
    const ri = ctx.runners.indexOf(r);
    if (ri !== -1) ctx.runners.splice(ri, 1);
  }
  ctx.outroRunnerArray = [];
  // show route
  await initRunnerRoute(ctx, outroSpline);
  // runners
  const scale = 1.75;
  const runner1 = await initRunner(ctx);
  runner1.userData['time'] = 0.37;
  runner1.userData['speed'] = 0.02;
  runner1.userData['random'] = 0;
  runner1.scale.set(scale, scale, scale);
  const runner2 = await initRunner(ctx);
  runner2.userData['time'] = 0.38;
  runner2.userData['speed'] = 0.02;
  runner2.userData['random'] = 0.5;
  runner2.scale.set(scale, scale, scale);

  // zero out uvs
  const uvAttribute = runner1.geometry.attributes['uv'];
  for (let i = 0; i < uvAttribute.count; i++) {
    uvAttribute.setXY(i, 0, 0);
  }
  // update "Hero" runner material
  if (!ctx.routeCompleteTexture) {
    ctx.routeCompleteTexture = await ctx.textureLoader.loadAsync(
      '/assets/textures/next_gradient.jpg',
    );
    ctx.routeCompleteTexture.wrapT = ctx.routeCompleteTexture.wrapS = THREE.RepeatWrapping;
  }

  const material = runner1.material as THREE.MeshStandardMaterial;
  material.emissiveMap = ctx.routeCompleteTexture;
  material.emissive = new THREE.Color(0xffffff);
  material.emissiveIntensity = 1.75;
  material.transparent = true;
  material.needsUpdate = true;

  const torusGeometry = new THREE.TorusGeometry(15, 2, 4, 32);
  torusGeometry.rotateX(Math.PI * 0.5);
  const torusMesh = new THREE.Mesh(torusGeometry, material);
  torusMesh.scale.y = 0.1;
  torusMesh.position.y = -5;
  runner1.add(torusMesh);

  ctx.controls.autoRotateSpeed = 0.3;

  await updateRunner(ctx, runner1, runner1.userData['time']);
  await updateRunner(ctx, runner2, runner2.userData['time']);

  const offset = new THREE.Vector3(500, 750, 750);

  await panCameraTo(ctx, runner1.position, offset);

  // follow runner — autoRotate for x s, lerp to fixed offset over x s, then release after x s
  followMesh(ctx, runner1 as THREE.Object3D, offset, true, {
    delay: 6.0,
    duration: 3.5,
    toOffset: new THREE.Vector3(20, 50, 600),
    releaseDelay: 6.5,
  });
}
*/

// ── Route draw-on animation ───────────────────────────────────────────────────

function animateInRoute(ctx: Context, splineLength: number, onComplete?: () => void): void {
  if (!ctx.currentRoute) return;
  const full =
    ctx.currentRoute.geometry.index?.count ??
    ctx.currentRoute.geometry.attributes['position'].count;
  const duration = splineLength / 12000;

  ctx.currentRoute.geometry.setDrawRange(0, 0);
  ctx.routeDraw = { active: true, elapsed: 0, duration, full, onComplete };
}

/** Called every frame from the Angular component's animate loop. */
export function tickRouteDraw(ctx: Context, delta: number): void {
  if (ctx.routeLightFade?.active) {
    ctx.routeLightFade.elapsed = Math.min(
      ctx.routeLightFade.elapsed + delta,
      ctx.routeLightFade.duration,
    );
    const lt = ctx.routeLightFade.elapsed / ctx.routeLightFade.duration;
    const easedLT = lt * lt * (3 - 2 * lt); // Smoothstep
    (ctx.ground.material as THREE.MeshStandardMaterial).emissiveIntensity = easedLT * 0.15;
    ctx.heightFogLightUpMaterial.uniforms['routeLightUp'].value = easedLT * 0.45;
    if (ctx.routeLightFade.elapsed >= ctx.routeLightFade.duration) {
      ctx.routeLightFade.active = false;
    }
  }

  if (!ctx.routeDraw?.active || !ctx.currentRoute) return;
  ctx.routeDraw.elapsed = Math.min(ctx.routeDraw.elapsed + delta, ctx.routeDraw.duration);
  const t = ctx.routeDraw.elapsed / ctx.routeDraw.duration;
  const easedT = Math.sin(t * Math.PI * 0.5); // Sinusoidal.Out
  ctx.currentRoute.geometry.setDrawRange(0, Math.round(easedT * ctx.routeDraw.full));

  // Keep ctx.drawRoute positioned at the current tip of the animated spline.
  if (ctx.drawRoute) {
    const path = (ctx.currentRoute.geometry as THREE.TubeGeometry).parameters.path;
    path.getPointAt(easedT, ctx.drawRoute.position);
  }

  if (ctx.routeDraw.elapsed >= ctx.routeDraw.duration) {
    ctx.routeDraw.active = false;
    if (ctx.currentRouteGoal) ctx.currentRouteGoal.visible = true;
    ctx.routeDraw.onComplete?.();
  }
}

/** Masks use 512² CanvasTextures; default mip generation on each upload caused visible flicker when moving the camera. */
function configureRoadMaskCanvasTexture(tex: THREE.CanvasTexture): void {
  tex.generateMipmaps = false;
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
}

// ── Spline-to-texture lightmap ────────────────────────────────────────────────

function drawSplineToTexture(ctx: Context, spline: THREE.CatmullRomCurve3): void {
  const SPLINE_SIZE = 512;
  const scale = 0.025;

  const img = ctx.routeCanvasTexture?.image;
  const reuseCanvas =
    img instanceof HTMLCanvasElement && img.width === SPLINE_SIZE && img.height === SPLINE_SIZE;

  let c: CanvasRenderingContext2D;
  if (reuseCanvas) {
    c = img.getContext('2d')!;
    c.fillStyle = 'black';
    c.fillRect(0, 0, SPLINE_SIZE, SPLINE_SIZE);
  } else {
    ctx.routeCanvasTexture?.dispose();
    const canvas = document.createElement('canvas');
    canvas.width = SPLINE_SIZE;
    canvas.height = SPLINE_SIZE;
    c = canvas.getContext('2d')!;
    c.fillStyle = 'black';
    c.fillRect(0, 0, SPLINE_SIZE, SPLINE_SIZE);
    ctx.routeCanvasTexture = new THREE.CanvasTexture(canvas);
    configureRoadMaskCanvasTexture(ctx.routeCanvasTexture);
    const texture = ctx.routeCanvasTexture;
    const groundMat = ctx.ground.material as THREE.MeshStandardMaterial;
    groundMat.emissiveMap = texture;
    groundMat.emissive = new THREE.Color(0xffffff);
    groundMat.emissiveIntensity = 0;
    groundMat.needsUpdate = true;
    ctx.heightFogLightUpMaterial.uniforms['routeMap'].value = texture;
    ctx.heightFogLightUpMaterial.uniforms['routeLightUp'].value = 0;
    ctx.roadsMaterial.uniforms['maskMap1'].value = texture;
    ctx.routeLightFade = { active: true, elapsed: 0, duration: 2.0 };
  }

  c.strokeStyle = 'white';
  c.lineWidth = 6;
  c.shadowBlur = 6;
  c.shadowColor = 'white';
  c.beginPath();
  const center = { x: 256, y: 256 };
  for (let i = 0; i < spline.points.length; i++) {
    const x = center.x + spline.points[i].x * scale;
    const y = center.y + spline.points[i].z * scale;
    i === 0 ? c.moveTo(x, y) : c.lineTo(x, y);
  }
  c.stroke();

  replayClosedTrafficSegmentMasks(ctx);

  ctx.routeCanvasTexture!.needsUpdate = true;
}

const ROUTE_MASK_SIZE = 512;
const ROUTE_MASK_SCALE = 0.025;

function worldToRouteSuppressCanvas(worldX: number, worldZ: number): { x: number; y: number } {
  const c = ROUTE_MASK_SIZE * 0.5;
  return { x: c + worldX * ROUTE_MASK_SCALE, y: c + worldZ * ROUTE_MASK_SCALE };
}

function ensureRouteMaskCanvasCtx(ctx: Context): CanvasRenderingContext2D {
  if (!ctx.routeCanvasTexture) {
    const canvas = document.createElement('canvas');
    canvas.width = ROUTE_MASK_SIZE;
    canvas.height = ROUTE_MASK_SIZE;
    const c = canvas.getContext('2d')!;
    c.fillStyle = 'black';
    c.fillRect(0, 0, ROUTE_MASK_SIZE, ROUTE_MASK_SIZE);
    ctx.routeCanvasTexture = new THREE.CanvasTexture(canvas);
    configureRoadMaskCanvasTexture(ctx.routeCanvasTexture);
    const texture = ctx.routeCanvasTexture;
    const groundMat = ctx.ground.material as THREE.MeshStandardMaterial;
    groundMat.emissiveMap = texture;
    groundMat.emissive = new THREE.Color(0xffffff);
    groundMat.emissiveIntensity = 0;
    groundMat.needsUpdate = true;
    ctx.heightFogLightUpMaterial.uniforms['routeMap'].value = texture;
    ctx.heightFogLightUpMaterial.uniforms['routeLightUp'].value = 0;
    ctx.roadsMaterial.uniforms['maskMap1'].value = texture;
    ctx.routeLightFade = { active: true, elapsed: 0, duration: 2.0 };
    return c;
  }
  const img = ctx.routeCanvasTexture.image;
  if (img instanceof HTMLCanvasElement) {
    return img.getContext('2d')!;
  }
  throw new Error('routeCanvasTexture.image is not a canvas');
}

function closedSegmentMaskId(worldPoints: Array<{ x: number; z: number }>): string {
  if (worldPoints.length < 2) return '';
  const a = worldPoints[0];
  const b = worldPoints[worldPoints.length - 1];
  return `${a.x.toFixed(3)}|${a.z.toFixed(3)}|${b.x.toFixed(3)}|${b.z.toFixed(3)}|${worldPoints.length}`;
}

function strokeRouteSuppressPolyline(
  ctx: Context,
  worldPoints: Array<{ x: number; z: number }>,
  color: 'white' | 'black',
): void {
  const c = ensureRouteMaskCanvasCtx(ctx);
  c.strokeStyle = color;
  c.lineWidth = 4;
  c.lineCap = 'round';
  c.lineJoin = 'round';
  c.beginPath();
  const p0 = worldToRouteSuppressCanvas(worldPoints[0].x, worldPoints[0].z);
  c.moveTo(p0.x, p0.y);
  for (let i = 1; i < worldPoints.length; i++) {
    const p = worldToRouteSuppressCanvas(worldPoints[i].x, worldPoints[i].z);
    c.lineTo(p.x, p.y);
  }
  c.stroke();
}

/** Re-stroke closed segments after drawSplineToTexture fills the mask canvas. */
function replayClosedTrafficSegmentMasks(ctx: Context): void {
  for (const { worldPoints } of ctx.closedTrafficSegmentMasks) {
    strokeRouteSuppressPolyline(ctx, worldPoints, 'white');
  }
}

/**
 * Stroke a polyline onto maskMap1 (same space as drawSplineToTexture).
 * White suppresses moving traffic along the segment; black restores it.
 */
export async function drawRouteSuppressSegmentToTexture(
  ctx: Context,
  worldPoints: Array<{ x: number; z: number }>,
  color: 'white' | 'black' = 'white',
): Promise<void> {
  if (worldPoints.length < 2) return;

  const id = closedSegmentMaskId(worldPoints);
  if (color === 'white') {
    const snapshot = worldPoints.map((p) => ({ x: p.x, z: p.z }));
    const idx = ctx.closedTrafficSegmentMasks.findIndex((e) => e.id === id);
    const entry = { id, worldPoints: snapshot };
    if (idx >= 0) ctx.closedTrafficSegmentMasks[idx] = entry;
    else ctx.closedTrafficSegmentMasks.push(entry);
  } else if (id) {
    ctx.closedTrafficSegmentMasks = ctx.closedTrafficSegmentMasks.filter((e) => e.id !== id);
  }

  strokeRouteSuppressPolyline(ctx, worldPoints, color);

  ctx.routeCanvasTexture!.needsUpdate = true;
}

// ── Trafficjam-to-texture mask ────────────────────────────────────────────────

const TRAFFIC_TEX_SIZE = 512;
const TRAFFIC_TEX_SCALE = 0.000049 * TRAFFIC_TEX_SIZE;

function worldToTrafficCanvas(worldX: number, worldZ: number): { x: number; y: number } {
  return {
    x: TRAFFIC_TEX_SIZE * 0.5 + worldX * TRAFFIC_TEX_SCALE,
    y: TRAFFIC_TEX_SIZE * 0.5 + worldZ * TRAFFIC_TEX_SCALE,
  };
}

function ensureTrafficjamCanvas(ctx: Context): CanvasRenderingContext2D {
  if (!ctx.trafficjamCanvas) {
    ctx.trafficjamCanvas = document.createElement('canvas');
    ctx.trafficjamCanvas.width = TRAFFIC_TEX_SIZE;
    ctx.trafficjamCanvas.height = TRAFFIC_TEX_SIZE;
    const init = ctx.trafficjamCanvas.getContext('2d')!;
    init.fillStyle = 'black';
    init.fillRect(0, 0, TRAFFIC_TEX_SIZE, TRAFFIC_TEX_SIZE);
  }
  return ctx.trafficjamCanvas.getContext('2d')!;
}

function syncTrafficjamTexture(ctx: Context): void {
  if (ctx.trafficjamCanvasTexture) {
    ctx.trafficjamCanvasTexture.needsUpdate = true;
  } else {
    ctx.trafficjamCanvasTexture = new THREE.CanvasTexture(ctx.trafficjamCanvas!);
    configureRoadMaskCanvasTexture(ctx.trafficjamCanvasTexture);
    ctx.roadsMaterial.uniforms['maskMap2'].value = ctx.trafficjamCanvasTexture;
  }
}

export async function drawTrafficjamToTexture(
  ctx: Context,
  worldX: number,
  worldZ: number,
  color = 'white',
): Promise<void> {
  const c = ensureTrafficjamCanvas(ctx);
  const { x: texX, y: texY } = worldToTrafficCanvas(worldX, worldZ);

  c.shadowBlur = 2;
  c.shadowColor = color;
  c.fillStyle = color;
  c.beginPath();
  c.arc(texX, texY, 10, 0, Math.PI * 2);
  c.fill();

  syncTrafficjamTexture(ctx);
}

/** Stroke a polyline in world XZ onto the traffic mask (same space as {@link drawTrafficjamToTexture}). */
export async function drawTrafficjamSegmentToTexture(
  ctx: Context,
  worldPoints: Array<{ x: number; z: number }>,
  color = 'white',
): Promise<void> {
  if (worldPoints.length < 2) return;

  const c = ensureTrafficjamCanvas(ctx);
  c.shadowBlur = 2;
  c.shadowColor = color;
  c.strokeStyle = color;
  c.lineWidth = 2;
  c.lineCap = 'round';
  c.lineJoin = 'round';
  c.beginPath();
  const p0 = worldToTrafficCanvas(worldPoints[0].x, worldPoints[0].z);
  c.moveTo(p0.x, p0.y);
  for (let i = 1; i < worldPoints.length; i++) {
    const p = worldToTrafficCanvas(worldPoints[i].x, worldPoints[i].z);
    c.lineTo(p.x, p.y);
  }
  c.stroke();

  syncTrafficjamTexture(ctx);
}

// ── Error ─────────────────────────────────────────────────────────────────────────

export function setError(ctx: Context, error: boolean) {
  ctx.errorState = error;
  let vignetteColor = 0x000000;
  let vignetteDarkness = 1.5;
  let vignetteOffset = 0.5;
  let trafficColor = 'black';
  let foilageColor = 0x419e92;

  if (error) {
    vignetteColor = 0xff0000;
    vignetteDarkness = 0.75;
    vignetteOffset = 1.5;
    trafficColor = 'white';
    foilageColor = 0x666666;
  }

  const redMaterial = new THREE.MeshStandardMaterial({
    color: 0x000000,
    emissive: 0xe76666,
    emissiveIntensity: 1.5,
  });
  for (let i = 0; i < ctx.windowMeshes.length; i++) {
    if (error) {
      ctx.windowMeshes[i].mesh.material = redMaterial;
    } else {
      ctx.windowMeshes[i].mesh.material = ctx.windowMeshes[i].originalMaterial;
    }
  }

  if (!ctx.foilageMaterial) return;

  ctx.foilageMaterial.color = new THREE.Color(foilageColor);

  ctx.vignettePass.uniforms['uColor'].value = new THREE.Color(vignetteColor);
  ctx.vignettePass.uniforms['darkness'].value = vignetteDarkness;
  ctx.vignettePass.uniforms['offset'].value = vignetteOffset;
  drawTrafficjamToTexture(ctx, 0, 0);
  if (ctx.trafficjamCanvasTexture && ctx.trafficjamCanvas) {
    const c = ctx.trafficjamCanvas.getContext('2d')!;
    c.fillStyle = trafficColor;
    c.fillRect(0, 0, TRAFFIC_TEX_SIZE, TRAFFIC_TEX_SIZE);
    ctx.trafficjamCanvasTexture.needsUpdate = true;
  }
}
