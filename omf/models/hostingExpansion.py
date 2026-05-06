''' A model skeleton for future models: Calculates the sum of two integers. '''

import warnings
# warnings.filterwarnings("ignore")

import shutil, datetime
from pathlib import Path
import numpy as np
import plotly.utils as pu
import plotly.express as px

# OMF imports
from omf import feeder
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf import weather
from omf.models import hostingCapacity
from omf.solvers import opendss

# Model metadata
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def run_pvwatts(modelDir, inputDict, attributes=[], modified=False):
	# Gather up defaults

	systemCapacity = int( inputDict["systemCapacity"] )
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	azimuth = float( inputDict['azimuth'] )
	tilt = float( inputDict['tilt'] )
	if modified == True:
		tilt = int(lat)
	else:
		tilt = float( inputDict['tilt'] )
	losses = float( inputDict['losses'] )
	year = int( inputDict['year'] )

	sys_design = {
		"ModelParams": {
				"SystemDesign": {
						"array_type": 2.0,
						"azimuth": azimuth,
						"losses": losses,
						"module_type": 2.0,
						"system_capacity": systemCapacity,
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

	nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_aggregated_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False

	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		import PySAM.Pvwattsv8 as pvwatts
		pvwatts_model = pvwatts.new()
		full_data = pd.read_csv(Path(modelDir,"output_aggregated_data.csv"))
		metadata = full_data.iloc[0:1].copy()
		wind_data = full_data.iloc[2:].copy()
		wind_data.columns = full_data.iloc[1]
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
		if modified == True:
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
		else:
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
		raise Exception("model pvwatts.py API request failed")
	
	ac = np.array( pvwatts_model.Outputs.ac, dtype=float) # Watts

	results_df = pd.DataFrame(
		{'timestamp': wind_data.index, 'ac_watts': ac},
		columns=['timestamp', 'ac_watts']
	)
	results_df["timestamp"] = pd.to_datetime(results_df["timestamp"])
	results_df = results_df.set_index( results_df["timestamp"])
	results_df = results_df.drop( columns=["timestamp"] )
	return results_df

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# Delete output file every run if it exists
	outData = {}		
	# Model operations goes here.

	pvwatts_data = run_pvwatts(modelDir=modelDir, inputDict=inputDict, attributes=['dni,dhi,ghi,wind_speed,air_temperature'])
	maxSolar_data = run_pvwatts(modelDir=modelDir, inputDict=inputDict, attributes=['clearsky_dhi', 'clearsky_dni', 'clearsky_ghi'], modified=True)
	#downlineload_df = hostingCapacity.run_downlineLoadAlgorithm(modelDir=modelDir, inputDict=inputDict, outData=outData)
	amiData = pd.read_csv( Path(modelDir, inputDict["AmiDataFileName"]) )
	full_df = pd.DataFrame({
    'hour': pvwatts_data.index,
    'total_load': amiData.iloc[:, 1:].sum(axis=1)*1000,
		'ac_watts': pvwatts_data['ac_watts'].values,
		'dc_nameplate_w': float(inputDict["systemCapacity"])*1000, # Convert kW to W 
		'max_solar_ac_watts': maxSolar_data['ac_watts'].values
	})
	full_df.to_csv(Path(modelDir, "output_LoadvsPySAM.csv"), index=False)
	scatterFigure = px.line(full_df, x='hour', y=['total_load','ac_watts', 'dc_nameplate_w', 'max_solar_ac_watts'])
	scatterFigure.update_traces(mode='lines')
	scatterFigure.update_traces(selector=dict(name='total_load'), name='Total Load (W)', line=dict(color='blue', width=2))
	scatterFigure.update_traces(selector=dict(name='ac_watts'), name='Solar Output (W)', line=dict(color='green', width=2))
	scatterFigure.update_traces(selector=dict(name='dc_nameplate_w'), name='DC Nameplate Capaciy (W)', line=dict(color='red', width=2, dash='dash'))
	scatterFigure.update_traces(selector=dict(name='max_solar_ac_watts'), name='Max Solar Output (W)', line=dict(color='darkgreen', width=2, dash='dash'))
	scatterFigure.update_layout(
    title=None,
		xaxis_title=None,
		yaxis_title=None,
		hovermode='x unified',
		legend={
      "orientation": "h",
      "yanchor": "bottom",
      "y": 1.02,
      "xanchor": "right",
      "x": 1
		}
	)
		

	outData['scatterFigure'] = json.dumps( scatterFigure, cls=pu.PlotlyJSONEncoder )
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	opendss.dssConvert.treeToDss(tree, Path(modelDir, 'circuit.dss'))
	
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	amiFileName = "input_mackelroy.csv"
	amiFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', amiFileName)
	ScadaFileName = "input_ScadaData.csv"
	ScadaFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', ScadaFileName)
	derPipelineFileName = "input_derPipelineData.csv"
	derPipelineFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', derPipelineFileName)
	newInterconnFileName = "input_newInterconnData.csv"
	newInterconnFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', newInterconnFileName)
	
	defaultInputs = {
		"user" : "admin",
		"modelType": modelName,
		"created":str(datetime.datetime.now()),
		"feederName1": 'iowa240.clean.dss',
		"AmiUIDisplay": amiFileName,
		"AmiDataFileName": amiFileName,
		"ScadaUIDisplay": ScadaFileName,
		"ScadaDataFileName": ScadaFileName,
		"derPipelineUIDisplay": derPipelineFileName,
		"derPipelineDataFileName": derPipelineFileName,
		"newInterconnUIDisplay": newInterconnFileName,
		"newInterconnDataFileName": newInterconnFileName,
		"longitude": "-94.67",
		"latitude": "39.10",
		"year": "2024",
		"azimuth": "180.0",
		"systemCapacity": 800,
		"tilt": 45,
		"losses": 15.5,
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	# Copy files from the test directory ( or respective places ) and put them in the model for use
	try:
		shutil.copyfile(
			Path(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'),
			Path(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile( amiFilePath, Path(modelDir, amiFileName) )
		shutil.copyfile( ScadaFilePath, Path(modelDir, ScadaFileName) )
		shutil.copyfile( derPipelineFilePath, Path(modelDir, derPipelineFileName))
		shutil.copyfile( newInterconnFilePath, Path(modelDir, newInterconnFileName))
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _tests():
	# Location
	modelLoc = Path(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
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
