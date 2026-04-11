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
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js';
import { SSAOPass } from 'three/examples/jsm/postprocessing/SSAOPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { LUTPass } from 'three/examples/jsm/postprocessing/LUTPass.js';
import { LUTCubeLoader } from 'three/examples/jsm/loaders/LUTCubeLoader.js';
import { FXAAShader } from 'three/examples/jsm/shaders/FXAAShader.js';
import { Context } from '../context';
import { DepthOutlineShader } from '../shaders/depth-outline-shader';
import { VignetteColorShader } from '../shaders/vignette-shader';

export function initPostProcessing(ctx: Context): void {
  const w = window.innerWidth,
    h = window.innerHeight;

  ctx.depthRT = new THREE.WebGLRenderTarget(w, h, {
    depthTexture: new THREE.DepthTexture(w, h),
    depthBuffer: true,
  });

  // Create the EffectComposer with a render target that includes a readable
  // DepthTexture. The constructor clones it for renderTarget2, giving each
  // buffer its own depth texture. This lets the RenderPass write scene depth
  // as part of its normal render — no separate depth pre-pass needed.
  // const pr = ctx.renderer.getPixelRatio();
  // const rt = new THREE.WebGLRenderTarget(w * pr, h * pr, {
  //   type: THREE.HalfFloatType,
  //   depthTexture: new THREE.DepthTexture(w * pr, h * pr),
  // });
  // ctx.composer = new EffectComposer(ctx.renderer, rt);

  ctx.composer = new EffectComposer(ctx.renderer);

  ctx.composer.addPass(new RenderPass(ctx.scene, ctx.camera));

  // SSAO
  ctx.ssaoPass = new SSAOPass(ctx.scene, ctx.camera, w, h);
  ctx.ssaoPass.kernelRadius = 120;
  ctx.ssaoPass.minDistance = 0.0;
  ctx.ssaoPass.maxDistance = 1000;
  const origOverrideVis = (ctx.ssaoPass as any)._overrideVisibility.bind(ctx.ssaoPass);
  (ctx.ssaoPass as any)._overrideVisibility = function (this: any) {
    origOverrideVis();
    this.scene.traverse((obj: THREE.Object3D) => {
      const m = obj as THREE.Mesh;
      if (
        m.isMesh &&
        m.visible &&
        m.material &&
        (m.material as THREE.Material).depthWrite === false
      ) {
        m.visible = false;
        this._visibilityCache.push(m);
      }
    });
  };
  ctx.composer.addPass(ctx.ssaoPass);

  // Depth outline
  ctx.depthOutlinePass = new ShaderPass(DepthOutlineShader);
  ctx.depthOutlinePass.uniforms['tDepth'].value = ctx.depthRT.depthTexture;

  // tDepth is updated per-frame in animate() to point to readBuffer.depthTexture,
  // since the EffectComposer swaps read/write buffers between frames.
  // ctx.depthOutlinePass.uniforms['tDepth'].value = (ctx.composer as any).readBuffer.depthTexture;
  ctx.depthOutlinePass.uniforms['resolution'].value.set(
    w * ctx.renderer.getPixelRatio(),
    h * ctx.renderer.getPixelRatio(),
  );
  ctx.depthOutlinePass.uniforms['cameraNear'].value = 500;
  ctx.depthOutlinePass.uniforms['cameraFar'].value = 15000;
  ctx.depthOutlinePass.uniforms['threshold'].value = 0.01;
  ctx.depthOutlinePass.uniforms['outlineColor'].value.set(0x656565);
  ctx.depthOutlinePass.uniforms['outlineColorLow'].value.set(0x373737);
  ctx.depthOutlinePass.uniforms['heightFadeMin'].value = 0;
  ctx.depthOutlinePass.uniforms['heightFadeMax'].value = 75;
  ctx.depthOutlinePass.uniforms['projectionMatrixInverse'].value =
    ctx.camera.projectionMatrixInverse;
  ctx.depthOutlinePass.uniforms['viewMatrixInverse'].value = ctx.camera.matrixWorld;
  ctx.depthOutlinePass.enabled = true;
  ctx.composer.addPass(ctx.depthOutlinePass);

  // Bloom
  ctx.bloomPass = new UnrealBloomPass(new THREE.Vector2(w, h), 0.12, 0.5, 0.02);
  ctx.composer.addPass(ctx.bloomPass);

  // LUT
  ctx.lutPass = new LUTPass();
  ctx.lutPass.intensity = 1.0;
  ctx.lutPass.enabled = false;
  ctx.composer.addPass(ctx.lutPass);
  new LUTCubeLoader().loadAsync('/assets/luts/Lut_v05.lut.CUBE').then((result: any) => {
    if (!ctx.lutPass) return;
    ctx.lutPass.lut = result.texture3D;
    ctx.lutPass.enabled = true;
  });

  // Vignette
  ctx.vignettePass = new ShaderPass(VignetteColorShader);
  ctx.vignettePass.uniforms['offset'].value = 0.5;
  ctx.vignettePass.uniforms['darkness'].value = 1.5;
  // uColor defaults to black — override via ctx.vignettePass.uniforms['uColor'].value
  ctx.composer.addPass(ctx.vignettePass);

  // FXAA
  ctx.fxaaPass = new ShaderPass(FXAAShader);
  ctx.fxaaPass.uniforms['resolution'].value.set(
    1 / (w * ctx.renderer.getPixelRatio()),
    1 / (h * ctx.renderer.getPixelRatio()),
  );
  ctx.composer.addPass(ctx.fxaaPass);
}
