"""Geometry helpers for WGS84 points over short distances.

The plots are under 100 m across, so a flat local projection is accurate
enough for bearings and offsets.
"""

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1, lon1, lat2, lon2):
    """Return the great circle distance in metres between two points."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (
        np.sin((lat2 - lat1) / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def to_local_xy(lat, lon, lat0, lon0):
    """Project points to metres around (lat0, lon0).

    Uses an equirectangular projection. x points east and y points north.
    """
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    x = np.radians(lon - lon0) * EARTH_RADIUS_M * np.cos(np.radians(lat0))
    y = np.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def bearing_deg(lat1, lon1, lat2, lon2):
    """Return the bearing from point 1 to point 2.

    The bearing is in degrees, measured clockwise from north.
    """
    x, y = to_local_xy(lat2, lon2, lat1, lon1)
    return np.degrees(np.arctan2(x, y)) % 360


def axis_deviation_from_ns(bearing):
    """Return the angle between a bearing and the north/south axis.

    The result is between 0 and 90 degrees.
    """
    b = np.asarray(bearing, float) % 180
    return np.minimum(b, 180 - b)


def project_on_line(lat, lon, a_lat, a_lon, b_lat, b_lon):
    """Locate points relative to the line that goes from A to B.

    Returns (along, offset) in metres. along is the distance from A
    measured in the direction of B. offset is the perpendicular distance,
    positive on the right side when walking from A to B.
    """
    bx, by = to_local_xy(b_lat, b_lon, a_lat, a_lon)
    px, py = to_local_xy(lat, lon, a_lat, a_lon)
    length = np.hypot(bx, by)
    ux, uy = bx / length, by / length
    along = px * ux + py * uy
    offset = px * uy - py * ux
    return along, offset


def parse_odk_geometry(s):
    """Parse an ODK geometry string into (lat, lon, alt, acc).

    The string holds up to four numbers separated by spaces. Missing or
    empty values become NaN.
    """
    if not isinstance(s, str) or not s.strip():
        return (np.nan,) * 4
    parts = [float(p) for p in s.split()]
    return tuple(parts + [np.nan] * (4 - len(parts)))[:4]
