"""Tests for the Layer 6 presentation API (Section 11.3): drill-down must
resolve from the root to individual connections and back, and every case
endpoint must correctly separate synthetic ground truth (only ever
returned from the dedicated /ground-truth endpoint) from the model's own
output.
"""
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from gridintel.gridsynth.scenario import ScenarioConfig, generate_scenario
from gridintel.presentation import api as api_module


@pytest.fixture()
def client(session):
    config = ScenarioConfig(
        substation_id="DS-API",
        n_transformers=1,
        connections_per_transformer=12,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        weeks=6,
        interval_minutes=30,
    )
    scenario = generate_scenario(session, config, seed=33)
    session.commit()

    def override_get_session():
        yield session

    api_module.app.dependency_overrides[api_module.get_session] = override_get_session
    yield TestClient(api_module.app), scenario.id, config
    api_module.app.dependency_overrides.clear()


def test_health(client):
    test_client, _, _ = client
    assert test_client.get("/health").json() == {"status": "ok"}


def test_scenarios_lists_seeded_scenario(client):
    test_client, scenario_id, _ = client
    resp = test_client.get("/api/scenarios")
    assert resp.status_code == 200
    assert any(s["id"] == scenario_id for s in resp.json())


def test_root_resolves_to_national_node(client):
    test_client, scenario_id, _ = client
    resp = test_client.get(f"/api/scenarios/{scenario_id}/root")
    assert resp.status_code == 200
    assert resp.json()["node_type"] == "national"


def test_drill_down_from_root_reaches_transformer_and_connections(client):
    test_client, scenario_id, config = client
    root = test_client.get(f"/api/scenarios/{scenario_id}/root").json()

    node_id = root["id"]
    visited_transformer = False
    for _ in range(6):
        node = test_client.get(f"/api/nodes/{node_id}?scenario_id={scenario_id}").json()
        if node["node_type"] == "transformer":
            visited_transformer = True
            assert len(node["connections"]) > 0
            break
        assert node["children"], f"node {node_id} has no children and is not a transformer"
        node_id = node["children"][0]["id"]

    assert visited_transformer


def test_node_timeseries_returns_aggregated_series(client):
    test_client, scenario_id, config = client
    root = test_client.get(f"/api/scenarios/{scenario_id}/root").json()
    resp = test_client.get(f"/api/nodes/{root['id']}/timeseries?scenario_id={scenario_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["n_connections"] == config.connections_per_transformer
    assert len(data["ts"]) > 0
    assert all(v is not None for v in data["mean_kw"])


def test_case_ground_truth_only_on_dedicated_endpoint(client):
    test_client, scenario_id, config = client
    transformer_id = f"{config.substation_id}-T01"
    cases = test_client.get(f"/api/nodes/{transformer_id}/cases?scenario_id={scenario_id}").json()

    for case in cases:
        assert "ground_truth" not in case  # case queue entries never leak ground truth inline

        detail = test_client.get(f"/api/cases/{case['connection_id']}?scenario_id={scenario_id}").json()
        assert "ground_truth" not in detail  # nor does the detail endpoint

        gt = test_client.get(f"/api/cases/{case['connection_id']}/ground-truth?scenario_id={scenario_id}").json()
        assert "has_ground_truth" in gt  # only the dedicated endpoint carries it


def test_unknown_node_returns_404(client):
    test_client, scenario_id, _ = client
    resp = test_client.get(f"/api/nodes/DOES-NOT-EXIST?scenario_id={scenario_id}")
    assert resp.status_code == 404
