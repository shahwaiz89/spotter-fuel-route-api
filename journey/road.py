"""Routing via the public OSRM demo server (no API key needed).

Exactly ONE OSRM call is made per trip plan. The client is deliberately
thin so a different provider could be swapped in without touching the
rest of the codebase.
"""

import requests

from . import http

OSRM_TEMPLATE = "https://router.project-osrm.org/route/v1/driving/{coords}"


class RoutingError(Exception):
    """Raised when the routing backend cannot be reached."""


class NoRouteError(RoutingError):
    """Raised when no driving route exists between the two points."""


def fetch_route(start_lat, start_lon, end_lat, end_lon):
    """Return ``(distance_miles, coordinates)`` for the driving route.

    ``coordinates`` is the GeoJSON LineString as ``[[lon, lat], ...]``.
    """
    url = OSRM_TEMPLATE.format(
        coords=f"{start_lon},{start_lat};{end_lon},{end_lat}"
    )
    try:
        response = http.get(
            "osrm",
            url,
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
    except requests.HTTPError as exc:
        # OSRM answers impossible routes with HTTP 400 + {"code": "NoRoute"}.
        status = exc.response.status_code if exc.response is not None else None
        try:
            code = exc.response.json().get("code") if exc.response is not None else None
        except Exception:
            code = None
        if status == 400 and code == "NoRoute":
            raise NoRouteError("No driving route exists between these locations.")
        raise RoutingError(f"OSRM request failed: {exc}")
    except requests.RequestException as exc:
        raise RoutingError(f"OSRM request failed: {exc}")
    payload = response.json()
    routes = payload.get("routes") or []
    if payload.get("code") != "Ok" or not routes:
        raise NoRouteError("No driving route exists between these locations.")
    best = routes[0]
    distance_miles = best["distance"] / 1609.344
    return distance_miles, best["geometry"]["coordinates"]
