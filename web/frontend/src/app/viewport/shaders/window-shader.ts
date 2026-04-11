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
 * Window / glass facade material for buildings.
 * Uses a height-based colour gradient (topColor → bottomColor) with
 * directional shadow support and scene fog.
 *
 * Clone the result and override `uniforms['bottomColor']` /
 * `uniforms['topColor']` to create per-building colour variants.
 */
export function createWindowMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    fog:    true,
    lights: true,
    uniforms: THREE.UniformsUtils.merge([
      THREE.UniformsLib['fog'],
      THREE.UniformsLib['lights'],
      {
        bottomColor:      { value: new THREE.Color(0x0250a9) },
        topColor:         { value: new THREE.Color(0x6ddb00) },
        heightFogNear:    { value: 320 },
        heightFogFar:     { value: 0.0 },
        heightFogDensity: { value: 1.0 },
        normalFogDensity: { value: 0.9 },
        unlitColor:       { value: new THREE.Color(0x333333) },
        litAmount:        { value: 1.0 },
      },
    ]),
    vertexShader: `
      #include <common>
      #include <fog_pars_vertex>
      #include <shadowmap_pars_vertex>
      varying vec3 vWorldPosition;
      varying vec2 vUv;
      varying vec3 vWorldNormal;
      varying vec3 vNormal;
      void main() {
        vUv = uv;
        vec4 worldPos = modelMatrix * vec4(position, 1.0);
        vWorldPosition = worldPos.xyz;
        vWorldNormal = normalize( ( modelMatrix * vec4( normal, 0.0 ) ).xyz );
        vec4 mvPosition = viewMatrix * worldPos;
        gl_Position = projectionMatrix * mvPosition;
        vec3 transformedNormal = normalMatrix * normal;
        vNormal = transformedNormal;
        vec4 worldPosition = worldPos;
        #include <shadowmap_vertex>
        #include <fog_vertex>
      }
    `,
    fragmentShader: `
      #include <common>
      #include <fog_pars_fragment>
      #include <shadowmap_pars_fragment>
      #include <lights_pars_begin>
      uniform vec3      bottomColor;
      uniform vec3      topColor;
      uniform float     heightFogNear;
      uniform float     heightFogFar;
      uniform float     heightFogDensity;
      uniform float     normalFogDensity;
      uniform vec3      unlitColor;
      uniform float     litAmount;
      varying vec3 vWorldPosition;
      varying vec2 vUv;
      varying vec3 vWorldNormal;
      varying vec3 vNormal;

      void main() {
        float hFogFactor = smoothstep(heightFogNear, heightFogFar, vWorldPosition.y);
        float shadow = 1.0;
        #if NUM_DIR_LIGHT_SHADOWS > 0
          DirectionalLightShadow dirShadow = directionalLightShadows[ 0 ];
          shadow = getShadow(
            directionalShadowMap[ 0 ],
            dirShadow.shadowMapSize,
            dirShadow.shadowIntensity,
            dirShadow.shadowBias,
            dirShadow.shadowRadius,
            vDirectionalShadowCoord[ 0 ]
          );
        #endif
        vec3 irradiance = ambientLightColor;
        #if NUM_DIR_LIGHTS > 0
          IncidentLight directLight;
          getDirectionalLightInfo( directionalLights[ 0 ], directLight );
          float NdotL = saturate( dot( normalize( vNormal ), directLight.direction ) );
          irradiance += NdotL * directLight.color * shadow;
        #endif
        vec3 baseColor = mix(topColor, bottomColor, heightFogDensity * hFogFactor) * irradiance;
        gl_FragColor = vec4(mix(unlitColor, baseColor, litAmount), 1.0);
        float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
        gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor*normalFogDensity );
      }
    `,
  });
}
