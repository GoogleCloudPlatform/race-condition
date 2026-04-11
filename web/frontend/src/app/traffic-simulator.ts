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

export type LightState = 'green' | 'yellow' | 'red';

export interface TrafficLight {
  nodeId: number;
  edgeId: number;
  direction: THREE.Vector3;
  state: LightState;
  mesh: THREE.Group | null;
}

interface IntersectionPhase {
  edgeIds: number[];
  greenDuration: number;
  yellowDuration: number;
}

interface IntersectionController {
  nodeId: number;
  lights: TrafficLight[];
  phases: IntersectionPhase[];
  currentPhase: number;
  timer: number;
  currentState: 'green' | 'yellow' | 'red';
}

const GREEN_DURATION = 8.0;
const YELLOW_DURATION = 2.0;
const RED_GAP = 0.5;
const LIGHT_HEIGHT = 5.0;
const LIGHT_OFFSET = 3.5;
const BOX_W = 0.6;
const BOX_H = 2.0;
const BOX_D = 0.4;
const BULB_RADIUS = 0.18;
const BULB_SPACING = 0.55;

export class TrafficSimulator {
  private controllers: IntersectionController[] = [];
  private sceneGroup: THREE.Group | null = null;

  constructor(
    private nodes: RoadNode[],
    private edges: RoadEdge[],
  ) {
    this.buildControllers();
  }

  private buildControllers(): void {
    const nodeEdgeMap = new Map<number, RoadEdge[]>();
    for (const edge of this.edges) {
      if (!nodeEdgeMap.has(edge.from)) nodeEdgeMap.set(edge.from, []);
      if (!nodeEdgeMap.has(edge.to)) nodeEdgeMap.set(edge.to, []);
      nodeEdgeMap.get(edge.from)!.push(edge);
      nodeEdgeMap.get(edge.to)!.push(edge);
    }

    for (const node of this.nodes) {
      const connectedEdges = nodeEdgeMap.get(node.id) ?? [];
      if (connectedEdges.length < 2) continue;

      const lights: TrafficLight[] = [];
      for (const edge of connectedEdges) {
        const isFrom = edge.from === node.id;
        const pts = edge.points;

        // Walk along the edge to find a point far enough to get a reliable direction
        let nearPt: THREE.Vector3 | null = null;
        if (isFrom) {
          for (let i = 1; i < pts.length; i++) {
            const dx = pts[i].x - node.position.x;
            const dz = pts[i].z - node.position.z;
            if (dx * dx + dz * dz > 0.01) { nearPt = pts[i]; break; }
          }
        } else {
          for (let i = pts.length - 2; i >= 0; i--) {
            const dx = pts[i].x - node.position.x;
            const dz = pts[i].z - node.position.z;
            if (dx * dx + dz * dz > 0.01) { nearPt = pts[i]; break; }
          }
        }
        if (!nearPt) continue;

        const dir = new THREE.Vector3()
          .subVectors(nearPt, node.position)
          .setY(0)
          .normalize();

        if (!isFinite(dir.x) || !isFinite(dir.z)) continue;

        lights.push({
          nodeId: node.id,
          edgeId: edge.id,
          direction: dir,
          state: 'red',
          mesh: null,
        });
      }

      const phases = this.buildPhases(lights);

      this.controllers.push({
        nodeId: node.id,
        lights,
        phases,
        currentPhase: 0,
        timer: Math.random() * GREEN_DURATION,
        currentState: 'green',
      });

      if (phases.length > 0) {
        for (const eid of phases[0].edgeIds) {
          const l = lights.find(li => li.edgeId === eid);
          if (l) l.state = 'green';
        }
      }
    }
  }

  private buildPhases(lights: TrafficLight[]): IntersectionPhase[] {
    if (lights.length <= 1) {
      return [{ edgeIds: lights.map(l => l.edgeId), greenDuration: GREEN_DURATION, yellowDuration: YELLOW_DURATION }];
    }

    const sorted = [...lights].sort((a, b) => {
      const angA = Math.atan2(a.direction.z, a.direction.x);
      const angB = Math.atan2(b.direction.z, b.direction.x);
      return angA - angB;
    });

    if (lights.length === 2) {
      return [
        { edgeIds: sorted.map(l => l.edgeId), greenDuration: GREEN_DURATION, yellowDuration: YELLOW_DURATION },
      ];
    }

    // Group opposing directions together
    const used = new Set<number>();
    const phases: IntersectionPhase[] = [];

    for (let i = 0; i < sorted.length; i++) {
      if (used.has(sorted[i].edgeId)) continue;
      const group = [sorted[i].edgeId];
      used.add(sorted[i].edgeId);

      // Find the most opposing direction
      let bestJ = -1, bestDot = 1;
      for (let j = 0; j < sorted.length; j++) {
        if (used.has(sorted[j].edgeId)) continue;
        const dot = sorted[i].direction.dot(sorted[j].direction);
        if (dot < bestDot) { bestDot = dot; bestJ = j; }
      }
      if (bestJ >= 0 && bestDot < -0.3) {
        group.push(sorted[bestJ].edgeId);
        used.add(sorted[bestJ].edgeId);
      }

      phases.push({ edgeIds: group, greenDuration: GREEN_DURATION, yellowDuration: YELLOW_DURATION });
    }

    return phases;
  }

  tick(delta: number): void {
    for (const ctrl of this.controllers) {
      if (ctrl.phases.length === 0) continue;

      ctrl.timer += delta;
      const phase = ctrl.phases[ctrl.currentPhase];

      if (ctrl.currentState === 'green' && ctrl.timer >= phase.greenDuration) {
        ctrl.timer = 0;
        ctrl.currentState = 'yellow';
        for (const eid of phase.edgeIds) {
          const l = ctrl.lights.find(li => li.edgeId === eid);
          if (l) l.state = 'yellow';
        }
      } else if (ctrl.currentState === 'yellow' && ctrl.timer >= phase.yellowDuration) {
        ctrl.timer = 0;
        // All red
        for (const l of ctrl.lights) l.state = 'red';
        ctrl.currentState = 'red';
      } else if (ctrl.currentState === 'red' && ctrl.timer >= RED_GAP) {
        ctrl.timer = 0;
        ctrl.currentPhase = (ctrl.currentPhase + 1) % ctrl.phases.length;
        ctrl.currentState = 'green';
        const nextPhase = ctrl.phases[ctrl.currentPhase];
        for (const eid of nextPhase.edgeIds) {
          const l = ctrl.lights.find(li => li.edgeId === eid);
          if (l) l.state = 'green';
        }
      }
    }

    this.updateLightVisuals();
  }

  addToScene(scene: THREE.Scene): void {
    this.removeFromScene(scene);
    this.sceneGroup = new THREE.Group();
    this.sceneGroup.name = 'traffic-lights';

    for (const ctrl of this.controllers) {
      const nodePos = this.nodes[ctrl.nodeId].position;
      for (const light of ctrl.lights) {
        light.mesh = this.buildLightMesh();
        const offset = light.direction.clone().multiplyScalar(LIGHT_OFFSET);
        light.mesh.position.set(
          nodePos.x + offset.x,
          LIGHT_HEIGHT,
          nodePos.z + offset.z,
        );
        // Face outward along the road (toward approaching traffic)
        light.mesh.lookAt(
          nodePos.x + offset.x + light.direction.x,
          LIGHT_HEIGHT,
          nodePos.z + offset.z + light.direction.z,
        );
        this.sceneGroup.add(light.mesh);
      }
    }

    scene.add(this.sceneGroup);
    this.updateLightVisuals();
  }

  removeFromScene(scene: THREE.Scene): void {
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

  private buildLightMesh(): THREE.Group {
    const group = new THREE.Group();

    // Black box housing
    const boxGeo = new THREE.BoxGeometry(BOX_W, BOX_H, BOX_D);
    const boxMat = new THREE.MeshBasicMaterial({ color: 0x111111 });
    const box = new THREE.Mesh(boxGeo, boxMat);
    group.add(box);

    // Three bulbs: red (top), yellow (middle), green (bottom)
    const bulbGeo = new THREE.CircleGeometry(BULB_RADIUS, 12);
    const colors = [0x330000, 0x333300, 0x003300]; // dim defaults
    const yOffsets = [BULB_SPACING, 0, -BULB_SPACING];

    for (let i = 0; i < 3; i++) {
      const mat = new THREE.MeshBasicMaterial({ color: colors[i] });
      const bulb = new THREE.Mesh(bulbGeo.clone(), mat);
      bulb.position.set(0, yOffsets[i], BOX_D / 2 + 0.01);
      bulb.name = ['bulb-red', 'bulb-yellow', 'bulb-green'][i];
      group.add(bulb);
    }

    return group;
  }

  getLightState(nodeId: number, edgeId: number): LightState | null {
    const ctrl = this.controllers.find(c => c.nodeId === nodeId);
    if (!ctrl) return null;
    const light = ctrl.lights.find(l => l.edgeId === edgeId);
    return light?.state ?? null;
  }

  private updateLightVisuals(): void {
    for (const ctrl of this.controllers) {
      for (const light of ctrl.lights) {
        if (!light.mesh) continue;
        const redBulb = light.mesh.getObjectByName('bulb-red') as THREE.Mesh | undefined;
        const yellowBulb = light.mesh.getObjectByName('bulb-yellow') as THREE.Mesh | undefined;
        const greenBulb = light.mesh.getObjectByName('bulb-green') as THREE.Mesh | undefined;

        if (redBulb) (redBulb.material as THREE.MeshBasicMaterial).color.setHex(light.state === 'red' ? 0xff0000 : 0x330000);
        if (yellowBulb) (yellowBulb.material as THREE.MeshBasicMaterial).color.setHex(light.state === 'yellow' ? 0xffdd00 : 0x333300);
        if (greenBulb) (greenBulb.material as THREE.MeshBasicMaterial).color.setHex(light.state === 'green' ? 0x00ff00 : 0x003300);
      }
    }
  }
}
