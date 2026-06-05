"""
The storageDeferral model calculates the amount of energy storage capacity needed to
reduce the load on a substation transformer or line below a user-defined limit. That
limit represents a thermal or voltage limit for the hardware in question.
"""

import sys, shutil, csv, math
from os.path import isdir, join as pJoin
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = ("The storageDeferral model calculates the amount of energy storage "
	"capacity needed to reduce the load on a substation transformer or line "
	"below a user-defined limit.")
hidden = False

def work(modelDir, inputDict):
	''' Run the model in a separate process. web.py calls this to run the model.
	This function will return fast, but results take a while to hit the file system.'''
	out = {}
	(cellCapacity, dischargeRate, chargeRate, cellCost) = \
		[float(inputDict[x]) for x in ('cellCapacity', 'dischargeRate', 'chargeRate', 'cellCost')]
	
	deferralType = inputDict.get('deferralType')
	projYears = int(inputDict.get('yearsToReplace'))
	avoidedCost = int(inputDict.get('avoidedCost'))
	yearsToReplace = int(inputDict.get('yearsToReplace'))
	batteryCycleLife = int(inputDict.get('batteryCycleLife'))
	retailCost = float(inputDict.get('retailCost'))
	dodFactor = float(inputDict.get('dodFactor')) / 100.0
	carryingCost = float(inputDict.get('carryingCost')) / 100.0
	
	threshold = float(inputDict.get('transformerThreshold')) * 1000
	inverterEfficiency = float(inputDict.get("inverterEfficiency", 92)) / 100.0
	# NOTE: Inverter Efficiency is round-trip
	battEff = float(inputDict.get("batteryEfficiency", 92)) / 100.0 * inverterEfficiency ** 2
		
	dc = []

	csv_output = csvValidateAndLoad(inputDict['demandCurve'], modelDir, header=None, ignore_nans=False, save_file='demand.csv')
	demand = csv_output[0]
	dc = [{	
		'power': abs(float(x)),
		'excessDemand': abs(float(x)) - threshold,
		'negative': True if float(x) < 0 else False 
	} for x in demand]

	'''
	Find when demand surpasses the threshold. Sum the excessDemand until 
	its negative component can appropriately charge a battery that 
	supports its positive component. That is one group. Sum the positive
	excessDemand for that group. Use the group with the largest positive
	sum to calculate how many batteries to use. 
	'''
	inloop, excess, excessDemandArray = False, [], []
	for r in dc:
		if not inloop:
			# Enter loop
			if r['excessDemand'] > 0:
				excess.append(r['excessDemand'])
				inloop = True
		else:
			# in loop
			if sum(excess) > 0:
				excess.append(r['excessDemand'])
			# exit loop
			else:
				excessDemandArray.append(sum([i for i in excess if i > 0]))
				inloop, excess = False, []
	assert len(excessDemandArray) != 0, ("Demand Curve does not exceed "
		"Threshold Capacity. Lower Threshold Capacity and run again.")	
	# High threshold
	numOfUnits = math.ceil(max(excessDemandArray)/chargeRate)

	found = False
	while True:
		battCapacity = numOfUnits * cellCapacity * dodFactor
		SoC = battCapacity
		for r in dc:
			charge = (-1*min(numOfUnits*dischargeRate, SoC, r['excessDemand']) if r['power'] > threshold 
				else min(numOfUnits*chargeRate, battCapacity-SoC, -1*r['excessDemand']))
			r['netpower'] = r['power'] + charge
			SoC += charge
			r['battSoC'] = SoC

		if found:
			break

		# reduce the 
		# For particularly low thresholds this will take a while unfortunately.
		if all([r['netpower'] <= threshold for r in dc]):
			numOfUnits -= 1
		else:
			numOfUnits += 1
			found = True

	# Convert to negative where appropriate
	for r in dc:
		if r['negative']:
			r['netpower'] *= -1
			r['power'] *= -1
	
	# -------------------------- CALCULATIONS ------------------------ #	
	
	# Demand Before and After Storage Graph
	out['demand'] = [t['power'] * 1000.0 for t in dc]
	out['demandAfterBattery'] = [t['netpower'] * 1000.0 for t in dc]
	out['batteryDischargekW'] = [abs(d) - abs(dab) for d, dab in zip(out['demand'], out['demandAfterBattery'])]
	out['batteryDischargekWMax'] = max(out['batteryDischargekW'])
	out['transformerThreshold'] = threshold * 1000.0 # kW -> W

	# Battery SoC Graph
	out['batterySoc'] = SoC = [t['battSoC']/battCapacity*100.0*dodFactor + (100-100*dodFactor) for t in dc]	
	cycleEquivalents = sum([SoC[i]-SoC[i+1] for i, x in enumerate(SoC[:-1]) if SoC[i+1] < SoC[i]]) / 100.0
	out['cycleEquivalents'] = cycleEquivalents
	out['batteryLife'] = batteryCycleLife / cycleEquivalents
	
	# Avoided Cost Graph
	out['numOfBatteries'] = numOfUnits
	rechargeCost = sum([t for t in out['batteryDischargekW'] if t > 0])/battEff*retailCost
	out['batteryCost'] = numOfUnits * cellCost + rechargeCost
	out['avoidedCost'] = carryingCost * avoidedCost * yearsToReplace
	out['netAvoidedCost'] = out['avoidedCost'] - (numOfUnits * cellCost)	
	lcoeTotCost = cycleEquivalents*battCapacity*retailCost + cellCost/batteryCycleLife*cycleEquivalents
	out['LCOE'] = lcoeTotCost / (cycleEquivalents * battCapacity)

	# Other
	out['startDate'] = '2011-01-01'
	out["stdout"] = "Success"
	out["stderr"] = ""

	return out

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","negativeDemand.csv")) as f:
		demand_curve = f.read()
	defaultInputs = {
		"batteryEfficiency": "92",
		"retailCost": "0.06",
		"inverterEfficiency": "97.5",
		"cellCapacity": "7",
		"created": "2015-06-12 17:20:39.308239",
		"dischargeRate": "5",
		"modelType": modelName,
		"chargeRate": "5",
		#"deferralType": "subTransformer", "demandCurve": open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","FrankScadaValidCSV_Copy.csv")).read(),
		"deferralType": "line",
		"demandCurve": demand_curve,
		"fileName": "FrankScadaValidCSV_Copy.csv",
		"cellCost": "7140",
		"dodFactor":"100",
		"avoidedCost":"2000000",
		"transformerThreshold":"6.3",
		"batteryCycleLife": "5000",
		"carryingCost":"7",
		"yearsToReplace":"2"
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	# Blow away old test results if necessary.
	if isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc) # Create New.
	__neoMetaModel__.renderAndShow(modelLoc) # Pre-run.
	__neoMetaModel__.runForeground(modelLoc) # Run the model.
	__neoMetaModel__.renderAndShow(modelLoc) # Show the output.

if __name__ == '__main__':
	_tests()
