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

/**
 * Rising animated particle system.
 *
 * Particles rise along the Y axis, fading out as they climb.
 * Each particle has an independent random speed and phase offset.
 * The particle shape and colour are driven by a texture sampled via gl_PointCoord.
 *
 * Uniforms:
 *   uTime        – accumulated elapsed time in seconds, updated every frame
 *   uSize        – base point size (window.innerHeight * 0.1)
 *   uPixelRatio  – device pixel ratio for crisp points on HiDPI screens
 *   uMap         – particle texture (sampled with gl_PointCoord)
 *
 * @param map            Texture to use for each particle sprite.
 * @param color          Tint colour multiplied with the texture (default: white).
 * @param radius         Radius of the XZ spawn circle (default: 100).
 * @param count          Number of particles (default: 100).
 * @param scaleMin       Minimum particle scale (default: 80).
 * @param scaleMax       Maximum particle scale (default: 80).
 * @param randomRotation Whether each particle gets a random fixed rotation (default: false).
 * @returns              The THREE.Points object — add to the scene or a parent as needed.
 *                       Access `.material` to tick `uTime` each frame.
 */
export function createAnimatedParticles(
  color: THREE.ColorRepresentation = 0xffffff,
  map: THREE.Texture,
  radius         = 100,
  count          = 100,
  scaleMin       = 80,
  scaleMax       = 80,
  randomRotation = false,
): THREE.Points {
  const positions  = new Float32Array(count * 3);
  const scales     = new Float32Array(count);
  const times      = new Float32Array(count);
  const speeds     = new Float32Array(count);
  const rotations  = new Float32Array(count);

  for (let i = 0; i < count; i++) {
    const angle = Math.random() * Math.PI * 2;
    const r     = Math.sqrt(Math.random()) * radius;  // sqrt for uniform disk distribution
    positions[i * 3]     = Math.cos(angle) * r;       // X
    positions[i * 3 + 1] = 0;                         // Y origin (rises in shader)
    positions[i * 3 + 2] = Math.sin(angle) * r;       // Z
    scales[i]    = scaleMin + Math.random() * (scaleMax - scaleMin);
    times[i]     = Math.random();                      // stagger phase
    speeds[i]    = 0.25 + Math.random() * 0.5;         // 0.25 – 0.75
    rotations[i] = randomRotation ? Math.PI + Math.random() * 1.5 - 0.75 : 0.0;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position',  new THREE.BufferAttribute(positions,  3));
  geometry.setAttribute('aScale',    new THREE.BufferAttribute(scales,     1));
  geometry.setAttribute('time',      new THREE.BufferAttribute(times,      1));
  geometry.setAttribute('speed',     new THREE.BufferAttribute(speeds,     1));
  geometry.setAttribute('aRotation', new THREE.BufferAttribute(rotations,  1));

  geometry.computeBoundingSphere();
  if(geometry.boundingSphere) {
    geometry.boundingSphere.radius = 250;
  }

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite:  false,
    blending:    THREE.AdditiveBlending,
    uniforms: {
      uTime:       { value: 0.0 },
      uSize:       { value: window.innerHeight * 0.1 },
      uPixelRatio: { value: window.devicePixelRatio },
      uMap:        { value: map },
      uColor:      { value: new THREE.Color(color) },
      uHeight:     { value: 500.0 },
    },

    vertexShader: `
      attribute float aScale;
      attribute float time;
      attribute float speed;
      attribute float aRotation;

      uniform float uTime;
      uniform float uSize;
      uniform float uPixelRatio;
      uniform float uHeight;

      varying float vAlpha;
      varying float vRotation;

      void main() {
        float localTime = mod(time + uTime * speed, 1.0);

        vec3 animated = position;
        animated.y = localTime * uHeight;

        vAlpha    = 1.0 - pow(localTime, 0.5);
        vRotation = aRotation;

        vec4 mvPosition = modelViewMatrix * vec4(animated, 1.0);
        gl_PointSize = aScale * uSize * uPixelRatio * (1.0 / -mvPosition.z);
        gl_Position  = projectionMatrix * mvPosition;
      }
    `,

    fragmentShader: `
      uniform sampler2D uMap;
      uniform vec3 uColor;
      varying float vAlpha;
      varying float vRotation;

      void main() {
        // Rotate gl_PointCoord around the sprite centre (0.5, 0.5)
        vec2  uv  = gl_PointCoord - 0.5;
        float s   = sin(vRotation);
        float c   = cos(vRotation);
        uv        = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y) + 0.5;

        vec4 texColor = texture2D(uMap, uv);
        gl_FragColor  = vec4(texColor.rgb * uColor, texColor.a * vAlpha);
      }
    `,
  });

  return new THREE.Points(geometry, material);
}
