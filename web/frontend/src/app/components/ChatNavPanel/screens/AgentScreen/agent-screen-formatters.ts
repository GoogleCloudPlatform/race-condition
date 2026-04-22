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

/** Backend velocity is normalized: real mph = velocity × SPEED_SCALE (6.2137). */
const PACE_SPEED_SCALE = 6.2137;

export function formatPaceFromNormalizedAvgVelocity(avgVelocity: number): string {
  if (!avgVelocity || avgVelocity <= 0) return '0:00';
  const totalMinutes = 60 / (avgVelocity * PACE_SPEED_SCALE);
  const mins = Math.floor(totalMinutes);
  const secs = Math.round((totalMinutes % 1) * 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
