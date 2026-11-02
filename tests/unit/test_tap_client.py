import httpx
import pytest
from tenacity import wait_none

from exoplanet_archive.ingest.tap_client import (
    PLANET_QUERY,
    TapError,
    TapUnavailable,
    fetch_planets,
    parse_response,
)

URL = "https://tap.example/sync"
# The shape of a real error response from the archive, which arrives with HTTP 200.
VOTABLE_ERROR = """<?xml version="1.0" encoding="UTF-8"?>
<VOTABLE version="1.4"><RESOURCE type="results">
<INFO name="QUERY_STATUS" value="ERROR">ORA-00904: 'ROWUPDATE': invalid identifier</INFO>
</RESOURCE></VOTABLE>"""


def fetch_with(handler, attempts=3):
    calls = []

    def recording_handler(request):
        calls.append(request)
        return handler(len(calls))

    with httpx.Client(transport=httpx.MockTransport(recording_handler)) as client:
        return fetch_planets(client, URL, attempts=attempts, wait=wait_none()), calls


def test_parse_response_returns_rows():
    assert parse_response('[{"pl_name": "55 Cnc b"}]') == [{"pl_name": "55 Cnc b"}]


def test_parse_response_detects_votable_error_sent_as_200():
    with pytest.raises(TapError, match="ORA-00904"):
        parse_response(VOTABLE_ERROR)


@pytest.mark.parametrize("body", ["not json", '{"pl_name": "x"}', "[1, 2]"])
def test_parse_response_rejects_unexpected_bodies(body):
    with pytest.raises(TapError):
        parse_response(body)


def test_fetch_sends_the_query_as_json():
    rows, calls = fetch_with(lambda _: httpx.Response(200, text="[]"))
    assert rows == []
    assert calls[0].url.params["query"] == PLANET_QUERY
    assert calls[0].url.params["format"] == "json"


def test_fetch_retries_server_errors_then_succeeds():
    rows, calls = fetch_with(
        lambda n: httpx.Response(503) if n < 3 else httpx.Response(200, text='[{"a": 1}]')
    )
    assert rows == [{"a": 1}]
    assert len(calls) == 3


def test_fetch_retries_network_errors_then_gives_up():
    def fail(_):
        raise httpx.ConnectTimeout("timed out")

    with pytest.raises(TapUnavailable):
        fetch_with(fail)


def test_fetch_does_not_retry_query_errors():
    attempts = []

    def handler(n):
        attempts.append(n)
        return httpx.Response(200, text=VOTABLE_ERROR)

    with pytest.raises(TapError):
        fetch_with(handler)
    assert attempts == [1]


def test_fetch_does_not_retry_client_errors():
    attempts = []

    def handler(n):
        attempts.append(n)
        return httpx.Response(400, text="bad query")

    with pytest.raises(TapError, match="HTTP 400"):
        fetch_with(handler)
    assert attempts == [1]
