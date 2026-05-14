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
from omf.solvers import pysam

# Model metadata:
tooltip = "The pvWatts model runs the NLR PySAM pvWattsv8 tool for quick estimation of solar panel output."
modelName, template = __neoMetaModel__.metadata(__file__)

def work(modelDir, inputDict):
	simStartDate = inputDict["simStartDate"]
	start = pd.to_datetime(inputDict["simStartDate"])
	# lat/long get checked in nrl_get_nsrdb_data
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )

	# parameter validation
	sys_design = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	# We need DNI, DHI, GHI, windspeed, and temp
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_tmy", longitude=long, latitude=lat, year="tmy", api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_tmy_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		setYear = simStartDate[0:4]
		pvwatts_model, results_df = pysam.run_pvwatts(modelDir, sys_design=sys_design, dataFile="output_tmy_data.csv", setYear=True, year=setYear)
	else:
		raise Exception("pvwatts.py: API request failed")

	outData = {}
	# Geodata output.
	outData['latitude'] = pvwatts_model.Outputs.lat
	outData['longitude'] = pvwatts_model.Outputs.lon
	outData['elev'] = pvwatts_model.Outputs.elev
	
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
		"simStartDate": "2013-04-01",
		"simLengthUnits": "hours",
		"simLength": "100",
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
