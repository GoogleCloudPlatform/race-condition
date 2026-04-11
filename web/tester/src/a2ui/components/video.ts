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
 * A2UI Video Component - v0.8.0
 */

import { resolveValue } from "..";

export function VideoRenderer(props: { url: any; autoplay?: boolean }) {
  const url = resolveValue(props.url);
  const el = document.createElement("div");
  el.className = "rounded-3xl overflow-hidden border border-slate-800 bg-black aspect-video relative group shadow-2xl";
  
  el.innerHTML = `
    <video class="w-full h-full object-cover" controls src="${url}" ${props.autoplay ? "autoplay" : ""}></video>
    <div class="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/80 to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity">
        <span class="text-[10px] font-bold text-white uppercase tracking-widest bg-indigo-600 px-2 py-0.5 rounded-lg shadow-lg">Native Stream</span>
    </div>
  `;

  return el;
}
