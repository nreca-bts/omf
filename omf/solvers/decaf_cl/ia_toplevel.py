from pathlib import Path
import numpy as np
import pandas as pd
from .dsse_functions import run_dsse_snapshot
from .evaluation_metrics import thermal_evaluation_metric, thermal_loading_from_ami_db, voltage_evaluation_metric
from . import decaf_db as ddb

def feeder_situation_awareness(
    base_dir=None,
    max_timestamps=None,
    pv_profile=None,
    pv_mapping=None,
    fixed_pv_specs=None,
    fixed_pv_injection_specs=None,
    thermal_threshold_pct=100.0,
    allow_positional_pv_alignment=False):
    '''IA State: state estimation powerflow-based HC analysis. We step through 3 powerflows: current system, system + approved pipeline, system + pipeline + 1 new interconnection'''

    # ============================================================
    # 1. User input parameters
    # ============================================================

    if base_dir is not None:
        base_dir = Path(base_dir).resolve()

    else:
        try:
            # works in .py script
            base_dir = Path(__file__).resolve().parent
        except NameError:
            base_dir = Path.cwd()

    INPUT_DIR = base_dir / "test_data"

    Voltage_file = INPUT_DIR/ "voltage_inputs" / "Iowa240_VLN_template.csv"
    Load_file = INPUT_DIR/ "voltage_inputs" / "Iowa240_LOAD_template.csv"
    Y_matrix_file = INPUT_DIR/ "voltage_inputs" / "240_bus_test_system_EXP_Y_wo_load.CSV"

    db_fp = INPUT_DIR / "iowa240" / "db_temp_files" / "version1_test_short_iowa_240.db"
    thermal_reference_dir = INPUT_DIR / "thermal_inputs"

    # Removed buses, 1-based index, Substation high voltage nodes
    remove_indices_1based = [1, 2, 3, 4, 5, 6, 7, 8, 9]

    # Do NOT manually set n_bus.
    # Use voltage file length to avoid mismatch.
    Voltage_template = pd.read_csv(Voltage_file)
    n_bus = len(Voltage_template)

    # Actual DSSE bus number after removing nodes
    nbus_actual = n_bus - len(remove_indices_1based)

    feeder_head_voltage = 1

    tol_stop = 1e-3
    max_iters = 20

    output_file = base_dir / "DSSE_voltage_timeseries.csv"
    pu_output_file = base_dir / "DSSE_voltage_timeseries_pu.csv"

    save_pu = True

    # ============================================================
    # 2. Measurement source settings
    # ============================================================

    cleaned_cap_name = [
        "bus2038__cap_201",
        "bus3079__cap_301",
    ]

    cleaned_scada_name = [
        "bus1__cb_101",
        "bus1__cb_201",
        "bus2012__cb_202",
        "bus2021__cb_203",
        "bus1__cb_301",
        "bus3075__cb_302",
    ]

    cleaned_scada_from_name = [
        "BUS1",
        "BUS1",
        "BUS2011",
        "BUS2021",
        "BUS1",
        "BUS3068",
    ]

    cleaned_scada_to_name = [
        "BUS1002",
        "BUS2002",
        "BUS2013",
        "BUS2027",
        "BUS3003",
        "BUS3076",
    ]

    # ============================================================
    # 3. Timestamp list
    # ============================================================

    #ami_dict = {"unit": ["kW", "Voltage", "kVAR"]}
    #select_ami = ddb.get_ami(db_fp, ami_dict=ami_dict)
    #timestamp_data = select_ami["Voltage"].index.tolist()
    #if max_timestamps is not None:
    #    timestamp_data = timestamp_data[:int(max_timestamps)]
    timestamp_data = [
        1483254000,
        1483257600,
        1483261200,
        1483264800,
        1483268400,
        1483272000,
        1483275600,
        1483279200,
        1483282800,
        1483286400,
        1483290000,
        1483293600,
        1483297200,
        1483300800,
        1483304400,
        1483308000,
        1483311600,
        1483315200,
        1483318800,
        1483322400,
        1483326000,
        1483329600,
        1483333200,
        1483336800,
    ]
    ntime = len(timestamp_data)

    print("=" * 70)
    print(f"Total timestamps: {ntime}")
    print(f"Original bus number from voltage file: {n_bus}")
    print(f"DSSE bus number after removal: {nbus_actual}")
    print("=" * 70)

    # ============================================================
    # 4. Pre-allocate result matrix
    # ============================================================

    V_all = np.full((ntime, nbus_actual), np.nan)

    # ============================================================
    # 5. Run DSSE over all timestamps
    # ============================================================

    for i, snapshot_time in enumerate(timestamp_data):

        print("=" * 70)
        print(f"Running DSSE {i + 1}/{ntime}, timestamp = {snapshot_time}")
        print("=" * 70)
        

        try:
            result = run_dsse_snapshot(
                voltage_file=Voltage_file,
                load_file=Load_file,
                y_matrix_file=Y_matrix_file,
                db_fp=db_fp,
                remove_indices_1based=remove_indices_1based,
                feeder_head_voltage_pu=feeder_head_voltage,
                snapshot_time=snapshot_time,
                cleaned_cap_name=cleaned_cap_name,
                cleaned_scada_name=cleaned_scada_name,
                cleaned_scada_from_name=cleaned_scada_from_name,
                cleaned_scada_to_name=cleaned_scada_to_name,
                tol_stop=tol_stop,
                max_iters=max_iters,
            )
        
        
            V_est = result['DSSE_results']["V"].flatten()
        
            if len(V_est) != nbus_actual:
                raise ValueError(
                    f"Voltage result length mismatch. "
                    f"Expected {nbus_actual}, got {len(V_est)}."
                )
        
            V_all[i, :] = V_est
        
        except Exception as e:
            print(f"Error at timestamp {snapshot_time}: {type(e).__name__}: {e}")
            print("This timestamp will be saved as NaN.")

    # ============================================================
    # 6. Save voltage results
    # ============================================================

    bus_columns = [f"Bus_{i + 1}" for i in range(nbus_actual)]

    df_out = pd.DataFrame(V_all, columns=bus_columns)
    df_out.insert(0, "timestamp", timestamp_data)

    df_out.to_csv(output_file, index=False)

    print("=" * 70)
    print("DSSE time-series calculation finished.")
    print(f"Saved voltage file: {output_file}")
    print(f"Output shape: {df_out.shape}")
    print("=" * 70)

    # ============================================================
    # 7. Optional: save per-unit voltage
    # ============================================================
    
    save_pu = True    
    if save_pu:
        Voltage_template = pd.read_csv(Voltage_file)
    
        remove_indices_0based = [i - 1 for i in remove_indices_1based]
    
        V_base = (
            Voltage_template["Base_kV"]
            .drop(remove_indices_0based)
            .reset_index(drop=True)
            .values
            * 1000/np.sqrt(3)
        )
    
        V_all_pu = V_all / V_base.reshape(1, -1)
    
        df_out_pu = pd.DataFrame(V_all_pu, columns=bus_columns)
        df_out_pu.insert(0, "timestamp", timestamp_data)
        df_out_pu.to_csv(pu_output_file, index=False)

    

    # ============================================================
    # 8. Calculate Evaluation Metrics
    # ============================================================

    # Voltage Metrics
    DSSE_outputs = pd.read_csv(pu_output_file, index_col=0).to_numpy()
    voltage_metric_results = voltage_evaluation_metric(DSSE_outputs, v_threshold=1.0)
    
    # Thermal Metrics 
    thermal_outputs = thermal_loading_from_ami_db(
        db_fp=db_fp,
        reference_dir=thermal_reference_dir,
        output_dir=base_dir,
        timestamps=timestamp_data,
        pv_profile=pv_profile,
        pv_mapping=pv_mapping,
        fixed_pv_specs=fixed_pv_specs,
        fixed_pv_injection_specs=fixed_pv_injection_specs,
        allow_positional_pv_alignment=allow_positional_pv_alignment,
    )
    thermal_metric_results = thermal_evaluation_metric(
        thermal_outputs["loading_pct"],
        threshold_pct=thermal_threshold_pct,
    )
    thermal_metric_results.to_csv(base_dir / "thermal_metrics.csv")
    
    
    return {
        "voltage": voltage_metric_results,
        "thermal": thermal_metric_results,
        "thermal_loading_pct": thermal_outputs["loading_pct"],
        "thermal_delta_adjusted_transformers": thermal_outputs["delta_adjusted_transformers"],
        "thermal_diagnostics": thermal_outputs["diagnostics"],
    }

def optimal_upgrades(
    site_id: str,
    target_hc_mw: float,
    catalog_id: str = "default",
) -> dict:
    """Plan Iowa240 upgrades for an absolute hosting-capacity target in MW.

    Uses the installed icnn_hc package. Returns the planner dictionary,
    including baseline_hc_mw, post_upgrade_hc_mw, total_cost_usd, upgrades,
    target_achieved and failure_reason. The upgrades are sequential actions,
    not a guarantee of a globally minimum-cost solution.
    Example:
        result = optimal_upgrades("bus3131", target_hc_mw=1.20)
    """
    from .icnn_hc.api import plan_upgrade

    return plan_upgrade(
        site_id=site_id,
        target_hc_mw=target_hc_mw,
        catalog_id=catalog_id,
    )
