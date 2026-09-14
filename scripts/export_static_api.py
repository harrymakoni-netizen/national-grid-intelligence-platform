"""Pre-renders every API response the drill-down interface needs for the
demo scenario into static JSON under frontend/data/.

Why: the deployed demo runs on static hosting (Vercel) with no Python at
request time. Trying to run FastAPI + OpenDSS + scikit-learn as serverless
functions would mean cold-start compilation of a native power-flow backend
inside a 10-second function timeout -- fragile in exactly the situation
where it must not be. Since the demo scenario is fixed and read-only, its
responses can be computed once here (where the toolchain is known to work)
and committed. The frontend detects which source it is talking to and uses
the same payload shapes either way (frontend/js/data.js).

The live FastAPI backend remains the development path: generating new
scenarios, recomputing anything, extending endpoints.

Run: python scripts/export_static_api.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from sqlalchemy import select  # noqa: E402

from gridintel.db.models import NetworkNode, NodeType, SyntheticScenario  # noqa: E402
from gridintel.db.session import make_engine, make_session_factory  # noqa: E402
from gridintel.hierarchy.aggregate import ancestor_chain, descendant_ids  # noqa: E402
from gridintel.presentation import api as papi  # noqa: E402

OUT = ROOT / "frontend" / "data"


def safe(part: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "_.-") else "_" for ch in str(part))


def write(kind: str | None, parts: list[str] | None, payload) -> None:
    if kind is None:
        path = OUT / f"{parts[0]}.json"
    else:
        path = OUT / kind / ("__".join(safe(p) for p in parts) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    engine = make_engine()
    Session = make_session_factory(engine)

    with Session() as session:
        scenarios = papi.list_scenarios(session)
        if not scenarios:
            raise SystemExit("no scenarios in the database -- run scripts/seed_demo_scenario.py first")
        write(None, ["scenarios"], scenarios)

        for meta in scenarios:
            scenario_id = meta["id"]
            scenario = session.get(SyntheticScenario, scenario_id)
            root = ancestor_chain(session, scenario.config["substation_id"])[0]

            write("root", [scenario_id], papi.get_root(scenario_id, session))
            write("summary", [scenario_id], papi.view_summary(scenario_id, session))
            write("revenue", [scenario_id], papi.view_revenue_protection(scenario_id, session))

            node_ids = descendant_ids(session, root.id)
            transformer_ids = []

            for node_id in node_ids:
                node = session.get(NetworkNode, node_id)
                write("node", [node_id], papi.get_node(node_id, scenario_id, session))
                write("timeseries", [node_id], papi.node_timeseries(node_id, scenario_id, session))
                write("cases", [node_id], papi.node_cases(node_id, scenario_id, session))
                write("map", [node_id], papi.node_map(node_id, scenario_id, session))
                if node.node_type == NodeType.TRANSFORMER.value:
                    transformer_ids.append(node_id)
                    write("ntl", [node_id], papi.node_nontechnical_loss(node_id, scenario_id, session))
                print(f"  node {node_id}")

            # Per-connection payloads for every connection the UI can reach.
            seen: set[str] = set()
            for tid in transformer_ids:
                node_payload = papi.get_node(tid, scenario_id, session)
                for conn in node_payload["connections"]:
                    cid = conn["id"]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    write("conn_timeseries", [cid], papi.connection_timeseries(cid, scenario_id, session))
                    write("gt", [cid], papi.case_ground_truth(cid, scenario_id, session))
                    try:
                        write("case", [cid], papi.case_detail(cid, scenario_id, session))
                    except Exception:
                        # Not every connection classifies (too little purchase
                        # history); the UI handles a missing case gracefully.
                        pass
                print(f"  connections for {tid}")

        try:
            write(None, ["held_out_evaluation"], papi.module_a_held_out_evaluation())
        except Exception as exc:  # pragma: no cover - optional artefact
            print(f"  held-out evaluation skipped: {exc}")

    n_files = sum(1 for _ in OUT.rglob("*.json"))
    size_kb = sum(f.stat().st_size for f in OUT.rglob("*.json")) / 1024
    print(f"\nWrote {n_files} JSON files ({size_kb:.0f} KB) to {OUT}")


if __name__ == "__main__":
    main()
