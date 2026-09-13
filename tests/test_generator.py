import numpy as np
import pandas as pd
import pytest

from gridintel.db.models import AnomalyType, ConnectionArchetype, NodeType
from gridintel.gridsynth import anomalies, archetypes, purchasing, shedding
from gridintel.gridsynth.lossmodel import transformer_loss_kw
from gridintel.gridsynth.topology import build_feeder_topology
from gridintel.hierarchy.aggregate import validate_parent_child


def test_topology_respects_hierarchy_ordering():
    topo = build_feeder_topology(
        substation_id="DS1", n_transformers=3, connections_per_transformer=8, seed=1
    )
    node_by_id = {nid: ntype for _, nid, ntype, _, _ in topo.node_records}
    for parent_id, node_id, node_type, _, _ in topo.node_records:
        parent_type = NodeType.DISTRIBUTION_SUBSTATION if parent_id == "DS1" else node_by_id[parent_id]
        validate_parent_child(parent_type, node_type)  # raises if invalid

    assert len(topo.transformers) == 3
    assert len(topo.connections) == 24
    # every connection's transformer_node_id must be a real transformer
    transformer_ids = {t.node_id for t in topo.transformers}
    assert all(c.transformer_node_id in transformer_ids for c in topo.connections)


def test_topology_archetype_mix_roughly_matches_config():
    mix = {
        ConnectionArchetype.HIGH_DENSITY_LOW_INCOME: 0.8,
        ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL: 0.1,
        ConnectionArchetype.SMALL_COMMERCIAL: 0.05,
        ConnectionArchetype.INDUSTRIAL: 0.05,
    }
    topo = build_feeder_topology(
        substation_id="DS1", n_transformers=4, connections_per_transformer=100,
        archetype_mix=mix, seed=3,
    )
    counts = {}
    for c in topo.connections:
        counts[c.archetype] = counts.get(c.archetype, 0) + 1
    frac_high_density = counts[ConnectionArchetype.HIGH_DENSITY_LOW_INCOME] / len(topo.connections)
    assert frac_high_density == pytest.approx(0.8, abs=0.05)


def test_archetype_shapes_normalised_and_real_source_used_for_residential():
    shape = archetypes.build_archetype_shape(
        ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL, interval_minutes=30
    )
    assert shape.diurnal.mean() == pytest.approx(1.0, abs=1e-6)
    assert shape.weekly.mean() == pytest.approx(1.0, abs=1e-6)
    assert len(shape.diurnal) == 48

    assert "real" in archetypes.ARCHETYPE_SHAPE_SOURCE[ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL]
    assert "assumed" in archetypes.ARCHETYPE_SHAPE_SOURCE[ConnectionArchetype.SMALL_COMMERCIAL]


def test_generate_true_consumption_nonnegative_and_within_plausible_range():
    topo = build_feeder_topology(
        substation_id="DS1", n_transformers=1, connections_per_transformer=10, seed=5
    )
    df = archetypes.generate_true_consumption(
        topo.connections,
        start=pd.Timestamp("2026-01-05", tz="UTC"),
        end=pd.Timestamp("2026-01-12", tz="UTC"),
        interval_minutes=30,
        seed=5,
    )
    assert (df["kw"] >= 0).all()
    # industrial connections should have materially higher mean draw than
    # high-density low-income connections
    conn_by_id = {c.connection_id: c for c in topo.connections}
    df["archetype"] = df["connection_id"].map(lambda cid: conn_by_id[cid].archetype)
    means = df.groupby("archetype")["kw"].mean()
    if ConnectionArchetype.INDUSTRIAL in means.index and ConnectionArchetype.HIGH_DENSITY_LOW_INCOME in means.index:
        assert means[ConnectionArchetype.INDUSTRIAL] > means[ConnectionArchetype.HIGH_DENSITY_LOW_INCOME]


def test_shedding_zeroes_consumption_only_in_assigned_group_windows():
    schedule = shedding.generate_shedding_schedule(n_groups=2, seed=1)
    index = pd.date_range("2026-01-05", periods=48 * 3, freq="30min", tz="UTC")
    df = pd.DataFrame({"connection_id": "C1", "ts": index, "kw": np.ones(len(index))})
    out = shedding.apply_shedding(
        df,
        transformer_by_connection={"C1": "T1"},
        group_by_transformer={"T1": 0},
        schedule=schedule,
    )
    assert out["shed"].any()
    assert out["shed"].any() and not out["shed"].all()
    shed_rows = out[out["shed"]]
    assert (shed_rows["kw"] < 0.5).all()  # dropped to standby fraction of 1.0 kw baseline


def test_purchasing_never_supplies_more_than_available_balance():
    """The hard upper bound Section 8.1 relies on: supplied energy can
    never exceed the prepaid balance, i.e. the simulator never invents
    energy from nothing. A low steady baseline (so the model settles into
    small, balance-appropriate purchases) followed by one abrupt massive
    spike forces a shortfall no plausible purchase history could have
    covered, which is what we check for.
    """
    index = pd.date_range("2026-01-01", periods=24 * 4 * 10, freq="15min", tz="UTC")
    true_kw = np.full(len(index), 0.2)
    true_kw[-1] = 1_000_000.0  # spike no plausible accumulated balance could hold
    actual_kwh, events = purchasing.simulate_connection(
        connection_id="C1",
        archetype=ConnectionArchetype.HIGH_DENSITY_LOW_INCOME,
        tariff_band="domestic_low",
        true_kw=true_kw,
        timestamps=index,
        interval_minutes=15,
        seed=1,
    )
    wanted_kwh = true_kw * 0.25
    assert (actual_kwh <= wanted_kwh + 1e-9).all()
    assert len(events) > 0
    assert actual_kwh[-1] < wanted_kwh[-1] - 1e-6  # the spike could not have been fully supplied


def test_bypass_anomaly_leaves_physical_unchanged_but_cuts_metered():
    index = pd.date_range("2026-01-01", periods=20, freq="30min", tz="UTC")
    df = pd.DataFrame({"connection_id": "C1", "ts": index, "kw": np.full(len(index), 2.0)})
    from gridintel.gridsynth.topology import ConnectionSpec

    conn = ConnectionSpec(
        connection_id="C1", transformer_node_id="T1", lv_feeder_node_id="F1",
        archetype=ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL,
        distance_from_transformer_m=50, service_drop_r_ohm=0.1, service_drop_x_ohm=0.01, phase=1,
    )
    out, records = anomalies.inject_anomalies(
        df, [conn],
        start=index[0], end=index[-1] + pd.Timedelta(minutes=30),
        interval_minutes=30,
        rates={AnomalyType.PARTIAL_BYPASS: 1.0},
        seed=1,
    )
    assert len(records) == 1
    rec = records[0]
    active = out["ts"] >= rec.start_ts
    assert (out.loc[active, "kw"] == 2.0).all()  # physical draw unaffected
    assert (out.loc[active, "metered_kw"] < 2.0).all()  # metered reduced
    assert (out.loc[~active, "metered_kw"] == out.loc[~active, "kw"]).all()  # baseline untouched


def test_vacancy_anomaly_reduces_physical_consumption():
    index = pd.date_range("2026-01-01", periods=20, freq="30min", tz="UTC")
    df = pd.DataFrame({"connection_id": "C1", "ts": index, "kw": np.full(len(index), 1.5)})
    from gridintel.gridsynth.topology import ConnectionSpec

    conn = ConnectionSpec(
        connection_id="C1", transformer_node_id="T1", lv_feeder_node_id="F1",
        archetype=ConnectionArchetype.MEDIUM_DENSITY_RESIDENTIAL,
        distance_from_transformer_m=50, service_drop_r_ohm=0.1, service_drop_x_ohm=0.01, phase=1,
    )
    out, records = anomalies.inject_anomalies(
        df, [conn],
        start=index[0], end=index[-1] + pd.Timedelta(minutes=30),
        interval_minutes=30,
        rates={AnomalyType.VACANCY: 1.0},
        seed=1,
    )
    active = out["ts"] >= records[0].start_ts
    assert (out.loc[active, "kw"] < 0.1).all()


def test_transformer_loss_increases_with_load_and_has_no_load_floor():
    zero_load = transformer_loss_kw(rating_kva=50, load_kw=0, no_load_loss_kw=0.19, load_loss_kw=1.10)
    half_load = transformer_loss_kw(rating_kva=50, load_kw=25, no_load_loss_kw=0.19, load_loss_kw=1.10)
    full_load = transformer_loss_kw(rating_kva=50, load_kw=50, no_load_loss_kw=0.19, load_loss_kw=1.10)
    assert zero_load == pytest.approx(0.19)
    assert zero_load < half_load < full_load
    assert full_load == pytest.approx(0.19 + 1.10)
