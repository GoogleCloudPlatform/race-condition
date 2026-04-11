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

export const DepthOutlineShader = {
  name: 'DepthOutlineShader',
  uniforms: {
    'tDiffuse':                { value: null },
    'tDepth':                  { value: null },
    'resolution':              { value: new THREE.Vector2(1, 1) },
    'cameraNear':              { value: 0.1 },
    'cameraFar':               { value: 10.0 },
    'threshold':               { value: 0.002 },
    'outlineColor':            { value: new THREE.Color(0x000000) },
    'outlineColorLow':         { value: new THREE.Color(0x000000) },
    'heightFadeMin':           { value: 0.0 },
    'heightFadeMax':           { value: 0.3 },
    'projectionMatrixInverse': { value: new THREE.Matrix4() },
    'viewMatrixInverse':       { value: new THREE.Matrix4() },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
    }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform sampler2D tDepth;
    uniform vec2      resolution;
    uniform float     cameraNear;
    uniform float     cameraFar;
    uniform float     threshold;
    uniform vec3      outlineColor;
    uniform vec3      outlineColorLow;
    uniform float     heightFadeMin;
    uniform float     heightFadeMax;
    uniform mat4      projectionMatrixInverse;
    uniform mat4      viewMatrixInverse;
    varying vec2 vUv;

    float linearDepth( float d ) {
      return ( 2.0 * cameraNear ) / ( cameraFar + cameraNear - d * ( cameraFar - cameraNear ) );
    }

    void main() {
      vec2 texel = 1.0 / resolution;

      float rawDepth = texture2D( tDepth, vUv ).r;
      float d0 = linearDepth( rawDepth );
      float d1 = linearDepth( texture2D( tDepth, vUv + vec2(  texel.x, 0.0     ) ).r );
      float d2 = linearDepth( texture2D( tDepth, vUv + vec2( -texel.x, 0.0     ) ).r );
      float d3 = linearDepth( texture2D( tDepth, vUv + vec2(  0.0,     texel.y ) ).r );
      float d4 = linearDepth( texture2D( tDepth, vUv + vec2(  0.0,    -texel.y ) ).r );

      float gx = d1 - d2;
      float gy = d3 - d4;
      float edge = sqrt( gx * gx + gy * gy );
      float outline = step( threshold, edge );

      // Reconstruct world-space Y from depth
      vec4 ndcPos = vec4( vUv * 2.0 - 1.0, rawDepth * 2.0 - 1.0, 1.0 );
      vec4 viewPos = projectionMatrixInverse * ndcPos;
      viewPos /= viewPos.w;
      float worldY = ( viewMatrixInverse * viewPos ).y;

      // Height-based outline colour fade
      float heightFade = smoothstep( heightFadeMin, heightFadeMax, worldY );
      vec3 finalOutlineColor = mix( outlineColorLow, outlineColor, heightFade );

      vec4 color = texture2D( tDiffuse, vUv );
      gl_FragColor = mix( color, vec4( finalOutlineColor, 1.0 ), outline );
    }
  `,
};
