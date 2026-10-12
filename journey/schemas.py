"""Request validation for the trip-planning endpoint."""

from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start_location = serializers.CharField(max_length=120)
    finish_location = serializers.CharField(max_length=120)

    def _clean_place(self, field, value):
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        if "," not in value:
            raise serializers.ValidationError("Use the 'City, ST' format, e.g. 'Denver, CO'.")
        city, state = [part.strip() for part in value.rsplit(",", 1)]
        if not city or not state:
            raise serializers.ValidationError("Both a city and a state are required.")
        return f"{city}, {state}"

    def validate(self, attrs):
        attrs["start_location"] = self._clean_place("start_location", attrs.get("start_location"))
        attrs["finish_location"] = self._clean_place("finish_location", attrs.get("finish_location"))
        return attrs
