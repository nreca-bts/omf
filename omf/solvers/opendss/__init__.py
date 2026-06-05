"""
Run OpenDSS circuits and expose conversion, plotting, and hosting-capacity helpers for
OMF models.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
from networkx.algorithms.traversal.depth_first_search import dfs_tree
import math
import os
import warnings
import subprocess
from copy import deepcopy
import opendssdirect as dss
from opendssdirect import run_command, Error
from omf.solvers.opendss import dssConvert
import multiprocessing
from functools import partial
from pathlib import Path

def runDssCommand(dsscmd, strict=False, logToFile=False, logFilePath=None):
	'''Execute a single opendsscmd in the current context.'''
	run_command(dsscmd)
	if logToFile == False:
		latest_error = Error.Description()
		if latest_error != '':
			if strict:
				raise Exception('OpenDSS Error:', latest_error)
			else:
				print('WARNING: OpenDSS Error:', latest_error)
	elif logToFile == True:
		if logFilePath != None:
			run_command(f'export errorlog "{logFilePath}"')
		else:
			run_command(f'export errorlog')

def runDSS(dssFilePath, logToFile=False, logFilePath=None):
	'''Run DSS circuit definition file, set export/data paths, solve powerflow.'''
	# Check for valid .dss file
	assert '.dss' in dssFilePath.lower(), 'The input file must be an OpenDSS circuit definition file.'
	fullPath = os.path.abspath(dssFilePath)
	dssFileLoc = os.path.dirname(fullPath)
	runDssCommand('clear', logToFile=logToFile, logFilePath=logFilePath)
	runDssCommand(f'set datapath="{dssFileLoc}"', logToFile=logToFile, logFilePath=logFilePath)
	runDssCommand(f'redirect "{fullPath}"', logToFile=logToFile, logFilePath=logFilePath)
	runDssCommand('calcvoltagebases', logToFile=logToFile, logFilePath=logFilePath)
	runDssCommand('solve', logToFile=logToFile, logFilePath=logFilePath)

def getCoords(dssFilePath):
	'''Takes in an OpenDSS circuit definition file and outputs the bus coordinates as a dataframe.'''
	dssFileLoc = os.path.dirname(dssFilePath)
	runDSS(dssFilePath)
	runDssCommand(f'export buscoords "{dssFileLoc}/coords.csv"')
	coords = pd.read_csv(dssFileLoc + '/coords.csv', header=None)
	coords.columns = ['Element', 'X', 'Y', 'radius']
	hyp = []
	for index, row in coords.iterrows():
		hyp.append(math.sqrt(row['X']**2 + row['Y']**2))
	coords['radius'] = hyp
	return coords

def _getByName(tree, name):
	'''Return first object with name in tree as an OrderedDict.'''
	matches =[]
	for x in tree:
		if x.get('object',''):
			if x.get('object','').split('.')[1] == name:
				matches.append(x)
	return matches[0]

def newQstsPlot(filePath, stepSizeInMinutes, numberOfSteps, keepAllFiles=False, actions={}, filePrefix='timeseries'):
	'''QSTS with native opendsscmd binary to avoid segfaults in opendssdirect.'''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	dss_run_file = ''
	dss_run_file += f'redirect "{filePath}"\n'
	dss_run_file += f'set datapath="{dssFileLoc}"\n'
	dss_run_file += f'set maxcontroliter=1000\n'
	dss_run_file += f'calcvoltagebases\n'
	# Attach Monitors
	tree = dssConvert.dssToTree(filePath)
	mon_names = []
	circ_name = 'NONE'
	base_kvs = pd.DataFrame()
	for ob in tree:
		obData = ob.get('object','NONE.NONE')
		obType, name = obData.split('.')
		mon_name = f'mon{obType}-{name}'
		if obData.startswith('circuit.'):
			circ_name = name
		elif obData.startswith('vsource.'):
			dss_run_file += f'new object=monitor.{mon_name} element={obType}.{name} terminal=1 mode=0\n'
			mon_names.append(mon_name)
		elif obData.startswith('isource.'):
			dss_run_file += f'new object=monitor.{mon_name} element={obType}.{name} terminal=1 mode=0\n'
			mon_names.append(mon_name)
		elif obData.startswith('generator.') or obData.startswith('isource.') or obData.startswith('storage.') or obData.startswith('pvsystem.'):
			mon_name = f'mongenerator-{name}'
			dss_run_file += f'new object=monitor.{mon_name} element={obType}.{name} terminal=1 mode=1 ppolar=no\n'
			mon_names.append(mon_name)
		elif ob.get('object','').startswith('load.'):
			dss_run_file += f'new object=monitor.{mon_name} element={obType}.{name} terminal=1 mode=0\n'
			mon_names.append(mon_name)
			new_kv = pd.DataFrame({'kv':[float(ob.get('kv',1.0))],'Name':['monload-' + name]})
			base_kvs = pd.concat([base_kvs,new_kv])
		elif ob.get('object','').startswith('capacitor.'):
			dss_run_file += f'new object=monitor.{mon_name} element={obType}.{name} terminal=1 mode=6\n'
			mon_names.append(mon_name)
		elif ob.get('object','').startswith('regcontrol.'):
			tformer = ob.get('transformer','NONE')
			winding = ob.get('winding',1)
			dss_run_file += f'new object=monitor.{mon_name} element=transformer.{tformer} terminal={winding} mode=2\n'
			mon_names.append(mon_name)
	# Run DSS
	dss_run_file += f'set mode=yearly stepsize={stepSizeInMinutes}m \n'
	if actions == {}:
		# Run all steps directly.
		dss_run_file += f'set number={numberOfSteps}\n'
		dss_run_file += 'solve\n'
	else:
		# Actions defined, run them at the appropriate timestep.
		dss_run_file += f'set number=1\n'
		for step in range(1, numberOfSteps+1):
			action = actions.get(step)
			if action != None:
				print(f'Step {step} executing:', action)
				dss_run_file += action
			dss_run_file += 'solve\n'
	# Export all monitors
	for name in mon_names:
		dss_run_file += f'export monitors monitorname={name}\n'
	# Write runner file and run.
	with open(f'{dssFileLoc}/dss_run_file.dss', 'w') as run_file:
		run_file.write(dss_run_file)
	# Run in the right directory and suppress the output
	runDSS('dss_run_file.dss')
	# Aggregate monitors
	all_gen_df = pd.DataFrame()
	all_load_df = pd.DataFrame()
	all_source_df = pd.DataFrame()
	all_control_df = pd.DataFrame()
	for name in mon_names:
		csv_path = f'{dssFileLoc}/{circ_name}_Mon_{name}_1.csv'
		df = pd.read_csv(f'{circ_name}_Mon_{name}_1.csv')
		if name.startswith('monload-'):
			# reassign V1 single phase voltages outputted by DSS to the appropriate column and filling Nans for neutral phases (V2)
			# three phase print out should work fine as is
			ob_name = name.split('-', 1)[1]
			# print("ob_name:", ob_name)
			the_object = _getByName(tree, ob_name)
			# print("the_object:", the_object)
			# create phase list, removing neutral phases
			phase_ids = the_object.get('bus1','').replace('.0','').split('.')[1:]
			# print("phase_ids:", phase_ids)
			# print("headings list:", df.columns)
			if phase_ids == ['1']:
				df[['V2']] = np.NaN
				df[['V3']] = np.NaN
			elif phase_ids == ['2']:
				df[['V2']] = df[['V1']]
				df[['V1']] = np.NaN
				df[['V3']] = np.NaN
			elif phase_ids == ['3']:
				df[['V3']] = df[['V1']]
				df[['V1']] = np.NaN
				df[['V2']] = np.NaN
			# # print("df after phase reassignment:")
			# # print(df.head(10))
			df['Name'] = name
			all_load_df = pd.concat([all_load_df, df], ignore_index=True, sort=False)
			#pd.set_option('display.max_columns', None)
			# print("all_load_df:", df.head(50))
		elif name.startswith('mongenerator-'):
			# reassign V1 single phase voltages outputted by DSS to the appropriate column and filling Nans for neutral phases (V2)
			# three phase print out should work fine as is
			ob_name = name.split('-')[1]
			# print("ob_name:", ob_name)
			the_object = _getByName(tree, ob_name)
			# print("the_object:", the_object)
			# create phase list, removing neutral phases
			phase_ids = the_object.get('bus1','').replace('.0','').split('.')[1:]
			# print("phase_ids:", phase_ids)
			# print("headings list:", df.columns)
			if phase_ids == ['1']:
				df[['P2 (kW)']] = np.NaN
				df[['P3 (kW)']] = np.NaN
			elif phase_ids == ['2']:
				df[['P2 (kW)']] = df[['P1 (kW)']]
				df[['P1 (kW)']] = np.NaN
				df[['P3 (kW)']] = np.NaN
			elif phase_ids == ['3']:
				df[['P3 (kW)']] = df[['P1 (kW)']]
				df[['P1 (kW)']] = np.NaN
				df[['P2 (kW)']] = np.NaN
			# # print("df after phase reassignment:")
			# # print(df.head(10))
			df['Name'] = name
			all_gen_df = pd.concat([all_gen_df, df], ignore_index=True, sort=False)
		elif name.startswith('monvsource-'):
			df['Name'] = name
			all_source_df = pd.concat([all_source_df, df], ignore_index=True, sort=False)
		elif name.startswith('monisource-'):
			df['Name'] = name
			all_source_df = pd.concat([all_source_df, df], ignore_index=True, sort=False)
		elif name.startswith('moncapacitor-'):
			df['Type'] = 'Capacitor'
			df['Name'] = name
			df = df.rename({' Step_1 ': 'Tap(pu)'}, axis='columns') #HACK: rename to match regulator tap name
			all_control_df = pd.concat([all_control_df, df], ignore_index=True, sort=False)
		elif name.startswith('monregcontrol-'):
			df['Type'] = 'Transformer'
			df['Name'] = name
			df = df.rename({' Tap (pu)': 'Tap(pu)'}, axis='columns') #HACK: rename to match cap tap name
			all_control_df = pd.concat([all_control_df, df], ignore_index=True, sort=False)
		if not keepAllFiles:
			os.remove(csv_path)
	# Collect switching actions
	for key, ob in actions.items():
		if ob.startswith('open'):
			switch_ob = ob.split()
			ob_name = switch_ob[1][7:]
			new_row = {'hour':key, 't(sec)':0.0,'Tap(pu)':1,'Type':'Switch','Name':ob_name}
			all_control_df = pd.concat([all_control_df, new_row], ignore_index=True, sort=False)
	for key, ob in actions.items():
		if ob.startswith('close'):
			switch_ob = ob.split()
			ob_name = switch_ob[1][7:]
			new_row = {'hour':key, 't(sec)':0.0,'Tap(pu)':1,'Type':'Switch','Name':ob_name}
			all_control_df = pd.concat([all_control_df, new_row], ignore_index=True, sort=False)
	# Write final aggregates
	if not all_gen_df.empty:
		all_gen_df.sort_values(['Name','hour'], inplace=True)
		all_gen_df.columns = all_gen_df.columns.str.replace(r'[ "]','',regex=True)
		all_gen_df.to_csv(f'{dssFileLoc}/{filePrefix}_gen.csv', index=False)
	if not all_control_df.empty:
		all_control_df.sort_values(['Name','hour'], inplace=True)
		all_control_df.columns = all_control_df.columns.str.replace(r'[ "]','',regex=True)
		all_control_df.to_csv(f'{dssFileLoc}/{filePrefix}_control.csv', index=False)
	if not all_source_df.empty:
		all_source_df.sort_values(['Name','hour'], inplace=True)
		all_source_df.columns = all_source_df.columns.str.replace(r'[ "]','',regex=True)
		all_source_df["P1(kW)"] = all_source_df["V1"].astype(float) * all_source_df["I1"].astype(float) / 1000.0
		all_source_df["P2(kW)"] = all_source_df["V2"].astype(float) * all_source_df["I2"].astype(float) / 1000.0
		all_source_df["P3(kW)"] = all_source_df["V3"].astype(float) * all_source_df["I3"].astype(float) / 1000.0
		all_source_df.to_csv(f'{dssFileLoc}/{filePrefix}_source.csv', index=False)
	if not all_load_df.empty:
		all_load_df.sort_values(['Name','hour'], inplace=True)
		all_load_df.columns = all_load_df.columns.str.replace(r'[ "]','',regex=True)
		all_load_df = all_load_df.join(base_kvs.set_index('Name'), on='Name')
		# TODO: insert ANSI bands here based on base_kv?  How to not display two bands per load with the appended CSV format?
		all_load_df['V1(PU)'] = all_load_df['V1'].astype(float) / (all_load_df['kv'].astype(float) * 1000.0)
		# HACK: reassigning 0V to "NaN" as below does not removes 0V phases but could impact 2 phase systems
		#all_load_df['V2'][(all_load_df['VAngle2']==0) & (all_load_df['V2']==0)] = "NaN"
		all_load_df['V2(PU)'] = all_load_df['V2'].astype(float) / (all_load_df['kv'].astype(float) * 1000.0)
		all_load_df['V3(PU)'] = all_load_df['V3'].astype(float) / (all_load_df['kv'].astype(float) * 1000.0)
		all_load_df.to_csv(f'{dssFileLoc}/{filePrefix}_load.csv', index=False)

def get_hosting_capacity_of_single_bus(FILE_PATH:str, BUS_NAME:str, max_test_kw:float):
	'''
	- Return the maximum hosting capacity at a single bus that is possible before a thermal violation or voltage violation is reached
		- E.g. if a violation occurs at 4 kW, then this function will return 3.5 kW with thermally_limited == False and voltage_limited == False
	- Special case: if a single bus experiences a violation at 1 kW, then this function will return 1 kW with thermally_limited == True and/or
		voltage_limited == True. In this case, the hosting capacity isn't known. We only know it's < 1 kW
	'''
	# - Get lower and upper bounds for the hosting capacity of a single bus
	thermally_limited = False
	voltage_limited = False
	thermally_limited_precise = False
	voltage_limited_precise = False
	lower_kw_bound = 1
	upper_kw_bound = 1
	while True:
		results = check_hosting_capacity_of_single_bus(FILE_PATH, BUS_NAME, upper_kw_bound)
		thermally_limited = results['thermally_limited']
		voltage_limited = results['voltage_limited']
		if thermally_limited or voltage_limited or upper_kw_bound == max_test_kw:
			break
		lower_kw_bound = upper_kw_bound
		upper_kw_bound = lower_kw_bound * 2
		if upper_kw_bound > max_test_kw:
			upper_kw_bound = max_test_kw
	# - If no violations were found at the max_test_kw, then just report the hosting capacity to be the max_test_kw even though the actual hosting
	#   capacity is higher
	if not thermally_limited and not voltage_limited and upper_kw_bound == max_test_kw:
		return {'bus': BUS_NAME, 'max_kw': max_test_kw, 'reached_max': False, 'thermally_limited': thermally_limited, 'voltage_limited': voltage_limited}
	# - Use the bounds to compute the hosting capacity of a single bus
	kw_step = (upper_kw_bound - lower_kw_bound) / 2
	kw = lower_kw_bound + kw_step
	# - The reported valid hosting capacity (i.e. lower_kw_bound) will be equal to the hosting capacity that causes a thermal or voltage violation
	#   minus a value that is less than 1 kW
	#   - E.g. a reported hosting capacity of 139.5 kW means that a violation probably occurred at 140 kW
	while not kw_step < .1:
		results = check_hosting_capacity_of_single_bus(FILE_PATH, BUS_NAME, kw)
		thermally_limited_precise = results['thermally_limited']
		voltage_limited_precise = results['voltage_limited']
		if not thermally_limited_precise and not voltage_limited_precise:
			lower_kw_bound = kw
		else:
			upper_kw_bound = kw
		kw_step = (upper_kw_bound - lower_kw_bound) / 2
		kw = lower_kw_bound + kw_step

	# This should catch if both were true in the first check and we need to narrow it down to the right one.
	if thermally_limited and voltage_limited:
		# If in the second stage, it was a thermal violation, then make sure voltage violation is false and its not both.
		if thermally_limited_precise:
			voltage_limited = False
		# Else, the opposite
		else:
			thermally_limited = False
	return {'bus': BUS_NAME, 'max_kw': lower_kw_bound, 'reached_max': True, 'thermally_limited': thermally_limited, 'voltage_limited': voltage_limited}

def check_hosting_capacity_of_single_bus(FILE_PATH:str, BUS_NAME:str, kwValue: float):
	''' Identify if an amount of generation that is added at BUS_NAME exceeds ANSI A Band voltage levels. '''
	fullpath = os.path.abspath(FILE_PATH)
	filedir = os.path.dirname(fullpath)
	ansi_a_max_pu = 1.05 #	ansi_b_max_pu = 1.058
	# Find the insertion kv level.
	kv_mappings = get_bus_kv_mappings(fullpath, logToFile=True)
	# Error cleanly on invalid bus.
	if BUS_NAME not in kv_mappings:
		raise Exception(f'BUS_NAME {BUS_NAME} not found in circuit.')
	# Get insertion bus; should always be safe to insert above makebuslist.
	tree = dssConvert.dssToTree(fullpath)
	for i, ob in enumerate(tree):
		if ob.get('!CMD', None) == 'makebuslist':
			insertion_index = i
	# Step through generator sizes, add to circuit, measure voltages.
	new_tree = deepcopy(tree)
	# Insert generator.
	new_gen = {
		'!CMD': 'new',
		'object': f'generator.hostcap_{BUS_NAME}',
		'bus1': f'{BUS_NAME}.1.2.3',
		'kw': kwValue,
		'pf': '1.0',
		'conn': 'wye',
		'phases': '3',
		'kv': kv_mappings[BUS_NAME],
		'model': '1' }
	# Make DSS and run.
	new_tree.insert(insertion_index, new_gen)
	dssConvert.treeToDss(new_tree, 'HOSTCAP.dss')
	runDSS('HOSTCAP.dss', logToFile=True)
	# Calc max voltages.
	runDssCommand(f'export voltages "{filedir}/volts.csv"', logToFile=True)
	volt_df = pd.read_csv(f'{filedir}/volts.csv')
	v_max_pu1, v_max_pu2, v_max_pu3 =  volt_df[' pu1'].max(), volt_df[' pu2'].max(), volt_df[' pu2'].max()
	v_max_pu_all = float(max(v_max_pu1, v_max_pu2, v_max_pu3))
	volt_violation = True if np.greater(v_max_pu_all, ansi_a_max_pu) else False
	# Calc number of thermal violations.
	runDssCommand(f'export overloads "overloads.csv"', logToFile=True)
	over_df = pd.read_csv(f'overloads.csv')
	therm_violation = True if len(over_df) > 0 else False
	return {'thermally_limited':therm_violation, 'voltage_limited':volt_violation}

def hosting_capacity_all(FNAME:str, max_test_kw:float=50000, BUS_LIST:list = None ):
	''' Generate hosting capacity results for all_buses. '''
	fullpath = os.path.abspath(FNAME)
	if not BUS_LIST:
		gen_buses = get_meter_buses(fullpath)
	else:
		gen_buses = BUS_LIST
	gen_buses = list(set(gen_buses))
	all_output = []
	# print('GEN_BUSES', gen_buses)
	for bus in gen_buses:
		try:
			single_output = get_hosting_capacity_of_single_bus(fullpath, bus, max_test_kw)
			all_output.append(single_output)
		except:
			print(f'Could not solve hosting capacity for BUS_NAME={bus}')
	# print( "multiprocessor false all_output: ", all_output )
	return all_output

def get_obj_by_name(name, tree, cmd=None):
	''' Get object with given name in tree. If multiple or zero objs found, raise exceptions. '''
	all_obs_name = [x for x in tree if x.get('object', '').endswith(f'.{name}')]
	if cmd:
		all_obs_name = [x for x in all_obs_name if x.get('!CMD','') == cmd]
	num_found = len(all_obs_name)
	if num_found == 1:
		return all_obs_name[0]
	elif num_found == 0:
		err = f'No object with name "{name}" found.'
		raise Exception(err)
	else:
		# - 2024-10-20: handle case where a transformer and a regcontrol share a name
		all_obs_name = [x for x in tree if x.get('object', '').endswith(f'.{name}') and not x.get('object').startswith('regcontrol')]
		if len(all_obs_name) == 1:
			return all_obs_name[0]
		else:
			err = f'Multiple objects with given name found: {all_obs_name}'
			raise Exception(err)

def get_subtree_obs(line, tree):
	'''Get all objects down-line from the affected line.'''
	aff_ob = get_obj_by_name(line, tree, cmd='new')
	# - 2024-10-20: handle case where aff_ob is transformer instead of a line
	if aff_ob.get('object').startswith('transformer.'):
		aff_bus = aff_ob.get('buses').strip('[]').split(',')[1].split('.')[0]
	else:
		aff_bus = aff_ob.get('bus2').split('.')[0]
	net = dssConvert.dss_to_networkx(None, tree=tree)
	sub_tree = dfs_tree(net, aff_bus)
	sub_names = [x for x in sub_tree.nodes]
	sub_obs = [x for x in tree if x.get('object','NO.NO').split('.')[1] in sub_names]
	return sub_obs

def get_subtree_lines(line, tree):
	'''Get all lines down-line from the affected line.'''
	aff_ob = get_obj_by_name(line, tree, cmd='new')
	# - 2024-10-20: handle case where aff_ob is transformer instead of a line
	if aff_ob.get('object').startswith('transformer.'):
		aff_bus = aff_ob.get('buses').strip('[]').split(',')[1].split('.')[0]
	else:
		aff_bus = aff_ob.get('bus2').split('.')[0]
	net = dssConvert.dss_to_networkx(None, tree=tree)
	sub_tree = dfs_tree(net, aff_bus)
	sub_names = [tup for tup in sub_tree.edges]
	sub_lines = [x for x in tree if (x.get('bus1', '').split('.')[0], x.get('bus2', '').split('.')[0]) in sub_names]
	return sub_lines

def voltagePlot(filePath, PU=True):
	'''Voltage plotting routine. Creates 'voltages.csv' and 'Voltage [PU|V].png' in directory of input file.'''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	runDSS(filePath)
	runDssCommand(f'export voltages "{dssFileLoc}/volts.csv"')
	voltageDF = pd.read_csv(dssFileLoc + '/volts.csv')
	plt.title('Voltage Profile')
	plt.ylabel('Count')
	if PU:
		for i in range(1, 4): 
			volt_ind = ' pu' + str(i)
			plt.hist(voltageDF[volt_ind], label='Phase ' + str(i))
		plt.xlabel('Voltage [PU]')
		plt.legend()
		plt.savefig(dssFileLoc + '/Voltage Profile [PU].png')
	else:
		# plt.axis([1, 7, 2000, 3000]) # Ignore sourcebus-much greater-for overall magnitude.
		for i in range(1, 4): 
			mag_ind = ' Magnitude' + str(i)
			plt.hist(voltageDF[mag_ind], label='Phase ' + str(i))
		plt.xlabel('Voltage [V]')
		plt.legend()
		plt.savefig(dssFileLoc + '/Voltage Profile [V].png')
	plt.clf()

def get_bus_kv_mappings(path_to_dss, logToFile=False, logFilePath=None):
	''' Returns a map {bus_name:base_kv} where base_kv is the line-to-neutral voltage.'''
	# voltagePlot(path_to_dss)
	runDSS(path_to_dss, logToFile=logToFile, logFilePath=logFilePath)
	runDssCommand('export voltages volts.csv', logToFile=logToFile, logFilePath=logFilePath)
	file_loc = os.path.dirname(os.path.abspath(path_to_dss))
	volt_file_loc = f'{file_loc}/volts.csv'
	volt_df = pd.read_csv(volt_file_loc)
	volt_df['kv_ln'] = volt_df[' BasekV']/math.sqrt(3)
	out_data = volt_df[['Bus','kv_ln']].values.tolist()
	out_dict = {x[0].lower():x[1] for x in out_data}
	return out_dict

def get_bus_phasing_map(path_to_dss):
	''' Returns a map {bus_name:phase_list} where phase list a list of all powered phases (e.g. [1,3]).'''
	voltagePlot(path_to_dss)
	path_to_dss = os.path.abspath(path_to_dss)
	file_loc = os.path.dirname(path_to_dss)
	volt_file_loc = f'{file_loc}/volts.csv'
	volt_df = pd.read_csv(volt_file_loc).set_index('Bus')
	bus_df = volt_df.transpose()
	results = {bus:[] for bus in bus_df.columns}
	for bus in bus_df.columns:
		for i, pu in enumerate([' pu1', ' pu2', ' pu3']):
			if bus_df[bus][pu] > 0:
				results[bus].append(i + 1)
	return results

def get_meter_buses(dss_file):
	''' return all bus names which have loads attached (i.e. meter buses.)'''
	tree = dssConvert.dssToTree(dss_file)
	meters = [x for x in tree if x.get('object','N/A').startswith('load.')]
	bus_names = [x['bus1'] for x in meters if 'bus1' in x]
	just_name_no_conn = [x.split('.')[0] for x in bus_names]
	return just_name_no_conn

def get_all_buses( DSS_FILE ):
	''' return all bus names in a .dss file '''
	tree = dssConvert.dssToTree( DSS_FILE )
	bus_list = []
	for item in tree:
		for key in item:
			if key == 'bus':
				bus_list.append( item[key])
	return bus_list

def currentPlot(filePath):
	''' Current plotting function.'''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	runDSS(filePath)
	runDssCommand(f'export currents "{dssFileLoc}/currents.csv"')
	currentDF = pd.read_csv(dssFileLoc + '/currents.csv')
	plt.xlabel('Current [A]')
	plt.ylabel('Count')
	plt.title('Current Profile')
	for i in range(1, 3):
		for j in range(1, 4):
			cur_ind = ' I' + str(i) + '_' + str(j)
			plt.hist(currentDF[cur_ind], label=cur_ind)
	plt.legend()
	plt.savefig(dssFileLoc + '/Current Profile.png')
	plt.clf()

def networkPlot(filePath, figsize=(20,20), output_name='networkPlot.png', show_labels=True, node_size=300, font_size=8):
	''' Plot the physical topology of the circuit.
	Returns a networkx graph of the circuit as a bonus. '''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	runDSS(filePath)
	coords = getCoords(filePath)
	runDssCommand(f'export voltages "{dssFileLoc}/volts.csv"')
	volts = pd.read_csv(dssFileLoc + '/volts.csv')
	coords.columns = ['Bus', 'X', 'Y', 'radius']
	G = nx.Graph()
	# Get the coordinates.
	pos = {}
	for index, row in coords.iterrows():
		try:
			bus_name = str(int(row['Bus']))
		except:
			bus_name = row['Bus']
		G.add_node(bus_name)
		pos[bus_name] = (float(row['X']), float(row['Y']))
	# Get the connecting edges using Pandas.
	lines = dss.utils.lines_to_dataframe()
	edges = []
	for index, row in lines.iterrows():
		#HACK: dss upercases everything in the coordinate output.
		bus1 = row['Bus1'].split('.')[0].upper()
		bus2 = row['Bus2'].split('.')[0].upper()
		edges.append((bus1, bus2))
	G.add_edges_from(edges)
	# Remove buses withouts coords
	no_pos_nodes = set(G.nodes()) - set(pos)
	if len(no_pos_nodes) > 0:
		warnings.warn(f'Node positions missing for {no_pos_nodes}')
	G.remove_nodes_from(list(no_pos_nodes))
	# We'll color the nodes according to voltage.
	volt_values = {}
	labels = {}
	for index, row in volts.iterrows():
		if row['Bus'].upper() in [x.upper() for x in pos]:
			volt_values[row['Bus']] = row[' pu1']
			labels[row['Bus']] = row['Bus']
	colorCode = [volt_values.get(node, 0.0) for node in G.nodes()]
	# Start drawing.
	plt.figure(figsize=figsize) 
	nodes = nx.draw_networkx_nodes(G, pos, node_color=colorCode, node_size=node_size)
	edges = nx.draw_networkx_edges(G, pos)
	if show_labels:
		nx.draw_networkx_labels(G, pos, labels, font_size=font_size)
	plt.colorbar(nodes)
	plt.legend()
	plt.title('Network Voltage Layout')
	plt.tight_layout()
	plt.savefig(dssFileLoc + '/' + output_name)
	plt.clf()
	return G

def dss_to_nx_fulldata( dssFilePath, tree=None, fullData = True ):
	''' Combines dss_to_networkX and opendss.networkPlot together.

	Creates a networkx directed graph from a dss files. If a tree is provided, build graph from that instead of the file.
	Adds data to certain DSS node types

	args:
		filepath ( PathLib path ):- dss file path
		tree (list): None - tree representation of dss file
	return:
		A networkx graph of the circuit 

	Each node is tied with an "object" attribute to identify object type.
		ex: G.add_node(bus, pos=(float_x, float_y), object='bus')

	Load objects: object='load'
		Supported data: bus1, phases, conn, kv, kw, kvar
	Line objects: 'object': 'line'
		Supported data:
	Transformer objects: 'object': 'transformer'
		Supported data:
	Generator objects: object='generator'
		Supported data: kv, kw, pf, yearly
	Storage objects: object='storage'
		Supported data: phases, kv, kwrated, dispmode, kwhstored, kwhrated
	PVSystem object: object='pvsystem'
		Support data: phases, kv, kva, irradiance, pmpp, pf
	'''
	if tree == None:
		tree = dssConvert.dssToTree( dssFilePath )

	G = nx.DiGraph()
	pos = {}
	# Add nodes for buses
	setbusxyList = [x for x in tree if '!CMD' in x and x['!CMD'] == 'setbusxy']
	x_coords = [x['x'] for x in setbusxyList if 'x' in x]
	y_coords = [x['y'] for x in setbusxyList if 'y' in x]
	bus_names = [x['bus'] for x in setbusxyList if 'bus' in x]
	for bus, x, y in zip( bus_names, x_coords, y_coords):
		float_x = float(x)
		float_y = float(y)
		G.add_node(bus, pos=(float_x, float_y), object='bus')
		pos[bus] = (float_x, float_y)

	# Add edges from lines
	lines = [x for x in tree if x.get('object', 'N/A').startswith('line.')]
	lines_bus1 = [x.split('.')[0] for x in [x['bus1'] for x in lines if 'bus1' in x]]
	lines_bus2 = [x.split('.')[0] for x in [x['bus2'] for x in lines if 'bus2' in x]]
	lines_name = [x.split('.')[1] for x in [x['object'] for x in lines if 'object' in x]]

	# Lines FullData
	# phases, length, units, linecode, seasons, ratings, normamps, emergamps, r1, r0, x1, x9, c1, c0

	edges = []
	for bus1, bus2, name in zip( lines_bus1, lines_bus2, lines_name ):
		edges.append( (bus1, bus2, {'color': 'blue', 'object': 'line', 'line_name': name}) )
	G.add_edges_from( edges )

	# new object=transformer.reg1 buses=[650.1,rg60.1] phases=1 bank=reg1 xhl=0.01 kvas=[1666,1666] kvs=[2.4,2.4] %loadloss=0.01
	transformers = [x for x in tree if x.get('object', 'N/A').startswith('transformer.')]
	transformer_name = [x.split('.')[1] for x in [x['object'] for x in transformers if 'object' in x]]
	transformer_buses_string = [x['buses'] for x in transformers if 'buses' in x] #['x.y,x.y,x.y']
	transformer_bus_names_full_conn = [ x.strip('[]').split(',') for x in transformer_buses_string] #['x.y', 'x.y', 'x.y']
	transformer_buses_names_only = [[prefix.split('.')[0].strip() for prefix in sublist.strip('[]').split(',')] for sublist in transformer_buses_string] #['x', 'x', 'x']
	transformer_edges = []
	for buses_full_conn, buses_name_only, transformer_name in zip(transformer_bus_names_full_conn, transformer_buses_names_only, transformer_name ):
		# new object=transformer.t_3160 windings=3 buses=[bus3160.3.0,t_bus3160_l.1.0,t_bus3160_l.0.2] phases=1 xhl=2.76 xht=2.76 xlt=1.84 conns=[wye,wye,wye] kvs=[7.9677,0.12,0.12] kvas=[25,25,25] taps=[1,1,1] %rs=[0.7,1.4,1.4]
		# [bus3160.3.0,t_bus3160_l.1.0,t_bus3160_l.0.2]
		# [bus3160, t_bus3160_l]
		if len(buses_name_only) == 2:
			bus0 = buses_name_only[0]
			bus1 = buses_name_only[1]
			bus1_full_conn_name = buses_full_conn[1]
			transformer_edges.append ( (bus0, bus1, {'object': 'transformer', 'transformer_name': transformer_name, 'transformer_1': bus1_full_conn_name }) )
		elif len(buses_name_only) == 3:
			bus0 = buses_name_only[0]
			bus1 = buses_name_only[1]
			bus1_full_conn_name = buses_full_conn[1]
			bus2_full_conn_name = buses_full_conn[2]
			transformer_edges.append ( (bus0, bus1, {'object': 'transformer', 'transformer_name': transformer_name,
																						'transformer_1': bus2_full_conn_name,
																						'transformer_2': bus2_full_conn_name}) )
		# Need to make this bullet proof for any number of transformers
	G.add_edges_from( transformer_edges )

	if fullData:
	#  %loadloss=0.01
		transformer_edges_with_attributes = {}
		transformer_phases = [x['phases'] for x in transformers if 'phases' in x]
		transformer_bank = [x['bank'] for x in transformers if 'bank' in x]
		transformer_xhl = [x['xhl'] for x in transformers if 'xhl' in x]
		transformer_kvas = [x['kvas'] for x in transformers if 'kvas' in x]
		transformer_kvs = [x['kvs'] for x in transformers if 'kvs' in x]
		transformer_loadloss = [x['loadloss'] for x in transformers if 'loadloss' in x]
	# 	for t_edge, phase, bank, xhl_val, kvas_val, kvs_val, loadloss_val in zip(transformer_edges, transformer_phases, transformer_bank, transformer_xhl, transformer_kvas, transformer_kvs, transformer_loadloss):
	# 			t_edge_nodes = (t_edge[0], t_edge[1])
	# 			transformer_edges_with_attributes[t_edge_nodes] = { "phases": phase, "bank": bank, "xhl": xhl_val, "kvas": kvas_val, "kvs": kvs_val, "loadloss": loadloss_val }
	# 			print( '{ "phases": phase, "bank": bank, "xhl": xhl_val, "kvas": kvas_val, "kvs": kvs_val, "loadloss": loadloss_val } ')
	# 			print( "t_edge_nodes: ", t_edge_nodes )
	# 	nx.set_edge_attributes( G, transformer_edges_with_attributes )
	
	loads = [x for x in tree if x.get('object', 'N/A').startswith('load.')] # This is an orderedDict
	load_names = [x['object'].split('.')[1] for x in loads if 'object' in x and x['object'].startswith('load.')]
	load_bus = [x.split('.')[0] for x in [x['bus1'] for x in loads if 'bus1' in x]]
	for load, bus in zip(load_names, load_bus):
		pos_tuple_of_bus = pos[bus]
		G.add_node(load, pos=pos_tuple_of_bus, object='load' )
		# Lines between buses and loads
		G.add_edge( bus, load )
		pos[load] = pos_tuple_of_bus
	if fullData:
		# Attributes for all loads
		load_phases = [x['phases'] for x in loads if 'phases' in x]
		load_conn = [x['conn'] for x in loads if 'conn' in x]
		load_kv = [x['kv'] for x in loads if 'kv' in x]
		load_kw = [x['kw'] for x in loads if 'kw' in x]
		load_kvar = [x['kvar'] for x in loads if 'kvar' in x]
		for load, bus, phases, conn, kv, kw, kvar in zip( load_names, load_bus, load_phases, load_conn, load_kv, load_kw, load_kvar):
			G.nodes[load]['bus1'] = bus
			G.nodes[load]['phases'] = phases
			G.nodes[load]['conn'] = conn
			G.nodes[load]['kv'] = kv
			G.nodes[load]['kw'] = kw
			G.nodes[load]['kvar'] = kvar

	# Need to add data for transformers
	# Some have windings.

	# Generators
	# Are there generators? If so, find them and add them as nodes. Their location is the same as their bus.
	generators = [x for x in tree if x.get('object', 'N/A').startswith('generator.')]
	gen_names = [x['object'].split('.')[1] for x in generators if 'object' in x and x['object'].startswith('generator.')]
	gen_bus1 = [x.split('.')[0] for x in [x['bus1'] for x in generators if 'bus1' in x]]
	for gen, bus_for_positioning, in zip( gen_names, gen_bus1, ):
		G.add_node( gen, pos=pos[bus_for_positioning], object='generator')
		pos[gen] = pos[bus_for_positioning]
		G.add_edge( bus_for_positioning, gen )
		# Need to add gen betwen bus and node.
		# but if what is between them is a transformer, then it'll get removed. then there would be an edge between a deleted node and the generator node.. it has to between the bus.. now im confused.
	# Generator FullData
	if fullData:
		gen_phases = [x['phases'] for x in generators if 'phases' in x]
		gen_kv = [x['kv'] for x in generators if 'kv' in x]
		gen_kw = [x['kw'] for x in generators if 'kw' in x]
		gen_pf = [x['pf'] for x in generators if 'pf' in x]
		gen_yearly = [x['yearly'] for x in generators if 'yearly' in x]
		for gen, phases, kv, kw, pf, yearly in zip( gen_names, gen_phases, gen_kv, gen_kw, gen_pf, gen_yearly ):
			G.nodes[gen]['bus1'] = bus_for_positioning
			G.nodes[gen]['phases'] = phases
			G.nodes[gen]['kv'] = kv
			G.nodes[gen]['kw'] = kw
			G.nodes[gen]['pf'] = pf
			G.nodes[gen]['yearly'] = yearly
	# Storage
	# Are there storage objects? If so, find them and add them as nodes. Their location is the same as their bus.
	storage = [x for x in tree if x.get('object', 'N/A').startswith('storage.')]
	storage_names = [x['object'].split('.')[1] for x in storage if 'object' in x and x['object'].startswith('storage.')]
	storage_bus1 = [x.split('.')[0] for x in [x['bus1'] for x in storage if 'bus1' in x]]
	for stor_name, bus in zip(storage_names, storage_bus1):
		G.add_node( stor_name, pos=pos[bus], object='storage')
		pos[stor_name] = pos[bus]
		G.add_edge( bus, stor_name)
	# Storage FullData
	if fullData: 
		storage_phases = [x['phases'] for x in storage if 'phases' in x]
		storage_kv = [x['kv'] for x in storage if 'kv' in x]
		storage_kwrated = [x['kwrated'] for x in storage if 'kwrated' in x]
		storage_dispmode = [x['dispmode'] for x in storage if 'dispmode' in x]
		storage_kwhstored = [x['kwhstored '] for x in storage if 'kwhstored ' in x]
		storage_kwhrated = [x['kwhrated'] for x in storage if 'kwhrated' in x]
		for stor_name, phase, kv, kwr, dispmode, kwhs, kwhr in zip( storage_names, storage_phases, storage_kv, storage_kwrated, storage_dispmode, storage_kwhstored, storage_kwhrated):
			G.nodes[stor_name]['bus1'] = bus
			G.nodes[stor_name]['phases'] = phase
			G.nodes[stor_name]['kv'] = kv
			G.nodes[stor_name]['kwrated'] = kwr
			G.nodes[stor_name]['dispmode'] = dispmode
			G.nodes[stor_name]['kwhstored'] = kwhs
			G.nodes[stor_name]['kwhrated'] = kwhr
	# PVSystem
	# Are there pvsystem objects? If so, find them and add them as nodes. Their location is the same as their bus.
	pvsystem = [x for x in tree if x.get('object', 'N/A').startswith('pvsystem.')]
	pvsystem_names = [x['object'].split('.')[1] for x in pvsystem if 'object' in x and x['object'].startswith('pvsystem.')]
	pvsystem_bus1 = [x.split('.')[0] for x in [x['bus1'] for x in pvsystem if 'bus1' in x]]
	for pvs_name, bus in zip(pvsystem_names, pvsystem_bus1):
		G.add_node( pvs_name, pos=pos[bus], object='pvsystem')
		pos[pvs_name] = pos[bus]
		G.add_edge( bus, pvs_name )
	# PVSystem FullData
	if fullData:
		pvsystem_phases = [x['phases'] for x in pvsystem if 'phases' in x]
		pvsystem_kv = [x['kv'] for x in pvsystem if 'kv' in x]
		pvsystem_kva = [x['kva'] for x in pvsystem if 'kva' in x]
		pvsystem_irradiance = [x['irradiance'] for x in pvsystem if 'irradiance' in x]
		pvsystem_pmpp = [x['pmpp'] for x in pvsystem if 'pmpp' in x]
		pvsystem_pf = [x['pf'] for x in pvsystem if 'pf' in x]
		for pvs_name, phase, kv, kva, irra, pmpp, pf in zip( pvsystem_names, pvsystem_phases, pvsystem_kv, pvsystem_kva, pvsystem_irradiance, pvsystem_pmpp, pvsystem_pf):
			G.nodes[pvs_name]['bus1'] = bus
			G.nodes[pvs_name]['phases'] = phase
			G.nodes[pvs_name]['kv'] = kv
			G.nodes[pvs_name]['kva'] = kva
			G.nodes[pvs_name]['irradiance'] = irra
			G.nodes[pvs_name]['pmpp'] = pmpp
			G.nodes[pvs_name]['pf'] = pf
	return G, pos

def THD(filePath):
	''' Calculate and plot total harmonic distortion. '''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	bus_coords = getCoords(filePath)
	runDssCommand('Solve mode=harmonics')
	runDssCommand('Export voltages "' + dssFileLoc + '/voltharmonics.csv"')
	# Clean up temp file.
	try:
		base = os.path.basename(filePath)
		fnameMinusExt = os.path.splitext(base)[0]
		os.remove('{}_SavedVoltages.dbl'.format(fnameMinusExt))
	except:
		pass
	voltHarmonics = pd.read_csv(dssFileLoc + '/voltharmonics.csv')
	bus_coords.columns = ['Bus', 'X', 'Y', 'radius']
	voltHarmonics.columns.str.strip()
	# for index, row in voltHarmonics.iterrows():
	voltHarmonics['THD'] = (voltHarmonics[' Magnitude1'] + voltHarmonics[' Magnitude2'] + voltHarmonics[' Magnitude3'])/3
	plt.hist(voltHarmonics['THD'])
	plt.xlabel('THD [Avg%]')
	plt.ylabel('Count')
	plt.title('Total Harmonic Distortion')
	plt.savefig(dssFileLoc + '/THD.png')
	plt.clf()

def dynamicPlot(filePath, time_step_s=0.001, iterations=100, at_elem='Vsource.SOURCE'):
	''' Do a dynamic, long-term study of the powerflow. time_step is in seconds. '''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))	
	runDSS(filePath)
	runDssCommand(f'new object=monitor.dynamic_monitor element={at_elem}')
	runDssCommand('solve')
	runDssCommand(f'solve mode=dynamics stepsize={time_step_s} number={iterations}')
	runDssCommand('export monitor dynamic_monitor filename=dynamic_monitor.csv')
	circ_name = dss.Circuit.Name()
	allDF = pd.read_csv(f'{dssFileLoc}/{circ_name}_Mon_dynamic_monitor.csv')
	fig, axs = plt.subplots(2)
	for vname in [' V1',' V2',' V3']:
		axs[0].plot(allDF[vname], label=vname)
	for cname in [' I1',' I2',' I3']:
		axs[1].plot(allDF[cname], label=cname)
	# # plt.xticks(range(iterations), [time_step_s * x for x in range(iterations)])
	axs[0].set_xlabel('Time [step]')
	axs[1].set_xlabel('Time [step]')
	axs[0].set_ylabel('Voltage [V]')
	axs[1].set_ylabel('Current [A]')
	axs[0].legend()
	fig.suptitle(f'Dynamic Simulation at {at_elem}')
	fig.tight_layout()
	fig.savefig(dssFileLoc + '/DynamicPowerPlot.png')

def faultPlot(filePath, faultCommand):
	''' Plot fault study for filePath dss and faultCommand (valid opendss fault str) ''' 
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	runDSS(filePath)
	runDssCommand(faultCommand)
	runDssCommand('Solve Mode=FaultStudy')
	runDssCommand('Export fault "' + dssFileLoc + '/faults.csv"')
	faultDF = pd.read_csv(dssFileLoc + '/faults.csv')
	faultDF.columns = faultDF.columns.str.strip()
	plt.xlabel('Bus Index')
	plt.ylabel('Current [Amps]')
	plt.yscale('log')
	plt.title('Fault Study')
	xpos = [x*4 for x in range(len(faultDF['Bus']))]
	plt.bar(xpos, faultDF['1-Phase'], label='1-Phase to Ground [A]')
	plt.bar([x+1 for x in xpos], faultDF['3-Phase'], label='3-Phase to Ground [A]')
	plt.bar([x+2 for x in xpos], faultDF['L-L'], label='Line-to-Line [A]')
	plt.xticks([x+1 for x in xpos], [int(x/4) for x in xpos])
	plt.legend(loc='upper center')
	plt.savefig(dssFileLoc + '/Fault Currents.png')
	plt.clf()

def capacityPlot(filePath):
	''' Plot power vs. distance '''
	dssFileLoc = os.path.dirname(os.path.abspath(filePath))
	runDSS(filePath)
	runDssCommand('Export Capacity "' + dssFileLoc + '/capacity.csv"')
	capacityDF = pd.read_csv(dssFileLoc + '/capacity.csv')
	plt.title('Transformer Loading')
	plt.ylabel('Loading Normal Rating [%]')
	plt.xlabel('Component Index')
	# print(capacityDF)
	x = capacityDF['Name']
	x_pos = range(len(x))
	plt.bar(
		x_pos,
		capacityDF[' %normal'],
		color='red'
	)
	plt.tight_layout() # Otherwise the right y-label is slightly clipped
	# plt.xticks(x_pos, x) # Doesn't fit. Names too long.
	# plt.legend()
	plt.savefig(dssFileLoc + '/Capacity Profile.png')
	plt.clf()
	
def voltageCompare(in1, in2, saveascsv=False, with_plots=False, outdir='', outfilebase='voltageCompare'):
	'''Compares two instances of the information provided by the 'Export voltages' opendss command and outputs 
	the maximum error ([0,100]% and absolute difference in [-inf,inf] volts or [-180,180] degrees) encountered for any value compared. If the 'keep_output' flag is set to 'True', also 
	outputs a file that describes the maximum, average, and minimum error encountered for each column. Use the 
	'output_filename' parameter to set the output file name. Inputs can be formatted as a .dss file of voltages
	output by OpenDSS, or as a dataframe of voltages obtained using the OMF's getVoltages().'''
	#TODO: rewrite description
	ins = [in1, in2]
	txtins = [x for x in ins if type(x)==str and 'dss'==x.lower().split('.')[-1]]
	memins = [x for x in ins if type(x)==pd.DataFrame]
	assert (len(txtins)+len(memins))==2, 'Inputs must either be a .dss file of voltages as output by the OpenDss \'Export Voltages\' command, or a dataframe of voltages output by the omf method \'getVoltages()\'.'
	# Convert .csvs to dataframes and add to the list
	for pth in txtins:
		df = pd.DataFrame()
		df = pd.read_csv(pth, header=0)
		df.index = df['Bus']
		df.drop(labels='Bus', axis=1, inplace=True)
		df = df.astype(float, copy=True)
		memins.append(df)
	# Which has more rows? We'll define the larger one to be 'avolts'. This is also considered the 'theoretical' set.
	foob = 0 if len(memins[0].index) > len(memins[1].index) else 1
	avolts = memins[foob]
	foob = 1-foob # returns 0 if foob==1 ; returns 1 if foob==0
	bvolts = memins[foob]
	# merge bvolts into avolts
	cols = bvolts.columns
	bvolts.columns = ["b_" + x for x in cols]
	ins = avolts.join(bvolts)
	del avolts
	del bvolts
	ins = ins.dropna()
	cols = [c for c in cols if (not c.startswith(' pu')) and (not c.startswith(' Node'))]
	colsP = [c + ' (0-100%)' for c in cols]
	colsD = []
	for c in cols:
		if c.lower().startswith(' basekv'):
			colsD.append(c + ' (kV)')
		if c.lower().startswith(' magnitude'):
			colsD.append(c + ' (V)')
		if c.lower().startswith(' angle'):
			colsD.append(c + ' (deg)')

	resultErrD = pd.DataFrame(index=ins.index, columns=colsD)
	resultErrP = pd.DataFrame(index=ins.index, columns=colsP)

	for i, col in enumerate(cols):
		for row in ins.index:
			ina = ins.loc[row,col]
			inb = ins.loc[row,"b_" + col]
			resultErrP.loc[row,colsP[i]] = 100*(ina - inb)/ina if ina!=0 else 0
			resultErrD.loc[row,colsD[i]] = ina - inb
	# Construct results
	resultSummP = pd.DataFrame(index=['Max %Err', 'Avg %Err', 'Min %Err', 'RMSPE'], columns=colsP)
	resultSummD = pd.DataFrame(index=['Max Diff', 'Avg Diff', 'Min Diff', 'RMSE'], columns=colsD)
	for cp in colsP:
		resultSummP.loc['Max %Err',cp] = resultErrP.loc[:,cp].max(skipna=True)
		resultSummP.loc['Avg %Err',cp] = resultErrP.loc[:,cp].mean(skipna=True)
		resultSummP.loc['Min %Err',cp] = resultErrP.loc[:,cp].min(skipna=True)
		resultSummP.loc['RMSPE',cp] = math.sqrt((resultErrP.loc[:,cp]**2).mean())
	for cd in colsD:
		resultSummD.loc['Max Diff',cd] = resultErrD.loc[:,cd].max(skipna=True)
		resultSummD.loc['Avg Diff',cd] = resultErrD.loc[:,cd].mean(skipna=True)
		resultSummD.loc['Min Diff',cd] = resultErrD.loc[:,cd].min(skipna=True)
		resultSummD.loc['RMSE',cd] = math.sqrt((resultErrD.loc[:,cd]**2).mean())
	if saveascsv:
		outroot = outdir + '/' + outfilebase

		resultErrP.dropna(inplace=True)
		resultSummP.to_csv(outroot + '_Perc.csv', header=True, index=True, mode='w')
		emptylineP = pd.DataFrame(index=[''],columns=colsP)
		emptylineP.to_csv(outroot + '_Perc.csv', header=False, index=True, mode='a')
		resultErrP.to_csv(outroot + '_Perc.csv', header=True, index=True, mode='a')
		
		resultErrD.dropna(inplace=True)
		resultSummD.to_csv(outroot + '_Diff.csv', header=True, index=True, mode='w')
		emptylineD = pd.DataFrame(index=[''],columns=colsD)
		emptylineD.to_csv(outroot + '_Diff.csv', header=False, index=True, mode='a')
		resultErrD.to_csv(outroot + '_Diff.csv', header=True, index=True, mode='a')
	if with_plots:
		# Produce boxplots to visually analyze the residuals
		from matplotlib.pyplot import boxplot
		magcols = [c for c in colsD if c.lower().startswith(' magnitude')]
		bxpltMdf = pd.DataFrame(index=ins.index,data=resultErrD,columns=magcols)
		bxpltM = []
		for item in magcols:
			bxpltM.append(bxpltMdf[item])
		figM, axM = plt.subplots()
		axM.set_title('Boxplot of Residuals: Voltage Magnitude (V)')
		plt.xticks(rotation=45)
		axM.set_xticklabels(magcols)
		axM.boxplot(bxpltM)
		figM.savefig(outroot + '_boxplot_Mag.png', bbox_inches='tight')
		plt.close()
		angcols = [c for c in colsD if c.lower().startswith(' angle')]
		bxpltAdf = pd.DataFrame(data=resultErrD[angcols],columns=angcols)
		bxpltA = []
		for item in angcols:
			bxpltA.append(bxpltAdf[item])
		figA, axA = plt.subplots()
		axA.set_title('Boxplot of Residuals: Voltage Angle (deg)')
		plt.xticks(rotation=45)
		axA.set_xticklabels(angcols)
		axA.boxplot(bxpltA)
		figA.savefig(outroot + '_boxplot_Ang.png', bbox_inches='tight')
		plt.close()
		for i,c in enumerate(cols):
			# construct a dataframe of busname, input, output, and residual
			dat = pd.concat([ins[c],ins['b_' + c],resultErrP[colsP[i]],resultErrD[colsD[i]]], axis=1,join='inner')
			dat.columns = ['buses+','buses-','residuals_P','residuals_D'] # buses+ denotes the value (voltage or angle) of the circuit with more buses; buses- denotes that of the circuit with fewer
			dat = dat.sort_values(by=['buses-','buses+'], ascending=True, na_position='first')
			# Produce plot of residuals
			#pltlenR = math.ceil(len(dat['residuals_P'])/2)
			#figR, axR = plt.subplots(figsize=(pltlenR,12))
			#axR.plot(dat['buses-'], 'k.', alpha=0.15)
			figR, axR = plt.subplots()
			axR.plot(dat['buses-'], dat['residuals_D'], 'k.', alpha=0.15)
			axR.set_title('Plot of Residuals: ' + colsD[i])
			#plt.xticks(rotation=45)
			axR.set_xlabel('Value for circuit with fewer buses: ' + colsD[i])
			axR.set_ylabel('Value of Residual')
			figR.savefig(outroot + '_residualplot_' + colsD[i] +'_.png', bbox_inches='tight')
			plt.close()
			# Produce scatter plots
			figS, axS = plt.subplots()
			axS.set_title('Scatter Plot: ' + colsD[i])
			axS.plot(dat['buses-'], dat['buses+'], 'k.', alpha=0.15)
			axS.set_xlabel('Value of ' + colsD[i] + ' for circuit with fewer buses')
			axS.set_ylabel('Value of ' + colsD[i] + ' for circuit with more buses')
			figS.savefig(outroot + '_scatterplot_' + colsD[i] +'_.png', bbox_inches='tight')
			plt.close()
	return resultSummP, resultSummD

def getVoltages(dssFilePath, keep_output=False, outdir='', output_filename='voltages.csv'):
	# TODO: rename to voltageGet for consistency with other functions?
	'''Obtains the OpenDss voltage output for a OpenDSS circuit definition file (*.dss). Input path 
	can be fully qualified or not. Set the 'keep_output' flag to 'True' to save output to the input 
	file's directory as 'voltages.csv',	or specify a filename for the output through the 
	'output_filename' parameter (i.e. '*.csv').'''
	dssFileLoc = os.path.dirname(os.path.abspath(dssFilePath))
	runDSS(os.path.abspath(dssFilePath))
	if outdir!='':
		outdir = outdir + '/'
	voltfile = dssFileLoc + '/' + outdir + output_filename
	runDssCommand('Export voltages "' + voltfile + '"')
	volts = pd.read_csv(voltfile, header=0)
	volts.index = volts['Bus']
	volts.drop(labels='Bus', axis=1, inplace=True)
	volts = volts.astype(float, copy=True)
	if not keep_output:
		os.remove(voltfile)
	return volts

def applyCnxns(tree):
	'''Gathers and applies connection information to dss lines and buses.'''
	relevantObjs = ['capacitor','line','transformer','load','reactor','monitor','energymeter','generator','pvsystem', 'storage', 'vsource','relay','fuse']
	# make a mapping between an object's name and its index in tree
	name2key = {v.get('bus', None):i for i,v in enumerate(tree) if v.get('!CMD','NC')=='setbusxy'}
	name2key.update({v.get('object', None):i for i,v in enumerate(tree) if v.get('!CMD','NC')=='new'})
	for obj in tree:
		objid = obj.get('object','None')
		if objid.split('.')[0] not in relevantObjs:
			continue
		cnxns = []
		for k,v in obj.items():
			if k == 'buses':
				bb = v
				bb = bb.replace(']','')
				bb = bb.replace('[','')
				bb = bb.split(',')
				for b in bb:
					cnxns.append(b.split('.')[0])
			elif k in ['bus','bus1','bus2']:
				cnxns.append(v.split('.')[0])
			elif k in ['element','monitoredobj']:
				cnxns.append(v)
		for cnxn in cnxns:
			if cnxn in name2key:
				# get existing connections, append, and reassign to tree
				treebusobj = tree[name2key[cnxn]]
				if '!CNXNS' in treebusobj:
					bb = treebusobj['!CNXNS']
					treebusobj['!CNXNS'] = bb.replace(']', ',' + objid + ']')
				else:
					treebusobj['!CNXNS'] = '[' + objid + ']'
			elif len(cnxn.split('.'))==1:
				# make a new entry in the tree and update name2key
				from collections import OrderedDict 
				newobj = OrderedDict([
					('!CMD','new'),
					('object',cnxn),
					('x','0'),
					('y','0'),
					('!CNXNS','[' + objid + ']')
					])
				tree.append(newobj)
				newdict = {cnxn:len(tree)-1}
				name2key.update(newdict)
			else:
				print('opendss.applyCnxns() reports an unprocessed item: %s\n'%(cnxn))
	return tree

def removeCnxns(tree):
	"""
	Perform remove cnxns processing for the wrapped solver workflow.
	"""
	for i,obj in enumerate(tree.copy()):
		if obj.get('!CNXNS','NCX')!='NCX':
			del tree[i]['!CNXNS']
	return tree

def reduceCircuit(tree):
	''' Apply all 3 circuit reduction functions. '''
	tree = mergeContigLines(tree)
	tree = rollUpTriplex(tree)
	tree = rollUpLoadTransformer(tree)
	return tree

def _mergeContigLinesOnce(tree):
	'''Reduces circuit complexity by combining adjacent line segments having identical configurations.'''
	# Applicable circuit model: [top bus]-[top line]-[middle bus]-[bottom line]-[bottom bus]-...
	from copy import deepcopy
	treeids = range(0,len(tree),1)
	tree = dict(zip(treeids,tree))
	name2key = {v.get('object', None):k for k,v in tree.items()}
	name2key.update({v.get('bus', None):k for k,v in tree.items() if v.get('!CMD', None) == 'setbusxy'})
	# Iterate through treecopy and perform any modifications directly on tree. Note that name2key can be used om either tree or treecopy.
	treecopy = deepcopy(tree)
	removedids = []
	for topobj in treecopy.values():
		top = topobj.copy()
		topid = top.get('object','None')
		# is this a line object?
		if not topid.startswith('line.'):
			continue
		# has this line already been removed?
		if topid in removedids:
			continue
		# Is the top a switch? Let's skip these for now. 
		# TODO: handle switches when merging them with adjacent line segments
		if top.get('switch','None') in ['true','yes']:
			continue
		# Get the 'to' bus
		midbusid = top.get('bus2','NA')
		if midbusid=='NA':
			continue 
		midbus = treecopy[name2key[midbusid.split('.')[0]]]
		# Get ids of the relevant objects (other than the top) connected to the parent bus (aka the bottoms)
		bottoms = midbus.get('!CNXNS','None')
		bottoms = bottoms.replace('[','').replace(']','')
		bottoms = bottoms.split(',')
		bottoms.remove(topid)
		# Check for a one-line-in, one-line-out scenario
		if len(bottoms) != 1:
			continue
		botid = bottoms[0]
		bottom = treecopy[name2key[botid]]
		if not bottom.get('object','None').startswith('line.'):
			continue
		# Is the bottom a switch? Let's skip these for now. 
		# TODO: handle switches when merging them with adjacent line segments
		if bottom.get('switch','None') in ['true','yes']:
			continue
		# Does the bottom have any other objects 'attached' to it? If so, we must not remove it. 
		if bottom.get('!CNXNS','NCX')!='NCX':
			continue
		# All checks have passed. Let's combine the top and bottom lines.
		if ('length' in top) and ('length' in bottom):
			# check that the configurations are equal
			diffprops = ['!CMD','object','bus1','bus2','length','!CNXNS'] # we don't care if these values differ between the top and the bottom
			continueFlag = False
			for k,vt in top.items():
				if not k in diffprops:
					vb = bottom.get(k,'None')
					if vt!=vb:
						continueFlag = True
						break
			if continueFlag:
				continueFlag = False
				continue
			# Set top line length = sum of both lines
			newLen = float(top['length']) + float(bottom['length']) # get the new length
			top['length'] = str(newLen)
			# Connect top line to the bottom bus
			top['bus2'] = bottom['bus2']
			tree[name2key[topid]] = top
			# Connect bottom bus to the top line 
			botbus = treecopy[name2key[bottom['bus2'].split('.')[0]]].copy()
			botbcons = botbus.get('!CNXNS','None')
			botbcons = botbcons.replace('[','').replace(']','')
			botbcons = botbcons.split(',')
			if bottom['object'] in botbcons:
				iji = botbcons.index(bottom['object'])
				botbcons[iji] = top['object']
			tstr = '['
			for item in botbcons:
				tstr = tstr + item + ','
			tstr = tstr[:-1] + ']'
			botbus['!CNXNS'] = tstr
			tree[name2key[botbus['bus']]] = botbus
			# Delete the bottom line element and the middle bus			
			removedids.append(bottom['object'])
			del tree[name2key[bottom['object']]]
			removedids.append(midbus['bus'])
			del tree[name2key[midbus['bus']]]
	with open('removed_ids.txt', 'a') as remfile:
		for remid in removedids:
			remfile.write(remid + '\n')
	return [v for k,v in tree.items()] # back to a list of dicts

def mergeContigLines(tree):
	''' merge all lines that are across nodes and have the same config
	topline --to-> node <-from-- bottomline'''
	tree = applyCnxns(tree)
	removedKeys = 1
	if os.path.exists('removed_ids.txt'):
		os.remove('removed_ids.txt')
	while removedKeys != 0:
		treeKeys = len(tree)
		tree = _mergeContigLinesOnce(tree)
		removedKeys = treeKeys - len(tree)
	tree = removeCnxns(tree)
	return tree

def rollUpTriplex(tree):
	'''Remove a triplex line and capture losses in the load it serves by applying enineerging estimates. Applies 
	to instances where one or more loads are connected to a single bus, and that bus is connected to a line which
	is then connected to a transformer.'''
	# Applicable circuit model: [one or more loads]-[bus]-[line]-[bus]-[transformer]-...
	tree = applyCnxns(tree)
	from copy import deepcopy
	from math import sqrt
	treeids = range(0,len(tree),1)
	tree = dict(zip(treeids,tree))
	name2key = {v.get('object', None):k for k,v in tree.items()}
	name2key.update({v.get('bus', None):k for k,v in tree.items() if v.get('!CMD', None) == 'setbusxy'})
	# Iterate through treecopy and perform any modifications directly on tree. Note that name2key can be used on either tree or treecopy.
	treecopy = deepcopy(tree)
	removedids = []
	for obj in treecopy.values():
		objid = obj.get('object','None')
		# Is this a load object? If not, move to next object in treecopy
		if not objid.startswith('load.'):
			continue
		# Get the load's parent bus
		loadbusid = obj.get('bus1','None').split('.')[0]
		loadbus = treecopy[name2key[loadbusid]]
		# Has this loadbus already been removed? if so, move on to the next object in treecopy
		if loadbusid in removedids:
			continue
		# Get everything that is attached to the parent bus
		loadsiblings = loadbus.get('!CNXNS','None')
		loadsiblings = loadsiblings.replace('[','').replace(']','')
		loadsiblings = loadsiblings.split(',')
		# Does the load's bus connect to a single line? If not, move to next object in treecopy
		loads = [x for x in loadsiblings if x.startswith('load.')]
		if len(loadsiblings)-len(loads) != 1:
			continue
		lines = [x for x in loadsiblings if x.startswith('line.')]
		if len(lines) != 1:
			continue
		# Capture the line for later removal
		linetoremove = lines[0]
		# Get the line's parent bus. 
		linebusid = treecopy[name2key[linetoremove]].get('bus1','None').split('.')[0] # bus1='from'; bus2='to'
		linebus = treecopy[name2key[linebusid]]
		# Get everything connected to the linebus
		linesiblings = linebus.get('!CNXNS','None')
		linesiblings = linesiblings.replace('[','').replace(']','')
		linesiblings = linesiblings.split(',')
		# Does the line's bus connect to one transformer? If not, move to next object in treecopy
		xfrmrids = [x for x in linesiblings if x.startswith('transformer.')]
		if len(linesiblings)-len(xfrmrids) != 1:
			continue		
		xfrmrids = list(set(xfrmrids)) # 3-winding xfrmrs often define two connections to the same bus (i.e. split-phase connections)
		if len(xfrmrids) != 1:
			continue
		#everything checks out. Begin modifications.
		# Fix the loads' and linebus' connections and correct kw for losses associated with removed triplex line 
		for load in loads:
			# Set linebus as loads' parent
			load_obj = tree[name2key[load]]
			conncode = load_obj.get('bus1','').split('.',1)[1]
			load_obj['bus1'] = linebusid + '.' + conncode
			# Check number of connections and fix load kw and kv values to capture triplex losses (0.81%)
			conncode = conncode.split('.')
			if '0' in conncode:
				conncode.remove('0') # no losses for grounds.
			load_obj['kw'] = str(float(load_obj.get('kw','0')) * 1.0081)
			#note: Corrections to power factor are negligible because triplex lines are short.
			tree[name2key[load]] = load_obj
			# Add load to linebus connections
			linebus_obj = tree[name2key[linebusid]]
			linebuscons = linebus_obj.get('!CNXNS','None')
			linebuscons = linebuscons.replace('[','').replace(']','')
			linebuscons = linebuscons.split(',')
			if linetoremove in linebuscons:
				linebuscons.remove(linetoremove)
			cstr = '['
			for elm in linebuscons:
				cstr += elm + ','
			cstr += load
			cstr = cstr + ']'
			linebus_obj['!CNXNS'] = cstr
			tree[name2key[linebusid]] = linebus_obj
		# Remove the line and loadbus (if not already removed)
		removedids.append(linetoremove)
		del tree[name2key[linetoremove]]
		removedids.append(loadbusid)
		del tree[name2key[loadbusid]]
	tree = [v for k,v in tree.items()] # back to a list of dicts
	tree = removeCnxns(tree)
	if os.path.exists('removed_ids.txt'):
		os.remove('removed_ids.txt')
	with open('removed_ids.txt', 'a') as remfile:
		for remid in removedids:
			remfile.write(remid + '\n')
	return tree

def rollUpLoadTransformer(tree, combine_loads=True):
	'''Removes a load-serving transformer and captures its losses in the loads it serves by applying 
	an engineering estimate. This process also combines multiple loads into a single representative load. Applies to instances where one or more loads are connected to a 
	single bus, and that bus is connected to a transformer which is connected to a bus.'''
	# Applicable circuit model: [one or more loads]-[bus]-[transformer]-[bus]...
	tree = applyCnxns(tree)
	from copy import deepcopy
	from math import sqrt
	treeids = range(0,len(tree),1)
	tree = dict(zip(treeids,tree))
	name2key = {v.get('object', None):k for k,v in tree.items()}
	name2key.update({v.get('bus', None):k for k,v in tree.items() if v.get('!CMD', None) == 'setbusxy'})
	# Iterate through treecopy and perform any modifications directly on tree. Note that name2key can be used on either tree or treecopy.
	treecopy = deepcopy(tree)
	removedids = []
	for obj in treecopy.values():
		objid = obj.get('object','None')
		# Is this a load object? If not, move to next object in treecopy
		if not objid.startswith('load.'):
			continue
		# Get the load's parent bus
		loadbusid = obj.get('bus1','None').split('.')[0]
		loadbus_obj = treecopy[name2key[loadbusid]]
		# Has this loadbus already been removed? if so, move on to the next object in treecopy
		if loadbusid in removedids:
			continue
		# Get everything that is attached to the parent bus
		loadsiblings = loadbus_obj.get('!CNXNS','None')
		loadsiblings = loadsiblings.replace('[','').replace(']','')
		loadsiblings = loadsiblings.split(',')
		# Does the loadbus connect to a transformer? If not, move to next object in treecopy
		xfrmrids = [x for x in loadsiblings if x.startswith('transformer.')] # only checks for immediately adjacent transformer. Use mergecontiglines first to condense similar line segments
		# Are other devices connected to the loadbus? If so, move to next object in treecopy
		loadids = [x for x in loadsiblings if x.startswith('load.')]
		if len(loadsiblings)-len(xfrmrids) != len(loadids):
			continue
		xfrmrids = list(set(xfrmrids)) # 3-winding xfrmrs often define two connections to the same bus (i.e. split-phase connections)
		if len(xfrmrids) != 1:
			continue
		#everything checks out. Begin modifications.
		# Get xfrmr parent/primary winding bus id
		xfrmrid = xfrmrids[0]
		xfrmr_obj = tree[name2key[xfrmrid]]
		xfrmrcnxns = xfrmr_obj.get('buses','None')
		xfrmrcnxns = xfrmrcnxns.replace('[','').replace(']','')
		xfrmrcnxns = xfrmrcnxns.split(',')
		xfrmrbusid = xfrmrcnxns[0].split('.',1)[0] # by convention, the primary winding is first
		# Get xfrmr primary winding connection code
		xfrmrconncode = xfrmrcnxns[0].split('.',1)[1]
		# Get xfrmr primary winding connection type (i.e. delta/wye)
		xfrmrconntype = xfrmr_obj.get('conns').replace(']','').replace('[','')
		xfrmrconntype = xfrmrconntype.split(',')[0] # by convention, the primary winding is first
		# Get xfrmr primary winding voltage
		#TODO: do we need to check that the base voltages are the same for the secondary windings before setting the load's kv?
		xfrmrkv = xfrmr_obj.get('kvs','None')
		xfrmrkv = xfrmrkv.replace('[','').replace(']','')
		xfrmrkv = xfrmrkv.split(',')
		xfrmrkv = xfrmrkv[0]
		xfrmrphases = [c for c in xfrmrconncode.split('.') if c!='0']
		xfrmrbus_obj = tree[name2key[xfrmrbusid]]
		xfrmrbuscons = xfrmrbus_obj.get('!CNXNS','None')
		xfrmrbuscons = xfrmrbuscons.replace('[','').replace(']','')
		xfrmrbuscons = xfrmrbuscons.split(',')

		load_obj = tree[name2key[objid]]	
		# Connect the load to the xfrmrbus
		load_obj['bus1'] = xfrmrbusid + '.' + xfrmrconncode
		# Set load kv to kv of primary winding.
		load_obj['kv'] = xfrmrkv
		if combine_loads==True:
			# Fix kw values to capture xfrmr losses (2.5%); aggregate kw, kvar, pf with any other sibling loads and correct the number of phases and the parent bus connection.
			newkw = 0
			newkvar = 0
			pfs = []
			for lid in loadids:
				lid_obj = tree[name2key[lid]]
				newkw = newkw + float(lid_obj.get('kw','0'))*1.025
				newkvar = newkvar + float(lid_obj.get('kvar','0'))
				if lid_obj.get('pf','None') != 'None':
					pfs.append(lid_obj.get('pf'))
			load_obj['kw'] = str(newkw)
			if load_obj.get('kvar','None') != 'None':
				load_obj['kvar'] = str(newkvar)
			if len(pfs) >0:
				totpf = 0
				for pf in pfs:
					totpf += float(pf)
				load_obj['pf'] = str(totpf/len(pfs))
			# Correct the number of phases on the load
			if xfrmrconntype == 'delta':
				load_obj['phases'] = str(len(xfrmrphases)-1)
			else:
				load_obj['phases'] = str(len(xfrmrphases))
			# Add load and remove transformer from xfrmrbus connections
			if xfrmrid in xfrmrbuscons:
				xfrmrbuscons.remove(xfrmrid)
			cstr = '['
			for elm in xfrmrbuscons:
				cstr += elm + ','
			cstr += objid + ','
			cstr = cstr[:-1] + ']'
			xfrmrbus_obj['!CNXNS'] = cstr
			# Update the new load and its new parent bus in tree
			tree[name2key[xfrmrbusid]] = xfrmrbus_obj
			tree[name2key[objid]] = load_obj
			# Remove from tree: Aggregated loads, xfrmr, loadbus
			for ld in loadids:
				if ld != objid:
					removedids.append(ld)
					del tree[name2key[ld]]
			removedids.append(xfrmrid)
			del tree[name2key[xfrmrid]]
			removedids.append(loadbusid)
			del tree[name2key[loadbusid]]
		else:
			for lid in loadids:
				lid_obj = tree[name2key[lid]]
				# Fix load kw values to capture xfrmr losses (2.5%)
				tree[name2key[lid["kw"]]] = float(lid_obj.get('kw','0'))*1.025
				# Correct the number of phases on the loads
				if xfrmrconntype == 'delta':
					lid_obj['phases'] = str(len(xfrmrphases)-1)
				else:
					lid_obj['phases'] = str(len(xfrmrphases))
				# update this load in tree
				tree[name2key[lid]] = lid_obj
			# Add load and remove transformer from xfrmrbus connections
			if xfrmrid in xfrmrbuscons:
				xfrmrbuscons.remove(xfrmrid)
			cstr = '['
			for elm in xfrmrbuscons:
				cstr += elm + ','
			for ld in loadids:
				cstr += ld + ','
			cstr = cstr[:-1] + ']'
			xfrmrbus_obj['!CNXNS'] = cstr
			# Update thenew parent bus in tree
			tree[name2key[xfrmrbusid]] = xfrmrbus_obj
			# Remove from tree: xfrmr, loadbus
			removedids.append(xfrmrid)
			del tree[name2key[xfrmrid]]
			removedids.append(loadbusid)
			del tree[name2key[loadbusid]]
	tree = [v for k,v in tree.items()] # back to a list of dicts
	tree = removeCnxns(tree)
	if os.path.exists('removed_ids.txt'):
		os.remove('removed_ids.txt')
	with open('removed_ids.txt', 'a') as remfile:
		for remid in removedids:
			remfile.write(remid + '\n')
	return tree

def _tests():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	import omf
	fpath = ['ieee37.clean.dss','ieee123_solarRamp.clean.dss','iowa240.clean.dss','ieeeLVTestCase.clean.dss','ieee8500-unbal_no_fuses.clean.dss']
	for fname in fpath:
		ckt = omf.omfDir + '/solvers/opendss/' + fname
		print('!!!!!!!!!!!!!! ',ckt,' !!!!!!!!!!!!!!')
		# Test for reduceCircuit, voltageCompare, getVoltages, and runDSS.
		tree = dssConvert.dssToTree(ckt)
		#voltagePlot(ckt,PU=False)
		#gldtree = dssConvert.evilDssTreeToGldTree(tree) # DEBUG
		#distNetViz.viz_mem(gldtree, open_file=True, forceLayout=True) # DEBUG
		oldsz = len(tree)
		tree = reduceCircuit(tree)
		newsz = len(tree)
		#gldtree = dssConvert.evilDssTreeToGldTree(tree) # DEBUG
		#distNetViz.viz_mem(gldtree, open_file=True, forceLayout=True) # DEBUG
		#tree = dssConvert.evilGldTreeToDssTree(gldtree) # DEBUG
		# outckt_loc = ckt[:-4] + '_reduced.dss'
		dssConvert.treeToDss(tree, ckt+'out.dss')
		runDSS(ckt+'out.dss')
		# Example of hosting capacity for all buses with loads, i.e. metered buses.
		# fname = 'iowa240clean.dss'
		### Hosting Capacity Section
		# meter_buses = get_meter_buses(ckt)
		# hosting_capacity_all(ckt, 10, 10.0, BUS_LIST=meter_buses)
		# outdir = omf.omfDir + '/solvers/opendss/voltageCompare_' + fname[:-4]
		#voltagePlot(outckt_loc,PU=False)
		# if not os.path.exists(outdir):
		# 	os.mkdir(outdir)
		#currentPlot(ckt)
		#networkPlot(ckt)
		#THD(ckt)
		#dynamicPlot(ckt, 1, 10)
		#faultPlot(ckt)
		#capacityPlot(ckt)
		# involts_loc = ckt[:-4] + '_volts.dss'
		# involts = getVoltages(ckt, keep_output=True, outdir=outdir, output_filename=involts_loc)
		# outvolts_loc = outckt_loc[:-4] + '_volts.dss'
		# outvolts = getVoltages(outckt_loc, keep_output=True, outdir=outdir, output_filename=outvolts_loc)
		# rsumm_P, rsumm_D = voltageCompare(involts, outvolts, saveascsv=True, with_plots=False, outdir=outdir, outfilebase=ckt[:-4])		
		# maxPerrM = [rsumm_P.loc['RMSPE',c] for c in rsumm_P.columns if c.lower().startswith(' magnitude')]
		# maxPerrM = pd.Series(maxPerrM).max()
		# maxPerrA = [rsumm_P.loc['RMSPE',c] for c in rsumm_P.columns if c.lower().startswith(' angle')]
		# maxPerrA = pd.Series(maxPerrA).max()
		# maxDerrA = [rsumm_D.loc['RMSE',c] for c in rsumm_D.columns if c.lower().startswith(' angle')]
		# maxDerrA = pd.Series(maxDerrA).max()
		# maxDerrM = [rsumm_D.loc['RMSE',c] for c in rsumm_D.columns if c.lower().startswith(' magnitude')]
		# maxDerrM = pd.Series(maxDerrM).max()
		# from shutil import rmtree
		# os.remove(outckt_loc)
		# rmtree(outdir)
		#print('Objects removed: %s (of %s).\nPercent reduction: %s%%\nMax RMSPE for voltage magnitude: %s%%\nMax RMSPE for voltage angle: %s%%\nMax RMSE for voltage magnitude: %s\nMax RMSE for voltage angle: %s\n'%(oldsz-newsz, oldsz, (oldsz-newsz)*100/oldsz, maxPerrM, maxPerrA, maxDerrM, maxDerrA)) # DEBUG
		# errlim = 0.30 # threshold of 30% error between reduced files. 
		# assert maxPerrM <= errlim*100, 'The voltage magnitude error between the compared files exceeds the allowable limit of %s%%.'%(errlim*100)

if __name__ == "__main__":
	_tests()