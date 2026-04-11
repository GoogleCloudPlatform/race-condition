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
 * Animated toilet material.
 *
 * Uniforms:
 *   uTime            – elapsed time in seconds, updated every frame
 *   toiletMap        – the toilet texture
 *   repeat           – UV tiling (default 4×4)
 *   speed            – animation speed multiplier (default 0.05)
 *   baseColor        – base surface tint
 *   toiletColor      – tint applied to the caustics sample
 *   toiletIntensity  – brightness multiplier for the caustics
 *   vFade            – 0 = no fade, 1 = fade out toward V=1
 */
export function createToiletMaterial(): THREE.ShaderMaterial {
  const blackTex = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
  blackTex.needsUpdate = true;

  return new THREE.ShaderMaterial({
    fog:        true,
    transparent: true,
    depthWrite:  false,
    blending:    THREE.AdditiveBlending,
    uniforms: THREE.UniformsUtils.merge([
      THREE.UniformsLib['fog'],
      {
        uTime:             { value: 0.0 },
        toiletMap:         { value: blackTex },
        repeat:            { value: new THREE.Vector2(1.0, 1.0) },
        speed:             { value: 0.5 },
        baseColor:         { value: new THREE.Color(0x003136) },
        toiletColor:       { value: new THREE.Color(0x00e4ff) },
        toiletIntensity:   { value: 0.7 },
        vFade:             { value: 0.0 },
        activeColor:       { value: new THREE.Color(0x94f4ff) },
        activeStrength:    { value: 0.0 },
      },
    ]),

    vertexShader: `
      #include <fog_pars_vertex>
      varying vec2 vUv;
      varying vec2 vActiveUv;

      void main() {
        vUv = uv;
        vActiveUv = position.xz / 100.0 * 0.5 + 0.5;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }
    `,

    fragmentShader: `
      #include <fog_pars_fragment>

      uniform float     uTime;
      uniform sampler2D toiletMap;
      uniform vec2      repeat;
      uniform float     speed;
      uniform vec3      baseColor;
      uniform vec3      toiletColor;
      uniform float     toiletIntensity;
      uniform float     vFade;
      uniform vec3      activeColor;
      uniform float     activeStrength;

      varying vec2 vUv;
      varying vec2 vActiveUv;

      vec2 rotateUV(vec2 uv, float angle) {
        float s = sin(angle);
        float c = cos(angle);
        uv -= 0.5;                        // move pivot to origin
        uv  = vec2(c * uv.x - s * uv.y,   // rotate
                    s * uv.x + c * uv.y);
        uv += 0.5;                        // move back
        return uv;
      }

      void main() {
        vec2 rUV = rotateUV(vActiveUv * repeat, uTime * speed);
        vec3 c = texture2D(toiletMap, rUV).rgb;
        vec3 toilet = c * toiletColor * toiletIntensity;

        // V-direction fade: mix(no fade, fade toward V=1, vFade)
        float fade = mix(1.0, 1.0 - vUv.y, vFade);

        // Glow sphere mask
        float radius   = 0.5;
        float softness = 0.6;

        vec2  dist = vActiveUv - vec2(0.5);
        float d    = dot(dist, dist) * 4.0;

        float strength = 1.0 - smoothstep(
            radius - softness,   // inner edge of falloff
            radius + softness,   // outer edge of falloff
            d
        );
        vec3 activeGlow = activeColor * strength * activeStrength;

        gl_FragColor = vec4(baseColor + activeGlow + toilet * fade, fade);
        #include <fog_fragment>
      }
    `,
  });
}
