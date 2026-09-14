"""Physical network catalog constants shared by the synthetic generator
(gridsynth, which needs them to invent a plausible feeder) and the digital
twin (digitaltwin, which needs them to interpret ANY feeder's records --
synthetic today, a real surveyed one later).

This module deliberately has no dependency on gridsynth: the twin is
meant to run in production against a real feeder that was never generated,
and must not import the synthetic generator package to do so. Catalog
constants live here, at the bottom of the dependency graph, so both
directions of use are correct.

Every value here is a REPRESENTATIVE placeholder for a typical 400V African
LV network, not a ZETDC measurement -- there is no feeder survey to draw
on yet (Section 7.3). Confirm against ZETDC network records or a feeder
survey, and have a power-systems engineer review before use beyond
internal development (Section 14.1).
"""
from __future__ import annotations

# PLACEHOLDER: representative LV service-drop conductor, 16mm2 Cu, typical
# published R/X per km for LV service cable. Confirm against ZETDC catalog.
SERVICE_DROP_R_OHM_PER_KM = 1.15
SERVICE_DROP_X_OHM_PER_KM = 0.09

# PLACEHOLDER: representative LV feeder aerial bundled conductor (ABC),
# 70mm2 AAAC, typical published R/X per km. Confirm against ZETDC catalog.
# NOTE: not currently consumed by any power-flow computation -- the
# generator and twin both model the LV network as a star of service drops
# directly off the transformer busbar (see topology.py / opendss_engine.py),
# not a shared trunk with laterals. A trunk+lateral topology would show
# more loss (shared conductor current, cumulative volt-drop along the
# trunk) than this star simplification does. This is a real fidelity gap,
# not a bug, and should be closed before this twin is trusted on a real
# feeder with a non-trivial LV backbone.
LV_FEEDER_R_OHM_PER_KM = 0.443
LV_FEEDER_X_OHM_PER_KM = 0.35

# PLACEHOLDER: representative 11kV/400V distribution transformer nameplate
# parameters by rating (kVA), typical IEC loss-class mid-range values.
# no_load_loss_kw is roughly load-independent (core loss); load_loss_kw is
# the loss at rated (full) load and scales ~ (load/rated)^2. Confirm against
# ZETDC's actual transformer fleet nameplate data.
TRANSFORMER_CATALOG = {
    50: {"no_load_loss_kw": 0.19, "load_loss_kw": 1.10, "impedance_pct": 4.0},
    100: {"no_load_loss_kw": 0.32, "load_loss_kw": 1.75, "impedance_pct": 4.0},
    200: {"no_load_loss_kw": 0.52, "load_loss_kw": 2.75, "impedance_pct": 4.5},
}

MV_KV = 11.0
LV_KV = 0.4

# Synthetic geography for generated feeders: a plausible urban Harare
# location so the drill-down map renders a realistic spatial layout.
# INVENTED, like every other physical parameter here -- not a survey, and
# not a claim about where any real ZETDC asset is.
SUBSTATION_BASE_LAT = -17.8292
SUBSTATION_BASE_LON = 31.0522
FEEDER_FOOTPRINT_DEG = 0.012  # roughly +/-1.3 km, a plausible LV feeder footprint
