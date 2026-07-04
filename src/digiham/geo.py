"""Maidenhead locator maths: grid <-> lat/lon, great-circle distance & bearing.

Used to annotate decodes with distance and beam heading, and by the polar
decode map. Everything is plain trigonometry with no dependencies beyond
the standard library.
"""

from __future__ import annotations

import math
from typing import Optional

_A = ord("A")


def grid_to_latlon(grid: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for the centre of a 4- or 6-char Maidenhead grid."""
    g = grid.strip().upper()
    if len(g) < 4:
        return None
    try:
        lon = (ord(g[0]) - _A) * 20 - 180
        lat = (ord(g[1]) - _A) * 10 - 90
        lon += int(g[2]) * 2
        lat += int(g[3]) * 1
        if len(g) >= 6 and g[4].isalpha() and g[5].isalpha():
            lon += (ord(g[4]) - _A) * (2 / 24) + (1 / 24)
            lat += (ord(g[5]) - _A) * (1 / 24) + (0.5 / 24)
        else:
            lon += 1.0        # centre of the 2-degree square
            lat += 0.5
    except (ValueError, IndexError):
        return None
    return lat, lon


def latlon_to_grid(lat: float, lon: float, precision: int = 6) -> str:
    """Encode lat/lon to a Maidenhead locator (4 or 6 chars)."""
    lon += 180
    lat += 90
    field_lon = int(lon // 20)
    field_lat = int(lat // 10)
    out = chr(_A + field_lon) + chr(_A + field_lat)
    out += str(int((lon % 20) // 2)) + str(int((lat % 10) // 1))
    if precision >= 6:
        out += chr(_A + int((lon % 2) / (2 / 24)))
        out += chr(_A + int((lat % 1) / (1 / 24)))
    return out


def distance_bearing(grid_a: str, grid_b: str) -> Optional[tuple[float, float]]:
    """Great-circle distance (km) and initial bearing (deg) from A to B."""
    a = grid_to_latlon(grid_a)
    b = grid_to_latlon(grid_b)
    if a is None or b is None:
        return None
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlon = lon2 - lon1
    # haversine distance
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    dist = 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))
    # initial bearing
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return dist, bearing


def short_distance(km: float) -> str:
    if km >= 1000:
        return f"{km/1000:.1f}k"
    return f"{km:.0f}"
