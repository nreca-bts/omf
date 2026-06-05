"""
This model takes in historical demand data (hourly for a year) and calculates what
demand changes in residential customers could be expected due to demand response
programs. Program types the model can calculate are time of use pricing (TOU), peak time
rebates (PTR), direct load control (DLC) or critical peak pricing (CPP). These
calculations are done using the Brattle Group's PRISM model.
"""

import json, shutil, datetime, csv, calendar, math, operator, copy
from pathlib import Path
from os.path import join as pJoin
#from dateutil.parser import parse
from numpy_financial import npv
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The demandResponse model takes in historical demand data (hourly for a year) and calculates what demand changes in residential customers could be expected due to demand response programs. "

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# Get variables.
	lifeSpan = int(inputDict.get('lifeSpan',25))
	lifeYears = list(range(1, 1 + lifeSpan))
	hours = list(range(0, 24))
	DrTechCost = float(inputDict.get('DrPurchInstallCost'))
	demandCharge = float(inputDict.get('demandCharge'))
	retailCost = float(inputDict.get('retailCost'))
	AnnDROM = float(inputDict.get('AnnualDROperationCost'))
	SubElas = float(inputDict.get('SubstitutionPriceElasticity'))
	DayElas = float(inputDict.get('DailyPriceElasticity'))
	wholesaleCost = float(inputDict.get('WholesaleEnergyCost'))
	ManagLoad = float(inputDict.get('LoadunderManagement')) / 100.0
	DiscountRate = float(inputDict.get('DiscountRate')) / 100
	ScalingAnnual = float(inputDict.get('ScalingAnnual'))/ 100
	PeakRate = float(inputDict.get('PeakRate'))
	OffPeakRate = float(inputDict.get('OffPeakRate'))
	startmonth= int(inputDict.get('startMonth'))
	stopmonth = int(inputDict.get('stopMonth'))
	starthour = int(inputDict.get('startHour'))
	stophour = int(inputDict.get('stopHour'))
	rateCPP = float(inputDict.get('rateCPP'))
	rate24hourly = [float(x) for x in inputDict.get('rate24hourly').split(',')]
	ratePTR = float(inputDict.get('ratePTR'))
	numCPPDays = int(inputDict.get('numCPPDays'))
	rateStruct = inputDict.get('rateStruct')
	# Price vector creation.
	OffPeakDailyPrice1 = [OffPeakRate for x in hours[0:starthour]]
	PeakDailyPrice = [PeakRate for x in hours[starthour-1:stophour]]
	OffPeakDailyPrice2 = [OffPeakRate for x in hours[stophour+1:24]]
	ProgramPrices =[]
	ProgramPrices.extend(OffPeakDailyPrice1)
	ProgramPrices.extend(PeakDailyPrice)
	ProgramPrices.extend(OffPeakDailyPrice2)
	# Setting up the demand curve.
	demandFile = Path(modelDir, inputDict['demandCurveDataFileName'])
	try:
		demandList = []
		with open(demandFile, newline='') as inFile:
			reader = csv.reader(inFile)
			for row in reader:
				demandList.append(row) #######demandList.append({'datetime': parse(row['timestamp']), 'power': float(row['power'])})
			if len(demandList)!=8760: raise Exception
	except:
		errorMessage = "CSV file is incorrect format. Please see valid format definition at <a target='_blank' href='https://github.com/dpinney/omf/wiki/Models-~-demandResponse#walkthrough'>OMF Wiki demandResponse</a>"
		raise Exception(errorMessage)

	demandCurve = [float(x[0]) for x in demandList]
	outData['startDate'] = '2011-01-01'######demandList[0]['datetime'].isoformat()
	# Run the PRISM model.
	allPrismOutput = prism({
		'rateStructure': rateStruct, # options: 2tier, 2tierCPP, PTR, 3tier, 24hourly
		'elasticitySubWOCPP': SubElas, # Substitution elasticty during non-CPP days.
		'elasticityDailyWOCPP': DayElas, # Daily elasticity during non-CPP days.
		'elasticitySubWCPP': SubElas, # Substitution elasticty during CPP days. Only required for 2tierCPP
		'elasticityDailyWCPP': DayElas, # Daily elasticity during non-CPP days. Only reuquired for 2tierCPP
		'startMonth': startmonth, # 1-12. Beginning month of the cooling season when the DR program will run.
		'stopMonth': stopmonth, # 1-12. Ending month of the cooling season when the DR program will run.
		'startHour': starthour, # 0-23. Beginning hour for on-peak and CPP rates.
		'stopHour': stophour, # 0-23. Ending hour for on-peak and CPP rates.
		'rateFlat': retailCost, # pre-DR Time-independent rate paid by residential consumers.
		'rateOffPeak': OffPeakRate,
		'rateOnPeak': PeakRate, # Peak hour rate on non-CPP days.
		'rateCPP': rateCPP, # Peak hour rate on CPP days. Only required for 2tierCPP
		'rate24hourly': rate24hourly, #Hourly energy price, only needed for 24hourly
		'ratePTR': ratePTR, # Only required for PTR. $/kWh payment to customers for demand reduction on PTR days. Value is entered as a positive value, just like the other rate values, even though it is a rebate.
		'numCPPDays': numCPPDays, # Number of CPP days in a cooling season. Only required for 2tierCPP
		'origLoad': demandCurve }) # 8760 load values
	fullParticipationModLoad = allPrismOutput['modLoad']
	modifiedLoad = [x*ManagLoad+y*(1-ManagLoad) for x,y in zip(fullParticipationModLoad,demandCurve)]
	# with open('modifiedLoad.csv', 'wb') as outFile:
	# 	for row in modifiedLoad:
	# 		outfile.write(str(row) + '\n')
	diff = [y-x for x,y in zip(modifiedLoad,demandCurve)]
	# Demand Before and After Program Plot
	outData['modifiedLoad'] = modifiedLoad
	outData['demandLoad'] = demandCurve
	outData['difference'] = diff
	outData['differenceMax'] = round(max(diff),0)
	outData['differenceMin'] = round(min(diff),0)
	# Getting the hourly prices for the whole year (8760 prices)
	ProgPricesArrayYear = ProgramPrices*365
	OneYearwholesaleCost = [wholesaleCost for x in range(8760)]
	AnnualEnergy = sum(demandCurve)
	demandCurveJanuary = max(demandCurve[0:744])
	demandCurveFebruary = max(demandCurve[745:1416])
	demandCurveMarch = max(demandCurve[1417:2160])
	demandCurveApril = max(demandCurve[2161:2880])
	demandCurveMay = max(demandCurve[2881:3624])
	demandCurveJune = max(demandCurve[3625:4344])
	demandCurveJuly = max(demandCurve[4345:5088])
	demandCurveAugust = max(demandCurve[5089:5832])
	demandCurveSeptember = max(demandCurve[5833:6552])
	demandCurveOctober = max(demandCurve[6553:7296])
	demandCurveNovmber = max(demandCurve[6553:7296])
	demandCurveDecember = max(demandCurve[7297:8760])
	maxMontlyDemand = [demandCurveJanuary,demandCurveFebruary,demandCurveMarch,
		demandCurveApril,demandCurveMay,demandCurveJune,demandCurveJuly,
		demandCurveAugust,demandCurveSeptember,demandCurveOctober,
		demandCurveNovmber,demandCurveDecember]
	annualDemandCost = demandCharge * sum(maxMontlyDemand)
	PowerCost = - (AnnualEnergy * wholesaleCost + annualDemandCost)
	# Calculating the maximum montly peaks after applying DR
	modifiedLoadJanuary = max(modifiedLoad[0:744])
	modifiedLoadFebruary = max(modifiedLoad[745:1416])
	modifiedLoadMarch = max(modifiedLoad[1417:2160])
	modifiedLoadApril = max(modifiedLoad[2161:2880])
	modifiedLoadMay = max(modifiedLoad[2881:3624])
	modifiedLoadJune = max(modifiedLoad[3625:4344])
	modifiedLoadJuly = max(modifiedLoad[4345:5088])
	modifiedLoadAugust = max(modifiedLoad[5089:5832])
	modifiedLoadSeptember = max(modifiedLoad[5833:6552])
	modifiedLoadOctober = max(modifiedLoad[6553:7296])
	modifiedLoadNovmber = max(modifiedLoad[6553:7296])
	modifiedLoadDecember = max(modifiedLoad[7297:8760])
	maxMontlyDemandDR = [modifiedLoadJanuary,modifiedLoadFebruary,modifiedLoadMarch,
		modifiedLoadApril,modifiedLoadMay,modifiedLoadJune,modifiedLoadJuly,
		modifiedLoadAugust,modifiedLoadSeptember,modifiedLoadOctober,
		modifiedLoadNovmber,modifiedLoadDecember]
	# Calculating the Base Case Profit
	EnergySale = sum(demandCurve) * retailCost
	EnergyCost = sum(demandCurve) * wholesaleCost
	PeakDemandCharge = sum([x*demandCharge for x in maxMontlyDemand])
	BaseCaseProfit = EnergySale - EnergyCost - PeakDemandCharge
	# Calculating the DR Case Profit
	EnergySaleDR = sum([z[0]*z[1] for z in zip(modifiedLoad,ProgPricesArrayYear)])
	PeakDemandChargeDR = sum([x*demandCharge for x in maxMontlyDemandDR])
	energyCostDR = sum(modifiedLoad) * wholesaleCost
	DRCaseProfit = EnergySaleDR - PeakDemandChargeDR
	# Outputs of First Year Financial Impact table.
	outData["BaseCase"] = [AnnualEnergy, EnergySale, abs(EnergyCost), PeakDemandCharge, 0]
	outData["DRCase"] = [sum(modifiedLoad),EnergySaleDR, abs(energyCostDR), PeakDemandChargeDR, DrTechCost]
	# Calculating the Benefit Cashflow and Total benefit
	energySaleDRyear = [x*y for x,y in zip(ProgPricesArrayYear, demandCurve)]
	oneYearRetail = [retailCost for x in range(8760)]
	energySaleArray = [x*y for x,y in zip(oneYearRetail, demandCurve)]
	energySaleChange = sum(energySaleDRyear) - sum(energySaleArray)
	peakDemandRed = PeakDemandCharge - PeakDemandChargeDR
	# Calculating the Purchase Cost, Operation and Maint. Cost and Total Cost
	outData["AnnualOpCost"] = [- AnnDROM for x in lifeYears[0:]]
	LifetimeOperationCost = (sum(outData["AnnualOpCost"]))
	outData["LifetimeOperationCost"] = abs(LifetimeOperationCost)
	outData["lifePurchaseCosts"] = [-1.0 * DrTechCost] + [0 for x in lifeYears[1:]]
	outData["TotalCost"] = abs(outData["LifetimeOperationCost"] + DrTechCost)
	# Outputs of the Program Lifetime Cash Flow figure
	outData["EnergySaleChangeBenefit"] = [energySaleChange * ScalingAnnual ** x for x in range(lifeSpan)]
	outData["PeakDemandReduction"] = [peakDemandRed * ScalingAnnual ** x for x in range(lifeSpan)]
	BenefitCurve = [x+y for x,y in zip(outData["EnergySaleChangeBenefit"], outData["PeakDemandReduction"])]
	outData["TotalBenefit"] = sum(BenefitCurve)
	outData["BenefittoCostRatio"] = float(outData["TotalBenefit"] / outData["TotalCost"])
	netBenefit = [x+y+z for x,y,z in zip(outData["AnnualOpCost"],outData["lifePurchaseCosts"],BenefitCurve)]
	outData["npv"] = npv(DiscountRate, netBenefit)
	outData["cumulativeNetBenefit"] = [sum(netBenefit[0:i+1]) for i,d in enumerate(netBenefit)]
	outData["SimplePaybackPeriod"] = DrTechCost / (outData["TotalBenefit"] / lifeSpan)
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def prism(prismDRDict):
	''' Calculate demand changes based on Brattle's PRISM. '''
	# Calculate times.
	startDate = datetime.date(2009,prismDRDict['startMonth'],1)
	lastDay = calendar.monthrange(2009, prismDRDict['stopMonth'])
	stopDate = datetime.date(2009,prismDRDict['stopMonth'],lastDay[1])
	dayCount = stopDate - startDate
	startIndex = startDate - datetime.date(2009,1,1)
	stopIndex = stopDate  - datetime.date(2009,1,1)
	prismDRDict['startIndex'] = (startIndex.days * 24)
	if (startDate <= stopDate):
		prismDRDict['dayCount'] = dayCount.days + 1
		prismDRDict['stopIndex'] = (stopIndex.days * 24) + 23
		prismDRDict['numMonths'] = prismDRDict['stopMonth'] - prismDRDict['startMonth'] + 1
	else:
		prismDRDict['dayCount']= 365 - dayCount.days + 1
		prismDRDict['stopIndex'] = (stopIndex.days * 24) + 23
		prismDRDict['numMonths'] = (12 - prismDRDict['startMonth'] + 1) + prismDRDict['startMonth']
	if prismDRDict['rateStructure'] != '24hourly':
		prismDRDict['numHoursOn'] = prismDRDict['stopHour'] - prismDRDict['startHour'] + 1
		prismDRDict['numHoursOff'] = (24 - prismDRDict['numHoursOn'])
	if prismDRDict['rateStructure'] == '2tierCPP'  or prismDRDict['rateStructure'] == 'PTR':
		prismDRDict['hrsOnPeakWCPP'] = prismDRDict['numHoursOn'] * prismDRDict['numCPPDays']
		prismDRDict['hrsOffPeakWCPP'] = prismDRDict['numHoursOff'] * prismDRDict['numCPPDays']
		prismDRDict['hrsOnPeakWOCPP'] = ((prismDRDict['stopHour'] - prismDRDict['startHour'] + 1) * prismDRDict['dayCount']) - prismDRDict['hrsOnPeakWCPP']
		prismDRDict['hrsOffPeakWOCPP'] = ((prismDRDict['dayCount'] * 24) - prismDRDict['hrsOnPeakWOCPP']) - prismDRDict['hrsOffPeakWCPP']
		prismDRDict['hrsOnPeakPerMonthWCPP'] = float(prismDRDict['hrsOnPeakWCPP']) / float(prismDRDict['numMonths'])
		prismDRDict['hrsOffPeakPerMonthWCPP'] = float(prismDRDict['hrsOffPeakWCPP']) / float(prismDRDict['numMonths'])
	elif prismDRDict['rateStructure'] == '24hourly':
		prismDRDict['hrsOn'] = 1 * prismDRDict['dayCount'] #Only one hour per day at a given price
		prismDRDict['hrsOff'] = 23 * prismDRDict['dayCount']
		prismDRDict['numHoursOn'] = 1 #Only one hour at a given price each day
		prismDRDict['numHoursOff'] = 23
	if prismDRDict['rateStructure'] != '24hourly':
		prismDRDict['hrsOnPeakPerMonthWOCPP'] = float(prismDRDict['hrsOnPeakWOCPP']) / float(prismDRDict['numMonths'])
		prismDRDict['hrsOffPeakPerMonthWOCPP'] = float(prismDRDict['hrsOffPeakWOCPP']) / float(prismDRDict['numMonths'])
	# Do 2tierCPP. Finds largest load days and designate them CPP days.
	if prismDRDict['rateStructure'] == '2tierCPP' or prismDRDict['rateStructure'] == 'PTR':
		prismDRDict['cppHours'] = []
		prismDRDict['cppDayIdx'] = []
		maxCount = 0
		tempLoad = list(prismDRDict['origLoad'])
		while maxCount < prismDRDict['numCPPDays']:
			maxIndex, maxLoad = max(enumerate(tempLoad), key=operator.itemgetter(1))
			maxIndex = (maxIndex // 24) * 24 #First hour of day.
			tempLoad[maxIndex:maxIndex + 24] = list([0] * 24) #Zero-ing out so that we don't consider this day again
			if prismDRDict['startIndex'] <= prismDRDict['stopIndex']:
				if maxIndex >= prismDRDict['startIndex'] and maxIndex <= prismDRDict['stopIndex']: #max day was in DR season
					prismDRDict['cppHours'].append([maxIndex+prismDRDict['startHour'], maxIndex+prismDRDict['stopHour']])
					for idx in range(0,24):
						prismDRDict['cppDayIdx'].append(maxIndex + idx)
					maxCount+=1
			else:
				if maxIndex >= prismDRDict['startIndex'] or maxIndex <= prismDRDict['stopIndex']: #max day was in DR season
					prismDRDict['cppHours'].append([maxIndex+prismDRDict['startHour'], maxIndex+prismDRDict['stopHour']])
					for idx in range(0,24):
						prismDRDict['cppDayIdx'].append(maxIndex + idx)
					maxCount+=1
	# Calculate energy.
	prismDRDict['onPeakWOCPPEnergy'] = 0.0
	prismDRDict['offPeakWCPPEnergy'] = 0.0
	prismDRDict['offPeakWOCPPEnergy'] = 0.0
	prismDRDict['impactFactorOnPeakWOCPP'] = 0.0
	prismDRDict['impactFactorOffPeakWOCPP'] = 0.0
	prismDRDict['onPeakWCPPEnergy'] = 0.0
	hourlyEnergy = list([0] * 24)
	for idx, load in enumerate(prismDRDict['origLoad']):
		if prismDRDict['startIndex'] <= prismDRDict['stopIndex']:
			if idx >= prismDRDict['startIndex'] and idx <= prismDRDict['stopIndex']: #is hour of year in the DR season?
				inDRSeason = 1
			else:
				inDRSeason = 0
		else:
			if idx >= prismDRDict['startIndex'] or idx <= prismDRDict['stopIndex']: #is hour of year in the DR season?
				inDRSeason = 1
			else:
				inDRSeason = 0
		if inDRSeason == 1:
			hourOfDay = idx % 24
			if prismDRDict['rateStructure'] == '2tierCPP' or prismDRDict['rateStructure'] == 'PTR':
				if idx in prismDRDict['cppDayIdx']:
					if (hourOfDay >= prismDRDict['startHour']) and (hourOfDay <= prismDRDict['stopHour']):
						prismDRDict['onPeakWCPPEnergy'] += load
					else:
						prismDRDict['offPeakWCPPEnergy'] += load
				else:
					if (hourOfDay >= prismDRDict['startHour']) and (hourOfDay <= prismDRDict['stopHour']):
						prismDRDict['onPeakWOCPPEnergy'] += load
					else:
						prismDRDict['offPeakWOCPPEnergy'] += load
			elif prismDRDict['rateStructure'] == '24hourly':
				hourlyEnergy[hourOfDay] += load
			else:
				if (hourOfDay >= prismDRDict['startHour']) and (hourOfDay <= prismDRDict['stopHour']):
					prismDRDict['onPeakWOCPPEnergy'] += load
				else:
					prismDRDict['offPeakWOCPPEnergy'] += load
		# else: #Load outside of cooling season not used
	if prismDRDict['rateStructure'] == '2tierCPP' or prismDRDict['rateStructure'] == 'PTR':
		prismDRDict['totalEnergy'] = prismDRDict['offPeakWOCPPEnergy'] + prismDRDict['onPeakWOCPPEnergy'] + prismDRDict['offPeakWCPPEnergy'] + prismDRDict['onPeakWCPPEnergy']
		prismDRDict['onPeakWCPPMonAvgkWh'] = prismDRDict['onPeakWCPPEnergy']/prismDRDict['numMonths']
		prismDRDict['offPeakWCPPMonAvgkWh'] = prismDRDict['offPeakWCPPEnergy']/prismDRDict['numMonths']
	elif prismDRDict['rateStructure'] == '24hourly':
		prismDRDict['totalEnergy'] = sum(hourlyEnergy)
		prismDRDict['hourlyMonAvgkWh'] = list([0]*24)
		for hour, energy in enumerate(hourlyEnergy):
			prismDRDict['hourlyMonAvgkWh'][hour] = energy/prismDRDict['numMonths']
		prismDRDict['offPeakMonAvgkWh'] = sum(prismDRDict['hourlyMonAvgkWh'])/prismDRDict['numMonths'] #For PRISM computation, defining the off-peak energy (used as elasticity baseline reference) as the average of the total energy.
	else:
		prismDRDict['totalEnergy'] = prismDRDict['offPeakWOCPPEnergy'] + prismDRDict['onPeakWOCPPEnergy']
	prismDRDict['onPeakWOCPPMonAvgkWh'] = prismDRDict['onPeakWOCPPEnergy']/prismDRDict['numMonths']
	prismDRDict['offPeakWOCPPMonAvgkWh'] = prismDRDict['offPeakWOCPPEnergy']/prismDRDict['numMonths']
	prismDRDict['totalMonAvgkWh'] = prismDRDict['totalEnergy']/prismDRDict['numMonths']
	#Calculate impact factors for Non-CPP days.
	if prismDRDict['rateStructure'] != '24hourly':
		kWhPerHrOldOnPeakWOCPP = prismDRDict['onPeakWOCPPMonAvgkWh']/prismDRDict['hrsOnPeakPerMonthWOCPP'] # B30
		kWhPerHrOldOffPeakWOCPP = prismDRDict['offPeakWOCPPMonAvgkWh']/prismDRDict['hrsOffPeakPerMonthWOCPP'] #C30
		logFactorWOCPP = math.log(kWhPerHrOldOnPeakWOCPP/kWhPerHrOldOffPeakWOCPP) + prismDRDict['elasticitySubWOCPP'] * (math.log(prismDRDict['rateOnPeak']/prismDRDict['rateOffPeak'] - math.log(prismDRDict['rateFlat']/prismDRDict['rateFlat']))) #B28
		kWhPerHrOldDailyWOCPP = ((kWhPerHrOldOnPeakWOCPP * prismDRDict['numHoursOn']) + (kWhPerHrOldOffPeakWOCPP * prismDRDict['numHoursOff']))/24 #D30
		dailyNewPeakWOCPP = ((prismDRDict['rateOnPeak'] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWOCPP) + (prismDRDict['rateOffPeak'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWOCPP)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWOCPP)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWOCPP)) #D24
		dailyOldPeakWOCPP = ((prismDRDict['rateFlat'] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWOCPP) + (prismDRDict['rateFlat'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWOCPP)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWOCPP)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWOCPP)) #D23
		kWhPerHrNewDailyWOCPP = math.exp(math.log(kWhPerHrOldDailyWOCPP) - (prismDRDict['elasticityDailyWOCPP'] * (math.log(dailyOldPeakWOCPP) - math.log(dailyNewPeakWOCPP)))) #D31
		kWhPerHrNewOffPeakWOCPP =  ((24/float(prismDRDict['numHoursOff'])) * kWhPerHrNewDailyWOCPP) / (1+((prismDRDict['numHoursOn']/float(prismDRDict['numHoursOff'])) * math.exp(logFactorWOCPP))) #C31
		kWhPerHrNewOnPeakWOCPP  = kWhPerHrNewOffPeakWOCPP * math.exp(logFactorWOCPP) #B31
		kWhDeltaOnPeakWOCPP = kWhPerHrNewOnPeakWOCPP - kWhPerHrOldOnPeakWOCPP #B32
		kWhDeltaOffPeakWOCPP = kWhPerHrNewOffPeakWOCPP - kWhPerHrOldOffPeakWOCPP #C32
		prismDRDict['impactFactorOnPeakWOCPP'] = kWhDeltaOnPeakWOCPP/kWhPerHrOldOnPeakWOCPP #B33
		prismDRDict['impactFactorOffPeakWOCPP'] = kWhDeltaOffPeakWOCPP/kWhPerHrOldOffPeakWOCPP #C33
	if prismDRDict['rateStructure'] == '24hourly':
		prismDRDict['impactFactor24hourly'] = list([0] * 24)
		prismDRDict['rateOffPeak'] = prismDRDict['rateFlat']
		kWhPerHrOldOffPeak = prismDRDict['offPeakMonAvgkWh']/prismDRDict['hrsOff']
		for hour,energy in enumerate(hourlyEnergy):
			kWhPerHrOldOnPeak = prismDRDict['hourlyMonAvgkWh'][hour]/prismDRDict['hrsOn']
			logFactor = math.log(kWhPerHrOldOnPeak/kWhPerHrOldOffPeak) + prismDRDict['elasticitySubWOCPP'] * (math.log(prismDRDict['rate24hourly'][hour]/prismDRDict['rateOffPeak'] - math.log(prismDRDict['rateFlat']/prismDRDict['rateFlat'])))
			kWhPerHrOldDaily = ((kWhPerHrOldOnPeak * prismDRDict['numHoursOn']) + (kWhPerHrOldOffPeak * prismDRDict['numHoursOff']))/24
			dailyNewPeak = ((prismDRDict['rate24hourly'][hour] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeak) + (prismDRDict['rateOffPeak'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeak)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeak)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeak))
			dailyOldPeak = ((prismDRDict['rateFlat'] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeak) + (prismDRDict['rateFlat'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeak)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeak)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeak))
			kWhPerHrNewDaily = math.exp(math.log(kWhPerHrOldDaily) - (prismDRDict['elasticityDailyWOCPP'] * (math.log(dailyOldPeak) - math.log(dailyNewPeak))))
			kWhPerHrNewOffPeak =  ((24/float(prismDRDict['numHoursOff'])) * kWhPerHrNewDaily) / (1+((prismDRDict['numHoursOn']/float(prismDRDict['numHoursOff'])) * math.exp(logFactor)))
			kWhPerHrNewOnPeak  = kWhPerHrNewOffPeak * math.exp(logFactor)
			kWhDeltaOnPeak = kWhPerHrNewOnPeak - kWhPerHrOldOnPeak
			prismDRDict['impactFactor24hourly'][hour] = kWhDeltaOnPeak/kWhPerHrOldOnPeak
	# Calculate CPP days.
	if prismDRDict['rateStructure'] == '2tierCPP' or prismDRDict['rateStructure'] == 'PTR':
		if prismDRDict['rateStructure'] == 'PTR':
			prismDRDict['rateCPP'] = prismDRDict['ratePTR'] + prismDRDict['rateFlat'] #Total value for consumer during PTR periods
		kWhPerHrOldOnPeakWCPP = prismDRDict['onPeakWCPPMonAvgkWh']/prismDRDict['hrsOnPeakPerMonthWCPP'] # B14
		kWhPerHrOldOffPeakWCPP = prismDRDict['offPeakWCPPMonAvgkWh']/prismDRDict['hrsOffPeakPerMonthWCPP'] #C14
		logFactorWCPP = math.log(kWhPerHrOldOnPeakWCPP/kWhPerHrOldOffPeakWCPP) + prismDRDict['elasticitySubWCPP'] * (math.log(prismDRDict['rateCPP']/prismDRDict['rateOffPeak'] - math.log(prismDRDict['rateFlat']/prismDRDict['rateFlat']))) #B12
		kWhPerHrOldDailyWCPP = ((kWhPerHrOldOnPeakWCPP * prismDRDict['numHoursOn']) +
								 (kWhPerHrOldOffPeakWCPP * prismDRDict['numHoursOff']))/24 #D14
		dailyNewPeakWCPP = ((prismDRDict['rateCPP'] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWCPP) + (prismDRDict['rateOffPeak'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWCPP)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWCPP)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWCPP)) #D8
		dailyOldPeakWCPP = ((prismDRDict['rateFlat'] * prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWCPP) + (prismDRDict['rateFlat'] * prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWCPP)) / ((prismDRDict['numHoursOn'] * kWhPerHrOldOnPeakWCPP)+(prismDRDict['numHoursOff'] * kWhPerHrOldOffPeakWCPP)) #D7
		kWhPerHrNewDailyWCPP = math.exp(math.log(kWhPerHrOldDailyWCPP) - (prismDRDict['elasticityDailyWCPP'] * (math.log(dailyOldPeakWCPP) - math.log(dailyNewPeakWCPP)))) #D15
		kWhPerHrNewOffPeakWCPP =  ((24/float(prismDRDict['numHoursOff'])) * kWhPerHrNewDailyWCPP) / (1+((prismDRDict['numHoursOn']/float(prismDRDict['numHoursOff'])) * math.exp(logFactorWCPP))) #C15
		kWhPerHrNewOnPeakWCPP  = kWhPerHrNewOffPeakWCPP * math.exp(logFactorWCPP) #B15
		kWhDeltaOnPeakWCPP = kWhPerHrNewOnPeakWCPP - kWhPerHrOldOnPeakWCPP #B16
		kWhDeltaOffPeakWCPP = kWhPerHrNewOffPeakWCPP - kWhPerHrOldOffPeakWCPP #C16
		prismDRDict['impactFactorOnPeakWCPP'] = kWhDeltaOnPeakWCPP/kWhPerHrOldOnPeakWCPP #B17
		prismDRDict['impactFactorOffPeakWCPP'] = kWhDeltaOffPeakWCPP/kWhPerHrOldOffPeakWCPP #C17
	# Make the modified load curve.
	prismDRDict['modLoad'] = list(prismDRDict['origLoad'])
	for idx, load in enumerate(prismDRDict['origLoad']):
		if prismDRDict['startIndex'] <= prismDRDict['stopIndex']:
			if idx >= prismDRDict['startIndex'] and idx <= prismDRDict['stopIndex']: #is hour of year in the DR season?
				inDRSeason = 1
			else:
				inDRSeason = 0
		else:
			if idx >= prismDRDict['startIndex'] or idx <= prismDRDict['stopIndex']: #is hour of year in the DR season?
				inDRSeason = 1
			else:
				inDRSeason = 0
		if inDRSeason == 1:
			hourOfDay  = idx % 24
			if prismDRDict['rateStructure'] == '2tierCPP' or prismDRDict['rateStructure'] == 'PTR':
				if idx in prismDRDict['cppDayIdx']:
					if (hourOfDay >= prismDRDict['startHour']) and (hourOfDay <= prismDRDict['stopHour']):
						prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOnPeakWCPP'])
					else:
						prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOffPeakWCPP'])
				else:
					if (hourOfDay >= prismDRDict['startHour']) and (hourOfDay <= prismDRDict['stopHour']):
						prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOnPeakWOCPP'])
					else:
						prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOffPeakWOCPP'])
			elif prismDRDict['rateStructure'] == '24hourly':
				prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactor24hourly'][hourOfDay])
			else:
				if (hourOfDay < prismDRDict['startHour']) or (hourOfDay > prismDRDict['stopHour']):
					prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOffPeakWOCPP'])
				else:
					prismDRDict['modLoad'][idx] = prismDRDict['origLoad'][idx] * (1 + prismDRDict['impactFactorOnPeakWOCPP'])
		#else: #Load outside of cooling season not modified
	return prismDRDict

def DLC(DLCDict):
	# Estimate load reduction from direct load control.
	"""
	Perform dlc processing for the demand response model.
	"""
	DLCDict['modLoad'] = list(DLCDict['origLoad'])
	DLCDict['whTotalPower'] = DLCDict['residenceCount'] * DLCDict['whPercentage'] * DLCDict['whRatingkW'] * DLCDict['whDutyCycle']
	DLCDict['hvacTotalPower'] = DLCDict['residenceCount'] * DLCDict['hvacPercentage'] * DLCDict['hvacRatingkW'] * DLCDict['hvacDutyCycle']
	for idx, load in enumerate(DLCDict['origLoad']):
		if idx in DLCDict['whControlHours']:
			DLCDict['modLoad'][idx] = load - DLCDict['whTotalPower']
		if idx in DLCDict['hvacControlHours']:
			DLCDict['modLoad'][idx] = load - DLCDict['hvacTotalPower']
	return DLCDict

def _prismTests():
	# Run Direct Load Control sim.
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	with open('./test_load.csv') as f:
		orig_load = [float(x) for x in f.readlines()]
	orig_load_copy = copy.deepcopy(orig_load)
	outputs = DLC({
		'residenceCount': 2000,
		'whPercentage': 0.30,
		'hvacPercentage': 0.20,
		'whRatingkW': 9,
		'hvacRatingkW': 4,
		'whDutyCycle': 0.1,
		'hvacDutyCycle': 0.3,
		'whControlHours': [0, 1, 2, 3, 4],
		'hvacControlHours': [6, 7, 8, 9,10],
		'origLoad': orig_load}) # 8760 load values
	# Run PRISM.
	outputs2 = prism({
		'rateStructure': '2tierCPP', # options: 2tierCPP, PTR, 24hourly
		'elasticitySubWOCPP': -0.09522, # Substitution elasticty during non-CPP days.
		'elasticityDailyWOCPP': -0.02302, # Daily elasticity during non-CPP days.
		'elasticitySubWCPP': -0.09698, # Substitution elasticty during CPP days. Only required for 2tierCPP
		'elasticityDailyWCPP': -0.01607, # Daily elasticity during non-CPP days. Only reuquired for 2tierCPP
		'startMonth': 9, # 1-12. Beginning month of the cooling season when the DR program will run.
		'stopMonth': 3, # 1-12. Ending month of the cooling season when the DR program will run.
		'startHour': 14, # 0-23. Beginning hour for on-peak and CPP rates.
		'stopHour': 18, # 0-23. Ending hour for on-peak and CPP rates.
		'rateFlat': 0.10, # pre-DR Time-independent rate paid by residential consumers.
		'rateOnPeak': 0.60, # Peak hour rate on non-CPP days.
		'rateOffPeak':0.01,
		'rateCPP': 1.80, # Peak hour rate on CPP days. Only required for 2tierCPP
		'rate24hourly': [0.074, 0.041, 0.020, 0.035, 0.100, 0.230, 0.391, 0.550, 0.688, 0.788, 0.859, 0.904, 0.941, 0.962, 0.980, 1.000, 0.999, 0.948, 0.904, 0.880, 0.772, 0.552, 0.341, 0.169], #Hourly energy price, only needed for 24hourly
		#'rate24hourly': [0.12, 0.054, 0.01, 0.04, 0.172, 0.436, 0.764, 1.086, 1.367, 1.569, 1.714, 1.805, 1.880, 1.923, 1.960, 2, 1.998, 1.895, 1.806, 1.757, 1.538, 1.089, 0.662, 0.313],
		'ratePTR': 2.65, # Only required for PTR. $/kWh payment to customers for demand reduction on PTR days. Value is entered as a positive value, just like the other rate values, even though it is a rebate.
		'numCPPDays': 10, # Number of CPP days in a cooling season. Only required for 2tierCPP
		'origLoad': orig_load_copy}) # 8760 load values

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	demandCurveFileName = "FrankScadaValidCSV_Copy.csv"
	demandCurveFilePath = Path(__neoMetaModel__._omfDir, "static", "testFiles", demandCurveFileName)
	defaultInputs = {
		"modelType": modelName,
		"retailCost": "0.1",
		"WholesaleEnergyCost": "0.07",
		"demandCurveUserDisplayName": demandCurveFileName,
		"demandCurveDataFileName": demandCurveFileName,
		"DrPurchInstallCost": "100000",
		"runTime": "0:00:03",
		"SubstitutionPriceElasticity": "-0.09522",
		"DailyPriceElasticity": "-0.02302",
		"demandCharge": "10",
		"DiscountRate":"3",
		"ScalingAnnual":"102",
		"LoadunderManagement":"100",
		"AnnualDROperationCost":"1000",
		"rateStruct": "2tierCPP",
		"PeakRate": "0.20",
		"OffPeakRate": "0.083",
		"startMonth": "2",
		"stopMonth": "4",
		"startHour": "6",
		"stopHour": "9",
		"rateCPP":"1.80",
		"numCPPDays":"10",
		"ratePTR":"2.65",
		"rate24hourly": "0.074, 0.041, 0.020, 0.035, 0.100, 0.230, 0.391, 0.550, 0.688, 0.788, 0.859, 0.904, 0.941, 0.962, 0.980, 1.000, 0.999, 0.948, 0.904, 0.880, 0.772, 0.552, 0.341, 0.169"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(demandCurveFilePath, Path(modelDir, demandCurveFileName))
	except Exception as e:
		print(f"demandRespone | new() | Could not copy file {demandCurveFileName}")
		print(f"{e}")
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
