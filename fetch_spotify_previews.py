#!/usr/bin/env python3
"""Fetch 30-second preview URLs from Spotify Web API for all trip tracks."""

import json
import urllib.request
import urllib.parse
import base64
import os
import time

TRACKS_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
OUTPUT_FILE = "nola_2024_viz/src/lib/data/trip_tracks.json"
CACHE_FILE = "nola_2024_viz/src/lib/data/spotify_cache.json"
ENV_FILE = ".env"


def load_env():
    """Read .env file for credentials."""
    env = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                env[key.strip()] = val.strip()
    return env


def get_access_token(client_id, client_secret):
    """Get Spotify access token via client credentials flow."""
    auth_str = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()

    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={
            "Authorization": f"Basic {auth_str}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    resp = urllib.request.urlopen(req, timeout=10)
    return json.loads(resp.read())["access_token"]


def search_track(track_name, artist_name, token):
    """Search Spotify for a track and return preview URL + metadata."""
    query = f"track:{track_name} artist:{artist_name}"
    params = urllib.parse.urlencode({
        "q": query,
        "type": "track",
        "limit": 5,
    })
    url = f"https://api.spotify.com/v1/search?{params}"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "User-Agent": "RoadTripViz/1.0",
    })

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())

        tracks = data.get("tracks", {}).get("items", [])
        if not tracks:
            return None

        # Try to find best match
        for t in tracks:
            t_name = t.get("name", "").lower()
            t_artist = ", ".join(a["name"] for a in t.get("artists", [])).lower()

            if (track_name.lower() in t_name or t_name in track_name.lower()) and \
               (artist_name.lower() in t_artist or t_artist in artist_name.lower()):
                return _extract_track_data(t)

        # Fall back to first result
        return _extract_track_data(tracks[0])

    except urllib.error.HTTPError as e:
        if e.code == 429:
            retry_after = int(e.headers.get("Retry-After", 5))
            print(f"    Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            return search_track(track_name, artist_name, token)
        print(f"    HTTP {e.code}: {track_name} - {artist_name}")
        return None
    except Exception as e:
        print(f"    Error: {e}")
        return None


def _extract_track_data(t):
    """Extract relevant fields from a Spotify track object."""
    images = t.get("album", {}).get("images", [])
    # Get ~300px artwork
    artwork = ""
    for img in images:
        if img.get("width", 0) >= 200:
            artwork = img["url"]
            break
    if not artwork and images:
        artwork = images[0]["url"]

    return {
        "previewUrl": t.get("preview_url"),
        "artworkUrl": artwork,
        "spotifyUri": t.get("uri"),
        "spotifyUrl": t.get("external_urls", {}).get("spotify"),
        "albumName": t.get("album", {}).get("name"),
    }


def main():
    env = load_env()
    client_id = env.get("SPOTIFY_CLIENT_ID")
    client_secret = env.get("SPOTIFY_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET in .env")
        return

    print("Authenticating with Spotify...")
    token = get_access_token(client_id, client_secret)
    print("Authenticated!")

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
    found_with_preview = 0
    cached_hits = 0
    not_found = 0

    for i, track in enumerate(tracks):
        cache_key = f"{track['artistName']}|||{track['trackName']}"

        if cache_key in cache:
            result = cache[cache_key]
            cached_hits += 1
        else:
            result = search_track(track["trackName"], track["artistName"], token)
            cache[cache_key] = result
            # Spotify allows ~30 req/s with client credentials, be conservative
            time.sleep(0.1)

        if result:
            found += 1
            if result.get("previewUrl"):
                track["previewUrl"] = result["previewUrl"]
                found_with_preview += 1
            if result.get("artworkUrl"):
                track["artworkUrl"] = result["artworkUrl"]
            if result.get("spotifyUrl"):
                track["spotifyUrl"] = result["spotifyUrl"]
            if result.get("albumName"):
                track["albumName"] = result["albumName"]
        else:
            not_found += 1

        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(tracks)} — {found} found ({found_with_preview} with preview), "
                  f"{not_found} missing, {cached_hits} cached")
            with open(CACHE_FILE, "w") as f:
                json.dump(cache, f)

    # Final save
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(tracks, f, indent=2)

    print(f"\nDone!")
    print(f"  Found on Spotify: {found}/{len(tracks)}")
    print(f"  With preview URL: {found_with_preview}/{len(tracks)}")
    print(f"  Not found: {not_found}")
    print(f"  Cache: {len(cache)} entries saved")


if __name__ == "__main__":
    main()
