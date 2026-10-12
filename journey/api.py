"""HTTP layer: a single POST endpoint that plans the trip."""

import requests
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import engine
from .geo import GeocodeError
from .optimizer import InfeasibleTrip
from .road import NoRouteError, RoutingError
from .schemas import RouteRequestSerializer


class RoutePlanView(APIView):
    """POST /api/route/ -> cheapest-fuel trip plan as JSON."""

    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        start = serializer.validated_data["start_location"]
        finish = serializer.validated_data["finish_location"]
        try:
            result = engine.plan_trip(start, finish)
        except NoRouteError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except InfeasibleTrip as exc:
            return Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except GeocodeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except RoutingError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except requests.RequestException as exc:
            return Response(
                {"error": f"Upstream request failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(result, status=status.HTTP_200_OK)
