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
import { createCausticsMaterial } from '../shaders/caustics-shader';
import { createMedicalMaterial } from '../shaders/medical-shader';
import { createToiletMaterial } from '../shaders/toilet-shader';
import { createAnimatedParticles } from '../shaders/animated-particle-shader';
import { MAP_CENTER_LAT, MAP_CENTER_LON } from '../config';
import { GLB_TRANSFORM } from '../../glb-roads';
// ── Texture loader helpers ───────────────────────────────────────────────────

/** Loads icon textures once; subsequent calls are no-ops. */
export async function loadIconTextures(ctx: Context): Promise<void> {
  if (ctx.iconCircleTexture) return; // already loaded
  [
    ctx.iconLineTexture,
    ctx.iconCircleTexture,
    ctx.iconCircleFilledTexture,
    ctx.warningTexture,
    ctx.iconDiamondTexture,
  ] = await Promise.all([
    ctx.textureLoader.loadAsync('/assets/textures/pin_gradient.png'),
    ctx.textureLoader.loadAsync('/assets/textures/TX_circle_bg.png'),
    ctx.textureLoader.loadAsync('/assets/textures/TX_circle_filled.png'),
    ctx.textureLoader.loadAsync('/assets/textures/warning.png'),
    ctx.textureLoader.loadAsync('/assets/textures/icons/icon_diamond.png'),
  ]);
}

// ── Start / goal ground-circle marker ────────────────────────────────────────

export async function getStartGoal(ctx: Context, hideOuterCircle = false): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const plane = new THREE.PlaneGeometry(150, 150);

  const mat1 = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    map: ctx.iconCircleTexture,
    fog: false,
    depthWrite: false,
    transparent: true,
    opacity: hideOuterCircle ? 0 : 0.6,
  });
  const groundCircleMesh = new THREE.Mesh(plane, mat1);
  groundCircleMesh.rotation.x = -Math.PI * 0.5;

  const mat2 = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    map: ctx.iconCircleFilledTexture,
    fog: false,
    depthWrite: false,
    transparent: true,
    opacity: 0.2,
  });
  const circleMesh2 = new THREE.Mesh(plane, mat2);
  circleMesh2.scale.set(0.65, 0.65, 0.65);
  groundCircleMesh.add(circleMesh2);

  const mat3 = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    map: ctx.iconCircleFilledTexture,
    fog: false,
    depthWrite: false,
    transparent: true,
    opacity: 1.0,
  });
  const circleMesh3 = new THREE.Mesh(plane, mat3);
  circleMesh3.scale.set(0.3, 0.3, 0.3);
  groundCircleMesh.add(circleMesh3);

  return groundCircleMesh;
}

// ── Warning ground decal ──────────────────────────────────────────────────────

export async function getWarning(ctx: Context, color: number): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const warningMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(color),
    map: ctx.warningTexture,
    blending: THREE.AdditiveBlending,
    transparent: true,
    fog: false,
    depthWrite: false,
  });

  const warningPlane = new THREE.PlaneGeometry(500, 500);
  warningPlane.rotateX(-Math.PI * 0.5);
  const warningMesh = new THREE.Mesh(warningPlane, warningMaterial);

  return warningMesh;
}

// ── Info-icon pin ─────────────────────────────────────────────────────────────

export async function getInfoIcon(
  ctx: Context,
  id: any = null,
  label = '',
  sublabel = '',
  type: 'water_station' | 'traffic' | 'medical' | 'crowd_zone' = 'water_station',
): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const pinMaterial = new THREE.MeshBasicMaterial({
    color: 0xffffff,
    map: ctx.iconLineTexture,
    transparent: true,
    fog: false,
    depthWrite: false,
  });
  const pinCylinder = new THREE.CylinderGeometry(2, 2, 400, 16);
  pinCylinder.translate(0, 200, 0);
  const pinMesh = new THREE.Mesh(pinCylinder, pinMaterial);
  pinMesh.visible = false;

  const diamondMaterial = new THREE.MeshStandardMaterial({
    emissive: 0xffffff,
    fog: false,
    depthWrite: true,
  });
  const diamondGeometry = new THREE.OctahedronGeometry(20, 0);
  const diamondMesh = new THREE.Mesh(diamondGeometry, diamondMaterial);
  diamondMesh.position.y = 450;
  pinMesh.add(diamondMesh);

  // Invisible pick mesh — registered in ctx.iconPickMeshes for raycasting.
  const pickGeometry = new THREE.IcosahedronGeometry(80, 1);
  const pickMesh = new THREE.Mesh(pickGeometry, new THREE.MeshBasicMaterial({ visible: false }));
  pickMesh.userData['id'] = id;
  pickMesh.userData['label'] = label;
  pickMesh.userData['sublabel'] = sublabel;
  pickMesh.userData['type'] = type;
  diamondMesh.add(pickMesh);
  ctx.iconPickMeshes.push(pickMesh);

  return pinMesh;
}

export async function getScreenSpacePosition(
  ctx: Context,
  mesh: THREE.Mesh,
): Promise<THREE.Vector2> {
  const world = new THREE.Vector3();
  mesh.getWorldPosition(world);

  world.project(ctx.camera);

  const halfWidth = window.innerWidth / 2;
  const halfHeight = window.innerHeight / 2;

  const screenX = world.x * halfWidth + halfWidth;
  const screenY = -(world.y * halfHeight) + halfHeight;

  return new THREE.Vector2(screenX, screenY);
}

// ── Zone helpers ──────────────────────────────────────────────────────────────

const _zoneWorldPos = new THREE.Vector3();
const _black        = new THREE.Color(0x000000);
const _white        = new THREE.Color(0xffffff);
let _zoneTickAccum = 0;
const ZONE_TICK_INTERVAL = 0.1; // check 10x/sec instead of 60x

function registerZone(
  ctx: Context,
  mesh: THREE.Mesh,
  material: THREE.ShaderMaterial,
  radius = 125,
): void {
  ctx.zones.push({ mesh, material, radius });
}

// Check if any runners are within the zone radius
export function tickZones(ctx: Context, delta: number): void {
  // Always lerp material uniforms for smooth visual transitions
  for (const zone of ctx.zones) {
    const current = zone.material.uniforms['activeStrength'].value as number;
    const target = (zone as any)._activeTarget ?? 0.0;
    const speed = target > 0 ? 4.0 : 2.0;
    zone.material.uniforms['activeStrength'].value =
      current + (target - current) * Math.min(delta * speed, 1.0);
  }
  // Only do proximity checks at reduced frequency
  _zoneTickAccum += delta;
  if (_zoneTickAccum < ZONE_TICK_INTERVAL) return;
  _zoneTickAccum = 0;

  for (const zone of ctx.zones) {
    zone.mesh.getWorldPosition(_zoneWorldPos);

    let anyInside = false;
    for (const runner of ctx.runners) {
      const dx = runner.position.x - _zoneWorldPos.x;
      const dz = runner.position.z - _zoneWorldPos.z;
      if (dx * dx + dz * dz < zone.radius * zone.radius) {
        anyInside = true;
        break;
      }
    }

    (zone as any)._activeTarget = anyInside ? 1.5 : 0.0;
  }
}

export function removeZone(ctx: Context, mesh: THREE.Mesh): void {
  const idx = ctx.zones.findIndex((z) => z.mesh === mesh);
  if (idx === -1) return;

  const zone = ctx.zones[idx];

  // Detach from scene graph
  mesh.parent?.remove(mesh);

  // Remove from zones registry
  ctx.zones.splice(idx, 1);

  // Remove hemisphere material from the shared uTime-tick array
  const matIdx = ctx.zonesMaterialArray.indexOf(zone.material);
  if (matIdx !== -1) ctx.zonesMaterialArray.splice(matIdx, 1);

  // Unregister any invisible pick meshes that live inside this zone
  mesh.traverse((child) => {
    const pickIdx = ctx.iconPickMeshes.indexOf(child as THREE.Mesh);
    if (pickIdx !== -1) ctx.iconPickMeshes.splice(pickIdx, 1);
  });
}

// ── Water zone ─────────────────────────────────────────────────────────────────

export async function getWaterZone(ctx: Context): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const causticsMaterial = createCausticsMaterial();
  const causticsTex = await ctx.textureLoader.loadAsync('/assets/textures/caustics.jpg');
  causticsTex.wrapT = causticsTex.wrapS = THREE.RepeatWrapping;
  causticsMaterial.uniforms['causticsMap'].value = causticsTex;
  ctx.zonesMaterialArray.push(causticsMaterial);
  const geo = new THREE.SphereGeometry(100, 36, 36, 0, Math.PI * 2, 0, Math.PI * 0.5);
  const mesh = new THREE.Mesh(geo, causticsMaterial);

  if (!ctx.causticsCylinderMaterial) {
    ctx.causticsCylinderMaterial = causticsMaterial.clone();
    ctx.causticsCylinderMaterial.side = THREE.DoubleSide;
    ctx.causticsCylinderMaterial.uniforms['vFade'].value = 1.0;
    ctx.causticsCylinderMaterial.uniforms['repeat'].value = new THREE.Vector2(2, 0.35);
  }
  const cylinderMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(120, 100, 400, 16, 1, true),
    ctx.causticsCylinderMaterial,
  );
  cylinderMesh.position.y = 200;
  mesh.add(cylinderMesh);

  const bubbleTexture = await ctx.textureLoader.loadAsync('/assets/textures/bubble.png');
  const points = createAnimatedParticles(0x42ebff, bubbleTexture, 100, 40, 100, 300, false);
  if (!ctx.causticsParticleMaterial) {
    ctx.causticsParticleMaterial = points.material as THREE.ShaderMaterial;
  } else {
    points.material = ctx.causticsParticleMaterial;
  }

  mesh.add(points);

  const infoIcon = await getInfoIcon(ctx, null, 'Water Station', '', 'water_station');
  mesh.add(infoIcon);

  registerZone(ctx, mesh, causticsMaterial);
  return mesh;
}

// ── Medical zone ──────────────────────────────────────────────────────────────

export async function getMedicalZone(ctx: Context): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const medicalMaterial = createMedicalMaterial();
  const medicalTex = await ctx.textureLoader.loadAsync('/assets/textures/ekg.jpg');
  medicalTex.wrapS = THREE.RepeatWrapping;
  medicalMaterial.uniforms['medicalMap'].value = medicalTex;
  ctx.zonesMaterialArray.push(medicalMaterial);
  const geo = new THREE.SphereGeometry(100, 36, 36, 0, Math.PI * 2, 0, Math.PI * 0.5);
  const mesh = new THREE.Mesh(geo, medicalMaterial);

  if (!ctx.medicalCylinderMaterial) {
    ctx.medicalCylinderMaterial = medicalMaterial.clone();
    ctx.medicalCylinderMaterial.side = THREE.DoubleSide;
    ctx.medicalCylinderMaterial.uniforms['vFade'].value = 1.0;
    ctx.medicalCylinderMaterial.uniforms['glowIntensity'].value = 0.0;
    ctx.medicalCylinderMaterial.uniforms['baseColor'].value = new THREE.Color(0x660066);
  }
  const cylinderMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(120, 100, 400, 16, 1, true),
    ctx.medicalCylinderMaterial,
  );
  cylinderMesh.position.y = 200;
  mesh.add(cylinderMesh);

  const crossTexture = await ctx.textureLoader.loadAsync('/assets/textures/cross.png');
  const points = createAnimatedParticles(0x888888, crossTexture, 100, 20, 100, 300, true);
  if (!ctx.medicalParticleMaterial) {
    ctx.medicalParticleMaterial = points.material as THREE.ShaderMaterial;
  } else {
    points.material = ctx.medicalParticleMaterial;
  }
  mesh.add(points);

  const infoIcon = await getInfoIcon(ctx, null, 'Medical Station', '', 'medical');
  mesh.add(infoIcon);

  registerZone(ctx, mesh, medicalMaterial);
  return mesh;
}

// ── Toilet zone ────────────────────────────────────────────────────────────────

export async function getToiletZone(ctx: Context): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const toiletMaterial = createToiletMaterial();
  const toiletTex = await ctx.textureLoader.loadAsync('/assets/textures/toilet.jpg');
  //toiletTex.wrapT = toiletTex.wrapS = THREE.RepeatWrapping;
  toiletMaterial.uniforms['toiletMap'].value = toiletTex;
  ctx.zonesMaterialArray.push(toiletMaterial);
  const geo = new THREE.SphereGeometry(100, 36, 36, 0, Math.PI * 2, 0, Math.PI * 0.5);
  const mesh = new THREE.Mesh(geo, toiletMaterial);

  if (!ctx.toiletCylinderMaterial) {
    ctx.toiletCylinderMaterial = toiletMaterial.clone();
    ctx.toiletCylinderMaterial.side = THREE.DoubleSide;
    ctx.toiletCylinderMaterial.uniforms['toiletIntensity'].value = 0.0;
    ctx.toiletCylinderMaterial.uniforms['toiletMap'].value = null;
    ctx.toiletCylinderMaterial.uniforms['vFade'].value = 1.0;
    ctx.toiletCylinderMaterial.uniforms['baseColor'].value = new THREE.Color(0x006666);
  }
  const cylinderMesh = new THREE.Mesh(
    new THREE.CylinderGeometry(120, 100, 400, 16, 1, true),
    ctx.toiletCylinderMaterial,
  );
  cylinderMesh.position.y = 200;
  mesh.add(cylinderMesh);

  /*
  const bubbleTexture = await ctx.textureLoader.loadAsync('/assets/textures/bubble.png');
  const points = createAnimatedParticles(0x42ebff, bubbleTexture, 100, 40, 100, 300, false);
  if (!ctx.causticsParticleMaterial) {
    ctx.causticsParticleMaterial = points.material as THREE.ShaderMaterial;
  } else {
    points.material = ctx.causticsParticleMaterial;
  }

  mesh.add(points);
  */

  const infoIcon = await getInfoIcon(ctx, null, 'Toilet Station', '', undefined);
  mesh.add(infoIcon);

  registerZone(ctx, mesh, toiletMaterial);
  return mesh;
}

// ── Geo conversion ────────────────────────────────────────────────────────────
// Matches the Mercator projection used by viewport-lookdev.geoToWorld.

const _R = 6378137;
const _CX = ((MAP_CENTER_LON * Math.PI) / 180) * _R;
const _CY = Math.log(Math.tan(Math.PI / 4 + (MAP_CENTER_LAT * Math.PI) / 180 / 2)) * _R;
const _S = GLB_TRANSFORM.scale * 10;

export function lngLatToWorld(lon: number, lat: number): THREE.Vector3 {
  const mx = ((lon * Math.PI) / 180) * _R;
  const my = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 180 / 2)) * _R;
  return new THREE.Vector3(
    (mx - _CX) * _S + GLB_TRANSFORM.offsetX,
    0,
    -((my - _CY) * _S) + GLB_TRANSFORM.offsetZ,
  );
}

// ── Crowd zone ────────────────────────────────────────────────────────────────

export async function getCrowdZone(ctx: Context): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const crowdMaterial = createMedicalMaterial();
  crowdMaterial.uniforms['baseColor'].value = new THREE.Color(0x000000);
  crowdMaterial.uniforms['activeColor'].value = new THREE.Color(0xff9494);
  ctx.zonesMaterialArray.push(crowdMaterial);

  const geo = new THREE.SphereGeometry(100, 36, 36, 0, Math.PI * 2, 0, Math.PI * 0.5);
  const mesh = new THREE.Mesh(geo, crowdMaterial);

  const heartTexture = await ctx.textureLoader.loadAsync('/assets/textures/heart.png');
  const points = createAnimatedParticles(0xff7d7d, heartTexture, 100, 20, 150, 400, true);
  if (!ctx.crowdParticleMaterial) {
    ctx.crowdParticleMaterial = points.material as THREE.ShaderMaterial;
    ctx.crowdParticleMaterial.uniforms['uHeight'].value = 300;
  } else {
    points.material = ctx.crowdParticleMaterial;
  }
  mesh.add(points);

  const infoIcon = await getInfoIcon(ctx, null, 'Crowd Zone', '', 'crowd_zone');
  mesh.add(infoIcon);

  registerZone(ctx, mesh, crowdMaterial);
  return mesh;
}

// ── Start zone ─────────────────────────────────────────────────────────────────

export async function getStartZone(ctx: Context): Promise<THREE.Mesh> {
  await loadIconTextures(ctx);

  const startMaterial = createCausticsMaterial();
  startMaterial.uniforms['vFade'].value = 1.0;
  startMaterial.uniforms['baseColor'].value = new THREE.Color(0x555555);
  startMaterial.side = THREE.DoubleSide;
  const geometry = new THREE.CylinderGeometry(80, 40, 400, 16, 1, true);
  geometry.translate(0, 200, 0);
  const mesh = new THREE.Mesh(geometry, startMaterial);

  return mesh;
}

export function triggerStartZoneAnimation(
  ctx: Context,
  mesh: THREE.Mesh,
  pulseCount    = 3,
  pulseDuration = 0.35,
  toScale       = 1.0,
  onComplete?:  () => void,
): void {

  const mat = mesh.material as THREE.ShaderMaterial;
  const fromColor = new THREE.Color(0xaaaaaa);
  if (mat.uniforms?.['baseColor']) {
    (mat.uniforms['baseColor'].value as THREE.Color).copy(fromColor);
  }

  mesh.scale.y = 0;

  ctx.startZoneAnimations.push({
    mesh,
    material:             mat.uniforms?.['baseColor'] ? mat : null,
    fromColor,
    elapsed:              0,
    pulseDuration,
    pulseCount,
    fromScale:            0.75,
    toScale,
    lastPulseIndex:       0,
    fromVignetteColor:    (ctx.vignettePass.uniforms['uColor'].value as THREE.Color).clone(),
    fromVignetteDarkness: ctx.vignettePass.uniforms['darkness'].value as number,
    restoring:            false,
    restoreElapsed:       0,
    restoreDuration:      0.5,
    restoreFromDarkness:  0,
    onComplete,
  });

  // Snap vignette colour to white immediately when animation starts
  (ctx.vignettePass.uniforms['uColor'].value as THREE.Color).copy(_white);
}

/** Called every frame from the animate loop. */
export function tickStartZoneAnimations(ctx: Context, delta: number): void {
  for (let i = ctx.startZoneAnimations.length - 1; i >= 0; i--) {
    const anim = ctx.startZoneAnimations[i];
    anim.elapsed += delta;

    const pulseIndex = Math.floor(anim.elapsed / anim.pulseDuration);

    if (pulseIndex >= anim.pulseCount || anim.restoring) {
      // Restore phase — ease colour and darkness back to originals
      if (!anim.restoring) {
        anim.restoring = true;
        anim.restoreFromDarkness = ctx.vignettePass.uniforms['darkness'].value as number;
      }
      anim.restoreElapsed += delta;
      const rt     = Math.min(anim.restoreElapsed / anim.restoreDuration, 1.0);
      const reased = rt * rt * (3 - 2 * rt);  // smoothstep
      (ctx.vignettePass.uniforms['uColor'].value as THREE.Color)
        .copy(_white)
        .lerp(anim.fromVignetteColor, reased);
      ctx.vignettePass.uniforms['darkness'].value =
        anim.restoreFromDarkness + (anim.fromVignetteDarkness - anim.restoreFromDarkness) * reased;
      if (rt >= 1.0) {
        anim.onComplete?.();
        ctx.startZoneAnimations.splice(i, 1);
      }
      continue;
    }

    // Reset scale and mesh colour at the start of each new pulse
    if (pulseIndex > anim.lastPulseIndex) {
      anim.mesh.scale.y   = anim.fromScale;
      anim.lastPulseIndex = pulseIndex;
      if (anim.material) {
        (anim.material.uniforms['baseColor'].value as THREE.Color).copy(anim.fromColor);
      }
    }

    const t      = (anim.elapsed % anim.pulseDuration) / anim.pulseDuration;
    const eased  = 1 - (1 - t) * (1 - t);
    const bump   = Math.sin((1 - t) * Math.PI);
    const s = anim.fromScale + (anim.toScale - anim.fromScale) * eased;
    anim.mesh.scale.set(s, s, s);

    if (anim.material) {
      (anim.material.uniforms['baseColor'].value as THREE.Color)
        .copy(anim.fromColor)
        .lerp(_black, eased);
    }

    // Pulse darkness: bumps up from fromVignetteDarkness and returns each pulse
    ctx.vignettePass.uniforms['darkness'].value =
      anim.fromVignetteDarkness - (3.5 - anim.fromVignetteDarkness) * bump;

  }
}
// ── Traffic zone ──────────────────────────────────────────────────────────────

export interface AffectedIntersection {
  /** [longitude, latitude] */
  coordinates: [number, number];
  cross_streets: string[];
  impact_level: string;
}

let _trafficParticleMaterial: THREE.ShaderMaterial | null = null;

/**
 * Creates one traffic-warning zone mesh per entry in `intersections`,
 * pre-positioned at the corresponding real-world geo coordinates.
 * Add the returned meshes directly to the scene or a parent object.
 */
export async function getTrafficZones(
  ctx: Context,
  intersections: AffectedIntersection[],
): Promise<THREE.Mesh[]> {
  await loadIconTextures(ctx);

  const meshes: THREE.Mesh[] = [];

  for (const intersection of intersections) {
    const trafficMaterial = createMedicalMaterial();
    trafficMaterial.uniforms['baseColor'].value = new THREE.Color(0x180800);
    trafficMaterial.uniforms['activeColor'].value = new THREE.Color(0xff6a00);
    trafficMaterial.uniforms['glowColor'].value = new THREE.Color(0xffaa33);
    ctx.zonesMaterialArray.push(trafficMaterial);

    const geo = new THREE.SphereGeometry(100, 36, 36, 0, Math.PI * 2, 0, Math.PI * 0.5);
    const mesh = new THREE.Mesh(geo, trafficMaterial);

    const points = createAnimatedParticles(0xff8800, ctx.warningTexture!, 100, 20, 150, 400, true);
    if (!_trafficParticleMaterial) {
      _trafficParticleMaterial = points.material as THREE.ShaderMaterial;
      _trafficParticleMaterial.uniforms['uHeight'].value = 300;
    } else {
      points.material = _trafficParticleMaterial;
    }
    mesh.add(points);

    const crossStreets = intersection.cross_streets.join(' & ');
    const infoIcon = await getInfoIcon(
      ctx,
      null,
      crossStreets || 'Traffic Alert',
      `Impact: ${intersection.impact_level}`,
      'traffic',
    );
    mesh.add(infoIcon);

    const [lon, lat] = intersection.coordinates;
    mesh.position.copy(lngLatToWorld(lon, lat));

    registerZone(ctx, mesh, trafficMaterial);
    meshes.push(mesh);
  }

  return meshes;
}
