"""
The model corrects GIS errors where meters are not associated with the correct
transformer. It does this by calculating voltage and power correlations between meters.
It is based on code and results developed by Logan Blakely and Matthew Reno at Sandia
National Laboratory.
"""

import warnings
# warnings.filterwarnings("ignore")

# Import Python libraries
import shutil
import numpy as np
from pathlib import Path
import pandas as pd
import base64

# OMF imports
import omf
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Import custom libraries
from omf.solvers import sdsmc 

# Model metadata:
tooltip = "Transformer Pairing"
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False


def work(modelDir, inputDict):

	"""
	Run the transformer pairing model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	useTrueLabels = True
	saveResultsPath = modelDir
	test_data_file_path = Path(omf.omfDir,'static','testFiles', 'transformerPairing')

	outData["useTrueLabels"] = useTrueLabels	

	voltageInputPathCSV = Path( modelDir, inputDict['voltageDataFileName'])
	realPowerInputPathCSV = Path( modelDir, inputDict['realPowerDataFileName'])
	custIDInputPathCSV = Path( modelDir, inputDict['customerIDDataFileName'])
	reactivePowerInputPathCSV = Path( modelDir, inputDict['reactivePowerDataFileName'])
	custLatLongInputPathCSV = Path( modelDir, inputDict['customerLatLongDataFileName'])

	transformer_labels_errors_file_name = 'TransformerLabelsErrors_AMI.csv'
	transformerLabelsErrorsPathCSV = Path( modelDir, transformer_labels_errors_file_name )

	if useTrueLabels:
		transformer_labels_true_file_name = 'TransformerLabelsTrue_AMI.csv'
		shutil.copyfile( Path( test_data_file_path, transformer_labels_true_file_name ), Path(modelDir, transformer_labels_true_file_name) )
		transformerLabelsTruePath = Path(modelDir, transformer_labels_true_file_name)

	if inputDict['algorithm'] == 'reactivePower':
		sdsmc.MeterTransformerPairing.TransformerPairing.run( voltageInputPathCSV, realPowerInputPathCSV, reactivePowerInputPathCSV, custIDInputPathCSV, transformerLabelsErrorsPathCSV, transformerLabelsTruePath, saveResultsPath, useTrueLabels )

	elif inputDict['algorithm'] == 'customerLatLong':
		sdsmc.MeterTransformerPairing.TransformerPairingWithDist.run( voltageInputPathCSV, realPowerInputPathCSV, custIDInputPathCSV, transformerLabelsErrorsPathCSV, custLatLongInputPathCSV, transformerLabelsTruePath, saveResultsPath, useTrueLabels )

	else:
		errorMessage = "Algorithm Choice Error"
		raise Exception(errorMessage)

	# The outputs for the customerLatLong version have _NoQ at the end of the output files. I removed it for outputs_ChangedCustomers_M2T

	changedCustomersDF = pd.read_csv( Path(modelDir, "outputs_ChangedCustomers_M2T.csv") )
	outData['customerTableHeadings'] = changedCustomersDF.columns.values.tolist()
	outData['customerTableValues'] = ( list(changedCustomersDF.sort_values( by="customer ID", ascending=True, ignore_index=True ).itertuples(index=False, name=None)))

	improvementStats = pd.read_csv( Path(modelDir, "outputs_ImprovementStats.csv") )
	outData['improvementTableHeadings'] = improvementStats.columns.values.tolist()
	outData['improvementTableValues'] = (list(improvementStats.itertuples(index=False, name=None)))

	with open( Path(modelDir,"CCThresholdSweep_NumFlaggedTrans_LINE.png"),"rb") as inFile:
		outData["correlationCoefficientPic"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	
	# Delete output file every run if it exists
	outData['stdout'] = "Success"
	outData['stderr'] = ""
	return outData

def runtimeEstimate(modelDir):
	''' Estimated runtime of model in minutes. '''
	return 1.0

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''

	test_data_file_path = Path(omf.omfDir,'static','testFiles', 'transformerPairing')

	# Default file names from static/testFiles/
	voltage_file_name = 'voltageData_AMI.csv'
	real_power_file_name = 'realPowerData_AMI.csv'
	customer_ids_file_name = 'CustomerIDs_AMI.csv'
	customer_latlong_file_name = 'CustomerLatLon.csv'
	reactive_power_file_name = 'reactivePowerData_AMI.csv'

	transformer_labels_errors_file_name = 'TransformerLabelsErrors_AMI.csv'

	# Default options: reactivePower, customerLatLong
	defaultAlgorithm = "reactivePower"

	defaultInputs = {
		"modelType": modelName,
		"algorithm": defaultAlgorithm,
		"userInputVoltageDisplayName": voltage_file_name,
		"voltageDataFileName": voltage_file_name,
		"userInputRealDisplayName": real_power_file_name,
		"realPowerDataFileName": real_power_file_name,
		"userInputCustIDDisplayName": customer_ids_file_name,
		"customerIDDataFileName": customer_ids_file_name,
		"userInputCustLatLongDisplayName": customer_latlong_file_name,
		"customerLatLongDataFileName": customer_latlong_file_name,
		"userInputReactiveDisplayName": reactive_power_file_name,
		"reactivePowerDataFileName": reactive_power_file_name
	}

	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile( Path( test_data_file_path, voltage_file_name), Path(modelDir, voltage_file_name))
		shutil.copyfile( Path( test_data_file_path, real_power_file_name), Path(modelDir, real_power_file_name))
		shutil.copyfile( Path( test_data_file_path, customer_ids_file_name), Path(modelDir, customer_ids_file_name))
		shutil.copyfile( Path( test_data_file_path, customer_latlong_file_name), Path(modelDir, customer_latlong_file_name))
		shutil.copyfile( Path( test_data_file_path, reactive_power_file_name), Path(modelDir, reactive_power_file_name))
		shutil.copyfile( Path( test_data_file_path, transformer_labels_errors_file_name ), Path(modelDir, transformer_labels_errors_file_name) )
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _disabled_tests():
	# Location
	"""
	Internal helper for transformer pairing disabled tests processing.
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
