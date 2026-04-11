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

import { marked } from "marked";
import DOMPurify from "dompurify";
import { resolveValue } from "..";

// --- Clipboard copy helpers ---
const CLIPBOARD_SVG = `<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3"/></svg>`;
const CHECK_SVG = `<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>`;

function setupCopyButton(
  btn: Element | null,
  getText: () => string,
): void {
  if (!btn) return;
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(getText()).then(() => {
      btn.innerHTML = CHECK_SVG;
      setTimeout(() => {
        btn.innerHTML = CLIPBOARD_SVG;
      }, 1500);
    });
  });
}

const copyBtnClasses =
  "shrink-0 p-0.5 rounded text-slate-600 hover:text-indigo-400 transition-colors";

export interface MessageBoxProps {
  speaker: any;
  text: any;
  typeLabel?: any;
  color?: string;
  children?: HTMLElement[];
  rawMessage?: any;
  sessionId?: string;
  simulationId?: string;
}

export function MessageBoxRenderer(props: MessageBoxProps) {
  const speaker = resolveValue(props.speaker);
  const text = resolveValue(props.text);
  const typeLabel = resolveValue(props.typeLabel) || "MESSAGE";
  const sessionId = props.sessionId || "";
  const simulationId = props.simulationId || "";

  const el = document.createElement("div");
  // Ensure the card itself doesn't scroll and has a clean flex layout
  el.className =
    "p-6 rounded-2xl border-l-4 border-y border-r border-slate-800 bg-slate-900 flex flex-col gap-3 shadow-sm shrink-0";

  if (props.color) {
    el.style.borderLeftColor = props.color;
  } else {
    el.classList.add("border-l-indigo-500");
  }

  // Configure marked for safe, rich rendering
  const rawHtml = marked.parse(text) as string;
  const cleanHtml = DOMPurify.sanitize(rawHtml);

  el.innerHTML = `
    <div class="message-header flex items-center justify-between cursor-pointer group/header select-none">
        <div class="flex flex-col">
            <div class="flex items-center gap-2">
                <span class="text-[10px] font-black text-indigo-400 uppercase tracking-[0.2em] mb-0.5">${typeLabel}</span>
                ${simulationId ? `<span class="flex items-center gap-1"><span class="px-1.5 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-[8px] font-bold text-amber-400 font-mono truncate max-w-[200px]" title="${simulationId}">SIM: ${simulationId.length > 12 ? simulationId.substring(0, 12) + "..." : simulationId}</span><button class="copy-sim-id ${copyBtnClasses} hover:!text-amber-400" title="Copy simulation ID">${CLIPBOARD_SVG}</button></span>` : ""}
            </div>
            <div class="flex items-center gap-2">
                <h3 class="text-sm font-black text-slate-100 uppercase italic transition-colors group-hover/header:text-indigo-300 line-clamp-1">${speaker}</h3>
                <svg class="message-toggle w-3 h-3 text-slate-500 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M19 9l-7 7-7-7"/></svg>
            </div>
            ${sessionId ? `<span class="flex items-center gap-1"><span class="text-[9px] font-mono text-slate-500 truncate max-w-[300px]" title="${sessionId}">${sessionId}</span><button class="copy-session-id ${copyBtnClasses}" title="Copy session ID">${CLIPBOARD_SVG}</button></span>` : ""}
        </div>
        <div class="flex items-center gap-3">
        </div>
    </div>
    <div class="message-body flex flex-col gap-3">
        <div class="h-px w-full bg-gradient-to-r from-slate-800 to-transparent my-1"></div>
        <div class="markdown-content text-[11px] leading-relaxed text-slate-300 font-medium bg-slate-950/40 p-4 rounded-xl border border-slate-800/50 break-words min-w-0">
          ${cleanHtml}
        </div>
        <div class="message-slot flex flex-col gap-4 mt-2"></div>
        ${props.rawMessage ? `
            <div class="mt-2 border-t border-slate-800/50 pt-2">
                <div class="flex items-center gap-2">
                    <button onclick="
                        const code = this.parentElement.nextElementSibling;
                        const isHidden = code.classList.contains('hidden');
                        if (isHidden) {
                            code.classList.remove('hidden');
                            this.querySelector('svg').style.transform = 'rotate(180deg)';
                        } else {
                            code.classList.add('hidden');
                            this.querySelector('svg').style.transform = 'rotate(0deg)';
                        }
                        event.stopPropagation();
                    " class="text-[9px] font-bold text-slate-500 hover:text-indigo-400 font-mono flex items-center gap-1 transition-colors z-10 relative">
                        <svg class="w-3 h-3 transition-transform duration-200" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                        RAW PROTO
                    </button>
                    <button class="copy-raw-proto ${copyBtnClasses}" title="Copy raw proto">${CLIPBOARD_SVG}</button>
                </div>
                <div class="raw-proto-content hidden mt-2 p-3 bg-slate-950 rounded-xl border border-slate-800 text-[10px] text-slate-400 break-words min-w-0 relative">
                    <pre class="m-0 bg-transparent border-none p-0 whitespace-pre-wrap break-words min-w-0"><code>${DOMPurify.sanitize(JSON.stringify(props.rawMessage, null, 2))}</code></pre>
                </div>
            </div>
        ` : ''}
    </div>
  `;

  const header = el.querySelector(".message-header") as HTMLElement;
  const body = el.querySelector(".message-body") as HTMLElement;
  const toggleIcon = el.querySelector(".message-toggle") as HTMLElement;

  let expanded = true;
  
  const updateState = () => {
    if (expanded) {
        body.style.display = "flex";
        toggleIcon.style.transform = "rotate(180deg)";
    } else {
        body.style.display = "none";
        toggleIcon.style.transform = "rotate(0deg)";
    }
  };

  header.onclick = (e) => {
    e.stopPropagation();
    expanded = !expanded;
    updateState();
  };

  // Initial state call
  updateState();

  const slot = el.querySelector(".message-slot");
  if (slot && props.children) {
    props.children.forEach(child => slot.appendChild(child));
  } else if (slot) {
    slot.remove(); 
  }

  // --- Wire up copy buttons ---
  setupCopyButton(
    el.querySelector(".copy-session-id"),
    () => sessionId,
  );
  setupCopyButton(
    el.querySelector(".copy-sim-id"),
    () => simulationId,
  );
  setupCopyButton(
    el.querySelector(".copy-raw-proto"),
    () => {
      const codeEl = el.querySelector(".raw-proto-content code");
      return codeEl?.textContent || "";
    },
  );

  return el;
}
