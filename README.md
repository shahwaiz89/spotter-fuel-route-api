# TripFuel — cheapest-fuel road-trip planner

A Django REST API that plans a driving route between two US cities and
picks the cheapest possible fuel stops along the way. Built as a
take-home assessment for a Backend Engineer role.

Vehicle model: **500-mile tank range, 10 MPG** (50-gallon tank).

## Quickstart

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# One-time: geocode every station city (~1 hr, respects Nominatim's
# 1 req/sec policy; resumable). The JSON cache ships with the repo, so
# you can skip this unless you want to rebuild it.
python manage.py build_coord_cache

python manage.py runserver
```

## API

```
POST /api/route/
Content-Type: application/json

{ "start_location": "Denver, CO", "finish_location": "Dallas, TX" }
```

Response: total distance, total fuel cost, gallons used, the ordered
fuel stops (station, price, gallons, cost, position), and the route
geometry as GeoJSON. Impossible trips return `422` with an explanation;
bad input returns `400`.

Try it:

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H 'Content-Type: application/json' \
  -d '{"start_location": "Denver, CO", "finish_location": "Dallas, TX"}'
```

## How it works

1. **Geocode** both endpoints with Nominatim (results cached in
   `journey/data/station_coords.json`, so repeats are free).
2. **Route once** with the public OSRM server — a single call per
   request returns distance plus the full route polyline.
3. **Snap stations to the route**: each of the ~8,000 fuel stations
   inherits its city coordinates from the cache; a grid index finds the
   stations within 10 miles of the polyline and records how far along
   the route each one sits.
4. **Cheapest stops via shortest path**: the trip becomes a DAG where an
   edge exists between two stations if the second is within one tank of
   the first, weighted by fuel burned at the first station's price. A
   shortest-path pass yields the provably cheapest fill-up plan for the
   whole trip (the truck starts with a full tank).

If any stretch of road has no station within tank range, the API answers
`422` instead of failing. (Example: Seattle → San Francisco has a
~548-mile station gap in the supplied dataset — southern Oregon and
northern/central California contain no stations at all — so it correctly
returns 422 with an explanation rather than an impossible plan.)

## Design notes

- No API keys anywhere: OSRM and Nominatim are both free and keyless.
- No database: the CSV + JSON cache are loaded into memory once.
- Outbound calls per request: 3 on a cold cache (2 geocodes + 1 route),
  exactly 1 on a warm cache (route only).
- The planning core (`journey/optimizer.py`) is pure Python with no
  Django imports, covered by unit tests.

## Tests

```bash
python manage.py test
```
