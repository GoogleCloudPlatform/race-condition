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
import { GLB_TRANSFORM } from './glb-roads';
import { TrafficSimulator } from './traffic-simulator';
import { CarSimulator } from './car-simulator';

// ── Coordinate conversion ───────────────────────────────────────────────────

const R_EARTH = 6378137;
const MAP_CENTER_LAT = 36.1085;
const MAP_CENTER_LON = -115.1769;

const CX = (MAP_CENTER_LON * Math.PI / 180) * R_EARTH;
const CY = Math.log(Math.tan(Math.PI / 4 + (MAP_CENTER_LAT * Math.PI / 180) / 2)) * R_EARTH;
const SCALE = GLB_TRANSFORM.scale;

function lonLatToWorld(lon: number, lat: number): THREE.Vector3 {
  const mx = (lon * Math.PI / 180) * R_EARTH;
  const my = Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI / 180) / 2)) * R_EARTH;
  return new THREE.Vector3(
    (mx - CX) * SCALE + GLB_TRANSFORM.offsetX,
    0,
    -((my - CY) * SCALE) + GLB_TRANSFORM.offsetZ,
  );
}

// ── Types ───────────────────────────────────────────────────────────────────

export interface RoadNode {
  id: number;
  position: THREE.Vector3;
}

export interface RoadEdge {
  id: number;
  from: number;
  to: number;
  points: THREE.Vector3[];
}

// ── Constants ───────────────────────────────────────────────────────────────

const SNAP_TOLERANCE = 1.5;
const NODE_RADIUS = 3.5;
const ROAD_Y = 0.15;
const NODE_Y = 0.16;
const SPAWN_Y = 0.17;
const SPAWN_RADIUS = 2.0;
const RIBBON_WIDTH = 0.7;
const LANE_OFFSET = 0.6;
const JOIN_SEGMENTS = 8;

// ── Ribbon geometry builder (same approach as path.ts) ──────────────────────

function buildRibbonGeo(pts: THREE.Vector3[], width: number): THREE.BufferGeometry {
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
  return geo;
}

// ── Segment intersection (2D, xz plane) ────────────────────────────────────

function segmentIntersection(
  ax: number, az: number, bx: number, bz: number,
  cx: number, cz: number, dx: number, dz: number,
): { t: number; u: number } | null {
  const denom = (bx - ax) * (dz - cz) - (bz - az) * (dx - cx);
  if (Math.abs(denom) < 1e-10) return null;
  const t = ((cx - ax) * (dz - cz) - (cz - az) * (dx - cx)) / denom;
  const u = ((cx - ax) * (bz - az) - (cz - az) * (bx - ax)) / denom;
  if (t > 0.01 && t < 0.99 && u > 0.01 && u < 0.99) return { t, u };
  return null;
}

// ── RoadNetwork ─────────────────────────────────────────────────────────────

interface RoadNameEntry {
  name: string;
  polyline: THREE.Vector3[];
}

export class RoadNetwork {
  readonly nodes: RoadNode[] = [];
  readonly edges: RoadEdge[] = [];
  readonly spawnNodeIds: number[] = [];

  private sceneGroup: THREE.Group | null = null;
  private trafficSim: TrafficSimulator | null = null;
  private carSim: CarSimulator | null = null;

  private closedEdgeIds = new Set<number>();
  private barrierGroup: THREE.Group | null = null;
  private edgeMeshes = new Map<number, THREE.Mesh[]>();
  private roadNames: RoadNameEntry[] = [];
  private edgeRoadName = new Map<number, string>();
  private roadColors = new Map<string, THREE.Color>();
  private streetNameGroup: THREE.Group | null = null;
  private edgeGroup: THREE.Group | null = null;
  private nodeGroup: THREE.Group | null = null;
  private spawnGroup: THREE.Group | null = null;
  private currentRoadMode: 'off' | 'on' | 'color' = 'color';

  /** Parse a GeoJSON FeatureCollection of LineStrings into a road network. */
  static fromGeoJSON(geojson: any): RoadNetwork {
    const net = new RoadNetwork();
    if (geojson?.type !== 'FeatureCollection') return net;

    // Step 1: Convert all features to world-space polylines
    const polylines: THREE.Vector3[][] = [];
    const featureNames: (string | null)[] = [];
    for (const feature of geojson.features ?? []) {
      if (feature.geometry?.type !== 'LineString') continue;
      const coords: [number, number][] = feature.geometry.coordinates;
      if (coords.length < 2) continue;
      polylines.push(coords.map(([lon, lat]) => {
        const p = lonLatToWorld(lon, lat);
        p.y = ROAD_Y;
        return p;
      }));
      featureNames.push(feature.properties?.name ?? null);
    }

    // Step 2: Find all intersection points (endpoints + cross-intersections)
    // Collect all points that should become nodes
    const nodePositions: THREE.Vector3[] = [];

    const findOrCreateNode = (pos: THREE.Vector3): number => {
      for (let i = 0; i < nodePositions.length; i++) {
        const dx = nodePositions[i].x - pos.x;
        const dz = nodePositions[i].z - pos.z;
        if (dx * dx + dz * dz < SNAP_TOLERANCE * SNAP_TOLERANCE) {
          return i;
        }
      }
      nodePositions.push(pos.clone());
      return nodePositions.length - 1;
    };

    // Register all endpoints as nodes
    for (const poly of polylines) {
      findOrCreateNode(poly[0]);
      findOrCreateNode(poly[poly.length - 1]);
    }

    // Check every pair of polylines for segment-level cross-intersections
    // and also check within a single polyline for self-intersections with
    // points from other polylines that are close to its segments.
    for (let i = 0; i < polylines.length; i++) {
      for (let j = i + 1; j < polylines.length; j++) {
        const polyA = polylines[i];
        const polyB = polylines[j];
        for (let ai = 0; ai < polyA.length - 1; ai++) {
          for (let bi = 0; bi < polyB.length - 1; bi++) {
            const hit = segmentIntersection(
              polyA[ai].x, polyA[ai].z, polyA[ai + 1].x, polyA[ai + 1].z,
              polyB[bi].x, polyB[bi].z, polyB[bi + 1].x, polyB[bi + 1].z,
            );
            if (hit) {
              const ix = polyA[ai].x + hit.t * (polyA[ai + 1].x - polyA[ai].x);
              const iz = polyA[ai].z + hit.t * (polyA[ai + 1].z - polyA[ai].z);
              const pos = new THREE.Vector3(ix, ROAD_Y, iz);
              findOrCreateNode(pos);
            }
          }
        }
      }
    }

    // Also detect where a vertex of one polyline is very close to a segment
    // of another polyline (T-intersections)
    for (let i = 0; i < polylines.length; i++) {
      for (let j = 0; j < polylines.length; j++) {
        if (i === j) continue;
        for (const pt of polylines[j]) {
          for (let si = 0; si < polylines[i].length - 1; si++) {
            const a = polylines[i][si];
            const b = polylines[i][si + 1];
            const dist = pointToSegmentDist(pt, a, b);
            if (dist < SNAP_TOLERANCE) {
              findOrCreateNode(pt);
            }
          }
        }
      }
    }

    // Build final node list
    for (let i = 0; i < nodePositions.length; i++) {
      net.nodes.push({ id: i, position: nodePositions[i] });
    }

    // Step 3: Split each polyline at node positions to create edges
    let edgeId = 0;
    for (let polyIdx = 0; polyIdx < polylines.length; polyIdx++) {
    const poly = polylines[polyIdx];
      // Find which nodes lie on this polyline (sorted by distance along it)
      const nodesOnPoly: { nodeId: number; segIdx: number; t: number }[] = [];

      for (let ni = 0; ni < nodePositions.length; ni++) {
        const np = nodePositions[ni];
        for (let si = 0; si < poly.length - 1; si++) {
          const a = poly[si];
          const b = poly[si + 1];
          const dist = pointToSegmentDist(np, a, b);
          if (dist < SNAP_TOLERANCE) {
            const segLen = Math.sqrt((b.x - a.x) ** 2 + (b.z - a.z) ** 2);
            const t = segLen > 0.001
              ? projectOntoSegment(np, a, b)
              : 0;
            nodesOnPoly.push({ nodeId: ni, segIdx: si, t });
            break; // Only match first segment
          }
        }
      }

      // Sort by position along polyline
      nodesOnPoly.sort((a, b) => a.segIdx - b.segIdx || a.t - b.t);

      // Deduplicate consecutive same-node entries
      const unique: typeof nodesOnPoly = [];
      for (const entry of nodesOnPoly) {
        if (unique.length === 0 || unique[unique.length - 1].nodeId !== entry.nodeId) {
          unique.push(entry);
        }
      }

      // Create edges between consecutive nodes
      for (let k = 0; k < unique.length - 1; k++) {
        const start = unique[k];
        const end = unique[k + 1];

        // Collect points for this sub-edge
        const pts: THREE.Vector3[] = [nodePositions[start.nodeId].clone()];

        const startSeg = start.segIdx;
        const endSeg = end.segIdx;

        // Add intermediate polyline vertices
        for (let si = startSeg + 1; si <= endSeg; si++) {
          pts.push(poly[si].clone());
        }

        pts.push(nodePositions[end.nodeId].clone());

        // Ensure all y values are correct
        for (const p of pts) p.y = ROAD_Y;

        if (pts.length >= 2) {
          const eid = edgeId++;
          net.edges.push({ id: eid, from: start.nodeId, to: end.nodeId, points: pts });
          const rname = featureNames[polyIdx];
          if (rname) net.edgeRoadName.set(eid, rname);
        }
      }
    }

    // Identify spawn/despawn nodes: nodes with only 1 connected edge (border dead-ends)
    const edgeCount = new Map<number, number>();
    for (const edge of net.edges) {
      edgeCount.set(edge.from, (edgeCount.get(edge.from) ?? 0) + 1);
      edgeCount.set(edge.to, (edgeCount.get(edge.to) ?? 0) + 1);
    }
    for (const [nodeId, count] of edgeCount) {
      if (count === 1) net.spawnNodeIds.push(nodeId);
    }

    // Store road names with their original polylines for labeling
    for (let i = 0; i < polylines.length; i++) {
      const name = featureNames[i];
      if (name) net.roadNames.push({ name, polyline: polylines[i] });
    }

    // Generate unique colors per road name
    const ROAD_PALETTE = [
      0x4dabf7, 0x69db7c, 0xffd43b, 0xff8787, 0xda77f2,
      0x38d9a9, 0xffa94d, 0x74c0fc, 0xa9e34b, 0xf783ac,
      0x3bc9db, 0xe599f7, 0x91a7ff, 0x8ce99a, 0xffec99,
      0x66d9e8, 0xd0bfff, 0xffc078, 0x63e6be, 0xeebefa,
      0x99e9f2, 0xb2f2bb, 0xffdeeb, 0xc5f6fa, 0xe7f5ff,
    ];
    const uniqueNames = [...new Set(net.roadNames.map(r => r.name))];
    for (let i = 0; i < uniqueNames.length; i++) {
      net.roadColors.set(uniqueNames[i], new THREE.Color(ROAD_PALETTE[i % ROAD_PALETTE.length]));
    }

    return net;
  }

  addToScene(scene: THREE.Scene): void {
    this.removeFromScene(scene);
    this.sceneGroup = new THREE.Group();
    this.sceneGroup.name = 'road-network';

    this.buildEdges();
    this.buildNodes();
    this.buildSpawnPoints();
    this.buildRoadNameLabels();

    scene.add(this.sceneGroup);

    this.trafficSim = new TrafficSimulator(this.nodes, this.edges);
    this.trafficSim.addToScene(scene);

    this.carSim = new CarSimulator(this.nodes, this.edges, this.trafficSim);
    this.carSim.addToScene(scene);
  }

  removeFromScene(scene: THREE.Scene): void {
    this.carSim?.removeFromScene(scene);
    this.carSim = null;
    this.trafficSim?.removeFromScene(scene);
    this.trafficSim = null;
    if (!this.sceneGroup) return;
    scene.remove(this.sceneGroup);
    this.sceneGroup.traverse(obj => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry.dispose();
        const mat = obj.material;
        if (Array.isArray(mat)) mat.forEach(m => m.dispose());
        else mat.dispose();
      }
    });
    this.sceneGroup = null;
  }

  tick(delta: number): void {
    this.trafficSim?.tick(delta);
    this.carSim?.tick(delta);
  }

  spawnCar(): void {
    this.carSim?.spawnCar();
  }

  removeCar(): void {
    this.carSim?.removeCar();
  }

  get carCount(): number {
    return this.carSim?.carCount ?? 0;
  }

  getCarInfos(): { id: number; colorHex: string }[] {
    return this.carSim?.getCarInfos() ?? [];
  }

  getCarPosition(carId: number): THREE.Vector3 | null {
    return this.carSim?.getCarPosition(carId) ?? null;
  }

  getCarRoutePath(carId: number): THREE.Vector3[] | null {
    return this.carSim?.getCarRoutePath(carId) ?? null;
  }

  /** Find edges that CROSS or JOIN the marathon path (not edges the path runs along). */
  findEdgesCrossingPath(pathPoints: readonly THREE.Vector3[], radius: number): number[] {
    const PARALLEL_THRESHOLD = Math.cos(35 * Math.PI / 180); // ~0.82 – edges more parallel than this are "along" the path

    const result: number[] = [];
    for (const edge of this.edges) {
      let isCrossing = false;
      for (let ei = 0; ei < edge.points.length - 1 && !isCrossing; ei++) {
        const eA = edge.points[ei], eB = edge.points[ei + 1];
        const eDx = eB.x - eA.x, eDz = eB.z - eA.z;
        const eLen = Math.sqrt(eDx * eDx + eDz * eDz);
        if (eLen < 0.001) continue;

        for (let pi = 0; pi < pathPoints.length - 1 && !isCrossing; pi++) {
          const pA = pathPoints[pi], pB = pathPoints[pi + 1];

          // Check if these segments are close enough
          const inter = segmentIntersection(
            eA.x, eA.z, eB.x, eB.z,
            pA.x, pA.z, pB.x, pB.z,
          );
          const isNear = inter || segmentToSegmentDist(eA, eB, pA, pB) < radius;
          if (!isNear) continue;

          // Check angle between edge direction and path direction
          const pDx = pB.x - pA.x, pDz = pB.z - pA.z;
          const pLen = Math.sqrt(pDx * pDx + pDz * pDz);
          if (pLen < 0.001) continue;

          const dot = Math.abs(eDx * pDx + eDz * pDz) / (eLen * pLen);
          // If angle is large enough (not parallel), it's a crossing road
          if (dot < PARALLEL_THRESHOLD) {
            isCrossing = true;
          }
        }
      }
      if (isCrossing) result.push(edge.id);
    }
    return result;
  }

  /** Close the given edges to traffic, rebuild adjacency, and show barriers. */
  closeEdges(edgeIds: number[], scene: THREE.Scene, pathPoints?: readonly THREE.Vector3[]): void {
    this.closedEdgeIds = new Set(edgeIds);
    this.carSim?.setClosedEdges(this.closedEdgeIds);
    this.colorClosedEdges();
    this.buildBarriers(scene, pathPoints);
  }

  /** Re-open all roads and remove barriers. */
  clearClosures(scene: THREE.Scene): void {
    this.closedEdgeIds.clear();
    this.carSim?.setClosedEdges(this.closedEdgeIds);
    this.restoreEdgeColors();
    this.removeBarriers(scene);
  }

  private colorClosedEdges(): void {
    const closedColor = new THREE.Color(0xcc3333);
    for (const edgeId of this.closedEdgeIds) {
      const meshes = this.edgeMeshes.get(edgeId);
      if (!meshes) continue;
      for (const mesh of meshes) {
        (mesh.material as THREE.MeshBasicMaterial).color.copy(closedColor);
        (mesh.material as THREE.MeshBasicMaterial).opacity = 0.8;
      }
    }
  }

  private restoreEdgeColors(): void {
    const defaultColor = new THREE.Color(0x3a5f8a);
    for (const [edgeId, meshes] of this.edgeMeshes) {
      let color: THREE.Color;
      if (this.currentRoadMode === 'color') {
        const roadName = this.edgeRoadName.get(edgeId);
        color = (roadName ? this.roadColors.get(roadName) : undefined) ?? defaultColor;
      } else {
        color = defaultColor;
      }
      for (const mesh of meshes) {
        (mesh.material as THREE.MeshBasicMaterial).color.copy(color);
        (mesh.material as THREE.MeshBasicMaterial).opacity = 0.6;
      }
    }
  }

  get hasClosures(): boolean { return this.closedEdgeIds.size > 0; }

  removeAllCars(): number {
    return this.carSim?.removeAllCars() ?? 0;
  }

  respawnCars(count: number): void {
    for (let i = 0; i < count; i++) this.carSim?.spawnCar();
  }

  private buildBarriers(scene: THREE.Scene, pathPoints?: readonly THREE.Vector3[]): void {
    this.removeBarriers(scene);
    this.barrierGroup = new THREE.Group();
    this.barrierGroup.name = 'road-barriers';

    const barrierMat = new THREE.MeshBasicMaterial({
      color: 0xff3333,
      transparent: true,
      opacity: 0.7,
      depthTest: false,
      side: THREE.DoubleSide,
    });
    const stripeMat = new THREE.MeshBasicMaterial({
      color: 0xffcc00,
      transparent: true,
      opacity: 0.8,
      depthTest: false,
      side: THREE.DoubleSide,
    });

    // Determine which nodes sit on the marathon path so we skip barriers there
    const PATH_NODE_DIST = NODE_RADIUS + 2.0;
    const nodesOnPath = new Set<number>();
    if (pathPoints && pathPoints.length >= 2) {
      for (const node of this.nodes) {
        for (let pi = 0; pi < pathPoints.length - 1; pi++) {
          if (pointToSegmentDist(node.position, pathPoints[pi], pathPoints[pi + 1]) < PATH_NODE_DIST) {
            nodesOnPath.add(node.id);
            break;
          }
        }
      }
    }

    // Track placed barrier positions to deduplicate at shared nodes
    const placedKeys = new Set<string>();
    const BARRIER_OFFSET = NODE_RADIUS + 2.0;

    for (const edgeId of this.closedEdgeIds) {
      const edge = this.edges.find(e => e.id === edgeId);
      if (!edge) continue;

      // Only place a barrier at ends that are NOT on the marathon path
      const ends: { nodeId: number; isFrom: boolean }[] = [];
      if (!nodesOnPath.has(edge.from)) ends.push({ nodeId: edge.from, isFrom: true });
      if (!nodesOnPath.has(edge.to)) ends.push({ nodeId: edge.to, isFrom: false });
      // If both ends are on the path, skip entirely (shouldn't happen with crossing logic)
      if (ends.length === 0) continue;

      for (const { nodeId, isFrom } of ends) {
        // Deduplicate: only one barrier per node
        const key = `${nodeId}`;
        if (placedKeys.has(key)) continue;
        placedKeys.add(key);

        const nearPt = isFrom ? edge.points[0] : edge.points[edge.points.length - 1];
        const nextPt = isFrom ? edge.points[Math.min(1, edge.points.length - 1)] : edge.points[Math.max(0, edge.points.length - 2)];
        const dir = new THREE.Vector3().subVectors(nextPt, nearPt).normalize();

        const barrierWidth = 3.0;
        const barrierHeight = 1.5;
        const barGeo = new THREE.BoxGeometry(barrierWidth, barrierHeight, 0.3);
        const bar = new THREE.Mesh(barGeo, barrierMat.clone());
        bar.position.set(
          nearPt.x + dir.x * BARRIER_OFFSET,
          barrierHeight / 2 + 0.1,
          nearPt.z + dir.z * BARRIER_OFFSET,
        );
        bar.lookAt(
          bar.position.x + dir.x,
          bar.position.y,
          bar.position.z + dir.z,
        );
        bar.renderOrder = 8;
        this.barrierGroup.add(bar);

        const stripeGeo = new THREE.BoxGeometry(barrierWidth * 0.8, barrierHeight * 0.25, 0.32);
        const stripe = new THREE.Mesh(stripeGeo, stripeMat.clone());
        stripe.position.copy(bar.position);
        stripe.position.y += 0.1;
        stripe.rotation.copy(bar.rotation);
        stripe.renderOrder = 9;
        this.barrierGroup.add(stripe);
      }
    }

    scene.add(this.barrierGroup);
  }

  private removeBarriers(scene: THREE.Scene): void {
    if (!this.barrierGroup) return;
    this.barrierGroup.traverse(obj => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry.dispose();
        (obj.material as THREE.Material).dispose();
      }
    });
    scene.remove(this.barrierGroup);
    this.barrierGroup = null;
  }

  private buildEdges(): void {
    if (!this.sceneGroup) return;

    this.edgeGroup = new THREE.Group();
    this.edgeGroup.name = 'road-edges';
    const defaultColor = new THREE.Color(0x3a5f8a);

    for (const edge of this.edges) {
      const fromNode = this.nodes[edge.from];
      const toNode = this.nodes[edge.to];

      const trimmed = this.trimEdgePoints(edge.points, fromNode.position, toNode.position);
      if (trimmed.length < 2) continue;

      const roadName = this.edgeRoadName.get(edge.id);
      const color = (roadName ? this.roadColors.get(roadName) : undefined) ?? defaultColor;

      const mat = new THREE.MeshBasicMaterial({
        color,
        depthTest: false,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.6,
      });

      const leftLane = offsetPolyline(trimmed, LANE_OFFSET);
      const rightLane = offsetPolyline(trimmed, -LANE_OFFSET);

      const meshes: THREE.Mesh[] = [];
      for (const lane of [leftLane, rightLane]) {
        const geo = buildRibbonGeo(lane, RIBBON_WIDTH);
        const mesh = new THREE.Mesh(geo, mat.clone());
        mesh.renderOrder = 4;
        this.edgeGroup!.add(mesh);
        meshes.push(mesh);
      }
      this.edgeMeshes.set(edge.id, meshes);
    }

    this.sceneGroup.add(this.edgeGroup);
  }

  private buildNodes(): void {
    if (!this.sceneGroup) return;

    this.nodeGroup = new THREE.Group();
    this.nodeGroup.name = 'road-nodes';
    const segments = 24;
    const circleGeo = new THREE.RingGeometry(NODE_RADIUS * 0.6, NODE_RADIUS, segments);
    circleGeo.rotateX(-Math.PI / 2);

    const mat = new THREE.MeshBasicMaterial({
      color: 0x5a8fba,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.7,
      depthTest: false,
    });

    for (const node of this.nodes) {
      const mesh = new THREE.Mesh(circleGeo.clone(), mat.clone());
      mesh.position.set(node.position.x, NODE_Y, node.position.z);
      mesh.renderOrder = 5;
      this.nodeGroup!.add(mesh);
    }

    this.sceneGroup.add(this.nodeGroup);
  }

  private buildSpawnPoints(): void {
    if (!this.sceneGroup) return;

    this.spawnGroup = new THREE.Group();
    this.spawnGroup.name = 'road-spawns';
    const segments = 16;
    const circleGeo = new THREE.CircleGeometry(SPAWN_RADIUS, segments);
    circleGeo.rotateX(-Math.PI / 2);

    const mat = new THREE.MeshBasicMaterial({
      color: 0x44cc88,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.8,
      depthTest: false,
    });

    for (const nodeId of this.spawnNodeIds) {
      const node = this.nodes[nodeId];
      const mesh = new THREE.Mesh(circleGeo.clone(), mat.clone());
      mesh.position.set(node.position.x, SPAWN_Y, node.position.z);
      mesh.renderOrder = 6;
      this.spawnGroup!.add(mesh);
    }

    this.sceneGroup.add(this.spawnGroup);
  }

  private buildRoadNameLabels(): void {
    if (!this.sceneGroup) return;

    this.streetNameGroup = new THREE.Group();
    this.streetNameGroup.name = 'street-names';

    const LABEL_FONT = `600 24px -apple-system, BlinkMacSystemFont, 'DM Sans', sans-serif`;
    const PIN_HEIGHT = 15;
    const PIN_DOT_RADIUS = 1.0;

    const seen = new Set<string>();

    for (const entry of this.roadNames) {
      if (seen.has(entry.name)) continue;
      seen.add(entry.name);

      const poly = entry.polyline;
      if (poly.length < 2) continue;

      const color = this.roadColors.get(entry.name) ?? new THREE.Color(0x3a5f8a);
      const colorHex = '#' + color.getHexString();

      // Find midpoint along the polyline
      const cumDist = [0];
      for (let i = 1; i < poly.length; i++) {
        const dx = poly[i].x - poly[i - 1].x;
        const dz = poly[i].z - poly[i - 1].z;
        cumDist.push(cumDist[i - 1] + Math.sqrt(dx * dx + dz * dz));
      }
      const totalDist = cumDist[cumDist.length - 1];
      if (totalDist < 5) continue;

      const halfDist = totalDist * 0.5;
      let midPos = poly[0].clone();
      for (let i = 1; i < cumDist.length; i++) {
        if (cumDist[i] >= halfDist) {
          const seg = cumDist[i] - cumDist[i - 1];
          const t = seg > 0.001 ? (halfDist - cumDist[i - 1]) / seg : 0;
          midPos = new THREE.Vector3().lerpVectors(poly[i - 1], poly[i], t);
          break;
        }
      }

      // ── Vertical pin line ──
      const lineGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(midPos.x, 0.2, midPos.z),
        new THREE.Vector3(midPos.x, PIN_HEIGHT, midPos.z),
      ]);
      const lineMat = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: 0.5,
        depthTest: false,
      });
      const line = new THREE.Line(lineGeo, lineMat);
      line.renderOrder = 3;
      this.streetNameGroup!.add(line);

      // ── Pin dot at the base ──
      const dotGeo = new THREE.SphereGeometry(PIN_DOT_RADIUS, 8, 6);
      const dotMat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.7,
        depthTest: false,
      });
      const dot = new THREE.Mesh(dotGeo, dotMat);
      dot.position.set(midPos.x, 0.5, midPos.z);
      dot.renderOrder = 3;
      this.streetNameGroup!.add(dot);

      // ── Billboard sprite label at the top ──
      const measure = document.createElement('canvas').getContext('2d')!;
      measure.font = LABEL_FONT;
      const textW = measure.measureText(entry.name).width;
      const padX = 20;
      const padY = 8;
      const pipR = 5;
      const canvasW = Math.ceil(textW + padX * 2 + pipR * 2 + 8);
      const canvasH = 40;

      const canvas = document.createElement('canvas');
      canvas.width = canvasW;
      canvas.height = canvasH;
      const ctx = canvas.getContext('2d')!;

      // Background pill
      const r = canvasH / 2;
      ctx.beginPath();
      ctx.moveTo(r, 0);
      ctx.lineTo(canvasW - r, 0);
      ctx.arcTo(canvasW, 0, canvasW, r, r);
      ctx.lineTo(canvasW, canvasH - r);
      ctx.arcTo(canvasW, canvasH, canvasW - r, canvasH, r);
      ctx.lineTo(r, canvasH);
      ctx.arcTo(0, canvasH, 0, canvasH - r, r);
      ctx.lineTo(0, r);
      ctx.arcTo(0, 0, r, 0, r);
      ctx.closePath();
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fill();
      ctx.strokeStyle = colorHex;
      ctx.lineWidth = 2;
      ctx.stroke();

      // Color pip
      const pipX = padX;
      const pipY = canvasH / 2;
      ctx.beginPath();
      ctx.arc(pipX, pipY, pipR, 0, Math.PI * 2);
      ctx.fillStyle = colorHex;
      ctx.shadowColor = colorHex;
      ctx.shadowBlur = 8;
      ctx.fill();
      ctx.shadowBlur = 0;

      // Text
      ctx.font = LABEL_FONT;
      ctx.fillStyle = 'rgba(255,255,255,0.92)';
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'left';
      ctx.shadowColor = 'rgba(0,0,0,0.7)';
      ctx.shadowBlur = 4;
      ctx.fillText(entry.name, pipX + pipR + 8, pipY);
      ctx.shadowBlur = 0;

      const tex = new THREE.CanvasTexture(canvas);
      tex.needsUpdate = true;

      const spriteMat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        depthTest: false,
        sizeAttenuation: true,
      });
      const sprite = new THREE.Sprite(spriteMat);
      const spriteScale = 0.12;
      sprite.scale.set(canvasW * spriteScale, canvasH * spriteScale, 1);
      sprite.position.set(midPos.x, PIN_HEIGHT + 2.5, midPos.z);
      sprite.renderOrder = 10;
      this.streetNameGroup!.add(sprite);
    }

    this.sceneGroup!.add(this.streetNameGroup);
  }

  setStreetNamesVisible(visible: boolean): void {
    if (this.streetNameGroup) this.streetNameGroup.visible = visible;
  }

  setRoadDisplayMode(mode: 'off' | 'on' | 'color'): void {
    this.currentRoadMode = mode;
    if (mode === 'off') {
      if (this.edgeGroup) this.edgeGroup.visible = false;
      if (this.nodeGroup) this.nodeGroup.visible = false;
      if (this.spawnGroup) this.spawnGroup.visible = false;
    } else {
      if (this.edgeGroup) this.edgeGroup.visible = true;
      if (this.nodeGroup) this.nodeGroup.visible = true;
      if (this.spawnGroup) this.spawnGroup.visible = true;
      const defaultColor = new THREE.Color(0x3a5f8a);
      for (const [edgeId, meshes] of this.edgeMeshes) {
        if (this.closedEdgeIds.has(edgeId)) continue;
        let color: THREE.Color;
        if (mode === 'color') {
          const roadName = this.edgeRoadName.get(edgeId);
          color = (roadName ? this.roadColors.get(roadName) : undefined) ?? defaultColor;
        } else {
          color = defaultColor;
        }
        for (const mesh of meshes) {
          (mesh.material as THREE.MeshBasicMaterial).color.copy(color);
        }
      }
    }
  }

  private trimEdgePoints(
    points: THREE.Vector3[],
    fromPos: THREE.Vector3,
    toPos: THREE.Vector3,
  ): THREE.Vector3[] {
    if (points.length < 2) return points;

    const result = points.map(p => p.clone());
    const gap = NODE_RADIUS * 1.2;

    // Trim from start
    let trimStart = 0;
    for (let i = 0; i < result.length - 1; i++) {
      const dx = result[i].x - fromPos.x;
      const dz = result[i].z - fromPos.z;
      if (Math.sqrt(dx * dx + dz * dz) < gap) {
        trimStart = i + 1;
      } else {
        break;
      }
    }

    // Trim from end
    let trimEnd = result.length;
    for (let i = result.length - 1; i > trimStart; i--) {
      const dx = result[i].x - toPos.x;
      const dz = result[i].z - toPos.z;
      if (Math.sqrt(dx * dx + dz * dz) < gap) {
        trimEnd = i;
      } else {
        break;
      }
    }

    const trimmed = result.slice(trimStart, trimEnd);

    if (trimStart > 0 && trimmed.length > 0) {
      const dir = new THREE.Vector3().subVectors(trimmed[0], fromPos).normalize();
      trimmed.unshift(fromPos.clone().addScaledVector(dir, gap));
    }
    if (trimEnd < result.length && trimmed.length > 0) {
      const dir = new THREE.Vector3().subVectors(trimmed[trimmed.length - 1], toPos).normalize();
      trimmed.push(toPos.clone().addScaledVector(dir, gap));
    }

    return trimmed;
  }
}

// ── Geometry helpers ────────────────────────────────────────────────────────

function pointToSegmentDist(p: THREE.Vector3, a: THREE.Vector3, b: THREE.Vector3): number {
  const abx = b.x - a.x, abz = b.z - a.z;
  const apx = p.x - a.x, apz = p.z - a.z;
  const dot = abx * apx + abz * apz;
  const lenSq = abx * abx + abz * abz;
  let t = lenSq > 0 ? dot / lenSq : 0;
  t = Math.max(0, Math.min(1, t));
  const cx = a.x + t * abx - p.x;
  const cz = a.z + t * abz - p.z;
  return Math.sqrt(cx * cx + cz * cz);
}

function projectOntoSegment(p: THREE.Vector3, a: THREE.Vector3, b: THREE.Vector3): number {
  const abx = b.x - a.x, abz = b.z - a.z;
  const apx = p.x - a.x, apz = p.z - a.z;
  const lenSq = abx * abx + abz * abz;
  if (lenSq < 1e-10) return 0;
  return Math.max(0, Math.min(1, (abx * apx + abz * apz) / lenSq));
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

/** Minimum 2D (xz) distance between two line segments. */
function segmentToSegmentDist(
  a1: THREE.Vector3, a2: THREE.Vector3,
  b1: THREE.Vector3, b2: THREE.Vector3,
): number {
  // Check all four point-to-segment distances and return the minimum
  return Math.min(
    pointToSegmentDist(a1, b1, b2),
    pointToSegmentDist(a2, b1, b2),
    pointToSegmentDist(b1, a1, a2),
    pointToSegmentDist(b2, a1, a2),
  );
}
