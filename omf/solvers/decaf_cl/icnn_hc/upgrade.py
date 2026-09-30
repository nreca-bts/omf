"""Thermal-first catalog planning, delayed one-bank placement, and HC fallback.

The public planner uses frozen target constraints and re-solves the ICNN LP
after accepted actions. Private KKT helpers are retained for regression
analysis but are not part of the current planning route.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from .data import load_runtime_data, site_index
from .lp import initial_network_state, solve_hc_lp, target_voltage_margins
from .sensitivity import response_for_taps, weighted_constraint_relief


MAX_ITERATIONS = 24
SCREEN_LIMIT = 6
KKT_SCORE_TOL = 1.0e-9
HC_NUMERICAL_TOL_MW = 1.0e-9


def _catalog(data: dict[str, Any], catalog_id: str) -> dict[str, Any]:
    ids = data["catalogs"]["id"].astype(str).tolist()
    if catalog_id not in ids:
        raise ValueError(f"Unknown catalog_id '{catalog_id}'. Available catalogs: {', '.join(ids)}")
    return data["catalogs"]


def _catalog_arrays(catalog: dict[str, Any], asset_type: str) -> tuple[np.ndarray, np.ndarray]:
    if asset_type == "primary_line":
        return catalog["line_rating_a"].astype(float), catalog["line_cost_usd_per_km"].astype(float)
    return catalog["transformer_rating_kva"].astype(float), catalog["transformer_cost_usd"].astype(float)


def _catalog_action_cost(catalog: dict[str, Any], asset_type: str, rating: float, length_km: float) -> float:
    ratings, costs = _catalog_arrays(catalog, asset_type)
    match = np.flatnonzero(np.isclose(ratings, rating))
    if not len(match):
        raise ValueError(f"Rating {rating:g} is not in the {asset_type} catalog")
    cost = float(costs[match[0]])
    return cost * float(length_km) if asset_type == "primary_line" else cost


def _incremental_cost(
    catalog: dict[str, Any], asset_type: str, new_rating: float, length_km: float,
    previously_paid_catalog_cost: float,
) -> tuple[float, float]:
    """Return additional project cost and cumulative catalog cost.

    The first replacement pays its catalog project cost. A later replacement
    of the same physical asset pays only the positive difference, so prior
    accepted expenditure is never charged again.
    """
    cumulative = _catalog_action_cost(catalog, asset_type, new_rating, length_km)
    return max(0.0, cumulative - float(previously_paid_catalog_cost)), cumulative


def _physical_asset_groups(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Group phase constraint rows into one physical line/transformer asset."""
    groups: OrderedDict[tuple[str, str], list[int]] = OrderedDict()
    ids = data["thermal"]["asset_id"].astype(str)
    types = data["thermal"]["asset_type"].astype(str)
    for row_index, key in enumerate(zip(types, ids)):
        groups.setdefault(key, []).append(row_index)
    return [
        {"asset_type": asset_type, "asset_id": asset_id, "row_indices": np.asarray(indices, dtype=int)}
        for (asset_type, asset_id), indices in groups.items()
    ]


def _pareto_efficient(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove rating/cost actions dominated within one physical asset."""
    efficient = []
    for candidate in candidates:
        dominated = any(
            other is not candidate
            and other["new_rating"] >= candidate["new_rating"]
            and other["incremental_cost_usd"] <= candidate["incremental_cost_usd"]
            and (
                other["new_rating"] > candidate["new_rating"]
                or other["incremental_cost_usd"] < candidate["incremental_cost_usd"]
            )
            for other in candidates
        )
        if not dominated:
            efficient.append(candidate)
    return efficient


def _maximum_hc_guidance(solution) -> dict[str, Any]:
    if solution.inequality_duals is None or solution.residuals is None:
        raise RuntimeError("Maximum-HC LP did not return KKT diagnostics")
    return {
        "duals": solution.inequality_duals,
        "residuals": solution.residuals,
        "row_ranges": solution.row_ranges,
        "source": "current maximum-HC LP KKT",
    }


def _thermal_candidates(
    data: dict[str, Any], state, guidance: dict[str, Any], catalog: dict[str, Any],
    selected: dict[tuple[str, str], dict[str, float]],
) -> list[dict[str, Any]]:
    t0, t1 = guidance["row_ranges"]["thermal"]
    n_hours = len(data["critical"]["hours"])
    n_rows = len(data["thermal"]["asset_id"])
    dual = guidance["duals"][t0:t1].reshape(n_hours, n_rows)
    original = data["thermal"]["original_rating"].astype(float)
    lengths = data["thermal"]["length_km"].astype(float)
    phases = data["thermal"]["asset_phase"].astype(str)
    candidates_by_asset: list[list[dict[str, Any]]] = []

    for group in _physical_asset_groups(data):
        rows = group["row_indices"]
        key = (group["asset_type"], group["asset_id"])
        prior = selected.get(key)
        current_rating = float(prior["rating"] if prior else np.max(original[rows]))
        previously_paid = float(prior["paid_catalog_cost"] if prior else 0.0)
        ratings, _ = _catalog_arrays(catalog, group["asset_type"])
        length_km = float(np.max(lengths[rows]))
        asset_candidates = []
        for new_rating in ratings[ratings > current_rating * (1.0 + 1.0e-10)]:
            incremental_cost, cumulative_cost = _incremental_cost(
                catalog, group["asset_type"], float(new_rating), length_km, previously_paid
            )
            delta_multiplier = float(new_rating) / original[rows] - state.thermal_rating_multipliers[rows]
            kkt_score = float(np.sum(dual[:, rows] * delta_multiplier.reshape(1, -1)))
            if kkt_score <= KKT_SCORE_TOL:
                continue
            asset_candidates.append({
                "kind": "thermal", "asset_id": group["asset_id"], "asset_type": group["asset_type"],
                "physical_row_indices": rows, "new_rating": float(new_rating),
                "rating_unit": str(data["thermal"]["rating_unit"][rows[0]]),
                "incremental_cost_usd": incremental_cost,
                "cumulative_catalog_cost_usd": cumulative_cost,
                "kkt_weighted_score": kkt_score,
                "screening_score": kkt_score / max(incremental_cost, 1.0),
                "affected_constraint_rows": int(n_hours * len(rows)),
                "affected_phases": sorted(set(phases[rows].tolist())),
                "guidance_source": guidance["source"],
            })
        efficient = _pareto_efficient(asset_candidates)
        if efficient:
            candidates_by_asset.append(efficient)

    # Screen physical assets after phase aggregation, then preserve every
    # Pareto-efficient rating option for each retained asset. This prevents a
    # large-rating option from crowding a cheaper option for the same asset out
    # of the realized-gain LP evaluation set.
    candidates_by_asset.sort(
        key=lambda items: max(item["screening_score"] for item in items), reverse=True
    )
    retained = [candidate for items in candidates_by_asset[:SCREEN_LIMIT] for candidate in items]
    retained.sort(key=lambda item: (item["screening_score"], item["kkt_weighted_score"]), reverse=True)
    return retained


def _voltage_candidates(data: dict[str, Any], state, guidance: dict[str, Any], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    v0, v1 = guidance["row_ranges"]["voltage"]
    n_hours = len(data["critical"]["hours"])
    n_outputs = len(data["outputs"]["name"])
    dual = guidance["duals"][v0:v1].reshape(n_hours, n_outputs)
    current_response = response_for_taps(data, state.regulator_taps)
    allowed = data["regulator"]["allowed_taps"].astype(int)
    anchors = data["regulator"]["tap_anchors"].astype(int)
    per_tap_cost = float(catalog["regulator_setting_cost_usd_per_tap"].reshape(-1)[0])
    candidates = []
    for location_index, location in enumerate(data["regulator"]["locations"].astype(str)):
        current = int(state.regulator_taps[location_index])
        for tap in allowed[allowed < current]:
            trial_taps = state.regulator_taps.copy()
            trial_taps[location_index] = int(tap)
            delta = response_for_taps(data, trial_taps) - current_response
            kkt_score = weighted_constraint_relief(dual, delta)
            if kkt_score <= KKT_SCORE_TOL:
                continue
            cost = abs(int(tap) - current) * per_tap_cost
            candidates.append({
                "kind": "regulator", "asset_id": str(location), "asset_type": "regulator",
                "location_index": location_index, "location": str(location), "new_tap": int(tap),
                "incremental_cost_usd": cost, "kkt_weighted_score": kkt_score,
                "screening_score": kkt_score / max(cost, 1.0),
                "response_source": str(data["regulator"]["response_source"].reshape(-1)[0]),
                "response_anchors": anchors.tolist(), "guidance_source": guidance["source"],
            })
    candidates.sort(key=lambda item: (item["screening_score"], item["kkt_weighted_score"]), reverse=True)
    return candidates[:SCREEN_LIMIT]


def _apply_candidate(data: dict[str, Any], state, candidate: dict[str, Any]):
    trial = state.copy()
    if candidate["kind"] == "thermal":
        rows = candidate["physical_row_indices"]
        originals = data["thermal"]["original_rating"].astype(float)[rows]
        trial.thermal_rating_multipliers[rows] = candidate["new_rating"] / originals
    else:
        trial.regulator_taps[candidate["location_index"]] = candidate["new_tap"]
    return trial


def _action_record(
    data: dict[str, Any], iteration: int, candidate: dict[str, Any], old_state, new_state,
    old_solution, new_solution, selected: dict[tuple[str, str], dict[str, float]],
) -> dict[str, Any]:
    common = {
        "iteration": int(iteration), "asset_id": str(candidate["asset_id"]),
        "asset_type": str(candidate["asset_type"]),
        "incremental_cost_usd": float(candidate["incremental_cost_usd"]),
        "kkt_weighted_score": float(candidate["kkt_weighted_score"]),
        "hc_before_mw": float(old_solution.hosting_capacity_mw),
        "hc_after_mw": float(new_solution.hosting_capacity_mw),
        "realized_hc_gain_mw": float(new_solution.hosting_capacity_mw - old_solution.hosting_capacity_mw),
        "binding_constraints_before": old_solution.binding_constraints,
        "guidance_source": str(candidate["guidance_source"]),
    }
    if candidate["kind"] == "thermal":
        key = (candidate["asset_type"], candidate["asset_id"])
        rows = candidate["physical_row_indices"]
        old_rating = float(selected[key]["rating"] if key in selected else np.max(data["thermal"]["original_rating"].astype(float)[rows]))
        return common | {
            "old_state": {"rating": old_rating, "unit": candidate["rating_unit"]},
            "new_state": {"rating": float(candidate["new_rating"]), "unit": candidate["rating_unit"]},
            "old_rating": old_rating, "new_rating": float(candidate["new_rating"]),
            "rating_unit": candidate["rating_unit"], "affected_phases": candidate["affected_phases"],
            "affected_constraint_rows": int(candidate["affected_constraint_rows"]),
            "reason": "physical-asset KKT screening; Pareto catalog action selected by realized HC gain per incremental cost after LP re-solve",
            "action_type": "catalog_replacement",
        }
    i = candidate["location_index"]
    old_tap, new_tap = int(old_state.regulator_taps[i]), int(new_state.regulator_taps[i])
    anchors = candidate["response_anchors"]
    return common | {
        "location": str(candidate["location"]), "regulator_location": str(candidate["location"]),
        "old_state": {"tap": old_tap}, "new_state": {"tap": new_tap},
        "old_tap": old_tap, "new_tap": new_tap,
        "selected_response_source": str(candidate["response_source"]),
        "response_anchor_information": {
            "anchors": anchors,
            "old_tap_mode": "exact_anchor" if old_tap in anchors else "linear_interpolation",
            "new_tap_mode": "exact_anchor" if new_tap in anchors else "linear_interpolation",
        },
        "reason": "maximum-HC KKT screening with frozen Iowa240 response; selected by realized HC gain per incremental cost after LP re-solve",
        "action_type": "regulator_tap_setting",
    }


def _thermal_target_actions(data, index, target, catalog):
    """Choose the smallest adequate catalog tier for every overloaded asset."""
    state = initial_network_state(data)
    baseline = data["thermal"]["baseline_frac"].astype(float)
    gamma = data["thermal"]["gamma_frac_per_mw"][index].astype(float)
    required_fraction = baseline + target * gamma
    original = data["thermal"]["original_rating"].astype(float)
    lengths = data["thermal"]["length_km"].astype(float)
    phases = data["thermal"]["asset_phase"].astype(str)
    choices = []
    for group in _physical_asset_groups(data):
        rows = group["row_indices"]
        required = float(np.max(required_fraction[:, rows] * original[rows][None, :]))
        current = float(np.max(original[rows]))
        if required <= current + 1e-7:
            continue
        ratings, _ = _catalog_arrays(catalog, group["asset_type"])
        eligible = ratings[(ratings > current + 1e-7) & (ratings >= required - 1e-7)]
        if not len(eligible):
            return None, [], (f"thermal catalog exhausted at {group['asset_id']}: "
                              f"required {required:.6g}, maximum {float(np.max(ratings)):.6g}")
        rating = float(np.min(eligible))
        cost, _ = _incremental_cost(catalog, group["asset_type"], rating,
                                    float(np.max(lengths[rows])), 0.0)
        choices.append({
            "kind": "thermal", "asset_id": str(group["asset_id"]),
            "asset_type": str(group["asset_type"]), "rows": rows,
            "old_rating": current, "new_rating": rating,
            "rating_unit": str(data["thermal"]["rating_unit"][rows[0]]),
            "affected_phases": sorted(str(phase) for phase in set(phases[rows].tolist())),
            "affected_constraint_rows": int(len(data["critical"]["hours"]) * len(rows)),
            "incremental_cost_usd": cost,
        })
        state.thermal_rating_multipliers[rows] = rating / original[rows]
    choices.sort(key=lambda action: (action["asset_type"], action["asset_id"]))
    if np.max(required_fraction - state.thermal_rating_multipliers[None, :]) > 1e-7:
        return None, [], "thermal target remains infeasible after catalog replacements"
    return state, choices, None


def _hourly_taps(margins, response, available, signed):
    """Exact integer minimum-tap schedule for one location and all frozen hours."""
    hours = len(margins)
    schedule = np.zeros((hours, 3), dtype=int)
    lower = -16 * np.asarray(available, dtype=int)
    upper = (16 if signed else 0) * np.asarray(available, dtype=int)
    a = np.zeros((response.shape[0] + 6, 6), dtype=float)
    a[:response.shape[0], :3] = response
    for phase in range(3):
        a[response.shape[0] + 2 * phase, phase] = 1
        a[response.shape[0] + 2 * phase, phase + 3] = -1
        a[response.shape[0] + 2 * phase + 1, phase] = -1
        a[response.shape[0] + 2 * phase + 1, phase + 3] = -1
    bounds = Bounds(np.r_[lower, np.zeros(3)], np.r_[upper, np.full(3, 16)])
    objective = np.r_[np.zeros(3), np.ones(3)]
    for hi, row in enumerate(margins):
        if np.max(row) <= 1e-8:
            continue
        best_possible = row + np.sum(np.minimum(response * lower, response * upper), axis=1)
        if np.max(best_possible) > 1e-8:
            return None
        lb = np.r_[np.full(len(row), -np.inf), np.full(6, -np.inf)]
        ub = np.r_[-row, np.zeros(6)]
        answer = milp(objective, integrality=np.array([1, 1, 1, 0, 0, 0]),
                      bounds=bounds, constraints=LinearConstraint(a, lb, ub),
                      options={"time_limit": 2.0, "mip_rel_gap": 0.0})
        if not answer.success or answer.x is None:
            return None
        tap = np.rint(answer.x[:3]).astype(int)
        if np.max(row + response @ tap) > 1e-6:
            return None
        schedule[hi] = tap
    return schedule


def _regulator_target_action(data, margins, catalog):
    """Find the least-tap feasible single line bank, then broaden tap search."""
    if "candidate" not in data:
        return None, "candidate response library missing"
    candidate = data["candidate"]
    names = candidate["locations"].astype(str)
    matrices = candidate["response_per_tap_margin_pu"].astype(float, copy=False)
    phases = candidate["available_phases"].astype(bool)
    best = None
    for signed in (False, True):
        for i, name in enumerate(names):
            schedule = _hourly_taps(margins, matrices[i], phases[i], signed)
            if schedule is None:
                continue
            effort = int(np.abs(schedule).sum())
            peak = int(np.max(np.abs(schedule), axis=0).sum())
            key = (effort, peak, name)
            if best is None or key < best[0]:
                best = (key, i, schedule, "signed_-16_to_16" if signed else "initial_-16_to_0")
        if best is not None:
            break
    if best is None:
        return None, f"no feasible one-bank location among {len(names)} frozen candidate lines after expanded signed-tap search"
    _, index, schedule, search_range = best
    fixed = float(catalog["regulator_install_cost_usd"].reshape(-1)[0])
    per_tap = float(catalog["regulator_setting_cost_usd_per_tap"].reshape(-1)[0])
    action = {
        "kind": "regulator", "asset_type": "regulator", "asset_id": str(names[index]),
        "location": str(names[index]), "location_index": int(index),
        "hourly_tap_schedule": schedule, "search_range": search_range,
        "candidate_location_count": len(names), "tap_effort": int(np.abs(schedule).sum()),
        "incremental_cost_usd": fixed + per_tap * int(np.max(np.abs(schedule), axis=0).sum()),
        "selected_response_source": str(candidate["response_source"].reshape(-1)[0]),
    }
    return action, None


def _plan_at_target(site_id, target, data, index, catalog):
    state, actions, failure = _thermal_target_actions(data, index, target, catalog)
    if failure is not None:
        return None, [], failure
    margins = target_voltage_margins(site_id, target, data)
    margins += response_for_taps(data, state.regulator_taps)
    if np.max(margins) > 1e-7:
        regulator, failure = _regulator_target_action(data, margins, catalog)
        if failure is not None:
            return None, [], failure
        state.candidate_location_index = regulator["location_index"]
        state.candidate_taps = regulator["hourly_tap_schedule"]
        actions.append(regulator)
    return state, actions, None


def _record_actions(site_id, data, baseline, choices):
    state = initial_network_state(data)
    current = baseline
    records = []
    original = data["thermal"]["original_rating"].astype(float)
    for iteration, action in enumerate(choices, 1):
        if action["kind"] == "thermal":
            rows = action["rows"]
            state.thermal_rating_multipliers[rows] = action["new_rating"] / original[rows]
        else:
            state.candidate_location_index = action["location_index"]
            state.candidate_taps = action["hourly_tap_schedule"]
        new = solve_hc_lp(site_id, data, state)
        if not new.success:
            raise RuntimeError(f"Upgrade LP failed after {action['asset_id']}: {new.message}")
        common = {
            "iteration": iteration, "asset_id": str(action["asset_id"]),
            "asset_type": str(action["asset_type"]),
            "incremental_cost_usd": float(action["incremental_cost_usd"]),
            "kkt_weighted_score": 0.0,
            "hc_before_mw": float(current.hosting_capacity_mw),
            "hc_after_mw": float(new.hosting_capacity_mw),
            "realized_hc_gain_mw": float(new.hosting_capacity_mw - current.hosting_capacity_mw),
            "binding_constraints_before": current.binding_constraints,
            "guidance_source": "frozen target-constraint sensitivity",
        }
        if action["kind"] == "thermal":
            record = common | {
                "old_rating": action["old_rating"], "new_rating": action["new_rating"],
                "rating_unit": action["rating_unit"],
                "old_state": {"rating": action["old_rating"], "unit": action["rating_unit"]},
                "new_state": {"rating": action["new_rating"], "unit": action["rating_unit"]},
                "affected_phases": action["affected_phases"],
                "affected_constraint_rows": action["affected_constraint_rows"],
                "reason": "thermal-first smallest adequate physical-asset catalog tier",
                "action_type": "catalog_replacement",
            }
        else:
            schedule = action["hourly_tap_schedule"]
            record = common | {
                "location": action["location"], "regulator_location": action["location"],
                "old_state": {"tap": 0},
                "new_state": {"tap": int(np.min(schedule))},
                "old_tap": 0, "new_tap": int(np.min(schedule)),
                "selected_response_source": action["selected_response_source"],
                "response_anchor_information": {
                    "anchors": [-1, 0], "old_tap_mode": "exact_anchor",
                    "new_tap_mode": "linear_interpolation",
                },
                "reason": "regulator-last, minimum total absolute taps among feasible frozen line candidates",
                "action_type": "regulator_tap_setting",
            }
        records.append(record)
        current = new
    return records, current


def plan_upgrade_impl(site_id: str, target_hc_mw: float, catalog_id: str) -> dict:
    if not np.isfinite(target_hc_mw) or float(target_hc_mw) <= 0.0:
        raise ValueError("target_hc_mw must be a finite positive absolute MW target")
    started = time.perf_counter()
    data = load_runtime_data()
    index = site_index(data, site_id)
    catalog = _catalog(data, catalog_id)
    state = initial_network_state(data)
    baseline = solve_hc_lp(site_id, data, state)
    if not baseline.success:
        raise RuntimeError(f"Baseline LP failed for {site_id}: {baseline.message}")
    if baseline.hosting_capacity_mw + HC_NUMERICAL_TOL_MW >= float(target_hc_mw):
        return {
            "site_id": str(data["sites"]["id"][index]), "baseline_hc_mw": baseline.hosting_capacity_mw,
            "target_hc_mw": float(target_hc_mw), "upgrade_required": False, "target_achieved": True,
            "post_upgrade_hc_mw": baseline.hosting_capacity_mw, "released_hc_mw": 0.0,
            "total_cost_usd": 0.0, "upgrades": [], "runtime_sec": time.perf_counter() - started,
            "success": True, "failure_reason": None,
        }

    requested = float(target_hc_mw)
    state, choices, failure = _plan_at_target(site_id, requested, data, index, catalog)
    verified_target = requested
    if failure is not None:
        original_failure = failure
        lower = float(baseline.hosting_capacity_mw)
        upper = requested
        best = (initial_network_state(data), [], lower)
        for factor in (0.75, 0.50, 0.25):
            trial = lower + factor * (requested - lower)
            trial_state, trial_choices, trial_failure = _plan_at_target(site_id, trial, data, index, catalog)
            if trial_failure is None:
                best = trial_state, trial_choices, trial
                lower = trial
                break
            upper = trial
        for _ in range(8):
            trial = 0.5 * (lower + upper)
            if upper - lower < 0.001:
                break
            trial_state, trial_choices, trial_failure = _plan_at_target(site_id, trial, data, index, catalog)
            if trial_failure is None:
                best = trial_state, trial_choices, trial
                lower = trial
            else:
                upper = trial
        state, choices, verified_target = best
        failure = f"requested target infeasible ({original_failure}); returned verified frozen-model HC fallback"
    actions, current = _record_actions(site_id, data, baseline, choices)
    if current.hosting_capacity_mw + 1e-6 < verified_target:
        raise RuntimeError("Frozen target feasibility disagrees with maximum-HC LP")
    achieved = bool(current.hosting_capacity_mw + 1e-6 >= requested)
    return {
        "site_id": str(data["sites"]["id"][index]), "baseline_hc_mw": baseline.hosting_capacity_mw,
        "target_hc_mw": float(target_hc_mw), "upgrade_required": True, "target_achieved": achieved,
        "post_upgrade_hc_mw": min(float(current.hosting_capacity_mw), requested) if not achieved else current.hosting_capacity_mw,
        "released_hc_mw": (min(float(current.hosting_capacity_mw), requested) if not achieved else current.hosting_capacity_mw) - baseline.hosting_capacity_mw,
        "total_cost_usd": float(sum(action["incremental_cost_usd"] for action in actions)),
        "upgrades": actions, "runtime_sec": time.perf_counter() - started,
        "success": achieved, "failure_reason": None if achieved else failure,
    }
