# Exoplanet Query API

Ingests confirmed exoplanets from the [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu/) into PostgreSQL and serves them through a FastAPI query service, including cone search by sky position.

> Independent portfolio project. Not affiliated with or endorsed by NASA, Caltech or IPAC.

```
NASA Exoplanet Archive            ingest job                 PostgreSQL + q3c        FastAPI
TAP service (pscomppars)  ─────►  fetch → validate → check ─► planets, ingest_runs ◄─ /planets
                                  → load in one transaction                           /planets/cone
                                                                                      /health, /metrics
```

## Quickstart

Requires Docker with Compose.

```bash
docker compose up --build -d       # Start the database, run migrations, start the API
docker compose run --rm ingest     # Load the archive
curl "localhost:8000/health"
```

Interactive API docs are at <http://localhost:8000/docs>. If port 8000 or 5432 is taken, set `API_PORT` or `DB_PORT`, for example `API_PORT=8080 docker compose up --build -d`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /planets` | Filtered, sorted, paginated planet list |
| `GET /planets/cone` | Planets within a radius of a sky position, nearest first |
| `GET /planets/{pl_name}` | One planet by name |
| `GET /health` | Database status, row count and last successful ingest. Returns 503 if the database is unreachable |
| `GET /metrics` | Prometheus request counts and latency |

`GET /planets` accepts these parameters:

| Parameter | Notes |
|---|---|
| `discovery_method`, `host` | Exact match, case-insensitive |
| `disc_year_min/max`, `radius_min/max`, `mass_min/max`, `period_min/max`, `eq_temp_min/max`, `distance_min/max` | Inclusive ranges. Planets with no value for that column are excluded |
| `sort` | `pl_name` (default), `disc_year`, `radius`, `mass`, `period`, `eq_temp`, `distance`. Nulls sort last |
| `order` | `asc` (default) or `desc` |
| `limit`, `offset` | `limit` defaults to 50, with a maximum of 500 |

Unknown parameters return 422, so a misspelled filter can't silently return unfiltered results.

```bash
# Earth-sized transiting planets, closest first
curl "localhost:8000/planets?discovery_method=transit&radius_min=0.8&radius_max=1.25&sort=distance"

# Planets within 2 degrees of the TRAPPIST-1 system (RA 346.6, Dec -5.04)
curl "localhost:8000/planets/cone?ra=346.6&dec=-5.04&radius_deg=2"

# One planet (URL-encode the spaces in its name)
curl "localhost:8000/planets/TRAPPIST-1%20e"
```

## Design decisions

**Full snapshot comparison instead of incremental fetching.** The `pscomppars` table has no last-updated column, so there's no way to ask for only what changed. Each run fetches every row and hashes its content. Only rows with a changed hash are rewritten, and rows gone from the snapshot are deleted. Running the ingest twice on unchanged data makes no changes.

**Bad upstream data can't wipe the table.** A run is aborted, leaving existing data untouched, if the snapshot has under 90% of the stored row count or more than 1% of its rows fail validation. The load runs in a single transaction, so a failure partway through rolls back completely. Every run, including failed ones, is recorded in `ingest_runs` with its counts.

**TAP errors are detected in the response body.** The archive's TAP service reports query errors as a VOTable XML document with an HTTP 200 status. The client checks the body and raises an error rather than trusting the status. Network failures and 5xx responses are retried with backoff, while query errors aren't, since retrying can't fix them.

**Cone search uses q3c.** Comparing angular distance on every row doesn't scale, and a plain range filter on RA and Dec gets the geometry wrong at the poles and at the RA 0/360 boundary. [q3c](https://github.com/segasai/q3c) indexes the sphere for this query. The tests compare its results against a brute-force haversine calculation, including across both of those problem areas.

**Observability.** Everything logs one JSON object per line. Each request gets an ID, returned in the `X-Request-ID` header and included in its log line. Metrics are labelled by route template rather than raw path, so planet names can't create unbounded label values.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest tests/unit

docker compose up -d --wait db     # Integration tests need the database
.venv/bin/pytest tests/integration
```

Integration tests create and drop their own `exoplanet_test` database, leaving development data alone. All tests use a saved sample of real rows in `tests/fixtures` and never call the live archive. GitHub Actions runs these same checks on every push and pull request, then builds the Docker image.

To run the ingest on a schedule, trigger `docker compose run --rm ingest` from cron or similar. It exits non-zero unless the run succeeds.

## Acknowledgement

This research has made use of the NASA Exoplanet Archive, which is operated by the California Institute of Technology, under contract with the National Aeronautics and Space Administration under the Exoplanet Exploration Program.
