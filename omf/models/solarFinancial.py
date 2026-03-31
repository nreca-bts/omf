''' Gives users the expected financial output of a PV system based on its costs and the amount energy it will likely produce. '''

import json, shutil, datetime as dt
from os.path import join as pJoin
from numpy_financial import irr, npv
import xlwt
from pathlib import Path
import numpy as np
from math import prod

# OMF imports
from omf import weather
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The solarFinancial model gives users the expected financial output of a PV system based on its costs and the amount energy it will likely produce."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''

	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	azimuth = float( inputDict['azimuth'] )
	trackingMode = int ( inputDict["trackingMode"] )
	inv_eff = float( inputDict['inverterEfficiency'] )
	rotlim = float( inputDict['rotlim'] )
	tilt = float( inputDict['tilt'] )
	systemSize = float(inputDict['systemSize'])
	simStartDate = inputDict['simStartDate']
	#Defaults

	derates = [
    float(inputDict.get("pvModuleDerate", 100)) / 100,
    float(inputDict.get("mismatch", 98)) / 100,
    float(inputDict.get("diodes", 99.5)) / 100,
    float(inputDict.get("dcWiring", 98)) / 100,
    float(inputDict.get("acWiring", 99)) / 100,
    float(inputDict.get("soiling", 95)) / 100,
    float(inputDict.get("shading", 100)) / 100,
    float(inputDict.get("sysAvail", 100)) / 100,
    float(inputDict.get("age", 100)) / 100
	]
	total_efficiency = prod(derates)
	total_loss_percent = (1 - total_efficiency) * 100
	### Set up system design parameter dict for PySAM pvWatts Model
	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": trackingMode,
						"azimuth": azimuth,
						"inv_eff": inv_eff,
						"losses": total_loss_percent,
						"rotlim": rotlim,
						"module_type": 2.0,
						"system_capacity": systemSize,
						"tilt": tilt,
				},
				"SolarResource": {
				}
		},
		"Other": {
				"lat": lat,
				"lon": long,
		}
	}
	# We need DNI, DHI, GHI, windspeed, and temp
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	requestSuccess = weather.nrel_getTMYData(modelDir=modelDir, attributes=attributes, longitude=long, latitude=lat)
	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		import PySAM.Pvwattsv8 as pvwatts
		pvwatts_model = pvwatts.new()
		full_data = pd.read_csv(Path(modelDir,"output_tmy_data.csv"))
		metadata = full_data.iloc[0:1].copy()
		wind_data = full_data.iloc[2:].copy()
		wind_data.columns = full_data.iloc[1]
		# We can snag elevation from the NSRDB Data we pulled out of the request
		# Source,Location ID,City,State,Country,Latitude,Longitude,Time Zone,Elevation
		# NSRDB,694051,-,-,-,33.21,-97.14,-6, 207 <- This 207 right here
		sys_design["Other"]["elev"] = int( metadata["Elevation"][0] )
		datetime_components_dict = {
			'year': simStartDate[0:4],
			'month': wind_data['Month'],
			'day': wind_data['Day'],
			'hour': wind_data['Hour'],
			'minute': wind_data['Minute'],
		}
		wind_data['datetime'] = pd.to_datetime(datetime_components_dict)
		wind_data = wind_data.set_index(wind_data["datetime"])
		solar_resource_data = {
			'lat': float( metadata["Latitude"][0] ),
			'lon': float( metadata["Longitude"][0] ),
			'tz': int( metadata["Time Zone"][0] ),
			'elev':  int( metadata["Elevation"][0] ),
			'year': [int(x) for x in wind_data['Year']],
			'month': [int(x) for x in wind_data['Month']],
			'day': [int(x) for x in wind_data['Day']],
			'hour': [int(x) for x in wind_data['Hour']],
			'minute': [int(x) for x in wind_data['Minute']],
			'dn': [float(x) for x in wind_data['DNI']],
			'df': [float(x) for x in wind_data['DHI']],
			'gh': [float(x) for x in wind_data['GHI']],
			'wspd': [float(x) for x in wind_data['Wind Speed']],
			'tdry': [float(x) for x in wind_data['Temperature']],
		}
		pvwatts_model.SolarResource.assign({'solar_resource_data': solar_resource_data})
		model_params = sys_design['ModelParams']
		pvwatts_model.assign(model_params)
		resource = pvwatts_model.SolarResource.export()
		# Convert and write JSON object to file
		with open( Path(modelDir, "solar_resource.json"), "w") as outfile: 
				json.dump(resource, outfile)
		pvwatts_model.execute()

		outData = {}
		# Geodata output.
		outData['latitude'] = pvwatts_model.Outputs.lat
		outData['longitude'] = pvwatts_model.Outputs.lon
		outData['elev'] = pvwatts_model.Outputs.elev

		poa = np.array( pvwatts_model.Outputs.poa, dtype=float)
		dn = np.array( pvwatts_model.Outputs.dn, dtype=float)
		df = np.array( pvwatts_model.Outputs.df, dtype=float)
		tamb = np.array( pvwatts_model.Outputs.tamb, dtype=float)
		tcell = np.array( pvwatts_model.Outputs.tcell, dtype=float)
		wspd = np.array( pvwatts_model.Outputs.wspd, dtype=float)
		ac = np.array( pvwatts_model.Outputs.ac, dtype=float) / 1000

		results_df = pd.DataFrame(
			{'timestamp': wind_data.index, 'poa': poa, 'dn': dn, 'df': df, 'tamb': tamb, 'tcell': tcell, 'wspd': wspd, 'ac': ac},
			columns=['timestamp', 'poa', 'dn', 'df', 'tamb', 'tcell', 'wspd', 'ac']
		)
		results_df = results_df.set_index( results_df["timestamp"])
		simLengthUnits = inputDict['simLengthUnits']
		if simLengthUnits == "minutes":
				freq = "t"
		elif simLengthUnits == "hours":
				freq = "h"
		elif simLengthUnits == "days":
				freq = "d"
		else:
				raise Exception()
		agg_df = results_df.resample(freq).sum(numeric_only=True)

		from calendar import monthrange
		simStartDate = inputDict["simStartDate"]
		sim_year = int(simStartDate.split("-")[0])

		def safe_replace_year(dt, target_year):
				try:
						return dt.replace(year=target_year)
				except ValueError:
						last_day = monthrange(target_year, dt.month)[1]
						return dt.replace(year=target_year, day=last_day)
		outData["timeStamps"] = [
				safe_replace_year(dt, sim_year).strftime('%Y-%m-%d %H:%M:%S') + ' UTC'
				for dt in agg_df.index
		]
		# Geodata output.
		outData['latitude'] = pvwatts_model.Outputs.lat
		outData['longitude'] = pvwatts_model.Outputs.lon
		# Weather output.
		outData['climate'] = {}
		outData['climate']['Global Horizontal Radiation (W/m^2)'] = agg_df["gh"].tolist() if "gh" in agg_df else []
		outData['climate']['Plane of Array Irradiance (W/m^2)'] = agg_df["poa"].tolist() if "poa" in agg_df else []
		outData['climate']['Ambient Temperature (F)'] = agg_df["tamb"].tolist() if "tamb" in agg_df else []
		outData['climate']['Cell Temperature (F)'] = agg_df["tcell"].tolist() if "tcell" in agg_df else []
		outData['climate']['Wind Speed (m/s)'] = agg_df["wspd"].tolist() if "wspd" in agg_df else []
		# Power generation and clipping.
		outData['powerOutputAc'] = agg_df["ac"].tolist() if "ac" in agg_df else []
		invSizeWatts = float(inputDict.get('inverterSize', 0)) * 1000
		outData['InvClipped'] = [x if x < invSizeWatts else invSizeWatts for x in outData['powerOutputAc']]
		try:
			outData['percentClipped'] = 100 * (1.0 - sum(outData['InvClipped']) / sum(outData['powerOutputAc']))
		except ZeroDivisionError:
			outData['percentClipped'] = 0.0
		# Cashflow outputs.
		lifeSpan = int(inputDict.get("lifeSpan",30))
		lifeYears = list(range(1, 1 + lifeSpan))
		retailCost = float(inputDict.get("retailCost",0.0))
		degradation = float(inputDict.get("degradation",0.5))/100
		installCost = float(inputDict.get("installCost",0.0))
		discountRate = float(inputDict.get("discountRate", 7))/100
		outData["oneYearGenerationWh"] = sum(outData["powerOutputAc"])
		outData["lifeGenerationDollars"] = [retailCost*(1.0/1000)*outData["oneYearGenerationWh"]*(1.0-(x*degradation)) for x in lifeYears]
		outData["lifeOmCosts"] = [-1.0*float(inputDict["omCost"]) for x in lifeYears]
		outData["lifePurchaseCosts"] = [-1.0 * installCost] + [0 for x in lifeYears[1:]]
		srec = inputDict.get("srecCashFlow", "").split(",")
		outData["srecCashFlow"] = list(map(float,srec)) + [0 for x in lifeYears[len(srec):]]
		outData["netCashFlow"] = [x+y+z+a for (x,y,z,a) in zip(outData["lifeGenerationDollars"], outData["lifeOmCosts"], outData["lifePurchaseCosts"], outData["srecCashFlow"])]
		outData["cumCashFlow"] = [x for x in _runningSum(outData["netCashFlow"])]
		outData["ROI"] = __neoMetaModel__.roundSig(sum(outData["netCashFlow"]), 3) / (-1*__neoMetaModel__.roundSig(sum(outData["lifeOmCosts"]), 3) + -1*__neoMetaModel__.roundSig(sum(outData["lifePurchaseCosts"], 3)))
		outData["NPV"] = __neoMetaModel__.roundSig(npv(discountRate, outData["netCashFlow"]), 3)
		outData["lifeGenerationWh"] = sum(outData["powerOutputAc"])*lifeSpan	
		outData["lifeEnergySales"] = sum(outData["lifeGenerationDollars"])
		try:
			# The IRR function is very bad.
			outData["IRR"] = __neoMetaModel__.roundSig(irr(outData["netCashFlow"]), 3)
		except:
			outData["IRR"] = "Undefined"
		# Monthly aggregation outputs.
		months = {"Jan":0,"Feb":1,"Mar":2,"Apr":3,"May":4,"Jun":5,"Jul":6,"Aug":7,"Sep":8,"Oct":9,"Nov":10,"Dec":11}
		totMonNum = lambda x:sum([z for (y,z) in zip(outData["timeStamps"], outData["powerOutputAc"]) if y.startswith(simStartDate[0:4] + "-{0:02d}".format(x+1))])
		outData["monthlyGeneration"] = [[a, totMonNum(b)] for (a,b) in sorted(months.items(), key=lambda x:x[1])]
		# Heatmaped hour+month outputs.
		hours = list(range(24))
		from calendar import monthrange
		totHourMon = lambda h,m:sum([z for (y,z) in zip(outData["timeStamps"], outData["powerOutputAc"]) if y[5:7]=="{0:02d}".format(m+1) and y[11:13]=="{0:02d}".format(h+1)])
		outData["seasonalPerformance"] = [[x,y,totHourMon(x,y) / monthrange(int(simStartDate[:4]), y+1)[1]] for x in hours for y in months.values()]
		# Stdout/stderr.
		outData["stdout"] = "Success"
		outData["stderr"] = ""
	return outData

def _dumpDataToExcel(modelDir):
	""" Dump data into .xls file in model workspace """
	# TODO: Think about a universal function
	wb = xlwt.Workbook()
	sh1 = wb.add_sheet("All Input Data")
	with open(pJoin(modelDir, "allInputData.json")) as f:
		inJson = json.load(f)
	size = len(inJson.keys())
	keys = list(inJson.keys())
	for i in range(size):
		sh1.write(i, 0, keys[i])
	values = list(inJson.values())
	for i in range(size):
		sh1.write(i, 1, values[i])
	with open(pJoin(modelDir, "allOutputData.json")) as f:
		outJson = json.load(f)
	sh1.write(0, 5, "Lat")
	sh1.write(0, 6, "Lon")
	sh1.write(0, 7, "Elev")
	sh1.write(1, 5, outJson["lat"])
	sh1.write(1, 6, outJson["lon"])
	sh1.write(1, 7, outJson["elev"])

	sh2 = wb.add_sheet("Hourly Data")
	sh2.write(0, 0, "TimeStamp")
	sh2.write(0, 1, "Power(kW-AC)")
	sh2.write(0, 2, "Power due to Inverter clipping(kW-AC)")	
	sh2.write(0, 3, "Plane of Array Irradiance (W/m^2)")	
	sh2.write(0, 4, "Global Horizontal Radiation(W/m^2)")	
	sh2.write(0, 5, "Wind Speed (m/s)")
	sh2.write(0, 6, "Ambient Temperature (F)")
	sh2.write(0, 7, "Cell Temperature (F)")

	for i in range(len(outJson["timeStamps"])):
		sh2.write(i + 1, 0, outJson["timeStamps"][i])
		sh2.write(i + 1, 1, outJson["powerOutputAc"][i])
		sh2.write(i + 1, 2, outJson["InvClipped"][i])
		sh2.write(i + 1, 3, outJson["climate"]["Plane of Array Irradiance (W/m^2)"][i])			
		sh2.write(i + 1, 4, outJson["climate"]["Global Horizontal Radiation (W/m^2)"][i])		
		sh2.write(i + 1, 5, outJson["climate"]["Wind Speed (m/s)"][i])
		sh2.write(i + 1, 6, outJson["climate"]["Ambient Temperature (F)"][i])
		sh2.write(i + 1, 7, outJson["climate"]["Cell Temperature (F)"][i])

	sh2.panes_frozen = True
	sh2.vert_split_pos = 1

	sh3 = wb.add_sheet("Monthly Data")
	sh3.write(0, 1, "Monthly Generation")
	for i in range(24):
		sh3.write(0, 3 + i, i + 1)
	for i in range(12):
		sh3.write(i + 1, 0, outJson["monthlyGeneration"][i][0])
		sh3.write(i + 1, 1, outJson["monthlyGeneration"][i][1])
	for i in range(len(outJson["seasonalPerformance"])):
		sh3.write(outJson["seasonalPerformance"][i][1] + 1, outJson["seasonalPerformance"]
				  [i][0] + 3, outJson["seasonalPerformance"][i][2])
	sh3.panes_frozen = True
	sh3.vert_split_pos = 3
	sh3.horz_split_pos = 1

	sh4 = wb.add_sheet("Annual Data")
	sh4.write(0, 0, "Year No.")
	for i in range(len(outJson["netCashFlow"])):
		sh4.write(i + 1, 0, i)
	sh4.write(0, 1, "Net Cash Flow ($)")
	sh4.write(0, 2, "Life O&M Costs ($)")
	sh4.write(0, 3, "Life Purchase Costs ($)")
	sh4.write(0, 4, "Cumulative Cash Flow ($)")
	for i in range(len(outJson["netCashFlow"])):
		sh4.write(i + 1, 1, outJson["netCashFlow"][i])
		sh4.write(i + 1, 2, outJson["lifeOmCosts"][i])
		sh4.write(i + 1, 3, outJson["lifePurchaseCosts"][i])
		sh4.write(i + 1, 4, outJson["cumCashFlow"][i])
	sh4.write(0, 10, "ROI")
	sh4.write(1, 10, outJson["ROI"])
	sh4.write(0, 11, "NPV")
	sh4.write(1, 11, outJson["NPV"])
	sh4.write(0, 12, "IRR")
	sh4.write(1, 12, outJson["IRR"])
	# sh4.write(2, 11, xlwt.Formula("NPV(('All Input Data'!B15/100,'Annual Data'!B2:B31))"))
	sh4.write(2, 12, xlwt.Formula("IRR(B2:B31)"))
	filename = "omf.solarFinancial.xls"
	wb.save(pJoin(modelDir, filename))
	outJson["excel"] = filename
	with open(pJoin(modelDir,"allOutputData.json"),"w") as outFile:
		json.dump(outJson, outFile, indent=4)

def _runningSum(inList):
	''' Give a list of running sums of inList. '''
	return [sum(inList[:i+1]) for (i,val) in enumerate(inList)]

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"simStartDate": "2013-01-01",
		"simLengthUnits": "hours",
		"modelType": modelName,
		"longitude": "-97.1292",
		"latitude": "33.2164",
		"simLength": "8760",
		"systemSize":"100",
		"installCost":"100000",
		"lifeSpan": "30",
		"degradation": "0.5",
		"retailCost": "0.10",
		"discountRate": "7",
		"pvModuleDerate": "100",
		"mismatch": "98",
		"diodes": "99.5",		
		"dcWiring": "98",
		"acWiring": "99",
		"soiling": "95",
		"shading": "100",
		"sysAvail": "100",
		"age": "100",		
		"inverterEfficiency": "92",
		"inverterSize": "75",
		"tilt": "45",
		"srecCashFlow": "5,5,3,3,2",
		"trackingMode":"0",
		"azimuth":"180",
		"runTime": "",
		"rotlim":"45.0",
		"gamma":"-0.45",
		"omCost": "1000"
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

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
