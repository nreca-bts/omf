''' Evaluate demand response energy and economic savings available using PNNL VirtualBatteries (VBAT) model. '''

import shutil, csv, pulp, os
from os.path import join as pJoin
import numpy as np
from numpy_financial import npv
#import platform, subprocess
#from numpy import arctan as atan, array

from omf.solvers import VB
from omf import forecast as fc
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Calculate the energy storage capacity for a collection of thermostatically controlled loads."

def pyVbat(modelDir, i):
	vbType = i['load_type']
	with open(pJoin(modelDir, 'temp.csv'), newline='') as f:
		ambientList = []
		for r in csv.reader(f):
			if r:
				ambientList.append(float(r[0]))
		ambient = np.array(ambientList)
	variables = [i['capacitance'], i['resistance'], i['power'], i['cop'], 
		i['deadband'], float(i['setpoint']), i['number_devices']]
	variables = [float(v) for v in variables]
	variables.insert(0, ambient)

	if vbType == '1':
		return VB.AC(*variables).generate() # air conditioning
	elif vbType == '2':
		return VB.HP(*variables).generate() # heat pump
	elif vbType == '3':
		return VB.RG(*variables).generate() # refrigerator
	elif vbType == '4':
		ambient = np.array([[i]*60 for i in list(variables[0])]).reshape(365*24*60, 1)
		variables[0] = ambient
		variables.append(ambient)
		file = pJoin(__neoMetaModel__._omfDir,'static','testFiles',"Flow_raw_1minute_BPA.csv")
		water = np.genfromtxt(file, delimiter=',')
		variables.append(water)
		return VB.WH(*variables).generate() # water heater

def pulpFunc(inputDict, demand, P_lower, P_upper, E_UL, monthHours):
	### Di's Modified dispatch code	
	alpha = 1-(1/(float(inputDict["capacitance"])*float(inputDict["resistance"])))  #1-(deltaT/(C*R)) hourly self discharge rate
	# LP Variables
	model = pulp.LpProblem("Demand charge minimization problem", pulp.LpMinimize)
	VBpower = pulp.LpVariable.dicts("ChargingPower", range(8760)) # decision variable of VB charging power; dim: 8760 by 1
	VBenergy = pulp.LpVariable.dicts("EnergyState", range(8760)) # decision variable of VB energy state; dim: 8760 by 1
	VBdispatch = pulp.LpVariable.dicts("NumberTimesDispatched", range(8760), lowBound=0) #upBound=1.5)

	for i in range(8760):
		VBpower[i].lowBound = -1*P_lower[i]
		VBpower[i].upBound = P_upper[i]
		VBenergy[i].lowBound = -1*E_UL[i]
		VBenergy[i].upBound = E_UL[i]
	pDemand = pulp.LpVariable.dicts("MonthlyDemand", range(12), lowBound=0)
	
	# Objective function: Minimize sum of peak demands
	model += pulp.lpSum(pDemand) 

	# VB energy state as a function of VB power
	model += VBenergy[0] == VBpower[0]
	for i in range(1, 8760):
		model += VBenergy[i] == alpha * VBenergy[i-1] + VBpower[i]

	for month, (s, f) in zip(range(12), monthHours):
		for i in range(s, f):
			model += pDemand[month] >= demand[i] + VBpower[i]

	model.solve()

	return [VBpower[i].varValue for i in range(8760)], [VBenergy[i].varValue for i in range(8760)]

def work(modelDir, inputDict):
	''' Run the model in its directory.'''

	out = {}
	with open(pJoin(modelDir, 'demand.csv'), 'w') as f:
		f.write(inputDict['demandCurve'].replace('\r', ''))
	with open(pJoin(modelDir, 'demand.csv'), newline='') as f:
		demand = [float(r[0]) for r in csv.reader(f)]
		assert len(demand) == 8760
	
	with open(pJoin(modelDir, 'temp.csv'), 'w') as f:
		lines = inputDict['tempCurve'].split('\n')
		out["tempData"] = [float(x) if x != '999.0' else float(inputDict['setpoint']) for x in lines if x != '']
		correctData = [x+'\n' if x != '999.0' else inputDict['setpoint']+'\n' for x in lines if x != '']
		f.write(''.join(correctData))
	assert len(correctData) == 8760

	## Get the energy rate curve from the inputs
	energy_rate_array = np.asarray([float(value) for value in inputDict['energyRateCurve'].split('\n') if value.strip()])
	out['energyRateCurve'] = energy_rate_array.tolist()

	## Get the monthly demand charge array from the inputs
	monthly_demand_charges = [float(value) for value in inputDict['monthlyDemandCharges'].split('\n') if value.strip()]
	out['monthlyDemandCharges'] = monthly_demand_charges

	# # created using calendar = {'1': 31, '2': 28, ..., '12': 31}
	# m = [calendar[key]*24 for key in calendar]
	# monthHours = [(sum(m[:i]), sum(m[:i+1])) for i, _ in enumerate(m)]
	monthHours = [(0, 744), (744, 1416), (1416, 2160), (2160, 2880), 
					(2880, 3624), (3624, 4344), (4344, 5088), (5088, 5832), 
					(5832, 6552), (6552, 7296), (7296, 8016), (8016, 8760)]

	P_lower, P_upper, E_UL = pyVbat(modelDir, inputDict)
	P_lower, P_upper, E_UL = list(P_lower), list(P_upper), list(E_UL)

	out["minPowerSeries"] = [-1*x for x in P_lower]
	out["maxPowerSeries"] = P_upper
	out["minEnergySeries"] = [-1*x for x in E_UL]
	out["maxEnergySeries"] = E_UL
	
	VBpower, out["VBenergy"] = pulpFunc(inputDict, demand, P_lower, P_upper, E_UL, monthHours)
	
	## Flip sign of VBpower values (positive now = discharging and negative = charging)
	VBpower = [i * -1. for i in VBpower]

	out["VBpower"] = VBpower
	out["dispatch_number"] = [len([p for p in VBpower[s:f] if p != 0]) for (s, f) in monthHours]

	peakDemand = [max(demand[s:f]) for s, f in monthHours] 
	energyMonthly = [sum(demand[s:f]) for s, f in monthHours]
	demandAdj = [d-p for d, p in zip(demand, out["VBpower"])]
	peakAdjustedDemand = [max(demandAdj[s:f]) for s, f in monthHours]
	energyAdjustedMonthly = [sum(demandAdj[s:f]) for s, f in monthHours]

	rms = all([x == 0 for x in P_lower]) and all([x == 0 for x in P_upper])
	out["dataCheck"] = 'VBAT returns no values for your inputs' if rms else ''
	out["demand"] = demand
	out["peakDemand"] = peakDemand
	out["energyMonthly"] = energyMonthly
	out["demandAdjusted"] = demandAdj
	out["peakAdjustedDemand"] = peakAdjustedDemand
	out["energyAdjustedMonthly"] = energyAdjustedMonthly
	out["VBdispatch"] = [dal-d for dal, d in zip(demandAdj, demand)]

	cellCost = float(inputDict["unitDeviceCost"])*float(inputDict["number_devices"])

	## Calculate the hourly and monthly energy consumption costs using the hourly $/kWh rates in the input Energy Rate Curve
	energy_cost_hourly = demand * energy_rate_array
	energy_cost_monthly = [sum(energy_cost_hourly[s:f]) for s, f in monthHours]
	adjusted_energy_cost_hourly = demandAdj * energy_rate_array
	adjusted_energy_cost_monthly = [sum(adjusted_energy_cost_hourly[s:f]) for s, f in monthHours]
	out["energyCost"] = energy_cost_monthly
	out["energyCostAdjusted"] = adjusted_energy_cost_monthly

	#out["demandCharge"] = [peak*dCharge for peak in peakDemand]
	
	out["demandCharge"] = (np.array(peakDemand)*np.array(monthly_demand_charges)).tolist()

	#out["demandChargeAdjusted"] = [pad*dCharge for pad in out["peakAdjustedDemand"]]
	out["demandChargeAdjusted"] = (np.array(out["peakAdjustedDemand"])*monthly_demand_charges).tolist()

	out["totalCost"] = [ec+dcm for ec, dcm in zip(out["energyCost"], out["demandCharge"])]
	out["totalCostAdjusted"] = [eca+dca for eca, dca in zip(out["energyCostAdjusted"], out["demandChargeAdjusted"])]
	out["savings"] = [tot-tota for tot, tota in zip(out["totalCost"], out["totalCostAdjusted"])]

	annualEarnings = sum(out["savings"]) - float(inputDict["unitUpkeepCost"])*float(inputDict["number_devices"])
	cashFlowList = [annualEarnings] * int(inputDict["projectionLength"])
	cashFlowList.insert(0, -1*cellCost)

	out["NPV"] = npv(float(inputDict["discountRate"])/100, cashFlowList)
	out["SPP"] = cellCost / annualEarnings
	out["netCashflow"] = cashFlowList
	out["cumulativeCashflow"] = [sum(cashFlowList[:i+1]) for i, d in enumerate(cashFlowList)]

	out["stdout"] = "Success"
	return out

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","vbatDispatch","Texas_1yr_Load.csv")) as f:
		demand_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","vbatDispatch","Texas_1yr_Temp.csv")) as f:
		temp_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","vbatDispatch","TOU_rate_schedule.csv")) as f:
		energy_rate_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","vbatDispatch","utility_monthly_demand_charges.csv")) as f:
		monthly_demand_charges = f.read()
		
	defaultInputs = {
		"user": "admin",
		"load_type": "1",
		"number_devices": "2000",
		"power": "5.6",
		"capacitance": "2",
		"resistance": "2",
		"cop": "2.5",
		"setpoint": "22.5",
		"deadband": "0.625",
		#"demandChargeCost":"25",
		"projectionLength":"15",
		"discountRate":"2",
		"unitDeviceCost":"150",
		"unitUpkeepCost":"5",
		"demandCurve": demand_curve,
		"tempCurve": temp_curve,
		"fileName": "Texas_1yr_Load.csv",
		"tempFileName": "Texas_1yr_Temp.csv",
		"modelType": modelName,
		'energyRateFileName': 'TOU_rate_schedule.csv',
		'energyRateCurve': energy_rate_curve,
		'monthlyDemandChargesFileName': 'utility_monthly_demand_charges.csv',
		'monthlyDemandCharges': monthly_demand_charges,
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	if os.path.isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc) # Create New.
	__neoMetaModel__.renderAndShow(modelLoc) # Pre-run.
	__neoMetaModel__.runForeground(modelLoc) # Run the model.
	__neoMetaModel__.renderAndShow(modelLoc) # Show the output.

if __name__ == '__main__':
	_tests()