from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from exoplanet_archive.db import get_session
from exoplanet_archive.ingest.load import STATUS_SUCCESS
from exoplanet_archive.models import IngestRun, Planet
from exoplanet_archive.schemas import HealthOut

log = structlog.get_logger(__name__)

router = APIRouter(tags=["operations"])


@router.get("/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthOut:
    try:
        planet_count = session.scalar(select(func.count()).select_from(Planet))
        last_ingest = session.scalar(
            select(func.max(IngestRun.finished_at)).where(IngestRun.status == STATUS_SUCCESS)
        )
    except SQLAlchemyError as exc:
        log.error("health_check_failed", error=str(exc)[:500])
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthOut(status="unavailable", database="unreachable")
    return HealthOut(
        status="ok",
        database="ok",
        planet_count=planet_count,
        last_successful_ingest=last_ingest,
    )


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
