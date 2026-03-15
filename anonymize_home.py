#!/usr/bin/env python3
"""Anonymize home-area location data by snapping nearby points to a safe city-center coordinate.

Replaces precise GPS near home with a general Detroit city-center point, and trims
road route segments so they don't extend into the home neighborhood.
"""

import json
from math import radians, sin, cos, sqrt, atan2

# Safe public landmark: Detroit city center (Campus Martius Park)
SAFE_POINT = {"lat": 42.3314, "lng": -83.0458}

# Any point within this radius (miles) of the home cluster gets anonymized
ANONYMIZE_RADIUS_MI = 5.0

# Home-area cluster centers (detected from the data)
HOME_CLUSTERS = [
    {"lat": 42.282, "lng": -83.149},  # Trip start area
    {"lat": 42.381, "lng": -82.940},  # Trip end area
    {"lat": 42.379, "lng": -82.947},  # Overnight return
]

ROUTE_FILE = "nola_2024_viz/src/lib/data/route.json"
TRACKS_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
ROAD_ROUTE_FILE = "nola_2024_viz/src/lib/data/road_route.json"
WAYPOINTS_FILE = "nola_2024_viz/src/lib/data/photo_waypoints.json"


def haversine_miles(lat1, lng1, lat2, lng2):
    R = 3959
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def is_near_home(lat, lng):
    """Check if a point is within the anonymize radius of any home cluster."""
    for h in HOME_CLUSTERS:
        if haversine_miles(lat, lng, h["lat"], h["lng"]) < ANONYMIZE_RADIUS_MI:
            return True
    return False


def anonymize_route(filepath):
    """Remove home-area waypoints from the photo route."""
    with open(filepath) as f:
        route = json.load(f)

    before = len(route)
    route = [p for p in route if not is_near_home(p["lat"], p["lng"])]
    after = len(route)

    with open(filepath, "w") as f:
        json.dump(route, f, indent=2)

    print(f"  route.json: {before} → {after} waypoints ({before - after} removed)")


def anonymize_waypoints(filepath):
    """Remove home-area waypoints from photo waypoints."""
    with open(filepath) as f:
        waypoints = json.load(f)

    before = len(waypoints)
    waypoints = [p for p in waypoints if not is_near_home(p["lat"], p["lng"])]
    after = len(waypoints)

    with open(filepath, "w") as f:
        json.dump(waypoints, f, indent=2)

    print(f"  photo_waypoints.json: {before} → {after} waypoints ({before - after} removed)")


def anonymize_tracks(filepath):
    """Snap home-area track locations to the safe city-center point."""
    with open(filepath) as f:
        tracks = json.load(f)

    moved = 0
    for t in tracks:
        if t.get("lat") and t.get("lng") and is_near_home(t["lat"], t["lng"]):
            t["lat"] = SAFE_POINT["lat"]
            t["lng"] = SAFE_POINT["lng"]
            t["locationConfidence"] = "low"
            t["locationType"] = "anonymized"
            moved += 1

    with open(filepath, "w") as f:
        json.dump(tracks, f, indent=2)

    print(f"  trip_tracks.json: {moved} tracks moved to city center")


def anonymize_road_route(filepath):
    """Trim road route segments that start/end in home area."""
    with open(filepath) as f:
        segments = json.load(f)

    total_removed = 0

    for i, seg in enumerate(segments):
        # Trim from the start
        trim_start = 0
        for j, p in enumerate(seg):
            if is_near_home(p["lat"], p["lng"]):
                trim_start = j + 1
            else:
                break

        # Trim from the end
        trim_end = len(seg)
        for j in range(len(seg) - 1, -1, -1):
            if is_near_home(seg[j]["lat"], seg[j]["lng"]):
                trim_end = j
            else:
                break

        if trim_start > 0 or trim_end < len(seg):
            before = len(seg)
            # Keep at least 2 points, replace start/end with safe point
            new_seg = seg[trim_start:trim_end]
            if new_seg:
                # Prepend/append safe point so the route still connects
                if trim_start > 0:
                    new_seg.insert(0, SAFE_POINT)
                if trim_end < len(seg):
                    new_seg.append(SAFE_POINT)
            removed = before - len(new_seg)
            total_removed += max(0, removed)
            segments[i] = new_seg

    # Remove empty segments
    segments = [s for s in segments if len(s) >= 2]

    with open(filepath, "w") as f:
        json.dump(segments, f)

    print(f"  road_route.json: {total_removed} points trimmed from home-area segments")


def main():
    print(f"Anonymizing home area (radius: {ANONYMIZE_RADIUS_MI} mi)")
    print(f"Safe point: {SAFE_POINT['lat']}, {SAFE_POINT['lng']} (Detroit city center)\n")

    anonymize_route(ROUTE_FILE)
    anonymize_waypoints(WAYPOINTS_FILE)
    anonymize_tracks(TRACKS_FILE)
    anonymize_road_route(ROAD_ROUTE_FILE)

    print("\nDone! Home-area data has been anonymized.")
    print("Note: Re-run snap_tracks_to_route.py if you want tracks re-snapped to the trimmed route.")


if __name__ == "__main__":
    main()
