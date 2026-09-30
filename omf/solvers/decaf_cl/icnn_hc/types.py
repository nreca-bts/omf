"""Internal typed result containers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class NetworkState:
    thermal_rating_multipliers: np.ndarray
    regulator_taps: np.ndarray
    candidate_location_index: int | None = None
    candidate_taps: np.ndarray | None = None

    def copy(self) -> "NetworkState":
        return NetworkState(
            self.thermal_rating_multipliers.copy(), self.regulator_taps.copy(),
            self.candidate_location_index,
            None if self.candidate_taps is None else self.candidate_taps.copy(),
        )


@dataclass
class LPSolution:
    success: bool
    status: int
    message: str
    hosting_capacity_mw: float
    runtime_sec: float
    build_time_sec: float
    primal_solution: np.ndarray | None
    inequality_duals: np.ndarray | None
    residuals: np.ndarray | None
    row_ranges: dict[str, tuple[int, int]]
    binding_constraints: list[dict[str, Any]] = field(default_factory=list)
    binding_constraint_family: str = "unknown"
    model_id: str = ""
