-- Copyright 2026 Google LLC
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Rule seed data for the rules table.
-- These rows match the chunks in LEGISLATION.txt and are inserted idempotently.
-- Run AFTER schema.sql has been applied.

INSERT INTO rules (source_file, chunk_id, city, text) VALUES
('LEGISLATION.txt', 1, 'Las Vegas',
'LAS VEGAS MUNICIPAL CODE - SIDEWALK VENDORS (CHAPTER 6.96)
6.96.020 - Definitions.
"Sidewalk vendor" means a person who, from a conveyance, sells food, beverages, or merchandise upon a public sidewalk or other pedestrian path.
6.96.070 - Operating Requirements and Prohibitions.
(A) It is unlawful for a sidewalk vendor to:
(1) Vend at locations where it will impede pedestrian traffic, normal use of the sidewalk, or hinder access or accessibility required by the Americans with Disabilities Act.
(5) Vend within 1,500 feet of a resort hotel.
(6) Vend within 1,000 feet of non-restricted gaming establishments, the Fremont Street Experience, the Downtown Entertainment Overlay District, city recreation facilities, pools, and schools.'),

('LEGISLATION.txt', 2, 'Nevada',
'NEVADA REVISED STATUTES - HISTORICAL ACT OF 1875
An Act to prohibit camels and dromedaries from running at large on or about the public highways of the State of Nevada. [Approved February 9, 1875.]
The People of the State of Nevada, represented in Senate and Assembly, do enact as follows:
Section 1. From and after the passage of this Act it shall be unlawful for the owner or owners of any camel or camels, dromedary or dromedaries, to permit them to run at large on or about the public roads or highways of this State.
Sec. 2. If any owner or owners of any camel or camels, dromedary or dromedaries shall, knowingly and willfully, permit any violation of this Act, he or they shall be deemed guilty of a misdemeanor, and shall be arrested, on complaint of any person feeling aggrieved; and when convicted, before any Justice of the Peace, he or they shall be punished by a fine not less than twenty-five (25) or more than one hundred (100) dollars, or by imprisonment not less than ten or more than thirty days, or by both such fine and imprisonment.'),

('LEGISLATION.txt', 3, 'Las Vegas',
'LAS VEGAS MUNICIPAL CODE - OBSTRUCTING PUBLIC RIGHTS-OF-WAY (SECTION 10.86.010)
10.86.010 - Pedestrian interference—Prohibited locations.
(A) It is unlawful for any person to sit, lie, sleep, camp, or otherwise lodge in the public right-of-way in the following locations:
(1) Any public street or sidewalk next to a residential property.
(2) Any public street or sidewalk within specific downtown districts.
(B) It is a misdemeanor to sit, lie, sleep, camp, or otherwise obstruct the sidewalk during designated cleaning times. Appropriate signs or markings must be placed to alert the public to these cleaning times.')

ON CONFLICT DO NOTHING;
