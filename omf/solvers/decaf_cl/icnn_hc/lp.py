"""Exact ReLU-epigraph ICNN LP and KKT diagnostics.

This module is the runtime extraction of the verified Iowa240 strict joint LP.
It has no simulation or feeder-model dependency.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csc_matrix, eye, hstack, kron, vstack

from .data import load_runtime_data, site_index
from .sensitivity import response_for_taps
from .types import LPSolution, NetworkState


DUAL_TOL = 1.0e-7
SLACK_TOL = 1.0e-7


def initial_network_state(data: dict[str, Any]) -> NetworkState:
    return NetworkState(
        thermal_rating_multipliers=np.ones(len(data["thermal"]["asset_id"]), dtype=float),
        regulator_taps=np.zeros(len(data["regulator"]["locations"]), dtype=float),
    )


def _model(data: dict[str, Any], model_id: str) -> dict[str, np.ndarray]:
    if model_id not in data["models"]:
        raise RuntimeError(f"Frozen model '{model_id}' is missing")
    model = data["models"][model_id]
    for key in ["W_0_weights", "W_1_weights", "W_2_weights", "Output_weights"]:
        if np.min(model[key]) < -1.0e-10:
            raise RuntimeError(f"{model_id}/{key} is not nonnegative; exact epigraph LP is invalid")
    return model


def target_voltage_margins(site_id: str, target_hc_mw: float, data: dict[str, Any]) -> np.ndarray:
    """Evaluate all frozen-hour ICNN margin outputs at an absolute PV capacity."""
    index = site_index(data, site_id)
    model = _model(data, str(data["sites"]["model_id"][index]))
    direction = (data["critical"]["pv_capacity_factor"].astype(float)[:, None] *
                 data["sites"]["direction"][index].astype(float)[None, :])
    x = data["critical"]["base_features"].astype(float) + float(target_hc_mw) * 1000.0 * direction
    x = (x - model["pq_mean"]) / model["pq_std"]
    z = np.maximum(x @ model["A_0_weights"].T + model["A_0_bias"], 0.0)
    for layer in range(1, 4):
        z = np.maximum(x @ model[f"A_{layer}_weights"].T + model[f"A_{layer}_bias"] +
                       z @ model[f"W_{layer-1}_weights"].T, 0.0)
    return (x @ model["A_output_weights"].T + model["Output_bias"] +
            z @ model["Output_weights"].T +
            float(data["config"]["voltage_guard_pu"].reshape(-1)[0]))


def _voltage_response(data: dict[str, Any], state: NetworkState) -> np.ndarray:
    response = response_for_taps(data, state.regulator_taps)
    if state.candidate_location_index is not None:
        if state.candidate_taps is None or "candidate" not in data:
            raise RuntimeError("Selected line regulator has no frozen tap response")
        matrix = data["candidate"]["response_per_tap_margin_pu"][state.candidate_location_index]
        taps = np.asarray(state.candidate_taps, dtype=float)
        if taps.shape != (len(data["critical"]["hours"]), 3):
            raise RuntimeError("Line-regulator hourly A/B/C taps are misaligned")
        response = response + taps @ matrix.T
    return response


def _add_h_column(block: csc_matrix, coefficient: np.ndarray) -> csc_matrix:
    return hstack([csc_matrix(coefficient.reshape(-1, 1)), block], format="csc")


def build_strict_joint_lp(
    base_features: np.ndarray,
    direction_by_hour_per_kw: np.ndarray,
    model: dict[str, np.ndarray],
    voltage_guard_pu: float,
    voltage_response_margin_pu: np.ndarray,
    thermal_baseline_frac: np.ndarray,
    thermal_gamma_frac_per_mw: np.ndarray,
    thermal_rating_multipliers: np.ndarray,
) -> tuple[np.ndarray, csc_matrix, np.ndarray, list[tuple[float | None, float | None]], dict[str, Any]]:
    """Build the verified strict ICNN LP without an artificial HC upper bound."""
    started = time.perf_counter()
    x0 = np.asarray(base_features, dtype=float)
    d = np.asarray(direction_by_hour_per_kw, dtype=float)
    mean = np.asarray(model["pq_mean"], dtype=float)
    std = np.asarray(model["pq_std"], dtype=float)
    t_count = x0.shape[0]
    output_count = model["Output_weights"].shape[0]
    hidden_widths = [model[f"A_{i}_weights"].shape[0] for i in range(4)]
    z_sizes = [t_count * width for width in hidden_widths]
    z1_size, z2_size, z3_size, z4_size = z_sizes
    n_hidden = sum(z_sizes)
    x_norm = (x0 - mean) / std
    d_norm = d / std

    def base_delta(a: np.ndarray, bias: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return x_norm @ a.T + bias.reshape(1, -1), d_norm @ a.T

    bases, deltas = [], []
    for layer in range(4):
        base, delta = base_delta(model[f"A_{layer}_weights"], model[f"A_{layer}_bias"])
        bases.append(base)
        deltas.append(delta)

    zero = csc_matrix
    rows: list[csc_matrix] = []
    rhs: list[np.ndarray] = []
    ranges: dict[str, tuple[int, int]] = {}
    cursor = 0

    block = hstack([-eye(z1_size, format="csc"), zero((z1_size, z2_size)), zero((z1_size, z3_size)), zero((z1_size, z4_size))], format="csc")
    rows.append(_add_h_column(block, deltas[0].reshape(-1)))
    rhs.append(-bases[0].reshape(-1))
    ranges["relu_z1"] = (cursor, cursor + z1_size); cursor += z1_size

    block = hstack([kron(eye(t_count, format="csc"), csc_matrix(model["W_0_weights"]), format="csc"), -eye(z2_size, format="csc"), zero((z2_size, z3_size)), zero((z2_size, z4_size))], format="csc")
    rows.append(_add_h_column(block, deltas[1].reshape(-1)))
    rhs.append(-bases[1].reshape(-1))
    ranges["relu_z2"] = (cursor, cursor + z2_size); cursor += z2_size

    block = hstack([zero((z3_size, z1_size)), kron(eye(t_count, format="csc"), csc_matrix(model["W_1_weights"]), format="csc"), -eye(z3_size, format="csc"), zero((z3_size, z4_size))], format="csc")
    rows.append(_add_h_column(block, deltas[2].reshape(-1)))
    rhs.append(-bases[2].reshape(-1))
    ranges["relu_z3"] = (cursor, cursor + z3_size); cursor += z3_size

    block = hstack([zero((z4_size, z1_size)), zero((z4_size, z2_size)), kron(eye(t_count, format="csc"), csc_matrix(model["W_2_weights"]), format="csc"), -eye(z4_size, format="csc")], format="csc")
    rows.append(_add_h_column(block, deltas[3].reshape(-1)))
    rhs.append(-bases[3].reshape(-1))
    ranges["relu_z4"] = (cursor, cursor + z4_size); cursor += z4_size

    out_base = x_norm @ model["A_output_weights"].T + model["Output_bias"].reshape(1, -1)
    out_base = out_base + np.asarray(voltage_response_margin_pu, dtype=float)
    out_delta = d_norm @ model["A_output_weights"].T
    block = hstack([zero((t_count * output_count, z1_size)), zero((t_count * output_count, z2_size)), zero((t_count * output_count, z3_size)), kron(eye(t_count, format="csc"), csc_matrix(model["Output_weights"]), format="csc")], format="csc")
    rows.append(_add_h_column(block, out_delta.reshape(-1)))
    rhs.append(-out_base.reshape(-1) - float(voltage_guard_pu))
    ranges["voltage"] = (cursor, cursor + t_count * output_count); cursor += t_count * output_count

    baseline = np.asarray(thermal_baseline_frac, dtype=float)
    gamma = np.asarray(thermal_gamma_frac_per_mw, dtype=float)
    rating = np.asarray(thermal_rating_multipliers, dtype=float)
    if baseline.shape != gamma.shape or baseline.shape != (t_count, len(rating)):
        raise RuntimeError("Thermal baseline/gamma/rating alignment error")
    thermal_coefficient = gamma.reshape(-1) / 1000.0
    thermal_block = csc_matrix((len(thermal_coefficient), n_hidden))
    rows.append(_add_h_column(thermal_block, thermal_coefficient))
    rhs.append((rating.reshape(1, -1) - baseline).reshape(-1))
    ranges["thermal"] = (cursor, cursor + baseline.size); cursor += baseline.size

    a_ub = vstack(rows, format="csc")
    b_ub = np.concatenate(rhs)
    objective = np.zeros(1 + n_hidden, dtype=float)
    objective[0] = -1.0
    bounds = [(0.0, None)] + [(0.0, None)] * n_hidden
    info = {
        "row_ranges": ranges,
        "build_time_sec": time.perf_counter() - started,
        "variables": int(a_ub.shape[1]),
        "constraints": int(a_ub.shape[0]),
        "nonzeros": int(a_ub.nnz),
        "artificial_capacity_upper_bound": False,
    }
    return objective, a_ub, b_ub, bounds, info


def _binding_rows(data: dict[str, Any], solution: Any, ranges: dict[str, tuple[int, int]]) -> tuple[list[dict[str, Any]], str]:
    residual = np.asarray(solution.ineqlin.residual, dtype=float)
    dual = np.maximum(-np.asarray(solution.ineqlin.marginals, dtype=float), 0.0)
    rows: list[dict[str, Any]] = []
    hours = data["critical"]["hours"].astype(int)
    output_names = data["outputs"]["name"].astype(str)
    asset_keys = data["thermal"]["asset_phase_key"].astype(str)
    v0, v1 = ranges["voltage"]
    v_res = residual[v0:v1].reshape(len(hours), len(output_names))
    v_dual = dual[v0:v1].reshape(v_res.shape)
    for hi, oi in np.argwhere((v_res <= SLACK_TOL) | (v_dual > DUAL_TOL)):
        rows.append({"family": "voltage", "hour": int(hours[hi]), "constraint": str(output_names[oi]), "slack": float(v_res[hi, oi]), "dual_kw_per_pu": float(v_dual[hi, oi])})
    t0, t1 = ranges["thermal"]
    t_res = residual[t0:t1].reshape(len(hours), len(asset_keys))
    t_dual = dual[t0:t1].reshape(t_res.shape)
    for hi, ai in np.argwhere((t_res <= SLACK_TOL) | (t_dual > DUAL_TOL)):
        rows.append({"family": "thermal", "hour": int(hours[hi]), "constraint": str(asset_keys[ai]), "asset_index": int(ai), "slack": float(t_res[hi, ai]), "dual_kw_per_loading_fraction": float(t_dual[hi, ai])})
    rows.sort(key=lambda item: (-float(item.get("dual_kw_per_pu", item.get("dual_kw_per_loading_fraction", 0.0))), float(item["slack"])))
    positive_families = {row["family"] for row in rows if max(row.get("dual_kw_per_pu", 0.0), row.get("dual_kw_per_loading_fraction", 0.0)) > DUAL_TOL}
    family = "joint" if len(positive_families) > 1 else (next(iter(positive_families)) if positive_families else (rows[0]["family"] if rows else "unknown"))
    return rows[:200], family


def solve_hc_lp(site_id: str, data: dict[str, Any] | None = None, state: NetworkState | None = None) -> LPSolution:
    """Solve maximum HC and retain primal, dual, residual and binding-row data."""
    data = load_runtime_data() if data is None else data
    index = site_index(data, site_id)
    state = initial_network_state(data) if state is None else state
    model_id = str(data["sites"]["model_id"][index])
    model = _model(data, model_id)
    response = _voltage_response(data, state)
    direction = data["critical"]["pv_capacity_factor"].astype(float)[:, None] * data["sites"]["direction"][index].astype(float)[None, :]
    c, a, b, bounds, info = build_strict_joint_lp(
        data["critical"]["base_features"], direction, model,
        float(data["config"]["voltage_guard_pu"].reshape(-1)[0]), response,
        data["thermal"]["baseline_frac"], data["thermal"]["gamma_frac_per_mw"][index],
        state.thermal_rating_multipliers,
    )
    started = time.perf_counter()
    result = linprog(c, A_ub=a, b_ub=b, bounds=bounds, method="highs", options={"presolve": True, "dual_feasibility_tolerance": 1e-7, "primal_feasibility_tolerance": 1e-7})
    solve_time = time.perf_counter() - started
    if not result.success:
        return LPSolution(False, int(result.status), str(result.message), float("nan"), solve_time, float(info["build_time_sec"]), None, None, None, info["row_ranges"], model_id=model_id)
    bindings, family = _binding_rows(data, result, info["row_ranges"])
    return LPSolution(
        True, int(result.status), str(result.message), float(result.x[0]) / 1000.0,
        solve_time, float(info["build_time_sec"]), np.asarray(result.x, dtype=float),
        np.maximum(-np.asarray(result.ineqlin.marginals, dtype=float), 0.0),
        np.asarray(result.ineqlin.residual, dtype=float), info["row_ranges"], bindings, family, model_id,
    )


def solve_target_restoration(site_id: str, target_hc_mw: float, data: dict[str, Any], state: NetworkState) -> dict[str, Any]:
    """Auxiliary positive-slack feasibility restoration at an infeasible target.

    Separate nonnegative engineering slacks are added only to voltage and
    thermal rows. Because their units differ, neither the objective nor its
    duals have an HC-sensitivity interpretation. The production upgrade
    planner does not use this routine; it is retained only as a diagnostic.
    """
    index = site_index(data, site_id)
    model = _model(data, str(data["sites"]["model_id"][index]))
    response = response_for_taps(data, state.regulator_taps)
    direction = data["critical"]["pv_capacity_factor"].astype(float)[:, None] * data["sites"]["direction"][index].astype(float)[None, :]
    c, a, b, bounds, info = build_strict_joint_lp(
        data["critical"]["base_features"], direction, model,
        float(data["config"]["voltage_guard_pu"].reshape(-1)[0]), response,
        data["thermal"]["baseline_frac"], data["thermal"]["gamma_frac_per_mw"][index], state.thermal_rating_multipliers,
    )
    ranges = info["row_ranges"]
    engineering = list(range(*ranges["voltage"])) + list(range(*ranges["thermal"]))
    n_slack = len(engineering)
    slack_block = csc_matrix((np.full(n_slack, -1.0), (engineering, np.arange(n_slack))), shape=(a.shape[0], n_slack))
    a_restore = hstack([a, slack_block], format="csc")
    objective = np.concatenate([np.zeros_like(c), np.ones(n_slack, dtype=float)])
    restore_bounds = [(float(target_hc_mw) * 1000.0, float(target_hc_mw) * 1000.0)] + bounds[1:] + [(0.0, None)] * n_slack
    result = linprog(objective, A_ub=a_restore, b_ub=b, bounds=restore_bounds, method="highs", options={"presolve": True})
    if not result.success:
        raise RuntimeError(f"Target feasibility restoration failed for {site_id}: {result.message}")
    dual = np.maximum(-np.asarray(result.ineqlin.marginals, dtype=float), 0.0)
    return {
        "restoration_weights": dual,
        "residuals": np.asarray(result.ineqlin.residual, dtype=float),
        "row_ranges": ranges,
        "dimensionless_restoration_score": float(np.sum(result.x[-n_slack:])),
    }
