"""Client for the NASA Exoplanet Archive TAP service."""

import json
from typing import Any

import httpx
import structlog
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import wait_base

log = structlog.get_logger(__name__)

PLANET_QUERY = (
    "select pl_name, hostname, discoverymethod, disc_year, disc_facility, pl_orbper, pl_rade, "
    "pl_bmasse, pl_eqt, sy_dist, st_teff, ra, dec from pscomppars"
)


class TapError(Exception):
    """The service answered, but the response is not a usable result. Retrying will not help."""


class TapUnavailable(Exception):
    """A network failure or 5xx response, which may succeed on retry."""


def parse_response(body: str) -> list[dict[str, Any]]:
    """Parse a TAP JSON response into rows.

    TAP reports query errors as a VOTable XML document with a 200 status, so a successful
    status code does not mean the body holds rows.
    """
    if body.lstrip().startswith("<"):
        raise TapError(f"expected JSON rows, got XML: {body.strip()[:500]}")
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise TapError(f"response is not valid JSON: {exc}") from exc
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TapError("expected a JSON array of objects")
    return rows


def _fetch_once(client: httpx.Client, url: str) -> list[dict[str, Any]]:
    try:
        response = client.get(url, params={"query": PLANET_QUERY, "format": "json"})
    except httpx.TransportError as exc:
        raise TapUnavailable(str(exc)) from exc
    if response.status_code >= 500:
        raise TapUnavailable(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise TapError(f"HTTP {response.status_code}: {response.text[:500]}")
    return parse_response(response.text)


def fetch_planets(
    client: httpx.Client,
    url: str,
    attempts: int = 4,
    wait: wait_base | None = None,
) -> list[dict[str, Any]]:
    retrying = Retrying(
        retry=retry_if_exception_type(TapUnavailable),
        stop=stop_after_attempt(attempts),
        wait=wait or wait_exponential(multiplier=2, max=30),
        before_sleep=lambda state: log.warning(
            "tap_fetch_retry",
            attempt=state.attempt_number,
            error=str(state.outcome.exception()) if state.outcome else None,
        ),
        reraise=True,
    )
    return retrying(_fetch_once, client, url)
