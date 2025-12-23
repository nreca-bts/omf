''' Calculate solar photovoltaic system output using PVWatts. '''

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
tooltip = "The pvWatts model runs the NREL pvWatts tool for quick estimation of solar panel output."
modelName, template = __neoMetaModel__.metadata(__file__)

def work(modelDir, inputDict):

	### Get inputs for system design parameters
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	azimuth = float( inputDict['azimuth'] )
	rotlim = float( inputDict['rotlim'] )
	inv_eff = float( inputDict['inverterEfficiency'] )
	losses = float( inputDict['losses'] )
	sys_cap = float( inputDict['systemCapacity'] )
	tilt = float( inputDict['tilt'] )
	start = pd.to_datetime(inputDict["simStartDate"])
	trackingMode = int ( inputDict["trackingMode"] )

	### Set up system design parameter dict for PySAM pvWatts Model
	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": trackingMode,
						"azimuth": azimuth,
						"inv_eff": inv_eff,
						"losses": losses,
						"rotlim": rotlim,
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

		outData = {}
		# Geodata output.
		outData['latitude'] = pvwatts_model.Outputs.lat
		outData['longitude'] = pvwatts_model.Outputs.lon
		outData['elev'] = pvwatts_model.Outputs.elev

		thirty_minute_start = pd.to_timedelta( 30, unit="minute")
		start = start + thirty_minute_start
		time_passed = pd.to_timedelta( int(inputDict['simLength']), unit=inputDict['simLengthUnits'])
		end = start + time_passed

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
		sim_df = results_df.loc[start:end]

		simLengthUnits = inputDict['simLengthUnits']
		if simLengthUnits == "minutes":
				freq = "T"
		elif simLengthUnits == "hours":
				freq = "H"
		elif simLengthUnits == "days":
				freq = "D"
		else:
				raise Exception()
		
		agg_df = sim_df.resample(freq).sum(numeric_only=True)
		simLengthUnits = inputDict.get("simLengthUnits","")
		simStartDate = inputDict["simStartDate"]
		startDateTime = simStartDate + " 00:00:00 UTC"
		outData["timeStamps"] = [datetime.datetime.strftime(
		datetime.datetime.strptime(startDateTime[0:19],"%Y-%m-%d %H:%M:%S") + 
		datetime.timedelta(**{simLengthUnits:x}),"%Y-%m-%d %H:%M:%S") + " UTC" for x in range(int(inputDict["simLength"]))]

		# Weather output.
		outData["climate"] = {}
		outData["climate"]["Plane of Array Irradiance (W/m^2)"] = agg_df["poa"].tolist() if "poa" in agg_df else []
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
		"longitude": "-97.1292",
		"latitude": "33.2164",
		"azimuth":"180.0",
		"rotlim": "45.0",
		"trackingMode": "2",
		"inverterEfficiency":"97.5",
		"losses": "15.53",
		"systemCapacity": "750",
		"systemSize": "10",
		"inverterSize": "8",
		"runTime": "",
		"tilt":"45",
		"simStartDate": "2023-07-01",
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
