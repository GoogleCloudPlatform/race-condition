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

// Fallback data used when /api/v1/services is unreachable.
const FALLBACK_CATEGORIES = [
  { id: "admin", name: "Admin & System", icon: "⚙️" },
  { id: "core", name: "Core Infrastructure", icon: "🏗️" },
  { id: "agent", name: "AI Agents", icon: "🤖" },
  { id: "ui", name: "Developer UIs", icon: "🖥️" },
  { id: "reaction", name: "Reaction System", icon: "⚡" },
  { id: "frontend", name: "Frontend", icon: "🌐" },
];

const FALLBACK_SERVICES = [
  {
    id: "admin",
    name: "Admin Dash",
    category: "admin",
    description: "Centralized health monitoring and service portal.",
    url: "",
    healthPath: "/health",
    browseable: true,
    type: "go",
  },
  {
    id: "gateway",
    name: "Gateway",
    category: "core",
    description: "Primary API entry point and session router.",
    url: "",
    healthPath: "/health",
    browseable: true,
    type: "go",
  },
  {
    id: "redis",
    name: "Redis",
    category: "core",
    description: "Session state & orchestration store.",
    url: "n/a",
    healthPath: "/",
    browseable: false,
    type: "infra",
  },
  {
    id: "pubsub",
    name: "PubSub",
    category: "core",
    description: "Global telemetry bus emulator.",
    url: "n/a",
    healthPath: "/",
    browseable: false,
    type: "infra",
  },
  {
    id: "alloydb",
    name: "AlloyDB",
    category: "core",
    description: "Durable session state store (PostgreSQL-compatible).",
    url: "n/a",
    healthPath: "/",
    browseable: false,
    type: "infra",
  },
];

export function getServiceBaseUrl(serviceId, port) {
  const envKey = `${serviceId.toUpperCase().replace("-", "_")}_URL`;
  if (window.ENV && window.ENV[envKey]) {
    return window.ENV[envKey];
  }
  return `http://${window.location.hostname}:${port}`;
}

export function createCategorySection(category) {
  const section = document.createElement("section");
  section.className = "category-section";
  section.id = `section-${category.id}`;

  const icon = category.icon || "";
  section.innerHTML = `
    <div class="category-header">
      <span>${icon} ${category.name}</span>
    </div>
    <div class="grid" id="grid-${category.id}"></div>
  `;

  return section;
}

export function createCard(service) {
  const isBrowseable = service.browseable;
  const tag = isBrowseable ? "a" : "div";
  const card = document.createElement(tag);

  card.className = `service-card${isBrowseable ? "" : " card-static"}`;
  card.id = `card-${service.id}`;

  if (isBrowseable) {
    card.href = `${service.url}/`;
    card.target = "_blank";
  }

  const urlDisplay = service.url.replace("http://", "").replace("https://", "");
  const urlBlock = isBrowseable ? `<span class="url">${urlDisplay}</span>` : "";
  const aeBadge =
    service.type === "ae" ? `<span class="ae-badge">AE</span>` : "";

  card.innerHTML = `
    <div class="card-header">
      <h3>${service.name}${aeBadge}</h3>
      <div class="indicator ind-unknown" id="ind-${service.id}"></div>
    </div>
    <div class="card-body">
      <p class="description">${service.description}</p>
      ${urlBlock}
    </div>
  `;

  return card;
}

const RESET_TARGETS = [
  { id: "sessions", label: "Sessions" },
  { id: "queues", label: "Spawn Queues" },
  { id: "maps", label: "Session Maps" },
];

export function createManagementSection() {
  const section = document.createElement("section");
  section.className = "management-section";

  const title = document.createElement("div");
  title.className = "management-title";
  title.textContent = "⚙️ Environment Management";
  section.appendChild(title);

  const panel = document.createElement("div");
  panel.className = "management-panel";

  const controlsGroup = document.createElement("div");
  controlsGroup.className = "management-controls";

  const checkboxGroup = document.createElement("div");
  checkboxGroup.className = "checkbox-group";
  for (const target of RESET_TARGETS) {
    const label = document.createElement("label");
    label.className = "reset-target-label";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = `reset-target-${target.id}`;
    checkbox.checked = true;

    const span = document.createElement("span");
    span.textContent = target.label;

    label.appendChild(checkbox);
    label.appendChild(span);
    checkboxGroup.appendChild(label);
  }
  controlsGroup.appendChild(checkboxGroup);

  const button = document.createElement("button");
  button.id = "reset-environment-btn";
  button.className = "reset-btn";
  button.textContent = "Reset Environment";
  controlsGroup.appendChild(button);

  panel.appendChild(controlsGroup);

  const status = document.createElement("div");
  status.id = "reset-status";
  status.className = "reset-status";
  panel.appendChild(status);

  section.appendChild(panel);

  button.addEventListener("click", async () => {
    const targets = RESET_TARGETS
      .filter((t) => {
        const cb = section.querySelector(`#reset-target-${t.id}`);
        return cb && cb.checked;
      })
      .map((t) => t.id);

    if (targets.length === 0) {
      status.textContent = "Select at least one target to reset.";
      status.className = "reset-status reset-status-error";
      return;
    }

    button.disabled = true;
    button.textContent = "Resetting...";
    status.textContent = "";
    status.className = "reset-status";

    try {
      const gatewayUrl = getServiceBaseUrl("gateway", 8101);
      const resp = await fetch(`${gatewayUrl}/api/v1/environment/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets }),
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
      }

      const data = await resp.json();
      const results = data.results || {};
      const parts = [];
      if (results.sessions?.flushed) parts.push(`${results.sessions.count} session(s)`);
      if (results.queues?.flushed) parts.push(`${results.queues.count} queue(s)`);
      if (results.maps?.flushed) parts.push(`${results.maps.count} map(s)`);

      status.textContent = `Reset complete: ${parts.join(", ") || "nothing selected"}`;
      status.className = "reset-status reset-status-success";
    } catch (err) {
      status.textContent = `Reset failed: ${err.message}`;
      status.className = "reset-status reset-status-error";
    } finally {
      button.disabled = false;
      button.textContent = "Reset Environment";
    }
  });

  return section;
}

// Cache for server-side health check results
let lastServiceHealth = {};

async function fetchServiceHealth() {
  try {
    const resp = await fetch("/api/v1/health/services");
    if (!resp.ok) return {};
    return await resp.json();
  } catch {
    return {};
  }
}

async function checkHealth(service) {
  // External services are not health-checked
  if (service.type === "external") return false;

  // Infra services proxy health through the admin backend
  if (service.id === "redis" || service.id === "pubsub" || service.id === "alloydb") {
    try {
      const resp = await fetch("/api/v1/health/infra");
      if (!resp.ok) return false;
      const data = await resp.json();
      return data[service.id] === "online";
    } catch {
      return false;
    }
  }

  // All other services use the server-side health proxy
  return lastServiceHealth[service.id] === "online";
}

async function fetchServiceRegistry() {
  try {
    const resp = await fetch("/api/v1/services");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (e) {
    console.warn("Failed to fetch service registry, using fallback:", e);
    return {
      categories: FALLBACK_CATEGORIES,
      services: FALLBACK_SERVICES,
    };
  }
}

let currentCategories = [];
let currentServices = [];

async function initDashboard() {
  const registry = await fetchServiceRegistry();
  currentCategories = registry.categories;
  currentServices = registry.services;
  await updateDashboard();

  // Insert management section after categories, before footer
  const container = document.getElementById("categories-container");
  if (container && !document.getElementById("reset-environment-btn")) {
    const mgmtSection = createManagementSection();
    container.parentNode.insertBefore(mgmtSection, container.nextSibling);
  }

  setInterval(refreshHealth, 5000);
}

async function updateDashboard() {
  const container = document.getElementById("categories-container");
  if (!container) return;

  container.innerHTML = "";

  for (const cat of currentCategories) {
    const catServices = currentServices.filter((s) => s.category === cat.id);
    if (catServices.length === 0) continue;

    const section = createCategorySection(cat);
    container.appendChild(section);

    const grid = section.querySelector(".grid");
    for (const service of catServices) {
      const card = createCard(service);
      grid.appendChild(card);
    }
  }

  await refreshHealth();
}

async function refreshHealth() {
  // Fetch all service health status from server-side proxy (single request)
  lastServiceHealth = await fetchServiceHealth();
  const globalStatus = document.getElementById("global-status");
  const lastUpdate = document.getElementById("last-update");

  const monitorable = currentServices.filter((s) => s.type !== "external");

  // Parallel health checks
  const results = await Promise.allSettled(
    monitorable.map(async (service) => {
      const isHealthy = await checkHealth(service);
      return { service, isHealthy };
    }),
  );

  let healthyCount = 0;
  for (const result of results) {
    if (result.status !== "fulfilled") continue;
    const { service, isHealthy } = result.value;
    const indicator = document.getElementById(`ind-${service.id}`);
    if (indicator) {
      indicator.className = `indicator ${isHealthy ? "ind-healthy" : "ind-unhealthy"}`;
    }
    if (isHealthy) healthyCount++;
  }

  if (globalStatus) {
    globalStatus.textContent = `System Pulse: ${healthyCount}/${monitorable.length} Core Services Online`;
    globalStatus.className = `status-badge ${healthyCount === monitorable.length ? "status-healthy" : "status-unhealthy"}`;
  }

  if (lastUpdate) {
    const now = new Date();
    lastUpdate.textContent = `Last Check: ${now.toLocaleTimeString()}`;
  }
}

// Auto-initialize when running in browser (not in test)
if (
  typeof document !== "undefined" &&
  document.getElementById("categories-container")
) {
  initDashboard();
}
