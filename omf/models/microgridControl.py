"""
The Microgrid Control model uses the PowerONM solver from Los Alamos National Labs to
find the optimal series of control actions by which a microgrid can support loads in the
case of an outage, in concert with an outage cost model for estimating the member and
utility costs of user-specified outage scenarios.
"""
import re, json, os, tempfile, shutil, csv, math, io
from os.path import join as pJoin
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly as py
import plotly.graph_objs as go
from plotly.tools import make_subplots
# from statistics import quantiles

# OMF imports
import omf
from omf import geo
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers.opendss import dssConvert
from omf.solvers import PowerModelsONM

# Model metadata:
tooltip = 'Calculate load, generator and switching controls to maximize power restoration for a circuit with multiple networked microgrids.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

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
		if (nodeName == key['properties'].get('name','')):
			current = key['geometry']['coordinates']
			coordLis = coordsFromString(current)
			coordStr = str(coordLis[0]) + ' ' + str(coordLis[1])
	return coordLis, coordStr

def lineToCoords(tree, feederMap, lineName):
	'get the latitude and longitude of a given entry in string format'
	coordStr = ''
	coordLis = []
	lineNode = ''
	lineNode2 = ''
	for key in tree.keys():
		try:
			if tree[key].get('name','') == lineName:
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
				coordStr = str(coordLis[0]) + ' ' + str(coordLis[1]) + ' ' + str(coordLis[2]) + ' ' + str(coordLis[3])
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

def colormap(action):
	'color map for drawing the map nodes'
	if action == 'Load Shed':
		color = '0000FF'
	elif action == 'Load Pickup':
		color = '00C957'
	elif action == 'Switch Opening':
		color = 'FF8000'
	elif action == 'Switch Closing':
		color = '9370DB'
	elif action == 'Battery Control':
		color = 'FFFF00'
	elif action == 'Generator Control':
		color = 'E0FFFF'
	return color

def microgridTimeline(outputTimeline, workDir):
	'generate timeline of microgrid events'
	# check to see if work directory is specified; otherwise, create a temporary directory
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)
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
		row = 0
		while row < len(outputTimeline):
			loadBeforeStr = outputTimeline.loc[row, 'loadBefore']
			loadAfterStr = outputTimeline.loc[row, 'loadAfter']
			loadStringDict = ["open", "closed", "online", "offline"]
			if str(loadBeforeStr) not in loadStringDict:
				loadBeforeStr = '{0:.3f}'.format(float(loadBeforeStr))
			if str(loadAfterStr) not in loadStringDict:
				loadAfterStr = '{0:.3f}'.format(float(loadAfterStr))
			new_html_str += '<tr><td>' + str(outputTimeline.loc[row, 'device']) + '</td><td>' + str(outputTimeline.loc[row, 'time']) + '</td><td>' + str(outputTimeline.loc[row, 'action']) + '</td><td>' + loadBeforeStr + '</td><td>' + loadAfterStr + '</td></tr>'
			row += 1
		new_html_str +="""</tbody></table>"""
		return new_html_str
	# print all intermediate and final costs
	timelineStatsHtml = timelineStats(
		outputTimeline = outputTimeline)
	with open(pJoin(workDir, 'timelineStats.html'), 'w') as timelineFile:
		timelineFile.write(timelineStatsHtml)
	return timelineStatsHtml

def customerOutageTable(customerOutageData, outageCost, workDir):
	'generate html table of customer outages'
	# check to see if work directory is specified; otherwise, create a temporary directory
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)
	# TODO: update table after calculating outage stats
	def customerOutageStats(customerOutageData, outageCost):
		new_html_str = """
			<table cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>Customer Name</th>
						<th>Duration</th>
						<th>Season</th>
						<th>Average kW/hr</th>
						<th>Business Type</th>
						<th>Load Name</th>
						<th>Outage Cost</th>
					</tr>
				</thead>
				<tbody>"""
		row = 0
		while row < len(customerOutageData):
			new_html_str += '<tr><td>' + str(customerOutageData.loc[row, 'Customer Name']) + '</td><td>' + str(customerOutageData.loc[row, 'Duration']) + '</td><td>' + str(customerOutageData.loc[row, 'Season']) + '</td><td>' + '{0:.2f}'.format(customerOutageData.loc[row, 'Average kW/hr']) + '</td><td>' + str(customerOutageData.loc[row, 'Business Type']) + '</td><td>' + str(customerOutageData.loc[row, 'Load Name']) + '</td><td>' + "${:,.2f}".format(outageCost[row])+ '</td></tr>'
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
	with open(pJoin(workDir, 'customerOutageTable.html'), 'w') as customerOutageFile:
		customerOutageFile.write(customerOutageHtml)
	return customerOutageHtml

def utilityOutageTable(average_lost_kwh, profit_on_energy_sales, restoration_cost, hardware_cost, outageDuration, workDir):
	# check to see if work directory is specified; otherwise, create a temporary directory
	"""
	Perform utility outage table processing for the microgrid control model.
	"""
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)
	
	# TODO: update table after calculating outage stats
	def utilityOutageStats(average_lost_kwh, profit_on_energy_sales, restoration_cost, hardware_cost, outageDuration):
		new_html_str = """
			<table cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>Lost kWh Sales</th>
						<th>Restoration Labor Cost</th>
						<th>Restoration Hardware Cost</th>
						<th>Utility Outage Cost</th>
					</tr>
				</thead>
				<tbody>"""
		
		new_html_str += '<tr><td>' + str(int(sum(average_lost_kwh))*profit_on_energy_sales*outageDuration) + '</td><td>' + "${:,.2f}".format(restoration_cost*outageDuration) + '</td><td>' + "${:,.2f}".format(hardware_cost) + '</td><td>' + "${:,.2f}".format(int(sum(average_lost_kwh))*profit_on_energy_sales*outageDuration + restoration_cost*outageDuration + hardware_cost) + '</td></tr>'

		new_html_str +="""</tbody></table>"""

		return new_html_str

	# print business information and estimated customer outage costs
	utilityOutageHtml = utilityOutageStats(
		average_lost_kwh = average_lost_kwh,
		profit_on_energy_sales = profit_on_energy_sales,
		restoration_cost = restoration_cost,
		hardware_cost = hardware_cost,
		outageDuration = outageDuration)
	with open(pJoin(workDir, 'utilityOutageTable.html'), 'w') as utilityOutageFile:
		utilityOutageFile.write(utilityOutageHtml)
	return utilityOutageHtml

def customerCost1(duration, season, averagekWperhr, businessType):
	'function to determine customer outage cost based on season, annual kWh usage, and business type'
	duration = float(duration)
	averagekW = float(averagekWperhr)

	times = np.array([0,1,2,3,4,5,6,7,8])
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

	def kWhApprox(kWDict, averagekWperhr, iterate):
		'helper function for approximating customer outage cost based on annual kWh by iteratively "averaging" the curves'
		step = 0
		# iterate the process a set number of times
		while step < iterate:
			#sort the current kWh values for which we have customer outage costs
			keys = list(kWDict.keys())
			keys.sort()
			# find the current kWh values estimated that are closest to the average kW/hr input...
			# ...then, estimate the outage costs for the kW/hr value directly between these
			key = 0
			newEntry = 0
			while key < len(keys)-1:
				if key == len(keys)-2:
					newEntry = (keys[key] + keys[key+1])/2
					averageCost = (kWDict[keys[key]] + kWDict[keys[key+1]])/2
					kWDict[newEntry] = averageCost
					break
				if float(averagekWperhr) > keys[key+1]:
					key+=1
				else:
					newEntry = (keys[key] + keys[key+1])/2
					averageCost = (kWDict[keys[key]] + kWDict[keys[key+1]])/2
					kWDict[newEntry] = averageCost
					break
			step+=1
			if step == iterate:
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
	kWperhrEstimate = 1.21 * kWperhrEstimate
	# find the estimated customer outage cost for the customer in question, given the duration of the outage
	times = np.array([0,1,2,3,4,5,6,7,8])
	wholeHours = int(math.floor(duration))
	partialHour = duration - wholeHours
	outageCost = (kWperhrEstimate[wholeHours] + (kWperhrEstimate[wholeHours+1] - kWperhrEstimate[wholeHours])*partialHour) * (duration>0)
	localMax = 0
	row = 0
	while row < 9:
		if kWperhrEstimate[row] > localMax:
			localMax = kWperhrEstimate[row]
		row+=1
	return outageCost, kWperhrEstimate, times, localMax

def validateSettingsFile(settingsFile):
	# TODO: check to see if settings file input is correct
	#if settings file is in correct format return 'True'
	"""
	Perform validate settings file processing for the microgrid control model.
	"""
	condition = True
	if condition:
		return 'True'
	#if settings file is incorrect, return 'Corrupted Settings file input, generating default settings'
	else:
		return 'Corrupted Settings file input, generating default settings'

def graphMicrogrid(pathToOmd, pathToJson, pathToCsv, outputFile, settingsFile, useCache, workDir, profit_on_energy_sales, restoration_cost, hardware_cost, eventsFilename, genSettings, solFidelity, loadPriorityFile, microgridTaggingFile):
	''' Run full microgrid control process. '''
	# Setup ONM if it hasn't been done already.
	if not PowerModelsONM.check_instantiated():
		PowerModelsONM.install_onm()
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)
	# get mip_solver_gap info (solFidelity)
	solFidelityVal = 0.05 #default to medium fidelity
	if solFidelity == '0.10':
		solFidelityVal = 0.10
	elif solFidelity == '0.02':
		solFidelityVal = 0.02

	# check custom load priorities file input
	if loadPriorityFile != None:
		loadPriorityFilePath = f'{workDir}/loadPriorities.json'
		shutil.copyfile(loadPriorityFile, loadPriorityFilePath)
	else:
		loadPriorityFilePath = ''
	# check custom microgrid tagging file input
	if microgridTaggingFile != None:
		microgridTaggingFilePath = f'{workDir}/microgridTagging.json'
		shutil.copyfile(microgridTaggingFile, microgridTaggingFilePath)
	else:
		microgridTaggingFilePath = ''

	# Handle Settings file generation or upload
	if genSettings == 'False' and settingsFile != None:
		correctSettings = validateSettingsFile(settingsFile)
		if correctSettings == 'True':
			# Scenario 1: The user chose to upload their own setttings file and it is formatted correctly
			shutil.copyfile(settingsFile, f'{workDir}/settings.json')
		else:
			# Scenario 2: The user chose to upload their own setttings file and it is formatted incorrectly
			print("Warning: " + correctSettings)
			PowerModelsONM.build_settings_file(circuitPath=f'{workDir}/circuit.dss', settingsPath=f'{workDir}/settings.json', loadPrioritiesFile=loadPriorityFilePath, microgridTaggingFile=microgridTaggingFilePath)
	else:
		# Scenario 3: The user wants to generate a settings file
		PowerModelsONM.build_settings_file(circuitPath=f'{workDir}/circuit.dss', settingsPath=f'{workDir}/settings.json', loadPrioritiesFile=loadPriorityFilePath, microgridTaggingFile=microgridTaggingFilePath)
	# Run ONM.
	if  useCache == 'True' and outputFile != None:
		shutil.copyfile(outputFile, f'{workDir}/output.json')
	else:
		PowerModelsONM.run_onm(
			circuitPath=f'{workDir}/circuit.dss',
			settingsPath=f'{workDir}/settings.json',
			outputPath=f'{workDir}/output.json',
			eventsPath=f'{workDir}/{eventsFilename}',
			mip_solver_gap=solFidelityVal
		)
	# Gather output data.
	with open(f'{workDir}/output.json') as inFile:
		data = json.load(inFile)
		genProfiles = data['Generator profiles']
		simTimeSteps = []
		for i in data['Simulation time steps']:
			simTimeSteps.append(float(i))
		numTimeSteps = len(simTimeSteps)
		stepSize = simTimeSteps[1]-simTimeSteps[0]
		voltages = data['Voltages']
		outageDuration = stepSize * numTimeSteps
		loadServed = data['Load served']
		storageSOC = data['Storage SOC (%)']
		switchLoadAction = data['Device action timeline']
		powerflow = data['Powerflow output']
	actionTime = []
	actionDevice = []
	actionAction = []
	actionLoadBefore = []
	actionLoadAfter = []
	loadsShed = []
	cumulativeLoadsShed = []
	timestep = 0
	# timestep = 1 #TODO: switch back to this value if timestep should start at 1, not zero
	for key in switchLoadAction:
		# if timestep == 0: #TODO: switch back to this value if timestep should start at 1, not zero
		if timestep == 0:
			switchActionsOld = key['Switch configurations']
		else:
			switchActionsNew = key['Switch configurations']
			for entry in switchActionsNew:
				if switchActionsNew[entry] != switchActionsOld[entry]:
					actionDevice.append(entry)
					actionTime.append(str(timestep))
					if switchActionsNew[entry] == 'open':
						actionAction.append('Switch Opening')
					else:
						actionAction.append('Switch Closing')
					actionLoadBefore.append(switchActionsOld[entry])
					actionLoadAfter.append(switchActionsNew[entry])
			switchActionsOld = key['Switch configurations']
		loadShed = key['Shedded loads']
		if len(loadShed) != 0:
			for entry in loadShed:
				cumulativeLoadsShed.append(entry)
				if entry not in loadsShed:
					actionDevice.append(entry)
					actionTime.append(str(timestep))
					actionAction.append('Load Shed')
					actionLoadBefore.append('online')
					actionLoadAfter.append('offline')
					loadsShed.append(entry)
				else:
					actionDevice.append(entry)
					actionTime.append(str(timestep))
					actionAction.append('Load Pickup')
					actionLoadBefore.append('offline')
					actionLoadAfter.append('online')
					loadsShed.remove(entry)
		timestep += 1
	timestep = 0
	# while timestep < 24:
	while timestep < numTimeSteps:
		if timestep == 0:
			powerflowOld = powerflow[timestep]
		else:
			powerflowNew = powerflow[timestep]
			for generator in list(powerflowNew['generator'].keys()):
				entryNew = powerflowNew['generator'][generator]['real power setpoint (kW)'][0]
				if generator in list(powerflowOld['generator'].keys()):
					entryOld = powerflowOld['generator'][generator]['real power setpoint (kW)'][0]
				else:
					entryOld = 0.0
				if math.sqrt(((entryNew - entryOld)/(entryOld + 0.0000001))**2) > 0.5:
					actionDevice.append(generator)
					actionTime.append(str(timestep))
					# actionTime.append(str(timestep + 1)) #TODO: switch back to this value if timestep should start at 1, not zero
					actionAction.append('Generator Control')
					actionLoadBefore.append(str(entryOld))
					actionLoadAfter.append(str(entryNew))
			for battery in list(powerflowNew['storage'].keys()):
				entryNew = powerflowNew['storage'][battery]['real power setpoint (kW)'][0]
				if battery in list(powerflowOld['storage'].keys()):
					entryOld = powerflowOld['storage'][battery]['real power setpoint (kW)'][0]
				else:
					entryOld = 0.0
				if math.sqrt(((entryNew - entryOld)/(entryOld + 0.0000001))**2) > 0.5:
					actionDevice.append(battery)
					actionTime.append(str(timestep))
					# actionTime.append(str(timestep + 1)) #TODO: switch back to this value if timestep should start at 1, not zero
					actionAction.append('Battery Control')
					actionLoadBefore.append(str(entryOld))
					actionLoadAfter.append(str(entryNew))
			powerflowOld = powerflow[timestep]
		timestep += 1
	line = {
		'time': actionTime,
		'device': actionDevice,
		'action': actionAction,
		'loadBefore': actionLoadBefore,
		'loadAfter': actionLoadAfter}
	outputTime = pd.DataFrame(line, columns = ['time','device','action','loadBefore','loadAfter'])
	outputTimeline = outputTime.sort_values('time')
	# Create traces
	gens = go.Figure()
	gens.add_trace(go.Scatter(
		x=simTimeSteps,
		y=genProfiles['Diesel DG (kW)'],
		mode='lines',
		name='Diesel DG',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Diesel DG</b>: %{y:.3f}kW'))
	gens.add_trace(go.Scatter(
		x=simTimeSteps,
		y=genProfiles['Energy storage (kW)'],
		mode='lines',
		name='Energy Storage',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Energy Storage</b>: %{y:.3f}kW'))
	gens.add_trace(go.Scatter(
		x=simTimeSteps,
		y=genProfiles['Solar DG (kW)'],
		mode='lines',
		name='Solar DG',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Solar DG</b>: %{y:.3f}kW'))
	gens.add_trace(go.Scatter(
		x=simTimeSteps,
		y=genProfiles['Grid mix (kW)'],
		mode='lines',
		name='Grid Mix',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Grid Mix</b>: %{y:.3f}kW'))
	# Edit the layout
	gens.update_layout(
		xaxis_title='Hours',
		yaxis_title='Power (kW)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
	volts = go.Figure()
	volts.add_trace(go.Scatter(
		x=simTimeSteps,
		y=voltages['Min voltage (p.u.)'],
		mode='lines',
		name='Minimum Voltage',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Minimum Voltage</b>: %{y:.4f}'))
	volts.add_trace(go.Scatter(
		x=simTimeSteps, y=voltages['Max voltage (p.u.)'],
		mode='lines',
		name='Maximum Voltage',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Maximum Voltage</b>: %{y:.4f}'))
	volts.add_trace(go.Scatter(
		x=simTimeSteps,
		y=voltages['Mean voltage (p.u.)'],
		mode='lines',
		name='Mean Voltage',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Mean Voltage</b>: %{y:.4f}'))
	# Edit the layout
	volts.update_layout(
		xaxis_title='Hours',
		yaxis_title='Power (p.u.)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
	loads = go.Figure()
	loads.add_trace(go.Scatter(
		x=simTimeSteps,
		y=loadServed['Feeder load (%)'],
		mode='lines',
		name='Feeder Load',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Feeder Load</b>: %{y:.2f}%'))
	loads.add_trace(go.Scatter(
		x=simTimeSteps,
		y=loadServed['Microgrid load (%)'],
		mode='lines',
		name='Microgrid Load',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Microgrid Load</b>: %{y:.2f}%'))
	loads.add_trace(go.Scatter(
		x=simTimeSteps,
		y=loadServed['Bonus load via microgrid (%)'],
		mode='lines',
		name='Bonus Load via Microgrid',
		hovertemplate=
		'<b>Time Step</b>: %{x}<br>' +
		'<b>Bonus Load via Microgrid</b>: %{y:.2f}%'))
	# Edit the layout
	loads.update_layout(
		xaxis_title='Hours',
		yaxis_title='Load (%)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
	timelineStatsHtml = microgridTimeline(outputTimeline, workDir)
	with open(pathToOmd) as inFile:
		tree = json.load(inFile)['tree']
	feederMap = geo.omdGeoJson(pathToOmd, conversion = False)
	# generate a list of substations
	busNodes = []
	for key in tree.keys():
		if tree[key].get('bustype','') == 'SWING':
			busNodes.append(tree[key]['name'])
	row = 0
	row_count_timeline = outputTimeline.shape[0]
	
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

	while row < row_count_timeline:
		full_data = pullDataForGraph(tree, feederMap, outputTimeline, row)
		device, coordLis, coordStr, time, action, loadBefore, loadAfter = full_data
		dev_dict = {}
		try:
			if len(coordLis) == 2:
				dev_dict['geometry'] = {'type': 'Point', 'coordinates': [coordLis[0], coordLis[1]]}
				dev_dict['type'] = 'Feature'
				dev_dict['properties'] = {
					'device': device, 
					'time': time,
					'action': action,
					'loadBefore': loadBefore,
					'loadAfter': loadAfter,
					'pointColor': '#' + str(colormap(action)), 
					'popupContent': 'Location: <b>' + coordStrFormatter(str(coordStr)) + '</b><br>Device: <b>' + str(device) + '</b><br>Time: <b>' + str(time) + '</b><br>Action: <b>' + str(action) + '</b><br>Before: <b>' + str(loadBefore) + '</b><br>After: <b>' + str(loadAfter) + '</b>.' }
				feederMap['features'].append(dev_dict)
			else:
				dev_dict['geometry'] = {'type': 'LineString', 'coordinates': [[coordLis[0], coordLis[1]], [coordLis[2], coordLis[3]]]}
				dev_dict['type'] = 'Feature'
				dev_dict['properties'] = {
					'device': device, 
					'time': time,
					'action': action,
					'loadBefore': loadBefore,
					'loadAfter': loadAfter,
					'edgeColor': '#' + str(colormap(action)),
					'popupContent': 'Location: <b>' + coordStrFormatter(str(coordStr)) + '</b><br>Device: <b>' + str(device) + '</b><br>Time: <b>' + str(time) + '</b><br>Action: <b>' + str(action) + '</b><br>Before: <b>' + str(loadBefore) + '</b><br>After: <b>' + str(loadAfter) + '</b>.' }
				feederMap['features'].append(dev_dict)
		except:
			print('MESSED UP MAPPING on', device, full_data)
		row += 1
	if not os.path.exists(workDir):
		os.makedirs(workDir)
	shutil.copy(omf.omfDir + '/templates/geoJsonMap.html', workDir)
	with open(pJoin(workDir,'geoJsonFeatures.js'),'w') as outFile:
		outFile.write('var geojson =')
		json.dump(feederMap, outFile, indent=4)
	# Save geojson dict to then read into outdata in work function below
	with open(pJoin(workDir,'geoDict.js'),'w') as outFile:
		json.dump(feederMap, outFile, indent=4)
	# Generate customer outage outputs
	try:
		customerOutageData = pd.read_csv(pathToCsv)
	except:
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
	numberRows = max(math.ceil(customerOutageData.shape[0]/2),1)
	fig, axs = plt.subplots(numberRows, 2)
	row = 0
	average_lost_kwh = []
	outageCost = []
	globalMax = 0
	fig = go.Figure()
	businessTypes = set(customerOutageData['Business Type'])
	outageCostsByType = {busType: [] for busType in businessTypes}
	avgkWColumn = []
	durationColumn = []
	dssTree = dssConvert.dssToTree(f'{workDir}/circuitOmfCompatible_cleanLists.dss')
	loadShapeMeanMultiplier = {}
	loadShapeMeanActual = {}
	for dssLine in dssTree:
		if 'object' in dssLine and dssLine['object'].split('.')[0] == 'loadshape':
			shape = dssLine['mult'].replace('[','').replace('(','').replace(']','').replace(')','').split(',')
			shape = [float(y) for y in shape]
			if 'useactual' in dssLine and dssLine['useactual'] == 'yes': loadShapeMeanActual[dssLine['object'].split('.')[1]] = np.mean(shape)
			else: loadShapeMeanMultiplier[dssLine['object'].split('.')[1]] = np.mean(shape)/np.max(shape)
	while row < customerOutageData.shape[0]:
		customerName = str(customerOutageData.loc[row, 'Customer Name'])
		loadName = str(customerOutageData.loc[row, 'Load Name'])
		businessType = str(customerOutageData.loc[row, 'Business Type'])
		duration = str(0)
		averagekWperhr = str(0)
		for elementDict in dssTree:
			if 'object' in elementDict and elementDict['object'].split('.')[0] == 'load' and elementDict['object'].split('.')[1] == loadName:
				if 'daily' in elementDict: averagekWperhr = float(loadShapeMeanMultiplier.get(elementDict['daily'],0)) * float(elementDict['kw']) + float(loadShapeMeanActual.get(elementDict['daily'],0))
				else: averagekWperhr = float(elementDict['kw'])/2
				duration = str(cumulativeLoadsShed.count(loadName) * stepSize)
		if float(duration) >= .1 and float(averagekWperhr) >= .1:
			durationColumn.append(duration)
			avgkWColumn.append(float(averagekWperhr))
			season = str(customerOutageData.loc[row, 'Season'])
			customerOutageCost, kWperhrEstimate, times, localMax = customerCost1(duration, season, averagekWperhr, businessType)
			average_lost_kwh.append(float(averagekWperhr))
			outageCost.append(customerOutageCost)
			outageCostsByType[businessType].append(customerOutageCost)
			if localMax > globalMax:
				globalMax = localMax
			# creating series
			timesSeries = pd.Series(times)
			kWperhrSeries = pd.Series(kWperhrEstimate)
			trace = py.graph_objs.Scatter(
				x = timesSeries,
				y = kWperhrSeries,
				name = customerName,
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
	customerOutageData.insert(3, "Average kW/hr", avgkWColumn, True)
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

	fig.update_layout(xaxis_title = 'Duration (hours)',
		yaxis_title = 'Cost ($)',
		legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
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

	customerOutageHtml = customerOutageTable(customerOutageData, outageCost, workDir)
	profit_on_energy_sales = float(profit_on_energy_sales)
	restoration_cost = int(restoration_cost)
	hardware_cost = int(hardware_cost)
	outageDuration = int(outageDuration)
	utilityOutageHtml = utilityOutageTable(average_lost_kwh, profit_on_energy_sales, restoration_cost, hardware_cost, outageDuration, workDir)
	try: customerOutageCost = customerOutageCost
	except: customerOutageCost = 0
	return {'utilityOutageHtml': utilityOutageHtml, 'customerOutageHtml': customerOutageHtml, 'timelineStatsHtml': timelineStatsHtml, 'gens': gens, 'loads': loads, 'volts': volts, 'fig': fig, 'customerOutageCost': customerOutageCost, 'numTimeSteps': numTimeSteps, 'stepSize': stepSize, 'custHist': custHist}

def buildCustomEvents(eventsCSV='', feeder='', customEvents='customEvents.json', defaultDispatchable = 'true'):
	"""
	Build the custom events artifact used by this workflow.
	"""
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
		niceDss = dssConvert.evilGldTreeToDssTree(tree)
		dssConvert.treeToDss(niceDss, 'circuitOmfCompatible.dss')
		dssTree = dssConvert.dssToTree('circuitOmfCompatible.dss')
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

def work(modelDir, inputDict):
	# Copy specific climate data into model directory
	"""
	Run the microgrid control model analysis and return the output data used by the OMF
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
	niceDss = dssConvert.evilGldTreeToDssTree(tree)
	dssConvert.treeToDss(niceDss, f'{modelDir}/circuit.dss')
	dssConvert.treeToDss(niceDss, f'{modelDir}/circuitOmfCompatible.dss') # for querying loadshapes
	dssConvert.dssCleanLists(f'{modelDir}/circuitOmfCompatible.dss') # for querying loadshapes

	# Remove syntax that ONM doesn't like.
	with open(f'{modelDir}/circuit.dss','r') as dss_file:
		content = dss_file.read()
		content = re.sub(r'(\d),(\d|\-)', r'\1 \2', content) #space sep lists
		content = re.sub(r'(\d),(\d|\-)', r'\1 \2', content) #hack: no really, space sep
		# content = re.sub(r',,', r',0\.0,', content) #hack: replace null entries in matrices with zeros.
		content = re.sub(r'.*spectrum.*', r'', content) #drop spectrum
		content = re.sub(r'object=', r'', content) #drop object=
	with open(f'{modelDir}/circuit.dss','w') as dss_file_2:
		dss_file_2.write(content)
	# Run the main functions of the program
	if inputDict['microgridTaggingFileName'] != '':
		try:
			with open(pJoin(modelDir, inputDict['microgridTaggingFileName']), 'w') as f5:
				pathToData5 = f5.name
				f5.write(inputDict['microgridTaggingData'])
		except:
			pathToData5 = None
			print("ERROR - Unable to read microgrid tagging file: " + str(inputDict['microgridTaggingFileName']))
	else:
		pathToData5 = None

	if inputDict['loadPriorityFileName'] != '':
		try:
			with open(pJoin(modelDir, inputDict['loadPriorityFileName']), 'w') as f4:
				pathToData4 = f4.name
				f4.write(inputDict['loadPriorityData'])
		except:
			pathToData4 = None
			print("ERROR - Unable to read load priority file: " + str(inputDict['loadPriorityFileName']))
	else:
		pathToData4 = None

	if inputDict['genSettings'] == 'False':
		try:
			with open(pJoin(modelDir, inputDict['settingsFileName']), 'w') as f3:
				pathToData3 = f3.name
				f3.write(inputDict['settingsData'])
		except:
			pathToData3 = None
			print("ERROR - Unable to read Settings file: " + str(inputDict['settingsFileName']))
	else:
		pathToData3 = None

	if inputDict['useCache'] == 'True':
		try:
			with open(pJoin(modelDir, inputDict['outputFileName']), 'w') as f2:
				pathToData2 = f2.name
				f2.write(inputDict['outputData'])
		except:
			pathToData2 = None
			print("ERROR - Unable to read Cached output file: " + str(inputDict['outputFileName']))
	else:
		pathToData2 = None

	if inputDict['customerFileName']:
		with open(pJoin(modelDir, inputDict['customerFileName']), 'w') as f1:
			pathToData1 = f1.name
			f1.write(inputDict['customerData'])
	else: 
		with open(pJoin(modelDir, 'customerInfo.csv'), 'w') as f1:
			pathToData1 = f1.name
			f1.write(inputDict['customerData'])

	with open(pJoin(modelDir, inputDict['eventFileName']), 'w') as f:
		pathToData = f.name
		f.write(inputDict['eventData'])

	plotOuts = graphMicrogrid(
		modelDir + '/' + feederName + '.omd', #OMD Path
		pathToData,
		pathToData1,
		pathToData2,
		pathToData3,
		inputDict['useCache'],
		modelDir, #Work directory
		inputDict['profit_on_energy_sales'],
		inputDict['restoration_cost'],
		inputDict['hardware_cost'],
		inputDict['eventFileName'],
		inputDict['genSettings'],
		inputDict['solFidelity'],
		pathToData4,
		pathToData5
		)
	# Textual outputs of outage timeline
	with open(pJoin(modelDir,'timelineStats.html')) as inFile:
		outData['timelineStatsHtml'] = inFile.read()
	# Textual outputs of customer cost statistic
	with open(pJoin(modelDir,'customerOutageTable.html')) as inFile:
		outData['customerOutageHtml'] = inFile.read()
	# Textual outputs of utility cost statistic
	with open(pJoin(modelDir,'utilityOutageTable.html')) as inFile:
		outData['utilityOutageHtml'] = inFile.read()
	#The geojson dictionary to load into the outageCost.py template
	with open(pJoin(modelDir,'geoDict.js'),'rb') as inFile:
		outData['geoDict'] = inFile.read().decode()
	# Image outputs.
	# with open(pJoin(modelDir,'customerCostFig.png'),'rb') as inFile:
	#	outData['customerCostFig.png'] = base64.standard_b64encode(inFile.read()).decode()
	# Plotly outputs.
	layoutOb = go.Layout()
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
	# Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''
	outData['numTimeSteps'] = plotOuts.get('numTimeSteps', 24)
	outData['stepSize'] = plotOuts.get('stepSize', 1)
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
	# ====== Iowa240 Test Case
	feeder_file_path= [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.dss.omd']
	event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.events.json']
	settings_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.settings.json']
	output_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.output.json']
	loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.loadPriority.basic.json']
	loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','iowa240_dwp_22.microgridTagging.basic.json']
	microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	# ====== Nreca1824 Test Case
	# feeder_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.omd']
	# event_csv_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824events.csv']
	# event_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.events.json']
	# settings_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.settings.json']
	# output_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.output.json']
	# loadPriority_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.loadPriority.basic.json']
	# loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	# microgridTagging_file_path = [__neoMetaModel__._omfDir,'static','testFiles','nreca1824_dwp.microgridTagging.basic.json']
	# microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	
	# ====== Comment this out if no output file is specified (running ONM)
	output_file_data = open(pJoin(*output_file_path)).read()
	# ====== Comment this out if no load priority file is specified
	# loadPriority_file_data = open(pJoin(*loadPriority_file_path)).read()
	# ====== Comment this out if no load microgrid tagging file is specified
	# microgridTagging_file_data = open(pJoin(*microgridTagging_file_path)).read()
	defaultInputs = {
		'modelType': modelName,
		'feederName1': feeder_file_path[-1][0:-4],
		'outageDuration': '5',
		'profit_on_energy_sales': '0.03',
		'restoration_cost': '100',
		'hardware_cost': '550',
		'customerFileName': '',
		'customerData': '',
		'eventFileName': event_file_path[-1],
		'eventData': open(pJoin(*event_file_path)).read(),
		'outputFileName': output_file_path[-1],
		'outputData': open(pJoin(*output_file_path)).read(),
		'useCache': 'True',
		'settingsFileName': settings_file_path[-1],
		'settingsData': open(pJoin(*settings_file_path)).read(),
		'genSettings': 'False',
		'solFidelity': '0.05',
		'loadPriorityFileName': loadPriority_file_path[-1],
		'loadPriorityData': loadPriority_file_data,
		'microgridTaggingFileName': microgridTagging_file_path[-1],
		'microgridTaggingData': microgridTagging_file_data,
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(*feeder_file_path), pJoin(modelDir, defaultInputs['feederName1']+'.omd'))
	except:
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
	_debugging()
