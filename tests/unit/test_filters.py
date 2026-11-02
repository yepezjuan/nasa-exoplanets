import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from exoplanet_archive.api.filters import PlanetQuery, build_conditions, build_order


def compiled(clause) -> str:
    dialect = postgresql.dialect()
    return str(clause.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def test_no_filters_means_no_conditions():
    assert build_conditions(PlanetQuery()) == []


def test_range_bounds_are_inclusive():
    conditions = build_conditions(PlanetQuery(radius_min=1.0, radius_max=2.0))
    assert [compiled(c) for c in conditions] == [
        "planets.radius_earth >= 1.0",
        "planets.radius_earth <= 2.0",
    ]


def test_zero_is_applied_as_a_filter():
    conditions = build_conditions(PlanetQuery(eq_temp_min=0))
    assert [compiled(c) for c in conditions] == ["planets.eq_temp_k >= 0.0"]


def test_text_filters_are_case_insensitive():
    conditions = build_conditions(PlanetQuery(discovery_method="TRANSIT", host="55 Cnc"))
    assert [compiled(c) for c in conditions] == [
        "lower(planets.discovery_method) = 'transit'",
        "lower(planets.hostname) = '55 cnc'",
    ]


def test_order_puts_nulls_last_with_a_stable_tiebreak():
    order = build_order(PlanetQuery(sort="mass", order="desc"))
    assert [compiled(o) for o in order] == [
        "planets.mass_earth DESC NULLS LAST",
        "planets.pl_name ASC",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"radius_min": 2, "radius_max": 1},
        {"disc_year_min": 2020, "disc_year_max": 2000},
        {"sort": "content_hash"},
        {"limit": 0},
        {"limit": 501},
        {"offset": -1},
        {"unknown_filter": 1},
    ],
)
def test_invalid_parameters_are_rejected(params):
    with pytest.raises(ValidationError):
        PlanetQuery(**params)
