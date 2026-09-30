'Main decaf_cl entrypoint'
# Python Imports
from pathlib import Path
import json

_decafDir = Path(__file__).parent

# from .ts_load import decaf_ts_load as ts_load
# from .sandia_toplevel import protection_analysis
from .ia_toplevel import (
    feeder_situation_awareness as run_pipeline,
    optimal_upgrades,
)

def run_all_tests():
    # End to End Test
    print('\n\n**** TESTING TS_LOAD ****')
    ts_load_input_dict = {
        "longitude": "-94.67",
        "latitude": "39.10",
        "year": "2023",
        "azimuth": "180.0",
        "systemCapacity": 10,
        "tilt": 45,
        "losses": 15.5,
        "array_type": 2 }
    # ts_load(_decafDir / 'test_data' / '15_min_local_tz.csv', ts_load_input_dict)

    # print('\n\n**** TESTING PROTECTION_ANALYSIS ****')
    # protection_result = protection_analysis(
    #         # database_fp = _decafDir / 'temp_delme'/ 'delme_temp.db',  # temporary file location
    #         ami_fp = _decafDir / 'test_data' / 'iowa240' / 'demand_source_files' / "20260129-iowa_240_synthetic_ami_short_04.csv",
    #         ckt_dss_fp= _decafDir / 'test_data' / 'iowa240' / 'main_no_profiles.dss',
    #         is_single_file_model= 0,
    #             )
    
    print('\n\n**** TESTING RUN_PIPELINE ****')
    run_pipeline(
      base_dir=None,
      max_timestamps=None,
      pv_profile=None,
      pv_mapping=None,
      fixed_pv_specs=None,
      fixed_pv_injection_specs=None)

    print('\n\n**** TESTING OPTIMAL_UPGRADES ****')
    site_id = "bus3131"
    target_hc_mw = 1.20
    opt_upg_results = optimal_upgrades(site_id=site_id, target_hc_mw=target_hc_mw)
    with open('output_optiUpgrResults.json', 'w') as fp:
        json.dump(opt_upg_results, fp)

    #TODO: Unit Tests if needed
    """
    current sandia test files:
    * test_decaf_db.py
    * test_decaf_graph.py
    * test_snl_toplevel.py
    """

