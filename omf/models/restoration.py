"""
omf.models.restoration is a new model currently under development. Check back in the
coming months for updates!
"""
import re, json, os, shutil, csv, math, io
from os.path import join as pJoin
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly as py
import plotly.graph_objs as go
import plotly.express as px
import networkx as nx
from scipy.stats import percentileofscore
import time
from collections import OrderedDict
import opendssdirect as dss
# from statistics import quantiles

# OMF imports
import omf
from omf import geo
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers.opendss.dssConvert import *
from omf.solvers.opendss.dssConvert import _dssToOmd_toBeTested as dssToOmd
from omf.solvers.opendss.dssConvert import _evilDssTreeToGldTree_toBeTested as evilDssTreeToGldTree
from omf.solvers.opendss.dssConvert import _treeToDss_toBeTested as treeToDss
from omf.solvers.opendss.dssConvert import _dss_to_clean_via_save_toBeTested as dss_to_clean_via_save
from omf.solvers.opendss.__init__ import reduceCircuit
from omf.solvers import PowerModelsONM
from omf.comms import createGraph

# Model metadata:
tooltip = 'Calculate load, generator and switching controls to maximize power restoration for a circuit with multiple networked microgrids.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

def makeCicuitTraversalDict(pathToOmd):
	''' Note: comment out line 99 in comms.py: "nxG = graphValidator(pathToOmdFile, nxG)" as a quick fix for the purpose of this funct
	
		Returns a dictionary of circuit objects and their properties from a given omd file
		with a set of downline loads and a set of downline objects (including loads) 
		added to their properties with the keys 'downlineLoads' and 'downlineObs'.
		
		The specific return format is a dictionary with keys representing circuit objects
		in the format of 'obType.obName' (e.g. load.load_2060) which correspond to values that are 
		dictionaries of circuit object properties such as:
		'name':'load_2060', 'object':'load', 'downlineLoads':{load.load_1002, load.load_1003, ...}, 'downlineObs':{...}, etc.
		'''	
	# TODO: remove first line in docstring once graphValidator is cleaned up
	with open(pathToOmd) as inFile:
		omd = json.load(inFile)
	obDict = {}
	namesToTypes = {}
	for ob in omd.get('tree',{}).values():
		obType = ob['object']
		obName = ob['name']
		key = f'{obType}.{obName}'
		obDict[key] = ob
		namesToTypes[obName] = obType

	digraph = createGraph(pathToOmd)
	nodes = digraph.nodes()
	for obKey, ob in obDict.items():
		obType = ob['object']
		obName = ob['name']
		obTo = ob.get('to')
		if obName in nodes:
			startingPoint = obName
		elif obTo in nodes:
			startingPoint = obTo
		else:
			continue 
		descendants = nx.descendants(digraph, startingPoint)
		ob['downlineObs'] = set()
		ob['downlineLoads'] = set()
		for circObName in descendants:
			circObType = namesToTypes.get(circObName)
			circObKey = f'{circObType}.{circObName}'
			if circObType == None:
				raise Exception(f'ERROR: Element {circObName} referenced by another object does not have its own entry in the omd')
			ob['downlineObs'].add(circObKey)
			if circObType == 'load':
				ob['downlineLoads'].add(circObKey)
	return obDict

def smartRound(val,decPl):
	'helper function to convert a value to a float and then round it if possible, otherwise just return the original value'
	try:
		return round(float(val),decPl)
	except ValueError:
		return val

def coordsFromString(entry):
	'helper function to take a location string to two integer values'
	p = re.compile(r'-?\d+\.\d+')  # Compile a pattern to capture float values
	coord = [float(i) for i in p.findall(str(entry))]  # Convert strings to float
	return coord

def locationToName(location, lines):
	'get the name of the line component associated with a given location (lat/lon)'
	# get the coordinates of the two points that make up the edges of the line
	coord = coordsFromString(location)
	coordLat = coord[0]
	coordLon = coord[1]
	row_count_lines = lines.shape[0]
	row = 0
	while row < row_count_lines:
		coord1Lat, coord1Lon, coord1 = coordsFromString(lines.loc[row, 'coords1'])
		coord2Lat, coord2Lon, coord2 = coordsFromString(lines.loc[row, 'coords2'])
		# use the triangle property to see if the new point lies on the line
		dist1 = math.sqrt((coordLat - coord1Lat)**2 + (coordLon - coord1Lon)**2)
		dist2 = math.sqrt((coord2Lat - coordLat)**2 + (coord2Lon - coordLon)**2)
		dist3 = math.sqrt((coord2Lat - coord1Lat)**2 + (coord2Lon - coord1Lon)**2)
		#threshold value just in case the component is not exactly in between the two points given
		threshold = 10e-5
		# triangle property with threshold
		if (dist1 + dist2 - dist3) < threshold:
			name = lines.loc[row, 'line_name']
			return name
		row += 1
	# if the location does not lie on any line, return 'None' (good for error testing)
	name = 'None'
	return name

def nodeToCoords(feederMap, nodeName):
	'get the latitude and longitude of a given entry in string format'
	coordStr = ''
	coordLis = []
	for key in feederMap['features']:
		if (nodeName.casefold() == key['properties'].get('name','').casefold()):
			current = key['geometry']['coordinates']
			coordLis = coordsFromString(current)
			coordStr = str(coordLis[1]) + ' ' + str(coordLis[0])
	return coordLis, coordStr

def lineToCoords(tree, feederMap, lineName):
	'get the latitude and longitude of a given entry in string format'
	coordStr = ''
	coordLis = []
	lineNode = ''
	lineNode2 = ''
	for key in tree.keys():
		try:
			if tree[key].get('name','').casefold() == lineName.casefold():
				lineNode = tree[key]['from']
				# print(lineNode)
				lineNode2 = tree[key]['to']
				# print(lineNode2)
				coordLis1, coordStr1 = nodeToCoords(feederMap, lineNode)
				# print(coordLis1)
				coordLis2, coordStr2 = nodeToCoords(feederMap, lineNode2)
				coordLis = []
				coordLis.append(coordLis1[0])
				coordLis.append(coordLis1[1])
				coordLis.append(coordLis2[0])
				coordLis.append(coordLis2[1])
				coordStr = str(coordLis[1]) + ' ' + str(coordLis[0]) + ' ' + str(coordLis[3]) + ' ' + str(coordLis[2])
		except:
			print('BAD COORDS for', tree[key])
	return coordLis, coordStr

def pullDataForGraph(tree, feederMap, outputTimeline, row):
	'get necessary data to build the activity graph'
	device = outputTimeline.loc[row, 'device']
	action = outputTimeline.loc[row, 'action']
	if action == 'Load Shed' or action == 'Battery Control' or action == 'Generator Control' or action == 'Load Pickup':
		coordLis, coordStr = nodeToCoords(feederMap, device)
	else:
		coordLis, coordStr = lineToCoords(tree, feederMap, device)
	time = outputTimeline.loc[row, 'time']
	loadBefore = outputTimeline.loc[row, 'loadBefore']
	loadAfter = outputTimeline.loc[row, 'loadAfter']
	return device, coordLis, coordStr, time, action, loadBefore, loadAfter

def microgridTimeline(outputTimeline, modelDir):
	'generate timeline of microgrid events'
	# TODO: update table after calculating outage stats
	def timelineStats(outputTimeline):
		new_html_str = """
			<table class="sortable" cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>Device</th>
						<th>Time</th>
						<th>Action</th>
						<th>Before</th>
						<th>After</th>
					</tr>
				</thead>
				<tbody>"""
		for row in range(len(outputTimeline)):
			loadBeforeStr = outputTimeline.loc[row, 'loadBefore']
			loadAfterStr = outputTimeline.loc[row, 'loadAfter']
			loadStringDict = ["open", "closed", "online", "offline"]
			if str(loadBeforeStr) not in loadStringDict:
				loadBeforeStr = '{0:.3f}'.format(float(loadBeforeStr))+' kW'
			if str(loadAfterStr) not in loadStringDict:
				loadAfterStr = '{0:.3f}'.format(float(loadAfterStr))+' kW'
			new_html_str += '<tr><td>' + str(outputTimeline.loc[row, 'device']) + '</td><td>' + str(outputTimeline.loc[row, 'time']) + '</td><td>' + str(outputTimeline.loc[row, 'action']) + '</td><td>' + loadBeforeStr + '</td><td>' + loadAfterStr + '</td></tr>'
		new_html_str +="""</tbody></table>"""
		return new_html_str
	# print all intermediate and final costs
	timelineStatsHtml = timelineStats(outputTimeline = outputTimeline)
	with open(pJoin(modelDir, 'timelineStats.html'), 'w') as timelineFile:
		timelineFile.write(timelineStatsHtml)
	return timelineStatsHtml

def customerOutageTable(customerOutageData, outageCost, modelDir):
	'''generate html table of customer outages'''
	# TODO: update table after calculating outage stats
	def customerOutageStats(customerOutageData, outageCost):
		new_html_str = """
			<table class="sortable" cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>Customer Name</th>
						<th>Duration</th>
						<th>Season</th>
						<th>Time Average kW</th>
						<th>Business Type</th>
						<th>Load Name</th>
						<th>Outage Cost</th>
					</tr>
				</thead>
				<tbody>"""
		row = 0
		while row < len(customerOutageData):
			new_html_str += '<tr><td>' + str(customerOutageData.loc[row, 'Customer Name']) + '</td><td>' + str(customerOutageData.loc[row, 'Duration']) + '</td><td>' + str(customerOutageData.loc[row, 'Season']) + '</td><td>' + '{0:.2f}'.format(customerOutageData.loc[row, 'Time Average kW']) + '</td><td>' + str(customerOutageData.loc[row, 'Business Type']) + '</td><td>' + str(customerOutageData.loc[row, 'Load Name']) + '</td><td>' + "${:,.2f}".format(outageCost[row])+ '</td></tr>'
			row += 1
		new_html_str +="""</tbody></table>"""
		return new_html_str

	# print business information and estimated customer outage costs
	try:
		customerOutageHtml = customerOutageStats(
			customerOutageData = customerOutageData,
			outageCost = outageCost)
	except:
		customerOutageHtml = ''
		#HACKCOBB: work aroun.
	with open(pJoin(modelDir, 'customerOutageTable.html'), 'w') as customerOutageFile:
		customerOutageFile.write(customerOutageHtml)
	return customerOutageHtml

def collectkWLostData(mgIDs, obMgDict, loadShapesPerLoad, outputTimeline, startTime, numTimeSteps):
	'''
	Collects kW lost data over the course of the simulation using load shapes and whether each load was shed or not at each timestep.
	
	:param mgIDs: List of microgrid IDs
	:param obMgDict: Dictionary mapping load names to microgrid IDs
	:param loadShapesPerLoad: Dictionary of load shapes for each load
	:param outputTimeline: DataFrame containing timeline data for each load
	:param startTime: Start time of the simulation
	:param numTimeSteps: Number of time steps in the simulation
	:return timeList: List of time steps
	:return kWLost: List of kW lost at each time step
	:return kWLostCumulative: List of cumulative kW at each time step
	:return kWLostPerMg: Dictionary containing lists of kW lost per microgrid at each time step
	'''
	loadList = list(loadShapesPerLoad.keys())
	timeList = [*range(startTime, numTimeSteps+startTime)]
	dfLoadTimeln, dfStatus = makeLoadOutTimelnAndStatusMap(outputTimeline, loadList, timeList)	
	#outLoadStatusDict = dfStatus.loc[:, (dfStatus == 0).any(axis=0)].to_dict(orient='list')
	outLoadStatusDict = dfStatus.to_dict(orient='list')
	kWLost = []
	kWTotal = []
	kWLostCumulative = []
	kWLostPerMg = {mgID: [] for mgID in mgIDs}
	for i in range(numTimeSteps):
		kWLostInTimestep = 0
		kWTotalInTimestep = 0
		kWLostInTimestepPerMg = {mgID: 0 for mgID in mgIDs}
		for loadName, statusList in outLoadStatusDict.items():
			experiencingOutage = 1-statusList[i]
			kW = loadShapesPerLoad[loadName][i]
			kWLostHere = experiencingOutage * kW
			kWLostInTimestep += kWLostHere
			kWTotalInTimestep += kW
			kWLostInTimestepPerMg[obMgDict.get(loadName, 'no MG')] += kWLostHere
		kWLost.append(kWLostInTimestep)
		kWTotal.append(kWTotalInTimestep)
		if i == 0:
			kWLostCumulative.append(kWLostInTimestep)
		else:
			kWLostCumulative.append(kWLostCumulative[i-1] + kWLostInTimestep)
		for mgID, kW in kWLostInTimestepPerMg.items():
			kWLostPerMg[mgID].append(kW)
	
	return timeList, kWLost, kWLostCumulative, kWLostPerMg, kWTotal

def utilityOutageGraph(timeList, kWLost, kWLostCumulative, stepSize):
	''' Generates a graph of utility lost kWh sales over time and saves it as an html file.
		The graph contains two lines: lost kWh sales at each timestep and cumulative lost kWh sales.
	'''
	utilOutFig = go.Figure()
	for varName, kWVals in [('kWh Sales Lost at Timestep', kWLost), ('kWh Sales Lost Cumulative', kWLostCumulative)]:
		trace = go.Scatter(
			x = timeList,
			y = kWVals,
			name = varName,
			mode = 'lines',
			line_shape='hv',
			hovertemplate = 
			'<b>Time Step</b>: %{x}<br>' +
			'<b>Lost kWh Sales</b>: %{y:.2f} kWh'
		)
		utilOutFig.add_trace(trace)
	utilOutFig.update_layout(
		xaxis_title = 'Time (Hours)',
		xaxis_range=[timeList[0],timeList[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':stepSize
		},
		yaxis_title = 'Lost kWh Sales (kWh)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
		title = 'Output is in kWh. To convert to $, multiply by $/kWh for your co-op at the particular time and day.'
	)
	return utilOutFig

def customerCost1(duration, season, averagekWperhr, businessType):
	''' Function to determine customer outage cost based on season, annual kWh usage, and business type.
		Only works for outages with duration of up to 25 hrs. 
	'''
	duration = float(duration)
	averagekW = float(averagekWperhr)
	# load the customer outage cost data (compared with average kW/hr usage) from the 2009 survey
	kWTemplate = {}

	# NOTE: We set a maximum average kW/hr set of values so the model doesn't crash for very large averagekWperhr inputs. However, the
	# model would still likely be very inaccurate for any value above 2500
	
	if businessType != 'residential':
		kWTemplate[5000.0] = np.array([50000,70000,120000,16000,200000,260000,300000,320000,350000,378072,410955,445306,483282,524087,568559,616684,668947,725604,787078,853750,926075,1004524,1089620,1181923,1282046,1390650])
		kWTemplate[2500.0] = np.array([20000,35000,58000,75000,95000,117000,133000,142000,145000,151437,156398,162431,168224,174468,180817,187462,194317,201440,208815,216464,224391,232609,241127,249957,259110,268598])
		kWTemplate[500.0] = np.array([10000,18000,23000,38000,48000,60000,68000,77000,78000,83668,87251,92289,96929,102164,107491,113196,119151,125447,132061,139031,146365,154087,162215,170772,179780,189263])
		kWTemplate[100.0] = np.array([4000,7000,13000,19000,23000,31000,37000,40000,41000,43174,44858,46922,48916,51080,53295,55629,58053,60588,63230,65989,68867,71871,75005,78276,81689,85251])
		kWTemplate[20.0] = np.array([1500,4000,6000,10000,14000,18000,19500,20500,21000,21794,22471,23244,24004,24809,25630,26483,27361,28269,29206,30174,31174,32207,33274,34376,35514,36689])
		kWTemplate[5.0] = np.array([500,900,1400,2050,2800,3600,4200,4850,5300,5955,6599,7363,8187,9119,10148,11298,12575,13998,15581,17343,19304,21486,23915,26618,29626,32974])
		kWTemplate[3.0] = np.array([500,900,1400,2050,2700,3500,3900,4600,5000,5666,6289,7053,7869,8802,9832,10990,12280,13723,15334,17134,19145,21392,23902,26706,29839,33339])
		kWTemplate[1.0] = np.array([400,750,1200,1900,2600,3200,3600,4000,4100,4379,4582,4844,5094,5371,5655,5958,6275,6610,6962,7333,7723,8134,8566,9021,9500,10004])
		kWTemplate[0.25] = np.array([350,700,1100,1700,2400,3000,3300,3500,3600,3760,3897,4054,4209,4374,4543,4719,4901,5090,5286,5489,5700,5919,6146,6381,6625,6878])
	else:
		kWTemplate[100.0] = np.array([4,6,7,9,12,14,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33])
		kWTemplate[8.0] = np.array([4,6,7,9,12,14,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33])
		kWTemplate[4.0] = np.array([3,5,6,8,9,11,12,13,13,13,13,13,13,13,13,13,13,13,13,13,13,13,13,13,13,13])
		kWTemplate[2.5] = np.array([3,4,6,7,8,10,11,12,12,12,12,12,12,12,12,12,12,12,12,12,12,12,12,12,12,12])
		kWTemplate[1.0] = np.array([3,4,5,6,7,8,9,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10,10])
		kWTemplate[0.25] = np.array([2,3,4,5,5,6,7,7,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8])
	# NOTE: We set a minimum average kWperhr value so the model doesn't crash for low values.
	kWTemplate[0] = np.array([0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0])

	def kWhApprox(kWDict, averagekWperhr, iterations):
		'''
		Helper function for approximating the customer outage cost for an averageKWperhr based on annual kWh by iteratively averaging the curves. 
		Each iteration, averages the curves for the kWperhr values directly above and below the averagekWperhr input, adding a new entry to the kWDict.
		With successive iterations, the kWDict becomes more granular, allowing for a more accurate estimate of the customer outage cost for the given averagekWperhr.
		'''
		step = 0
		# iterate the process a set number of times
		while step < iterations:
			#sort the current kWh values for which we have customer outage costs
			keys = list(kWDict.keys())
			keys.sort()
			# find the current kWh values estimated that are closest to the average kW/hr input...
			# ...then, estimate the outage costs for the kW/hr value directly between these
			keyCounter = 0
			newEntry = 0
			while keyCounter < len(keys)-1:
				if keyCounter == len(keys)-2:
					newEntry = (keys[keyCounter] + keys[keyCounter+1])/2
					averageCost = (kWDict[keys[keyCounter]] + kWDict[keys[keyCounter+1]])/2
					kWDict[newEntry] = averageCost
					break
				if float(averagekWperhr) > keys[keyCounter+1]:
					keyCounter+=1
				else:
					newEntry = (keys[keyCounter] + keys[keyCounter+1])/2
					averageCost = (kWDict[keys[keyCounter]] + kWDict[keys[keyCounter+1]])/2
					kWDict[newEntry] = averageCost
					break
			step+=1
			if step == iterations:
				return(kWDict[newEntry])

	# estimate customer outage cost based on annualkWh
	kWperhrEstimate = kWhApprox(kWTemplate, averagekWperhr, 20)

	# based on the annualkWh usage, import the average relationship between season/business type and outage cost
	# NOTE: This data is also taken from the Lawton survey
	if float(averagekWperhr) > 10:
		winter = np.array([10000, 19000, 27000, 41000, 59000, 72000, 83000, 91000, 93000])
		summer = np.array([11000, 20000, 31000, 43000, 60000, 73000, 84000, 92000, 94500])
		manufacturing = np.array([25000, 35000, 54000, 77000, 106000, 127000, 147000, 161000, 165000])
		construction = np.array([27000, 49000, 73000, 102000, 135000, 167000, 190000, 215000, 225000])
		finance = np.array([24000, 32000, 49000, 70000, 90000, 115000, 130000, 144000, 148000])
		public = np.array([7000, 17000, 26000, 40000, 50000, 65000, 75000, 77000, 80000])
		retail = np.array([6000, 14000, 23000, 35000, 40000, 47000, 52000, 55000, 57000])
		utilities = np.array([10000, 20000, 30000, 45000, 65000, 76000, 85000, 93000, 96000])
		mining = np.array([6000, 15000, 24000, 38000, 47000, 54000, 65000, 70000, 72000])
		services = np.array([6000, 15000, 24000, 38000, 47000, 54000, 65000, 70000, 72000])
		agriculture = np.array([5000, 10000, 17000, 22000, 26000, 30000, 37000, 40000, 42000])

	elif businessType != 'residential':
		winter = np.array([600, 1100, 2000, 3000, 4150, 5400, 6500, 7300, 7800])
		summer = np.array([550, 900, 1350, 2000, 2800, 3450, 4000, 4550, 4800])
		manufacturing = np.array([850, 1100, 1900, 2600, 3600, 4500, 5400, 6000, 6300])
		mining = np.array([1000, 1800, 2750, 4000, 5600, 6800, 8000, 8900, 9300])
		construction = np.array([1100, 1900, 3000, 4300, 5900, 7400, 8600, 9500, 10100])
		agriculture = np.array([500, 650, 1300, 1800, 2400, 3300, 4000, 4600, 4800])
		finance = np.array([850, 1100, 1900, 2600, 3600, 4500, 5400, 6000, 6300])
		retail = np.array([500, 650, 1300, 1800, 2300, 3000, 3500, 3900, 4100])
		services = np.array([500, 600, 900, 1500, 2100, 2600, 3000, 3500, 3700])
		utilities = np.array([850, 1100, 1900, 2600, 3600, 4500, 5400, 6000, 6300])
		public = np.array([400, 500, 800, 1200, 1800, 2200, 2600, 3100, 3300])
	
	# NOTE: if the customer is residential, there is no business type relationship
	else:
		summer = np.array([4, 5, 7, 8, 10, 11, 12, 13, 14])
		winter = np.array([3, 4, 5, 6, 8, 9, 10, 11, 11])

	# adjust the estimated customer outage cost by the difference between the average outage cost and the average seasonal cost
	averageSeason = np.sum((winter + summer)/2)/9
	averageSummer = np.sum(summer)/9
	averageWinter = np.sum(winter)/9
	if season == 'summer':
		seasonMultiplier = averageSummer/averageSeason
	else:
		seasonMultiplier = averageWinter/averageSeason
	kWperhrEstimate = kWperhrEstimate * seasonMultiplier

	# adjust the estimated customer outage cost by the difference between the average outage cost and the average business type cost
	if businessType != 'residential':
		averageBusiness = np.sum((manufacturing + construction + finance + retail + services + utilities + public + mining + agriculture)/9)/9
		if businessType == 'manufacturing':
			averageManufacturing = np.sum(manufacturing)/9
			businessMultiplier = averageManufacturing/averageBusiness
		elif businessType == 'construction':
			averageConstruction = np.sum(construction)/9
			businessMultiplier = averageConstruction/averageBusiness
		elif businessType == 'finance':
			averageFinance = np.sum(finance)/9
			businessMultiplier = averageFinance/averageBusiness
		elif businessType == 'retail':
			averageRetail = np.sum(retail)/9
			businessMultiplier = averageRetail/averageBusiness
		elif businessType == 'services':
			averageServices = np.sum(services)/9
			businessMultiplier = averageServices/averageBusiness
		elif businessType == 'utilities':
			averageUtilities = np.sum(utilities)/9
			businessMultiplier = averageUtilities/averageBusiness
		elif businessType == 'agriculture':
			averageAgriculture = np.sum(agriculture)/9
			businessMultiplier = averageAgriculture/averageBusiness
		elif businessType == 'mining':
			averageMining = np.sum(mining)/9
			businessMultiplier = averageMining/averageBusiness
		else:
			averagePublic = np.sum(public)/9
			businessMultiplier = averagePublic/averageBusiness
		kWperhrEstimate = kWperhrEstimate * businessMultiplier

	# adjust for inflation from 2008 to 2020 using the CPI
	# TODO: update to grab inflation rate dynamically for most recent year. As an intermediate, updated with value for Oct 2025 (from 2003 since that's when the lawton survey was published) from https://www.bls.gov/data/inflation_calculator.htm
	kWperhrEstimate = 1.78 * kWperhrEstimate
	# find the estimated customer outage cost for the customer in question, given the duration of the outage
	wholeHours = int(math.floor(duration))
	partialHour = duration - wholeHours
	try:
		outageCost = (kWperhrEstimate[wholeHours] + (kWperhrEstimate[wholeHours+1] - kWperhrEstimate[wholeHours])*partialHour) * (duration>0)
	except IndexError as e:
		if wholeHours == 25:
			outageCost = kWperhrEstimate[25]
		else:
			raise e
	return outageCost, kWperhrEstimate

def makeLoadOutTimelnAndStatusMap(outputTimeline, loadList, timeList):
	''' Helper function to create 2 dataframes:
	
		A deep copy of outputTimeline with only the loads in loadList, sorted by device name and then time

		A dataframe of load statuses at each timestep with 0 being offline and 1 being online	
	'''
	# Create a copy of outputTimeline containing only load devices in loadList sorted by device name and then time. 
	dfLoadTimeln = outputTimeline.copy(deep=True)
	dfLoadTimeln = dfLoadTimeln[dfLoadTimeln['device'].isin(loadList)]
	dfLoadTimeln['time'] = dfLoadTimeln['time'].astype(int)
	dfLoadTimeln = dfLoadTimeln.sort_values(by=['device','time'])

	# Create dataframe of load status after each timestep
	dfStatus = pd.DataFrame(np.ones((len(timeList),len(loadList))), dtype=int, index=timeList, columns=loadList)
	statusMapping = {'offline':0, 'online':1}
	for loadName in loadList:
		# Create a copy of dfLoadTimeln containing only a single load device, with rows indexed by time
		dfSoloLoadTimeln = dfLoadTimeln[dfLoadTimeln['device'] == loadName].set_index('time')
		currentStatus = statusMapping.get('online')
		for timeStep in timeList:
			if timeStep in dfSoloLoadTimeln.index:
				currentStatus = statusMapping.get(dfSoloLoadTimeln.at[timeStep,'loadAfter'])
			dfStatus.at[timeStep,loadName] = currentStatus
	
	return dfLoadTimeln, dfStatus

def calcTradMetrics(outputTimeline, loadList, loadBcsDict, loadLcsDict, mergedLoadWeights, startTime, numTimeSteps):
		''' Calculates SAIDI, SAIFI, CAIDI, CAIFI, CI, CMI, CS, and DCI over the course of the simulation for the loads in the given loadList which should have only unique entries.
			Also calculates average LCI of the loads in loadList by calculating average LCS and ranking it among LCS scores (shouldn't take the average of an index directly)
			CI = # Customer Interruptions
			CMI = # Customer Minute Interruptions 
			CS = # Customers Served
			DCI = # Distinct Customers Interrupted
			SAIDI = CMI/CS
			SAIFI = CI/CS
			CAIDI = CMI/CI = SAIDI/SAIFI
			CAIFI = CI/DCI
			'''
		dfLoadTimeln, dfStatus = makeLoadOutTimelnAndStatusMap(outputTimeline, loadList, [*range(startTime, numTimeSteps+startTime)])
		# Make sure loadList doesn't contain duplicates
		loadList = set(loadList)
		# CS (Customers Served)
		CS = len(loadList)
		# CI (Customer Interruptions) = How many total load shed actions have occurred over the event
		CI = dfLoadTimeln[dfLoadTimeln['action'] == 'Load Shed'].shape[0]
		# CMI (Customer Minutes Interrupted)= The total number of timesteps (hr) each load is offline * 60 min/hr 
		CMI = float(dfStatus.map(lambda x:1.0-x).to_numpy().sum())*60
		# DCI (Distinct Customers Interrupted)= The number of distinct loads that have been offline at some point
		DCI = len(dfStatus.columns[dfStatus.isin([0]).any()])
		SAIDI = CMI/CS if CS!=0 else 0
		SAIFI = CI/CS if CS!=0 else 0
		CAIDI = CMI/CI if CI!=0 else 0
		CAIFI = CI/DCI if DCI!=0 else 0
		# loadBcsDict contains values exclusively for all loads with BCS values and loadList contains the subset of loads given to the function
		reducedLL = set(loadBcsDict.keys()) & loadList
		sumBCS = sum([loadBcsDict[load] for load in reducedLL])
		if reducedLL:
			averageLCS = sum([loadLcsDict[load] for load in reducedLL])/len(reducedLL)
			# kind='weak' measures % of values <= current value, which is consistent with resilientCommunity
			averageLCI = float(percentileofscore(list(loadLcsDict.values()),averageLCS, kind='weak'))/100
			averageLCIxPriorities = sum([mergedLoadWeights[load] for load in reducedLL])/len(reducedLL)
		else:
			averageLCI = 'n/a'
			averageLCIxPriorities = 'n/a'
		return {'SAIDI':SAIDI,
				'SAIFI':SAIFI,
				'CAIDI':CAIDI,
				'CAIFI':CAIFI,
				'CS':	CS,
				'CI':	CI,
				'CMI':	CMI,
				'DCI':	DCI,
				'Sum BCS': sumBCS,
				'Average LCI': averageLCI,
				'Average LCIxPriorities': averageLCIxPriorities}

def tradMetricsByMgTable(outputTimeline, loadMgDict, startTime, numTimeSteps, modelDir, loadLciDict, loadLcsDict, loadBcsDict, mergedLoadPrioritiesFilePath, useLci):
	'''
	Generate table of SAIDI, SAIFI, CAIDI, and CAIFI during the outage simulation period, both for the whole system and broken down by microgrid. 
	'''
	# TODO: Update function name and docstring
	with open(mergedLoadPrioritiesFilePath) as inFile:
		mergedLoadWeights = {k:float(v) for k,v in json.load(inFile).items()}

	loadsPerMg = {}
	for load,mg in loadMgDict.items():
		loadsPerMg[mg] = loadsPerMg.get(mg,[])+[load]

	systemwideMetrics = {k:(round(v,2) if type(v) == float else v) for k,v in calcTradMetrics(outputTimeline, loadMgDict.keys(), loadBcsDict, loadLcsDict, mergedLoadWeights, startTime, numTimeSteps).items()}

	metricsPerMg = {}
	for mg, mgLoadList in loadsPerMg.items():
		metricsPerMg[mg] = {k:(round(v,2) if type(v) == float else v) for k,v in calcTradMetrics(outputTimeline, mgLoadList,  loadBcsDict, loadLcsDict, mergedLoadWeights, startTime, numTimeSteps).items()}
	metricsPerMg = OrderedDict(sorted(metricsPerMg.items()))

	lciHeaderInsert = '''<th>Est. People Served</th>
						<th>LCI of Average Load</th>
						<th>Avg. Load Priorities modified by LCI</th>''' if useLci == 'Yes' else ''
	mg_html_str = f"""
		<table class="sortable" cellpadding="0" cellspacing="0">
			<thead>
				<tr>
					<th>Microgrid</th>
					<th>SC-SAIDI</th>
					<th>SC-SAIFI</th>
					<th>SC-CAIDI</th>
					<th>SC-CAIFI</th>
					<th>Loads Served</th>
					{lciHeaderInsert}
				</tr>
			</thead>
			<tbody>"""
	lciSWContentInsert = f'''<td>{ systemwideMetrics["Sum BCS"] }</td>
							<td>{ systemwideMetrics["Average LCI"] }</td>
							<td>{ systemwideMetrics["Average LCIxPriorities"] }</td>''' if useLci == 'Yes' else ''
	mg_html_str += f"""
					<tr>
						<td>Whole System</td>
						<td>{ systemwideMetrics["SAIDI"] }</td>
						<td>{ systemwideMetrics["SAIFI"] }</td>
						<td>{ systemwideMetrics["CAIDI"] }</td>
						<td>{ systemwideMetrics["CAIFI"] }</td>
						<td>{ systemwideMetrics["CS"] }</td>
						{lciSWContentInsert}
					</tr>"""
	for mg, metrics in metricsPerMg.items():
		lciContentInsert = f'''<td>{ metrics["Sum BCS"] }</td>
							<td>{ metrics["Average LCI"] }</td>
							<td>{ metrics["Average LCIxPriorities"] }</td>''' if useLci == 'Yes' else ''
		mg_html_str += f"""
						<tr>
							<td>Microgrid ID: {mg}</td>
							<td>{ metrics["SAIDI"] }</td>
							<td>{ metrics["SAIFI"] }</td>
							<td>{ metrics["CAIDI"] }</td>
							<td>{ metrics["CAIFI"] }</td>
							<td>{ metrics["CS"] }</td>
							{lciContentInsert}
						</tr>"""
	mg_html_str +="""</tbody></table>"""
	with open(pJoin(modelDir, 'mgTradMetricsTable.html'), 'w') as customerOutageFile:
		customerOutageFile.write(mg_html_str)

	if useLci == 'Yes':
		loadsPerLciQuart = {'Low LCI':[], 'Low-Medium LCI':[], 'High-Medium LCI':[], 'High LCI':[]}
		# TODO: Consider if np.percentile is right to use considering resCom calculates percentile a little differently (# values equal to or below current val)
		quart = np.percentile(list(loadLciDict.values()),[25,50,75]) if len(loadLciDict)>0 else [0,0,0]
		for load,lci in loadLciDict.items():
			if lci <= quart[0]:
				loadsPerLciQuart['Low LCI'].append(load)
			elif lci <= quart[1]:
				loadsPerLciQuart['Low-Medium LCI'].append(load)
			elif lci <= quart[2]:
				loadsPerLciQuart['High-Medium LCI'].append(load)
			else:
				loadsPerLciQuart['High LCI'].append(load)

		metricsPerLciQuart = {}
		for lciQuart, quartLoadList in loadsPerLciQuart.items():
			metricsPerLciQuart[lciQuart] = {k:(round(v,2) if type(v) == float else v) for k,v in calcTradMetrics(outputTimeline, quartLoadList, loadBcsDict, loadLcsDict, mergedLoadWeights, startTime, numTimeSteps).items()}

		lciQuart_html_str = f"""
			<table class="sortable" cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>LCI Quartile</th>
						<th>SC-SAIDI</th>
						<th>SC-SAIFI</th>
						<th>SC-CAIDI</th>
						<th>SC-CAIFI</th>
						<th>Loads Served</th>
						<th>Est. Household Residents Served</th>
						<th>LCI of Average Residential Load</th>
						<th>Avg. Load Priorities modified by LCI</th>
					</tr>
				</thead>
				<tbody>"""
		for lciQuart, metrics in metricsPerLciQuart.items():
			lciQuart_html_str += f"""
						<tr>
							<td>{ lciQuart }</td>
							<td>{ metrics["SAIDI"] }</td>
							<td>{ metrics["SAIFI"] }</td>
							<td>{ metrics["CAIDI"] }</td>
							<td>{ metrics["CAIFI"] }</td>
							<td>{ metrics["CS"] }</td>
							<td>{ metrics["Sum BCS"] }</td>
							<td>{ metrics["Average LCI"] }</td>
							<td>{ metrics["Average LCIxPriorities"] }</td>
						</tr>"""
		lciQuart_html_str +="""</tbody></table>"""
		with open(pJoin(modelDir, 'lciQuartTradMetricsTable.html'), 'w') as customerOutageFile:
			customerOutageFile.write(lciQuart_html_str)
	else:
		lciQuart_html_str = '<!-- No LCI Quartile Table -->'
		with open(pJoin(modelDir, 'lciQuartTradMetricsTable.html'), 'w') as customerOutageFile:
			customerOutageFile.write(lciQuart_html_str)
	return mg_html_str, lciQuart_html_str

def outageIncidenceGraph(customerOutageData, outputTimeline, startTime, numTimeSteps, loadPriorityFilePath, loadMgDict):
	'''	Returns plotly figures displaying graphs of outage incidences over the course of the event data.
		Unweighted outage incidence at each timestep is calculated as (num loads experiencing outage)/(num loads).
		A load is considered to be "experiencing an outage" at a particular timestep if its "loadAfter" value 
		in outputTimeline is "offline".

		Weighted outage incidence is calculated similarly, but with loads being weighted in the calculation based
		on their priority given in the Load Priorities JSON file that can be provided as input to the model.
		If a load does not have a priority assigned to it, it is assigned a default priority of 1. 
	'''
	# TODO: Rename function

	loadList = list(loadMgDict.keys())
	mgIDs = set(loadMgDict.values())
	timeList = [*range(startTime, numTimeSteps+startTime)]
	dfLoadTimeln, dfStatus = makeLoadOutTimelnAndStatusMap(outputTimeline, loadList, timeList)

	# Calculate unweighted outage incidence
	outageIncidence = dfStatus.sum(axis=1,).map(lambda x:100*(1.0-(x/dfStatus.shape[1]))).round(3).values.tolist()

	#Calculate weighted outage incidence based on 'Business Type'
	includeGroupWeights = False
	if includeGroupWeights:
		typeWeights = {'residential': 64, 'retail':32, 'agriculture':16, 'public':8, 'services':4, 'manufacturing':2}
		leftoverCustomers = set(loadList)
		Sum_wc_nc = np.zeros(len(outageIncidence))
		Sum_wc_Nc = 0
		for customerType in typeWeights.keys():
			customersOfType = customerOutageData[customerOutageData['Business Type'].str.contains(customerType)]['Customer Name'].values.tolist()
			dfStatusOfType = dfStatus[customersOfType]
			Nc = dfStatusOfType.shape[1]
			Sum_wc_Nc += typeWeights[customerType]*Nc
			nc = dfStatusOfType.sum(axis=1,).map(lambda x: Nc-x).to_numpy()
			Sum_wc_nc = np.add(Sum_wc_nc,typeWeights[customerType]*nc) 
			leftoverCustomers = leftoverCustomers - set(customersOfType)
		dfStatusOfLeftovers = dfStatus[list(leftoverCustomers)]
		Nc = dfStatusOfLeftovers.shape[1]
		Sum_wc_Nc += 1*Nc
		nc = dfStatusOfLeftovers.sum(axis=1,).map(lambda x: Nc-x).to_numpy()
		Sum_wc_nc = np.add(Sum_wc_nc,1*nc) 
		weightedOutageIncidence = np.around((100*Sum_wc_nc/Sum_wc_Nc), 3).tolist()
	###################################################################################################################################################################
	# TODO: Clean this up to make it more readable. For now though, functionality is the focus.
	###################################################################################################################################################################

	def calcWeightedOI(loadWeights):
		''' Individually weighted outage incidence calculated as
			
			(Sum from i=1 to N of w_i*n_i)/(Sum from i=1 to N of w_i)

			N = number of loads total,
			
			ni = (1-status) of load i,
			
			wi = weight of load i 
		'''
		Sum_wi_ni = np.zeros(len(outageIncidence)) #one entry for each timestep
		Sum_wi = 0
		for load_i in loadList:
			wi = loadWeights.get(load_i,1)
			ni = dfStatus[load_i].map(lambda x: 1-x).to_numpy()
			wi_ni = wi * ni
			Sum_wi += wi
			Sum_wi_ni = np.add(Sum_wi_ni, wi_ni)
		indivWeightedOI = np.around((100*Sum_wi_ni/Sum_wi),3).tolist()
		return indivWeightedOI
	def startAt0(inList):
		''' If a list doesn't start at 0, insert a 0 at the 0th position.
			Modifies the original input list and also returns it.'''
		if startTime != 0:
			inList.insert(0,0)
		return inList

	# Calculate weighted outage incidence based on individually assigned weights
	with open(loadPriorityFilePath) as inFile:
		loadWeights = {k:float(v) for k,v in json.load(inFile).items()}

	indivWeightedOI = calcWeightedOI(loadWeights)

	listMean = lambda lst: sum(lst)/len(lst)

	startAt0(timeList)
	mgOIFigures = {}
	for targetID in mgIDs:
		mgLoadMask = 	{load:(1 if id == targetID else 0) for (load,id) in loadMgDict.items()}
		mgLoadWeights = {load:(val*loadWeights.get(load,1)) for (load,val) in mgLoadMask.items()}
		mgOI = 			calcWeightedOI(mgLoadMask)
		mgOIWeighted = 	calcWeightedOI(mgLoadWeights)
		meanMgOI = 		listMean(mgOI)
		meanMgOIWeighted = listMean(mgOIWeighted)
		startAt0(mgOI)
		startAt0(mgOIWeighted)
		mgOIFigures[targetID] = go.Figure()
		mgOIFigures[targetID].add_trace(go.Scatter(
			x=timeList,
			y=mgOI,
			mode='lines',
			line_shape='hv',
			name='Unweighted OI',
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>Unweighted OI for Microgrid {targetID}</b>: %{{y:.3f}}%'))
		mgOIFigures[targetID].add_trace(go.Scatter(
			x=timeList,
			y=mgOIWeighted,
			mode='lines',
			line_shape='hv',
			name='Weighted OI',
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>Weighted OI for Microgrid {targetID}</b>: %{{y:.3f}}%'))
		mgOIFigures[targetID].update_layout(
			xaxis_title='Time (Hours)',
			xaxis_range=[timeList[0],timeList[-1]],
			xaxis={
				'tickmode':'linear',
				'dtick':timeList[1]-timeList[0]
			},
			yaxis_title='Outage Incidence (%)',
			yaxis_range=[-5,105],
			title=f'Microgrid {targetID}',
			legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
		# Add mean lines
		mgOIFigures[targetID].add_shape(
			type="line",
			xref="paper", 
			yref="y", 
			x0=0, 
			y0=meanMgOI, 
			x1=1.0,
			y1=meanMgOI, 
			line=dict(
				color="blue",
				#width=3,
				dash="dash"
			)
		)
		mgOIFigures[targetID].add_annotation(
			xref="x",
			yref="y",
			x=0.5,
			y=meanMgOI+5.0,
			xanchor="left",
			text=f'Mean Unweighted OI: {round(meanMgOI,2)}%',
			showarrow=False
		)
		mgOIFigures[targetID].add_shape(
			type="line",
			xref="paper", 
			yref="y", 
			x0=0, 
			y0=meanMgOIWeighted, 
			x1=1.0,
			y1=meanMgOIWeighted, 
			line=dict(
				color="red",
				#width=3,
				dash="dash"
			)
		)
		mgOIFigures[targetID].add_annotation(
			xref="x",
			yref="y",
			x=6.5,
			y=meanMgOIWeighted-5.0,
			xanchor="left",
			text=f'Mean Weighted OI: {round(meanMgOIWeighted,2)}%',
			showarrow=False
		)

	#Take means before potentially adding 0 to the beginning of the lists
	meanOI = listMean(outageIncidence)
	meanWOI = listMean(indivWeightedOI)
	#If start is not at time 0, show that outage incidence at time 0 would be 0%
	startAt0(outageIncidence)
	startAt0(indivWeightedOI)
	outageIncidenceFigure = go.Figure()
	outageIncidenceFigure.add_trace(go.Scatter(
		x=timeList,
		y=outageIncidence,
		mode='lines',
		line_shape='hv',
		name='Unweighted Outage Incidence',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Unweighted Outage Incidence</b>: %{y:.3f}%'))
	if includeGroupWeights:
		outageIncidenceFigure.add_trace(go.Scatter(
			x=timeList,
			y=weightedOutageIncidence,
			mode='lines',
			line_shape='hv',
			name='Group-Weighted Outage Incidence',
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			'<b>Group-Weighted Outage Incidence</b>: %{y:.3f}%'))
	outageIncidenceFigure.add_trace(go.Scatter(
		x=timeList,
		y=indivWeightedOI,
		mode='lines',
		line_shape='hv',
		name='Weighted Outage Incidence',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Weighted Outage Incidence</b>: %{y:.3f}%'))
	# Add mean lines
	outageIncidenceFigure.add_shape(
		type="line",
		xref="paper", 
		yref="y", 
		x0=0, 
		y0=meanOI, 
		x1=1.0,
		y1=meanOI, 
		line=dict(
			color="blue",
			#width=3,
			dash="dash"
		)
	)
	outageIncidenceFigure.add_annotation(
		xref="x",
		yref="y",
		x=0.5,
		y=meanOI+5.0,
		xanchor="left",
		text=f'Mean Unweighted OI: {round(meanOI,2)}%',
		showarrow=False
	)
	outageIncidenceFigure.add_shape(
		type="line",
		xref="paper", 
		yref="y", 
		x0=0, 
		y0=meanWOI, 
		x1=1.0,
		y1=meanWOI, 
		line=dict(
			color="red",
			#width=3,
			dash="dash"
		)
	)
	outageIncidenceFigure.add_annotation(
		xref="x",
		yref="y",
		x=6.5,
		y=meanWOI-5.0,
		xanchor="left",
		text=f'Mean Weighted OI: {round(meanWOI,2)}%',
		showarrow=False
	)
	# Edit the layout 
	outageIncidenceFigure.update_layout(
		xaxis_title='Time (Hours)',
		xaxis_range=[timeList[0],timeList[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':timeList[1]-timeList[0]
		},
		yaxis_title='Outage Incidence (%)',
		yaxis_range=[-5,105],
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))

	return outageIncidenceFigure, mgOIFigures

def makeTaofiAndTaodiHist(outputTimeline, startTime, numTimeSteps, loadList):
	''' Generate histogram of TAOFI and TAODI for each load.
		
		Outputs: taofiHist, taodiHist, TAOFI, TAODI

		TAOFI (Time Avg. Outage Frequency Index)= 1/Average period length where a period is defined as the time from one load shed to the next load shed. 

		TAODI (Time Avg. Outage Duration Index)= Total duration of outages for a load over the total duartion of the simulation.  
	'''
	endTime = numTimeSteps+startTime
	dfLoadTimeln, dfStatus = makeLoadOutTimelnAndStatusMap(outputTimeline, loadList, [*range(startTime, endTime)])
	dfStatus = dfStatus.map(lambda x:1.0-x)
	TAOFI = {}
	TAODI = {}
	for loadName in loadList:
		dfLoadSheds = dfLoadTimeln[(dfLoadTimeln['device'] == loadName)][(dfLoadTimeln['action'] == 'Load Shed')]
		numLoadSheds = dfLoadSheds.shape[0]
		timeOfFirstLoadShed = dfLoadSheds['time'].min()
		timeOfLastLoadShed = dfLoadSheds['time'].max()
		#TODO: Multiply denomenator for TAOFI by the time step size if not 1 hour
		TAOFI[loadName] = (numLoadSheds-1)/(timeOfLastLoadShed-timeOfFirstLoadShed)
		TAODI[loadName] = 100*dfStatus[loadName].sum()/numTimeSteps
	minVals = (min(list(TAOFI.values())), 0)
	maxVals = (max(list(TAOFI.values())), 100)
	numBins = 45
	binSizes = ((maxVals[0]-minVals[0])/numBins, (maxVals[1]-minVals[1])/numBins)

	taofiHist = go.Figure()
	taofiHist.add_trace(go.Histogram(
		x=list(TAOFI.values()),
		name='TAOFI', # name used in legend and hover labels
		xbins=dict(
			start=minVals[0],
			end=maxVals[0]+binSizes[0],
			size=binSizes[0]
		),
		bingroup=1,
		marker_color='#0000ff'
	))
	taofiHist.update_layout(
		xaxis_title_text='TAOFI Values', # xaxis label
		yaxis_title_text='Load Count', # yaxis label
		barmode='overlay',
		bargap=0.1 # gap between bars of adjacent location coordinates
	)

	taodiHist = go.Figure()
	taodiHist.add_trace(go.Histogram(
		x=list(TAODI.values()),
		name='TAODI', # name used in legend and hover labels
		xbins=dict(
			start=minVals[1],
			end=maxVals[1]+binSizes[1],
			size=binSizes[1]
		),
		bingroup=1,
		marker_color='#ff0000'
	))
	taodiHist.update_layout(
		xaxis_title_text='TAODI Values (%)', # xaxis label
		yaxis_title_text='Load Count', # yaxis label
		barmode='overlay',
		bargap=0.1 # gap between bars of adjacent location coordinates
	)
	return taofiHist, taodiHist, TAOFI, TAODI

def makeLciTaofiTaodiScatter(loadLciDict, TAOFI, TAODI):
	''' Returns scatter plots of TAOFI vs LCI and TAODI vs LCI with accompanying correlation coefficient. 
		Only includes loads with LCI values.
	'''
	# Enforce standard ordering for loads in loadLciDict
	orderedVals = {'LCI':[], 'TAODI':[], 'TAOFI':[]}
	for load, lci in loadLciDict.items():
		orderedVals['LCI'].append(lci)
		orderedVals['TAODI'].append(TAODI[load])
		orderedVals['TAOFI'].append(TAOFI[load])
	dfOrderedVals = pd.DataFrame(orderedVals)

	def makeCorrReport(var1,var2):
		''' Takes two variable names as input and returns a string reporting the correlation and an interpretation of it.'''
		dfReduced = dfOrderedVals[[var1,var2]].dropna()
		corr = round(np.corrcoef(dfReduced[var1],dfReduced[var2])[0][1],3)
		sign = ' negative ' if corr < 0 else ' '
		absCorr = abs(corr)
		if absCorr == 0:
			level = "No"
		elif absCorr < 0.3:
			level = 'Very low'
		elif absCorr < 0.5:
			level = 'Low'
		elif absCorr < 0.7:
			level = 'Moderate'
		elif absCorr < 0.9:
			level = 'High'
		elif absCorr >= 0.9:
			level = 'Very high'
		else:
			return 'Correlation is undefined because at least one variable has 0 variance.'
		# Levels taken from https://www.andrews.edu/~calkins/math/edrm611/edrm05.htm#:~:text=Correlation%20coefficients%20whose%20magnitude%20are%20between%200.7%20and%200.9%20indicate,can%20be%20considered%20moderately%20correlated.
		return f'R = {corr} ({level}{sign}correlation)'
	
	lciTaodiScatter = px.scatter(
		pd.DataFrame(orderedVals),
		x='LCI',
		y='TAODI',
		trendline='ols',
		title = makeCorrReport('LCI','TAODI'),
		color_discrete_sequence=["red"]
	)
	lciTaofiScatter = px.scatter(
		pd.DataFrame(orderedVals),
		x='LCI',
		y='TAOFI',
		trendline='ols',
		title = makeCorrReport('LCI','TAOFI'),
	)
	return lciTaofiScatter, lciTaodiScatter

def getMicrogridInfo(modelDir, pathToOmd, settingsFile, makeCSV = True):
	'''	Gathers microgrid info including loads and other circuit objects in each microgrid by finding what microgrid each load's parent bus is designated as having. 
		Microgrid assignments to buses are taken from settingsFile so that we can see what microgrid assignments the 
		code is working with, not just what they are intended to be via the microgrid tagging input file

		Returns a dictionary with keys loadMgDict, busMgDict, obMgDict, and mgIDs

		loadMgDict, busMgDict, and obMgDict correspond to dictionaries mapping circuit object names to microgrid labels.
		loadMgDict corresponds to loads, busMgDict corresponds to buses, and obMgDict corresponds to all circuit objects that have the parent bus. 
		mgIDs corresponds to a set of the unique microgrid labels derived from the values of busMgDict.	
		
		If makeCSV is True, which is default, creates a file called microgridAssignmentOutputs.csv containing 
		the information from loadMgDict for inspection by users.
	'''

	with open(settingsFile) as inFile:
		settingsData = json.load(inFile)
	busMgDict = {}
	for busName,v in settingsData['bus'].items():	
		busMgDict[busName] = v.get('microgrid_id', 'no MG')
	
	with open(pathToOmd) as inFile:
		omd = json.load(inFile)
	loadMgDict = {}
	obMgDict = {}
	for ob in omd.get('tree',{}).values():
		# The settings.json generated by PowerModelsONM forces things lowercase, so this needs to too so that names in settings.json can be used to access values here
		lowercaseName = ob['name'].lower()
		if ob['object'] == 'load':
			loadMgDict[lowercaseName] = busMgDict[ob['parent'].lower()]
		if 'parent' in ob.keys():
			obMgDict[lowercaseName] = busMgDict.get(ob['parent'].lower(),'no MG')
	
	if makeCSV:
		with open(pJoin(modelDir,'microgridAssignmentOutputs.csv'), 'w', newline='') as file:
			writer = csv.writer(file)
			writer.writerow(['load name','microgrid_id'])
			#for loadName,mg_id in loadMgDict.items():
			#	writer.writerow([loadName,mg_id])
			for busName,mg_id in busMgDict.items():
				writer.writerow([busName,mg_id])
			for obName,mg_id in obMgDict.items():
				writer.writerow([obName,mg_id])

	mgIDs = set(busMgDict.values())

	return {'loadMgDict':loadMgDict, 'busMgDict':busMgDict, 'obMgDict':obMgDict, 'mgIDs':mgIDs}

def getResComInfo(modelDir, pathToOmd, useLci, rescomOutputFilePath):
	''' Returns a complete list of loads on the circuit and 3 dictionaries of loads and their LCI's, LCS's, & BCS's respectively in the following format:
		
		[loadName1, loadName2, loadname3, ...],

		{loadName1:lci1, loadName2:lci2, loadName3:lci3, ...},

		{loadName1:lcs1, loadName2:lcs2, loadName3:lcs3, ...},

		{loadName1:bcs1, loadName2:bcs2, loadName3:bcs3, ...}

		If there are any loads without lci/lcs/bcs on the circuit, they won't have entries in the dictionaries, but all loads are represented in the complete load list. 
	'''
	completeLoadList = []	
	with open(pathToOmd,'r') as omdFile:
		omd = json.load(omdFile)
	for ob in omd.get('tree', {}).values():
		if ob['object'] == 'load':
			completeLoadList.append(ob['name'])
	lciDict = {}
	lcsDict = {}
	bcsDict = {}
	if useLci == 'Yes':
		try:
			with open(rescomOutputFilePath, mode='r') as f:
				rescomLoadDict = json.load(f)
		except TypeError:
			raise Exception('ERROR: You may have selected "Yes" for "Use LCI" without uploading a valid .json file to "Load LCI Data (.json file)".')
		except Exception as e:
			raise e
		for loadName in completeLoadList:
			loadData = rescomLoadDict.get(f'load.{loadName}')
			if loadData != None:
				try:
					lciDict[loadName] = loadData['locational crit index']
					lcsDict[loadName] = loadData['locational crit score']
					bcsDict[loadName] = loadData['base crit score']
				except KeyError as e:
					errorString = f'ERROR: Missing expected key {e} in Load LCI Data (.json file) for load {loadName}. Data found: {loadData}'
					raise KeyError(errorString)	
	return completeLoadList, lciDict, lcsDict, bcsDict

def combineLoadPriorityWithLCI(modelDir, loadList, loadPriorityFilePath, loadLciDict, lciImpact):
	'''	Creates a JSON file called loadWeightsMerged.json containing user-input load priorities combined with LCI values via RMS and weighted by lciImpact.

		If an empty JSON file is provided for loadPriorityFilePath, just returns a JSON file with max(1,lci*lciImpact) for each load.

		Returns a string containing the path to loadWeightsMerged.json
	'''
	# Previous versions of this function contained code transforming each load priority to nullify a weighting scheme within PowerModelsONM. 
	# After discussion with David Fobes, one of the primary contributors to PowerModelsONM, we decided not to include this transformation 
	# because the aforementioned weighting scheme was for weighting load blocks with microgrids in them, not individual loads themselves. 
	# Block weights are seprate from but related to load priorities in that they help ensure microgrids have higher priority for supporting
	# themselves rather than reaching out to neighboring blocks. 
	# 	David Fobes - dfobes@lanl.gov
	# 	PowerModelsONM Primary Contributor
	# 	R&D Manager at Los Alamos National Laboratory (LANL)
	
	lciImpact = float(lciImpact)
	with open(loadPriorityFilePath) as inFile:
		loadWeights = {}
		outOfBoundsLW = {}
		for load,weight in json.load(inFile).items():
			weight = float(weight)
			loadWeights[load] = weight
			if weight < 1.0 or weight > 100.0:
				outOfBoundsLW[load] = weight
		if outOfBoundsLW:
			raise Exception(f"ERROR - Load priorities must be between 1 and 100 inclusive. The uploaded load priorities include: {outOfBoundsLW}")
	# If-statement outside of the function definition so it isn't checked every time the function is called
	if loadWeights:
		mergeLciAndWeights = lambda lci,weight : ((lciImpact*lci**2 + weight**2)/(1+lciImpact))**0.5
	else:
		mergeLciAndWeights = lambda lci,weight : max(1,lci*lciImpact)
	loadWeightsMerged = {}
	for loadName in loadList:
		# Loads defaulting to weight 1 is done to reflect that choice within PowerModelsONM and the expected priorities scale discussed above
		loadWeight = loadWeights.get(loadName,1)
		lci = loadLciDict.get(loadName)
		if lci != None:
			# PowerModelsONM expects a priorities scale of 1=non-critical, 10=sub-critical, 100=critical. 
			# e^(x0.0460517) is the exponential best fit for (0,1),(50,10),(100,100)
			# Using that transform, we can force linear lci values into the exponential scale expected by PowerModelsONM 
			# (Ex: the load with 50% lci would have ~10 expLci, appropriately representing being subcritical)
			lciAsPercent = 100*lci
			expLci = math.e**(lciAsPercent*0.0460517)
			loadWeightsMerged[loadName] = mergeLciAndWeights(expLci,loadWeight)
		else:
			loadWeightsMerged[loadName] = loadWeight
	mergedLoadWeightsFile = pJoin(modelDir, 'loadWeightsMerged.json')
	with open(mergedLoadWeightsFile, 'w') as outfile:
		json.dump(loadWeightsMerged, outfile)
	return mergedLoadWeightsFile

def runMicrogridControlSim(modelDir, solFidelity, eventsFilename, loadPriorityFile, microgridTaggingFile):
	''' Runs a microgrid control simulation using PowerModelsONM to determine optimal control actions during a configured outage event.
		Once the simulation is run, the results are stored in an output file called output.json in the working directory. 
		Before running the simulation, a settings file for the simulation is generated using the feeder file, a load priorities file, and a microgrid tagging file. 
	'''
	# Setup ONM if it hasn't been done already.
	if not PowerModelsONM.check_instantiated():
		PowerModelsONM.install_onm()

	# Define file paths for use in function
	lpFile = loadPriorityFile if loadPriorityFile != None else ''
	mgFile = microgridTaggingFile if microgridTaggingFile != None else ''
	circuitPath = pJoin(modelDir,'circuit_simplified.dss')
	settingsPath = pJoin(modelDir,'settings.json')
	outputPath = pJoin(modelDir,'output.json')
	eventsPath = pJoin(modelDir,eventsFilename)

	PowerModelsONM._build_settings_file_toBeTested(
		circuitPath = circuitPath,
		settingsPath = settingsPath, 
		loadPrioritiesFile = lpFile, 
		microgridTaggingFile = mgFile)
	
	# get mip_solver_gap info (solFidelity)
	solFidelityVal = 0.05 #default to medium fidelity
	if solFidelity == '0.10':
		solFidelityVal = 0.10
	elif solFidelity == '0.02':
		solFidelityVal = 0.02
	
	# If there's already an ouput file in memory, remove it so that if there's a problem with run_onm and a new output file isn't created, the code doesn't proceed with an old ouput file
	if os.path.exists(outputPath):
		os.remove(outputPath)

	PowerModelsONM._run_onm_toBeTested(
		circuitPath = circuitPath,
		settingsPath = settingsPath,
		outputPath = outputPath,
		eventsPath = eventsPath,
		mip_solver_gap = solFidelityVal
	)	

	# Give extra time for output.json to be written since it's a big file and we've encountered issues where the code will move on from run_onm() before the output file is finished writing
	maxWait = 60*15
	waitTime = 30
	maxIters = maxWait//waitTime
	for i in range(0,maxIters):
		print(f'{(waitTime*i)//60}m {(waitTime*i)%60}s elapsed since PowerModelsONM finished running.')
		if os.path.exists(outputPath):
			print('output.json successfully generated by PowerModelsONM')
			break
		elif i >= maxIters-1:
			raise Exception(f'ERROR - output.json still not written {maxWait//60}m {maxWait%60}s after PowerModelsONM finished running. This exceeds the maximum allotted wait time. PowerModelsONM may have encountered an error during the simulation. You can try running your feeder through the feeder reduction code before uploading it again to see if that resolves the issue.')
		else:
			time.sleep(waitTime)

def genProfilesByMicrogrid(mgIDs, obMgDict, powerflow, simTimeSteps, startTime, kWLost, kWLostPerMg, kWTotal):
	''' Aggregates powerflow data by powerflow circuit object type to create generation profiles.
		Aggregated powerflow data is separated based on the microgrid in which each pf circuit object is located.
		Generation profiles for the entire system are also calculated alongside gen profiles for each microgrid. 
		Also adds demand not served to the stacked area plots to visualize total demand.

		Outputs a touple containing two elements: gensFigure, mgGensFigures

		gensFigure is a plotly figure visualizing generation profiles for the whole system. 
		
		mgGensFigures is a dictionary with strings containing microgrid IDs as the keys and plotly figures visualizing corresponding generation profiles as values. 
	'''

	# We want these specific types of powerflow (IFF they're in the output.json) in this order for the sake of the order that they're drawn on the stacked area chart later.
	# Intentionally omitted bus, switch, and protection
	ordDesiredTypes = ['storage','solar','generator','voltage_source']
	pfTypes = [type for type in ordDesiredTypes if type in powerflow[0]]
	pfDataAggregated = {mgID:pd.DataFrame(0, index=simTimeSteps, columns=pfTypes) for mgID in mgIDs.union({'no MG'})}
	pfDataSystemwide = pd.DataFrame(0, index=simTimeSteps, columns=pfTypes)
	pfTotalsAtEachT = []
	
	for timestepIndex in range(len(powerflow)):
		pfTotalAtT = 0
		for pfType in pfTypes:
			for obName, obData in powerflow[timestepIndex][pfType].items():
				obPf = sum(obData.get('real power setpoint (kW)',[0]))
				obPf *= -1 if pfType == "storage" else 1
				obMg = obMgDict.get(obName, 'no MG')
				pfDataAggregated[obMg].at[simTimeSteps[timestepIndex],pfType] += obPf
				pfDataSystemwide.at[simTimeSteps[timestepIndex],pfType] += obPf
				pfTotalAtT += obPf
		pfTotalsAtEachT.append(pfTotalAtT)

	# minVal is defined as the lowest total of stacked vals (without adding in kWLost since it's never negative) and individual vals
	# 	This is to account for if the graph has multiple negative vals stacking bringing things lower than any individual val would.
	# maxVal is defined as the highest total of stacked vals (including kWLost) and individual vals
	# 	This is to account for the case where the graph goes higher than the total stacked vals because of order of stacked layers
	#	I.e. a very high positive val layer is drawn before a very large negative val layer is drawn "atop" it. The total is lower than the graph is drawn since the high pos val was drawn first.
	maxVal = float('-inf')
	for i, val in enumerate(pfTotalsAtEachT):
		maxVal = max(maxVal, val+kWLost[i])
	minVal = min(pfTotalsAtEachT)
	for df in pfDataAggregated.values():
		minVal = min(minVal, df.min().min())
		maxVal = max(maxVal, df.max().max())
	axisPadding = 0.05*(maxVal-minVal)
	graphMin = minVal-axisPadding
	graphMax = maxVal+axisPadding
	
	pfTypeNameMap = {
		'voltage_source':'Grid',
		'solar':'Solar DG',
		'storage':'Energy Storage',
		'generator':'Diesel DG'
	}
	gensFigure = go.Figure()
	for pfType in pfTypes:
		pfTypeRenamed = pfTypeNameMap.get(pfType,pfType)
		gensFigure.add_trace(go.Scatter(
			fill='tonexty',
			stackgroup='group1',
			x=simTimeSteps,
			y=pfDataSystemwide[pfType].to_list(),
			mode='lines',
			line_shape='hv',
			name=pfTypeRenamed,
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>{pfTypeRenamed}</b>: %{{y:.3f}}kW'))
	gensFigure.add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group1',
		x=simTimeSteps,
		y=kWLost,
		mode='lines',
		line_shape='hv',
		name='Demand Not Served',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Demand Not Served</b>: %{{y:.3f}}kW'))

	# Traces for debugging. Do not leave these uncommented when pushing
	"""
	gensFigure.add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group3',
		x=simTimeSteps,
		y=kWTotal,
		mode='lines',
		line_shape='hv',
		name='Total Demand Scheduled',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Total Demand Scheduled</b>: %{{y:.3f}}kW'))

	totalPowerFlow = pfDataSystemwide.sum(axis=1).to_list()
	factor = [powerflow/projected for powerflow, projected in zip(totalPowerFlow,kWTotal)]

	gensFigure.add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group4',
		x=simTimeSteps,
		y=totalPowerFlow,
		mode='lines',
		line_shape='hv',
		name='Total Power Flow',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Total Power Flow</b>: %{{y:.3f}}kW'))
	
	gensFigure.add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group5',
		x=simTimeSteps,
		y=factor,
		mode='lines',
		line_shape='hv',
		name='Factor (total power flow / scheduled demand)',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Factor (total power flow / scheduled demand)</b>: %{{y:.3f}}'))
	"""
	gensFigure.update_layout(
		xaxis_title='Time (Hours)',
		xaxis_range=[simTimeSteps[0],simTimeSteps[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':simTimeSteps[1]-simTimeSteps[0]
		},
		yaxis_title='Power (kW)',
		yaxis_range=[graphMin, graphMax],
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))

	mgGensFigures = {}
	for mgID in mgIDs:
		mgGensFigures[mgID] = go.Figure()
		for pfType in pfTypes:
			pfTypeRenamed = pfTypeNameMap.get(pfType,pfType)
			mgGensFigures[mgID].add_trace(go.Scatter(
				fill='tonexty',
				stackgroup='group1',
				x=simTimeSteps,
				y=pfDataAggregated[mgID][pfType].to_list(),
				mode='lines',
				line_shape='hv',
				name=pfTypeRenamed,
				hovertemplate=
				'<b>Time Step</b>: %{x}<br>' +
				f'<b>{pfTypeRenamed} for Microgrid {mgID}</b>: %{{y:.3f}}kW'))
		mgGensFigures[mgID].add_trace(go.Scatter(
			fill='tonexty',
			stackgroup='group1',
			x=simTimeSteps,
			y=kWLostPerMg[mgID],
			mode='lines',
			line_shape='hv',
			name='Demand Not Served',
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>Demand Not Served</b>: %{{y:.3f}}kW'))
		mgGensFigures[mgID].update_layout(
			xaxis_title='Time (Hours)',
			xaxis_range=[simTimeSteps[0],simTimeSteps[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':simTimeSteps[1]-simTimeSteps[0]
		},
			yaxis_title='Power (kW)',
			yaxis_range=[graphMin, graphMax],
			title=f'Microgrid {mgID}',
			legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))

	return gensFigure, mgGensFigures

def graphMicrogrid(modelDir, pathToOmd, pathToJson, pathToCsv, loadPriorityFile, loadMgDict, obMgDict, busMgDict, mgIDs, loadLciDict, loadLcsDict, loadBcsDict, useLci):
	''' Run full microgrid control process. '''
	# Gather output data.
	with open(pJoin(modelDir,'output.json')) as inFile:
		data = json.load(inFile)
		genProfiles = data['Generator profiles']
		simTimeStepsRaw = data['Simulation time steps']
		numTimeSteps = len(simTimeStepsRaw)
		stepSize = simTimeStepsRaw[1]-simTimeStepsRaw[0]
		voltages = data['Voltages']
		simulationDuration = stepSize * numTimeSteps
		loadServed = data['Load served']
		storageSOC = data['Storage SOC (%)']
		deviceActionTimeline = data['Device action timeline']
		powerflow = data['Powerflow output']
	
	startTime = 1
	timestep = startTime

	if type(simTimeStepsRaw[0]) == str:
		raise Exception("ERROR - Simulation timesteps are datetime strings in output.json. They need to be floats representing hours")
	simTimeSteps = [float(i)+startTime for i in simTimeStepsRaw]
	
	timelineActions = []
	cumulativeLoadsShed = []
	prevLoadsShed = []
	powerflowOld = {}
	switchConfigsOld = {switch:'closed' for switch in deviceActionTimeline[0]['Switch configurations'].keys()}

	for deviceActions in deviceActionTimeline:
		# TODO: replace the stuff with incrementing timestep in the loop to just use the following:
		#		for i, deviceActions in enumerate(deviceActionTimeline):
		#			timestep = i+startTime
		# Switch timeline actions
		switchActions = []
		switchConfigsNew = deviceActions['Switch configurations']
		for switch in switchConfigsNew:
			if switchConfigsNew[switch] != switchConfigsOld[switch]:
				switchActions.append({
					'device':		switch,
					'time':			str(timestep),
					'action':		'Switch Opening' if switchConfigsNew[switch] == 'open' else 'Switch Closing',
					'loadBefore':	switchConfigsOld[switch],
					'loadAfter':	switchConfigsNew[switch]
				})
		switchConfigsOld = deviceActions['Switch configurations']
		
		# Load timeline actions
		loadActions = []
		allShed = deviceActions['Shedded loads']
		cumulativeLoadsShed = cumulativeLoadsShed + allShed
		loadsPickedUp = [load for load in prevLoadsShed if load not in allShed]
		newShed = [load for load in allShed if load not in prevLoadsShed]
		for load in newShed:
			loadActions.append({
					'device':		load,
					'time':			str(timestep),
					'action':		'Load Shed',
					'loadBefore':	'online',
					'loadAfter':	'offline'
				})
		for load in loadsPickedUp:
			loadActions.append({
					'device':		load,
					'time':			str(timestep),
					'action':		'Load Pickup',
					'loadBefore':	'offline',
					'loadAfter':	'online'
				})
		prevLoadsShed = allShed

		# Generator timeline actions
		genActions = []
		if not powerflow:
			raise Exception('PowerModelsONM returned output without powerflow information')
		powerflowNew = powerflow[timestep-startTime]
		for generator in list(powerflowNew.get('generator',{}).keys()):
			entryNew = powerflowNew['generator'][generator]['real power setpoint (kW)'][0]
			if generator in list(powerflowOld.get('generator',{}).keys()):
				entryOld = powerflowOld['generator'][generator]['real power setpoint (kW)'][0]
			else:
				entryOld = 0.0
			if math.sqrt(((entryNew - entryOld)/(entryOld + 0.0000001))**2) > 0.5:
				genActions.append({
				'device':		generator,
				'time':			str(timestep),
				'action':		'Generator Control',
				'loadBefore':	f'{entryOld}',
				'loadAfter':	f'{entryNew}'
				})

		# Battery timeline actions
		batActions = []		
		for battery in list(powerflowNew.get('storage',{}).keys()):
			entryNew = powerflowNew['storage'][battery]['real power setpoint (kW)'][0]
			if battery in list(powerflowOld.get('storage',{}).keys()):
				entryOld = powerflowOld['storage'][battery]['real power setpoint (kW)'][0]
			else:
				entryOld = 0.0
			if math.sqrt(((entryNew - entryOld)/(entryOld + 0.0000001))**2) > 0.5:
				batActions.append({
				'device':		battery,
				'time':			str(timestep),
				'action':		'Battery Control',
				'loadBefore':	f'{entryOld}',
				'loadAfter':	f'{entryNew}'
				})
		powerflowOld = powerflowNew

		# The order of addition is the order that actions will appear in each timestep on a table
		timelineActions += switchActions + genActions + batActions + loadActions
		timestep += 1
	outputTimeline = pd.DataFrame(timelineActions, columns=['time','device','action','loadBefore','loadAfter']).sort_values('time')

	# Create traces
	# generation profiles code moved to bottom of this file to use data gathered later

	volts = go.Figure()
	voltsKeysAndNames = [
		('Min voltage (p.u.)','Minimum Voltage'),
		('Max voltage (p.u.)','Maximum Voltage'),
		('Mean voltage (p.u.)','Mean Voltage')]
	for deviceActions, name in voltsKeysAndNames:
		volts.add_trace(go.Scatter(
			x=simTimeSteps,
			y=voltages[deviceActions],
			mode='lines',
			line_shape='hv',
			name=name,
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>{name}</b>: %{{y:.4f}}'))
	# Edit the layout
	volts.update_layout(
		xaxis_title='Time (Hours)',
		xaxis_range=[simTimeSteps[0],simTimeSteps[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':stepSize
		},
		yaxis_title='Power (p.u.)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
	
	loads = go.Figure()
	loadsKeysAndNames = [
		('Total load (%)', '% Total Demand Served'),
		('Feeder load (%)','% Non-Microgrid Demand Served By Grid'),
		('Microgrid load (%)','% Microgrid Demand Served'),
		('Bonus load via microgrid (%)','% Non-Microgrid Demand Served By Microgrids')]
	for deviceActions,name in loadsKeysAndNames:
		loads.add_trace(go.Scatter(
			x=simTimeSteps,
			y=loadServed[deviceActions],
			mode='lines',
			line_shape='hv',
			name=name,
			hovertemplate=
			'<b>Time Step</b>: %{x}<br>' +
			f'<b>{name}</b>: %{{y:.2f}}% kW'))
	# Edit the layout
	loads.update_layout(
		xaxis_title='Time (Hours)',
		xaxis_range=[simTimeSteps[0],simTimeSteps[-1]],
		xaxis={
			'tickmode':'linear',
			'dtick':stepSize
		},
		yaxis_title='Demand Served (%)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
	
	timelineStatsHtml = microgridTimeline(outputTimeline, modelDir)
	with open(pathToOmd) as inFile:
		tree = json.load(inFile)['tree']
	feederMap = geo.omdGeoJson(pathToOmd, conversion = False)
	
	def coordStrFormatter(coordString):
		coordList = coordString.split()
		newCoordString = ""
		count = 0
		for x in coordList:
			if count%2 == 0:
				newCoordString = newCoordString + "(" + x + ", "
			else:
				newCoordString = newCoordString + x + ")"
				if count < len(coordList) - 1:
					newCoordString = newCoordString + ", \n"
			count = count+1
		return newCoordString
	
	kWPropDict = {}
	for i in range(len(feederMap['features'])):
		props = feederMap['features'][i]['properties']
		name = props.get('name',0)
		if name:
			rawCoords = feederMap['features'][i]['geometry']['coordinates']
			mgID = None
			kW = None
			if isinstance(rawCoords[0], float):
				coordStr = f'({rawCoords[1]},{rawCoords[0]})'
				mgID = obMgDict.get(name, busMgDict.get(name,'no MG ID'))
				kW = props.get('kw')
			else:
				coordStr = f'({rawCoords[0][1]},{rawCoords[0][0]}), ({rawCoords[1][1]},{rawCoords[1][0]})'
			props['popupContent'] =	f'''Location: <b>{coordStr}</b><br>
										Device: <b>{name}</b><br>
										''' 
			if mgID: 
				props['popupContent'] += f'Microgrid ID: <b>{mgID}</b>'
			if kW:
				props['popupContent'] += f'<br>kW: <b>{smartRound(kW,3)}</b>'
				kWPropDict[name] = kW

	row = 0
	row_count_timeline = outputTimeline.shape[0]
	colormap = {
		'Load Shed':'0000FF',
		'Load Pickup':'00C957',
		'Switch Opening':'FF8000',
		'Switch Closing':'9370DB',
		'Battery Control':'FFFF00',
		'Generator Control':'E0FFFF',
	}
	hr4Popup = '_____________________________________________'
	for row in range(row_count_timeline):
		full_data = pullDataForGraph(tree, feederMap, outputTimeline, row)
		device, coordLis, coordStr, time, action, loadBefore, loadAfter = full_data
		units = ' kW' if str(action) in ['Generator Control','Battery Control'] else ''
		dev_dict = {}
		try:
			dev_dict['type'] = 'Feature'
			dev_dict['properties'] = {
				'device': device, 
				'time': time,
				'action': action,
				'loadBefore': loadBefore,
				'loadAfter': loadAfter,
				'popupContent': f'''Location: <b>{coordStrFormatter(str(coordStr))}</b><br>
									Device: <b>{str(device)}</b><br>
									{hr4Popup}<br>Latest Action: <b>{str(action)}</b><br>
									Timestep: <b>{str(time)}</b><br>
									Before: <b>{str(smartRound(loadBefore,3))}{units}</b><br>
									After: <b>{str(smartRound(loadAfter,3))}{units}</b>''' }
			if len(coordLis) != 2:
				dev_dict['geometry'] = {'type': 'LineString', 'coordinates': [[coordLis[0], coordLis[1]], [coordLis[2], coordLis[3]]]}
				dev_dict['properties']['edgeColor'] = f'#{colormap[action]}'
			else:
				dev_dict['geometry'] = {'type': 'Point', 'coordinates': [coordLis[0], coordLis[1]]}
				dev_dict['properties']['pointColor'] = f'#{colormap[action]}'
				if obMgDict != None:
					mgID = obMgDict.get(str(device),'no MG ID')
					dev_dict['properties']['microgrid_id'] = mgID
					dev_dict['properties']['popupContent'] = dev_dict['properties']['popupContent'].replace(f'{hr4Popup}<br>Latest Action', f'Microgrid ID: <b>{mgID}</b><br>{hr4Popup}<br>Latest Action')
				obkW = kWPropDict.get(device)
				if obkW != None:
					dev_dict['properties']['kW'] = obkW
					dev_dict['properties']['popupContent'] = dev_dict['properties']['popupContent'].replace(f'{hr4Popup}<br>Latest Action', f'kW: <b>{smartRound(obkW,3)}</b><br>{hr4Popup}<br>Latest Action')
			feederMap['features'].append(dev_dict)
		except:
			print('MESSED UP MAPPING on', device, full_data)
	shutil.copy(omf.omfDir + '/templates/geoJsonMap.html', modelDir)
	with open(pJoin(modelDir,'geoJsonFeatures.js'),'w') as outFile:
		outFile.write('var geojson =')
		json.dump(feederMap, outFile, indent=4)
	# Save geojson dict to then read into outdata in work function below
	with open(pJoin(modelDir,'geoDict.js'),'w') as outFile:
		json.dump(feederMap, outFile, indent=4)

	# Generate customer outage outputs
	try:
		# TODO: this should not be customerOutageData... this is the input of customer info. It's later turned into customerOutageData by adding more info, but this same variable should NOT be used for the same thing
		# Below variable starts as dataframe of Customer Information File data
		customerOutageData = pd.read_csv(pathToCsv)
	except:
		# TODO: Needs to be updated to provide info for all loads, not just shed loads. Outage Incidence plot is dependent on all loads
		deviceTimeline = data["Device action timeline"]
		loadsShed = []
		for line in deviceTimeline:
			loadsShed.append(line["Shedded loads"])
		customerOutageData = pd.DataFrame(columns=['Customer Name','Season','Business Type','Load Name'])
		for elementDict in tree.values():
			if elementDict['object'] == 'load' and float(elementDict['kw'])>.1 and elementDict['name'] in loadsShed[0]:
				loadName = elementDict['name']
				avgLoad = float(elementDict['kw'])/2.5
				busType = 'residential'*(avgLoad<=10) + 'retail'*(avgLoad>10)*(avgLoad<=20) + 'agriculture'*(avgLoad>20)*(avgLoad<=39) + 'public'*(avgLoad>39)*(avgLoad<=50) + 'services'*(avgLoad>50)*(avgLoad<=100) + 'manufacturing'*(avgLoad>100)
				customerOutageData.loc[len(customerOutageData.index)] =[loadName,'summer',busType,loadName]
	row = 0
	average_lost_kwh = []
	outageCost = []
	fig = go.Figure()
	businessTypes = set(customerOutageData['Business Type'])
	outageCostsByType = {busType: [] for busType in businessTypes}
	avgkWColumn = []
	durationColumn = []
	dssTree = dssToTree(pJoin(modelDir,'circuit_simplified.dss'))
	loadShapeMeanMultiplier = {}
	loadShapeMeanActual = {}
	loadShapesActual = {}
	loadShapesMult = {}
	loadShapesPerLoad = {}
	for dssLine in dssTree:
		if 'object' in dssLine and dssLine['object'].split('.')[0] == 'loadshape':
			loadShape = dssLine['mult'].replace('[','').replace('(','').replace(']','').replace(')','').split(',')
			loadShape = [float(y) for y in loadShape]
			if str(dssLine.get('useactual')).lower() in ['yes', 'true', 'y']: 
				loadShapeMeanActual[dssLine['object'].split('.')[1]] = np.mean(loadShape)
				loadShapesActual[dssLine['object'].split('.')[1]] = loadShape
			else: 
				# TODO: Inquire to Lisa about whether there should be the division at all. If mult is already supposed to be a multiplier, why divide by max? If this is correct, divide the line below it.
				loadShapeMeanMultiplier[dssLine['object'].split('.')[1]] = np.mean(loadShape)/np.max(loadShape)
				loadShapesMult[dssLine['object'].split('.')[1]] = loadShape
	while row < customerOutageData.shape[0]:
		customerName = str(customerOutageData.loc[row, 'Customer Name'])
		loadName = str(customerOutageData.loc[row, 'Load Name'])
		businessType = str(customerOutageData.loc[row, 'Business Type'])
		duration = str(0)
		# durationFloatCapAt25 capped at 25 hours for cost calculation purposes because it is used as an index to a 26-element cost list in customerCost1 function
		durationFloatCapAt25 = 0.0
		averagekWperhr = str(0)
		for elementDict in dssTree:
			if 'object' in elementDict and elementDict['object'].split('.')[0] == 'load' and elementDict['object'].split('.')[1] == loadName:
				if 'daily' in elementDict: 
					averagekWperhr = float(loadShapeMeanMultiplier.get(elementDict['daily'],0)) * float(elementDict['kw']) + float(loadShapeMeanActual.get(elementDict['daily'],0))
				else: 
					averagekWperhr = float(elementDict['kw'])/2
				# TODO: Once Lisa confirms whether the above should have a no 'daily' case, update accordingly.
				if loadShapesActual.get(elementDict['daily']) != None:
					loadShapesPerLoad[loadName] = loadShapesActual[elementDict['daily']] 
				else:
					loadShapesPerLoad[loadName] = [x * float(elementDict['kw']) for x in loadShapesMult[elementDict['daily']]]
				duration = str(cumulativeLoadsShed.count(loadName) * stepSize)
				durationFloatCapAt25 = min(float(duration), 25.0)
				# TODO: Verify with Lisa that the break is good i.e. each object should only be defined once and this won't be skipping an expected second definition.
				break
		if float(duration) >= .1 and float(averagekWperhr) >= .1:
			durationColumn.append(duration)
			avgkWColumn.append(float(averagekWperhr))
			season = str(customerOutageData.loc[row, 'Season'])
			customerOutageCost, kWperhrEstimate = customerCost1(durationFloatCapAt25, season, averagekWperhr, businessType)
			average_lost_kwh.append(float(averagekWperhr))
			outageCost.append(customerOutageCost)
			outageCostsByType[businessType].append(customerOutageCost)
			trace = go.Scatter(
				x = [*range(0,1+int(durationFloatCapAt25))],
				y = [float(a) for a in kWperhrEstimate[:1+int(durationFloatCapAt25)]],
				name = customerName,
				mode='lines+markers',
				hoverlabel = dict(namelength = -1),
				hovertemplate = 
				'<b>Duration</b>: %{x} h<br>' +
				'<b>Cost</b>: $%{y:.2f}')
			fig.add_trace(trace)
			row += 1
		else:
			customerOutageData = customerOutageData.drop(index=row)
			customerOutageData = customerOutageData.reset_index(drop=True)
	customerOutageData.insert(1, "Duration", durationColumn, True)
	customerOutageData.insert(3, "Time Average kW", avgkWColumn, True)
	durations = customerOutageData.get('Duration',['0'])
	try:
		maxDuration = max([float(x) for x in durations])
	except:
		maxDuration = 12.0 #HACKCOBB: Duration comes back as 'Duration'
	customersOutByTime = [{busType: 0 for busType in businessTypes} for x in range(math.ceil(maxDuration)+1)]
	customerCostByTime = [{busType: 0.0 for busType in businessTypes} for x in range(math.ceil(maxDuration)+1)]
	customerCountByType = {busType: 0 for busType in businessTypes}
	# def deciles(dList): return [0.0] + quantiles([float(x) for x in dList], n=10) + [max([float(x) for x in dList])]
	# outageDeciles = deciles(customerOutageData['Duration'].tolist())
	# costDeciles = deciles(outageCost)
	if not outageCost: outageCost = [.001]
	minCustomerCost = min(outageCost)
	maxCustomerCost = max(outageCost)
	numBins = 45
	binSize = (maxCustomerCost-minCustomerCost)/numBins
	totalCustomerCost = sum(outageCost)
	meanCustomerCost = totalCustomerCost / len(outageCost)

	durationWarning = None if maxDuration <= 25.0 else 'Some durations exceed 25 hours but cost calculations are capped there because of available data.'
	fig.update_layout(
		title = durationWarning,
		xaxis_title = 'Total Outage Duration (hours)',
		yaxis_title = 'Cost ($)',
		)
	
	# Customer Outage Histogram
	busColors = {'residential':'#0000ff', 'manufacturing':'#ff0000', 'mining':'#708090', 'construction':'#ff8c00', 'agriculture':'#008000', 'finance':'#d6b600', 'retail':'#ff69b4', 'services':'#191970', 'utilities':'#8b4513', 'public':'#9932cc'}
	custHist = go.Figure()
	# custHist.add_trace(go.Histogram(
	#	x=outageCost,
	#	xbins=dict(
	#		start=minCustomerCost,
	#		end=maxCustomerCost+binSize,
	#		size=binSize
	#	)
	# ))
	for busType in businessTypes:
		custHist.add_trace(go.Histogram(
			x=outageCostsByType[busType],
			name=busType, # name used in legend and hover labels
			xbins=dict(
				start=minCustomerCost,
				end=maxCustomerCost+binSize,
				size=binSize
			),
			bingroup=1,
			marker_color=busColors[busType]
		))
	custHist.update_layout(
		xaxis_title_text='Outage Cost ($)', # xaxis label
		yaxis_title_text='Customer Count', # yaxis label
		barmode='stack',
		bargap=0.1 # gap between bars of adjacent location coordinates
	)
	meanCustomerCostStr = "Mean Outage Cost: $"+"{:.2f}".format(meanCustomerCost)
	# custHist.add_vline(
	#	x=meanCustomerCost,
	#	line_width=3, 
	#	line_dash="dash",
	#	line_color="black",
	#	annotation_text=meanCustomerCostStr, 
	#	annotation_position="top right"
	# )
	custHist.add_shape(
		type="line",
		xref="x", 
		yref="paper", 
		x0=meanCustomerCost, 
		y0=0, 
		x1=meanCustomerCost,
		y1=1.0, 
		line=dict(
			color="black",
			width=3,
			dash="dash"
		)
	)
	custHist.add_annotation(
		xref="x",
		yref="paper",
		x=meanCustomerCost,
		y=1.0,
		xanchor="left",
		text=meanCustomerCostStr,
		showarrow=False
	)

	outageIncidenceFig, mgOIFigs = outageIncidenceGraph(customerOutageData, outputTimeline, startTime, numTimeSteps, loadPriorityFile, loadMgDict)
	taofiHist, taodiHist, TAOFI, TAODI = makeTaofiAndTaodiHist(outputTimeline, startTime, numTimeSteps, list(loadMgDict.keys()))
	lciTaofiScatter, lciTaodiScatter = makeLciTaofiTaodiScatter(loadLciDict, TAOFI, TAODI)
	tradMetricsHtml, lciQuartTradMetricsHtml = tradMetricsByMgTable(outputTimeline, loadMgDict, startTime, numTimeSteps, modelDir, loadLciDict, loadLcsDict, loadBcsDict, loadPriorityFile, useLci)

	customerOutageHtml = customerOutageTable(customerOutageData, outageCost, modelDir)
	simulationDuration = int(simulationDuration)
	timeList, kWLost, kWLostCumulative, kWLostPerMg, kWTotal = collectkWLostData(mgIDs, obMgDict, loadShapesPerLoad, outputTimeline, startTime, numTimeSteps)
	utilOutFig = utilityOutageGraph(timeList, kWLost, kWLostCumulative, stepSize)
	gens, mgGensFigs = genProfilesByMicrogrid(mgIDs, obMgDict, powerflow, simTimeSteps, startTime, kWLost, kWLostPerMg, kWTotal)


	try: customerOutageCost = customerOutageCost
	except: customerOutageCost = 0
	return {'utilOutFig': 	utilOutFig, 
			'customerOutageHtml': 	customerOutageHtml, 
			'timelineStatsHtml': 	timelineStatsHtml,
			'tradMetricsHtml':		tradMetricsHtml,
			'lciQuartTradMetricsHtml': lciQuartTradMetricsHtml,
			'outageIncidenceFig': 	outageIncidenceFig, 
			'mgOIFigs':				mgOIFigs, 
			'mgGensFigs':			mgGensFigs, 
			'gens': 				gens, 
			'loads': 				loads, 
			'volts': 				volts, 
			'fig': 					fig, 
			'lciTaodiScatter':		lciTaodiScatter,
			'lciTaofiScatter':		lciTaofiScatter,
			'customerOutageCost': 	customerOutageCost, 
			'endTime': 				simTimeSteps[-1], 
			'stepSize': 			stepSize, 
			'startTime': 			startTime,
			'custHist': 			custHist,
			'taofiHist':			taofiHist,
			'taodiHist':			taodiHist}

def __buildCustomEvents(eventsCSV='', feeder='', customEvents='customEvents.json', defaultDispatchable = 'true'):
	''' Builds an events json file for use by restoration.py based on an events CSV input.'''
	# TODO: refactor code to accept a csv from the user and convert it into the appropriate json using this function
	def outageSwitchState(outList): return ('open'*(outList[3] == 'closed') + 'closed'*(outList[3]=='open'))
	def eventJson(dispatchable, state, timestep, affected_asset):
		return {
			"event_data": {
				"status": 1,
				"dispatchable": dispatchable,
				"type": "breaker",
				"state": state
			},
			"timestep": timestep,
			"affected_asset": ("line." + affected_asset),
			"event_type": "switch"
		}
	if eventsCSV == '': # Find largest switch, flip it and set to non-dispatchable at timestep 1.
		with open(feeder, 'a') as f:
			f.write('Export Currents')
		with open(feeder, 'r') as f:
			f.read()
	elif ',' in eventsCSV:
		outageReader = csv.reader(io.StringIO(eventsCSV))
	else:
		outageReader = csv.reader(open(eventsCSV))
	if feeder.endswith('.omd'):
		with open(feeder) as omdFile:
			tree = json.load(omdFile)['tree']
		niceDss = evilGldTreeToDssTree(tree)
		treeToDss(niceDss, 'circuitOmfCompatible.dss')
		dssTree = dssToTree('circuitOmfCompatible.dss')
	else: return('Error: Feeder must be an OMD file.')
	outageAssets = [] # formerly row[0] for row in outageReader
	customEventList = []
	for row in outageReader:
		outageAssets.append(row[0])
		try:
			customEventList.append(eventJson('false',outageSwitchState(row),int(row[1]),row[0]))
			if int(row[2])>0:
				customEventList.append(eventJson(row[4],row[3],int(row[2]),row[0]))
		except: pass
	unaffectedOpenAssets = [dssLine['object'].split('.')[1] for dssLine in dssTree if dssLine['!CMD'] == 'open']
	unaffectedClosedAssets = [dssLine['object'].split('.')[1] for dssLine in dssTree if dssLine.get('!CMD') == 'new' \
		and dssLine['object'].split('.')[0] == 'line' \
		and 'switch' in [key for key in dssLine] \
	#   and dssLine['switch'] == 'y'] # \
		and (dssLine['object'].split('.')[1] not in (unaffectedOpenAssets + outageAssets))]
	customEventList += [eventJson(defaultDispatchable,'open',1,asset) for asset in unaffectedOpenAssets] 
	customEventList += [eventJson(defaultDispatchable,'closed',1,asset) for asset in unaffectedClosedAssets]
	customEventList += [eventJson('false',outageSwitchState(row),int(row[1]),row[0]) for row in outageReader]
	customEventList += [eventJson(row.get('dispatchable'),row.get('defaultState',int(row.get('timestep'))),row.get('asset')) for row in outageReader if int(row[2])>0]
	with open(customEvents,'w') as eventsFile:
		json.dump(customEventList, eventsFile)

def copyInputFilesToModelDir(modelDir, inputDict):
	''' Creates local copies of input files in the model directory modelDir.
		Returns a dictionary of paths to the local copies with the following keys:

		'mgTagging', 'loadPriority', 'customerInfo', 'event', 'rescomOutput'
	'''
	# TODO: See if there's any reason it's done this way as opposed to just copying files to the modelDir with shutil.copy(src,dest)
	pathToLocalFile = {}
	if inputDict['microgridTaggingFileName'] != '':
		try:
			with open(pJoin(modelDir, inputDict['microgridTaggingFileName']), 'w') as mgtFile:
				pathToLocalFile['mgTagging'] = mgtFile.name
				mgtFile.write(inputDict['microgridTaggingData'])
		except:
			pathToLocalFile['mgTagging'] = None
			raise Exception("ERROR - Unable to write microgrid tagging file: " + str(inputDict['microgridTaggingFileName']))
	else:
		pathToLocalFile['mgTagging'] = None

	if inputDict['loadPriorityFileName'] != '':
		try:
			with open(pJoin(modelDir, inputDict['loadPriorityFileName']), 'w') as lpFile:
				pathToLocalFile['loadPriority'] = lpFile.name
				lpFile.write(inputDict['loadPriorityData'])
		except:
			pathToLocalFile['loadPriority'] = None
			raise Exception("ERROR - Unable to write load priority file: " + str(inputDict['loadPriorityFileName']))
	else:
		pathToLocalFile['loadPriority'] = None

	if inputDict['customerFileName']:
		with open(pJoin(modelDir, inputDict['customerFileName']), 'w') as ciFile:
			pathToLocalFile['customerInfo'] = ciFile.name
			ciFile.write(inputDict['customerData'])
	else: 
		with open(pJoin(modelDir, 'customerInfo.csv'), 'w') as ciFile:
			pathToLocalFile['customerInfo'] = ciFile.name
			ciFile.write(inputDict['customerData'])

	with open(pJoin(modelDir, inputDict['eventFileName']), 'w') as eFile:
		pathToLocalFile['event'] = eFile.name
		eFile.write(inputDict['eventData'])

	if inputDict['rescomOutputFileName'] != '':
		with open(pJoin(modelDir, inputDict['rescomOutputFileName']), 'w') as eFile:
			pathToLocalFile['rescomOutput'] = eFile.name
			eFile.write(inputDict['rescomOutputData'])
	else:
		pathToLocalFile['rescomOutput'] = None

	return pathToLocalFile

def simplifyFeeder(inDss, outDss, maxBessCharge=True):
	''' Simplifies a feeder to put less strain on simulations in which it is used. 
	
		Removes fuses and optionally sets kwhstored to the value of kwhrated.
		Passes the feeder through feeder reduction code containing mergeContigLines(), rollUpTriplex(), and rollUpLoadTransformer().
		Cleans the formatting of the reduced feeder with dss_to_clean_via_save() and then strips out tcc_curves, spectrum, growthshape, and default objects + calcv related things that were addded by the cleaning function.

		Args:
			inDss: The file path of the dss to be simplified
			outDss: The desired file path of the resulting simplified dss
			maxBessCharge: If True, each BESS will be defined as fully charged by setting the value of kwhstored to the value of kwhrated.
	'''
	with tempfile.TemporaryDirectory() as tempDir:
		# remove fuses & set kwhstored equal to kwhrated + remove show commands 
		with open(inDss, 'r') as infile:
			inputLines = infile.readlines()
			outStr = ''
			for line in inputLines:
				line = line.lower()
				if 'object=fuse.' not in line and 'show ' not in line:
					if 'kwhstored' in line and 'kwhrated' in line and maxBessCharge == True:
						itemDict = {}
						for item in line.split(' '):
							try:
								k,v = item.split('=')
								itemDict[k] = v
							except:
								continue
						toReplace = 'kwhstored='+itemDict['kwhstored']
						replaceWith = 'kwhstored='+itemDict['kwhrated']
						outStr += line.replace(toReplace,replaceWith)
					else:
						outStr += line
		with open(pJoin(tempDir,'rm_fuses_max_storage.dss'),'w') as outfile:
			outfile.write(outStr)		
		print('\nRemoved fuses and set kwhstored to kwhrated\n')
		# reduce feeder size
		'''
		tree = dssToTree(pJoin(tempDir,'rm_fuses_max_storage.dss'))
		oldsz = len(tree)
		tree = reduceCircuit(tree)
		newsz = len(tree)
		cutsz = oldsz-newsz
		treeToDss(tree, pJoin(tempDir,'rm_fuses_max_storage_resized.dss'))
		print(f'\nPerformed feeder reduction, reducing the size of the feeder by {cutsz} objects (oldsz={oldsz}, newsz={newsz})\n')
		'''
		# clean file
		srcDss = pJoin(tempDir,'rm_fuses_max_storage.dss')
		cleanDss = pJoin(tempDir,'rm_fuses_max_storage_clean.dss')
		dss_to_clean_via_save(srcDss, cleanDss)
		print('\nCleaned file formatting\n')
		# strip out tcc_curves, spectrum, growthshape, and default objects + calcv related things that were addded by cleaning function
		with open(cleanDss, 'r') as infile:
			inputLines = infile.readlines()
			outStr = ''
			removalFlags = ['tcc_curve',
							'object=tcc_curve', 
							'spectrum.dss',
							'object=spectrum',
							'growthshape.dss',
							'object=growthshape',
							'default',
							'voltagebases',
							'calcv',
							'solve',
							'show']
			for line in inputLines:
				keepLine = True
				for flag in removalFlags:
					if flag in line.lower():
						keepLine = False
						break
				if keepLine:
					outStr += line
		print('\nRemoved extra elements added by file cleaner function (defaults, tcc curves, spectrum, growthshapes, voltagebases, calcv, solve, show)\n')
	with open(outDss,'w') as outfile:
		outfile.write(outStr)

"""
def sanityCheck(dssLocation):
	''' Function to provide a comparison of active power, apparent power, and total solved power at each load for each timestep.
		Used to check against cumulative kWh measured based on mult and base kW of circuit objects. 
	'''
	textCommands = 	f'''Compile "{dssLocation}"
						new object=monitor.feederHead element=transformer.sub_xfmr terminal=1 mode=1 ppolar=no
						set maxiterations=1000
						set maxcontroliter=1000
						set mode=daily
						set stepsize=1h
						set number=24'''.replace('\t','').split('\n')
	for tc in textCommands:
		dss.Text.Command(tc)
	dss.Solution.Solve()
	dss.Monitors.Name('feederHead')
	p1 = np.array(dss.Monitors.Channel(1))
	p2 = np.array(dss.Monitors.Channel(3))
	p3 = np.array(dss.Monitors.Channel(5))
	s = lambda p,q: (p**2 + q**2)**0.5
	ch = lambda a: dss.Monitors.Channel(a)
	# p = active power, s = reactive power
	pTotal = p1+p2+p3
	sTotal = s(ch(1),ch(2))+s(ch(3),ch(4))+s(ch(5),ch(6))
	# Recompile freshly and Sum power for all loads individually as a sanity check on the sanity check
	loadProfile=[]
	textCommands = 	f'''Compile "{dssLocation}"
						set mode=daily
						set stepsize=1h
						set number=1'''.replace('\t','').split('\n')
	for tc in textCommands:
		dss.Text.Command(tc)
	for i in range(24):
		dss.Solution.Solve()
		totalLoadkW = 0
		for load in dss.Loads.AllNames():
			dss.Loads.Name(load)
			totalLoadkW += sum(dss.CktElement.Powers()[::2])
		loadProfile.append(totalLoadkW)
	return [p.item() for p in pTotal], [s.item() for s in sTotal], loadProfile
"""

def work(modelDir, inputDict):
	# Copy specific climate data into model directory
	"""
	Run the restoration model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	# Write in the feeder
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName
	with open(f'{modelDir}/{feederName}.omd', 'r') as omdFile:
		omd = json.load(omdFile)
	tree = omd['tree']

	# Output a .dss file, which will be needed for ONM.
	niceDss = evilGldTreeToDssTree(tree)
	treeToDss(niceDss, pJoin(modelDir,'circuit.dss'))
	simplifyFeeder(pJoin(modelDir,'circuit.dss'),pJoin(modelDir,'circuit_simplified.dss'), maxBessCharge=False)

	omdFilePath = f'{modelDir}/{feederName}.omd'
	
	pathToLocalFile = copyInputFilesToModelDir(modelDir, inputDict)
	
	loadList, loadLciDict, loadLcsDict, loadBcsDict = getResComInfo(
		modelDir 				= modelDir, 
		pathToOmd				= omdFilePath,
		useLci					= inputDict['useLci'],
		rescomOutputFilePath	= pathToLocalFile['rescomOutput']
	)
	pathToMergedPriorities = combineLoadPriorityWithLCI(
		modelDir				= modelDir,
		loadList				= loadList,
		loadPriorityFilePath	= pathToLocalFile['loadPriority'],
		loadLciDict				= loadLciDict,
		lciImpact				= inputDict['lciImpact']
	)
	runMicrogridControlSim(
		modelDir				= modelDir, 
		solFidelity				= inputDict['solFidelity'],
		eventsFilename			= inputDict['eventFileName'],
		loadPriorityFile		= pathToMergedPriorities,
		microgridTaggingFile	= pathToLocalFile['mgTagging']
	)
	microgridInfo = getMicrogridInfo(
		modelDir				= modelDir, 
		pathToOmd				= omdFilePath, 
		settingsFile			= f'{modelDir}/settings.json'
	)
	plotOuts = graphMicrogrid(
		modelDir				= modelDir, 
		pathToOmd				= omdFilePath, 
		pathToJson				= pathToLocalFile['event'],
		pathToCsv				= pathToLocalFile['customerInfo'],
		loadPriorityFile		= pathToMergedPriorities,
		loadMgDict				= microgridInfo['loadMgDict'],
		obMgDict 				= microgridInfo['obMgDict'],
		busMgDict				= microgridInfo['busMgDict'],
		mgIDs					= microgridInfo['mgIDs'],
		loadLciDict				= loadLciDict,
		loadLcsDict				= loadLcsDict,
		loadBcsDict				= loadBcsDict,
		useLci					= inputDict['useLci']
	)

	# Sanity check traces for debugging. Do not leave these uncommented when pushing
	"""
	p,s,l = sanityCheck(pJoin(modelDir,'circuit_simplified.dss'))
	plotOuts['gens'].add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group2',
		x=[*range(1,25)],
		y=p,
		mode='lines',
		line_shape='hv',
		name='Total p (sum of P\'s monitoring line after ssxfrmr)',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Total p</b>: %{{y:.3f}}kW'))
	plotOuts['gens'].add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group6',
		x=[*range(1,25)],
		y=s,
		mode='lines',
		line_shape='hv',
		name='Total s (sum of s\'s monitoring line after ssxfrmr)',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>Total s</b>: %{{y:.3f}}kW'))
	plotOuts['gens'].add_trace(go.Scatter(
		fill='tonexty',
		stackgroup='group7',
		x=[*range(1,25)],
		y=l,
		mode='lines',
		line_shape='hv',
		name='loadProfile (sum of solved power of each load at each timestep)',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		f'<b>loadProfile</b>: %{{y:.3f}}kW'))
	"""


	# Textual outputs of outage timeline
	with open(pJoin(modelDir,'timelineStats.html')) as inFile:
		outData['timelineStatsHtml'] = inFile.read()
	# Textual outputs of customer cost statistic
	with open(pJoin(modelDir,'customerOutageTable.html')) as inFile:
		outData['customerOutageHtml'] = inFile.read()
	# Textual outputs of traditional metrics table
	with open(pJoin(modelDir,'mgTradMetricsTable.html')) as inFile:
		outData['tradMetricsHtml'] = inFile.read()
	# Textual outputs of traditional metrics table for lciQuarts
	with open(pJoin(modelDir,'lciQuartTradMetricsTable.html')) as inFile:
		outData['lciQuartTradMetricsHtml'] = inFile.read()
	#The geojson dictionary to load into the outageCost.py template
	with open(pJoin(modelDir,'geoDict.js'),'rb') as inFile:
		outData['geoDict'] = inFile.read().decode()

	outData['outageIncidenceHtml'] = plotOuts.get('outageIncidenceHtml')
	# Image outputs.
	# with open(pJoin(modelDir,'customerCostFig.png'),'rb') as inFile:
	#	outData['customerCostFig.png'] = base64.standard_b64encode(inFile.read()).decode()
	# Plotly outputs.
	layoutOb = go.Layout()
	outData['mgGensFigsData'] = {mg:json.dumps(figData, cls=py.utils.PlotlyJSONEncoder) for mg,figData in plotOuts.get('mgGensFigs',{}).items()}
	outData['mgGensFigsLayout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig1Data'] = json.dumps(plotOuts.get('gens',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig1Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig2Data'] = json.dumps(plotOuts.get('volts',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig2Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig3Data'] = json.dumps(plotOuts.get('loads',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig3Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig4Data'] = json.dumps(plotOuts.get('fig',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig4Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig5Data'] = json.dumps(plotOuts.get('custHist',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig5Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['utilOutFigData'] = json.dumps(plotOuts.get('utilOutFig',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['utilOutFigLayout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['fig6Data'] = json.dumps(plotOuts.get('outageIncidenceFig',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['fig6Layout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['mgOIFigsData'] = {mg:json.dumps(figData, cls=py.utils.PlotlyJSONEncoder) for mg,figData in plotOuts.get('mgOIFigs',{}).items()}
	outData['mgOIFigsLayout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['taofiHistData'] = json.dumps(plotOuts.get('taofiHist',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['taofiHistLayout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['taodiHistData'] = json.dumps(plotOuts.get('taodiHist',{}), cls=py.utils.PlotlyJSONEncoder)
	outData['taodiHistLayout'] = json.dumps(layoutOb, cls=py.utils.PlotlyJSONEncoder)
	outData['lciTaodiScatterData'] = json.dumps(plotOuts.get('lciTaodiScatter',{}).data, cls=py.utils.PlotlyJSONEncoder)
	outData['lciTaodiScatterLayout'] = json.dumps(plotOuts.get('lciTaodiScatter',{}).layout, cls=py.utils.PlotlyJSONEncoder)
	outData['lciTaofiScatterData'] = json.dumps(plotOuts.get('lciTaofiScatter',{}).data, cls=py.utils.PlotlyJSONEncoder)
	outData['lciTaofiScatterLayout'] = json.dumps(plotOuts.get('lciTaofiScatter',{}).layout, cls=py.utils.PlotlyJSONEncoder)

	# Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''
	outData['endTime'] = plotOuts.get('endTime', 24)
	outData['stepSize'] = plotOuts.get('stepSize', 1)
	outData['startTime'] = plotOuts.get('startTime',1)
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	# ====== For All Test Cases
	cust_file_path = ''
	# ====== Optional inputs for custom load priority and microgrid tagging - set the file path to '' and data to None initially and change their value below if desired
	loadPriority_file_path = ['']
	loadPriority_file_data = None
	microgridTagging_file_path = ['']
	microgridTagging_file_data = None
	'''
	# ====== Iowa240 Variant 3MG DER + Coop Resources @ Top of Feeder
	dest_folder_path 			= [__neoMetaModel__._omfDir,'static','testFiles','restoration','Testing Demo Files']
	feeder_file_path 			= dest_folder_path+['iowa240_topOfFeeder+DERs.omd']
	event_file_path 			= dest_folder_path+['iowa240_topOfFeeder+DERs_events.json']
	loadPriority_file_path 		= dest_folder_path+['iowa240_loadPriority_EMPTY.json']
	loadPriority_file_data 		= open(pJoin(*loadPriority_file_path)).read()
	microgridTagging_file_path	= dest_folder_path+['iowa240_topOfFeeder+DERs_mgTagging_3MG.json']
	microgridTagging_file_data	= open(pJoin(*microgridTagging_file_path)).read()
	'''
	
	# ====== Iowa240 Test Case
	# feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22_no_show_voltage.dss.omd']
	feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles','iowa240_in_Florida_copy2_no_show_voltage.dss.omd']
	event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.events.json']
	loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.loadPriority.basic.json']
	loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.microgridTagging.basic.json']
	microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	customerInfo_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','customerInfoExample.csv']
	customerInfo_file_data = open(pJoin(*customerInfo_file_path)).read()
	rescomOutput_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','rescomOutputForIowa240.json']
	rescomOutput_file_data = open(pJoin(*rescomOutput_file_path)).read()
	'''
	feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles','restoration','ieee37busdata', 'ieee37_LBL_simplified.omd']
	event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration', 'empty event.json']
	loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','empty dict.json']
	loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','empty dict.json']
	microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	customerInfo_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','ieee37busdata','customerInfoExample.csv']
	customerInfo_file_data = open(pJoin(*customerInfo_file_path)).read()
	

	# ====== 1010 bus feeder Test Case
	feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles', '1010 bus feeder', '1010 bus feeder 100% charged l pv 24hr ADDED INVCONTROL_simplified.omd']
	event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration', 'empty event.json']
	loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','empty dict.json']
	loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','empty dict.json']
	microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	customerInfo_file_path = [__neoMetaModel__._omfDir,'static','testFiles','1010 bus feeder','customerInfoExample.csv']
	customerInfo_file_data = open(pJoin(*customerInfo_file_path)).read()
	
	
	# ====== 3300 bus feeder with PV & Storage test case
	feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles','3300 bus feeder with pv and storage','MasterNewNames5hr_clean.omd']
	# create bespoke events file
	event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.events.json']
	# create bespoke priority file
	loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','Microgrid Tagging','iowa240_dwp_22.microgridTagging.EMPTY.json']
	loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	# create bespoke mg tagging file
	microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','restoration','Microgrid Tagging','iowa240_dwp_22.microgridTagging.EMPTY.json']
	microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	customerInfo_file_path = [__neoMetaModel__._omfDir,'static','testFiles','3300 bus feeder with pv and storage','ExampleCustomerInfoFile.csv']
	customerInfo_file_data = open(pJoin(*customerInfo_file_path)).read()
	'''
	# ====== Nreca1824 Test Case
	# feeder_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.omd']
	# event_csv_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824events.csv']
	# event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.events.json']
	# loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.loadPriority.basic.json']
	# loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	# microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.microgridTagging.basic.json']
	# microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	
	# ====== Comment this out if no load priority file is specified
	# loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	# ====== Comment this out if no load microgrid tagging file is specified
	# microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	defaultInputs = {
		'modelType': modelName,
		'feederName1': feeder_file_path[-1][0:-4],
		'outageDuration': '5',
		'customerFileName': customerInfo_file_path[-1],
		'customerData': customerInfo_file_data,
		'eventFileName': event_file_path[-1],
		'eventData': open(pJoin(*event_file_path)).read(),
		'solFidelity': '0.05',
		'loadPriorityFileName': loadPriority_file_path[-1],
		'loadPriorityData': loadPriority_file_data,
		'microgridTaggingFileName': microgridTagging_file_path[-1],
		'microgridTaggingData': microgridTagging_file_data,
		'rescomOutputFileName': rescomOutput_file_path[-1],
		'rescomOutputData': rescomOutput_file_data,
		'useLci': 'Yes',
		'lciImpact': '1.0'
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(*feeder_file_path), pJoin(modelDir, defaultInputs['feederName1']+'.omd'))
	except Exception as e:
		print(e)
		return False
	return __neoMetaModel__.new(modelDir, defaultInputs)

def _debugging():
	# outageCostAnalysis(omf.omfDir + '/static/publicFeeders/Olin Barre LatLon.omd', omf.omfDir + '/static/testFiles/smartswitch_Outages.csv', None, '60', '1')
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
	# buildCustomSettings(pJoin(omf.omfDir,'static','testFiles','nreca1824events.csv'),pJoin(omf.omfDir,'static','testFiles','nreca1824_dwp.omd'),pJoin(modelLoc,'customSettings.json'))
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
	#_debugging()
	potato='baked'