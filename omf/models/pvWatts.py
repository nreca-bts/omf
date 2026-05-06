''' Calculate solar photovoltaic system output using PySAM PVWattsv8. '''

import shutil, datetime
from os.path import join as pJoin
import numpy as np
import requests
from pathlib import Path

# OMF imports
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf import weather

# Model metadata:
tooltip = "The pvWatts model runs the NLR PySAM pvWattsv8 tool for quick estimation of solar panel output."
modelName, template = __neoMetaModel__.metadata(__file__)

def _pysam_sysDesignSetup(inputDict: dict, lat: float, long: float) -> dict:
	'''
	Helper function to set up the system design parameters for the PySAM pvWattsv8 model.
	Reference hostingExpansion for another example of running a PySAM model without using pvwatts.new()

	Parameters:
		inputDict (dict)
		- Required keys:
			- latitude
			- longitude
			- array_type
			- losses
			- system_capacity
			- azimuth - Required if array_type < 4 (not 2-axis tracking)
			- tilt - Required if array_type < 4 (not 2-axis tracking)
	Returns:
		sys_design (dict): A dictionary containing the system design parameters for PySAM pvWattsv8
	'''

	# Values from inputDict
	array_type = int( inputDict.get('trackingMode', 2))
	if not (0 <= array_type <= 4):
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: trackingMode must be an integer between 0 and 4 inclusive.")
	azimuth = float( inputDict.get('azimuth', 180.0))
	if not (0 <= azimuth <= 360) and array_type < 4:
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: azimuth must be between 0 and 360 degrees.")
	inv_eff = float( inputDict.get('inverterEfficiency', 96))
	if not (90 < inv_eff <= 99.5):
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: inverterEfficiency must be between 90 and 99.5 percent.")
	losses = float( inputDict.get('losses', 15.53)) # DC system losses [%] - 15.53 is an OMF Default
	if not (-5 <= losses <= 99):
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: losses must be between -5 and 99 percent.")
	rotlim = float( inputDict.get('rotlim', 45))
	if not (0 <= rotlim <= 360):
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: rotlim must be between 0 and 360 degrees.")
	systemSize = int( inputDict.get('systemSize', inputDict.get('systemCapacity', 10)))
	if systemSize <= 0:
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: systemSize must be a positive integer.")
	tilt = float( inputDict.get('tilt', 45))
	if not (0 <= tilt <= 90) and array_type < 4:
		raise ValueError("pvwatts.py _pysam_sysDesignSetup: tilt must be between 0 and 90 degrees.")

	# OMF Defaults not in inputDict
	module_type = 2.0
	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": array_type,
						"azimuth": azimuth,
						"inv_eff": inv_eff,
						"losses": losses,
						"rotlim": rotlim,
						"module_type": module_type,
						"system_capacity": systemSize,
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
	return sys_design

def run_pvwatts_tmy(modelDir, inputDict):
	# lat/long get checked in nrl_get_nsrdb_data
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )

	# parameter validation
	sys_design = _pysam_sysDesignSetup(inputDict, lat, long)
	# We need DNI, DHI, GHI, windspeed, and temp
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_tmy", longitude=long, latitude=lat, year="tmy", api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_tmy_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		simStartDate = inputDict["simStartDate"]
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
		if bool(inputDict.get('setYear'))	 == True:
			datetime_components_dict = {
				'year': simStartDate[0:4],
				'month': wind_data['Month'],
				'day': wind_data['Day'],
				'hour': wind_data['Hour'],
				'minute': wind_data['Minute'],
			}
		else:
			datetime_components_dict = {
				'year': wind_data["Year"],
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
	else:
		raise Exception("pvwatts.py: API request failed")

	outData = {}
	# Geodata output.
	outData['latitude'] = pvwatts_model.Outputs.lat
	outData['longitude'] = pvwatts_model.Outputs.lon
	outData['elev'] = pvwatts_model.Outputs.elev
	gh = np.array( pvwatts_model.Outputs.gh, dtype=float)
	poa = np.array( pvwatts_model.Outputs.poa, dtype=float)
	dn = np.array( pvwatts_model.Outputs.dn, dtype=float)
	df = np.array( pvwatts_model.Outputs.df, dtype=float)
	tamb = np.array( pvwatts_model.Outputs.tamb, dtype=float)
	tcell = np.array( pvwatts_model.Outputs.tcell, dtype=float)
	wspd = np.array( pvwatts_model.Outputs.wspd, dtype=float)
	ac = np.array( pvwatts_model.Outputs.ac, dtype=float)
	results_df = pd.DataFrame(
		{'timestamp': wind_data.index, 'gh': gh, 'poa': poa, 'dn': dn, 'df': df, 'tamb': tamb, 'tcell': tcell, 'wspd': wspd, 'ac': ac},
		columns=['timestamp', 'gh', 'poa', 'dn', 'df', 'tamb', 'tcell', 'wspd', 'ac']
	)
	results_df["timestamp"] = pd.to_datetime(results_df["timestamp"])
	results_df = results_df.set_index( results_df["timestamp"])
	results_df = results_df.drop( columns=["timestamp"] )
	return pvwatts_model, results_df

def work(modelDir, inputDict):
	outData = {}
	simStartDate = inputDict["simStartDate"]
	start = pd.to_datetime(inputDict["simStartDate"])
	pvwatts_model, results_df = run_pvwatts_tmy(modelDir, inputDict)
	
	thirty_minute_start = pd.to_timedelta( 30, unit="minute") # The NSRDB data starts at 00:30 so everything is off by 30 minutes - that's what this is for.
	start = start + thirty_minute_start
	time_passed = pd.to_timedelta( int(inputDict['simLength']), unit=inputDict['simLengthUnits'])
	end = start + time_passed
	sim_df = results_df.loc[start:end]
	simLengthUnits = inputDict['simLengthUnits']
	if simLengthUnits == "minutes":
			freq = "t"
	elif simLengthUnits == "hours":
			freq = "h"
	elif simLengthUnits == "days":
			freq = "d"
	else:
			raise Exception()
	agg_df = sim_df.resample(freq).sum(numeric_only=True)
	simLengthUnits = inputDict.get("simLengthUnits","")
	startDateTime = simStartDate + " 00:00:00 UTC"
	outData["timeStamps"] = [ datetime.datetime.strftime(
	datetime.datetime.strptime(startDateTime[0:19],"%Y-%m-%d %H:%M:%S") + 
	datetime.timedelta(**{simLengthUnits:x}),"%Y-%m-%d %H:%M:%S") + " UTC" for x in range(int(inputDict["simLength"]))]

	# Weather output.
	outData["climate"] = {}
	outData["climate"]["Plane of Array Irradiance (W/m^2)"] = agg_df["poa"].tolist() if "poa" in agg_df else []
	outData["climate"]["Global Horizonal Irradiance (W/m^2)"] = agg_df["gh"].tolist() if "gh" in agg_df else []
	outData["climate"]["Beam Normal Irradiance (W/m^2)"] = agg_df["dn"].tolist() if "dn" in agg_df else []
	outData["climate"]["Diffuse Irradiance (W/m^2)"] = agg_df["df"].tolist() if "df" in agg_df else []
	outData["climate"]["Ambient Temperature (F)"] = agg_df["tamb"].tolist() if "tamb" in agg_df else []
	outData["climate"]["Cell Temperature (F)"] = agg_df["tcell"].tolist() if "tcell" in agg_df else []
	outData["climate"]["Wind Speed (m/s)"] = agg_df["wspd"].tolist() if "wspd" in agg_df else []
	# Power generation.
	outData["Consumption"] = {}
	outData["Consumption"]["Power"] = [x for x in agg_df["ac"].tolist() ]
	outData["Consumption"]["Losses"] = [0 for x in agg_df["ac"].tolist() ]
	outData["Consumption"]["DG"] = agg_df["ac"].tolist() if "ac" in agg_df else []
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def runtimeEstimate(modelDir):
	''' Estimated runtime of model in minutes. '''
	return 0.5

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"modelType": modelName,
		"longitude": "-94.67",
		"latitude": "39.10",
		"azimuth":"180.0",
		"rotlim": "45.0",
		"trackingMode": "2",
		"inverterEfficiency":"97.5",
		"systemSize": "10",
		"inverterSize": "8",
		"runTime": "",
		"tilt":"45",
		"simStartDate": "2013-01-01",
		"simLengthUnits": "days",
		"simLength": "365",
		"setYear": "True"
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
