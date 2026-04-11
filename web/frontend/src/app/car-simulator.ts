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
import { RoadNode, RoadEdge } from './road-network';
import { TrafficSimulator, LightState } from './traffic-simulator';

// ── Constants ────────────────────────────────────────────────────────────────

const CAR_RADIUS = 1.4;
const CAR_Y = 1.0;
const LANE_OFFSET = 0.6;

const MAX_SPEED = 12.0;
const ACCELERATION = 5.0;
const BRAKING = 14.0;
const SAFE_DISTANCE = 5.0;
const STOP_DISTANCE = 2.0;
const INTERSECTION_STOP_LINE = 5.0;
const INTERSECTION_LOOK_AHEAD = 15.0;

// ── Adjacency for pathfinding ────────────────────────────────────────────────

interface AdjEntry { edgeId: number; neighborNodeId: number; cost: number }

function buildAdjacency(
  nodes: RoadNode[],
  edges: RoadEdge[],
  closedEdges?: Set<number>,
): Map<number, AdjEntry[]> {
  const adj = new Map<number, AdjEntry[]>();
  for (const n of nodes) adj.set(n.id, []);
  for (const e of edges) {
    if (closedEdges?.has(e.id)) continue;
    let len = 0;
    for (let i = 1; i < e.points.length; i++) {
      const dx = e.points[i].x - e.points[i - 1].x;
      const dz = e.points[i].z - e.points[i - 1].z;
      len += Math.sqrt(dx * dx + dz * dz);
    }
    adj.get(e.from)!.push({ edgeId: e.id, neighborNodeId: e.to, cost: len });
    adj.get(e.to)!.push({ edgeId: e.id, neighborNodeId: e.from, cost: len });
  }
  return adj;
}

function findRoute(
  adj: Map<number, AdjEntry[]>,
  edges: RoadEdge[],
  start: number,
  end: number,
): { edgeId: number; forward: boolean }[] | null {
  const edgeMap = new Map<number, RoadEdge>();
  for (const e of edges) edgeMap.set(e.id, e);

  const dist = new Map<number, number>();
  const prev = new Map<number, { fromNode: number; edgeId: number }>();
  const visited = new Set<number>();

  dist.set(start, 0);
  const queue: { nodeId: number; cost: number }[] = [{ nodeId: start, cost: 0 }];

  while (queue.length > 0) {
    queue.sort((a, b) => a.cost - b.cost);
    const { nodeId: curr, cost } = queue.shift()!;
    if (visited.has(curr)) continue;
    visited.add(curr);
    if (curr === end) break;

    for (const neighbor of adj.get(curr) ?? []) {
      if (visited.has(neighbor.neighborNodeId)) continue;
      const newCost = cost + neighbor.cost;
      if (newCost < (dist.get(neighbor.neighborNodeId) ?? Infinity)) {
        dist.set(neighbor.neighborNodeId, newCost);
        prev.set(neighbor.neighborNodeId, { fromNode: curr, edgeId: neighbor.edgeId });
        queue.push({ nodeId: neighbor.neighborNodeId, cost: newCost });
      }
    }
  }

  if (!prev.has(end) && start !== end) return null;
  if (start === end) return [];

  const path: { edgeId: number; forward: boolean }[] = [];
  let curr = end;
  while (curr !== start) {
    const p = prev.get(curr)!;
    const edge = edgeMap.get(p.edgeId)!;
    // forward = we entered this edge from edge.from side
    const forward = p.fromNode === edge.from;
    path.unshift({ edgeId: p.edgeId, forward });
    curr = p.fromNode;
  }

  return path;
}

// ── Lane points helper ───────────────────────────────────────────────────────

function getLanePoints(edge: RoadEdge, forward: boolean): THREE.Vector3[] {
  const pts = edge.points;
  // Right-hand traffic: forward cars use right offset, backward cars also use right from their perspective
  const offset = forward ? LANE_OFFSET : -LANE_OFFSET;
  const lanePoints = offsetPolyline(pts, offset);

  if (!forward) {
    lanePoints.reverse();
  }
  // Set Y for cars
  for (const p of lanePoints) p.y = CAR_Y;
  return lanePoints;
}

function offsetPolyline(pts: THREE.Vector3[], offset: number): THREE.Vector3[] {
  if (pts.length < 2) return pts.map(p => p.clone());
  const result: THREE.Vector3[] = [];

  for (let i = 0; i < pts.length; i++) {
    let nx = 0, nz = 0;

    if (i === 0) {
      const dx = pts[1].x - pts[0].x, dz = pts[1].z - pts[0].z;
      const len = Math.sqrt(dx * dx + dz * dz);
      if (len > 0.0001) { nx = -dz / len; nz = dx / len; }
    } else if (i === pts.length - 1) {
      const dx = pts[i].x - pts[i - 1].x, dz = pts[i].z - pts[i - 1].z;
      const len = Math.sqrt(dx * dx + dz * dz);
      if (len > 0.0001) { nx = -dz / len; nz = dx / len; }
    } else {
      const dx1 = pts[i].x - pts[i - 1].x, dz1 = pts[i].z - pts[i - 1].z;
      const len1 = Math.sqrt(dx1 * dx1 + dz1 * dz1);
      const dx2 = pts[i + 1].x - pts[i].x, dz2 = pts[i + 1].z - pts[i].z;
      const len2 = Math.sqrt(dx2 * dx2 + dz2 * dz2);
      if (len1 > 0.0001 && len2 > 0.0001) {
        nx = (-dz1 / len1 + -dz2 / len2) * 0.5;
        nz = (dx1 / len1 + dx2 / len2) * 0.5;
        const nLen = Math.sqrt(nx * nx + nz * nz);
        if (nLen > 0.0001) { nx /= nLen; nz /= nLen; }
      }
    }

    result.push(new THREE.Vector3(
      pts[i].x + nx * offset,
      pts[i].y,
      pts[i].z + nz * offset,
    ));
  }
  return result;
}

// ── Car entity ───────────────────────────────────────────────────────────────

interface Car {
  id: number;
  mesh: THREE.Mesh;
  glow: THREE.Sprite;
  color: number;

  // Route
  route: { edgeId: number; forward: boolean }[];
  routeIdx: number;

  // Current edge movement
  lanePoints: THREE.Vector3[];
  cumDist: number[];
  totalDist: number;
  distAlongEdge: number;

  // Physics
  speed: number;
  targetSpeed: number;

  // State
  currentNodeId: number;
  destinationNodeId: number;
  waiting: boolean;
}

// ── CarSimulator ─────────────────────────────────────────────────────────────

export class CarSimulator {
  private cars: Car[] = [];
  private nextCarId = 0;
  private sceneGroup: THREE.Group | null = null;
  private adj: Map<number, AdjEntry[]>;
  private edgeMap: Map<number, RoadEdge>;
  private scene: THREE.Scene | null = null;

  private closedEdges = new Set<number>();
  private carGeo: THREE.SphereGeometry;
  private glowTexture: THREE.Texture;
  private carColors = [
    0xe74c3c, 0x3498db, 0x2ecc71, 0xf39c12, 0x9b59b6,
    0x1abc9c, 0xe67e22, 0xecf0f1, 0x34495e, 0xf1c40f,
  ];

  constructor(
    private nodes: RoadNode[],
    private edges: RoadEdge[],
    private trafficSim: TrafficSimulator | null,
  ) {
    this.adj = buildAdjacency(nodes, edges);
    this.edgeMap = new Map();
    for (const e of edges) this.edgeMap.set(e.id, e);
    this.carGeo = new THREE.SphereGeometry(CAR_RADIUS, 16, 12);
    this.glowTexture = CarSimulator.createGlowTexture();
  }

  private static createGlowTexture(): THREE.Texture {
    const size = 64;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const grad = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    grad.addColorStop(0, 'rgba(255,255,255,0.7)');
    grad.addColorStop(0.3, 'rgba(255,255,255,0.3)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, size, size);
    const tex = new THREE.CanvasTexture(canvas);
    return tex;
  }

  addToScene(scene: THREE.Scene): void {
    this.scene = scene;
    this.sceneGroup = new THREE.Group();
    this.sceneGroup.name = 'cars';
    scene.add(this.sceneGroup);
  }

  removeFromScene(scene: THREE.Scene): void {
    if (!this.sceneGroup) return;
    for (const car of this.cars) {
      car.mesh.geometry.dispose();
      (car.mesh.material as THREE.Material).dispose();
      (car.glow.material as THREE.Material).dispose();
    }
    this.cars = [];
    this.glowTexture.dispose();
    scene.remove(this.sceneGroup);
    this.sceneGroup = null;
    this.scene = null;
  }

  get carCount(): number { return this.cars.length; }

  getCarInfos(): { id: number; colorHex: string }[] {
    return this.cars.map(c => ({
      id: c.id,
      colorHex: '#' + c.color.toString(16).padStart(6, '0'),
    }));
  }

  getCarPosition(carId: number): THREE.Vector3 | null {
    const car = this.cars.find(c => c.id === carId);
    return car ? car.mesh.position.clone() : null;
  }

  /** Get the remaining path points for a car (from current position forward along route). */
  getCarRoutePath(carId: number): THREE.Vector3[] | null {
    const car = this.cars.find(c => c.id === carId);
    if (!car) return null;

    const pts: THREE.Vector3[] = [car.mesh.position.clone()];

    // Add remaining points on the current edge
    const d = car.distAlongEdge;
    let startIdx = 0;
    for (let i = 1; i < car.cumDist.length; i++) {
      if (car.cumDist[i] >= d) { startIdx = i; break; }
    }
    for (let i = startIdx; i < car.lanePoints.length; i++) {
      pts.push(car.lanePoints[i].clone());
    }

    // Add points from subsequent route edges
    for (let ri = car.routeIdx + 1; ri < car.route.length; ri++) {
      const step = car.route[ri];
      const edge = this.edgeMap.get(step.edgeId);
      if (!edge) break;
      const lanePts = getLanePoints(edge, step.forward);
      for (const p of lanePts) pts.push(p.clone());
    }

    return pts;
  }

  spawnCar(): void {
    if (!this.sceneGroup || this.edges.length < 1) return;

    // Pick a random open edge to spawn on
    const openEdges = this.edges.filter(e => !this.closedEdges.has(e.id));
    if (openEdges.length === 0) return;
    const spawnEdge = openEdges[Math.floor(Math.random() * openEdges.length)];

    // Pick a random direction and position along this edge
    const forward = Math.random() < 0.5;
    const startNodeId = forward ? spawnEdge.from : spawnEdge.to;

    // Find a destination and route from the end of the spawn edge
    const endNodeId = forward ? spawnEdge.to : spawnEdge.from;
    let destIdx = endNodeId;
    let attempts = 0;
    while (destIdx === endNodeId && attempts < 50) {
      destIdx = this.nodes[Math.floor(Math.random() * this.nodes.length)].id;
      attempts++;
    }

    // Build a route starting from the end of the spawn edge
    const tailRoute = findRoute(this.adj, this.edges, endNodeId, destIdx);
    const route: { edgeId: number; forward: boolean }[] = [
      { edgeId: spawnEdge.id, forward },
      ...(tailRoute ?? []),
    ];

    const color = this.carColors[this.nextCarId % this.carColors.length];
    const mat = new THREE.MeshStandardMaterial({
      color,
      emissive: color,
      emissiveIntensity: 0.6,
      roughness: 0.3,
      metalness: 0.2,
    });
    const mesh = new THREE.Mesh(this.carGeo.clone(), mat);
    mesh.renderOrder = 7;
    this.sceneGroup.add(mesh);

    const glowMat = new THREE.SpriteMaterial({
      map: this.glowTexture,
      color,
      transparent: true,
      opacity: 0.5,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    const glow = new THREE.Sprite(glowMat);
    glow.scale.set(CAR_RADIUS * 5, CAR_RADIUS * 5, 1);
    glow.renderOrder = 6;
    mesh.add(glow);

    const lanePoints = getLanePoints(spawnEdge, forward);
    const { cumDist, totalDist } = computeDistances(lanePoints);

    // Random starting position along the edge
    const distAlongEdge = Math.random() * totalDist;

    const car: Car = {
      id: this.nextCarId++,
      mesh,
      glow,
      color,
      route,
      routeIdx: 0,
      lanePoints,
      cumDist,
      totalDist,
      distAlongEdge,
      speed: MAX_SPEED * (0.5 + Math.random() * 0.3),
      targetSpeed: MAX_SPEED * (0.8 + Math.random() * 0.4),
      currentNodeId: startNodeId,
      destinationNodeId: destIdx,
      waiting: false,
    };

    this.positionCar(car);
    this.cars.push(car);
  }

  removeCar(): void {
    if (this.cars.length === 0) return;
    const car = this.cars.pop()!;
    this.sceneGroup?.remove(car.mesh);
    car.mesh.geometry.dispose();
    (car.mesh.material as THREE.Material).dispose();
    (car.glow.material as THREE.Material).dispose();
  }

  removeAllCars(): number {
    const count = this.cars.length;
    for (const car of this.cars) {
      this.sceneGroup?.remove(car.mesh);
      car.mesh.geometry.dispose();
      (car.mesh.material as THREE.Material).dispose();
      (car.glow.material as THREE.Material).dispose();
    }
    this.cars = [];
    return count;
  }

  setClosedEdges(closed: Set<number>): void {
    this.closedEdges = closed;
    this.adj = buildAdjacency(this.nodes, this.edges, this.closedEdges);
  }

  tick(delta: number): void {
    for (const car of this.cars) {
      this.updateCar(car, delta);
    }
  }

  private updateCar(car: Car, delta: number): void {
    // Determine desired speed based on obstacles ahead
    let desiredSpeed = car.targetSpeed;

    // Check traffic light at the end of current edge
    const distToEnd = car.totalDist - car.distAlongEdge;
    if (distToEnd < INTERSECTION_LOOK_AHEAD) {
      const lightState = this.getLightStateForCar(car);
      if (lightState === 'red' || lightState === 'yellow') {
        const stopAt = distToEnd - INTERSECTION_STOP_LINE;
        if (stopAt <= 0) {
          // Already past the stop line or at it — hard stop
          desiredSpeed = 0;
        } else {
          // Brake to stop at the stop line: v = sqrt(2 * braking * distance)
          const maxSpeedToStop = Math.sqrt(2 * BRAKING * stopAt);
          desiredSpeed = Math.min(desiredSpeed, maxSpeedToStop);
        }
      }
    }

    // Check car ahead on same edge
    const aheadDist = this.getDistToCarAhead(car);
    if (aheadDist !== null) {
      const gap = aheadDist - CAR_RADIUS * 2;
      if (gap < STOP_DISTANCE) {
        desiredSpeed = 0;
      } else if (gap < SAFE_DISTANCE) {
        const ratio = (gap - STOP_DISTANCE) / (SAFE_DISTANCE - STOP_DISTANCE);
        desiredSpeed = Math.min(desiredSpeed, car.targetSpeed * ratio);
      }
    }

    // Apply acceleration / braking
    if (car.speed < desiredSpeed) {
      car.speed = Math.min(desiredSpeed, car.speed + ACCELERATION * delta);
    } else if (car.speed > desiredSpeed) {
      car.speed = Math.max(desiredSpeed, car.speed - BRAKING * delta);
    }

    // Move along edge
    car.distAlongEdge += car.speed * delta;

    // Hard clamp: do not cross the stop line when light is red/yellow
    const lightState = this.getLightStateForCar(car);
    if (lightState === 'red' || lightState === 'yellow') {
      const stopLimit = car.totalDist - INTERSECTION_STOP_LINE;
      if (stopLimit > 0 && car.distAlongEdge >= stopLimit) {
        car.distAlongEdge = stopLimit;
        car.speed = 0;
      }
    }

    // Check if we've reached the end of the current edge
    while (car.distAlongEdge >= car.totalDist) {
      // Don't transition to next edge if light is red/yellow
      const curLight = this.getLightStateForCar(car);
      if (curLight === 'red' || curLight === 'yellow') {
        car.distAlongEdge = car.totalDist - INTERSECTION_STOP_LINE;
        if (car.distAlongEdge < 0) car.distAlongEdge = 0;
        car.speed = 0;
        break;
      }

      car.distAlongEdge -= car.totalDist;
      car.routeIdx++;

      if (car.routeIdx >= car.route.length) {
        // Reached destination — pick a new one
        this.assignNewDestination(car);
        if (car.route.length === 0) {
          car.distAlongEdge = 0;
          car.speed = 0;
          break;
        }
      }

      // Load next edge
      const step = car.route[car.routeIdx];
      const edge = this.edgeMap.get(step.edgeId)!;
      car.lanePoints = getLanePoints(edge, step.forward);
      const d = computeDistances(car.lanePoints);
      car.cumDist = d.cumDist;
      car.totalDist = d.totalDist;

      // Update current node
      car.currentNodeId = step.forward ? edge.from : edge.to;
    }

    this.positionCar(car);
  }

  private getLightStateForCar(car: Car): LightState | null {
    if (!this.trafficSim) return null;
    const step = car.route[car.routeIdx];
    if (!step) return null;
    return this.trafficSim.getLightState(
      this.getEndNodeOfStep(step),
      step.edgeId,
    );
  }

  private getEndNodeOfStep(step: { edgeId: number; forward: boolean }): number {
    const edge = this.edgeMap.get(step.edgeId)!;
    return step.forward ? edge.to : edge.from;
  }

  private getDistToCarAhead(car: Car): number | null {
    const step = car.route[car.routeIdx];
    if (!step) return null;

    let closest: number | null = null;

    for (const other of this.cars) {
      if (other.id === car.id) continue;
      const otherStep = other.route[other.routeIdx];
      if (!otherStep) continue;

      // Same edge, same direction
      if (otherStep.edgeId === step.edgeId && otherStep.forward === step.forward) {
        const dist = other.distAlongEdge - car.distAlongEdge;
        if (dist > 0 && (closest === null || dist < closest)) {
          closest = dist;
        }
      }
    }

    // Also check cars on the next edge near the start
    if (car.routeIdx + 1 < car.route.length) {
      const nextStep = car.route[car.routeIdx + 1];
      const distToEnd = car.totalDist - car.distAlongEdge;
      if (distToEnd < SAFE_DISTANCE * 2) {
        for (const other of this.cars) {
          if (other.id === car.id) continue;
          const otherStep = other.route[other.routeIdx];
          if (!otherStep) continue;
          if (otherStep.edgeId === nextStep.edgeId && otherStep.forward === nextStep.forward) {
            const dist = distToEnd + other.distAlongEdge;
            if (dist > 0 && (closest === null || dist < closest)) {
              closest = dist;
            }
          }
        }
      }
    }

    return closest;
  }

  private assignNewDestination(car: Car): void {
    // Current position is at the end of the last route step
    const lastStep = car.route[car.route.length - 1];
    const currentNode = lastStep
      ? this.getEndNodeOfStep(lastStep)
      : car.currentNodeId;

    let destIdx = currentNode;
    let attempts = 0;
    while (destIdx === currentNode && attempts < 50) {
      destIdx = this.nodes[Math.floor(Math.random() * this.nodes.length)].id;
      attempts++;
    }

    const route = findRoute(this.adj, this.edges, currentNode, destIdx);
    if (!route || route.length === 0) {
      car.route = [];
      car.routeIdx = 0;
      return;
    }

    car.route = route;
    car.routeIdx = 0;
    car.destinationNodeId = destIdx;
    car.currentNodeId = currentNode;

    const step = route[0];
    const edge = this.edgeMap.get(step.edgeId)!;
    car.lanePoints = getLanePoints(edge, step.forward);
    const d = computeDistances(car.lanePoints);
    car.cumDist = d.cumDist;
    car.totalDist = d.totalDist;
    car.distAlongEdge = 0;
  }

  private positionCar(car: Car): void {
    if (car.lanePoints.length < 2) return;

    const d = car.distAlongEdge;
    let pos: THREE.Vector3;

    // Find segment
    for (let i = 1; i < car.cumDist.length; i++) {
      if (car.cumDist[i] >= d || i === car.cumDist.length - 1) {
        const seg = car.cumDist[i] - car.cumDist[i - 1];
        const t = seg > 0.001 ? (d - car.cumDist[i - 1]) / seg : 0;
        pos = new THREE.Vector3().lerpVectors(car.lanePoints[i - 1], car.lanePoints[i], Math.max(0, Math.min(1, t)));
        car.mesh.position.copy(pos);
        return;
      }
    }

    // Fallback
    car.mesh.position.copy(car.lanePoints[0]);
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function computeDistances(pts: THREE.Vector3[]): { cumDist: number[]; totalDist: number } {
  const cumDist = [0];
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].x - pts[i - 1].x;
    const dz = pts[i].z - pts[i - 1].z;
    cumDist.push(cumDist[i - 1] + Math.sqrt(dx * dx + dz * dz));
  }
  return { cumDist, totalDist: cumDist[cumDist.length - 1] ?? 0 };
}
