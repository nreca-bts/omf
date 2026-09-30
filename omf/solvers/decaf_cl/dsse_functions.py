#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WLS-DSSE (Weighted Least Squares — Distribution System State Estimation)

This module provides functions to estimate bus voltage magnitudes (V) and angles (theta) for a
three-phase distribution network using a weighted least-squares formulation.

Supported measurement types
---------------------------
1. Voltage magnitude measurements      (type = 1)
2. Real power injections at buses      (type = 2)
3. Reactive power injections at buses  (type = 3)
4. Real power flow on branches         (type = 4)
5. Reactive power flow on branches     (type = 5)

Units
-----
- Voltage: volts (phase-to-neutral)
- Power: watts / vars
- Angle: radians

Notes
-----
- The first 3 buses are treated as the reference/slack phases and are not part
  of the solved state vector.
- The solved state vector is:
      x = [theta_4 ... theta_n, V_4 ... V_n]^T
- This version mainly focuses on code quality, consistency, input checking,
  and clearer structure while preserving the original modeling logic.




System adaptation summary (what to change for a new system)
-------------------------
To apply this DSSE code to a new testing system, the following information
must be checked and updated:

1. Network model (Y-matrix file)
   - Replace the Y-bus file with the one for the new system.
   - Make sure the bus order in the Y-bus matches the order used in the
     voltage/load template files.
   - When generate the Y-matrix from OpenDSS, need to ensure all the shunt elements (e.g., capacitors) and loads are disabled or removed.
   
2. Voltage template
   - Replace the voltage template file. The template used here can be generated from OpenDSS.
   - Required fields include at least:
       Bus_Node, VLN_kV, Base_kV, pu, Angle
   - These data are used for:
       (a) initial voltage magnitude, Base_kV can be used as initial voltage values,
       (b) initial angle can be obtained from any OpenDSS powerflow result,
       (c) voltage base values can be ontained from model

3. Load template
   - Replace the load template file.
   - Required fields include at least:
       Bus_Node, kW, kVar
   - These data are used to build P/Q injection measurements.

5. Removed nodes / feeder-head treatment
   - Update remove_indices_1based for the new system.
   - These indices define which nodes are removed from the original network. Feeder head nodes are usually kept as references here. 
   - Nodes beyond the feeder head (e.g., substation-side nodes) should be removed.


6. Measurement sources
   - If AMI data are used, update the database path, snapshot time, and bus
     mapping.
   - If capacitor bank measurements are used, update the capacitor stream names.
   - If recloser / breaker flow measurements are used, update:
       cleaned_scada_name,
       cleaned_scada_from_name,
       cleaned_scada_to_name
   - These settings define how line flow measurements are constructed.

7. Lineflow measurement table
   - If branch flow measurements are used, the generated lineflow table must
     follow the current format:
       Element, P_1, P_2, P_3, Q_1, Q_2, Q_3,
       Bus11, Bus12, Bus13, Bus21, Bus22, Bus23

8. System size
   - Check the bus count after node removal.
   - The final DSSE bus number must match the trimmed voltage/load/Y-bus data.

In short, moving this code to a new system mainly requires updating:
Y-bus, voltage template, load template, removed bus indices, bus-name mapping,
AMI/SCADA source definitions, and lineflow measurement configuration.

Snapshot to Time Series
-------------------------
The current code processes a single snapshot. 
To extend it to time series, master file may be created to loop through multiple timestamps.
"snapshot_time = 1483257600"

Author: Liming Liu @ ISU
Created: 2025-12-17
Refactored: 2026-03-08
"""

# ==============================
# Imports
# ==============================
import time
import re
import warnings
from typing import List, Sequence, Tuple, Dict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from pathlib import Path

warnings.filterwarnings("ignore")


# ==============================
# Helpers: Index clean
# ==============================

def update_indices(remove_list, target_indices):
    """
    Update bus indices after removing some nodes.

    Parameters
    ----------
    remove_list : list
        Removed bus indices, using 1-based indexing.
    target_indices : list
        Original target indices, also using 1-based indexing.

    Returns
    -------
    updated : list
        New indices after removing the buses in remove_list.

    Notes
    -----
    Example:
        if remove_list = [1, 2, 5], then original bus 6 becomes new bus 3.
    """
    remove_list = sorted(remove_list)
    updated = []
    for t in target_indices:
        shift = sum(r < t for r in remove_list)
        updated.append(t - shift)
    return updated


# ==============================
# Helpers: Variance models
# ==============================

def var_from_pct(z_watt: float, pct: float = 0.01) -> float:
    """
    Return measurement variance σ² for power based on a relative percentage.

    σ = pct * max(|z|, 5), so that very small values do not give σ≈0.
    The returned value is variance, not standard deviation.
    """
    return (pct * max(abs(z_watt), 5)) ** 2



def var_from_pct_voltage(z_value: float, rel: float = 0.005, floor: float = 0.02) -> float:
    """
    Return variance (σ²) for a voltage measurement.

    σ = max(rel*|z|, floor). All are in the same unit as z (volts).
    rel=0.005 means 0.5% relative error.
    floor is used to avoid unrealistically small variance.
    """
    sigma = max(rel * abs(z_value), floor)
    return sigma * sigma


# ==============================
# Data assembly
# ==============================

def build_measurements(
    voltage_df: pd.DataFrame,
    load_df: pd.DataFrame,
    lineflow: pd.DataFrame,
    remove_indices_0based: Sequence[int],
    remove_indices_1based: Sequence[int],
    nbus: int,
) -> np.ndarray:
    """
    Build the measurement table zdata (m x 6) with rows:
      [idx, type, value, fbus, tbus, variance]

    Column meaning:
      idx      : measurement index, 1-based
      type     : 1 Vi, 2 Pi, 3 Qi, 4 Pij, 5 Qij
      value    : measurement value in physical unit
      fbus     : from-bus index, 1-based
      tbus     : to-bus index, 1-based (0 for bus injections / voltage)
      variance : measurement variance σ²

    Voltage inputs:
      voltage_df columns: 'pu', 'Base_kV'
      All voltage values converted to phase-to-neutral volts.

    Load inputs:
      load_df columns: 'kW', 'kVar'
      P, Q converted to watts and vars.

    remove_indices_0based: list of removed node indices (0-based)
    remove_indices_1based: list of removed node indices (1-based)
    """
    # Remove the dropped nodes so that voltage/load data match the trimmed Y-bus.
    V_pu = voltage_df['pu'].drop(remove_indices_0based).reset_index(drop=True)
    V_base_kV = voltage_df['Base_kV'].drop(remove_indices_0based).reset_index(drop=True)

    # Convert voltage from per-unit to phase-to-neutral volts.
    # Here Base_kV is assumed to be line-to-line base voltage.
    V_volts = np.array(V_pu * V_base_kV * 1000.0 / np.sqrt(3), dtype=float)

    P_kW = load_df['kW'].drop(remove_indices_0based).reset_index(drop=True)
    Q_kVar = load_df['kVar'].drop(remove_indices_0based).reset_index(drop=True)
    P_watts = np.array(P_kW * 1000.0, dtype=float)
    Q_vars  = np.array(Q_kVar * 1000.0, dtype=float)

    # Treat buses with nonzero P or Q as buses with injection measurements.
    load_location = np.where((abs(P_watts) > 0.0001) | (abs(Q_vars) > 0.0001))[0].tolist()

    # Extract bus indices involved in lineflow measurements, and use them as
    # additional voltage measurement locations.
    lineselected = [{'Name': name} for name in lineflow['Element'].tolist()]

    lineflow_voltage = []
    for lineinfor in lineselected:
        lineflow_voltage = lineflow_voltage + list(lineflow[lineflow['Element'] == lineinfor['Name']]['Bus11'])
        lineflow_voltage = lineflow_voltage + list(lineflow[lineflow['Element'] == lineinfor['Name']]['Bus12'])
        lineflow_voltage = lineflow_voltage + list(lineflow[lineflow['Element'] == lineinfor['Name']]['Bus13'])
    lineflow_voltage_update = update_indices(remove_indices_1based, [i for i in lineflow_voltage])

    # Voltage measurements are used at:
    #   1) first 3 buses (reference/slack phases),
    #   2) load buses,
    #   3) buses appearing in lineflow measurements.
    voltage_location = [k for k in range(0, 3)] + load_location + [i - 1 for i in lineflow_voltage_update]

    # Remove duplicates while keeping original order.
    voltage_location = list(dict.fromkeys(voltage_location))

    zrows: List[List[float]] = []
    meas_idx = 1

    # --- Voltage magnitude measurements (type=1) ---
    # For buses with actual/selected voltage measurements, use tight variance.
    # For all others, use nominal voltage as pseudo measurement with loose variance.
    for i in range(nbus):
        if i < len(V_volts):
            if i in voltage_location:
                Vi_meas = float(V_volts[i])
                var_V = var_from_pct_voltage(Vi_meas, rel=0.00001, floor=0.0001)
                zrows.append([meas_idx, 1, Vi_meas, i + 1, 0, var_V])
            else:
                Vi_nom = float(V_base_kV[i]) * 1000.0 / np.sqrt(3)
                var_V = var_from_pct_voltage(Vi_nom, rel=0.03, floor=5.0)
                zrows.append([meas_idx, 1, Vi_nom, i + 1, 0, var_V])
            meas_idx += 1

    # --- Real power injections (type=2) ---
    # Starting from bus 4, because the first 3 buses are treated as references.
    for i in range(3, nbus):
        if i in load_location:
            # Load is modeled as negative injection.
            P_inj = -float(P_watts[i])
            var_P = var_from_pct(P_watts[i])
        else:
            # No actual measurement: use zero injection with loose variance.
            P_inj = 0.0
            var_P = 10000000.0
        zrows.append([meas_idx, 2, P_inj, i + 1, 0, var_P])
        meas_idx += 1

    # --- Reactive power injections (type=3) ---
    for i in range(3, nbus):
        if i in load_location:
            Q_inj = -float(Q_vars[i])
            var_Q = var_from_pct(Q_vars[i])
        else:
            Q_inj = 0.0
            var_Q = 10000000.0
        zrows.append([meas_idx, 3, Q_inj, i + 1, 0, var_Q])
        meas_idx += 1

    # --- Line flow real power measurements (type=4) ---
    for lineinfor in lineselected:
        P1 = lineflow[lineflow['Element'] == lineinfor['Name']]['P_1'].item()
        P2 = lineflow[lineflow['Element'] == lineinfor['Name']]['P_2'].item()
        P3 = lineflow[lineflow['Element'] == lineinfor['Name']]['P_3'].item()

        B11 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus11'].item()
        B12 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus12'].item()
        B13 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus13'].item()
        B21 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus21'].item()
        B22 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus22'].item()
        B23 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus23'].item()

        # Update bus numbering after node removal.
        B11_update = update_indices(remove_indices_1based, [B11])[0]
        B12_update = update_indices(remove_indices_1based, [B12])[0]
        B13_update = update_indices(remove_indices_1based, [B13])[0]
        B21_update = update_indices(remove_indices_1based, [B21])[0]
        B22_update = update_indices(remove_indices_1based, [B22])[0]
        B23_update = update_indices(remove_indices_1based, [B23])[0]

        zrows.append([meas_idx, 4, P1 * 1000, B11_update, B21_update, var_from_pct(P1 * 1000, pct=0.01)])
        meas_idx += 1
        zrows.append([meas_idx, 4, P2 * 1000, B12_update, B22_update, var_from_pct(P2 * 1000, pct=0.01)])
        meas_idx += 1
        zrows.append([meas_idx, 4, P3 * 1000, B13_update, B23_update, var_from_pct(P3 * 1000, pct=0.01)])
        meas_idx += 1

    # --- Line flow reactive power measurements (type=5) ---
    for lineinfor in lineselected:
        Q1 = lineflow[lineflow['Element'] == lineinfor['Name']]['Q_1'].item()
        Q2 = lineflow[lineflow['Element'] == lineinfor['Name']]['Q_2'].item()
        Q3 = lineflow[lineflow['Element'] == lineinfor['Name']]['Q_3'].item()

        B11 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus11'].item()
        B12 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus12'].item()
        B13 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus13'].item()
        B21 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus21'].item()
        B22 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus22'].item()
        B23 = lineflow[lineflow['Element'] == lineinfor['Name']]['Bus23'].item()

        B11_update = update_indices(remove_indices_1based, [B11])[0]
        B12_update = update_indices(remove_indices_1based, [B12])[0]
        B13_update = update_indices(remove_indices_1based, [B13])[0]
        B21_update = update_indices(remove_indices_1based, [B21])[0]
        B22_update = update_indices(remove_indices_1based, [B22])[0]
        B23_update = update_indices(remove_indices_1based, [B23])[0]

        zrows.append([meas_idx, 5, Q1 * 1000, B11_update, B21_update, var_from_pct(Q1 * 1000, pct=0.05)])
        meas_idx += 1
        zrows.append([meas_idx, 5, Q2 * 1000, B12_update, B22_update, var_from_pct(Q2 * 1000, pct=0.05)])
        meas_idx += 1
        zrows.append([meas_idx, 5, Q3 * 1000, B13_update, B23_update, var_from_pct(Q3 * 1000, pct=0.05)])
        meas_idx += 1

    return np.array(zrows, dtype=float)



def read_y_matrix_csv(path: str, remove_indices_0based: Sequence[int]) -> np.ndarray:
    """
    Read a rectangular CSV that stores the Y-matrix by (Re, Im) pairs per entry.
    Remove rows/cols at indices in remove_indices_0based to match measurements.

    Expected format:
      - No header with names; raw text cells that may contain odd minus chars.
      - Each row has: [<row_id>, Re(1,1), Im(1,1), Re(1,2), Im(1,2), ...]

    Returns
    -------
    Y : complex ndarray of shape (N, N) after removals.
    """
    df = pd.read_csv(path, header=None, dtype=str)
    n = len(df)
    Y = np.zeros((n, n), dtype=np.complex128)

    def to_float(cell: str | None) -> float:
        """
        Robust float parser for cells like ' -1.23E-4i ' or with odd dashes.
        Only the numeric part is returned.
        """
        if cell is None:
            return 0.0
        s = cell.strip().replace('−', '-').replace('—', '-').replace(' ', '')
        s = s.lower().replace('i', 'j').replace('*', '')
        if s.endswith('j'):
            s = s[:-1]
        if s in {'', '+', '-'}:
            return 0.0
        try:
            return float(s)
        except Exception:
            m = re.search(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?', s)
            return float(m.group(0)) if m else 0.0

    # Fill Y from pairs of (Re, Im).
    for i in range(n):
        row = df.iloc[i, 1:1 + 2 * n]
        for j in range(n):
            re_s = row.iloc[2 * j] if 2 * j < len(row) else '0'
            im_s = row.iloc[2 * j + 1] if 2 * j + 1 < len(row) else '0'
            Y[i, j] = to_float(re_s) + 1j * to_float(im_s)

    # Keep Y-bus consistent with the measurement space after node removal.
    Y = np.delete(np.delete(Y, remove_indices_0based, axis=0), remove_indices_0based, axis=1)
    return Y


# ==============================
# Main WLS-DSSE
# ==============================

def run_wls_dsse(
    voltage_csv: pd.DataFrame,
    angle_init_csv: pd.DataFrame,
    load_csv: pd.DataFrame,
    lineflow_csv: pd.DataFrame,
    y_matrix_csv: str,
    nbus: int,
    feeder_head_voltage_pu: float,
    remove_indices_1based: Sequence[int],
    tol_stop: float = 1e-1,
    max_iters: int = 50,
) -> Dict[str, np.ndarray]:
    """
    Run the WLS-DSSE loop.

    Returns
    -------
    del1   : estimated angles (rad), shape (nbus, 1)
    V      : estimated voltages (V), shape (nbus, 1)
    zdata  : measurement table, shape (m, 6)
    ybus   : complex Y-bus used in DSSE
    V_true : reference voltage values used for plotting/compare
    """
    # Convert removed 1-based indices to 0-based indices for pandas/numpy use.
    nodes_remove_0 = [i - 1 for i in remove_indices_1based]

    # Read inputs.
    voltage_df = voltage_csv
    load_df = load_csv
    lineflow_df = lineflow_csv

    # Build measurement table.
    zdata = build_measurements(voltage_df, load_df, lineflow_df, nodes_remove_0, remove_indices_1based, nbus)

    # Parse zdata columns.
    type_arr = zdata[:, 1].astype(int)
    z = zdata[:, 2]
    fbus = zdata[:, 3].astype(int)
    tbus = zdata[:, 4].astype(int)
    Ri = np.diagflat(zdata[:, 5])

    # Voltage data after removing nodes.
    V_LN = voltage_df['VLN_kV'].drop(nodes_remove_0).reset_index(drop=True) * 1000
    V_base_kV = voltage_df['Base_kV'].drop(nodes_remove_0).reset_index(drop=True)

    # Initial voltage state.
    # Use feeder_head_voltage_pu for all buses as a flat start,
    # then overwrite the first 3 reference buses with actual values.
    V0_volts = np.array(V_base_kV * 1000.0 / np.sqrt(3), dtype=float)
    V = np.array(feeder_head_voltage_pu * np.ones((nbus)) * V0_volts, dtype=float).reshape(-1, 1)
    V_first3 = np.array(V_LN, dtype=float)
    V[0:3] = V_first3[0:3].reshape(-1, 1)

    # Initial angle state.
    # Minimal fix: use the function input angle_init_csv instead of external global variable.
    del1 = np.array(angle_init_csv.drop(nodes_remove_0), dtype=float).reshape(-1, 1)

    # Read trimmed Y-bus.
    ybus = read_y_matrix_csv(y_matrix_csv, nodes_remove_0)

    # State vector E = [θ_4..θ_n, V_4..V_n]^T.
    # The first 3 buses are treated as reference, so they are excluded from the solved state.
    E = np.concatenate((del1[3:], V[3:]), axis=0)

    # Measurement index groups by type.
    vi_idx = np.where(type_arr == 1)[0]
    pi_idx = np.where(type_arr == 2)[0]
    qi_idx = np.where(type_arr == 3)[0]
    pf_idx = np.where(type_arr == 4)[0]
    qf_idx = np.where(type_arr == 5)[0]

    iter_no = 1
    tol = np.inf

    # Weight matrix W = Ri^{-1}. Since Ri is diagonal, this is easy to compute.
    # ws = sqrt(diag(W)) is used to row-scale H and residual r.
    W = np.linalg.inv(Ri)
    ws = np.sqrt(np.clip(np.diag(W), 1e-15, None))

    start = time.time()

    while (tol > tol_stop) and (iter_no <= max_iters):
        print(f"WLS-DSSE Running...  Iteration: {iter_no}")

        # Flatten state vectors for vectorized calculation.
        V1 = V.reshape(-1)
        d1 = del1.reshape(-1)

        # Real and imaginary parts of Y-bus.
        G = ybus.real
        B = ybus.imag

        # Pairwise angle differences θ_i - θ_k and corresponding trig values.
        D = d1[:, None] - d1[None, :]
        C = np.cos(D)
        S = np.sin(D)

        # Kernels used in power injection formulas.
        T_P = G * C + B * S
        T_Q = G * S - B * C

        # ================= h(x): predicted measurements =================
        # Voltage magnitude measurements.
        h1 = V1[(fbus[vi_idx] - 1)].reshape(-1, 1)

        # Power injections at all buses, then select measurement rows.
        PV_full = V1 * (T_P @ V1)
        QV_full = V1 * (T_Q @ V1)
        h2 = PV_full[(fbus[pi_idx] - 1)].reshape(-1, 1)
        h3 = QV_full[(fbus[qi_idx] - 1)].reshape(-1, 1)

        # Branch flow prediction for type 4 and 5 measurements.
        def _flow_blocks(idx_arr: np.ndarray, is_P: bool) -> np.ndarray:
            if idx_arr.size == 0:
                return np.empty((0, 1), float)
            fm = (fbus[idx_arr] - 1).astype(int)
            tn = (tbus[idx_arr] - 1).astype(int)
            c = np.cos(d1[fm] - d1[tn])
            s = np.sin(d1[fm] - d1[tn])
            Gmn = np.asarray(G[fm, tn]).reshape(-1)
            Bmn = np.asarray(B[fm, tn]).reshape(-1)
            Vm = V1[fm]
            Vn = V1[tn]
            if is_P:
                val = -Vm**2 * Gmn - Vm * Vn * (-Gmn * c - Bmn * s)
            else:
                val = -Vm**2 * (-Bmn) - Vm * Vn * (-Gmn * s + Bmn * c)
            return val.reshape(-1, 1)

        h4 = _flow_blocks(pf_idx, is_P=True)
        h5 = _flow_blocks(qf_idx, is_P=False)

        # Stack all predicted measurements in the same order as zdata.
        h = np.vstack([h1, h2, h3, h4, h5])

        # Residual: measured - predicted.
        r = z.reshape(-1, 1) - h

        # ================ Jacobian H = ∂h/∂x =================
        # x = [θ_4..θ_n, V_4..V_n]
        nvar = nbus - 3
        var_cols = np.arange(3, nbus, dtype=int)

        # A) Voltage measurement Jacobian block.
        # Voltage measurement does not depend on angle states directly.
        H11 = np.zeros((vi_idx.size, nvar))
        H12 = np.zeros((vi_idx.size, nvar))
        if vi_idx.size > 0:
            m_vi = (fbus[vi_idx] - 1)
            mask = (m_vi >= 3)
            rows = np.nonzero(mask)[0]
            cols = (m_vi[mask] - 3)
            H12[rows, cols] = 1.0

        # B) Injection Jacobian blocks.
        VmVk = np.outer(V1, V1)
        diagG = np.diag(G)
        diagB = np.diag(B)
        eps = 1e-12

        # ∂P/∂θ
        dP_dth = VmVk * (G * S - B * C)
        np.fill_diagonal(dP_dth, -QV_full - diagB * V1**2)

        # ∂Q/∂θ
        dQ_dth = -VmVk * (G * C + B * S)
        np.fill_diagonal(dQ_dth, PV_full - diagG * V1**2)

        # ∂P/∂V
        dP_dV = V1[:, None] * (G * C + B * S)
        np.fill_diagonal(dP_dV, PV_full / np.maximum(V1, eps) + diagG * V1)

        # ∂Q/∂V
        dQ_dV = V1[:, None] * (G * S - B * C)
        np.fill_diagonal(dQ_dV, QV_full / np.maximum(V1, eps) - diagB * V1)

        m_pi = (fbus[pi_idx] - 1)
        m_qi = (fbus[qi_idx] - 1)

        H21 = dP_dth[m_pi][:, var_cols]
        H22 = dP_dV[m_pi][:, var_cols]
        H31 = dQ_dth[m_qi][:, var_cols]
        H32 = dQ_dV[m_qi][:, var_cols]

        # C) Branch flow Jacobian blocks.
        # Each row only depends on the two terminal buses of that branch.
        def _flow_jac_blocks(idx_arr: np.ndarray, is_P: bool) -> Tuple[np.ndarray, np.ndarray]:
            Hth = np.zeros((idx_arr.size, nvar))
            HV = np.zeros((idx_arr.size, nvar))
            if idx_arr.size == 0:
                return Hth, HV

            fm = (fbus[idx_arr] - 1).astype(int)
            tn = (tbus[idx_arr] - 1).astype(int)
            c = np.cos(d1[fm] - d1[tn])
            s = np.sin(d1[fm] - d1[tn])
            Gmn = np.asarray(G[fm, tn]).reshape(-1)
            Bmn = np.asarray(B[fm, tn]).reshape(-1)
            Vm = V1[fm]
            Vn = V1[tn]

            if is_P:
                dth_m = Vm * Vn * (-Gmn * s + Bmn * c)
                dth_n = -Vm * Vn * (-Gmn * s + Bmn * c)
                dVm = -2 * Gmn * Vm - Vn * (-Gmn * c - Bmn * s)
                dVn = -Vm * (-Gmn * c - Bmn * s)
            else:
                dth_m = -Vm * Vn * (-Gmn * c - Bmn * s)
                dth_n = Vm * Vn * (-Gmn * c - Bmn * s)
                dVm = -2 * Vm * (-Bmn) - Vn * (-Gmn * s + Bmn * c)
                dVn = -Vm * (-Gmn * s + Bmn * c)

            cm = fm - 3
            cn = tn - 3
            mk = (cm >= 0)
            nk = (cn >= 0)
            ar_m = np.nonzero(mk)[0]
            ar_n = np.nonzero(nk)[0]

            Hth[ar_m, cm[mk]] = dth_m[mk]
            Hth[ar_n, cn[nk]] = dth_n[nk]
            HV[ar_m, cm[mk]] = dVm[mk]
            HV[ar_n, cn[nk]] = dVn[nk]
            return Hth, HV

        H41, H42 = _flow_jac_blocks(pf_idx, is_P=True)
        H51, H52 = _flow_jac_blocks(qf_idx, is_P=False)

        # Assemble full Jacobian in the same measurement order as h and z.
        H1 = np.hstack([H11, H12])
        H2 = np.hstack([H21, H22])
        H3 = np.hstack([H31, H32])
        H4 = np.hstack([H41, H42])
        H5 = np.hstack([H51, H52])
        H = np.vstack([H1, H2, H3, H4, H5])

        # ================= Weighted LS solve =================
        # Scale H and r by sqrt(W), then solve least squares:
        #   min || W^(1/2) (r - H dE) ||_2
        A = H * ws[:, None]
        b = r * ws[:, None]

        dE, *_ = np.linalg.lstsq(A, b, rcond=1e-12)

        # Update the state vector.
        E = E + dE
        del1[3:] = E[0:(nbus - 3)]
        V[3:] = E[(nbus - 3):]

        # Use max absolute state change as stopping criterion.
        tol = float(np.max(np.abs(dE)))
        print(f"  Tolerance: {tol:.4e}")
        iter_no += 1

    elapsed = time.time() - start
    print(f"WLS-DSSE Finished in {elapsed:.3f} s, iterations: {iter_no - 1}, final tol: {tol:.3e}")

    DSSE_results = {
        'del1': del1,
        'V': V,
        'zdata': zdata,
        'ybus': ybus,
        'V_true': V_LN,
    }
    return DSSE_results



# ==============================
# Snapshot preparation wrapper
# ==============================

def run_dsse_snapshot(
    voltage_file,
    load_file,
    y_matrix_file,
    db_fp,
    remove_indices_1based,
    feeder_head_voltage_pu,
    snapshot_time,
    cleaned_cap_name=None,
    cleaned_scada_name=None,
    cleaned_scada_from_name=None,
    cleaned_scada_to_name=None,
    ami_units=None,
    scada_units=None,
    secondary_base_kv=0.208,
    tol_stop=1e-3,
    max_iters=20,
):
    """
    Prepare one DSSE snapshot and run WLS-DSSE.

    This function wraps the original main-code logic while keeping the DSSE
    model and measurement-building logic unchanged.

    Parameters
    ----------
    voltage_file : str or Path
        Voltage template CSV. Required columns include:
        Bus_Node, VLN_kV, Base_kV, pu, Angle.
    load_file : str or Path
        Load template CSV. Required columns include:
        Bus_Node, kW, kVar.
    y_matrix_file : str or Path
        Y-bus CSV file.
    db_fp : str or Path
        decaf database path.
    remove_indices_1based : sequence of int
        Original 1-based node indices removed from the Y-bus/model space.
    feeder_head_voltage_pu : float
        Initial flat-start voltage multiplier for non-reference buses.
    snapshot_time : int or str
        Timestamp used to extract AMI/SCADA snapshot values.
    cleaned_cap_name : list[str], optional
        Capacitor-bank SCADA stream names.
    cleaned_scada_name : list[str], optional
        Recloser/breaker SCADA stream names used for lineflow measurements.
    cleaned_scada_from_name : list[str], optional
        From-bus names for each lineflow stream.
    cleaned_scada_to_name : list[str], optional
        To-bus names for each lineflow stream.
    ami_units : list[str], optional
        AMI units to request. Default: ['kW', 'Voltage', 'kVAR'].
    scada_units : list[str], optional
        SCADA units to request. Default includes MW/MVAR/kV for phases a/b/c.
    secondary_base_kv : float
        Base kV used when AMI voltage overwrites secondary voltage points.
    tol_stop : float
        WLS stopping tolerance.
    max_iters : int
        Maximum WLS iterations.

    Returns
    -------
    results : dict
        Contains DSSE_results, Voltage_data, Load_data, lineflow_data, and input summary.
    """
    from . import decaf_db as ddb

    cleaned_cap_name = cleaned_cap_name or []
    cleaned_scada_name = cleaned_scada_name or []
    cleaned_scada_from_name = cleaned_scada_from_name or []
    cleaned_scada_to_name = cleaned_scada_to_name or []

    if not (
        len(cleaned_scada_name)
        == len(cleaned_scada_from_name)
        == len(cleaned_scada_to_name)
    ):
        raise ValueError(
            "cleaned_scada_name, cleaned_scada_from_name, and "
            "cleaned_scada_to_name must have the same length."
        )

    ami_units = ami_units or ['kW', 'Voltage', 'kVAR']
    scada_units = scada_units or [
        'MW_a', 'MVAR_a', 'kV_a',
        'MW_b', 'MVAR_b', 'kV_b',
        'MW_c', 'MVAR_c', 'kV_c',
    ]

    # -----------------------------
    # Load base template data
    # -----------------------------
    Voltage_data = pd.read_csv(voltage_file)
    Load_data = pd.read_csv(load_file)
    Angle_initial = Voltage_data['Angle'].copy()

    required_voltage_cols = {'Bus_Node', 'VLN_kV', 'Base_kV', 'pu', 'Angle'}
    required_load_cols = {'Bus_Node', 'kW', 'kVar'}

    missing_v = required_voltage_cols - set(Voltage_data.columns)
    missing_l = required_load_cols - set(Load_data.columns)

    if missing_v:
        raise ValueError(f"Voltage file is missing columns: {sorted(missing_v)}")
    if missing_l:
        raise ValueError(f"Load file is missing columns: {sorted(missing_l)}")

    Voltage_data['VLN_kV'] = Voltage_data['VLN_kV'].astype(float)
    Voltage_data['Base_kV'] = Voltage_data['Base_kV'].astype(float)
    Voltage_data['pu'] = Voltage_data['pu'].astype(float)

    # -----------------------------
    # Load AMI data and overwrite snapshot measurements
    # -----------------------------
    ami_dict = {
        'unit': ami_units,
    }
    select_ami = ddb.get_ami(db_fp, ami_dict=ami_dict)

    if 'Voltage' in select_ami:
        ami_bus = select_ami['Voltage'].loc[snapshot_time]

        for target in ami_bus.index:
            mask = Load_data['Bus_Node'].str.contains(target, case=False, regex=False)

            if not mask.any():
                continue

            if 'kW' in select_ami:
                Load_data.loc[mask, 'kW'] = select_ami['kW'].loc[snapshot_time, target]

            if 'kVAR' in select_ami:
                Load_data.loc[mask, 'kVar'] = select_ami['kVAR'].loc[snapshot_time, target]

            Voltage_data.loc[mask, 'VLN_kV'] = (
                select_ami['Voltage'].loc[snapshot_time, target] / 1000
            )
            Voltage_data.loc[mask, 'Base_kV'] = secondary_base_kv
            Voltage_data.loc[mask, 'pu'] = (
                Voltage_data.loc[mask, 'VLN_kV']
                / (Voltage_data.loc[mask, 'Base_kV'] / np.sqrt(3))
            )

    # -----------------------------
    # Load capacitor SCADA data and overwrite P/Q/V measurements
    # -----------------------------
    if len(cleaned_cap_name) > 0:
        scada_dict_cap = {
            'stream': cleaned_cap_name,
            'unit': scada_units,
        }
        select_scada_cap = ddb.get_scada(db_fp, scada_dict=scada_dict_cap)

        phase_info = [
            ('.1', 'kV_a', 'MW_a', 'MVAR_a'),
            ('.2', 'kV_b', 'MW_b', 'MVAR_b'),
            ('.3', 'kV_c', 'MW_c', 'MVAR_c'),
        ]

        for target in cleaned_cap_name:
            base_bus = target.split('__')[0]

            for phase, kv_col, mw_col, mvar_col in phase_info:
                target_phase = base_bus + phase
                mask = Load_data['Bus_Node'].str.contains(
                    target_phase, case=False, regex=False
                )

                if not mask.any():
                    continue

                Voltage_data.loc[mask, 'VLN_kV'] = select_scada_cap[kv_col].loc[
                    snapshot_time, target
                ]
                Voltage_data.loc[mask, 'pu'] = (
                    Voltage_data.loc[mask, 'VLN_kV']
                    / (Voltage_data.loc[mask, 'Base_kV'] / np.sqrt(3))
                )
                Load_data.loc[mask, 'kW'] = (
                    select_scada_cap[mw_col].loc[snapshot_time, target] * 1000
                )
                Load_data.loc[mask, 'kVar'] = (
                    select_scada_cap[mvar_col].loc[snapshot_time, target] * 1000
                )

    # -----------------------------
    # Load recloser/breaker SCADA and build lineflow measurements
    # -----------------------------
    lineflow_data = pd.DataFrame(columns=[
        'Element', 'P_1', 'P_2', 'P_3', 'Q_1', 'Q_2', 'Q_3',
        'Bus11', 'Bus12', 'Bus13', 'Bus21', 'Bus22', 'Bus23',
    ])

    if len(cleaned_scada_name) > 0:
        scada_dict_line = {
            'stream': cleaned_scada_name,
            'unit': scada_units,
        }
        select_scada_line = ddb.get_scada(db_fp, scada_dict=scada_dict_line)

        temp_P1, temp_P2, temp_P3 = [], [], []
        temp_Q1, temp_Q2, temp_Q3 = [], [], []
        temp_From11, temp_From12, temp_From13 = [], [], []
        temp_From21, temp_From22, temp_From23 = [], [], []

        phase_info = [
            ('.1', 'kV_a', temp_From11, temp_From21),
            ('.2', 'kV_b', temp_From12, temp_From22),
            ('.3', 'kV_c', temp_From13, temp_From23),
        ]

        for target, target_from, target_to in zip(
            cleaned_scada_name,
            cleaned_scada_from_name,
            cleaned_scada_to_name,
        ):
            for phase, kv_col, from_list, to_list in phase_info:
                target_from_phase = target_from.split('__')[0] + phase
                target_to_phase = target_to.split('__')[0] + phase

                mask_from = Load_data['Bus_Node'].str.contains(
                    target_from_phase, case=False, regex=False
                )
                mask_to = Load_data['Bus_Node'].str.contains(
                    target_to_phase, case=False, regex=False
                )

                if not mask_from.any():
                    raise ValueError(
                        f"From bus phase {target_from_phase} was not found in Load_data."
                    )
                if not mask_to.any():
                    raise ValueError(
                        f"To bus phase {target_to_phase} was not found in Load_data."
                    )

                Voltage_data.loc[mask_from, 'VLN_kV'] = select_scada_line[kv_col].loc[
                    snapshot_time, target
                ]
                Voltage_data.loc[mask_from, 'pu'] = (
                    Voltage_data.loc[mask_from, 'VLN_kV']
                    / (Voltage_data.loc[mask_from, 'Base_kV'] / np.sqrt(3))
                )

                from_bus_name = Load_data.loc[mask_from, 'Bus_Node'].iloc[0]
                to_bus_name = Load_data.loc[mask_to, 'Bus_Node'].iloc[0]

                from_idx = Load_data.index[Load_data['Bus_Node'] == from_bus_name][0]
                to_idx = Load_data.index[Load_data['Bus_Node'] == to_bus_name][0]

                from_list.append(from_idx)
                to_list.append(to_idx)

            temp_P1.append(select_scada_line['MW_a'].loc[snapshot_time, target] * 1000)
            temp_P2.append(select_scada_line['MW_b'].loc[snapshot_time, target] * 1000)
            temp_P3.append(select_scada_line['MW_c'].loc[snapshot_time, target] * 1000)
            temp_Q1.append(select_scada_line['MVAR_a'].loc[snapshot_time, target] * 1000)
            temp_Q2.append(select_scada_line['MVAR_b'].loc[snapshot_time, target] * 1000)
            temp_Q3.append(select_scada_line['MVAR_c'].loc[snapshot_time, target] * 1000)

        lineflow_data = pd.DataFrame({
            'Element': cleaned_scada_name,
            'P_1': temp_P1,
            'P_2': temp_P2,
            'P_3': temp_P3,
            'Q_1': temp_Q1,
            'Q_2': temp_Q2,
            'Q_3': temp_Q3,
            'Bus11': (np.array(temp_From11) + 1).tolist(),
            'Bus12': (np.array(temp_From12) + 1).tolist(),
            'Bus13': (np.array(temp_From13) + 1).tolist(),
            'Bus21': (np.array(temp_From21) + 1).tolist(),
            'Bus22': (np.array(temp_From22) + 1).tolist(),
            'Bus23': (np.array(temp_From23) + 1).tolist(),
        })

    # -----------------------------
    # Run DSSE
    # -----------------------------
    nbus_actual = len(Voltage_data) - len(remove_indices_1based)

    DSSE_results = run_wls_dsse(
        voltage_csv=Voltage_data,
        angle_init_csv=Angle_initial,
        load_csv=Load_data,
        lineflow_csv=lineflow_data,
        y_matrix_csv=y_matrix_file,
        nbus=nbus_actual,
        feeder_head_voltage_pu=feeder_head_voltage_pu,
        remove_indices_1based=remove_indices_1based,
        tol_stop=tol_stop,
        max_iters=max_iters,
    )

    return {
        'DSSE_results': DSSE_results,
        'Voltage_data': Voltage_data,
        'Load_data': Load_data,
        'lineflow_data': lineflow_data,
        'nbus_actual': nbus_actual,
        'input_summary': {
            'voltage_file': voltage_file,
            'load_file': load_file,
            'y_matrix_file': y_matrix_file,
            'db_fp': db_fp,
            'remove_indices_1based': remove_indices_1based,
            'feeder_head_voltage_pu': feeder_head_voltage_pu,
            'snapshot_time': snapshot_time,
            'cleaned_cap_name': cleaned_cap_name,
            'cleaned_scada_name': cleaned_scada_name,
            'cleaned_scada_from_name': cleaned_scada_from_name,
            'cleaned_scada_to_name': cleaned_scada_to_name,
            'tol_stop': tol_stop,
            'max_iters': max_iters,
        }
    }


# ==============================
# Plot and evaluation helper
# ==============================

def plot_and_print_dsse_results(results_dict, remove_indices_1based):
    """
    Plot voltage angle and voltage magnitude results, and print voltage MAE.
    """
    DSSE_results = results_dict['DSSE_results']
    Voltage_data = results_dict['Voltage_data']

    sns.set_style("darkgrid")

    nbus_plot = len(DSSE_results['V_true'])

    plt.figure(figsize=(10, 3))
    plt.plot(np.arange(1, nbus_plot + 1), DSSE_results['del1'], "-*")
    plt.title("Voltage phase angles")
    plt.xlabel("Bus number")
    plt.ylabel("Phase angle (rad)")
    plt.xlim(1, nbus_plot)
    plt.tight_layout()

    plt.figure(figsize=(10, 3))
    plt.plot(
        np.arange(1, nbus_plot + 1),
        DSSE_results['V_true'],
        label="Actual-Measurements/ Pseudo-Measurements",
    )
    plt.plot(
        np.arange(1, nbus_plot + 1),
        DSSE_results['V'],
        label="DSSE",
    )
    plt.xlabel("Bus number")
    plt.ylabel("Voltage (V)")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()

    V_base = Voltage_data['Base_kV'].drop([i - 1 for i in remove_indices_1based])
    MAE = np.mean(
        np.abs(
            DSSE_results['V_true'] / (V_base * 1000)
            - DSSE_results['V'].flatten() / (V_base * 1000)
        )
    )
    print(
        "Mean voltage error: Between Actual-Measurements/ "
        f"Pseudo-Measurements and DSSE: {MAE:.6f} p.u."
    )
    print('DSSE Finished')

    return MAE
