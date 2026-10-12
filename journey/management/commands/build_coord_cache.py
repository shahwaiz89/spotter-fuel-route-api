"""One-time job: geocode every US city/state pair from the fuel-price CSV.

Writes ``journey/data/station_coords.json``. Respects Nominatim's usage
policy (1 request/second), skips Canadian provinces entirely (the
assessment is USA-only), and saves progress incrementally so an
interrupted run can simply be re-run to completion.
"""

import json
import time

from django.core.management.base import BaseCommand

from journey import http
from journey.depots import us_places
from journey.geo import CACHE_PATH, NOMINATIM_URL, cache_key


class Command(BaseCommand):
    help = "Geocode all US station cities into journey/data/station_coords.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Only geocode the first N places (0 = all).",
        )
        parser.add_argument(
            "--delay", type=float, default=1.0,
            help="Seconds to wait between Nominatim requests (policy: >= 1).",
        )

    def handle(self, *args, **options):
        places = us_places()
        if options["limit"]:
            places = places[: options["limit"]]

        cache = {}
        if CACHE_PATH.exists():
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        todo = [(c, s) for c, s in places if cache_key(c, s) not in cache]
        self.stdout.write(f"{len(places)} US places; {len(todo)} still to geocode.")

        batch, done = {}, 0
        for city, state in todo:
            try:
                payload = http.get(
                    "nominatim", NOMINATIM_URL,
                    params={"q": f"{city}, {state}, USA", "format": "json", "limit": 1},
                ).json()
            except Exception as exc:  # network hiccup: log and move on
                self.stderr.write(f"SKIP {city}, {state}: {exc}")
            else:
                if payload:
                    batch[cache_key(city, state)] = [
                        float(payload[0]["lat"]), float(payload[0]["lon"])
                    ]
                else:
                    self.stderr.write(f"NO RESULT for {city}, {state}")
            done += 1
            if done % 25 == 0:
                cache.update(batch)
                batch = {}
                CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")
                self.stdout.write(f"... {done}/{len(todo)} geocoded")
            time.sleep(options["delay"])

        if batch:
            cache.update(batch)
            CACHE_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(
            f"Done. Cache now holds {len(cache)} places."
        ))
