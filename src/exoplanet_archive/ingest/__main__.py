import sys

import httpx

from exoplanet_archive.config import get_settings
from exoplanet_archive.db import get_engine
from exoplanet_archive.ingest.load import STATUS_SUCCESS, run_ingest
from exoplanet_archive.ingest.tap_client import fetch_planets
from exoplanet_archive.logging import configure_logging


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)

    with httpx.Client(timeout=settings.tap_timeout_seconds) as client:
        run = run_ingest(
            get_engine(),
            fetch=lambda: fetch_planets(client, settings.tap_url),
            min_row_ratio=settings.ingest_min_row_ratio,
            max_reject_ratio=settings.ingest_max_reject_ratio,
        )
    return 0 if run.status == STATUS_SUCCESS else 1


if __name__ == "__main__":
    sys.exit(main())
