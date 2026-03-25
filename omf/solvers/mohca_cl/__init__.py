''' mohca_cl, command line interface to the Model-Free Hosting Capacity Algorithm. '''
from . import sandia
from . import sandia_TCHC
from . import ISU_PINNbasedHCA
from . import transformer_customer_mapping_isu

import argparse
import os
from pathlib import Path
import unittest

mohca_dir = Path(__file__).parent

def add(x,y):
  ''' Add two python objects. Maybe ints, maybe floats, strings work... '''
  return x + y

def hello():
  ''' Hello world test function. '''
  return 'hello mohca'

def sandia1(in_path, out_path, der_pf, vv_x, vv_y, load_pf_est):
  ''' Execute Sandia hosting capacity algorithm on in_path CSV with output written as CSV to out_path. '''
  ret_value = sandia.hosting_cap(in_path, out_path, der_pf, vv_x, vv_y, load_pf_est)
  return ret_value

def sandiaTCHC( in_path, out_path, final_results, der_pf, vv_x, vv_y, overload_constraint, xf_lookup):
  ''' Execute Sandia thermal constrained hosting capacity algorithm on in_path CSV with output written as CSV to out_path'''
  ret_val = sandia_TCHC.hosting_cap_tchc( in_path, out_path, final_results, der_pf, vv_x, vv_y, overload_constraint, xf_lookup )
  return ret_val

def isu_transformerCustMapping( input_meter_data_fp, grouping_output_fp, minimum_xfmr_n, fmr_n_is_exact, bus_coords_fp):
  ''' Execute iowa states transformer customer mapping code. Note: Last 3 inputs can be None, False, None respectively '''
  ret_val = transformer_customer_mapping_isu.get_groupings( input_meter_data_fp, grouping_output_fp, minimum_xfmr_n, fmr_n_is_exact, bus_coords_fp)
  return ret_val

def iastate(in_path, out_path):
  ''' Execute ISU hosting capacity algorithm on in_path CSV with output written as CSV to out_path. '''
  ''' Besides the in_path and out_path, more setting information is needed for the code running. The information of the testing system is shown below.'''
  input_csv_path = 'ISU_InputData_realsystem.csv'  # input path
  output_csv_path = 'Output_csv_path.csv'      # output path
  system_name = 'AMU_EC3'                      # system name for model saving
  node_list_for_HC = [i for i in range(3)]     # selected bus for HC analysis
  total_bus_number = 50                        # total bus number
  model_retrain = 0                            # 1 for retraining; 0 for not training
  inverter_control_setting = 'var'             # two setting mode: var prioirty and watt priority
  inverter_advanced_control = 1                # 0->'without control'  1->'constant power factor' 2->'constant reactive power' 3->'active power-reactive power' 4->'voltage-reactive power'
  ret_value = ISU_PINNbasedHCA.PINN_HC(system_name, input_csv_path, output_csv_path, total_bus_number, nodes_selected=node_list_for_HC, retrain_indicator=model_retrain, inverter_control=inverter_advanced_control, control_setting=inverter_control_setting)
  #ret_value = ISU_PINNbasedHCA.PINN_HC(in_path, out_path)
  
  return ret_value

def run_all_tests():
  ''' Run all tests in the project. '''
  sandia.hosting_cap('./mohca_cl/test_data/loc1.csv', './mohca_cl/test_data/loc1_out.csv')
  sandia.sanity_check('./mohca_cl/test_data/HC_Results_model_based.csv', './mohca_cl/test_data/loc1_out.csv')

  #test_sandia.py = 9 tests
  #test_sandia_TCHC.py = 8 tests 

  PROJ_ROOT = Path("__file__").parent.absolute()

  testLoader = unittest.TestLoader()
  testSuite = testLoader.discover(start_dir=str( str(PROJ_ROOT) + "/mohca_cl"), pattern='test_*.py')
  runner = unittest.TextTestRunner(verbosity=2)
  runner.run(testSuite)

def init_cli():
  # Main Parser
  parser = argparse.ArgumentParser(prog='MoHCA_CL', description='MoHCA Command Tool',
                                   epilog="Example: mohca_cl add x y")
  # Sub Parser
  subparsers = parser.add_subparsers(dest='commands')
  # Each function needs its own sub
  # Add Function
  add_parser = subparsers.add_parser('add')
  add_parser.add_argument('x', help="First number")
  add_parser.add_argument('y', help="Second number")
  add_parser.set_defaults(func=add)
  #hello
  hello_parser = subparsers.add_parser('hello')
  hello_parser.set_defaults(func=hello)
  # sandia1 function
  sandia1_parser = subparsers.add_parser("sandia1")
  sandia1_parser.add_argument('in_path', help='Input Path for csv - check OMF hosting capacity wiki for .csv formatting')
  sandia1_parser.add_argument('out_path', help='Output Path')
  sandia1_parser.add_argument('der_pf', type=float, default=None, help='Optional DER Power Flow Input - Positive for capacitive, Negative for inductive')
  sandia1_parser.add_argument('vv_x', type=list, default=None, help='x coords for volt_var curve')
  sandia1_parser.add_argument('vv_y', type=list, default=None, help='y coords for volt_var curve')
  sandia1_parser.add_argument('load_pf_est', type=float, default=None, help='estimated average power factor')
  sandia1_parser.set_defaults(func=sandia1)
  #sandiaTCHC
  sandiaTCHC_parser = subparsers.add_parser("sandiaTCHC")
  sandiaTCHC_parser.add_argument('in_path', help='Input Path for csv - check OMF hosting capacity wiki for .csv formatting')
  sandiaTCHC_parser.add_argument('out_path', help='Output Path')
  sandiaTCHC_parser.add_argument('final_results', help='dataframe: busname, Transformer Index, X, Y')
  sandiaTCHC_parser.add_argument('der_pf', default=None, help='Optional DER Power Flow Input - Positive for capacitive, Negative for inductive')
  sandiaTCHC_parser.add_argument('vv_x', default=None, help='x coords for volt_var curve')
  sandiaTCHC_parser.add_argument('vv_y', default=None, help='y coords for volt_var curve')
  sandiaTCHC_parser.add_argument('load_pf_est', default=None, help='estimated average power factor')
  sandiaTCHC_parser.add_argument('overload_constraint', default=None, help='transformer thermal constraint')
  sandiaTCHC_parser.add_argument('xf_lookup', default=None, help='Expected Columns are: "kVA", "R_ohms_LV", "X_ohms_LV"')
  sandiaTCHC_parser.set_defaults(func=sandiaTCHC)
  #isu_transformerCustMapping
  isu_transcustmapping_parser = subparsers.add_parser('isu_transformerCustMapping')
  isu_transcustmapping_parser.add_argument('input_meter_data_fp', help="input file path")
  isu_transcustmapping_parser.add_argument('grouping_output_fp', help="output file path")
  isu_transcustmapping_parser.add_argument('minimum_xfmr_n', type=int, default=None, help="Minimum transformer num")
  isu_transcustmapping_parser.add_argument('fmr_n_is_exact,', type=bool, default=False, help="Bool - Transformer number exact")
  isu_transcustmapping_parser.add_argument('bus_coords_fp', default=None)
  isu_transcustmapping_parser.set_defaults(func=isu_transformerCustMapping)
  #iastate
  iastate_parser = subparsers.add_parser('iastate')
  iastate_parser.add_argument('in_path', help="input .csv")
  iastate_parser.add_argument('out_path')
  iastate_parser.set_defaults(func=iastate)

  #run tests
  tests_parser = subparsers.add_parser('run_all_tests')
  tests_parser.set_defaults(func=run_all_tests)
  args = parser.parse_args()
  if args.commands == 'add':
    print( args.func(args.x, args.y) )
  elif args.commands == 'hello':
    print( args.func() )
  elif args.commands == 'sandia1':
    args.func( args.in_path, args.out_path, args.der_pf, args.vv_x, args.vv_y, args.load_pf_est )
  elif args.commands == 'sandiaTCHC':
    args.func( args.in_path, args.out_path, args.final_results, args.der_pf, args.vv_x, args.vv_y, args.load_pf_est, args.overload_constraint, args.xf_lookup )
  elif args.commands == 'isu_tranformerCustMapping':
    args.func( args.input_meter_data_fp, args.grouping_output_fp, args.minimum_xfmr_n, args.fmr_n_is_exact, args.bus_coords_fp )
  elif args.commands == 'iastate':
    args.func( args.in_path, args.out_path )
  elif args.commands == 'run_all_tests':
    args.func()
  else:
    print("Invalid Command")