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
 * Animated sphere material.
 *
 * Uniforms:
 *   uTime       – elapsed time in seconds, updated every frame
 *   uBaseColor  – dark base fill visible at wave troughs
 *   uColor0/1/2 – three colours to cycle through (#00AB49, #1E88FD, #FFB900)
 *   uCycleSpeed – how fast the colour cycles (full loop = 1 / uCycleSpeed seconds)
 *   unlitColor  – colour shown when litAmount = 0 (intro dark state)
 *   litAmount   – 0 = unlit, 1 = fully lit
 */
export function createSphereMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    fog: true,
    uniforms: THREE.UniformsUtils.merge([
      THREE.UniformsLib['fog'],
      {
        uTime:       { value: 0.0 },
        uBaseColor:  { value: new THREE.Color(0x313d43) },
        uColor0:     { value: new THREE.Color(0x00AB49) },
        uColor1:     { value: new THREE.Color(0x1E88FD) },
        uColor2:     { value: new THREE.Color(0xFFB900) },
        uCycleSpeed: { value: 0.06 },
        unlitColor:  { value: new THREE.Color(0x333333) },
        litAmount:   { value: 1.0 },
      },
    ]),

    vertexShader: `
      #include <fog_pars_vertex>
      varying vec2 vUv;
      void main() {
        vUv = uv;
        vec4 worldPos  = modelMatrix * vec4(position, 1.0);
        vec4 mvPosition = viewMatrix * worldPos;
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }
    `,

    fragmentShader: `
      #include <fog_pars_fragment>
      uniform float uTime;
      uniform vec3  uBaseColor;
      uniform vec3  uColor0;
      uniform vec3  uColor1;
      uniform vec3  uColor2;
      uniform float uCycleSpeed;
      uniform vec3  unlitColor;
      uniform float litAmount;
      varying vec2  vUv;

      void main() {
        vec2  uv = vUv;
        float s1 = 0.5 + 0.5  * sin( uTime + uv.x * 3.1415 * ( cos( uTime )       + 2.0 ) );
        float s2 = 0.5 + 0.25 * cos( uTime + uv.x * 3.1415 * ( sin( uTime ) * 2.0 + 2.0 ) );
        float r  = pow( 1.0 - sqrt( abs( uv.y - s1 ) ), 3.5 );
        float g  = pow( 1.0 - sqrt( abs( uv.y - s2 ) ), 2.5 );
        float b  = 2.0 * ( r + g );
        float final = (g + b) * 0.6;

        // Cycle smoothly through uColor0 → uColor1 → uColor2 → uColor0
        float t  = mod( uTime * uCycleSpeed, 1.0 );
        float t3 = t * 3.0;
        vec3 cycleColor;
        if ( t3 < 1.0 ) {
          cycleColor = mix( uColor0, uColor1, smoothstep( 0.0, 1.0, t3 ) );
        } else if ( t3 < 2.0 ) {
          cycleColor = mix( uColor1, uColor2, smoothstep( 0.0, 1.0, t3 - 1.0 ) );
        } else {
          cycleColor = mix( uColor2, uColor0, smoothstep( 0.0, 1.0, t3 - 2.0 ) );
        }

        vec3 baseColor = mix( uBaseColor, cycleColor, final );
        gl_FragColor = vec4( mix( unlitColor, baseColor, litAmount ), 1.0 );
        #include <fog_fragment>
      }
    `,
  });
}
