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

const ROUTE_NAMES = [
  'Alpha', 'Beta', 'Gamma', 'Delta',
  'Epsilon', 'Zeta', 'Eta', 'Theta'
];
let nameIdx = 0;
export function nextPathName(): string {
  return ROUTE_NAMES[nameIdx++ % ROUTE_NAMES.length];
}

const PATH_PALETTE = [
  0x2aabaa, 0xe07c38, 0xd4b800, 0x3daa55,
  0x3577d4, 0x8844cc, 0xcc4488, 0x2aabaa,
];
let colourIdx = 0;
export function nextPathColor(): THREE.Color {
  return new THREE.Color(PATH_PALETTE[colourIdx++ % PATH_PALETTE.length]);
}
