"""Integration tests run against a dedicated database on the Compose `db` service."""

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

SERVER_URL = make_url(
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://exoplanet:exoplanet@localhost:5432/exoplanet_test",
    )
)
# Must be set before the app reads its settings, so tests can never touch the dev database.
os.environ["DATABASE_URL"] = SERVER_URL.render_as_string(hide_password=False)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from exoplanet_archive.api.main import create_app  # noqa: E402
from exoplanet_archive.db import get_engine  # noqa: E402
from exoplanet_archive.ingest.load import load_snapshot  # noqa: E402
from exoplanet_archive.ingest.transform import transform  # noqa: E402


def _recreate_database() -> None:
    admin = create_engine(SERVER_URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{SERVER_URL.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{SERVER_URL.database}"'))
    admin.dispose()


def _alembic_config() -> Config:
    config = Config("alembic.ini")
    config.attributes["url"] = os.environ["DATABASE_URL"]
    return config


@pytest.fixture(scope="session")
def migrated_engine():
    _recreate_database()
    command.upgrade(_alembic_config(), "head")
    yield get_engine()
    get_engine().dispose()


@pytest.fixture
def engine(migrated_engine):
    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE planets, ingest_runs RESTART IDENTITY"))
    return migrated_engine


@pytest.fixture
def client(engine):
    with TestClient(create_app(), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def loaded(engine, raw_rows):
    """The database with the sample rows loaded. Returns those rows in their stored form."""
    rows = transform(raw_rows).rows
    with Session(engine) as session, session.begin():
        load_snapshot(session, rows)
    return rows
