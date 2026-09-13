# National Grid Intelligence Platform

Build sequence (Section 13.1) items 1-4: network hierarchy data model,
synthetic vending/network generator, ingestion and time-series storage,
and the feeder digital twin.
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
