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
import { MapPath } from './path';

const GRADIENT_SEGMENTS = 200;
const RIBBON_WIDTH = 2.5;
const Y_GRADIENT = 0.25;

function lerpColor(a: THREE.Color, b: THREE.Color, t: number): THREE.Color {
  return new THREE.Color(
    a.r + (b.r - a.r) * t,
    a.g + (b.g - a.g) * t,
    a.b + (b.b - a.b) * t,
  );
}

function rateToColor(rate: number): THREE.Color {
  const green = new THREE.Color(0x22cc66);
  const yellow = new THREE.Color(0xeecc22);
  const red = new THREE.Color(0xdd3333);
  if (rate >= 0.5) return lerpColor(yellow, green, (rate - 0.5) * 2);
  return lerpColor(red, yellow, rate * 2);
}

export class GradientPathMesh {
  private mesh: THREE.Mesh | null = null;
  private scene: THREE.Scene;
  private path: MapPath;
  private segmentRates: number[] = [];
  private visibleSegmentCount = GRADIENT_SEGMENTS;

  constructor(scene: THREE.Scene, path: MapPath) {
    this.scene = scene;
    this.path = path;
    this.segmentRates = new Array(GRADIENT_SEGMENTS).fill(1.0);
  }

  updateRates(rates: number[]): void {
    this.segmentRates = rates;
    this.rebuild();
  }

  setVisibleSegmentCount(count: number): void {
    this.visibleSegmentCount = Math.max(0, Math.min(GRADIENT_SEGMENTS, count));
    this.rebuild();
  }

  private rebuild(): void {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
      (this.mesh.material as THREE.Material).dispose();
      this.mesh = null;
    }

    if (this.visibleSegmentCount < 1) return;

    const pos: number[] = [];
    const colors: number[] = [];
    const idx: number[] = [];

    for (let i = 0; i < this.visibleSegmentCount; i++) {
      const t0 = i / GRADIENT_SEGMENTS;
      const t1 = (i + 1) / GRADIENT_SEGMENTS;

      const p0 = this.path.getPositionAt(t0);
      const p1 = this.path.getPositionAt(t1);
      const tang = new THREE.Vector3().subVectors(p1, p0).normalize();
      const perp = new THREE.Vector3(-tang.z, 0, tang.x);

      const rate = this.segmentRates[i] ?? 1.0;
      const col = rateToColor(rate);

      const base = pos.length / 3;

      pos.push(
        p0.x + perp.x * RIBBON_WIDTH * 0.5, Y_GRADIENT, p0.z + perp.z * RIBBON_WIDTH * 0.5,
        p0.x - perp.x * RIBBON_WIDTH * 0.5, Y_GRADIENT, p0.z - perp.z * RIBBON_WIDTH * 0.5,
        p1.x + perp.x * RIBBON_WIDTH * 0.5, Y_GRADIENT, p1.z + perp.z * RIBBON_WIDTH * 0.5,
        p1.x - perp.x * RIBBON_WIDTH * 0.5, Y_GRADIENT, p1.z - perp.z * RIBBON_WIDTH * 0.5,
      );

      for (let v = 0; v < 4; v++) {
        colors.push(col.r, col.g, col.b);
      }

      idx.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geo.setIndex(idx);

    const mat = new THREE.MeshBasicMaterial({
      vertexColors: true,
      depthTest: false,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.82,
    });

    this.mesh = new THREE.Mesh(geo, mat);
    this.mesh.renderOrder = 6;
    this.scene.add(this.mesh);
  }

  dispose(): void {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
      (this.mesh.material as THREE.Material).dispose();
      this.mesh = null;
    }
  }
}

export { GRADIENT_SEGMENTS };
