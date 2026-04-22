/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */

import type { ChatMessage } from '../../../../gateway.service';

export interface RouteCard {
  id: string;
  name: string;
  distance: string;
  color: string;
  imageDataUrl: string;
  coords: [number, number][];
}

export interface SimRunner {
  id: string;
  name: string;
  status: 'active' | 'finished' | 'did-not-finish';
  velocity: number;
  hydration: number;
  energy: number;
  percentComplete: number;
  color: string;
}

/** Race results summary shown after compile_results */
export interface RaceResults {
  totalTicks: number;
  finalStatusCounts: Record<string, number>;
  notableEvents: string[];
  samplingQuality: number;
  avgRunnersReporting: number;
}

/** Standalone tick-progress card shown while a simulation is running */
export interface TickProgressItem {
  kind: 'tick_progress';
  guid: string;
  tick: number;
  maxTicks: number;
  label: string;
  done: boolean;
}

/** Union type for display items in the chat list */
export type DisplayItem =
  | { kind: 'system'; msg: ChatMessage }
  | { kind: 'message'; msg: ChatMessage }
  | { kind: 'route'; msg: ChatMessage; card: RouteCard }
  | { kind: 'a2ui'; node: unknown }
  | { kind: 'race_results'; msg: ChatMessage; results: RaceResults }
  | { kind: 'tool_call'; msg: ChatMessage; done?: boolean; error?: boolean; warning?: boolean }
  | TickProgressItem;

export interface PathEntry {
  id: number;
  name: string;
  lengthMi: number;
  colorHex: string;
  waterStationCount: number;
}

export interface SyncPayload {
  paths: PathEntry[];
  selectedId: number | null;
}
