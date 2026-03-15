#!/usr/bin/env python3
"""Fetch 30-second preview URLs from Deezer API. Free, no auth, has actual previews."""

import json
import urllib.request
import urllib.parse
import time

TRACKS_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
OUTPUT_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
CACHE_FILE = "nola_2024_viz/src/lib/data/deezer_cache.json"


def search_deezer(track_name, artist_name):
    """Search Deezer for a track and return preview URL + artwork."""
    query = f"{track_name} {artist_name}"
    params = urllib.parse.urlencode({"q": query, "limit": 5})
    url = f"https://api.deezer.com/search?{params}"

    req = urllib.request.Request(url, headers={"User-Agent": "RoadTripViz/1.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        results = data.get("data", [])
        if not results:
            return None

        # Try exact match first
        for t in results:
            t_name = t.get("title", "").lower()
            t_artist = t.get("artist", {}).get("name", "").lower()

            if (track_name.lower() in t_name or t_name in track_name.lower()) and \
               (artist_name.lower() in t_artist or t_artist in artist_name.lower()):
                return {
                    "previewUrl": t.get("preview"),
                    "artworkUrl": t.get("album", {}).get("cover_big", ""),
                }

        # Fall back to first result
        t = results[0]
        return {
            "previewUrl": t.get("preview"),
            "artworkUrl": t.get("album", {}).get("cover_big", ""),
        }

    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("    Rate limited, waiting 5s...")
            time.sleep(5)
            return search_deezer(track_name, artist_name)
        print(f"    HTTP {e.code}: {track_name}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def main():
    with open(TRACKS_FILE) as f:
        tracks = json.load(f)

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
            result = search_deezer(track["trackName"], track["artistName"])
            cache[cache_key] = result
            # Deezer allows ~50 req/s, be polite
            time.sleep(0.15)

        if result and result.get("previewUrl"):
            track["previewUrl"] = result["previewUrl"]
            # Only use Deezer artwork if we don't already have Spotify artwork
            if not track.get("artworkUrl") and result.get("artworkUrl"):
                track["artworkUrl"] = result["artworkUrl"]
            found += 1
        else:
            not_found += 1

        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(tracks)} — {found} with preview, {not_found} missing, {cached_hits} cached")
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)

    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(tracks, f, indent=2)

    print(f"\nDone! {found}/{len(tracks)} tracks have audio previews ({not_found} missing)")


if __name__ == "__main__":
    main()
