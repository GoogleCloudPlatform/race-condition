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
import { IMapPath } from './path';
import { StationZone } from './water-station';

/**
 * Lightweight adapter wrapping a CatmullRomCurve3 to satisfy IMapPath.
 * Used by viewport-lookdev.ts so Runner can traverse CatmullRom splines
 * without building full MapPath ribbon geometry.
 */
export class CatmullRomPathAdapter implements IMapPath {
  readonly allStations: StationZone[] = [];
  readonly lengthMi: number | null;
  private curve: THREE.CatmullRomCurve3;
  private totalLen: number;

  constructor(
    curve: THREE.CatmullRomCurve3,
    options?: {
      lengthMi?: number;
      stations?: StationZone[];
    },
  ) {
    this.curve = curve;
    this.totalLen = curve.getLength();
    this.lengthMi = options?.lengthMi ?? null;
    if (options?.stations) this.allStations.push(...options.stations);
  }

  getPositionAt(t: number): THREE.Vector3 {
    return this.curve.getPointAt(Math.max(0, Math.min(1, t)));
  }

  getTangentAt(t: number): THREE.Vector3 {
    return this.curve.getTangentAt(Math.max(0, Math.min(1, t)));
  }

  getTotalLength(): number {
    return this.totalLen;
  }
}
