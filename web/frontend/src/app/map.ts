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

export interface OSMBuilding {
  id: string;
  footprint: THREE.Vector2[];
  height: number;
  levels: number;
  buildingType: string;
  name?: string;
  tags: Record<string, string>;
}

export interface OSMRoad {
  id: string;
  points: THREE.Vector2[];
  nodeIds: string[];
  width: number;
  highway: string;
  name?: string;
  tags: Record<string, string>;
}

export interface OSMPath {
  id: string;
  points: THREE.Vector2[];
  width: number;
  pathType: string;
  name?: string;
  tags: Record<string, string>;
}

export interface RoadGraphEdge {
  toNodeId: string;
  roadId: string;
  points: THREE.Vector2[];
  length: number;
}

export interface RoadGraphNode {
  id: string;
  position: THREE.Vector2;
  edges: RoadGraphEdge[];
}

export interface RoadGraph {
  nodes: Map<string, RoadGraphNode>;
  nodeIds: string[];
  getNode(id: string): RoadGraphNode | undefined;
  getNeighbours(nodeId: string): RoadGraphEdge[];
  randomNode(): RoadGraphNode;
}

export interface GeoJSONLandmark {
  id: string;
  name: string;
  worldPos: THREE.Vector2;
}

export interface OSMMapData {
  buildings: OSMBuilding[];
  roads: OSMRoad[];
  paths: OSMPath[];
  landmarks: GeoJSONLandmark[];
  roadGraph: RoadGraph;
  bounds: {
    minX: number; maxX: number;
    minY: number; maxY: number;
    width: number; height: number;
    centerX: number; centerY: number;
  };
  rawCenterX: number;
  rawCenterY: number;
}

interface GeoJSONFeature {
  type: 'Feature';
  properties: Record<string, unknown> | null;
  geometry: {
    type: string;
    coordinates: unknown;
  };
}

interface GeoJSONCollection {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

const DEFAULT_ROAD_WIDTH = 0.3;
const DEFAULT_ROAD_TYPE = 'residential';

const ROAD_WIDTHS: Record<string, number> = {
  motorway: 0.8,   motorway_link: 0.5,
  trunk: 0.7,      trunk_link: 0.5,
  primary: 0.6,    primary_link: 0.4,
  secondary: 0.5,  secondary_link: 0.35,
  tertiary: 0.4,   tertiary_link: 0.3,
  residential: 0.3, living_street: 0.25,
  service: 0.2,    unclassified: 0.3,
  road: 0.3,
};

const PATH_WIDTHS: Record<string, number> = {
  footway: 0.12, path: 0.1, cycleway: 0.15, pedestrian: 0.2,
  steps: 0.1, track: 0.18, bridleway: 0.12,
};

const ROAD_TAGS = new Set(Object.keys(ROAD_WIDTHS));
const PATH_TAGS = new Set(Object.keys(PATH_WIDTHS));

function latLonToMeters(lat: number, lon: number): { x: number; y: number } {
  const R = 6378137;
  return {
    x: (lon * Math.PI / 180) * R,
    y: Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI / 180) / 2)) * R,
  };
}

function segmentLength(points: THREE.Vector2[]): number {
  let len = 0;
  for (let i = 0; i < points.length - 1; i++) len += points[i].distanceTo(points[i + 1]);
  return len;
}

export class GeoJSONMap {
  private data: OSMMapData | null = null;

  async load(url: string, worldScale = 1): Promise<OSMMapData> {
    const response = await fetch(url);
    const json: GeoJSONCollection = await response.json();
    this.data = this.parse(json, worldScale);
    return this.data;
  }

  parseFromObject(json: GeoJSONCollection, worldScale = 1): OSMMapData {
    this.data = this.parse(json, worldScale);
    return this.data;
  }

  private parse(json: GeoJSONCollection, worldScale: number): OSMMapData {
    const { roads, paths, buildings, landmarks } = this.parseFeatures(json.features);

    const allPoints = [
      ...buildings.flatMap(b => b.footprint),
      ...roads.flatMap(r => r.points),
      ...paths.flatMap(p => p.points),
    ];

    const bounds = this.computeBounds(allPoints);
    const center = new THREE.Vector2(bounds.centerX, bounds.centerY);
    const rawCenterX = bounds.centerX;
    const rawCenterY = bounds.centerY;

    buildings.forEach(b => {
      b.footprint = b.footprint.map(p => p.clone().sub(center).multiplyScalar(worldScale));
      b.height *= worldScale;
    });
    roads.forEach(r => {
      r.points = r.points.map(p => p.clone().sub(center).multiplyScalar(worldScale));
      r.width *= worldScale;
    });
    paths.forEach(p => {
      p.points = p.points.map(pt => pt.clone().sub(center).multiplyScalar(worldScale));
      p.width *= worldScale;
    });
    landmarks.forEach(l => {
      l.worldPos = l.worldPos.clone().sub(center).multiplyScalar(worldScale);
    });

    const roadGraph = this.buildRoadGraph(roads);

    bounds.minX = (bounds.minX - bounds.centerX) * worldScale;
    bounds.maxX = (bounds.maxX - bounds.centerX) * worldScale;
    bounds.minY = (bounds.minY - bounds.centerY) * worldScale;
    bounds.maxY = (bounds.maxY - bounds.centerY) * worldScale;
    bounds.width *= worldScale;
    bounds.height *= worldScale;
    bounds.centerX = 0;
    bounds.centerY = 0;

    return { buildings, roads, paths, landmarks, roadGraph, bounds, rawCenterX, rawCenterY };
  }

  private parseFeatures(features: GeoJSONFeature[]): {
    roads: OSMRoad[];
    paths: OSMPath[];
    buildings: OSMBuilding[];
    landmarks: GeoJSONLandmark[];
  } {
    const roads: OSMRoad[] = [];
    const paths: OSMPath[] = [];
    const buildings: OSMBuilding[] = [];
    const landmarks: GeoJSONLandmark[] = [];

    features.forEach((feature, idx) => {
      const props = feature.properties ?? {};
      const geom = feature.geometry;
      const id = String(idx);

      if (geom.type === 'Point') {
        const name = (props['name'] as string | undefined)?.trim();
        if (!name) return;
        const [lon, lat] = geom.coordinates as [number, number];
        const m = latLonToMeters(lat, lon);
        landmarks.push({ id, name, worldPos: new THREE.Vector2(m.x, m.y) });
        return;
      }

      if (geom.type === 'LineString') {
        const coords = geom.coordinates as [number, number][];
        const points = coords.map(([lon, lat]) => {
          const m = latLonToMeters(lat, lon);
          return new THREE.Vector2(m.x, m.y);
        });
        if (points.length < 2) return;

        const highway = this.resolveHighway(props);
        const tags = this.propsToTags(props, highway);

        if (PATH_TAGS.has(highway)) {
          paths.push({
            id,
            points,
            width: PATH_WIDTHS[highway] ?? 0.1,
            pathType: highway,
            name: props['name'] as string | undefined,
            tags,
          });
        } else {
          roads.push({
            id,
            points,
            nodeIds: points.map((_, i) => `${id}_${i}`),
            width: ROAD_WIDTHS[highway] ?? DEFAULT_ROAD_WIDTH,
            highway,
            name: props['name'] as string | undefined,
            tags,
          });
        }
      }

      if (geom.type === 'Polygon') {
        const rings = geom.coordinates as [number, number][][];
        const outer = rings[0];
        if (!outer || outer.length < 3) return;

        const footprint = outer.map(([lon, lat]) => {
          const m = latLonToMeters(lat, lon);
          return new THREE.Vector2(m.x, m.y);
        });
        if (footprint.length > 1 && footprint[0].distanceTo(footprint[footprint.length - 1]) < 0.01) {
          footprint.pop();
        }

        const tags = this.propsToTags(props);
        buildings.push({
          id,
          footprint,
          height: this.resolveHeight(props),
          levels: this.resolveLevels(props),
          buildingType: this.classifyBuilding(tags),
          name: props['name'] as string | undefined,
          tags,
        });
      }
    });

    return { roads, paths, buildings, landmarks };
  }

  private resolveHighway(props: Record<string, unknown>): string {
    const hw = (props['highway'] ?? props['type'] ?? props['road_type'] ?? '') as string;
    if (hw && (ROAD_TAGS.has(hw) || PATH_TAGS.has(hw))) return hw;
    return DEFAULT_ROAD_TYPE;
  }

  private propsToTags(props: Record<string, unknown>, highway?: string): Record<string, string> {
    const tags: Record<string, string> = {};
    for (const [k, v] of Object.entries(props)) {
      if (v != null) tags[k] = String(v);
    }
    if (highway) tags['highway'] = highway;
    return tags;
  }

  private resolveHeight(props: Record<string, unknown>): number {
    const h = parseFloat(String(props['height'] ?? props['building:height'] ?? ''));
    if (!isNaN(h) && h > 0) return h;
    const levels = parseInt(String(props['building:levels'] ?? props['levels'] ?? ''));
    if (!isNaN(levels) && levels > 0) return levels * 3;
    return 6;
  }

  private resolveLevels(props: Record<string, unknown>): number {
    const l = parseInt(String(props['building:levels'] ?? props['levels'] ?? ''));
    return isNaN(l) ? 2 : l;
  }

  private classifyBuilding(tags: Record<string, string>): string {
    const b = tags['building'], amenity = tags['amenity'];
    if (amenity === 'place_of_worship' || b === 'church' || b === 'cathedral') return 'worship';
    if (b === 'industrial' || b === 'warehouse' || b === 'factory') return 'industrial';
    if (tags['shop'] || b === 'retail' || b === 'commercial') return 'commercial';
    if (b === 'office' || tags['office']) return 'office';
    if (amenity === 'hospital' || b === 'hospital') return 'medical';
    if (amenity === 'school' || amenity === 'university') return 'education';
    if (b === 'house' || b === 'detached' || b === 'terrace' || b === 'bungalow') return 'residential';
    if (b === 'apartments' || b === 'residential') return 'apartments';
    return 'generic';
  }

  private buildRoadGraph(roads: OSMRoad[]): RoadGraph {
    const SNAP = 0.5;
    const posKey = (p: THREE.Vector2) => `${Math.round(p.x / SNAP)},${Math.round(p.y / SNAP)}`;

    const canonical = new Map<string, THREE.Vector2>();
    const getCanon = (p: THREE.Vector2): THREE.Vector2 => {
      const k = posKey(p);
      if (!canonical.has(k)) canonical.set(k, p.clone());
      return canonical.get(k)!;
    };

    type RawSeg = { roadId: string; a: THREE.Vector2; b: THREE.Vector2 };
    const allSegs: RawSeg[] = [];
    for (const road of roads) {
      for (let i = 0; i < road.points.length - 1; i++) {
        allSegs.push({ roadId: road.id, a: road.points[i], b: road.points[i + 1] });
      }
    }

    const intersectSegs = (
      a1: THREE.Vector2, a2: THREE.Vector2,
      b1: THREE.Vector2, b2: THREE.Vector2,
    ): THREE.Vector2 | null => {
      const dx1 = a2.x - a1.x, dy1 = a2.y - a1.y;
      const dx2 = b2.x - b1.x, dy2 = b2.y - b1.y;
      const denom = dx1 * dy2 - dy1 * dx2;
      if (Math.abs(denom) < 1e-10) return null;
      const dx3 = b1.x - a1.x, dy3 = b1.y - a1.y;
      const t = (dx3 * dy2 - dy3 * dx2) / denom;
      const u = (dx3 * dy1 - dy3 * dx1) / denom;
      if (t > 1e-6 && t < 1 - 1e-6 && u > 1e-6 && u < 1 - 1e-6) {
        return new THREE.Vector2(a1.x + t * dx1, a1.y + t * dy1);
      }
      return null;
    };

    const splitMap = new Map<number, THREE.Vector2[]>();
    for (let i = 0; i < allSegs.length; i++) {
      for (let j = i + 1; j < allSegs.length; j++) {
        const pt = intersectSegs(allSegs[i].a, allSegs[i].b, allSegs[j].a, allSegs[j].b);
        if (!pt) continue;
        const cp = getCanon(pt);
        if (!splitMap.has(i)) splitMap.set(i, []);
        if (!splitMap.has(j)) splitMap.set(j, []);
        splitMap.get(i)!.push(cp);
        splitMap.get(j)!.push(cp);
      }
    }

    type GraphSeg = { roadId: string; a: THREE.Vector2; b: THREE.Vector2 };
    const graphSegs: GraphSeg[] = [];

    for (let i = 0; i < allSegs.length; i++) {
      const { roadId, a, b } = allSegs[i];
      const ca = getCanon(a), cb = getCanon(b);
      const pts = splitMap.get(i) ?? [];
      if (!pts.length) { graphSegs.push({ roadId, a: ca, b: cb }); continue; }
      const dir = cb.clone().sub(ca);
      const tLen = dir.length();
      const sorted = pts
        .map(p => ({ p, t: p.clone().sub(ca).dot(dir) / (tLen * tLen) }))
        .filter(x => x.t > 1e-6 && x.t < 1 - 1e-6)
        .sort((x, y) => x.t - y.t);
      let prev = ca;
      for (const { p } of sorted) { graphSegs.push({ roadId, a: prev, b: p }); prev = p; }
      graphSegs.push({ roadId, a: prev, b: cb });
    }

    const nodes = new Map<string, RoadGraphNode>();
    const ensureNode = (p: THREE.Vector2): RoadGraphNode => {
      const k = posKey(p);
      if (!nodes.has(k)) nodes.set(k, { id: k, position: p.clone(), edges: [] });
      return nodes.get(k)!;
    };

    for (const { roadId, a, b } of graphSegs) {
      const na = ensureNode(a), nb = ensureNode(b);
      if (na.id === nb.id) continue;
      const seg = [a.clone(), b.clone()];
      const len = segmentLength(seg);
      na.edges.push({ toNodeId: nb.id, roadId, points: seg, length: len });
      nb.edges.push({ toNodeId: na.id, roadId, points: [b.clone(), a.clone()], length: len });
    }

    const nodeIds = Array.from(nodes.keys());
    return {
      nodes, nodeIds,
      getNode: id => nodes.get(id),
      getNeighbours: id => nodes.get(id)?.edges ?? [],
      randomNode: () => nodes.get(nodeIds[Math.floor(Math.random() * nodeIds.length)])!,
    };
  }

  private computeBounds(points: THREE.Vector2[]): OSMMapData['bounds'] {
    if (!points.length) {
      return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0, centerX: 0, centerY: 0 };
    }
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const p of points) {
      if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x;
      if (p.y < minY) minY = p.y; if (p.y > maxY) maxY = p.y;
    }
    return {
      minX, maxX, minY, maxY,
      width: maxX - minX,
      height: maxY - minY,
      centerX: (minX + maxX) / 2,
      centerY: (minY + maxY) / 2,
    };
  }

  getData(): OSMMapData | null { return this.data; }
}

export { GeoJSONMap as OSMMap };
