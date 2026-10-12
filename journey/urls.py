"""URL routes for the journey app."""

from django.urls import path

from .api import RoutePlanView

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
]
