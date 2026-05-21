"""
Estimate distribution hosting-capacity expansion options and visualize upgrade scenarios
for additional DER adoption.
"""

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
from omf.solvers import pysam

# Model metadata
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# Delete output file every run if it exists
	outData = {}
	# Model operations goes here.
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	year = int( inputDict['year'] )
	sys_design = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_aggregated_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	if requestSuccess:
		pvwatts_model, pvwatts_data = pysam.run_pvwatts(modelDir=modelDir, sys_design=sys_design, dataFile="output_aggregated_data.csv")
	else:
		raise Exception("hostingExpansion.py: API request 1 Failed")

	# For Max Solar - Set tilt = latitude
	inputDict['tilt'] = lat
	sys_design_max = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes_clearsky = ['clearsky_dhi', 'clearsky_dni', 'clearsky_ghi']
	nrlAPIResponse_clearsky = weather.nrl_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes_clearsky, filename=Path(modelDir,"output_aggregated_clearsky_data.csv"))
	requestSuccess = True if nrlAPIResponse_clearsky.status_code == 200 else False
	if requestSuccess:
		maxSolar_model, maxSolar_data = pysam.run_pvwatts_historical_max(modelDir=modelDir, sys_design=sys_design_max, dataFile="output_aggregated_clearsky_data.csv")
	else:
		raise Exception("hostingExpansion.py: API request 2 Failed")

	#downlineload_df = hostingCapacity.run_downlineLoadAlgorithm(modelDir=modelDir, inputDict=inputDict, outData=outData)
	amiData = pd.read_csv( Path(modelDir, inputDict["AmiDataFileName"]) )
	full_df = pd.DataFrame({
    'hour': pvwatts_data.index,
    'total_load': amiData.iloc[:, 1:].sum(axis=1)*1000,
		'pysam_ac_watts': pvwatts_data['ac'].values,
		'dc_nameplate_w': float(inputDict["systemCapacity"])*1000, # Convert kW to W 
		'max_solar_ac_watts': maxSolar_data['ac'].values
	})
	full_df.to_csv(Path(modelDir, "output_LoadvsPySAM.csv"), index=False)
	scatterFigure = px.line(full_df, x='hour', y=['total_load','pysam_ac_watts', 'dc_nameplate_w', 'max_solar_ac_watts'])
	scatterFigure.update_traces(mode='lines')
	scatterFigure.update_traces(selector=dict(name='total_load'), name='Total Load (W)', line=dict(color='blue', width=2))
	scatterFigure.update_traces(selector=dict(name='pysam_ac_watts'), name='Solar Output (W)', line=dict(color='green', width=2))
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
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
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
