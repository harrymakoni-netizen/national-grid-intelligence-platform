# National Grid Intelligence Platform

Build sequence (Section 13.1) items 1-5, 7 and 8: network hierarchy data
model, synthetic vending/network generator, ingestion and time-series
storage, the feeder digital twin, consumption reconstruction (Module A),
loss attribution (Module B), and the drill-down interface. Item 6
(sensing device firmware) needs physical hardware and is out of scope here.
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

## Running the demo (Section 12.4)

```bash
python scripts/seed_demo_scenario.py       # generates a scenario into ./gridintel.sqlite3
uvicorn gridintel.presentation.api:app --reload --port 8010
```

Then open `http://127.0.0.1:8010/`. This serves both the JSON API
(`/api/*`) and the frontend (`frontend/`) from one process. Every number on
the page is either Module A's reconstruction, Module B's case output, or
(only on a case's "ground truth" panel, clearly labelled) synthetic ground
truth for validation -- never presented as a measurement.

The interface has seven views: the six role-specific views of Section 11.4
(Executive, Revenue protection, Network operations, System control,
Regulatory, Industrial customer) plus the network explorer. Views that
depend on unbuilt modules (C, D, E, G) render an explicit "not built"
panel naming the specification section, rather than a fabricated chart.

### Deployment

The deployed demo is a **static snapshot**, not a running backend:

```bash
python scripts/export_static_api.py   # renders every API response to frontend/data/*.json
vercel deploy --prod
```

Vercel runs no Python at request time. Serving FastAPI + OpenDSS +
scikit-learn as serverless functions would mean cold-starting a native
power-flow backend inside a function timeout -- fragile in exactly the
situation where it must not be. The demo scenario is fixed and read-only,
so its responses are computed once (where the toolchain is known to work)
and committed as ~270 KB of JSON. `frontend/js/data.js` detects which
source it is talking to and uses identical payload shapes either way, so
the same frontend serves both the live backend and the static deploy.

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
- `src/gridintel/module_b/` -- loss attribution (Section 8.2). `features.py`
  builds per-connection features directly from Section 8.2's discriminating-
  signature table, on top of Module A's reconstruction (not privileged
  ground truth). `unsupervised.py` is an isolation-forest suspicion score
  (Section 8.2's stage 1). `weak_supervision.py` is stage 2's labelling
  functions plus a two-stage vote combiner. `pipeline.py` assembles the
  ranked case queue; `evaluate.py` scores it (precision at the top of the
  queue, by cause class, with meter-failure/full-bypass ambiguity reported
  honestly). `nontechnical_loss.py` is Section 7.2's energy-balance
  equation at transformer level. Stage 3 (supervised, on real field-
  confirmed labels) is deliberately not built -- no real labels exist yet.
- `src/gridintel/presentation/` -- Layer 6, the drill-down interface's data
  source (Section 11.3). `api.py` is a FastAPI app serving national-down-
  to-connection navigation, aggregated consumption, and Module B's case
  queue/detail, plus the static frontend. `aggregation.py` sums Module A's
  reconstruction over a subtree (never ground truth).
- `frontend/` -- the UI: vanilla HTML/JS + Tailwind (CDN) + Chart.js +
  Leaflet, no build step. Deliberately not React/Node -- a build toolchain
  would be pure overhead here, and a zero-build static bundle is what makes
  the deployed demo immune to runtime failure. `js/data.js` abstracts the
  live-API vs static-snapshot data source; `js/views.js` holds the six
  role views plus the explorer. `frontend/data/` is the committed static
  snapshot (generated by `scripts/export_static_api.py`).
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

## Module B: loss attribution

Section 8.2 calls this "the hardest and most valuable model in the
platform." Built on top of Module A's (already imperfect) reconstruction
rather than privileged ground truth, per the real production dependency
chain -- so it inherits Module A's noise, and testing it end-to-end against
synthetic data found four real bugs in the first pass, not just accuracy
gaps:

1. **Vote-splitting in the label combiner.** A flat plurality vote let a
   single-cause hypothesis (e.g. "normal", one vote of 0.6) beat a
   genuinely ambiguous meter-failure/full-bypass split (0.5 + 0.5 = 1.0
   total anomaly evidence) purely because the anomaly evidence was divided
   across two labels. Fixed by deciding "anomalous or not" and "which
   cause" as two separate steps (`weak_supervision.classify`).
2. **Solar's evening-preservation check was a bonus, not a gate.** A
   connection whose evening consumption collapsed exactly as much as its
   daylight consumption (a real vacancy case) was still classified as
   solar because a spurious negative irradiance correlation (Module A
   reconstruction noise on a near-zero series) was enough on its own.
   Evening preservation is now a required condition.
3. **The vacancy rule over-required corroborating signal.** Demanding zero
   recent purchase activity IN ADDITION TO an inactive customer-system flag
   excluded real vacancy cases where a habitual top-up landed in the
   recent window on calendar timing alone, after physical consumption had
   already collapsed. The customer-system flag is now sufficient by itself.
4. **A purchase-gap feature looked in the wrong place.** Section 8.2 names
   "sustained zero consumption with an active transformer implies meter
   failure or bypass" directly -- implemented as a feature comparing the
   longest purchase gap to a connection's own historical typical gap. The
   first version only checked the CURRENTLY OPEN gap, missing a real
   meter-failure case (confirmed in this generator's own output) where a
   47-day silence was followed by one small habitual top-up before the
   window ended, closing the gap that would otherwise have flagged it.

**Honest results** (`build_case_queue` + `evaluate_case_queue`, averaged
over 10 independent synthetic scenarios): precision over the WHOLE case
queue is modest (~15% exact, ~20% treating meter-failure/full-bypass as
one confusable outcome, since Section 8.2 itself says they're genuinely
hard to tell apart). Precision restricted to the TOP of the ranked list --
the metric Section 8.2 actually specifies, because inspector capacity is
the binding constraint, not queue length -- is materially better: **~47%
exact / ~50% confusable-aware at top-3** across the same 10 scenarios,
dropping toward the whole-queue figure by top-10. This is the expected
shape of the result and validates the ranking-by-confidence design, not
just the classifier: the model doesn't know everything, but it is
meaningfully better at knowing what it doesn't know. Solar and vacancy
detection (clear, well-separated signatures) work well; meter-failure/full-
bypass is the weakest category by volume of false positives, consistent
with it being the genuinely hardest and most information-poor
discrimination in Section 8.2's own table.

Stage 3 (supervised gradient-boosted classification on real field-
confirmed outcomes, Section 8.2) is not built. No real labels exist yet --
building it against synthetic labels would risk the model looking "ready"
in a way that wouldn't transfer, exactly the trap Section 15 warns against.

### A structural finding, not a bug: why solar recall is weak

Building the drill-down interface (below) meant actually looking at
individual cases end to end, which surfaced something the aggregate
precision numbers above don't show on their own: solar detection is weak
for a specific, verifiable reason, not because a threshold needs tuning.

Section 8.2's solar signature is a SHAPE change: daylight consumption
collapses, evening is untouched. Checked directly against this
generator's own ground truth for one solar case: true daylight change was
**-99.7%**, true evening change was **+4.9%** (noise) -- a clean, textbook
signature, genuinely present in the data. Module A's reconstruction of
that SAME connection showed **-84% for both**. The reason is structural:
`segment_reconstruction.py` can only vary a connection's overall
consumption SCALE per inter-purchase segment; it always redistributes that
scale using the same fixed archetype diurnal template. A single scaled
copy of one template cannot represent "only daylight changed" -- so
Module A mechanically erases the one signature Module B most needs for
this discrimination, before Module B ever sees the data.

This is an information gap between what Module A's architecture can
output and what solar-vs-bypass discrimination needs, confirmed with real
numbers while building the drill-down interface below (see
`module_b/features.py`'s docstring). It is flagged as a genuine open
problem for future work -- extending Module A to support intra-day shape
adjustment -- rather than patched with a threshold change that couldn't
actually fix it. In an interactive search across 17 independent scenarios
built while testing the demo, this generator's ~5%-rate solar injections
were not correctly classified even once, which is a more sobering number
than the aggregate stats above (drawn from a smaller sample) suggested.

### A phantom 23 kW of "theft", found by building the energy-balance view

Wiring Section 7.2's energy balance into the interface immediately produced
a transformer showing **26.3 kW of non-technical loss -- 63% of its
inflow**. That would have read as spectacular theft. It was not.

Almost all of it (23.6 kW) came from a single industrial connection, whose
true draw was 27.97 kW but which Module A reconstructed at 4.37 kW. Every
other connection on the feeder was within 0.11 kW. The cause is Module A's
known weakness: it infers consumption from purchase *timing*, and an
industrial customer buying in rare bulk lots gives it almost nothing to
work with.

The fix is not a better reconstruction -- it is not reconstructing them at
all. Section 3.1 lists post-paid billing and meter reading history for
commercial and industrial accounts as Tier 1 data the utility *already
holds*. Reconstructing those accounts from vending events manufactures a
phantom loss from a data source production would never use. The energy
balance now serves industrial connections from meter reads and discloses
which ones in the UI; the residual on that transformer fell to **0.198 kW
(0.5% of inflow)** -- a plausible loss figure instead of a fictional theft
case. Pinned by `test_industrial_connections_accounted_from_meter_reads_not_reconstruction`.

This is the failure mode the specification warns about most sharply: a
number that looks like a triumph in a demo and collapses the moment a
utility engineer asks what is in it.

## The interface (Section 11.3, 11.4 / Section 12.4's demo)

A working web UI: national aggregate down to individual connection,
Module B's case queue at any level, and a case detail view showing
evidence plus (for this synthetic scenario only, clearly labelled)
what was actually injected. Run it per "Running the demo" above.

What it demonstrates, honestly: drilling from national to an individual
connection works, as does opening a case and seeing it match synthetic
ground truth (e.g. a vacancy case in the seeded demo scenario is
correctly classified at 0.90 confidence, matching what was actually
injected exactly). Section 12.4 also asks for a theft case distinguished
from a solar case -- theft-family cases (partial/full bypass, meter
failure) do appear correctly in the demo; solar does not reliably, for the
structural reason documented above, and the demo does not pretend
otherwise. Asset-health degradation trajectories (Module C) are not built
at all and are out of scope for this interface.

Now built: all six role-specific views of Section 11.4; the Section 7.2
non-technical-loss chart (with its four series and the industrial
disclosure above); and geographic rendering via Leaflet + OpenStreetMap,
the open-source mapping stack Section 13.3 names for exactly this
("borrow, don't build"). Transformer coordinates are synthetic, like every
other physical parameter in a generated scenario.

Still out of scope: schematic (single-line-diagram) network rendering, as
opposed to the geographic map; and any view content that depends on
Modules C, D, E or G, which render an explicit "not built" panel naming
the relevant specification section instead of a placeholder chart. Those
panels are a deliberate product decision -- a utility engineer reading
"asset health: not built, requires the sensing device from item 6" learns
something true, where a fabricated hazard curve would cost the platform
its credibility the first time anyone asked what was behind it.

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
