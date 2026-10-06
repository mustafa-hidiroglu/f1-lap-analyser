# f1lap

High-performance F1 lap telemetry analyser: ingestion, distance-domain resampling, and delta-time
analysis against a reference lap.

```mermaid
flowchart LR
    A[FastF1 session] -->|fetch_lap| T[LapTrace<br/>raw SoA]
    B[CSV / Parquet export] -->|read_trace| T
    T -->|resample_to_distance| R[ResampledLap<br/>uniform distance grid]
    R -->|write_lap| P[(Parquet zstd<br/>data/)]
    P -->|read_lap| R
```

Every lap is mapped onto the same grid (`0, step, 2·step, …` metres), so sample `i` of any two
laps is the same point on track — the basis for delta-time, corner and braking analysis.

## Usage

```sh
uv sync
uv run f1lap fetch 2024 Monza Q LEC            # fastest lap; or --lap 17
uv run f1lap import export.csv --driver VER    # FastF1 or canonical column names
uv run f1lap info data/2024_italian_grand_prix_q_lec_l20.parquet
uv run f1lap corners data/…_qualifying_lec_l20.parquet       # corners located on this lap
uv run f1lap delta data/…_qualifying_lec_l20.parquet data/…_qualifying_sai_l17.parquet --json report.json
```

`delta` puts the compared lap on the reference lap's grid (rescaling its distance to the reference
length), prints the delta at the line and a per-corner table (time per segment, delta, minimum
speed), and optionally writes the same report as JSON. Deltas are `other − reference`:
positive = slower. `--sectors N` uses N equal micro-sectors instead of corners.

### Circuit model

Corners come from, in order: `--circuit file.json`; the circuit `fetch` saved to
`data/circuits/` (FastF1's corner markers); or detection from the reference lap's telemetry
(speed minima ≥ 20 km/h deep; flat-out kinks are skipped). `--detect` forces detection.

FastF1 markers are hand-placed labels, not apexes (Monza's Parabolica marker is 52 m past the
slowest point). Each marker is snapped to the lap's own X/Y line within ±300 m. Corners closer than
150 m form one complex (`T1-2`, `T8-10`); segment boundaries sit midway between complexes.

### Corner phases

In corner mode `delta` also splits every corner into phases and compares the key points:

```
approach | braking | mid | exit | straight
       entry   mid_start  mid_end   full throttle
```

- **entry** — last point at full attack (throttle ≥ 95 %, brake off) before the apex; "braking"
  includes lift-only corners.
- **mid** — the minimum-speed zone: within 5 % of the corner's slowest point. (F1 drivers go
  straight from brake to throttle, so an input-defined mid phase would be ~0 m.)
- **full throttle** — back to full attack after the mid zone.
- Also reported per lap: brake on / release (end of the first braking run), number of brake
  applications, throttle pickup (≥ 20 % with brake off), entry / apex / exit speed.
- Corners taken flat are flagged `flat`.

Phases are cut at the reference lap's boundaries, so phase deltas sum exactly to the corner
delta, and corner deltas to the delta at the line. `--json` includes all points per corner.

### Lap rating

```sh
uv run f1lap rate 2024 Monza Q LEC            # fastest lap; or --lap 17, --json rating.json
```

Rates one lap against every valid lap in the session (accurate, not deleted, no pit in/out, within
107 % of the fastest), all cut into the same corner segments on the session's fastest lap:

- **theoretical best**: the driver's best time in every segment, summed. `lap - theoretical best`
  is the time left on the table, and the table shows which lap set each personal best.
- **session ultimate**: the best time in every segment by anyone, and who set it.
- **rank / percentile** per corner against every *other* driver's best in that corner.
- **score** (0-100): the mean corner percentile. Seconds are the primary result; the score is a
  scale-free summary for ranking laps and drivers.

Segment times add up to the official lap time: the last segment is extended from the grid end to
the finish line (checked to 0.0 ms on all 87 valid laps of 2024 Monza qualifying).
UIs should call `await rating.rate_fastf1_lap_async(...)`, which returns a typed `LapRating`
(`.to_dict()` for JSON).

### Driver metrics

```sh
uv run f1lap metrics data/…_lec_l20.parquet data/…_sai_l17.parquet   # side by side, --json
```

- **Lap**: time-weighted share at full throttle (≥ 95 %), braking, and coasting (throttle < 10 %,
  brake off); ramp-weighted throttle smoothness.
- **Per corner exit**: throttle smoothness = net rise / total throttle movement from the *final*
  pickup to full throttle (1.0 = one clean push; a chicane's first corner is excluded), ramp time
  and rate, and lifts (drops > 10 points).
- **Per braking zone**: peak deceleration (g) and its 10-90 % rise time. FastF1 brake is on/off,
  so deceleration comes from the speed trace, differentiated over ±0.25 s to match FastF1's
  ~4 Hz speed sampling (Monza T1 ≈ 5 g). The window widens rise times by up to ~0.5 s: compare
  them between laps from the same source, don't read them as absolute.
- **Brake pressure** exports (most braking samples between 0 and 1) are detected automatically:
  braking then starts at 5 % of peak pressure and the 10-90 % pressure rise time is reported.

Global options (before the subcommand): `--step 0.5` grid spacing, `--length 5793` normalise lap
length, `-o path.parquet`, `--config f1lap.toml`.

```python
from f1lap import resample_to_distance
from f1lap.ingest.fastf1_source import fetch_lap_async  # non-blocking (worker thread)
from f1lap.delta import compare, corner_table, micro_sectors, summary
from f1lap.circuit import corner_segments, detect_corners
from f1lap.phases import analyse_corners, compare_corners
```

## Data model

| Channel | Unit | Kind | Resampling |
|---|---|---|---|
| distance | m | axis | uniform grid |
| time | s | continuous | linear |
| speed | km/h | continuous | linear |
| throttle | 0–100 % | continuous | linear |
| brake | 0–1 | continuous | linear |
| rpm, x, y, z | — | continuous | linear |
| gear, drs | — | discrete (int16) | zero-order hold |

Distance is cleaned first: NaN rows and samples that don't advance past all earlier samples are
dropped (never interpolated through), the lap is shifted to start at 0 m, and gaps over 500 m are
rejected as corrupt. The true lap length is kept in `meta.raw_length_m`; when comparing laps,
resample them with `length_m=<reference raw_length_m>` so grids match exactly.

`brake` is linearly interpolated: FastF1's on/off brake becomes fractional only on the grid point
straddling a transition (onset error ≤ one step). Pressure exports are stored as provided.

Discrete channels: NaN gaps are forward-filled; non-integer or out-of-range values are rejected.

## macOS app sidecar

The Mac app (SwiftUI, in progress) runs `f1lap-server` as a child process and talks
JSON-RPC 2.0 over stdin/stdout, one message per line. No network port is opened.

```mermaid
sequenceDiagram
    participant App as SwiftUI app
    participant S as f1lap-server (asyncio)
    participant W as worker thread
    App->>S: {"method":"compare", ...}\n
    S->>W: run_in_executor (FastF1 / pandas, serialised)
    W-->>S: summary + corners + metrics
    W->>W: write traces → ~/Library/Caches/f1lap/traces/*.f1soa
    S-->>App: {"result": {..., "traces": {"path", "columns"}}}\n
    App->>App: mmap .f1soa, view columns in place
```

| Method | Params | Result |
|---|---|---|
| `ping` | — | protocol version, cache dir |
| `schedule` | `year` | events with round, date, format, session names |
| `session` | `year, event, session` | drivers (team, colour, position) and every lap with validity |
| `compare` | session + `reference`/`other`: `{driver, lap?}` | delta summary, corner table, phases, metrics for both laps, circuit (corners, segments, track outline), trace file |
| `rate` | session + `driver, lap?` | `LapRating.to_dict()` + circuit + reference lap |

- Errors: standard JSON-RPC codes, `-32000` for analysis failures (unknown driver, missing data).
  Non-finite numbers are sent as `null`.
- The event loop never blocks. FastF1 work runs on one worker thread, so `ping` answers while a
  session loads. The 2 most recent sessions stay loaded, with resampled laps memoised (first
  `rate` of a session ~5 s, then ~20 ms).
- `.f1soa` traces: Structure-of-Arrays, each column contiguous little-endian `f64`/`i16` at an
  8-byte-aligned offset, described by `columns: [{name, dtype, offset, count}]`. The 20 newest are
  kept.
- The FastF1 cache defaults to `~/Library/Caches/f1lap` (`--cache-dir` / `F1LAP_CACHE_DIR`).

## Configuration

`f1lap.toml` (`[paths] cache_dir, data_dir`, `[resample] step_m`); paths are relative to the
file. Environment overrides: `F1LAP_CACHE_DIR`, `F1LAP_DATA_DIR`, `F1LAP_STEP_M`.

> **Security:** FastF1 stores its HTTP cache as Python pickles. Never point `cache_dir` at a
> cache from an untrusted source — loading it can execute arbitrary code.

## Development

```sh
uv run pytest            # offline suite
uv run pytest -m network # live FastF1 test
uv run ruff check . && uv run mypy src tests
app/scripts/test.sh       # Swift F1LapKit tests (live sidecar tests use .venv + cache/)
```

## Roadmap

1. ~~Ingestion + distance resampling~~
2. ~~Delta-time trace vs reference lap, micro-sectors~~
3. ~~Corners: circuit model, per-corner delta, braking/mid/exit phases and key points~~
4. ~~Driver metrics: throttle smoothness, full-throttle time, braking steepness~~
5. ~~Lap rating vs the driver's theoretical best and the field~~
6. Native macOS app UI: interactive traces (speed, delta, throttle/brake, gear), reports.
   The `f1lap` core stays UI-agnostic: typed results + JSON-ready summaries, async I/O.
7. Native kernels (C++/nanobind) where profiling shows NumPy is the bottleneck
