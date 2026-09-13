"""Seeds the default SQLite database with a demo scenario for the
drill-down interface (Section 12.4's twenty-minute demonstration): a
synthetic feeder with injected theft, solar and other anomaly cases,
sized to browse comfortably.

Run: python scripts/seed_demo_scenario.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from gridintel.db.session import init_db, make_engine, make_session_factory
from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario

DEMO_SUBSTATION_ID = "DS-DEMO"
DEMO_SEED = 42


def main() -> None:
    engine = make_engine()
    init_db(engine)
    Session = make_session_factory(engine)

    config = ScenarioConfig(
        substation_id=DEMO_SUBSTATION_ID,
        n_transformers=3,
        connections_per_transformer=18,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=8,
        interval_minutes=30,
    )
    with Session() as session:
        scenario = generate_scenario(session, config, seed=DEMO_SEED)
        session.commit()
        print(f"Seeded demo scenario: {scenario.id}")
        print(f"Root substation: {config.substation_id}")


if __name__ == "__main__":
    main()
