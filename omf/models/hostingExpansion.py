"""
Estimate distribution hosting-capacity expansion options
& visualize upgrade scenarios for additional DER adoption.
"""

# Python Imports
import shutil
import datetime
import json
import os
import pandas as pd
from pathlib import Path
import logging
import plotly.utils as pu
import plotly.graph_objects as go

# OMF imports
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf import weather
from omf.solvers import opendss
from omf.solvers import pysam

# Model metadata
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False


def checkCircuitSolar(modelDir, inputDict: dict):
	'''
	Reviews any pvsystems or batteries in the circuit and sums up their kW values
	'''
	returningKW = 0
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	inputDict['feederName1'] = feederName[:-4]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	pvsystems = [x for x in tree if x.get('object', 'N/A').startswith('pvsystem.')]
	batteries = [x for x in tree if x.get('object', 'N/A').startswith('battery.')]
	if len(pvsystems) == 0 and len(batteries) == 0:
		return returningKW
	if len(pvsystems) != 0:
		kwFromPV = [x['kw'] for x in pvsystems if 'kw' in x]
		for item in kwFromPV:
			returningKW += float(item)
	if len(batteries) != 0:
		kwFromBattery = [x['kw'] for x in batteries if 'kw' in x]
		for item in kwFromBattery:
			returningKW += float(item)
	return returningKW


def work(modelDir, inputDict: dict) -> dict:
	''' Run the model in its directory. '''
	# Delete output file every run if it exists
	outData = {}
	# Model operations goes here.
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	year = int( inputDict['year'] )
	sys_design = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nlr_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_aggregated_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	if requestSuccess:
		pvwatts_model, pvwatts_data = pysam.run_pvwatts(
			modelDir=modelDir,
			sys_design=sys_design,
			dataFile="output_aggregated_data.csv"
		)
	else:
		raise Exception("hostingExpansion.py: API request 1 Failed")
	# For Max Solar - Set tilt = latitude
	inputDict['tilt'] = lat
	sys_design_max = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes_clearsky = ['clearsky_dhi', 'clearsky_dni', 'clearsky_ghi']
	nrlAPIResponse_clearsky = weather.nlr_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes_clearsky, filename=Path(modelDir,"output_aggregated_clearsky_data.csv"))
	requestSuccess = True if nrlAPIResponse_clearsky.status_code == 200 else False
	if requestSuccess:
		maxSolar_model, maxSolar_data = pysam.run_pvwatts_historical_max(modelDir=modelDir, sys_design=sys_design_max, dataFile="output_aggregated_clearsky_data.csv")
	else:
		raise Exception("hostingExpansion.py: API request 2 Failed")
	amiData = pd.read_csv( Path(modelDir, inputDict["AmiDataFileName"]) )
	# Determine the length of available data (use load data length, should be max 1 year)
	data_length = len(amiData)
	# Slice solar data to match load data length
	pvwatts_data_sliced = pvwatts_data.iloc[:data_length]
	maxSolar_data_sliced = maxSolar_data.iloc[:data_length]
	# Get existing storage capacity on circuit
	storage_output = checkCircuitSolar(modelDir, inputDict)
	full_df = pd.DataFrame({
			'hour': pvwatts_data_sliced.index,
			'total_load': amiData.iloc[:, 1:].sum(axis=1)*1000,  # Convert kW to W
			'pysam_ac_watts': pvwatts_data_sliced['ac'].values,
			'storage_output_w': storage_output * 1000,  # Convert kW to W
			'dc_nameplate_w': float(inputDict["systemCapacity"])*1000,  # kW to W
			'max_solar_ac_watts': maxSolar_data_sliced['ac'].values
	})
	full_df.to_csv(Path(modelDir, "output_LoadvsPySAM.csv"), index=False)
	scatterFigure = go.Figure()
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['storage_output_w'],
		name='Storage Output (W)',
		fill='tozeroy',
		fillcolor='rgba(0, 200, 0, 0.3)',
		line=dict(color='darkgreen', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['pysam_ac_watts'] + full_df['storage_output_w'],
		name='Solar Output (W)',
		line=dict(color='darkgreen', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['total_load'],
		name='Total Load (W)',
		line=dict(color='blue', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['dc_nameplate_w'],
		name='DC Nameplate Capacity (W)',
		line=dict(color='red', width=2, dash='dash'),
		mode='lines'
	))
	# Add max solar output
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['max_solar_ac_watts'] + full_df['storage_output_w'],
		name='Max Solar Output (W)',
		line=dict(color='darkgreen', width=2, dash='dash'),
		mode='lines'
	))
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
		"user": "admin",
		"modelType": modelName,
		"created": str(datetime.datetime.now()),
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
	modelLoc = Path(__neoMetaModel__._omfDir, "data", "Model", "admin", "Automated Testing of " + modelName)
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
