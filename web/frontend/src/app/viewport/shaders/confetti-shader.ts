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

export interface ConfettiOptions {
  count?: number;
  spawnRadius?: number;
  fallHeight?: number;
  speedMin?: number;
  speedMax?: number;
  width?: number;
  height?: number;
  maxRotationSpeed?: number;
  colors?: THREE.ColorRepresentation[];
}

/** Default Google-brand confetti palette */
const DEFAULT_COLORS: THREE.ColorRepresentation[] = [
  0x009649,
  0x008EFF,
  0x0F2EFF,
  0xF686E5,
  0xFF4B64,
  0xFD6800,
  0xFFC200, 
  0x009649,
];

/**
 * Endlessly looping confetti effect using shader-animated planes.
 *
 * Each piece falls from the top of `fallHeight` to the bottom, then instantly
 * loops back to the top — identical to the animated-particle-shader approach.
 * Per-particle `aPhase` offsets distribute pieces across the full fall range
 * at any point in time. All motion is pure GLSL; zero CPU work per frame.
 *
 * Add to `ctx.camera` (camera is in scene via `ctx.scene.add(ctx.camera)`)
 * for a screen-filling effect, or to the scene for a world-space placement.
 *
 * Drive `material.uniforms['uTime'].value += delta` each frame.
 * Set `uTime = 0` (or any value >= 0) to start; set to -1 to hide.
 *
 * @returns THREE.Mesh — add to camera or scene; drive uTime externally.
 */
export function createConfettiParticles(options: ConfettiOptions = {}): THREE.Mesh {
  const {
    count            = 500,
    spawnRadius      = 800,
    fallHeight       = 800,
    speedMin         = 0.15,
    speedMax         = 0.3,
    width            = 12,
    height           = 6,
    maxRotationSpeed = 8.0,
    colors           = DEFAULT_COLORS,
  } = options;

  const vertexCount = count * 4;

  const positions = new Float32Array(vertexCount * 3); // quad corner offsets (x,y,0)
  const aSpawnPos = new Float32Array(vertexCount * 3); // XZ spread, Y unused (driven by shader)
  const aPhase    = new Float32Array(vertexCount);     // random 0-1 phase
  const aSpeed    = new Float32Array(vertexCount);     // fall speed multiplier
  const aRotAxis  = new Float32Array(vertexCount * 3);
  const aRotSpeed = new Float32Array(vertexCount);
  const aSize     = new Float32Array(vertexCount * 2);
  const aColor    = new Float32Array(vertexCount * 3);
  const indices   = new Uint32Array(count * 6);

  const CORNERS: [number, number][] = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]];
  const _col = new THREE.Color();

  for (let i = 0; i < count; i++) {
    // Flat XZ scatter — Y is driven by the shader loop
    const angle = Math.random() * Math.PI * 2;
    const r     = Math.sqrt(Math.random()) * spawnRadius; // uniform disc
    const sx    = Math.cos(angle) * r;
    const sz    = Math.sin(angle) * r;

    // Random normalised rotation axis
    let ax = Math.random() - 0.5;
    let ay = Math.random() - 0.5;
    let az = Math.random() - 0.5;
    const al = Math.sqrt(ax * ax + ay * ay + az * az) || 1;
    ax /= al; ay /= al; az /= al;

    const rotSpeed = (Math.random() * 2 - 1) * maxRotationSpeed;
    const phase    = Math.random();                             // distribute pieces across fall range
    const speed    = speedMin + Math.random() * (speedMax - speedMin);

    _col.set(colors[Math.floor(Math.random() * colors.length)]);

    for (let v = 0; v < 4; v++) {
      const vi = i * 4 + v;

      positions[vi * 3]     = CORNERS[v][0];
      positions[vi * 3 + 1] = CORNERS[v][1];
      positions[vi * 3 + 2] = 0;

      aSpawnPos[vi * 3]     = sx;
      aSpawnPos[vi * 3 + 1] = 0;
      aSpawnPos[vi * 3 + 2] = sz;

      aPhase[vi]    = phase;
      aSpeed[vi]    = speed;

      aRotAxis[vi * 3]     = ax;
      aRotAxis[vi * 3 + 1] = ay;
      aRotAxis[vi * 3 + 2] = az;

      aRotSpeed[vi] = rotSpeed;

      aSize[vi * 2]     = width;
      aSize[vi * 2 + 1] = height;

      aColor[vi * 3]     = _col.r;
      aColor[vi * 3 + 1] = _col.g;
      aColor[vi * 3 + 2] = _col.b;
    }

    // Two triangles per quad
    const base = i * 4;
    const ii   = i * 6;
    indices[ii]     = base;
    indices[ii + 1] = base + 1;
    indices[ii + 2] = base + 2;
    indices[ii + 3] = base;
    indices[ii + 4] = base + 2;
    indices[ii + 5] = base + 3;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',  new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aSpawnPos', new THREE.BufferAttribute(aSpawnPos, 3));
  geometry.setAttribute('aPhase',    new THREE.BufferAttribute(aPhase,    1));
  geometry.setAttribute('aSpeed',    new THREE.BufferAttribute(aSpeed,    1));
  geometry.setAttribute('aRotAxis',  new THREE.BufferAttribute(aRotAxis,  3));
  geometry.setAttribute('aRotSpeed', new THREE.BufferAttribute(aRotSpeed, 1));
  geometry.setAttribute('aSize',     new THREE.BufferAttribute(aSize,     2));
  geometry.setAttribute('aColor',    new THREE.BufferAttribute(aColor,    3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));

  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 99999);

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite:  false,
    side:        THREE.DoubleSide,
    uniforms: {
      uTime:       { value: -1.0 },   // set to 0 to start; -1 = hidden
      uFallHeight: { value: fallHeight },
      uDriftAmp:   { value: 80.0 },   // XZ sway amplitude
      uAlpha: { value: 1.0 },
    },

    vertexShader: /* glsl */`
      const float TWO_PI = 6.28318530718;

      attribute vec3  aSpawnPos;
      attribute float aPhase;
      attribute float aSpeed;
      attribute vec3  aRotAxis;
      attribute float aRotSpeed;
      attribute vec2  aSize;
      attribute vec3  aColor;

      uniform float uTime;
      uniform float uFallHeight;
      uniform float uDriftAmp;

      varying vec3  vColor;
      varying float vAlpha;

      mat3 rotMat(vec3 axis, float angle) {
        float c = cos(angle), s = sin(angle), t = 1.0 - c;
        float x = axis.x,  y = axis.y,  z = axis.z;
        return mat3(
          t*x*x + c,     t*x*y + s*z,   t*x*z - s*y,
          t*x*y - s*z,   t*y*y + c,     t*y*z + s*x,
          t*x*z + s*y,   t*y*z - s*x,   t*z*z + c
        );
      }

      void main() {
        // Looping 0→1 time, offset per particle so they're spread across the range
        float localTime = mod(aPhase + uTime * aSpeed, 1.0);
        float angle     = localTime * TWO_PI;

        vec3 pos = aSpawnPos;

        // XZ drift: slightly different frequencies on each axis
        pos.x += sin(angle * 1.1 + aPhase * TWO_PI) * uDriftAmp;
        pos.z += cos(angle * 0.9 + aPhase * TWO_PI) * uDriftAmp * 0.7;

        pos.y = uFallHeight * (0.5 - localTime)
              + uFallHeight * sin(angle * 3.0) * 0.04;

        // Continuous tumble — driven by absolute uTime so rotation never snaps at the loop
        mat3 rot    = rotMat(aRotAxis, uTime * aRotSpeed);
        vec3 corner = rot * vec3(position.xy * aSize, 0.0);

        vColor = aColor;

        // Fade in over first 5 % of cycle, fade out over last 5 % — hides the loop seam
        float fadeIn  = smoothstep(0.0,  0.05, localTime);
        float fadeOut = 1.0 - smoothstep(0.95, 1.0, localTime);
        vAlpha = (uTime >= 0.0) ? fadeIn * fadeOut : 0.0;

        gl_Position = projectionMatrix * modelViewMatrix * vec4(pos + corner, 1.0);
      }
    `,

    fragmentShader: /* glsl */`
      uniform float uAlpha;
      varying vec3  vColor;
      varying float vAlpha;

      void main() {
        if (vAlpha*uAlpha <= 0.0) discard;
        gl_FragColor = vec4(vColor, vAlpha*uAlpha);
      }
    `,
  });

  const mesh = new THREE.Mesh(geometry, material);
  mesh.geometry.computeBoundingSphere();
  if (mesh.geometry.boundingSphere) {
    mesh.geometry.boundingSphere.radius = 2000;
  }
  return mesh;
}
