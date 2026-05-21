"""
Electric Vehicle Interconnection Analysis
"""

import json, os, shutil, csv, warnings, base64, platform
from os.path import join as pJoin
from random import randint, uniform
import numpy as np

import matplotlib
from matplotlib import pyplot as plt
#plt.style.use('seaborn')

# dateutil imports
from dateutil import parser
from dateutil.relativedelta import *

# OMF imports
import omf
from omf.models import voltageDrop, faultAnalysis
from omf.solvers import reopt_jl
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Injects faults in to circuits and measures fault currents, voltages, and protective device response."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# feederName = inputDict["feederName1"]
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	# Create voltage drop plot.
	# print "*DEBUG: feederName:", feederName
	with open(pJoin(modelDir,feederName + '.omd')) as f:
		omd = json.load(f)
	if inputDict.get("layoutAlgorithm", "geospatial") == "geospatial":
		neato = False
	else:
		neato = True
	# None check for batterySize
	if inputDict.get("batterySize", "None") == "None":
		batterySizeValue = None
	else:
		batterySizeValue = float(inputDict["batterySize"])
	# None check for chargeRate
	if inputDict.get("chargeRate", "None") == "None":
		chargeRateValue = None
	else:
		chargeRateValue = float(inputDict["chargeRate"])
	# None check for efficiency
	if inputDict.get("efficiency", "None") == "None":
		efficiencyValue = None
	else:
		efficiencyValue = float(inputDict["efficiency"])
	# None check for gasEfficiency
	if inputDict.get("gasEfficiency", "None") == "None":
		gasEfficiencyValue = None
	else:
		gasEfficiencyValue = float(inputDict["gasEfficiency"])
	# None check for numVehicles
	if inputDict.get("numVehicles", "None") == "None":
		numVehiclesValue = None
	else:
		numVehiclesValue = int(inputDict["numVehicles"])
	# None check for energyCost
	if inputDict.get("energyCost", "None") == "None":
		energyCostValue = None
	else:
		energyCostValue = float(inputDict["energyCost"])
	# None check for demandCost
	if inputDict.get("demandCost", "None") == "None":
		demandCostValue = None
	else:
		demandCostValue = float(inputDict["demandCost"])
	# None check for startHour
	if inputDict.get("startHour", "None") == "None":
		startHourValue = None
	else:
		startHourValue = int(inputDict["startHour"])
	# None check for endHour
	if inputDict.get("endHour", "None") == "None":
		endHourValue = None
	else:
		endHourValue = int(inputDict["endHour"])
	# None check for chargeLimit
	if inputDict.get("chargeLimit", "None") == "None":
		chargeLimitValue = None
	else:
		chargeLimitValue = float(inputDict["chargeLimit"])
	# None check for minCharge
	if inputDict.get("minCharge", "None") == "None":
		minChargeValue = None
	else:
		minChargeValue = float(inputDict["minCharge"])/100
	# None check for maxCharge
	if inputDict.get("maxCharge", "None") == "None":
		maxChargeValue = None
	else:
		maxChargeValue = float(inputDict["maxCharge"])/100
	# None check for gasCost
	if inputDict.get("gasCost", "None") == "None":
		gasCostValue = None
	else:
		gasCostValue = float(inputDict["gasCost"])
	# None check for workload
	if inputDict.get("workload", "None") == "None":
		workloadValue = None
	else:
		workloadValue = float(inputDict["workload"])
	# None check for loadName
	if inputDict.get("loadName", "None") == "None":
		loadNameValue = None
	else:
		loadNameValue = inputDict["loadName"]
	# None check for latitude
	if inputDict.get("latitude", "None") == "None":
		latitudeValue = None
	else:
		latitudeValue = float(inputDict["latitude"])
	# None check for longitude
	if inputDict.get("longitude", "None") == "None":
		longitudeValue = None
	else:
		longitudeValue = float(inputDict["longitude"])
	# None check for year
	if inputDict.get("year", "None") == "None":
		yearValue = None
	else:
		yearValue = int(inputDict["year"])

	# Setting up the loadShape file.
	with open(pJoin(modelDir,"loadShape.csv"),"w") as loadShapeFile:
		loadShapeFile.write(inputDict['loadShape'])
	try:
		loadShapeList = []
		with open(pJoin(modelDir,"loadShape.csv"), newline='') as inFile:
			reader = csv.reader(inFile)
			for row in reader:
				loadShapeList.append(row) 
			if len(loadShapeList)!=8760: raise Exception
	except:
		errorMessage = "CSV file is incorrect format. Please see valid format definition at <a target='_blank' href='https://github.com/dpinney/omf/wiki/Models-~-demandResponse#walkthrough'>OMF Wiki demandResponse</a>"
		raise Exception(errorMessage)

	loadShapeValue = [float(x[0]) for x in loadShapeList]

	# print loadShapeValue
	
	#calculate and display EV Charging Demand image, carpet plot image of 8760 load shapes
	maxLoadValue, demandImg, carpetPlotImg, hourlyConValue, combinedLoadShapeValue = plotEVShape(
		modelDir,
		numVehicles = numVehiclesValue,
		chargeRate = chargeRateValue, 
		batterySize = batterySizeValue, 
		startHour = startHourValue, 
		endHour = endHourValue, 
		chargeLimit = chargeLimitValue, 
		minCharge = minChargeValue, 
		maxCharge = maxChargeValue, 
		loadShape = loadShapeValue)
	demandImg.savefig(pJoin(modelDir, "evChargingDemand.png"))
	with open(pJoin(modelDir, "evChargingDemand.png"),"rb") as evFile:
		outData["evChargingDemand"] = base64.standard_b64encode(evFile.read()).decode('ascii')
	carpetPlotImg.savefig(pJoin(modelDir, "carpetPlot.png"))
	with open(pJoin(modelDir, "carpetPlot.png"),"rb") as cpFile:
		outData["carpetPlot"] = base64.standard_b64encode(cpFile.read()).decode('ascii')
	#run and display fuel cost calculation
	fuelCostHtml = fuelCostCalc(
		numVehicles = numVehiclesValue,
		batterySize = batterySizeValue,
		efficiency = efficiencyValue,
		energyCost = energyCostValue,
		gasEfficiency = gasEfficiencyValue,
		gasCost = gasCostValue,
		workload = workloadValue)
	with open(pJoin(modelDir, "fuelCostCalc.html"), "w") as fuelFile:
		fuelFile.write(fuelCostHtml)
	outData["fuelCostCalcHtml"] = fuelCostHtml

	#run and display voltage drop image and protective device status table
	voltPlotChart = voltageDrop.drawPlot(
		pJoin(modelDir,feederName + ".omd"),
		neatoLayout = neato,
		edgeCol = "PercentOfRating",
		nodeCol = "perUnitVoltage",
		nodeLabs = None,
		edgeLabs = None,
		customColormap = False,
		scaleMin = .9,
		scaleMax = 1.1,
		faultLoc = None,
		faultType = None,
		rezSqIn = 225,
		simTime = "2000-01-01 0:00:00",
		workDir = modelDir)
	voltPlotChart.savefig(pJoin(modelDir, "output.png"))
	with open(pJoin(modelDir, "output.png"),"rb") as inFile:
		outData["voltageDrop"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	protDevTable = faultAnalysis.drawTable(
		pJoin(modelDir,feederName + ".omd"),
		workDir = modelDir)
	with open(pJoin(modelDir, "statusTable.html"), "w") as tabFile:
		tabFile.write(protDevTable)
	outData['protDevTableHtml'] = protDevTable

	def voltplot_protdev(max_value=None, load_name=None):
		# warnings.filterwarnings("ignore")
		with open(pJoin(modelDir,feederName + ".omd")) as f:
			omd = json.load(f)
		tree = omd.get('tree', {})
		attachments = omd.get('attachments',[])

		#check to see that maximum load value is passed in
		maxValue = max_value
		loadName = load_name
		# maxValue = maxLoadValue
		# loadName = loadNameValue
		if maxValue != None:
			maxValue = float(maxValue)
			maxValueWatts = maxValue * 1000
			# print "maxValue = " + str(maxValue)
			# print "maxValueWatts = " + str(maxValueWatts)
			#check to see that loadName is specified
			if loadName != None:
				# Map to speed up name lookups.
				nameToIndex = {tree[key].get('name',''):key for key in tree.keys()}
				#check if the specified load name is in the tree
				if loadName in nameToIndex:
					key = nameToIndex[loadName]
					obtype = tree[key].get("object","")
					if obtype in ['triplex_node', 'triplex_load']:
						tree[key]['power_12_real'] = maxValueWatts
						#tree[key]['power_12'] = maxValueWatts
					elif obtype in ['load', 'pqload']:
						#tree[key]['constant_power_A_real'] = maxValueWatts
						tree[key]['constant_power_A_real'] = maxValueWatts/3
						tree[key]['constant_power_B_real'] = maxValueWatts/3
						tree[key]['constant_power_C_real'] = maxValueWatts/3
					else:
						raise Exception('Specified load name does not correspond to a load object. Make sure the object is of the following types: load, pqload, triplex_node, triplex_meter.')
					#run gridlab-d simulation with specified load set to max value
					omd['tree'] = tree
					feederName2 = "Olin Barre Fault - evInterconnection.omd"
					with open(modelDir + '/' + feederName2, "w+") as write_file:
						json.dump(omd, write_file)

					tempVoltPlotChart = voltageDrop.drawPlot(
						pJoin(modelDir,feederName2),
						neatoLayout = neato,
						edgeCol = "PercentOfRating",
						nodeCol = "perUnitVoltage",
						nodeLabs = "Load",
						edgeLabs = None,
						customColormap = False,
						scaleMin = .9,
						scaleMax = 1.1,
						faultLoc = None,
						faultType = None,
						rezSqIn = 225,
						simTime = "2000-01-01 0:00:00",
						workDir = modelDir,
						loadLoc = loadName)
					# loadVoltPlotChart.savefig(pJoin(modelDir, "loadVoltPlot.png"))
					# with open(pJoin(modelDir, "loadStatusTable.html"), "w") as tabFile:
					# 	tabFile.write(loadProtDevTable)
					# outData['loadProtDevTableHtml'] = loadProtDevTable
					# with open(pJoin(modelDir, "loadVoltPlot.png"),"rb") as inFile:
					# 	outData["loadVoltageDrop"] = inFile.read().encode("base64")
					tempProtDevTable = faultAnalysis.drawTable(
						pJoin(modelDir,feederName2),
						workDir = modelDir)
					return tempVoltPlotChart, tempProtDevTable
				else:
					print("Didn't find the gridlab object named " + loadName)
					#raise an exception if loadName isn't in the tree
					raise Exception('Specified load name does not correspond to an object in the tree.')
			else:
				print("loadName is None")
				#raise an exception if loadName isn't specified
				raise Exception('Invalid request. Load Name must be specified.')
		else:
			print("maxValue is None")
			#raise an exception if maximum load value is not being passed in
			raise Exception('Error retrieving maximum load value from load shape.')

	#run and display voltage drop image and protective device status table with updated glm where the node with the specified load name is changed to the max value
	loadVoltPlotChart, loadProtDevTable = voltplot_protdev(max_value=maxLoadValue, load_name=loadNameValue)
	loadVoltPlotChart.savefig(pJoin(modelDir, "loadVoltPlot.png"))
	with open(pJoin(modelDir, "loadStatusTable.html"), "w") as tabFile:
		tabFile.write(loadProtDevTable)
	outData['loadProtDevTableHtml'] = loadProtDevTable
	with open(pJoin(modelDir, "loadVoltPlot.png"),"rb") as inFile:
		outData["loadVoltageDrop"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	# Create the input JSON file for REopt
	scenario = {
		"Site": {
			"latitude": latitudeValue,
			"longitude": longitudeValue,
		},
		"ElectricLoad": {
			"loads_kw": combinedLoadShapeValue,		#8760 value list
			"year": yearValue 										#MUST BE THE CORRECT YEAR CORRELATING TO loads_kw!!
		},
		"ElectricTariff": {
			"urdb_rate_name": "custom",
			"blended_annual_energy_rate": energyCostValue, # "blended_annual_rates_us_dollars_per_kwh" $/kWh.
			"blended_annual_demand_rate": demandCostValue # "blended_annual_demand_charges_us_dollars_per_kw" $/kW/month
		}
	}
	with open(pJoin(modelDir, "Scenario_test_POST.json"), "w") as jsonFile:
		json.dump(scenario, jsonFile)
	# Run REopt API script
	reopt_jl.run_reopt_jl(modelDir, "Scenario_test_POST.json", run_with_sysimage=False)

	#read results from json generated from REopt
	with open(pJoin(modelDir, "results.json"), "r") as REoptFile:
		REopt_output = json.load(REoptFile)
		#print REopt_output
	print(pJoin(modelDir, "results.json"))
	# ********* If testing, set test_results_on_fail to True **********
	test_results_on_fail = False
	#check to see if REopt worked correctly. If not, use a cached results file for testing or raise exception. 
	if REopt_output["status"] != "optimal":
		if test_results_on_fail:
			print("Continuing simulation with cached results in dummyResults.json...")
			with open(pJoin(omf.omfDir, "static", "testFiles", "REoptDummyResults.json"), "r") as dummyResults:
				REopt_output = json.load(dummyResults)
		else:
			raise Exception("Error: REopt results generated are invalid")
		

	#find the values for energy cost with and without microgrid
	# REopt_ev_energy_cost = REopt_output["outputs"]["Scenario"]["Site"]["ElectricTariff"]["year_one_bill_bau_us_dollars"] # 2026-03 commented
	# REopt_opt_energy_cost =	REopt_output["outputs"]["Scenario"]["Site"]["ElectricTariff"]["year_one_bill_us_dollars"]
	REopt_ev_energy_cost = REopt_output["ElectricTariff"]["year_one_bill_before_tax_bau"]
	REopt_opt_energy_cost = REopt_output["ElectricTariff"]["year_one_bill_before_tax"]
	# REopt_ev_energy_cost = 100000
	# REopt_opt_energy_cost =	90000

	#Create the building energy cost table
	energyCostHtml = energyCostCalc(
		max_bau_load_shape = max(loadShapeValue),
		sum_bau_load_shape = sum(loadShapeValue),
		demand_charge = demandCostValue,
		energy_charge = energyCostValue,
		REopt_EV_output = REopt_ev_energy_cost,
		REopt_opt_output = REopt_opt_energy_cost)
	with open(pJoin(modelDir, "energyCostCalc.html"), "w") as energyFile:
		energyFile.write(energyCostHtml)
	outData["energyCostCalcHtml"] = energyCostHtml

	#get REopt's optimized load shape value list
	# REoptLoadShape = REopt_output["outputs"]["Scenario"]["Site"]["LoadProfile"]["year_one_electric_load_series_kw"]
	# REoptLoadShape = REopt_output["outputs"]["Scenario"]["Site"]["ElectricTariff"]["year_one_to_load_series_kw"] - 2026-03 commented
	REoptLoadShape = REopt_output["ElectricUtility"]["electric_to_load_series_kw"]
	

	#Create the maxLoadShape image and REopt carpet plot
	maxLoadShapeImg, REoptCarpetPlotImg = plotMaxLoadShape(
		loadShape = loadShapeValue,
		combined_load = combinedLoadShapeValue,
		hourly_con = hourlyConValue,
		REopt_load = REoptLoadShape)
	maxLoadShapeImg.savefig(pJoin(modelDir, "maxLoadShape.png"))
	with open(pJoin(modelDir, "maxLoadShape.png"),"rb") as evFile:
		outData["maxLoadShape"] = base64.standard_b64encode(evFile.read()).decode('ascii')
	REoptCarpetPlotImg.savefig(pJoin(modelDir, "REoptCarpetPlot.png"))
	with open(pJoin(modelDir, "REoptCarpetPlot.png"),"rb") as cpFile:
		outData["REoptCarpetPlot"] = base64.standard_b64encode(cpFile.read()).decode('ascii')
	#Create 3rd powerflow run with maximum load from new ReOpt output load shape
	REoptVoltPlotChart, REoptProtDevTable = voltplot_protdev(max_value=max(REoptLoadShape), load_name=loadNameValue)
	REoptVoltPlotChart.savefig(pJoin(modelDir, "REoptVoltPlot.png"))
	with open(pJoin(modelDir, "REoptStatusTable.html"), "w") as tabFile:
		tabFile.write(REoptProtDevTable)
	outData['REoptProtDevTableHtml'] = REoptProtDevTable
	with open(pJoin(modelDir, "REoptVoltPlot.png"),"rb") as inFile:
		outData["REoptVoltageDrop"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	fName = "input - 200 Employee Office, Springfield Illinois, 2001.csv"
	with open(pJoin(omf.omfDir, "static", "testFiles", fName)) as f:
		load_shape = f.read()
	defaultInputs = {
		"feederName1": "Olin Barre Fault",
		"modelType": modelName,
		"runTime": "",
		"layoutAlgorithm": "geospatial",
		"batterySize" : "50",
		"chargeRate" : "40",
		"efficiency" : "0.5",
		"gasEfficiency" : "8",
		"numVehicles" : "50",
		"energyCost" : "0.12",
		"startHour" : "8",
		"endHour" : "10",
		"chargeLimit" : "150",
		"minCharge" : "10",
		"maxCharge" : "50",
		"gasCost" : "2.70",
		"workload" : "40",
		"loadShape" : load_shape,
		"fileName" : fName,
		"loadName" : "62474211556",
		"rezSqIn" : "400",
		"simTime" : '2000-01-01 0:00:00',
		"latitude" : '39.7817',
		"longitude" : '-89.6501',
		"year" : '2001',
		"demandCost" : '0.1'
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _testingPlot():
	"""
	Internal helper for ev interconnection testing plot processing.
	"""
	PREFIX = omf.omfDir + '/scratch/CIGAR/'
	# FNAME = 'test_base_R4-25.00-1.glm_CLEAN.glm'
	# FNAME = 'test_Exercise_4_2_1.glm'
	# FNAME = 'test_ieee37node.glm'
	FNAME = 'test_ieee37nodeFaultTester.glm'
	# FNAME = 'test_ieee123nodeBetter.glm'
	# FNAME = 'test_large-R5-35.00-1.glm_CLEAN.glm'
	# FNAME = 'test_medium-R4-12.47-1.glm_CLEAN.glm'
	# FNAME = 'test_smsSingle.glm'
	# Hack: Agg backend doesn't work for interactivity. Switch to something we can use:
	# plt.switch_backend('MacOSX')
	chart = drawPlotFault(PREFIX + FNAME, neatoLayout=True, edgeCol="Current", nodeCol=None, nodeLabs="Name", edgeLabs=None, faultLoc="node713-704", faultType="TLG", customColormap=False, scaleMin=None, scaleMax=None, rezSqIn=225, simTime='2000-01-01 0:00:00')
	chart.savefig(PREFIX + "YO_WHATS_GOING_ON.png")
	# plt.show()

def plotMaxLoadShape(loadShape=None, combined_load=None, hourly_con=None, REopt_load=None):
	"""
	Create a plot or display artifact for max load shape results.
	"""
	base_shape = loadShape
	com_shape_REopt = REopt_load

	#find the maximum combined load value
	max_val = max(combined_load)
	#find that value's index
	max_index = combined_load.index(max_val)

	#find the day that the max load value occurs
	max_day_val = int((max_index)/24)
	max_hour_val = (max_index)%24
	day_shape = base_shape[max_day_val*24:max_day_val*24+24]

	#find the maximum REopt load value
	max_val_REopt = max(com_shape_REopt)
	#find that value's index
	max_index_REopt = com_shape_REopt.index(max_val_REopt)

	#find the day that the max REopt load value occurs
	max_day_val_REopt = int((max_index_REopt)/24)
	max_hour_val_REopt = (max_index_REopt)%24
	day_shape_REopt = com_shape_REopt[max_day_val_REopt*24:max_day_val_REopt*24+24]

	# print "max_val: " + str(max_val)
	# print "max_val_REopt: " + str(max_val_REopt)

	def maxLoadShape(load_vec, daily_vec, REopt_vec):
		maxLoadShapeImg = plt.figure()
		plt.style.use('seaborn')
		plt.ylim(0.0, 1.15*max_val)
		if len(load_vec) != 0:
			plt.stackplot(list(range(len(load_vec))), load_vec, daily_vec)
		if len(REopt_vec) != 0:
			plt.plot(day_shape_REopt, color='black', linestyle='dotted', label='with REopt Optimization')
		plt.title('Maximum Daily Load Shape')
		plt.ylabel('Demand (KW)')
		plt.xlabel('Time of Day (Hour)')
		plt.legend()
		plt.close()
		return maxLoadShapeImg

	#find the base shape of the REopt loads by subtracting the values of hourly_con
	base_shape_REopt = []
	for i in range(8760):
		base_load = com_shape_REopt[i] - hourly_con[i % 24]
		base_shape_REopt.append(base_load)

	def carpet_plot(load_vec, daily_vec):
		'Plot an 8760 load shape plus a daily augmentation in a nice grid.'
		carpetPlotImg = plt.figure()
		plt.style.use('seaborn')
		for i in range(1,371):
			# x = np.random.rand(24)
			x = list(load_vec[i*24:i*24 + 24])
			plt.subplot(31, 12, i)
			plt.axis('off')
			plt.ylim(0.0, max_val) # Should this be the same max value as the original combined carpet plot for better side-by-side comparison? It would only be an issue if for some reason REopt load values were higher than the originals, which shouldn't ever happen
			if len(x) != 0:
				plt.stackplot(list(range(len(x))), x, daily_vec)
			if i <= 12:
				plt.title(i)
			if i % 12 == 1:
				plt.text(-5.0, 0.1, str(int(1 + i / 12)), horizontalalignment='left',verticalalignment='center')
		#plt.show()
		plt.close()
		return carpetPlotImg


	return maxLoadShape(day_shape, hourly_con, day_shape_REopt), carpet_plot(base_shape_REopt, hourly_con)

def plotEVShape(modelDir, numVehicles=None, chargeRate=None, batterySize=None, startHour=None, endHour=None, chargeLimit=None, minCharge=None, maxCharge=None, loadShape=None, rezSqIn=None):
	"""
	Create a plot or display artifact for evshape results.
	"""
	shapes = []
	for i in range(numVehicles):
		# Random arrival
		charge_start = randint(startHour * 60, endHour * 60)
		# Random charge needed
		charge_needed = (1 - uniform(minCharge, maxCharge)) * batterySize
		# Make an array of charging powers and set them.
		shape = np.zeros(30*60)	# minute resolution, day + 6 hours.
		charging_minutes = int(60 * charge_needed/chargeRate)
		shape[charge_start: charge_start + charging_minutes] = 1.0 * chargeRate
		shapes.append(shape)
	def first_free_minute(shape, start_minute):
		'Find the earliest minute a load is not charging.'
		for m in range(start_minute, len(shape)):
			if shape[m] == 0:
				return m
		# If it's never free:
		return -1

	# Peak limit a collection of load shapes.
	shapes2 = np.copy(shapes)
	max_minutes = len(shapes2[0])
	for minute in range(max_minutes):	
		tot_load = sum([x[minute] for x in shapes2])
		if tot_load > chargeLimit:
			reduce_perc = chargeLimit / tot_load
			for shape in shapes2:
				# Stick the additional charging needed at the first free time.
				free_min = first_free_minute(shape, minute)
				shape[free_min] = (1 - reduce_perc) * shape[minute]
				# Reduce current load in proportion to how high the total is.
				shape[minute] = reduce_perc * shape[minute]
	# Plot the EV shape.
	evShape = plt.figure()
	plt.title('EV Charging Demand')
	plt.stackplot(list(range(max_minutes)), shapes2)
	plt.ylabel('Demand (KW)')
	plt.xlabel('Time of Day (Hour)')
	plt.plot(sum(shapes), color='black', label='Total (Uncontrolled)')
	plt.plot(sum(shapes2), color='black', linestyle='dotted', label='Total (Controlled)')
	plt.xticks([x*60 for x in range(int(max_minutes/60))], list(range(int(max_minutes/60))))
	plt.legend()
	plt.close()
	#plt.show()

	# Make a charging shape.
	con_charge = sum(shapes2)
	hourly_con = list(range(24))
	for i in range(24):
		hourly_con[i] = float(sum(con_charge[i * 60:i * 60 + 60])/60.0)

	# Make an annual building load base shape.
	#ann_shape = open(loadShape).readlines()
	#base_shape = [float(x) for x in ann_shape]
	base_shape = loadShape

	# Make an output csv.
	combined = []
	for i in range(8760):
		com_load = base_shape[i] + hourly_con[i % 24]
		combined.append(com_load)
	with open(pJoin(modelDir,'output - evInterconnection combined load shapes.csv'), 'w') as outFile:
		for row in combined:
			outFile.write(str(row) + '\n')

	def carpet_plot(load_vec, daily_vec):
		'Plot an 8760 load shape plus a daily augmentation in a nice grid.'
		carpetPlotImg = plt.figure()
		plt.style.use('seaborn')
		for i in range(1,371):
			# x = np.random.rand(24)
			x = list(load_vec[i*24:i*24 + 24])
			plt.subplot(31, 12, i)
			plt.axis('off')
			plt.ylim(0.0, max(combined))
			if len(x) != 0:
				plt.stackplot(list(range(len(x))), x, daily_vec)
			if i <= 12:
				plt.title(i)
			if i % 12 == 1:
				plt.text(-5.0, 0.1, str(int(1 + i / 12)), horizontalalignment='left',verticalalignment='center')
		#plt.show()
		plt.close()
		return carpetPlotImg

	#find the maximum combined load value
	max_val = max(combined)
	# #find that value's index
	# max_index = combined.index(max_val)

	# #find the day that the max load value occurs
	# max_day_val = (max_index)/24
	# max_hour_val = (max_index)%24
	# day_shape = base_shape[max_day_val*24:max_day_val*24+24]

	# def maxLoadShape(load_vec, daily_vec):
	# 	maxLoadShapeImg = plt.figure()
	# 	plt.style.use('seaborn')
	# 	plt.ylim(0.0, 1.15*max_val)
	# 	if len(load_vec) != 0:
	# 		plt.stackplot(range(len(load_vec)), load_vec, daily_vec)
	# 	plt.title('Maximum Daily Load Shape')
	# 	plt.ylabel('Demand (KW)')
	# 	plt.xlabel('Time of Day (Hour)')
	# 	plt.close()
	# 	return maxLoadShapeImg
		
	#return max_val, evShape, carpet_plot(base_shape, hourly_con), maxLoadShape(day_shape, hourly_con), combined
	return max_val, evShape, carpet_plot(base_shape, hourly_con), hourly_con, combined

def fuelCostCalc(numVehicles=None, batterySize=None, efficiency=None, energyCost=None, gasEfficiency=None, gasCost=None, workload=None):
	"""
	Perform fuel cost calc processing for the ev interconnection model.
	"""
	dailyGasAmount = workload/gasEfficiency #amount(gal) of gas used per vehicle, daily
	dailyGasCost = dailyGasAmount*gasCost #amount($) spent on gas per vehicle, daily
	totalGasCost = numVehicles*dailyGasCost #amount($) spent on gas daily for all vehicles
	dailyEnergyAmount = workload/efficiency #amount(KWh) of energy used per vehicle, daily
	dailyEnergyCost = dailyEnergyAmount*energyCost #amount($) spent on energy per vehicle, daily
	totalEnergyCost = numVehicles*dailyEnergyCost #amount($) spent on energy daily for all vehicles
	dailySavings = dailyGasCost-dailyEnergyCost #amount($) saved per vehicle, daily
	totalSavings = totalGasCost-totalEnergyCost #amount($) saved daily
	html_str = """
		<div style="text-align:center">
			<p style="padding-top:10px; padding-bottom:10px;">Driving <b>""" + str(numVehicles) +"""</b> vehicles <b>"""+ str(workload) +""" miles</b> daily, at <b>"""+ str(gasEfficiency) +""" mpg</b> and <b>$""" + str(gasCost) + """/gal</b>:</p>
			<p>Total gas used daily:<span style="padding-left:2em">"""+str(dailyGasAmount)+""" gal</span></p>
			<p>Daily Cost per vehicle:<span style="padding-left:2em">$"""+str(dailyGasCost)+"""</span></p>
			<p>Total daily cost:<span style="padding-left:2em">$"""+str(totalGasCost)+"""</span></p>
			<p style="padding-top:10px; padding-bottom:10px;">Driving <b>""" + str(numVehicles) +"""</b> vehicles <b>"""+ str(workload) +""" miles</b> daily, at <b>"""+ str(efficiency) +""" mpkwh</b> and <b>$""" + str(energyCost) + """/kwh:</b></p>
			<p>Total energy used daily:<span style="padding-left:2em">"""+str(dailyEnergyAmount)+""" kwh</span></p>
			<p>Daily cost per vehicle:<span style="padding-left:2em">$"""+str(dailyEnergyCost)+"""</span></p>
			<p>Total daily cost:<span style="padding-left:2em">$"""+str(totalEnergyCost)+"""</span></p>
			<p style="padding-top:10px; padding-bottom:10px;">Daily savings per vehicle:<span style="padding-left:1em">$"""+str(dailySavings)+"""</span><span style="padding-left:4em">Total daily savings:<span style="padding-left:1em">$"""+str(totalSavings)+"""</span></span></p>
		</div>"""
	return html_str

def energyCostCalc(max_bau_load_shape = None, sum_bau_load_shape = None, demand_charge = None, energy_charge = None, REopt_EV_output=None, REopt_opt_output=None):
	"""
	Perform energy cost calc processing for the ev interconnection model.
	"""
	bau_energy_cost = max_bau_load_shape*demand_charge + sum_bau_load_shape*energy_charge
	ev_energy_cost = REopt_EV_output
	opt_energy_cost = REopt_opt_output
	html_str = """
		<div style="text-align:center">
			<p style="padding-top:30px; padding-bottom:15px;">Yearly Energy Costs:</p>
			<p style="padding-top:10px; padding-bottom:10px;">Business as usual (no EVs): <b>$""" + '{:20,.2f}'.format(bau_energy_cost) +"""</b> </p>
			<p style="padding-top:10px; padding-bottom:10px;">with EVs: <b>$""" + '{:20,.2f}'.format(ev_energy_cost) +"""</b> </p>
			<p style="padding-top:10px; padding-bottom:30px;">with EVs and microgrid: <b>$""" + '{:20,.2f}'.format(opt_energy_cost) +"""</b> </p>
		</div>"""
	return html_str

@neoMetaModel_test_setup
def _debug():
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
	_debug()
	# _testingPlot()