"""
The faultAnalysis model calculates and displays the effects of a fault on a given feeder
circuit. It is similar to the voltageDrop model, with the addition of a fault to the
provided circuit. ### Walkthrough The faultAnalysis model calculates and displays the
effects of a fault on a given feeder circuit. It is similar to the voltageDrop model,
with the addition of a fault to the provided circuit. The "Node Coloring By" and "Line
Coloring By" fields denote the values that nodes and edges will be colored by in the
loadflow output image. Similarly, "Node Labels" and "Line Labels" provide an option to
label nodes and lines by name or value. The user can also choose to display only the
line label for the location of the fault on the circuit. "Color Map" is set to Viridis
by default for optimal readability of the scale. "Color Scale Min" and "Color Scale Max"
allow the user to specify a specific range for the color scale, which is set by default
when these fields are left empty. "Image Resolution" allows the user to specify the size
of the output image, which is useful for varying circuit sizes. "Fault Location" and
"Fault Type" specify where the fault occurs and what type of fault occurs. Finally,
"Simulation Time" denotes the date and time at which the simulation is run.
"""

import json, os, shutil, csv, base64
from os.path import join as pJoin

# dateutil imports
from dateutil.relativedelta import *

# OMF imports
import omf
from omf import feeder
from omf.models import voltageDrop
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Injects faults in to circuits and measures fault currents, voltages, and protective device response."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# feederName = inputDict["feederName1"]
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	# Create voltage drop plot.
	# print "*DEBUG: feederName:", feederName
	with open(pJoin(modelDir,feederName + '.omd')) as f:
		omd = json.load(f)
	if inputDict.get("layoutAlgorithm", "geospatial") == "geospatial":
		neato = False
	else:
		neato = True
	# None check for edgeCol
	if inputDict.get("edgeCol", "None") == "None":
		edgeColValue = None
	else:
		edgeColValue = inputDict["edgeCol"]
	# None check for nodeCol
	if inputDict.get("nodeCol", "None") == "None":
		nodeColValue = None
	else:
		nodeColValue = inputDict["nodeCol"]
	# None check for edgeLabs
	if inputDict.get("edgeLabs", "None") == "None":
		edgeLabsValue = None
	else:
		edgeLabsValue = inputDict["edgeLabs"]
	# None check for nodeLabs
	if inputDict.get("nodeLabs", "None") == "None":
		nodeLabsValue = None
	else:
		nodeLabsValue = inputDict["nodeLabs"]
	# Type correction for colormap input
	if inputDict.get("customColormap", "True") == "True":
		customColormapValue = True
	else:
		customColormapValue = False
	# None check for scaleMin
	if inputDict.get("scaleMin", "None") == "None":
		scaleMinValue = None
	else:
		scaleMinValue = inputDict["scaleMin"]
	# None check for scaleMax
	if inputDict.get("scaleMax", "None") == "None":
		scaleMaxValue = None
	else:
		scaleMaxValue = inputDict["scaleMax"]
	if inputDict.get("simTime", "") == "":
		simTimeValue = '2000-01-01 0:00:00'
	else:
		simTimeValue = inputDict["simTime"]
	if inputDict.get("faultType", "None") == "None":
		faultTypeValue = None
	else:
		faultTypeValue = inputDict["faultType"]

	chart = voltageDrop.drawPlot(
		pJoin(modelDir,feederName + ".omd"),
		neatoLayout = neato,
		edgeCol = edgeColValue,
		nodeCol = nodeColValue,
		nodeLabs = nodeLabsValue,
		edgeLabs = edgeLabsValue,
		customColormap = customColormapValue,
		scaleMin = scaleMinValue,
		scaleMax = scaleMaxValue,
		faultLoc = inputDict["faultLoc"],
		faultType = faultTypeValue,
		rezSqIn = int(inputDict["rezSqIn"]),
		simTime = simTimeValue,
		workDir = modelDir)
	chart.savefig(pJoin(modelDir, "output.png"))
	with open(pJoin(modelDir, "output.png"),"rb") as inFile:
		outData["voltageDrop"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	table = drawTable(
		pJoin(modelDir,feederName + ".omd"),
		workDir = modelDir)
	with open(pJoin(modelDir, "statusTable.html"), "w") as tabFile:
		tabFile.write(table)
	outData['tableHtml'] = table
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"feederName1": "Olin Barre Fault",
		"modelType": modelName,
		"runTime": "",
		"layoutAlgorithm": "geospatial",
		"edgeCol" : "Current",
		"nodeCol" : "Voltage",
		"nodeLabs" : "None",
		"edgeLabs" : "None",
		"faultLoc" : "17720",
		"faultType" : "SLG-A",
		"customColormap" : "False",
		"scaleMin" : "None",
		"scaleMax" : "None",
		"rezSqIn" : "400",
		"simTime" : '2000-01-01 0:00:00'
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _testingPlot():
	"""
	Internal helper for fault analysis testing plot processing.
	"""
	PREFIX = omf.omfDir + '/scratch/CIGAR/'
	# FNAME = 'test_base_R4-25.00-1.glm_CLEAN.glm'
	# FNAME = 'test_Exercise_4_2_1.glm'
	# FNAME = 'test_ieee37node.glm'
	FNAME = 'test_ieee37nodeFaultTester.glm'
	# FNAME = 'test_ieee123nodeBetter.glm'
	# FNAME = 'test_large-R5-35.00-1.glm_CLEAN.glm'
	# FNAME = 'test_medium-R4-12.47-1.glm_CLEAN.glm'
	# FNAME = 'test_smsSingle.glm'
	# Hack: Agg backend doesn't work for interactivity. Switch to something we can use:
	# plt.switch_backend('MacOSX')
	chart = voltageDrop.drawPlot(PREFIX + FNAME, neatoLayout=True, edgeCol="Current", nodeCol=None, nodeLabs="Name", edgeLabs=None, faultLoc="node713-704", faultType="TLG", customColormap=False, scaleMin=None, scaleMax=None, rezSqIn=225, simTime='2000-01-01 0:00:00')
	chart.savefig(PREFIX + "YO_WHATS_GOING_ON.png")
	#plt.show()

def drawTable(path, workDir=None):
	#return self.log
	
	# warnings.filterwarnings("ignore")
	"""
	Create a plot or display artifact for table results.
	"""
	if path.endswith('.glm'):
		tree = feeder.parse(path)
		attachments = []
	elif path.endswith('.omd'):
		with open(path) as f:
			omd = json.load(f)
		tree = omd.get('tree', {})
		attachments = omd.get('attachments',[])
	else:
		raise Exception('Invalid input file type. We require a .glm or .omd.')

	# Reminder: fuse objects have 'phase_X_status' instead of 'phase_X_state'
	protDevices = dict.fromkeys(['fuse', 'recloser', 'switch', 'sectionalizer'], False)
	#dictionary of protective device initial states for each phase
	protDevInitStatus = {}
	#dictionary of protective devices final states for each phase after running Gridlab-D
	protDevFinalStatus = {}
	#dictionary of protective device types to help the testing and debugging process
	protDevTypes = {}
	protDevOpModes = {}
	for key in tree:
		obj = tree[key]
		obType = obj.get('object')
		if obType in protDevices.keys():
			obName = obj.get('name', '')
			protDevTypes[obName] = obType
			if obType != 'fuse':
				protDevOpModes[obName] = obj.get('operating_mode', 'INDIVIDUAL')
			protDevices[obType] = True
			protDevInitStatus[obName] = {}
			protDevFinalStatus[obName] = {}
			for phase in ['A', 'B', 'C']:
				if obType != 'fuse':
					phaseState = obj.get('phase_' + phase + '_state','CLOSED')
				else:
					phaseState = obj.get('phase_' + phase + '_status','GOOD')
				if phase in obj.get('phases', ''):
					protDevInitStatus[obName][phase] = phaseState

	for key in protDevices.keys():
		if protDevices[key]:
			for phase in ['A', 'B', 'C']:
				with open(pJoin(workDir,key+'_phase_'+phase+'_state.csv'), newline='') as statusFile:
					reader = csv.reader(statusFile)
					# loop past the header, 
					keys = []
					vals = []
					for row in reader:
						if '# timestamp' in row:
							keys = row
							i = keys.index('# timestamp')
							keys.pop(i)
							vals = next(reader)
							vals.pop(i)
					for pos,key2 in enumerate(keys):
						protDevFinalStatus[key2][phase] = vals[pos]

	html_str = """
		<table cellpadding="0" cellspacing="0">
			<thead>
				<tr>
					<th>Protective Device Name</th>
					<th>Device Type</th>
					<th>Initial States</th>
					<th>Final States</th>
					<th>Changes</th>
				</tr>
			</thead>
			<tbody>"""
	for device in protDevInitStatus.keys():
		row_str = "<tr><td>"+device+"</td><td>"
		devType = protDevTypes[device]
		if devType == 'fuse':
			row_str += "Fuse (F)</td><td>"
		elif devType == 'switch':
			row_str += "Switch (S)</td><td>"
		elif devType == 'recloser':
			row_str += "Recloser (R)</td><td>"
		elif devType == 'sectionalizer':
			row_str += "Sectionalizer (X)</td><td>"
		else:
			row_str += "Unknown</td><td>"
		for phase in protDevInitStatus[device].keys():
			row_str += "Phase " + phase + " = " + protDevInitStatus[device][phase] + "</br>"
		row_str += "</td><td>"
		for phase in protDevFinalStatus[device].keys():
			row_str += "Phase " + phase + " = " + protDevFinalStatus[device][phase] + "</br>"
		row_str += "</td>"
		noChange = True
		change_str = ""
		for phase in protDevFinalStatus[device].keys():
			try:
				if protDevInitStatus[device][phase] != protDevFinalStatus[device][phase]:
					change_str += "Phase " + phase + " : " + protDevInitStatus[device][phase] + " -> " + protDevFinalStatus[device][phase] + "</br>"
					noChange = False
			except:
				pass #key error...
		if noChange:
			row_str += "<td>No Change"
		else:
			row_str += "<td style=\"color: red;\">"
			row_str += change_str
		row_str += "</td></tr>"
		html_str += row_str
	html_str += """</tbody></table>"""
	return html_str

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
	#_testingPlot()