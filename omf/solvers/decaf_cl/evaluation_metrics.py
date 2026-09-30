#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Evaluation Metric Calculation
voltage evaluation metrics and thermal evaluation metrics are all included.
Author: Liming Liu @ ISU
Created: 2026-1-12
Ack: refined by Chatgpt
"""

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture
from scipy.stats import norm
from scipy.optimize import brentq


def gmm_voltage_statistics_model(
    voltage_matrix,
    n_components=2,
    v_threshold=1.05,
    alpha=20.0
):
    """
    Gaussian Mixture Model per node → voltage risk statistics + fit-quality indicators.

    This revised version is more robust for:
    - NaN values
    - constant voltage columns
    - very small variance columns
    - brentq quantile failure
    """

    voltage_matrix = np.asarray(voltage_matrix, dtype=float)
    T, N = voltage_matrix.shape

    p5 = np.full(N, np.nan)
    p95 = np.full(N, np.nan)
    prob_exceed = np.full(N, np.nan)
    avg_overvoltage = np.full(N, np.nan)
    ks_stat = np.full(N, np.nan)
    credibility = np.full(N, np.nan)

    def safe_gmm_quantile(mixture_cdf, q, v):
        """
        Safely calculate GMM-based quantile.
        If brentq fails, fall back to empirical percentile.
        """
        v = np.asarray(v, dtype=float)
        v = v[np.isfinite(v)]

        if len(v) == 0:
            return np.nan

        if np.std(v) < 1e-10:
            return float(v[0])

        v_std = np.std(v)

        # Use wider range than [min, max]
        v_min = np.min(v) - 10 * v_std
        v_max = np.max(v) + 10 * v_std

        try:
            return brentq(lambda z: mixture_cdf(z) - q, v_min, v_max)
        except ValueError:
            return np.percentile(v, q * 100)

    for i in range(N):

        # -----------------------------
        # Clean one bus voltage series
        # -----------------------------
        v = voltage_matrix[:, i].astype(float)
        v = v[np.isfinite(v)]

        if len(v) < 3:
            continue

        # -----------------------------
        # Constant or near-constant column
        # -----------------------------
        if np.std(v) < 1e-10:
            v0 = float(v[0])

            p5[i] = v0
            p95[i] = v0
            prob_exceed[i] = float(v0 > v_threshold)
            avg_overvoltage[i] = max(v0 - v_threshold, 0.0)
            ks_stat[i] = 0.0
            credibility[i] = 1.0
            continue

        x = v.reshape(-1, 1)

        # -----------------------------
        # Fit GMM
        # -----------------------------
        try:
            gmm = GaussianMixture(
                n_components=min(n_components, len(v)),
                covariance_type="full",
                random_state=0,
                reg_covar=1e-8
            )
            gmm.fit(x)
        except Exception:
            # Fallback to empirical statistics if GMM fails
            p5[i] = np.percentile(v, 5)
            p95[i] = np.percentile(v, 95)
            prob_exceed[i] = np.mean(v > v_threshold)
            avg_overvoltage[i] = np.mean(np.maximum(v - v_threshold, 0.0))
            ks_stat[i] = np.nan
            credibility[i] = np.nan
            continue

        weights = gmm.weights_
        means = gmm.means_.flatten()
        stds = np.sqrt(gmm.covariances_.flatten())
        stds = np.maximum(stds, 1e-8)

        # -----------------------------
        # Mixture CDF
        # -----------------------------
        def mixture_cdf(val):
            return np.sum(weights * norm.cdf(val, means, stds))

        # -----------------------------
        # Quantiles
        # -----------------------------
        p5[i] = safe_gmm_quantile(mixture_cdf, 0.05, v)
        p95[i] = safe_gmm_quantile(mixture_cdf, 0.95, v)

        # -----------------------------
        # Exceedance probability
        # -----------------------------
        prob_exceed[i] = 1.0 - mixture_cdf(v_threshold)

        # Avoid tiny numerical negative/above-one values
        prob_exceed[i] = np.clip(prob_exceed[i], 0.0, 1.0)

        # -----------------------------
        # Average overvoltage
        # -----------------------------
        ov = 0.0

        for w, mu, sigma in zip(weights, means, stds):
            a = (v_threshold - mu) / sigma
            ov += w * (
                sigma * norm.pdf(a)
                + (mu - v_threshold) * (1.0 - norm.cdf(a))
            )

        avg_overvoltage[i] = max(ov, 0.0)

        # -----------------------------
        # Fit-quality indicators
        # -----------------------------
        v_sorted = np.sort(v)
        T_valid = len(v_sorted)
        ecdf = np.arange(1, T_valid + 1) / T_valid

        gmm_cdf_vals = np.array([mixture_cdf(val) for val in v_sorted])
        ks = np.max(np.abs(ecdf - gmm_cdf_vals))

        ks_stat[i] = ks
        credibility[i] = np.exp(-alpha * ks)

    return {
        "p5": p5,
        "p95": p95,
        "prob_exceed": prob_exceed,
        "avg_overvoltage": avg_overvoltage,
        "ks_stat": ks_stat,
        "credibility": credibility
    }

def empirical_voltage_statistics_model(
    voltage_matrix,
    v_threshold=1.05
):
    """
    Empirical (data-driven) voltage statistics per node.

    Parameters
    ----------
    voltage_matrix : ndarray (T, N)
        Voltage time series. Each column is one node; each row is one hour (or one time step).
    v_threshold : float
        Voltage threshold used to compute exceedance metrics (e.g., 1.05 p.u.).

    Returns
    -------
    results : dict
        p5 : ndarray (N,)
            Empirical 5th percentile voltage for each node.
        p95 : ndarray (N,)
            Empirical 95th percentile voltage for each node.
        prob_exceed : ndarray (N,)
            Fraction of hours where voltage > v_threshold for each node (i.e., exceedance probability).
        exceed_hours : ndarray (N,)
            Number of hours where voltage > v_threshold for each node.
        avg_overvoltage : ndarray (N,)
            Average overvoltage amount above the threshold for exceed hours:
            mean(max(V - v_threshold, 0)).
            (This is averaged over all hours, so it reflects both frequency and severity.)
    """

    p5 = np.percentile(voltage_matrix, 5, axis=0)
    p95 = np.percentile(voltage_matrix, 95, axis=0)

    exceed_mask = voltage_matrix > v_threshold
    exceed_hours = np.sum(exceed_mask, axis=0)
    prob_exceed = np.mean(exceed_mask, axis=0)

    # Overvoltage magnitude above threshold (0 if not exceeding)
    overvoltage = np.maximum(voltage_matrix - v_threshold, 0.0)
    avg_overvoltage = np.mean(overvoltage, axis=0)

    return {
        "p5": p5,
        "p95": p95,
        "prob_exceed": prob_exceed,
        "exceed_hours": exceed_hours,
        "avg_overvoltage": avg_overvoltage
    }

def voltage_evaluation_metric(
    voltage_matrix,
    v_threshold=1.05
):
    """
    Parameters
    ----------
    voltage_matrix : ndarray (T, N)
        Voltage time series, each column is one node
    v_threshold : float
        Voltage threshold for probability calculation

    Returns
    -------
    results : dict
        keys: 'p5_emp', 'p95_emp', 'prob_exceed_emp', 'p5_gmm', 'p95_gmm', 'prob_exceed_gmm
        each value is an array of length N (per node)
    """
    res_gmm = gmm_voltage_statistics_model(voltage_matrix, v_threshold=v_threshold)
    res_emp = empirical_voltage_statistics_model(voltage_matrix, v_threshold=v_threshold)
    return {
        "p5_emp": res_emp["p5"],
        "p95_emp": res_emp["p95"],
        "prob_exceed_emp": res_emp["prob_exceed"],
        "avg_overvoltage_emp": res_emp["avg_overvoltage"],
        "exceed_hours_emp": res_emp["exceed_hours"],
        "p5_gmm": res_gmm["p5"],
        "p95_gmm": res_gmm["p95"],
        "prob_exceed_gmm": res_gmm["prob_exceed"],
        "avg_overvoltage_gmm": res_gmm["avg_overvoltage"],
        "credibility": res_gmm["credibility"]
    }


def _load_columns(csv_path):
    return list(pd.read_csv(csv_path, nrows=0).columns)


def _service_transformer_columns(columns):
    return [col for col in columns if str(col).startswith("t_")]


def _ami_customer_to_load_id(customer_name):
    """
    Convert db AMI customer names such as t_bus1003_l to load_1003.
    """
    name = str(customer_name).strip().lower()
    if name.startswith("load_"):
        return name
    if name.startswith("t_bus") and name.endswith("_l"):
        bus_no = name[len("t_bus"):-len("_l")]
        return f"load_{bus_no}"
    if name.startswith("bus"):
        bus_no = name[len("bus"):].split("_")[0]
        return f"load_{bus_no}"
    return None


def _normalize_load_id(name):
    name = str(name).strip().lower()
    if name.startswith("load_"):
        return name
    if name.startswith("t_bus") and name.endswith("_l"):
        return _ami_customer_to_load_id(name)
    if name.startswith("bus"):
        return _ami_customer_to_load_id(name)
    if name.isdigit():
        return f"load_{name}"
    return name


def _align_series_to_timestep(values, timesteps, allow_positional=False):
    """
    Align a time series to the AMI timestamp window.

    If timestamp information is present in the Series index, timestamp-based
    reindexing is always used. Positional alignment is allowed only for inputs
    with no timestamp index and only when allow_positional=True.
    """
    series = pd.Series(values)
    timestep_index = pd.Index([str(t) for t in timesteps])

    has_timestamp_index = not isinstance(series.index, pd.RangeIndex)
    if has_timestamp_index:
        indexed = pd.to_numeric(series, errors="coerce").fillna(0.0)
        indexed.index = indexed.index.astype(str)
        if indexed.index.has_duplicates:
            indexed = indexed.groupby(level=0).sum()
        missing = timestep_index.difference(indexed.index)
        if len(missing) > 0:
            raise ValueError(f"PV profile is missing AMI timesteps, for example: {list(missing[:5])}")
        return indexed.reindex(timestep_index).to_numpy(dtype=float)

    if allow_positional and len(series) == len(timesteps):
        return pd.to_numeric(series, errors="coerce").fillna(0.0).to_numpy(dtype=float)

    raise ValueError(
        "PV profile has no timestamp index. Add a timestep column, or explicitly allow positional alignment."
    )


def load_pv_profile(pv_profile):
    """
    Load a PV profile from a DataFrame or CSV path.

    Supported CSV shapes:
    1. Wide load columns:
       timestep, load_2043, load_2052
    2. Wide explicit P/Q columns:
       timestep, PVkW__load_2043, PVkVAR__load_2043
    3. Long rows:
       timestep, load_id, pv_kw, pv_kvar
    """
    if pv_profile is None:
        return None
    if isinstance(pv_profile, pd.DataFrame):
        return pv_profile.copy()
    return pd.read_csv(pv_profile)


def _load_pv_mapping(pv_mapping):
    if pv_mapping is None:
        return None
    if isinstance(pv_mapping, pd.DataFrame):
        mapping = pv_mapping.copy()
    else:
        mapping = pd.read_csv(pv_mapping)
    if "pv_id" not in mapping.columns or "load_id" not in mapping.columns:
        raise ValueError("PV mapping must include pv_id and load_id columns.")
    mapping["pv_id"] = mapping["pv_id"].astype(str)
    mapping["load_id"] = mapping["load_id"].map(_normalize_load_id)
    return dict(zip(mapping["pv_id"], mapping["load_id"]))


def _apply_pv_profile_to_net_pq(
    net_pq,
    pv_profile=None,
    pv_mapping=None,
    allow_positional_pv_alignment=False,
    return_diagnostics=False,
):
    if pv_profile is None:
        diagnostics = {"pv_targets_applied": 0, "unmatched_pv_targets": []}
        return (net_pq, diagnostics) if return_diagnostics else net_pq

    profile = load_pv_profile(pv_profile)
    if profile is None or profile.empty:
        diagnostics = {"pv_targets_applied": 0, "unmatched_pv_targets": []}
        return (net_pq, diagnostics) if return_diagnostics else net_pq

    out = net_pq.copy()
    timesteps = out["timestep"].to_numpy()
    mapping = _load_pv_mapping(pv_mapping) or {}
    unmatched_loads = []
    applied_loads = set()

    def subtract_from_load(load_id, pv_kw, pv_kvar=None):
        load_id = _normalize_load_id(mapping.get(str(load_id), load_id))
        p_col = f"Pnet__{load_id}"
        q_col = f"Qnet__{load_id}"
        if p_col not in out.columns:
            unmatched_loads.append(load_id)
            return
        out[p_col] = pd.to_numeric(out[p_col], errors="coerce").fillna(0.0).to_numpy(dtype=float) - pv_kw
        if pv_kvar is not None and q_col in out.columns:
            out[q_col] = pd.to_numeric(out[q_col], errors="coerce").fillna(0.0).to_numpy(dtype=float) - pv_kvar
        applied_loads.add(load_id)

    if {"load_id", "pv_kw"}.issubset(profile.columns):
        for load_id, group in profile.groupby("load_id"):
            group = group.copy()
            if "timestep" in group.columns:
                group = group.set_index("timestep")
            pv_kw = _align_series_to_timestep(
                pd.to_numeric(group["pv_kw"], errors="coerce").fillna(0.0),
                timesteps,
                allow_positional=allow_positional_pv_alignment,
            )
            pv_kvar = None
            if "pv_kvar" in group.columns:
                pv_kvar = _align_series_to_timestep(
                    pd.to_numeric(group["pv_kvar"], errors="coerce").fillna(0.0),
                    timesteps,
                    allow_positional=allow_positional_pv_alignment,
                )
            subtract_from_load(load_id, pv_kw, pv_kvar)
        if unmatched_loads:
            raise ValueError(f"PV targets do not match AMI load columns: {sorted(set(unmatched_loads))[:10]}")
        diagnostics = {
            "pv_targets_applied": len(applied_loads),
            "unmatched_pv_targets": sorted(set(unmatched_loads)),
        }
        return (out, diagnostics) if return_diagnostics else out

    wide = profile.copy()
    if "timestep" in wide.columns:
        wide = wide.set_index("timestep")

    for col in wide.columns:
        col_str = str(col)
        if col_str.startswith("PVkW__"):
            load_id = col_str.replace("PVkW__", "", 1)
            q_col = f"PVkVAR__{load_id}"
            pv_kw = _align_series_to_timestep(
                pd.to_numeric(wide[col], errors="coerce").fillna(0.0),
                timesteps,
                allow_positional=allow_positional_pv_alignment,
            )
            pv_kvar = None
            if q_col in wide.columns:
                pv_kvar = _align_series_to_timestep(
                    pd.to_numeric(wide[q_col], errors="coerce").fillna(0.0),
                    timesteps,
                    allow_positional=allow_positional_pv_alignment,
                )
            subtract_from_load(load_id, pv_kw, pv_kvar)
        elif col_str.startswith("PVkVAR__"):
            continue
        else:
            pv_kw = _align_series_to_timestep(
                pd.to_numeric(wide[col], errors="coerce").fillna(0.0),
                timesteps,
                allow_positional=allow_positional_pv_alignment,
            )
            subtract_from_load(col_str, pv_kw, None)

    if unmatched_loads:
        raise ValueError(f"PV targets do not match AMI load columns: {sorted(set(unmatched_loads))[:10]}")

    diagnostics = {
        "pv_targets_applied": len(applied_loads),
        "unmatched_pv_targets": sorted(set(unmatched_loads)),
    }
    return (out, diagnostics) if return_diagnostics else out


def build_fixed_pv_injection_profile(timesteps, pv_specs):
    """
    Build a constant PV injection profile from fixed kW/kVAR specs.

    pv_specs columns: load_id, pv_kw, optional pv_kvar.
    This represents constant injection at every evaluated timestamp, not PV
    nameplate capacity or a time-varying production profile.
    """
    if pv_specs is None:
        return None
    specs = pv_specs.copy() if isinstance(pv_specs, pd.DataFrame) else pd.read_csv(pv_specs)
    if "load_id" not in specs.columns or "pv_kw" not in specs.columns:
        raise ValueError("Fixed PV specs must include load_id and pv_kw columns.")

    rows = []
    for timestep in timesteps:
        for row in specs.itertuples(index=False):
            item = {
                "timestep": timestep,
                "load_id": _normalize_load_id(row.load_id),
                "pv_kw": float(row.pv_kw),
            }
            if hasattr(row, "pv_kvar"):
                item["pv_kvar"] = float(row.pv_kvar)
            rows.append(item)
    return pd.DataFrame(rows)


def build_fixed_pv_profile(timesteps, pv_specs):
    """
    Backward-compatible alias for build_fixed_pv_injection_profile().
    """
    return build_fixed_pv_injection_profile(timesteps, pv_specs)


def ami_to_net_pq_timeseries(
    kw_df,
    kvar_df,
    pv_profile=None,
    pv_mapping=None,
    allow_positional_pv_alignment=False,
    return_diagnostics=False,
):
    """
    Convert AMI data read from decaf_db.get_ami into the SM-PQ format used by
    the Iowa240 thermal aggregation workflow.

    Input columns are AMI customer names, for example t_bus1003_l.
    Output columns are Pnet__/Qnet__ load columns, for example
    Pnet__load_1003 and Qnet__load_1003.
    """
    if kw_df is None or kvar_df is None:
        raise ValueError("Both kW and kVAR AMI dataframes are required.")

    kw_df = pd.DataFrame(kw_df).copy()
    kvar_df = pd.DataFrame(kvar_df).copy()
    if not kw_df.index.equals(kvar_df.index):
        common_index = kw_df.index.intersection(kvar_df.index)
        kw_df = kw_df.loc[common_index].sort_index()
        kvar_df = kvar_df.loc[common_index].sort_index()
    if not kw_df.index.equals(kvar_df.index):
        raise ValueError("AMI kW and kVAR timestamps could not be aligned.")

    common_customers = [col for col in kw_df.columns if col in set(kvar_df.columns)]
    if not common_customers:
        raise ValueError("No common AMI customers found between kW and kVAR data.")

    p_by_load = {}
    q_by_load = {}
    duplicate_load_ids = set()

    for customer in common_customers:
        load_id = _ami_customer_to_load_id(customer)
        if load_id is None:
            continue

        p_values = pd.to_numeric(kw_df[customer], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        q_values = pd.to_numeric(kvar_df[customer], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        if load_id in p_by_load:
            duplicate_load_ids.add(load_id)
            p_by_load[load_id] = p_by_load[load_id] + p_values
            q_by_load[load_id] = q_by_load[load_id] + q_values
        else:
            p_by_load[load_id] = p_values
            q_by_load[load_id] = q_values

    if len(p_by_load) == 0:
        raise ValueError("AMI customer names could not be mapped to load ids.")

    data = {"timestep": kw_df.index.to_numpy()}
    for load_id in sorted(p_by_load):
        data[f"Pnet__{load_id}"] = p_by_load[load_id]
        data[f"Qnet__{load_id}"] = q_by_load[load_id]

    net_pq = pd.DataFrame(data)
    net_pq, pv_diagnostics = _apply_pv_profile_to_net_pq(
        net_pq,
        pv_profile=pv_profile,
        pv_mapping=pv_mapping,
        allow_positional_pv_alignment=allow_positional_pv_alignment,
        return_diagnostics=True,
    )
    diagnostics = {
        "ami_customers_used": len(common_customers),
        "loads_mapped": len(p_by_load),
        "duplicate_load_ids_aggregated": sorted(duplicate_load_ids),
        **pv_diagnostics,
    }
    return (net_pq, diagnostics) if return_diagnostics else net_pq


def estimate_thermal_from_smpq(dataset_dir, return_diagnostics=False):
    """
    Estimate service-transformer loading from SM-PQ data.

    dataset_dir must contain:
    - net_pq_timeseries.csv
    - load_to_transformer_phase_map.csv
    - transformer_ratings.csv
    - transformer_loading_pct.csv
    """
    from pathlib import Path

    dataset_dir = Path(dataset_dir)
    net_path = dataset_dir / "net_pq_timeseries.csv"
    map_path = dataset_dir / "load_to_transformer_phase_map.csv"
    ratings_path = dataset_dir / "transformer_ratings.csv"
    loading_template_path = dataset_dir / "transformer_loading_pct.csv"

    for path in [net_path, map_path, ratings_path, loading_template_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing thermal input file: {path}")

    map_df = pd.read_csv(map_path)
    ratings = pd.read_csv(ratings_path)
    required_map_cols = {"load_id", "transformer_id", "phase"}
    required_rating_cols = {"transformer_id", "kva", "phases"}
    if not required_map_cols.issubset(map_df.columns):
        raise ValueError(f"Thermal map file is missing columns: {sorted(required_map_cols - set(map_df.columns))}")
    if not required_rating_cols.issubset(ratings.columns):
        raise ValueError(f"Transformer ratings file is missing columns: {sorted(required_rating_cols - set(ratings.columns))}")

    net_cols = _load_columns(net_path)
    load_ids = [col.replace("Pnet__", "", 1) for col in net_cols if col.startswith("Pnet__")]
    p_cols = [f"Pnet__{load_id}" for load_id in load_ids]
    q_cols = [f"Qnet__{load_id}" for load_id in load_ids]

    missing_q = [col for col in q_cols if col not in net_cols]
    if missing_q:
        raise ValueError(f"Missing Qnet columns for thermal input: {missing_q[:5]}")

    net = pd.read_csv(net_path, usecols=["timestep", *p_cols, *q_cols])

    xfmr_names = _service_transformer_columns(_load_columns(loading_template_path))
    if not xfmr_names:
        raise ValueError("No service transformer columns found in transformer_loading_pct.csv.")

    template_xfmrs = set(xfmr_names)
    rating_xfmrs = set(ratings["transformer_id"].astype(str))
    map_xfmrs = set(map_df["transformer_id"].astype(str))
    missing_ratings = sorted(template_xfmrs - rating_xfmrs)
    unmapped_xfmrs = sorted(template_xfmrs - map_xfmrs)
    extra_map_xfmrs = sorted(map_xfmrs - template_xfmrs)
    if missing_ratings:
        raise ValueError(f"Missing transformer ratings for service transformers: {missing_ratings[:10]}")

    mapped_loads = set(map_df["load_id"].astype(str))
    missing_loads_in_net = sorted(mapped_loads - set(load_ids))
    net_loads_not_mapped = sorted(set(load_ids) - mapped_loads)

    xfmr_index = {xfmr: i for i, xfmr in enumerate(xfmr_names)}
    load_index = {load_id: i for i, load_id in enumerate(load_ids)}

    ratings = ratings.set_index("transformer_id")
    kva = ratings.reindex(xfmr_names)["kva"].astype(float)
    phases = ratings.reindex(xfmr_names)["phases"].astype(float)
    kva_bucket = (kva / phases.clip(lower=1.0)).to_numpy(dtype=float)

    p = net[p_cols].to_numpy(dtype=float)
    q = net[q_cols].to_numpy(dtype=float)
    n_samples = len(net)
    pph = np.zeros((n_samples, len(xfmr_names), 3), dtype=float)
    qph = np.zeros_like(pph)

    map_df = map_df[map_df["load_id"].isin(load_ids)].copy()
    for row in map_df.itertuples(index=False):
        xfmr = str(row.transformer_id)
        load_id = str(row.load_id)
        if xfmr not in xfmr_index or load_id not in load_index:
            continue

        xi = xfmr_index[xfmr]
        li = load_index[load_id]
        xfmr_phases = int(float(ratings.at[xfmr, "phases"])) if xfmr in ratings.index else 1

        if xfmr_phases <= 1:
            buckets = [0]
        else:
            phase_tokens = [tok for tok in str(row.phase).split(".") if tok in {"1", "2", "3"}]
            buckets = [int(tok) - 1 for tok in phase_tokens] or [0, 1, 2]

        share = 1.0 / len(buckets)
        for bucket in buckets:
            pph[:, xi, bucket] += p[:, li] * share
            qph[:, xi, bucket] += q[:, li] * share

    smax = np.sqrt(pph**2 + qph**2).max(axis=2)
    loading = 100.0 * smax / kva_bucket[None, :]
    out = pd.DataFrame(loading, columns=xfmr_names)
    out.insert(0, "timestep", net["timestep"].to_numpy())
    diagnostics = {
        "service_transformers_evaluated": len(xfmr_names),
        "unmapped_transformers": unmapped_xfmrs,
        "extra_map_transformers": extra_map_xfmrs,
        "map_loads_missing_from_net_pq": missing_loads_in_net,
        "net_pq_loads_not_in_map": net_loads_not_mapped,
        "thermal_timestamp_count": int(n_samples),
    }
    return (out, diagnostics) if return_diagnostics else out


def apply_delta_line_line_adjustment(dataset_dir, loading_df):
    """
    Adjust two-phase delta line-line service transformers by 2/sqrt(3).
    """
    from pathlib import Path

    dataset_dir = Path(dataset_dir)
    ratings = pd.read_csv(dataset_dir / "transformer_ratings.csv")
    adjusted = loading_df.copy()
    delta_like = ratings[
        (ratings["transformer_id"].astype(str).str.startswith("t_"))
        & (pd.to_numeric(ratings["phases"], errors="coerce") == 2)
        & (~ratings["buses"].astype(str).str.contains(".0", regex=False))
    ]["transformer_id"].astype(str).tolist()

    factor = 2.0 / np.sqrt(3.0)
    for col in delta_like:
        if col in adjusted.columns:
            adjusted[col] = pd.to_numeric(adjusted[col], errors="coerce").fillna(0.0) * factor

    return adjusted, delta_like


def thermal_evaluation_metric(
    loading_pct_df,
    threshold_pct=100.0,
):
    """
    Calculate service-transformer loading summary and threshold risk metrics.

    Each column is one transformer and each row is one timestamp.
    """
    if loading_pct_df is None or len(loading_pct_df) == 0:
        return pd.DataFrame()

    df = pd.DataFrame(loading_pct_df).copy()
    df = df.drop(columns=["timestep"], errors="ignore")
    df = df.apply(pd.to_numeric, errors="coerce")
    df = df.dropna(axis=1, how="all")
    if df.empty:
        return pd.DataFrame()

    over_limit = df > threshold_pct
    violation = (df - threshold_pct).clip(lower=0.0)
    metrics_df = pd.DataFrame({
        "mean_loading_pct": df.mean(axis=0),
        "p50_loading_pct": df.quantile(0.50, axis=0),
        "p95_loading_pct": df.quantile(0.95, axis=0),
        "p99_loading_pct": df.quantile(0.99, axis=0),
        "max_loading_pct": df.max(axis=0),
        "min_loading_pct": df.min(axis=0),
        "std_loading_pct": df.std(axis=0),
        "n_samples": int(df.shape[0]),
        "hours_over_limit": over_limit.sum(axis=0),
        "prob_over_limit": over_limit.mean(axis=0),
        "avg_violation_pct": violation.mean(axis=0),
        "max_violation_pct": violation.max(axis=0),
        "p95_violation_pct": violation.quantile(0.95, axis=0),
    })
    metrics_df.index.name = "device"

    return metrics_df


def thermal_loading_from_ami_db(
    db_fp,
    reference_dir,
    output_dir=None,
    timestamps=None,
    apply_delta_adjustment=True,
    pv_profile=None,
    pv_mapping=None,
    fixed_pv_specs=None,
    fixed_pv_injection_specs=None,
    allow_positional_pv_alignment=False,
):
    """
    Read AMI kW/kVAR from the decaf SQLite db, optionally subtract PV, build
    SM-PQ input, and estimate service-transformer loading.
    """
    from pathlib import Path
    from . import decaf_db as ddb

    reference_dir = Path(reference_dir)
    output_dir = Path(output_dir) if output_dir is not None else reference_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    ami = ddb.get_ami(db_fp, ami_dict={"unit": ["kW", "kVAR"]})
    if "kW" not in ami or "kVAR" not in ami:
        raise ValueError("AMI db query must return kW and kVAR data.")

    kw_df = ami["kW"]
    kvar_df = ami["kVAR"]
    if timestamps is not None:
        timestamp_index = pd.Index(timestamps)
        kw_df = kw_df.reindex(timestamp_index)
        kvar_df = kvar_df.reindex(timestamp_index)
        if kw_df.isna().any().any() or kvar_df.isna().any().any():
            raise ValueError("Thermal AMI kW/kVAR data are missing one or more requested timestamps.")

    fixed_specs = fixed_pv_injection_specs if fixed_pv_injection_specs is not None else fixed_pv_specs
    if fixed_specs is not None:
        pv_profile = build_fixed_pv_injection_profile(kw_df.index.to_numpy(), fixed_specs)

    net_pq, ami_diagnostics = ami_to_net_pq_timeseries(
        kw_df,
        kvar_df,
        pv_profile=pv_profile,
        pv_mapping=pv_mapping,
        allow_positional_pv_alignment=allow_positional_pv_alignment,
        return_diagnostics=True,
    )

    work_dir = output_dir / "thermal_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    net_pq.to_csv(work_dir / "net_pq_timeseries.csv", index=False)

    for name in [
        "load_to_transformer_phase_map.csv",
        "transformer_ratings.csv",
        "transformer_loading_pct.csv",
    ]:
        src = reference_dir / name
        dst = work_dir / name
        if not src.exists():
            raise FileNotFoundError(f"Missing thermal reference file: {src}")
        dst.write_bytes(src.read_bytes())

    loading, reference_diagnostics = estimate_thermal_from_smpq(work_dir, return_diagnostics=True)
    delta_adjusted_transformers = []
    if apply_delta_adjustment:
        loading, delta_adjusted_transformers = apply_delta_line_line_adjustment(work_dir, loading)

    loading.to_csv(output_dir / "thermal_transformer_loading_pct.csv", index=False)
    diagnostics = {
        **ami_diagnostics,
        **reference_diagnostics,
        "delta_adjusted_transformers": delta_adjusted_transformers,
        "number_of_delta_adjusted_transformers": len(delta_adjusted_transformers),
        "thermal_timestamp_count": int(len(loading)),
    }
    pd.DataFrame(
        [{"item": key, "value": value if not isinstance(value, list) else ";".join(map(str, value))}
         for key, value in diagnostics.items()]
    ).to_csv(output_dir / "thermal_diagnostics.csv", index=False)

    return {
        "loading_pct": loading,
        "net_pq_timeseries": net_pq,
        "delta_adjusted_transformers": delta_adjusted_transformers,
        "diagnostics": diagnostics,
        "work_dir": work_dir,
    }
