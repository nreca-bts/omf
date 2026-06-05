"""
Wrap NLR PySAM photovoltaic, wind, and weather-data workflows for OMF renewable-energy
models.
"""

# Python Imports
import pandas as pd
from pathlib import Path
import json
import PySAM.Pvwattsv8 as pvwatts
import numpy as np
import os
import requests

# OMF Imports
from omf import omfDir
from omf import weather

NLR_KEY = "rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56"

def _pysam_sysDesignSetup(inputDict: dict, lat: float, long: float) -> dict:
	'''
	Helper function to set up the system design parameters for the PySAM pvWattsv8 model.

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
		raise ValueError("_pysam_sysDesignSetup: trackingMode must be an integer between 0 and 4 inclusive.")
	azimuth = float( inputDict.get('azimuth', 180.0))
	if not (0 <= azimuth <= 360) and array_type < 4:
		raise ValueError("_pysam_sysDesignSetup: azimuth must be between 0 and 360 degrees.")
	inv_eff = float( inputDict.get('inverterEfficiency', 96))
	if not (90 < inv_eff <= 99.5):
		raise ValueError("_pysam_sysDesignSetup: inverterEfficiency must be between 90 and 99.5 percent.")
	losses = float( inputDict.get('losses', 15.53)) # DC system losses [%] - 15.53 is an OMF Default
	if not (-5 <= losses <= 99):
		raise ValueError("_pysam_sysDesignSetup: losses must be between -5 and 99 percent.")
	rotlim = float( inputDict.get('rotlim', 45))
	if not (0 <= rotlim <= 360):
		raise ValueError("_pysam_sysDesignSetup: rotlim must be between 0 and 360 degrees.")
	systemSize = int( inputDict.get('systemSize', inputDict.get('systemCapacity', 10)))
	if systemSize <= 0:
		raise ValueError("_pysam_sysDesignSetup: systemSize must be a positive integer.")
	tilt = float( inputDict.get('tilt', 45))
	if not (0 <= tilt <= 90) and array_type < 4:
		raise ValueError("_pysam_sysDesignSetup: tilt must be between 0 and 90 degrees.")

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

def run_pvwatts(modelDir, sys_design: dict, dataFile: str = "solar_resource_file.csv", setYear: bool=False, year: str=None) -> tuple:
	'''

	Runs PySAM PvWattsv8 with the given system design and solar resource data.

	parameters:
	- modelDir (str): The directory where the model is located.
	- sys_design is the output of _pysam_sysDesignSetup.
		- This is dictated from PySAM PvWattsv8
	- dataFile (str): Name of CSV File containing the solar resource data. This is the output of weather.nrl_get_nsrdb_data() using either goes_tmy or goes_aggregated
	  - nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_tmy", longitude=long, latitude=lat, year="tmy", api_key="", attributes=attributes, filename=Path(modelDir,"output_tmy_data.csv"))
	  - attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
		- These attributes will be expected.

	- setYear (bool): TMY is a bunch of years of data put together - if you want to set the year to be a specific year, set this to True
	- year (str): If setYear is True, this is the year to set the data to.

	returns:
	- pvwatts_model: The PySAM pvWattsv8 model object.
	- results_df: A pandas DataFrame containing the results of the simulation.
		- Contains the following columns:
			- timestamp: The date and time of the data point.
			- gh: Global Horizontal Radiation (W/m^2).
			- poa: Plane of Array Irradiance (W/m^2).
			- dn: Direct Normal Irradiance (W/m^2).
			- df: Diffuse Horizontal Irradiance (W/m^2).
			- tamb: Ambient Temperature (F).
			- tcell: Cell Temperature (F).
			- wspd: Wind Speed (m/s).
			- ac: AC Power Output (W).
	'''
	pvwatts_model = pvwatts.new()
	full_data = pd.read_csv(Path(modelDir, dataFile))
	metadata = full_data.iloc[0:1].copy()
	wind_data = full_data.iloc[2:].copy()
	wind_data.columns = full_data.iloc[1]
	# Validate required columns exist
	required_columns = ['DNI', 'DHI', 'GHI', 'Wind Speed', 'Temperature']
	missing_columns = [col for col in required_columns if col not in wind_data.columns]
	if missing_columns:
		raise ValueError(f"run_pvwatts: Missing required columns in dataframe: {', '.join(missing_columns)}")
	# We can snag elevation from the NSRDB Data we pulled out of the request
	# Source,Location ID,City,State,Country,Latitude,Longitude,Time Zone,Elevation
	# NSRDB,694051,-,-,-,33.21,-97.14,-6, 207 <- This 207 right here
	sys_design["Other"]["elev"] = int( metadata["Elevation"][0] )
	if setYear:
		datetime_components_dict = {
			'year': year,
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

def run_pvwatts_historical_max(modelDir, sys_design: dict, dataFile: str="solar_resource_file.csv") -> tuple:
	'''

	Runs PySAM PvWattsv8 with historical clearsky DNI/DHI/GHI data. Windspeed and temp set to 0.
	see omf hostingExpansion.py for example.

	parameters:
	- modelDir (str): The directory where the model is located.
	- sys_design is the output of _pysam_sysDesignSetup.
		- This is dictated from PySAM PvWattsv8
	- dataFile (str): Name of CSV File containing the solar resource data. This is the output of weather.nrl_get_nsrdb_data() using goes_aggregated
		- Note: Because this only uses goes_aggregated and is historical data, there is only the data for the year provided.
			  - nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year="<given year>", api_key="", attributes=attributes, filename=Path(modelDir,"output_aggregated_data.csv"))
	  		- attributes = ['clearsky_dhi', 'clearsky_dni', 'clearsky_ghi']

	returns:
	- pvwatts_model: The PySAM pvWattsv8 model object.
	- results_df: A pandas DataFrame containing the results of the simulation.
			- ac: AC Power Output (W).
			- Note: This can be modified in the future to have the same output columns as run_pvwatts. For its current use, only the ac column is available.
	'''
	pvwatts_model = pvwatts.new()
	full_data = pd.read_csv(Path(modelDir,"output_aggregated_clearsky_data.csv"))
	metadata = full_data.iloc[0:1].copy()
	wind_data = full_data.iloc[2:].copy()
	wind_data.columns = full_data.iloc[1]
	# Validate required columns exist
	required_columns = ['Clearsky DNI', 'Clearsky DHI', 'Clearsky GHI']
	missing_columns = [col for col in required_columns if col not in wind_data.columns]
	if missing_columns:
		raise ValueError(f"run_pvwatts_historical_max: Missing required columns in dataframe: {', '.join(missing_columns)}")
	# We can snag elevation from the NSRDB Data we pulled out of the request
	# Source,Location ID,City,State,Country,Latitude,Longitude,Time Zone,Elevation
	# NSRDB,694051,-,-,-,33.21,-97.14,-6, 207 <- This 207 right here
	sys_design["Other"]["elev"] = int( metadata["Elevation"][0] )
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
		'dn': [float(x) for x in wind_data['Clearsky DNI']],
		'df': [float(x) for x in wind_data['Clearsky DHI']],
		'gh': [float(x) for x in wind_data['Clearsky GHI']],
		'wspd': [0.0] * len(wind_data),
		'tdry': [0.0] * len(wind_data),
	}
	pvwatts_model.SolarResource.assign({'solar_resource_data': solar_resource_data})
	model_params = sys_design['ModelParams']
	pvwatts_model.assign(model_params)
	resource = pvwatts_model.SolarResource.export()
	# Convert and write JSON object to file
	with open( Path(modelDir, "solar_resource.json"), "w") as outfile: 
			json.dump(resource, outfile)
	pvwatts_model.execute()
	ac = np.array( pvwatts_model.Outputs.ac, dtype=float) # Watts

	results_df = pd.DataFrame(
		{'timestamp': wind_data.index, 'ac': ac},
		columns=['timestamp', 'ac']
	)
	results_df["timestamp"] = pd.to_datetime(results_df["timestamp"])
	results_df = results_df.set_index( results_df["timestamp"])
	results_df = results_df.drop( columns=["timestamp"] )
	return pvwatts_model, results_df

def nlr_pysam_getWind(modelDir, year: int, longitude: float, latitude: float) -> dict:
	'''
		'windpower-inputs.json' - windpower defaults
		'wind-turbines.json' - wind turbine data. 
	'''
	import PySAM.Windpower as wp

	wind_turbine_model = wp.new()
	testFileDir = Path(omfDir, "static", "testFiles", "weatherPulling", "nrel_windTurbineDefaults")
	# Add try here
	with open( Path(testFileDir, 'input_windpower.json'), 'r') as json_file:
		windpower_data = json.load(json_file)
		
		for k, v in windpower_data.items():
			if k != 'number_inputs':
				wind_turbine_model.value(k, v)

	nlrAPIResponse = weather.nlr_get_nsrdb_data(data_set="wind", longitude=longitude, latitude=latitude, year=year, api_key=NLR_KEY, filename="output_NLR_winddata.csv")
	requestSuccess = True if nlrAPIResponse.status_code == 200 else False

	if requestSuccess:
		wind_turbine_model.value('wind_resource_filename', str(modelDir) + '/output_NLR_winddata.csv')
	else:
		raise Exception(f"nlr_pysam_getWind: API Request Failed")
	wind_turbine_model.value('wind_resource_shear', 0.14)
	# load wind turbine parameters from JSON
	with open( Path(testFileDir, 'input_windTurbines.json'), 'r') as file:
		turbine_data = json.load(file)
	# set up wind farm for one turbine
	wind_turbine_model.value('wind_farm_xCoordinates', [ -71.25 ])
	wind_turbine_model.value('wind_farm_yCoordinates', [ 42.25 ])
	for turbine in turbine_data:
		# set wind turbine parameters
		wind_turbine_model.value('wind_turbine_rotor_diameter', turbine['rotor_diameter'])
		wind_turbine_model.value('wind_turbine_powercurve_windspeeds', turbine['wind_speeds'])
		wind_turbine_model.value('wind_turbine_powercurve_powerout',  turbine['turbine_powers'])
		wind_turbine_model.value('wind_turbine_hub_ht', turbine['hub_height'])
		# set wind farm capacity
		number_of_turbines = len(wind_turbine_model.value('wind_farm_xCoordinates'))
		farm_capacity =  number_of_turbines * turbine['rated_power']
		wind_turbine_model.value('system_capacity', farm_capacity)
		# run simulation
		wind_turbine_model.execute()
		print(turbine['name'])
		print('annual energy (kWh) = ', wind_turbine_model.Outputs.annual_energy)
		print('capacity factor = ', wind_turbine_model.Outputs.capacity_factor)
		return wind_turbine_model.Outputs

#### Cool stuff with copernicus data
## PySAM PvWatts & feedinlib for solar and wind stuff

def cds_csvToPySAMSolarData(cdsDataFile: str="output_cdsWeatherDataFull.csv") -> np.array:
	'''
		Turns one large CVS of copernicus weather data into the inputs required for pysam pvwatts 
	'''
	copernicus_df = pd.read_csv(cdsDataFile)
	copernicus_df["Timestamp"] = pd.DatetimeIndex(pd.to_datetime(copernicus_df["valid_time"], utc=True))
	copernicus_df = copernicus_df.set_index("Timestamp")
	# DNI - Direct Normal
	# GHI - Global Horizontal
	# DHI - Diffuse Horizontal

	from pvlib.irradiance import erbs
	copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"] = (copernicus_df.ssrd / 3600.0)
	copernicus_df["dirhi"] = (copernicus_df.fdir / 3600.0)
	copernicus_df["CDS Diffusal Horizonal Irradiance (DHI) (W/m²_irr)"] = (copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"] - copernicus_df.dirhi)
	dni_data = erbs(copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"], zenith=30, datetime_or_doy=copernicus_df.index )
	copernicus_df["CDS Direct Normal Irradiance (DNI) (W/m²_irr)"] = dni_data["dni"]
	copernicus_df["CDS Wind Speed"] = np.sqrt(copernicus_df["u10"] ** 2 + copernicus_df["v10"] ** 2)
	copernicus_df["CDS Temp"] = copernicus_df.t2m - 273.15
	# lat, long, index, year, month, day, hour, minute, DNI, DHI, GHI, winspeed, dry bulb temperature
	weather_data = np.array([
			copernicus_df.iloc[0][1],
			copernicus_df.iloc[0][2],
			copernicus_df.index,
			copernicus_df.index.year,
			copernicus_df.index.month,
			copernicus_df.index.day,
			copernicus_df.index.hour,
			copernicus_df.index.minute,
			copernicus_df['CDS Direct Normal Irradiance (DNI) (W/m²_irr)'], #5 = dn
			copernicus_df["CDS Diffusal Horizonal Irradiance (DHI) (W/m²_irr)"],
			copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"],
			copernicus_df["CDS Wind Speed"],
			copernicus_df['CDS Temp']
	])
	return weather_data

def cds_pySAM_getSolar(cdsDataFile):
	'''

	uses PySAM.pvWattsv8 to turn Copernicus data from Climate Data Store

	Inputs:
		cdsDataFile - comes from omf weather.cds_processWeatherData first argument

	weather_data has very specific formatting:
	# lat, long, first index, year, month, day, hour, minute, DNI, DHI, GHI, windspeed, dry bulb temperature

	'''
	weather_data = cds_csvToPySAMSolarData(cdsDataFile=cdsDataFile)

		# required argument for pysam pvwatts, this is default formatting that works for the copernicus data
	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": 2.0,
						"azimuth": 180.0,
						"dc_ac_ratio": 1.08,
						"gcr": 0.592,
						"inv_eff": 97.5,
						"losses": 15.53,
						"module_type": 2.0,
						"system_capacity": 720,
						"tilt": 0.0
				},
				"SolarResource": {
				}
		},
		"Other": {
				"lat": weather_data[0],
				"lon": weather_data[1],
				"elev": 1829
		}
	}

	model_params = sys_design['ModelParams']
	elev = sys_design['Other']['elev']
	lat = sys_design['Other']['lat']
	lon = sys_design['Other']['lon']
	tz = (weather_data[2])[0].utcoffset().total_seconds()/60/60
	system_model = pvwatts.new()
	system_model.assign(model_params)
	solar_resource_data = {
		'tz': tz, # timezone
		'elev': elev, # elevation
		'lat': lat, # latitude
		'lon': lon, # longitude
		'year': tuple(weather_data[3]), # year
		'month': tuple(weather_data[4]), # month
		'day': tuple(weather_data[5]), # day
		'hour': tuple(weather_data[6]), # hour
		'minute': tuple(weather_data[7]), # minute
		'dn': tuple(weather_data[8]), # direct normal irradiance
		'df': tuple(weather_data[9]), # diffuse irradiance
		'gh': tuple(weather_data[10]), # global horizontal irradiance
		'wspd': tuple(weather_data[11]), # windspeed
		'tdry': tuple(weather_data[12]) # dry bulb temperature
		}
	system_model.SolarResource.assign({'solar_resource_data': solar_resource_data})
	system_model.AdjustmentFactors.assign({'adjust_constant': 0})
	resource = system_model.SolarResource.export()
	# Convert and write JSON object to file
	with open("solar_resource.json", "w") as outfile: 
			json.dump(resource, outfile)
	system_model.execute()
	out = system_model.Outputs.export()
	ac = np.array(out['ac']) / 1000
	dc = np.array(out['dc']) / 1000
	ac_dc_df = pd.DataFrame({"ac": ac, "dc": dc}, columns = ['ac','dc'])
	ac_dc_df = ac_dc_df.set_index((weather_data[2]).copy())
	return ac_dc_df

def _format_windpowerlib(ds):
    """
    Code from feedinlib
    Format dataset to dataframe as required by the windpowerlib's ModelChain.

    The windpowerlib's ModelChain requires a weather DataFrame with time
    series for

    - wind speed `wind_speed` in m/s,
    - temperature `temperature` in K,
    - roughness length `roughness_length` in m,
    - pressure `pressure` in Pa.

    The columns of the DataFrame need to be a MultiIndex where the first level
    contains the variable name as string (e.g. 'wind_speed') and the second
    level contains the height as integer in m at which it applies (e.g. 10,
    if it was measured at a height of 10 m).

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset with ERA5 weather data.

    Returns
    --------
    pd.DataFrame
        Dataframe formatted for the windpowerlib.

    """

    # compute the norm of the wind speed
    ds["wnd100m"] = np.sqrt(ds["u100"] ** 2 + ds["v100"] ** 2).assign_attrs(
        units=ds["u100"].attrs["units"], long_name="100 metre wind speed"
    )

    ds["wnd10m"] = np.sqrt(ds["u10"] ** 2 + ds["v10"] ** 2).assign_attrs(
        units=ds["u10"].attrs["units"], long_name="10 metre wind speed"
    )
    # drop not needed variables
    windpowerlib_vars = ["wnd10m", "wnd100m", "sp", "t2m", "fsr"]
    ds_vars = list(ds.variables)
    drop_vars = [
        _
        for _ in ds_vars
        if _ not in windpowerlib_vars + ["latitude", "longitude", "time"]
    ]
    ds = ds.drop(drop_vars)
    # convert to dataframe
    df = ds.to_dataframe().reset_index()
    # the time stamp given by ERA5 for mean values (probably) corresponds to
    # the end of the valid time interval; the following sets the time stamp
    # to the middle of the valid time interval
    df['valid_time'] = pd.to_datetime(df['valid_time'])
    df["time"] = df["valid_time"] - pd.Timedelta(minutes=60)

    df.set_index(["time", "latitude", "longitude"], inplace=True)
    df.sort_index(inplace=True)
    df = df.tz_localize("UTC", level=0)

    # reorder the columns of the dataframe
    df = df[windpowerlib_vars]

    # define a multiindexing on the columns
    midx = pd.MultiIndex(
        levels=[
            ["wind_speed", "pressure", "temperature", "roughness_length"],
            # variable
            [0, 2, 10, 100],  # height
        ],
        codes=[
            [0, 0, 1, 2, 3],  # indexes from variable list above
            [2, 3, 0, 1, 0],  # indexes from the height list above
        ],
        names=["variable", "height"],  # name of the levels
    )
    df.columns = midx
    df.dropna(inplace=True)
    return df

def cds_windpowerlib_getWind(weather_dataset):
	'''
	Uses feednilib windpowerlib instead of PySAM Wind Turbines to turn copernicus data into wind outputs

	'''
	from omf.solvers import feedinlib_custom

	bergey_turbine_data = {
		'nominal_power': 15600, # in W
		'hub_height': 24, # in meters  
		'power_curve': pd.DataFrame( # https://github.com/wind-python/windpowerlib <-- for info on adding custom loadshapes 
			data={'value': [p * 1000 for p in [0, 0, 0.108, 0.679, 2.074, 3.824, 6.089, 8.500, 11.265, 13.664, 15.612, 16.876, 18.212, 19.096, 20.355, 20.611, 19.687]],  # kW -> W
			'wind_speed': [1.0, 2.01, 2.99, 4.01, 5.00, 6.00, 7.00, 8.00, 9.00, 9.99, 11.01, 11.97, 12.99, 13.99, 15.00, 15.97, 16.47]})  # in m/s
	}
	wind_turbine = feedinlib_custom.powerplants.WindPowerPlant(**bergey_turbine_data)
	windpowerlib_df = _format_windpowerlib(weather_dataset)  
	windpowerlib_df = windpowerlib_df.droplevel([1,2])
	wind_output_ds = wind_turbine.feedin(
		weather = windpowerlib_df,
		density_correction = True,
		scaling = 'nominal_power',
	)
	wind_output_ds.reset_index(drop=True, inplace=True)
	return wind_output_ds
