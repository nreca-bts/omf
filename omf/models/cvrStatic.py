"""
The cvrStatic model calculates the expected costs and benefits (including energy, loss,
and peak reductions) for implementing conservation voltage reduction on a given feeder
circuit. For a longer discussion on Load Profile Effects of CVR, click here.
"""

import json, os, shutil, math, base64, platform
from copy import copy
from os.path import join as pJoin

import matplotlib
from matplotlib import pyplot as plt
import numpy as np

# OMF imports
from omf import feeder
from omf.solvers import gridlabd
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The cvrStatic model calculates the expected costs and benefits (including energy, loss, and peak reductions) for implementing conservation voltage reduction on a given feeder circuit."

def work(modelDir, inputDict):
	''' Run the model in the foreground. WARNING: can take about a minute. '''
	# Global vars, and load data from the model directory.
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict["feederName1"] = feederName
	feederPath = pJoin(modelDir,feederName+'.omd')
	with open(feederPath) as f:
		feederJson = json.load(f)
	tree = feederJson.get("tree",{})
	attachments = feederJson.get("attachments",{})
	outData = {}
	''' Run CVR analysis. '''
	# Reformate monthData and rates.
	rates = {k:float(inputDict[k]) for k in ['capitalCost', 'omCost', 'wholesaleEnergyCostPerKwh',
		'retailEnergyCostPerKwh', 'peakDemandCostSpringPerKw', 'peakDemandCostSummerPerKw',
		'peakDemandCostFallPerKw', 'peakDemandCostWinterPerKw']}
	monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
		'September', 'October', 'November', 'December']
	monthToSeason = {'January':'Winter','February':'Winter','March':'Spring','April':'Spring',
		'May':'Spring','June':'Summer','July':'Summer','August':'Summer',
		'September':'Fall','October':'Fall','November':'Fall','December':'Winter'}
	monthData = []
	for i, x in enumerate(monthNames):
		monShort = x[0:3].lower()
		season = monthToSeason[x]
		histAvg = float(inputDict.get(monShort + "Avg", 0))
		histPeak = float(inputDict.get(monShort + "Peak", 0))
		monthData.append({"monthId":i, "monthName":x, "histAverage":histAvg,
			"histPeak":histPeak, "season":season})
	# Graph the SCADA data.
	fig = plt.figure(figsize=(10,6))
	indices = [r['monthName'] for r in monthData]
	d1 = [r['histPeak']/(10**3) for r in monthData]
	d2 = [r['histAverage']/(10**3) for r in monthData]
	ticks = list(range(len(d1)))
	bar_peak = plt.bar(ticks,d1,color='gray')
	bar_avg = plt.bar(ticks,d2,color='dimgray')
	plt.legend([bar_peak[0],bar_avg[0]],['histPeak','histAverage'],bbox_to_anchor=(0., 1.015, 1., .102), loc=3,
	   ncol=2, mode="expand", borderaxespad=0.1)
	plt.xticks([t+0.5 for t in ticks],indices)
	plt.ylabel('Mean and peak historical power consumptions (kW)')
	fig.autofmt_xdate()
	plt.savefig(pJoin(modelDir,"scadaChart.png"))
	outData["histPeak"] = d1
	outData["histAverage"] = d2
	outData["monthName"] = [name[0:3] for name in monthNames]
	# Graph feeder.
	fig = plt.figure(figsize=(10,10))
	myGraph = feeder.treeToNxGraph(tree)
	feeder.latLonNxGraph(myGraph, neatoLayout=False)
	plt.savefig(pJoin(modelDir,"feederChart.png"))
	with open(pJoin(modelDir,"feederChart.png"),"rb") as inFile:
		outData["feederChart"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	# Get the load levels we need to test.
	allLoadLevels = [x.get('histPeak',0) for x in monthData] + [y.get('histAverage',0) for y in monthData]
	maxLev = _roundOne(max(allLoadLevels),'up')
	minLev = _roundOne(min(allLoadLevels),'down')
	tenLoadLevels = list(range(int(minLev),int(maxLev),int((maxLev-minLev)/10)))
	# Gather variables from the feeder.
	for key in list(tree.keys()):
		# Set clock to single timestep.
		if tree[key].get('clock','') == 'clock':
			tree[key] = {"timezone":"PST+8PDT",
				"stoptime":"'2013-01-01 00:00:00'",
				"starttime":"'2013-01-01 00:00:00'",
				"clock":"clock"}
		# Save swing node index.
		if tree[key].get('bustype','').lower() == 'swing':
			swingIndex = key
			swingName = tree[key].get('name')
		# Remove all includes.
		if tree[key].get('omftype','') == '#include':
			del key
	# Find the substation regulator and config.
	for key in tree:
		if tree[key].get('object','') == 'regulator' and tree[key].get('from','') == swingName:
			regIndex = key
			regConfName = tree[key]['configuration']
	if not regConfName: regConfName = False
	for key in tree:
		if tree[key].get('name','') == regConfName:
			regConfIndex = key
	# Set substation regulator to manual operation.
	baselineTap = float(inputDict.get("baselineTap")) # GLOBAL VARIABLE FOR DEFAULT TAP POSITION
	tree[regConfIndex] = {
		'name':tree[regConfIndex]['name'],
		'object':'regulator_configuration',
		'connect_type':'1',
		'raise_taps':'10',
		'lower_taps':'10',
		'CT_phase':'ABC',
		'PT_phase':'ABC',
		'regulation':'0.10', #Yo, 0.10 means at tap_pos 10 we're 10% above 120V.
		'Control':'MANUAL',
		'control_level':'INDIVIDUAL',
		'Type':'A',
		'tap_pos_A':str(baselineTap),
		'tap_pos_B':str(baselineTap),
		'tap_pos_C':str(baselineTap) }
	# Attach recorders relevant to CVR.
	recorders = [
		{'object': 'collector',
		'file': 'ZlossesTransformer.csv',
		'group': 'class=transformer',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'collector',
		'file': 'ZlossesUnderground.csv',
		'group': 'class=underground_line',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'collector',
		'file': 'ZlossesOverhead.csv',
		'group': 'class=overhead_line',
		'limit': '0',
		'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
		{'object': 'recorder',
		'file': 'Zregulator.csv',
		'limit': '0',
		'parent': tree[regIndex]['name'],
		'property': 'tap_A,tap_B,tap_C,power_in.real,power_in.imag'},
		{'object': 'collector',
		'file': 'ZvoltageJiggle.csv',
		'group': 'class=triplex_meter',
		'limit': '0',
		'property': 'min(voltage_12.mag),mean(voltage_12.mag),max(voltage_12.mag),std(voltage_12.mag)'},
		{'object': 'recorder',
		'file': 'ZsubstationTop.csv',
		'limit': '0',
		'parent': tree[swingIndex]['name'],
		'property': 'voltage_A,voltage_B,voltage_C'},
		{'object': 'recorder',
		'file': 'ZsubstationBottom.csv',
		'limit': '0',
		'parent': tree[regIndex]['to'],
		'property': 'voltage_A,voltage_B,voltage_C'} ]
	biggest = 1 + max([int(k) for k in tree.keys()])
	for index, rec in enumerate(recorders):
		tree[biggest + index] = rec
	# Change constant PF loads to ZIP loads. (See evernote for rationale about 50/50 power/impedance mix.)
	blankZipModel = {'object':'triplex_load',
		'name':'NAMEVARIABLE',
		'base_power_12':'POWERVARIABLE',
		'power_fraction_12': str(inputDict.get("p_percent")),
		'impedance_fraction_12': str(inputDict.get("z_percent")),
		'current_fraction_12': str(inputDict.get("i_percent")),
		'power_pf_12': str(inputDict.get("power_factor")), #MAYBEFIX: we can probably get this PF data from the Milsoft loads.
		'impedance_pf_12':str(inputDict.get("power_factor")),
		'current_pf_12':str(inputDict.get("power_factor")),
		'nominal_voltage':'120',
		'phases':'PHASESVARIABLE',
		'parent':'PARENTVARIABLE' }
	def powerClean(powerStr):
		''' take 3339.39+1052.29j to 3339.39 '''
		return powerStr[0:powerStr.find('+')]
	for key in tree:
		if tree[key].get('object','') == 'triplex_node':
			# Get existing variables.
			name = tree[key].get('name','')
			power = tree[key].get('power_12','')
			parent = tree[key].get('parent','')
			phases = tree[key].get('phases','')
			# Replace object and reintroduce variables.
			tree[key] = copy(blankZipModel)
			tree[key]['name'] = name
			tree[key]['base_power_12'] = powerClean(power)
			tree[key]['parent'] = parent
			tree[key]['phases'] = phases
	# Function to determine how low we can tap down in the CVR case:
	def loweringPotential(baseLine):
		''' Given a baseline end of line voltage, how many more percent can we shave off the substation voltage? '''
		''' testsWePass = [122.0,118.0,200.0,110.0] '''
		lower = int(math.floor((baseLine/114.0-1)*100)) - 1
		# If lower is negative, we can't return it because we'd be undervolting beyond what baseline already was!
		if lower < 0:
			return baselineTap
		else:
			return baselineTap - lower
	# Run all the powerflows.
	powerflows = []
	for doingCvr in [False, True]:
		# For each load level in the tenLoadLevels, run a powerflow with the load objects scaled to the level.
		for desiredLoad in tenLoadLevels:
			# Find the total load that was defined in Milsoft:
			loadList = []
			for key in tree:
				if tree[key].get('object','') == 'triplex_load':
					loadList.append(tree[key].get('base_power_12',''))
			totalLoad = sum([float(x) for x in loadList])
			# Rescale each triplex load:
			for key in tree:
				if tree[key].get('object','') == 'triplex_load':
					currentPow = float(tree[key]['base_power_12'])
					ratio = desiredLoad/totalLoad
					tree[key]['base_power_12'] = str(currentPow*ratio)
			# If we're doing CVR then lower the voltage.
			if doingCvr:
				# Find the minimum voltage we can tap down to:
				newTapPos = baselineTap
				for row in powerflows:
					if row.get('loadLevel','') == desiredLoad:
						newTapPos = loweringPotential(row.get('lowVoltage',114))
				# Tap it down to there.
				# MAYBEFIX: do each phase separately because that's how it's done in the field... Oof.
				tree[regConfIndex]['tap_pos_A'] = str(newTapPos)
				tree[regConfIndex]['tap_pos_B'] = str(newTapPos)
				tree[regConfIndex]['tap_pos_C'] = str(newTapPos)
			# Run the model through gridlab and put outputs in the table.
			output = gridlabd.runInFilesystem(tree, attachments=attachments,
				keepFiles=True, workDir=modelDir)
			os.remove(pJoin(modelDir,"PID.txt"))
			p = output['Zregulator.csv']['power_in.real'][0]
			q = output['Zregulator.csv']['power_in.imag'][0]
			s = math.sqrt(p**2+q**2)
			lossTotal = 0.0
			for device in ['ZlossesOverhead.csv','ZlossesTransformer.csv','ZlossesUnderground.csv']:
				for letter in ['A','B','C']:
					r = output[device]['sum(power_losses_' + letter + '.real)'][0]
					i = output[device]['sum(power_losses_' + letter + '.imag)'][0]
					lossTotal += math.sqrt(r**2 + i**2)
			## Entire output:
			powerflows.append({
				'doingCvr':doingCvr,
				'loadLevel':desiredLoad,
				'realPower':p,
				'powerFactor':p/s,
				'losses':lossTotal,
				'subVoltage': (
					output['ZsubstationBottom.csv']['voltage_A'][0] +
					output['ZsubstationBottom.csv']['voltage_B'][0] +
					output['ZsubstationBottom.csv']['voltage_C'][0] )/3/60,
				'lowVoltage':output['ZvoltageJiggle.csv']['min(voltage_12.mag)'][0]/2,
				'highVoltage':output['ZvoltageJiggle.csv']['max(voltage_12.mag)'][0]/2 })
	# For a given load level, find two points to interpolate on.
	def getInterpPoints(t):
		''' Find the two points we can interpolate from. '''
		''' tests pass on [tenLoadLevels[0],tenLoadLevels[5]+499,tenLoadLevels[-1]-988] '''
		loc = sorted(tenLoadLevels + [t]).index(t)
		if loc==0:
			return (tenLoadLevels[0],tenLoadLevels[1])
		elif loc>len(tenLoadLevels)-2:
			return (tenLoadLevels[-2],tenLoadLevels[-1])
		else:
			return (tenLoadLevels[loc-1],tenLoadLevels[loc+1])
	# Calculate peak reduction.
	for row in monthData:
		peak = row['histPeak']
		peakPoints = getInterpPoints(peak)
		peakTopBase = [x for x in powerflows if x.get('loadLevel','') == peakPoints[-1] and x.get('doingCvr','') == False][0]
		peakTopCvr = [x for x in powerflows if x.get('loadLevel','') == peakPoints[-1] and x.get('doingCvr','') == True][0]
		peakBottomBase = [x for x in powerflows if x.get('loadLevel','') == peakPoints[0] and x.get('doingCvr','') == False][0]
		peakBottomCvr = [x for x in powerflows if x.get('loadLevel','') == peakPoints[0] and x.get('doingCvr','') == True][0]
		# Linear interpolation so we aren't running umpteen million loadflows.
		x = (peakPoints[0],peakPoints[1])
		y = (peakTopBase['realPower'] - peakTopCvr['realPower'],
			 peakBottomBase['realPower'] - peakBottomCvr['realPower'])
		peakRed = y[0] + (y[1] - y[0]) * (peak - x[0]) / (x[1] - x[0])
		row['peakReduction'] = peakRed
	# Calculate energy reduction and loss reduction based on average load.
	for row in monthData:
		avgEnergy = row['histAverage']
		energyPoints = getInterpPoints(avgEnergy)
		avgTopBase = [x for x in powerflows if x.get('loadLevel','') == energyPoints[-1] and x.get('doingCvr','') == False][0]
		avgTopCvr = [x for x in powerflows if x.get('loadLevel','') == energyPoints[-1] and x.get('doingCvr','') == True][0]
		avgBottomBase = [x for x in powerflows if x.get('loadLevel','') == energyPoints[0] and x.get('doingCvr','') == False][0]
		avgBottomCvr = [x for x in powerflows if x.get('loadLevel','') == energyPoints[0] and x.get('doingCvr','') == True][0]
		# Linear interpolation so we aren't running umpteen million loadflows.
		x = (energyPoints[0], energyPoints[1])
		y = (avgTopBase['realPower'] - avgTopCvr['realPower'],
			avgBottomBase['realPower'] - avgBottomCvr['realPower'])
		energyRed = y[0] + (y[1] - y[0]) * (avgEnergy - x[0]) / (x[1] - x[0])
		row['energyReduction'] = energyRed
		lossY = (avgTopBase['losses'] - avgTopCvr['losses'],
			avgBottomBase['losses'] - avgBottomCvr['losses'])
		lossRed = lossY[0] + (lossY[1] - lossY[0]) * (avgEnergy - x[0]) / (x[1] - x[0])
		row['lossReduction'] = lossRed
	# Multiply by dollars.
	for row in monthData:
		row['energyReductionDollars'] = row['energyReduction']/1000 * (rates['wholesaleEnergyCostPerKwh'] - rates['retailEnergyCostPerKwh'])
		row['peakReductionDollars'] = row['peakReduction']/1000 * rates['peakDemandCost' + row['season'] + 'PerKw']
		row['lossReductionDollars'] = row['lossReduction']/1000 * rates['wholesaleEnergyCostPerKwh']
	# Pretty output
	def plotTable(inData):
		fig = plt.figure(figsize=(10,5))
		plt.axis('off')
		plt.tight_layout()
		plt.table(cellText=[row for row in inData[1:]],
			loc = 'center',
			rowLabels = list(range(len(inData)-1)),
			colLabels = inData[0])
	def dictalToMatrix(dictList):
		''' Take our dictal format to a matrix. '''
		matrix = [list(dictList[0].keys())]
		for row in dictList:
			matrix.append(list(row.values()))
		return matrix
	# Powerflow results.
	plotTable(dictalToMatrix(powerflows))
	plt.savefig(pJoin(modelDir,"powerflowTable.png"))
	# Monetary results.
	## To print partial money table
	monthDataMat = dictalToMatrix(monthData)
	dimX = len(monthDataMat)
	dimY = len(monthDataMat[0])
	monthDataPart = []
	for k in range (0,dimX):
		monthDatatemp = []
		for m in range (4,dimY):
			monthDatatemp.append(monthDataMat[k][m])
		monthDataPart.append(monthDatatemp)
	plotTable(monthDataPart)
	plt.savefig(pJoin(modelDir,"moneyTable.png"))
	outData["monthDataMat"] = dictalToMatrix(monthData)
	outData["monthDataPart"] = monthDataPart
	# Graph the money data.
	fig = plt.figure(figsize=(10,8))
	indices = [r['monthName'] for r in monthData]
	d1 = [r['energyReductionDollars'] for r in monthData]
	d2 = [r['lossReductionDollars'] for r in monthData]
	d3 = [r['peakReductionDollars'] for r in monthData]
	ticks = list(range(len(d1)))
	bar_erd = plt.bar(ticks,d1,color='red')
	bar_lrd = plt.bar(ticks,d2,color='green')
	d2_abs = np.abs(d2)
	bar_prd = plt.bar(ticks,d3,color='blue',yerr=d2_abs)
	plt.legend([bar_prd[0], bar_lrd[0], bar_erd[0]], ['peakReductionDollars','lossReductionDollars','energyReductionDollars'],bbox_to_anchor=(0., 1.015, 1., .102), loc=3,
	   ncol=2, mode="expand", borderaxespad=0.1)
	plt.xticks([t+0.5 for t in ticks],indices)
	plt.ylabel('Utility Savings ($)')
	plt.tight_layout()
	fig.autofmt_xdate()
	plt.savefig(pJoin(modelDir,"spendChart.png"))
	outData["energyReductionDollars"] = d1
	outData["lossReductionDollars"] = d2
	outData["peakReductionDollars"] = d3
	# Graph the cumulative savings.
	fig = plt.figure(figsize=(10,5))
	annualSavings = sum(d1) + sum(d2) + sum(d3)
	annualSave = lambda x:(annualSavings - rates['omCost']) * x - rates['capitalCost']
	simplePayback = rates['capitalCost']/(annualSavings - rates['omCost'])
	plt.xlabel('Year After Installation')
	plt.xlim(0,30)
	plt.ylabel('Cumulative Savings ($)')
	plt.plot([0 for x in range(31)],c='gray')
	plt.axvline(x=simplePayback, ymin=0, ymax=1, c='gray', linestyle='--')
	plt.plot([annualSave(x) for x in range(31)], c='green')
	plt.savefig(pJoin(modelDir,"savingsChart.png"))
	outData["annualSave"] = [annualSave(x) for x in range(31)]
	# For autotest, there won't be such file.
	return outData

def _roundOne(x,direc):
	''' Round x in direc (up/down) to 1 sig fig. '''
	thou = 10.0**math.floor(math.log10(x))
	decForm = x/thou
	if direc=='up':
		return math.ceil(decForm)*thou
	elif direc=='down':
		return math.floor(decForm)*thou
	else:
		raise Exception

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	colomaMonths = {"janAvg": 914000.0, "janPeak": 1290000.0,
		"febAvg": 897000.00, "febPeak": 1110000.0,
		"marAvg": 731000.00, "marPeak": 1030000.0,
		"aprAvg": 864000.00, "aprPeak": 2170000.0,
		"mayAvg": 1620000.0, "mayPeak": 4580000.0,
		"junAvg": 2210000.0, "junPeak": 5550000.0,
		"julAvg": 3570000.0, "julPeak": 6260000.0,
		"augAvg": 3380000.0, "augPeak": 5610000.0,
		"sepAvg": 1370000.0, "sepPeak": 3740000.0,
		"octAvg": 1030000.0, "octPeak": 1940000.0,
		"novAvg": 1020000.0, "novPeak": 1340000.0,
		"decAvg": 1030000.0, "decPeak": 1280000.0}
	# friendshipMonths = {"janAvg": 2740000.0, "janPeak": 4240000.0,
	# 	"febAvg": 2480000.0, "febPeak": 3310000.0,
	# 	"marAvg": 2030000.0, "marPeak": 2960000.0,
	# 	"aprAvg": 2110000.0, "aprPeak": 3030000.0,
	# 	"mayAvg": 2340000.0, "mayPeak": 4080000.0,
	# 	"junAvg": 2770000.0, "junPeak": 5810000.0,
	# 	"julAvg": 3970000.0, "julPeak": 6750000.0,
	# 	"augAvg": 3270000.0, "augPeak": 5200000.0,
	# 	"sepAvg": 2130000.0, "sepPeak": 4900000.0,
	# 	"octAvg": 1750000.0, "octPeak": 2340000.0,
	# 	"novAvg": 2210000.0, "novPeak": 3550000.0,
	# 	"decAvg": 2480000.0, "decPeak": 3370000.0}
	defaultInputs = {
		"modelType": modelName,
		"feederName1": "ABEC Columbia",
		"runTime": "",
		"capitalCost": 30000,
		"omCost": 1000,
		"wholesaleEnergyCostPerKwh": 0.06,
		"retailEnergyCostPerKwh": 0.10,
		"peakDemandCostSpringPerKw": 5.0,
		"peakDemandCostSummerPerKw": 10.0,
		"peakDemandCostFallPerKw": 6.0,
		"peakDemandCostWinterPerKw": 8.0,
		"baselineTap": 3.0,
		"z_percent": 0.5,
		"i_percent": 0.0,
		"p_percent": 0.5,
		"power_factor": 0.9}
	for key in colomaMonths:
		defaultInputs[key] = colomaMonths[key]
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
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
