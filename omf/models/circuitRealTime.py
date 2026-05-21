"""
The circuitRealtime Model is an OMF frontend to the JavaScript version of the Falstad
Circuit Simulator.
"""

import shutil
from os.path import join as pJoin
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = 'Real time circuit simulator'

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# Stdout/stderr.
	outData = {}		
	outData["stdout"] = "Success"
	outData["stderr"] = ""

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"modelType": modelName,
		"circString":"$ 1 0.000005 10.20027730826997 50 5 43\nr 176 64 384 64 0 10\ns 384 64 448 64 0 1 false\nw 176 64 176 336 0\nc 384 336 176 336 0 0.000014999999999999999 2.2688085065409958\nl 384 64 384 336 0 1 0.035738623044691664\nv 448 336 448 64 0 0 40 5 0 0 0.5\nr 384 336 448 336 0 100\no 4 64 0 2083 20 0.05 0 -1 0",
		"user":"admin"
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
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

if __name__ == '__main__':
	_tests()