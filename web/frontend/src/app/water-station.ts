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

export interface StationDef {
  id: number;
  kmMark: number;
  worldPos: THREE.Vector3;
}

export type WaterStationDef = StationDef;
export type MedicalTentDef = StationDef;

export interface StationZone {
  readonly id: number;
  readonly stationType: 'water_station' | 'medical_tent' | 'crowd_zone';
  readonly worldPos: THREE.Vector3;
  readonly radius: number;
  isInsideRadius(position: THREE.Vector3): boolean;
}

export type WaterStationZone = StationZone;

/** Lightweight StationZone for collision detection only (no scene visuals). */
export class SimpleStationZone implements StationZone {
  readonly id: number;
  readonly stationType: 'water_station' | 'medical_tent' | 'crowd_zone';
  readonly worldPos: THREE.Vector3;
  readonly radius: number;
  readonly kmMark: number;

  constructor(id: number, type: 'water_station' | 'medical_tent' | 'crowd_zone', worldPos: THREE.Vector3, radius: number, kmMark = 0) {
    this.id = id;
    this.stationType = type;
    this.worldPos = worldPos.clone();
    this.radius = radius;
    this.kmMark = kmMark;
  }

  isInsideRadius(position: THREE.Vector3): boolean {
    const dx = position.x - this.worldPos.x;
    const dz = position.z - this.worldPos.z;
    return Math.sqrt(dx * dx + dz * dz) <= this.radius;
  }
}

const SEGMENTS = 32;

function buildGradientMaterial(color: THREE.Color, height: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uColor: { value: color },
      uHeight: { value: height },
    },
    vertexShader: `
      varying float vY;
      void main() {
        vY = position.y;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform float uHeight;
      varying float vY;
      void main() {
        float t = clamp(vY / uHeight, 0.0, 1.0);
        float alpha = 0.45 * (1.0 - t);
        gl_FragColor = vec4(uColor, alpha);
      }
    `,
  });
}

abstract class BaseStation implements StationZone {
  readonly id: number;
  readonly kmMark: number;
  readonly worldPos: THREE.Vector3;
  abstract readonly stationType: 'water_station' | 'medical_tent';
  abstract readonly radius: number;

  protected groundMesh!: THREE.Mesh;
  protected columnMesh!: THREE.Mesh;

  constructor(def: StationDef) {
    this.id = def.id;
    this.kmMark = def.kmMark;
    this.worldPos = def.worldPos.clone();
  }

  isInsideRadius(position: THREE.Vector3): boolean {
    const dx = position.x - this.worldPos.x;
    const dz = position.z - this.worldPos.z;
    return Math.sqrt(dx * dx + dz * dz) <= this.radius;
  }

  addToScene(scene: THREE.Scene): void {
    scene.add(this.groundMesh);
    scene.add(this.columnMesh);
  }

  removeFromScene(scene: THREE.Scene): void {
    scene.remove(this.groundMesh);
    scene.remove(this.columnMesh);
    this.groundMesh.geometry.dispose();
    (this.groundMesh.material as THREE.Material).dispose();
    this.columnMesh.geometry.dispose();
    (this.columnMesh.material as THREE.Material).dispose();
  }
}

// ── Water Station (circle + cylinder, blue) ─────────────────────────────────

const WATER_RADIUS = 10.0;
const WATER_CYLINDER_HEIGHT = 24.0;
const WATER_CYLINDER_RADIUS = 7.0;
const WATER_COLOR = new THREE.Color(0x2299ff);

export class WaterStation extends BaseStation {
  readonly stationType = 'water_station' as const;
  readonly radius = WATER_RADIUS;

  constructor(def: WaterStationDef) {
    super(def);

    const circleGeo = new THREE.CircleGeometry(WATER_RADIUS, SEGMENTS);
    circleGeo.rotateX(-Math.PI / 2);
    const circleMat = new THREE.MeshBasicMaterial({
      color: WATER_COLOR,
      transparent: true,
      opacity: 0.35,
      depthTest: false,
      side: THREE.DoubleSide,
    });
    this.groundMesh = new THREE.Mesh(circleGeo, circleMat);
    this.groundMesh.position.set(this.worldPos.x, 0.2, this.worldPos.z);
    this.groundMesh.renderOrder = 4;

    const cylGeo = new THREE.CylinderGeometry(
      WATER_CYLINDER_RADIUS, WATER_CYLINDER_RADIUS, WATER_CYLINDER_HEIGHT, SEGMENTS, 1, true,
    );
    cylGeo.translate(0, WATER_CYLINDER_HEIGHT / 2, 0);
    this.columnMesh = new THREE.Mesh(cylGeo, buildGradientMaterial(WATER_COLOR, WATER_CYLINDER_HEIGHT));
    this.columnMesh.position.set(this.worldPos.x, 0.2, this.worldPos.z);
    this.columnMesh.renderOrder = 4;
  }
}

// ── Medical Tent (square + box, pink/red) ───────────────────────────────────

const MEDICAL_RADIUS = 10.0;
const MEDICAL_BOX_HEIGHT = 24.0;
const MEDICAL_BOX_HALF = 7.0;
const MEDICAL_COLOR = new THREE.Color(0xff4466);

export class MedicalTent extends BaseStation {
  readonly stationType = 'medical_tent' as const;
  readonly radius = MEDICAL_RADIUS;

  constructor(def: MedicalTentDef) {
    super(def);

    const size = MEDICAL_RADIUS * 2;
    const squareGeo = new THREE.PlaneGeometry(size, size);
    squareGeo.rotateX(-Math.PI / 2);
    const squareMat = new THREE.MeshBasicMaterial({
      color: MEDICAL_COLOR,
      transparent: true,
      opacity: 0.35,
      depthTest: false,
      side: THREE.DoubleSide,
    });
    this.groundMesh = new THREE.Mesh(squareGeo, squareMat);
    this.groundMesh.position.set(this.worldPos.x, 0.2, this.worldPos.z);
    this.groundMesh.renderOrder = 4;

    const boxSide = MEDICAL_BOX_HALF * 2;
    const boxGeo = new THREE.BoxGeometry(boxSide, MEDICAL_BOX_HEIGHT, boxSide);
    boxGeo.translate(0, MEDICAL_BOX_HEIGHT / 2, 0);
    // Remove top and bottom faces — keep only the 4 sides
    // BoxGeometry groups: 0=+x, 1=-x, 2=+y(top), 3=-y(bottom), 4=+z, 5=-z
    this.columnMesh = new THREE.Mesh(boxGeo, buildGradientMaterial(MEDICAL_COLOR, MEDICAL_BOX_HEIGHT));
    this.columnMesh.position.set(this.worldPos.x, 0.2, this.worldPos.z);
    this.columnMesh.renderOrder = 4;
  }
}
