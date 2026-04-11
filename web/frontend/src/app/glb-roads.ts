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
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export interface GLBRoadsTransform {
  scale: number;
  offsetX: number;
  offsetY: number;
  offsetZ: number;
  rotationY: number;
}

export const GLB_TRANSFORM: GLBRoadsTransform = {
  scale: .1,
  offsetX: 40,
  offsetY: 0,
  offsetZ: -10,
  rotationY: 0,
};

export class GLBRoadsLoader {
  private scene: THREE.Scene;
  private root: THREE.Group | null = null;
  private loaded = false;

  constructor(scene: THREE.Scene) {
    this.scene = scene;
  }

  async load(url: string): Promise<void> {
    const loader = new GLTFLoader();
    return new Promise((resolve) => {
      loader.load(
        url,
        (gltf) => {
          if (this.root) this.scene.remove(this.root);
          this.root = gltf.scene;

          this.root.traverse((child) => {
            if ((child as THREE.Mesh).isMesh) {
              const mesh = child as THREE.Mesh;
              const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
              mats.forEach((mat) => {
                if (mat) {
                  mat.side = THREE.DoubleSide;
                  if ('emissive' in mat) {
                    (mat as THREE.MeshStandardMaterial).emissive = new THREE.Color(0x334455);
                    (mat as THREE.MeshStandardMaterial).emissiveIntensity = 0.4;
                  }
                }
              });
              mesh.renderOrder = 1;
              mesh.castShadow = false;
              mesh.receiveShadow = false;
            }
          });

          this.scene.add(this.root);
          this.applyTransform();
          this.loaded = true;
          resolve();
        },
        undefined,
        (err) => {
          console.warn('GLB Roads: failed to load', url, err);
          resolve();
        },
      );
    });
  }

  isLoaded(): boolean {
    return this.loaded;
  }

  dispose(): void {
    if (this.root) {
      this.scene.remove(this.root);
      this.root.traverse((child) => {
        if ((child as THREE.Mesh).isMesh) {
          const mesh = child as THREE.Mesh;
          mesh.geometry?.dispose();
          const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
          mats.forEach(m => m?.dispose());
        }
      });
      this.root = null;
    }
  }

  private applyTransform(): void {
    if (!this.root) return;
    const t = GLB_TRANSFORM;
    this.root.scale.setScalar(t.scale);
    this.root.position.set(t.offsetX, t.offsetY, t.offsetZ);
    this.root.rotation.set(0, THREE.MathUtils.degToRad(t.rotationY), 0);
  }
}
