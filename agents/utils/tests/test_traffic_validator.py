# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for ``validate_route_geojson``.

Single chokepoint shape validator used at wire boundaries to reject
route_geojson values whose shape would crash downstream traffic helpers
(specifically ``build_segment_distance_index`` and
``identify_closed_segments``, which iterate features and call ``.get()``
on each).
"""

from __future__ import annotations

import json

from agents.utils.traffic import validate_route_geojson


def _good_route() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Strip"},
                "geometry": {"type": "LineString", "coordinates": [[-115.17, 36.08]]},
            }
        ],
    }


def test_validator_accepts_well_formed_feature_collection():
    ok, msg = validate_route_geojson(_good_route())
    assert ok is True
    assert msg == ""


def test_validator_accepts_empty_features_list():
    ok, msg = validate_route_geojson({"type": "FeatureCollection", "features": []})
    assert ok is True


def test_validator_rejects_non_dict_route():
    ok, msg = validate_route_geojson("not a dict")  # type: ignore[arg-type]
    assert ok is False
    assert "dict" in msg.lower()


def test_validator_rejects_features_not_a_list():
    ok, msg = validate_route_geojson({"type": "FeatureCollection", "features": "oops"})
    assert ok is False
    assert "list" in msg.lower()


def test_validator_rejects_stringified_features():
    """The exact production failure shape: each feature is a JSON-encoded string."""
    good = _good_route()
    bad = {
        "type": "FeatureCollection",
        "features": [json.dumps(f) for f in good["features"]],
    }
    ok, msg = validate_route_geojson(bad)
    assert ok is False
    assert "feature" in msg.lower()


def test_validator_pinpoints_first_bad_feature_index():
    bad = {
        "type": "FeatureCollection",
        "features": [_good_route()["features"][0], "stringified-feature"],
    }
    ok, msg = validate_route_geojson(bad)
    assert ok is False
    assert "features[1]" in msg


def test_validator_accepts_missing_features_key():
    """Missing 'features' is allowed; downstream consumers handle it gracefully."""
    ok, msg = validate_route_geojson({"type": "FeatureCollection"})
    assert ok is True
    assert msg == ""
