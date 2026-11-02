from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from exoplanet_archive.api.filters import PlanetQuery, build_conditions, build_order
from exoplanet_archive.db import get_session
from exoplanet_archive.models import Planet
from exoplanet_archive.schemas import ConeMatch, ConePage, PlanetOut, PlanetPage

router = APIRouter(prefix="/planets", tags=["planets"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.get("")
def list_planets(query: Annotated[PlanetQuery, Query()], session: SessionDep) -> PlanetPage:
    conditions = build_conditions(query)
    total = session.scalar(select(func.count()).select_from(Planet).where(*conditions)) or 0
    planets = session.scalars(
        select(Planet)
        .where(*conditions)
        .order_by(*build_order(query))  # type: ignore[arg-type]
        .limit(query.limit)
        .offset(query.offset)
    ).all()
    return PlanetPage(
        total=total,
        limit=query.limit,
        offset=query.offset,
        items=[PlanetOut.model_validate(planet) for planet in planets],
    )


# Declared before /{pl_name} so that "cone" isn't treated as a planet name.
@router.get("/cone")
def cone_search(
    session: SessionDep,
    ra: Annotated[float, Query(ge=0, le=360, description="Right ascension (deg, ICRS)")],
    dec: Annotated[float, Query(ge=-90, le=90, description="Declination (deg, ICRS)")],
    radius_deg: Annotated[float, Query(gt=0, le=180, description="Search radius (deg)")],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConePage:
    in_cone = func.q3c_radial_query(Planet.ra_deg, Planet.dec_deg, ra, dec, radius_deg)
    separation = func.q3c_dist(Planet.ra_deg, Planet.dec_deg, ra, dec)
    total = session.scalar(select(func.count()).select_from(Planet).where(in_cone)) or 0
    rows = session.execute(
        select(Planet, separation.label("separation_deg"))
        .where(in_cone)
        .order_by(separation, Planet.pl_name)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        ConeMatch(
            **PlanetOut.model_validate(planet).model_dump(),
            separation_deg=separation_deg,
        )
        for planet, separation_deg in rows
    ]
    return ConePage(total=total, limit=limit, offset=offset, items=items)


@router.get("/{pl_name}")
def get_planet(pl_name: str, session: SessionDep) -> PlanetOut:
    planet = session.get(Planet, pl_name)
    if planet is None:
        raise HTTPException(status_code=404, detail=f"Planet not found: {pl_name}")
    return PlanetOut.model_validate(planet)
