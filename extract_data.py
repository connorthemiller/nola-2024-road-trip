#!/usr/bin/env python3
"""Extract photo EXIF data and correlate with Spotify listening history for the NOLA road trip."""

import json
import subprocess
import os
from datetime import datetime, timezone, timedelta
from math import radians, sin, cos, sqrt, atan2

PHOTO_DIR = "trip_photos"
SPOTIFY_DIR = "Spotify Account Data"
OUTPUT_DIR = "nola_2024_viz/src/lib/data"

TRIP_START = datetime(2024, 6, 4, tzinfo=timezone.utc)
TRIP_END = datetime(2024, 6, 15, tzinfo=timezone.utc)

# Max plausible driving speed in mph — anything faster is a GPS outlier
MAX_SPEED_MPH = 120


def haversine_miles(lat1, lng1, lat2, lng2):
    """Distance in miles between two GPS points."""
    R = 3959
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1-a))


def extract_photo_metadata():
    """Extract GPS + timestamp from all photos using mdls."""
    photo_dir = PHOTO_DIR
    files = os.listdir(photo_dir)

    supported = ('.heic', '.jpg', '.jpeg', '.png', '.mov', '.mp4')
    files = [f for f in files if os.path.splitext(f)[1].lower() in supported]

    print(f"Processing {len(files)} files...")

    full_paths = [os.path.join(photo_dir, f) for f in files]

    batch_size = 100
    all_output = ""
    for i in range(0, len(full_paths), batch_size):
        batch = full_paths[i:i+batch_size]
        result = subprocess.run(
            ["mdls", "-name", "kMDItemLatitude", "-name", "kMDItemLongitude",
             "-name", "kMDItemContentCreationDate", "-name", "kMDItemFSName",
             "-name", "kMDItemContentType"] + batch,
            capture_output=True, text=True
        )
        all_output += result.stdout

    # Parse mdls output — attributes come alphabetically, 5 per file
    photos = []
    lines = [l.strip() for l in all_output.strip().split("\n") if l.strip()]

    attrs_per_file = 5
    for i in range(0, len(lines), attrs_per_file):
        chunk = lines[i:i+attrs_per_file]
        if len(chunk) < attrs_per_file:
            break

        current = {}
        for line in chunk:
            if "kMDItemFSName" in line:
                current["filename"] = line.split("=", 1)[1].strip().strip('"')
            elif "kMDItemContentCreationDate" in line:
                val = line.split("=", 1)[1].strip()
                if val != "(null)":
                    current["timestamp"] = val
            elif "kMDItemLatitude" in line:
                val = line.split("=", 1)[1].strip()
                if val != "(null)":
                    current["lat"] = float(val)
            elif "kMDItemLongitude" in line:
                val = line.split("=", 1)[1].strip()
                if val != "(null)":
                    current["lng"] = float(val)
            elif "kMDItemContentType" in line:
                val = line.split("=", 1)[1].strip().strip('"')
                current["type"] = val

        if current.get("filename"):
            photos.append(current)

    # Filter to photos with GPS data within trip dates
    gps_photos = []
    no_gps = 0
    outside_trip = 0

    for p in photos:
        if "lat" not in p or "lng" not in p:
            no_gps += 1
            continue
        if "timestamp" not in p:
            continue

        try:
            dt = datetime.strptime(p["timestamp"], "%Y-%m-%d %H:%M:%S %z")
        except ValueError:
            continue

        if dt < TRIP_START or dt > TRIP_END:
            outside_trip += 1
            continue

        gps_photos.append({
            "filename": p["filename"],
            "timestamp": dt.isoformat(),
            "timestamp_unix": dt.timestamp(),
            "lat": p["lat"],
            "lng": p["lng"],
            "type": p.get("type", "unknown")
        })

    gps_photos.sort(key=lambda x: x["timestamp_unix"])

    print(f"  Total files: {len(files)}")
    print(f"  With GPS in trip range: {len(gps_photos)}")
    print(f"  No GPS: {no_gps}")
    print(f"  Outside trip dates: {outside_trip}")

    return gps_photos


def clean_route(photos):
    """Remove GPS outliers using a spike-detection approach.

    An outlier is a point that is far from BOTH its neighbors, while the neighbors
    are close to each other. This avoids cascade-removing legitimate sequences.
    We run multiple passes until no more outliers are found.
    """
    if len(photos) < 3:
        return photos

    removed = []
    current = list(photos)

    for pass_num in range(5):  # max 5 passes
        new_removed = []
        keep = [True] * len(current)

        for i in range(1, len(current) - 1):
            prev = current[i - 1]
            curr = current[i]
            nxt = current[i + 1]

            # Distance from curr to both neighbors
            d_prev = haversine_miles(prev["lat"], prev["lng"], curr["lat"], curr["lng"])
            d_next = haversine_miles(curr["lat"], curr["lng"], nxt["lat"], nxt["lng"])
            # Distance if we skip curr
            d_skip = haversine_miles(prev["lat"], prev["lng"], nxt["lat"], nxt["lng"])

            # Time gaps
            t_prev = (curr["timestamp_unix"] - prev["timestamp_unix"]) / 3600
            t_next = (nxt["timestamp_unix"] - curr["timestamp_unix"]) / 3600
            t_skip = (nxt["timestamp_unix"] - prev["timestamp_unix"]) / 3600

            # This is a spike if:
            # 1. curr is far from both neighbors (>10 miles each)
            # 2. Skipping curr gives a shorter/more plausible path
            # 3. Speed to/from curr is impossible
            if d_prev > 10 and d_next > 10 and d_skip < max(d_prev, d_next) * 0.7:
                speed_in = d_prev / t_prev if t_prev > 0 else float('inf')
                speed_out = d_next / t_next if t_next > 0 else float('inf')
                speed_skip = d_skip / t_skip if t_skip > 0 else float('inf')

                if (speed_in > MAX_SPEED_MPH or speed_out > MAX_SPEED_MPH) and speed_skip <= MAX_SPEED_MPH * 1.5:
                    keep[i] = False
                    new_removed.append(curr["filename"])

        if not new_removed:
            break

        current = [p for p, k in zip(current, keep) if k]
        removed.extend(new_removed)
        print(f"    Pass {pass_num + 1}: removed {len(new_removed)} outliers")

    print(f"  Total removed: {len(removed)} outliers: {removed}")
    return current


def smooth_route(photos, window=3):
    """Light smoothing to reduce GPS jitter while preserving the actual path.

    Only smooths when consecutive points are close together (stationary/slow movement).
    Preserves large movements (driving between cities).
    """
    if len(photos) < window:
        return photos

    smoothed = []
    for i in range(len(photos)):
        # Collect neighbors within window
        start = max(0, i - window // 2)
        end = min(len(photos), i + window // 2 + 1)
        neighbors = photos[start:end]

        # Check if all neighbors are close (within ~0.5 mile) — only smooth clusters
        all_close = all(
            haversine_miles(photos[i]["lat"], photos[i]["lng"], n["lat"], n["lng"]) < 0.5
            for n in neighbors
        )

        if all_close and len(neighbors) > 1:
            avg_lat = sum(n["lat"] for n in neighbors) / len(neighbors)
            avg_lng = sum(n["lng"] for n in neighbors) / len(neighbors)
            smoothed.append({**photos[i], "lat": round(avg_lat, 6), "lng": round(avg_lng, 6)})
        else:
            smoothed.append(photos[i])

    return smoothed


def deduplicate_stationary(photos, min_distance_miles=0.01, min_time_seconds=5):
    """Collapse near-duplicate waypoints taken from the same spot."""
    if not photos:
        return photos

    deduped = [photos[0]]

    for i in range(1, len(photos)):
        prev = deduped[-1]
        curr = photos[i]
        dist = haversine_miles(prev["lat"], prev["lng"], curr["lat"], curr["lng"])
        time_gap = curr["timestamp_unix"] - prev["timestamp_unix"]

        # Keep if moved meaningfully OR enough time has passed (to preserve time coverage)
        if dist > min_distance_miles or time_gap > 300:  # 5 min
            deduped.append(curr)

    return deduped


def extract_spotify_data():
    """Load and filter Spotify streaming history to trip dates."""
    all_tracks = []

    for i in range(5):
        filepath = os.path.join(SPOTIFY_DIR, f"StreamingHistory_music_{i}.json")
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                tracks = json.load(f)
                all_tracks.extend(tracks)

    print(f"Total Spotify tracks: {len(all_tracks)}")

    trip_tracks = []
    for t in all_tracks:
        try:
            dt = datetime.strptime(t["endTime"], "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if dt < TRIP_START or dt > TRIP_END:
            continue

        if t["msPlayed"] < 30000:
            continue

        start_dt = dt - timedelta(milliseconds=t["msPlayed"])

        trip_tracks.append({
            "artistName": t["artistName"],
            "trackName": t["trackName"],
            "msPlayed": t["msPlayed"],
            "endTime": dt.isoformat(),
            "endTime_unix": dt.timestamp(),
            "startTime": start_dt.isoformat(),
            "startTime_unix": start_dt.timestamp(),
        })

    trip_tracks.sort(key=lambda x: x["startTime_unix"])
    print(f"Trip tracks (>30s): {len(trip_tracks)}")

    return trip_tracks


def detect_stationary_segments(photos, max_radius_miles=2.0):
    """Identify time ranges where the user stayed in roughly the same place.

    Returns a list of (start_time, end_time, center_lat, center_lng, radius_miles)
    for each stationary segment. A segment is stationary if all photos within it
    are within max_radius_miles of the segment's centroid.
    """
    if not photos:
        return []

    segments = []
    seg_start = 0

    for i in range(1, len(photos)):
        # Check if current photo is still near the segment start
        cluster = photos[seg_start:i + 1]
        center_lat = sum(p["lat"] for p in cluster) / len(cluster)
        center_lng = sum(p["lng"] for p in cluster) / len(cluster)

        all_within = all(
            haversine_miles(center_lat, center_lng, p["lat"], p["lng"]) < max_radius_miles
            for p in cluster
        )

        if not all_within:
            # Close out previous segment if it had meaningful duration (>1 hour)
            if i - seg_start >= 2:
                seg_photos = photos[seg_start:i]
                duration_hrs = (seg_photos[-1]["timestamp_unix"] - seg_photos[0]["timestamp_unix"]) / 3600
                if duration_hrs >= 1:
                    c_lat = sum(p["lat"] for p in seg_photos) / len(seg_photos)
                    c_lng = sum(p["lng"] for p in seg_photos) / len(seg_photos)
                    max_r = max(haversine_miles(c_lat, c_lng, p["lat"], p["lng"]) for p in seg_photos)
                    segments.append({
                        "start_time": seg_photos[0]["timestamp_unix"],
                        "end_time": seg_photos[-1]["timestamp_unix"],
                        "lat": c_lat,
                        "lng": c_lng,
                        "radius": max_r,
                        "num_photos": len(seg_photos),
                        "duration_hrs": duration_hrs,
                    })
            seg_start = i

    # Close final segment
    if len(photos) - seg_start >= 2:
        seg_photos = photos[seg_start:]
        duration_hrs = (seg_photos[-1]["timestamp_unix"] - seg_photos[0]["timestamp_unix"]) / 3600
        if duration_hrs >= 1:
            c_lat = sum(p["lat"] for p in seg_photos) / len(seg_photos)
            c_lng = sum(p["lng"] for p in seg_photos) / len(seg_photos)
            max_r = max(haversine_miles(c_lat, c_lng, p["lat"], p["lng"]) for p in seg_photos)
            segments.append({
                "start_time": seg_photos[0]["timestamp_unix"],
                "end_time": seg_photos[-1]["timestamp_unix"],
                "lat": c_lat,
                "lng": c_lng,
                "radius": max_r,
                "num_photos": len(seg_photos),
                "duration_hrs": duration_hrs,
            })

    return segments


def classify_segment(photos, before_idx, after_idx):
    """Determine if the segment between two photos is stationary or driving."""
    if before_idx is None or after_idx is None:
        return "unknown", 0

    dist = haversine_miles(
        photos[before_idx]["lat"], photos[before_idx]["lng"],
        photos[after_idx]["lat"], photos[after_idx]["lng"]
    )
    time_hrs = (photos[after_idx]["timestamp_unix"] - photos[before_idx]["timestamp_unix"]) / 3600

    if time_hrs <= 0:
        return "stationary", 0

    speed = dist / time_hrs

    # If both photos are within ~2 miles, you didn't move
    if dist < 2:
        return "stationary", dist
    # If speed is walking/city pace, mostly stationary
    elif speed < 10:
        return "stationary", dist
    else:
        return "driving", dist


def interpolate_locations(photos, tracks):
    """For each track, estimate location by interpolating between nearest photos.

    Three improvements over naive interpolation:
    1. Wider confidence windows (30 min = high, 2 hr = medium) appropriate for road trips
    2. Stationary detection — if you didn't move between photos, all songs in that
       window get the same location with high confidence regardless of time gap
    3. Driving corridor awareness — driving tracks get interpolated along the route
       and rated based on distance uncertainty rather than just time gap
    """
    from bisect import bisect_right

    if not photos:
        print("No photos with GPS data!")
        return tracks

    # Detect stationary segments
    stationary = detect_stationary_segments(photos)
    print(f"  Found {len(stationary)} stationary segments:")
    for seg in stationary:
        start_dt = datetime.fromtimestamp(seg["start_time"], tz=timezone.utc)
        end_dt = datetime.fromtimestamp(seg["end_time"], tz=timezone.utc)
        print(f"    {start_dt.strftime('%m/%d %H:%M')}-{end_dt.strftime('%m/%d %H:%M')} UTC "
              f"({seg['duration_hrs']:.1f}hrs, {seg['num_photos']} photos, "
              f"r={seg['radius']:.2f}mi @ {seg['lat']:.4f},{seg['lng']:.4f})")

    photo_times = [p["timestamp_unix"] for p in photos]

    located_tracks = []
    for track in tracks:
        mid_time = (track["startTime_unix"] + track["endTime_unix"]) / 2

        # --- Check stationary segments first ---
        in_stationary = None
        for seg in stationary:
            if seg["start_time"] <= mid_time <= seg["end_time"]:
                in_stationary = seg
                break
            # Also catch tracks slightly outside segment bounds but still nearby in time
            # (e.g., listening at night between last evening photo and first morning photo)
            margin = 2 * 3600  # 2 hour margin
            if (seg["start_time"] - margin) <= mid_time <= (seg["end_time"] + margin):
                # Only if the margin-extended version doesn't overlap with driving
                idx = bisect_right(photo_times, mid_time)
                b = idx - 1 if idx > 0 else None
                a = idx if idx < len(photo_times) else None
                if b is not None and a is not None:
                    seg_type, _ = classify_segment(photos, b, a)
                    if seg_type == "stationary":
                        in_stationary = seg
                        break

        if in_stationary:
            lat = in_stationary["lat"]
            lng = in_stationary["lng"]
            # Confidence based on how well we know this area
            if in_stationary["radius"] < 0.5 and in_stationary["num_photos"] >= 3:
                confidence = "high"
            elif in_stationary["radius"] < 2:
                confidence = "high"
            else:
                confidence = "medium"

            track_with_loc = {
                **track,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "locationConfidence": confidence,
                "locationType": "stationary",
            }
            located_tracks.append(track_with_loc)
            continue

        # --- Standard interpolation for driving/transit ---
        idx = bisect_right(photo_times, mid_time)
        before = idx - 1 if idx > 0 else None
        after = idx if idx < len(photo_times) else None

        lat, lng = None, None
        confidence = "none"
        nearest_photo = None
        loc_type = "interpolated"

        if before is not None and after is not None:
            t_before = photo_times[before]
            t_after = photo_times[after]
            time_span = t_after - t_before

            if time_span > 0:
                ratio = (mid_time - t_before) / time_span
                lat = photos[before]["lat"] + ratio * (photos[after]["lat"] - photos[before]["lat"])
                lng = photos[before]["lng"] + ratio * (photos[after]["lng"] - photos[before]["lng"])

                seg_type, seg_dist = classify_segment(photos, before, after)
                gap_minutes = time_span / 60

                if seg_type == "stationary":
                    # Not caught by segment detection but photos show no movement
                    confidence = "high"
                    loc_type = "stationary"
                else:
                    # Driving — confidence based on both time gap AND distance uncertainty
                    # Max possible error: how far you could be from the interpolated point
                    # On a highway, interpolation along the route is usually pretty good
                    max_error_miles = seg_dist * 0.25  # worst case ~25% off along route

                    if gap_minutes < 30 or max_error_miles < 5:
                        confidence = "high"
                    elif gap_minutes < 120 or max_error_miles < 20:
                        confidence = "medium"
                    else:
                        confidence = "low"
                    loc_type = "driving"
            else:
                lat = photos[before]["lat"]
                lng = photos[before]["lng"]
                confidence = "high"

            if (mid_time - t_before) < (t_after - mid_time):
                nearest_photo = photos[before]["filename"]
            else:
                nearest_photo = photos[after]["filename"]

        elif before is not None:
            lat = photos[before]["lat"]
            lng = photos[before]["lng"]
            gap = (mid_time - photo_times[before]) / 60
            confidence = "high" if gap < 30 else "medium" if gap < 120 else "low"
            nearest_photo = photos[before]["filename"]

        elif after is not None:
            lat = photos[after]["lat"]
            lng = photos[after]["lng"]
            gap = (photo_times[after] - mid_time) / 60
            confidence = "high" if gap < 30 else "medium" if gap < 120 else "low"
            nearest_photo = photos[after]["filename"]

        track_with_loc = {**track}
        if lat is not None:
            track_with_loc["lat"] = round(lat, 6)
            track_with_loc["lng"] = round(lng, 6)
            track_with_loc["locationConfidence"] = confidence
            track_with_loc["locationType"] = loc_type
        if nearest_photo:
            track_with_loc["nearestPhoto"] = nearest_photo

        located_tracks.append(track_with_loc)

    high = sum(1 for t in located_tracks if t.get("locationConfidence") == "high")
    med = sum(1 for t in located_tracks if t.get("locationConfidence") == "medium")
    low = sum(1 for t in located_tracks if t.get("locationConfidence") == "low")
    none_count = sum(1 for t in located_tracks if t.get("locationConfidence") is None)

    stat = sum(1 for t in located_tracks if t.get("locationType") == "stationary")
    drv = sum(1 for t in located_tracks if t.get("locationType") == "driving")
    interp = sum(1 for t in located_tracks if t.get("locationType") == "interpolated")

    print(f"\nLocation confidence:")
    print(f"  High: {high}  Medium: {med}  Low: {low}  None: {none_count}")
    print(f"\nLocation type:")
    print(f"  Stationary: {stat}  Driving: {drv}  Interpolated: {interp}")

    return located_tracks


def compute_route_stats(route):
    """Print useful stats about the final route."""
    total_dist = 0
    for i in range(1, len(route)):
        total_dist += haversine_miles(route[i-1]["lat"], route[i-1]["lng"],
                                       route[i]["lat"], route[i]["lng"])

    # Time span
    start = route[0]["timestamp"]
    end = route[-1]["timestamp"]

    print(f"  Route points: {len(route)}")
    print(f"  Total distance: {total_dist:.0f} miles (straight-line)")
    print(f"  Time span: {start[:10]} to {end[:10]}")

    # Check for remaining large jumps
    big_jumps = 0
    for i in range(1, len(route)):
        dist = haversine_miles(route[i-1]["lat"], route[i-1]["lng"],
                                route[i]["lat"], route[i]["lng"])
        time_h = (route[i]["timestamp_unix"] - route[i-1]["timestamp_unix"]) / 3600
        if time_h > 0 and dist / time_h > MAX_SPEED_MPH:
            big_jumps += 1

    if big_jumps:
        print(f"  Warning: {big_jumps} segments still exceed {MAX_SPEED_MPH} mph")
    else:
        print(f"  All segments below {MAX_SPEED_MPH} mph")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=== Extracting photo metadata ===")
    photos = extract_photo_metadata()

    print("\n=== Cleaning route ===")
    print(f"  Before: {len(photos)} waypoints")
    photos = clean_route(photos)
    print(f"  After outlier removal: {len(photos)} waypoints")
    photos = smooth_route(photos)
    photos = deduplicate_stationary(photos)
    print(f"  After smoothing + dedup: {len(photos)} waypoints")

    print("\n=== Extracting Spotify data ===")
    tracks = extract_spotify_data()

    print("\n=== Interpolating locations ===")
    located_tracks = interpolate_locations(photos, tracks)

    # Save outputs
    with open(os.path.join(OUTPUT_DIR, "photo_waypoints.json"), "w") as f:
        json.dump(photos, f, indent=2)

    with open(os.path.join(OUTPUT_DIR, "trip_tracks.json"), "w") as f:
        json.dump(located_tracks, f, indent=2)

    route = [{"lat": p["lat"], "lng": p["lng"], "timestamp": p["timestamp"],
              "timestamp_unix": p["timestamp_unix"], "filename": p["filename"]}
             for p in photos]
    with open(os.path.join(OUTPUT_DIR, "route.json"), "w") as f:
        json.dump(route, f, indent=2)

    print(f"\n=== Route stats ===")
    compute_route_stats(route)

    print(f"\n=== Done! ===")
    print(f"Saved to {OUTPUT_DIR}/:")
    print(f"  photo_waypoints.json ({len(photos)} waypoints)")
    print(f"  trip_tracks.json ({len(located_tracks)} tracks)")
    print(f"  route.json ({len(route)} route points)")


if __name__ == "__main__":
    main()
