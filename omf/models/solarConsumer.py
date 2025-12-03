''' Calculate solar costs and benefits for consumers. '''

# OMF Imports
from omf import weather
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Python Imports
from pathlib import Path
import requests
import numpy as np
import shutil, datetime
from os.path import join as pJoin
from matplotlib import pyplot as plt

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The solarConsumer model calculates the expected costs for a consumer who buys solar in one of 3 different ways: through a PPA with a 3rd party, a community solar project, or buying a rooftop system."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''

	### Get inputs for system design parameters
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )

	# Constants
	azimuth = 180
	trackingMode = 0
	inv_eff = 97.5
	losses = 15.53
	sys_cap = 750
	tilt = 45

	### Set up system design parameter dict for PySAM pvWatts Model
	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": trackingMode,
						"azimuth": azimuth,
						"inv_eff": inv_eff,
						"losses": losses,
						"module_type": 2.0,
						"system_capacity": sys_cap,
						"tilt": tilt
				},
				"SolarResource": {
				}
		},
		"Other": {
				"lat": lat,
				"lon": long,
		}
	}

	### Get the data from NSRDB API
	nrel_key = "rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56"
	email = "admin@omf.coop"
	base_url = f"https://developer.nrel.gov/api/nsrdb/v2/solar/nsrdb-GOES-tmy-v4-0-0-download.csv?"

	# We need DNI, DHI, GHI, windspeed, and temp
	requestSuccess = False
	lat_long_to_wkt = weather.nsrbd_latlon_to_wkt(longitude=long, latitude=lat) # "POINT({lon_str} {lat_str})"
	modified_url = f"{base_url}wkt={lat_long_to_wkt}&attributes={'dni,dhi,ghi,wind_speed,air_temperature'}&names=tmy&utc=false&leap_day=true&email={email}&api_key={nrel_key}"
	response = requests.get(modified_url)
	if response.status_code == 400:
		print(f"url: {modified_url}")
		raise Exception(f"pvwatts work(): API Request Failed :: Request Code: {response.status_code} :: Reason: {response.reason}")
	else:
		text = response.text
		lines = text.splitlines()[2:]
		nsrdb_data = text.splitlines()[:2]
		clean_text = "\n".join(lines)
		with open( Path(modelDir,"output_tmy_wind_data.csv"), "w") as text_file:
			text_file.write(clean_text)
			requestSuccess = True

	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		import PySAM.Pvwattsv8 as pvwatts
		pvwatts_model = pvwatts.new()
		wind_data = pd.read_csv(Path(modelDir,"output_tmy_wind_data.csv"))

		# We can snag elevation from the NSRDB Data we pulled out of the request
		# Source,Location ID,City,State,Country,Latitude,Longitude,Time Zone,Elevation
		# NSRDB,694051,-,-,-,33.21,-97.14,-6, 207 <- This 207 right here
		elevation = int( nsrdb_data[1].split(",")[8] )
		sys_design["Other"]["elev"] = elevation
		datetime_components_dict = {
			'year': wind_data['Year'],
			'month': wind_data['Month'],
			'day': wind_data['Day'],
			'hour': wind_data['Hour'],
			'minute': wind_data['Minute'],
		}
		wind_data['datetime'] = pd.to_datetime(datetime_components_dict)
		wind_data = wind_data.set_index(wind_data["datetime"])
		solar_resource_data = {
			'lat': lat,
			'lon': long,
			'tz': -7,
			'elev': elevation,
			'year': wind_data['Year'].tolist(),
			'month': wind_data['Month'].tolist(),
			'day': wind_data['Day'].tolist(),
			'hour': wind_data['Hour'].tolist(),
			'minute': wind_data['Minute'].tolist(),
			'dn': wind_data['DNI'].tolist(),
			'df': wind_data['DHI'].tolist(),
			'gh': wind_data['GHI'].tolist(),
			'wspd': wind_data['Wind Speed'].tolist(),
			'tdry': wind_data['Temperature'].tolist(),
		}

		pvwatts_model.SolarResource.solar_resource_data = solar_resource_data
		model_params = sys_design['ModelParams']
		pvwatts_model.assign(model_params)
		resource = pvwatts_model.SolarResource.export()
		# Convert and write JSON object to file
		with open( Path(modelDir, "solar_resource.json"), "w") as outfile: 
				json.dump(resource, outfile)
		pvwatts_model.execute()

	# Set the timezone to be UTC, it won't affect calculation and display, relative offset handled in pvWatts.html
	startDateTime = "2013-01-01 00:00:00 UTC"

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
	# Timestamp output.
	outData = {}
	outData['timeStamps'] = [
		(datetime.datetime.strptime(startDateTime[0:19], '%Y-%m-%d %H:%M:%S') + datetime.timedelta(**{'hours':x})).strftime('%Y-%m-%d %H:%M:%S') + ' UTC'
		for x in range(8760)
	]
	# HACK: makes it easier to calculate some things later.
	outData["pythonTimeStamps"] = [datetime.datetime(2012,1,1,0) + x * datetime.timedelta(hours=1) for x in range(8760)]

	# Geodata output.
	outData['lat'] = lat
	outData['lon'] = long
	outData['elev'] = elevation
	# Weather output.
	outData["climate"] = {}
	outData['climate']['Global Horizontal Radiation (W/m^2)'] = results_df["gh"].tolist() if "gh" in results_df else []
	outData['climate']['Plane of Array Irradiance (W/m^2)'] = results_df["poa"].tolist() if "poa" in results_df else []
	outData['climate']['Ambient Temperature (F)'] = results_df["tamb"].tolist() if "tamb" in results_df else []
	outData['climate']['Cell Temperature (F)'] = results_df["tcell"].tolist() if "tcell" in results_df else []
	outData['climate']['Wind Speed (m/s)'] = results_df["wspd"].tolist() if "wspd" in results_df else []
	# Power generation.
	outData['powerOutputAc'] = results_df["ac"].tolist() if "ac" in results_df else []

	# TODO: INSERT TJ CODE BELOW
	tjCode(inputDict, outData)
	del outData["pythonTimeStamps"]
	# TODO: INSERT TJ CODE ABOVE

	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def tjCode(inputs, outData):
	# Make inputs the right types.
	for k in inputs.keys():
		try:
			inputs[k] = float(inputs[k])
		except:
			pass
	inputs['years'] = int(inputs['years'])
	inputs['monthlyDemand'] = [float(x) for x in inputs['monthlyDemand'].split(',')]
	# Associate solar output with time
	monthlySolarOutput = list(zip(outData["powerOutputAc"],outData["pythonTimeStamps"]))
	outData["monthlySolarGen"] = []
	for y in range(1,13):
		monthSum = sum([x[0] for x in monthlySolarOutput if x[1].month == y])
		#convert to kWh
		monthSum = monthSum / 1000
		outData["monthlySolarGen"].append(monthSum)
	# Calculate monthly energy use for all cases.
	totalEnergyUse=[]
	totalSolarGen=[]
	for z in range(inputs['years']):
		totalEnergyUse.extend([x-y for x,y in zip(inputs["monthlyDemand"],outData["monthlySolarGen"])])
		totalSolarGen.extend(outData["monthlySolarGen"])
		outData["monthlySolarGen"] = [.995*x for x in outData["monthlySolarGen"]]
	# Calculating monthly bills for all cases.
	monthlyBillsBaseCase = []
	monthlyBillsComS = []
	monthlyBillsRoof = []
	monthlyBillsGrid3rdParty = []
	monthlyBillsSolar3rdParty = []
	monthlyBills3rdParty = []
	# Variables for goal seeking on.
	retailRate = inputs["retailCost"]
	PartyRate = inputs["ThirdPartyRate"]
	comRate = inputs["comRate"]
	#Calculate Net Energy Metering Scenario:
	if inputs["meteringType"]=='netEnergyMetering':
		for x in range(inputs['years']):
			for y in range(1,13):
				monthlyBillsBaseCase.append(retailRate * inputs['monthlyDemand'][y-1])
				monthlyBillsComS.append(comRate * totalEnergyUse[x*12+y-1]+inputs["comMonthlyCharge"])
				monthlyBillsRoof.append(retailRate * totalEnergyUse[x*12+y-1]+inputs["utilitySolarMonthlyCharge"])
				monthlyBills3rdParty.append(retailRate * totalEnergyUse[x*12+y-1]+PartyRate * totalSolarGen[x*12+y-1]+inputs["utilitySolarMonthlyCharge"])
			retailRate = retailRate*(1+inputs["rateIncrease"]/100)
			comRate = comRate*(1+inputs["comRateIncrease"]/100)
			PartyRate = PartyRate*(1+inputs["ThirdPartyRateIncrease"]/100)
	#Calculate Production Metering Scenario
	elif inputs["meteringType"]=='production':
		for x in range(inputs['years']):
			for y in range(1,13):
				monthlyBillsBaseCase.append(retailRate * inputs['monthlyDemand'][y-1])
				monthlyBillsComS.append(comRate * inputs['monthlyDemand'][y-1]+inputs["comMonthlyCharge"] - inputs['valueOfSolarRate']*totalSolarGen[x*12+y-1])
				monthlyBillsRoof.append(retailRate * inputs['monthlyDemand'][y-1]+inputs["utilitySolarMonthlyCharge"] - inputs['valueOfSolarRate']*totalSolarGen[x*12+y-1])
				monthlyBills3rdParty.append(retailRate * totalEnergyUse[x*12+y-1]+PartyRate * totalSolarGen[x*12+y-1]+inputs["utilitySolarMonthlyCharge"])
			retailRate = retailRate*(1+inputs["rateIncrease"]/100)
			comRate = comRate*(1+inputs["comRateIncrease"]/100)
			PartyRate = PartyRate*(1+inputs["ThirdPartyRateIncrease"]/100)
	#Calculate Excess Metering Scenario
	elif inputs["meteringType"]=='excessEnergyMetering':
		for x in range(inputs['years']):
			for y in range(1,13):
				if totalEnergyUse[x*12+y-1]>0:
					monthlyBillsBaseCase.append(retailRate * inputs['monthlyDemand'][y-1])
					monthlyBillsComS.append(comRate * inputs['monthlyDemand'][y-1]+inputs["comMonthlyCharge"] - inputs['valueOfSolarRate']*totalSolarGen[x*12+y-1])
					monthlyBillsRoof.append(retailRate * inputs['monthlyDemand'][y-1]+inputs["utilitySolarMonthlyCharge"] - inputs['valueOfSolarRate']*totalSolarGen[x*12+y-1])
					monthlyBills3rdParty.append(retailRate * totalEnergyUse[x*12+y-1]+PartyRate * totalSolarGen[x*12+y-1]+inputs["utilitySolarMonthlyCharge"])
				else:
					excessSolar=abs(totalEnergyUse[x*12+y-1])
					monthlyBillsBaseCase.append(retailRate * inputs['monthlyDemand'][y-1])
					monthlyBillsComS.append(comRate * inputs['monthlyDemand'][y-1]+inputs["comMonthlyCharge"] - inputs['valueOfSolarRate']*excessSolar)
					monthlyBillsRoof.append(retailRate * inputs['monthlyDemand'][y-1]+inputs["utilitySolarMonthlyCharge"] - inputs['valueOfSolarRate']*excessSolar)
					monthlyBills3rdParty.append(retailRate * totalEnergyUse[x*12+y-1]+PartyRate * totalSolarGen[x*12+y-1]+inputs["utilitySolarMonthlyCharge"])
			retailRate = retailRate*(1+inputs["rateIncrease"]/100)
			comRate = comRate*(1+inputs["comRateIncrease"]/100)
			PartyRate = PartyRate*(1+inputs["ThirdPartyRateIncrease"]/100)
	# Add upfront costs to the first month.
	monthlyBillsComS[0]+= inputs["comUpfrontCosts"]
	monthlyBillsRoof[0]+= inputs["roofUpfrontCosts"]
	# Average monthly bill calculation:
	outData["avgMonthlyBillBaseCase"] = sum(monthlyBillsBaseCase)/len(monthlyBillsBaseCase)
	outData["avgMonthlyBillComS"] = sum(monthlyBillsComS)/len(monthlyBillsComS)
	outData["avgMonthlyBillRoof"] = sum(monthlyBillsRoof)/len(monthlyBillsRoof)
	outData["avgMonthlyBill3rdParty"] = sum(monthlyBills3rdParty)/len(monthlyBills3rdParty)
	# Total energy cost calculation:
	outData["totalCostBaseCase"] = sum(monthlyBillsBaseCase)
	outData["totalCostComS"] = sum(monthlyBillsComS)
	outData["totalCostRoof"] = sum(monthlyBillsRoof)
	outData["totalCost3rdParty"] = sum(monthlyBills3rdParty)
	#Cost per kWh
	outData["kWhCostBaseCase"]=outData["totalCostBaseCase"]/sum(inputs["monthlyDemand"]*inputs["years"])
	outData["kWhCostComS"]=outData["totalCostComS"]/sum(inputs["monthlyDemand"]*inputs["years"])
	outData["kWhCost3rdParty"]=outData["totalCost3rdParty"]/sum(inputs["monthlyDemand"]*inputs["years"])
	outData["kWhCostRoof"]=outData["totalCostRoof"]/sum(inputs["monthlyDemand"]*inputs["years"])
	# Total Savings Money saved compared to base case:
	outData["totalSavedByComS"] = outData["totalCostBaseCase"] - outData["totalCostComS"]
	outData["totalSavedBy3rdParty"] = outData["totalCostBaseCase"] - outData["totalCost3rdParty"]
	outData["totalSavedByRoof"] = outData["totalCostBaseCase"] - outData["totalCostRoof"]
	#Lists of cumulative Costs
	outData['cumulativeBaseCase'] = cumulativeBaseCase = [sum(monthlyBillsBaseCase[0:i+1]) for i,d in enumerate(monthlyBillsBaseCase)]
	outData['cumulativeComS'] = cumulativeComS = [sum(monthlyBillsComS[0:i+1]) for i,d in enumerate(monthlyBillsComS)]
	outData['cumulative3rdParty'] = cumulative3rdParty = [sum(monthlyBills3rdParty[0:i+1]) for i,d in enumerate(monthlyBills3rdParty)]
	outData['cumulativeRoof'] = cumulativeRoof = [sum(monthlyBillsRoof[0:i+1]) for i,d in enumerate(monthlyBillsRoof)]
	#When does communtiy solar and others beat the base case?
	#Calculate Simple Payback of solar options
	def spp(cashflow):
		''' Years to pay back the initial investment. Or -1 if it never pays back. '''
		for i, val in enumerate(cashflow):
				net = sum(cashflow[0:i+1])
				if net >= 0:
						return i + (abs(float(cashflow[i-1]))/val)
		return -1
	outData["sppComS"] = spp([x-y for x,y in zip(monthlyBillsBaseCase, monthlyBillsComS)])/12
	outData["spp3rdParty"] = spp([x-y for x,y in zip(monthlyBillsBaseCase, monthlyBills3rdParty)])/12
	outData["sppRoof"] = spp([x-y for x,y in zip(monthlyBillsBaseCase, monthlyBillsRoof)])/12
	# Green electron calculations:
	sumDemand = sum(inputs["monthlyDemand"])*inputs['years']
	sumSolarGen = sum(totalSolarGen)
	sumSolarDemandDif = sumDemand - sumSolarGen
	if sumSolarGen>= sumDemand:
		outData["greenElectrons"]=100
	else:
		outData["greenElectrons"]=(sumSolarDemandDif/sumDemand)*inputs["greenFuelMix"]+(sumSolarGen/sumDemand)*100
	# Lifetime costs to the consumer graph:
	plt.figure()
	plt.title('Lifetime Energy Costs')
	plt.bar([1,2,3,4],[outData["totalCostBaseCase"],outData["totalCostComS"],outData["totalCost3rdParty"],outData["totalCostRoof"]])
	plt.ylabel('Cost ($)')
	plt.xticks([1.4,2.4,3.4,4.4], ['No Solar','Community Solar','Leased Rooftop','Purchased Rooftop'])
	# # Monthly bills graph:
	# plt.figure()
	# plt.title('Monthly Bills')
	# plt.plot(monthlyBillsBaseCase, color ="black")
	# plt.plot(monthlyBillsComS, color ="blue")
	# plt.plot(monthlyBills3rdParty, color ="red")
	# plt.plot(monthlyBillsRoof, color ="yellow")
	# Cumulative consumer costs over time graph:
	plt.figure()
	plt.title('Cumulative Costs')
	plt.plot(cumulativeBaseCase, color='black', label='No Solar')
	plt.plot(cumulativeComS, color='blue', label='Community Solar')
	plt.plot(cumulative3rdParty, color='red', label='Leased Rooftop')
	plt.plot(cumulativeRoof, color='orange', label='Purchased Rooftop')
	plt.legend(loc='upper left')
	# All other outputs in data table:
	plt.figure()
	plt.title('Costs By Purchase Type')
	plt.axis('off')
	plt.table(
		loc='center',
		rowLabels=["Base Case", "Community Solar", "Rooftop Solar", "3rd Party Solar"],
		colLabels=["Total Cost","Total Saved", "Average Monthly Cost", "$/kWh", "Simple Payback Period", "Green Electrons"],
		cellText=[
			[outData["totalCostBaseCase"],"Not Available", outData["avgMonthlyBillBaseCase"],outData["kWhCostBaseCase"], "Not Available",inputs["greenFuelMix"]],
			[outData["totalCostComS"],outData["totalSavedByComS"], outData["avgMonthlyBillComS"],outData["kWhCostComS"], outData["sppComS"], outData["greenElectrons"]],
			[outData["totalCostRoof"],outData["totalSavedByRoof"], outData["avgMonthlyBillRoof"],outData["kWhCostRoof"], outData["sppRoof"], outData["greenElectrons"]],
			[outData["totalCost3rdParty"],outData["totalSavedBy3rdParty"], outData["avgMonthlyBill3rdParty"],outData["kWhCost3rdParty"], outData["spp3rdParty"], outData["greenElectrons"]]])
	# plt.show()

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		'modelType':modelName,
		"latitude": "33.2164",
		"longitude": "-97.1292",
		'SystemSize': 9,
		'meteringType':
			'netEnergyMetering', # Total cost reduced by total solar gen * retail rate.
			#'production', # Total cost reduced by total solar gen * wholesale rate.
			#'excessEnergyMetering', # Total cost reduced by total solar gen * retail rate; but, if generation exceeds demand (over the life of the system), only get paid wholesale rate for the excess.
		'years':25,
		'retailCost':0.11,
		'valueOfSolarRate':.07,
		'monthlyDemand':'3000,3000,3000,3000,3000,3000,3000,3000,3000,3000,3000,3000',
		'rateIncrease':2.5,
		'roofUpfrontCosts':17500,
		'utilitySolarMonthlyCharge':0,
		'ThirdPartyRate':0.09,
		'ThirdPartyRateIncrease':3.5,
		'comUpfrontCosts':10000,
		'comMonthlyCharge':10,
		'comRate':0,
		'comRateIncrease':0,
		'greenFuelMix':12
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
