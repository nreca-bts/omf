"""
The storageArbitrage model calculates the costs and benefits of using energy storage to
buy energy in times of low prices and sell that energy at times of high prices.
"""

import sys, shutil, csv
from datetime import datetime as dt, timedelta
from os.path import isdir, join as pJoin
from numpy_financial import npv
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = metadata(__file__)
tooltip = ("The storageArbitrage model calculates the costs and benefits of "
	"using energy storage to buy energy in times of low prices and sell that "
	"energy at times of high prices.")
hidden = False

def work(modelDir, inputDict):
	''' Run the model in a separate process. web.py calls this to run the model.
	This function will return fast, but results take a while to hit the file system.'''
	o = {}
	(cellCapacity, dischargeRate, chargeRate, cellQuantity, cellCost) = \
		[float(inputDict[x]) for x in ('cellCapacity', 'dischargeRate', 'chargeRate', 'cellQuantity', 'cellCost')]
	inverterEfficiency = float(inputDict.get("inverterEfficiency")) / 100.0
	battEff	= float(inputDict.get("batteryEfficiency")) / 100.0 * (inverterEfficiency ** 2)
	discountRate = float(inputDict.get('discountRate')) / 100.0
	dodFactor = float(inputDict.get('dodFactor')) / 100.0
	projYears = int(inputDict.get('projYears'))
	dischargePriceThreshold	= float(inputDict.get('dischargePriceThreshold'))
	chargePriceThreshold = float(inputDict.get('chargePriceThreshold'))
	batteryCycleLife = int(inputDict.get('batteryCycleLife'))
	
	# Put demand data in to a file for safe keeping.
	with open(pJoin(modelDir,'demand.csv'),'w') as f:
		f.write(inputDict['demandCurve'])
	with open(pJoin(modelDir,'priceCurve.csv'),'w') as f:
		f.write(inputDict['priceCurve'])
	
	# Most of our data goes inside the dc "table"
	dates = [dt(2011, 1, 1)+timedelta(hours=1)*x for x in range(8760)]
	dc = []
	try:
		with open(pJoin(modelDir, 'demand.csv'), newline='') as f:
			for row, date in zip(csv.reader(f), dates):
				dc.append({ 'month': date.month - 1,
							'power': float(row[0])})
		assert len(dc) == 8760
	except:
		if str(sys.exc_info()[0]) != "<type 'exceptions.SystemExit'>":
			raise Exception("Demand CSV file is incorrect format.")
	#Add price to dc table
	try:
		with open(pJoin(modelDir,'priceCurve.csv'), newline='') as f:
			for row, d in zip(csv.reader(f), dc):
				d['price'] = float(row[0])
		assert all(['price' in r for r in dc])
	except:
		if str(sys.exc_info()[0]) != "<type 'exceptions.SystemExit'>":
			raise Exception("Price Curve File is in an incorrect format.")

	battCapacity = cellQuantity * cellCapacity * dodFactor
	battSoC = battCapacity
	for r in dc:
		#If price of energy is above price threshold and battery has charge, discharge battery
		if r['price'] >= dischargePriceThreshold:
			charge = -1*min(cellQuantity * dischargeRate, battSoC)
		elif r['price'] <= chargePriceThreshold:
			charge = min(cellQuantity * chargeRate, battCapacity-battSoC)
		else:
			charge = 0
		r['netpower'] = r['power'] + charge
		r['battSoC'] = battSoC
		battSoC += charge

	# There's definitely a nicer way to make this for loop, apologies
	monthlyCharge = []
	monthlyDischarge = []
	monthlyDischargeSavings = []
	monthlyChargeCost = []
	# Calculate the monthly cost to charge and savings by discharging
	for x in range(12):
		chargeCost = 0
		dischargeSavings = 0
		chargePower = 0
		dischargePower = 0
		for r in dc:
			if r['month'] == x:
				diff = r['netpower'] - r['power']
				if diff > 0:
					chargePower += diff
					chargeCost += diff*r['price']
				if diff < 0:
					dischargePower += -1*diff
					dischargeSavings += -1*diff*r['price']
		monthlyCharge.append(chargePower)
		monthlyDischarge.append(dischargePower)
		monthlyDischargeSavings.append(dischargeSavings)
		monthlyChargeCost.append(chargeCost)
	
	# include BattEff into calculations
	monthlyCharge = [t/battEff for t in monthlyCharge]
	monthlyChargeCost = [t/battEff for t in monthlyChargeCost]

	# Monthly Cost Comparison Table
	o['energyOffset'] = monthlyDischarge
	o['dischargeSavings'] = monthlyDischargeSavings
	o['kWhtoRecharge'] =  monthlyCharge
	o['costToRecharge'] = monthlyChargeCost
	# NPV, SPP are below

	# Demand Before and After Storage Graph
	o['demand'] = [t['power']*1000.0 for t in dc]
	o['demandAfterBattery'] = [t['netpower']*1000.0 for t in dc]
	o['batteryDischargekW'] = [d-b for d, b in zip(o['demand'], o['demandAfterBattery'])]
	o['batteryDischargekWMax'] = max(o['batteryDischargekW'])
	
	# Price Input Graph
	o['price'] = [r['price'] for r in dc]

	# Battery SoC Graph
	o['batterySoc'] = SoC = [t['battSoC']/battCapacity*100.0*dodFactor + (100-100*dodFactor) for t in dc]
	cycleEquivalents = sum([SoC[i]-SoC[i+1] for i, x in enumerate(SoC[:-1]) if SoC[i+1] < SoC[i]]) / 100.0
	o['cycleEquivalents'] = cycleEquivalents
	o['batteryLife'] = batteryCycleLife/cycleEquivalents

	# Cash Flow Graph
	yearlyDischargeSavings = sum(monthlyDischargeSavings)
	yearlyChargeCost = sum(monthlyChargeCost)
	cashFlowCurve = [yearlyDischargeSavings-yearlyChargeCost]*projYears
	cashFlowCurve.insert(0, -1*cellCost*cellQuantity)
	o['benefitNet'] = [ds-cc for cc, ds in zip(o['costToRecharge'], o['dischargeSavings'])]
	o['netCashflow'] = cashFlowCurve
	o['cumulativeCashflow'] = [sum(cashFlowCurve[:i+1]) for i, d in enumerate(cashFlowCurve)]
	o['NPV'] = npv(discountRate, cashFlowCurve)
	o['SPP'] = (cellCost*cellQuantity)/(yearlyDischargeSavings-yearlyChargeCost)
	battCostPerCycle =  cellQuantity * cellCost / batteryCycleLife
	lcoeTotCost = (cycleEquivalents*cellQuantity*cellCapacity*chargePriceThreshold) + (battCostPerCycle*cycleEquivalents)
	o['LCOE'] = lcoeTotCost / (cycleEquivalents * cellCapacity * cellQuantity)

	# Other
	o['startDate'] = '2011-01-01'
	o["stdout"] = "Success"
	o["stderr"] = ""
	return o

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","FrankScadaValidCSV_Copy.csv")) as f:
		demandCurve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","priceCurve_Copy.csv")) as f:
		priceCurve = f.read()
	defaultInputs = {
		"batteryEfficiency": "92",
		"inverterEfficiency": "97.5",
		"cellCapacity": "7",
		"discountRate": "2.5",
		"created": "2015-06-12 17:20:39.308239",
		"dischargeRate": "5",
		"modelType": modelName,
		"chargeRate": "5",
		"demandCurve": demandCurve,
		"fileName": "FrankScadaValidCSV_Copy.csv",
		"priceCurve": priceCurve,
		"priceFileName":"priceCurve_Copy.csv",
		"cellCost": "7140",
		"cellQuantity": "10",
		"runTime": "0:00:03",
		"projYears": "15",
		"chargePriceThreshold": "0.07",
		"dischargePriceThreshold":"0.15",
		"dodFactor":"100",
		"batteryCycleLife": "5000"
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
	if isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc) # Create New.
	renderAndShow(modelLoc) # Pre-run.
	runForeground(modelLoc) # Run the model.
	renderAndShow(modelLoc) # Show the output.

if __name__ == '__main__':
	_tests()
