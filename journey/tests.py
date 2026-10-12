"""Tests: optimizer unit tests + API tests (network fully mocked)."""

from unittest.mock import Mock, patch

import requests
from django.test import TestCase
from rest_framework.test import APIClient

from journey import depots as depot_store
from journey import geo, http, road
from journey.road import NoRouteError
from journey.depots import Depot
from journey.optimizer import (
    InfeasibleTrip,
    cheapest_plan,
    haversine_miles,
    locate_depots,
    route_mileposts,
)


def make_depot(name, along_miles, price):
    depot = Depot(
        opis_id="1", name=name, address="123 HWY", city="Town",
        state="CO", price=price, lat=39.0, lon=-105.0,
    )
    depot.along_miles = along_miles
    depot.detour_miles = 1.0
    return depot


class OptimizerTests(TestCase):
    def test_haversine_sanity(self):
        # One degree of latitude is ~69 miles.
        self.assertAlmostEqual(haversine_miles(39.0, -105.0, 40.0, -105.0), 69.0, delta=1.0)

    def test_route_mileposts(self):
        _, total = route_mileposts([[-105.0, 39.0], [-105.0, 40.0]])
        self.assertAlmostEqual(total, 69.0, delta=1.0)

    def test_cheapest_plan_picks_cheaper_reachable(self):
        # 800-mile trip, full tank at start. Both stations reachable on the
        # opening tank; the cheaper one ($3.00) must win.
        a = make_depot("EXPENSIVE", 400.0, 4.00)
        b = make_depot("CHEAP", 450.0, 3.00)
        plan = cheapest_plan(800.0, [a, b])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0][0].name, "CHEAP")
        self.assertAlmostEqual(plan[0][1], 35.0)  # 350 miles / 10 MPG

    def test_cheapest_plan_multiple_stops(self):
        a = make_depot("FIRST", 450.0, 5.00)
        b = make_depot("SECOND", 800.0, 3.00)
        plan = cheapest_plan(900.0, [a, b])
        self.assertEqual([d.name for d, _ in plan], ["FIRST", "SECOND"])
        self.assertAlmostEqual(plan[0][1], 35.0)
        self.assertAlmostEqual(plan[1][1], 10.0)

    def test_infeasible_gap_raises(self):
        a = make_depot("ONLY", 400.0, 3.00)
        with self.assertRaises(InfeasibleTrip):
            cheapest_plan(1200.0, [a])

    def test_locate_depots_filters_by_detour(self):
        # Straight east-west route along 39N.
        coords = [[-106.0, 39.0], [-104.0, 39.0]]
        mileposts, _ = route_mileposts(coords)
        close = Depot(opis_id="1", name="CLOSE", address="a", city="T",
                      state="CO", price=3.0, lat=39.02, lon=-105.0)
        far = Depot(opis_id="2", name="FAR", address="a", city="T",
                    state="CO", price=2.5, lat=39.8, lon=-105.0)
        near = locate_depots(coords, mileposts, [close, far])
        self.assertEqual([d.name for d in near], ["CLOSE"])
        self.assertLess(near[0].detour_miles, 10.0)


class RoadClientTests(TestCase):
    def test_osrm_noroute_becomes_422(self):
        # OSRM answers impossible routes with HTTP 400 + {"code": "NoRoute"}.
        err = requests.HTTPError("400 Client Error")
        err.response = Mock(status_code=400)
        err.response.json.return_value = {"code": "NoRoute", "message": "Impossible route"}
        with patch("journey.http.get", side_effect=err):
            with self.assertRaises(NoRouteError):
                road.fetch_route(21.3069, -157.8583, 25.7617, -80.1918)


class RouteApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        geo._memory.clear()
        geo._file = {}
        http.reset_log()
        depot_store.reset_catalog()

    def test_blank_fields_rejected(self):
        response = self.client.post("/api/route/", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_bad_format_rejected(self):
        response = self.client.post(
            "/api/route/",
            {"start_location": "Denver", "finish_location": "Dallas, TX"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_happy_path_shape(self):
        fake_result = {
            "start_location": "Denver, CO",
            "finish_location": "Dallas, TX",
            "total_distance_miles": 780.4,
            "total_fuel_cost_usd": 100.0,
            "gallons_used": 33.3,
            "fuel_stops": [],
            "route_geometry": {"type": "LineString", "coordinates": []},
        }
        with patch("journey.api.engine.plan_trip", return_value=fake_result):
            response = self.client.post(
                "/api/route/",
                {"start_location": "Denver, CO", "finish_location": "Dallas, TX"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_distance_miles"], 780.4)

    def test_infeasible_returns_422(self):
        with patch("journey.api.engine.plan_trip", side_effect=InfeasibleTrip("nope")):
            response = self.client.post(
                "/api/route/",
                {"start_location": "Denver, CO", "finish_location": "Dallas, TX"},
                format="json",
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("error", response.json())

    def _fake_http(self, mock_get):
        def fake(service, url, params=None):
            # The mock replaces http.get, so log the call the way the real
            # implementation would.
            http.CALL_LOG.append((service, url))
            resp = Mock()
            if service == "nominatim":
                resp.json.return_value = [{"lat": "39.7", "lon": "-105.0"}]
            else:
                resp.json.return_value = {
                    "code": "Ok",
                    "routes": [{
                        "distance": 160934.4,  # 100 miles
                        "geometry": {"coordinates": [[-105.0, 39.7], [-104.0, 39.7]]},
                    }],
                }
            return resp
        mock_get.side_effect = fake

    def test_outbound_call_budget(self):
        """Cold cache: 2 geocodes + 1 route. Warm cache: route only."""
        with patch("journey.http.get") as mock_get, \
             patch("journey.depots.load_depots", return_value=[]):
            self._fake_http(mock_get)
            first = self.client.post(
                "/api/route/",
                {"start_location": "Denver, CO", "finish_location": "Limon, CO"},
                format="json",
            )
            self.assertEqual(first.status_code, 200)
            services = [s for s, _ in http.CALL_LOG]
            self.assertEqual(services.count("nominatim"), 2)
            self.assertEqual(services.count("osrm"), 1)

            http.reset_log()
            second = self.client.post(
                "/api/route/",
                {"start_location": "Denver, CO", "finish_location": "Limon, CO"},
                format="json",
            )
            self.assertEqual(second.status_code, 200)
            services = [s for s, _ in http.CALL_LOG]
            self.assertEqual(services, ["osrm"])
