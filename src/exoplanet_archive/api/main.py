import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from exoplanet_archive.api.middleware import RequestObservabilityMiddleware
from exoplanet_archive.api.routes import health, planets
from exoplanet_archive.config import get_settings
from exoplanet_archive.logging import configure_logging

log = structlog.get_logger(__name__)


async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.error("database_unavailable", path=request.url.path, error=str(exc)[:500])
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


def create_app() -> FastAPI:
    configure_logging(get_settings().log_level)
    app = FastAPI(
        title="Exoplanet Query API",
        description="Query confirmed exoplanets ingested from the NASA Exoplanet Archive.",
        version="0.1.0",
    )
    app.add_middleware(RequestObservabilityMiddleware)
    app.add_exception_handler(OperationalError, database_unavailable)
    app.include_router(planets.router)
    app.include_router(health.router)
    return app


app = create_app()
