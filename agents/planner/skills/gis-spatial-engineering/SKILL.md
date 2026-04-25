---
name: gis-spatial-engineering
description: >
  Use when the marathon plan needs a 26.2-mile physical route generated
  from road-network GeoJSON, or when the request mentions traffic
  impact, route variety via seed, finishing landmarks, or the
  zone-sweep algorithm. Triggered by route-planning or
  traffic-analysis language.
license: Apache-2.0
metadata:
  adk_additional_tools:
    - plan_marathon_route
    - report_marathon_route
    - assess_traffic_impact
---

# GIS Spatial Engineering

You use this skill to generate the physical path of the marathon.

## Geographic Context (Built-in Data)
You have access to a road network GeoJSON located at `assets/network.json`.
Key features available in this network include:
- **Landmarks**: Point features with `properties.name` (e.g., Mandalay Bay,
  Bellagio, Sphere, Las Vegas Sign, Allegiant Stadium, The Venetian,
  Michelob Ultra Arena, etc.).
  These landmarks are used automatically by `plan_marathon_route()` to build the route.
- **Named Roads**: All 34 LineString features have `properties.name` (e.g.,
  Las Vegas Boulevard, Las Vegas Freeway, Sahara Avenue, Flamingo Road,
  Rainbow Boulevard, Paradise Road, Sunset Road, Tropicana Avenue,
  Desert Inn Road, Eastern Avenue, Maryland Parkway, etc.).

## Algorithm

The default algorithm is **zone-sweep**: the route starts at the Las Vegas Sign,
goes northbound on the Strip past MGM Grand, sweeps through city zones
(neighborhoods) using non-crossing geometry, and finishes near a prominent
landmark (e.g., Michelob Ultra Arena). The algorithm handles all route geometry
automatically — you do not need to select petals or manually sequence landmarks.

## Instructions

1. **Just call it**: `plan_marathon_route()` with no arguments produces a valid
   26.2-mile zone-sweep route. Use `finish_landmark` and `seed` for variety.
2. **Precision**: The tool uses interpolation to guarantee exactly 26.2 miles.
3. **GeoJSON**: Input must be valid road network GeoJSON.

## Tools

- `plan_marathon_route(finish_landmark: Optional[str] = None, seed: Optional[int] = None, geojson_data: Optional[str] = None)`:
  Generate the exact 26.2-mile path.
  - `finish_landmark`: Name of a landmark to finish near (e.g., `"Michelob Ultra Arena"`).
  - `seed`: Integer seed for route variety. Different seeds produce different routes.
- `report_marathon_route(route_geojson: dict)`: Emit the final GeoJSON to the system registry.

### Decision-Making Guidance
- For most requests, call `plan_marathon_route()` with default arguments.
- Use `seed` to generate alternative routes when the user wants variety.
- Use `finish_landmark` when the user specifies a preferred finishing area.
