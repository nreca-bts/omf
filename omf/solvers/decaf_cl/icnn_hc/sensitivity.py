"""Data-driven interpolation of frozen Iowa240 regulator responses."""

from __future__ import annotations

import numpy as np

from .data import RuntimeDataError


def response_for_taps(data: dict, taps: np.ndarray) -> np.ndarray:
    """Return summed margin response for static or per-hour A/B/C tap states."""
    locations = data["regulator"]["locations"].astype(str)
    anchors = data["regulator"]["tap_anchors"].astype(float)
    library = data["regulator"]["response_margin_pu"].astype(float, copy=False)
    taps = np.asarray(taps, dtype=float)
    static = taps.shape == (len(locations),)
    hourly = taps.shape == (library.shape[2], len(locations))
    if not (static or hourly):
        raise RuntimeDataError(
            f"Expected {(len(locations),)} static or "
            f"{(library.shape[2], len(locations))} hourly taps, got shape {taps.shape}"
        )
    if library.shape[:2] != (len(locations), len(anchors)):
        raise RuntimeDataError("Regulator response location/anchor alignment error")
    if np.any(taps < anchors.min()) or np.any(taps > anchors.max()):
        raise ValueError(f"Regulator taps must lie in [{anchors.min():g}, {anchors.max():g}]")
    total = np.zeros(library.shape[2:], dtype=float)
    if static:
        taps = np.broadcast_to(taps, (library.shape[2], len(locations)))
    hour_index = np.arange(library.shape[2])
    for location_index in range(len(locations)):
        location_taps = taps[:, location_index]
        upper = np.searchsorted(anchors, location_taps, side="left")
        upper = np.clip(upper, 1, len(anchors) - 1)
        lower = upper - 1
        fraction = ((location_taps - anchors[lower]) /
                    (anchors[upper] - anchors[lower]))
        total += ((1.0 - fraction[:, None]) * library[location_index, lower, hour_index] +
                  fraction[:, None] * library[location_index, upper, hour_index])
    return total


def weighted_constraint_relief(lambda_rows: np.ndarray, delta_margin: np.ndarray) -> float:
    """Return ``-sum(lambda * delta_g)`` as a candidate-screening score.

    The score ranks frozen response actions under current maximum-HC KKT
    weights. It is not reported as, or substituted for, realized HC gain.
    """
    return float(-np.sum(np.asarray(lambda_rows) * np.asarray(delta_margin)))
