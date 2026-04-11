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

import { resolveValue } from "..";

export interface NotificationProps {
  title: any;
  message: any;
  type: "info" | "warning" | "error" | "success";
}

export function NotificationRenderer(props: NotificationProps) {
  const title = resolveValue(props.title);
  const message = resolveValue(props.message);
  const el = document.createElement("div");
  
  const colors = {
    info: "indigo",
    warning: "amber",
    error: "rose",
    success: "emerald"
  };
  
  const color = colors[props.type] || "indigo";

  el.className = `p-4 rounded-xl border border-${color}-500/20 bg-${color}-500/5 backdrop-blur-md flex gap-3 shadow-lg animate-in slide-in-from-right-10 duration-500`;
  
  el.innerHTML = `
    <div class="w-1.5 h-full rounded-full bg-${color}-500 shadow-[0_0_10px_rgba(var(--${color}-500-rgb),0.5)]"></div>
    <div class="flex flex-col gap-1">
        <h4 class="text-[10px] font-black text-${color}-400 uppercase tracking-widest">${title}</h4>
        <p class="text-[11px] text-slate-300 font-medium leading-tight">${message}</p>
    </div>
  `;

  return el;
}
