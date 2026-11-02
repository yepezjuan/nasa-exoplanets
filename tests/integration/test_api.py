import math
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from exoplanet_archive.api.main import create_app
from exoplanet_archive.db import get_session
from exoplanet_archive.ingest.load import run_ingest


def angular_separation(ra1, dec1, ra2, dec2):
    """Great-circle distance in degrees, using the haversine formula."""
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1, dec1, ra2, dec2))
    h = (
        math.sin((dec2 - dec1) / 2) ** 2
        + math.cos(dec1) * math.cos(dec2) * math.sin((ra2 - ra1) / 2) ** 2
    )
    return math.degrees(2 * math.asin(math.sqrt(h)))


def names(response):
    return [item["pl_name"] for item in response.json()["items"]]


def test_list_returns_every_planet(client, loaded):
    response = client.get("/planets")
    assert response.json()["total"] == len(loaded)
    assert sorted(names(response)) == sorted(row["pl_name"] for row in loaded)


def test_name_sort_directions_are_exact_reverses(client, loaded):
    # Compared this way because name order depends on the database collation.
    ascending = client.get("/planets", params={"order": "asc"})
    descending = client.get("/planets", params={"order": "desc"})
    assert names(ascending) == names(descending)[::-1]


def test_response_excludes_internal_columns(client, loaded):
    item = client.get("/planets", params={"limit": 1}).json()["items"][0]
    assert "content_hash" not in item
    assert "updated_at" not in item


def test_pagination_covers_every_row_exactly_once(client, loaded):
    seen = []
    for offset in range(0, len(loaded), 10):
        body = client.get("/planets", params={"limit": 10, "offset": offset}).json()
        assert body["total"] == len(loaded)
        assert body["limit"] == 10
        assert body["offset"] == offset
        seen += [item["pl_name"] for item in body["items"]]
    assert sorted(seen) == sorted(row["pl_name"] for row in loaded)
    assert len(seen) == len(set(seen))


def test_discovery_method_filter_ignores_case(client, loaded):
    response = client.get("/planets", params={"discovery_method": "transit", "limit": 500})
    expected = {r["pl_name"] for r in loaded if r["discovery_method"] == "Transit"}
    assert expected
    assert set(names(response)) == expected


def test_host_filter(client, loaded):
    host = loaded[0]["hostname"]
    response = client.get("/planets", params={"host": host.upper(), "limit": 500})
    assert set(names(response)) == {r["pl_name"] for r in loaded if r["hostname"] == host}


@pytest.mark.parametrize(
    ("low_param", "high_param", "column"),
    [
        ("disc_year_min", "disc_year_max", "disc_year"),
        ("radius_min", "radius_max", "radius_earth"),
        ("mass_min", "mass_max", "mass_earth"),
        ("period_min", "period_max", "orbital_period_days"),
        ("eq_temp_min", "eq_temp_max", "eq_temp_k"),
        ("distance_min", "distance_max", "distance_pc"),
    ],
)
def test_range_filters_match_a_manual_calculation(client, loaded, low_param, high_param, column):
    values = sorted(r[column] for r in loaded if r[column] is not None)
    low, high = values[len(values) // 4], values[3 * len(values) // 4]
    response = client.get("/planets", params={low_param: low, high_param: high, "limit": 500})
    expected = {r["pl_name"] for r in loaded if r[column] is not None and low <= r[column] <= high}
    assert expected
    assert set(names(response)) == expected


def test_sort_puts_nulls_last_in_both_directions(client, loaded):
    null_names = {r["pl_name"] for r in loaded if r["eq_temp_k"] is None}
    assert null_names
    for order in ("asc", "desc"):
        items = client.get(
            "/planets", params={"sort": "eq_temp", "order": order, "limit": 500}
        ).json()["items"]
        values = [i["eq_temp_k"] for i in items if i["eq_temp_k"] is not None]
        assert values == sorted(values, reverse=order == "desc")
        assert {i["pl_name"] for i in items[-len(null_names) :]} == null_names


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 501},
        {"limit": 0},
        {"offset": -1},
        {"sort": "content_hash"},
        {"order": "sideways"},
        {"radius_min": 5, "radius_max": 1},
        {"radius_min": "big"},
        {"not_a_filter": 1},
    ],
)
def test_invalid_list_parameters_return_422(client, params):
    assert client.get("/planets", params=params).status_code == 422


def test_get_planet(client, loaded):
    expected = loaded[0]
    response = client.get(f"/planets/{quote(expected['pl_name'])}")
    assert response.status_code == 200
    assert response.json()["hostname"] == expected["hostname"]


def test_get_planet_with_plus_in_name(client, loaded):
    name = next(r["pl_name"] for r in loaded if "+" in r["pl_name"])
    response = client.get(f"/planets/{quote(name)}")
    assert response.status_code == 200
    assert response.json()["pl_name"] == name


def test_get_unknown_planet_returns_404(client, loaded):
    response = client.get("/planets/Vulcan")
    assert response.status_code == 404
    assert "Vulcan" in response.json()["detail"]


@pytest.mark.parametrize(
    ("ra", "dec", "radius"),
    [
        (133.0, 28.0, 5.0),
        (290.0, 44.0, 20.0),  # The Kepler field, which holds many planets.
        (0.5, 0.0, 30.0),  # Crosses the RA 0/360 boundary.
        (359.9, -10.0, 45.0),
        (10.0, 89.5, 60.0),  # Reaches over the north celestial pole.
        (200.0, -89.0, 75.0),  # Reaches over the south celestial pole.
        (180.0, 0.0, 180.0),  # The whole sky.
    ],
)
def test_cone_search_matches_brute_force(client, loaded, ra, dec, radius):
    response = client.get(
        "/planets/cone", params={"ra": ra, "dec": dec, "radius_deg": radius, "limit": 500}
    )
    assert response.status_code == 200
    expected = {
        r["pl_name"]
        for r in loaded
        if angular_separation(ra, dec, r["ra_deg"], r["dec_deg"]) <= radius
    }
    assert set(names(response)) == expected
    assert response.json()["total"] == len(expected)


def test_cone_search_sorts_by_separation_and_reports_it(client, loaded):
    body = client.get(
        "/planets/cone", params={"ra": 290, "dec": 44, "radius_deg": 180, "limit": 500}
    ).json()
    separations = [item["separation_deg"] for item in body["items"]]
    assert separations == sorted(separations)
    for item in body["items"]:
        expected = angular_separation(290, 44, item["ra_deg"], item["dec_deg"])
        assert item["separation_deg"] == pytest.approx(expected, abs=1e-6)


def test_cone_search_with_no_matches(client, loaded):
    body = client.get("/planets/cone", params={"ra": 0, "dec": 0, "radius_deg": 1e-6}).json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"dec": 0, "radius_deg": 1},
        {"ra": 361, "dec": 0, "radius_deg": 1},
        {"ra": -1, "dec": 0, "radius_deg": 1},
        {"ra": 0, "dec": 91, "radius_deg": 1},
        {"ra": 0, "dec": 0, "radius_deg": 0},
        {"ra": 0, "dec": 0, "radius_deg": 181},
    ],
)
def test_invalid_cone_parameters_return_422(client, params):
    assert client.get("/planets/cone", params=params).status_code == 422


def test_health_reports_data_and_last_ingest(client, engine, raw_rows):
    assert client.get("/health").json()["last_successful_ingest"] is None

    run_ingest(engine, lambda: raw_rows, min_row_ratio=0.9, max_reject_ratio=0.01)

    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["planet_count"] == len(raw_rows)
    assert body["last_successful_ingest"] is not None


def test_health_returns_503_when_database_is_unreachable(engine):
    from fastapi.testclient import TestClient

    unreachable = create_engine(
        "postgresql+psycopg://nobody@localhost:1/nothing", connect_args={"connect_timeout": 1}
    )

    def broken_session():
        with Session(unreachable) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = broken_session
    with TestClient(app) as test_client:
        response = test_client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"


@pytest.mark.parametrize(
    "path",
    ["/planets", "/planets/Vulcan", "/planets/cone?ra=0&dec=0&radius_deg=1"],
)
def test_query_endpoints_return_503_when_database_is_unreachable(engine, path):
    from fastapi.testclient import TestClient

    unreachable = create_engine(
        "postgresql+psycopg://nobody@localhost:1/nothing", connect_args={"connect_timeout": 1}
    )

    def broken_session():
        with Session(unreachable) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = broken_session
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_metrics_use_route_templates_not_raw_paths(client, loaded):
    client.get("/planets/Vulcan")
    text = client.get("/metrics").text
    assert 'route="/planets/{pl_name}",status="404"' in text
    assert "Vulcan" not in text
    assert "http_request_duration_seconds_bucket" in text


def test_responses_carry_a_request_id(client):
    assert client.get("/health").headers["X-Request-ID"]
