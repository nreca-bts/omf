"""
The Resilient Distribution model simulates the effect of weather hazards on the
structure of an electrical distribution network. Users are able to compare the results
and cost of hardening various individual components with the integrity of the network.
The outputs include an optimal set of hardening options that improve the resiliency at
the lowest possible cost. The model uses General Fragility Model, GridLAB-D, and
Resilient Distribution Tool as part of the data pipeline.
"""

import json, os, shutil, subprocess, datetime, random, copy, base64, platform
import os.path
from os.path import join as pJoin
import numpy as np
import networkx as nx
import matplotlib
from matplotlib import pyplot as plt
import omf
from omf import feeder, weather, distNetViz
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.weather import get_ndfd_data

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Model extreme weather and determine optimal investment for distribution resiliency."
hidden = False

# Constant for converting map-feet to lat-lon for GFM:
HACK_SCALING_CONSTANT = 5000.0

def ndfdToHazardFieldFile(xStart, xEnd, yStart, yEnd, cellsize, outFilePath):
	# Loop through get_ndfd_data calls to populate HazardField data
	"""
	Perform ndfd to hazard field file processing for the resilient dist model.
	"""
	fieldArray = []
	xNumSteps = round((xEnd - xStart) / cellsize)
	yNumSteps = round((yEnd - yStart) / cellsize)
	for y_step in range(0, yNumSteps):
		curRow = []
		for x_step in range(0, xNumSteps):
			xOffset = x_step * cellsize
			yOffset = y_step * cellsize
			outputVal = -9999.0
			try:
				output = get_ndfd_data(str(xStart + xOffset), str(yStart + yOffset), ['wspd'])
				outputVal = output['dwml']['data']['parameters']['wind-speed']['value'][0]
			except:
				pass
			# add value to row's list
			curRow.append(outputVal)
		# add row of values to field
		fieldArray.append(curRow)

	# write the header of the .asc file
	with open(outFilePath, "w", newline='') as hazardFieldFile:
		hazardFieldFile.write("ncols " + str(xNumSteps) + "\n")
		hazardFieldFile.write("nrows " + str(yNumSteps) + "\n")
		hazardFieldFile.write("xllcorner " + str(xStart) + "\n")
		hazardFieldFile.write("yllcorner " + str(yStart) + "\n")
		hazardFieldFile.write("cellsize " + str(cellsize) + "\n")
		hazardFieldFile.write("NODATA_value -9999.0" + "\n")
		hazardFieldFile.writelines(' '.join(str(val) for val in line) +'\n' for line in fieldArray)

class HazardField(object):
	''' Object to modify a hazard field from an .asc file. '''

	def __init__(self, filePath):
		''' Use parsing function to set up harzard data in dict format in constructor.'''
		self.hazardObj = self.parseHazardFile(filePath)

	def parseHazardFile(self, inPath):
		''' Parse input .asc file. '''
		with open(inPath, "r") as hazardFile: # Parse the file, strip away whitespaces.
			content = hazardFile.readlines()
		content = [x.strip() for x in content]
		hazardObj = {}
		field = []
		newContent = []
		for i in range(len(content)):
			line = content[i].split()
			if len(line) > 1:
				newContent.append(line)
		i = 0
		j = 0
		while i < len(content):
			if j <= 5: # First, get the the parameters for the export function below. Each gets their own entry in our object.
				# line = re.split(r"\s+",content[i])
				line = content[i].split()
				if len(line) < 2:
					i += 1
					continue
				hazardObj[line[0]] = float(line[1])
				i += 1
				j += 1
			if j > 5: # Then, get the numerical data, mapping each number to its appropriate parameter.
				content[i] = content[i].replace(" ", ",")
				try:
					field.insert((i-6), list(map(float,content[i].split(","))))
					i += 1
					j += 1
				except:
					i += 1
					continue
		field = np.array(field)
		hazardObj["field"] = field
		return hazardObj

	def exportHazardObj(self, outPath):
		''' Export file. ''' 
		ncols = "ncols        " + str(self.hazardObj["ncols"]) + "\n" # Get parameters from object.
		nrows = "nrows        " + str(self.hazardObj["nrows"]) + "\n"
		xllcorner = "xllcorner    " + str(self.hazardObj["xllcorner"]) + "\n"
		yllcorner = "yllcorner    " + str(self.hazardObj["yllcorner"]) + "\n"
		cellsize = "cellsize     " + str(self.hazardObj["cellsize"]) + "\n"
		NODATA_value = "NODATA_value " + str(self.hazardObj["NODATA_value"]) + "\n"
		output = ncols + nrows + xllcorner + yllcorner + cellsize + NODATA_value
		fieldList = self.hazardObj["field"].tolist() # Get numerical data, convert each number to a string and add that onto the to-be exported data. 
		for i in range(len(fieldList)):
			output = output + " ".join(list(map(str, fieldList[i]))) + "\n"
		with open(outPath, "w") as newHazardFile: # Export to new file.
			newHazardFile.write("%s" % output)

	def moveLocation(self, x, y): 
		''' Shift temporal boundaries for image plot. ''' 
		self.hazardObj["xllcorner"] = x
		self.hazardObj["yllcorner"] = y

	def changeCellSize(self, cellSize): 
		''' Scale the cell size in image plot. '''
		self.hazardObj["cellsize"] = cellSize

	def mapRanges(self, values, fromMin, fromMax):
		"""
		Implement map ranges behavior for HazardField instances.
		"""
		def mapValue(self, value, fromMin, fromMax, toMin=.7, toMax=1):
			newValue = float(value - fromMin) / float(fromMax-fromMin)
			return toMin + (newValue * (toMax-toMin))
		newValues = []
		for value in values:
			newValues.append(mapValue(value, fromMin, fromMax))
		return newValues

	def drawDamageField(self, damageData):
		''' Draw damage field, assuming a numpy input. '''
		pass


	def drawHeatMap(self, show=True):
		''' Draw heat map-color coded image map with user-defined boundaries and cell-size. '''
		heatMap = plt.imshow(
			self.hazardObj['field'],
			cmap = 'gray',
			alpha = 0.2,
			interpolation = 'nearest',
			extent = [
				self.hazardObj["xllcorner"],
				self.hazardObj["xllcorner"] + self.hazardObj["ncols"] * self.hazardObj["cellsize"],
				self.hazardObj["yllcorner"],
				self.hazardObj["yllcorner"] + self.hazardObj["nrows"] * self.hazardObj["cellsize"]
			],
			aspect='auto')
		#plt.gca().invert_yaxis() This isn't needed anymore?
		plt.title("Hazard Field")
		if show:
			plt.show()

	def scaleField(self, scaleFactor):
		''' Numerically scale the field with user defined scaling factor. ''' 
		for a in np.nditer(self.hazardObj["field"], op_flags=['readwrite']):
			a[...] = scaleFactor * a

	def randomField(self, lowerLimit = 0, upperLimit = 100):
		''' Generate random field with user defined limits. '''
		for a in np.nditer(self.hazardObj["field"], op_flags=['readwrite']):
			a[...] = random.uniform(lowerLimit, upperLimit) 

def _testHazards():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	hazard = HazardField(omf.omfDir + "/static/testFiles/wf_clip.asc")
	hazard.scaleField(.5)
	hazard.moveLocation(20, 100)
	hazard.changeCellSize(0.5)
	hazard.randomField()
	# hazard.exportHazardObj("modWindFile.asc")
	# hazard.drawHeatMap()

	# Test the ndfdToHazardFieldFile function
	xStart1 = 38.912832283302436
	yStart1 = -77.02056029181865
	cellSize1 = 0.01
	numRows1 = 8
	numCols1 = 8
	xEnd1 = xStart1 + (cellSize1*numCols1)
	yEnd1 = yStart1 + (cellSize1*numRows1)
	outFilePath1 = omf.omfDir + "/static/testFiles/ndfdTest.asc"
	# ndfdToHazardFieldFile(38.912832283302436, 38.932832283302436, -77.02056029181865, -77.00056029181865, 0.01, outFilePath1)
	ndfdToHazardFieldFile(xStart1, xEnd1, yStart1, yEnd1, cellSize1, outFilePath1)

def getNodePhases(obj, maxRealPhase):
	''' Convert phase info in GridLAB-D obj (e.g. ABC) to GFM phase format (e.g. [True,True,True].'''
	numPhases = 0
	hasphaseA, hasphaseB, hasphaseC = False, False, False
	maxRealPhaseA, maxRealPhaseB, maxRealPhaseC = 0.0, 0.0, 0.0
	maxReactivePhaseA, maxReactivePhaseB, maxReactivePhaseC = 0.0, 0.0, 0.0
	phases = obj.get('phases','').strip('S').strip('N')
	if phases != '': 
		if 'A' in phases: 
			hasphaseA = True
			maxRealPhaseA = float(maxRealPhase)
			maxReactivePhaseA = float(maxRealPhase)*0.1
			numPhases+=1
		if 'B' in phases: 
			hasphaseB = True
			maxRealPhaseB = float(maxRealPhase)
			maxReactivePhaseB = float(maxRealPhase)*0.1
			numPhases+=1
		if 'C' in phases: 
			hasphaseC = True
			maxRealPhaseC = float(maxRealPhase)
			maxReactivePhaseC = float(maxRealPhase)*0.1
			numPhases+=1
	return numPhases, [hasphaseA, hasphaseB, hasphaseC], [maxRealPhaseA, maxRealPhaseB, maxRealPhaseC], [maxReactivePhaseA, maxReactivePhaseB, maxReactivePhaseC]

def convertToGFM(gfmInputTemplate, feederModel):
	'''Read a omd.json feeder and convert it to GFM format.'''
	# Create GFM dict.
	gfmJson = {
		'buses' : [],
		'loads' : [],
		'generators' : [],
		'line_codes' : [],
		'lines' : [],
		'lineLikeObjs' : [],
		'critical_load_met' : gfmInputTemplate.get('critical_load_met',0.98),
		'total_load_met' : gfmInputTemplate.get('total_load_met',0.9),
		'chance_constraint' : gfmInputTemplate.get('chance_constraint', 1.0),
		'phase_variation' : gfmInputTemplate.get('phase_variation', 0.15),
	}
	# Get necessary data from .omd.
	jsonTree = feederModel.get('tree',{})
	distNetViz.insert_coordinates(jsonTree)
	jsonNodes = feederModel.get('nodes',[])
	#Line Creation
	critLoads = gfmInputTemplate["criticalLoads"].strip().replace(' ', '').split(',')
	objToFind = ['transformer', 'regulator', 'underground_line', 'overhead_line', 'fuse', 'switch']
	lineCount = 0
	for key, line in jsonTree.items():
		if 'from' in line.keys() and 'to' in line.keys():
			gfmJson['lineLikeObjs'].append(line['name'])
		if line.get('object','') in objToFind:
			phases = line.get('phases')
			if 'S' in phases:
				continue # We don't support secondary system transformers.
			newLine = {
				'id' : line.get('name',''),
				'node1_id' : line.get('from','')+'_bus',
				'node2_id' : line.get('to','')+'_bus',
				'length' : float(line.get('length',100)), #* Units match line code entries.
			}
			gfmJson['lines'].append(newLine)
			lineCount+=1
	# Bus creation:
	objToFind = ['node', 'load', 'triplex_meter']
	for key, bus in jsonTree.items():
		objType = bus.get('object','')
		# HACK: some loads can be parented to other things. Don't make buses for them.
		hasParent = 'parent' in bus
		if objType in objToFind and not hasParent:
			newBus = dict({
				'id': '', #*
				# 'min_voltage': 0.8, # in p.u.
				# 'max_voltage': 1.2, # in p.u.
				'y': float(bus.get('latitude',0.0))/HACK_SCALING_CONSTANT,
				'x': float(bus.get('longitude',0.0))/HACK_SCALING_CONSTANT,
				# 'has_phase': [True, True, True],
				# 'ref_voltage': [1.0, 1.0, 1.0]
				# 'ref_voltage': 1.0 # From github.
			})
			newBus['id'] = bus.get('name','')+'_bus'
			numPhases, newBus['has_phase'], max_real_phase, max_reactive_phase = getNodePhases(bus, 0.0)
			gfmJson['buses'].append(newBus)
			if len(jsonNodes) != 0:
				# HACK: no lat/lon data in tree, so use data from jsonNodes instead.
				for busNode in jsonNodes:
					# HACK: sometimes keys are strings. Sometimes not.
					if int(key) == busNode.get('treeIndex',0):
						# HACK: nice coords for GFM which wants lat/lon.
						newBus['y'] = busNode.get('y')/HACK_SCALING_CONSTANT
						newBus['x'] = busNode.get('x')/HACK_SCALING_CONSTANT
	# Load creation:
	objToFind = ['load']
	phaseNames = {'A':0, 'B':1, 'C':2}
	for key, load in jsonTree.items():
		objType = load.get('object','')
		hasParent = 'parent' in load
		if objType in objToFind:
			newLoad = dict({
				'id': '', #*
				'node_id': '', #*
				'is_critical': False, 
				'max_real_phase': [0,0,0], #*
				'max_reactive_phase': [0,0,0], #*
				'has_phase': [False, False, False] #*
			})
			if load.get('name','') in critLoads:
				newLoad['is_critical'] = True
			newLoad['id'] = load.get('name','')+'_lod'
			# Associate the new load with the bus it is attached to.
			if hasParent:
				newLoad['node_id'] = load['parent'] + '_bus'
			else: #no parent, i.e. we created a bus for the load.
				newLoad['node_id'] = load['name'] + '_bus'
			voltage = float(load.get('nominal_voltage','4800'))
			newLoad['nominal_voltage'] = voltage
			for phaseName, index in phaseNames.items():
				impedance = 'constant_impedance_' + phaseName
				power = 'constant_power_' + phaseName
				current = 'constant_current_' + phaseName
				if impedance in load:
					constImpedRaw = load.get(impedance,'').replace(' ','')
					constImped = complex(constImpedRaw)
					realImpedance = constImped.real
					reactiveImpedance = constImped.imag
					newLoad['max_real_phase'][index] = abs((voltage*voltage)/realImpedance)/1000000
					newLoad['max_reactive_phase'][index] = abs((voltage*voltage)/reactiveImpedance)/1000000
					newLoad['has_phase'][index] = True
				if current in load:
					constCurrRaw = load.get(current,'').replace(' ','')
					constCurr = complex(constCurrRaw)
					realCurr = constCurr.real
					reactiveCurr = constCurr.imag
					newLoad['max_real_phase'][index] = abs(voltage*realCurr)/1000000
					newLoad['max_reactive_phase'][index] = abs(voltage*reactiveCurr)/1000000
					newLoad['has_phase'][index] = True
				if power in load:
					constPowerRaw = load.get(power,'').replace(' ','')
					constPower = complex(constPowerRaw)
					realPower = constPower.real
					reactivePower = constPower.imag
					newLoad['max_real_phase'][index] = abs(realPower)/1000000
					newLoad['max_reactive_phase'][index] = abs(reactivePower)/1000000
					newLoad['has_phase'][index] = True
			gfmJson['loads'].append(newLoad)
	# Generator creation:
	genCands = gfmInputTemplate['generatorCandidates'].strip().replace(' ', '').split(',')
	for key, glmOb in jsonTree.items():
		# Check for a swing node:
		isSwing = glmOb.get('bustype','') == 'SWING'
		if glmOb.get('name', None) in genCands or isSwing:
			genID = glmOb.get('name','')+'_gen'
			for elem in gfmJson['buses']:
				if elem['id'][0:-4] == genID[0:-4]:
					busID = elem['id']
			numPhases, has_phase, max_real_phase, max_reactive_phase = getNodePhases(glmOb, gfmInputTemplate['maxDGPerGenerator'])
			if isSwing:
				# HACK: swing buses get "infinitely large", i.e. 5 TW, generator capacity.
				genSize = 5.0 * 1000.0 * 1000.0
				isNew = False
				has_phase = [True, True, True]
			else:
				# Non swing buses get 1 MW generators.
				genSize = gfmInputTemplate['maxDGPerGenerator']
				isNew = True
			genObj = {
	 			'id': glmOb.get('name','')+'_gen', #*
				'node_id': busID, #*
				'is_new': isNew, # Whether or not new generation can be built.
				'microgrid_cost': gfmInputTemplate['dgUnitCost'], # Per MW capacity of building DG.
				'max_microgrid': genSize, # Max additional capacity for this gen.
				'microgrid_fixed_cost': 0, # One-time fixed cost for building DG.
				'has_phase': has_phase, #*
				'max_reactive_phase': [genSize,genSize,genSize], #*
				'max_real_phase': [genSize,genSize,genSize] #*
			}
			gfmJson['generators'].append(genObj)
	return gfmJson

def genDiagram(outputDir, feederJson, damageDict, critLoads, damagedLoads, edgeLabelsToAdd, generatorList):
	# print damageDict
	# warnings.filterwarnings("ignore")
	# Load required data.
	"""
	Perform gen diagram processing for the resilient dist model.
	"""
	tree = feederJson.get("tree",{})
	links = feederJson.get("links",{})
	# Generate lat/lons from nodes and links structures.
	for link in links:
		for typeLink in link.keys():
			if typeLink in ['source', 'target']:
				for key in link[typeLink].keys():
					if key in ['x', 'y']:
						objName = link[typeLink]['name']
						for x in tree:
							leaf = tree[x]
							if leaf.get('name','')==objName:
								if key=='x': leaf['latitude'] = link[typeLink][key]
								else: leaf['longitude'] = link[typeLink][key]
	# Remove even more things (no lat, lon or from = node without a position).
	for key in list(tree.keys()):
		aLat = tree[key].get('latitude')
		aLon = tree[key].get('longitude')
		aFrom = tree[key].get('from')
		if aLat is None and aLon is None and aFrom is None:
			tree.pop(key)
	# Create and save the graphic.
	inGraph = feeder.treeToNxGraph(tree)
	labels=True
	neatoLayout=False 
	showPlot=False
	plt.axis('off')
	plt.tight_layout()
	plt.gca().invert_yaxis()
	plt.gca().set_aspect('equal')
	# Layout the graph via GraphViz neato. Handy if there's no lat/lon data.
	if neatoLayout:
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(inGraph.edges())
		# HACK2: might miss nodes without edges without the following.
		cleanG.add_nodes_from(inGraph)
		# pos = nx.nx_agraph.graphviz_layout(cleanG, prog='neato')
		pos = nx.kamada_kawai_layout(cleanG)
		pos = {k:(1000 * pos[k][0],1000 * pos[k][1]) for k in pos} # get out of array notation
	else:
		pos = {n:inGraph.nodes[n].get('pos',(0,0)) for n in inGraph}
	# Rescale using the magic number.
	for k in pos:
		newPos = (pos[k][0]/HACK_SCALING_CONSTANT, pos[k][1]/HACK_SCALING_CONSTANT)
		pos[k] = newPos
	# Draw all the edges
	selected_labels = {}
	for e in inGraph.edges():
		edgeName = inGraph.edges[e].get('name')
		if edgeName in edgeLabelsToAdd.keys():
			selected_labels[e] = edgeLabelsToAdd[edgeName]
		edgeColor = 'black'
		if edgeName in damageDict:
			if damageDict[edgeName] == 1:
				edgeColor = 'yellow'
			if damageDict[edgeName] == 2:
				edgeColor = 'orange'
			if damageDict[edgeName] >= 3:
				edgeColor = 'red'
		eType = inGraph.edges[e].get('type','underground_line')
		ePhases = inGraph.edges[e].get('phases',1)
		standArgs = {
			'edgelist':[e],
			'edge_color':edgeColor,
			'width':2,
			'style':{'parentChild':'dotted','underground_line':'dashed'}.get(eType,'solid')
		}
		if ePhases==3:
			standArgs.update({'width':5})
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
			standArgs.update({'width':3,'edge_color':'gainsboro'})
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
			standArgs.update({'width':1,'edge_color':edgeColor})
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
		if ePhases==2:
			standArgs.update({'width':3})
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
			standArgs.update({'width':1,'edge_color':'gainsboro'})
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
		else:
			nx.draw_networkx_edges(inGraph,pos,**standArgs)
	# Get swing buses.
	green_list = []
	for node in tree:
		if 'bustype' in tree[node] and tree[node]['bustype'] == 'SWING':
			green_list.append(tree[node]['name'])
	isFirst = {'green': False, 'red': False, 'blue': False, 'grey': False, 'dimgrey': False}
	nodeLabels = {'green': 'Swing Bus', 'red': 'Critical Load', 'blue': 'Load', 'dimgrey':'New Generator', 'grey': 'Other'}
	# Draw nodes and optional labels.
	for key in pos.keys():
		isLoad = key[2:6]
		nodeColor = 'grey'
		nodeLabel = 'Other'
		if key in green_list:
			nodeColor = 'green'
		elif key in critLoads:
			nodeColor = 'red'			
		elif isLoad == 'load':
			nodeColor = 'blue'
		elif key in generatorList and key not in green_list:
			nodeColor = 'dimgrey'
		kwargs = {
			'nodelist': [key],
			'node_color': nodeColor,
			'node_size': 16,
			'linewidths': 1.0
		}
		if not isFirst[nodeColor]:
			kwargs['label'] = nodeLabels[nodeColor]
			isFirst[nodeColor] = True
		node = nx.draw_networkx_nodes(inGraph, pos, **kwargs)
		if key in generatorList:
			node.set_edgecolor('black')
	if labels:
		nx.draw_networkx_labels(
			inGraph,
			pos,
			labels=damagedLoads,
			font_color='white',
			font_weight='bold',
			font_size=3
		)
		nx.draw_networkx_edge_labels(
			inGraph,
			pos,
			edge_labels=selected_labels,
			bbox={'alpha':0},
			font_color='red',
			font_size=4
		)
	# Final showing or saving.
	fig = matplotlib.pyplot.gcf()
	fig.set_size_inches(9, 6)
	plt.legend(loc='lower right')
	if showPlot: plt.show()
	plt.savefig(pJoin(outputDir,"feederChart.png"), dpi=800, pad_inches=0.0)

def circuitOutsideOfHazard(hazard, gfmJson):
	''' Detect if hazard field extends beyond circuit boundaries, issue a warning to the front-end if it does. '''
	x_min = hazard.hazardObj["xllcorner"]
	x_max =	hazard.hazardObj["xllcorner"] + hazard.hazardObj["ncols"] * hazard.hazardObj["cellsize"]
	y_min =	hazard.hazardObj["yllcorner"]
	y_max = hazard.hazardObj["yllcorner"] + hazard.hazardObj["nrows"] * hazard.hazardObj["cellsize"]
	returnCode = True
	for bus in gfmJson['buses']:
		busInsideBox = x_min <= bus['x'] <= x_max and y_min <= bus['y'] <= y_max
		if busInsideBox:
			returnCode = False
	return returnCode

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	hazardPath = pJoin(modelDir,inputDict['weatherImpactsFileName'])
	with open(hazardPath,'w') as hazardFile:
		hazardFile.write(inputDict['weatherImpacts'])
	with open(pJoin(modelDir, feederName + '.omd'), "r") as jsonIn:
		feederModel = json.load(jsonIn)
	# Create GFM input file.
	print("RUNNING GFM FOR", modelDir)
	critLoads = inputDict['criticalLoads']
	gfmInputTemplate = {
		'phase_variation' : float(inputDict['phaseVariation']),
		'chance_constraint' : float(inputDict['chanceConstraint']),
		'critical_load_met' : float(inputDict['criticalLoadMet']),
		'total_load_met' : float(inputDict['nonCriticalLoadMet']),
		'maxDGPerGenerator' : float(inputDict['maxDGPerGenerator']),
		'dgUnitCost' : float(inputDict['dgUnitCost']),
		'generatorCandidates' : inputDict['generatorCandidates'],
		'criticalLoads' : inputDict['criticalLoads']
	}
	gfmJson = convertToGFM(gfmInputTemplate, feederModel)
	gfmInputFilename = 'gfmInput.json'
	with open(pJoin(modelDir, gfmInputFilename), 'w') as outFile:
		json.dump(gfmJson, outFile, indent=4)
	# Check for overlap between hazard field and GFM circuit input:
	hazard = HazardField(hazardPath)
	if circuitOutsideOfHazard(hazard, gfmJson):
		outData['warning'] = 'Warning: the hazard field does not overlap with the circuit.'
	# Draw hazard field if needed.
	if inputDict['showHazardField'] == 'Yes':
		hazard.drawHeatMap(show=False)
		plt.title('') #Hack: remove plot title.
	# Run GFM
	gfmBinaryPath = pJoin(__neoMetaModel__._omfDir,'solvers','gfm', 'Fragility.jar')
	rdtInputName = 'rdtInput.json'
	if platform.system() == 'Darwin':
		#HACK: force use of Java8 on MacOS.
		javaCmd = '/Library/Java/JavaVirtualMachines/jdk1.8.0_181.jdk/Contents/Home/bin/java'
	else:
		javaCmd = 'java'
	proc = subprocess.Popen(
		[javaCmd,'-jar', gfmBinaryPath, '-r', gfmInputFilename, '-wf', inputDict['weatherImpactsFileName'],
		'-num',inputDict['scenarioCount'],'-ro',rdtInputName
		],
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		cwd=modelDir
	)
	(stdout,stderr) = proc.communicate()
	with open(pJoin(modelDir, "gfmConsoleOut.txt"), "w") as gfmConsoleOut:
		gfmConsoleOut.write(stdout.decode())
	rdtInputFilePath = pJoin(modelDir,'rdtInput.json')
	# Pull GFM input data on lines and generators for HTML presentation.
	with open(rdtInputFilePath, 'r') as rdtInputFile:
		# HACK: we use rdtInput as a string in the frontend.
		rdtJsonAsString = rdtInputFile.read()
		rdtJson = json.loads(rdtJsonAsString)
	rdtJson["power_flow"] = inputDict["power_flow"]
	rdtJson["solver_iteration_timeout"] = 300.0
	rdtJson["algorithm"] = "miqp"
	# Calculate line costs.
	lineData = {}
	for line in rdtJson["lines"]:
		lineData[line["id"]] = '{:,.2f}'.format(float(line["length"]) * float(inputDict["lineUnitCost"]))
	outData["lineData"] = lineData
	outData["generatorData"] = '{:,.2f}'.format(float(inputDict["dgUnitCost"]) * float(inputDict["maxDGPerGenerator"]))
	outData['gfmRawOut'] = rdtJsonAsString
	# Insert user-specified scenarios block into RDT input
	if inputDict['scenarios'] != "":
		rdtJson['scenarios'] = json.loads(inputDict['scenarios'])
		with open(pJoin(rdtInputFilePath), "w") as rdtInputFile:
			json.dump(rdtJson, rdtInputFile, indent=4)
	# Run GridLAB-D first time to generate xrMatrices.
	print("RUNNING 1ST GLD RUN FOR", modelDir)
	omdPath = pJoin(modelDir, feederName + ".omd")
	with open(omdPath, "r") as omd:
		omd = json.load(omd)
	# Remove new line candidates to get normal system powerflow results.
	deleteList = []
	newLines = inputDict["newLineCandidates"].strip().replace(' ', '').split(',')
	for newLine in newLines:
		for omdObj in omd["tree"]:
			if ("name" in omd["tree"][omdObj]):
				if (newLine == omd["tree"][omdObj]["name"]):
					deleteList.append(omdObj)
	for delItem in deleteList:
		del omd["tree"][delItem]
	#Load a blank glm file and use it to write to it
	feederPath = pJoin(modelDir, 'feeder.glm')
	with open(feederPath, 'w') as glmFile:
		toWrite = feeder.sortedWrite(omd['tree']) + "object jsondump {\n\tfilename_dump_reliability JSON_dump_line.json;\n\twrite_system_info true;\n\twrite_per_unit true;\n\tsystem_base 100.0 MVA;\n};\n"
		glmFile.write(toWrite)		
	#Write attachments from omd, if no file, one will be created
	for fileName in omd['attachments']:
		with open(os.path.join(modelDir, fileName),'w') as file:
			file.write(omd['attachments'][fileName])
	#Wire in the file the user specifies via zipcode.
	climateFileName = weather.zipCodeToClimateName(inputDict["simulationZipCode"])
	shutil.copy(pJoin(__neoMetaModel__._omfDir, "data", "Climate", climateFileName + ".tmy2"), pJoin(modelDir, 'climate.tmy2'))
	# Platform specific binaries for GridLAB-D First Run.
	if platform.system() == "Linux":
		myEnv = os.environ.copy()
		myEnv['GLPATH'] = omf.omfDir + '/solvers/gridlabdv990/'
		commandString = omf.omfDir + '/solvers/gridlabdv990/gridlabd.bin feeder.glm'  
	elif platform.system() == "Windows":
		myEnv = os.environ.copy()
		commandString = 'gridlabd' + ' -w ' + 'feeder.glm'
		# commandString =  '"' + pJoin(omf.omfDir, "solvers", "gridlabdv990", "gridlabd.exe") + '"' + " feeder.glm"
	elif platform.system() == "Darwin":
		myEnv = os.environ.copy()
		myEnv['GLPATH'] = omf.omfDir + '/solvers/gridlabdv990/MacRC4p1_std8/'
		commandString = '"' + omf.omfDir + '/solvers/gridlabdv990/MacRC4p1_std8/gld.sh" feeder.glm'
	# Run GridLAB-D First Time.
	proc = subprocess.Popen(commandString, stdout=subprocess.PIPE, shell=True, cwd=modelDir, env=myEnv)
	(out, err) = proc.communicate()
	with open(pJoin(modelDir, "gldConsoleOut.txt"), "w") as gldConsoleOut:
		gldConsoleOut.write(out.decode())
	with open(pJoin(modelDir, "JSON_dump_line.json"), "r") as gldOut:
		gld_json_line_dump = json.load(gldOut)
	outData['gridlabdRawOut'] = gld_json_line_dump
	# Add GridLAB-D line objects and line codes in to the RDT model.
	rdtJson["line_codes"] = gld_json_line_dump["properties"]["line_codes"]
	rdtJson["lines"] = gld_json_line_dump["properties"]["lines"]
	hardCands = list(set(gfmJson['lineLikeObjs']) - set(inputDict['hardeningCandidates']))
	newLineCands = inputDict['newLineCandidates'].strip().replace(' ', '').split(',')
	switchCands = inputDict['switchCandidates'].strip().replace(' ', '').split(',')
	for line in rdtJson["lines"]:
		line_id = line.get('id','') # this is equal to name in the OMD objects.
		object_type = line.get('object','')
		line['node1_id'] = line['node1_id'] + "_bus"
		line['node2_id'] = line['node2_id'] + "_bus"
		line_code = line["line_code"]
		# Getting ratings from OMD
		tree = omd['tree']
		nameToIndex = {tree[key].get('name',''):key for key in tree}
		treeOb = tree[nameToIndex[line_id]]
		config_name = treeOb.get('configuration','')
		config_ob = tree.get(nameToIndex[config_name], {})
		full_rating = 0
		for phase in ['A','B','C']:
			cond_name = config_ob.get('conductor_' + phase, '')
			cond_ob = tree.get(nameToIndex.get(cond_name, ''), '')
			rating = cond_ob.get('rating.summer.continuous','')
			try:
				full_rating = int(rating) #TODO: replace with avg of 3 phases.
			except:
				pass
		if full_rating != 0:
			line['capacity'] = full_rating
		else:
			line['capacity'] = 10000
		# Setting other line parameters.
		line['construction_cost'] = float(inputDict['lineUnitCost'])
		line['harden_cost'] = float(inputDict['hardeningUnitCost'])
		line['switch_cost'] = float(inputDict['switchCost'])
		if line_id in hardCands:
			line['can_harden'] = True
		if line_id in switchCands:
			line['can_add_switch'] = True
		if line_id in newLineCands:
			line['is_new'] = True
		if object_type in ['transformer','regulator']: 
			line['is_transformer'] = True
		if object_type == 'switch':
			line['has_switch'] = True
	with open(rdtInputFilePath, "w") as outFile:
		json.dump(rdtJson, outFile, indent=4)
	# Run RDT.
	print("RUNNING RDT FOR", modelDir)
	rdtOutFile = modelDir + '/rdtOutput.json'
	rdtSolverFolder = pJoin(__neoMetaModel__._omfDir,'solvers','rdt')
	rdtJarPath = pJoin(rdtSolverFolder,'micot-rdt.jar')
	# TODO: modify path, don't assume SCIP installation.
	proc = subprocess.Popen(['java', "-Djna.library.path=" + rdtSolverFolder, '-jar', rdtJarPath, '-c', rdtInputFilePath, '-e', rdtOutFile], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	(stdout,stderr) = proc.communicate()
	with open(pJoin(modelDir, "rdtConsoleOut.txt"), "w") as rdtConsoleOut:
		rdtConsoleOut.write(str(stdout))
	with open(rdtOutFile) as f:
		rdtRawOut = f.read()
	outData['rdtRawOut'] = rdtRawOut
	# Indent the RDT output nicely.
	with open(pJoin(rdtOutFile),"w") as outFile:
		rdtOut = json.loads(rdtRawOut)
		json.dump(rdtOut, outFile, indent = 4)
	# Generate and run 2nd copy of GridLAB-D model with changes specified by RDT.
	print("RUNNING 2ND GLD RUN FOR", modelDir)
	feederCopy = copy.deepcopy(feederModel)
	lineSwitchList = []
	edgeLabels = {}
	generatorList = []
	for gen in rdtOut['design_solution']['generators']:
		generatorList.append(gen['id'][:-4])
	damagedLoads = {}
	for scenario in rdtOut['scenario_solution']:
		for load in scenario['loads']:
			if load['id'] in damagedLoads.keys():
				damagedLoads[load['id'][:-4]] += 1
			else:
				damagedLoads[load['id'][:-4]] = 1
	for line in rdtOut['design_solution']['lines']:
		if('switch_built' in line and 'hardened' in line):
			lineSwitchList.append(line['id'])
			if (line['switch_built'] == True and line['hardened'] == True):
				edgeLabels[line['id']] = "SH"
			elif(line['switch_built'] == True):
				edgeLabels[line['id']] = "S"
			elif (line['hardened'] == True):
				edgeLabels[line['id']] = "H"
		elif('switch_built' in line):
			lineSwitchList.append(line['id'])
			if (line['switch_built'] == True):
				edgeLabels[line['id']] = "S"
		elif('hardened' in line):
			if (line['hardened'] == True):
				edgeLabels[line['id']] = "H"
	# Remove nonessential lines in second model as indicated by RDT output.
	for key in list(feederCopy['tree'].keys()):
		value = feederCopy['tree'][key]
		if('object' in value):
			if (value['object'] == 'underground_line') or (value['object'] == 'overhead_line'):
				if value['name'] not in lineSwitchList:
					del feederCopy['tree'][key]
	# Add generators to second model.
	maxTreeKey = int(max(feederCopy['tree'], key=int)) + 1
	maxTreeKey = max(feederCopy['tree'], key=int)
	# Load a blank glm file and use it to write to it
	feederPath = pJoin(modelDir, 'feederSecond.glm')
	with open(feederPath, 'w') as glmFile:
		toWrite =  "module generators;\n\n" + feeder.sortedWrite(feederCopy['tree']) + "object voltdump {\n\tfilename voltDump2ndRun.csv;\n};\nobject jsondump {\n\tfilename_dump_reliability test_JSON_dump.json;\n\twrite_system_info true;\n\twrite_per_unit true;\n\tsystem_base 100.0 MVA;\n};\n"# + "object jsonreader {\n\tfilename " + insertRealRdtOutputNameHere + ";\n};"
		glmFile.write(toWrite)
	# Run GridLAB-D second time.
	if platform.system() == "Windows":
		proc = subprocess.Popen(['gridlabd', 'feederSecond.glm'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, cwd=modelDir)
		(out, err) = proc.communicate()
		outData["secondGLD"] = str(os.path.isfile(pJoin(modelDir,"voltDump2ndRun.csv")))
	else:
		# TODO: make 2nd run of GridLAB-D work on Unixes.
		outData["secondGLD"] = str(False)
	# Draw the feeder.
	damageDict = {}
	for scenario in rdtJson["scenarios"]:
		for line in scenario["disable_lines"]:
			if line in damageDict:
				damageDict[line] = damageDict[line] + 1
			else:
				damageDict[line] = 1
	genDiagram(modelDir, feederModel, damageDict, critLoads, damagedLoads, edgeLabels, generatorList)
	with open(pJoin(modelDir,"feederChart.png"),"rb") as inFile:
		outData["oneLineDiagram"] = base64.standard_b64encode(inFile.read()).decode()
	# And we're done.
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","wf_clip.asc")) as f:
		weather_impacts = f.read()

	defaultInputs = {
		"feederName1": "ieee13", # "trip37" "UCS Winter 2017 Fixed" "SVECNoIslands"
		"modelType": modelName,
		"layoutAlgorithm": "geospatial",
		"modelName": modelDir,
		"user": "admin",
		"created": str(datetime.datetime.now()),
		"lineUnitCost": "3000.0",
		"switchCost": "10000.0",
		"dgUnitCost": "1000000.0",
		"hardeningUnitCost": "10.0",
		"maxDGPerGenerator": "1.0",
		# "hardeningCandidates": "A_node701-702",
		# "newLineCandidates": "TIE_A_to_C,TIE_C_to_B,TIE_B_to_A",
		# "generatorCandidates": "A_node706,A_node707,A_node708,B_node704,B_node705,B_node703",
		# "switchCandidates" : "A_node705-742,A_node705-712",
		# "criticalLoads": "C_load722",
		# "hardeningCandidates": "line068069",
		# "newLineCandidates": "line072073",
		# "generatorCandidates": "node072",
		# "switchCandidates": "line106107",
		# "criticalLoads": "node050",
		"hardeningCandidates": "L692_675",
		"newLineCandidates": "L632_671",
		"generatorCandidates": "nx645",
		"switchCandidates": "L650_632",
		"criticalLoads": "ntpmLOAD634C",
		"criticalLoadMet": "0.98",
		"nonCriticalLoadMet": "0.5",
		"chanceConstraint": "1.0",
		"phaseVariation": "0.15",
		"weatherImpacts": weather_impacts,
		"weatherImpactsFileName": "wf_clip.asc", # "wf_clip.asc" "wind_grid_1UCS.asc" "wf_clipSVEC.asc"
		"scenarios": "",
		"scenariosFileName": "",
		"scenarioCount":"3",
		"simulationDate": "2012-01-01",
		"simulationZipCode": "64735",
		"power_flow": "network_flow",
		"showHazardField": "No"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		# Copy the feeder from one place to another
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _runModel():
	# Testing the hazard class.
	"""
	Internal helper for resilient dist run model processing.
	"""
	_testHazards()
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
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_runModel()
