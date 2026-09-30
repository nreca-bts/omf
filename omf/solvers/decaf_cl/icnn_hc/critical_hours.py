"""Offline critical-hour selection helper; normal HC runtime uses frozen hours."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import numpy as np

from .data import load_runtime_data


def _diverse_top(scores: np.ndarray, eligible: np.ndarray, count: int, separation: int) -> list[int]:
    selected: list[int] = []
    for hour in np.argsort(np.where(eligible, scores, -np.inf))[::-1]:
        if np.isfinite(scores[hour]) and all(abs(int(hour) - prior) >= separation for prior in selected):
            selected.append(int(hour))
            if len(selected) == count:
                break
    return selected


def select_critical_hours(
    voltage_risk: Iterable[float],
    thermal_risk: Iterable[float],
    pv_capacity_factor: Iterable[float],
    *,
    voltage_count: int = 62,
    thermal_count: int = 13,
    daylight_threshold: float = 0.10,
    separation_hours: int = 24,
) -> list[dict]:
    """Select explained voltage/thermal hours from precomputed annual metrics.

    This utility does not run OpenDSS and is not called by either business API.
    The production API always uses the frozen 80-hour set in runtime data.
    """
    voltage = np.asarray(list(voltage_risk), dtype=float)
    thermal = np.asarray(list(thermal_risk), dtype=float)
    pv = np.asarray(list(pv_capacity_factor), dtype=float)
    if not (voltage.ndim == thermal.ndim == pv.ndim == 1 and len(voltage) == len(thermal) == len(pv)):
        raise ValueError("voltage_risk, thermal_risk and pv_capacity_factor must be aligned 1-D arrays")
    eligible = np.isfinite(pv) & (pv >= daylight_threshold)
    reasons: dict[int, set[str]] = defaultdict(set)
    for hour in _diverse_top(voltage, eligible, voltage_count, max(1, separation_hours // 4)):
        reasons[hour].add("voltage_risk")
    for hour in _diverse_top(thermal, eligible, thermal_count, separation_hours):
        reasons[hour].add("thermal_risk")
    return [
        {"timestep": hour, "selection_reasons": sorted(reason), "voltage_risk": float(voltage[hour]), "thermal_risk": float(thermal[hour]), "pv_capacity_factor": float(pv[hour])}
        for hour, reason in sorted(reasons.items())
    ]


def frozen_critical_hours() -> list[int]:
    return load_runtime_data()["critical"]["hours"].astype(int).tolist()
