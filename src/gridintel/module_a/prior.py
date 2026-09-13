"""Population-level consumption shape prior for Module A (Section 8.1):
"conditioned on tariff band, connection type, settlement typology, season,
temperature and the load-shedding hours applicable to the customer's
group."

This is deliberately the SAME shape template gridsynth.archetypes uses to
generate synthetic consumption -- reusing it here is not circular. It is
population-level, real-data-derived-or-documented-as-assumed information
(the UCI reference shape for residential archetypes; explicit templates for
commercial/industrial, per ARCHETYPE_SHAPE_SOURCE), independent of any
particular connection's ground truth. A real deployment would derive this
prior from the archetype/tariff population as a whole (e.g. the same public
reference data, or later, aggregated confirmed-normal connections), not
from the specific connection being reconstructed -- which is exactly how
it's used here: as a shape, not as an answer.

The prior encodes WHERE consumption is likely to fall within a day/week; it
carries no information about a connection's overall consumption LEVEL,
which reconstruct.py infers from that connection's own purchase history.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from gridintel.db.models import ConnectionArchetype
from gridintel.gridsynth.archetypes import build_archetype_shape
from gridintel.shedding_schedule import SheddingWindow, shed_mask_for_group

# During a shedding window, actual draw is a small standby fraction of what
# it would otherwise be (fridge thermal mass, security lighting, etc.) --
# the same figure the generator itself uses (gridsynth/shedding.py), so the
# prior's shedding treatment and the generator's are consistent by
# construction.
SHEDDING_STANDBY_FRACTION = 0.05


def population_shape_prior(
    archetype: ConnectionArchetype,
    index: pd.DatetimeIndex,
    *,
    shedding_windows: list[SheddingWindow] | None = None,
) -> np.ndarray:
    """Relative consumption weight per interval in `index` (mean ~1 over a
    full week absent shedding). Multiply by an inferred scale to get an
    absolute kW prior.
    """
    if len(index) == 0:
        return np.array([])

    interval_minutes = int(pd.Series(index).diff().dropna().dt.total_seconds().mode().iloc[0] / 60)
    shape = build_archetype_shape(archetype, interval_minutes)

    n_slots = len(shape.diurnal)
    slot_of_day = ((index.hour * 60 + index.minute) // interval_minutes).to_numpy() % n_slots
    dow = index.dayofweek.to_numpy()

    weight = shape.diurnal[slot_of_day] * shape.weekly[dow]

    if shedding_windows:
        mask = shed_mask_for_group(index, shedding_windows)
        weight = weight.copy()
        weight[mask] *= SHEDDING_STANDBY_FRACTION

    return weight
