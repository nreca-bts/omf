"""
This model generates a communications network on top of a feeder. It calculates the cost
of the communications network equipment and if the bandwidth is sufficient to handle
each meter sending a packet simultaneously.
"""

import os, datetime, shutil
from os.path import join as pJoin
import networkx as nx
from omf import comms
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *


# Model metadata:
tooltip = "Calculate the bandwidth requirements for a communications system on a feeder"
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def work(modelDir, inputDict):
	"""
	Run the comms bandwidth model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName
	feederPath = pJoin(modelDir,feederName+'.omd')
	#delete previous saved omd/omc files so sotrage doesn't blow up - may need to adjust in future for editing
	#for file in os.listdir(modelDir):
	#	if file.endswith(".omc") or file.endswith(".omd"):
	#		os.remove(pJoin(modelDir, file))
	#shutil.copyfile(pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', feederName+'.omd'), pJoin(modelDir, feederName+'.omd'))
	feeder = comms.createGraph(feederPath)

	#set the omc objects
	comms.setSmartMeters(feeder)
	comms.setRFCollectors(feeder)
	comms.setFiber(feeder)
	comms.setRF(feeder)

	#Calculate the bandwidth capacities
	comms.setSmartMeterBandwidth(feeder, packetSize=int(inputDict['meterPacket']))
	comms.setRFCollectorCapacity(feeder, rfBandwidthCap=int(inputDict['rfCapacity']))
	comms.setFiberCapacity(feeder, fiberBandwidthCap=int(inputDict['fiberCapacity']), setSubstationBandwidth=True)
	comms.setRFEdgeCapacity(feeder)

	#calculate the bandwidth use
	comms.calcBandwidth(feeder)

	comms.saveOmc(comms.graphGeoJson(feeder), modelDir, feederName)

	#bandwidth capacity vs bandwidth use
	overloadedFiber = []
	for edge in nx.get_edge_attributes(feeder, 'fiber'):
		if feeder[edge[0]][edge[1]].get('fiber',False):
			if feeder[edge[0]][edge[1]]['bandwidthUse'] > feeder[edge[0]][edge[1]]['bandwidthCapacity']:
				overloadedFiber.append(edge)

	overloadedCollectors = []
	for rfCollector in nx.get_node_attributes(feeder, 'rfCollector'):
		if feeder.nodes[rfCollector].get('rfCollector',False):
			if feeder.nodes[rfCollector]['bandwidthUse'] > feeder.nodes[rfCollector]['bandwidthCapacity']:
				overloadedCollectors.append(rfCollector)

	outData['overloadedFiber'] = overloadedFiber
	outData['overloadedCollectors'] = overloadedCollectors
	if len(overloadedFiber) == 0:
		outData['fiberStatus'] = 'passed'
	else:
		outData['fiberStatus'] = 'insufficient'
	if len(overloadedCollectors) == 0:
		outData['collectorStatus'] = 'passed'
	else:
		outData['collectorStatus'] = 'insufficient'

	#cost calculations

	outData['fiber_cost'] = comms.getFiberCost(feeder, float(inputDict.get('fiber_cost', 0)))
	outData['rf_collector_cost'] = comms.getrfCollectorsCost(feeder, float(inputDict.get('rf_collector_cost', 0)))
	outData['smart_meter_cost'] = comms.getsmartMetersCost(feeder, float(inputDict.get('smart_meter_cost', 0)))

	outData['total_cost'] = outData['fiber_cost'] + outData['rf_collector_cost'] + outData['smart_meter_cost']

	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"modelType": modelName,
		"fiberCapacity": 10**6,
		"rfCapacity": 10**3*5,
		"meterPacket": 10,
		"feederName1":"Olin Barre LatLon",
		"fiber_cost": 3,
		"rf_collector_cost": 30000,
		"smart_meter_cost": 1000,
		"created":str(datetime.datetime.now())
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', defaultInputs['feederName1']+'.omd'), pJoin(modelDir, defaultInputs['feederName1']+'.omd'))
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
	__neoMetaModel__.renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
