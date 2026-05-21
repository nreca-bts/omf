"""
The transmission model calculates the expected powerflow voltage results per bus on a
given transmission circuit. The underlying calculations are handled by MATPOWER.
"""

import json, os, shutil, platform, base64
from os.path import join as pJoin
import matplotlib
from matplotlib import pyplot as plt
import matplotlib.cm as cm
import pandapower as ppow
from omf import transmission as network
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The transmission model imports, runs and visualizes MATPOWER transmission and generation simulations."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory.'''
	outData = {
		'tableData' : {'volts': [[],[]], 'powerReal' : [[],[]], 'powerReact' : [[],[]]},
		# 'charts' : {'volts' : '', 'powerReact' : '', 'powerReal' : ''},
		'voltsChart' : '', 'powerReactChart' : '', 'powerRealChart' : '',
		'stdout' : '', 'stderr' : ''
		}
	# Read feeder and convert to .m.
	try:
		networkName = [x for x in os.listdir(modelDir) if x.endswith('.omt')][0][0:-4]
	except:
		networkName = 'case9'
	with open(pJoin(modelDir,networkName+".omt")) as f:
		networkJson = json.load(f)
	matName = 'matIn'
	matFileName = matName + '.m'
	matStr = network.netToMat(networkJson, matName)
	matStr = matStr + ['''mpc.gencost = [
	2	1500	0	3	0.11	5	150;
	2	2000	0	3	0.085	1.2	600;
	2	3000	0	3	0.1225	1	335;
	];'''] #HACK: include gencost
	with open(pJoin(modelDir, matFileName),"w") as outMat:
		for row in matStr: outMat.write(row)		
	# Run pandapower powerflow and generate results
	case = ppow.converter.from_mpc(pJoin(modelDir, matFileName))
	ppow.runpp(case)
	bus_labels = [f'bus{x}' for x in case.res_bus.index]
	volt_amounts = list(case.res_bus['vm_pu'])
	pow_amounts = list(case.res_bus['p_mw'])
	react_amounts = list(case.res_bus['q_mvar'])
	outData['tableData'] = {
		"volts":[
			bus_labels,
			volt_amounts
		],
		"powerReal":[
			bus_labels,
			pow_amounts
		],
		"powerReact":[
			bus_labels,
			react_amounts
		]
	}
	# Create chart
	nodeVolts = outData["tableData"]["volts"][1]
	minNum = min(nodeVolts)
	maxNum = max(nodeVolts)
	norm = matplotlib.colors.Normalize(vmin=minNum, vmax=maxNum, clip=True)
	cmViridis = plt.get_cmap('viridis')
	mapper = cm.ScalarMappable(norm=norm, cmap=cmViridis)
	mapper._A = []
	plt.figure(figsize=(10,10))
	plt.colorbar(mapper)
	plt.axis('off')
	plt.tight_layout()
	plt.gca().invert_yaxis() # HACK: to make latitudes show up right. TODO: y-flip the transEdit.html and remove this.
	plt.gca().set_aspect('equal')
	busLocations = {}
	i = 0
	for busName, busInfo in networkJson["bus"].items():
		y = float(busInfo["latitude"])
		x = float(busInfo["longitude"])
		plt.plot([x], [y], marker='o', markersize=12.0, color=mapper.to_rgba(nodeVolts[i]), zorder=5)  
		busLocations[busName] = [x, y]
		i = i + 1
	for genName, genInfo in networkJson["gen"].items():
		x,y =  busLocations[genInfo["bus"]]
		plt.plot([x], [y], 's', color='gray', zorder=10, markersize=6.0)
	for branchName, branchInfo in networkJson["branch"].items():
		x1, y1 = busLocations[branchInfo["fbus"]]
		x2, y2 = busLocations[branchInfo["tbus"]]
		plt.plot([x1, x2], [y1,y2], color='black', marker = '', zorder=0)
	plt.savefig(modelDir + '/output.png')
	with open(pJoin(modelDir,"output.png"),"rb") as inFile:
		outData["chart"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def _getMatPath(matDir):
	# Get paths required for matpower7.0 in octave
	"""
	Internal helper for transmission get mat path processing.
	"""
	if platform.system() == "Windows":
		pathSep = ";"
	else:
		pathSep = ":"
	relativePaths = ['lib', 'lib/t', 'data', 'mips/lib', 'mips/lib/t', 'most/lib', 'most/lib/t', 'mptest/lib', 'mptest/lib/t', 'extras/maxloadlim', 'extras/maxloadlim/tests', 'extras/maxloadlim/examples', 'extras/misc', 'extras/reduction', 'extras/sdp_pf', 'extras/se', 'extras/smartmarket', 'extras/state_estimator', 'extras/syngrid/lib','extras/syngrid/lib/t']
	paths = [matDir] + [pJoin(matDir, relativePath) for relativePath in relativePaths]
	matPath = '"' + pathSep.join(paths) + '"'
	return matPath

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"user": "admin",
		"networkName1": "case9",
		"algorithm": "NR",
		"model": "AC",
		"tolerance": "0.00000001",
		"iteration": 10,
		"genLimits": 0,
		"modelType":modelName}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copy(pJoin(__neoMetaModel__._omfDir,"static","SimpleNetwork.json"),pJoin(modelDir,"case9.omt"))
	except:
		return False
	return creationCode

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
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
