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

const PARTICLE_COUNT = 5000;

/**
 * Ambient floating particle system.
 *
 * Uniforms:
 *   globalTime – accumulated elapsed time, updated every frame
 *   scale      – controls screen-space point size relative to camera distance
 *   color      – particle tint colour
 */
export function initParticles(ctx: Context): void {
  const positions = new Float32Array(PARTICLE_COUNT * 3);
  const sizes     = new Float32Array(PARTICLE_COUNT);
  const times     = new Float32Array(PARTICLE_COUNT);

  for (let i = 0; i < PARTICLE_COUNT; i++) {
    positions[i * 3]     = (Math.random() - 0.5) * 15000;  // X spread
    positions[i * 3 + 1] =  Math.random()        *  3000;  // Y height band
    positions[i * 3 + 2] = (Math.random() - 0.5) * 15000;  // Z spread
    sizes[i] = 4 + Math.random() * 10;
    times[i] = Math.random();                              // stagger animation phase
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('size',     new THREE.BufferAttribute(sizes,     1));
  geometry.setAttribute('time',     new THREE.BufferAttribute(times,     1));

  const material = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite:  false,
    blending:    THREE.NormalBlending,
    uniforms: {
      globalTime: { value: 0 },
      scale:      { value: window.innerHeight },
      color:      { value: new THREE.Color(0xbfc0de) },
    },

    vertexShader: `
      attribute float size;
      attribute float time;
      uniform float globalTime;
      uniform float scale;

      void main() {
        vec3 pos = position;

        float localTime = time + globalTime * 0.01;
        float modTime   = mod(localTime, 1.0);
        float accTime   = modTime * modTime;

        pos.x += cos(accTime * 2.0 + position.z) * 50.0;
        pos.y += sin(accTime * 4.0 + position.x) * 500.0;
        pos.z += accTime * 1500.0;
        pos.z += sin(accTime * 4.0 + position.y) * 50.0;

        vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);

        float sizem = sin(modTime * 10.0 + pos.z * 0.1) + 0.5;
        gl_PointSize = max(0.5, size * sizem) * (scale / length(mvPosition.xyz));
        gl_Position  = projectionMatrix * mvPosition;
      }
    `,

    fragmentShader: `
      uniform vec3 color;

      void main() {
        // Diamond: discard fragments outside |x-0.5| + |y-0.5| < 0.5
        vec2  pc   = gl_PointCoord - 0.5;
        float dist = abs(pc.x) + abs(pc.y);
        if (dist > 0.5) discard;

        gl_FragColor    = vec4(color, 0.6);
        gl_FragColor.w *= pow(gl_FragCoord.z, 8.0);
      }
    `,
  });

  ctx.particleMaterial = material;
  ctx.scene.add(new THREE.Points(geometry, material));
}
