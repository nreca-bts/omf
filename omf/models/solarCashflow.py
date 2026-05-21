"""
The solarCashflow model allows a utility to calculate what impact consumer-owned solar
systems will have on their costs. The model takes financial data from the utility as
well as information about their consumers’ typical solar system size to determine the
average monthly bill for solar and non-solar customers as well as the total cost of
power for all consumers. The model uses pvWatts, software from NREL, to calculate how
much energy the solar system will produce. The economic inputs can all be collected from
the RUS Form 7.
"""

import shutil, datetime
from os.path import join as pJoin

# OMF imports
from omf import weather
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers import pysam

# Python imports
from pathlib import Path
import numpy as np
import requests
import datetime

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The solarCashflow model allows a utility to calculate what impact member owned solar systems will have on their costs."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# lat/long get checked in nrl_get_nsrdb_data
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	# parameter validation
	sys_design = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	# We need DNI, DHI, GHI, windspeed, and temp
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_tmy", longitude=long, latitude=lat, year="tmy", api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_tmy_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	# If getting the data was successful:
	# - Combine data + system parameters into pvwatts model and execute
	if requestSuccess:
		pvwatts_model, results_df = pysam.run_pvwatts(modelDir, sys_design=sys_design, dataFile="output_tmy_data.csv")
	else:
		raise Exception("solarCashflow.py: API request failed")
	outData = {}
	# Geodata output.
	outData['latitude'] = pvwatts_model.Outputs.lat
	outData['longitude'] = pvwatts_model.Outputs.lon
	outData['elev'] = pvwatts_model.Outputs.elev
	# Set the timezone to be UTC, it won't affect calculation and display, relative offset handled in pvWatts.html
	startDateTime = "2013-01-01 00:00:00 UTC"
	# Timestamp output.
	outData = {}
	outData["timeStamps"] = [datetime.datetime.strftime(
		datetime.datetime.strptime(startDateTime[0:19],"%Y-%m-%d %H:%M:%S") +
		datetime.timedelta(**{"hours":x}),"%Y-%m-%d %H:%M:%S") + " UTC" for x in range(int(8760))]
	
	# Geodata output.
	outData['lat'] = lat
	outData['lon'] = long
	# Weather output.
	outData["climate"] = {}
	outData['climate']['Global Horizontal Radiation (W/m^2)'] = results_df["gh"].tolist() if "gh" in results_df else []
	outData['climate']['Plane of Array Irradiance (W/m^2)'] = results_df["poa"].tolist() if "poa" in results_df else []
	outData['climate']['Ambient Temperature (F)'] = results_df["tamb"].tolist() if "tamb" in results_df else []
	outData['climate']['Cell Temperature (F)'] = results_df["tcell"].tolist() if "tcell" in results_df else []
	outData['climate']['Wind Speed (m/s)'] = results_df["wspd"].tolist() if "wspd" in results_df else []
	# Power generation.
	outData['powerOutputAc'] = results_df["ac"].tolist() if "ac" in results_df else []

	solarFraction = float(inputDict.get("resPenetration", .05))/100
	fossilFraction = max(1 - solarFraction, 10**-6)
	# Monthly aggregation outputs.
	months = {"Jan":0,"Feb":1,"Mar":2,"Apr":3,"May":4,"Jun":5,"Jul":6,"Aug":7,"Sep":8,"Oct":9,"Nov":10,"Dec":11}
	totMonNum = lambda x:sum([z for (y,z) in zip(outData["timeStamps"], outData["powerOutputAc"]) if y.startswith(startDateTime[0:4] + "-{0:02d}".format(x+1))])
	outData["monthlyGeneration"] = [[a, __neoMetaModel__.roundSig(totMonNum(b),2)] for (a,b) in sorted(months.items(), key=lambda x:x[1])]
	monthlyConsumers = []
	monthlyResidentialkWhLoad = []
	monthlyResidentialRevenue = []
	monthlyTotalkWhLoad = []
	monthlyTotalRevenue = []
	for key in inputDict:
		# MAYBEFIX: data in list may not be ordered by month.
		if key.endswith("Sale"):
			monthlyConsumers.append([key[:3].title(),float(inputDict.get(key, 0))])
		elif key.endswith("KWh"):# the order of calculation matters
			monthlyResidentialkWhLoad.append([key[:3].title(),float(inputDict.get(key, 0))])
		elif key.endswith("Rev"):
			monthlyResidentialRevenue.append([key[:3].title(),float(inputDict.get(key, 0))])
		elif key.endswith("KWhT"):
			monthlyTotalkWhLoad.append([key[:3].title(),float(inputDict.get(key, 0))])
		elif key.endswith("RevT"):
			monthlyTotalRevenue.append([key[:3].title(),float(inputDict.get(key, 0))])
	outData["monthlyConsumers"] = sorted(monthlyConsumers, key=lambda x:months[x[0]])
	outData["monthlyResidentialkWhLoad"] = sorted(monthlyResidentialkWhLoad, key=lambda x:months[x[0]])
	outData["monthlyResidentialRevenue"] = sorted(monthlyResidentialRevenue, key=lambda x:months[x[0]])
	outData["monthlyTotalkWhLoad"] = sorted(monthlyTotalkWhLoad, key=lambda x:months[x[0]])
	outData["monthlyTotalRevenue"] = sorted(monthlyTotalRevenue, key=lambda x:months[x[0]])
	outData["monthlySolarkWhGenerated"] = [[sorted(months.items(), key=lambda x:x[1])[i][0], outData["monthlyGeneration"][i][1]/1000*outData["monthlyConsumers"][i][1]*solarFraction] for i in range(12)]
	outData["monthlyTotalNetLoadAfterSolar"] = [[sorted(months.items(), key=lambda x:x[1])[i][0], outData["monthlyTotalkWhLoad"][i][1] - outData["monthlySolarkWhGenerated"][i][1]] for i in range(12)]
	
	## Flow Diagram Calculations, and order of calculation matters
	retailCost 				= float(inputDict.get("retailCost"))
	solarLCoE  				= float(inputDict.get('solarLCoE'))
	customerServiceCharge	= float(inputDict.get("customServiceCharge", 0))
	solarServiceCharge		= float(inputDict.get("solarServiceCharge", 0))
	totalkWhLoad 			= sum(monthlyTotalkWhLoad[i][1] for i in range(12))
	# BAU case
	outData["BAU"] = {}
	# E23 = E11
	outData["BAU"]["totalKWhPurchased"] = float(inputDict.get("totalKWhPurchased", 1))
	# E24 = SUM(E19:P19)
	outData["BAU"]["totalKWhSales"] = totalkWhLoad
	# E25 = E23-E24
	outData["BAU"]["losses"] = float(inputDict.get("totalKWhPurchased", 0)) - totalkWhLoad
	# E26 = E25/E23
	outData["BAU"]["effectiveLossRate"] = outData["BAU"]["losses"] / outData["BAU"]["totalKWhPurchased"]
	# E27 = 0
	outData["BAU"]["annualSolarGen"] = 0
	# E28 = SUM(E17:P17)
	outData["BAU"]["resNonSolarKWhSold"] = sum([monthlyResidentialkWhLoad[i][1] for i in range(12)])
	# E29 = 0
	outData["BAU"]["solarResDemand"] = 0
	# E30 = 0
	outData["BAU"]["solarResSold"] = 0
	# E31 = E24-E28
	outData["BAU"]["nonResKWhSold"] = outData["BAU"]["totalKWhSales"] - outData["BAU"]["resNonSolarKWhSold"]
	# E32 = 0
	outData["BAU"]["costSolarGen"] = 0
	# E33 = SUM(E20:P20)-SUM(E18:P18)+E10
	outData["BAU"]["nonResRev"] = sum([monthlyTotalRevenue[i][1] for i in range(12)]) - sum([monthlyResidentialRevenue[i][1] for i in range(12)]) + float(inputDict.get("otherElecRevenue"))
	# E34 = (SUM(E18:P18)-SUM(E16:P16)*E6)/SUM(E17:P17):Buggy and complicated line calculating effectiveResRate replaced with retailCost. Was somehow messing up solar fixed charges.
	# outData["BAU"]["effectiveResRate"] = (sum ([monthlyResidentialRevenue[i][1] for i in range(12)]) - sum([monthlyConsumers[i][1] for i in range(12)])*customerServiceCharge)/sum([monthlyResidentialkWhLoad[i][1] for i in range(12)])
	customerMonths = sum([monthlyConsumers[i][1] for i in range(12)])
	# E35 = E34*E28+SUM(E16:P16)*E6
	outData["BAU"]["resNonSolarRev"] = retailCost * outData["BAU"]["resNonSolarKWhSold"] + customerMonths*customerServiceCharge
	# E36 = E30*E34
	outData["BAU"]["solarResRev"] = 0
	# E37 = SUM(E48:E54)+SUM(E56:E62)-SUM(E65:E71), update after Form 7 model
	outData["BAU"]["nonPowerCosts"] = 0
	# E38 = E23-E25-E28-E30-E31
	outData["BAU"]["energyAllBal"] = 0
	# E39 = E36+E33+E35-E47-E72-E37
	outData["BAU"]["dollarAllBal"] = 0
	# E40 = 0
	outData["BAU"]["avgMonthlyBillSolarCus"] = 0
	# E41 = E35/SUM(E16:P16)
	avgCustomerCount = (customerMonths/12)
	outData["BAU"]["avgMonthlyBillNonSolarCus"] = outData["BAU"]["resNonSolarRev"] / customerMonths
	# E42 = E63/E24, update after Form 7 model
	outData["BAU"]["costofService"] = 0
	# Solar case
	outData["Solar"] = {}
	# F27 = SUM(E15:P15)
	outData["Solar"]["annualSolarGen"] = sum([outData["monthlySolarkWhGenerated"][i][1] for i in range(12)])
	# F24 = E24-F27
	outData["Solar"]["totalKWhSales"] = totalkWhLoad - outData["Solar"]["annualSolarGen"]
	# F23 =F24/(1-E26)
	outData["Solar"]["totalKWhPurchased"] = outData["Solar"]["totalKWhSales"]/ (1-outData["BAU"]["effectiveLossRate"])
	outData["totalsolarmonthly"] = [[sorted(months.items(), key=lambda x:x[1])[i][0], outData["monthlyTotalNetLoadAfterSolar"][i][1] / (1-outData["BAU"]["effectiveLossRate"])] for i in range(12)]
	# F25 = F23-F24
	outData["Solar"]["losses"] = (outData["Solar"]["totalKWhPurchased"] - outData["Solar"]["totalKWhSales"])
	# F26 = E26
	outData["Solar"]["effectiveLossRate"] = outData["BAU"]["effectiveLossRate"]
	# F28 = (1-E5)*E28
	outData["Solar"]["resNonSolarKWhSold"] = fossilFraction * outData["BAU"]["resNonSolarKWhSold"]
	# F29 = E5*E28
	outData["Solar"]["solarResDemand"] = solarFraction * outData["BAU"]["resNonSolarKWhSold"]
	# F30 = F29-F27
	outData["Solar"]["solarResSold"] = outData["Solar"]["solarResDemand"] - outData["Solar"]["annualSolarGen"]
	# F31 = E31
	outData["Solar"]["nonResKWhSold"] = outData["BAU"]["nonResKWhSold"]
	# F32 = E9*F27
	outData["Solar"]["costSolarGen"] = solarLCoE*outData["Solar"]["annualSolarGen"]
	# F33 = E33
	outData["Solar"]["nonResRev"] = outData["BAU"]["nonResRev"]
	# F34 = E34
	outData["Solar"]["effectiveResRate"] = retailCost
	# F35 = E35*(1-E5)
	outData["Solar"]["resNonSolarRev"] = outData["BAU"]["resNonSolarRev"] * fossilFraction
	# F30*E34 = Solar revenue from selling at residential rate
	solarSoldRateRev = outData["Solar"]["solarResSold"] * outData["Solar"]["effectiveResRate"]
	# (E6+E7)*SUM(E16:P16)*E5 = Solar revenue from charges
	solarChargesRev = (customerServiceCharge+solarServiceCharge)*customerMonths*solarFraction
	# F36 = F30*E34+(E6+E7)*SUM(E16:P16)*E5 = solarSoldRate + solarChargesRev
	outData["Solar"]["solarResRev"] = solarSoldRateRev + solarChargesRev
	# F37 = SUM(E48:E54)+SUM(E56:E62)-SUM(E65:E71) = E37, update after Form 7 model
	outData["Solar"]["nonPowerCosts"] = 0
	# F38 = F23-F25-F28-F30-E31
	outData["Solar"]["energyAllBal"] = 0
	# F39 = F36+E33+F35-F47-F72-E37
	outData["Solar"]["dollarAllBal"] = 0
	if (solarFraction > 0):
		# F41 = (F35)/(SUM(E16:P16)*(1-E5))
		outData["Solar"]["avgMonthlyBillNonSolarCus"] = outData["Solar"]["resNonSolarRev"] / (customerMonths* fossilFraction)
		# F42 = F30*E34/(SUM(E16:P16)*E5)+E6+E7
		outData["Solar"]["avgMonthlyBillSolarCus"] = outData["Solar"]["solarResSold"] * retailCost / (customerMonths * solarFraction) + customerServiceCharge + solarServiceCharge
		# F43 = (F27/(SUM(E16:P16)*E5))*E9
		outData["Solar"]["avgMonthlyBillSolarSolarCus"] = (outData["Solar"]["annualSolarGen"] / (customerMonths * solarFraction)) * solarLCoE
	else:
		outData["Solar"]["avgMonthlyBillNonSolarCus"] = 0
		outData["Solar"]["avgMonthlyBillSolarCus"] = 0
		outData["Solar"]["avgMonthlyBillSolarSolarCus"] = 0
	# Net Average Monthly Bill
	avgMonthlyBillSolarNet = outData["Solar"]["avgMonthlyBillSolarCus"] + outData["Solar"]["avgMonthlyBillSolarSolarCus"]
	outData["Solar"]["avgMonthlyBillSolarCus"] = avgMonthlyBillSolarNet
	# F45 = F63/F24, update after Form 7 model
	outData["Solar"]["costofService"] = 0
	## Form 7 Model
	# E46
	outData["Solar"]["powerProExpense"] = outData["BAU"]["powerProExpense"] = float(inputDict.get("powerProExpense", 0))
	# E47 != F47
	outData["BAU"]["costPurchasedPower"] = float(inputDict.get("costPurchasedPower", 0))
	# E48
	outData["Solar"]["transExpense"] = outData["BAU"]["transExpense"] = float(inputDict.get("transExpense", 0))
	# E49
	outData["Solar"]["distriExpenseO"] = outData["BAU"]["distriExpenseO"] = float(inputDict.get("distriExpenseO", 0))
	# E50
	outData["Solar"]["distriExpenseM"] = outData["BAU"]["distriExpenseM"] = float(inputDict.get("distriExpenseM", 0))
	# E51
	outData["Solar"]["customerAccountExpense"] = outData["BAU"]["customerAccountExpense"] = float(inputDict.get("customerAccountExpense", 0))
	# E52
	outData["Solar"]["customerServiceExpense"] = outData["BAU"]["customerServiceExpense"] = float(inputDict.get("customerServiceExpense", 0))
	# E53
	outData["Solar"]["salesExpense"] = outData["BAU"]["salesExpense"] = float(inputDict.get("salesExpense", 0))
	# E54
	outData["Solar"]["adminGeneralExpense"] = outData["BAU"]["adminGeneralExpense"] = float(inputDict.get("adminGeneralExpense", 0))
	# E56
	outData["Solar"]["depreAmortiExpense"] = outData["BAU"]["depreAmortiExpense"] = float(inputDict.get("depreAmortiExpense", 0))
	# E57
	outData["Solar"]["taxExpensePG"] = outData["BAU"]["taxExpensePG"] = float(inputDict.get("taxExpensePG", 0))
	# E58
	outData["Solar"]["taxExpense"] = outData["BAU"]["taxExpense"] = float(inputDict.get("taxExpense", 0))
	# E59
	outData["Solar"]["interestLongTerm"] = outData["BAU"]["interestLongTerm"] = float(inputDict.get("interestLongTerm", 0))
	# E60
	outData["Solar"]["interestConstruction"] = outData["BAU"]["interestConstruction"] = float(inputDict.get("interestConstruction", 0))
	# E61
	outData["Solar"]["interestExpense"] = outData["BAU"]["interestExpense"] = float(inputDict.get("interestExpense", 0))
	# E62
	outData["Solar"]["otherDeductions"] = outData["BAU"]["otherDeductions"] = float(inputDict.get("otherDeductions", 0))
	# E65
	outData["Solar"]["nonOpMarginInterest"] = outData["BAU"]["nonOpMarginInterest"] = float(inputDict.get("nonOpMarginInterest", 0))
	# E66
	outData["Solar"]["fundsUsedConstruc"] = outData["BAU"]["fundsUsedConstruc"] = float(inputDict.get("fundsUsedConstruc", 0))
	# E67
	outData["Solar"]["incomeEquityInvest"] = outData["BAU"]["incomeEquityInvest"] = float(inputDict.get("incomeEquityInvest", 0))
	# E68
	outData["Solar"]["nonOpMarginOther"] = outData["BAU"]["nonOpMarginOther"] = float(inputDict.get("nonOpMarginOther", 0))
	# E69
	outData["Solar"]["genTransCapCredits"] = outData["BAU"]["genTransCapCredits"] = float(inputDict.get("genTransCapCredits", 0))
	# E70
	outData["Solar"]["otherCapCreditsPatroDivident"] = outData["BAU"]["otherCapCreditsPatroDivident"] = float(inputDict.get("otherCapCreditsPatroDivident", 0))
	# E71
	outData["Solar"]["extraItems"] = outData["BAU"]["extraItems"] = float(inputDict.get("extraItems", 0))
	# Calculation
	# E45 = SUM(E20:P20)+E10
	outData["BAU"]["operRevPatroCap"] = sum([monthlyTotalRevenue[i][1] for i in range(12)])+float(inputDict.get("otherElecRevenue", 0))
	# E55 = SUM(E46:E54)
	outData["BAU"]["totalOMExpense"] = float(inputDict.get("powerProExpense")) \
		+ float(inputDict.get("costPurchasedPower")) \
		+ float(inputDict.get("transExpense")) \
		+ float(inputDict.get("distriExpenseO")) \
		+ float(inputDict.get("distriExpenseM")) \
		+ float(inputDict.get("customerAccountExpense")) \
		+ float(inputDict.get("customerServiceExpense")) \
		+ float(inputDict.get("salesExpense"))  \
		+ float(inputDict.get("adminGeneralExpense"))
	# E63 = SUM(E55:E62)
	outData["BAU"]["totalCostElecService"] = outData["BAU"]["totalOMExpense"] \
		+ float(inputDict.get("depreAmortiExpense"))\
		+ float(inputDict.get("taxExpensePG"))\
		+ float(inputDict.get("taxExpense"))\
		+ float(inputDict.get("interestLongTerm"))\
		+ float(inputDict.get("interestExpense"))\
		+ float(inputDict.get("interestConstruction"))\
		+ outData["BAU"]["otherDeductions"]
	# E64 = E45-E63
	outData["BAU"]["patCapOperMargins"] = outData["BAU"]["operRevPatroCap"] - outData["BAU"]["totalCostElecService"]
	# E72 = SUM(E64:E71)
	outData["BAU"]["patCapital"] = outData["BAU"]["patCapOperMargins"]\
		+ float(inputDict.get("nonOpMarginInterest"))\
		+ float(inputDict.get("fundsUsedConstruc"))\
		+ float(inputDict.get("incomeEquityInvest"))\
		+ float(inputDict.get("nonOpMarginOther"))\
		+ float(inputDict.get("genTransCapCredits"))\
		+ float(inputDict.get("otherCapCreditsPatroDivident"))\
		+ float(inputDict.get("extraItems"))
	# F48 = E48-F27*E34+SUM(E16:P16)*E5*E7
	outData["Solar"]["operRevPatroCap"] = outData["BAU"]["operRevPatroCap"] - retailCost * outData["Solar"]["annualSolarGen"] + customerMonths*solarFraction*solarServiceCharge
	# F47 = (F23)*E8
	inputDict["costofPower"] = float(inputDict.get("costPurchasedPower", 0)) /  float(inputDict.get("totalKWhPurchased", 0))
	outData["Solar"]["costPurchasedPower"] = outData["Solar"]["totalKWhPurchased"] * float(inputDict.get("costofPower", 0))
	inputDict["costofPower"] = round(inputDict["costofPower"],3)
	# F55 = SUM(F46:F54)
	outData["Solar"]["totalOMExpense"] = outData["Solar"]["powerProExpense"]\
		+ outData["Solar"]["costPurchasedPower"]\
		+ outData["Solar"]["transExpense"]\
		+ outData["Solar"]["distriExpenseO"]\
		+ outData["Solar"]["distriExpenseM"]\
		+ outData["Solar"]["customerAccountExpense"]\
		+ outData["Solar"]["customerServiceExpense"]\
		+ outData["Solar"]["salesExpense"]\
		+ outData["Solar"]["adminGeneralExpense"]
	# F63 = E63
	outData["Solar"]["totalCostElecService"] = outData["Solar"]["totalOMExpense"]\
		+ outData["Solar"]["depreAmortiExpense"]\
		+ outData["Solar"]["taxExpensePG"]\
		+ outData["Solar"]["taxExpense"]\
		+ outData["Solar"]["interestLongTerm"]\
		+ outData["Solar"]["interestConstruction"]\
		+ outData["Solar"]["interestExpense"]\
		+ outData["Solar"]["otherDeductions"]
	# F64 = F45 - F63
	outData["Solar"]["patCapOperMargins"] = outData["Solar"]["operRevPatroCap"] - outData["Solar"]["totalCostElecService"]
	# F72 = SUM(F64:F71)
	outData["Solar"]["patCapital"] = outData["Solar"]["patCapOperMargins"]\
		+ outData["Solar"]["nonOpMarginInterest"]\
		+ outData["Solar"]["fundsUsedConstruc"]\
		+ outData["Solar"]["incomeEquityInvest"]\
		+ outData["Solar"]["nonOpMarginOther"]\
		+ outData["Solar"]["genTransCapCredits"]\
		+ outData["Solar"]["otherCapCreditsPatroDivident"]\
		+ outData["Solar"]["extraItems"]
	# E37 = SUM(E48:E54)+SUM(E56:E62)-SUM(E65:E71), update after Form 7 model
	outData["BAU"]["nonPowerCosts"] = outData["BAU"]["transExpense"] \
		+ outData["BAU"]["distriExpenseO"] \
		+ outData["BAU"]["distriExpenseM"] \
		+ outData["BAU"]["customerAccountExpense"] \
		+ outData["BAU"]["customerServiceExpense"] \
		+ outData["BAU"]["salesExpense"] \
		+ outData["BAU"]["adminGeneralExpense"] \
		+ outData["BAU"]["depreAmortiExpense"] \
		+ outData["BAU"]["taxExpensePG"] \
		+ outData["BAU"]["taxExpense"] \
		+ outData["BAU"]["interestLongTerm"] \
		+ outData["BAU"]["interestConstruction"] \
		+ outData["BAU"]["interestExpense"] \
		+ outData["BAU"]["otherDeductions"] \
		- (outData["BAU"]["nonOpMarginInterest"] \
		+ outData["BAU"]["fundsUsedConstruc"] \
		+ outData["BAU"]["incomeEquityInvest"] \
		+ outData["BAU"]["nonOpMarginOther"] \
		+ outData["BAU"]["genTransCapCredits"] \
		+ outData["BAU"]["otherCapCreditsPatroDivident"] \
		+ outData["BAU"]["extraItems"])
	# E42 = E63/E24, update after Form 7 model
	outData["BAU"]["costofService"] = outData["BAU"]["totalCostElecService"] / outData["BAU"]["totalKWhSales"]
	# F37 = SUM(E48:E54)+SUM(E56:E62)-SUM(E65:E71) = E37, update after Form 7 model
	outData["Solar"]["nonPowerCosts"] = outData["BAU"]["nonPowerCosts"]
	# F42 = F63/F24, update after Form 7 model
	outData["Solar"]["costofService"] = outData["Solar"]["totalCostElecService"] / outData["Solar"]["totalKWhSales"]
	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	monthlyData = {
	"janSale": "46668", "janKWh": "64467874", "janRev": "8093137", "janKWhT": "85628959", "janRevT": "10464278",
	"febSale": "46724", "febKWh": "66646882", "febRev": "8812203", "febKWhT": "89818661", "febRevT": "11508047",
	"marSale": "46876", "marKWh": "62467031", "marRev": "8277498", "marKWhT": "84780954", "marRevT": "10874720",
	"aprSale": "46858", "aprKWh": "49781827", "aprRev": "6664021", "aprKWhT": "70552865", "aprRevT": "9122130",
	"maySale": "46919", "mayKWh": "41078029", "mayRev": "5567683", "mayKWhT": "63397699", "mayRevT": "8214078",
	"junSale": "46977", "junKWh": "40835343", "junRev": "5528717", "junKWhT": "64781785", "junRevT": "8332117",
	"julSale": "47013", "julKWh": "58018686", "julRev": "7585330", "julKWhT": "86140915", "julRevT": "10793395",
	"augSale": "47114", "augKWh": "67825037", "augRev": "8836269", "augKWhT": "98032727", "augRevT": "12219454",
	"sepSale": "47140", "sepKWh": "59707578", "sepRev": "7809767", "sepKWhT": "88193645", "sepRevT": "11052318",
	"octSale": "47088", "octKWh": "46451858", "octRev": "6146975", "octKWhT": "70425336", "octRevT": "8936767",
	"novSale": "47173", "novKWh": "41668828", "novRev": "5551288", "novKWhT": "65008851", "novRevT": "8228072",
	"decSale": "47081", "decKWh": "53354283", "decRev": "7014717", "decKWhT": "73335526", "decRevT": "9385203" }
	defaultInputs = {
		"modelType": modelName,
		"latitude": "33.2164",
		"longitude": "-97.1292",
		"runTime": "",
		# Single data point
		"systemSize": "10",
		"resPenetration": "5",
		"customServiceCharge": "20",
		"solarServiceCharge": "0",
		"solarLCoE": "0.09",
		"otherElecRevenue": "1544165",
		"totalKWhPurchased": "999330657",
		"retailCost": "0.10",
		# Form 7 data
		"powerProExpense": "0",
		"costPurchasedPower": "80466749",
		"transExpense": "15027",
		"distriExpenseO": "5294026",
		"distriExpenseM": "5535844",
		"customerAccountExpense": "4426441",
		"customerServiceExpense": "643418",
		"salesExpense": "127084",
		"adminGeneralExpense": "8264362",
		"depreAmortiExpense": "8975862",
		"taxExpensePG": "0",
		"taxExpense": "197924",
		"interestLongTerm": "10195988",
		"interestConstruction": "0",
		"interestExpense": "209969",
		"otherDeductions": "126640",
		"nonOpMarginInterest": "123401",
		"fundsUsedConstruc":"0",
		"incomeEquityInvest":"0",
		"nonOpMarginOther": "811043",
		"genTransCapCredits": "1015764",
		"otherCapCreditsPatroDivident": "1135379",
		"extraItems":"0" }
	for key in monthlyData:
		defaultInputs[key] = monthlyData[key]
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
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
