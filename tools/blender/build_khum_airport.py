# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Build a stylized KHUM/Houma-Terrebonne Airport model in Blender.

This script is designed to be run inside Blender, either via the Blender MCP
`execute_blender_code` tool or with Blender's `--python` flag. It creates a
layout-accurate, Vegas-style airport blockout using public OurAirports runway
metadata and exports a GLB for the Race Condition frontend.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
from mathutils import Vector

PROJECT_ROOT = Path("/Users/nick/Sites/race-condition")
ASSET_DIR = PROJECT_ROOT / "web/frontend/public/assets/models"
EXPORT_GLB = ASSET_DIR / "KHUM_Houma_Airport.glb"
EXPORT_BLEND = ASSET_DIR / "KHUM_Houma_Airport.blend"

KHUM_CENTER_LAT = 29.56740278
KHUM_CENTER_LON = -90.66035278
EARTH_RADIUS_M = 6_378_137.0
FT_TO_M = 0.3048

# OurAirports runway metadata for KHUM, fetched 2026-04-30.
RUNWAYS = [
    {
        "name": "RWY_12_30",
        "le_ident": "12",
        "he_ident": "30",
        "length_ft": 4999,
        "width_ft": 185,
        "le_lat": 29.57089996,
        "le_lon": -90.66690063,
        "he_lat": 29.56290054,
        "he_lon": -90.65409851,
    },
    {
        "name": "RWY_18_36",
        "le_ident": "18",
        "he_ident": "36",
        "length_ft": 6509,
        "width_ft": 150,
        "le_lat": 29.575001,
        "le_lon": -90.660301,
        "he_lat": 29.5571,
        "he_lon": -90.6604,
    },
]


def lonlat_to_xy(lon: float, lat: float) -> tuple[float, float]:
    """Convert lon/lat to local meters using Web Mercator delta from KHUM center.

    Blender uses X/East and Y/North in meters. The frontend can later scale or
    rotate this GLB as needed, but these coordinates preserve real runway
    bearings and relative lengths.
    """

    lon_r = math.radians(lon)
    lat_r = math.radians(lat)
    center_lon_r = math.radians(KHUM_CENTER_LON)
    center_lat_r = math.radians(KHUM_CENTER_LAT)
    x = EARTH_RADIUS_M * (lon_r - center_lon_r)
    y = EARTH_RADIUS_M * (
        math.log(math.tan(math.pi / 4 + lat_r / 2))
        - math.log(math.tan(math.pi / 4 + center_lat_r / 2))
    )
    return x, y


def make_mat(
    name: str,
    color: tuple[float, float, float, float],
    roughness: float = 0.85,
    metallic: float = 0.0,
    emission: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
):
    """Create materials tuned to the keynote Vegas night palette."""

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if emission:
            bsdf.inputs["Emission Color"].default_value = emission
            bsdf.inputs["Emission Strength"].default_value = emission_strength
    mat.diffuse_color = color
    return mat


# Colors are sampled by eye from the Vegas scene: charcoal-blue ground, graphite
# buildings, icy window grids, pale road/runway striping, and sparing cyan/teal
# accents. The airport should feel like a KHUM-specific miniature in the same
# nighttime diorama world, not a bright daytime field.
MATS = {
    "ground": make_mat("KHUM_vegas_night_ground", (0.020, 0.025, 0.040, 1.0)),
    "field_block": make_mat("KHUM_vegas_field_block", (0.035, 0.045, 0.065, 1.0)),
    "field_block_alt": make_mat("KHUM_vegas_field_block_alt", (0.045, 0.055, 0.078, 1.0)),
    "runway": make_mat("KHUM_vegas_runway_graphite", (0.070, 0.080, 0.105, 1.0)),
    "asphalt": make_mat("KHUM_vegas_taxiway_asphalt", (0.045, 0.053, 0.072, 1.0)),
    "apron": make_mat("KHUM_vegas_apron_slate", (0.080, 0.095, 0.125, 1.0)),
    "marking": make_mat("KHUM_vegas_cool_white_marking", (0.72, 0.82, 0.98, 1.0), emission=(0.36, 0.50, 0.78, 1.0), emission_strength=0.12),
    "taxi_yellow": make_mat("KHUM_vegas_muted_taxi_amber", (0.88, 0.67, 0.28, 1.0), emission=(0.65, 0.40, 0.08, 1.0), emission_strength=0.10),
    "building": make_mat("KHUM_vegas_building_graphite", (0.115, 0.135, 0.180, 1.0)),
    "building_dark": make_mat("KHUM_vegas_building_midnight", (0.060, 0.070, 0.095, 1.0)),
    "roof": make_mat("KHUM_vegas_roof_midnight", (0.028, 0.033, 0.048, 1.0)),
    "glass": make_mat("KHUM_vegas_glass_blue", (0.055, 0.120, 0.200, 1.0), roughness=0.35, emission=(0.020, 0.080, 0.160, 1.0), emission_strength=0.18),
    "window_cool": make_mat("KHUM_vegas_window_ice_blue", (0.50, 0.70, 1.00, 1.0), emission=(0.32, 0.58, 1.00, 1.0), emission_strength=1.35),
    "window_warm": make_mat("KHUM_vegas_window_warm", (1.00, 0.72, 0.35, 1.0), emission=(1.00, 0.42, 0.12, 1.0), emission_strength=0.65),
    "road_glow": make_mat("KHUM_vegas_road_glow", (0.45, 0.55, 0.72, 1.0), emission=(0.35, 0.48, 0.72, 1.0), emission_strength=0.55),
    "light": make_mat("KHUM_vegas_airfield_edge_light", (0.35, 0.70, 1.0, 1.0), emission=(0.22, 0.55, 1.0, 1.0), emission_strength=1.25),
    "beacon": make_mat("KHUM_vegas_teal_beacon", (0.12, 0.85, 0.78, 1.0), emission=(0.00, 0.75, 0.68, 1.0), emission_strength=1.4),
    "service": make_mat("KHUM_vegas_service_vehicle", (0.72, 0.48, 0.18, 1.0), emission=(0.32, 0.16, 0.02, 1.0), emission_strength=0.08),
    "emergency": make_mat("KHUM_vegas_emergency_vehicle", (0.65, 0.08, 0.12, 1.0), emission=(0.70, 0.03, 0.08, 1.0), emission_strength=0.35),
}


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for collection in list(bpy.data.collections):
        if collection.users == 0:
            bpy.data.collections.remove(collection)


def make_collection(name: str):
    coll = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if coll.name not in bpy.context.scene.collection.children:
        try:
            bpy.context.scene.collection.children.link(coll)
        except RuntimeError:
            pass
    return coll


def link_to(coll, obj):
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    # unlink from master collection if directly linked there, keeps hierarchy clean
    try:
        bpy.context.scene.collection.objects.unlink(obj)
    except RuntimeError:
        pass


def add_box(name: str, loc: tuple[float, float, float], scale: tuple[float, float, float], mat, coll=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    if coll:
        link_to(coll, obj)
    return obj


def add_plane_box(name: str, center: Vector, length: float, width: float, angle: float, mat, z: float, height: float = 0.08, coll=None):
    obj = add_box(name, (center.x, center.y, z), (length, width, height), mat, coll=coll)
    obj.rotation_euler[2] = angle
    return obj


def add_cylinder(name: str, loc, radius: float, depth: float, mat, vertices: int = 32, coll=None):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    obj = bpy.context.object
    obj.name = name
    if mat:
        obj.data.materials.append(mat)
    if coll:
        link_to(coll, obj)
    return obj


def add_text(name: str, text: str, loc, size: float, mat, rot_z: float = 0.0, coll=None):
    bpy.ops.object.text_add(location=loc, rotation=(math.radians(90), 0, rot_z))
    obj = bpy.context.object
    obj.name = name
    obj.data.body = text
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    obj.data.size = size
    obj.data.extrude = 0.02
    if mat:
        obj.data.materials.append(mat)
    if coll:
        link_to(coll, obj)
    return obj


def runway_vectors(runway):
    x1, y1 = lonlat_to_xy(runway["le_lon"], runway["le_lat"])
    x2, y2 = lonlat_to_xy(runway["he_lon"], runway["he_lat"])
    p1 = Vector((x1, y1, 0))
    p2 = Vector((x2, y2, 0))
    center = (p1 + p2) * 0.5
    direction = (p2 - p1).normalized()
    normal = Vector((-direction.y, direction.x, 0))
    angle = math.atan2(direction.y, direction.x)
    length = runway["length_ft"] * FT_TO_M
    width = runway["width_ft"] * FT_TO_M
    return p1, p2, center, direction, normal, angle, length, width


def build_runway(runway, coll):
    p1, p2, center, direction, normal, angle, length, width = runway_vectors(runway)
    add_plane_box(runway["name"], center, length, width, angle, MATS["runway"], z=0.03, height=0.10, coll=coll)

    # edge shoulders
    for side, offset in [("L", width / 2 + 5), ("R", -width / 2 - 5)]:
        add_plane_box(f"{runway['name']}_shoulder_{side}", center + normal * offset, length, 4, angle, MATS["asphalt"], z=0.025, height=0.06, coll=coll)

    # centerline dashes
    dash_len = 38
    gap = 42
    count = max(8, int(length // (dash_len + gap)))
    start = -((count - 1) * (dash_len + gap)) / 2
    for i in range(count):
        c = center + direction * (start + i * (dash_len + gap))
        add_plane_box(f"{runway['name']}_centerline_{i:02d}", c, dash_len, 1.4, angle, MATS["marking"], z=0.12, height=0.025, coll=coll)

    # threshold bars and runway numbers
    for ident, end, sign in [(runway["le_ident"], p1, 1), (runway["he_ident"], p2, -1)]:
        threshold_center = end + direction * sign * 60
        for j in range(-3, 4):
            if j == 0:
                continue
            add_plane_box(
                f"{runway['name']}_threshold_{ident}_{j}",
                threshold_center + normal * (j * width / 9),
                28,
                2.6,
                angle,
                MATS["marking"],
                z=0.13,
                height=0.025,
                coll=coll,
            )
        text_rot = angle if sign > 0 else angle + math.pi
        add_text(
            f"{runway['name']}_number_{ident}",
            ident,
            (threshold_center - direction * sign * 55).to_tuple(),
            size=22,
            mat=MATS["marking"],
            rot_z=text_rot,
            coll=coll,
        )

    # runway edge lights
    step = 125
    light_count = int(length // step)
    for i in range(light_count + 1):
        d = -length / 2 + i * step
        if abs(d) > length / 2:
            continue
        for side, offset in [("L", width / 2 + 8), ("R", -width / 2 - 8)]:
            pos = center + direction * d + normal * offset
            lamp = add_cylinder(f"{runway['name']}_edge_light_{side}_{i:02d}", (pos.x, pos.y, 0.45), 0.55, 0.9, MATS["light"], vertices=12, coll=coll)
            lamp.rotation_euler[0] = math.radians(90)


def build_taxiways_and_apron(runway_data, coll):
    # Main north/south runway and diagonal runway vectors.
    r12, r18 = runway_data[0], runway_data[1]
    _, _, c12, d12, n12, a12, l12, w12 = runway_vectors(r12)
    _, _, c18, d18, n18, a18, l18, w18 = runway_vectors(r18)

    # East-side parallel taxiway for 18/36.
    parallel_center = c18 + Vector((125, 0, 0))
    add_plane_box("Taxiway_A_parallel_18_36", parallel_center, l18 * 0.88, 18, a18, MATS["asphalt"], 0.07, 0.08, coll)
    # Connectors to 18/36.
    for idx, yoff in enumerate([-650, -250, 220, 650]):
        conn_center = Vector((62, yoff, 0))
        add_plane_box(f"Taxiway_A_connector_{idx+1}", conn_center, 125, 16, 0, MATS["asphalt"], 0.08, 0.08, coll)
        add_plane_box(f"Taxiway_A_connector_{idx+1}_yellow", conn_center, 125, 1.0, 0, MATS["taxi_yellow"], 0.15, 0.02, coll)

    # Crossfield taxiway/connector near runway intersection.
    add_plane_box("Taxiway_B_to_12_30", c12 + Vector((70, -25, 0)), l12 * 0.62, 16, a12, MATS["asphalt"], 0.08, 0.08, coll)
    for i in range(16):
        pos = c12 + d12 * (-l12 * 0.28 + i * (l12 * 0.56 / 15)) + Vector((70, -25, 0))
        add_plane_box(f"Taxiway_B_centerline_{i:02d}", pos, 18, 0.75, a12, MATS["taxi_yellow"], 0.16, 0.02, coll)

    # FBO/ramp/apron on the east side, stylized but placed relative to real field.
    apron_center = Vector((310, 120, 0))
    add_plane_box("FBO_Apron_Main", apron_center, 420, 230, math.radians(2), MATS["apron"], 0.06, 0.08, coll)
    add_plane_box("FBO_Apron_Taxi_Line_NS", apron_center + Vector((-80, 0, 0)), 180, 1.2, math.radians(90), MATS["taxi_yellow"], 0.14, 0.02, coll)
    add_plane_box("FBO_Apron_Taxi_Line_EW", apron_center + Vector((5, -5, 0)), 310, 1.2, math.radians(0), MATS["taxi_yellow"], 0.14, 0.02, coll)

    # Parking stand markings.
    for i, x in enumerate([190, 250, 310, 370, 430]):
        add_plane_box(f"Ramp_parking_T_{i+1}_stem", Vector((x, 40, 0)), 52, 0.9, math.radians(90), MATS["taxi_yellow"], 0.15, 0.02, coll)
        add_plane_box(f"Ramp_parking_T_{i+1}_bar", Vector((x, 65, 0)), 34, 0.9, 0, MATS["taxi_yellow"], 0.15, 0.02, coll)

    # Service road / entry stripe, maintaining demo's graphic style.
    add_plane_box("Airport_service_road", Vector((470, -40, 0)), 310, 10, math.radians(80), MATS["asphalt"], 0.05, 0.06, coll)


def add_window_grid(
    coll,
    prefix: str,
    center_x: float,
    face_y: float,
    base_z: float,
    width: float,
    height: float,
    columns: int,
    rows: int,
    warm_every: int = 5,
):
    """Add tiny emissive window tiles like the Vegas city GLB."""

    if columns <= 0 or rows <= 0:
        return
    x_step = width / columns
    z_step = height / rows
    tile_w = min(3.2, x_step * 0.42)
    tile_h = min(2.4, z_step * 0.42)
    for row in range(rows):
        for col in range(columns):
            # Deterministic sparse pattern; avoids every window being lit.
            if (row * 7 + col * 3 + len(prefix)) % 4 == 0:
                continue
            x = center_x - width / 2 + x_step * (col + 0.5)
            z = base_z + z_step * (row + 0.5)
            mat = MATS["window_warm"] if (row + col) % warm_every == 0 else MATS["window_cool"]
            add_box(f"{prefix}_window_{row:02d}_{col:02d}", (x, face_y, z), (tile_w, 0.24, tile_h), mat, coll)


def add_roof_cap(name: str, x: float, y: float, z: float, sx: float, sy: float, coll):
    roof = add_box(name, (x, y, z), (sx, sy, 4), MATS["roof"], coll)
    roof.rotation_euler[2] = math.radians(1.5)
    return roof


def build_buildings(coll):
    # Terminal/FBO complex and hangars, reshaped to the Vegas blockout language:
    # dark extruded forms, stacked roof caps, and many cool pinprick windows.
    add_box("KHUM_FBO_terminal", (390, 245, 14), (126, 44, 28), MATS["building"], coll)
    add_box("KHUM_FBO_terminal_stepback", (390, 248, 34), (92, 36, 14), MATS["building_dark"], coll)
    add_roof_cap("KHUM_FBO_terminal_roof", 390, 245, 45, 142, 58, coll)
    add_box("KHUM_FBO_glass_front", (390, 222.5, 18), (112, 1.2, 22), MATS["glass"], coll)
    add_window_grid(coll, "KHUM_FBO_terminal", 390, 221.6, 8, 110, 27, 11, 4)

    hangars = [
        ("KHUM_hangar_west", 210, 255, 96, 78, 34, 6, 4),
        ("KHUM_hangar_mid", 310, 270, 86, 70, 30, 5, 4),
        ("KHUM_hangar_east", 515, 250, 112, 84, 38, 7, 5),
        ("KHUM_maintenance_hangar", 520, 115, 84, 64, 26, 5, 3),
    ]
    for name, x, y, sx, sy, sz, cols, rows in hangars:
        add_box(name, (x, y, sz / 2), (sx, sy, sz), MATS["building"], coll)
        add_box(name + "_upper_block", (x + sx * 0.12, y + sy * 0.08, sz + 7), (sx * 0.56, sy * 0.54, 14), MATS["building_dark"], coll)
        add_roof_cap(name + "_roof", x, y, sz + 17, sx + 10, sy + 10, coll)
        add_box(name + "_door_glass", (x, y - sy / 2 - 0.7, sz * 0.48), (sx * 0.68, 1.4, sz * 0.62), MATS["glass"], coll)
        add_window_grid(coll, name, x, y - sy / 2 - 1.55, 6, sx * 0.72, sz * 0.75, cols, rows)

    # Add a few low airport-office blocks so the ramp reads as a small glowing campus.
    office_blocks = [
        ("KHUM_ops_office_1", 620, 180, 78, 52, 24, 6, 3),
        ("KHUM_ops_office_2", 125, 150, 64, 46, 20, 5, 3),
        ("KHUM_fire_station", 610, 55, 70, 42, 20, 5, 3),
    ]
    for name, x, y, sx, sy, sz, cols, rows in office_blocks:
        add_box(name, (x, y, sz / 2), (sx, sy, sz), MATS["building_dark"], coll)
        add_roof_cap(name + "_roof", x, y, sz + 4, sx + 8, sy + 8, coll)
        add_window_grid(coll, name, x, y - sy / 2 - 1.2, 5, sx * 0.75, sz * 0.7, cols, rows, warm_every=6)

    # Tower and beacon with teal Vegas accent.
    add_cylinder("KHUM_control_tower_stem", (555, -20, 28), 7, 56, MATS["building_dark"], vertices=16, coll=coll)
    add_box("KHUM_control_tower_cab", (555, -20, 63), (36, 36, 14), MATS["glass"], coll)
    add_window_grid(coll, "KHUM_tower_cab", 555, -38.2, 58, 30, 10, 5, 2, warm_every=7)
    add_cylinder("KHUM_rotating_beacon", (555, -20, 75), 4, 4, MATS["beacon"], vertices=16, coll=coll)

    # Small stylized aircraft / ground vehicles for scale and activity.
    for i, (x, y, rot) in enumerate([(245, 70, 15), (320, 58, -8), (400, 70, 5)]):
        plane = add_box(f"KHUM_static_aircraft_{i+1}_fuselage", (x, y, 4), (34, 5, 5), MATS["marking"], coll)
        plane.rotation_euler[2] = math.radians(rot)
        wing = add_box(f"KHUM_static_aircraft_{i+1}_wing", (x, y, 4.4), (7, 34, 1.2), MATS["marking"], coll)
        wing.rotation_euler[2] = math.radians(rot)
        tail = add_box(f"KHUM_static_aircraft_{i+1}_tail", (x - 14 * math.cos(math.radians(rot)), y - 14 * math.sin(math.radians(rot)), 7), (4, 10, 6), MATS["marking"], coll)
        tail.rotation_euler[2] = math.radians(rot)

    for i, (x, y, mat) in enumerate([(450, 80, MATS["service"]), (485, 35, MATS["service"]), (510, -5, MATS["emergency"])]):
        add_box(f"KHUM_ops_vehicle_{i+1}", (x, y, 2.1), (16, 7, 4.2), mat, coll)
        add_box(f"KHUM_ops_vehicle_{i+1}_cab", (x + 4, y, 5.0), (7, 6, 3), mat, coll)

def build_landscape(coll):
    add_box("KHUM_airport_terrain_tile", (0, 0, -0.08), (2500, 2500, 0.12), MATS["ground"], coll)

    # Vegas-style surrounding blocks: dark parcels instead of bright grass, with
    # thin icy service-road highlights to visually connect airport and city scenes.
    patches = [
        (-780, 420, 300, 160, 12, MATS["field_block"]),
        (-620, -520, 360, 190, -18, MATS["field_block_alt"]),
        (720, -570, 340, 160, 25, MATS["field_block"]),
        (820, 520, 290, 180, -8, MATS["field_block_alt"]),
        (80, 820, 470, 120, 4, MATS["field_block"]),
        (-160, -850, 520, 130, -6, MATS["field_block_alt"]),
        (760, 130, 360, 95, 7, MATS["field_block"]),
        (-920, -60, 260, 130, -3, MATS["field_block_alt"]),
    ]
    for i, (x, y, sx, sy, rot, mat) in enumerate(patches):
        add_plane_box(f"KHUM_night_land_parcel_{i+1}", Vector((x, y, 0)), sx, sy, math.radians(rot), mat, 0.0, 0.025, coll)

    # Road grid around the airport, matching the Vegas glowing arterial lines.
    road_specs = [
        ("KHUM_outer_service_road_n", 0, 1000, 1700, 7, 0),
        ("KHUM_outer_service_road_s", 0, -1000, 1700, 7, 0),
        ("KHUM_outer_service_road_e", 980, 0, 1700, 7, 90),
        ("KHUM_outer_service_road_w", -980, 0, 1700, 7, 90),
        ("KHUM_fbo_access_glow", 520, 115, 520, 6, 82),
        ("KHUM_terminal_access_glow", 285, 330, 430, 5, 5),
    ]
    for name, x, y, length, width, rot in road_specs:
        add_plane_box(name, Vector((x, y, 0)), length, width, math.radians(rot), MATS["road_glow"], 0.09, 0.018, coll)

    # Low surrounding warehouse/city blocks echo the Vegas asset's field of
    # extruded rectangles with pinprick blue windows. They are intentionally
    # secondary to the airfield but remove the bright-green/empty-airport feel.
    blocks = [
        (-760, 760, 90, 70, 32, 5, 3),
        (-610, 825, 120, 80, 42, 7, 4),
        (-430, 765, 72, 58, 28, 4, 3),
        (650, 760, 110, 75, 36, 6, 3),
        (810, 720, 86, 66, 30, 5, 3),
        (-780, -780, 105, 82, 34, 6, 3),
        (-610, -830, 76, 58, 26, 4, 3),
        (650, -760, 112, 84, 38, 6, 4),
        (825, -820, 95, 70, 32, 5, 3),
        (-1080, 280, 80, 64, 28, 4, 3),
        (-1100, -250, 105, 72, 36, 6, 3),
        (1090, 310, 92, 68, 30, 5, 3),
        (1080, -290, 118, 76, 38, 7, 3),
    ]
    for i, (x, y, sx, sy, sz, cols, rows) in enumerate(blocks):
        name = f"KHUM_surrounding_night_block_{i+1}"
        add_box(name, (x, y, sz / 2), (sx, sy, sz), MATS["building_dark"], coll)
        add_box(name + "_roof", (x, y, sz + 2.5), (sx + 8, sy + 8, 5), MATS["roof"], coll)
        add_window_grid(coll, name, x, y - sy / 2 - 1.1, 5, sx * 0.72, sz * 0.70, cols, rows, warm_every=8)

def setup_camera_and_lights():
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 800))
    sun = bpy.context.object
    sun.name = "KHUM_sun_key"
    sun.data.energy = 1.1
    sun.rotation_euler = (math.radians(42), 0, math.radians(-35))

    bpy.ops.object.light_add(type="AREA", location=(120, -260, 420))
    area = bpy.context.object
    area.name = "KHUM_vegas_softbox_blue"
    area.data.energy = 450
    area.data.size = 900

    camera_location = Vector((820, -1180, 830))
    camera_target = Vector((35, -25, 0))
    bpy.ops.object.camera_add(location=camera_location)
    camera = bpy.context.object
    bpy.context.scene.camera = camera
    camera.name = "KHUM_overview_camera"
    camera.rotation_euler = (camera_target - camera_location).to_track_quat("-Z", "Y").to_euler()
    camera.data.lens = 24
    camera.data.clip_end = 6000
    camera.data.dof.use_dof = False

    bpy.context.scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
    bpy.context.scene.render.resolution_x = 1920
    bpy.context.scene.render.resolution_y = 1080
    bpy.context.scene.view_settings.view_transform = "Filmic"
    bpy.context.scene.view_settings.look = "Medium High Contrast"
    bpy.context.scene.view_settings.exposure = -0.45
    bpy.context.scene.view_settings.gamma = 1


def build_scene():
    clear_scene()
    bpy.context.scene.name = "KHUM_Houma_Terrebonne_Airport"
    coll = make_collection("KHUM_Airport_Model")

    build_landscape(coll)
    for runway in RUNWAYS:
        build_runway(runway, coll)
    build_taxiways_and_apron(RUNWAYS, coll)
    build_buildings(coll)
    add_text("KHUM_scene_label", "KHUM / Houma-Terrebonne Airport", (0, -1080, 2), 42, MATS["marking"], rot_z=0, coll=coll)
    setup_camera_and_lights()

    # Set origin/metadata for frontend integration.
    bpy.context.scene["airport_ident"] = "KHUM"
    bpy.context.scene["center_lat"] = KHUM_CENTER_LAT
    bpy.context.scene["center_lon"] = KHUM_CENTER_LON
    bpy.context.scene["units"] = "meters; X=east, Y=north"

    # Select all KHUM objects for export.
    bpy.ops.object.select_all(action="DESELECT")
    for obj in coll.objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = next(iter(coll.objects), None)

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(EXPORT_BLEND))
    bpy.ops.export_scene.gltf(
        filepath=str(EXPORT_GLB),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
        export_materials="EXPORT",
    )
    return {
        "blend": str(EXPORT_BLEND),
        "glb": str(EXPORT_GLB),
        "object_count": len(coll.objects),
        "runways": [r["name"] for r in RUNWAYS],
    }


if __name__ == "__main__":
    result = build_scene()
    print("KHUM_BUILD_RESULT", result)
