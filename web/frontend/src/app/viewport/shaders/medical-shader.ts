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
 * Medical / vein-like animated material.
 * Scrolls one texture along U while sinusoidally
 *
 * Uniforms:
 *   uTime            – elapsed time in seconds, updated every frame
 *   medicalMap       – the texture to animate
 *   repeat           – UV tiling (default 1×1)
 *   speed            – scroll speed along U (default 0.1)
 *   frequency        – sine frequency along V (default 6.0)
 *   baseColor        – base surface tint
 *   medicalColor     – tint applied to the texture sample
 *   medicalIntensity – brightness multiplier for the texture
 *   vFade            – 0 = no fade, 1 = fade out toward V=1
 */
export function createMedicalMaterial(): THREE.ShaderMaterial {
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
        uTime:           { value: 0.0 },
        medicalMap:      { value: blackTex },
        repeat:          { value: new THREE.Vector2(4, 1) },
        speed:           { value: 0.1 },
        offset:          { value: new THREE.Vector2(0, 0.2) },
        pulseSpeed:      { value: 0.5 },
        pulseWidth:      { value: 0.3 },
        pulseCount:      { value: 2.0 },
        baseColor:       { value: new THREE.Color(0x880088) },
        glowColor:       { value: new THREE.Color(0xff88ff) },
        glowIntensity:   { value: 3.0 },
        vFade:           { value: 0.0 },
        activeColor:     { value: new THREE.Color(0xffa3ff) },
        activeStrength:  { value: 0.0 },
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
      uniform sampler2D medicalMap;
      uniform vec2      repeat;
      uniform float     speed;
      uniform vec2      offset;
      uniform float     pulseSpeed;
      uniform float     pulseWidth;
      uniform float     pulseCount;
      uniform float     frequency;
      uniform vec3      baseColor;
      uniform vec3      glowColor;
      uniform float     glowIntensity;
      uniform float     vFade;
      uniform vec3      activeColor;
      uniform float     activeStrength;

      varying vec2 vUv;
      varying vec2 vActiveUv;

      void main() {

        float u = vUv.x - uTime * speed;
        vec2 animUv = vec2(u, vUv.y) * repeat + offset;
        vec3 tex    = texture2D(medicalMap, animUv).rgb;

        // Travelling pulse mask along U — sharp leading edge, smooth trailing fade
        float phase = fract((vUv.x - uTime * pulseSpeed) * pulseCount);
        float pulse = smoothstep(0.0, pulseWidth, phase)  // smooth trail (back of pulse)
                    * step(phase, 1.0 - pulseWidth);       // sharp front (leading edge)

        vec3 col    = tex * glowColor * glowIntensity * pulse;

        // V-direction fade: fades to 0 toward V=1
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

        gl_FragColor = vec4(baseColor + activeGlow + col * fade, fade);
        #include <fog_fragment>
      }
    `,
  });
}
