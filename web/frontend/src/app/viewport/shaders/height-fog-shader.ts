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
 * Building base material with height-based fog, emissive window tiling,
 * route light-up map, and directional shadow support.
 *
 * After creation set `uniforms['emissiveMap'].value` to the window texture.
 */
export function createHeightFogMaterial(): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    fog:    true,
    lights: true,
    uniforms: THREE.UniformsUtils.merge([
      THREE.UniformsLib['fog'],
      THREE.UniformsLib['lights'],
      {
        heightFogColor:             { value: new THREE.Color(0x000000) },
        baseColor:                  { value: new THREE.Color(0x2b2e30) },
        heightFogNear:              { value: 90 },
        heightFogFar:               { value: 0.0 },
        heightFogDensity:           { value: 0.75 },
        emissiveMap:                { value: null },
        emissiveColor:              { value: new THREE.Color(0xB0BCBF) },
        emissiveIntensity:          { value: 0.5 },
        emissiveRepeat:             { value: new THREE.Vector2(30, 30) },
        normalFogOnEmissiveDensity: { value: 0.2 },
        routeMap:                   { value: null },
        worldUvScale:               { value: 0.000049 },
        routeLightUp:               { value: 0 },
      },
    ]),
    vertexShader: `
      #include <common>
      #include <fog_pars_vertex>
      #include <shadowmap_pars_vertex>
      uniform float worldUvScale;
      varying vec3 vWorldPosition;
      varying vec2 vUv;
      varying vec3 vWorldNormal;
      varying vec3 vNormal;
      varying vec2 worldUv;
      void main() {
        vUv = uv;
        vec4 worldPos = modelMatrix * vec4(position, 1.0);
        worldUv = vec2(worldPos.x*worldUvScale, worldPos.z*-worldUvScale);
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
      uniform vec3      heightFogColor;
      uniform vec3      baseColor;
      uniform float     heightFogNear;
      uniform float     heightFogFar;
      uniform float     heightFogDensity;
      uniform sampler2D emissiveMap;
      uniform vec3      emissiveColor;
      uniform float     emissiveIntensity;
      uniform vec2      emissiveRepeat;
      uniform float     normalFogOnEmissiveDensity;
      uniform sampler2D routeMap;
      uniform float     routeLightUp;
      varying vec3 vWorldPosition;
      varying vec2 vUv;
      varying vec3 vWorldNormal;
      varying vec3 vNormal;
      varying vec2 worldUv;

      void main() {
        vec3 routeTexture = texture2D( routeMap, worldUv+0.5 ).rgb;
        float hFogFactor = smoothstep(heightFogNear, heightFogFar, vWorldPosition.y);
        float sideFacing = smoothstep( 1.0, 0.0, vWorldNormal.y );
        vec3 emissiveTexture = texture2D( emissiveMap, vUv * emissiveRepeat ).rgb;
        vec3 emissive = (emissiveTexture.r + routeTexture.r*routeLightUp) * emissiveColor * emissiveIntensity * sideFacing;
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
        gl_FragColor = vec4(mix(baseColor, heightFogColor, hFogFactor * heightFogDensity) * irradiance + emissive, 1.0);
        float fogFactor = smoothstep( fogNear, fogFar, vFogDepth ) - ((1.0-normalFogOnEmissiveDensity)*min(emissiveTexture.r+routeTexture.r, 1.0))*sideFacing;
        gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
      }
    `,
  });
}
