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

A working setup returns:

```json
{"status": "ok", "database": "ok", "planet_count": 6451, "last_successful_ingest": "2026-11-02T06:31:53.565779Z"}
```

`planet_count` grows as NASA adds planets. Before the first ingest it is `0` and `last_successful_ingest` is `null`.

There is no web front end. Open the interactive API docs at <http://localhost:8000/docs> to browse and run queries. The root URL `/` returns 404. If port 8000 or 5432 is taken, see [Troubleshooting](#troubleshooting).

## Loading data

`docker compose run --rm ingest` fetches every row of NASA's `pscomppars` table, validates it, and loads it in one transaction. Running it again on unchanged data changes nothing. See [Design decisions](#design-decisions) for how changes are detected and how bad data is rejected.

A run usually takes a few seconds, though that depends on NASA's service. Each request has a 120-second timeout, and network failures and 5xx responses are tried up to 4 times with backoff.

To confirm a run worked:

1. The command exits `0` on success and non-zero otherwise (`echo $?`).
2. The last log line is `ingest_finished`, with the run's counts:

   ```json
   {"run_id": 4, "status": "success", "fetched": 6451, "inserted": 0, "updated": 0, "deleted": 0, "rejected": 0, "event": "ingest_finished", ...}
   ```

3. `/health` shows the new `planet_count` and `last_successful_ingest`.
4. The `ingest_runs` table records every run, including failed ones:

   ```bash
   docker compose exec db psql -U exoplanet -d exoplanet -c \
     "select id, status, finished_at, fetched, inserted, updated, deleted, rejected, detail
      from ingest_runs order by id desc limit 5"
   ```

| Status | Meaning |
|---|---|
| `success` | The snapshot was loaded |
| `aborted` | A safety check failed. Existing data was left untouched, and `detail` gives the reason |
| `failed` | An error occurred and the load was rolled back. `detail` holds the error |

## Walkthrough

These steps assume the app is running and the ingest has completed. Quote URLs in the shell so `?` and `&` aren't misread.

**1. Explore in the browser.** Open <http://localhost:8000/docs>, expand `GET /planets`, click **Try it out**, set `host` to `TRAPPIST-1` and click **Execute**. The page shows the request URL, the equivalent `curl` command and the response.

**2. Look up one planet.** The name must match exactly, including case. Write spaces as `%20`.

```bash
curl "localhost:8000/planets/TRAPPIST-1%20e"
```

```json
{
  "pl_name": "TRAPPIST-1 e",
  "hostname": "TRAPPIST-1",
  "discovery_method": "Transit",
  "disc_year": 2017,
  "disc_facility": "Multiple Observatories",
  "orbital_period_days": 6.101013,
  "radius_earth": 0.92,
  "mass_earth": 0.692,
  "eq_temp_k": 249.7,
  "distance_pc": 12.42988881,
  "stellar_teff_k": 2566.0,
  "ra_deg": 346.6263919,
  "dec_deg": -5.0434618
}
```

[Response fields](#response-fields) explains each field and its unit.

**3. Find planet names by host star.** This match is case-insensitive.

```bash
curl "localhost:8000/planets?host=TRAPPIST-1"
```

List endpoints wrap results in a page. `total` is the number of matches, and `items` holds up to `limit` of them:

```json
{"total": 7, "limit": 50, "offset": 0, "items": [{"pl_name": "TRAPPIST-1 b", ...}, ...]}
```

**4. Filter and sort.** Radius is in Earth radii, so this finds transiting planets between 0.8 and 1.25 times Earth's size, closest first:

```bash
curl "localhost:8000/planets?discovery_method=transit&radius_min=0.8&radius_max=1.25&sort=distance"
```

**5. Page through results.** Use `limit` and `offset` to step through large result sets:

```bash
curl "localhost:8000/planets?sort=disc_year&order=desc&limit=20&offset=0"    # First 20
curl "localhost:8000/planets?sort=disc_year&order=desc&limit=20&offset=20"   # Next 20
```

**6. Search by sky position.** The cone search returns planets within `radius_deg` of a point, nearest first. Each result adds `separation_deg`, its distance from that point:

```bash
curl "localhost:8000/planets/cone?ra=346.6&dec=-5.04&radius_deg=2"
```

```json
{"total": 7, "limit": 50, "offset": 0, "items": [{"pl_name": "TRAPPIST-1 b", ..., "separation_deg": 0.0265}, ...]}
```

**7. Make output readable.** Responses are a single line of JSON. Pipe them through [jq](https://jqlang.org/) to format them:

```bash
curl -s "localhost:8000/planets/TRAPPIST-1%20e" | jq
```

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
| `disc_year_min/max`, `radius_min/max`, `mass_min/max`, `period_min/max`, `eq_temp_min/max`, `distance_min/max` | Inclusive ranges, in the units listed under [Response fields](#response-fields). Planets with no value for that column are excluded |
| `sort` | `pl_name` (default), `disc_year`, `radius`, `mass`, `period`, `eq_temp`, `distance`. Nulls sort last |
| `order` | `asc` (default) or `desc` |
| `limit`, `offset` | `limit` defaults to 50, with a maximum of 500 |

Unknown parameters return 422, so a misspelled filter can't silently return unfiltered results.

`GET /planets/cone` takes `ra` (0 to 360), `dec` (−90 to 90) and `radius_deg` (above 0, up to 180), all in degrees, plus `limit` and `offset`.

### Response fields

| Field | Meaning | Unit | Filter / sort |
|---|---|---|---|
| `pl_name` | Planet name, unique | | `/planets/{pl_name}`, `sort=pl_name` |
| `hostname` | Host star | | `host` |
| `discovery_method` | How the planet was found | | `discovery_method` |
| `disc_year` | Year of discovery | year | `disc_year_min/max`, `sort=disc_year` |
| `disc_facility` | Observatory or mission that made the discovery | | |
| `orbital_period_days` | Time to complete one orbit | days | `period_min/max`, `sort=period` |
| `radius_earth` | Planet radius | Earth radii (Earth = 1) | `radius_min/max`, `sort=radius` |
| `mass_earth` | Best available mass estimate | Earth masses (Earth = 1) | `mass_min/max`, `sort=mass` |
| `eq_temp_k` | Equilibrium temperature | kelvin | `eq_temp_min/max`, `sort=eq_temp` |
| `distance_pc` | Distance from Earth | parsecs (1 pc ≈ 3.26 light-years) | `distance_min/max`, `sort=distance` |
| `stellar_teff_k` | Host star's effective temperature | kelvin | |
| `ra_deg`, `dec_deg` | Sky position (ICRS right ascension and declination) | degrees | `/planets/cone` |
| `separation_deg` | Distance from the search point, cone search only | degrees | |

`null` means the archive has no value for that planet. The fields come from NASA's `pscomppars` columns (`pl_orbper`, `pl_rade`, `pl_bmasse`, `pl_eqt`, `sy_dist`, `st_teff`, `ra`, `dec`), which are defined in the archive's [column documentation](https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html).

`discovery_method` values in the archive include Transit, Radial Velocity, Microlensing, Imaging, Transit Timing Variations, Eclipse Timing Variations, Orbital Brightness Modulation, Pulsar Timing, Astrometry, Pulsation Timing Variations and Disk Kinematics. Write spaces as `%20` in a URL, for example `discovery_method=radial%20velocity`.

## Stopping and resetting

```bash
docker compose logs -f api         # Follow the API logs
docker compose stop                # Stop the containers, keeping the data
docker compose down                # Remove the containers, keeping the data
docker compose down -v             # Also delete the database volume. Run the ingest again afterwards
docker compose up --build -d       # Start again, rebuilding after code changes
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `port is already allocated` on startup | Another program is using port 8000 or 5432. Set `API_PORT` or `DB_PORT`, for example `API_PORT=8080 docker compose up --build -d`, or put them in `.env` (see `.env.example`) |
| `/health` returns 503 with `"database": "unreachable"` | The database isn't running. Check `docker compose ps` and `docker compose logs db` |
| `planet_count` is 0, or `/planets` returns `"total": 0` | The ingest hasn't run. Run `docker compose run --rm ingest` |
| The ingest exits non-zero | Check `detail` in `ingest_runs` (see [Loading data](#loading-data)). An `aborted` run means the snapshot had under 90% of the stored row count or over 1% invalid rows, and existing data was kept. A `failed` run is usually a network problem or an error from NASA's service, so try again later |
| 422 with `"type": "extra_forbidden"` | A parameter name is misspelled. The error's `loc` names it, for example `["query", "radus_min"]` |
| 422 with `must not be greater than` | A `_min` filter is larger than its `_max` |
| 404 with `Planet not found` | The name is wrong or in the wrong case. Look up the exact name with `/planets?host=<star>` |
| Code changes don't appear | The image is stale. Rebuild with `docker compose up --build -d` |

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
