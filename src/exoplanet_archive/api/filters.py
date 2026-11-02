"""Query parameters for GET /planets, and their translation into SQL."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ColumnElement, UnaryExpression, func

from exoplanet_archive.models import Planet

# (minimum parameter, maximum parameter, column)
RANGE_FILTERS = (
    ("disc_year_min", "disc_year_max", Planet.disc_year),
    ("radius_min", "radius_max", Planet.radius_earth),
    ("mass_min", "mass_max", Planet.mass_earth),
    ("period_min", "period_max", Planet.orbital_period_days),
    ("eq_temp_min", "eq_temp_max", Planet.eq_temp_k),
    ("distance_min", "distance_max", Planet.distance_pc),
)

SORT_COLUMNS = {
    "pl_name": Planet.pl_name,
    "disc_year": Planet.disc_year,
    "radius": Planet.radius_earth,
    "mass": Planet.mass_earth,
    "period": Planet.orbital_period_days,
    "eq_temp": Planet.eq_temp_k,
    "distance": Planet.distance_pc,
}

SortField = Literal["pl_name", "disc_year", "radius", "mass", "period", "eq_temp", "distance"]


class PlanetQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discovery_method: str | None = None
    host: str | None = None
    disc_year_min: int | None = None
    disc_year_max: int | None = None
    radius_min: float | None = None
    radius_max: float | None = None
    mass_min: float | None = None
    mass_max: float | None = None
    period_min: float | None = None
    period_max: float | None = None
    eq_temp_min: float | None = None
    eq_temp_max: float | None = None
    distance_min: float | None = None
    distance_max: float | None = None
    sort: SortField = "pl_name"
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def check_ranges(self) -> Self:
        for min_name, max_name, _ in RANGE_FILTERS:
            low, high = getattr(self, min_name), getattr(self, max_name)
            if low is not None and high is not None and low > high:
                raise ValueError(f"{min_name} must not be greater than {max_name}")
        return self


def build_conditions(query: PlanetQuery) -> list[ColumnElement[bool]]:
    """Build WHERE clauses. A range filter excludes planets with no value for that column."""
    conditions: list[ColumnElement[bool]] = []
    if query.discovery_method is not None:
        conditions.append(func.lower(Planet.discovery_method) == query.discovery_method.lower())
    if query.host is not None:
        conditions.append(func.lower(Planet.hostname) == query.host.lower())
    for min_name, max_name, column in RANGE_FILTERS:
        low, high = getattr(query, min_name), getattr(query, max_name)
        if low is not None:
            conditions.append(column >= low)
        if high is not None:
            conditions.append(column <= high)
    return conditions


def build_order(query: PlanetQuery) -> list[UnaryExpression[object] | object]:
    """Order by the chosen column, nulls last, using the name as a tiebreak for stable paging."""
    column = SORT_COLUMNS[query.sort]
    primary = column.desc() if query.order == "desc" else column.asc()
    return [primary.nulls_last(), Planet.pl_name.asc()]
