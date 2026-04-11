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
 * A2UI MultipleChoice Component - v0.8.0
 */

import { resolveValue } from "..";

export function MultipleChoiceRenderer(props: { options: any[]; selections: any; maxAllowedSelections?: number }) {
  const el = document.createElement("div");
  el.className = "flex flex-col gap-2 w-full";
  
  const selections = resolveValue(props.selections) || [];
  const options = props.options || [];

  options.forEach((opt: any) => {
    const label = resolveValue(opt.label);
    const value = opt.value;
    const isSelected = selections.includes(value);

    const btn = document.createElement("button");
    btn.className = `flex items-center gap-3 px-4 py-3 rounded-2xl border transition-all text-xs font-bold ${
      isSelected 
        ? "bg-indigo-600/20 border-indigo-500 text-indigo-400" 
        : "bg-slate-900 border-slate-800 text-slate-400 hover:border-slate-700 hover:bg-slate-800"
    }`;
    
    btn.innerHTML = `
      <span class="material-icons text-sm">${isSelected ? 'check_circle' : 'circle'}</span>
      <span>${label}</span>
    `;
    
    el.appendChild(btn);
  });

  return el;
}
