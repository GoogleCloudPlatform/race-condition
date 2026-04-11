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

import { describe, it, expect, vi, beforeEach } from "vitest";

// Import the functions we'll export from main.js
import {
  createCard,
  createCategorySection,
  createManagementSection,
  getServiceBaseUrl,
} from "../main.js";

describe("getServiceBaseUrl", () => {
  beforeEach(() => {
    globalThis.window = globalThis.window || {};
    delete globalThis.window.ENV;
  });

  it("returns localhost URL when no ENV override", () => {
    const url = getServiceBaseUrl("gateway", 8101);
    expect(url).toBe("http://localhost:8101");
  });

  it("uses ENV override when available", () => {
    window.ENV = { GATEWAY_URL: "https://custom.example.com" };
    const url = getServiceBaseUrl("gateway", 8101);
    expect(url).toBe("https://custom.example.com");
  });
});

describe("createCard", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    globalThis.window.ENV = undefined;
  });

  it("creates a clickable card for browseable services", () => {
    const service = {
      id: "gateway",
      name: "Gateway",
      url: "http://localhost:8101",
      description: "Primary API entry point.",
      browseable: true,
    };

    const card = createCard(service);

    expect(card.tagName).toBe("A");
    expect(card.href).toContain("http://localhost:8101");
    expect(card.target).toBe("_blank");
    expect(card.classList.contains("service-card")).toBe(true);
    expect(card.classList.contains("card-static")).toBe(false);
    expect(card.querySelector("h3").textContent).toBe("Gateway");
    expect(card.querySelector(".indicator")).toBeTruthy();
  });

  it("creates a non-clickable card for non-browseable services", () => {
    const service = {
      id: "redis",
      name: "Redis",
      url: "n/a",
      description: "Session state store.",
      browseable: false,
    };

    const card = createCard(service);

    expect(card.tagName).toBe("DIV");
    expect(card.href).toBeUndefined();
    expect(card.classList.contains("service-card")).toBe(true);
    expect(card.classList.contains("card-static")).toBe(true);
    expect(card.querySelector("h3").textContent).toBe("Redis");
  });

  it("shows URL for browseable services", () => {
    const service = {
      id: "gateway",
      name: "Gateway",
      url: "http://localhost:8101",
      description: "API entry point.",
      browseable: true,
    };
    const card = createCard(service);
    expect(card.querySelector(".url")).toBeTruthy();
  });

  it("hides URL for non-browseable services", () => {
    const service = {
      id: "redis",
      name: "Redis",
      url: "n/a",
      description: "Session state store.",
      browseable: false,
    };
    const card = createCard(service);
    expect(card.querySelector(".url")).toBeFalsy();
  });

  it("shows AE badge for ae type services", () => {
    const service = {
      id: "simulator",
      name: "Simulator",
      url: "https://ae.example.com",
      description: "AE-hosted agent.",
      browseable: false,
      type: "ae",
    };
    const card = createCard(service);
    expect(card.querySelector(".ae-badge")).toBeTruthy();
    expect(card.querySelector(".ae-badge").textContent).toBe("AE");
  });

  it("does not show AE badge for non-ae type services", () => {
    const service = {
      id: "runner_autopilot",
      name: "Runner Autopilot",
      url: "http://localhost:8210",
      description: "Local agent.",
      browseable: false,
      type: "python",
    };
    const card = createCard(service);
    expect(card.querySelector(".ae-badge")).toBeFalsy();
  });
});

describe("createCategorySection", () => {
  it("creates a section with icon and name", () => {
    const category = { id: "core", name: "Core Infrastructure", icon: "🏗️" };
    const section = createCategorySection(category);

    expect(section.id).toBe("section-core");
    expect(section.querySelector(".category-header").textContent).toContain(
      "Core Infrastructure",
    );
  });
});

describe("createManagementSection", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("creates a section with the management-section class", () => {
    const section = createManagementSection();
    expect(section.tagName).toBe("SECTION");
    expect(section.classList.contains("management-section")).toBe(true);
  });

  it("has an Environment Management title", () => {
    const section = createManagementSection();
    const title = section.querySelector(".management-title");
    expect(title).toBeTruthy();
    expect(title.textContent).toContain("Environment Management");
  });

  it("has three checkboxes all checked by default", () => {
    const section = createManagementSection();
    const checkboxes = section.querySelectorAll('input[type="checkbox"]');
    expect(checkboxes).toHaveLength(3);
    for (const cb of checkboxes) {
      expect(cb.checked).toBe(true);
    }
  });

  it("has checkboxes for sessions, queues, and maps", () => {
    const section = createManagementSection();
    expect(section.querySelector('#reset-target-sessions')).toBeTruthy();
    expect(section.querySelector('#reset-target-queues')).toBeTruthy();
    expect(section.querySelector('#reset-target-maps')).toBeTruthy();
  });

  it("has a Reset Environment button", () => {
    const section = createManagementSection();
    const button = section.querySelector("#reset-environment-btn");
    expect(button).toBeTruthy();
    expect(button.textContent).toContain("Reset Environment");
  });

  it("has a status display area", () => {
    const section = createManagementSection();
    const status = section.querySelector("#reset-status");
    expect(status).toBeTruthy();
  });

  it("sends reset request when button is clicked", async () => {
    const section = createManagementSection();
    document.body.appendChild(section);

    const mockResponse = {
      status: "reset",
      results: {
        sessions: { flushed: true, count: 42 },
        queues: { flushed: true, count: 3 },
        maps: { flushed: true, count: 15 },
      },
    };

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    });

    const button = section.querySelector("#reset-environment-btn");
    button.click();

    // Wait for the async handler to complete
    await vi.waitFor(() => {
      const status = section.querySelector("#reset-status");
      expect(status.textContent).toContain("Reset complete");
      expect(status.textContent).toContain("42 session(s)");
      expect(status.textContent).toContain("3 queue(s)");
      expect(status.textContent).toContain("15 map(s)");
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/environment/reset"),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targets: ["sessions", "queues", "maps"],
        }),
      }),
    );
  });

  it("handles errors gracefully", async () => {
    const section = createManagementSection();
    document.body.appendChild(section);

    globalThis.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    const button = section.querySelector("#reset-environment-btn");
    button.click();

    await vi.waitFor(() => {
      const status = section.querySelector("#reset-status");
      expect(status.textContent).toContain("Network error");
    });
  });

  it("sends only selected targets", async () => {
    const section = createManagementSection();
    document.body.appendChild(section);

    // Uncheck queues
    const queuesCheckbox = section.querySelector('#reset-target-queues');
    queuesCheckbox.checked = false;

    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        status: "reset",
        results: {
          sessions: { flushed: true, count: 5 },
          queues: { flushed: false, count: 0 },
          maps: { flushed: true, count: 3 },
        },
      }),
    });

    const button = section.querySelector("#reset-environment-btn");
    button.click();

    await vi.waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalled();
    });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/environment/reset"),
      expect.objectContaining({
        body: JSON.stringify({
          targets: ["sessions", "maps"],
        }),
      }),
    );
  });
});
