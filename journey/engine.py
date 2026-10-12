"""End-to-end trip planning: geocode -> route -> nearby stations -> cheapest stops.

This is the only place that wires the pieces together. Exactly three
outbound HTTP calls happen on a cold cache (2x Nominatim + 1x OSRM) and
exactly one on a warm cache (OSRM only).
"""

from . import depots as depot_store
from . import geo, road
from .optimizer import MILES_PER_GALLON, cheapest_plan, locate_depots, route_mileposts


def _split_label(label):
    city, state = [part.strip() for part in label.rsplit(",", 1)]
    return city, state


def plan_trip(start_label, finish_label):
    """Plan a trip; returns the JSON-serializable response dict."""
    start_city, start_state = _split_label(start_label)
    end_city, end_state = _split_label(finish_label)

    start_lat, start_lon = geo.lookup(start_city, start_state)
    end_lat, end_lon = geo.lookup(end_city, end_state)

    total_miles, coordinates = road.fetch_route(start_lat, start_lon, end_lat, end_lon)
    mileposts, _ = route_mileposts(coordinates)

    nearby = locate_depots(coordinates, mileposts, depot_store.load_depots())
    stops = cheapest_plan(total_miles, nearby)

    fuel_stops = []
    for number, (depot, gallons) in enumerate(stops, start=1):
        leg_cost = gallons * depot.price
        fuel_stops.append({
            "stop_number": number,
            "truckstop_name": depot.name,
            "address": depot.address,
            "city": depot.city,
            "state": depot.state,
            "retail_price_per_gallon": round(depot.price, 3),
            "gallons_purchased": round(gallons, 2),
            "cost_usd": round(leg_cost, 2),
            "latitude": round(depot.lat, 4),
            "longitude": round(depot.lon, 4),
            "distance_from_start_miles": round(depot.along_miles, 1),
        })

    total_cost = round(sum(s["cost_usd"] for s in fuel_stops), 2)
    total_gallons = round(total_miles / MILES_PER_GALLON, 2)
    return {
        "start_location": start_label,
        "finish_location": finish_label,
        "total_distance_miles": round(total_miles, 1),
        "total_fuel_cost_usd": total_cost,
        # Total fuel burned on the trip. Note this is larger than the sum of
        # gallons_purchased: the trip starts with a full tank, so the first
        # leg runs on fuel bought before the trip.
        "gallons_used": total_gallons,
        "fuel_stops": fuel_stops,
        "route_geometry": {"type": "LineString", "coordinates": coordinates},
    }
