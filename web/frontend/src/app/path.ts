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
import { WaterStation, WaterStationDef, MedicalTent, MedicalTentDef, StationZone } from './water-station';

/** Minimal path interface consumed by Runner — satisfied by both MapPath and CatmullRomPathAdapter. */
export interface IMapPath {
  getPositionAt(t: number): THREE.Vector3;
  getTangentAt(t: number): THREE.Vector3;
  getTotalLength(): number;
  readonly allStations: StationZone[];
  readonly lengthMi: number | null;
}

const _scratchPos = new THREE.Vector3();
const _scratchTan = new THREE.Vector3();
const _mapScratchPos = new THREE.Vector3();
const _mapScratchTan = new THREE.Vector3();

/** Adapter wrapping a pre-baked arc-length LUT (from CatmullRomCurve3) as an IMapPath. */
export class CatmullRomPathAdapter implements IMapPath {
  private lut: THREE.Vector3[];
  readonly allStations: StationZone[];
  readonly lengthMi: number | null;

  constructor(lut: THREE.Vector3[], lengthMi: number | null, stations: StationZone[] = []) {
    this.lut = lut;
    this.lengthMi = lengthMi;
    this.allStations = stations;
  }

  getPositionAt(t: number): THREE.Vector3 {
    t = Math.max(0, Math.min(1, t));
    const ft = t * (this.lut.length - 1);
    const i = Math.floor(ft);
    const frac = ft - i;
    const next = Math.min(i + 1, this.lut.length - 1);
    return _scratchPos.lerpVectors(this.lut[i], this.lut[next], frac);
  }

  getTangentAt(t: number): THREE.Vector3 {
    t = Math.max(0, Math.min(1, t));
    const ft = t * (this.lut.length - 1);
    const i = Math.floor(ft);
    const next = Math.min(i + 1, this.lut.length - 1);
    if (i === next) return _scratchTan.set(0, 0, 1);
    return _scratchTan.subVectors(this.lut[next], this.lut[i]).normalize();
  }

  getTotalLength(): number {
    let len = 0;
    for (let i = 1; i < this.lut.length; i++) {
      len += this.lut[i].distanceTo(this.lut[i - 1]);
    }
    return len;
  }
}

export interface MapPathOptions {
  name: string;
  color: THREE.Color;
  isLoop: boolean;
  lengthMi?: number;
  waterStations?: WaterStationDef[];
  medicalTents?: MedicalTentDef[];
}

const DEFAULTS: MapPathOptions = {
  name: 'Path',
  color: new THREE.Color(0x2244ff),
  isLoop: false,
};

const Y_OFFSET = 0.18;
const RIBBON_WIDTH_NORMAL = 1.2;
const RIBBON_WIDTH_HIGHLIGHTED = 1.8;
const JOIN_SEGMENTS = 8;
const DRAW_ANIM_DURATION = 2.0;

interface RibbonBuild {
  geo: THREE.BufferGeometry;
  totalIndexCount: number;
}

function buildRibbonGeo(pts: THREE.Vector3[], width: number): RibbonBuild {
  const pos: number[] = [];
  const idx: number[] = [];
  const half = width * 0.5;

  const norm = (a: THREE.Vector3, b: THREE.Vector3) => {
    const dx = b.x - a.x, dz = b.z - a.z;
    const len = Math.sqrt(dx * dx + dz * dz);
    return len < 0.0001 ? null : new THREE.Vector2(-dz / len, dx / len);
  };

  const addDisc = (c: THREE.Vector3, y: number) => {
    const center = pos.length / 3;
    pos.push(c.x, y, c.z);
    for (let s = 0; s <= JOIN_SEGMENTS; s++) {
      const a = (s / JOIN_SEGMENTS) * Math.PI * 2;
      pos.push(c.x + Math.cos(a) * half, y, c.z + Math.sin(a) * half);
    }
    for (let s = 0; s < JOIN_SEGMENTS; s++) {
      idx.push(center, center + 1 + s, center + 2 + s);
    }
  };

  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i], b = pts[i + 1];
    const n = norm(a, b);
    if (n) {
      const base = pos.length / 3;
      pos.push(
        a.x + n.x * half, a.y, a.z + n.y * half,
        a.x - n.x * half, a.y, a.z - n.y * half,
        b.x + n.x * half, b.y, b.z + n.y * half,
        b.x - n.x * half, b.y, b.z - n.y * half,
      );
      idx.push(base, base + 1, base + 2, base + 1, base + 3, base + 2);
    }
    addDisc(b, b.y);
  }

  if (pts.length > 0) addDisc(pts[0], pts[0].y);

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setIndex(idx);
  return { geo, totalIndexCount: idx.length };
}

export class MapPath {
  readonly id: number;
  readonly name: string;
  readonly isLoop: boolean;
  readonly color: THREE.Color;
  readonly lengthMi: number | null;

  private pts: THREE.Vector3[] = [];
  private cumLen: number[] = [];
  private totalLen = 0;
  private lineMesh: THREE.Mesh | null = null;
  private totalIndexCount = 0;

  private drawAnimating = false;
  private drawAnimElapsed = 0;
  private finishLineGroup: THREE.Group | null = null;

  waterStationTs: number[] = [];
  readonly waterStations: WaterStation[] = [];
  readonly medicalTents: MedicalTent[] = [];
  readonly allStations: StationZone[] = [];

  constructor(
    id: number,
    worldPoints: THREE.Vector3[],
    options: Partial<MapPathOptions> = {},
  ) {
    this.id = id;
    const opts = { ...DEFAULTS, ...options };
    this.name = opts.name;
    this.isLoop = opts.isLoop;
    this.color = (opts.color instanceof THREE.Color)
      ? opts.color.clone()
      : new THREE.Color(opts.color);

    const raw = worldPoints.map(p => new THREE.Vector3(p.x, p.y + Y_OFFSET, p.z));

    if (this.isLoop && raw.length > 1) {
      if (raw[0].distanceTo(raw[raw.length - 1]) > 0.001) raw.push(raw[0].clone());
    }

    this.pts = raw;
    this.buildLengths();
    this.lengthMi = opts.lengthMi ?? null;

    if (opts.waterStations) {
      for (const def of opts.waterStations) {
        const station = new WaterStation(def);
        this.waterStations.push(station);
        this.allStations.push(station);
        this.waterStationTs.push(this.worldPosToT(def.worldPos));
      }
    }
    if (opts.medicalTents) {
      for (const def of opts.medicalTents) {
        const tent = new MedicalTent(def);
        this.medicalTents.push(tent);
        this.allStations.push(tent);
      }
    }
  }

  private buildLengths(): void {
    this.cumLen = [0];
    for (let i = 1; i < this.pts.length; i++) {
      this.cumLen.push(this.cumLen[i - 1] + this.pts[i].distanceTo(this.pts[i - 1]));
    }
    this.totalLen = this.cumLen[this.cumLen.length - 1] ?? 0;
  }

  getPositionAt(t: number): THREE.Vector3 {
    if (!this.pts.length) return _mapScratchPos.set(0, 0, 0);
    const clamped = Math.max(0, Math.min(1, t));
    const tgt = clamped * this.totalLen;
    if (tgt <= 0) return _mapScratchPos.copy(this.pts[0]);
    if (tgt >= this.totalLen) return _mapScratchPos.copy(this.pts[this.pts.length - 1]);
    for (let i = 1; i < this.cumLen.length; i++) {
      if (this.cumLen[i] >= tgt) {
        const seg = this.cumLen[i] - this.cumLen[i - 1];
        const lt = seg > 0 ? (tgt - this.cumLen[i - 1]) / seg : 0;
        return _mapScratchPos.lerpVectors(this.pts[i - 1], this.pts[i], lt);
      }
    }
    return _mapScratchPos.copy(this.pts[this.pts.length - 1]);
  }

  getTangentAt(t: number): THREE.Vector3 {
    if (this.pts.length < 2) return _mapScratchTan.set(1, 0, 0);
    const tgt = Math.max(0, Math.min(1, t)) * this.totalLen;
    for (let i = 1; i < this.cumLen.length; i++) {
      if (this.cumLen[i] >= tgt || i === this.cumLen.length - 1) {
        return _mapScratchTan.copy(this.pts[i]).sub(this.pts[i - 1]).normalize();
      }
    }
    return _mapScratchTan.set(1, 0, 0);
  }

  getTotalLength(): number { return this.totalLen; }

  getWorldPoints(): readonly THREE.Vector3[] { return this.pts; }

  getCenter(): THREE.Vector3 {
    const c = new THREE.Vector3();
    this.pts.forEach(p => c.add(p));
    return this.pts.length ? c.divideScalar(this.pts.length) : c;
  }

  getBoundingRadius(): number {
    const c = this.getCenter();
    return this.pts.reduce((m, p) => Math.max(m, p.distanceTo(c)), 0);
  }

  worldPosToT(worldPos: THREE.Vector3): number {
    let best = 0, bestDist = Infinity;
    for (let i = 0; i < this.pts.length; i++) {
      const d = worldPos.distanceTo(this.pts[i]);
      if (d < bestDist) { bestDist = d; best = this.cumLen[i] / this.totalLen; }
    }
    return best;
  }

  startDrawAnimation(): void {
    this.drawAnimElapsed = 0;
    this.drawAnimating = true;
    this.setDrawRange(0);
  }

  tickDrawAnimation(delta: number): boolean {
    if (!this.drawAnimating) return true;
    this.drawAnimElapsed += delta;
    const t = Math.min(this.drawAnimElapsed / DRAW_ANIM_DURATION, 1);
    this.setDrawRange(easeOutCubic(t));
    if (t >= 1) {
      this.drawAnimating = false;
      return true;
    }
    return false;
  }

  isDrawAnimating(): boolean { return this.drawAnimating; }

  private setDrawRange(progress: number): void {
    if (!this.lineMesh) return;
    this.lineMesh.geometry.setDrawRange(0, Math.round(progress * this.totalIndexCount));
  }

  addToScene(mainScene: THREE.Scene, _overlayScene: THREE.Scene): void {
    this.removeFromScene(mainScene, _overlayScene);
    this._buildLine(mainScene);
    for (const station of this.waterStations) {
      station.addToScene(mainScene);
    }
    for (const tent of this.medicalTents) {
      tent.addToScene(mainScene);
    }
    this._buildFinishLine(mainScene);
  }

  removeFromScene(mainScene: THREE.Scene, _overlayScene: THREE.Scene): void {
    if (this.lineMesh) {
      mainScene.remove(this.lineMesh);
      this.lineMesh.geometry.dispose();
      (this.lineMesh.material as THREE.Material).dispose();
      this.lineMesh = null;
    }
    if (this.finishLineGroup) {
      mainScene.remove(this.finishLineGroup);
      this.finishLineGroup.traverse(c => {
        if ((c as THREE.Mesh).geometry) (c as THREE.Mesh).geometry.dispose();
        if ((c as THREE.Mesh).material) {
          const mat = (c as THREE.Mesh).material;
          if (Array.isArray(mat)) mat.forEach(m => m.dispose());
          else (mat as THREE.Material).dispose();
        }
      });
      this.finishLineGroup = null;
    }
    for (const station of this.waterStations) {
      station.removeFromScene(mainScene);
    }
    for (const tent of this.medicalTents) {
      tent.removeFromScene(mainScene);
    }
  }

  setHighlighted(on: boolean): void {
    if (!this.lineMesh) return;
    const { geo, totalIndexCount } = buildRibbonGeo(
      this.pts,
      on ? RIBBON_WIDTH_HIGHLIGHTED : RIBBON_WIDTH_NORMAL,
    );
    this.lineMesh.geometry.dispose();
    this.lineMesh.geometry = geo;
    this.totalIndexCount = totalIndexCount;
    if (!this.drawAnimating) {
      this.lineMesh.geometry.setDrawRange(0, totalIndexCount);
    }
  }

  private _buildLine(scene: THREE.Scene): void {
    if (this.pts.length < 2) return;
    const { geo, totalIndexCount } = buildRibbonGeo(this.pts, RIBBON_WIDTH_NORMAL);
    this.totalIndexCount = totalIndexCount;
    const mat = new THREE.MeshBasicMaterial({
      color: this.color,
      depthTest: false,
      side: THREE.DoubleSide,
    });
    this.lineMesh = new THREE.Mesh(geo, mat);
    this.lineMesh.renderOrder = 5;
    scene.add(this.lineMesh);
  }

  /** Build a finish line arch at the end of the path */
  private _buildFinishLine(scene: THREE.Scene): void {
    if (this.pts.length < 2) return;

    const endPt = this.pts[this.pts.length - 1];
    const tangent = this.getTangentAt(1);
    const cross = new THREE.Vector3(-tangent.z, 0, tangent.x).normalize();

    const group = new THREE.Group();
    const archWidth = 4.0;
    const archHeight = 4.5;
    const poleRadius = 0.15;
    const bannerHeight = 0.8;

    // Two vertical poles
    const poleGeo = new THREE.CylinderGeometry(poleRadius, poleRadius, archHeight, 8);
    const poleMat = new THREE.MeshStandardMaterial({ color: 0xffffff, metalness: 0.6, roughness: 0.3 });
    const leftPos = endPt.clone().add(cross.clone().multiplyScalar(archWidth / 2));
    const rightPos = endPt.clone().add(cross.clone().multiplyScalar(-archWidth / 2));

    const leftPole = new THREE.Mesh(poleGeo, poleMat);
    leftPole.position.set(leftPos.x, leftPos.y + archHeight / 2, leftPos.z);
    group.add(leftPole);

    const rightPole = new THREE.Mesh(poleGeo, poleMat);
    rightPole.position.set(rightPos.x, rightPos.y + archHeight / 2, rightPos.z);
    group.add(rightPole);

    // Horizontal crossbar at the top
    const barLength = archWidth;
    const barGeo = new THREE.CylinderGeometry(poleRadius, poleRadius, barLength, 8);
    const bar = new THREE.Mesh(barGeo, poleMat);
    bar.position.set(endPt.x, endPt.y + archHeight, endPt.z);
    bar.rotation.set(0, 0, Math.PI / 2);
    // Align bar along the cross direction
    bar.lookAt(endPt.x + cross.x, endPt.y + archHeight, endPt.z + cross.z);
    bar.rotateX(Math.PI / 2);
    group.add(bar);

    // Checkered banner below crossbar
    const bannerGeo = new THREE.PlaneGeometry(archWidth, bannerHeight, 8, 2);
    const canvas = document.createElement('canvas');
    canvas.width = 128; canvas.height = 32;
    const ctx = canvas.getContext('2d')!;
    const squareSize = 16;
    for (let row = 0; row < 2; row++) {
      for (let col = 0; col < 8; col++) {
        ctx.fillStyle = (row + col) % 2 === 0 ? '#000000' : '#ffffff';
        ctx.fillRect(col * squareSize, row * squareSize, squareSize, squareSize);
      }
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    const bannerMat = new THREE.MeshBasicMaterial({
      map: texture, side: THREE.DoubleSide, transparent: true, opacity: 0.9,
    });
    const banner = new THREE.Mesh(bannerGeo, bannerMat);
    banner.position.set(endPt.x, endPt.y + archHeight - bannerHeight / 2 - poleRadius, endPt.z);
    // Orient banner to face along path tangent
    banner.lookAt(endPt.x + tangent.x, endPt.y + archHeight - bannerHeight / 2, endPt.z + tangent.z);
    group.add(banner);

    this.finishLineGroup = group;
    scene.add(group);
  }
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}
