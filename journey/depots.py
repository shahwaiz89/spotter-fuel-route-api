"""Fuel-station catalogue.

Rows come from the supplied CSV (truckstop name, address, city, state,
retail price). Coordinates are NOT in the CSV: each station inherits the
geocoded position of its "City, ST" from the JSON cache built by the
``build_coord_cache`` management command. Stations whose city was never
geocoded are skipped.

Canadian rows exist in the CSV but the assessment is USA-only, so those
provinces are excluded everywhere here.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .geo import CACHE_PATH, cache_key

# Provinces present in the CSV that are not US states.
CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NS", "ON", "QC", "SK", "YT"}

CSV_PATH = Path(__file__).resolve().parent / "data" / "fuel-prices.csv"


@dataclass
class Depot:
    opis_id: str
    name: str
    address: str
    city: str
    state: str
    price: float
    lat: float
    lon: float
    along_miles: float = field(default=0.0, compare=False)
    detour_miles: float = field(default=0.0, compare=False)


_catalog = None


def us_places():
    """Sorted unique (city, state) pairs in the CSV, excluding Canada."""
    seen = set()
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            city = row["City"].strip()
            state = row["State"].strip().upper()
            if not city or state in CANADIAN_PROVINCES:
                continue
            seen.add((city, state))
    return sorted(seen)


def load_depots():
    """All US stations with coordinates, cached in memory after first load."""
    global _catalog
    if _catalog is not None:
        return _catalog
    import json

    coords = {}
    if CACHE_PATH.exists():
        coords = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    depots = []
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            city = row["City"].strip()
            state = row["State"].strip().upper()
            if state in CANADIAN_PROVINCES:
                continue
            hit = coords.get(cache_key(city, state))
            if hit is None:
                continue
            try:
                price = float(row["Retail Price"])
            except (TypeError, ValueError):
                continue
            depots.append(
                Depot(
                    opis_id=row["OPIS Truckstop ID"].strip(),
                    name=row["Truckstop Name"].strip(),
                    address=row["Address"].strip(),
                    city=city,
                    state=state,
                    price=price,
                    lat=hit[0],
                    lon=hit[1],
                )
            )
    _catalog = depots
    return depots


def reset_catalog():
    global _catalog
    _catalog = None
