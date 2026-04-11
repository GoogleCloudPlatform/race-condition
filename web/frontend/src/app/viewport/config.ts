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

/** Tweakable fog far-plane distance; mutated by the Tweakpane debug panel. */
export const baseFog = { far: 9000 };

/** World-space offset from the orbit target to the directional light. */
export const lightOffset = new THREE.Vector3(-6000, 5000, 5000);

// ── Map center ──────────────────────────────────────────────────────────────
// Set these to the lat/lon that should appear at the origin of the 3D world.
// Adjust to align imported paths with the GLB road mesh.
export const MAP_CENTER_LAT =  36.1085;
export const MAP_CENTER_LON = -115.1769;
