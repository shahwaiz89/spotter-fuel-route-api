"""One shared doorway for all outbound HTTP.

Every external call in this project (Nominatim, OSRM) goes through
``get`` so timeouts, the User-Agent header and a diagnostic call log
live in exactly one place. Tests use CALL_LOG to assert the
"minimal routing API calls" requirement.
"""

import requests

REQUEST_TIMEOUT = 10
USER_AGENT = "tripfuel-spotter-assessment/1.0"

# Simple in-memory log of (service, url) for every outbound request.
CALL_LOG = []


def reset_log():
    del CALL_LOG[:]


def get(service, url, params=None):
    """GET with a fixed timeout and User-Agent; raises on transport errors."""
    CALL_LOG.append((service, url))
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response
