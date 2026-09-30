"""Hosting-capacity business service."""

from __future__ import annotations

from .data import load_runtime_data, site_index
from .lp import solve_hc_lp


def evaluate_hosting_capacity_impl(site_id: str) -> dict:
    data = load_runtime_data()
    index = site_index(data, site_id)
    result = solve_hc_lp(site_id, data=data)
    return {
        "site_id": str(data["sites"]["id"][index]),
        "phases": str(data["sites"]["phases"][index]).split("."),
        "hosting_capacity_mw": result.hosting_capacity_mw,
        "binding_constraint_family": result.binding_constraint_family,
        "binding_constraints": result.binding_constraints,
        "critical_hours": data["critical"]["hours"].astype(int).tolist(),
        "model_id": result.model_id,
        "runtime_sec": result.build_time_sec + result.runtime_sec,
        "solver_status": result.message,
        "success": result.success,
    }
