"""Route geometry math and cheapest-fuel-stop planning.

Pure functions only — no Django imports — so the algorithm is trivially
unit-testable. The planner finds the provably cheapest set of fuel stops
for a 500-mile-range / 10-MPG vehicle via a shortest-path pass over the
stations that sit near the route.
"""

import math

TANK_RANGE_MILES = 500.0
MILES_PER_GALLON = 10.0
TANK_GALLONS = TANK_RANGE_MILES / MILES_PER_GALLON  # 50 gallons per fill
MAX_DETOUR_MILES = 10.0
EARTH_RADIUS_MILES = 3958.8

# Spatial grid cell size (degrees) used to index route segments.
_CELL = 0.5
# Bbox padding (degrees) when indexing a segment; comfortably larger than
# the max detour so no nearby station is ever missed.
_PAD = 0.35


class InfeasibleTrip(Exception):
    """Raised when some stretch of road has no reachable fuel station."""


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def route_mileposts(coordinates):
    """Cumulative miles at each route point.

    ``coordinates``: GeoJSON LineString ``[[lon, lat], ...]``.
    Returns ``(mileposts, total_miles)``.
    """
    mileposts = [0.0]
    for (lon1, lat1), (lon2, lat2) in zip(coordinates, coordinates[1:]):
        mileposts.append(mileposts[-1] + haversine_miles(lat1, lon1, lat2, lon2))
    return mileposts, mileposts[-1]


def _project_onto_segment(lat, lon, lat1, lon1, lat2, lon2):
    """Nearest point on a segment to (lat, lon), in a local mile plane.

    Returns ``(distance_miles, t)`` where ``t`` in [0, 1] is the fraction
    along the segment.
    """
    mlat, mlon = (lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0
    kx = 69.172 * math.cos(math.radians(mlat))
    ky = 68.94
    px, py = (lon - mlon) * kx, (lat - mlat) * ky
    ax, ay = (lon1 - mlon) * kx, (lat1 - mlat) * ky
    bx, by = (lon2 - mlon) * kx, (lat2 - mlat) * ky
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def _cell_of(lat, lon):
    return (math.floor(lat / _CELL), math.floor(lon / _CELL))


def locate_depots(coordinates, mileposts, depots):
    """Attach ``along_miles`` / ``detour_miles`` to depots near the route.

    Returns the depots within MAX_DETOUR_MILES of the polyline, sorted
    by distance along the route. Each depot object is mutated in place
    and also returned in the sorted list.
    """
    lats = [c[1] for c in coordinates]
    lons = [c[0] for c in coordinates]

    # Index every route segment into the grid cells its padded bbox covers.
    grid = {}
    for i in range(len(coordinates) - 1):
        lat_lo = min(lats[i], lats[i + 1]) - _PAD
        lat_hi = max(lats[i], lats[i + 1]) + _PAD
        lon_lo = min(lons[i], lons[i + 1]) - _PAD
        lon_hi = max(lons[i], lons[i + 1]) + _PAD
        for ci in range(math.floor(lat_lo / _CELL), math.floor(lat_hi / _CELL) + 1):
            for cj in range(math.floor(lon_lo / _CELL), math.floor(lon_hi / _CELL) + 1):
                grid.setdefault((ci, cj), []).append(i)

    seg_lens = [b - a for a, b in zip(mileposts, mileposts[1:])]
    near = []
    for depot in depots:
        ci, cj = _cell_of(depot.lat, depot.lon)
        best_dist, best_along = None, None
        seen = set()
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for s in grid.get((ci + di, cj + dj), ()):
                    if s in seen:
                        continue
                    seen.add(s)
                    dist, t = _project_onto_segment(
                        depot.lat, depot.lon,
                        lats[s], lons[s], lats[s + 1], lons[s + 1],
                    )
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        best_along = mileposts[s] + t * seg_lens[s]
        if best_dist is not None and best_dist <= MAX_DETOUR_MILES:
            depot.detour_miles = best_dist
            depot.along_miles = best_along
            near.append(depot)
    near.sort(key=lambda d: (d.along_miles, d.price))
    return near


def _gap_message(positions):
    worst, at = 0.0, 0.0
    for a, b in zip([0.0] + positions, positions):
        if b - a > worst:
            worst, at = b - a, a
    return (
        f"Route not feasible: a {worst:.1f}-mile stretch without any fuel "
        f"station (around mile {at:.1f}) exceeds the 500-mile tank range."
    )


def cheapest_plan(total_miles, depots):
    """Cheapest fuel-stop plan for the trip.

    ``depots`` must be sorted by ``along_miles`` (see ``locate_depots``).
    Models the trip as a shortest path over a DAG: an edge i -> j exists
    when station j is within one tank of station i, weighted by the fuel
    burned on that leg at i's price. The vehicle starts with a full tank.

    Returns ``[(depot, gallons_to_buy), ...]`` in driving order.
    Raises ``InfeasibleTrip`` when the destination cannot be reached.
    """
    positions = [d.along_miles for d in depots] + [total_miles]
    prices = [d.price for d in depots]  # destination has no price
    n = len(depots)

    INF = math.inf
    cost = [INF] * (n + 1)   # cheapest known cost to reach node j (empty tank)
    prev = [-2] * (n + 1)    # predecessor node; -1 means "from the start"

    for j in range(n + 1):
        best, best_i = INF, -2
        if positions[j] <= TANK_RANGE_MILES:
            best, best_i = 0.0, -1  # reachable on the opening full tank
        for i in range(j - 1, -1, -1):
            gap = positions[j] - positions[i]
            if gap > TANK_RANGE_MILES:
                break
            if math.isinf(cost[i]):
                continue
            candidate = cost[i] + gap / MILES_PER_GALLON * prices[i]
            if candidate < best:
                best, best_i = candidate, i
        cost[j], prev[j] = best, best_i

    if math.isinf(cost[n]):
        raise InfeasibleTrip(_gap_message(positions))

    # Walk predecessors back from the destination to rebuild the stops.
    legs = []
    j = n
    while j != -1:
        i = prev[j]
        legs.append((i, j))
        j = i
    legs.reverse()

    plan = []
    for frm, to in legs:
        if frm == -1:  # opening leg ran on the initial full tank: no purchase
            continue
        gallons = (positions[to] - positions[frm]) / MILES_PER_GALLON
        plan.append((depots[frm], gallons))
    return plan
