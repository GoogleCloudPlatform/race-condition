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
 * A2UI Core - v0.8.0 Strict Specification Rendering Engine
 */

import { VideoRenderer } from "./components/video";
import { MultipleChoiceRenderer } from "./components/multipleChoice";
import { ImageRenderer } from "./components/image";
import { MessageBoxRenderer } from "./components/messageBox";
import { NotificationRenderer } from "./components/notification";

/**
 * Resolves a property value from a structured A2UI v0.8.0 property object.
 */
export function resolveValue(value: any): any {
  if (value && typeof value === 'object') {
    if ('literalString' in value) return value.literalString;
    if ('literalNumber' in value) return value.literalNumber;
    if ('literalBoolean' in value) return value.literalBoolean;
    if ('literalArray' in value) return value.literalArray;
    if ('path' in value) return `[${value.path}]`; // Binding syntax
  }
  return value;
}

export interface RenderingContext {
  components: Record<string, any>;
  color?: string;
  sessionId?: string;
  onAction?: (action: { name: string; [key: string]: any }) => void;
}

export type Renderer = (props: any, context: RenderingContext) => HTMLElement;

// Layout Renderers
const LayoutRenderer = (type: string) => (props: any, context: RenderingContext) => {
  const el = document.createElement("div");
  el.className = `a2ui-${type.toLowerCase()} flex gap-3`;
  
  if (type === 'Column') el.style.flexDirection = 'column';
  if (type === 'Row') el.style.flexDirection = 'row';
  if (type === 'Card') {
    el.className = "a2ui-card p-6 bg-slate-900/50 border border-slate-800 rounded-3xl backdrop-blur-xl shadow-2xl transition-all hover:border-indigo-500/30";
  }
  
  // Alignment & Distribution
  if (props.distribution) el.style.justifyContent = props.distribution;
  if (props.alignment) el.style.alignItems = props.alignment;

  // Resolve children by ID
  const childrenIds = props.children?.explicitList || (props.child ? [props.child] : []);
  childrenIds.forEach((id: string) => {
    const componentData = context.components[id];
    if (componentData) {
        el.appendChild(renderA2UI(componentData, context));
    } else {
        const err = document.createElement("div");
        err.className = "text-[8px] text-red-500 italic";
        err.textContent = `[Missing Component ID: ${id}]`;
        el.appendChild(err);
    }
  });
  
  return el;
};

const REGISTRY: Record<string, Renderer> = {
  // --- Layout ---
  "Column": LayoutRenderer("Column"),
  "Row": LayoutRenderer("Row"),
  "Card": LayoutRenderer("Card"),
  "List": (props, context) => {
      const el = LayoutRenderer("List")(props, context);
      el.classList.add('overflow-y-auto', 'max-h-96', 'custom-scrollbar');
      if (props.direction === 'horizontal') el.classList.remove('flex-col');
      return el;
  },
  "Tabs": (props, context) => {
      const el = document.createElement("div");
      el.className = "flex flex-col gap-4 w-full";
      
      const tabList = document.createElement("div");
      tabList.className = "flex gap-2 p-1 bg-slate-900/80 border border-slate-800 rounded-2xl self-start";
      
      const contentArea = document.createElement("div");
      contentArea.className = "min-h-[100px] transition-all duration-300";

      const items = props.tabItems || [];
      items.forEach((tab: any, idx: number) => {
          const btn = document.createElement("button");
          btn.className = idx === 0 
            ? "px-4 py-1.5 bg-indigo-600 text-white text-[10px] font-black rounded-xl shadow-lg"
            : "px-4 py-1.5 text-slate-500 text-[10px] font-bold hover:text-slate-300 transition-all";
          btn.textContent = resolveValue(tab.title);
          
          btn.onclick = () => {
              tabList.querySelectorAll('button').forEach(b => {
                  b.className = "px-4 py-1.5 text-slate-500 text-[10px] font-bold hover:text-slate-300 transition-all";
              });
              btn.className = "px-4 py-1.5 bg-indigo-600 text-white text-[10px] font-black rounded-xl shadow-lg";
              
              contentArea.innerHTML = "";
              const childData = context.components[tab.child];
              if (childData) contentArea.appendChild(renderA2UI(childData, context));
          };
          
          tabList.appendChild(btn);
          if (idx === 0 && tab.child) {
              const childData = context.components[tab.child];
              if (childData) contentArea.appendChild(renderA2UI(childData, context));
          }
      });
      
      el.appendChild(tabList);
      el.appendChild(contentArea);
      return el;
  },
  "Modal": (props, context) => {
      const overlay = document.createElement("div");
      overlay.className = "fixed inset-0 z-50 flex items-center justify-center p-8 bg-slate-950/80 backdrop-blur-md animate-in fade-in duration-300";
      
      const content = document.createElement("div");
      content.className = "w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-300";
      
      const header = document.createElement("div");
      header.className = "px-8 py-4 border-b border-slate-800 flex justify-between items-center bg-slate-900/50";
      header.innerHTML = `
        <h3 class="text-xs font-black text-white uppercase tracking-widest">Modal Update</h3>
        <button class="p-1.5 hover:bg-slate-800 rounded-lg transition-all text-slate-500 hover:text-white">
            <span class="material-icons text-sm">close</span>
        </button>
      `;
      
      const body = document.createElement("div");
      body.className = "p-8";
      
      if (props.contentChild) {
          const childData = context.components[props.contentChild];
          if (childData) body.appendChild(renderA2UI(childData, context));
      }
      
      header.querySelector('button')!.onclick = () => overlay.remove();
      
      content.appendChild(header);
      content.appendChild(body);
      overlay.appendChild(content);

      // Wrapper to handle entryPointChild
      const entryWrapper = document.createElement("div");
      entryWrapper.className = "inline-block";
      if (props.entryPointChild) {
          const entryData = context.components[props.entryPointChild];
          if (entryData) {
              const entryEl = renderA2UI(entryData, context);
              entryEl.onclick = (e) => {
                  e.preventDefault();
                  document.body.appendChild(overlay);
              };
              entryWrapper.appendChild(entryEl);
          }
      }
      
      return entryWrapper;
  },
  "Divider": (props) => {
    const hr = document.createElement("hr");
    hr.className = `border-0 border-t border-slate-800 my-4 ${props.axis === 'vertical' ? 'h-full border-l border-t-0' : 'w-full'}`;
    return hr;
  },

  // --- Display ---
  "Text": (props) => {
    const el = document.createElement("span");
    const hintClasses: Record<string, string> = {
      h1: "text-2xl font-black text-white",
      h2: "text-xl font-bold text-white",
      h3: "text-lg font-bold text-slate-200",
      h4: "text-base font-semibold text-slate-300",
      h5: "text-sm font-semibold text-slate-400",
      body: "text-sm text-slate-400 leading-relaxed",
      caption: "text-[10px] text-slate-500 uppercase tracking-widest font-bold"
    };
    el.className = hintClasses[props.usageHint] || hintClasses.body;
    el.textContent = resolveValue(props.text) || "";
    return el;
  },
  "Image": ImageRenderer,
  "Icon": (props) => {
    const el = document.createElement("span");
    el.className = "material-icons text-slate-400 text-lg hover:text-indigo-400 transition-colors cursor-default";
    el.textContent = resolveValue(props.name) || "help_outline";
    return el;
  },
  "Video": VideoRenderer,
  "AudioPlayer": (props) => {
      const el = document.createElement("div");
      el.className = "flex items-center gap-4 p-4 bg-slate-900/50 border border-slate-800 rounded-2xl w-full";
      el.innerHTML = `
        <button class="w-10 h-10 rounded-full bg-indigo-600 flex items-center justify-center text-white shadow-lg active:scale-90 transition-all">
            <span class="material-icons">play_arrow</span>
        </button>
        <div class="flex-1 min-w-0">
            <div class="h-1 bg-slate-800 rounded-full w-full mb-1">
                <div class="h-full bg-indigo-500 w-1/3"></div>
            </div>
            <div class="text-[8px] font-black text-slate-500 uppercase tracking-tighter truncate">${resolveValue(props.description) || 'Audio Stream'}</div>
        </div>
      `;
      return el;
  },

  // --- Input ---
  "Button": (props, context) => {
    const btn = document.createElement("button");
    btn.className = props.primary 
      ? "px-4 py-2 bg-indigo-600 text-white text-xs font-bold rounded-xl hover:bg-indigo-500 transition-all shadow-lg shadow-indigo-500/20 active:scale-95"
      : "px-4 py-2 bg-slate-800 text-slate-300 text-xs font-bold rounded-xl hover:bg-slate-700 transition-all active:scale-95";
    
    if (props.child) {
      const childData = context.components[props.child];
      if (childData) {
          btn.appendChild(renderA2UI(childData, context));
      } else {
          btn.textContent = props.child;
      }
    }

    // Wire up action handling
    if (props.action && context.onAction) {
      const actionName = resolveValue(props.action?.name) || props.action?.name;
      btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.classList.add("opacity-50", "cursor-not-allowed");
        context.onAction!({ name: actionName });
      });
      btn.classList.add("cursor-pointer");
    }

    return btn;
  },
  "TextField": (props) => {
      const el = document.createElement("div");
      el.className = "flex flex-col gap-1.5 w-full";
      el.innerHTML = `
        <label class="text-[9px] font-black text-slate-500 uppercase tracking-widest px-1">${resolveValue(props.label) || 'Input'}</label>
        <input type="${props.textFieldType === 'number' ? 'number' : (props.textFieldType === 'obscured' ? 'password' : (props.textFieldType === 'date' ? 'date' : 'text'))}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-all" value="${resolveValue(props.text) || ''}" />
      `;
      return el;
  },
  "MultipleChoice": MultipleChoiceRenderer,
  "CheckBox": (props) => {
      const el = document.createElement("label");
      el.className = "flex items-center gap-3 p-3 bg-slate-900/30 border border-slate-800 rounded-xl cursor-pointer hover:bg-slate-800/50 transition-all group";
      const checked = resolveValue(props.value);
      el.innerHTML = `
        <div class="w-5 h-5 rounded-md border-2 ${checked ? 'bg-indigo-600 border-indigo-600' : 'border-slate-700'} flex items-center justify-center transition-all group-hover:border-indigo-500/50">
            ${checked ? '<span class="material-icons text-white text-xs font-black">check</span>' : ''}
        </div>
        <span class="text-xs font-bold text-slate-300 group-hover:text-white transition-colors">${resolveValue(props.label) || ''}</span>
      `;
      return el;
  },
  "Slider": (props) => {
     const val = resolveValue(props.value) || 0;
     const el = document.createElement("div");
     el.className = "flex flex-col gap-1.5 w-full";
     el.innerHTML = `
        <div class="flex justify-between text-[8px] text-slate-500 font-bold uppercase tracking-widest px-1">
            <span>Range</span>
            <span class="text-indigo-400">${val}%</span>
        </div>
        <div class="h-2 w-full bg-slate-950 border border-slate-900 rounded-full overflow-hidden p-0.5">
            <div class="h-full bg-indigo-500 rounded-full transition-all duration-700 shadow-[0_0_10px_rgba(99,102,241,0.5)]" style="width: ${val}%"></div>
        </div>
     `;
     return el;
  },
  "DateTimeInput": (props) => {
      const el = document.createElement("div");
      el.className = "flex flex-col gap-1.5 w-full";
      let displayType = "datetime-local";
      if (props.enableDate && !props.enableTime) displayType = "date";
      if (!props.enableDate && props.enableTime) displayType = "time";
      
      el.innerHTML = `
        <label class="text-[9px] font-black text-slate-500 uppercase tracking-widest px-1">Schedule</label>
        <input type="${displayType}" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-slate-200 outline-none focus:border-indigo-500 transition-all font-mono" value="${resolveValue(props.value) || ''}" />
      `;
      return el;
  },

  // --- Internal/Aggregators ---
  "Notification": NotificationRenderer,
  "MessageBox": MessageBoxRenderer,
};

export function registerComponent(type: string, renderer: Renderer) {
  REGISTRY[type] = renderer;
}

/**
 * The main rendering entry point. Handles strict v0.8.0 wrappers and Surface updates.
 */
export function renderA2UI(part: any, context?: RenderingContext): HTMLElement {
  if (!part) return createError('Null or undefined A2UI part', {});

  // 1. Handle Spec-Mandated System Messages (v0.8.0)
  if (part.beginRendering) {
    const el = document.createElement("div");
    el.className = "a2ui-system-msg p-4 bg-indigo-500/10 border border-indigo-500/20 rounded-xl flex items-center gap-3 w-full my-2";
    el.setAttribute("data-a2ui-type", "beginRendering");
    el.innerHTML = `
      <span class="material-icons text-indigo-400">play_circle</span>
      <div class="flex flex-col">
        <span class="text-[10px] font-black text-indigo-300 uppercase tracking-widest">Initializing Surface</span>
        <span class="text-[9px] text-indigo-400/70 font-mono">ROOT: ${part.beginRendering.root}</span>
      </div>
    `;
    return el;
  }

  if (part.dataModelUpdate) {
    const el = document.createElement("div");
    el.className = "a2ui-system-msg p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl flex items-center gap-3 w-full my-2";
    el.setAttribute("data-a2ui-type", "dataModelUpdate");
    el.innerHTML = `
      <span class="material-icons text-emerald-400">storage</span>
      <div class="flex flex-col">
        <span class="text-[10px] font-black text-emerald-300 uppercase tracking-widest">Data Model Update</span>
        <span class="text-[9px] text-emerald-400/70 font-mono">PATH: ${part.dataModelUpdate.path}</span>
      </div>
    `;
    return el;
  }

  // 2. Handle Surface Updates (Message level)
  if (part.surfaceUpdate) {
    const componentsList = part.surfaceUpdate.components || [];
    const compsMap: Record<string, any> = context?.components || {};
    
    if (Array.isArray(componentsList)) {
        componentsList.forEach((c: any) => compsMap[c.id] = c);
    } else if (typeof componentsList === 'object') {
        Object.assign(compsMap, componentsList);
    }
    
    const root = componentsList.length > 0 ? componentsList[componentsList.length - 1] : part;
    return renderA2UI(root, { components: compsMap });
  }

  // Handle a part that HAS a components map itself
  if (part.components && !context) {
      const compsMap: Record<string, any> = {};
      if (Array.isArray(part.components)) {
          part.components.forEach((c: any) => compsMap[c.id] = c);
      } else {
          Object.assign(compsMap, part.components);
      }
      return renderA2UI({ ...part, components: undefined }, { components: compsMap });
  }

  // 2. Handle Component Wrappers {"id": "...", "component": {"Type": {...}}}
  let context_to_use = context || { components: {} };

  if (part.id && part.component) {
      const types = Object.keys(part.component);
      if (types.length === 1) {
          const type = types[0];
          const renderer = REGISTRY[type];
          if (renderer) {
              const element = renderer(part.component[type], context_to_use);
              element.setAttribute('data-a2ui-type', type);
              element.setAttribute('data-a2ui-id', part.id);
              if (!element.className.includes('a2ui-')) {
                  element.classList.add('a2ui-component');
              }
              return element;
          } else {
              return createError(`Unknown primitive: ${type}`, part);
          }
      }
  }

  return createError('Invalid or Non-Compliant structure', part);
}

function createError(msg: string, part: any): HTMLElement {
  const error = document.createElement("div");
  error.className = "p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-500 text-[10px] font-mono a2ui-error";
  error.textContent = `[A2UI] ${msg}: ${JSON.stringify(part).substring(0, 50)}...`;
  return error;
}
