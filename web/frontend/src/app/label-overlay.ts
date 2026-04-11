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

export interface PathLabelEntry {
  id: number;
  name: string;
  colorHex: string;
  centerWorld: THREE.Vector3;
}

export interface RunnerLabelEntry {
  guid: string;
  label: string;
  position: THREE.Vector3;
  colorHex: string;
  water: number;
}

export interface LandmarkLabelEntry {
  name: string;
  position: THREE.Vector3;
}

interface LabelState {
  id: number;
  sprite: THREE.Sprite;
  texNormal: THREE.CanvasTexture;
  texHover: THREE.CanvasTexture;
  worldPos3: THREE.Vector3;
  hovered: boolean;
  name: string;
  accentHex: string;
}

interface RunnerLabelState {
  guid: string;
  sprite: THREE.Sprite;
  texNormal: THREE.CanvasTexture;
  texHover: THREE.CanvasTexture;
  hovered: boolean;
  label: string;
  colorHex: string;
  water: number;
}

interface LandmarkLabelState {
  name: string;
  sprite: THREE.Sprite;
  tex: THREE.CanvasTexture;
}

const FONT = `600 22px -apple-system, BlinkMacSystemFont, 'DM Sans', sans-serif`;
const LANDMARK_FONT = `500 13px -apple-system, BlinkMacSystemFont, 'DM Sans', sans-serif`;
const PAD_X = 24;
const H = 44;
const H_WITH_BAR = 56;
const BAR_H = 6;
const BAR_Y = H + 3;
const SPRITE_PIXEL_H = 28;

function drawLabel(
  name: string,
  accentHex: string,
  hover: boolean,
  waterLevel?: number,
): THREE.CanvasTexture {
  const hasBar = waterLevel !== undefined;
  const measure = document.createElement('canvas').getContext('2d')!;
  measure.font = FONT;
  const textW = measure.measureText(name).width;
  const W = Math.ceil(textW + 18 + PAD_X * 2);
  const totalH = hasBar ? H_WITH_BAR : H;

  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = totalH;
  const ctx = canvas.getContext('2d')!;
  const r = H / 2;

  const roundRect = () => {
    ctx.beginPath();
    ctx.moveTo(r, 0);
    ctx.lineTo(W - r, 0);
    ctx.arcTo(W, 0, W, r, r);
    ctx.lineTo(W, H - r);
    ctx.arcTo(W, H, W - r, H, r);
    ctx.lineTo(r, H);
    ctx.arcTo(0, H, 0, H - r, r);
    ctx.lineTo(0, r);
    ctx.arcTo(0, 0, r, 0, r);
    ctx.closePath();
  };

  roundRect();
  const bg = ctx.createLinearGradient(0, 0, W * 0.4, H);
  bg.addColorStop(0,    hover ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.10)');
  bg.addColorStop(0.45, hover ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)');
  bg.addColorStop(1,    hover ? 'rgba(0,0,0,0.45)'       : 'rgba(0,0,0,0.28)');
  ctx.fillStyle = bg;
  ctx.fill();

  ctx.save();
  ctx.clip();
  const glare = ctx.createLinearGradient(0, 0, 0, H * 0.42);
  glare.addColorStop(0, hover ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.06)');
  glare.addColorStop(1, 'rgba(255,255,255,0.00)');
  ctx.fillStyle = glare;
  ctx.fillRect(0, 0, W, H * 0.42);
  ctx.restore();

  roundRect();
  ctx.strokeStyle = hover ? 'rgba(255,255,255,0.30)' : 'rgba(255,255,255,0.13)';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(r + 1, 0.75);
  ctx.lineTo(W - r - 1, 0.75);
  ctx.strokeStyle = hover ? 'rgba(255,255,255,0.50)' : 'rgba(255,255,255,0.24)';
  ctx.lineWidth = 1;
  ctx.stroke();

  const pipX = PAD_X;
  const pipY = H / 2;
  const pipR = 4;

  ctx.beginPath();
  ctx.arc(pipX, pipY, pipR, 0, Math.PI * 2);
  ctx.fillStyle = accentHex;
  ctx.shadowColor = accentHex;
  ctx.shadowBlur = 11;
  ctx.fill();
  ctx.shadowBlur = 0;

  ctx.font = FONT;
  ctx.fillStyle = hover ? 'rgba(255,255,255,1.0)' : 'rgba(255,255,255,0.92)';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.shadowColor = 'rgba(0,0,0,0.7)';
  ctx.shadowBlur = 5;
  ctx.fillText(name, pipX + 13, pipY);
  ctx.shadowBlur = 0;

  if (hasBar && waterLevel !== undefined) {
    const barX = PAD_X;
    const barW = W - PAD_X * 2;
    const barR = BAR_H / 2;

    // Background track
    ctx.beginPath();
    ctx.roundRect(barX, BAR_Y, barW, BAR_H, barR);
    ctx.fillStyle = 'rgba(255,255,255,0.12)';
    ctx.fill();

    // Filled portion
    const fillW = Math.max(BAR_H, barW * (waterLevel / 100));
    const barColor = waterLevel > 50 ? '#4dabf7' : waterLevel > 20 ? '#ffd43b' : '#ff6b6b';
    ctx.beginPath();
    ctx.roundRect(barX, BAR_Y, fillW, BAR_H, barR);
    ctx.fillStyle = barColor;
    ctx.fill();
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

function drawLandmarkLabel(name: string): THREE.CanvasTexture {
  const measure = document.createElement('canvas').getContext('2d')!;
  measure.font = LANDMARK_FONT;
  const textW = measure.measureText(name).width;
  const padX = 16;
  const h = 32;
  const W = Math.ceil(textW + padX * 2);

  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = h;
  const ctx = canvas.getContext('2d')!;

  ctx.font = LANDMARK_FONT;
  ctx.fillStyle = 'rgba(255,255,255,0.55)';
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.shadowColor = 'rgba(0,0,0,0.8)';
  ctx.shadowBlur = 6;
  ctx.fillText(name, W / 2, h / 2);
  ctx.shadowBlur = 0;

  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}

export class LabelOverlay {
  private scene: THREE.Scene;
  private camera: THREE.Camera;
  private canvas: HTMLCanvasElement;
  private labels = new Map<number, LabelState>();
  private runnerLabels = new Map<string, RunnerLabelState>();
  private landmarkLabels: LandmarkLabelState[] = [];
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2(-9999, -9999);
  private onFlyTo: (pos: THREE.Vector3, id: number) => void;

  private pointerDownPos = { x: 0, y: 0 };
  private static DRAG_THRESHOLD = 5;

  constructor(
    scene: THREE.Scene,
    camera: THREE.Camera,
    domCanvas: HTMLCanvasElement,
    onFlyTo: (pos: THREE.Vector3, id: number) => void,
  ) {
    this.scene = scene;
    this.camera = camera;
    this.canvas = domCanvas;
    this.onFlyTo = onFlyTo;
    domCanvas.addEventListener('mousemove', this.onMouseMove);
    domCanvas.addEventListener('pointerdown', this.onPointerDown);
    domCanvas.addEventListener('click', this.onClick);
  }

  private createSprite(tex: THREE.CanvasTexture, pos: THREE.Vector3): THREE.Sprite {
    const mat = new THREE.SpriteMaterial({
      map: tex,
      transparent: true,
      depthTest: false,
      sizeAttenuation: false,
    });
    const sprite = new THREE.Sprite(mat);
    const cw = (tex.image as HTMLCanvasElement).width;
    const ch = (tex.image as HTMLCanvasElement).height;
    const aspect = cw / ch;
    const h = SPRITE_PIXEL_H / window.innerHeight;
    sprite.scale.set(h * aspect, h, 1);
    sprite.position.copy(pos);
    sprite.renderOrder = 20;
    return sprite;
  }

  setPathLabels(pathLabels: PathLabelEntry[]): void {
    const seen = new Set<number>();
    for (const pl of pathLabels) {
      seen.add(pl.id);
      if (this.labels.has(pl.id)) {
        const state = this.labels.get(pl.id)!;
        state.worldPos3.copy(pl.centerWorld);
        state.sprite.position.copy(pl.centerWorld);
        state.sprite.position.y += 8;
        continue;
      }
      const spritePos = pl.centerWorld.clone();
      spritePos.y += 8;
      const texN = drawLabel(pl.name, pl.colorHex, false);
      const texH = drawLabel(pl.name, pl.colorHex, true);
      const sprite = this.createSprite(texN, spritePos);
      this.scene.add(sprite);
      this.labels.set(pl.id, {
        id: pl.id,
        sprite,
        texNormal: texN,
        texHover: texH,
        worldPos3: pl.centerWorld.clone(),
        hovered: false,
        name: pl.name,
        accentHex: pl.colorHex,
      });
    }
    for (const [id, state] of this.labels) {
      if (!seen.has(id)) this.removePathState(id, state);
    }
  }

  removePathLabel(id: number): void {
    const state = this.labels.get(id);
    if (state) this.removePathState(id, state);
  }

  setRunnerLabels(entries: RunnerLabelEntry[]): void {
    const seen = new Set<string>();
    for (const entry of entries) {
      seen.add(entry.guid);
      if (this.runnerLabels.has(entry.guid)) continue;
      const spritePos = entry.position.clone();
      spritePos.y += 5;
      const texN = drawLabel(entry.label, entry.colorHex, false, entry.water);
      const texH = drawLabel(entry.label, entry.colorHex, true, entry.water);
      const sprite = this.createSprite(texN, spritePos);
      this.scene.add(sprite);
      this.runnerLabels.set(entry.guid, {
        guid: entry.guid, sprite, texNormal: texN, texHover: texH, hovered: false,
        label: entry.label, colorHex: entry.colorHex, water: entry.water,
      });
    }
    for (const [guid, state] of this.runnerLabels) {
      if (!seen.has(guid)) this.removeRunnerState(guid, state);
    }
  }

  updateRunnerPositions(positions: Map<string, THREE.Vector3>): void {
    for (const [guid, state] of this.runnerLabels) {
      const pos = positions.get(guid);
      if (pos) {
        state.sprite.position.set(pos.x, pos.y + 5, pos.z);
      }
    }
  }

  updateRunnerWaterLevels(levels: Map<string, number>): void {
    for (const [guid, state] of this.runnerLabels) {
      const water = levels.get(guid);
      if (water === undefined || Math.round(water) === Math.round(state.water)) continue;
      state.water = water;
      state.texNormal.dispose();
      state.texHover.dispose();
      state.texNormal = drawLabel(state.label, state.colorHex, false, water);
      state.texHover = drawLabel(state.label, state.colorHex, true, water);
      const mat = state.sprite.material as THREE.SpriteMaterial;
      mat.map = state.hovered ? state.texHover : state.texNormal;
      mat.needsUpdate = true;
      // Update sprite scale for potentially changed canvas size
      const cw = (mat.map!.image as HTMLCanvasElement).width;
      const ch = (mat.map!.image as HTMLCanvasElement).height;
      const h = SPRITE_PIXEL_H / window.innerHeight;
      state.sprite.scale.set(h * (cw / ch), h, 1);
    }
  }

  setLandmarkLabels(entries: LandmarkLabelEntry[]): void {
    for (const state of this.landmarkLabels) {
      this.scene.remove(state.sprite);
      state.tex.dispose();
      (state.sprite.material as THREE.SpriteMaterial).dispose();
    }
    this.landmarkLabels = [];

    const LANDMARK_PIXEL_H = 18;
    for (const entry of entries) {
      const tex = drawLandmarkLabel(entry.name);
      const spritePos = entry.position.clone();
      spritePos.y += 12;
      const mat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        depthTest: false,
        sizeAttenuation: false,
      });
      const sprite = new THREE.Sprite(mat);
      const cw = (tex.image as HTMLCanvasElement).width;
      const ch = (tex.image as HTMLCanvasElement).height;
      const h = LANDMARK_PIXEL_H / window.innerHeight;
      sprite.scale.set(h * (cw / ch), h, 1);
      sprite.position.copy(spritePos);
      sprite.renderOrder = 20;
      this.scene.add(sprite);
      this.landmarkLabels.push({ name: entry.name, sprite, tex });
    }
  }

  setLandmarkVisibility(visible: boolean): void {
    for (const state of this.landmarkLabels) {
      state.sprite.visible = visible;
    }
  }

  private removePathState(id: number, state: LabelState): void {
    this.scene.remove(state.sprite);
    state.texNormal.dispose();
    state.texHover.dispose();
    (state.sprite.material as THREE.SpriteMaterial).dispose();
    this.labels.delete(id);
  }

  private removeRunnerState(guid: string, state: RunnerLabelState): void {
    this.scene.remove(state.sprite);
    state.texNormal.dispose();
    state.texHover.dispose();
    (state.sprite.material as THREE.SpriteMaterial).dispose();
    this.runnerLabels.delete(guid);
  }

  update(): void {
    const allSprites = [
      ...Array.from(this.labels.values()).map(s => s.sprite),
      ...Array.from(this.runnerLabels.values()).map(s => s.sprite),
    ];
    if (!allSprites.length) return;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hits = this.raycaster.intersectObjects(allSprites, false);
    const hitSet = new Set(hits.map(h => h.object as THREE.Sprite));

    let cursorPointer = false;
    for (const state of this.labels.values()) {
      const nowHovered = hitSet.has(state.sprite);
      if (nowHovered) cursorPointer = true;
      if (nowHovered !== state.hovered) {
        state.hovered = nowHovered;
        const mat = state.sprite.material as THREE.SpriteMaterial;
        mat.map = nowHovered ? state.texHover : state.texNormal;
        mat.needsUpdate = true;
      }
    }
    for (const state of this.runnerLabels.values()) {
      const nowHovered = hitSet.has(state.sprite);
      if (nowHovered) cursorPointer = true;
      if (nowHovered !== state.hovered) {
        state.hovered = nowHovered;
        const mat = state.sprite.material as THREE.SpriteMaterial;
        mat.map = nowHovered ? state.texHover : state.texNormal;
        mat.needsUpdate = true;
      }
    }
    this.canvas.style.cursor = cursorPointer ? 'pointer' : '';
  }

  private onMouseMove = (e: MouseEvent): void => {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.set(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
  };

  private onPointerDown = (e: PointerEvent): void => {
    this.pointerDownPos.x = e.clientX;
    this.pointerDownPos.y = e.clientY;
  };

  private wasDrag(e: MouseEvent): boolean {
    const dx = e.clientX - this.pointerDownPos.x;
    const dy = e.clientY - this.pointerDownPos.y;
    return Math.sqrt(dx * dx + dy * dy) > LabelOverlay.DRAG_THRESHOLD;
  }

  private onClick = (e: MouseEvent): void => {
    if (this.wasDrag(e)) return;

    const rect = this.canvas.getBoundingClientRect();
    const m = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(m, this.camera);

    const pathSprites = Array.from(this.labels.values()).map(s => s.sprite);
    const pathHits = this.raycaster.intersectObjects(pathSprites, false);
    if (pathHits.length) {
      const hitSprite = pathHits[0].object as THREE.Sprite;
      for (const state of this.labels.values()) {
        if (state.sprite === hitSprite) {
          this.onFlyTo(state.worldPos3, state.id);
          return;
        }
      }
    }

    const runnerSprites = Array.from(this.runnerLabels.values()).map(s => s.sprite);
    const runnerHits = this.raycaster.intersectObjects(runnerSprites, false);
    if (runnerHits.length) {
      const hitSprite = runnerHits[0].object as THREE.Sprite;
      for (const state of this.runnerLabels.values()) {
        if (state.sprite === hitSprite) {
          window.dispatchEvent(new CustomEvent('hud:focusRunner', { detail: { guid: state.guid } }));
          return;
        }
      }
    }

    window.dispatchEvent(new CustomEvent('viewport:emptyClick'));
  };

  refreshScale(): void {
    const invH = 1 / window.innerHeight;
    for (const state of this.labels.values()) {
      const mat = state.sprite.material as THREE.SpriteMaterial;
      const cw = (mat.map!.image as HTMLCanvasElement).width;
      const ch = (mat.map!.image as HTMLCanvasElement).height;
      const h = SPRITE_PIXEL_H * invH;
      state.sprite.scale.set(h * (cw / ch), h, 1);
    }
    for (const state of this.runnerLabels.values()) {
      const mat = state.sprite.material as THREE.SpriteMaterial;
      const cw = (mat.map!.image as HTMLCanvasElement).width;
      const ch = (mat.map!.image as HTMLCanvasElement).height;
      const h = SPRITE_PIXEL_H * invH;
      state.sprite.scale.set(h * (cw / ch), h, 1);
    }
    const LANDMARK_PIXEL_H = 18;
    for (const state of this.landmarkLabels) {
      const mat = state.sprite.material as THREE.SpriteMaterial;
      const cw = (mat.map!.image as HTMLCanvasElement).width;
      const ch = (mat.map!.image as HTMLCanvasElement).height;
      const h = LANDMARK_PIXEL_H * invH;
      state.sprite.scale.set(h * (cw / ch), h, 1);
    }
  }

  dispose(): void {
    this.canvas.removeEventListener('mousemove', this.onMouseMove);
    this.canvas.removeEventListener('pointerdown', this.onPointerDown);
    this.canvas.removeEventListener('click', this.onClick);
    for (const [id, state] of this.labels) this.removePathState(id, state);
    for (const [guid, state] of this.runnerLabels) this.removeRunnerState(guid, state);
    for (const state of this.landmarkLabels) {
      this.scene.remove(state.sprite);
      state.tex.dispose();
      (state.sprite.material as THREE.SpriteMaterial).dispose();
    }
    this.landmarkLabels = [];
  }
}
