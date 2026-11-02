from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from exoplanet_archive.ingest import load
from exoplanet_archive.ingest.load import run_ingest
from exoplanet_archive.models import IngestRun, Planet


def ingest(engine, rows):
    return run_ingest(engine, lambda: rows, min_row_ratio=0.9, max_reject_ratio=0.01)


def planet_count(engine):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Planet))


def get_planet(engine, name):
    with Session(engine, expire_on_commit=False) as session:
        return session.get(Planet, name)


def test_migrations_create_tables_and_cone_index(engine):
    inspector = inspect(engine)
    assert {"planets", "ingest_runs"} <= set(inspector.get_table_names())
    with engine.connect() as connection:
        indexdef = connection.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_planets_q3c'")
        )
    assert "q3c_ang2ipix" in indexdef


def test_first_ingest_inserts_every_row(engine, raw_rows):
    run = ingest(engine, raw_rows)
    assert run.status == "success"
    assert (run.fetched, run.inserted, run.updated, run.deleted, run.rejected) == (
        len(raw_rows),
        len(raw_rows),
        0,
        0,
        0,
    )
    assert run.finished_at is not None
    assert planet_count(engine) == len(raw_rows)


def test_repeat_ingest_changes_nothing(engine, raw_rows):
    ingest(engine, raw_rows)
    before = get_planet(engine, raw_rows[0]["pl_name"]).updated_at

    run = ingest(engine, raw_rows)

    assert run.status == "success"
    assert (run.inserted, run.updated, run.deleted) == (0, 0, 0)
    assert get_planet(engine, raw_rows[0]["pl_name"]).updated_at == before


def test_changed_rows_are_updated(engine, raw_rows):
    ingest(engine, raw_rows)
    name = raw_rows[0]["pl_name"]
    before = get_planet(engine, name).updated_at
    changed = [{**raw_rows[0], "pl_rade": 123.0}, *raw_rows[1:]]

    run = ingest(engine, changed)

    assert (run.inserted, run.updated, run.deleted) == (0, 1, 0)
    planet = get_planet(engine, name)
    assert planet.radius_earth == 123.0
    assert planet.updated_at > before


def test_rows_missing_from_the_snapshot_are_deleted(engine, raw_rows):
    ingest(engine, raw_rows)
    run = ingest(engine, raw_rows[1:])
    assert (run.inserted, run.updated, run.deleted) == (0, 0, 1)
    assert get_planet(engine, raw_rows[0]["pl_name"]) is None


def test_a_small_rejected_share_is_tolerated(engine, raw_rows):
    run = run_ingest(
        engine,
        lambda: [{**raw_rows[0], "ra": None}, *raw_rows[1:]],
        min_row_ratio=0.9,
        max_reject_ratio=0.5,
    )
    assert run.status == "success"
    assert run.rejected == 1
    assert run.inserted == len(raw_rows) - 1


def test_shrunken_snapshot_aborts_and_keeps_data(engine, raw_rows):
    ingest(engine, raw_rows)

    run = ingest(engine, raw_rows[:5])

    assert run.status == "aborted"
    assert "under 90%" in run.detail
    assert planet_count(engine) == len(raw_rows)


def test_mostly_invalid_snapshot_aborts_and_keeps_data(engine, raw_rows):
    ingest(engine, raw_rows)
    corrupted = [{**row, "ra": None} for row in raw_rows[:10]] + raw_rows[10:]

    run = ingest(engine, corrupted)

    assert run.status == "aborted"
    assert run.rejected == 10
    assert planet_count(engine) == len(raw_rows)
    assert get_planet(engine, raw_rows[0]["pl_name"]) is not None


def test_empty_snapshot_aborts_and_keeps_data(engine, raw_rows):
    ingest(engine, raw_rows)
    run = ingest(engine, [])
    assert run.status == "aborted"
    assert planet_count(engine) == len(raw_rows)


def test_fetch_failure_is_recorded_and_keeps_data(engine, raw_rows):
    ingest(engine, raw_rows)

    def failing_fetch():
        raise RuntimeError("archive is down")

    run = run_ingest(engine, failing_fetch, min_row_ratio=0.9, max_reject_ratio=0.01)

    assert run.status == "failed"
    assert run.detail == "archive is down"
    assert planet_count(engine) == len(raw_rows)


def test_failure_during_load_rolls_back_partial_work(engine, raw_rows, monkeypatch):
    ingest(engine, raw_rows)
    changed = [{**row, "pl_rade": 999.0} for row in raw_rows]
    real_load = load.load_snapshot

    def load_then_fail(session, rows):
        real_load(session, rows)
        raise RuntimeError("disk full")

    monkeypatch.setattr(load, "load_snapshot", load_then_fail)

    run = ingest(engine, changed)

    assert run.status == "failed"
    assert run.fetched == len(raw_rows)  # Counts recorded before the load survive the rollback.
    assert run.updated == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).where(Planet.radius_earth == 999.0)) == 0
        statuses = session.scalars(select(IngestRun.status).order_by(IngestRun.id)).all()
    assert statuses == ["success", "failed"]
