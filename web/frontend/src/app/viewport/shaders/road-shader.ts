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
 * Custom road surface material.
 *
 * Uniforms:
 *   color             – base surface colour
 *   emissive          – emissive tint colour
 *   emissiveMap       – emissive texture (e.g. animated traffic)
 *   emissiveIntensity – emissive brightness multiplier
 *   maskMap1          – greyscale mask: white suppresses / hides the emissiveMap
 *   maskMap2              – greyscale mask: white shifts the emissive tint to maskColor2
 *   maskColor2            – target emissive colour driven by maskMap2
 *   emissiveMapRepeat     – UV repeat for emissiveMap (default 1,1)
 *   emissiveMapOffset     – UV offset for emissiveMap (default 0,0)
 */
export function createRoadsMaterial(): THREE.ShaderMaterial {
  // 1×1 black fallback so uniforms are never null before textures are assigned.
  const blackTex = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
  blackTex.needsUpdate = true;

  return new THREE.ShaderMaterial({
    fog:         true,
    depthWrite:  false,
    //transparent: true,
    uniforms: THREE.UniformsUtils.merge([
      THREE.UniformsLib['fog'],
      {
        color:             { value: new THREE.Color(0x141414) },
        //emissive:          { value: new THREE.Color(0x58525d) },
        emissive:          { value: new THREE.Color(0xb0bcbf) },
        emissiveMap:       { value: blackTex },
        emissiveMapStopped:{ value: blackTex },
        emissiveIntensity: { value: 1.0 },
        maskMap1:          { value: blackTex },
        maskMap2:              { value: blackTex },
        maskColor2:            { value: new THREE.Color(0xE76666) },
        maskColor2Intensity:   { value: 3.0 },
        emissiveMapRepeat:     { value: new THREE.Vector2(2, 0.1) },
        emissiveMapOffset:     { value: new THREE.Vector2(0, 0) },
        worldUvScale:          { value: 0.000049 },
        worldUvOffset:         { value: new THREE.Vector2(0.5, 0.5) },
        edgeFadeStart:         { value: 0.2 },
        edgeFadeEnd:           { value: 0.15 },
        edgeFadeColor:         { value: new THREE.Color(0x414244) },
      },
    ]),

    vertexShader: `
      #include <common>
      #include <fog_pars_vertex>
      uniform float worldUvScale;
      uniform vec2 worldUvOffset;
      varying vec2 worldUv;
      varying vec2 vUv;
      void main() {
        vUv = uv;
        vec4 worldPos = modelMatrix * vec4(position, 1.0);
        worldUv = vec2(worldPos.x*worldUvScale, worldPos.z*-worldUvScale) + worldUvOffset;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }
    `,

    fragmentShader: `
      #include <common>
      #include <fog_pars_fragment>

      uniform vec3      color;
      uniform vec3      emissive;
      uniform sampler2D emissiveMap;
      uniform sampler2D emissiveMapStopped;
      uniform float     emissiveIntensity;
      uniform sampler2D maskMap1;
      uniform sampler2D maskMap2;
      uniform vec3      maskColor2;
      uniform float     maskColor2Intensity;
      uniform vec2      emissiveMapRepeat;
      uniform vec2      emissiveMapOffset;
      uniform float     edgeFadeStart;
      uniform float     edgeFadeEnd;
      uniform vec3      edgeFadeColor;

      varying vec2 vUv;
      varying vec2 worldUv;

      void main() {
        // maskMap1: white suppresses the emissive map
        float suppress = texture2D(maskMap1, worldUv).r;

        // maskMap2: white shifts the emissive tint and intensity towards maskColor2
        float slow               = texture2D(maskMap2, worldUv).r;
        vec3  emissiveCol        = mix(emissive,           maskColor2,          slow);
        float effectiveIntensity = mix(emissiveIntensity,  maskColor2Intensity, slow);

        // flip UV
        vec2 uv = vUv;
        uv.y = mix(uv.y, 1.0 - uv.y, step(0.5, uv.x));

        // Blend between moving traffic and a frozen sample of the same texture.
        // slow=0 → full movement, slow=1 → fully stopped. No reversal possible.
        vec2 movingUv  = uv * emissiveMapRepeat + emissiveMapOffset;
        vec2 stoppedUv = uv * emissiveMapRepeat * vec2(1.0, 1.0) + emissiveMapOffset * vec2(1.0, 0.2);
        vec3 emissiveTex = mix(
            texture2D(emissiveMap, movingUv).rgb,
            texture2D(emissiveMapStopped, stoppedUv).rgb,
            slow
        );
        //vec3 emissiveTex = texture2D(emissiveMap, emissiveUv).rgb * (1.0 - slow);

        float fadeX    = smoothstep(edgeFadeEnd, edgeFadeStart, worldUv.x)
                       * smoothstep(1.0 - edgeFadeEnd, 1.0 - edgeFadeStart, worldUv.x);
        float fadeY    = smoothstep(edgeFadeEnd, edgeFadeStart, worldUv.y)
                       * smoothstep(1.0 - edgeFadeEnd, 1.0 - edgeFadeStart, worldUv.y);
        float edgeFade = fadeX * fadeY;

        vec3 finalEmissive = emissiveTex * (1.0 - suppress) * emissiveCol * effectiveIntensity;

        gl_FragColor = vec4( mix(edgeFadeColor, color + finalEmissive, edgeFade) , 1.0);
        #include <fog_fragment>
      }
    `,
  });
}
