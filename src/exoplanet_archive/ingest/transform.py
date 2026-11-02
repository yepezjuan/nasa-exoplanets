"""Validate raw archive rows and map them onto our column names."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

NonEmptyStr = Annotated[str, Field(min_length=1)]


class ArchiveRow(BaseModel):
    """One row of `pscomppars`. Only the identifying fields and coordinates are required."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True, allow_inf_nan=False)

    pl_name: NonEmptyStr
    hostname: NonEmptyStr
    discoverymethod: NonEmptyStr
    disc_year: int
    disc_facility: str | None = None
    pl_orbper: float | None = None
    pl_rade: float | None = None
    pl_bmasse: float | None = None
    pl_eqt: float | None = None
    sy_dist: float | None = None
    st_teff: float | None = None
    ra: float = Field(ge=0, le=360)
    dec: float = Field(ge=-90, le=90)


@dataclass
class TransformResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fetched(self) -> int:
        return len(self.rows) + len(self.rejected)


def content_hash(values: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def to_db_row(row: ArchiveRow) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pl_name": row.pl_name,
        "hostname": row.hostname,
        "discovery_method": row.discoverymethod,
        "disc_year": row.disc_year,
        "disc_facility": row.disc_facility,
        "orbital_period_days": row.pl_orbper,
        "radius_earth": row.pl_rade,
        "mass_earth": row.pl_bmasse,
        "eq_temp_k": row.pl_eqt,
        "distance_pc": row.sy_dist,
        "stellar_teff_k": row.st_teff,
        "ra_deg": row.ra,
        "dec_deg": row.dec,
    }
    return {**values, "content_hash": content_hash(values)}


def transform(raw_rows: Iterable[dict[str, Any]]) -> TransformResult:
    result = TransformResult()
    seen: set[str] = set()
    for raw in raw_rows:
        name = raw.get("pl_name")
        try:
            row = ArchiveRow.model_validate(raw)
        except ValidationError as exc:
            errors = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            result.rejected.append({"pl_name": name, "errors": errors})
            continue
        # A repeated key would make the batched upsert fail with a cardinality error.
        if row.pl_name in seen:
            result.rejected.append({"pl_name": name, "errors": ["duplicate pl_name"]})
            continue
        seen.add(row.pl_name)
        result.rows.append(to_db_row(row))
    return result


def check_snapshot(
    valid: int,
    rejected: int,
    current_count: int,
    min_row_ratio: float,
    max_reject_ratio: float,
) -> str | None:
    """Return why a snapshot looks wrong and must not be loaded, or None if it looks fine."""
    if valid == 0:
        return "snapshot contains no valid rows"
    reject_ratio = rejected / (valid + rejected)
    if reject_ratio > max_reject_ratio:
        return (
            f"rejected {rejected} of {valid + rejected} rows, over the {max_reject_ratio:.1%} limit"
        )
    if valid < current_count * min_row_ratio:
        return (
            f"snapshot has {valid} valid rows, under {min_row_ratio:.0%} "
            f"of the {current_count} currently stored"
        )
    return None
