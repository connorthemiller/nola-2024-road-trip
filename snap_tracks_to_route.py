#!/usr/bin/env python3
"""Snap track marker positions to the nearest point on the road-snapped route.

For stationary clusters, spreads markers along a short stretch of route
so they don't all pile on top of each other.
"""

import json
from math import radians, sin, cos, sqrt, atan2

ROAD_ROUTE = "nola_2024_viz/src/lib/data/road_route.json"
TRACKS = "nola_2024_viz/src/lib/data/trip_tracks.json"
OUTPUT = "nola_2024_viz/src/lib/data/trip_tracks.json"


def haversine_miles(lat1, lng1, lat2, lng2):
    R = 3959
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def sq_dist(lat1, lng1, lat2, lng2):
    """Fast squared distance for comparison (no need for actual haversine when just comparing)."""
    dlat = lat1 - lat2
    dlng = (lng1 - lng2) * cos(radians((lat1 + lat2) / 2))
    return dlat * dlat + dlng * dlng


def point_to_segment_nearest(px, py, ax, ay, bx, by):
    """Find the closest point on segment AB to point P. Returns (lat, lng, sq_distance)."""
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy

    if len_sq == 0:
        return ax, ay, sq_dist(px, py, ax, ay)

    # Project P onto AB, clamped to [0,1]
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy

    return proj_x, proj_y, sq_dist(px, py, proj_x, proj_y)


def build_route_index(road_route):
    """Flatten all segments into a single list of consecutive line segments with cumulative distance.

    Returns:
        segments: list of (lat1, lng1, lat2, lng2, cum_dist_start, cum_dist_end, seg_idx)
        total_distance: total route distance in degrees (approximate)
    """
    segments = []
    cum_dist = 0.0

    for seg_idx, segment in enumerate(road_route):
        for i in range(len(segment) - 1):
            p1 = segment[i]
            p2 = segment[i + 1]
            d = sqrt(sq_dist(p1["lat"], p1["lng"], p2["lat"], p2["lng"]))
            segments.append((
                p1["lat"], p1["lng"],
                p2["lat"], p2["lng"],
                cum_dist,
                cum_dist + d,
                seg_idx,
            ))
            cum_dist += d

    return segments, cum_dist


def snap_to_route(lat, lng, route_segments):
    """Find the nearest point on the route to a given lat/lng.

    Returns (snapped_lat, snapped_lng, route_position) where route_position
    is a 0-1 value representing how far along the total route this point is.
    """
    best_dist = float('inf')
    best_lat = lat
    best_lng = lng
    best_pos = 0

    for (lat1, lng1, lat2, lng2, cum_start, cum_end, _) in route_segments:
        proj_lat, proj_lng, d = point_to_segment_nearest(lat, lng, lat1, lng1, lat2, lng2)
        if d < best_dist:
            best_dist = d
            best_lat = proj_lat
            best_lng = proj_lng
            # Interpolate position along this segment
            seg_len = cum_end - cum_start
            if seg_len > 0:
                local_d = sqrt(sq_dist(lat1, lng1, proj_lat, proj_lng))
                best_pos = cum_start + local_d
            else:
                best_pos = cum_start

    return best_lat, best_lng, best_pos


def spread_cluster(tracks, route_segments, total_dist, spread_radius_deg=0.003):
    """For a group of tracks at the same position, spread them along the route.

    This takes tracks that would otherwise stack on top of each other and
    distributes them evenly along a short stretch of the route centered
    on their snapped position.
    """
    if len(tracks) <= 1:
        return

    # Find the center route position
    center_pos = tracks[len(tracks) // 2]["_route_pos"]

    # Spread them over a small range centered on the midpoint
    # More tracks = wider spread, but cap it
    n = len(tracks)
    spread = min(spread_radius_deg * min(n, 30), total_dist * 0.01)

    start_pos = center_pos - spread / 2
    end_pos = center_pos + spread / 2

    # Clamp to route bounds
    start_pos = max(0, start_pos)
    end_pos = min(total_dist, end_pos)

    if n == 1:
        return

    step = (end_pos - start_pos) / (n - 1) if n > 1 else 0

    for i, track in enumerate(tracks):
        target_pos = start_pos + i * step
        # Find the point on the route at this position
        for (lat1, lng1, lat2, lng2, cum_start, cum_end, _) in route_segments:
            if cum_start <= target_pos <= cum_end:
                seg_len = cum_end - cum_start
                if seg_len > 0:
                    t = (target_pos - cum_start) / seg_len
                else:
                    t = 0
                track["lat"] = round(lat1 + t * (lat2 - lat1), 6)
                track["lng"] = round(lng1 + t * (lng2 - lng1), 6)
                track["_route_pos"] = target_pos
                break


def main():
    with open(ROAD_ROUTE) as f:
        road_route = json.load(f)
    with open(TRACKS) as f:
        tracks = json.load(f)

    print(f"Snapping {len(tracks)} tracks to road route...")

    route_segments, total_dist = build_route_index(road_route)
    print(f"  Route: {len(route_segments)} line segments, {total_dist:.4f} deg total")

    # Phase 1: Snap every track to the nearest route point
    for track in tracks:
        if track.get("lat") and track.get("lng"):
            slat, slng, pos = snap_to_route(track["lat"], track["lng"], route_segments)
            orig_dist = haversine_miles(track["lat"], track["lng"], slat, slng)
            track["lat"] = round(slat, 6)
            track["lng"] = round(slng, 6)
            track["_route_pos"] = pos
            track["_snap_dist_mi"] = round(orig_dist, 2)

    # Phase 2: Detect clusters (tracks with nearly identical positions) and spread them
    # Sort by route position for cluster detection
    positioned = [t for t in tracks if "_route_pos" in t]
    positioned.sort(key=lambda t: t["_route_pos"])

    cluster_threshold = 0.0005  # ~0.03 miles
    clusters = []
    current_cluster = [positioned[0]] if positioned else []

    for i in range(1, len(positioned)):
        if abs(positioned[i]["_route_pos"] - current_cluster[-1]["_route_pos"]) < cluster_threshold:
            current_cluster.append(positioned[i])
        else:
            if len(current_cluster) > 2:
                clusters.append(current_cluster)
            current_cluster = [positioned[i]]

    if len(current_cluster) > 2:
        clusters.append(current_cluster)

    print(f"  Found {len(clusters)} clusters to spread ({sum(len(c) for c in clusters)} tracks)")

    for cluster in clusters:
        spread_cluster(cluster, route_segments, total_dist)

    # Stats
    snap_dists = [t["_snap_dist_mi"] for t in tracks if "_snap_dist_mi" in t]
    if snap_dists:
        avg = sum(snap_dists) / len(snap_dists)
        mx = max(snap_dists)
        close = sum(1 for d in snap_dists if d < 1)
        print(f"  Snap distances: avg={avg:.2f} mi, max={mx:.2f} mi, <1mi={close}/{len(snap_dists)}")

    # Clean up internal fields
    for track in tracks:
        track.pop("_route_pos", None)
        track.pop("_snap_dist_mi", None)

    with open(OUTPUT, "w") as f:
        json.dump(tracks, f, indent=2)

    print(f"  Saved to {OUTPUT}")


if __name__ == "__main__":
    main()
