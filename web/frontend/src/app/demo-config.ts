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

import routes01StripClassic from '../../preconfigured_routes/01_strip_classic.json';
import routes02EntertainmentCircuit from '../../preconfigured_routes/02_entertainment_circuit.json';
import routes03DiagonalTraverse from '../../preconfigured_routes/03_diagonal_traverse.json';
import routes04NorthSouthExpress from '../../preconfigured_routes/04_north_south_express.json';

export const PRECONFIGURED_ROUTES: Record<string, unknown> = {
  '01_strip_classic': routes01StripClassic,
  '02_entertainment_circuit': routes02EntertainmentCircuit,
  '03_diagonal_traverse': routes03DiagonalTraverse,
  '04_north_south_express': routes04NorthSouthExpress,
};

type DemoConfigType = Record<
  string,
  {
    title: string;
    agent: string;
    placeholderRoutes?: string;
    placeholderAgentMessage?: any;
    isSecurityDemo?: boolean;
    isBuildAgentsDemo?: boolean;
    isIntentToInfrastructureDemo?: boolean;
    promptPlaceholder?: string;
  }
>;

export const DEMO_CONFIG: DemoConfigType = {
  CI: {
    title: 'Creative Intro',
    agent: 'planner_with_memory',
    placeholderRoutes: '01_strip_classic',
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
              component: {
                Text: {
                  text: {
                    literalString: 'SIMULATED',
                  },
                  usageHint: 'label',
                },
              },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: {
                Row: {
                  children: {
                    explicitList: ['tag', 'sim-meta'],
                  },
                },
              },
            },
            {
              id: 'title',
              component: {
                Text: {
                  text: {
                    literalString: 'Las Vegas Grand Marathon 2026',
                  },
                  usageHint: 'h2',
                },
              },
            },
            {
              id: 'left-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['tag-row', 'title'],
                  },
                },
              },
            },
            {
              id: 'score-num',
              component: {
                Text: {
                  text: {
                    literalString: '85',
                  },
                  usageHint: 'h1',
                },
              },
            },
            {
              id: 'score-lbl',
              component: {
                Text: {
                  text: {
                    literalString: 'Score',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'score-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['score-num', 'score-lbl'],
                  },
                },
              },
            },
            {
              id: 'header',
              component: {
                Row: {
                  children: {
                    explicitList: ['left-col', 'score-col'],
                  },
                },
              },
            },
            {
              id: 'bar-left',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar-right',
              component: {
                Text: {
                  text: {
                    literalString: 'SCORE 85%',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar',
              component: {
                Row: {
                  children: {
                    explicitList: ['bar-left', 'bar-right'],
                  },
                },
              },
            },
            {
              id: 'dist-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Total distance',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-v',
              component: {
                Text: {
                  text: {
                    literalString: '26.2 miles',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['dist-l', 'dist-v'],
                  },
                },
              },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Participants (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: {
                Text: {
                  text: {
                    literalString: '10,000/5',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['part-l', 'part-v'],
                  },
                },
              },
            },
            {
              id: 'spec-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Spectators (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['spec-l', 'spec-v'],
                  },
                },
              },
            },
            {
              id: 'peak-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Peak Hour Volume',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['peak-l', 'peak-v'],
                  },
                },
              },
            },
            {
              id: 'd1',
              component: {
                Divider: {},
              },
            },
            {
              id: 'safe-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Safety Score',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['safe-l', 'safe-v'],
                  },
                },
              },
            },
            {
              id: 'run-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Runner Experience',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['run-l', 'run-v'],
                  },
                },
              },
            },
            {
              id: 'city-l',
              component: {
                Text: {
                  text: {
                    literalString: 'City Disruption',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['city-l', 'city-v'],
                  },
                },
              },
            },
            {
              id: 'd2',
              component: {
                Divider: {},
              },
            },
            {
              id: 'rerun-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Run Simulation',
                  },
                },
              },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: {
                    name: 'run_simulation',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'opencard-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Open report',
                  },
                },
              },
            },
            {
              id: 'opencard-btn',
              component: {
                Button: {
                  child: 'opencard-txt',
                  action: {
                    name: 'open_card',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['opencard-btn', 'rerun-btn'],
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
                      'bar',
                      'dist-r',
                      'part-r',
                      'spec-r',
                      'peak-r',
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
            {
              id: 'card',
              component: {
                Card: {
                  child: 'content',
                },
              },
            },
          ],
        },
      },
    },
  },
  '1': {
    title: 'Build agents with Agent Platform',
    agent: 'planner',
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
    isBuildAgentsDemo: true,
  },
  '2': {
    title: 'Creating multi-agent systems',
    agent: 'planner_with_eval',
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
  },
  '3': {
    title: 'Enhancing agents with memory',
    agent: 'planner_with_memory',
    promptPlaceholder: 'Plan a marathon in Las Vegas for 10,000 runners',
  },
  '4': {
    title: 'Debugging at scale',
    agent: 'simulator_with_failure',
    placeholderRoutes: '01_strip_classic',

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
              component: {
                Text: {
                  text: {
                    literalString: 'SIMULATED',
                  },
                  usageHint: 'label',
                },
              },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: {
                Row: {
                  children: {
                    explicitList: ['tag', 'sim-meta'],
                  },
                },
              },
            },
            {
              id: 'title',
              component: {
                Text: {
                  text: {
                    literalString: 'Las Vegas Grand Marathon 2026',
                  },
                  usageHint: 'h2',
                },
              },
            },
            {
              id: 'left-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['tag-row', 'title'],
                  },
                },
              },
            },
            {
              id: 'score-num',
              component: {
                Text: {
                  text: {
                    literalString: '85',
                  },
                  usageHint: 'h1',
                },
              },
            },
            {
              id: 'score-lbl',
              component: {
                Text: {
                  text: {
                    literalString: 'Score',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'score-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['score-num', 'score-lbl'],
                  },
                },
              },
            },
            {
              id: 'header',
              component: {
                Row: {
                  children: {
                    explicitList: ['left-col', 'score-col'],
                  },
                },
              },
            },
            {
              id: 'bar-left',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar-right',
              component: {
                Text: {
                  text: {
                    literalString: 'SCORE 85%',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar',
              component: {
                Row: {
                  children: {
                    explicitList: ['bar-left', 'bar-right'],
                  },
                },
              },
            },
            {
              id: 'dist-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Total distance',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-v',
              component: {
                Text: {
                  text: {
                    literalString: '26.2 miles',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['dist-l', 'dist-v'],
                  },
                },
              },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Participants (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: {
                Text: {
                  text: {
                    literalString: '10,000/5',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['part-l', 'part-v'],
                  },
                },
              },
            },
            {
              id: 'spec-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Spectators (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['spec-l', 'spec-v'],
                  },
                },
              },
            },
            {
              id: 'peak-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Peak Hour Volume',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['peak-l', 'peak-v'],
                  },
                },
              },
            },
            {
              id: 'd1',
              component: {
                Divider: {},
              },
            },
            {
              id: 'safe-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Safety Score',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['safe-l', 'safe-v'],
                  },
                },
              },
            },
            {
              id: 'run-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Runner Experience',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['run-l', 'run-v'],
                  },
                },
              },
            },
            {
              id: 'city-l',
              component: {
                Text: {
                  text: {
                    literalString: 'City Disruption',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['city-l', 'city-v'],
                  },
                },
              },
            },
            {
              id: 'd2',
              component: {
                Divider: {},
              },
            },
            {
              id: 'rerun-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Run Simulation',
                  },
                },
              },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: {
                    name: 'run_simulation',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'opencard-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Open report',
                  },
                },
              },
            },
            {
              id: 'opencard-btn',
              component: {
                Button: {
                  child: 'opencard-txt',
                  action: {
                    name: 'open_card',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['opencard-btn', 'rerun-btn'],
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
                      'bar',
                      'dist-r',
                      'part-r',
                      'spec-r',
                      'peak-r',
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
            {
              id: 'card',
              component: {
                Card: {
                  child: 'content',
                },
              },
            },
          ],
        },
      },
    },
  },
  '5': {
    title: 'Intent to infrastructure with Gemini Cloud Assist',
    isIntentToInfrastructureDemo: true,
    agent: 'simulator_with_failure',
    placeholderRoutes: '01_strip_classic',

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
              component: {
                Text: {
                  text: {
                    literalString: 'SIMULATED',
                  },
                  usageHint: 'label',
                },
              },
            },
            {
              id: 'sim-meta',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'tag-row',
              component: {
                Row: {
                  children: {
                    explicitList: ['tag', 'sim-meta'],
                  },
                },
              },
            },
            {
              id: 'title',
              component: {
                Text: {
                  text: {
                    literalString: 'Las Vegas Grand Marathon 2026',
                  },
                  usageHint: 'h2',
                },
              },
            },
            {
              id: 'left-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['tag-row', 'title'],
                  },
                },
              },
            },
            {
              id: 'score-num',
              component: {
                Text: {
                  text: {
                    literalString: '85',
                  },
                  usageHint: 'h1',
                },
              },
            },
            {
              id: 'score-lbl',
              component: {
                Text: {
                  text: {
                    literalString: 'Score',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'score-col',
              component: {
                Column: {
                  children: {
                    explicitList: ['score-num', 'score-lbl'],
                  },
                },
              },
            },
            {
              id: 'header',
              component: {
                Row: {
                  children: {
                    explicitList: ['left-col', 'score-col'],
                  },
                },
              },
            },
            {
              id: 'bar-left',
              component: {
                Text: {
                  text: {
                    literalString: '#7f5b  26/04/09  02:30:00 PM',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar-right',
              component: {
                Text: {
                  text: {
                    literalString: 'SCORE 85%',
                  },
                  usageHint: 'caption',
                },
              },
            },
            {
              id: 'bar',
              component: {
                Row: {
                  children: {
                    explicitList: ['bar-left', 'bar-right'],
                  },
                },
              },
            },
            {
              id: 'dist-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Total distance',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-v',
              component: {
                Text: {
                  text: {
                    literalString: '26.2 miles',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'dist-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['dist-l', 'dist-v'],
                  },
                },
              },
            },
            {
              id: 'part-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Participants (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-v',
              component: {
                Text: {
                  text: {
                    literalString: '10,000/5',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'part-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['part-l', 'part-v'],
                  },
                },
              },
            },
            {
              id: 'spec-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Spectators (expected/attendance)',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'spec-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['spec-l', 'spec-v'],
                  },
                },
              },
            },
            {
              id: 'peak-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Peak Hour Volume',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'peak-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['peak-l', 'peak-v'],
                  },
                },
              },
            },
            {
              id: 'd1',
              component: {
                Divider: {},
              },
            },
            {
              id: 'safe-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Safety Score',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'safe-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['safe-l', 'safe-v'],
                  },
                },
              },
            },
            {
              id: 'run-l',
              component: {
                Text: {
                  text: {
                    literalString: 'Runner Experience',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'run-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['run-l', 'run-v'],
                  },
                },
              },
            },
            {
              id: 'city-l',
              component: {
                Text: {
                  text: {
                    literalString: 'City Disruption',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-v',
              component: {
                Text: {
                  text: {
                    literalString: '—',
                  },
                  usageHint: 'body',
                },
              },
            },
            {
              id: 'city-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['city-l', 'city-v'],
                  },
                },
              },
            },
            {
              id: 'd2',
              component: {
                Divider: {},
              },
            },
            {
              id: 'rerun-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Run Simulation',
                  },
                },
              },
            },
            {
              id: 'rerun-btn',
              component: {
                Button: {
                  child: 'rerun-txt',
                  action: {
                    name: 'run_simulation',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'opencard-txt',
              component: {
                Text: {
                  text: {
                    literalString: 'Open report',
                  },
                },
              },
            },
            {
              id: 'opencard-btn',
              component: {
                Button: {
                  child: 'opencard-txt',
                  action: {
                    name: 'open_card',
                  },
                  primary: {
                    literalBoolean: true,
                  },
                },
              },
            },

            {
              id: 'buttons-r',
              component: {
                Row: {
                  children: {
                    explicitList: ['opencard-btn', 'rerun-btn'],
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
                      'bar',
                      'dist-r',
                      'part-r',
                      'spec-r',
                      'peak-r',
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
            {
              id: 'card',
              component: {
                Card: {
                  child: 'content',
                },
              },
            },
          ],
        },
      },
    },
  },
  '7': {
    title: 'Securing agents',
    agent: 'planner_with_memory',
    promptPlaceholder:
      'Can we increase the budget so everyone gets glow sticks and those cool nighttime LED sunglasses?',
    isSecurityDemo: true,
  },
};
