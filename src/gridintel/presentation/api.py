"""Layer 6 presentation API (Section 11.3): the drill-down interface's data
source -- national aggregate down to individual connection, with every
figure traceable to what produced it.

Every number this API returns that is not explicitly a ground-truth
comparison comes from Module A's reconstruction and Module B's case
pipeline -- the same code paths a real deployment would use. Ground truth
is exposed ONLY on endpoints whose name says so (`/ground-truth`), and the
frontend must label those as synthetic ground truth, never as a measurement
(Section 15).

This API has no equivalent for a real feeder yet because there is no real
feeder -- every scenario it serves is synthetic, selected explicitly by
`scenario_id`, never implied as production data.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from gridintel.db.models import (
    Connection,
    GroundTruthAnomaly,
    NetworkNode,
    NodeType,
    SyntheticScenario,
    VendingEvent,
)
from gridintel.db.session import make_engine, make_session_factory
from gridintel.hierarchy.aggregate import ancestor_chain, descendant_ids, resolve_connections
from gridintel.module_a.evaluate import evaluate_against_held_out_real_data
from gridintel.module_a.reconstruct import reconstruct_for_connection
from gridintel.module_b.evaluate import evaluate_case_queue
from gridintel.module_b.nontechnical_loss import compute_nontechnical_loss
from gridintel.module_b.pipeline import build_case_queue, compute_features_for_transformer
from gridintel.module_b.weak_supervision import classify
from gridintel.presentation.aggregation import reconstructed_consumption_for_subtree

app = FastAPI(title="National Grid Intelligence Platform - Presentation API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)  # local demo only -- not a production CORS policy

_engine = make_engine()
_SessionFactory = make_session_factory(_engine)


def get_session():
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()


def _scenario_window(scenario: SyntheticScenario) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    cfg = scenario.config
    start = pd.Timestamp(cfg["start"])
    end = start + pd.Timedelta(weeks=cfg["weeks"])
    return start, end, cfg["interval_minutes"]


def _get_scenario_or_404(session: Session, scenario_id: str) -> SyntheticScenario:
    scenario = session.get(SyntheticScenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, f"scenario {scenario_id!r} not found")
    return scenario


@app.get("/api/scenarios")
def list_scenarios(session: Session = Depends(get_session)):
    rows = session.execute(select(SyntheticScenario)).scalars().all()
    return [
        {
            "id": s.id,
            "name": s.name,
            "seed": s.seed,
            "substation_id": s.config.get("substation_id"),
            "weeks": s.config.get("weeks"),
            "created_at": s.created_at.isoformat(),
            "config": s.config,
        }
        for s in rows
    ]


@app.get("/api/scenarios/{scenario_id}/root")
def get_root(scenario_id: str, session: Session = Depends(get_session)):
    scenario = _get_scenario_or_404(session, scenario_id)
    substation_id = scenario.config["substation_id"]
    chain = ancestor_chain(session, substation_id)
    root = chain[0]
    return {"id": root.id, "name": root.name, "node_type": root.node_type}


@app.get("/api/nodes/{node_id}")
def get_node(node_id: str, scenario_id: str | None = None, session: Session = Depends(get_session)):
    node = session.get(NetworkNode, node_id)
    if node is None:
        raise HTTPException(404, f"node {node_id!r} not found")

    children = session.execute(select(NetworkNode).where(NetworkNode.parent_id == node_id)).scalars().all()
    response = {
        "id": node.id,
        "name": node.name,
        "node_type": node.node_type,
        "parent_id": node.parent_id,
        "attributes": node.attributes,
        "children": [{"id": c.id, "name": c.name, "node_type": c.node_type} for c in children],
        "connections": [],
    }

    # Connections associate directly with a TRANSFORMER (Section 11.1 --
    # never with an LV feeder in this schema, see hierarchy/aggregate.py),
    # so this is checked at every node regardless of whether it also has
    # NetworkNode children, not only at tree leaves.
    if scenario_id:
        resolved = [r for r in resolve_connections(session, node_id) if r.network_node_id == node_id]
        for r in resolved:
            conn = session.get(Connection, r.connection_id)
            response["connections"].append(
                {
                    "id": r.connection_id,
                    "archetype": conn.archetype if conn else None,
                    "status": conn.status if conn else None,
                    "confidence": r.confidence,
                    "source_type": r.source_type,
                }
            )

    return response


@app.get("/api/nodes/{node_id}/timeseries")
def node_timeseries(node_id: str, scenario_id: str, session: Session = Depends(get_session)):
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    df = reconstructed_consumption_for_subtree(
        session, node_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
    )
    if df.empty:
        return {"ts": [], "mean_kw": [], "n_connections": 0}

    n_connections = df["connection_id"].nunique()
    agg = df.groupby("ts")["kw"].sum().sort_index()
    agg.index = pd.to_datetime(agg.index)
    daily = agg.resample("1D").mean()
    return {
        "ts": [t.isoformat() for t in daily.index],
        "mean_kw": [round(float(v), 4) for v in daily.values],
        "n_connections": int(n_connections),
    }


@app.get("/api/connections/{connection_id}/timeseries")
def connection_timeseries(connection_id: str, scenario_id: str, session: Session = Depends(get_session)):
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    try:
        result = reconstruct_for_connection(
            session, connection_id, scenario_id, start=start, end=end, interval_minutes=interval_minutes
        )
    except ValueError:
        return {"ts": [], "mean_kw": [], "p10_kw": [], "p90_kw": [], "purchase_events": []}

    df = pd.DataFrame(
        {"mean_kw": result.mean_kw, "p10_kw": result.p10_kw, "p90_kw": result.p90_kw}, index=result.index
    ).resample("1D").mean()

    events = session.execute(
        select(VendingEvent.ts, VendingEvent.kwh_purchased, VendingEvent.amount)
        .where(VendingEvent.connection_id == connection_id)
        .where(VendingEvent.scenario_id == scenario_id)
    ).all()

    return {
        "ts": [t.isoformat() for t in df.index],
        "mean_kw": [None if pd.isna(v) else round(float(v), 4) for v in df["mean_kw"]],
        "p10_kw": [None if pd.isna(v) else round(float(v), 4) for v in df["p10_kw"]],
        "p90_kw": [None if pd.isna(v) else round(float(v), 4) for v in df["p90_kw"]],
        "purchase_events": [
            {"ts": pd.Timestamp(ts).isoformat(), "kwh": round(kwh, 2), "amount": amount} for ts, kwh, amount in events
        ],
    }


def _transformer_ids_under(session: Session, node_id: str) -> list[str]:
    node_ids = descendant_ids(session, node_id)
    return [
        nid
        for nid in node_ids
        if (n := session.get(NetworkNode, nid)) is not None and n.node_type == NodeType.TRANSFORMER.value
    ]


@app.get("/api/nodes/{node_id}/cases")
def node_cases(node_id: str, scenario_id: str, session: Session = Depends(get_session)):
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    transformer_ids = _transformer_ids_under(session, node_id)
    all_entries = []
    for tid in transformer_ids:
        all_entries.extend(
            build_case_queue(session, tid, scenario_id, start=start, end=end, interval_minutes=interval_minutes)
        )
    all_entries.sort(key=lambda e: (e.confidence, e.suspicion_score), reverse=True)

    return [
        {
            "connection_id": e.connection_id,
            "predicted_cause": e.predicted_cause,
            "confidence": round(e.confidence, 3),
            "suspicion_score": round(e.suspicion_score, 3),
            "estimated_recoverable_kw": round(e.estimated_recoverable_kw, 3),
        }
        for e in all_entries
    ]


@app.get("/api/cases/{connection_id}")
def case_detail(connection_id: str, scenario_id: str, session: Session = Depends(get_session)):
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    from gridintel.db.models import ConnectionAssociation

    assoc = session.execute(
        select(ConnectionAssociation.network_node_id)
        .where(ConnectionAssociation.connection_id == connection_id)
        .where(ConnectionAssociation.effective_to.is_(None))
    ).scalar_one_or_none()
    if assoc is None:
        raise HTTPException(404, f"connection {connection_id!r} has no current association")

    features_list = compute_features_for_transformer(
        session, assoc, scenario_id, start=start, end=end, interval_minutes=interval_minutes
    )
    features = next((f for f in features_list if f.connection_id == connection_id), None)
    if features is None:
        raise HTTPException(404, f"no reconstructable purchase history for {connection_id!r}")

    label = classify(features)

    return {
        "connection_id": connection_id,
        "transformer_id": assoc,
        "predicted_cause": label.predicted_cause,
        "confidence": round(label.confidence, 3),
        "votes": {k: round(v, 3) for k, v in label.votes.items()},
        "evidence": {
            "baseline_mean_kw": round(features.baseline_mean_kw, 3),
            "recent_mean_kw": round(features.recent_mean_kw, 3),
            "fractional_change": round(features.fractional_change, 3),
            "daylight_fractional_change": round(features.daylight_fractional_change, 3),
            "evening_fractional_change": round(features.evening_fractional_change, 3),
            "irradiance_correlation": round(features.irradiance_correlation, 3),
            "step_sharpness": round(features.step_sharpness, 2),
            "open_segment_ratio": round(features.open_segment_ratio, 2),
            "zero_purchase_activity_recent": features.zero_purchase_activity_recent,
            "connection_inactive": features.connection_inactive,
            "peer_group_z_score": round(features.peer_group_z_score, 2),
            "estimated_recoverable_kw": round(features.estimated_recoverable_kw, 3),
        },
    }


@app.get("/api/cases/{connection_id}/ground-truth")
def case_ground_truth(connection_id: str, scenario_id: str, session: Session = Depends(get_session)):
    """Synthetic ground truth ONLY -- the frontend must present this as
    "actually injected as" for a demo/validation view, never as if it were
    independently observed. Does not exist for a real connection.
    """
    row = session.execute(
        select(GroundTruthAnomaly)
        .where(GroundTruthAnomaly.scenario_id == scenario_id)
        .where(GroundTruthAnomaly.connection_id == connection_id)
    ).scalar_one_or_none()
    if row is None:
        return {"has_ground_truth": False}
    return {
        "has_ground_truth": True,
        "anomaly_type": row.anomaly_type,
        "start_ts": row.start_ts.isoformat(),
        "parameters": row.parameters,
    }


@app.get("/api/module-a/held-out-evaluation")
def module_a_held_out_evaluation():
    """Section 12.4's explicit demo requirement: 'measured reconstruction
    error against held-out real interval data, stated as a number.'
    """
    result = evaluate_against_held_out_real_data(seed=1)
    return {
        "source": "UCI household power consumption dataset, last 90 days held out, never used to fit anything",
        "daily_mae_kw": round(result.daily_mae, 4),
        "daily_relative_mae": round(result.daily_relative_mae, 4),
        "monthly_mae_kw": round(result.monthly_mae, 4),
        "p10_p90_coverage": round(result.p10_p90_coverage, 3) if result.p10_p90_coverage == result.p10_p90_coverage else None,
    }


@app.get("/api/nodes/{node_id}/map")
def node_map(node_id: str, scenario_id: str, session: Session = Depends(get_session)):
    """Geographic layout for every transformer beneath a node, annotated
    with its open case count -- Section 11.3's "geographic representation
    at each level". Coordinates are synthetic (network_catalog.py), like
    every other physical parameter in a generated scenario.
    """
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    points = []
    for tid in _transformer_ids_under(session, node_id):
        node = session.get(NetworkNode, tid)
        if node is None or node.latitude is None or node.longitude is None:
            continue
        cases = build_case_queue(
            session, tid, scenario_id, start=start, end=end, interval_minutes=interval_minutes
        )
        n_connections = len(
            [r for r in resolve_connections(session, tid) if r.network_node_id == tid]
        )
        points.append(
            {
                "id": tid,
                "name": node.name,
                "node_type": node.node_type,
                "latitude": node.latitude,
                "longitude": node.longitude,
                "n_connections": n_connections,
                "n_cases": len(cases),
                "recoverable_kw": round(sum(c.estimated_recoverable_kw for c in cases), 3),
                "top_cause": cases[0].predicted_cause if cases else None,
                "rating_kva": node.attributes.get("rating_kva"),
            }
        )
    return {"points": points}


@app.get("/api/nodes/{node_id}/nontechnical-loss")
def node_nontechnical_loss(node_id: str, scenario_id: str, session: Session = Depends(get_session)):
    """Section 7.2's energy balance for a single transformer. `measured_kw`
    is sensor-EMULATED from synthetic ground truth -- no sensing hardware
    exists yet (item 6) -- while accounted energy and modelled technical
    loss come from Module A and the digital twin respectively.
    """
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)

    node = session.get(NetworkNode, node_id)
    if node is None:
        raise HTTPException(404, f"node {node_id!r} not found")
    if node.node_type != NodeType.TRANSFORMER.value:
        raise HTTPException(
            400, "the energy-balance equation is defined at transformer level (Section 7.2)"
        )

    result = compute_nontechnical_loss(
        session, scenario_id, node_id, start=start, end=end, interval_minutes=interval_minutes
    )
    daily = (
        pd.DataFrame(
            {
                "measured": result.measured_inflow_kw,
                "accounted": result.energy_accounted_kw,
                "modelled_loss": result.modelled_technical_loss_kw,
                "residual": result.series,
            }
        )
        .resample("1D")
        .mean()
    )
    return {
        "ts": [t.isoformat() for t in daily.index],
        "measured_kw": [round(float(v), 4) for v in daily["measured"]],
        "accounted_kw": [round(float(v), 4) for v in daily["accounted"]],
        "modelled_technical_loss_kw": [round(float(v), 4) for v in daily["modelled_loss"]],
        "nontechnical_loss_kw": [round(float(v), 4) for v in daily["residual"]],
        "twin_coverage_fraction": round(result.twin_coverage_fraction, 3),
        "mean_nontechnical_loss_kw": round(float(result.series.mean()), 4),
        "mean_measured_kw": round(float(result.measured_inflow_kw.mean()), 4),
        "metered_connection_ids": result.metered_connection_ids,
    }


@app.get("/api/views/summary")
def view_summary(scenario_id: str, session: Session = Depends(get_session)):
    """Cross-cutting figures the role views share. Deliberately explicit
    about which modules are NOT built, so a view can render an honest
    "not available" state instead of a fabricated number.
    """
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)
    root = ancestor_chain(session, scenario.config["substation_id"])[0]

    cases = []
    for tid in _transformer_ids_under(session, root.id):
        cases.extend(
            build_case_queue(session, tid, scenario_id, start=start, end=end, interval_minutes=interval_minutes)
        )
    cases.sort(key=lambda e: (e.confidence, e.suspicion_score), reverse=True)

    by_cause: dict[str, dict] = {}
    for c in cases:
        entry = by_cause.setdefault(c.predicted_cause, {"n": 0, "recoverable_kw": 0.0})
        entry["n"] += 1
        entry["recoverable_kw"] = round(entry["recoverable_kw"] + c.estimated_recoverable_kw, 3)

    connections = session.execute(select(Connection)).scalars().all()
    archetype_counts: dict[str, int] = {}
    for conn in connections:
        archetype_counts[conn.archetype] = archetype_counts.get(conn.archetype, 0) + 1

    total_recoverable_kw = sum(c.estimated_recoverable_kw for c in cases)
    transformer_ids = _transformer_ids_under(session, root.id)

    return {
        "scenario_id": scenario_id,
        "root_id": root.id,
        "n_transformers": len(transformer_ids),
        "n_connections": len(connections),
        "n_cases": len(cases),
        "total_recoverable_kw": round(total_recoverable_kw, 3),
        # 90 days is Section 17.1's pilot measurement window.
        "recoverable_kwh_90d": round(total_recoverable_kw * 24 * 90, 1),
        "cases_by_cause": by_cause,
        "archetype_counts": archetype_counts,
        "top_cases": [
            {
                "connection_id": c.connection_id,
                "predicted_cause": c.predicted_cause,
                "confidence": round(c.confidence, 3),
                "estimated_recoverable_kw": round(c.estimated_recoverable_kw, 3),
            }
            for c in cases[:5]
        ],
        "modules_not_built": {
            "C_asset_health": "Transformer health / remaining-life (Section 8.3) is not built.",
            "D_demand_forecasting": "Demand forecasting (Section 8.4) is not built.",
            "E_shedding_allocation": "Shedding optimisation (Section 9.1) is not built.",
            "G_industrial_nilm": "Industrial load disaggregation (Section 9.3) is not built.",
        },
    }


@app.get("/api/views/revenue-protection")
def view_revenue_protection(scenario_id: str, session: Session = Depends(get_session)):
    """Case-queue precision measured against synthetic ground truth. In a
    real deployment this number cannot exist until the field loop returns
    confirmed outcomes (Section 10.1) -- it is shown here as validation of
    a synthetic scenario, and must be labelled as such.
    """
    scenario = _get_scenario_or_404(session, scenario_id)
    start, end, interval_minutes = _scenario_window(scenario)
    root = ancestor_chain(session, scenario.config["substation_id"])[0]

    cases = []
    for tid in _transformer_ids_under(session, root.id):
        cases.extend(
            build_case_queue(session, tid, scenario_id, start=start, end=end, interval_minutes=interval_minutes)
        )
    cases.sort(key=lambda e: (e.confidence, e.suspicion_score), reverse=True)

    top3 = evaluate_case_queue(session, scenario_id, cases, k=3)
    top5 = evaluate_case_queue(session, scenario_id, cases, k=5)
    full = evaluate_case_queue(session, scenario_id, cases)

    def _fmt(ev):
        return {
            "n_cases": ev.n_cases,
            "exact_precision": None if ev.n_cases == 0 else round(ev.exact_precision, 3),
            "confusable_aware_precision": None if ev.n_cases == 0 else round(ev.confusable_aware_precision, 3),
            "by_cause": ev.by_cause,
        }

    return {
        "validation_basis": "synthetic ground truth -- NOT field-confirmed outcomes",
        "precision_at_3": _fmt(top3),
        "precision_at_5": _fmt(top5),
        "precision_full_queue": _fmt(full),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


_FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if _FRONTEND_DIR.exists():
    # Mounted last so it never shadows the /api/* and /health routes above.
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
