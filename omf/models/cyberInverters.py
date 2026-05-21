"""
The cyberInverters model shows the impacts of inverter hacks on a feeder including
system voltages, regulator actions, and capacitor responses. It leverages PyCIGAR, which
is a computational framework for deep Reinforcement Learning and control experiments for
the distributed grid, developed by LBNL.
"""


import json
from pathlib import Path
from shutil import copy2, copytree, rmtree
import pandas as pd
import datetime
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *


# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The cyberInverters model shows the impacts of inverter hacks on a feeder including system voltages, regulator actions, and capacitor responses."
hidden = True


def work(model_dir, input_dict):
    ''' Run the model in its directory.'''
    # - Create inputs directory to pycigar and insert data
    (Path(model_dir) / 'pycigar_inputs').mkdir(parents=True, exist_ok=True)
    (Path(model_dir) / 'pycigar_outputs').mkdir(parents=True, exist_ok=True)
    filenames = (
        # - TODO: if we allow the user to upload their own feeder, then insert new tuples here
        (input_dict['miscInputsFilename'], input_dict['miscInputsFile']),
        (input_dict['breakpointsFilename'], input_dict['breakpointsFile']),
        (input_dict['deviceInputsFilename'], input_dict['deviceInputsFile']),
        (input_dict['loadSolarFilename'], input_dict['loadSolarFile']),
        (input_dict['attackNodeDataFilename'], input_dict['attackNodeDataFile']),
        (input_dict['attackSwitchDataFilename'], input_dict['attackSwitchDataFile']),
        (input_dict['attackDeviceDataFilename'], input_dict['attackDeviceDataFile']))
    for t in filenames:
        with (Path(model_dir) / 'pycigar_inputs' / t[0]).open('w') as f:
            f.write(t[1])
    # - Could use dssConvert.treeToDss(0) to convert the omd into a dss file (see commit #dce8c7f)
    # - TODO: if we allow the user to upload their own feeder, remove these two lines
    copy2(Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / 'ieee37busdata' / 'ieee37_LBL.dss', Path(model_dir) / 'pycigar_inputs' / f'{input_dict["feederName1"]}.dss')

    # - Adjust the user's input arguments or raise an error due to invalid user arguments
    # - The 'start' argument to pycigar.main() must be >= 50
    #   - Does it actually need to be >= 50? Yes. pycigar crashes with values 0 - 49 (inclusive)
    #   - I would think it could be 0, but it cannot
    start = int(input_dict['start'])
    if start < 50:
        raise ValueError()
    # - The 'duration' argument to pycigar.main() must be >= 0
    duration = int(input_dict['duration'])
    if duration < 0:
        raise ValueError()
    # - We read the user's uploaded load_solar_data.csv (which currently is just a single CSV that we copy) to determine its length
    with (Path(model_dir) / 'pycigar_inputs' / input_dict['loadSolarFilename']).open() as f:
        df = pd.read_csv(f)
    if start + duration > len(df):
        duration = len(df) - start
    run_pycigar(model_dir, input_dict, start, duration, df)
    return format_output(model_dir, input_dict, start, duration)


def run_pycigar(model_dir, input_dict, start, duration, df):
    """
    Run the pycigar workflow and return its results.
    """
    # - Must import the package here so that developers who haven't installed pycigar can still use the OMF
    import pycigar
    # - Set the 'test' argument to pycigar.main() to be 'NO_DEFENSE', 'TRAIN', or 'DEFENSE'
    #   - If the user set Train? to True, then test = 'TRAIN'
    #   - If the user set Train? to True and selected a defense agent, what do we do? (not handled)
    #   - If the user set Train? to False and did not select a defense agent, then test = 'NO_DEFENSE'
    #   - If the user set Train? to False and selected a defense agent, then test = 'DEFENSE'
    if input_dict['trainAgent'] == 'True':
        trainAgent = True
    elif input_dict['trainAgent'] == 'False':
        trainAgent = False
    else:
        raise ValueError()
    if trainAgent:
        test = 'TRAIN'
    else:
        if input_dict['defenseAgent'] == 'None':
            test = 'NO_DEFENSE'
        else:
            test = 'DEFENSE'
    # - The 'type_attack' argument to pycigar.main() should be None, 'VOLTAGE_IMBALANCE', or 'VOLTAGE_OSCILLATION'
    # - The 'battery_vvc' argument to pycigar.main() must be False in order for pycigar to run when type_attack is None. If pycigar doesn't run at
    #   all, then this module crashes when it tries to format the output
    #   - Otherwise, I think battery_vvc should be True because that satisfies more if-statements in pycigar.main()
    # - battery_status can be True or False, regardless of the values of type_attack and battery_vvc
    battery_vvc = True
    #if input_dict['typeAttack'] == 'None':
    #    type_attack = None
    #    battery_vvc = False
    #elif input_dict['typeAttack'] == 'VOLTAGE_IMBALANCE':
    #    type_attack = 'VOLTAGE_IMBALANCE'
    #elif input_dict['typeAttack'] == 'VOLTAGE_OSCILLATION':
    #    type_attack = 'VOLTAGE_OSCILLATION'
    #else:
    #    raise ValueError()
    # - The 'battery_status' argument to pycigar.main() must be 'True' or 'False'
    if input_dict['batteryStatus'] == 'True':
        battery_status = True
    elif input_dict['batteryStatus'] == 'False':
        battery_status = False
    else:
        raise ValueError()
    # - The 'hack_start' argument to pycigar.main() should be able to be None, but in reality it must be >= 0 because of
    #   ceds-cigar-external/pycigar/core/kernel/scenario/opendss.py
    # - The 'hack_end' argument to pycigar.main() can be None (like it's supposed to), but to be consistent with 'hack_start' it must be >=
    #   'hack_start'
    #   - Play with these argument values and see what happens
    #if input_dict['hackStart'] == 'None':
    #    hack_start = None
    #else:
    #    hack_start = int(input_dict['hackStart'])
    #if input_dict['hackEnd'] == 'None':
    #    hack_end = None
    #else:
    #    hack_end = int(input_dict['hackEnd'])
    #if hack_start < 0 or hack_start >= len(df):
    #    raise ValueError()
    #if hack_end < 0 or hack_end >= len(df) or hack_end <= hack_start:
    #    raise ValueError()
    # - The 'percentage_hack' argument to pycigar.main() must be between 0 and 100
    #percentage_hack = int(input_dict['percentageHack'])
    #if percentage_hack < 0 or percentage_hack > 100:
    #    raise ValueError()
    # - The 'policy' argument to pycigar.main() should be None or a path to pycigar_inputs/policy_ieee37_imbalance_sample_feb2023
    #   - Currently, there is only one possible defense policy definition
    if input_dict['defenseAgent'] == 'None':
        policy = None
    elif input_dict['defenseAgent'] == 'policy_ieee37_imbalance_sample_feb2023':
        policy = f'{model_dir}/pycigar_inputs/{input_dict["defenseAgent"]}'
        copytree(
            Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / input_dict['defenseAgent'],
            Path(model_dir) / 'pycigar_inputs' / input_dict['defenseAgent'],
            dirs_exist_ok=True)
    else:
        raise ValueError()
    # TODO: test training functionality
    # TODO: make it possible to re-train a defense when 'TRAIN' is selected and so is one of the pre-trained defenses
    pycigar.main(
        misc_inputs_path=f'{model_dir}/pycigar_inputs/{input_dict["miscInputsFilename"]}',
        dss_path=f'{model_dir}/pycigar_inputs/{input_dict["circuitFilename"]}',
        load_solar_path=f'{model_dir}/pycigar_inputs/{input_dict["loadSolarFilename"]}',
        breakpoints_path=f'{model_dir}/pycigar_inputs/{input_dict["breakpointsFilename"]}',
        test=test,
        output=f'{model_dir}/pycigar_outputs',
        #type_attack=type_attack,
        policy=policy,
        start=start,
        duration = duration,
        #hack_start=hack_start,
        #hack_end=hack_end,
        #percentage_hack=percentage_hack,
        device_path=f'{model_dir}/pycigar_inputs/{input_dict["deviceInputsFilename"]}',
        battery_status=battery_status,
        battery_vvc=battery_vvc,
        attack_node_data_path=f'{model_dir}/pycigar_inputs/{input_dict["attackNodeDataFilename"]}',
        attack_switch_data_path=f'{model_dir}/pycigar_inputs/{input_dict["attackSwitchDataFilename"]}',
        attack_device_data_path=f'{model_dir}/pycigar_inputs/{input_dict["attackDeviceDataFilename"]}')

        # - Austin (2025-01-29) - this is a leftover comment
        # Report out the agent paths
        # NOTE: This doesn't appear to be used anywhere later. Leave commented out. See additional note
        #defAgentFolders = os.listdir(pJoin(model_dir,"pycigarOutput"))
        #inputDict['defenseAgentNames'] = ','.join([x for x in defAgentFolders if x.startswith('policy_')]) # TODO: don't do it this way. Instead, save off the policy instead, and upload the names accordingly on startup.
        # inputDict['kpi'] = ['oscillation_kpi', 'unbalance_kpi', 'network_kpi', 'RedTeam_kpi']
        # update the input data json file
        ## Might break with allInputData file locking.
        #with open(pJoin(model_dir, "allInputData.json")) as inFileOb:
        #	json.dump(inputDict, inFileOb, indent=4)


def format_output(model_dir, input_dict, start, duration):
    """
    Perform format output processing for the cyber inverters model.
    """
    # - Must import the package here so that developers who haven't installed pycigar can still use the OMF
    from pycigar.utils.logging import logger
    # - TODO: a lot of the operations we do to set properties on the out_data dict are to create data for visualizations in highchart.js. Should we
    #   instead create the visualizations with a Python library (e.g. plotly) and then simply write those visualization .html pages into the
    #   pycigar_outputs/ directory and load them in cyberInverters.html?
    out_data = {
        'Consumption': {
            'realPower': None,
            'apparentPower': None,
            'reactivePower': None,
            'losses': None,
            'realDG': None,
        }
    }
    # - The 'timeStamps' key is only needed for highchart visualizations. It has no impact on pycigar
    start_dt = datetime.datetime.fromisoformat(input_dict['simStartDate'].replace('Z', '+00:00')) + datetime.timedelta(seconds=start)
    out_data['timeStamps'] = [(start_dt + datetime.timedelta(seconds=x)).strftime('%Y-%m-%d %H:%M:%S%z') for x in range(duration)]

    with (Path(model_dir) / 'pycigar_outputs' / 'pycigar_output_specs.json').open() as f:
        pycigar_json = json.load(f)
    # Get KPIs from Logger into out_data
    out_data['oscillation_kpi'] = logger().log_dict['oscillation_kpi']
    out_data['oscillation_kpi_area_under_curve'] = logger().log_dict['oscillation_kpi_area_under_curve']
    out_data['oscillation_kpi_bus_oscillation_voltage'] = logger().log_dict['oscillation_kpi_bus_oscillation_voltage']
    out_data['unbalance_kpi'] = logger().log_dict['unbalance_kpi']

    #convert meter voltage data
    out_data["allMeterVoltages"] = pycigar_json["allMeterVoltages"]

    #convert consumption data
    out_data["Consumption"]["realPower"] = pycigar_json["Consumption"]["Power Substation (W)"]
    out_data["Consumption"]["apparentPower"] = pycigar_json["Consumption"]["Apparent Power Substation (VA)"]
    out_data["Consumption"]["reactivePower"] = pycigar_json["Consumption"]["Reactive Power Substation (V)"]
    out_data["Consumption"]["losses"] = pycigar_json["Consumption"]["Losses Total (W)"]
    out_data["Consumption"]["realDG"] = [-1.0 * x for x in pycigar_json["Consumption"]["DG Output (W)"] ]
    #out_data["Consumption"]["realDG"] = [-1.0 * x for x in pycigar_json["Consumption"]["Real DG Output (W)"] ]
    #out_data["Consumption"]["reactiveDG"] = [-1.0 * x for x in pycigar_json["Consumption"]["Reactive DG Output (V)"] ]

    #convert substation data
    out_data["powerFactor"] = pycigar_json["Substation Power Factor (%)"]
    out_data["swingVoltage"] = pycigar_json["Substation Top Voltage (U)"]
    out_data["downlineNodeVolts"] = pycigar_json["Substation Bottom Voltage (U)"]
    out_data["minVoltBand"] = pycigar_json["Substation Regulator Minimum Voltage(V)"]
    out_data["maxVoltBand"] = pycigar_json["Substation Regulator Maximum Voltage(V)"]
    out_data["Capacitor_Outputs"] = pycigar_json["Capacitor Outputs"]

    #get switch info
    out_data["switchStates"] = pycigar_json["Switch Outputs"]

    #convert regulator data
    # create lists of regulator object names
    regNameList = []
    for key in pycigar_json:
        if key.startswith('Regulator_'):
            regNameList.append(key)
    regDict = {}
    for reg_name in regNameList:
        short_reg_name = reg_name.replace("Regulator_","") # TODO: ask LBL to alter regulator, capacitor output to match that of "bus voltages"
        newReg = {}
        newReg["phases"] = list(pycigar_json[reg_name]["RegPhases"])
        tapchanges = {}
        for phase in newReg["phases"]:
            phsup = phase.upper()
            tapchanges[phsup] = pycigar_json[reg_name][short_reg_name + phase.lower()]
        newReg["tapchanges"] = tapchanges
        regDict[reg_name] = newReg
    out_data["Regulator_Outputs"] = regDict

    #convert inverter data
    inverter_output_dict = {}
    for inv_dict in pycigar_json["Inverter Outputs"]:
        #create a new dictionary to represent the single inverter
        new_inv_dict = {}
        #get values from pycigar output for given single inverter
        inv_name = inv_dict["Name"]
        inv_volt = inv_dict["Voltage (V)"]
        #populate single inverter dict with pycigar values
        new_inv_dict["Voltage"] = inv_volt
        new_inv_dict["Power_Real"] = [ -1 * x for x in inv_dict["Power Output (W)"] ]
        new_inv_dict["Power_Imag"] = [-1 * x for x in inv_dict["Reactive Power Output (VAR)"] ]
        #new_inv_dict["Power_Real"] = inv_dict["Power Output (W)"]
        #new_inv_dict["Power_Imag"] = inv_dict["Reactive Power Output (VAR)"]
        #add single inverter dict to dict of all the inverters using the inverter name as the key
        inverter_output_dict[inv_name] = new_inv_dict
    out_data["Inverter_Outputs"] = inverter_output_dict

    #convert battery data
    battery_output_dict = {}
    transformatter = {"discharge":0,"standby":1,"charge":2}
    for bname, batt_dict in pycigar_json["Battery Outputs"].items():
        new_batt_dict = {}
        new_batt_dict["SOC"] = [x*100 for x in batt_dict["SOC"]]
        new_batt_dict["Charge_Status"] = [transformatter[x] for x in batt_dict["control_setting"]]
        #new_batt_dict["Power_Out"] = batt_dict["Power Output (W)"]
        #new_batt_dict["Power_In"] = batt_dict["Power Input (W)"]
        # create value for combined power in/output
        batt_power = batt_dict["Power Output (W)"]
        for i, val in enumerate(batt_dict["Power Input (W)"]):
            batt_power[i] = -(batt_power[i] + val)
        new_batt_dict["Real_Power"] = batt_power
        #TODO: uncomment this when battery vars come available as an output from pycigar
        #batt_power = batt_dict["Reactive Power Output (VAR)"]
        #for i, val in enumerate(batt_dict["Reactive Power Input (W)"]):
        #	batt_power[i] = -(batt_power[i] + val)
        #new_batt_dict["Reactive_Power"] = batt_power
        if len(batt_dict["bat_cycle"]) == 0:
            new_batt_dict["Cycles"] = 0.0
        else:
            new_batt_dict["Cycles"] = batt_dict["bat_cycle"][-1]
        # add single battery dict to dict of all the batteries using the battery name as the key
        battery_output_dict[batt_dict["Name"]] = new_batt_dict
    out_data["Battery_Outputs"] = battery_output_dict

    # convert voltage imbalance data
    out_data["voltageImbalances"] = {}
    for bus_name in pycigar_json["Voltage Imbalances"].keys():
        if (bus_name!="u_worst") and (bus_name!="u_mean"):
            out_data["voltageImbalances"][bus_name] = pycigar_json["Voltage Imbalances"][bus_name]

    # convert bus voltage data
    out_data["Bus_Voltages"] = {}
    for busname in pycigar_json["Bus Voltages"].keys():
        out_data["Bus_Voltages"][busname] = { k:v for k,v in pycigar_json["Bus Voltages"][busname].items() if k!="Phases" }

    #capture the pycigar output file
    out_data["stdout"] = pycigar_json["stdout"]
    return out_data


def new(model_dir):
    ''' Create a new instance of this model. Returns true on success, false on failure. '''
    # - By convention, we use a try-except block to fail model creation instead of raising an internal exception on the server
    try:
        # - omf files
        circuit_dir = 'ieee37busdata'
        omd_prefix = 'ieee37_LBL'
        # - redteam_addon_parser_V3.py files
        breakpoints_filename = 'breakpoints.csv'
        device_inputs_filename = 'device_inputs.txt'
        load_solar_filename = 'load_solar_data.csv'
        misc_inputs_filename = 'misc_inputs.csv'
        attack_node_data_filename = 'redteam_attack_node_data.csv'
        attack_switch_data_filename = 'redteam_attack_switch_data.csv'
        attack_device_data_filename = 'redteam_attack_regulator_data.csv'
        # - Get file contents
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / breakpoints_filename).open() as f:
            breakpoints_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / device_inputs_filename).open() as f:
            device_inputs_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / load_solar_filename).open() as f:
            load_solar_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / misc_inputs_filename).open() as f:
            misc_inputs_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / attack_node_data_filename).open() as f:
            attack_node_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / attack_switch_data_filename).open() as f:
            attack_switch_data = f.read()
        with (Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / circuit_dir / attack_device_data_filename).open() as f:
            attack_device_data = f.read()
        defaultInputs = {
            'simStartDate': '2019-07-01T00:00:00Z',
            'duration': '2000',                                             # - Max value for the default CSV is 14400
            'durationUnits': 'seconds',
            'start': '50',
            'feederName1': omd_prefix,
            'circuitFilename': f'{omd_prefix}.dss',
            'loadSolarFilename': load_solar_filename,
            'loadSolarFile': load_solar_data,
            'breakpointsFilename':breakpoints_filename,
            'breakpointsFile': breakpoints_data,
            'miscInputsFilename': misc_inputs_filename,
            'miscInputsFile': misc_inputs_data,
            'deviceInputsFilename': device_inputs_filename,
            'deviceInputsFile': device_inputs_data,
            'batteryStatus': 'True',
            'batteryVVC': 'True',
            'modelType': modelName,
            'zipCode': '59001',
            'trainAgent': 'False',
            #'typeAttack': 'None',
            'defenseAgent': 'None',                                         # - The defense agent selected by the user
            #'hackStart': '100',
            #'hackEnd': '700',
            #'percentageHack': '40',
            'defenseAgentNames': 'policy_ieee37_imbalance_sample_feb2023',  # - A list of possible defense agents
            'attackNodeDataFilename': attack_node_data_filename,
            'attackNodeDataFile': attack_node_data,
            'attackSwitchDataFilename': attack_switch_data_filename,
            'attackSwitchDataFile': attack_switch_data,
            'attackDeviceDataFilename': attack_device_data_filename,
            'attackDeviceDataFile': attack_device_data,
            'learningAlgorithm': 'None'
        }
        neometamodel_was_created = __neoMetaModel__.new(model_dir, defaultInputs)
        # - Could grab <feederName1>.omd from publicFeeders/ instead
        # - Must copy the omd here to use the "Open Editor" button
        copy2(Path(omf.omfDir) / 'static' / 'testFiles' / 'pyCIGAR' / 'ieee37busdata' / 'ieee37_LBL.omd', Path(model_dir) / f'{omd_prefix}.omd')
    except:
        return False
    return neometamodel_was_created


@neoMetaModel_test_setup
def _debugging():
    # Location
    """
    Run this module's local smoke tests or debugging workflow.
    """
    model_loc = Path(omf.omfDir) / 'data' / 'Model' / 'admin' / f'Automated Testing of {modelName}'
    # Blow away old test results if necessary.
    try:
        rmtree(model_loc)
    except:
        # No previous test results.
        pass
    # Create New.
    new(model_loc)
    # Pre-run.
    # __neoMetaModel__.renderAndShow(modelLoc)
    # Run the model.
    __neoMetaModel__.runForeground(model_loc)
    # Show the output.
    __neoMetaModel__.renderAndShow(model_loc)


if __name__ == '__main__':
	_debugging()