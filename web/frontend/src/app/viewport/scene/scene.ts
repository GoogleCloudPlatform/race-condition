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
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { Context } from '../context';
import { baseFog } from '../config';
import { createHeightFogMaterial } from '../shaders/height-fog-shader';
import { createWindowMaterial } from '../shaders/window-shader';
import { createRoadsMaterial } from '../shaders/road-shader';
import { createSphereMaterial } from '../shaders/sphere-shader';

// ── Renderer, scene, camera, controls ────────────────────────────────────────
export function initScene(ctx: Context, canvas: HTMLCanvasElement): void {
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
    navigator.userAgent,
  );
  const w = window.innerWidth,
    h = window.innerHeight;

  ctx.renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  ctx.renderer.setPixelRatio(isMobile ? 1 : window.devicePixelRatio);
  ctx.renderer.setSize(w, h);
  ctx.renderer.shadowMap.enabled = true;
  ctx.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

  ctx.scene = new THREE.Scene();
  ctx.scene.fog = new THREE.Fog(0x313131, 2000, baseFog.far);
  ctx.scene.background = (ctx.scene.fog as THREE.Fog).color;

  ctx.camera = new THREE.PerspectiveCamera(50, w / h, 10, 50000);
  ctx.camera.position.set(4000, 1500, 4500);

  ctx.scene.add(ctx.camera);
  ctx.controls = new OrbitControls(ctx.camera, canvas);
  ctx.controls.target.set(1000, 0, -100);
  ctx.controls.minDistance = 500;
  ctx.controls.maxDistance = 10000;
  ctx.controls.maxPolarAngle = Math.PI * 0.5 - 0.1;
  ctx.controls.enableDamping = true;
  ctx.controls.dampingFactor = 0.015;
  ctx.controls.autoRotate = true;
  ctx.controls.autoRotateSpeed = 0.4;
  ctx.controls.screenSpacePanning = false;
  ctx.controls.update();

  // Limit camera panning distance
  const minPan = new THREE.Vector3(-10000, 0, -10000);
  const maxPan = new THREE.Vector3(10000, 10000, 10000);
  const _v = new THREE.Vector3();

  ctx.controls.addEventListener('change', () => {
    _v.copy(ctx.controls.target);
    ctx.controls.target.clamp(minPan, maxPan);
    _v.sub(ctx.controls.target);
    ctx.camera.position.sub(_v);
  });
}

// ── Lights ────────────────────────────────────────────────────────────────────
export function initLights(ctx: Context): void {
  ctx.dirLight = new THREE.DirectionalLight(0xffffff, 3.3);
  ctx.dirLight.position.set(-6000, 5000, 5000);
  ctx.dirLight.castShadow = true;
  ctx.dirLight.shadow.camera.near = 5000;
  ctx.dirLight.shadow.camera.far = 15000;
  const size = 1500;
  ctx.dirLight.shadow.camera.left = -size;
  ctx.dirLight.shadow.camera.right = size;
  ctx.dirLight.shadow.camera.top = size;
  ctx.dirLight.shadow.camera.bottom = -size;
  ctx.dirLight.shadow.mapSize.width = 1024;
  ctx.dirLight.shadow.mapSize.height = 1024;
  ctx.dirLight.shadow.intensity = 0.9;
  ctx.dirLight.shadow.bias = 0.0002;
  ctx.scene.add(ctx.dirLight);
  ctx.scene.add(ctx.dirLight.target);

  ctx.ambient = new THREE.AmbientLight(0xffffff, 3.0);
  ctx.scene.add(ctx.ambient);
}

// ── Ground plane ──────────────────────────────────────────────────────────────
export function initGround(ctx: Context): void {
  const groundPlane = new THREE.PlaneGeometry(20500, 20500);
  groundPlane.rotateX(-Math.PI * 0.5);
  ctx.ground = new THREE.Mesh(
    groundPlane,
    new THREE.MeshStandardMaterial({
      color: new THREE.Color(0x2f3030),
      roughness: 1.0,
      metalness: 0.0,
      depthWrite: true,
    }),
  );
  ctx.ground.position.y = -1;
  ctx.ground.receiveShadow = true;
  ctx.scene.add(ctx.ground);
  // outer ground tiles
  const outerGroundMaterial = new THREE.MeshStandardMaterial({
      color: new THREE.Color(0x2f3030),
      roughness: 1.0,
      metalness: 0.0,
      depthWrite: false,
    });
  const leftGroundTile = new THREE.Mesh(groundPlane, outerGroundMaterial);
  leftGroundTile.scale.set(0.75, 1, 2);
  leftGroundTile.position.set(-20500*0.75,0,0);
  ctx.scene.add(leftGroundTile);

  const rightGroundTile = new THREE.Mesh(groundPlane, outerGroundMaterial);
  rightGroundTile .scale.set(0.75, 1, 2);
  rightGroundTile .position.set(20500*0.75,0,0);
  ctx.scene.add(rightGroundTile );

  const upGroundTile = new THREE.Mesh(groundPlane, outerGroundMaterial);
  upGroundTile.position.set(0,0,-20500);
  ctx.scene.add(upGroundTile);

  const downGroundTile = new THREE.Mesh(groundPlane, outerGroundMaterial);
  downGroundTile.position.set(0,0,20500);
  ctx.scene.add(downGroundTile);
}

// ── Sky cylinder + mountains ──────────────────────────────────────────────────
export function initHorizon(ctx: Context): void {
  const skyHeight = 3000;
  const skyGeometry = new THREE.CylinderGeometry(20000, 20000, skyHeight, 36, 1, true);
  skyGeometry.translate(0, skyHeight * 0.5, 0);
  ctx.skyMaterial = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    uniforms: {
      colorBottom: { value: new THREE.Color(0x56565c) },
      colorTop: { value: (ctx.scene.fog as THREE.Fog).color.clone() },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
      }
    `,
    fragmentShader: `
      uniform vec3 colorBottom;
      uniform vec3 colorTop;
      varying vec2 vUv;
      void main() {
        gl_FragColor = vec4( mix( colorBottom, colorTop, vUv.y ), 1.0 );
      }
    `,
  });
  ctx.skyMesh = new THREE.Mesh(skyGeometry, ctx.skyMaterial);
  ctx.skyMesh.scale.y = 1.5;
  ctx.scene.add(ctx.skyMesh);

  const count = 15;
  const radius = 19000;
  const mtnWidth = 10000;
  const mtnHeight = 26;
  const widthSegs = 12;

  ctx.mountainMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color(0x434345),
    depthWrite: false,
    fog: false,
  });

  for (let i = 0; i < count; i++) {
    const angle = (i / count) * Math.PI * 2;
    const geo = new THREE.PlaneGeometry(mtnWidth, mtnHeight, widthSegs, 1);
    const pos = geo.attributes['position'] as THREE.BufferAttribute;
    const topY = mtnHeight * 0.5;

    for (let v = 0; v < pos.count; v++) {
      if (pos.getY(v) >= topY - 1.0) {
        const nx = (pos.getX(v) / (mtnWidth / 2) + 1) / 2;
        const t = nx * Math.PI;
        const peak =
          Math.sin(t) * mtnHeight * (0.5 + Math.random() * 0.5) +
          Math.sin(t * 2 + Math.random() * 2) * mtnHeight * 0.2 +
          Math.sin(t * 3 + Math.random() * 3) * mtnHeight * 0.1;
        pos.setY(v, 400 + (topY + Math.max(0, peak)) * (Math.random() * mtnHeight));
        const x = pos.getX(v);
        const edge = mtnWidth * 0.5 - 1;
        if (x < -edge || x > edge) pos.setY(v, 0);
      }
    }
    pos.needsUpdate = true;
    geo.computeVertexNormals();

    const mesh = new THREE.Mesh(geo, ctx.mountainMaterial);
    mesh.position.set(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
    mesh.rotation.y = Math.atan2(mesh.position.x, mesh.position.z) + Math.PI;
    ctx.scene.add(mesh);
  }
}

// ── GLB model + material assignment ──────────────────────────────────────────
export async function initModel(ctx: Context): Promise<void> {
  const gltfLoader = new GLTFLoader().setPath('/assets/');
  gltfLoader.setMeshoptDecoder(MeshoptDecoder as any);

  const [gltf] = await Promise.all([gltfLoader.loadAsync('models/Google_LasVegas_Export_v32.glb')]);

  gltf.scene.scale.set(1, 1, 1);
  ctx.scene.add(gltf.scene);

  const windows = await ctx.textureLoader.loadAsync('/assets/textures/windows.png');
  windows.wrapS = THREE.RepeatWrapping;
  windows.wrapT = THREE.RepeatWrapping;
  windows.minFilter = windows.magFilter = THREE.NearestFilter;

  const trafficTexture = await ctx.textureLoader.loadAsync('/assets/textures/traffic.png');
  trafficTexture.wrapT = trafficTexture.wrapS = THREE.RepeatWrapping;
  //trafficTexture.minFilter = trafficTexture.magFilter = THREE.NearestFilter;
  const trafficJamTexture = await ctx.textureLoader.loadAsync('/assets/textures/traffic_que.png');
  trafficJamTexture.wrapT = trafficJamTexture.wrapS = THREE.RepeatWrapping;
  //trafficJamTexture.minFilter = trafficJamTexture.magFilter = THREE.NearestFilter;
  ctx.heightFogMaterial = createHeightFogMaterial();
  ctx.heightFogMaterial.name = 'BaseMaterial';

  ctx.heightFogLightUpMaterial = ctx.heightFogMaterial.clone();
  ctx.heightFogLightUpMaterial.uniforms['emissiveMap'].value = windows;

  setupWindowMaterials(ctx);

  ctx.foilageMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(0x419e92),
  });

  ctx.roadsMaterial = createRoadsMaterial();
  ctx.roadsMaterial.uniforms['emissiveMap'].value = trafficTexture;
  ctx.roadsMaterial.uniforms['emissiveMapStopped'].value = trafficJamTexture;

  ctx.roadsGlowMaterial = new THREE.MeshStandardMaterial({
    color: new THREE.Color(0x000000),
    emissive: new THREE.Color(0x7b7c83),
    emissiveIntensity: 0.5,
    depthWrite: false,
  });

  gltf.scene.traverse((child) => {
    const mesh = child as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    if ((mesh.material as THREE.Material).name === 'BaseMaterial')
      mesh.material = ctx.heightFogMaterial;
    if ((mesh.material as THREE.Material).name === '') mesh.material = ctx.heightFogMaterial;
    if ((mesh.material as THREE.Material).name === 'Foilage') mesh.material = ctx.foilageMaterial;
    if ((mesh.material as THREE.Material).name === 'Road_Line') {
      mesh.material = ctx.roadsGlowMaterial;
      mesh.castShadow = false;
    }
    if ((mesh.material as THREE.Material).name === 'Road.Base') {
      mesh.material = ctx.roadsMaterial;
      mesh.castShadow = false;
    }
    if (
      (mesh.material as THREE.Material).name === 'BaseMaterial' &&
      child.parent?.name === 'ROADS'
    ) {
      mesh.material = ctx.roadsMaterial;
      mesh.castShadow = false;
    }
    if (mesh.name == 'HighRollerWheel') {
      ctx.ferrisWheel = mesh;
      mesh.material = ctx.windowMaterialArray[0];
      mesh.material.name = 'Windows_Emission1';
    }
    if (mesh.name == 'Surroundingbuildings') {
      mesh.material = ctx.heightFogLightUpMaterial;
    }
    if ((mesh.material as THREE.Material).name.includes('Windows_Emission')) {
      const matName = (mesh.material as THREE.Material).name;
      const index = parseInt(matName.substring(matName.length - 1));
      if (!isNaN(index) && index >= 1 && index <= ctx.windowMaterialArray.length) {
        mesh.material = (ctx.windowMaterialArray[index - 1] as THREE.ShaderMaterial).clone();
        if (child.parent?.name === 'MandalayBayArena' || child.parent?.name === 'TMobileArena') {
          const tempMat = (ctx.windowMaterialArray[index - 1] as THREE.ShaderMaterial).clone();
          tempMat.uniforms['heightFogNear'].value = 100;
          mesh.material = tempMat;
        }
        if (child.parent?.name === 'Airport') {
          const tempMat = (ctx.windowMaterialArray[index - 1] as THREE.ShaderMaterial).clone();
          tempMat.uniforms['bottomColor'].value = new THREE.Color(0x001936);
          tempMat.uniforms['topColor'].value = new THREE.Color(0x0057bb);
          mesh.material = tempMat;
        }
      }
      // theSphere
      if (child.parent?.name === 'theSphere') {
        if (!ctx.sphereMaterial) ctx.sphereMaterial = createSphereMaterial();
        mesh.material = ctx.sphereMaterial;
      }

      // Register for intro window light-up. worldZ and litTarget are filled in startCameraIntro.
      ctx.windowMeshes.push({
        mesh,
        originalMaterial: mesh.material as THREE.Material,
        worldZ: 0,
        litTarget: 1,
      });
    }
  });
}

function setupWindowMaterials(ctx: Context): void {
  const windowMaterialBase = createWindowMaterial();

  ctx.windowMaterialArray = [windowMaterialBase];
  const numOfWindowMaterials = 7;
  const bottomColorArray = [0x013369, 0x92300a, 0x003617, 0x151060, 0x7f0f33, 0x410583];
  const topColorArray = [0x5676e0, 0xffb900, 0x6ddb00, 0x106ed7, 0xe35f95, 0xd1457e];

  for (let i = 1; i < numOfWindowMaterials; i++) {
    const mat = windowMaterialBase.clone();
    mat.uniforms['bottomColor'].value = new THREE.Color(bottomColorArray[i - 1]);
    mat.uniforms['topColor'].value = new THREE.Color(topColorArray[i - 1]);
    ctx.windowMaterialArray.push(mat);
  }
}

// ── Camera intro ─────────────────────────────────────────────────────────────

const introSpline = new THREE.CatmullRomCurve3(
  [
    new THREE.Vector3(-4000, 2000, -4500),
    new THREE.Vector3(1100, 650, -1300),
    new THREE.Vector3(4000, 1500, 4500),
  ],
  false,
  'catmullrom',
  0.5,
);

/**
 * Fly the camera along introSpline, lerping the look-at target from
 * fromTarget to the normal orbit target. Simultaneously sweeps a Z threshold
 * north→south across the city, restoring each building's window material as
 * the threshold passes it. Resolves when the transition is complete.
 *
 * @param fromTarget         World position the camera looks at at t=0.
 * @param duration           Travel time in seconds (default 10).
 * @param windowLightStartT  Normalised intro time (0-1) when windows start lighting up.
 * @param windowLightEndT    Normalised intro time (0-1) when all windows are lit.
 */
export function startCameraIntro(
  ctx: Context,
  fromTarget = new THREE.Vector3(0, 0, 0),
  duration = 10.0,
  windowLightStartT = -0.2,
  windowLightEndT = 0.9,
): Promise<void> {
  ctx.camera.position.copy(introSpline.getPoint(0));
  ctx.camera.lookAt(fromTarget);

  ctx.controls.enabled = false;

  // Dark out all windows via shader and cache each mesh's world Z position.
  const _wp = new THREE.Vector3();
  let minZ = Infinity,
    maxZ = -Infinity;

  for (const entry of ctx.windowMeshes) {
    entry.litTarget = 0;
    const mat = entry.originalMaterial as THREE.ShaderMaterial;
    if (mat.uniforms?.['litAmount']) mat.uniforms['litAmount'].value = 0.0;
    entry.mesh.getWorldPosition(_wp);
    entry.worldZ = _wp.z;
    if (_wp.z < minZ) minZ = _wp.z;
    if (_wp.z > maxZ) maxZ = _wp.z;
  }
  ctx.windowMeshes.sort((a, b) => a.worldZ - b.worldZ);

  return new Promise((resolve) => {
    ctx.cameraIntro = {
      active: true,
      elapsed: 0,
      duration,
      spline: introSpline,
      fromTarget: fromTarget.clone(),
      toTarget: new THREE.Vector3(1000, 0, -100),
      windowLightStartT,
      windowLightEndT,
      windowMinZ: minZ,
      windowMaxZ: maxZ,
      windowLightIndex: 0,
      onComplete: resolve,
    };
  });
}

/** Called every frame from the animate loop. */
export function tickCameraIntro(ctx: Context, delta: number): void {
  if (!ctx.cameraIntro?.active) return;

  ctx.cameraIntro.elapsed = Math.min(ctx.cameraIntro.elapsed + delta, ctx.cameraIntro.duration);
  const t = ctx.cameraIntro.elapsed / ctx.cameraIntro.duration;
  const easedT = t * t * (3 - 2 * t); // smoothstep — ease in and out
  // Move camera along spline.
  ctx.camera.position.copy(ctx.cameraIntro.spline.getPoint(easedT));

  // Lerp look-at target and point camera at it.
  const lookAt = new THREE.Vector3().lerpVectors(
    ctx.cameraIntro.fromTarget,
    ctx.cameraIntro.toTarget,
    easedT,
  );
  ctx.camera.lookAt(lookAt);

  // Window light-up sweep — advance sorted pointer, set litTarget on triggered entries.
  const { windowLightStartT, windowLightEndT, windowMinZ, windowMaxZ } = ctx.cameraIntro;
  if (t >= windowLightStartT && ctx.windowMeshes.length > 0) {
    const wt = Math.min((t - windowLightStartT) / (windowLightEndT - windowLightStartT), 1.0);
    const zThreshold = windowMinZ + wt * (windowMaxZ - windowMinZ);

    while (
      ctx.cameraIntro.windowLightIndex < ctx.windowMeshes.length &&
      ctx.windowMeshes[ctx.cameraIntro.windowLightIndex].worldZ <= zThreshold
    ) {
      ctx.windowMeshes[ctx.cameraIntro.windowLightIndex].litTarget = 1.0;
      ctx.cameraIntro.windowLightIndex++;
    }
  }

  // Lerp every window material toward its litTarget each frame.
  const fadeSpeed = 0.8; // full brightness in ~0.33 s
  for (const entry of ctx.windowMeshes) {
    const mat = entry.originalMaterial as THREE.ShaderMaterial;
    if (!mat.uniforms?.['litAmount']) continue;
    const current = mat.uniforms['litAmount'].value as number;
    if (current < entry.litTarget) {
      mat.uniforms['litAmount'].value = Math.min(current + delta * fadeSpeed, entry.litTarget);
    }
  }

  if (t >= 1.0) {
    // Ensure any remaining windows are fully triggered (e.g. if endT < 1.0).
    for (const entry of ctx.windowMeshes) {
      entry.litTarget = 1.0;
    }
    ctx.cameraIntro.active = false;

    ctx.camera.position.copy(ctx.cameraIntro.spline.getPoint(1.0));
    ctx.controls.target.copy(ctx.cameraIntro.toTarget);
    ctx.controls.update();
    ctx.controls.enabled = true;
    ctx.cameraIntro.onComplete?.();
  }
}

// ── Camera pan ────────────────────────────────────────────────────────────────

const PAN_UNITS_PER_SECOND = 2000; // world-units per second at full speed
const PAN_MIN_DURATION = 0.25;
const PAN_MAX_DURATION = 5.0;

/**
 * Smoothly pan the orbit target to targetPosition, with the camera
 * offset from that target by cameraOffset.
 * Duration is derived from how far the target needs to travel.
 */
export function panCameraTo(
  ctx: Context,
  targetPosition: THREE.Vector3,
  cameraOffset: THREE.Vector3,
  options?: { speed?: number; minDuration?: number; maxDuration?: number },
): Promise<void> {
  return new Promise((resolve) => {
    // A new pan replaces ctx.cameraPan; without resolving the prior onComplete, any code
    // awaiting the previous pan never continues (e.g. first hud:addSimRunner vs another pan).
    const prev = ctx.cameraPan;
    if (prev?.onComplete) {
      if (prev.active) {
        ctx.controls.enabled = true;
      }
      const done = prev.onComplete;
      prev.onComplete = undefined;
      done();
    }

    const unitsPerSecond = options?.speed       ?? PAN_UNITS_PER_SECOND;
    const minDur         = options?.minDuration ?? PAN_MIN_DURATION;
    const maxDur         = options?.maxDuration ?? PAN_MAX_DURATION;
    const toPosition = targetPosition.clone().add(cameraOffset);
    const distance = ctx.controls.target.distanceTo(targetPosition);
    const duration = THREE.MathUtils.clamp(
      distance / unitsPerSecond,
      minDur,
      maxDur,
    );
    ctx.cameraPan = {
      active: true,
      elapsed: 0,
      duration,
      fromPosition: ctx.camera.position.clone(),
      toPosition,
      fromTarget: ctx.controls.target.clone(),
      toTarget: targetPosition.clone(),
      onComplete: resolve,
    };

    // Disable controls during the tween so they don't fight it.
    ctx.controls.enabled = false;
  });
}

/** Called every frame from the animate loop. */
export function tickCameraPan(ctx: Context, delta: number): void {
  if (!ctx.cameraPan?.active) return;

  ctx.cameraPan.elapsed = Math.min(ctx.cameraPan.elapsed + delta, ctx.cameraPan.duration);
  const t = ctx.cameraPan.elapsed / ctx.cameraPan.duration;

  // Smoothstep — ease in and ease out
  const easedT = t * t * (3 - 2 * t);

  ctx.camera.position.lerpVectors(ctx.cameraPan.fromPosition, ctx.cameraPan.toPosition, easedT);
  ctx.controls.target.lerpVectors(ctx.cameraPan.fromTarget, ctx.cameraPan.toTarget, easedT);
  ctx.controls.update();

  if (ctx.cameraPan.elapsed >= ctx.cameraPan.duration) {
    ctx.cameraPan.active = false;
    ctx.controls.enabled = true;
    ctx.cameraPan.onComplete?.();
  }
}

// ── Camera follow ─────────────────────────────────────────────────────────────

/**
 * Lock the camera to follow a mesh. The orbit target sits on the mesh,
 * the camera is positioned at mesh + offset.
 * Any pointer interaction on the canvas ends the follow automatically.
 */
const FOLLOW_DEFAULT_POLAR = Math.PI * 0.28;
const FOLLOW_MIN_POLAR = Math.PI * 0.08;
const FOLLOW_MAX_POLAR = Math.PI * 0.5 - 0.1;

export function followMesh(
  ctx: Context,
  mesh: THREE.Object3D,
  offset: THREE.Vector3,
  autoRotate = false,
  offsetTransition?: {
    delay: number;
    duration: number;
    toOffset: THREE.Vector3;
    releaseDelay?: number;
  },
  damping = 2.0,
): void {
  ctx.cameraFollow = {
    mesh,
    offset: offset.clone(),
    autoRotate,
    damping,
    offsetTransition: offsetTransition
      ? {
          delay: offsetTransition.delay,
          duration: offsetTransition.duration,
          elapsed: 0,
          toOffset: offsetTransition.toOffset.clone(),
          fromOffset: new THREE.Vector3(),
          started: false,
          releaseDelay: offsetTransition.releaseDelay ?? 0,
        }
      : undefined,
  };
  ctx.cameraPan = null;
  ctx.controls.enabled = true;
}

/**
 * Swap the follow target to a different mesh without resetting camera orbit state.
 * tickCameraFollow()'s existing lerp provides a smooth transition.
 */
export function swapFollowTarget(ctx: Context, mesh: THREE.Object3D): void {
  if (!ctx.cameraFollow) return;
  ctx.cameraFollow.mesh = mesh;
}

export function stopFollowMesh(ctx: Context): void {
  if (!ctx.cameraFollow) return;
  ctx.cameraFollow = null;
  ctx.controls.enabled = true;
}

/** Called every frame from the animate loop. */

const _occRaycaster = new THREE.Raycaster();
const _occTestDir = new THREE.Vector3();
const _occIdealPos = new THREE.Vector3();
const _occSmoothedPos = new THREE.Vector3();
let _occAzimuth = 0;
let _occPolar = FOLLOW_DEFAULT_POLAR;
let _occTargetPolar = FOLLOW_DEFAULT_POLAR;
let _occDist = 1500;
let _occClearTimer = 0;
let _occInitialized = false;
const OCC_LOOKAHEAD = 4.0;
const OCC_RISE_SPEED = 0.6;
const OCC_FALL_SPEED = 0.3;
const OCC_CLEAR_DELAY = 2.0;
const OCC_AUTO_ROTATE_SPEED = 0.08;
const OCC_POS_LERP = 3.0;
const OCC_POLAR_LERP = 2.0;

export function followZoom(amount: number): void {
  _occDist = Math.max(300, Math.min(8000, _occDist + amount));
}

function _isBlocked(
  ctx: Context,
  origin: THREE.Vector3,
  azimuth: number,
  polar: number,
  dist: number,
): boolean {
  const sinP = Math.sin(polar);
  _occTestDir.set(Math.sin(azimuth) * sinP, Math.cos(polar), Math.cos(azimuth) * sinP);
  _occRaycaster.set(origin, _occTestDir.normalize());
  _occRaycaster.far = dist;
  return _occRaycaster.intersectObjects(ctx.occlusionMeshes, false).length > 0;
}

function _posFromSpherical(
  origin: THREE.Vector3,
  azimuth: number,
  polar: number,
  dist: number,
  out: THREE.Vector3,
): void {
  const sinP = Math.sin(polar);
  out.set(
    origin.x + Math.sin(azimuth) * sinP * dist,
    origin.y + Math.cos(polar) * dist,
    origin.z + Math.cos(azimuth) * sinP * dist,
  );
}

export function tickCameraFollow(ctx: Context, delta: number): void {
  if (!ctx.cameraFollow) return;
  const targetPos = ctx.cameraFollow.mesh.position;
  const damping = ctx.cameraFollow.damping ?? 2;
  const targetSmooth = 1 - Math.exp(-damping * delta);

  if (ctx.cameraFollow.autoRotate) {
    const speed = ctx.controls.autoRotateSpeed * 0.02 * delta;
    const ox = ctx.cameraFollow.offset.x;
    const oz = ctx.cameraFollow.offset.z;
    ctx.cameraFollow.offset.x = ox * Math.cos(speed) - oz * Math.sin(speed);
    ctx.cameraFollow.offset.z = ox * Math.sin(speed) + oz * Math.cos(speed);
  }

  ctx.controls.target.lerp(targetPos, targetSmooth);
  ctx.camera.position.lerp(targetPos.clone().add(ctx.cameraFollow.offset), targetSmooth);
  ctx.camera.lookAt(ctx.controls.target);
}
