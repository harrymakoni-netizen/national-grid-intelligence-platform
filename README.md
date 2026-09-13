# National Grid Intelligence Platform

Milestone 1 (Section 13.1, items 1-3): network hierarchy data model,
synthetic vending/network generator, ingestion and time-series storage.
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

Then validate it against Section 15's acceptance criterion:

```python
from gridintel.gridsynth.validate import compare_to_reference_shape, check_anomaly_recoverability
print(compare_to_reference_shape(session, scenario.id))
print(check_anomaly_recoverability(session, scenario.id))
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
  value is marked `PLACEHOLDER` in `gridsynth/topology.py` and must be
  confirmed against a feeder survey and reviewed by a power-systems
  engineer (Section 14.1) before being used for anything beyond internal
  development.
- **The digital twin ground-truth loss model uses OpenDSS**, not
  pandapower, specifically for the LV network's single-phase, unbalanced
  loading -- see the module docstring in `gridsynth/lossmodel.py` for the
  reasoning. This is a real architectural decision, not a default; confirm
  it with the power-systems reviewer before Milestone 2.
