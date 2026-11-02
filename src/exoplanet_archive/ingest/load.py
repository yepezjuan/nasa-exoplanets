"""Load a validated snapshot into PostgreSQL and record the run."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import (
    ARRAY,
    Boolean,
    Engine,
    Text,
    all_,
    delete,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from exoplanet_archive.ingest.transform import check_snapshot, transform
from exoplanet_archive.models import IngestRun, Planet

log = structlog.get_logger(__name__)

BATCH_SIZE = 1000

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ABORTED = "aborted"
STATUS_FAILED = "failed"


@dataclass
class LoadCounts:
    inserted: int = 0
    updated: int = 0
    deleted: int = 0


def load_snapshot(session: Session, rows: list[dict[str, Any]]) -> LoadCounts:
    """Make `planets` match the snapshot. The caller owns the transaction."""
    counts = LoadCounts()
    for start in range(0, len(rows), BATCH_SIZE):
        base = insert(Planet).values(rows[start : start + BATCH_SIZE])
        columns = {c.name: c for c in base.excluded if c.name not in ("pl_name", "updated_at")}
        upsert = base.on_conflict_do_update(
            index_elements=[Planet.pl_name],
            set_={**columns, "updated_at": func.now()},
            # Unchanged rows are skipped, so they aren't rewritten or counted.
            where=Planet.content_hash != base.excluded.content_hash,
        ).returning(literal_column("xmax = 0", Boolean))  # xmax is 0 only for a new row.
        for (was_inserted,) in session.execute(upsert):
            if was_inserted:
                counts.inserted += 1
            else:
                counts.updated += 1

    names = [row["pl_name"] for row in rows]
    deleted = session.scalars(
        delete(Planet)
        .where(Planet.pl_name != all_(literal(names, ARRAY(Text))))
        .returning(Planet.pl_name)
    ).all()
    counts.deleted = len(deleted)
    return counts


def run_ingest(
    engine: Engine,
    fetch: Callable[[], Iterable[dict[str, Any]]],
    min_row_ratio: float,
    max_reject_ratio: float,
) -> IngestRun:
    """Run one ingest and return its record. Bad data never replaces what's already stored."""
    with Session(engine, expire_on_commit=False) as session:
        run = IngestRun(status=STATUS_RUNNING)
        session.add(run)
        session.commit()
        log.info("ingest_started", run_id=run.id)

        try:
            result = transform(fetch())
            run.fetched = result.fetched
            run.rejected = len(result.rejected)
            for rejection in result.rejected:
                log.warning("ingest_row_rejected", run_id=run.id, **rejection)
            # Committed separately so these counts survive a rollback of the load below.
            session.commit()

            current_count = session.scalar(select(func.count()).select_from(Planet)) or 0
            reason = check_snapshot(
                valid=len(result.rows),
                rejected=len(result.rejected),
                current_count=current_count,
                min_row_ratio=min_row_ratio,
                max_reject_ratio=max_reject_ratio,
            )
            if reason:
                run.status = STATUS_ABORTED
                run.detail = reason
                log.error("ingest_aborted", run_id=run.id, reason=reason)
            else:
                counts = load_snapshot(session, result.rows)
                run.inserted = counts.inserted
                run.updated = counts.updated
                run.deleted = counts.deleted
                run.status = STATUS_SUCCESS
        except Exception as exc:
            # Undoes any partial load, while keeping a record of the failed run.
            session.rollback()
            run.status = STATUS_FAILED
            run.detail = str(exc)[:2000]
            log.exception("ingest_failed", run_id=run.id)

        run.finished_at = session.scalar(select(func.now()))
        session.commit()

        log.info(
            "ingest_finished",
            run_id=run.id,
            status=run.status,
            fetched=run.fetched,
            inserted=run.inserted,
            updated=run.updated,
            deleted=run.deleted,
            rejected=run.rejected,
        )
        return run
