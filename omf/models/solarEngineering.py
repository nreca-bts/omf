''' Shows users the technical system impacts of solar on a feeder including DG power generated, regulator tap changes, capacitor activation, and meter voltages '''

import json, os, csv, shutil, datetime, math, gc, platform
from os.path import join as pJoin
from functools import reduce
import numpy as np
import networkx as nx
import matplotlib
from matplotlib import pyplot as plt
from matplotlib import animation
from matplotlib.animation import FuncAnimation
from omf import feeder, weather
from omf.solvers import gridlabd
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The solarEngineering model shows users the technical system impacts of solar on a feeder including DG power generated, regulator tap changes, capacitor activation, and meter voltages. "
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. WARNING: GRIDLAB CAN TAKE HOURS TO COMPLETE. '''
	# feederName = inputDict["feederName1"]
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	inputDict["climateName"] = weather.zipCodeToClimateName(inputDict["zipCode"])
	shutil.copy(pJoin(__neoMetaModel__._omfDir, "data", "Climate", inputDict["climateName"] + ".tmy2"),
		pJoin(modelDir, "climate.tmy2"))
	with open(pJoin(modelDir, feederName + '.omd')) as f:
		feederJson = json.load(f)
	tree = feederJson["tree"]
	# Set up GLM with correct time and recorders:
	feeder.attachRecorders(tree, "Regulator", "object", "regulator")
	feeder.attachRecorders(tree, "Capacitor", "object", "capacitor")
	feeder.attachRecorders(tree, "Inverter", "object", "inverter")
	feeder.attachRecorders(tree, "Windmill", "object", "windturb_dg")
	feeder.attachRecorders(tree, "CollectorVoltage", None, None)
	feeder.attachRecorders(tree, "Climate", "object", "climate")
	feeder.attachRecorders(tree, "OverheadLosses", None, None)
	feeder.attachRecorders(tree, "UndergroundLosses", None, None)
	feeder.attachRecorders(tree, "TriplexLosses", None, None)
	feeder.attachRecorders(tree, "TransformerLosses", None, None)
	feeder.groupSwingKids(tree)
	# Attach recorders for system voltage map:
	stub = {'object':'group_recorder', 'group':'"class=node"', 'interval':3600}
	for phase in ['A','B','C']:
		copyStub = dict(stub)
		copyStub['property'] = 'voltage_' + phase
		copyStub['file'] = phase.lower() + 'VoltDump.csv'
		tree[feeder.getMaxKey(tree) + 1] = copyStub
	# Attach recorders for system voltage map, triplex:
	stub = {'object':'group_recorder', 'group':'"class=triplex_node"', 'interval':3600}
	for phase in ['1','2']:
		copyStub = dict(stub)
		copyStub['property'] = 'voltage_' + phase
		copyStub['file'] = phase.lower() + 'nVoltDump.csv'
		tree[feeder.getMaxKey(tree) + 1] = copyStub
	# Attach current recorder for overhead_lines
	currentStub = {'object':'group_recorder', 'group':'"class=overhead_line"', 'interval':3600}
	for phase in ['A','B','C']:
		copyCurrentStub = dict(currentStub)
		copyCurrentStub['property'] = 'current_out_' + phase
		copyCurrentStub['file'] = 'OH_line_current_phase' + phase + '.csv'
		tree[feeder.getMaxKey(tree) + 1] = copyCurrentStub
	rating_stub = {'object':'group_recorder', 'group':'"class=overhead_line"', 'interval':3600}
	copyRatingStub = dict(rating_stub)
	copyRatingStub['property'] = 'continuous_rating'
	copyRatingStub['file'] = 'OH_line_cont_rating.csv'
	tree[feeder.getMaxKey(tree) + 1] = copyRatingStub
	flow_stub = {'object':'group_recorder', 'group':'"class=overhead_line"', 'interval':3600}
	copyFlowStub = dict(flow_stub)
	copyFlowStub['property'] = 'flow_direction'
	copyFlowStub['file'] = 'OH_line_flow_direc.csv'
	tree[feeder.getMaxKey(tree) + 1] = copyFlowStub
	# Attach current recorder for underground_lines
	currentStubOH = {'object':'group_recorder', 'group':'"class=underground_line"', 'interval':3600}
	for phase in ['A','B','C']:
		copyCurrentStubOH = dict(currentStubOH)
		copyCurrentStubOH['property'] = 'current_out_' + phase
		copyCurrentStubOH['file'] = 'UG_line_current_phase' + phase + '.csv'
		tree[feeder.getMaxKey(tree) + 1] = copyCurrentStubOH
	ug_rating_stub = {'object':'group_recorder', 'group':'"class=underground_line"', 'interval':3600}
	copyUGRatingStub = dict(ug_rating_stub)
	copyUGRatingStub['property'] = 'continuous_rating'
	copyUGRatingStub['file'] = 'UG_line_cont_rating.csv'
	tree[feeder.getMaxKey(tree) + 1] = copyUGRatingStub
	ug_flow_stub = {'object':'group_recorder', 'group':'"class=underground_line"', 'interval':3600}
	ugCopyFlowStub = dict(ug_flow_stub)
	ugCopyFlowStub['property'] = 'flow_direction'
	ugCopyFlowStub['file'] = 'UG_line_flow_direc.csv'
	tree[feeder.getMaxKey(tree) + 1] = ugCopyFlowStub
	# And get meters for system voltage map:
	stub = {'object':'group_recorder', 'group':'"class=triplex_meter"', 'interval':3600}
	for phase in ['1','2']:
		copyStub = dict(stub)
		copyStub['property'] = 'voltage_' + phase
		copyStub['file'] = phase.lower() + 'mVoltDump.csv'
		tree[feeder.getMaxKey(tree) + 1] = copyStub
	for key in tree:
		if 'bustype' in tree[key].keys():
			if tree[key]['bustype'] == 'SWING':
				tree[key]['object'] = 'meter'
				swingN = tree[key]['name']
	swingRecord = {'object':'recorder', 'property':'voltage_A,measured_real_power,measured_power','file':'subVoltsA.csv','parent':swingN, 'interval':60}
	tree[feeder.getMaxKey(tree) + 1] = swingRecord
	for key in tree:
		if 'omftype' in tree[key].keys() and tree[key]['argument']=='minimum_timestep=3600':
			tree[key]['argument'] = 'minimum_timestep=60'
	# If there is a varvolt object in the tree, add recorder to swingbus and node from voltage_measurements property
	# Find var_volt object
	downLineNode = 'None'
	for key in tree:
		if 'object' in tree[key].keys() and tree[key]['object']=='volt_var_control':
			downLineNode = tree[key]['voltage_measurements']
	if downLineNode != 'None':
		downNodeRecord = {'object':'recorder', 'property':'voltage_A','file':'firstDownlineVoltsA.csv','parent':downLineNode, 'interval':60}
		tree[feeder.getMaxKey(tree) + 1] = downNodeRecord
	# Violation recorder to display to users 
	# violationRecorder = {'object':'violation_recorder','node_continuous_voltage_limit_lower':0.95,'file':'Violation_Log.csv',
	# 					'secondary_dist_voltage_rise_lower_limit':-0.042,'substation_pf_lower_limit':0.85,'substation_breaker_C_limit':300,
	# 					'secondary_dist_voltage_rise_upper_limit':0.025,'substation_breaker_B_limit':300,'violation_flag':'ALLVIOLATIONS',
	# 					'node_instantaneous_voltage_limit_upper':1.1, 'inverter_v_chng_per_interval_lower_bound':-0.05, 'virtual_substation':swingN,
	# 					'substation_breaker_A_limit':300, 'xfrmr_thermal_limit_lower':0,'node_continuous_voltage_interval':300,'strict':'false',
	# 					'node_instantaneous_voltage_limit_lower':0,'line_thermal_limit_upper':1,'echo':'false','node_continuous_voltage_limit_upper':1.05,
	# 					'interval':30,'line_thermal_limit_lower':0,'summary':'Violation_Summary.csv','inverter_v_chng_interval':60,
	# 					'xfrmr_thermal_limit_upper':2,'inverter_v_chng_per_interval_upper_bound':0.050}
	# tree[feeder.getMaxKey(tree) + 1] = violationRecorder
	feeder.adjustTime(tree=tree, simLength=float(inputDict["simLength"]),
		simLengthUnits=inputDict["simLengthUnits"], simStartDate=inputDict["simStartDate"])
	# RUN GRIDLABD IN FILESYSTEM (EXPENSIVE!)
	rawOut = gridlabd.runInFilesystem(tree, attachments=feederJson["attachments"], 
		keepFiles=True, workDir=pJoin(modelDir))
		# voltDumps have no values when gridlabD fails or the files dont exist
	if not os.path.isfile(pJoin(modelDir,'aVoltDump.csv')):
		with open (pJoin(modelDir,'stderr.txt')) as inFile:
			stdErrText = inFile.read()
		message = 'GridLAB-D crashed. Error log:\n' + stdErrText
		raise Exception(message)
	elif len(rawOut['aVoltDump.csv']['# timestamp']) == 0:
		with open (pJoin(modelDir,'stderr.txt')) as inFile:
			stdErrText = inFile.read()
		message = 'GridLAB-D crashed. Error log:\n' + stdErrText
		raise Exception(message)
	outData = {}
	# Std Err and Std Out
	outData['stderr'] = rawOut['stderr']
	outData['stdout'] = rawOut['stdout']
	# Time Stamps
	for key in rawOut:
		if '# timestamp' in rawOut[key]:
			outData['timeStamps'] = rawOut[key]['# timestamp']
			break
		elif '# property.. timestamp' in rawOut[key]:
			outData['timeStamps'] = rawOut[key]['# property.. timestamp']
		else:
			outData['timeStamps'] = []
	# Day/Month Aggregation Setup:
	stamps = outData.get('timeStamps',[])
	level = inputDict.get('simLengthUnits','hours')
	# Climate
	for key in rawOut:
		if key.startswith('Climate_') and key.endswith('.csv'):
			outData['climate'] = {}
			outData['climate']['Rain Fall (in/h)'] = hdmAgg(rawOut[key].get('rainfall'), sum, level)
			outData['climate']['Wind Speed (m/s)'] = hdmAgg(rawOut[key].get('wind_speed'), avg, level)
			outData['climate']['Temperature (F)'] = hdmAgg(rawOut[key].get('temperature'), max, level)
			outData['climate']['Snow Depth (in)'] = hdmAgg(rawOut[key].get('snowdepth'), max, level)
			outData['climate']['Direct Normal (W/sf)'] = hdmAgg(rawOut[key].get('solar_direct'), sum, level)
			#outData['climate']['Global Horizontal (W/sf)'] = hdmAgg(rawOut[key].get('solar_global'), sum, level)	
			climateWbySFList= hdmAgg(rawOut[key].get('solar_global'), sum, level)
			#converting W/sf to W/sm
			climateWbySMList= [x*10.76392 for x in climateWbySFList]
			outData['climate']['Global Horizontal (W/sm)']=climateWbySMList			
	# Voltage Band
	if 'VoltageJiggle.csv' in rawOut:
		outData['allMeterVoltages'] = {}
		outData['allMeterVoltages']['Min'] = hdmAgg([float(i / 2) for i in rawOut['VoltageJiggle.csv']['min(voltage_12.mag)']], min, level)
		outData['allMeterVoltages']['Mean'] = hdmAgg([float(i / 2) for i in rawOut['VoltageJiggle.csv']['mean(voltage_12.mag)']], avg, level)
		outData['allMeterVoltages']['StdDev'] = hdmAgg([float(i / 2) for i in rawOut['VoltageJiggle.csv']['std(voltage_12.mag)']], avg, level)
		outData['allMeterVoltages']['Max'] = hdmAgg([float(i / 2) for i in rawOut['VoltageJiggle.csv']['max(voltage_12.mag)']], max, level)
	# Power Consumption
	outData['Consumption'] = {}
	# Set default value to be 0, avoiding missing value when computing Loads
	outData['Consumption']['Power'] = [0] * int(inputDict["simLength"])
	outData['Consumption']['Losses'] = [0] * int(inputDict["simLength"])
	outData['Consumption']['DG'] = [0] * int(inputDict["simLength"])
	for key in rawOut:
		if key.startswith('SwingKids_') and key.endswith('.csv'):
			oneSwingPower = hdmAgg(vecPyth(rawOut[key]['sum(power_in.real)'],rawOut[key]['sum(power_in.imag)']), avg, level)
			if 'Power' not in outData['Consumption']:
				outData['Consumption']['Power'] = oneSwingPower
			else:
				outData['Consumption']['Power'] = vecSum(oneSwingPower,outData['Consumption']['Power'])
		elif key.startswith('Inverter_') and key.endswith('.csv'): 	
			realA = rawOut[key]['power_A.real']
			realB = rawOut[key]['power_B.real']
			realC = rawOut[key]['power_C.real']
			imagA = rawOut[key]['power_A.imag']
			imagB = rawOut[key]['power_B.imag']
			imagC = rawOut[key]['power_C.imag']
			oneDgPower = hdmAgg(vecSum(vecPyth(realA,imagA),vecPyth(realB,imagB),vecPyth(realC,imagC)), avg, level)
			if 'DG' not in outData['Consumption']:
				outData['Consumption']['DG'] = oneDgPower
			else:
				outData['Consumption']['DG'] = vecSum(oneDgPower,outData['Consumption']['DG'])
		elif key.startswith('Windmill_') and key.endswith('.csv'):
			vrA = rawOut[key]['voltage_A.real']
			vrB = rawOut[key]['voltage_B.real']
			vrC = rawOut[key]['voltage_C.real']
			viA = rawOut[key]['voltage_A.imag']
			viB = rawOut[key]['voltage_B.imag']
			viC = rawOut[key]['voltage_C.imag']
			crB = rawOut[key]['current_B.real']
			crA = rawOut[key]['current_A.real']
			crC = rawOut[key]['current_C.real']
			ciA = rawOut[key]['current_A.imag']
			ciB = rawOut[key]['current_B.imag']
			ciC = rawOut[key]['current_C.imag']
			powerA = vecProd(vecPyth(vrA,viA),vecPyth(crA,ciA))
			powerB = vecProd(vecPyth(vrB,viB),vecPyth(crB,ciB))
			powerC = vecProd(vecPyth(vrC,viC),vecPyth(crC,ciC))
			oneDgPower = hdmAgg(vecSum(powerA,powerB,powerC), avg, level)
			if 'DG' not in outData['Consumption']:
				outData['Consumption']['DG'] = oneDgPower
			else:
				outData['Consumption']['DG'] = vecSum(oneDgPower,outData['Consumption']['DG'])
		elif key in ['OverheadLosses.csv', 'UndergroundLosses.csv', 'TriplexLosses.csv', 'TransformerLosses.csv']:
			realA = rawOut[key]['sum(power_losses_A.real)']
			imagA = rawOut[key]['sum(power_losses_A.imag)']
			realB = rawOut[key]['sum(power_losses_B.real)']
			imagB = rawOut[key]['sum(power_losses_B.imag)']
			realC = rawOut[key]['sum(power_losses_C.real)']
			imagC = rawOut[key]['sum(power_losses_C.imag)']
			oneLoss = hdmAgg(vecSum(vecPyth(realA,imagA),vecPyth(realB,imagB),vecPyth(realC,imagC)), avg, level)
			if 'Losses' not in outData['Consumption']:
				outData['Consumption']['Losses'] = oneLoss
			else:
				outData['Consumption']['Losses'] = vecSum(oneLoss,outData['Consumption']['Losses'])
		elif key.startswith('Regulator_') and key.endswith('.csv'):
			#split function to strip off .csv from filename and user rest of the file name as key. for example- Regulator_VR10.csv -> key would be Regulator_VR10
			regName=""
			regName = key
			newkey=regName.split(".")[0]
			outData[newkey] ={}
			outData[newkey]['RegTapA'] = [0] * int(inputDict["simLength"])
			outData[newkey]['RegTapB'] = [0] * int(inputDict["simLength"])
			outData[newkey]['RegTapC'] = [0] * int(inputDict["simLength"])
			outData[newkey]['RegTapA'] = rawOut[key]['tap_A']
			outData[newkey]['RegTapB'] = rawOut[key]['tap_B']
			outData[newkey]['RegTapC'] = rawOut[key]['tap_C']
			outData[newkey]['RegPhases'] = rawOut[key]['phases'][0]
		elif key.startswith('Capacitor_') and key.endswith('.csv'):
			capName=""
			capName = key
			newkey=capName.split(".")[0]
			outData[newkey] ={}
			outData[newkey]['Cap1A'] = [0] * int(inputDict["simLength"])
			outData[newkey]['Cap1B'] = [0] * int(inputDict["simLength"])
			outData[newkey]['Cap1C'] = [0] * int(inputDict["simLength"])
			outData[newkey]['Cap1A'] = rawOut[key]['switchA']
			outData[newkey]['Cap1B'] = rawOut[key]['switchB']
			outData[newkey]['Cap1C'] = rawOut[key]['switchC']
			outData[newkey]['CapPhases'] = rawOut[key]['phases'][0]
	# Capture voltages at the swingbus
	# Loop through voltDump for swingbus voltages
	subData = []
	downData = []
	with open(pJoin(modelDir,"subVoltsA.csv"), newline='') as subFile:
		reader = csv.reader(subFile)
		subData = [x for x in reader]
	if downLineNode != 'None':
		with open(pJoin(modelDir,"firstDownlineVoltsA.csv"), newline='') as downFile:
			reader = csv.reader(downFile)
			downData = [x for x in reader]
	FIRST_DATA_ROW = 9
	cleanDown = [stringToMag(x[1]) for x in downData[FIRST_DATA_ROW:-1]]
	swingTimestamps = [x[0] for x in subData[FIRST_DATA_ROW:-1]]
	cleanSub = [stringToMag(x[1]) for x in subData[FIRST_DATA_ROW:-1]]
	# real_power / power
	powerFactors = []
	for row in subData[FIRST_DATA_ROW:-1]:
		powerFactors.append(abs(float(row[2])/stringToMag(row[3])))
	outData['powerFactors'] = powerFactors
	outData['swingVoltage'] = cleanSub
	outData['downlineNodeVolts'] = cleanDown
	outData['swingTimestamps'] = swingTimestamps
	# If there is a var volt system, find the min and max voltage for a band
	minVoltBand = []
	maxVoltBand = []
	if downLineNode != 'None':
		for key in tree:
			objKeys = tree[key].keys()
			if 'object' in objKeys:
				if tree[key]['object']=='volt_var_control':
					minVoltBand.append(float(tree[key]['minimum_voltages']))
					maxVoltBand.append(float(tree[key]['maximum_voltages']))
		outData['minVoltBand'] = minVoltBand
		outData['maxVoltBand'] = maxVoltBand
	# Violation Summary and Log
	# violationData = ''
	# violationArray = []
	# with open(pJoin(modelDir,"Violation_Summary.csv")) as vioSum:
	# 	reader = csv.reader(vioSum)
	# 	for row in reader:
	# 		violationArray.append(row)	
	# for row in violationArray[4:]:
	# 	violationData += str(' '.join(row)) + "\n"
	# outData["violationSummary"] = violationData
	# violationLogArray = []
	# violationLog = ''
	# with open(pJoin(modelDir,"Violation_Log.csv")) as vioLog:
	# 	logger = csv.reader(vioLog)
	# 	for row in logger:
	# 		violationLogArray.append(row)
	# for row in violationLogArray[6:]:
	# 	violationLog += str(' '.join(row)) + "\n"
	# outData['violationLog'] = violationLog
	# What percentage of our keys have lat lon data?
	latKeys = [tree[key]['latitude'] for key in tree if 'latitude' in tree[key]]
	latPerc = 1.0*len(latKeys)/len(tree)
	if latPerc < 0.25: doNeato = True
	else: doNeato = False
	# Generate the frames for the system voltage map time traveling chart.
	genTime, mapTimestamp = generateVoltChart(tree, rawOut, modelDir, neatoLayout=doNeato)
	outData['genTime'] = genTime
	outData['mapTimestamp'] = mapTimestamp
	# Aggregate up the timestamps:
	if level=='days':
		outData['timeStamps'] = aggSeries(stamps, stamps, lambda x:x[0][0:10], 'days')
	elif level=='months':
		outData['timeStamps'] = aggSeries(stamps, stamps, lambda x:x[0][0:7], 'months')
	return outData

def generateVoltChart(tree, rawOut, modelDir, neatoLayout=True):
	''' Map the voltages on a feeder over time using a movie.'''
	# We need to timestamp frames with the system clock to make sure the browser caches them appropriately.
	genTime = str(datetime.datetime.now()).replace(':','.')
	# Detect the feeder nominal voltage:
	for key in tree:
		ob = tree[key]
		if type(ob)==dict and ob.get('bustype','')=='SWING':
			feedVoltage = float(ob.get('nominal_voltage',1))
	# Make a graph object.
	fGraph = feeder.treeToNxGraph(tree)
	if neatoLayout:
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(fGraph.edges())
		cleanG.add_nodes_from(fGraph)
		# was formerly : positions = nx.graphviz_layout(cleanG, prog='neato') but this threw an error
		# positions = nx.nx_agraph.graphviz_layout(cleanG, prog='neato')
		positions = nx.kamada_kawai_layout(cleanG)
		positions = {k:(1000 * positions[k][0],1000 * positions[k][1]) for k in positions} # get out of array notation
	else:
		rawPositions = {n:fGraph.nodes[n].get('pos',(0,0)) for n in fGraph}
		#HACK: the import code reverses the y coords.
		def yFlip(pair):
			try: return (pair[0], -1.0*pair[1])
			except: return (0,0)
		positions = {k:yFlip(rawPositions[k]) for k in rawPositions}
	# Plot all time steps.
	nodeVolts = {}
	for step, stamp in enumerate(rawOut['aVoltDump.csv']['# timestamp']):
		# Build voltage map.
		nodeVolts[step] = {}
		for nodeName in [x for x in
			list(rawOut.get('aVoltDump.csv',{}).keys()) + list(rawOut.get('1nVoltDump.csv',{}).keys()) + list(rawOut.get('1mVoltDump.csv',{}).keys())
			if x != '# timestamp'
		]:
			allVolts = []
			for phase in ['a','b','c','1n','2n','1m','2m']:
				try:
					voltStep = rawOut[phase + 'VoltDump.csv'][nodeName][step]
				except:
					continue # the nodeName doesn't have the phase we're looking for.
				# HACK: Gridlab complex number format sometimes uses i, sometimes j, sometimes d. WTF?
				if type(voltStep) is str:
					voltStep = voltStep.replace('i','j')
				v = complex(voltStep)
				phaseVolt = abs(v)
				if phaseVolt != 0.0:
					if _digits(phaseVolt)>3:
						# Normalize to 120 V standard
						phaseVolt = phaseVolt*(120/feedVoltage)
					allVolts.append(phaseVolt)
			# HACK: Take average of all phases to collapse dimensionality.
			nodeVolts[step][nodeName] = avg(allVolts)
	# Line current calculations
	lineCurrents = {}
	if os.path.exists(pJoin(modelDir,'OH_line_current_phaseA.csv')):
		for step, stamp in enumerate(rawOut['OH_line_current_phaseA.csv']['# timestamp']):
			lineCurrents[step] = {} 
			currentArray = []
			# Finding currents of all phases on the line
			for key in [x for x in rawOut.get('OH_line_current_phaseA.csv',{}).keys() if x != '# timestamp']:
				currA = rawOut['OH_line_current_phaseA.csv'][key][step]
				currB = rawOut['OH_line_current_phaseB.csv'][key][step]
				currC = rawOut['OH_line_current_phaseC.csv'][key][step]
				flowDir = rawOut['OH_line_flow_direc.csv'][key][step]
				lineRating = rawOut['OH_line_cont_rating.csv'][key][step]
				if 'R' in flowDir:
					direction = -1
				else :
					direction = 1
				if type(currA) is str: 
					currA = stringToMag(currA)
					currB = stringToMag(currB)
					currC = stringToMag(currC)
					maxCurrent = max(abs(currA),abs(currB),abs(currC))
					directedCurrent = float(maxCurrent/lineRating * direction)
				for objt in tree:
					if 'name' in tree[objt].keys():
						if tree[objt]['name'] == str(int(key)):
							keyTup = (tree[objt]['to'],tree[objt]['from'])
				lineCurrents[step][keyTup] = directedCurrent
	# Underground Lines
	if os.path.exists(pJoin(modelDir,'UG_line_current_phaseA.csv')):
		for step, stamp in enumerate(rawOut['UG_line_current_phaseA.csv']['# timestamp']):
			currentArray = []
			# Finding currents of all phases on the line
			for key in [x for x in rawOut.get('UG_line_current_phaseA.csv',{}).keys() if x != '# timestamp']:
				currA = rawOut['UG_line_current_phaseA.csv'][key][step]
				currB = rawOut['UG_line_current_phaseB.csv'][key][step]
				currC = rawOut['UG_line_current_phaseC.csv'][key][step]
				flowDir = rawOut['UG_line_flow_direc.csv'][key][step]
				lineRating = rawOut['UG_line_cont_rating.csv'][key][step]
				if 'R' in flowDir:
					direction = -1
				else :
					direction = 1
				if type(currA) is str: 
					currA = stringToMag(currA)
					currB = stringToMag(currB)
					currC = stringToMag(currC)
					maxCurrent = max(abs(currA),abs(currB),abs(currC))
					directedCurrent = float(maxCurrent/lineRating * direction)
				for objt in tree:
					if 'name' in tree[objt].keys():
						if tree[objt]['name'] == str(int(key)):
							keyTup = (tree[objt]['to'],tree[objt]['from'])
				lineCurrents[step][keyTup] = directedCurrent
		for step in lineCurrents:
			for edge in fGraph.edges():
				if edge not in lineCurrents[step].keys():
					lineCurrents[step][edge] = 0
	# Draw animation.
	voltChart = plt.figure(figsize=(15,15))
	plt.axes(frameon = 0)
	plt.axis('off')
	#set axes step equal
	voltChart.gca().set_aspect('equal')
	custom_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(0.0,'blue'),(0.25,'darkgray'),(0.75,'darkgray'),(1.0,'yellow')])
	custom_cm.set_under(color='black')
	current_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(0.0,'green'),(0.999999,'green'),(1.0,'red')])
	# current_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(-1.0,'green'),(0.0, 'gray'),(1.0,'red'),(1.0,'red')])
	# use edge color to set color and dashness of overloaded/negative currents
	if len(lineCurrents)>0:
		edgeIm = nx.draw_networkx_edges(fGraph, 
			pos = positions,
			edge_color = [lineCurrents[0].get(n,0) for n in fGraph.edges()],
			edge_cmap = current_cm)
	else:	
		edgeIm = nx.draw_networkx_edges(fGraph, positions)
	nodeIm = nx.draw_networkx_nodes(fGraph,
		pos = positions,
		node_color = [nodeVolts[0].get(n,0) for n in fGraph.nodes()],
		linewidths = 0,
		node_size = 30,
		cmap = custom_cm)
	plt.sci(nodeIm)
	plt.clim(110,130)
	plt.colorbar()
	plt.title(rawOut['aVoltDump.csv']['# timestamp'][0])
	plt.tight_layout()
	def update(step):
		nodeColors = np.array([nodeVolts[step].get(n,0) for n in fGraph.nodes()])
		if len(lineCurrents)>0:
			edgeColors = np.array([lineCurrents[step].get(n,0) for n in fGraph.edges()])
			edgeIm.set_array(edgeColors)
		plt.title(rawOut['aVoltDump.csv']['# timestamp'][step])
		nodeIm.set_array(nodeColors)
		return nodeColors,
	mapTimestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
	anim = FuncAnimation(voltChart, update, frames=len(rawOut['aVoltDump.csv']['# timestamp']), interval=200, blit=False)
	try:
		import imageio_ffmpeg
		matplotlib.rcParams['animation.ffmpeg_path'] = imageio_ffmpeg.get_ffmpeg_exe()
	except ImportError:
		pass
	ffmpegwriter = animation.FFMpegWriter(codec='h264', extra_args=['-pix_fmt', 'yuv420p'])
	anim.save(pJoin(modelDir,'voltageChart_'+ mapTimestamp +'.mp4'), writer=ffmpegwriter)
	# Reclaim memory by closing, deleting and garbage collecting the last chart.
	voltChart.clf()
	plt.close()
	del voltChart
	gc.collect()
	return genTime, mapTimestamp

def avg(inList):
	''' Average a list. Really wish this was built-in. '''
	return sum(inList)/len(inList)

def hdmAgg(series, func, level):
	''' Simple hour/day/month aggregation for Gridlab. '''
	if level in ['days','months']:
		return aggSeries(series, func, level)
	else:
		return series

def aggSeries(timeStamps, timeSeries, func, level):
	''' Aggregate a list + timeStamps up to the required time level. '''
	# Different substring depending on what level we aggregate to:
	if level=='months': endPos = 7
	elif level=='days': endPos = 10
	combo = list(zip(timeStamps, timeSeries))
	# Group by level:
	groupedCombo = _groupBy(combo, lambda x1,x2: x1[0][0:endPos]==x2[0][0:endPos])
	# Get rid of the timestamps:
	groupedRaw = [[pair[1] for pair in group] for group in groupedCombo]
	return list(map(func, groupedRaw))

def _pyth(x,y):
	''' Compute the third side of a triangle--BUT KEEP SIGNS THE SAME FOR DG. '''
	sign = lambda z:(-1 if z<0 else 1)
	fullSign = sign(sign(x)*x*x + sign(y)*y*y)
	return fullSign*math.sqrt(x*x + y*y)

def _digits(x):
	''' Returns number of digits before the decimal in the float x. '''
	return math.ceil(math.log10(x+1))

def vecPyth(vx,vy):
	''' Pythagorean theorem for pairwise elements from two vectors. '''
	rows = zip(vx,vy)
	return [_pyth(*x) for x in rows]

def vecSum(*args):
	''' Add n vectors. '''
	return list(map(sum,zip(*args)))

def _prod(inList):
	''' Product of all values in a list. '''
	return reduce(lambda x,y:x*y, inList, 1)

def vecProd(*args):
	''' Multiply n vectors. '''
	return list(map(_prod, zip(*args)))

def threePhasePowFac(ra,rb,rc,ia,ib,ic):
	''' Get power factor for a row of threephase volts and amps. Gridlab-specific. '''
	pfRow = lambda row:math.cos(math.atan((row[0]+row[1]+row[2])/(row[3]+row[4]+row[5])))
	rows = zip(ra,rb,rc,ia,ib,ic)
	return list(map(pfRow, rows))

def roundSeries(ser):
	''' Round everything in a vector to 4 sig figs. '''
	return [roundSig(x,4) for x in ser]

def _groupBy(inL, func):
	''' Take a list and func, and group items in place comparing with func. Make sure the func is an equivalence relation, or your brain will hurt. '''
	if inL == []: return inL
	if len(inL) == 1: return [inL]
	newL = [[inL[0]]]
	for item in inL[1:]:
		if func(item, newL[-1][0]):
			newL[-1].append(item)
		else:
			newL.append([item])
	return newL

def stringToMag(s):
	if 'd' in s:
		return complex(s.replace('d','j')).real
	elif 'j' in s or 'i' in s:
		return abs(complex(s.replace('i','j')))

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"simStartDate": "2012-04-02",
		"simLengthUnits": "hours",
		"feederName1": "Olin Barre GH EOL Solar AVolts CapReg",
		"modelType": modelName,
		"zipCode": "59001",
		"simLength": "24"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _tests():
	# Location
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
	# Create New.
	new(modelLoc)
	# Pre-run.
	__neoMetaModel__.renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
