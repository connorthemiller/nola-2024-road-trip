#!/usr/bin/env python3
"""Fetch 30-second audio preview URLs from iTunes Search API for all trip tracks."""

import json
import urllib.request
import urllib.parse
import time
import sys

TRACKS_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
OUTPUT_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
# Cache to avoid re-fetching the same song (many repeats on a road trip)
CACHE_FILE = "nola_2024_viz/src/lib/data/preview_cache.json"


def search_itunes(track_name, artist_name):
    """Search iTunes for a track and return preview URL + artwork."""
    query = f"{track_name} {artist_name}"
    params = urllib.parse.urlencode({
        "term": query,
        "media": "music",
        "entity": "song",
        "limit": 3,
    })
    url = f"https://itunes.apple.com/search?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "RoadTripViz/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        if data["resultCount"] > 0:
            # Try to find exact match first
            for result in data["results"]:
                r_track = result.get("trackName", "").lower()
                r_artist = result.get("artistName", "").lower()
                if (track_name.lower() in r_track or r_track in track_name.lower()) and \
                   (artist_name.lower() in r_artist or r_artist in artist_name.lower()):
                    return {
                        "previewUrl": result.get("previewUrl"),
                        "artworkUrl": result.get("artworkUrl100", "").replace("100x100", "300x300"),
                        "itunesUrl": result.get("trackViewUrl"),
                    }

            # Fall back to first result
            result = data["results"][0]
            return {
                "previewUrl": result.get("previewUrl"),
                "artworkUrl": result.get("artworkUrl100", "").replace("100x100", "300x300"),
                "itunesUrl": result.get("trackViewUrl"),
            }

        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def main():
    with open(TRACKS_FILE) as f:
        tracks = json.load(f)

    # Load cache
    try:
        with open(CACHE_FILE) as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}

    print(f"Processing {len(tracks)} tracks ({len(cache)} cached)...")

    found = 0
    cached_hits = 0
    not_found = 0

    for i, track in enumerate(tracks):
        cache_key = f"{track['artistName']}|||{track['trackName']}"

        if cache_key in cache:
            result = cache[cache_key]
            cached_hits += 1
        else:
            result = search_itunes(track["trackName"], track["artistName"])
            cache[cache_key] = result
            # Rate limit: ~20 requests/min to be safe
            time.sleep(0.4)

        if result and result.get("previewUrl"):
            track["previewUrl"] = result["previewUrl"]
            track["artworkUrl"] = result.get("artworkUrl", "")
            found += 1
        else:
            not_found += 1

        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(tracks)} — {found} found, {not_found} missing, {cached_hits} cached")
            # Save cache periodically
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)

    # Final save
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(tracks, f, indent=2)

    print(f"\nDone! {found}/{len(tracks)} tracks have previews ({not_found} missing)")
    print(f"Cache: {len(cache)} entries saved to {CACHE_FILE}")


if __name__ == "__main__":
    main()
