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

/** Loose A2UI wire payload; narrowed at call sites over time. */
export type A2uiNode = Record<string, unknown> & {
  id?: string;
  component?: Record<string, unknown>;
  surfaceUpdate?: A2uiSurfaceUpdate;
};

export interface A2uiSurfaceUpdate {
  surfaceId?: string;
  components?: A2uiComponentRecord[];
}

export interface A2uiSurfacePayload {
  components?: A2uiComponentRecord[];
}

export type A2uiComponentRecord = Record<string, unknown> & { id?: string };

export type A2uiActionPayload = Record<string, unknown> | undefined;
