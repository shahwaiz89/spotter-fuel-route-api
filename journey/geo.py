"""City/state geocoding via Nominatim (OpenStreetMap).

Lookups are cached at two levels so a request never pays for the same
geocode twice: an in-memory dict for the life of the process and a JSON
file (``journey/data/station_coords.json``) that survives restarts. The
file cache is filled once by the ``build_coord_cache`` management
command; request-time lookups only hit the network for genuinely new
"CITY, ST" labels.
"""

import json
import time
from pathlib import Path

import requests

from . import http

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
CACHE_PATH = Path(__file__).resolve().parent / "data" / "station_coords.json"


class GeocodeError(Exception):
    """Raised when a place cannot be geocoded or Nominatim is unreachable."""


_memory = {}
_file = None


def cache_key(city, state):
    return f"{city.strip().title()}, {state.strip().upper()}"


def _file_cache():
    global _file
    if _file is None:
        if CACHE_PATH.exists():
            _file = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        else:
            _file = {}
    return _file


def persist(entries):
    """Merge ``{key: [lat, lon]}`` entries into the JSON file cache."""
    cache = _file_cache()
    cache.update(entries)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    _memory.update({k: tuple(v) for k, v in entries.items()})


def lookup(city, state, polite_delay=0):
    """Return ``(lat, lon)`` for a US "City, ST" pair.

    ``polite_delay`` sleeps that many seconds before a network call so
    bulk jobs can respect Nominatim's usage policy (1 req/sec).
    """
    key = cache_key(city, state)
    if key in _memory:
        return _memory[key]
    hit = _file_cache().get(key)
    if hit is not None:
        _memory[key] = (hit[0], hit[1])
        return _memory[key]
    if polite_delay:
        time.sleep(polite_delay)
    try:
        payload = http.get(
            "nominatim",
            NOMINATIM_URL,
            params={"q": f"{city}, {state}, USA", "format": "json", "limit": 1},
        ).json()
    except requests.RequestException as exc:
        raise GeocodeError(f"Nominatim request failed for '{key}': {exc}")
    if not payload:
        raise GeocodeError(f"Could not geocode '{key}'.")
    lat, lon = float(payload[0]["lat"]), float(payload[0]["lon"])
    _memory[key] = (lat, lon)
    return lat, lon
