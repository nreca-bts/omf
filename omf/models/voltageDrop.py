"""
The voltageDrop model runs loadflow to show system voltages at all nodes.
"""
import json, os, tempfile, shutil, csv, math, base64
from os.path import join as pJoin
import networkx as nx
import matplotlib
from matplotlib import pyplot as plt
# dateutil imports
from dateutil import parser
from dateutil.relativedelta import *
# OMF imports 
import omf
from omf import feeder
from omf.solvers import gridlabd
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The voltageDrop model runs loadflow to show system voltages at all nodes."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# feederName = inputDict["feederName1"]
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	# Create voltage drop plot.
	print("*DEBUG: feederName:", feederName)
	with open(pJoin(modelDir,feederName + '.omd')) as f:
		omd = json.load(f)
	if inputDict.get("layoutAlgorithm", "geospatial") == "geospatial":
		neato = False
	else:
		neato = True
	# None cheack for edgeCol
	if inputDict.get("edgeCol", "None") == "None":
		edgeColValue = None
	else:
		edgeColValue = inputDict["edgeCol"]
	# None check for nodeCol
	if inputDict.get("nodeCol", "None") == "None":
		nodeColValue = None
	else:
		nodeColValue = inputDict["nodeCol"]
	# None check for edgeLabs
	if inputDict.get("edgeLabs", "None") == "None":
		edgeLabsValue = None
	else:
		edgeLabsValue = inputDict["edgeLabs"]
	# None check for nodeLabs
	if inputDict.get("nodeLabs", "None") == "None":
		nodeLabsValue = None
	else:
		nodeLabsValue = inputDict["nodeLabs"]
	# Type correction for colormap input
	if inputDict.get("customColormap", "True") == "True":
		customColormapValue = True
	else:
		customColormapValue = False
	# chart = voltPlot(omd, workDir=modelDir, neatoLayout=neato)
	chart = drawPlot(
		pJoin(modelDir,feederName + ".omd"),
		workDir = modelDir,
		neatoLayout = neato,
		edgeCol = edgeColValue,
		nodeCol = nodeColValue,
		nodeLabs = nodeLabsValue,
		edgeLabs = edgeLabsValue,
		customColormap = customColormapValue,
		rezSqIn = int(inputDict["rezSqIn"]))
	chart.savefig(pJoin(modelDir,"output.png"))
	with open(pJoin(modelDir,"output.png"),"rb") as inFile:
		outData["voltageDrop"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	return outData

def drawPlot(path, workDir=None, neatoLayout=False, edgeLabs=None, nodeLabs=None, edgeCol=None, nodeCol=None, faultLoc=None, faultType=None, customColormap=False, scaleMin=None, scaleMax=None, rezSqIn=400, simTime='2000-01-01 0:00:00', loadLoc=None):
	''' Draw a color-coded map of the voltage drop on a feeder.
	path is the full path to the GridLAB-D .glm file or OMF .omd file.
	workDir is where GridLAB-D will run, if it's None then a temp dir is used.
	neatoLayout=True means the circuit is displayed using a force-layout approach.
	edgeCol property must be either 'Current', 'Power', 'Rating', 'PercentOfRating', or None
	nodeCol property must be either 'Voltage', 'VoltageImbalance', 'perUnitVoltage', 'perUnit120Voltage', or None
	edgeLabs and nodeLabs properties must be either 'Name', 'Value', or None
	edgeCol and nodeCol can be set to false to avoid coloring edges or nodes
	customColormap=True means use a one that is nicely scaled to perunit values highlighting extremes.
	faultType and faultLoc are the type of fault and the name of the line that it occurs on.
	Returns a matplotlib object.'''
	# Be quiet matplotlib:
	# warnings.filterwarnings("ignore")
	if path.endswith('.glm'):
		tree = feeder.parse(path)
		attachments = []
	elif path.endswith('.omd'):
		with open(path) as f:
			omd = json.load(f)
		tree = omd.get('tree', {})
		attachments = omd.get('attachments',[])
	else:
		raise Exception('Invalid input file type. We require a .glm or .omd.')
	#print path
	# add fault object to tree
	def safeInt(x):
		try: return int(x)
		except: return 0
	biggestKey = max([safeInt(x) for x in tree.keys()])
	# Add Reliability module
	tree[str(biggestKey*10)] = {"module":"reliability","maximum_event_length":"18000","report_event_log":"true"}
	CLOCK_START = simTime
	dt_start = parser.parse(CLOCK_START)
	dt_end = dt_start + relativedelta(seconds=+20)
	CLOCK_END = str(dt_end)
	CLOCK_RANGE = CLOCK_START + ',' + CLOCK_END
	if faultType != None:
		# Add eventgen object (the fault)
		tree[str(biggestKey*10 + 1)] = {"object":"eventgen","name":"ManualEventGen","parent":"RelMetrics", "fault_type":faultType, "manual_outages":faultLoc + ',' + CLOCK_RANGE} # TODO: change CLOCK_RANGE to read the actual start and stop time, not just hard-coded
		# Add fault_check object
		tree[str(biggestKey*10 + 2)] = {"object":"fault_check","name":"test_fault","check_mode":"ONCHANGE", "eventgen_object":"ManualEventGen", "output_filename":"Fault_check_out.txt"}
		# Add reliabilty metrics object
		tree[str(biggestKey*10 + 3)] = {"object":"metrics", "name":"RelMetrics", "report_file":"Metrics_Output.csv", "module_metrics_object":"PwrMetrics", "metrics_of_interest":'"SAIFI,SAIDI,CAIDI,ASAI,MAIFI"', "customer_group":'"groupid=METERTEST"', "metric_interval":"5 h", "report_interval":"5 h"}
		# Add power_metrics object
		tree[str(biggestKey*10 + 4)] = {"object":"power_metrics","name":"PwrMetrics","base_time_value":"1 h"}
		
		# HACK: set groupid for all meters so outage stats are collected.
		noMeters = True
		for key in tree:
			if tree[key].get('object','') in ['meter', 'triplex_meter']:
				tree[key]['groupid'] = "METERTEST"
				noMeters = False
		if noMeters:
			raise Exception("No meters detected on the circuit. Please add at least one meter to allow for collection of outage statistics.")
	for key in tree:
		if 'clock' in tree[key]:
			tree[key]['starttime'] = "'" + CLOCK_START + "'"
			tree[key]['stoptime'] = "'" + CLOCK_END + "'"
	
	# dictionary to hold info on lines present in glm
	edge_bools = dict.fromkeys(['underground_line','overhead_line','triplex_line','transformer','regulator', 'fuse', 'switch'], False)
	# Map to speed up name lookups.
	nameToIndex = {tree[key].get('name',''):key for key in tree.keys()}
	# Get rid of schedules and climate and check for all edge types:
	for key in list(tree.keys()):
		obtype = tree[key].get("object","")
		if obtype == 'underground_line':
			edge_bools['underground_line'] = True
		elif obtype == 'overhead_line':
			edge_bools['overhead_line'] = True
		elif obtype == 'triplex_line':
			edge_bools['triplex_line'] = True
		elif obtype == 'transformer':
			edge_bools['transformer'] = True
		elif obtype == 'regulator':
			edge_bools['regulator'] = True
		elif obtype == 'fuse':
			edge_bools['fuse'] = True
		elif obtype == 'switch':
			edge_bools['switch'] = True
		if tree[key].get("argument","") == "\"schedules.glm\"" or tree[key].get("tmyfile","") != "":
			del tree[key]
	# Make sure we have a voltage dump and current dump:
	tree[str(biggestKey*10 + 5)] = {"object":"voltdump","filename":"voltDump.csv"}
	tree[str(biggestKey*10 + 6)] = {"object":"currdump","filename":"currDump.csv"}
	# Line rating dumps
	tree[feeder.getMaxKey(tree) + 1] = {
		'module': 'tape'
	}
	for key in edge_bools.keys():
		if edge_bools[key]:
			tree[feeder.getMaxKey(tree) + 1] = {
				'object':'group_recorder', 
				'group':'"class='+key+'"',
				'property':'continuous_rating',
				'file':key+'_cont_rating.csv'
			}
	#Record initial status readout of each fuse/recloser/switch/sectionalizer before running
	# Reminder: fuse objects have 'phase_X_status' instead of 'phase_X_state'
	protDevices = dict.fromkeys(['fuse', 'recloser', 'switch', 'sectionalizer'], False)
	#dictionary of protective device initial states for each phase
	protDevInitStatus = {}
	#dictionary of protective devices final states for each phase after running Gridlab-D
	protDevFinalStatus = {}
	#dictionary of protective device types to help the testing and debugging process
	protDevTypes = {}
	protDevOpModes = {}
	for key in tree:
		obj = tree[key]
		obType = obj.get('object')
		if obType in protDevices.keys():
			obName = obj.get('name', '')
			protDevTypes[obName] = obType
			if obType != 'fuse':
				protDevOpModes[obName] = obj.get('operating_mode', 'INDIVIDUAL')
			protDevices[obType] = True
			protDevInitStatus[obName] = {}
			protDevFinalStatus[obName] = {}
			for phase in ['A', 'B', 'C']:
				if obType != 'fuse':
					phaseState = obj.get('phase_' + phase + '_state','CLOSED')
				else:
					phaseState = obj.get('phase_' + phase + '_status','GOOD')
				if phase in obj.get('phases', ''):
					protDevInitStatus[obName][phase] = phaseState
	#print protDevInitStatus

	#Create a recorder for protective device states
	for key in protDevices.keys():
		if protDevices[key]:
			for phase in ['A', 'B', 'C']:
				if key != 'fuse':
					tree[feeder.getMaxKey(tree) + 1] = {
						'object':'group_recorder', 
						'group':'"class='+key+'"',
						'property':'phase_' + phase + '_state',
						'file':key + '_phase_' + phase + '_state.csv'
					}
				else:
					tree[feeder.getMaxKey(tree) + 1] = {
						'object':'group_recorder', 
						'group':'"class='+key+'"',
						'property':'phase_' + phase + '_status',
						'file':key + '_phase_' + phase + '_state.csv'
					}

	# Run Gridlab.
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)
	# for i in range(6):
	# 	gridlabOut = gridlabd.runInFilesystem(tree, attachments=attachments, workDir=workDir)
	# 	#HACK: workaround for shoddy macOS gridlabd build.
	# 	if 'error when setting parent' not in gridlabOut.get('stderr','OOPS'):
	# 		break
	gridlabOut = gridlabd.runInFilesystem(tree, attachments=attachments, workDir=workDir)

	#Record final status readout of each fuse/recloser/switch/sectionalizer after running
	try:
		for key in protDevices.keys():
			if protDevices[key]:
				for phase in ['A', 'B', 'C']:
					with open(pJoin(workDir, key + '_phase_' + phase + '_state.csv'), newline='') as statusFile:
						reader = csv.reader(statusFile)
						# loop past the header, 
						keys = []
						vals = []
						for row in reader:
							if '# timestamp' in row:
								keys = row
								i = keys.index('# timestamp')
								keys.pop(i)
								vals = next(reader)
								vals.pop(i)
						for pos,key2 in enumerate(keys):
							protDevFinalStatus[key2][phase] = vals[pos]
	except:
		pass
	#print protDevFinalStatus
	#compare initial and final states of protective devices
	#quick compare to see if they are equal
	#print cmp(protDevInitStatus, protDevFinalStatus)
	#find which values changed
	changedStates = {}
	#read voltDump values into a dictionary.
	try:
		with open(pJoin(workDir, 'voltDump.csv'), newline='') as dumpFile:
			reader = csv.reader(dumpFile)
			next(reader) # Burn the header.
			keys = next(reader)
			voltTable = []
			for row in reader:
				rowDict = {}
				for pos,key in enumerate(keys):
					rowDict[key] = row[pos]
				voltTable.append(rowDict)
	except:
		raise Exception('GridLAB-D failed to run with the following errors:\n' + gridlabOut['stderr'])
	# read currDump values into a dictionary
	with open(pJoin(workDir, 'currDump.csv'), newline='') as currDumpFile:
		reader = csv.reader(currDumpFile)
		next(reader) # Burn the header.
		keys = next(reader)
		currTable = []
		for row in reader:
			rowDict = {}
			for pos,key in enumerate(keys):
				rowDict[key] = row[pos]
			currTable.append(rowDict)
	# read line rating values into a single dictionary
	lineRatings = {}
	rating_in_VA = []
	for key1 in edge_bools.keys():
		if edge_bools[key1]:		
			with open(pJoin(workDir, key1 + '_cont_rating.csv'), newline='') as ratingFile:
				reader = csv.reader(ratingFile)
				# loop past the header, 
				keys = []
				vals = []
				for row in reader:
					if '# timestamp' in row:
						keys = row
						i = keys.index('# timestamp')
						keys.pop(i)
						vals = next(reader)
						vals.pop(i)
				for pos,key2 in enumerate(keys):
					lineRatings[key2] = abs(float(vals[pos]))
	#edgeTupleRatings = lineRatings copy with to-from tuple as keys for labeling
	edgeTupleRatings = {}
	for edge in lineRatings:
		for obj in tree.values():
			if obj.get('name','').replace('"','') == edge:
				nodeFrom = obj.get('from')
				nodeTo = obj.get('to')
				coord = (nodeFrom, nodeTo)
				ratingVal = lineRatings.get(edge)
				edgeTupleRatings[coord] = ratingVal
	# Calculate average node voltage deviation. First, helper functions.
	def digits(x):
		''' Returns number of digits before the decimal in the float x. '''
		return math.ceil(math.log10(x+1))
	def avg(l):
		''' Average of a list of ints or floats. '''
		# HACK: add a small value to the denominator to avoid divide by zero for out of service locations (i.e. zero voltage).
		return sum(l)/(len(l) + 0.00000000000000001)
	# Detect the feeder nominal voltage:
	for key in tree:
		ob = tree[key]
		if type(ob)==dict and ob.get('bustype','')=='SWING':
			feedVoltage = float(ob.get('nominal_voltage',1))
	# Tot it all up.
	nodeVolts = {}
	nodeVoltsPU = {}
	nodeVoltsPU120 = {}
	voltImbalances = {}
	for row in voltTable:
		allVolts = []
		allVoltsPU = []
		allDiffs = []
		nodeName = row.get('node_name','')
		for phase in ['A','B','C']:
			realVolt = abs(float(row['volt'+phase+'_real']))
			imagVolt = abs(float(row['volt'+phase+'_imag']))
			phaseVolt = math.sqrt((realVolt ** 2) + (imagVolt ** 2))
			if phaseVolt != 0.0:
				treeKey = nameToIndex.get(nodeName, 0)
				nodeObj = tree.get(treeKey, {})
				try:
					nominal_voltage = float(nodeObj['nominal_voltage'])
				except:
					nominal_voltage = feedVoltage
				allVolts.append(phaseVolt)
				normVolt = (phaseVolt/nominal_voltage)
				allVoltsPU.append(normVolt)
		avgVolts = avg(allVolts)
		avgVoltsPU = avg(allVoltsPU)
		avgVoltsPU120 = 120 * avgVoltsPU
		nodeVolts[nodeName] = float("{0:.2f}".format(avgVolts))
		nodeVoltsPU[nodeName] = float("{0:.2f}".format(avgVoltsPU))
		nodeVoltsPU120[nodeName] = float("{0:.2f}".format(avgVoltsPU120))
		if len(allVolts) == 3:
			voltA = allVolts.pop()
			voltB = allVolts.pop()
			voltC = allVolts.pop()
			allDiffs.append(abs(float(voltA-voltB)))
			allDiffs.append(abs(float(voltA-voltC)))
			allDiffs.append(abs(float(voltB-voltC)))
			maxDiff = max(allDiffs)
			voltImbal = maxDiff/avgVolts
			voltImbalances[nodeName] = float("{0:.2f}".format(voltImbal))
		# Use float("{0:.2f}".format(avg(allVolts))) if displaying the node labels
	nodeLoadNames = {}
	nodeNames = {}
	for key in nodeVolts.keys():
		nodeNames[key] = key
		if key == loadLoc:
			nodeLoadNames[key] = "LOAD: " + key
	# find edge currents by parsing currdump
	edgeCurrentSum = {}
	edgeCurrentMax = {}
	for row in currTable:
		allCurr = []
		for phase in ['A','B','C']:
			realCurr = abs(float(row['curr'+phase+'_real']))
			imagCurr = abs(float(row['curr'+phase+'_imag']))
			phaseCurr = math.sqrt((realCurr ** 2) + (imagCurr ** 2))
			allCurr.append(phaseCurr)
		edgeCurrentSum[row.get('link_name','')] = sum(allCurr)
		edgeCurrentMax[row.get('link_name','')] = max(allCurr)
	# When just showing current as labels, use sum of the three lines' current values, when showing the per unit values (current/rating), use the max of the three
	#edgeTupleCurrents = edgeCurrents copy with to-from tuple as keys for labeling
	edgeTupleCurrents = {}
	#edgeValsPU = values normalized per unit by line ratings
	edgeValsPU = {}
	#edgeTupleValsPU = edgeValsPU copy with to-from tuple as keys for labeling
	edgeTupleValsPU = {}
	#edgeTuplePower = dict with to-from tuples as keys and sim power as values for debugging
	edgeTuplePower = {}
	#edgeTupleNames = dict with to-from tuples as keys and names as values for debugging
	edgeTupleNames = {}
	#edgeTupleFaultNames = dict with to-from tuples as keys and the name of the Fault as the only value
	edgeTupleFaultNames = {}
	#edgeTupleProtDevs = dict with to-from tuples as keys and the initial of the type of protective device as the value
	edgeTupleProtDevs = {}
	#linePhases = dictionary containing the number of phases on each line for line-width purposes
	linePhases = {}
	edgePower = {}
	for edge in edgeCurrentSum:
		for obj in tree.values():
			obname = obj.get('name','').replace('"','')
			if obname == edge:
				objType = obj.get('object')
				nodeFrom = obj.get('from')
				nodeTo = obj.get('to')
				coord = (nodeFrom, nodeTo)
				currVal = edgeCurrentSum.get(edge)
				voltVal = avg([nodeVolts.get(nodeFrom), nodeVolts.get(nodeTo)])
				power = (currVal * voltVal)/1000
				lineRating = lineRatings.get(edge, 10.0**9)
				edgePerUnitVal = (edgeCurrentMax.get(edge))/lineRating
				edgeTupleCurrents[coord] = "{0:.2f}".format(currVal)
				edgeTuplePower[coord] = "{0:.2f}".format(power)
				edgePower[edge] = power
				edgeValsPU[edge] = edgePerUnitVal
				edgeTupleValsPU[coord] = "{0:.2f}".format(edgePerUnitVal)
				edgeTupleNames[coord] = edge
				if faultLoc == edge:
					edgeTupleFaultNames[coord] = "FAULT: " + edge
				phaseStr = obj.get('phases','').replace('"','').replace('N','').replace('S','')
				numPhases = len(phaseStr)
				if (numPhases < 1) or (numPhases > 3):
					numPhases = 1
				linePhases[edge] = numPhases
				protDevLabel = ""
				protDevBlownStr = ""
				if objType in protDevices.keys():
					for phase in protDevFinalStatus[obname].keys():
						if objType == 'fuse':
							if protDevFinalStatus[obname][phase] == "BLOWN":
								protDevBlownStr = "!"
						else:
							if protDevFinalStatus[obname][phase] == "OPEN":
								protDevBlownStr = "!"
				if objType == 'fuse':
					protDevLabel = 'F'
				elif objType == 'switch':
					protDevLabel = 'S'
				elif objType == 'recloser':
					protDevLabel = 'R'
				elif objType == 'sectionalizer':
					protDevLabel = 'X'
				edgeTupleProtDevs[coord] = protDevLabel + protDevBlownStr
	#define which dict will be used for edge line color
	edgeColors = edgeValsPU
	#define which dict will be used for edge label
	edgeLabels = edgeTupleValsPU
	# Build the graph.
	fGraph = feeder.treeToNxGraph(tree)
	# TODO: consider whether we can set figsize dynamically.
	wlVal = int(math.sqrt(float(rezSqIn)))
	voltChart = plt.figure(figsize=(wlVal, wlVal))
	plt.axes(frameon = 0)
	plt.axis('off')
	voltChart.gca().set_aspect('equal')
	plt.tight_layout()
	#set axes step equal
	if neatoLayout:
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(fGraph.edges())
		cleanG.add_nodes_from(fGraph)
		# positions = graphviz_layout(cleanG, prog='neato')
		positions = nx.kamada_kawai_layout(cleanG)
		positions = {k:(1000 * positions[k][0],1000 * positions[k][1]) for k in positions} # get out of array notation		
	else:
		remove_nodes = [n for n in fGraph if fGraph.nodes[n].get('pos', (0, 0)) == (0, 0)]
		fGraph.remove_nodes_from(remove_nodes)
		positions = {n:fGraph.nodes[n].get('pos',(0,0)) for n in fGraph}
	# Need to get edge names from pairs of connected node names.
	edgeNames = []
	for e in fGraph.edges():
		edgeNames.append((fGraph.edges[e].get('name','BLANK')).replace('"',''))
	#create custom colormap
	if customColormap:
		if scaleMin != None and scaleMax != None:
			scaleDif = scaleMax - scaleMin
			custom_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(scaleMin,'blue'),(scaleMin+(0.12*scaleDif),'darkgray'),(scaleMin+(0.56*scaleDif),'darkgray'),(scaleMin+(0.8*scaleDif),'red')])
			vmin = scaleMin
			vmax = scaleMax
		else:
			custom_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(0.0,'blue'),(0.15,'darkgray'),(0.7,'darkgray'),(1.0,'red')])
			vmin = 0
			vmax = 1.25
		custom_cm.set_under(color='black')
	else:
		custom_cm = plt.cm.get_cmap('viridis')
		if scaleMin != None and scaleMax != None:
			vmin = scaleMin
			vmax = scaleMax
		else:
			vmin = None
			vmax = None
	drawColorbar = False
	emptyColors = {}
	#draw edges with or without colors
	if edgeCol != None:
		drawColorbar = True
		if edgeCol == "Current":
			edgeList = [edgeCurrentSum.get(n,1) for n in edgeNames]
			drawColorbar = True
		elif edgeCol == "Power":
			edgeList = [edgePower.get(n,1) for n in edgeNames]
			drawColorbar = True
		elif edgeCol == "Rating":
			edgeList = [lineRatings.get(n, 10.0**9) for n in edgeNames]
			drawColorbar = True
		elif edgeCol == "PercentOfRating":
			edgeList = [edgeValsPU.get(n,.5) for n in edgeNames]
			drawColorbar = True
		else:
			edgeList = [emptyColors.get(n,.6) for n in edgeNames]
			print("WARNING: edgeCol property must be 'Current', 'Power', 'Rating', 'PercentOfRating', or None")
	else:
		edgeList = [emptyColors.get(n,.6) for n in edgeNames]
	edgeIm = nx.draw_networkx_edges(
		fGraph,
		pos = positions,
		edge_color = edgeList,
		width = [linePhases.get(n,1) for n in edgeNames],
		edge_cmap = custom_cm
	)
	#draw edge labels
	if edgeLabs != None:
		if edgeLabs == "Name":
			edgeLabels = edgeTupleNames
		elif edgeLabs == "Fault":
			edgeLabels = edgeTupleFaultNames
		elif edgeLabs == "Value":
			if edgeCol == "Current":
				edgeLabels = edgeTupleCurrents
			elif edgeCol == "Power":
				edgeLabels = edgeTuplePower
			elif edgeCol == "Rating":
				edgeLabels = edgeTupleRatings
			elif edgeCol == "PercentOfRating":
				edgeLabels = edgeTupleValsPU
			else:
				edgeLabels = None
				print("WARNING: edgeCol property cannot be set to None when edgeLabs property is set to 'Value'")
		elif edgeLabs == "ProtDevs":
			edgeLabels = edgeTupleProtDevs
		else:
			edgeLabs = None
			print("WARNING: edgeLabs property must be either 'Name', 'Value', or None")
	if edgeLabs != None:
		edgeLabelsIm = nx.draw_networkx_edge_labels(fGraph,
			pos = positions,
			edge_labels = edgeLabels,
			font_size = 8)
	# draw nodes with or without color
	if nodeCol != None:
		if nodeCol == "Voltage":
			nodeList = [nodeVolts.get(n,1) for n in fGraph.nodes()]
			drawColorbar = True
		elif nodeCol == "VoltageImbalance":
			nodeList = [voltImbalances.get(n,1) for n in fGraph.nodes()]
			drawColorbar = True
		elif nodeCol == "perUnitVoltage":
			nodeList = [nodeVoltsPU.get(n,.5) for n in fGraph.nodes()]
			drawColorbar = True
		elif nodeCol == "perUnit120Voltage":
			nodeList = [nodeVoltsPU120.get(n,120) for n in fGraph.nodes()]
			drawColorbar = True
		else:
			nodeList = [emptyColors.get(n,1) for n in fGraph.nodes()]
			print("WARNING: nodeCol property must be 'Voltage', 'VoltageImbalance', 'perUnitVoltage', 'perUnit120Voltage', or None")
	else:
		nodeList = [emptyColors.get(n,.6) for n in fGraph.nodes()]

	nodeIm = nx.draw_networkx_nodes(fGraph,
		pos = positions,
		node_color = nodeList,
		linewidths = 0,
		node_size = 30,
		vmin = vmin,
		vmax = vmax,
		cmap = custom_cm)
	#draw node labels
	nodeLabels = {}
	if nodeLabs != None:
		if nodeLabs == "Name":
			nodeLabels = nodeNames
		elif nodeLabs == "Value":
			if nodeCol == "Voltage":
				nodeLabels = nodeVolts
			elif nodeCol == "VoltageImbalance":
				nodeLabels = voltImbalances
			elif nodeCol == "perUnitVoltage":
				nodeLabels = nodeVoltsPU
			elif nodeCol == "perUnit120Voltage":
				nodeLabels = nodeVoltsPU120
			else:
				nodeLabels = None
				print("WARNING: nodeCol property cannot be set to None when nodeLabs property is set to 'Value'")
		#HACK: add hidden node label option for displaying specified load name
		elif nodeLabs == "Load":
			nodeLabels = nodeLoadNames
		else:
			nodeLabs = None
			print("WARNING: nodeLabs property must be either 'Name', 'Value', or None")
	if nodeLabs != None:
		nodeLabelsIm = nx.draw_networkx_labels(fGraph,
			pos = positions,
			labels = nodeLabels,
			font_size = 8)
	plt.sci(nodeIm)
	# plt.clim(110,130)
	if drawColorbar:
		plt.colorbar()
	return voltChart

def glmToModel(glmPath, modelDir):
	''' One shot model creation from glm. '''
	tree = feeder.parse(glmPath)
	print("glmPath:    " + glmPath)
	print("modelDir:   " + modelDir)
	# Run powerflow. First name the folder for it.
	# Remove old copy of the model.
	shutil.rmtree(modelDir, ignore_errors=True)
	# Create the model directory.
	new(modelDir)
	# Create the .omd.
	os.remove(modelDir + '/Olin Barre Geo.omd')
	with open(modelDir + '/Olin Barre Geo.omd','w') as omdFile:
		omd = dict(feeder.newFeederWireframe)
		omd['tree'] = tree
		json.dump(omd, omdFile, indent=4)

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"feederName1": "Olin Barre Geo",
		"modelType": modelName,
		"runTime": "",
		"layoutAlgorithm": "geospatial",
		"edgeCol" : "None",
		"nodeCol" : "perUnit120Voltage",
		"nodeLabs" : "None",
		"edgeLabs" : "None",
		"customColormap" : "False",
		"rezSqIn" : "225"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _testingPlot():
	"""
	Internal helper for voltage drop testing plot processing.
	"""
	PREFIX = omf.omfDir + '/scratch/CIGAR/'
	# FNAME = 'test_base_R4-25.00-1.glm_CLEAN.glm'
	FNAME = 'test_Exercise_4_2_1.glm'
	# FNAME = 'test_ieee37node.glm'
	# FNAME = 'test_ieee123nodeBetter.glm'
	# FNAME = 'test_large-R5-35.00-1.glm_CLEAN.glm'
	# FNAME = 'test_medium-R4-12.47-1.glm_CLEAN.glm'
	# FNAME = 'test_smsSingle.glm'
	# Hack: Agg backend doesn't work for interactivity. Switch to something we can use:
	# plt.switch_backend('MacOSX')
	chart = drawPlot(PREFIX + FNAME, neatoLayout=True, edgeCol="PercentOfRating", nodeCol="perUnitVoltage", nodeLabs="Value", edgeLabs="Name", customColormap=True, rezSqIn=225)
	chart.savefig(PREFIX + "YO_WHATS_GOING_ON.png")
	# plt.show()

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
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
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
	# _testingPlot()
