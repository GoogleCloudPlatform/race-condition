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
 * Uniforms:
 *   tDiffuse  – input render target (set automatically by ShaderPass)
 *   offset    – controls the spread/size of the vignette (default: 1.0)
 *   darkness  – controls the blend strength at the edges   (default: 1.0)
 *   uColor    – vignette edge colour                       (default: black)
 */
export const VignetteColorShader = {

  name: 'VignetteColorShader',

  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    offset:   { value: 1.0 },
    darkness: { value: 1.0 },
    uColor:   { value: new THREE.Color(0x000000) },
  },

  vertexShader: /* glsl */`
    varying vec2 vUv;

    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
    }`,

  fragmentShader: /* glsl */`
    uniform float offset;
    uniform float darkness;
    uniform vec3  uColor;

    uniform sampler2D tDiffuse;

    varying vec2 vUv;

    void main() {
      // Eskil's vignette — identical to VignetteShader but mixes towards uColor.
      vec4 texel = texture2D( tDiffuse, vUv );
      vec2 uv    = ( vUv - vec2( 0.5 ) ) * vec2( offset );
      gl_FragColor = vec4( mix( texel.rgb, uColor * ( 1.0 - darkness ), dot( uv, uv ) ), texel.a );
    }`,
};
