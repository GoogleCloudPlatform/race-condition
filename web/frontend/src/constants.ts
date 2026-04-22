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
import * as THREE from 'three';

export const DEMO_HOTKEYS = ['0', '1', '2', '3', '4', '5', '7', 'd', 'r', 'l', 'a', 's', 'd'];

/**
 * @deprecated Display names now come from the backend via proto
 * Origin.display_name. This map is kept only as a local fallback for
 * the spawn system-chat message until the first proto message arrives.
 */
export const AGENT_DISPLAY_NAMES: Record<string, string> = {};

export const DEMO_IDS = ['Sandbox', '1', '2', '3', '4', '5a', '5b', '7a', '7b'] as const;
export type DemoId = (typeof DEMO_IDS)[number];

export const demoFiveSpeaker = 'simulator_with_failure';

export const SECURE_AGENT_PROMPT = 'Switch to secure financial modeling';
export const UNSECURE_AGENT_PROMPT = 'Switch off the secure financial modeling mode';

export const RUNNER_EMOJIS = [
  '🏃',
  '🏃‍♀️',
  '🏃‍♂️',
  '💃',
  '🥨',
  '🍌',
  '🌮',
  '🍪',
  '🍔',
  '🍫',
  '😊',
  '😅',
  '🫠',
  '🥲',
  '🤪',
  '😑',
  '😶‍🌫️',
  '😏',
  '😌',
  '🥵',
  '🥴',
  '🤯',
  '🤠',
  '🥳',
  '😥',
  '😭',
  '🙄',
  '🥤',
  '🧃',
  '👵',
  '👴',
  '🧓',
  '👐',
  '✊',
  '💪',
  '👊',
  '✌️',
  '👻',
  '💥',
  '🐪',
  '🐫',
  '💧',
  '🔥',
  '👟',
  '🤖',
  '😎',
  '🚀',
  '🦬',
  '🦄',
];

export const DNF_RUNNER_EMOJIS = ['💀', '☠️'];

export const LOW_VITALS_EMOJIS = ['🧟', '🧟‍♀️', '🧟‍♂️', '😵', '😵‍💫', '🤢', '🤕', '🐌', '💩'];

// test splines
export const roadSpline1 = new THREE.CatmullRomCurve3(
  [
    new THREE.Vector3(490.7326182257384, 0, 3070.3698186911643),
    new THREE.Vector3(489.1107783275985, 0, 2807.5944370795905),
    new THREE.Vector3(487.48893842945864, 0, 2544.8190554680164),
    new THREE.Vector3(485.86709853131873, 0, 2282.0436738564426),
    new THREE.Vector3(484.2669848990841, 0, 2019.2681683990643),
    new THREE.Vector3(482.8930301085051, 0, 1756.4913737729084),
    new THREE.Vector3(481.51855971841024, 0, 1493.7145818461504),
    new THREE.Vector3(480.1410027948678, 0, 1230.9378060787972),
    new THREE.Vector3(479.0025781222212, 0, 968.1601591339647),
    new THREE.Vector3(478.46549122921994, 0, 705.3803214686047),
    new THREE.Vector3(477.9284043362186, 0, 442.6004838032453),
    new THREE.Vector3(477.3913174432173, 0, 179.82064613788532),
    new THREE.Vector3(477.4583076754737, 0, -82.9554385767398),
    new THREE.Vector3(481.26037235937395, 0, -345.7083183895084),
    new THREE.Vector3(485.06243704327414, 0, -608.4611982022757),
    new THREE.Vector3(479.3610789411804, 0, -862.192462902493),
    new THREE.Vector3(216.76579390619554, 0, -872.0538939933062),
    new THREE.Vector3(-45.51441774436964, 0, -874.8744122608522),
    new THREE.Vector3(-306.17931403717125, 0, -841.5976427898388),
    new THREE.Vector3(-568.0806496325745, 0, -821.7441818097789),
    new THREE.Vector3(-824.828475975437, 0, -855.5338362551488),
    new THREE.Vector3(-1076.9234346732092, 0, -929.7070345476055),
    new THREE.Vector3(-1331.986821314806, 0, -984.068889491817),
    new THREE.Vector3(-1594.7539827203711, 0, -983.6514927548322),
    new THREE.Vector3(-1857.5232487775534, 0, -981.2339813209604),
    new THREE.Vector3(-2120.2925148347354, 0, -978.8164698870887),
    new THREE.Vector3(-2383.06178089192, 0, -976.3989584532169),
    new THREE.Vector3(-2645.83711809493, 0, -974.8829721349492),
    new THREE.Vector3(-2908.615110646796, 0, -973.7612876095455),
    new THREE.Vector3(-3171.3931031986626, 0, -972.6396030841419),
    new THREE.Vector3(-3434.164017015825, 0, -971.3345974253857),
    new THREE.Vector3(-3696.246052952768, 0, -952.1894156578768),
    new THREE.Vector3(-3958.3280888897098, 0, -933.0442338903679),
    new THREE.Vector3(-4220.410124826652, 0, -913.8990521228591),
    new THREE.Vector3(-4482.518329658484, 0, -895.1201003516346),
    new THREE.Vector3(-4744.659821060988, 0, -876.8069894462035),
    new THREE.Vector3(-5006.801312463494, 0, -858.4938785407722),
    new THREE.Vector3(-5268.942803865996, 0, -840.1807676353412),
    new THREE.Vector3(-5303.029190540135, 0, -1067.3931185066601),
    new THREE.Vector3(-5304.080336848383, 0, -1330.1714026878337),
    new THREE.Vector3(-5305.1314831566315, 0, -1592.9496868690094),
    new THREE.Vector3(-5306.203308139791, 0, -1855.727874986969),
    new THREE.Vector3(-5307.593638516221, 0, -2118.5045834814773),
    new THREE.Vector3(-5308.862690986091, 0, -2381.2817328236038),
    new THREE.Vector3(-5309.382769303699, 0, -2644.061604701774),
    new THREE.Vector3(-5253.933846479278, 0, -2854.30623229617),
    new THREE.Vector3(-4991.646905454281, 0, -2870.4025708088316),
    new THREE.Vector3(-4729.359964429287, 0, -2886.4989093214936),
    new THREE.Vector3(-4467.073023404293, 0, -2902.595247834155),
    new THREE.Vector3(-4204.846173420781, 0, -2919.627641861928),
    new THREE.Vector3(-3942.654036695811, 0, -2937.2007743475315),
    new THREE.Vector3(-3680.4618999708373, 0, -2954.773906833135),
    new THREE.Vector3(-3418.2405853702217, 0, -2971.482517934374),
    new THREE.Vector3(-3155.460238765182, 0, -2971.6273761312664),
    new THREE.Vector3(-2892.6798921601385, 0, -2971.772234328159),
    new THREE.Vector3(-2629.899545555099, 0, -2971.917092525052),
    new THREE.Vector3(-2367.166472434253, 0, -2974.4875095292405),
    new THREE.Vector3(-2104.5800396659183, 0, -2984.5819075680142),
    new THREE.Vector3(-1841.9291629211912, 0, -2991.322294127196),
    new THREE.Vector3(-1579.1487763894638, 0, -2991.322294127196),
    new THREE.Vector3(-1316.6780983292338, 0, -2982.3705597645517),
    new THREE.Vector3(-1054.5260525142228, 0, -2964.209160568223),
    new THREE.Vector3(-792.374006699212, 0, -2946.0477613718945),
    new THREE.Vector3(-536.7420901532091, 0, -2973.570454972525),
    new THREE.Vector3(-298.0929881025837, 0, -3079.978937079736),
    new THREE.Vector3(-54.816225682991956, 0, -3165.7476327159034),
    new THREE.Vector3(203.16155054223623, 0, -3215.7576169155545),
    new THREE.Vector3(460.99139338747244, 0, -3192.4547902592403),
    new THREE.Vector3(590.1718542660075, 0, -3418.3115981927203),
    new THREE.Vector3(717.4835184163293, 0, -3648.192592877015),
    new THREE.Vector3(844.7951825666491, 0, -3878.0735875613072),
    new THREE.Vector3(969.3443567514771, 0, -4109.448001777618),
    new THREE.Vector3(1091.9564139165464, 0, -4341.869633695808),
    new THREE.Vector3(1214.5684710816122, 0, -4574.2912656139915),
    new THREE.Vector3(1337.1805282466812, 0, -4806.712897532181),
    new THREE.Vector3(1224.390280628895, 0, -4904.1015010321935),
    new THREE.Vector3(961.9190837698211, 0, -4916.771200098726),
    new THREE.Vector3(699.5262551472997, 0, -4931.0377705778965),
    new THREE.Vector3(436.93816132168706, 0, -4940.79490561367),
    new THREE.Vector3(174.16703109945496, 0, -4943.000504737645),
    new THREE.Vector3(-88.60096074768447, 0, -4945.48824299198),
    new THREE.Vector3(-351.35613436823724, 0, -4949.128336589198),
    new THREE.Vector3(-614.119906614007, 0, -4951.527010646649),
    new THREE.Vector3(-876.9002931457289, 0, -4951.527010646649),
    new THREE.Vector3(-1139.6583238539345, 0, -4954.679057631392),
    new THREE.Vector3(-1402.4122743044575, 0, -4958.406398292947),
    new THREE.Vector3(-1665.1798952879662, 0, -4960.706756076184),
    new THREE.Vector3(-1927.9558461818883, 0, -4962.194846621886),
    new THREE.Vector3(-2190.727569446631, 0, -4964.32862220543),
    new THREE.Vector3(-2453.4992927113735, 0, -4966.462397788974),
    new THREE.Vector3(-2716.2663753643155, 0, -4969.092177299074),
    new THREE.Vector3(-2979.0320230732545, 0, -4971.875328366653),
    new THREE.Vector3(-3241.7976707821977, 0, -4974.658479434231),
    new THREE.Vector3(-3504.560513972161, 0, -4975.8387608727),
    new THREE.Vector3(-3767.3148135708707, 0, -4972.136114771045),
    new THREE.Vector3(-4030.031470427266, 0, -4966.71059920003),
    new THREE.Vector3(-4292.696746189476, 0, -4958.933423972131),
    new THREE.Vector3(-4555.39543082963, 0, -4952.463353323881),
    new THREE.Vector3(-4818.038201983793, 0, -4944.132409801034),
    new THREE.Vector3(-5080.750425550823, 0, -4938.435134623356),
    new THREE.Vector3(-5343.487086254747, 0, -4933.641527639802),
    new THREE.Vector3(-5606.209514161279, 0, -4928.123055339807),
    new THREE.Vector3(-5868.931836895199, 0, -4922.599226680566),
    new THREE.Vector3(-6131.654159629124, 0, -4917.075398021325),
    new THREE.Vector3(-6394.392181900833, 0, -4914.3961187773775),
    new THREE.Vector3(-6657.159471443866, 0, -4917.019683521605),
    new THREE.Vector3(-6919.926760986909, 0, -4919.643248265833),
    new THREE.Vector3(-7182.69405052995, 0, -4922.26681301006),
    new THREE.Vector3(-7310.730394029589, 0, -4788.612616452937),
    new THREE.Vector3(-7311.106455223088, 0, -4525.832499009204),
    new THREE.Vector3(-7311.482516416588, 0, -4263.052381565476),
    new THREE.Vector3(-7311.858577610086, 0, -4000.27226412174),
    new THREE.Vector3(-7312.831313103898, 0, -3737.494018803412),
    new THREE.Vector3(-7314.104240979607, 0, -3474.716715368758),
    new THREE.Vector3(-7315.377168855317, 0, -3211.9394119341073),
    new THREE.Vector3(-7316.650096731027, 0, -2949.1621084994604),
    new THREE.Vector3(-7317.390076760935, 0, -2686.382884563202),
    new THREE.Vector3(-7318.011017086669, 0, -2423.603231662003),
    new THREE.Vector3(-7095.992956271734, 0, -2378.903152566337),
    new THREE.Vector3(-6833.256700547899, 0, -2374.087399875163),
    new THREE.Vector3(-6570.520444824067, 0, -2369.271647183989),
    new THREE.Vector3(-6307.784267340031, 0, -2364.4517917315293),
    new THREE.Vector3(-6045.05543238508, 0, -2359.2469066245626),
    new THREE.Vector3(-5782.326597430126, 0, -2354.042021517596),
    new THREE.Vector3(-5519.597762475174, 0, -2348.8371364106292),
    new THREE.Vector3(-5256.9555302233475, 0, -2347.830017049117),
    new THREE.Vector3(-4994.664916838473, 0, -2363.8664030492496),
    new THREE.Vector3(-4732.374303453584, 0, -2379.9027890493835),
    new THREE.Vector3(-4470.083690068702, 0, -2395.9391750495165),
    new THREE.Vector3(-4207.77946828318, 0, -2411.750398107331),
    new THREE.Vector3(-3945.466687101166, 0, -2427.4199984315296),
    new THREE.Vector3(-3683.153905919152, 0, -2443.0895987557287),
    new THREE.Vector3(-3420.8134835213978, 0, -2457.957522253537),
    new THREE.Vector3(-3158.0443773620696, 0, -2460.392351609228),
    new THREE.Vector3(-2895.2752712027345, 0, -2462.8271809649195),
    new THREE.Vector3(-2632.506165043407, 0, -2465.262010320611),
    new THREE.Vector3(-2369.758256303693, 0, -2468.891378143832),
    new THREE.Vector3(-2107.0682011301515, 0, -2475.7809687476715),
    new THREE.Vector3(-1844.3781459566171, 0, -2482.6705593515107),
    new THREE.Vector3(-1581.6880907830825, 0, -2489.5601499553504),
    new THREE.Vector3(-1319.049887994411, 0, -2488.423609694104),
    new THREE.Vector3(-1056.4707758261893, 0, -2478.1405460109777),
    new THREE.Vector3(-793.8916636579676, 0, -2467.8574823278514),
    new THREE.Vector3(-531.3125514897457, 0, -2457.574418644725),
    new THREE.Vector3(-269.02243571476555, 0, -2442.578855373989),
    new THREE.Vector3(-7.154445054608459, 0, -2420.699938276144),
    new THREE.Vector3(253.08992036773813, 0, -2385.184950214056),
    new THREE.Vector3(513.4467813482903, 0, -2353.0737103781184),
    new THREE.Vector3(776.20858907204, 0, -2349.948978787974),
    new THREE.Vector3(1034.4060085170063, 0, -2311.3764644757666),
    new THREE.Vector3(1195.9894060155111, 0, -2118.9564416150592),
    new THREE.Vector3(1366.6529055855328, 0, -1943.4121362890098),
    new THREE.Vector3(1466.7234236634283, 0, -1759.5429664003245),
    new THREE.Vector3(1468.2625935262595, 0, -1496.7670875569722),
    new THREE.Vector3(1469.8017633890909, 0, -1233.9912087136124),
    new THREE.Vector3(1471.3409332519223, 0, -971.2153298702599),
    new THREE.Vector3(1473.3621694272147, 0, -708.4431763271289),
    new THREE.Vector3(1475.8842868349752, 0, -445.6748934816742),
    new THREE.Vector3(1478.4064042427356, 0, -182.90661063622667),
    new THREE.Vector3(1480.9429035102678, 0, 79.86152988333153),
    new THREE.Vector3(1483.6215904226265, 0, 342.6282632842486),
    new THREE.Vector3(1486.3002773349851, 0, 605.3949966851657),
    new THREE.Vector3(1488.978964247344, 0, 868.1617300860827),
    new THREE.Vector3(1398.3012353943554, 0, 1038.9207986528593),
    new THREE.Vector3(1135.5233446838824, 0, 1040.0660931659668),
    new THREE.Vector3(872.745453973417, 0, 1041.211387679074),
    new THREE.Vector3(609.9675632629588, 0, 1042.356682192181),
    new THREE.Vector3(347.2129474158085, 0, 1045.4710712544786),
    new THREE.Vector3(84.48140298037504, 0, 1050.537342500152),
    new THREE.Vector3(-178.2501414550585, 0, 1055.6036137458254),
    new THREE.Vector3(-440.97748029423036, 0, 1058.0483507544106),
    new THREE.Vector3(-703.6914173025625, 0, 1052.1391336027896),
    new THREE.Vector3(-966.4053543108947, 0, 1046.2299164511687),
    new THREE.Vector3(-1229.119291319227, 0, 1040.3206992995479),
    new THREE.Vector3(-1401.2326322538836, 0, 1127.165388821946),
    new THREE.Vector3(-1401.4948054893002, 0, 1389.9456445698954),
    new THREE.Vector3(-1401.756978724717, 0, 1652.725900317845),
    new THREE.Vector3(-1402.0191519601337, 0, 1915.5061560657944),
    new THREE.Vector3(-1402.4334154116486, 0, 2178.2861760458554),
    new THREE.Vector3(-1402.9859572127907, 0, 2441.065981668969),
    new THREE.Vector3(-1403.5384990139326, 0, 2703.8457872920826),
    new THREE.Vector3(-1404.0910408150746, 0, 2966.625592915203),
    new THREE.Vector3(-1405.9599887518962, 0, 3229.3978921710927),
    new THREE.Vector3(-1408.404213951237, 0, 3492.1669111001456),
    new THREE.Vector3(-1410.6615601849915, 0, 3754.937583468688),
    new THREE.Vector3(-1412.8671297266974, 0, 4017.708713939218),
    new THREE.Vector3(-1415.0726992684033, 0, 4280.479844409748),
    new THREE.Vector3(-1417.2782688101092, 0, 4543.250974880278),
    new THREE.Vector3(-1418.2886350050271, 0, 4806.029267432571),
    new THREE.Vector3(-1403.547214940009, 0, 5054.79459654865),
    new THREE.Vector3(-1142.3226948572783, 0, 5083.347733912352),
    new THREE.Vector3(-881.0981747745402, 0, 5111.900871276055),
    new THREE.Vector3(-619.8736546918165, 0, 5140.4540086397565),
    new THREE.Vector3(-358.48093337143524, 0, 5166.230169217695),
    new THREE.Vector3(-95.71984471365352, 0, 5169.41479370815),
    new THREE.Vector3(166.79220492928968, 0, 5163.168655458403),
    new THREE.Vector3(429.01900808626107, 0, 5146.120627659343),
    new THREE.Vector3(536.6473689935914, 0, 4987.636561524397),
    new THREE.Vector3(530.3556657824571, 0, 4724.931506345647),
    new THREE.Vector3(524.0639625713229, 0, 4462.2264511669055),
  ],
  false,
  'catmullrom',
  0.5,
);

export const roadSpline2 = new THREE.CatmullRomCurve3(
  [
    new THREE.Vector3(-1000, 0, -900),
    new THREE.Vector3(-500, 0, -850),
    new THREE.Vector3(1450, 0, -860),
    new THREE.Vector3(1450, 0, 50),
    new THREE.Vector3(480, 0, 50),
    new THREE.Vector3(480, 0, 600),
    new THREE.Vector3(180, 0, 680),
    new THREE.Vector3(0, 0, 630),
    new THREE.Vector3(-380, 0, 630),
    new THREE.Vector3(-480, 0, 520),
    new THREE.Vector3(-480, 0, 50),
    new THREE.Vector3(-700, 0, 40),
    new THREE.Vector3(-1180, 0, -30),
    new THREE.Vector3(-1380, 0, -200),
    new THREE.Vector3(-1440, 0, -900),
  ],
  false,
  'catmullrom',
  0.1,
);

export const roadSpline3 = new THREE.CatmullRomCurve3(
  [
    new THREE.Vector3(-380, 0, -1520),
    new THREE.Vector3(-380, 0, 1000),
    new THREE.Vector3(-1430, 0, 1000),
    new THREE.Vector3(-1400, 0, 200),
    new THREE.Vector3(-1250, 0, -50),
    new THREE.Vector3(-930, 0, 10),
    new THREE.Vector3(-150, 0, 30),
    new THREE.Vector3(100, 0, -100),
    new THREE.Vector3(480, 0, -100),
    new THREE.Vector3(480, 0, -850),
    new THREE.Vector3(-750, 0, -850),
    new THREE.Vector3(-1300, 0, -1000),
    new THREE.Vector3(-1430, 0, -1000),
    new THREE.Vector3(-1430, 0, -1950),
    new THREE.Vector3(-1220, 0, -1980),
  ],
  false,
  'catmullrom',
  0.1,
);

export const CACHED_ORGANIZER_MESSAGE = {
  wrapperType: 'a2ui',
  event: 'a2ui',
  data: {
    surfaceUpdate: {
      surfaceId: 'route_list',
      components: [
        {
          id: 'tag-1',
          component: { Text: { text: { literalString: 'SIMULATED' }, usageHint: 'label' } },
        },
        {
          id: 'sim-meta-1',
          component: {
            Text: {
              text: { literalString: 'b59e317a-8f2c-4e1a-bd84-362203e85764' },
              usageHint: 'caption',
            },
          },
        },
        {
          id: 'tag-row-1',
          component: { Row: { children: { explicitList: ['tag-1', 'sim-meta-1'] } } },
        },
        {
          id: 'title-1',
          component: {
            Text: { text: { literalString: 'Las Vegas Neon Night Marathon' }, usageHint: 'h2' },
          },
        },
        {
          id: 'left-col-1',
          component: { Column: { children: { explicitList: ['tag-row-1', 'title-1'] } } },
        },
        {
          id: 'score-num-1',
          component: { Text: { text: { literalString: '83' }, usageHint: 'h1' } },
        },
        {
          id: 'score-lbl-1',
          component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
        },
        {
          id: 'score-col-1',
          component: { Column: { children: { explicitList: ['score-num-1', 'score-lbl-1'] } } },
        },
        {
          id: 'header-1',
          component: { Row: { children: { explicitList: ['left-col-1', 'score-col-1'] } } },
        },
        {
          id: 'dist-l-1',
          component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
        },
        {
          id: 'dist-v-1',
          component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
        },
        {
          id: 'dist-r-1',
          component: { Row: { children: { explicitList: ['dist-l-1', 'dist-v-1'] } } },
        },
        {
          id: 'part-l-1',
          component: {
            Text: {
              text: { literalString: 'Participants (expected/simulated)' },
              usageHint: 'body',
            },
          },
        },
        {
          id: 'part-v-1',
          component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
        },
        {
          id: 'part-r-1',
          component: { Row: { children: { explicitList: ['part-l-1', 'part-v-1'] } } },
        },
        { id: 'd1-1', component: { Divider: {} } },
        {
          id: 'safe-l-1',
          component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
        },
        {
          id: 'safe-v-1',
          component: { Text: { text: { literalString: '75' }, usageHint: 'body' } },
        },
        {
          id: 'safe-r-1',
          component: { Row: { children: { explicitList: ['safe-l-1', 'safe-v-1'] } } },
        },
        {
          id: 'run-l-1',
          component: {
            Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
          },
        },
        {
          id: 'run-v-1',
          component: { Text: { text: { literalString: '90' }, usageHint: 'body' } },
        },
        {
          id: 'run-r-1',
          component: { Row: { children: { explicitList: ['run-l-1', 'run-v-1'] } } },
        },
        {
          id: 'city-l-1',
          component: {
            Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
          },
        },
        {
          id: 'city-v-1',
          component: { Text: { text: { literalString: '82' }, usageHint: 'body' } },
        },
        {
          id: 'city-r-1',
          component: { Row: { children: { explicitList: ['city-l-1', 'city-v-1'] } } },
        },
        { id: 'd2-1', component: { Divider: {} } },
        { id: 'osc-txt-1', component: { Text: { text: { literalString: 'Open Report' } } } },
        {
          id: 'osc-btn-1',
          component: {
            Button: { child: 'osc-txt-1', action: { name: 'organizer_show_scorecard' } },
          },
        },
        { id: 'sr-txt-1', component: { Text: { text: { literalString: 'Show Route' } } } },
        {
          id: 'sr-btn-1',
          component: {
            Button: {
              child: 'sr-txt-1',
              action: {
                name: 'show_route',
                payload: { seed: 'dd82048d-914d-4bbc-99f8-d44c33c9834c' },
              },
              primary: { literalBoolean: true },
            },
          },
        },
        {
          id: 'buttons-r-1',
          component: {
            Row: {
              children: {
                explicitList: ['osc-btn-1', 'sr-btn-1'],
              },
            },
          },
        },
        {
          id: 'content-1',
          component: {
            Column: {
              children: {
                explicitList: [
                  'header-1',
                  'dist-r-1',
                  'part-r-1',
                  'd1-1',
                  'safe-r-1',
                  'run-r-1',
                  'city-r-1',
                  'd2-1',
                  'buttons-r-1',
                ],
              },
            },
          },
        },
        { id: 'card-1', component: { Card: { child: 'content-1' } } },
        {
          id: 'tag-2',
          component: { Text: { text: { literalString: 'SIMULATED' }, usageHint: 'label' } },
        },
        {
          id: 'sim-meta-2',
          component: {
            Text: {
              text: { literalString: 'f47ac10b-58cc-4372-a567-0e02b2c3d479' },
              usageHint: 'caption',
            },
          },
        },
        {
          id: 'tag-row-2',
          component: { Row: { children: { explicitList: ['tag-2', 'sim-meta-2'] } } },
        },
        {
          id: 'title-2',
          component: {
            Text: { text: { literalString: 'Grand Loop' }, usageHint: 'h2' },
          },
        },
        {
          id: 'left-col-2',
          component: { Column: { children: { explicitList: ['tag-row-2', 'title-2'] } } },
        },
        {
          id: 'score-num-2',
          component: { Text: { text: { literalString: '84' }, usageHint: 'h1' } },
        },
        {
          id: 'score-lbl-2',
          component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
        },
        {
          id: 'score-col-2',
          component: { Column: { children: { explicitList: ['score-num-2', 'score-lbl-2'] } } },
        },
        {
          id: 'header-2',
          component: { Row: { children: { explicitList: ['left-col-2', 'score-col-2'] } } },
        },
        {
          id: 'dist-l-2',
          component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
        },
        {
          id: 'dist-v-2',
          component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
        },
        {
          id: 'dist-r-2',
          component: { Row: { children: { explicitList: ['dist-l-2', 'dist-v-2'] } } },
        },
        {
          id: 'part-l-2',
          component: {
            Text: {
              text: { literalString: 'Participants (expected/simulated)' },
              usageHint: 'body',
            },
          },
        },
        {
          id: 'part-v-2',
          component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
        },
        {
          id: 'part-r-2',
          component: { Row: { children: { explicitList: ['part-l-2', 'part-v-2'] } } },
        },
        { id: 'd1-2', component: { Divider: {} } },
        {
          id: 'safe-l-2',
          component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
        },
        {
          id: 'safe-v-2',
          component: { Text: { text: { literalString: '87' }, usageHint: 'body' } },
        },
        {
          id: 'safe-r-2',
          component: { Row: { children: { explicitList: ['safe-l-2', 'safe-v-2'] } } },
        },
        {
          id: 'run-l-2',
          component: {
            Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
          },
        },
        {
          id: 'run-v-2',
          component: { Text: { text: { literalString: '75' }, usageHint: 'body' } },
        },
        {
          id: 'run-r-2',
          component: { Row: { children: { explicitList: ['run-l-2', 'run-v-2'] } } },
        },
        {
          id: 'city-l-2',
          component: {
            Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
          },
        },
        {
          id: 'city-v-2',
          component: { Text: { text: { literalString: '90' }, usageHint: 'body' } },
        },
        {
          id: 'city-r-2',
          component: { Row: { children: { explicitList: ['city-l-2', 'city-v-2'] } } },
        },
        { id: 'd2-2', component: { Divider: {} } },

        { id: 'osc-txt-2', component: { Text: { text: { literalString: 'Open Report' } } } },
        {
          id: 'osc-btn-2',
          component: {
            Button: { child: 'osc-txt-2', action: { name: 'organizer_show_scorecard' } },
          },
        },
        { id: 'sr-txt-2', component: { Text: { text: { literalString: 'Show Route' } } } },
        {
          id: 'sr-btn-2',
          component: {
            Button: {
              child: 'sr-txt-2',
              action: {
                name: 'show_route',
                payload: { seed: 'seed-0004-grand-loop-m3n4o5p6' },
              },
              primary: { literalBoolean: true },
            },
          },
        },

        {
          id: 'buttons-r-2',
          component: {
            Row: {
              children: {
                explicitList: ['osc-btn-2', 'sr-btn-2'],
              },
            },
          },
        },
        {
          id: 'content-2',
          component: {
            Column: {
              children: {
                explicitList: [
                  'header-2',
                  'dist-r-2',
                  'part-r-2',
                  'd1-2',
                  'safe-r-2',
                  'run-r-2',
                  'city-r-2',
                  'd2-2',
                  'buttons-r-2',
                ],
              },
            },
          },
        },
        { id: 'card-2', component: { Card: { child: 'content-2' } } },
        {
          id: 'tag-3',
          component: { Text: { text: { literalString: 'SIMULATED' }, usageHint: 'label' } },
        },
        {
          id: 'sim-meta-3',
          component: {
            Text: {
              text: { literalString: '740203f1-3375-47e3-9993-9c88e733075d' },
              usageHint: 'caption',
            },
          },
        },
        {
          id: 'tag-row-3',
          component: { Row: { children: { explicitList: ['tag-3', 'sim-meta-3'] } } },
        },
        {
          id: 'title-3',
          component: {
            Text: { text: { literalString: 'East Side Explorer' }, usageHint: 'h2' },
          },
        },
        {
          id: 'left-col-3',
          component: { Column: { children: { explicitList: ['tag-row-3', 'title-3'] } } },
        },
        {
          id: 'score-num-3',
          component: { Text: { text: { literalString: '78' }, usageHint: 'h1' } },
        },
        {
          id: 'score-lbl-3',
          component: { Text: { text: { literalString: 'Score' }, usageHint: 'caption' } },
        },
        {
          id: 'score-col-3',
          component: { Column: { children: { explicitList: ['score-num-3', 'score-lbl-3'] } } },
        },
        {
          id: 'header-3',
          component: { Row: { children: { explicitList: ['left-col-3', 'score-col-3'] } } },
        },
        {
          id: 'dist-l-3',
          component: { Text: { text: { literalString: 'Total distance' }, usageHint: 'body' } },
        },
        {
          id: 'dist-v-3',
          component: { Text: { text: { literalString: '26.2 miles' }, usageHint: 'body' } },
        },
        {
          id: 'dist-r-3',
          component: { Row: { children: { explicitList: ['dist-l-3', 'dist-v-3'] } } },
        },
        {
          id: 'part-l-3',
          component: {
            Text: {
              text: { literalString: 'Participants (expected/simulated)' },
              usageHint: 'body',
            },
          },
        },
        {
          id: 'part-v-3',
          component: { Text: { text: { literalString: '10,000/1,000' }, usageHint: 'body' } },
        },
        {
          id: 'part-r-3',
          component: { Row: { children: { explicitList: ['part-l-3', 'part-v-3'] } } },
        },
        { id: 'd1-3', component: { Divider: {} } },
        {
          id: 'safe-l-3',
          component: { Text: { text: { literalString: 'Safety Score' }, usageHint: 'body' } },
        },
        {
          id: 'safe-v-3',
          component: { Text: { text: { literalString: '70' }, usageHint: 'body' } },
        },
        {
          id: 'safe-r-3',
          component: { Row: { children: { explicitList: ['safe-l-3', 'safe-v-3'] } } },
        },
        {
          id: 'run-l-3',
          component: {
            Text: { text: { literalString: 'Runner Experience' }, usageHint: 'body' },
          },
        },
        {
          id: 'run-v-3',
          component: { Text: { text: { literalString: '90' }, usageHint: 'body' } },
        },
        {
          id: 'run-r-3',
          component: { Row: { children: { explicitList: ['run-l-3', 'run-v-3'] } } },
        },
        {
          id: 'city-l-3',
          component: {
            Text: { text: { literalString: 'City Disruption' }, usageHint: 'body' },
          },
        },
        {
          id: 'city-v-3',
          component: { Text: { text: { literalString: '74' }, usageHint: 'body' } },
        },
        {
          id: 'city-r-3',
          component: { Row: { children: { explicitList: ['city-l-3', 'city-v-3'] } } },
        },
        { id: 'd2-3', component: { Divider: {} } },

        { id: 'osc-txt-3', component: { Text: { text: { literalString: 'Open Report' } } } },
        {
          id: 'osc-btn-3',
          component: {
            Button: { child: 'osc-txt-3', action: { name: 'organizer_show_scorecard' } },
          },
        },
        { id: 'sr-txt-3', component: { Text: { text: { literalString: 'Show Route' } } } },
        {
          id: 'sr-btn-3',
          component: {
            Button: {
              child: 'sr-txt-3',
              action: {
                name: 'show_route',
                payload: { seed: 'seed-0003-east-side-explorer-i9j0k1l2' },
              },
              primary: { literalBoolean: true },
            },
          },
        },

        {
          id: 'buttons-r-3',
          component: {
            Row: {
              children: {
                explicitList: ['osc-btn-3', 'sr-btn-3'],
              },
            },
          },
        },
        {
          id: 'content-3',
          component: {
            Column: {
              children: {
                explicitList: [
                  'header-3',
                  'dist-r-3',
                  'part-r-3',
                  'd1-3',
                  'safe-r-3',
                  'run-r-3',
                  'city-r-3',
                  'd2-3',
                  'buttons-r-3',
                ],
              },
            },
          },
        },
        { id: 'card-3', component: { Card: { child: 'content-3' } } },

        {
          id: 'list-1',
          component: { List: { children: { explicitList: ['card-1', 'card-2', 'card-3'] } } },
        },
        { id: 'root-card', component: { Card: { child: 'list-1' } } },
      ],
    },
  },
  timestamp: '2026-04-16T20:54:01.166349',
  origin: {
    id: 'planner_with_memory',
    type: 'agent',
    sessionId: 'fb6cba72-3346-4888-9166-869e81defe02',
  },
  speaker: 'planner_with_memory (fb6cba)',
};

export const SWITCH_RUNNER_THOUGHTS_MS = 5000;

export const EXTERNAL_THOUGHTS = [
  'The fountains gave me hope.',
  'Only three miles left.',
  'Cheesecake is the answer.',
  'Mile nine, why?',
  'Seven more miles, then we eat.',
  'I can hear the finish line.',
  'Vegas, send music.',
  'Burrito, please wait for me.',
  'Mile five feels blessed.',
  'The city is watching.',
  'A tourist just high-fived me.',
  'Crowd noise is medicine.',
  'Pho at the finish line is the dream.',
  'Counted twenty-two Stormtroopers so far.',
  'The Sphere is calling me.',
  'Why did I sign up for this again?',
  'Small steps, no thoughts.',
  'One foot, then another.',
  'Almost at the finish line.',
  'Keep going, you legend.',
  'Vibing, somehow.',
  'Just three more steps.',
  'Post-race pizza is going to be amazing.',
  'Imagining a big bowl of ramen.',
  'I really miss my couch.',
  'Mile ten is everything.',
  'Good job, legs.',
  'Donuts are the answer.',
  'The wind is finally on my side.',
  'I want tacos so badly.',
  'Wait for the milkshake.',
  'Water is the only thing I need.',
  'Smile, you got this.',
  'The road loves me.',
  'Mile one was so much easier.',
  'A buffet is the ultimate goal.',
  'My feet feel afloat.',
  'We are all in this together.',
  'Just keep going.',
  'The neon lights are watching over me.',
  'I definitely earned that burger.',
  'One more mile to go.',
  'Vegas, send some energy.',
  'I miss being still.',
  'Small steps, big heart.',
  'The finish line is a state of mind.',
  'Drinking water saved my life.',
  'Smile for the cameras.',
  'Think about the pancakes.',
  'The desert air is cooling down.',
  'I love you, running shoes.',
  'Almost home.',
  'One foot in front of the other.',
  'Just follow the person in front of you.',
  'Focus on the music.',
  'Imagine the shower after this.',
  'My heart is still in it.',
  'Vegas made me a runner tonight.',
  'Is that the finish line or a mirage?',
  'Keep your head up.',
  'You are doing great.',
  'The crowd is cheering for me.',
  'Think about the reward.',
  'Almost there, keep pushing.',
  'This is for the medal.',
];
