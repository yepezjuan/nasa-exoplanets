"""ORM mappings. The schema itself, including indexes, is defined by the Alembic migrations."""

from datetime import datetime

from sqlalchemy import DateTime, Double, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Planet(Base):
    __tablename__ = "planets"

    pl_name: Mapped[str] = mapped_column(primary_key=True)
    hostname: Mapped[str]
    discovery_method: Mapped[str]
    disc_year: Mapped[int]
    disc_facility: Mapped[str | None]
    orbital_period_days: Mapped[float | None] = mapped_column(Double)
    radius_earth: Mapped[float | None] = mapped_column(Double)
    mass_earth: Mapped[float | None] = mapped_column(Double)
    eq_temp_k: Mapped[float | None] = mapped_column(Double)
    distance_pc: Mapped[float | None] = mapped_column(Double)
    stellar_teff_k: Mapped[float | None] = mapped_column(Double)
    ra_deg: Mapped[float] = mapped_column(Double)
    dec_deg: Mapped[float] = mapped_column(Double)
    content_hash: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched: Mapped[int] = mapped_column(default=0)
    inserted: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    deleted: Mapped[int] = mapped_column(default=0)
    rejected: Mapped[int] = mapped_column(default=0)
    detail: Mapped[str | None]
