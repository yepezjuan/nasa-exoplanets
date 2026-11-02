from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from exoplanet_archive.config import get_settings


@lru_cache
def get_engine() -> Engine:
    # The short connect timeout lets /health report a database outage promptly.
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
