#!/usr/bin/env python3
"""Snap photo waypoints to actual roads using OSRM public API.

Breaks the trip into driving segments (between stationary periods),
routes each segment via OSRM, then stitches into a single road-snapped route.
"""

import json
import urllib.request
import time
from math import radians, sin, cos, sqrt, atan2

INPUT = "nola_2024_viz/src/lib/data/route.json"
OUTPUT = "nola_2024_viz/src/lib/data/road_route.json"

STATIONARY_THRESHOLD_MILES = 2.0  # points closer than this are "same place"
OSRM_MAX_COORDS = 80  # stay well under the 100-point limit


def haversine_miles(lat1, lng1, lat2, lng2):
    R = 3959
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def split_into_segments(route):
    """Split the route into driving segments by detecting stationary clusters.

    Returns list of segments, each a list of waypoints. Stationary clusters
    become single-point segments, driving portions stay as multi-point segments.
    """
    if not route:
        return []

    segments = []
    current_seg = [route[0]]

    for i in range(1, len(route)):
        prev = current_seg[-1]
        curr = route[i]
        dist = haversine_miles(prev["lat"], prev["lng"], curr["lat"], curr["lng"])
        time_gap_hrs = (curr["timestamp_unix"] - prev["timestamp_unix"]) / 3600

        # Start new segment if big time gap (>8 hours, e.g., overnight)
        if time_gap_hrs > 8:
            segments.append(current_seg)
            current_seg = [curr]
        else:
            current_seg.append(curr)

    if current_seg:
        segments.append(current_seg)

    return segments


def sample_segment(segment, max_points=OSRM_MAX_COORDS):
    """Downsample a segment to fit OSRM limits while keeping first, last, and key turns."""
    if len(segment) <= max_points:
        return segment

    # Always keep first and last
    step = len(segment) / (max_points - 1)
    indices = [int(i * step) for i in range(max_points - 1)] + [len(segment) - 1]
    indices = sorted(set(indices))
    return [segment[i] for i in indices]


def osrm_route(waypoints):
    """Get road-snapped route between waypoints using OSRM."""
    if len(waypoints) < 2:
        return [[wp["lng"], wp["lat"]] for wp in waypoints]

    # Build coordinate string: lng,lat;lng,lat;...
    coords = ";".join(f"{wp['lng']},{wp['lat']}" for wp in waypoints)
    url = (f"https://router.project-osrm.org/route/v1/driving/{coords}"
           f"?overview=full&geometries=geojson")

    req = urllib.request.Request(url, headers={"User-Agent": "RoadTripViz/1.0"})

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())

        if data["code"] == "Ok" and data["routes"]:
            return data["routes"][0]["geometry"]["coordinates"]
        else:
            print(f"    OSRM returned: {data['code']}")
            return [[wp["lng"], wp["lat"]] for wp in waypoints]
    except Exception as e:
        print(f"    OSRM error: {e}")
        return [[wp["lng"], wp["lat"]] for wp in waypoints]


def main():
    with open(INPUT) as f:
        route = json.load(f)

    print(f"Input: {len(route)} waypoints")

    # Split into segments
    segments = split_into_segments(route)
    print(f"Split into {len(segments)} segments")

    # Route each segment through OSRM
    all_road_coords = []  # list of segments, each a list of [lng, lat]
    total_road_points = 0

    for i, seg in enumerate(segments):
        # Skip tiny segments (stationary, < 2 miles total)
        if len(seg) >= 2:
            total_dist = sum(
                haversine_miles(seg[j]["lat"], seg[j]["lng"], seg[j+1]["lat"], seg[j+1]["lng"])
                for j in range(len(seg) - 1)
            )
        else:
            total_dist = 0

        start_ts = seg[0]["timestamp"][:16]
        end_ts = seg[-1]["timestamp"][:16]

        # Bridge gap from previous segment to this one
        if i > 0 and all_road_coords and all_road_coords[-1]:
            prev_last = all_road_coords[-1][-1]  # [lng, lat]
            curr_first_lat = seg[0]["lat"]
            curr_first_lng = seg[0]["lng"]
            bridge_dist = haversine_miles(prev_last[1], prev_last[0], curr_first_lat, curr_first_lng)

            if bridge_dist > 1.0:
                print(f"  Bridge: {bridge_dist:.1f} mi gap between seg {i} and {i+1}")
                bridge_wps = [
                    {"lat": prev_last[1], "lng": prev_last[0]},
                    {"lat": curr_first_lat, "lng": curr_first_lng},
                ]
                bridge_coords = osrm_route(bridge_wps)
                if bridge_coords and len(bridge_coords) > 1:
                    # Append bridge to previous segment (skip first point, it's a dupe)
                    all_road_coords[-1].extend(bridge_coords[1:])
                    total_road_points += len(bridge_coords) - 1
                time.sleep(0.5)

        if total_dist < 1.0 or len(seg) < 2:
            # Stationary — just use the centroid as a point
            lat = sum(p["lat"] for p in seg) / len(seg)
            lng = sum(p["lng"] for p in seg) / len(seg)
            print(f"  Seg {i+1}: stationary ({len(seg)} pts, {total_dist:.1f} mi) {start_ts}")
            all_road_coords.append([[lng, lat]])
            total_road_points += 1
            continue

        # For longer driving segments, may need to batch OSRM calls
        sampled = sample_segment(seg)
        print(f"  Seg {i+1}: driving ({len(seg)} pts → {len(sampled)} sampled, {total_dist:.1f} mi) {start_ts} → {end_ts}")

        # Batch into sub-requests if still too many points
        road_coords = []
        batch_size = OSRM_MAX_COORDS
        for b in range(0, len(sampled), batch_size - 1):  # overlap by 1 for continuity
            batch = sampled[b:b + batch_size]
            if len(batch) < 2:
                road_coords.extend([[p["lng"], p["lat"]] for p in batch])
                continue

            coords = osrm_route(batch)
            if road_coords and coords:
                # Skip first point of new batch (overlap)
                coords = coords[1:]
            road_coords.extend(coords)

            # Be nice to the public API
            time.sleep(0.5)

        all_road_coords.append(road_coords)
        total_road_points += len(road_coords)

    # Build output: list of segments, each as a list of {lat, lng} for the frontend
    output = []
    for seg_coords in all_road_coords:
        output.append([{"lat": c[1], "lng": c[0]} for c in seg_coords])

    with open(OUTPUT, "w") as f:
        json.dump(output, f)

    print(f"\nDone! {total_road_points} road points across {len(output)} segments → {OUTPUT}")
    # Also print file size
    import os
    size_kb = os.path.getsize(OUTPUT) / 1024
    print(f"File size: {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
