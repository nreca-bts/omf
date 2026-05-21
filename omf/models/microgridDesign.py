''' Design microgrid with optimal generation mix for economics and/or reliability. '''
import warnings, csv, json
from io import StringIO
from pathlib import Path
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Border, Font, PatternFill, Side
import time
import plotly
import plotly.graph_objs as go
import omf
import omf.solvers.reopt_jl as reopt_jl
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# warnings.filterwarnings('ignore')

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The microGridDesign model uses a 1yr load profile to determine the most economical combination of solar, wind, and storage technologies to use in a microgrid. The model also provides basic resiliency analysis."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	# - When this model is run though microgridup_gui.py, boolean parameters are stored as False and True.
	# - When this model is run through web.py, boolean parameters are stored as "false" and true"
	#   - Translate "false" into False and "true" into True
	for k, v in inputDict.items():
		if v == 'true':
			inputDict[k] = True
		elif v == 'false':
			inputDict[k] = False
	outData = {}
	solar = inputDict['solar'] 
	wind = inputDict['wind']
	battery = inputDict['battery']
	urdbLabelSwitch = inputDict['urdbLabelSwitch']
	outData['solar'] = inputDict['solar']
	outData['wind'] = inputDict['wind']
	outData['battery'] = inputDict['battery']
	outData['year'] = inputDict['year']
	outData['urdbLabelSwitch'] = inputDict['urdbLabelSwitch']
    # - Write loadShape.csv
	load_df = pd.read_csv(StringIO(inputDict['loadShape']), header=None)
	if load_df.shape[0] != 8760:
		raise Exception("Loadshape CSV file is incorrect format. Please see valid format definition at <a target='_blank' href='https://github.com/dpinney/omf/wiki/Models-~-demandResponse#walkthrough'>OMF Wiki demandResponse</a>")
	with (Path(modelDir).resolve(True) / 'loadShape.csv').open('w') as f:
		f.write(inputDict['loadShape'])
    # - Write criticalLoadShape.csv
	critical_load_df = pd.read_csv(StringIO(inputDict['criticalLoadShape']), header=None)
	if critical_load_df.shape[0] != 8760:
		raise Exception("Critical Loadshape CSV file is incorrect format. Please see valid format definition at <a target='_blank' href='https://github.com/dpinney/omf/wiki/Models-~-demandResponse#walkthrough'>OMF Wiki demandResponse</a>")
	with (Path(modelDir).resolve(True) / 'criticalLoadShape.csv').open('w') as f:
		f.write(inputDict['criticalLoadShape'])
	latitude = float(inputDict['latitude'])
	longitude = float(inputDict['longitude'])
	energyCost = float(inputDict['energyCost'])
	demandCost = float(inputDict['demandCost'])
	if urdbLabelSwitch:
		urdbLabel = str(inputDict['urdbLabel'])
	# TODO: Enable all instances of 'annualCostSwitch', 'energyCostMonthly', 'demandCostMonthly' in mgDesign.py once a suitable way to enter a list of 12 monthly rates is found for mgDesign.html
	# annualCostSwitch = inputDict['annualCostSwitch']
	# energyCostMonthly = inputDict['energyCostMonthly']
	# demandCostMonthly = inputDict['demandCostMonthly']
	wholesaleCost = float(inputDict['wholesaleCost'])
	omCostEscalator = float(inputDict['omCostEscalator'])
	year = int(inputDict['year'])
	analysisYears = int(inputDict['analysisYears'])
	discountRate = float(inputDict['discountRate'])
	max_runtime = int(inputDict['maxRuntimeSeconds'])
	solarMacrsOptionYears = int(inputDict['solarMacrsOptionYears'])
	windMacrsOptionYears = int(inputDict['windMacrsOptionYears'])
	batteryMacrsOptionYears = int(inputDict['batteryMacrsOptionYears'])
	dieselMacrsOptionYears = int(inputDict['dieselMacrsOptionYears'])
	solarItcPercent = float(inputDict['solarItcPercent'])
	windItcPercent = float(inputDict['windItcPercent'])
	batteryItcPercent = float(inputDict['batteryItcPercent'])
	solarCost = float(inputDict['solarCost'])
	windCost = float(inputDict['windCost'])
	batteryPowerCost = float(inputDict['batteryPowerCost'])
	batteryCapacityCost = float(inputDict['batteryCapacityCost'])
	batteryPowerCostReplace = float(inputDict['batteryPowerCostReplace'])
	batteryCapacityCostReplace = float(inputDict['batteryCapacityCostReplace'])
	batteryPowerReplaceYear = float(inputDict['batteryPowerReplaceYear'])
	batteryCapacityReplaceYear = float(inputDict['batteryCapacityReplaceYear'])
	dieselGenCost = float(inputDict['dieselGenCost'])
	solarMin = float(inputDict['solarMin'])
	windMin = float(inputDict['windMin'])
	batteryPowerMin = float(inputDict['batteryPowerMin'])
	batteryCapacityMin = float(inputDict['batteryCapacityMin'])
	solarMax = float(inputDict['solarMax'])
	windMax = float(inputDict['windMax'])
	batteryPowerMax = float(inputDict['batteryPowerMax'])
	batteryCapacityMax = float(inputDict['batteryCapacityMax'])
	batterySocMinFraction = float(inputDict['batterySocMinFraction'])
	solarExisting = float(inputDict['solarExisting'])
	fuelAvailable = float(inputDict['fuelAvailable'])
	genExisting = float(inputDict['genExisting'])
	minGenLoading = float(inputDict['minGenLoading'])
	outage_start_hour = int(inputDict['outage_start_hour'])
	outage_duration = int(inputDict['outageDuration'])
	outage_end_hour = outage_start_hour + outage_duration - 1  # REopt end_time_step is inclusive: [start, end] = duration steps
	if outage_end_hour > 8759:
		outage_end_hour = 8759
	value_of_lost_load = float(inputDict['value_of_lost_load'])
	solarCanExport = inputDict['solarCanExport']
	solarCanCurtail = inputDict['solarCanCurtail']
	# explicitly convert string inputs from microgridDesign.html into usable boolean for REopt Scenario
	if inputDict['solarCanExport']:
		solarCanExport = True
	else:
		solarCanExport = False
	if inputDict['solarCanCurtail']:
		solarCanCurtail = True
	else:
		solarCanCurtail = False
	dieselMax = float(inputDict['dieselMax'])
	dieselMin = float(inputDict['dieselMin'])
	dieselFuelCostGal = float(inputDict['dieselFuelCostGal'])
	dieselCO2Factor = float(inputDict['dieselCO2Factor'])
	dieselOMCostKw = float(inputDict['dieselOMCostKw'])
	dieselOMCostKwh = float(inputDict['dieselOMCostKwh'])
	dieselOnlyRunsDuringOutage = inputDict['dieselOnlyRunsDuringOutage']
	tolerance = float(inputDict['solverTolerance'])
	loadShape = np.array(load_df)
	criticalLoadShape = np.array(critical_load_df)
	numRows = loadShape.shape[0]
	numCols = loadShape.shape[1]
	outData['numScenarios'] = numCols+1
	totalLoad = np.zeros(numRows)
	totalCriticalLoad = np.zeros(numRows)
	for i in range(0,1+numCols):
		indexString = str(i+1)
		if i == numCols:
			load = totalLoad
			criticalLoad = totalCriticalLoad
		else:
			load = loadShape[:,i]
			# print(type(load), load[0], load )
			load = [float(x) for x in load]
			totalLoad = np.add(totalLoad, load)
			criticalLoad = criticalLoadShape[:,i]
			# print(type(load), load[0], load )
			criticalLoad = [float(x) for x in criticalLoad]
			totalCriticalLoad = np.add(totalCriticalLoad, criticalLoad)
		jsonifiableLoad = list(load)
		jsonifiableCriticalLoad = list(criticalLoad)

		# Create the input JSON file for REopt
		# TODO: To use energyCostMonthly, comment out demandCost and energyCost lines in the Scenario JSON
		scenario = {
			#"Scenario": {
				#"optimality_tolerance_bau": float(inputDict['solverTolerance']),
				#"optimality_tolerance_techs": float(inputDict['solverTolerance']),
				"Site": {
					"latitude": latitude,
					"longitude": longitude
				},
				"ElectricTariff": {
					"wholesale_rate": wholesaleCost
					#"wholesale_rate_us_dollars_per_kwh": wholesaleCost,
					#"wholesale_rate_above_site_load_us_dollars_per_kwh": wholesaleCost
				},
				"ElectricLoad": { #"LoadProfile": {
					"loads_kw": jsonifiableLoad,
					"year": year
				},
				"Financial": {
					"value_of_lost_load_per_kwh": value_of_lost_load,
					#"value_of_lost_load_us_dollars_per_kwh": value_of_lost_load,
					"analysis_years": analysisYears,
					"om_cost_escalation_rate_fraction": omCostEscalator,
					#"om_cost_escalation_pct": omCostEscalator,
					"offtaker_discount_rate_fraction": discountRate
					#"offtaker_discount_pct": discountRate
				},
				"PV": {
					"installed_cost_per_kw": solarCost,
					#"installed_cost_us_dollars_per_kw": solarCost,
					"min_kw": solarMin,
					"can_export_beyond_nem_limit": solarCanExport,
					#"can_export_beyond_site_load": solarCanExport,
					"can_curtail": solarCanCurtail,
					"macrs_option_years": solarMacrsOptionYears,
					"federal_itc_fraction": solarItcPercent
					#"federal_itc_pct": solarItcPercent
				},
				"ElectricStorage": { #"Storage": {
					"installed_cost_per_kw": batteryPowerCost,
					#"installed_cost_us_dollars_per_kw": batteryPowerCost,
					"installed_cost_per_kwh": batteryCapacityCost,
					#"installed_cost_us_dollars_per_kwh": batteryCapacityCost,
					"replace_cost_per_kw": batteryPowerCostReplace,
					#"replace_cost_us_dollars_per_kw": batteryPowerCostReplace,
					"replace_cost_per_kwh": batteryCapacityCostReplace,
					#"replace_cost_us_dollars_per_kwh": batteryCapacityCostReplace,
					"inverter_replacement_year": batteryPowerReplaceYear,
					"battery_replacement_year": batteryCapacityReplaceYear,
					"min_kw": batteryPowerMin,
					"min_kwh": batteryCapacityMin,
					"macrs_option_years": batteryMacrsOptionYears,
					"total_itc_fraction": batteryItcPercent
					#"total_itc_percent": batteryItcPercent
				},
				"Wind": {
					"installed_cost_per_kw": windCost,
					#"installed_cost_us_dollars_per_kw": windCost,
					"can_export_beyond_nem_limit": solarCanExport,
					"can_curtail": solarCanCurtail,
					"min_kw": windMin,
					"macrs_option_years": windMacrsOptionYears,
					"federal_itc_fraction": windItcPercent
					#"federal_itc_pct": windItcPercent
				},
				"Generator": {
					"installed_cost_per_kw": dieselGenCost,
					#"installed_cost_us_dollars_per_kw": dieselGenCost,
					"only_runs_during_grid_outage": dieselOnlyRunsDuringOutage,
					#"generator_only_runs_during_grid_outage": dieselOnlyRunsDuringOutage,
					"macrs_option_years": dieselMacrsOptionYears
				}
		}

		# TODO: Enable all instances of 'annualCostSwitch', 'energyCostMonthly', 'demandCostMonthly' in mgDesign.py once a suitable way to enter a list of 12 monthly rates is found for mgDesign.html
		# pick whether to use annual or monthly rates
		# if annualCostSwitch == 'on':
		# 	scenario['Scenario']['Site']['ElectricTariff']['blended_annual_rates_us_dollars_per_kwh'] = energyCost
		# 	scenario['Scenario']['Site']['ElectricTariff']['blended_annual_demand_charges_us_dollars_per_kw'] = demandCost
		# elif annualCostSwitch == 'off':
		# 	scenario['Scenario']['Site']['ElectricTariff']['blended_monthly_rates_us_dollars_per_kwh'] = energyCostMonthly
		# 	scenario['Scenario']['Site']['ElectricTariff']['blended_monthly_demand_charges_us_dollars_per_kw'] = demandCostMonthly
		# solar and battery have default 'max_kw' == 1000000000; Wind has default 'max_kw' == 0 and thus must be set explicitly; Check https://developer.nrel.gov/docs/energy-optimization/reopt-v1 for updates
		scenario['PV']['existing_kw'] = solarExisting
		if not solar:
			scenario['PV']['max_kw'] = 0
		else:
			scenario['PV']['max_kw'] = solarMax
			scenario['ElectricLoad']['loads_kw_is_net'] = False
			# To turn off energy export/net-metering, set wholesaleCost to "0" and excess PV gen will be curtailed
			if not solarCanExport:
				#scenario['Scenario']['ElectricTariff']["wholesale_rate_above_site_load_us_dollars_per_kwh"] = 0
				scenario['ElectricTariff']['wholesale_rate'] = 0
				#["wholesale_rate_us_dollars_per_kwh"] = 0
		# REopt.jl's Wind struct does not support existing_kw (unlike PV which does).
		# To give REopt the correct ceiling, manually add windExisting to windMax here, mirroring the effect of PV's existing_kw which REopt adds to max_kw internally
		windExistingVal = float(inputDict.get('windExisting', 0))
		scenario['Wind']['max_kw'] = windMax + windExistingVal
		wind_mps = inputDict.get('windMetersPerSec')
		if wind_mps:
			scenario['Wind']['wind_meters_per_sec'] = wind_mps
			wind_dir = inputDict.get('windDirectionDegrees')
			wind_temp = inputDict.get('windTemperatureCelsius')
			wind_press = inputDict.get('windPressureAtmospheres')
			if wind_dir:
				scenario['Wind']['wind_direction_degrees'] = wind_dir
			if wind_temp:
				scenario['Wind']['temperature_celsius'] = wind_temp
			if wind_press:
				scenario['Wind']['pressure_atmospheres'] = wind_press
		scenario['ElectricStorage']['max_kw'] = batteryPowerMax
		scenario['ElectricStorage']['max_kwh'] = batteryCapacityMax
		scenario['ElectricStorage']['soc_min_fraction'] = batterySocMinFraction
		# if outage_start_hour is > 0, a resiliency optimization that includes diesel is triggered
		run_outages = True if outage_start_hour != 0 else False
		if outage_start_hour == 0:
			outage_end_hour = 0
		#scenario['Scenario']['LoadProfile']['outage_is_major_event'] = True
		scenario['ElectricUtility'] = {}
		scenario['ElectricUtility']['outage_start_time_step'] = outage_start_hour
		#['LoadProfile']['outage_start_time_step'] = outage_start_hour
		scenario['ElectricUtility']['outage_end_time_step'] = outage_end_hour
		#['LoadProfile']['outage_end_time_step'] = outage_end_hour
		scenario['Generator']['fuel_avail_gal'] = fuelAvailable
		scenario['Generator']['min_turn_down_fraction'] = minGenLoading
		#['min_turn_down_pct'] = minGenLoading
		scenario['Generator']['existing_kw'] = genExisting
		scenario['Generator']['fuel_cost_per_gallon'] = dieselFuelCostGal
		#['diesel_fuel_cost_us_dollars_per_gallon'] = dieselFuelCostGal
		scenario['Generator']['emissions_factor_lb_CO2_per_gal'] = dieselCO2Factor
		scenario['Generator']['om_cost_per_kw'] = dieselOMCostKw
		#['om_cost_us_dollars_per_kw'] = dieselOMCostKw
		scenario['Generator']['om_cost_per_kwh'] = dieselOMCostKwh
		#['om_cost_us_dollars_per_kwh'] = dieselOMCostKwh
		scenario['ElectricLoad']['critical_loads_kw'] = jsonifiableCriticalLoad
		# diesel has a quirk in how it gets inputted to REopt such that when strictly specified, allOutputData["sizeDiesel1"] = allInputData['dieselMax'] + allInputData['genExisting']
		#todo: check if still true for reopt.jl => doesn't seem to be
		#if dieselMax - genExisting > 0:
		scenario['Generator']['max_kw'] = dieselMax # - genExisting
		#else:
		#	scenario['Generator']['max_kw'] = 0
		#if dieselMin - genExisting > 0:
		scenario['Generator']['min_kw'] = dieselMin # - genExisting
		#else:
		#	scenario['Generator']['min_kw'] = 0
		#adding outage results (REopt.jl)
		#scenario['ElectricUtility']['outage_durations'] = [ outage_duration ] #not sure if correct

		# set rates
		if not urdbLabelSwitch:
			scenario['ElectricTariff']['blended_annual_energy_rate'] = energyCost
			#['blended_annual_rates_us_dollars_per_kwh'] = energyCost
			scenario['ElectricTariff']['blended_annual_demand_rate'] = demandCost
			#['blended_annual_demand_charges_us_dollars_per_kw'] = demandCost
		else:
			scenario['ElectricTariff']['urdb_label'] = urdbLabel

		start_time = time.time()
		with open(pJoin(modelDir, "Scenario_test_POST.json"), "w") as jsonFile:
			json.dump(scenario, jsonFile)

		# Run REopt API script *** => switched to REopt.jl
		try:
			output = reopt_jl.run_reopt_jl(modelDir, "Scenario_test_POST.json", outages=run_outages, max_runtime_s = max_runtime, tolerance = tolerance)
			with open(pJoin(modelDir, 'results.json')) as jsonFile:
				results = json.load(jsonFile)
		except FileNotFoundError:
			raise RuntimeError(f"results.json file not found. Output: {output}")

		#getting REoptInputs to access default input values more easily 
		with open(pJoin(modelDir, 'REoptInputs.json')) as jsonFile:
			reopt_inputs = json.load(jsonFile)
		
		if run_outages:
			with open(pJoin(modelDir, 'resultsResilience.json')) as jsonFile:
				resultsResilience = json.load(jsonFile)

		end_time = time.time()
		print(f'reopt_jl solver runtime: {end_time - start_time} seconds')
		
		outData['solverStatus' + indexString] = results['status']
		outData['hitTimeout' + indexString] = True if results['status'] == "timed-out" else False
		outData['solverSeconds' + indexString] = results.get('solver_seconds')

		#resultsSubset = results['outputs']['Scenario']['Site']
		outData['demandCostBAU' + indexString] = results['ElectricTariff']['lifecycle_demand_cost_after_tax_bau']#['total_demand_cost_bau_us_dollars']
		if outData['demandCostBAU' + indexString] is None:
			raise Exception('Error: results not received')
	
		outData['demandCost' + indexString] = results['ElectricTariff']['lifecycle_demand_cost_after_tax']#['total_demand_cost_us_dollars']
		outData['demandCostDiff' + indexString] = round(outData['demandCostBAU' + indexString] - outData['demandCost' + indexString],2)
		outData['energyCostBAU' + indexString] = results['ElectricTariff']['lifecycle_energy_cost_after_tax_bau']#['total_energy_cost_bau_us_dollars']
		outData['energyCost' + indexString] = results['ElectricTariff']['lifecycle_energy_cost_after_tax']#['total_energy_cost_us_dollars']
		outData['energyCostDiff' + indexString] = round(outData['energyCostBAU' + indexString] - outData['energyCost' + indexString],2)
		outData['fixedCostBAU' + indexString] = results['ElectricTariff']['lifecycle_fixed_cost_after_tax_bau']#['total_fixed_cost_bau_us_dollars']
		outData['fixedCost' + indexString] = results['ElectricTariff']['lifecycle_fixed_cost_after_tax']#['total_fixed_cost_us_dollars']
		outData['fixedCostDiff' + indexString] = outData['fixedCostBAU' + indexString] - outData['fixedCost' + indexString]
		outData['powerGridToBattery' + indexString] = results['ElectricUtility']['electric_to_storage_series_kw']
		#['ElectricTariff']['year_one_to_battery_series_kw']
		outData['powerGridToLoad' + indexString] = results['ElectricUtility']['electric_to_load_series_kw']
		#['ElectricTariff']['year_one_to_load_series_kw']
		outData['totalCostBAU' + indexString] = results['Financial']['lcc_bau']#['lcc_bau_us_dollars']
		outData['totalCost' + indexString] = results['Financial']['lcc'] #['lcc_us_dollars']
		outData['totalCostDiff' + indexString] = round(outData['totalCostBAU' + indexString] - outData['totalCost' + indexString],2)
		outData['savings' + indexString] = results['Financial']['npv']#['npv_us_dollars']
		outData['initial_capital_costs' + indexString] = results['Financial']['initial_capital_costs']#['initial_capital_costs']
		outData['initial_capital_costs_after_incentives' + indexString] = results['Financial']['initial_capital_costs_after_incentives']#['initial_capital_costs_after_incentives']
		load_series = results['ElectricLoad']['load_series_kw']
		outData['load' + indexString] = load_series #['LoadProfile']['year_one_electric_load_series_kw']
		outData['avgLoad' + indexString] = round(sum(load_series)/len(load_series),1)
		#['LoadProfile']['year_one_electric_load_series_kw'])/len(resultsSubset['LoadProfile']['year_one_electric_load_series_kw']),1)
		
		# carry over analysisYears as this is not an REopt output
		outData['analysisYears' + indexString] = analysisYears
		outData['discountRate' + indexString] = discountRate

		# outputs to be used in microgridup.py
		# outData['yearOneEmissionsLbsBau' + indexString] = resultsSubset['year_one_emissions_bau_lb_C02']
		# outData['yearOneEmissionsLbs' + indexString] = resultsSubset['year_one_emissions_lb_C02']
		# outData['yearOneEmissionsTons' + indexString] = round((outData['yearOneEmissionsLbs' + indexString])/2205,0)
		# outData['yearOneEmissionsReducedTons' + indexString] = round((resultsSubset['year_one_emissions_bau_lb_C02'] - resultsSubset['year_one_emissions_lb_C02'])/2205,0)
		# outData['yearOneEmissionsReducedPercent' + indexString] = round((resultsSubset['year_one_emissions_bau_lb_C02'] - resultsSubset['year_one_emissions_lb_C02'])/resultsSubset['year_one_emissions_bau_lb_C02']*100,0)		
		# outData['yearOnePercentRenewable' + indexString] = round(resultsSubset['renewable_electricity_energy_pct']*100,0)
		
		y1_emissions = results['Site']['annual_emissions_tonnes_CO2']
		y1_emissions_bau = results['Site']['annual_emissions_tonnes_CO2_bau']
		outData['yearOneEmissionsTons' + indexString] = round(y1_emissions)#['year_one_emissions_tCO2'])
		outData['yearOneEmissionsReducedTons' + indexString] = round(y1_emissions_bau - y1_emissions)
		#['year_one_emissions_tCO2_bau'] - resultsSubset['year_one_emissions_tCO2'])
		outData['yearOneEmissionsReducedPercent' + indexString] = round((y1_emissions_bau - y1_emissions)/y1_emissions_bau*100,0)
		#(resultsSubset['year_one_emissions_tCO2_bau'] - resultsSubset['year_one_emissions_tCO2'])/resultsSubset['year_one_emissions_tCO2_bau']*100,0)
		outData['yearOnePercentRenewable' + indexString] = round(results['Site']['renewable_electricity_fraction']*100,0)
		#['annual_renewable_electricity_pct']*100,0)
		outData['yearOneOMCostsBeforeTax' + indexString] = round(results['Financial']['year_one_om_costs_before_tax'])
		#['year_one_om_costs_before_tax_us_dollars'],0)
		
		#getting extra data for reopt.jl proforma analysis
		outData['irr' + indexString] = results['Financial']['internal_rate_of_return']
		outData['paybackYears' + indexString] = results['Financial']['simple_payback_years']

		yearOneBill = results['ElectricTariff']['year_one_bill_before_tax']
		yearOneBillBAU = results['ElectricTariff']['year_one_bill_before_tax_bau']
		outData['yearOneBillBAU' + indexString] = yearOneBillBAU
		outData['yearOneExportBenefitBAU' + indexString] = results['ElectricTariff']['year_one_export_benefit_before_tax_bau']
		outData['yearOneBill' + indexString] = yearOneBill
		outData['yearOneExportBenefit' + indexString] = results['ElectricTariff']['year_one_export_benefit_before_tax']
		outData['totalElectricityProduced' + indexString] = 0

		outData['totalRenewableEnergyProduced' + indexString] = results['Site']['annual_renewable_electricity_kwh']
		outData['reductionElectricBillFraction' + indexString] = (yearOneBillBAU - yearOneBill) / yearOneBillBAU * 100
		outData['yearOneEmissionsTonsBAU' + indexString] = y1_emissions_bau
		outData['utilityYearOneEmissionsTons' + indexString] = results['ElectricUtility']['annual_emissions_tonnes_CO2']
		outData['utilityYearOneEmissionsTonsBAU' + indexString] = results['ElectricUtility']['annual_emissions_tonnes_CO2_bau']
		outData['yearOneEmissionsFromFuelburnTons' + indexString] = results['Site']['annual_emissions_from_fuelburn_tonnes_CO2']
		outData['yearOneEmissionsFromFuelburnTonsBAU' + indexString] = results['Site']['annual_emissions_from_fuelburn_tonnes_CO2_bau']

		outData['omCostEscalator' + indexString] = omCostEscalator * 100
		outData['elecCostEscalator' + indexString] = reopt_inputs['s']['financial']['elec_cost_escalation_rate_fraction'] * 100
		outData['discountRate' + indexString] = discountRate * 100
		outData['federalITCFraction' + indexString] = reopt_inputs['s']['financial']['offtaker_tax_rate_fraction'] * 100

		outData['totalInstalledCost' + indexString] = results['Financial']['initial_capital_costs']
		outData['freeCashFlows' + indexString] = results['Financial']['offtaker_annual_free_cashflows']

		#getting extra data from reopt.jl inputs (default values) to include in analysis results
		outData['macrsFiveYear' + indexString] = reopt_inputs['s']['financial']['macrs_five_year']
		outData['macrsSevenYear' + indexString] = reopt_inputs['s']['financial']['macrs_seven_year']

		if 'PV' in results:
			outData['sizePV' + indexString] = results['PV']['size_kw']
			outData['sizePVRounded' + indexString] = round(results['PV']['size_kw'],1)
			outData['powerPVToBattery' + indexString] = results['PV']['electric_to_storage_series_kw']#['year_one_to_battery_series_kw']
			outData['powerPVToLoad' + indexString] = results['PV']['electric_to_load_series_kw']#['year_one_to_load_series_kw']
			outData['powerPVCurtailed' + indexString] = results['PV']['electric_curtailed_series_kw']#['year_one_curtailed_production_series_kw']
			outData['powerPVToGrid' + indexString] = results['PV']['electric_to_grid_series_kw']#['year_one_to_grid_series_kw']
			powerPVProductionValues = (outData['powerPVToBattery' + indexString], outData['powerPVToLoad' + indexString],
							  outData['powerPVCurtailed' + indexString], outData['powerPVToGrid' + indexString])
			outData['powerPV' + indexString] = [sum(x) for x in zip(*powerPVProductionValues)]
			#resultsSubset['PV']['year_one_power_production_series_kw']
			outData['sizePVExisting' + indexString] = solarExisting
			#results['inputs']['Scenario']['Site']['PV']['existing_kw']
			outData['solarCost' + indexString] = float(inputDict['solarCost'])
			#adding for proforma analysis (solar)
			outData['sizePVPurchased' + indexString] = results['PV']['size_kw'] - solarExisting
			outData['degradationRatePVFraction' + indexString] = reopt_inputs['s']['pvs'][0]['degradation_fraction']
			outData['lcoePV' + indexString] = results['PV']['lcoe_per_kwh']
			outData['pvYearOneEnergyProducedBAU' + indexString] = 0
			if solarExisting != 0:
				outData['pvYearOneEnergyProducedBAU' + indexString] = results['PV']['year_one_energy_produced_kwh_bau']
			outData['pvYearOneEnergyProduced' + indexString] = results['PV']['year_one_energy_produced_kwh']
			outData['totalElectricityProduced' + indexString] += results['PV']['year_one_energy_produced_kwh']
			outData['pvAnnualEnergyProduced' + indexString] = results['PV']['annual_energy_produced_kwh']
			outData['pvOMCosts' + indexString] = reopt_inputs['s']['pvs'][0]['om_cost_per_kw']
			outData['pvITCFraction' + indexString] = solarItcPercent
			outData['costPVInstalled' + indexString] = outData['sizePVPurchased' + indexString] * solarCost

			#getting extra data from reopt.jl inputs (default values) to include in analysis results
			outData['pvMacrsBonusFraction' + indexString] = reopt_inputs['s']['pvs'][0]['macrs_bonus_fraction']
			outData['pvStateIbiFraction' + indexString] = reopt_inputs['s']['pvs'][0]['state_ibi_fraction']
			outData['pvStateIbiMax' + indexString] = reopt_inputs['s']['pvs'][0]['state_ibi_max']
			outData['pvUtilityIbiFraction' + indexString] = reopt_inputs['s']['pvs'][0]['utility_ibi_fraction']
			outData['pvUtilityIbiMax' + indexString] = reopt_inputs['s']['pvs'][0]['utility_ibi_max']
			outData['pvFederalCbi' + indexString] = reopt_inputs['s']['pvs'][0]['federal_rebate_per_kw']
			outData['pvStateCbi' + indexString] = reopt_inputs['s']['pvs'][0]['state_rebate_per_kw']
			outData['pvStateCbiMax' + indexString] = reopt_inputs['s']['pvs'][0]['state_rebate_max']
			outData['pvUtilityCbi' + indexString] = reopt_inputs['s']['pvs'][0]['utility_rebate_per_kw']
			outData['pvUtilityCbiMax' + indexString] = reopt_inputs['s']['pvs'][0]['utility_rebate_max']
			outData['pvPbi' + indexString] = reopt_inputs['s']['pvs'][0]['production_incentive_per_kwh']
			outData['pvPbiMax' + indexString] = reopt_inputs['s']['pvs'][0]['production_incentive_max_benefit']
			outData['pvPbiYears' + indexString] = reopt_inputs['s']['pvs'][0]['production_incentive_years']
			outData['pvPbiMaxKw' + indexString] = reopt_inputs['s']['pvs'][0]['production_incentive_max_kw']


		else:
			outData['sizePV' + indexString] = 0
			outData['sizePVRounded' + indexString] = 0

		if 'ElectricStorage' in results:
			outData['powerBattery' + indexString] = results['ElectricStorage']['size_kw']
			#['Storage']['size_kw']
			outData['powerBatteryRounded' + indexString] = round(results['ElectricStorage']['size_kw'],1)
			#['Storage']['size_kw'],1)
			outData['capacityBattery' + indexString] = results['ElectricStorage']['size_kwh']
			#['Storage']['size_kwh']
			outData['capacityBatteryRounded' + indexString] = round(results['ElectricStorage']['size_kwh'],1)
			#['Storage']['size_kwh'],1)
			outData['chargeLevelBattery' + indexString] = results['ElectricStorage']['soc_series_fraction']
			#['Storage']['year_one_soc_series_pct']
			outData['powerBatteryToLoad' + indexString] = results['ElectricStorage']['storage_to_load_series_kw']
			#['Storage']['year_one_to_load_series_kw']
			outData['batteryPowerCost' + indexString] = batteryPowerCost
			outData['batteryCapacityCost' + indexString] = batteryCapacityCost
			# batteryPowerReplaceYear, batteryCapacityReplaceYear, 'batteryPowerCostReplace', 'batteryCapacityCostReplace', batteryKwExisting and batteryKwhExisting are pass through variables used in microgridUp project
			outData['batteryPowerCostReplace' + indexString] = batteryPowerCostReplace
			outData['batteryCapacityCostReplace' + indexString] = batteryCapacityCostReplace
			outData['batteryPowerReplaceYear' + indexString] = batteryPowerReplaceYear
			outData['batteryCapacityReplaceYear' + indexString] = batteryCapacityReplaceYear
			outData['batteryKwExisting' + indexString] = float(inputDict.get('batteryKwExisting',0))
			outData['batteryKwhExisting' + indexString] = float(inputDict.get('batteryKwhExisting',0))
			
			#adding for ProForma analysis
			powerBatteryInstalled = results['ElectricStorage']['size_kw']
			if outData['batteryKwExisting' + indexString] > 0:
				powerBatteryInstalled -= outData['batteryKwExisting' + indexString]
			powerBatteryInstalledCost = powerBatteryInstalled * outData['batteryPowerCost' + indexString]

			capacityBatteryInstalled = results['ElectricStorage']['size_kwh']
			if outData['batteryKwhExisting' + indexString] > 0:
				capacityBatteryInstalled -= outData['batteryKwhExisting' + indexString] #save battery(Kw/Kwh)Existing at top to reduce lookups?
			capacityBatteryInstalledCost = capacityBatteryInstalled * outData['batteryCapacityCost' + indexString] 

			outData['batteryInstalledCost' + indexString] = powerBatteryInstalledCost + capacityBatteryInstalledCost

			#getting extra data from reopt.jl inputs (default values) to include in analysis results
			outData['batteryMacrsBonusFraction' + indexString] = reopt_inputs['s']['storage']['attr']['ElectricStorage']['macrs_bonus_fraction']
			outData['degradationRateBatteryFraction' + indexString] = 0 #default: model_degradation == False for battery
			#reopt_inputs['s']['storage']['attr']['ElectricStorage']['degradation_fraction']
			outData['batteryItcFraction' + indexString]  = reopt_inputs['s']['storage']['attr']['ElectricStorage']['total_itc_fraction']
			outData['batteryCbiKw' + indexString]  = reopt_inputs['s']['storage']['attr']['ElectricStorage']['total_rebate_per_kw']
			outData['batteryCbiKwh' + indexString]  = reopt_inputs['s']['storage']['attr']['ElectricStorage']['total_rebate_per_kwh']

		else:
			outData['powerBattery' + indexString] = 0
			outData['capacityBattery' + indexString] = 0
			outData['powerBatteryRounded' + indexString] = 0
			outData['capacityBatteryRounded' + indexString] = 0

		if 'Wind' in results:
			outData['sizeWind' + indexString] = results['Wind']['size_kw']
			outData['sizeWindRounded' + indexString] = round(results['Wind']['size_kw'],1)
			outData['powerWindToBattery' + indexString] = results['Wind']['electric_to_storage_series_kw']
			#['year_one_to_battery_series_kw']
			outData['powerWindToLoad' + indexString] = results['Wind']['electric_to_load_series_kw']
			#['year_one_to_load_series_kw']
			#adding powerWindToGrid and powerWindCurtailed to ensure accuracy of total wind production series (powerWind)
			outData['powerWindToGrid' + indexString] = results['Wind']['electric_to_grid_series_kw']
			outData['powerWindCurtailed' + indexString] = results['Wind']['electric_curtailed_series_kw']
			powerWindProductionValues = (outData['powerWindToBattery' + indexString], outData['powerWindToLoad' + indexString],
								outData['powerWindToGrid' + indexString], outData['powerWindCurtailed' + indexString])
			outData['powerWind' + indexString] = [sum(x) for x in zip(*powerWindProductionValues)]
			#resultsSubset['Wind']['year_one_power_production_series_kw']
			outData['windCost' + indexString] = windCost
			#adding for proforma analysis (wind)
			outData['lcoeWind' + indexString] = results['Wind']['lcoe_per_kwh']
			outData['windAnnualEnergyProduced' + indexString] = results['Wind']['annual_energy_produced_kwh']
			outData['totalElectricityProduced' + indexString] += results['Wind']['annual_energy_produced_kwh']

			# windExisting is a pass through variables used in microgridUp project
			windExisting = float(inputDict.get('windExisting',0))
			outData['windExisting' + indexString] = windExisting
			outData['windPurchased' + indexString] = outData['sizeWind' + indexString] - windExisting

			outData['windInstalledCost' + indexString] = outData['windPurchased' + indexString] * windCost

			#getting extra data from reopt.jl inputs (default values) to include in analysis results
			outData['windOMCosts' + indexString] = reopt_inputs['s']['wind']['om_cost_per_kw']
			outData['windMacrsBonusFraction' + indexString] = reopt_inputs['s']['wind']['macrs_bonus_fraction']
			outData['windStateIbiFraction' + indexString] = reopt_inputs['s']['wind']['state_ibi_fraction']
			outData['windStateIbiMax' + indexString] = reopt_inputs['s']['wind']['state_ibi_max']
			outData['windUtilityIbiFraction' + indexString] = reopt_inputs['s']['wind']['utility_ibi_fraction']
			outData['windUtilityIbiMax' + indexString] = reopt_inputs['s']['wind']['utility_ibi_max']
			outData['degradationRateWindFraction' + indexString] = 0 #degradation not modeled for Wind
			outData['windFederalCbi' + indexString] = reopt_inputs['s']['wind']['federal_rebate_per_kw']
			outData['windStateCbi' + indexString] = reopt_inputs['s']['wind']['state_rebate_per_kw']
			outData['windStateCbiMax' + indexString] = reopt_inputs['s']['wind']['state_rebate_max']
			outData['windUtilityCbi' + indexString] = reopt_inputs['s']['wind']['utility_rebate_per_kw']
			outData['windUtilityCbiMax' + indexString] = reopt_inputs['s']['wind']['utility_rebate_max']
			outData['windPbi' + indexString] = reopt_inputs['s']['wind']['production_incentive_per_kwh']
			outData['windPbiMax' + indexString] = reopt_inputs['s']['wind']['production_incentive_max_benefit']
			outData['windPbiYears' + indexString] = reopt_inputs['s']['wind']['production_incentive_years']
			outData['windPbiMaxKw' + indexString] = reopt_inputs['s']['wind']['production_incentive_max_kw']


		else:
			outData['sizeWind' + indexString] = 0
			outData['sizeWindRounded' + indexString] = 0

		# diesel generator does not follow on/off convention, as it is not turned on by user, but rather is automatically turned on when an outage is specified
		#adding check to ensure 'Generator' key exists
		if 'Generator' in results:
			outData['sizeDiesel' + indexString] = results['Generator']['size_kw']
			outData['sizeDieselRounded' + indexString] = round(results['Generator']['size_kw'],1)
			outData['dieselGenCost' + indexString] = dieselGenCost #float(inputDict['dieselGenCost'])
			outData['dieselOnlyRunsDuringOutage' + indexString] = dieselOnlyRunsDuringOutage #bool(inputDict['dieselOnlyRunsDuringOutage'])
			outData['dieselOMCostKw' + indexString] = dieselOMCostKw 
			outData['dieselOMCostKwh' + indexString] = dieselOMCostKwh #float(inputDict['dieselOMCostKwh'])
			if results['Generator']['size_kw'] == 0:
				outData['sizeDieselRounded' + indexString] = 0
			outData['fuelUsedDiesel' + indexString] = results['Generator']['annual_fuel_consumption_gal']#['fuel_used_gal']
			outData['fuelUsedDieselRounded' + indexString] = round(results['Generator']['annual_fuel_consumption_gal'], 0)
			#['fuel_used_gal'],0)
			outData['sizeDieselExisting' + indexString] = genExisting #float(inputDict['genExisting'])
			outData['sizeDieselPurchased' + indexString] = outData['sizeDiesel' + indexString] - genExisting #outData['sizeDieselExisting' + indexString]
			#results['inputs']['Scenario']['Site']['Generator']['existing_kw']
			outData['powerDieselToBattery' + indexString] = results['Generator']['electric_to_storage_series_kw']
			#['year_one_to_battery_series_kw']
			outData['powerDieselToLoad' + indexString] = results['Generator']['electric_to_load_series_kw']
			#['year_one_to_load_series_kw']
			#adding powerDieselToGrid to ensure accuracy of total diesel production series (powerDiesel)
			outData['powerDieselToGrid' + indexString] = results['Generator']['electric_to_grid_series_kw']
			powerDieselProductionValues = (outData['powerDieselToBattery' + indexString], outData['powerDieselToLoad' + indexString],
								  outData['powerDieselToGrid' + indexString])
			outData['powerDiesel' + indexString] = [sum(x) for x in zip(*powerDieselProductionValues)]
			#resultsSubset['Generator']['year_one_power_production_series_kw']

			#adding for proforma analysis (generator)
			outData['dieselAnnualEnergyProduced' + indexString] = results['Generator']['annual_energy_produced_kwh']
			outData['totalElectricityProduced' + indexString] += results['Generator']['annual_energy_produced_kwh'] #year_one_energy_produced_kwh?
			outData['dieselInstalledCost' + indexString] = outData['sizeDieselPurchased' + indexString] * dieselGenCost
			outData['fuelUsedDieselCost' + indexString] = outData['fuelUsedDiesel' + indexString] * dieselFuelCostGal
			outData['fuelUsedDieselCostBAU' + indexString] = 0 
			if genExisting > 0:
				outData['fuelUsedDieselCostBAU' + indexString] = results['Generator']['annual_fuel_consumption_gal_bau'] * dieselFuelCostGal

			# output resilience stats if resilienceRun was successful
		if run_outages: #'outage_sim_results' in resultsResilience:
			outData['resilience' + indexString] = resultsResilience['resilience_by_time_step']#['outage_durations'] <- not working?
			#['outage_sim_results']['resilience_by_timestep']
			outData['minOutage' + indexString] = resultsResilience['resilience_hours_min']
			#['outage_sim_results']['resilience_hours_min']
			outData['maxOutage' + indexString] = resultsResilience['resilience_hours_max']
			#['outage_sim_results']['resilience_hours_max']
			outData['avgOutage' + indexString] = resultsResilience['resilience_hours_avg']
			#['outage_sim_results']['resilience_hours_avg']
			outData['survivalProbX' + indexString] = resultsResilience['outage_durations']
			#['outage_sim_results']['outage_durations']
			outData['survivalProbY' + indexString] = resultsResilience['probs_of_surviving']
			#['outage_sim_results']['probs_of_surviving']
			outData['avoidedOutageCosts' + indexString] = -1 # N/A? Financial => lifecycle_outage_cost but no bau
			#resultsResilience['outage_sim_results']['avoided_outage_costs_us_dollars']

			#adding for ProForma analysis (outages)
			#if outage_duration != 0: #can outage duration = 0 if outage_start_hour != 0?
			#	outData['']

		#todo: decide on ProForma output type (excel, html, or both)

		workbook = Workbook()
		worksheet = workbook.active
		worksheet.title = "Results Summary and Inputs"

		thin_side = Side(style='thin', color='000000')
		cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
		header_fill = PatternFill(fill_type='solid', fgColor='C0C0C0')
		header_font = Font(bold=True)

		def apply_cell_style(cell, is_header=False):
			cell.border = cell_border
			if is_header:
				cell.fill = header_fill
				cell.font = header_font

		excel_row = 0
		excel_col = 0
		results_row = 3
		results_col = 3

		#todo: move out of main function 
		def write_table(table, name, start_row, start_col):
			rows = len(table)
			if rows == 0: 
				return 0
			cols = len(table[0])
			if cols == 0:
				return
			#writing single header if name given
			if name:
				worksheet.merge_cells(start_row=start_row + 1, start_column=start_col + 1, end_row=start_row + 1, end_column=start_col + cols)
				cell = worksheet.cell(row=start_row + 1, column=start_col + 1, value=name)
				apply_cell_style(cell, is_header=True)
			for i in range(rows):
				for j in range(cols):
					if j >= len(table[i]):
						continue
					table_val = table[i][j]
					x = start_row + i + 1 if name else start_row + i
					y = start_col + j
					cell = worksheet.cell(row=x + 1, column=y + 1, value=table_val)
					apply_cell_style(cell, is_header=(i == 0 and not name))
					column_letter = cell.column_letter
					column_width = max(worksheet.column_dimensions[column_letter].width or 0, len(str(table_val)) + 2)
					worksheet.column_dimensions[column_letter].width = column_width

		#potential idea: dictionary mapping proforma row name to outdata variable (wouldn't be that much more efficient)
		proforma_system_design = [
			['PV Nameplate capacity (kW), purchased', outData.get('sizePVPurchased' + indexString,0)],
			['PV Nameplate capacity (kW), existing', outData.get('sizePVExisting' + indexString,0)],
			['PV degradation rate (%/year)', outData.get('degradationRatePVFraction' + indexString,0)],
			['PV LCOE of New Capacity ($/kWh), nominal', outData.get('lcoePV' + indexString,0)],
			['Wind Nameplate capacity (kW), purchased', outData.get('windPurchased' + indexString, 0)],
			['Wind LCOE ($/kWh), nominal', outData.get('lcoeWind' + indexString,0)],
			['Backup Generator Nameplate capacity (kW), purchased', outData.get('sizeDieselPurchased' + indexString,0)],
			['Backup Generator Nameplate capacity (kW), existing', outData.get('sizeDieselExisting' + indexString,0)],
			['Battery power (kW)', outData.get('powerBattery' + indexString,0)],
			['Battery capacity (kWh)', outData.get('capacityBattery' + indexString,0)]
		]

		write_table(proforma_system_design,"OPTIMAL SYSTEM DESIGN (with existing)",excel_row,excel_col)
		excel_row += results_row
		excel_col += results_col

		proforma_results = [
			['Business as usual LCC, $', outData.get('totalCostBAU' + indexString,0)],
			['Optimal LCC, $', outData.get('totalCost' + indexString,0)],
			['NPV, $', outData.get('savings' + indexString,0)],
			['IRR, %', outData.get('irr' + indexString,0)],
			['Simple Payback Period, years', outData.get('paybackYears' + indexString,0)]
		]

		write_table(proforma_results,"RESULTS",excel_row,excel_col)
		excel_row += len(proforma_system_design) - results_row + 2
		excel_col -= results_col

		proforma_annual_results = [
			['Present value of annual Business as Usual electric utility bill ($/year)', outData.get('yearOneBillBAU' + indexString,0)], 
			['Present value of annual Business as Usual export credits ($/year)', outData.get('yearOneExportBenefitBAU' + indexString,0)],
			['Present value of annual Optimal electric utility bill($/year)', outData.get('yearOneBill' + indexString,0)],
			['Present value of annual Optimal export credits ($/year)', outData.get('yearOneExportBenefit' + indexString,0)],
			['Existing PV electricity produced (kWh), Year 1', outData.get('pvYearOneEnergyProducedBAU' + indexString,0)],
			['Total PV optimal electricity produced (kWh), Year 1', outData.get('pvYearOneEnergyProduced' + indexString,0)],
			['Nominal annual optimal wind electricity produced (kWh/year)', outData.get('windAnnualEnergyProduced' + indexString,0)],
			['Nominal annual optimal backup generator electricity produced (kWh/year)', outData.get('dieselAnnualEnergyProduced' + indexString,0)],
			['Total optimal electricity produced (kWh/year)', outData.get('totalElectricityProduced' + indexString,0)],
			['Percent electricity from on-site renewable resources', outData.get('yearOnePercentRenewable' + indexString,0)],
			['Percent reduction in annual electricity bill', outData.get('reductionElectricBillFraction' + indexString,0)],
			['Year one total site carbon dioxide emissions (ton CO2)', outData.get('yearOneEmissionsTons' + indexString,0)],
			['Year one total site carbon dioxide emissions BAU (ton CO2)', outData.get('yearOneEmissionsTonsBAU' + indexString,0)],
			['Year one total carbon dioxide emissions from electric utility purchases (ton CO2)', outData.get('utilityYearOneEmissionsTons' + indexString,0)],
			['Year one total carbon dioxide emissions from electric utility purchases BAU (ton CO2)', outData.get('utilityYearOneEmissionsTonsBAU' + indexString,0)],
			['Year one total carbon dioxide emissions from on-site fuel burn (ton CO2)', outData.get('yearOneEmissionsFromFuelburnTons' + indexString,0)],
			['Year one total carbon dioxide emissions from on-site fuel burn BAU (ton CO2)', outData.get('yearOneEmissionsFromFuelburnTonsBAU' + indexString,0)]
		]

		write_table(proforma_annual_results,"ANNUAL RESULTS",excel_row,excel_col)
		excel_row += len(proforma_annual_results) + 2

		proforma_system_costs = [
			['Total Installed Cost ($)', outData.get('totalInstalledCost' + indexString,0)],
			['PV Installed Cost ($)', outData.get('costPVInstalled' + indexString,0)],
			['Wind Installed Cost ($)', outData.get('windInstalledCost' + indexString,0)],
			['Backup generator Installed Cost ($)', outData.get('dieselInstalledCost' + indexString,0)],
			['Battery Installed Cost ($)', outData.get('batteryInstalledCost' + indexString,0)]
		]

		write_table(proforma_system_costs, "SYSTEM COSTS",excel_row,excel_col)
		excel_row += len(proforma_system_costs) + 1

		proforma_om = [
			['Fixed PV O&M ($/kW-yr)', outData.get('pvOMCosts' + indexString,0)],
			['Fixed Wind O&M ($/kW-yr)', outData.get('windOMCosts' + indexString,0)],
			['Fixed Backup Generator O&M ($/kW-yr)', outData.get('dieselOMCostKw' + indexString,0)],
			['Variable Backup Generator O&M ($/kWh)', outData.get('dieselOMCostKwh' + indexString,0)],
			['Diesel fuel used cost ($)', outData.get('fuelUsedDieselCost' + indexString,0)],
			['Diesel BAU fuel used cost ($)', outData.get('fuelUsedDieselCostBAU' + indexString,0)],
			['Battery replacement cost ($/kW)', outData.get('batteryPowerCostReplace' + indexString,0)],
			['Battery kW replacement year', outData.get('batteryPowerReplaceYear' + indexString,0)],
			['Battery replacement cost ($/kWh)', outData.get('batteryCapacityCostReplace' + indexString,0)], 
			['Battery kWh replacement year', outData.get('batteryCapacityReplaceYear' + indexString,0)]
		]

		write_table(proforma_om, "Operation and Maintenance (O&M)",excel_row,excel_col)
		excel_row += len(proforma_om) + 2

		proforma_analysis_parameters = [
			['Analysis period (years)', outData.get('analysisYears' + indexString,0)],
			['Nominal O&M cost escalation rate (%/year)', outData.get('omCostEscalator' + indexString,0)],
			['Nominal electric utility cost escalation rate (%/year)', outData.get('elecCostEscalator' + indexString,0)],
			['Nominal discount rate (%/year)', outData.get('discountRate' + indexString,0)]
		]

		write_table(proforma_analysis_parameters, "ANALYSIS PARAMETERS",excel_row,excel_col)
		excel_row += len(proforma_analysis_parameters) + 2

		proforma_tax_insurance = [
			['Federal income tax rate (%)', outData.get('federalITCFraction' + indexString,0)]
		]
		write_table(proforma_tax_insurance, "TAX AND INSURANCE PARAMETERS",excel_row,excel_col)
		excel_row += len(proforma_tax_insurance) + 2

		if 'PV' in results:
			proforma_tax_credits = [
				#note: removing values from table that are not included in reopt.jl calculations
				['Investment tax credit (ITC)', '' ],
                ['As percentage', '%' ],
                ['Federal', solarItcPercent ]
			]
			write_table(proforma_tax_credits, 'PV TAX CREDITS', excel_row, excel_col)
			excel_row += len(proforma_tax_credits) + 2

			proforma_cash_incentives = [
				['Investment based incentive (IBI)', '', '' ],
				['As percentage', '%', 'Maximum ($)'],
				['State (% of total installed cost)', outData['pvStateIbiFraction' + indexString], 
	 				outData['pvStateIbiMax' + indexString]], 
				['Utility (% of total installed cost)', outData['pvUtilityIbiFraction' + indexString], 
	 				outData['pvUtilityIbiMax' + indexString]],
				['Capacity based incentive (CBI)', 'Amount ($/W)', 'Maximum ($)'],
				['Federal ($/W)', outData['pvFederalCbi' + indexString], '' ],
				['State  ($/W)', outData['pvStateCbi' + indexString], outData['pvStateCbiMax' + indexString]],
				['Utility  ($/W)', outData['pvUtilityCbi' + indexString], outData['pvUtilityCbiMax' + indexString]],
				['Production based incentive (PBI)', 'Amount ($/kWh)', 'Maximum ($/year)', 'Term (years)', 
	 				'System Size Limit (kW)'],
				['Combined ($/kWh)', outData['pvPbi' + indexString], outData['pvPbiMax' + indexString], 
	 				outData['pvPbiYears' + indexString], outData['pvPbiMaxKw' + indexString] ]
			]
			write_table(proforma_cash_incentives, 'PV DIRECT CASH INCENTIVES',excel_row,excel_col)
			excel_row += len(proforma_cash_incentives) + 2
		
		if 'Wind' in results:
			proforma_tax_credits = [
				['Investment tax credit (ITC)', '' ],
                ['As percentage', '%' ],
                ['Federal', windItcPercent ]
			]
			write_table(proforma_tax_credits, 'WIND TAX CREDITS', excel_row, excel_col)
			excel_row += len(proforma_tax_credits) + 2

			proforma_cash_incentives = [
				['Investment based incentive (IBI)', '', ''],
				['As percentage', '%', 'Maximum ($)'],
				['State (% of total installed cost)',  outData['windStateIbiFraction' + indexString], outData['windStateIbiMax' + indexString]],
				['Utility (% of total installed cost)', outData['windUtilityIbiFraction' + indexString], outData['windUtilityIbiMax' + indexString]],
				['Capacity based incentive (CBI)', 'Amount ($/W)', 'Maximum ($)'],
				['Federal ($/W)', outData['windFederalCbi' + indexString] ],
				['State  ($/W)', outData['windStateCbi' + indexString], outData['windStateCbiMax' + indexString] ],
				['Utility  ($/W)', outData['windUtilityCbi' + indexString], outData['windUtilityCbiMax' + indexString]],
				['Production based incentive (PBI)', 'Amount ($/kWh)', 'Maximum ($/year)', 'Term (years)', 'System Size Limit (kW)'],
				['Combined ($/kWh)', outData['windPbi' + indexString], outData['windPbiMax' + indexString], 
	 				outData['windPbiYears' + indexString], outData['windPbiMaxKw' + indexString]]
			]
			write_table(proforma_cash_incentives, 'WIND DIRECT CASH INCENTIVES',excel_row,excel_col)
			excel_row += len(proforma_cash_incentives) + 2

		if 'ElectricStorage' in results:
			proforma_tax_credits = [
				['Investment tax credit (ITC)', '' ],
                ['As percentage', '%' ],
                ['Federal', batteryItcPercent ]
			]
			write_table(proforma_tax_credits, 'BATTERY TAX CREDITS', excel_row, excel_col)
			excel_row += len(proforma_tax_credits) + 2

			proforma_cash_incentives = [
				['Capacity based incentive (CBI)', 'Amount'],
				['Total ($/W)', outData['batteryCbiKw' + indexString] ],
				['Total  ($/Wh)', outData['batteryCbiKwh' + indexString] ]
			]
			write_table(proforma_cash_incentives, 'BATTERY DIRECT CASH INCENTIVES',excel_row,excel_col)
			excel_row += len(proforma_cash_incentives) + 2
			
		
		depreciation_proforma = [
			['DEPRECIATION'],
            ['Federal (years)'],
            ['Federal bonus fraction']
        ]

		def add_to_depreciation_proforma(der_type, years, bonus_fraction):
			depreciation_proforma[0].append(der_type)
			depreciation_proforma[1].append(years)
			depreciation_proforma[2].append(bonus_fraction)
		
		if 'PV' in results:
			pv_bonus_fraction = outData['pvMacrsBonusFraction' + indexString]
			add_to_depreciation_proforma("PV",str(solarMacrsOptionYears), pv_bonus_fraction)
			
		if 'ElectricStorage' in results:
			battery_bonus_fraction = outData['batteryMacrsBonusFraction' + indexString]
			add_to_depreciation_proforma("BATTERY",str(batteryMacrsOptionYears), battery_bonus_fraction)
			
		if 'Wind' in results:
			wind_bonus_fraction = outData['windMacrsBonusFraction' + indexString]
			add_to_depreciation_proforma("WIND", str(windMacrsOptionYears), wind_bonus_fraction)
			
		write_table(depreciation_proforma, "",excel_row,excel_col)
		excel_col += len(depreciation_proforma[0]) + 1
		
		macrs_proforma = [
			["Year"] + [str(i) for i in range(1,9)],
			["5-Year"] + outData['macrsFiveYear' + indexString], 
			["7-Year"] + outData['macrsSevenYear' + indexString]
		]

		write_table(macrs_proforma,"MACRS SCHEDULES (INFORMATIONAL ONLY)",excel_row,excel_col)
		excel_row += len(macrs_proforma) + 2
		excel_col = 0

		annual_values_proforma = [
			['ANNUAL VALUES'],
			['PV Annual electricity (kWh)'],
			['Existing PV Annual electricity (kWh)'],
			['Wind Annual electricity (kWh)'],
			['Backup Generator Annual electricity (kWh)'],
			['PV Federal depreciation percentages (fraction)'],
			['Wind Federal depreciation percentages (fraction)'],
			['Battery Federal depreciation percentages (fraction)'],
			['Free Cash Flow'],
			['Cumulative Free Cash Flow']
		]

		def get_macrs(i, macrs):
			if i > macrs or i == 0:
				return "0"
			elif macrs == 5:
				return macrs_proforma[1][i]
			elif macrs == 7:
				return macrs_proforma[2][i]
			else:
				return "0"
			
		def get_energy_produced(energy_type, degradation_type, i):
			return str(outData.get(energy_type + indexString,0) * pow(1 - outData.get(degradation_type + indexString,0),i))

		for i in range(analysisYears):
			annual_values_proforma[0].append(str(i))
			annual_values_proforma[1].append(get_energy_produced('pvYearOneEnergyProduced','degradationRatePVFraction',i))
			annual_values_proforma[2].append(get_energy_produced('pvYearOneEnergyProducedBAU','degradationRatePVFraction',i))
			annual_values_proforma[3].append(get_energy_produced('windAnnualEnergyProduced','degradationRateWindFraction',i))
			annual_values_proforma[4].append(get_energy_produced('dieselAnnualEnergyProduced','degradationRateBatteryFraction',i))
			annual_values_proforma[5].append(get_macrs(i, solarMacrsOptionYears))
			annual_values_proforma[6].append(get_macrs(i, windMacrsOptionYears))
			annual_values_proforma[7].append(get_macrs(i, batteryMacrsOptionYears))

		annual_values_proforma[8].extend(outData['freeCashFlows' + indexString])
		annual_values_proforma[9].extend(np.cumsum(outData['freeCashFlows' + indexString]))

		write_table(annual_values_proforma,"",excel_row,excel_col)
		excel_row += len(annual_values_proforma) + 1

		workbook.save(os.path.join(modelDir,"ProForma.xlsx"))

		#helper function for generating output graphs
		def makeGridLine(x,y,color,name):
			plotLine = go.Scatter(
				x = x, 
				y = y,
				line = dict( color=(color)),
				name = name,
				hoverlabel = dict(namelength = -1),
				showlegend=True,
				stackgroup='one',
				mode='none'
			)
			return plotLine

		#Set plotly layout ---------------------------------------------------------------
		plotlyLayout = go.Layout(
			width=1000,
			height=375,
			legend=dict(
				x=0,
				y=1.25,
				orientation="h")
			)
		x = list(range(len(outData['powerGridToLoad' + indexString])))
		plotData = []
		x_values = pd.to_datetime(x, unit = 'h', origin = pd.Timestamp(f'{year}-01-01'))
		powerGridToLoad = makeGridLine(x_values,outData['powerGridToLoad' + indexString],'blue','Load met by Grid')
		plotData.append(powerGridToLoad)

		if 'PV' in results:
			powerPVToLoad = makeGridLine(x_values,outData['powerPVToLoad' + indexString],'yellow','Load met by Solar')
			plotData.append(powerPVToLoad)

		if 'ElectricStorage' in results:
			powerBatteryToLoad = makeGridLine(x_values,outData['powerBatteryToLoad' + indexString],'gray','Load met by Battery')
			plotData.append(powerBatteryToLoad)

		if 'Wind' in results:
			powerWindToLoad = makeGridLine(x_values,outData['powerWindToLoad' + indexString],'purple','Load met by Wind')
			plotData.append(powerWindToLoad)

		if 'Generator' in results and results['Generator']['size_kw'] > 0:
			powerDieselToLoad = makeGridLine(x_values,outData['powerDieselToLoad' + indexString],'brown','Load met by Fossil Gen')
			plotData.append(powerDieselToLoad)			

		plotlyLayout['yaxis'].update(title='Power (kW)')
		plotlyLayout['xaxis'].update(title='Time')
		outData["powerGenerationData" + indexString ] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
		outData["plotlyLayout"] = json.dumps(plotlyLayout, cls=plotly.utils.PlotlyJSONEncoder)

		plotData = []
		if 'PV' in results:
			powerPVToLoad = makeGridLine(x_values,outData['powerPVToLoad' + indexString],'yellow','Solar used to meet Load')
			plotData.append(powerPVToLoad)

			powerPVToGrid = makeGridLine(x_values,outData['powerPVToGrid' + indexString],'blue','Solar exported to Grid')
			plotData.append(powerPVToGrid)

			powerPVCurtailed = makeGridLine(x_values,outData['powerPVCurtailed' + indexString],'red','Solar power curtailed')
			plotData.append(powerPVCurtailed)

			if 'ElectricStorage' in results:
				powerPVToBattery = makeGridLine(x_values,outData['powerPVToBattery' + indexString],'gray','Solar used to charge Battery')
				plotData.append(powerPVToBattery)

			# powerPV = go.Scatter(
			# 	x=pd.to_datetime(x, unit = 'h', origin = pd.Timestamp(f'{year}-01-01')),
			# 	y=outData['powerPV' + indexString],
			# 	line=dict( color=('red') ),
			# 	name="Solar Generation")
			# plotData.append(powerPV)

		outData["solarData" + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)

			
		plotData = []
		if 'Wind' in results:
			powerWindToLoad = makeGridLine(x_values,outData['powerWindToLoad' + indexString],'purple','Wind used to meet Load')
			plotData.append(powerWindToLoad)

			if 'ElectricStorage' in results:
				powerWindToBattery = makeGridLine(x_values,outData['powerWindToBattery' + indexString],'gray','Wind used to charge Battery')
				plotData.append(powerWindToBattery)

			# powerWind = go.Scatter(
			# 	x=pd.to_datetime(x, unit = 'h', origin = pd.Timestamp(f'{year}-01-01')),
			# 	y=outData['powerWind' + indexString],
			# 	line=dict( color=('red') ),
			# 	name="Wind Generation")
			# plotData.append(powerWind)

		outData["windData"  + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)

		plotData = []
		if 'Generator' in results and results['Generator']['size_kw'] > 0:
			powerDieselToLoad = makeGridLine(x_values,outData['powerDieselToLoad' + indexString],'brown','Fossil Gen used to meet Load')
			plotData.append(powerDieselToLoad)

			if 'ElectricStorage' in results:
				powerDieselToBattery = makeGridLine(x_values,outData['powerDieselToBattery' + indexString],'gray','Fossil Gen used to charge Battery')
				plotData.append(powerDieselToBattery)

			# powerDiesel = go.Scatter(
			# 	x=pd.to_datetime(x, unit = 'h', origin = pd.Timestamp(f'{year}-01-01')),
			# 	y=outData['powerDiesel' + indexString],
			# 	line=dict( color=('red') ),
			# 	name="Fossil Generation")
			# plotData.append(powerDiesel)

		outData["dieselData"  + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)

		plotData = []
		if 'ElectricStorage' in results:
			powerGridToBattery = makeGridLine(x_values,outData['powerGridToBattery' + indexString],'blue','Grid')
			plotData.append(powerGridToBattery)

			if 'PV' in results:
				powerPVToBattery = makeGridLine(x_values,outData['powerPVToBattery' + indexString],'yellow','Solar')
				plotData.append(powerPVToBattery)

			if 'Wind' in results:
				powerWindToBattery = makeGridLine(x_values,outData['powerWindToBattery' + indexString],'purple','Wind')
				plotData.append(powerWindToBattery)

			if 'Generator' in results and results['Generator']['size_kw'] > 0:
				powerDieselToBattery = makeGridLine(x_values,outData['powerDieselToBattery' + indexString],'brown','Fossil Gen')
				plotData.append(powerDieselToBattery)


		outData["batteryData" + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
			
		plotData = []
		if 'ElectricStorage' in results:
			chargeLevelBattery = go.Scatter(
				x=pd.to_datetime(x, unit = 'h', origin = pd.Timestamp(f'{year}-01-01')),
				y=outData['chargeLevelBattery' + indexString],
				line=dict( color=('red') )
			)
			plotData.append(chargeLevelBattery)
			plotlyLayout['yaxis'].update(title='Charge (%)')
			plotlyLayout['xaxis'].update(title='Time')
			outData["batteryChargeData" + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
			outData["batteryChargeLayout" + indexString] = json.dumps(plotlyLayout, cls=plotly.utils.PlotlyJSONEncoder)
		# plot resilience stats if resilienceRun was successful
		if run_outages: #'resilience_by_timestep' in resultsResilience['outage_sim_results']:
			plotData = []
			resilience = go.Scatter(
				x=x,
				y=outData['resilience'+ indexString],
				line=dict( color=('red') ),
			)
			plotData.append(resilience)
			plotlyLayout['yaxis'].update(title='Longest Outage survived (Hours)')
			plotlyLayout['xaxis'].update(title='Start Hour')
			outData["resilienceData" + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
			outData["resilienceLayout" + indexString] = json.dumps(plotlyLayout, cls=plotly.utils.PlotlyJSONEncoder)
			plotData = []
			survivalProb = go.Scatter(
				x=outData['survivalProbX' + indexString],
				y=outData['survivalProbY' + indexString],
				line=dict( color=('red') ),
				name="Probability of Surviving Outage of a Given Duration")
			plotData.append(survivalProb)
			plotlyLayout['yaxis'].update(title='Probability of meeting critical Load')
			plotlyLayout['xaxis'].update(title='Outage Length (Hours)')
			outData["resilienceProbData" + indexString] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
			outData["resilienceProbLayout"  + indexString] = json.dumps(plotlyLayout, cls=plotly.utils.PlotlyJSONEncoder)
		if numCols == 1:
			#todo: test reopt.jl updates with multiple loads
			break # if we only have a single load, don't run an additional combined load shape run.

	return outData

def runtimeEstimate(modelDir):
	''' Estimated runtime of model in minutes. '''
	return 2.0

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	# fName = "input - col 1 commercial 120 kW per day, col 2 residential  30 kWh per day.csv"
	fName = "input - 200 Employee Office, Springfield Illinois, 2001.csv"
	with open(pJoin(omf.omfDir, "static", "testFiles", fName)) as f:
		load_shape = f.read()
	cfName = "critical_load_test.csv"
	with open(pJoin(omf.omfDir, "static", "testFiles", cfName)) as f:
		crit_load_shape = f.read()
	defaultInputs = {
		"modelType": modelName,
		"runTime": "",
		"loadShape" : load_shape,
		"criticalLoadShape" : crit_load_shape,
		"solar" : True,
		"wind" : False,
		"battery" : True,
		"fileName" : fName,
		"criticalFileName" : cfName,
		"latitude" : '39.7817',
		"longitude" : '-89.6501',
		"year" : '2017',
		"analysisYears" : '25',
		"discountRate" : '0.083', # Nominal energy offtaker discount rate. In single ownership model the offtaker is also the generation owner
        "solverTolerance": "0.05", # The threshold for the difference between the solution's objective value and the best possible value at which the solver terminates
		"maxRuntimeSeconds": "240",
		"energyCost" : "0.1",
		"demandCost" : '20',
		"urdbLabelSwitch": False,
		"urdbLabel" : '5b75cfe95457a3454faf0aea',
		# TODO: Enable all instances of 'annualCostSwitch', 'energyCostMonthly', 'demandCostMonthly' in mgDesign.py once a suitable way to enter a list of 12 monthly rates is found for mgDesign.html
		# "annualCostSwitch": "off",
		# "energyCostMonthly" : [0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531, 0.0531],
		# "demandCostMonthly" : [8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879, 8.6879],
		"wholesaleCost" : "0.034",
		"omCostEscalator" : "0.025", # annual O+M cost escalation rate for all generation types
		"solarMacrsOptionYears": "5", # Set to zero to disable MACRS accelerated depreciation
		"windMacrsOptionYears": "5", # Set to zero to disable MACRS accelerated depreciation
		"batteryMacrsOptionYears": "7", # Set to zero to disable MACRS accelerated depreciation
		"dieselMacrsOptionYears": 0, # Set to zero to disable MACRS accelerated depreciation
		"solarItcPercent": "0.26",
		"windItcPercent": "0.26",
		"batteryItcPercent": 0,
		"solarCost" : "1600",
		"windCost" : "4898",
		"batteryPowerCost" : "840",
		"batteryCapacityCost" : "420",
		"batteryPowerCostReplace" : "410",
		"batteryCapacityCostReplace" : "200",
		"batteryPowerReplaceYear": '10', # year at which batteryPowerCostReplace (the inverter) is reinstalled, one time
		"batteryCapacityReplaceYear": '10', # year at which batteryCapacityCostReplace (the battery cells) is reinstalled, one time
		"dieselGenCost": "500",
		"solarMin": 0,
		"windMin": 0,
		"batteryPowerMin": 0,
		"batteryCapacityMin": 0,
		"dieselMin": 0,
		"solarMax": "10000000",
		"windMax": "10000000",
		"batteryPowerMax": "1000000",
		"batteryCapacityMax": "1000000",
		"batterySocMinFraction": "0.2",
		"dieselMax": "100000",
		"solarExisting": 0,
		"outage_start_hour": "500",
		"outageDuration": "24",
		"fuelAvailable": "20000",
		"genExisting": 0,
		"minGenLoading": "0.3",
		"dieselFuelCostGal": "3", # default value for diesel
		"dieselCO2Factor": 22.4, # default value for diesel
		"dieselOMCostKw": 10, # default value for diesel
		"dieselOMCostKwh": 0, # default value for diesel
		#"windExisting": "20",
		#"batteryKwExisting": 0,
		#"batteryKwhExisting": 0,
		"value_of_lost_load": "100",
		"solarCanCurtail": True,
		"solarCanExport": True,
		"dieselOnlyRunsDuringOutage": True,
		"criticalLoadFactor": "0.5"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _tests():
		# Location
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
	renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
