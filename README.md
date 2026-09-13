# National Grid Intelligence Platform

Build sequence (Section 13.1) items 1-5: network hierarchy data model,
synthetic vending/network generator, ingestion and time-series storage,
the feeder digital twin, and consumption reconstruction (Module A).
Full context: [docs/National_Grid_Intelligence_Platform_v3.md](docs/National_Grid_Intelligence_Platform_v3.md).

## Setup

```bash
pip install -r requirements.txt
pip install -e .                           # makes `import gridintel` work outside pytest
python scripts/process_public_dataset.py   # only needed if data/processed/ is regenerated
python -m pytest tests/ -v
```

No Docker is required for any of the above -- the full test suite runs
against SQLite. Docker is only needed to run the production-shaped stack
(TimescaleDB + Mosquitto):

```bash
docker compose up
```

## What's here

- `src/gridintel/db/` -- SQLAlchemy models and session/engine setup. Same
  models run against SQLite (default, no setup) or PostgreSQL/TimescaleDB
  (set `GRIDINTEL_DATABASE_URL`).
- `src/gridintel/hierarchy/` -- network hierarchy construction, drill-down,
  roll-up, and the connection-to-transformer association logic (Section 11.1).
- `src/gridintel/gridsynth/` -- the synthetic vending and network generator
  (Section 12.1). `scenario.generate_scenario()` is the entry point.
- `src/gridintel/ingestion/` -- HTTP and MQTT ingestion, sharing one storage
  path (`store.py`) so synthetic and real device data go through identical code.
- `src/gridintel/digitaltwin/` -- the feeder digital twin (Section 7).
  `opendss_engine.py` is the single physics engine shared by the generator's
  own ground-truth loss computation and the twin's operational one (so a
  mismatch between them is always attributable to what data each was
  given, never to two implementations disagreeing). `twin.py` computes
  modelled loss from the database's CURRENT knowledge (only connections
  with a confirmed association and a known electrical placement);
  `validate.py` compares it against synthetic ground truth.
- `src/gridintel/network_catalog.py` -- shared physical placeholder
  constants (conductor R/X, transformer loss classes), used by both the
  generator and the twin. Deliberately has no dependency on either, since
  the twin must be able to run against a real feeder that was never
  synthetically generated.
- `src/gridintel/shedding_schedule.py` -- the shedding window data
  structure and mask computation, shared by the generator (which invents a
  schedule) and Module A (which conditions on one -- synthetic today,
  ZESA's published one later). Same dependency-direction reasoning as
  `network_catalog.py`.
- `src/gridintel/module_a/` -- consumption reconstruction (Section 8.1).
  `prior.py` builds the population-level shape prior (real data for
  residential archetypes, documented templates for commercial/industrial).
  `segment_reconstruction.py` is the actual estimator -- see "Module A" below,
  it is not the first thing this module tried. `reconstruct.py` is the
  public entry point (`reconstruct_from_events` is DB-free and reusable
  against real data; `reconstruct_for_connection` is the DB adapter).
  `evaluate.py` implements Section 8.1's evaluation methodology, including
  the Section 12.2 held-out-real-data check.
- `migrations/` -- Alembic migrations. `alembic upgrade head` against
  either database backend.
- `data/processed/` -- small, git-tracked reference artefacts derived from
  public datasets (real load shape, real Harare irradiance, held-out
  interval sample). `data/public/` holds the large raw source files and is
  gitignored.

## Generating a scenario

```python
import pandas as pd
from gridintel.db.session import make_engine, make_session_factory, init_db
from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario

engine = make_engine()  # SQLite by default
init_db(engine)
Session = make_session_factory(engine)

config = ScenarioConfig(
    substation_id="DS-DEMO",
    n_transformers=3,
    connections_per_transformer=15,
    start=pd.Timestamp("2026-01-05", tz="UTC"),
    weeks=4,
)
with Session() as session:
    scenario = generate_scenario(session, config, seed=1)
    session.commit()
    print(scenario.id)
```

Then validate it against Section 15's acceptance criterion for the generator:

```python
from gridintel.gridsynth.validate import compare_to_reference_shape, check_anomaly_recoverability
print(compare_to_reference_shape(session, scenario.id))
print(check_anomaly_recoverability(session, scenario.id))
```

And for the digital twin -- how well the twin's loss estimate (computed
from only what's currently associated and placed) tracks the generator's
full-information ground truth:

```python
from gridintel.digitaltwin.validate import compare_twin_to_ground_truth
print(compare_twin_to_ground_truth(session, scenario.id, "DS-DEMO-T01"))
```

## Module A: consumption reconstruction

Section 8.1 calls this "largely unaddressed" in the published literature,
and building and testing a first version confirmed why -- two designs were
tried, and the honest results below are mixed, not a clean win.

**What shipped.** `segment_reconstruction.py`: between each pair of
purchases, assume the funding purchase is mostly consumed within that
segment (the reason a prepaid customer buys again), so the segment's
average consumption level is `purchase_kwh / (population shape prior's
total weight over the segment)`. Redistributing that amount across the
segment by the shape prior (real data for residential archetypes, shedding-
aware) satisfies Section 8.1's hard bound -- cumulative consumption never
exceeds cumulative purchases -- EXACTLY, by construction, not as a fitted
constraint. Per-connection uncertainty comes from the spread of a
connection's own segment estimates (log-normal band), so an erratic
customer gets a wide band and a consistent one gets a tight one.

**What was tried first and discarded.** A bootstrap particle filter with a
purchase-hazard observation model (buying probability rising as simulated
balance depletes). It ran and produced output, but testing against
synthetic data surfaced a real identifiability problem: purchase frequency
alone can't distinguish "low consumption, frequent small purchases" from
"high consumption, rare bulk purchases" without assuming a hazard shape --
and that assumed shape is necessarily miscalibrated for at least some
archetypes (small commercial buys in 5-30-day bulk lots in this platform's
own generator). It produced a stable ~50% underestimation bias, not noise.
The segment-based replacement makes no hazard assumption at all.

**A real bug this surfaced, unrelated to the algorithm itself:**
`gridsynth/purchasing.py`'s purchase-probability parameters were written as
per-day rates but applied every 15/30-minute interval without converting
between the two -- inflating purchase frequency roughly 50x (one connection
bought 51 times in 28 days, totalling more energy than the archetype could
plausibly consume in a year). This affected every scenario generated in
Milestone 1 and item 4, though it didn't surface in those validations
because they check consumption SHAPE and loss physics, not purchase-event
frequency. Fixed in the same commit as Module A; regenerate any scenario
you'd built before this fix.

**Honest evaluation findings**, from `module_a/evaluate.py` run across
archetypes and against the real held-out UCI household data (Section
12.2's methodology -- real consumption, simulated purchases, compare
reconstruction to the real series):

- High-density low-income connections (frequent small purchases, weekly
  income cycle) reconstruct well and reliably beat a naive constant-mean
  baseline -- `tests/test_module_a.py`'s
  `test_reconstruction_beats_naive_for_frequent_purchase_archetype` pins this.
- Small commercial and industrial connections (rare, large purchases)
  perform materially worse -- fewer segments means less information, and a
  single mistimed segment dominates the error. Per Section 8.1's own
  calibration note and Section 3.1's Tier 1 data list, real
  commercial/industrial customers are also the segment most likely to
  already have post-paid interval metering, so `evaluate_scenario()`
  excludes industrial from transformer-level aggregation by default --
  those customers shouldn't need purchase-based reconstruction in
  production at all.
- A specific, understood failure mode: a "stockpiling" bulk purchase
  followed by a smaller top-up before the bulk is actually depleted
  inflates that segment's estimate (confirmed on the real held-out data --
  a 793 kWh purchase produced a segment reading roughly 2-3x its
  neighbours). Mitigated, not eliminated, by capping outlier segments
  toward the connection's own median (upper-bound-only, so the hard bound
  is never violated) -- see `WINSORIZE_LOG_CAP` in `segment_reconstruction.py`.
- On the single real held-out household, reconstruction accuracy varies
  substantially by purchase-timing luck (different random seeds for the
  simulated purchase process give daily relative MAE anywhere from ~0.25 to
  ~0.6) and does not reliably beat a naive baseline on that one household.
  This is reported plainly rather than cherry-picked -- see
  `test_evaluate_against_held_out_real_data_runs_and_returns_sane_bounds`,
  which checks the pipeline is sane, not that it wins.

The spec's own framing -- "solving it is the precondition for every other
module operating on Tier 1 data" and "largely unaddressed" in the
literature -- was not an exaggeration. This is a genuine, partial first
version with clearly documented limits, not a finished solution; more
segments (real vending history, once available) and less-invented
purchasing behaviour are what would actually move it forward, not further
tuning against this synthetic data.

## Known gaps (see conversation / design review for full discussion)

- **No Docker on the dev machine this was built on.** TimescaleDB
  hypertable promotion and the MQTT broker path are written and unit-tested
  at the logic level but not exercised end-to-end. Run `docker compose up`
  once Docker Desktop is available and re-run the test suite with
  `GRIDINTEL_DATABASE_URL` pointed at the Postgres container to close this gap.
- **Purchasing behaviour model is invented, not fitted** -- there is no
  public dataset pairing real interval consumption with real prepaid
  vending events. Re-fit `gridsynth/purchasing.py` against real ZETDC
  vending data the moment any is available, however small.
- **Small commercial and industrial load shapes are template-based, not
  data-fitted** -- no public dataset for those archetypes was acquired in
  this milestone. See `ARCHETYPE_SHAPE_SOURCE` in `gridsynth/archetypes.py`.
- **Physical network parameters (conductor R/X, transformer loss split)
  are representative placeholders**, not ZETDC measurements. Every such
  value is marked `PLACEHOLDER` in `network_catalog.py` and must be
  confirmed against a feeder survey and reviewed by a power-systems
  engineer (Section 14.1) before being used for anything beyond internal
  development.
- **The technical-loss model uses OpenDSS**, not pandapower, specifically
  for the LV network's single-phase, unbalanced loading -- see the module
  docstring in `digitaltwin/opendss_engine.py` for the reasoning. This is a
  real architectural decision, not a default; confirm it with the
  power-systems reviewer before relying on it for a real feeder.
- **The LV network is modelled as a star** of service-drop laterals direct
  from the transformer busbar, not a shared trunk with laterals branching
  off it. A real trunk+lateral LV feeder would show more loss (shared
  conductor current, cumulative volt-drop along the trunk) than this star
  simplification does -- see `network_catalog.py`'s note on
  `LV_FEEDER_R_OHM_PER_KM`, which is currently unused by any power-flow
  computation as a result. Close this gap before trusting twin loss
  figures on a feeder with a non-trivial LV backbone.
- **Twin coverage (fraction of connections placed) is not the same as
  loss-accuracy coverage.** Testing the twin surfaced this directly: loss
  scales with the square of current, so a twin missing a few
  high-consumption (often industrial) connections can understate loss far
  more than its connection-count coverage would suggest -- and, just as
  easily, high coverage by count can still miss most of the loss if the
  few missing connections happen to be the largest loads. Section 15's
  "association accuracy" metric and Appendix B's pilot metric are both
  currently defined as a plain fraction of connections; consider whether a
  load-weighted variant is needed before either is used to represent twin
  reliability to the utility.
