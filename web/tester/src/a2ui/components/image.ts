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

/**
 * A2UI Image Component - v0.8.0
 */

import { resolveValue } from "..";

export function ImageRenderer(props: { url: any; fit?: string; usageHint?: string }) {
  const url = resolveValue(props.url);
  const el = document.createElement("div");
  
  // Custom scaling for hints
  const hintClasses: Record<string, string> = {
      'avatar': 'w-12 h-12 rounded-full',
      'smallFeature': 'w-24 h-24 rounded-2xl',
      'hero': 'w-full aspect-video rounded-3xl'
  };
  
  const scalingClass = (props.usageHint && hintClasses[props.usageHint as keyof typeof hintClasses]) || 'w-full aspect-square rounded-2xl';
  
  el.className = `overflow-hidden border border-slate-800 bg-slate-900 ${scalingClass}`;
  el.innerHTML = `<img class="w-full h-full object-${props.fit || 'cover'}" src="${url}" />`;

  return el;
}
