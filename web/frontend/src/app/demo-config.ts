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

import cacheRoute01 from '../../cached_routes/cache-1.json';
import cacheRoute02 from '../../cached_routes/cache-2.json';
import cacheRoute03 from '../../cached_routes/cache-3.json';

export const PRECONFIGURED_ROUTES: Record<string, unknown> = {
  cachedRoute01: cacheRoute01,
  cachedRoute02: cacheRoute02,
  cachedRoute03: cacheRoute03,
};

type DemoConfigType = Record<
  string,
  {
    title: string;
    agent: string;
    placeholderRoutes?: keyof typeof PRECONFIGURED_ROUTES;
    placeholderAgentMessage?: any;
    isSecurityDemo?: boolean;
    isBuildAgentsDemo?: boolean;
    isIntentToInfrastructureDemo?: boolean;
    promptPlaceholder?: string;
    orbitCamera?: boolean;
    recordingConfig?: {
      cachedMessageStreams?: string[];
      timeScale?: number;
    };
  }
>;

export const DEMO_CONFIG: DemoConfigType = {
  Sandbox: {
    title: 'Sandbox',
    agent: 'planner_with_memory',
    placeholderRoutes: 'cachedRoute01',
    orbitCamera: false,
    placeholderAgentMessage: {
      guid: '934d9c7e-5203-4dd8-b31a-590e1bfc3f2f',
      speaker: 'planner_with_memory (934d9c)',
      emotion: '',
      isUser: false,
      timestamp: '2026-03-19T20:55:01.098Z',
      color: '#6bcb77',
      msgType: 'tool_end',
      icon: 'build',
      toolName: 'validate_and_emit_a2ui',
      text: 'a2ui',
      rawJson:
        '{"a2ui":{"surfaceUpdate":{"surfaceId":"marathon-dashboard","components":[{"id":"h1","component":{"Text":{"text":{"literalString":"Vegas Strip Marathon Plan"},"usageHint":"h3"}}},{"id":"d1","component":{"Divider":{}}},{"id":"t1","component":{"Text":{"text":{"literalString":"Theme: Neon Strip Run"},"usageHint":"body"}}},{"id":"t2","component":{"Text":{"text":{"literalString":"Date: November 17, 2024"},"usageHint":"body"}}},{"id":"t3","component":{"Text":{"text":{"literalString":"Distance: 26.2 Miles"},"usageHint":"body"}}},{"id":"t4","component":{"Text":{"text":{"literalString":"Participants: 10,000 Runners"},"usageHint":"body"}}},{"id":"t5","component":{"Text":{"text":{"literalString":"Budget: $1.2M (Estimated)"},"usageHint":"body"}}},{"id":"d2","component":{"Divider":{}}},{"id":"h2","component":{"Text":{"text":{"literalString":"Evaluation Metrics"},"usageHint":"h3"}}},{"id":"m1","component":{"Text":{"text":{"literalString":"Plan Quality: 0.1 (Status: Needs Improvement)"},"usageHint":"body"}}},{"id":"m2","component":{"Text":{"text":{"literalString":"Distance Compliance: 1.0 (Status: Pass)"},"usageHint":"body"}}},{"id":"d3","component":{"Divider":{}}},{"id":"btn-text","component":{"Text":{"text":{"literalString":"Run Simulation"}}}},{"id":"btn1","component":{"Button":{"child":"btn-text","action":{"name":"run_simulation"},"primary":{"literalBoolean":true}}}},{"id":"col1","component":{"Column":{"children":{"explicitList":["h1","d1","t1","t2","t3","t4","t5","d2","h2","m1","m2","d3","btn1"]}}}},{"id":"card1","component":{"Card":{"child":"col1"}}}]}}}',
      result: {
        surfaceUpdate: {
          surfaceId: 'sim_results',
          components: [
            {
              id: 'tag',
              component: { Text: { text: { literalString: 'PLAN' }, usageHint: 'label' } },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: { literalString: '881f2086-acca-4ac8-a969-b477a349d866' },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: { Row: { children: { explicitList: ['tag', 'sim-meta'] } } },
            },
            {
              id: 'title',
              component: {
                Text: { text: { literalString: 'Las Vegas Neon Night Marathon' }, usageHint: 'h2' },
              },
            },
            {
              id: 'left-col',
              component: { Column: { children: { explicitList: ['tag-row', 'title'] } } },
            },
            {
              id: 'score-num',
              component: { Text: { text: { literalString: '91' }, usageHint: 'h1' } },
            },
            {
              id: 'score-lbl',
              component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
            },
            {
              id: 'score-col',
              component: { Column: { children: { explicitList: ['score-num', 'score-lbl'] } } },
            },
            {
              id: 'header',
              component: { Row: { children: { explicitList: ['left-col', 'score-col'] } } },
            },
            {
              id: 'dist-l',
              component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
            },
            {
              id: 'dist-v',
              component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
            },
            {
              id: 'dist-r',
              component: { Row: { children: { explicitList: ['dist-l', 'dist-v'] } } },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: { literalString: 'Participants (expected/simulated)' },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
            },
            {
              id: 'part-r',
              component: { Row: { children: { explicitList: ['part-l', 'part-v'] } } },
            },
            { id: 'd1', component: { Divider: {} } },
            {
              id: 'safe-l',
              component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
            },
            {
              id: 'safe-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            {
              id: 'safe-r',
              component: { Row: { children: { explicitList: ['safe-l', 'safe-v'] } } },
            },
            {
              id: 'run-l',
              component: {
                Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
              },
            },
            {
              id: 'run-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            { id: 'run-r', component: { Row: { children: { explicitList: ['run-l', 'run-v'] } } } },
            {
              id: 'city-l',
              component: {
                Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
              },
            },
            {
              id: 'city-v',
              component: { Text: { text: { literalString: '100' }, usageHint: 'body' } },
            },
            {
              id: 'city-r',
              component: { Row: { children: { explicitList: ['city-l', 'city-v'] } } },
            },
            { id: 'd2', component: { Divider: {} } },
            {
              id: 'rerun-txt',
              component: { Text: { text: { literalString: 'Run Simulation' } } },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: { name: 'run_simulation' },
                  primary: { literalBoolean: true },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['rerun-btn'],
                  },
                },
              },
            },
            {
              id: 'content',
              component: {
                Column: {
                  children: {
                    explicitList: [
                      'header',
                      'dist-r',
                      'part-r',
                      'd1',
                      'safe-r',
                      'run-r',
                      'city-r',
                      'd2',
                      'buttons-r',
                    ],
                  },
                },
              },
            },
            { id: 'card', component: { Card: { child: 'content' } } },
          ],
        },
      },
    },
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-ci-log.ndjson'],
      timeScale: 1,
    },
  },
  '1': {
    title: 'Build agents with Agent Platform',
    agent: 'planner',
    orbitCamera: true,
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
    isBuildAgentsDemo: true,
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-1-log.ndjson'],
      timeScale: 2,
    },
  },
  '2': {
    title: 'Creating multi-agent systems',
    agent: 'planner_with_eval',
    orbitCamera: false,
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-2-log.ndjson', '/assets/sim-2-run-log.ndjson'],
      timeScale: 2,
    },
  },
  '3': {
    title: 'Enhancing agents with memory',
    agent: 'planner_with_memory',
    placeholderRoutes: 'cachedRoute03',
    orbitCamera: false,
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-3-log.ndjson', '/assets/sim-3-run-log.ndjson'],
      timeScale: 6,
    },
  },
  '4': {
    title: 'Debugging at scale',
    agent: 'simulator_with_failure',
    placeholderRoutes: 'cachedRoute01',
    orbitCamera: true,

    placeholderAgentMessage: {
      guid: '934d9c7e-5203-4dd8-b31a-590e1bfc3f2f',
      speaker: 'planner_with_memory (934d9c)',
      emotion: '',
      isUser: false,
      timestamp: '2026-03-19T20:55:01.098Z',
      color: '#6bcb77',
      msgType: 'tool_end',
      icon: 'build',
      toolName: 'validate_and_emit_a2ui',
      text: 'a2ui',
      rawJson:
        '{"a2ui":{"surfaceUpdate":{"surfaceId":"marathon-dashboard","components":[{"id":"h1","component":{"Text":{"text":{"literalString":"Vegas Strip Marathon Plan"},"usageHint":"h3"}}},{"id":"d1","component":{"Divider":{}}},{"id":"t1","component":{"Text":{"text":{"literalString":"Theme: Neon Strip Run"},"usageHint":"body"}}},{"id":"t2","component":{"Text":{"text":{"literalString":"Date: November 17, 2024"},"usageHint":"body"}}},{"id":"t3","component":{"Text":{"text":{"literalString":"Distance: 26.2 Miles"},"usageHint":"body"}}},{"id":"t4","component":{"Text":{"text":{"literalString":"Participants: 10,000 Runners"},"usageHint":"body"}}},{"id":"t5","component":{"Text":{"text":{"literalString":"Budget: $1.2M (Estimated)"},"usageHint":"body"}}},{"id":"d2","component":{"Divider":{}}},{"id":"h2","component":{"Text":{"text":{"literalString":"Evaluation Metrics"},"usageHint":"h3"}}},{"id":"m1","component":{"Text":{"text":{"literalString":"Plan Quality: 0.1 (Status: Needs Improvement)"},"usageHint":"body"}}},{"id":"m2","component":{"Text":{"text":{"literalString":"Distance Compliance: 1.0 (Status: Pass)"},"usageHint":"body"}}},{"id":"d3","component":{"Divider":{}}},{"id":"btn-text","component":{"Text":{"text":{"literalString":"Run Simulation"}}}},{"id":"btn1","component":{"Button":{"child":"btn-text","action":{"name":"run_simulation"},"primary":{"literalBoolean":true}}}},{"id":"col1","component":{"Column":{"children":{"explicitList":["h1","d1","t1","t2","t3","t4","t5","d2","h2","m1","m2","d3","btn1"]}}}},{"id":"card1","component":{"Card":{"child":"col1"}}}]}}}',

      result: {
        surfaceUpdate: {
          surfaceId: 'sim_results',
          components: [
            {
              id: 'tag',
              component: { Text: { text: { literalString: 'PLAN' }, usageHint: 'label' } },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: { literalString: '881f2086-acca-4ac8-a969-b477a349d866' },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: { Row: { children: { explicitList: ['tag', 'sim-meta'] } } },
            },
            {
              id: 'title',
              component: {
                Text: { text: { literalString: 'Las Vegas Neon Night Marathon' }, usageHint: 'h2' },
              },
            },
            {
              id: 'left-col',
              component: { Column: { children: { explicitList: ['tag-row', 'title'] } } },
            },
            {
              id: 'score-num',
              component: { Text: { text: { literalString: '91' }, usageHint: 'h1' } },
            },
            {
              id: 'score-lbl',
              component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
            },
            {
              id: 'score-col',
              component: { Column: { children: { explicitList: ['score-num', 'score-lbl'] } } },
            },
            {
              id: 'header',
              component: { Row: { children: { explicitList: ['left-col', 'score-col'] } } },
            },
            {
              id: 'dist-l',
              component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
            },
            {
              id: 'dist-v',
              component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
            },
            {
              id: 'dist-r',
              component: { Row: { children: { explicitList: ['dist-l', 'dist-v'] } } },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: { literalString: 'Participants (expected/simulated)' },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
            },
            {
              id: 'part-r',
              component: { Row: { children: { explicitList: ['part-l', 'part-v'] } } },
            },
            { id: 'd1', component: { Divider: {} } },
            {
              id: 'safe-l',
              component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
            },
            {
              id: 'safe-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            {
              id: 'safe-r',
              component: { Row: { children: { explicitList: ['safe-l', 'safe-v'] } } },
            },
            {
              id: 'run-l',
              component: {
                Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
              },
            },
            {
              id: 'run-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            { id: 'run-r', component: { Row: { children: { explicitList: ['run-l', 'run-v'] } } } },
            {
              id: 'city-l',
              component: {
                Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
              },
            },
            {
              id: 'city-v',
              component: { Text: { text: { literalString: '100' }, usageHint: 'body' } },
            },
            {
              id: 'city-r',
              component: { Row: { children: { explicitList: ['city-l', 'city-v'] } } },
            },
            { id: 'd2', component: { Divider: {} } },
            {
              id: 'rerun-txt',
              component: { Text: { text: { literalString: 'Run Simulation' } } },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: { name: 'run_simulation' },
                  primary: { literalBoolean: true },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['rerun-btn'],
                  },
                },
              },
            },
            {
              id: 'content',
              component: {
                Column: {
                  children: {
                    explicitList: [
                      'header',
                      'dist-r',
                      'part-r',
                      'd1',
                      'safe-r',
                      'run-r',
                      'city-r',
                      'd2',
                      'buttons-r',
                    ],
                  },
                },
              },
            },
            { id: 'card', component: { Card: { child: 'content' } } },
          ],
        },
      },
    },
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-4-log.ndjson'],
      timeScale: 1.5,
    },
  },
  '5a': {
    title: 'Intent to infrastructure with Gemini Cloud Assist',
    isIntentToInfrastructureDemo: true,
    agent: 'simulator_with_failure',
    placeholderRoutes: 'cachedRoute01',
    orbitCamera: true,
    placeholderAgentMessage: {
      guid: '934d9c7e-5203-4dd8-b31a-590e1bfc3f2f',
      speaker: 'planner_with_memory (934d9c)',
      emotion: '',
      isUser: false,
      timestamp: '2026-03-19T20:55:01.098Z',
      color: '#6bcb77',
      msgType: 'tool_end',
      icon: 'build',
      toolName: 'validate_and_emit_a2ui',
      text: 'a2ui',
      rawJson:
        '{"a2ui":{"surfaceUpdate":{"surfaceId":"marathon-dashboard","components":[{"id":"h1","component":{"Text":{"text":{"literalString":"Vegas Strip Marathon Plan"},"usageHint":"h3"}}},{"id":"d1","component":{"Divider":{}}},{"id":"t1","component":{"Text":{"text":{"literalString":"Theme: Neon Strip Run"},"usageHint":"body"}}},{"id":"t2","component":{"Text":{"text":{"literalString":"Date: November 17, 2024"},"usageHint":"body"}}},{"id":"t3","component":{"Text":{"text":{"literalString":"Distance: 26.2 Miles"},"usageHint":"body"}}},{"id":"t4","component":{"Text":{"text":{"literalString":"Participants: 10,000 Runners"},"usageHint":"body"}}},{"id":"t5","component":{"Text":{"text":{"literalString":"Budget: $1.2M (Estimated)"},"usageHint":"body"}}},{"id":"d2","component":{"Divider":{}}},{"id":"h2","component":{"Text":{"text":{"literalString":"Evaluation Metrics"},"usageHint":"h3"}}},{"id":"m1","component":{"Text":{"text":{"literalString":"Plan Quality: 0.1 (Status: Needs Improvement)"},"usageHint":"body"}}},{"id":"m2","component":{"Text":{"text":{"literalString":"Distance Compliance: 1.0 (Status: Pass)"},"usageHint":"body"}}},{"id":"d3","component":{"Divider":{}}},{"id":"btn-text","component":{"Text":{"text":{"literalString":"Run Simulation"}}}},{"id":"btn1","component":{"Button":{"child":"btn-text","action":{"name":"run_simulation"},"primary":{"literalBoolean":true}}}},{"id":"col1","component":{"Column":{"children":{"explicitList":["h1","d1","t1","t2","t3","t4","t5","d2","h2","m1","m2","d3","btn1"]}}}},{"id":"card1","component":{"Card":{"child":"col1"}}}]}}}',
      result: {
        surfaceUpdate: {
          surfaceId: 'sim_results',
          components: [
            {
              id: 'tag',
              component: { Text: { text: { literalString: 'PLAN' }, usageHint: 'label' } },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: { literalString: '881f2086-acca-4ac8-a969-b477a349d866' },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: { Row: { children: { explicitList: ['tag', 'sim-meta'] } } },
            },
            {
              id: 'title',
              component: {
                Text: { text: { literalString: 'Las Vegas Neon Night Marathon' }, usageHint: 'h2' },
              },
            },
            {
              id: 'left-col',
              component: { Column: { children: { explicitList: ['tag-row', 'title'] } } },
            },
            {
              id: 'score-num',
              component: { Text: { text: { literalString: '91' }, usageHint: 'h1' } },
            },
            {
              id: 'score-lbl',
              component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
            },
            {
              id: 'score-col',
              component: { Column: { children: { explicitList: ['score-num', 'score-lbl'] } } },
            },
            {
              id: 'header',
              component: { Row: { children: { explicitList: ['left-col', 'score-col'] } } },
            },
            {
              id: 'dist-l',
              component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
            },
            {
              id: 'dist-v',
              component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
            },
            {
              id: 'dist-r',
              component: { Row: { children: { explicitList: ['dist-l', 'dist-v'] } } },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: { literalString: 'Participants (expected/simulated)' },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
            },
            {
              id: 'part-r',
              component: { Row: { children: { explicitList: ['part-l', 'part-v'] } } },
            },
            { id: 'd1', component: { Divider: {} } },
            {
              id: 'safe-l',
              component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
            },
            {
              id: 'safe-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            {
              id: 'safe-r',
              component: { Row: { children: { explicitList: ['safe-l', 'safe-v'] } } },
            },
            {
              id: 'run-l',
              component: {
                Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
              },
            },
            {
              id: 'run-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            { id: 'run-r', component: { Row: { children: { explicitList: ['run-l', 'run-v'] } } } },
            {
              id: 'city-l',
              component: {
                Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
              },
            },
            {
              id: 'city-v',
              component: { Text: { text: { literalString: '100' }, usageHint: 'body' } },
            },
            {
              id: 'city-r',
              component: { Row: { children: { explicitList: ['city-l', 'city-v'] } } },
            },
            { id: 'd2', component: { Divider: {} } },
            {
              id: 'rerun-txt',
              component: { Text: { text: { literalString: 'Run Simulation' } } },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: { name: 'run_simulation' },
                  primary: { literalBoolean: true },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['rerun-btn'],
                  },
                },
              },
            },
            {
              id: 'content',
              component: {
                Column: {
                  children: {
                    explicitList: [
                      'header',
                      'dist-r',
                      'part-r',
                      'd1',
                      'safe-r',
                      'run-r',
                      'city-r',
                      'd2',
                      'buttons-r',
                    ],
                  },
                },
              },
            },
            { id: 'card', component: { Card: { child: 'content' } } },
          ],
        },
      },
    },
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-5a-log.ndjson'],
      timeScale: 3,
    },
  },
  '5b': {
    title: 'Intent to infrastructure with Gemini Cloud Assist (Upgraded)',
    isIntentToInfrastructureDemo: true,
    agent: 'planner_with_memory',
    orbitCamera: true,
    placeholderRoutes: 'cachedRoute01',

    placeholderAgentMessage: {
      guid: '934d9c7e-5203-4dd8-b31a-590e1bfc3f2f',
      speaker: 'planner_with_memory (934d9c)',
      emotion: '',
      isUser: false,
      timestamp: '2026-03-19T20:55:01.098Z',
      color: '#6bcb77',
      msgType: 'tool_end',
      icon: 'build',
      toolName: 'validate_and_emit_a2ui',
      text: 'a2ui',
      rawJson:
        '{"a2ui":{"surfaceUpdate":{"surfaceId":"marathon-dashboard","components":[{"id":"h1","component":{"Text":{"text":{"literalString":"Vegas Strip Marathon Plan"},"usageHint":"h3"}}},{"id":"d1","component":{"Divider":{}}},{"id":"t1","component":{"Text":{"text":{"literalString":"Theme: Neon Strip Run"},"usageHint":"body"}}},{"id":"t2","component":{"Text":{"text":{"literalString":"Date: November 17, 2024"},"usageHint":"body"}}},{"id":"t3","component":{"Text":{"text":{"literalString":"Distance: 26.2 Miles"},"usageHint":"body"}}},{"id":"t4","component":{"Text":{"text":{"literalString":"Participants: 10,000 Runners"},"usageHint":"body"}}},{"id":"t5","component":{"Text":{"text":{"literalString":"Budget: $1.2M (Estimated)"},"usageHint":"body"}}},{"id":"d2","component":{"Divider":{}}},{"id":"h2","component":{"Text":{"text":{"literalString":"Evaluation Metrics"},"usageHint":"h3"}}},{"id":"m1","component":{"Text":{"text":{"literalString":"Plan Quality: 0.1 (Status: Needs Improvement)"},"usageHint":"body"}}},{"id":"m2","component":{"Text":{"text":{"literalString":"Distance Compliance: 1.0 (Status: Pass)"},"usageHint":"body"}}},{"id":"d3","component":{"Divider":{}}},{"id":"btn-text","component":{"Text":{"text":{"literalString":"Run Simulation"}}}},{"id":"btn1","component":{"Button":{"child":"btn-text","action":{"name":"run_simulation"},"primary":{"literalBoolean":true}}}},{"id":"col1","component":{"Column":{"children":{"explicitList":["h1","d1","t1","t2","t3","t4","t5","d2","h2","m1","m2","d3","btn1"]}}}},{"id":"card1","component":{"Card":{"child":"col1"}}}]}}}',
      result: {
        surfaceUpdate: {
          surfaceId: 'sim_results',
          components: [
            {
              id: 'tag',
              component: { Text: { text: { literalString: 'PLAN' }, usageHint: 'label' } },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: { literalString: '881f2086-acca-4ac8-a969-b477a349d866' },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: { Row: { children: { explicitList: ['tag', 'sim-meta'] } } },
            },
            {
              id: 'title',
              component: {
                Text: { text: { literalString: 'Las Vegas Neon Night Marathon' }, usageHint: 'h2' },
              },
            },
            {
              id: 'left-col',
              component: { Column: { children: { explicitList: ['tag-row', 'title'] } } },
            },
            {
              id: 'score-num',
              component: { Text: { text: { literalString: '91' }, usageHint: 'h1' } },
            },
            {
              id: 'score-lbl',
              component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
            },
            {
              id: 'score-col',
              component: { Column: { children: { explicitList: ['score-num', 'score-lbl'] } } },
            },
            {
              id: 'header',
              component: { Row: { children: { explicitList: ['left-col', 'score-col'] } } },
            },
            {
              id: 'dist-l',
              component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
            },
            {
              id: 'dist-v',
              component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
            },
            {
              id: 'dist-r',
              component: { Row: { children: { explicitList: ['dist-l', 'dist-v'] } } },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: { literalString: 'Participants (expected/simulated)' },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
            },
            {
              id: 'part-r',
              component: { Row: { children: { explicitList: ['part-l', 'part-v'] } } },
            },
            { id: 'd1', component: { Divider: {} } },
            {
              id: 'safe-l',
              component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
            },
            {
              id: 'safe-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            {
              id: 'safe-r',
              component: { Row: { children: { explicitList: ['safe-l', 'safe-v'] } } },
            },
            {
              id: 'run-l',
              component: {
                Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
              },
            },
            {
              id: 'run-v',
              component: { Text: { text: { literalString: '80' }, usageHint: 'body' } },
            },
            { id: 'run-r', component: { Row: { children: { explicitList: ['run-l', 'run-v'] } } } },
            {
              id: 'city-l',
              component: {
                Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
              },
            },
            {
              id: 'city-v',
              component: { Text: { text: { literalString: '100' }, usageHint: 'body' } },
            },
            {
              id: 'city-r',
              component: { Row: { children: { explicitList: ['city-l', 'city-v'] } } },
            },
            { id: 'd2', component: { Divider: {} } },
            {
              id: 'rerun-txt',
              component: { Text: { text: { literalString: 'Run Simulation' } } },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: { name: 'run_simulation' },
                  primary: { literalBoolean: true },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['rerun-btn'],
                  },
                },
              },
            },
            {
              id: 'content',
              component: {
                Column: {
                  children: {
                    explicitList: [
                      'header',
                      'dist-r',
                      'part-r',
                      'd1',
                      'safe-r',
                      'run-r',
                      'city-r',
                      'd2',
                      'buttons-r',
                    ],
                  },
                },
              },
            },
            { id: 'card', component: { Card: { child: 'content' } } },
          ],
        },
      },
    },
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-5b-log.ndjson'],
      timeScale: 3,
    },
  },
  '7a': {
    title: 'Securing agents',
    agent: 'planner_with_memory',
    orbitCamera: true,
    promptPlaceholder:
      'Can we increase the budget so everyone gets glow sticks and those cool nighttime LED sunglasses?',
    isSecurityDemo: true,
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-7a-log.ndjson'],
      timeScale: 1.5,
    },
  },
  '7b': {
    title: 'Securing agents (Secure)',
    agent: 'planner_with_memory',
    orbitCamera: true,
    promptPlaceholder:
      'Can we increase the budget so everyone gets glow sticks and those cool nighttime LED sunglasses?',
    isSecurityDemo: true,
    recordingConfig: {
      cachedMessageStreams: ['/assets/sim-7b-log.ndjson'],
      timeScale: 0.5,
    },
  },
};
