from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlanetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pl_name: str
    hostname: str
    discovery_method: str
    disc_year: int
    disc_facility: str | None
    orbital_period_days: float | None
    radius_earth: float | None
    mass_earth: float | None
    eq_temp_k: float | None
    distance_pc: float | None
    stellar_teff_k: float | None
    ra_deg: float
    dec_deg: float


class PlanetPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[PlanetOut]


class ConeMatch(PlanetOut):
    separation_deg: float


class ConePage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ConeMatch]


class HealthOut(BaseModel):
    status: str
    database: str
    planet_count: int | None = None
    last_successful_ingest: datetime | None = None
