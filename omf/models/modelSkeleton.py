"""
Provide a minimal template model showing the OMF model lifecycle, metadata, defaults,
and test hooks.
"""

import warnings
# warnings.filterwarnings("ignore")

import shutil, datetime
from pathlib import Path

# OMF imports
from omf import feeder
from omf.models.voltageDrop import drawPlot
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

def castAddInputs(val1,val2):
	''' Casts string inputs to appropriate type and returns their sum. 
		If inputs are cast to floats, rounds their sum to avoid float subtraction errors.'''
	try:
		cast1 = int(val1)
		cast2 = int(val2)
		return cast1+cast2
	except ValueError:
		try:
			cast1 = float(val1)
			cast2 = float(val2)
            #Find longest decimal place of the numbers and round their sum to that place to avoid float arithmetic errors
			decPl1 = val1.strip()[::-1].find('.')
			decPl2 = val2.strip()[::-1].find('.')  
            #valX.strip() used instead of str(castX) because str(castX) may return scientific notation
			roundedSum = round(cast1+cast2,max(decPl1,decPl2,1))     
			return roundedSum
		except ValueError:
			return val1+val2

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# Delete output file every run if it exists
	outData = {}		
	# Model operations goes here.
	inputOne = inputDict.get("input1", 123)
	inputTwo = inputDict.get("input2", 867)
	output = str(castAddInputs(inputOne,inputTwo))
	outData["output"] = output
	# Model operations typically ends here.
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"user" : "admin",
		"modelType": modelName,
		"input1": "abc1 Easy as...",
		"input2": "123 Or Simple as...",
		"created":str(datetime.datetime.now())
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

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
