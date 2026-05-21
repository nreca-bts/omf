"""
The hostingCapacity model calculates hosting capacity for DERs.
"""
import shutil
import plotly as py
import plotly.express as px
import pandas as pd
import numpy as np
from pathlib import Path
import time
import networkx as nx

# OMF imports
import omf
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers import opendss
from omf.solvers import mohca_cl

# Model metadata:
tooltip = "Calculate hosting capacity using AMI-based or model-based methods."
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def convertTime( seconds ):
	"""
	Convert time data between solver or OMF representations.
	"""
	milliseconds = seconds * 1000
	# toCalculate hours, minutes, seconds, and milliseconds
	hours, remainder = divmod(milliseconds, 3600000)
	minutes, remainder = divmod(remainder, 60000)
	seconds, milliseconds = divmod(remainder, 1000)
	return "{:02d}:{:02d}:{:02d}.{:03d}".format(int(hours), int(minutes), int(seconds), int(milliseconds))

def hostingCapacityMap( modelDir, inputDict, outData ):
	"""
	Perform hosting capacity map processing for the hosting capacity model.
	"""
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	pathToOmd = Path(modelDir, feederName)
	starting_omd = json.load(open(pathToOmd)) 
	# Starting there are no warnings
	outData['mapWarningFlag'] = False
	outData['hideMap'] = False
	if inputDict['runAmiAlgorithm'] == 'on':
		modelFreeData = Path(modelDir, 'output_modelFreeFull.csv')
		modelFreeData_df = pd.read_csv(modelFreeData)
		with open(pathToOmd) as f:
			omd = json.load(f)
		omdTreeBuses = []
		for k, v in omd['tree'].items():
			if v['object'] == 'bus':
				omdTreeBuses.append(v['name'])
		modelFreeBuses = modelFreeData_df['busname'].unique()
		# Finding the buses from mohca thats in the circuit. this is what we will color
		modelFreeBusesInOmdFile = list(set(modelFreeBuses).intersection(omdTreeBuses))
		if len(modelFreeBusesInOmdFile) != 0:
			# Great, there are some buses in the mohca file that are in the omd file. That means we can have some color!
			# Note: If buses are in the omd and not in the Model-Free results, nothing is done.
			# 			If buses are in the Model-Free results and not in the omd, nothing is done.
			# If this were to change:
			# - These are the buses that are in the model-free results and not in the omd file they would have to get dropped.
			# 	buses_in_mohca_not_in_omd = set(mohca_buses) - set(omdTreeBuses)
			attachment_keys = {
				"coloringFiles": {
					"output_modelFreeFull.csv": {
						"csv": "<content>",
						"colorOnLoadColumnIndex": "1"
					}
				}
			}
			modelFreeColorData = Path(modelDir, 'output_modelFreeFull.csv').read_text()
			# adding the mohca color output to the attachment
			attachment_keys['coloringFiles']['output_modelFreeFull.csv']['csv'] = modelFreeColorData
			new_omd_path = Path(modelDir, 'color.omd')
			starting_omd['attachments'] = attachment_keys
			with open(new_omd_path, 'w+') as out_file:
				json.dump(starting_omd, out_file, indent=4)
			omf.geo.map_omd(new_omd_path, modelDir, open_browser=False)
			outData['hostingCapacityMap'] = open(Path(modelDir, "geoJson_offline.html"), 'r').read()
		else:
			# Warning there are no buses 
			outData['mapWarningFlag'] = True
			outData['mapWarningInfo'] = f"There are no buses in the .csv file that was provided for the model-free algorithm that are present in the circuit file. Map display may be affected."
	if inputDict['runModelBasedAlgorithm'] == 'on':
		# This code is copied from what previously existed in run_modelBased_algorithm
		# Except now, we are gonna check if color.omd is created.
		# If it is, then we just need to add the results to the already existing stuff
		# If its not, that means we need to create the map fresh.
		colorPath = Path(modelDir, 'color.omd')
		if colorPath.exists():
			# Just add model-based coloring
				modelBasedColor = {
					"colorByModelBased.csv": {
						"csv": "<content>",
						"colorOnLoadColumnIndex": "0"
					}
				}
				modelBasedColorData = Path(modelDir, 'colorByModelBased.csv').read_text()
				originalFileData = json.load( open(colorPath) )
				originalFileData['attachments']['coloringFiles'].update(modelBasedColor)
				originalFileData['attachments']['coloringFiles']['colorByModelBased.csv']['csv'] = modelBasedColorData
				with open(colorPath, 'w+') as out_file:
					json.dump(originalFileData, out_file, indent=4)
				omf.geo.map_omd(colorPath, modelDir, open_browser=False )
				outData['hostingCapacityMap'] = open(Path(modelDir, "geoJson_offline.html"), 'r' ).read()
		else:
			attachment_keys = {
				"coloringFiles": {
				"colorByModelBased.csv": {
					"csv": "<content>",
					"colorOnLoadColumnIndex": "1"
				},
				}
			}
			modelBasedColorData = Path(modelDir, 'colorByModelBased.csv').read_text()
			attachment_keys['coloringFiles']['colorByModelBased.csv']['csv'] = modelBasedColorData
			new_omd_path = Path(modelDir, 'color.omd')
			starting_omd['attachments'] = attachment_keys
			with open(new_omd_path, 'w+') as out_file:
				json.dump(starting_omd, out_file, indent=4)
			omf.geo.map_omd(new_omd_path, modelDir, open_browser=False )
			outData['hostingCapacityMap'] = open(Path(modelDir, "geoJson_offline.html"), 'r' ).read()
	if inputDict['runDownlineAlgorithm'] == 'on':
		# Same thing as the above if. We need to check if its created already. If it is, we just adding the color, if its not, we need to create the map setup as well
		colorPath = Path(modelDir, 'color.omd')
		if colorPath.exists():
			downline_color_data = Path(modelDir, 'output_downlineLoad.csv').read_text()
			downline_color = {
				"output_downlineLoad.csv": {
					"csv": "<content>",
					"colorOnLoadColumnIndex": "0"
				}
			}
			originalFileData = json.load( open(colorPath) )
			originalFileData['attachments']['coloringFiles'].update(downline_color)
			originalFileData['attachments']['coloringFiles']['output_downlineLoad.csv']['csv'] = downline_color_data
			with open(colorPath, 'w+') as out_file:
				json.dump(originalFileData, out_file, indent=4)
			omf.geo.map_omd(colorPath, modelDir, open_browser=False )
			outData['hostingCapacityMap'] = open(Path(modelDir, "geoJson_offline.html"), 'r' ).read()
		else:
			attachment_keys = {
				"coloringFiles": {
				"output_downlineLoad.csv": {
					"csv": "<content>",
					"colorOnLoadColumnIndex": "1"
				},
				}
			}
			downlineColorData = Path(modelDir, 'output_downlineLoad.csv').read_text()
			attachment_keys['coloringFiles']['output_downlineLoad.csv']['csv'] = downlineColorData
			new_omd_path = Path(modelDir, 'color.omd')
			starting_omd['attachments'] = attachment_keys
			with open(new_omd_path, 'w+') as out_file:
				json.dump(starting_omd, out_file, indent=4)
			omf.geo.map_omd(new_omd_path, modelDir, open_browser=False )
			outData['hostingCapacityMap'] = open(Path(modelDir, "geoJson_offline.html"), 'r' ).read()

	if outData["mapWarningFlag"] == True and inputDict['runModelBasedAlgorithm'] == 'off' and inputDict['runDownlineAlgorithm'] == 'off':
		# If there are no buses in the .csv that match the circuit, and model based and downline load both are not running, we don't need the map
		outData["hideMap"] = True

def run_downlineLoadAlgorithm( modelDir, inputDict, outData ):
	"""
	Run the downline load algorithm workflow and return its results.
	"""
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	opendss.dssConvert.treeToDss(tree, Path(modelDir, 'downlineLoad.dss'))
	downline_start_time = time.time()
	nx_data = opendss.dss_to_nx_fulldata( os.path.join( modelDir, 'downlineLoad.dss') )
	graph = nx_data[0]
	buses = opendss.get_all_buses( os.path.join( modelDir, 'downlineLoad.dss') )
	buses_output = {}
	objectTypesFromGraph = nx.get_node_attributes(graph, 'object')

	kwFromGraph = nx.get_node_attributes(graph, 'kw') #Load, generator attribute
	kwRatedFromGraph = nx.get_node_attributes( graph, 'kwrated') # Storage attribute
	kvFromGraph = nx.get_node_attributes( graph, 'kv' )
	# Check if they are buses
	for bus in buses:
		if bus in graph.nodes:
			kwSum = 0
			get_dependents = sorted(nx.descendants(graph, bus))
			for dependent in get_dependents:
				if dependent in kwFromGraph.keys() and objectTypesFromGraph[dependent] == 'load':
					kwSum += float( kwFromGraph[dependent] )
				elif dependent in kwFromGraph.keys() and objectTypesFromGraph[dependent] == 'generator':
					kwSum -= float( kwFromGraph[dependent] )
				elif dependent in kwRatedFromGraph.keys() and objectTypesFromGraph[dependent] == 'storage':
					kwSum -= float( kwRatedFromGraph[dependent] )
				elif dependent in kvFromGraph.keys() and objectTypesFromGraph[dependent] == 'pvsystem':
					pfFromGraph = nx.get_node_attributes(graph, 'pf')
					# pvsystem has kv, not kw
					kwForPVSys = kvFromGraph[dependent] * pfFromGraph[dependent]
					kwSum -= kwForPVSys
			buses_output[bus] = kwSum
	downline_output = pd.DataFrame(list(buses_output.items()), columns=['bus', 'kw'] )
	downline_end_time = time.time()
	sorted_downlineDF = downline_output.sort_values(by='bus')
	buses_to_remove = ['eq_source_bus', 'bus_xfmr']
	indexes = []
	for bus in buses_to_remove:
		indexes.append( sorted_downlineDF[sorted_downlineDF['bus'] == bus].index )
	for i in indexes:
		sorted_downlineDF = sorted_downlineDF.drop(i)
	sorted_downlineDF.to_csv(Path(modelDir, 'output_downlineLoad.csv'), index=False)

	outData['downline_tableHeadings'] = downline_output.columns.values.tolist()
	outData['downline_tableValues'] = (list(sorted_downlineDF.itertuples(index=False, name=None)))
	outData['downline_runtime'] = convertTime( downline_end_time - downline_start_time )
	return sorted_downlineDF

def checkKvar( inputPathAMIData ):
	''' Uses sandia's get_has_input_q function from mohca_cl.sandia to check presence of reactive power'''
	data = pd.read_csv(inputPathAMIData)
	# First check of the column is there
	if 'kvar_reading' in data:
		# Returns False if no q
		return mohca_cl.sandia.get_has_input_q(data)
	else:
		return False
	
def getBool( string ):
	''' Converts string of boolean word to python bool type'''
	retVal = False
	if string.lower() == "true":
		retVal = True
	elif string.lower() == 'false':
		retVal = False
	return retVal

def run_AMIAlgorithm( modelDir, inputDict, outData ):
	''' mohca data-driven hosting capacity '''

	inputPathAMIData = Path(modelDir, inputDict['AmiDataFileName'])
	AMIDataAsString = inputPathAMIData.read_text()
	try:
		csvValidateAndLoad(AMIDataAsString, modelDir=modelDir, header=0, nrows=None, ncols=None, dtypes=[], return_type='df', ignore_nans=True, save_file=None, ignore_errors=False )
	except:
		errorMessage = "AMI-Data CSV file is incorrect format. Please see valid format definition at <a target='_blank' href='https://github.com/dpinney/omf/wiki/Models-~-hostingCapacity#meter-data-input-csv-file-format'>OMF Wiki hostingCapacity</a>"
		raise Exception(errorMessage)
	outputPathVoltageHC = Path(modelDir, 'outputMohcaVoltageHC.csv')
	outputPathThermalHC = Path(modelDir, 'outputMohcaThermalHC.csv')
	custTransPairing = inputDict["custTransPairingPresent"]
	hasKvar = checkKvar( inputPathAMIData )
	processThermal = True
	if hasKvar == False:
		outData["reactivePowerWarningFlag"] = True
		outData["reactivePowerWarningInfo"] = f"Reactive power not present in Meter Data Input File. Model-free voltage-constrained results will be estimated. No model-free thermal-constrained results available."
		processThermal = False
		# Thermal Hosting Capacity Variables
	if inputDict["custTransPairingPresent"] == "off":
		outData["custTransPairingWarningFlag"] = True
		outData["custTransPairingWarningInfo"] = f"Customer to Transformer Pairing either was not computed or provided. No model-free thermal contrained results available"
		processThermal = False
	if processThermal == True: # Process all the inputs for Thermal-Constrained Hosting Capacity
		busCoords = None
		xfLookup = None
		completed_xfmrCustFlag = False
		xfLookupPath = Path(modelDir, inputDict['xfLookupDataFileName']) 
		xfLookupDF = pd.read_csv( xfLookupPath )
		if xfLookupDF.empty:
			xfLookup = None
		else:
			xfLookup = xfLookupDF
		if custTransPairing == "compute":
			busCoords = Path(modelDir, inputDict['busCoordsDataFileName'])
			numOfXfmr = int( inputDict['numOfXfmrs'])
			exactXfmrs = getBool( inputDict['exactXfmrs'] )
			# If numOfXfmrs = 0, the input for mohca_cl.isu_transformerCustMapping must be None, False, None
			if numOfXfmr == 0:
				numOfXfmr = None
				exactXfmrs = False
				busCoords = None
				inputDict['exactXfmr'] = False
				inputDict['busCoords'] = None
				outData["xfmrWarningFlag"] = True
				outData["xfmrWarningInfo"] = f"If the number of transformers ( numOfXFmrs ) is set to False ( or 0 ), Exact Transformers ( exactXfmrs ) is set to False and no buscoords are used ( set to None )."
				completed_xfmrCustFlag = False
		elif custTransPairing == "completed":
			completed_xfmrCustPath = Path(modelDir, inputDict['completed_xfmrCustDataFileName'])
			completed_xfmrCustDF = pd.read_csv( completed_xfmrCustPath )
			completed_xfmrCustFlag = False # We assume it has not been calculated
			if completed_xfmrCustDF.empty == False:
				# If it's not empty, then it has been completed and we do not need to calculate it
				completed_xfmrCustFlag = True
			else:
				processThermal = False
				outData["completedCustTransPairingWarningFlag"] = True
				outData["completedCustTransPairingWarningInfo"] = f"User selected 'completed' for customer transformer pairing but the file inputted was empty. Will compute voltage-constrained hosting capacity only"
	# end if processThermal
	amiStartTime = time.time()
	if inputDict[ "algorithm" ] == "sandia1":
		if inputDict["dgInverterSetting"] == 'constantPF':
			valueDerPF = float(inputDict['derPF'])
			if valueDerPF > 1.0 or valueDerPF < 0:
				errorMessage = "DG Power Factor must be between 0 and 1"
				raise Exception(errorMessage)
			# Calculate Voltage Hosting Capacity
			mohca_cl.sandia1( in_path=inputPathAMIData, out_path=outputPathVoltageHC, der_pf= float(inputDict['derPF']), vv_x=None, vv_y=None, load_pf_est=float(inputDict['load_pf_est'] ))
			# Temp warning and catching if statement until fixed
			if hasKvar and processThermal:
				# Calculate Thermal Hosting Capacity
				# Check if user inputted their own completed xfmr <-> customer mappings. If so, Calculate with theirs
				if completed_xfmrCustFlag == True:
					mohca_cl.sandiaTCHC( in_path=inputPathAMIData, out_path=outputPathThermalHC, final_results=completed_xfmrCustDF, der_pf=float(inputDict['derPF']), vv_x=None, vv_y=None, overload_constraint=float(inputDict['overloadConstraint']), xf_lookup=xfLookup )
				# If they did not include their own, calculate it as best as you can with ISU's function, then calculate thermal with the result gotten from ISU's algo
				else:
					outputPath_xfmrCustResults = Path(modelDir, 'output_IsuXfmrCustPairing.csv')
					xfmrCustMapResult = mohca_cl.isu_transformerCustMapping(input_meter_data_fp=inputPathAMIData, grouping_output_fp=outputPath_xfmrCustResults, minimum_xfmr_n=numOfXfmr, fmr_n_is_exact=exactXfmrs, bus_coords_fp=busCoords )
					mohca_cl.sandiaTCHC( in_path=inputPathAMIData, out_path=outputPathThermalHC, final_results=xfmrCustMapResult, der_pf=float(inputDict['derPF']), vv_x=None, vv_y=None, overload_constraint=float(inputDict['overloadConstraint']), xf_lookup=xfLookup )
				# end if completed_xfmrCustFlag
			# end if hasKvar & processThermal
		# end if constantPF
		elif inputDict["dgInverterSetting"] == 'voltVar':
			# Calculate Voltage Hosting Capacity
			vvPointsSplit = [float(x) for x in inputDict['vvPoints'].split(',')]
			vv_x = [v for i,v in enumerate(vvPointsSplit) if i%2==0]
			vv_y = [v for i,v in enumerate(vvPointsSplit) if i%2==1]
			mohca_cl.sandia1( in_path=inputPathAMIData, out_path=outputPathVoltageHC, der_pf= float(inputDict['derPF']), vv_x=vv_x, vv_y=vv_y, load_pf_est=float(inputDict['load_pf_est'] ))
			if hasKvar and processThermal:
				# Calculate Thermal Hosting Capacity
				if completed_xfmrCustFlag == True:
					mohca_cl.sandiaTCHC( in_path=inputPathAMIData, out_path=outputPathThermalHC, final_results=completed_xfmrCustDF, der_pf=float(inputDict['derPF']), vv_x=vv_x, vv_y=vv_y, overload_constraint=float(inputDict['overloadConstraint']), xf_lookup=xfLookup )
				else:
					outputPath_xfmrCustResults = Path(modelDir, 'output_IsuXfmrCustPairing.csv')
					xfmrCustMapResult = mohca_cl.isu_transformerCustMapping(input_meter_data_fp=inputPathAMIData, grouping_output_fp=outputPath_xfmrCustResults, minimum_xfmr_n=numOfXfmr, fmr_n_is_exact=exactXfmrs, bus_coords_fp=busCoords )
					mohca_cl.sandiaTCHC( in_path=inputPathAMIData, out_path=outputPathThermalHC, final_results=xfmrCustMapResult, der_pf=float(inputDict['derPF']), vv_x=vv_x, vv_y=vv_y, overload_constraint=float(inputDict['overloadConstraint']), xf_lookup=xfLookup )
				# end if completed_xfmrCustFlag
			# end if hasKvar & processThermal
		# end if voltVar
		else:
			errorMessage = "DG Error - Should not happen. dgInverterSetting is not either of the 2 options it is supposed to be."
			raise Exception(errorMessage)
	elif inputDict[ "algorithm" ] == "iastate":
		mohca_cl.iastate( inputPathAMIData, outputPathVoltageHC )
	else:
		errorMessage = "Algorithm name error"
		raise Exception(errorMessage)
	amiEndTime = time.time()
	modelFreeResults = pd.read_csv( outputPathVoltageHC, index_col=False)
	modelFreeResults.rename(columns={'kw_hostable': 'voltage_cap_kW'}, inplace=True)
	modelFreeResultsSorted = modelFreeResults.sort_values(by='busname')
	if hasKvar == True and processThermal:
		modelFreeThermalResults = pd.read_csv( outputPathThermalHC )
		thermalKwResults = modelFreeThermalResults['TCHC (kW)']
		modelFreeResultsSorted['thermal_cap_kW'] = thermalKwResults
		histogramFigure = px.histogram( modelFreeResultsSorted, x=['voltage_cap_kW', 'thermal_cap_kW'], template="simple_white", color_discrete_sequence=["lightblue", "MediumPurple"] )
		histogramFigure.update_layout(bargap=0.5)
		modelFreeResultsSorted['min_allowed_kW'] = np.minimum( modelFreeResultsSorted['voltage_cap_kW'], modelFreeResultsSorted['thermal_cap_kW'])
		modelFreeResultsSorted = modelFreeResultsSorted[['busname', 'min_allowed_kW', 'voltage_cap_kW', 'thermal_cap_kW']]
		barChartFigure = px.bar(modelFreeResultsSorted, x='busname', y=['min_allowed_kW','voltage_cap_kW', 'thermal_cap_kW'], barmode='group', color_discrete_sequence=["green", "lightblue", "MediumPurple"], template="simple_white" )
		barChartFigure.update_layout( legend=dict(
			orientation='h',
			yanchor='bottom',
			y=1.02,
			xanchor='right',
			x=1
		) )
	else:
		histogramFigure = px.histogram( modelFreeResultsSorted, x=['voltage_cap_kW'], template="simple_white", color_discrete_sequence=["lightblue"] )
		histogramFigure.update_layout(bargap=0.5)
		modelFreeResultsSorted['min_allowed_kW'] = modelFreeResultsSorted['voltage_cap_kW']
		modelFreeResultsSorted = modelFreeResultsSorted[['busname', 'min_allowed_kW', 'voltage_cap_kW']]
		barChartFigure = px.bar(modelFreeResultsSorted, x='busname', y=['min_allowed_kW','voltage_cap_kW'], barmode='group', color_discrete_sequence=["green", "lightblue"], template="simple_white" )
		barChartFigure.update_layout( legend=dict(
			orientation='h',
			yanchor='bottom',
			y=1.02,
			xanchor='right',
			x=1
		) )
	modelFreeResultsSorted.to_csv( Path(modelDir, "output_modelFreeFull.csv"), index=False )
	barChartFigure.add_traces( list(px.line(modelFreeResultsSorted, x='busname', y='min_allowed_kW', markers=True).select_traces()) )
	outData['histogramFigure'] = json.dumps( histogramFigure, cls=py.utils.PlotlyJSONEncoder )
	outData['barChartFigure'] = json.dumps( barChartFigure, cls=py.utils.PlotlyJSONEncoder )
	outData['AMI_tableHeadings'] = modelFreeResultsSorted.columns.values.tolist()
	outData['AMI_tableValues'] = ( list(modelFreeResultsSorted.itertuples(index=False, name=None)) )
	outData['AMI_runtime'] = convertTime( amiEndTime - amiStartTime )

def run_modelBasedAlgorithm( modelDir, inputDict, outData ):
	"""
	Run the model based algorithm workflow and return its results.
	"""
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	inputDict['feederName1'] = feederName[:-4]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	opendss.dssConvert.treeToDss(tree, Path(modelDir, 'circuit.dss'))
	modelBasedStartTime = time.time()
	modelBasedHCResults = opendss.hosting_capacity_all( FNAME = Path(modelDir, 'circuit.dss'), max_test_kw=int(inputDict["modelBasedHCMaxTestKw"]))
	modelBasedEndTime = time.time()
	# - opendss.hosting_capacity_all() changes the cwd, so change it back so other code isn't affected
	modelBasedHCDF = pd.DataFrame( modelBasedHCResults )
	sorted_modelBasedHCDF = modelBasedHCDF.sort_values(by='bus')
	sorted_modelBasedHCDF.to_csv( "output_tradHC.csv")
	modelBasedHCFigure = px.bar( sorted_modelBasedHCDF, x='bus', y='max_kw', barmode='group', template='simple_white', color_discrete_sequence=["green"] )
	modelBasedHCFigure.update_xaxes(categoryorder='array', categoryarray=sorted_modelBasedHCDF.bus.values)
	# These files need to be made for coloring the map.
	color_df = sorted_modelBasedHCDF[['bus','max_kw']]
	color_df.to_csv(Path(modelDir, 'colorByModelBased.csv'), index=False)
	outData['modelBasedGraphData'] = json.dumps(modelBasedHCFigure, cls=py.utils.PlotlyJSONEncoder )
	outData['modelBasedHCTableHeadings'] = sorted_modelBasedHCDF.columns.values.tolist()
	outData['modelBasedHCTableValues'] = (list(sorted_modelBasedHCDF.itertuples(index=False, name=None)))
	outData['modelBasedRuntime'] = convertTime( modelBasedEndTime - modelBasedStartTime )
	outData['modelBasedHCResults'] = modelBasedHCResults

def runtimeEstimate(modelDir):
	''' Estimated runtime of model in minutes. '''
	return 1.0

def work(modelDir, inputDict):
	"""
	Run the hosting capacity model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	if inputDict['runAmiAlgorithm'] == 'on':
		run_AMIAlgorithm(modelDir, inputDict, outData)
	if inputDict.get('runModelBasedAlgorithm', outData) == 'on':
		run_modelBasedAlgorithm(modelDir, inputDict, outData)
	if inputDict.get('runDownlineAlgorithm') == 'on':
		run_downlineLoadAlgorithm( modelDir, inputDict, outData)
	hostingCapacityMap(modelDir=modelDir, inputDict=inputDict, outData=outData)
	outData['stdout'] = "Success"
	outData['stderr'] = ""
	return outData

'''
meterFileName = input_mohca.csv
The name choice is a standard name. Every file that gets inputted will be changed into that name.
Reference : /omf/static/testfiles/hostingCapacity for all the testFiles and their standard names.
This file comes from a sample input from Sandia to match the secondaryTestCircuit
'''

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	meterFileName = 'input_mohcaData.csv'
	meterFilePath = Path(omf.omfDir,'static','testFiles', 'hostingCapacity', meterFileName)
	xfLookupFileName = "input_xfLookup.csv"
	xfLookupFilePath = Path( omf.omfDir, 'static','testFiles', 'hostingCapacity', xfLookupFileName )
	completed_xfmrCustFileName = 'input_completed_xfmrCust.csv'
	completed_xfmrCustFilePath = Path(omf.omfDir, 'static', 'testFiles', 'hostingCapacity', completed_xfmrCustFileName)
	busCoordsFileName = "input_busCoords.csv"
	busCoordsFilePath = Path(omf.omfDir, 'static', 'testFiles', 'hostingCapacity', busCoordsFileName)

	defaultInputs = {
		"modelType": modelName,
		"feederName1": 'nreca_secondaryTestSet',
		"runAmiAlgorithm": 'on',
		"AmiDataFileName": meterFileName,
		"AmiUIDisplay": meterFileName,
		"algorithm": 'sandia1',
		"load_pf_est": 1.0,
		"dgInverterSetting": 'constantPF',
		"derPF": 1.00,
		"vvPoints": "0.8,0.44,0.92,0.44,0.98,0,1.02,0,1.08,-0.44,1.2,-0.44",
		"overloadConstraint": 1.2,
		"xfLookupDataFileName": xfLookupFileName,
		"xfLookupUIDisplay": xfLookupFileName,
		"numOfXfmrs": 12,
		"exactXfmrs": "False",
		"busCoordsDataFileName": busCoordsFileName,
		"busCoordsUIDisplay": busCoordsFileName,
		"completed_xfmrCustDataFileName": completed_xfmrCustFileName,
		"completed_xfmrCustUIDisplay": completed_xfmrCustFileName,
		"runModelBasedAlgorithm": 'on',
		"modelBasedHCMaxTestKw": 50000,
		"runDownlineAlgorithm": 'on',
		'custTransPairingPresent': 'compute'
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	# Copy files from the test directory ( or respective places ) and put them in the model for use
	try:
		shutil.copyfile(
			Path(__neoMetaModel__._omfDir, "static", "testFiles", 'hostingCapacity', defaultInputs["feederName1"]+'.omd'),
			Path(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile( meterFilePath, Path(modelDir, meterFileName) )
		shutil.copyfile( xfLookupFilePath, Path(modelDir, xfLookupFileName) )
		shutil.copyfile( busCoordsFilePath, Path(modelDir, busCoordsFileName))
		shutil.copyfile( completed_xfmrCustFilePath, Path(modelDir, completed_xfmrCustFileName) )
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _disabled_tests():
	# Location
	"""
	Internal helper for hosting capacity disabled tests processing.
	"""
	modelLoc = Path(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		pass # No previous test results.
	# Create New.
	new(modelLoc)
	# Pre-run.
	__neoMetaModel__.renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_disabled_tests()
