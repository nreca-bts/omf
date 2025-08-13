''' Performs a cost-benefit analysis for a utility or cooperative member interested in 
controlling behind-the-meter distributed energy resources (DERs).'''

## Python imports
import warnings
#warnings.filterwarnings("ignore")
import shutil, datetime, csv, json
from os.path import join as pJoin
import numpy as np
import pandas as pd
import plotly.graph_objs as go
import plotly.utils
import plotly.express as px
from numpy_financial import npv

## OMF imports
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.models import vbatDispatch as vb
from omf.solvers import reopt_jl

## Model metadata:
tooltip = ('The derUtilityCost model evaluates the financial costs of controlling behind-the-meter '
	'distributed energy resources (DERs) using the NREL Renewable Energy Optimization Tool (REopt) and '
	'the OMF virtual battery dispatch module (vbatDispatch).')
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True ## Keep the model hidden=True during active development

## NOTE & TODO: This function needs development. The purpose of this function is to handle both the energy rate structure and the demand charge rate structure from the .json response file, whereas the construct_energy_rate_array() function only handles the energy rate structure information.
def construct_tou_tariff_arrays(response_file, timestamps):
	"""
	Constructs hourly rate arrays (length 8760) for TOU Energy Charges ($/kWh), TOU Demand Charges ($/kW), and fixed monthly facility demand charges ($/kW/month).
	Inputs:
	- response_file (JSON): File generated from the NREL REopt Custom Tariff Builder (requires a free account) https://reopt.nrel.gov/tool/custom_tariffs/new which contains information abou the TOU Energy Charges, TOU Demand Charges, and facility demand charges if applicable.
	- timestamps (array, length 8760): Hourly timestamps for the year used to identify the proper weekdays and weekends when building the rate schedules.

	Returns:
	- energy_rate_array (array, length 8760): The hourly energy rates ($/kWh) for an entire year
	- TODO: demand_rate_array (not currently implemented)
	- monthly_demand_rates (array, length 12): The monthly demand charges ($/kW) for an entire year
	"""
	energy_rate_array = np.zeros(8760)
	if 'energyratestructure' in response_file:
		## The energy rate structure refers to a nested list of dictionary items with "rate" and "unit" keys
		## For example: response_file['energyratestructure'] = [[{'rate': 0, 'unit': 'kWh'}], [{'rate': 0.06, 'unit': 'kWh'}], [{'rate': 0.1525, 'unit': 'kWh'}]]
		## Must first flatten the nested list of dictionary objects and extract the rate information for index-based access
		energy_weekday_schedule = response_file['energyweekdayschedule']
		energy_weekend_schedule = response_file['energyweekendschedule']
		energy_rate_structure_flattened = [item[0] for item in response_file['energyratestructure']]
		energy_rates = [item['rate'] for item in energy_rate_structure_flattened]
		
		## Construct an array of 8760 elements representing the hourly energy rates ($/kWh) for the entire year
		for hour_index, date in enumerate(timestamps):
			if date.weekday() < 5:  ## Weekdays (Monday=0, Sunday=7) - use the weekday rate schedule
				energy_rate_array[hour_index] = energy_rates[energy_weekday_schedule[date.month-1][date.hour]] ## NOTE: date.month is offset by 1 due to 0 indexing
			else: ## Weekends - use the weekend rate schedule
				energy_rate_array[hour_index] = energy_rates[energy_weekend_schedule[date.month-1][date.hour]]

	## --- Demand Rate Construction ---
	#demand_rate_array = np.zeros(8760)
	#if 'demandratestructure' in response_file:
	#	demand_weekday_schedule = response_file['demandweekdayschedule']
	#	demand_weekend_schedule = response_file['demandweekendschedule']
	#	demand_rate_structure_flattened = [item[0] for item in response_file['demandratestructure']]
	#	demand_rates = [item['rate'] for item in demand_rate_structure_flattened]

	#	demand_rate_array = np.zeros(8760)
	#	for i, date in enumerate(timestamps):
	#		schedule = demand_weekday_schedule if date.weekday() < 5 else demand_weekend_schedule
	#		tier = schedule[date.month - 1][date.hour]
	#		demand_rate_array[i] = demand_rates[tier]
			
	## --- Facility Demand Charge Construction ---
	monthly_demand_charge = np.zeros(12)
	if 'flatdemandmonths' in response_file and len(response_file['flatdemandmonths']) != 0:
		demand_rate_structure_flattened = [item[0] for item in response_file['flatdemandstructure']]
		demand_rates = [item['rate'] for item in demand_rate_structure_flattened]
		del demand_rates[0] ## Drop the first element which is a value of 0 due to zero-indexing structure
		monthly_demand_charge = np.array(demand_rates)

		##TODO: Add functionality for multi-tiered rates?
		#for month in range(12):
		#	period = response_file['flatdemandmonths'][month] ## zero-indexed
		#	rate = response_file['flatdemandstructure'][period] ## Rate for the corresponding period month
		#	
		#	for t, tier in enumerate(rates):
		#		demand_rates[month,t] = 
		
	## --- Fixed charges $/day ---

	return energy_rate_array, monthly_demand_charge#, demand_rate_array

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	
	## Delete output file every run if it exists
	outData = {}

	## Convert user provided demand and temperature data from str to float
	## NOTE: assumes the input temperature curve is in degrees Fahrenheit. The degrees Celsius conversion is used later for vbatDispatch, which expects deg C. 
	temperatures_degF = [float(value) for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	temperatures_degC = [float(value)-32.0 * 5/9 for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	demand = [float(value) for value in inputDict['demandCurve'].split('\n') if value.strip()]
	
	## Check if the demand and temperature curves are the correct length and account for leap years by removing Dec 31 data.
	if len(demand) != 8760:
		raise Exception(f"Demand Curve must have exactly 8760 elements, but got {len(demand)}. If this is a leap year, remove December 31 and ensure there are 8760 elements.")
	if len(temperatures_degF) != 8760:
		raise Exception(f"Temperature Curve must have exactly 8760 elements, but got {len(temperatures_degF)}. If this is a leap year, remove December 31 and ensure there are 8760 elements.")

	## Gather input variables to pass to the omf.solvers.reopt_jl model
	latitude = float(inputDict['latitude'])
	longitude = float(inputDict['longitude'])
	year = int(inputDict['year'])
	projectionLength = int(inputDict['projectionLength'])
	
	########################################################################################################################################################
	## Construct the timestamp array
	## If the input year is a leap year, remove the last day in December and keep the extra day in February as recommended in REopt's documentation:
	## https://reopt.nrel.gov/tool/reopt-user-manual.pdf#page=37 (Section 7.1 Actual (Custom) Load Profile)
	########################################################################################################################################################
	start_date = pd.Timestamp(f'{year}-01-01')
	is_leap_year = start_date.is_leap_year
	if is_leap_year == True:
		## If it's a leap year, do not use the last day in December
		end_date = f'{year}-12-30 23:59'
	else:
		## If it's not a leap year, use all of December
		end_date = f'{year}-12-31 23:59'
	timestamps = pd.date_range(start=start_date, end=end_date, freq='h')

	if len(timestamps) != 8760:
		raise Exception(f"The timestamp array should be 8760 elements long. Instead, got {len(timestamps)} elements.")
	
	########################################################################################################################################################
	## Construct the wholesale energy rate structure array
	## Expects a user-provided JSON file or the default static testFile provided in the OMF
	########################################################################################################################################################
	if inputDict.get('useWholesaleJSONBool'): ## Checkbox to use the .json file is True by default
		## Load the Wholesale Energy Rate Structure JSON file
		try:
			## Try to normally parse the JSON file and use it as a Python dictionary
			response_file = json.loads(inputDict['wholesaleRateStructure'])
		except json.JSONDecodeError:
			## Convert single quotes to double quotes for proper JSON formatting, then parse the JSON and use it as a Python dictionary
			fixed = inputDict['wholesaleRateStructure'].replace("'", '"')
			response_file = json.loads(fixed)
		except TypeError:
			## If the wholesale_rate_curve is already a Python dictionary, use it directly
			if isinstance(inputDict['wholesaleRateStructure'], dict):
				response_file = inputDict['wholesaleRateStructure']
		
		## Construct the energy rate array from the JSON file (used in the financial analysis below)
		#energy_rate_array, monthly_demand_charge, demand_rate_array = construct_tou_tariff_arrays(response_file, timestamps)
		energy_rate_array, monthly_demand_charge = construct_tou_tariff_arrays(response_file, timestamps)

	else: ## Use the Wholesale Energy Rate Curve (.csv) file instead of the Wholesale Energy Rate Structure (.json) file
		energy_rate_array = [float(value) for value in inputDict['wholesaleRateCurve'].split('\n') if value.strip()]
		monthly_demand_charge = np.zeros(12)
		#demand_rate_array = np.fill(12,inputDict['demandChargeCost'])
		if len(energy_rate_array) != 8760:
			raise ValueError(f"Energy Rate Curve must have exactly 8760 values, but got {len(energy_rate_array)}.")
		
	########################################################################################################################
	## Construct monthly demand charge ($/kW) array
	########################################################################################################################
	## Define the monthly peak demand charge array ($/kW per month) the utility pays to the G&T
	if sum(monthly_demand_charge) == 0:
		## If no monthly demand charge is specified in the JSON response file, use the user-defined CSV input instead
		#peakDemandCharge = np.full(12, float(inputDict['demandChargeCost']))
		peakDemandCharge = np.array([float(value) for value in inputDict['monthlyDemandCharges'].split('\n') if value.strip()])
	else:
		## Use the array of $/kW demand charges defined in the input JSON response file, assuming the values are non-zero.
		peakDemandCharge = np.array(monthly_demand_charge)

	########################################################################################################################
	## Run REopt.jl solver
	########################################################################################################################
	
	## Create a REopt input dictionary called 'scenario' (required input for omf.solvers.reopt_jl)
	scenario = {
		'Site': {
			'latitude': latitude,
			'longitude': longitude
		},
		'ElectricTariff': {
			#'urdb_label': urdbLabel,
			#'urdb_response': response_file,
			#'tou_energy_rates_per_kwh': energy_rate_array.tolist(), ## This method produced some issues with REopt (e.g. no generator was present in the outputs)
			'add_tou_energy_rates_to_urdb_rate': True
		},
		'ElectricLoad': {
			'loads_kw': demand,
			'year': year
		},
		'Financial': {
			'analysis_years': projectionLength
		}
	}

	## Adjust the Electric Tariff input to REopt based on the user's preference of either the Wholesale Energy Rate Structure (.json) or Wholesale Energy Rate Curve (.csv)
	if inputDict.get('useWholesaleJSONBool'): 
		## Use the Wholesale Energy Rate Structure (.json) file
		scenario['ElectricTariff']['urdb_response'] = response_file
	else: 
		## Use the Wholesale Energy Rate Curve (.csv) file
		scenario['ElectricTariff']['tou_energy_rates_per_kwh'] = energy_rate_array#.tolist()

	## Add fossil fuel generator to input scenario, if enabled
	if inputDict['fossilGenerator'] == 'Yes' and float(inputDict['number_devices_GEN']) > 0:
		GENcheck = 'enabled'
		scenario['Generator'] = {
			'existing_kw': float(inputDict['existing_gen_kw']) * float(inputDict['number_devices_GEN']),
			'max_kw': 0.0, ## New generator minumum
			'min_kw': 0.0, ## New generator maximum
			'only_runs_during_grid_outage': False,
			'fuel_avail_gal': float(inputDict['fuel_avail']) * float(inputDict['number_devices_GEN']),
			'fuel_cost_per_gallon': float(inputDict['fuel_cost']),
		}
	else:
		GENcheck = 'disabled'

	## Add a Battery Energy Storage System (BESS) section to REopt input scenario, if enabled 
	if inputDict['enableBESS'] == 'Yes' and float(inputDict['number_devices_BESS']) > 0:
		BESScheck = 'enabled'
		scenario['ElectricStorage'] = {
			'min_kw': float(inputDict['BESS_kw']) * float(inputDict['number_devices_BESS']),
			'max_kw': float(inputDict['BESS_kw']) * float(inputDict['number_devices_BESS']),
			'min_kwh': float(inputDict['BESS_kwh']) * float(inputDict['number_devices_BESS']),
			'max_kwh': float(inputDict['BESS_kwh']) * float(inputDict['number_devices_BESS']),
			'can_grid_charge': True,
			'total_rebate_per_kw': 0,
			'macrs_option_years': 0,
			'installed_cost_per_kw': 0,
			'installed_cost_per_kwh': 0,
			'battery_replacement_year': 0,
			'inverter_replacement_year': 0,
			'replace_cost_per_kwh': 0.0,
			'replace_cost_per_kw': 0.0,
			'total_rebate_per_kw': 0.0,
			'total_itc_fraction': 0.0,
			}
	else:
		BESScheck = 'disabled'
	
	## Save the scenario file
	## NOTE: reopt_jl currently requires a path for the input file, so the file must be saved to a location preferrably in the modelDir directory
	with open(pJoin(modelDir, 'reopt_input_scenario.json'), 'w') as jsonFile:
		json.dump(scenario, jsonFile)

	########################################################################################################################
	## Run REopt.jl
	########################################################################################################################
	reopt_jl.run_reopt_jl(modelDir, 'reopt_input_scenario.json')

	## Load the REopt results once it is finished running.
	## TODO: Add warnings here to handle when REopt does not produce an output or gives an error
	with open(pJoin(modelDir, 'results.json')) as jsonFile:
		reoptResults = json.load(jsonFile)
	outData.update(reoptResults) ## Update output file with reopt results

	## Check if DER technology is enabled by the user and define relevant variables from REopt
	if BESScheck == 'enabled':
		BESS = reoptResults['ElectricStorage']['storage_to_load_series_kw']
		grid_charging_BESS = reoptResults['ElectricUtility']['electric_to_storage_series_kw']
		outData['chargeLevelBattery'] = list(np.array(reoptResults['ElectricStorage']['soc_series_fraction']) * 100.)
	else:
		BESS = np.zeros_like(demand)
		grid_charging_BESS = np.zeros_like(demand)
		outData['chargeLevelBattery'] = list(np.zeros_like(demand))

	if GENcheck == 'enabled':
		generator = np.array(reoptResults['Generator']['electric_to_load_series_kw'])
	else:
		generator = np.zeros_like(demand)

	########################################################################################################################
	## Run vbatDispatch model
	########################################################################################################################
	
	## Set up base input dictionary for vbatDispatch runs
	inputDict_vbatDispatch = {
		'load_type': '', ## 1=AirConditioner, 2=HeatPump, 3=Refrigerator, 4=WaterHeater (This is from OMF model vbatDispatch.html)
		'number_devices': '',
		'power': '',
		'capacitance': '',
		'resistance': '',
		'cop': '',
		'setpoint':  '',
		'deadband': '',
		'unitDeviceCost': '0.0', ## set to zero: assuming utility does not pay for this
		'unitUpkeepCost':  '0.0', ## set to zero: assuming utility does not pay for this
		'monthlyDemandCharges': inputDict['monthlyDemandCharges'],
		'projectionLength': inputDict['projectionLength'],
		'discountRate': inputDict['discountRate'],
		'fileName': inputDict['fileName'],
		'tempFileName': inputDict['temperatureFileName'],
		'demandCurve': inputDict['demandCurve'],
		'tempCurve': '\n'.join(f"{temperature:.2f}" for temperature in temperatures_degC), ## Convert temperatures_degC into the expected format for vbatDispatch
		'energyRateCurve': '\n'.join(f"{rate:.2f}" for rate in energy_rate_array), ## Convert energy_rate_array into the expected format for vbatDispatch
	}
	
	## Define thermal variables that change depending on the thermal technology(ies) enabled by the user
	thermal_suffixes = ['_hp', '_ac', '_wh'] ## heat pump, air conditioner, water heater - (Add more suffixes here after establishing inputs in the defaultInputs and derUtilityCost.html)
	thermal_variables=['load_type','number_devices','power','capacitance','resistance','cop','setpoint','deadband','TESS_subsidy_ongoing','TESS_subsidy_onetime']

	all_device_suffixes = []
	single_device_results = {} 
	for suffix in thermal_suffixes:
		## Include only the thermal devices specified by the user
		if float(inputDict['load_type'+suffix]) > 0: ## NOTE: If thermal tech is not enabled by the user, the load_type_X variable will be set to 0 in derConsumer.html
			all_device_suffixes.append(suffix)

			## Add the appropriate thermal device variables to the inputDict_vbatDispatch
			for i in thermal_variables:
				inputDict_vbatDispatch[i] = inputDict[i+suffix]

			## Create a model subdirectory for each thermal device and store the vbatDispatch results
			newDir = pJoin(modelDir,'vbatDispatch_results'+suffix)
			os.makedirs(newDir, exist_ok=True)
			os.chdir(newDir) ##jump into the newly created subdirectory

			## Run vbatDispatch for the thermal device
			vbatResults = vb.work(modelDir,inputDict_vbatDispatch)
			with open(pJoin(newDir, 'vbatResults.json'), 'w') as jsonFile:
				json.dump(vbatResults, jsonFile)
			
			## Update the vbatResults to include subsidies (for easier usage later)
			vbatResults['TESS_subsidy_onetime'] = float(inputDict_vbatDispatch['TESS_subsidy_onetime'])*float(inputDict['number_devices'+suffix])
			vbatResults['TESS_subsidy_ongoing'] = float(inputDict_vbatDispatch['TESS_subsidy_ongoing'])*float(inputDict['number_devices'+suffix])

			## Store the results in all_device_results dictionary
			single_device_results['vbatResults'+suffix] = vbatResults

			## Go back to the main derUtilityCost model directory and continue on
			os.chdir(modelDir)
	
	########################################################################################################################
	## TESS technology combined and individual calculations
	########################################################################################################################
	## Define the consumption rate compensation ($/kWh) paid to member-consumers
	#consumptionCost = float(inputDict['electricityCost'])
	rateCompensation = float(inputDict['rateCompensation'])

	## Initialize an empty dictionary to hold all thermal device results added together
	## Length 8760 represents hourly data for one year, length 12 is monthly data for a year
	combined_device_results = {
		'vbatPower_series': [0]*8760,
		'vbat_charge': [0]*8760,
		'vbat_discharge': [0]*8760,
		'vbat_charge_flipsign': [0]*8760,
		'vbatMinEnergyCapacity': [0]*8760,
		'vbatMaxEnergyCapacity':[0]*8760,
		'vbatEnergy':[0]*8760,
		'vbatMinPowerCapacity': [0]*8760,
		'vbatMaxPowerCapacity': [0]*8760,
		'vbatPower': [0]*8760,
		'savingsTESS': [0]*12,
		'energyAdjustedMonthlyTESS': [0]*12,
		'demandAdjustedTESS': [0]*8760,
		'peakAdjustedDemandTESS': [0]*12,
		'totalCostAdjustedTESS': [0]*12,
		'demandChargeAdjustedTESS': [0]*12,
		'monthlyEnergyConsumptionCost_Adjusted_TESS':[0]*12,
		'combinedTESS_subsidy_ongoing': 0,
		'combinedTESS_subsidy_onetime': 0,
	}

	thermal_device_savings = {}
	## Combine all thermal device variable data for plotting
	for device_result in single_device_results:
		single_device_vbatPower = single_device_results[device_result]['VBpower']
		single_device_vbatPower_series = pd.Series(single_device_vbatPower)
		single_device_vbat_discharge_component = single_device_vbatPower_series.where(single_device_vbatPower_series > 0, 0) ##positive values = discharging
		single_device_vbat_charge_component = single_device_vbatPower_series.where(single_device_vbatPower_series < 0, 0) ##negative values = charging
		#single_device_vbat_charge_component_flipsign = single_device_vbat_charge_component.mul(-1)
		
		combined_device_results['vbatPower'] = [sum(x) for x in zip(combined_device_results['vbatPower'], single_device_vbatPower)]
		combined_device_results['vbatMinEnergyCapacity'] = [sum(x) for x in zip(combined_device_results['vbatMinEnergyCapacity'], single_device_results[device_result]['minEnergySeries'])]
		combined_device_results['vbatMaxEnergyCapacity'] = [sum(x) for x in zip(combined_device_results['vbatMaxEnergyCapacity'], single_device_results[device_result]['maxEnergySeries'])]
		combined_device_results['vbatEnergy'] = [sum(x) for x in zip(combined_device_results['vbatEnergy'], single_device_results[device_result]['VBenergy'])]
		combined_device_results['vbatMinPowerCapacity'] = [sum(x) for x in zip(combined_device_results['vbatMinPowerCapacity'], single_device_results[device_result]['minPowerSeries'])]
		combined_device_results['vbatMaxPowerCapacity'] = [sum(x) for x in zip(combined_device_results['vbatMaxPowerCapacity'], single_device_results[device_result]['maxPowerSeries'])]
		combined_device_results['savingsTESS'] = [sum(x) for x in zip(combined_device_results['savingsTESS'], single_device_results[device_result]['savings'])]
		combined_device_results['energyAdjustedMonthlyTESS'] = [sum(x) for x in zip(combined_device_results['energyAdjustedMonthlyTESS'], single_device_results[device_result]['energyAdjustedMonthly'])]
		combined_device_results['demandAdjustedTESS'] = [sum(x) for x in zip(combined_device_results['demandAdjustedTESS'], single_device_results[device_result]['demandAdjusted'])]
		combined_device_results['peakAdjustedDemandTESS'] = [sum(x) for x in zip(combined_device_results['peakAdjustedDemandTESS'], single_device_results[device_result]['peakAdjustedDemand'])]
		combined_device_results['totalCostAdjustedTESS'] = [sum(x) for x in zip(combined_device_results['totalCostAdjustedTESS'], single_device_results[device_result]['totalCostAdjusted'])]
		combined_device_results['demandChargeAdjustedTESS'] = [sum(x) for x in zip(combined_device_results['demandChargeAdjustedTESS'], single_device_results[device_result]['demandChargeAdjusted'])]
		combined_device_results['monthlyEnergyConsumptionCost_Adjusted_TESS'] = [sum(x) for x in zip(combined_device_results['monthlyEnergyConsumptionCost_Adjusted_TESS'], single_device_results[device_result]['energyCostAdjusted'])]
		combined_device_results['combinedTESS_subsidy_ongoing'] += float(single_device_results[device_result]['TESS_subsidy_ongoing'])
		combined_device_results['combinedTESS_subsidy_onetime'] += float(single_device_results[device_result]['TESS_subsidy_onetime'])

		## Calculate subsidy for each thermal DER technology
		single_device_subsidy_ongoing = float(single_device_results[device_result]['TESS_subsidy_ongoing'])
		single_device_subsidy_onetime = float(single_device_results[device_result]['TESS_subsidy_onetime'])
		single_device_subsidy_year1_array = np.full(12, single_device_subsidy_ongoing)
		single_device_subsidy_year1_array[0] += single_device_subsidy_onetime
		single_device_subsidy_allyears_array = np.full(projectionLength, single_device_subsidy_ongoing*12.0)
		single_device_subsidy_allyears_array[0] += single_device_subsidy_onetime

		## Calculate the consumer compensation for each thermal DER technology
		monthHours = [(0, 744), (744, 1416), (1416, 2160), (2160, 2880), 
				(2880, 3624), (3624, 4344), (4344, 5088), (5088, 5832), 
				(5832, 6552), (6552, 7296), (7296, 8016), (8016, 8760)]
		single_device_compensation_year1_array = np.array([sum(single_device_vbat_discharge_component[s:f])*rateCompensation for s, f in monthHours])
		single_device_compensation_year1_total = np.sum(single_device_compensation_year1_array)
		single_device_compensation_allyears_array = np.full(projectionLength, single_device_compensation_year1_total)

		## Calculate the consumption cost savings for each DER tech using the input rate structure (hourly data for the whole year)
		single_device_consumption_cost_year1 = [float(a) * float(b) for a, b in zip(single_device_vbatPower, energy_rate_array)]
		single_device_consumption_cost_monthly = [sum(single_device_consumption_cost_year1[s:f]) for s, f in monthHours]
		single_device_consumption_cost_allyears = np.full(projectionLength, sum(single_device_consumption_cost_year1))
		single_device_monthlyTESS_consumption_total = [sum(single_device_vbatPower[s:f]) for s, f in monthHours]

		## Add up all the costs for the total TESS
		costs_year1_monthly_single_device = single_device_subsidy_year1_array + single_device_compensation_year1_array
		costs_allyears_single_device = single_device_subsidy_allyears_array + single_device_compensation_allyears_array 

		## Save relevant variables for calculating the demand cost savings later on
		thermal_device_savings[device_result] = {
			'demand': np.array(single_device_vbatPower),
			'consumption_cost_monthly': np.array(single_device_consumption_cost_monthly),
			'consumption_cost_allyears': np.array(single_device_consumption_cost_allyears),
    	}

		## Savings Breakdown Per Thermal Technology cost variables
		## NOTE: This is where the html variables outData['vbatResults_wh_costs_allyears'], outData['vbatResults_hp_costs_allyears'], and outData['vbatResults_ac_costs_allyears'] are saved.
		outData[device_result+'_costs_allyears'] = list(costs_allyears_single_device*-1.0) ## Multiply by negative one for displaying in the plot as a cost
		outData[device_result+'_check'] = 'enabled'

	## Get the charging and discharging behavior from the total combined TESS
	combined_TESS_vbatPower = combined_device_results['vbatPower']
	combined_TESS_vbatPower_series = pd.Series(combined_TESS_vbatPower)
	combined_device_results['vbat_discharge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series > 0, 0) ##positive values = discharging
	combined_device_results['vbat_charge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series < 0, 0) ##negative values = charging
	combined_device_results['vbat_charge_flipsign'] = combined_device_results['vbat_charge'].mul(-1)
	

	## NOTE: temporarily comment out the two derConsumer runs. This needs some development since derConsumer.py has changed over time.
	"""
	## Scale down the utility demand to create an ad-hoc small consumer load (1 kW average) and large consumer load (10 kW average)
	utilityLoadAverage = np.average(demand)
	smallConsumerTargetAverage = 1.0 #Unit: kW
	largeConsumerTargetAverage = 10.0 #Unit: kW
	smallConsumerLoadScaleFactor = smallConsumerTargetAverage / utilityLoadAverage 
	largeConsumerLoadScaleFactor = largeConsumerTargetAverage / utilityLoadAverage 
	smallConsumerLoad = demand * smallConsumerLoadScaleFactor
	largeConsumerLoad = demand * largeConsumerLoadScaleFactor

	## Convert small and large consumer load arrays into strings and pass it back to derConsumer
	smallConsumerLoadString = '\n'.join([str(value) for value in smallConsumerLoad])
	largeConsumerLoadString = '\n'.join([str(value) for value in largeConsumerLoad])

	## Create a new derConsumer model directory to store the results for both small and large consumers
	newDir_smallderConsumer = pJoin(modelDir,'smallderConsumer')
	newDir_largederConsumer = pJoin(modelDir,'largederConsumer')
	os.makedirs(newDir_smallderConsumer, exist_ok=True)
	os.makedirs(newDir_largederConsumer, exist_ok=True)
	os.chdir(newDir_smallderConsumer)
	print("Current Directory:", os.getcwd())

	## Set up model inputs for derConsumer and pass the small and large consumer loads to omf/models/derConsumer
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','residential_critical_load.csv')) as f:
		criticalLoad_curve = f.read()
	
	derConsumerInputDict = {
		## OMF inputs:
		'user' : 'admin',
		'modelType': modelName,
		'created': str(datetime.datetime.now()),

		## REopt inputs:
		## NOTE: Variables are strings as dictated by the html input options
		'latitude':  inputDict['latitude'], ## use utility's lat and lon 
		'longitude': inputDict['longitude'], 
		'year' : '2018',
		'urdbLabel': inputDict['urdbLabel'],
		'fileName': 'residential_PV_load.csv',
		'tempFileName': 'residential_extended_temperature_data.csv',
		'criticalLoadFileName': 'residential_critical_load.csv', ## critical load here = 50% of the daily demand
		'demandCurve': smallConsumerLoadString,
		'tempCurve': inputDict['tempCurve'],
		'criticalLoad': criticalLoad_curve,
		'criticalLoadSwitch': 'Yes',
		'criticalLoadFactor': '0.50',
		'PV': 'Yes',
		'BESS': 'Yes',
		'generator': 'No',
		'outage': True,
		'outage_start_hour': '4637',
		'outage_duration': '3',

		## Financial Inputs
		'demandChargeURDB': 'Yes',
		'demandChargeCost': '25',
		'projectionLength': '25',

		## vbatDispatch inputs:
		'load_type': '2', ## Heat Pump
		'number_devices': '1',
		'power': '5.6',
		'capacitance': '2',
		'resistance': '2',
		'cop': '2.5',
		'setpoint': '19.5',
		'deadband': '0.625',
		'electricityCost': '0.16',
		'discountRate': '2',
		'unitDeviceCost': '150',
		'unitUpkeepCost': '5',

		## DER Program Design inputs:
		'utilityProgram': 'No',
		'rateCompensation': '0.1', ## unit: $/kWh
		#'maxBESSDischarge': '0.80', ## Between 0 and 1 (Percent of total BESS capacity) #TODO: Fix the HTML input for this
		'subsidy': '12',
	}
	smallConsumerOutput = derConsumer.work(newDir_smallderConsumer,derConsumerInputDict)

	## Change directory to large derConsumer and run that case
	os.chdir(newDir_largederConsumer)
	derConsumerInputDict['demandCurve'] = largeConsumerLoadString
	derConsumerInputDict['number_devices'] = '2'
	largeConsumerOutput = derConsumer.work(newDir_largederConsumer,derConsumerInputDict)

	## Change directory back to derUtilityCost
	os.chdir(modelDir)
	outData.update({
		'TESSsavingsSmallConsumer': smallConsumerOutput['savings'],
		'TESSsavingsLargeConsumer': largeConsumerOutput['savings']
	})
	"""
	########################################################################################################################################################
	## DER Serving Load Overview plot 
	########################################################################################################################################################

	## vbatDispatch variables
	vbat_discharge_component = np.array(combined_device_results['vbat_discharge'])
	vbat_charge_component = np.array(combined_device_results['vbat_charge_flipsign'])
	vbat_charge_component[vbat_charge_component == -0.0] = 0.0 ## convert all -0 to just 0 for precaution

	## Convert all values from kW to Watts for plotting purposes only
	grid_to_load = reoptResults['ElectricUtility']['electric_to_load_series_kw']
	grid_to_load_W = np.array(grid_to_load) * 1000.
	BESS_W = np.array(BESS) * 1000.
	grid_charging_BESS_W = np.array(grid_charging_BESS) * 1000.
	vbat_discharge_component_W = vbat_discharge_component * 1000.
	vbat_charge_component_W = vbat_charge_component * 1000.
	demand_W = np.array(demand) * 1000.
	grid_serving_new_load_W = grid_to_load_W + grid_charging_BESS_W + vbat_charge_component_W - vbat_discharge_component_W
	generator_W = generator * 1000.

	## Put all DER plot variables into a dataFrame for plotting
	df = pd.DataFrame({
		'timestamp': timestamps,
		'Home BESS Serving Load': BESS_W,
		'Home TESS Serving Load': vbat_discharge_component_W,
		'Grid Serving Load': grid_to_load_W, #grid_serving_new_load_W,
		'Home Generator Serving Load': generator_W,
		'Grid Charging Home BESS': grid_charging_BESS_W,
		'Grid Charging Home TESS': vbat_charge_component_W
	})

	## Define colors for each plot series
	colors = {
		'Grid Serving Load': 'rgba(128, 128, 128, 0.8)',  ## Gray
		'Home BESS Serving Load': 'rgba(0, 128, 0, 0.8)',  ## Green
		'Home Generator Serving Load': 'rgba(139, 0, 0, 0.8)',  ## Dark red
		'Home TESS Serving Load': 'rgba(128, 0, 128, 0.8)',  ## Purple
		'Grid Charging Home BESS': 'rgba(0, 128, 0, 0.4)',  ## Green w/ half opacity
		'Grid Charging Home TESS': 'rgba(128, 0, 128, 0.4)'  ## Purple w/ half opacity
	}

	## Plot options
	showlegend = True ## either enable or disable the legend toggle in the plot
	lineshape = 'hv'
	fig = go.Figure()

	## Discharging DERs to plot
	for col in ["Grid Serving Load", "Home BESS Serving Load", "Home Generator Serving Load", "Home TESS Serving Load","Grid Charging Home BESS", "Grid Charging Home TESS"]:
		fig.add_trace(go.Scatter(
			x=df["timestamp"],
			y=df[col],
			fill="tonexty",
			mode="none",
			name=col,
			fillcolor=colors[col],
			line_shape=lineshape,			
			stackgroup="discharge"  ## Stack all the discharging DERs together
		))

	## Temperature line on a secondary y-axis (defined in the plot layout)
	fig.add_trace(go.Scatter(x=timestamps,
						y=temperatures_degF,
						yaxis='y2',
						#mode='lines',
						line=dict(color='red',width=1),
						name='Average Air Temperature',
						showlegend=showlegend 
						))
	
	## Make temperature and its legend name hidden in the plot by default
	fig.update_traces(legendgroup='Average Air Temperature', visible='legendonly', selector=dict(name='Average Air Temperature')) 
	fig.update_layout(
		xaxis_title="Timestamp",yaxis_title="Power (W)",
		yaxis2=dict(title='degrees Fahrenheit',overlaying='y',side='right'),
    	legend=dict(orientation='h',yanchor='bottom', xanchor='right',y=1.02,x=1,)
	)

	## NOTE: This opens a window that displays the correct figure with the appropriate patterns.
	## NOTE (cont.): For some reason, the slash-mark patterns are not showing up on the OMF page otherwise. Eventually we will delete this part.
	#fig.show()
	#outData['derOverviewHtml'] = fig.to_html(full_html=False)
	fig.write_html(pJoin(modelDir, "Plot_DerServingLoadOverview.html"))

	## Encode plot data as JSON for showing in the HTML 
	outData['derOverviewData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['derOverviewLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)

	###################################################################################################################################
	## Impact to Demand plot 
	###################################################################################################################################
	showlegend = True ## either enable or disable the legend toggle in the plot
	#lineshape = 'linear'
	lineshape = 'hv'

	fig = go.Figure()
	new_demand = demand_W + vbat_charge_component_W + grid_charging_BESS_W - BESS_W - vbat_discharge_component_W - generator_W

	## Original load piece (minus any vbat or BESS charging aka 'new/additional loads')
	fig.add_trace(go.Scatter(x=timestamps,
						y = demand_W,
						yaxis='y1',
						mode='none',
						name='Original Demand',
						fill='tozeroy',
						fillcolor='rgba(81,40,136,1)',
						showlegend=showlegend))
	## Make original load and its legend name hidden in the plot by default
	#fig.update_traces(legendgroup='Original Demand', visible='legendonly', selector=dict(name='Original Demand')) 

	## New demand piece (minus any vbat or BESS charging aka 'new/additional loads')
	fig.add_trace(go.Scatter(x=timestamps,
						y = new_demand,
						yaxis='y1',
						mode='none',
						name='New Demand',
						fill='tozeroy',
						fillcolor='rgba(235,97,35,0.5)',
						showlegend=showlegend))

	## Temperature line on a secondary y-axis (defined in the plot layout)
	fig.add_trace(go.Scatter(x=timestamps,
						y=temperatures_degF,
						yaxis='y2',
						#mode='lines',
						line=dict(color='red',width=1),
						name='Average Air Temperature',
						showlegend=showlegend 
						))
	
	## Make temperature and its legend name hidden in the plot by default
	fig.update_traces(legendgroup='Average Air Temperature', visible='legendonly', selector=dict(name='Average Air Temperature')) 

	## Plot layout
	fig.update_layout(
    	xaxis=dict(title='Timestamp'),
    	#yaxis=dict(title='Power (W)',type='log'),
		yaxis=dict(title='Power (W)'),
    	yaxis2=dict(title='degrees Fahrenheit',overlaying='y',side='right'),
		legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='right',x=1)
	)

	## NOTE: This opens a window that displays the correct figure with the appropriate patterns.
	## For some reason, the slash-mark patterns are not showing up on the OMF page otherwise.
	## Eventually we will delete this part.
	#fig.show()
	#outData['derOverviewHtml'] = fig.to_html(full_html=False)
	fig.write_html(pJoin(modelDir, "Plot_NewDemand.html"))

	## Encode plot data as JSON for showing in the HTML 
	outData['newDemandData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['newDemandLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)

	################################################################################################################################################
	## Create Thermal Battery Power plot object 
	################################################################################################################################################
	fig = go.Figure()

	data_names = ['vbatMinPowerCapacity', 'vbatMaxPowerCapacity', 'vbatPower']
	colors = ['green', 'blue', 'black']
	titles = ['Minimum Calculated Power Capacity', 'Maximum Calculated Power Capacity', 'Actual Power Utilized']

	dataCheckList = []
	for data_name, color, title in zip(data_names, colors, titles):
		dataCheck = np.sum(combined_device_results[data_name])
		dataCheckList.append(dataCheck)
		fig.add_trace(go.Scatter(
			x=timestamps, 
			y=np.array(combined_device_results[data_name])*1000., ## convert from kW to W
			yaxis='y1',
			mode='lines',
			line=dict(color=color, width=1),
			name=title,
			showlegend=True
		))

	fig.update_layout(xaxis=dict(title='Timestamp'), yaxis=dict(title='Power (W)'),
		legend=dict(orientation='h',yanchor='bottom',y=1.02,xanchor='right',x=1))
	
	## Add a thermal battery variable that signals to the HTML plot if all of the thermal series contain no data
	outData['thermalDataCheck'] = float(sum(np.array(dataCheckList)))
	
	## Encode plot data as JSON for showing in the HTML side
	outData['thermalBatPowerPlot'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['thermalBatPowerPlotLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)	

	################################################################################################################################################
	## Create Chemical BESS State of Charge plot object 
	################################################################################################################################################
	fig = go.Figure()
	fig.add_trace(go.Scatter(x=timestamps, y=outData['chargeLevelBattery'],
						mode='lines',
						line=dict(color='purple', width=1),
						name='Battery SOC',
						showlegend=True))
	
	fig.update_layout(xaxis=dict(title='Timestamp'), yaxis=dict(title='Charge (%)'), legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right',x=1))

	outData['batteryChargeData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['batteryChargeLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)


	"""
	#####################################################################################################################################################################################################
	## Compensation rate to member-consumer
	compensationRate = float(inputDict['rateCompensation'])
	subsidy = float(inputDict['subsidy']) ## TODO: Amount for the entire analysis - should we divide this up by # of months and add to the monthly consumer savings?
	consumptionCost = float(inputDict['electricityCost'])

	monthHours = [(0, 744), (744, 1416), (1416, 2160), (2160, 2880), 
					(2880, 3624), (3624, 4344), (4344, 5088), (5088, 5832), 
					(5832, 6552), (6552, 7296), (7296, 8016), (8016, 8760)]
	
	load_smallConsumer_monthly = np.asarray([sum(smallConsumerLoad[s:f]) for s, f in monthHours])
	load_largeConsumer_monthly = np.asarray([sum(largeConsumerLoad[s:f]) for s, f in monthHours])
	loadCost_smallConsumer_monthly = load_smallConsumer_monthly * consumptionCost
	loadCost_largeConsumer_monthly = load_largeConsumer_monthly * consumptionCost

	## Check if REopt results include a BESS output that is not an empty list
	if 'ElectricStorage' in reoptResults and any(reoptResults['ElectricStorage']['storage_to_load_series_kw']):
		BESS_utility = reoptResults['ElectricStorage']['storage_to_load_series_kw'] ## The BESS that is recommended for the utility
		BESS_smallConsumer = smallConsumerOutput['ElectricStorage']['storage_to_load_series_kw'] ## A scaled down version of the utility's load to represent a small consumer (1 kWh average load)
		BESS_largeConsumer = largeConsumerOutput['ElectricStorage']['storage_to_load_series_kw'] ## A scaled down version of the utility's load to represent a large consumer (10 kWh average load)
		BESS_smallConsumer_monthly = np.asarray([sum(BESS_smallConsumer[s:f]) for s, f in monthHours])
		BESS_largeConsumer_monthly = np.asarray([sum(BESS_largeConsumer[s:f]) for s, f in monthHours])
		BESSCost_smallConsumer_monthly = BESS_smallConsumer_monthly * compensationRate
		BESSCost_largeConsumer_monthly = BESS_largeConsumer_monthly * compensationRate

		## Divide subsidy amount up into the monthly consumer savings
		subsidy_monthly = np.full(12, subsidy/12)

		## Add BESS + TESS + subsidy(divided by 12 months) = total savings
		TESSCost_smallConsumer_monthly = np.asarray(outData['TESSsavingsSmallConsumer'])
		TESSCost_largeConsumer_monthly = np.asarray(outData['TESSsavingsLargeConsumer'])
		totalCost_smallConsumer_monthly = TESSCost_smallConsumer_monthly + BESSCost_smallConsumer_monthly + subsidy_monthly
		totalCost_largeConsumer_monthly = TESSCost_largeConsumer_monthly + BESSCost_largeConsumer_monthly + subsidy_monthly

		## Update the consumer savings output to represent both thermal BESS (vbatDispatch results) and REopt's BESS results
		outData.update({
			'totalSavingsSmallConsumer': list(totalCost_smallConsumer_monthly),
			'totalSavingsLargeConsumer': list(totalCost_largeConsumer_monthly)
		})

		## Print some monthly costs/savings for analysis
		print('Small Consumer consumption cost (w/o BESS): ${:,.2f}'.format(np.sum(loadCost_smallConsumer_monthly)))
		print('Small Consumer savings for BESS only: ${:,.2f} \n'.format(np.sum(BESSCost_smallConsumer_monthly)))	
		print('Large Consumer consumption cost (w/o BESS): ${:,.2f}'.format(np.sum(loadCost_largeConsumer_monthly)))
		print('Large Consumer savings for BESS only: ${:,.2f}'.format(np.sum(BESSCost_largeConsumer_monthly)))
		BESS_compensated_to_consumer = np.sum(BESS_utility)*compensationRate+subsidy
		print('--------------------------------------------------------')
		print('Utility total compensation for consumer BESS ($ annually): ${:,.2f}'.format(BESS_compensated_to_consumer))
		BESS_bought_from_grid = np.sum(BESS_utility) * consumptionCost
		print('Utility BESS savings (1 year BESS kWh x electricity cost): ${:,.2f}'.format(BESS_bought_from_grid))
		print('Difference (Utility BESS savings - Compensation to consumers): ${:,.2f}'.format(BESS_bought_from_grid-BESS_compensated_to_consumer))

	"""

	#########################################################################################################################################################
	### Calculate the monthly consumption and peak demand costs and savings
	#########################################################################################################################################################

	## Calculate the monthly peak demand and energy consumption of the base demand curve
	## NOTE: The base demand = the demand curve without DERs
	outData['monthlyPeakDemand'] = [demand[np.argmax(demand[s:f])] for s, f in monthHours] ## The maximum peak kW for each month
	outData['monthlyPeakDemandCost'] = (peakDemandCharge*np.array(outData['monthlyPeakDemand'])).tolist()  ## peak demand charge before including DERs
	consumption_cost_array = [float(a) * float(b) for a, b in zip(demand, energy_rate_array)]
	monthlyEnergyConsumption = [sum(demand[s:f]) for s, f in monthHours] ## The total energy in kWh for each month
	monthlyEnergyConsumptionCost = [sum(consumption_cost_array[s:f]) for s, f in monthHours] ## The total energy cost in $$ for each month	

	## Calculate the monthly peak demand and energy consumption of the adjusted demand curve
	## NOTE: The adjusted demand = the demand curve including DERs
	adjusted_demand = np.array(demand) - BESS - vbat_discharge_component - generator + grid_charging_BESS + vbat_charge_component
	outData['adjustedDemand'] = list(adjusted_demand)
	#monthly_peak_adjusted_demand = [adjusted_demand[np.argmax(adjusted_demand[s:f])] for s, f in monthHours] 
	monthlyAdjustedEnergyConsumption = [sum(adjusted_demand[s:f]) for s, f in monthHours] ## The total adjusted energy in kWh for each month
	adjusted_consumption_cost_array = [float(a) * float(b) for a, b in zip(adjusted_demand, energy_rate_array)]
	monthlyAdjustedEnergyConsumptionCost = [sum(adjusted_consumption_cost_array[s:f]) for s, f in monthHours] ## The total adjusted energy cost in $$ for each month	
	monthlyEnergyConsumptionSavings = np.array(monthlyEnergyConsumptionCost) - np.array(monthlyAdjustedEnergyConsumptionCost)
	outData['monthlyTotalCostService'] = [ec+dcm for ec, dcm in zip(monthlyEnergyConsumptionCost, outData['monthlyPeakDemandCost'])] ## total cost of energy and demand charge prior to DERs
	outData['monthlyAdjustedPeakDemand'] = [adjusted_demand[np.argmax(adjusted_demand[s:f])] for s, f in monthHours] ## monthly peak demand hours (including DERs)
	outData['monthlyAdjustedPeakDemandCost'] = (peakDemandCharge * np.array(outData['monthlyAdjustedPeakDemand'])).tolist() ## peak demand charge after including all DERs
	outData['monthlyPeakDemandSavings'] = (np.array(outData['monthlyPeakDemandCost']) - np.array(outData['monthlyAdjustedPeakDemandCost'])).tolist() ## total demand charge savings from all DERs
	
	## Calculate the combined costs and savings from the adjusted energy and adjusted demand charges
	outData['monthlyTotalCostService'] = [ec+dcm for ec, dcm in zip(monthlyEnergyConsumptionCost, outData['monthlyPeakDemandCost'])] ## total cost of energy and demand charge prior to DERs
	outData['monthlyTotalCostAdjustedService'] = [eca+dca for eca, dca in zip(monthlyAdjustedEnergyConsumptionCost, outData['monthlyAdjustedPeakDemandCost'])] ## total cost of energy and peak demand from including DERs
	outData['monthlyTotalSavingsAdjustedService'] = [tot-tota for tot, tota in zip(outData['monthlyTotalCostService'], outData['monthlyTotalCostAdjustedService'])] ## total savings from all DERs

	#########################################################################################################################################################
	### Calculate the individual (BESS, TESS, and GEN) contributions to the consumption and peak demand savings
	#########################################################################################################################################################
	BESS_demand = np.array(BESS)-np.array(grid_charging_BESS)
	TESS_demand = np.array(combined_TESS_vbatPower) #np.array(vbat_discharge_component)-np.array(vbat_charge_component)
	GEN_demand = np.array(generator)

	## Calculate the monthly energy consumption savings for BESS, TESS, and GEN technologies
	BESS_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(BESS_demand, energy_rate_array)]
	TESS_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(TESS_demand, energy_rate_array)]
	GEN_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(GEN_demand, energy_rate_array)]

	BESS_consumption_savings_monthly = [sum(BESS_consumption_savings_year1[s:f]) for s, f in monthHours]
	TESS_consumption_savings_monthly = [sum(TESS_consumption_savings_year1[s:f]) for s, f in monthHours]
	GEN_consumption_savings_monthly = [sum(GEN_consumption_savings_year1[s:f]) for s, f in monthHours]

	allDevices_consumption_savings_monthly = [a+b+c for a,b,c in zip(BESS_consumption_savings_monthly,TESS_consumption_savings_monthly,GEN_consumption_savings_monthly)]
	allDevices_consumption_savings_total = sum(allDevices_consumption_savings_monthly)
	#print('allDevices monthly consumption savings: ', allDevices_consumption_savings_monthly)
	#print('total consumption savings monthly (base demand consumption cost - adj demand cost): ', monthlyEnergyConsumptionSavings)

	## Calculate the peak demand savings for BESS, TESS, and GEN technologies
	demand = np.array(demand)
	peak_demand_indices = np.array([np.argmax(demand[s:f]) for s, f in monthHours])
	adjusted_demand_indices = np.array([np.argmax(adjusted_demand[s:f]) for s, f in monthHours])

	peak_demand_at_baseP = demand[peak_demand_indices]
	peak_demand_at_adjP = demand[adjusted_demand_indices]
	#adjusted_demand_at_baseP = adjusted_demand[peak_demand_indices]
	#adjusted_demand_at_adjP = adjusted_demand[adjusted_demand_indices]
	
	#peak_demand_at_baseP_cost = peak_demand_at_baseP * peakDemandCharge
	#peak_demand_at_adjP_cost = peak_demand_at_adjP * peakDemandCharge
	#adjusted_demand_at_baseP_cost = adjusted_demand_at_baseP * peakDemandCharge
	#adjusted_demand_at_adjP_cost = adjusted_demand_at_adjP * peakDemandCharge

	BESS_demand_at_baseP = BESS_demand[peak_demand_indices]
	BESS_demand_at_adjP = BESS_demand[adjusted_demand_indices]
	TESS_demand_at_baseP = TESS_demand[peak_demand_indices]
	TESS_demand_at_adjP = TESS_demand[adjusted_demand_indices]
	GEN_demand_at_baseP = GEN_demand[peak_demand_indices]
	GEN_demand_at_adjP = GEN_demand[adjusted_demand_indices]

	BESS_demand_at_baseP_cost = BESS_demand_at_baseP * peakDemandCharge
	TESS_demand_at_baseP_cost = TESS_demand_at_baseP * peakDemandCharge
	GEN_demand_at_baseP_cost = GEN_demand_at_baseP * peakDemandCharge

	#BESS_demand_at_adjP_cost = BESS_demand_at_adjP * peakDemandCharge
	#TESS_demand_at_adjP_cost = TESS_demand_at_adjP * peakDemandCharge
	#GEN_demand_at_adjP_cost = GEN_demand_at_adjP * peakDemandCharge

	allDER_at_baseP = BESS_demand_at_baseP+TESS_demand_at_baseP+GEN_demand_at_baseP
	allDER_at_adjP = BESS_demand_at_adjP+TESS_demand_at_adjP+GEN_demand_at_adjP

	## Calculate the F_val (the linear scaling factor that quantifies the impact of DERs on peak demand savings)
	## NOTE: See CIDER project plan for doc link to detailed calculation of F_val
	demand_1 = np.array(peak_demand_at_baseP) ## peak demand at t=1
	demand_2 = np.array(peak_demand_at_adjP) ## peak demand at t=2
	D_DER_1 = np.array(allDER_at_baseP) ## DER contribution (kW) at t=1
	D_DER_2 = np.array(allDER_at_adjP) ## DER contribution (kW) at t=2
	F_val = (demand_1 - demand_2 + D_DER_2) / D_DER_1

	## Apply the monthly F_val to the monthly BESS, TESS, GEN peak demand savings
	BESS_peakDemand_savings_monthly = BESS_demand_at_baseP_cost*F_val
	TESS_peakDemand_savings_monthly = TESS_demand_at_baseP_cost*F_val
	GEN_peakDemand_savings_monthly = GEN_demand_at_baseP_cost*F_val
	allDevices_peakDemand_savings_monthly = [a+b+c for a,b,c in zip(BESS_peakDemand_savings_monthly,TESS_peakDemand_savings_monthly,GEN_peakDemand_savings_monthly)]
	allDevices_peakDemand_savings_total = sum(allDevices_peakDemand_savings_monthly)

	BESS_peakDemand_savings_allyears = np.full(projectionLength, sum(BESS_peakDemand_savings_monthly))
	BESS_consumption_savings_allyears = np.full(projectionLength, sum(BESS_consumption_savings_monthly))
	BESS_savings_allyears = BESS_peakDemand_savings_allyears + BESS_consumption_savings_allyears

	TESS_peakDemand_savings_allyears = np.full(projectionLength, sum(TESS_peakDemand_savings_monthly))
	TESS_consumption_savings_allyears = np.full(projectionLength, sum(TESS_consumption_savings_monthly))
	TESS_savings_allyears = TESS_peakDemand_savings_allyears + TESS_consumption_savings_allyears

	GEN_peakDemand_savings_allyears = np.full(projectionLength, sum(GEN_peakDemand_savings_monthly))
	GEN_consumption_savings_allyears = np.full(projectionLength, sum(GEN_consumption_savings_monthly))
	GEN_savings_allyears = GEN_peakDemand_savings_allyears + GEN_consumption_savings_allyears

	## Calculate the individual TESS technology consumption and peak demand savings
	for device_result in single_device_results:
		device_demand = thermal_device_savings[device_result]['demand']
		device_demand_at_baseP = device_demand[peak_demand_indices]
		device_demand_at_baseP_cost = device_demand_at_baseP * peakDemandCharge
		device_peakDemand_savings_monthly = device_demand_at_baseP_cost*F_val

		device_peakDemand_savings_allyears = np.full(projectionLength, sum(device_peakDemand_savings_monthly))

		device_consumption_savings_monthly = thermal_device_savings[device_result]['consumption_cost_monthly']
		device_consumption_savings_allyears = thermal_device_savings[device_result]['consumption_cost_allyears']

		#device_savings_monthly = device_peakDemand_savings_monthly + device_consumption_savings_monthly
		#device_savings_allyears = device_peakDemand_savings_allyears + device_consumption_savings_allyears
		#print(device_result+' savings :', device_peakDemand_savings_monthly)

		outData[device_result+'_consumption_savings_allyears'] = device_consumption_savings_allyears.tolist()
		outData[device_result+'_peakDemand_savings_allyears'] = device_peakDemand_savings_allyears.tolist()


	######################################################################################################################################################
	## COSTS
	## Calculate the financial costs of controlling member-consumer DERs
	## e.g. subsidies, operational costs, startup costs
	######################################################################################################################################################

	## If the DER tech is disabled or the discharge array is empty, then set all its subsidies equal to zero.
	if BESScheck == 'enabled' and np.sum(BESS_demand) > 0.0:
		BESS_subsidy_ongoing = float(inputDict['BESS_subsidy_ongoing'])*float(inputDict['number_devices_BESS'])
		BESS_subsidy_onetime = float(inputDict['BESS_subsidy_onetime'])*float(inputDict['number_devices_BESS'])
	else:
		BESS_subsidy_ongoing = 0
		BESS_subsidy_onetime = 0

	if GENcheck == 'enabled' and np.sum(GEN_demand) > 0.0:
		GEN_subsidy_ongoing = float(inputDict['GEN_subsidy_ongoing'])*float(inputDict['number_devices_GEN'])
		GEN_subsidy_onetime = float(inputDict['GEN_subsidy_onetime'])*float(inputDict['number_devices_GEN'])
	else:
		GEN_subsidy_ongoing = 0
		GEN_subsidy_onetime = 0

	if sum(np.array(vbat_discharge_component)) == 0:
		TESS_subsidy_ongoing = 0
		TESS_subsidy_onetime = 0
	else:
		TESS_subsidy_ongoing = combined_device_results['combinedTESS_subsidy_ongoing']
		TESS_subsidy_onetime = combined_device_results['combinedTESS_subsidy_onetime']

	## Calculate the BESS subsidy for year 1 and the projection length (all years)
	## Year 1 includes the onetime subsidy, but subsequent years do not.
	BESS_subsidy_year1_total =  BESS_subsidy_onetime + (BESS_subsidy_ongoing*12.0)
	BESS_subsidy_allyears_array = np.full(projectionLength, BESS_subsidy_ongoing*12.0)
	BESS_subsidy_allyears_array[0] += BESS_subsidy_onetime

	## Calculate the total TESS subsidies for year 1 and the projection length (all years)
	## Year 1 includes the onetime subsidy, but subsequent years do not.
	combinedTESS_subsidy_year1_total = TESS_subsidy_onetime + (TESS_subsidy_ongoing*12.0)
	combinedTESS_subsidy_allyears_array = np.full(projectionLength, TESS_subsidy_ongoing*12.0)
	combinedTESS_subsidy_allyears_array[0] += TESS_subsidy_onetime

	## Calculate Generator Subsidy for year 1 and the projection length (all years)
	## Year 1 includes the onetime subsidy, but subsequent years do not.
	GEN_subsidy_year1_total =  GEN_subsidy_onetime + (GEN_subsidy_ongoing*12.0)
	GEN_subsidy_allyears_array = np.full(projectionLength, GEN_subsidy_ongoing*12.0)
	GEN_subsidy_allyears_array[0] += GEN_subsidy_onetime
	
	## Calculate the total TESS+BESS+generator subsidies for year 1 and the projection length (all years)
	## The first month of Year 1 includes the onetime subsidy, but subsequent months and years do not include the onetime subsidy again.
	allDevices_subsidy_ongoing = GEN_subsidy_ongoing + BESS_subsidy_ongoing + TESS_subsidy_ongoing
	allDevices_subsidy_onetime = GEN_subsidy_onetime + BESS_subsidy_onetime + TESS_subsidy_onetime
	allDevices_subsidy_year1_total = allDevices_subsidy_onetime + (allDevices_subsidy_ongoing*12.0)
	allDevices_subsidy_year1_array = np.full(12, allDevices_subsidy_ongoing)
	allDevices_subsidy_year1_array[0] += allDevices_subsidy_onetime
	allDevices_subsidy_allyears_array = np.full(projectionLength, allDevices_subsidy_ongoing*12.0)
	allDevices_subsidy_allyears_array[0] += allDevices_subsidy_onetime

	## Calculate the compensation per kWh for BESS, TESS, and GEN technologies
	BESS_compensation_year1_array = np.array([sum(BESS[s:f])*rateCompensation for s, f in monthHours])
	BESS_compensation_year1_total = np.sum(BESS_compensation_year1_array)
	BESS_compensation_allyears_array = np.full(projectionLength, BESS_compensation_year1_total)
	GEN_compensation_year1_array = np.array([sum(generator[s:f])*rateCompensation for s, f in monthHours])
	GEN_compensation_year1_total = np.sum(GEN_compensation_year1_array)
	GEN_compensation_allyears_array = np.full(projectionLength, GEN_compensation_year1_total)
	TESS_compensation_year1_array = np.array([sum(vbat_discharge_component[s:f])*rateCompensation for s, f in monthHours])
	TESS_compensation_year1_total = np.sum(TESS_compensation_year1_array)
	TESS_compensation_allyears_array = np.full(projectionLength, TESS_compensation_year1_total)
	allDevices_compensation_year1_array = BESS_compensation_year1_array + GEN_compensation_year1_array + TESS_compensation_year1_array
	allDevices_compensation_year1_total = np.sum(allDevices_compensation_year1_array)
	allDevices_compensation_allyears_array = BESS_compensation_allyears_array + GEN_compensation_allyears_array + TESS_compensation_allyears_array

	## Calculate ongoing and onetime operational costs
	## NOTE: This includes costs for things like API calls to control the DERs
	operationalCosts_ongoing = float(inputDict['operationalCosts_ongoing'])
	operationalCosts_onetime = float(inputDict['operationalCosts_onetime'])
	operationalCosts_year1_total = operationalCosts_onetime + (operationalCosts_ongoing*12.0)
	operationalCosts_year1_array = np.full(12, operationalCosts_ongoing)
	operationalCosts_year1_array[0] += operationalCosts_onetime
	operationalCosts_allyears_array = np.full(projectionLength, operationalCosts_ongoing*12.0)
	operationalCosts_allyears_array[0] += operationalCosts_onetime

	## Calculate startup costs
	startupCosts = float(inputDict['startupCosts'])
	startupCosts_year1_array = np.zeros(12)
	startupCosts_year1_array[0] += startupCosts
	startupCosts_allyears_array = np.full(projectionLength, 0.0)
	startupCosts_allyears_array[0] += startupCosts

	## Calculate total utility costs for year 1 and all years
	utilityCosts_year1_total = operationalCosts_year1_total + allDevices_subsidy_year1_total + allDevices_compensation_year1_total + startupCosts
	utilityCosts_year1_array = operationalCosts_year1_array + allDevices_subsidy_year1_array + allDevices_compensation_year1_array 
	utilityCosts_year1_array[0] += startupCosts ## Add startup costs to the first year in the total cost array
	utilityCosts_allyears_array = operationalCosts_allyears_array + allDevices_subsidy_allyears_array + allDevices_compensation_allyears_array 
	utilityCosts_allyears_array[0] += startupCosts ## Add startup costs to the first year in the total cost array
	utilityCosts_allyears_total = np.sum(utilityCosts_allyears_array)

	## Calculate total costs for BESS, TESS, and GEN
	totalCosts_GEN_allyears_array = GEN_subsidy_allyears_array + GEN_compensation_allyears_array
	totalCosts_BESS_allyears_array = BESS_subsidy_allyears_array + BESS_compensation_allyears_array
	totalCosts_TESS_allyears_array = combinedTESS_subsidy_allyears_array + TESS_compensation_allyears_array

	######################################################################################################################################################
	## SAVINGS
	## Calculate the financial savings of controlling member-consumer DERs
	## NOTE: The savings are just from the adjusted energy cost and adjusted demand charge. 
	######################################################################################################################################################
	utilitySavings_year1_total = np.sum(outData['monthlyTotalSavingsAdjustedService'])
	utilitySavings_year1_array = np.array(outData['monthlyTotalSavingsAdjustedService'])
	utilitySavings_allyears_array = np.full(projectionLength, utilitySavings_year1_total)
	utilitySavings_allyears_total = np.sum(utilitySavings_allyears_array)

	## Calculating total utility net savings (savings minus costs)
	utilityNetSavings_year1_total =  utilitySavings_year1_total - utilityCosts_year1_total
	utilityNetSavings_year1_array = utilitySavings_year1_array - utilityCosts_year1_array
	utilityNetSavings_allyears_total = utilitySavings_allyears_total - utilityCosts_allyears_total
	utilityNetSavings_allyears_array = utilitySavings_allyears_array - utilityCosts_allyears_array

	## Update financial parameters
	outData['totalCost_year1'] = list(utilityCosts_year1_array)
	outData['totalSavings_year1'] = list(utilitySavings_year1_array)
	outData['totalCost_paidToConsumer'] = list(allDevices_compensation_year1_array + allDevices_subsidy_year1_array)
	
	## Calculate Net Present Value (NPV) and Simple Payback Period (SPP)
	outData['NPV'] = npv(float(inputDict['discountRate'])/100., utilityNetSavings_allyears_array)
	initialInvestment = startupCosts + operationalCosts_onetime + allDevices_subsidy_onetime
	utilityCosts_year1_minus_onetime_costs = (operationalCosts_ongoing*12.0) + (allDevices_subsidy_ongoing*12.0) + allDevices_compensation_year1_total
	utilityNetSavings_year1_total_minus_onetime_costs = utilitySavings_year1_total - utilityCosts_year1_minus_onetime_costs
	SPP = initialInvestment/utilityNetSavings_year1_total_minus_onetime_costs
	outData['SPP'] = SPP
	outData['totalNetSavings_year1'] = list(utilityNetSavings_year1_array) ## (total cost of service - adjusted total cost of service) - (operational costs + subsidies + compensation to consumer + startup costs)
	outData['totalNetSavings_allyears'] = list(utilityNetSavings_allyears_array)
	outData['cumulativeCashflow_total'] = list(np.cumsum(utilityNetSavings_allyears_array))
	outData['savingsAllYears'] = list(utilitySavings_allyears_array)
	outData['costsAllYears'] = list(utilityCosts_allyears_array*-1.) ## Show as negative for plotting purposes
	
	######################################################################################################################################################
	## Monthly Cost Comparison Plot Variables
	######################################################################################################################################################
	outData['monthlyEnergyConsumption'] = list(monthlyEnergyConsumption)
	outData['monthlyAdjustedEnergyConsumption'] = list(monthlyAdjustedEnergyConsumption)
	outData['monthlyEnergyConsumptionCost'] = list(monthlyEnergyConsumptionCost)
	outData['monthlyAdjustedEnergyConsumptionCost'] = list(monthlyAdjustedEnergyConsumptionCost)
	outData['monthlyEnergyConsumptionSavings'] = list(monthlyEnergyConsumptionSavings)
	
	#outData['monthly_gen_fuel_cost'] = list(monthly_fuel_cost)
	#outData['allDevices_subsidy_year1'] = list(allDevices_subsidy_year1_array)
	#outData['allDevices_compensation_year1'] = list(allDevices_compensation_year1_array)
	#outData['savings_year1_monthly_array'] = list(savings_year1_monthly_array)
	#outData['costs_year1_array'] = list(costs_year1_array)
	#outData['net_savings_year1_array'] = list(net_savings_year1_array)

	######################################################################################################################################################
	## CashFlow Projection Plot variables
	## NOTE: The utility costs are shown as negative values
	######################################################################################################################################################
	outData['subsidies'] = list(allDevices_subsidy_allyears_array*-1.)
	outData['BESS_compensation_to_consumer_allyears'] = list(BESS_compensation_allyears_array*-1.)
	outData['TESS_compensation_to_consumer_allyears'] = list(TESS_compensation_allyears_array*-1.)
	outData['GEN_compensation_to_consumer_allyears'] = list(GEN_compensation_allyears_array*-1.)
	outData['operationalCosts_allyears'] = list(operationalCosts_allyears_array*-1.)
	outData['operationalCosts_year1'] = list(operationalCosts_year1_array*-1.)
	outData['startupCosts_year1'] = list(startupCosts_year1_array*-1.)
	outData['startupCosts_allyears'] = list(startupCosts_allyears_array*-1.)
	
	## Combine the startup and operational costs for displaying in the Monthly Cost Comparison table
	startup_and_operational_costs_year1_array = startupCosts_year1_array + operationalCosts_year1_array
	outData['startupAndOperationalCosts_year1'] = list(startup_and_operational_costs_year1_array)
	
	######################################################################################################################################################
	## Savings Breakdown Per Technology Plot variables
	######################################################################################################################################################
	outData['savings_peakDemand_BESS_allyears'] = list(BESS_peakDemand_savings_allyears)
	outData['savings_consumption_BESS_allyears'] = list(BESS_consumption_savings_allyears)
	outData['savings_peakDemand_TESS_allyears'] = list(TESS_peakDemand_savings_allyears)
	outData['savings_consumption_TESS_allyears'] = list(TESS_consumption_savings_allyears)
	outData['savings_peakDemand_GEN_allyears'] = list(GEN_peakDemand_savings_allyears)
	outData['savings_consumption_GEN_allyears'] = list(GEN_consumption_savings_allyears)
	outData['totalCosts_BESS_allyears'] = list(-1.0*totalCosts_BESS_allyears_array) ## Costs are negative for plotting purposes
	outData['totalCosts_TESS_allyears'] = list(-1.0*totalCosts_TESS_allyears_array) ## Costs are negative for plotting purposes
	outData['totalCosts_GEN_allyears'] = list(-1.0*totalCosts_GEN_allyears_array) ## Costs are negative for plotting purposes
	outData['cumulativeSavings_total'] = list(np.cumsum(utilitySavings_allyears_array))
	
	## Add a flag for the case when no DER technology is specified. The Savings Breakdown plot will then display a placeholder plot with no available data.
	outData['techCheck'] = float(sum(BESS) + sum(vbat_discharge_component) + sum(generator))

	## Model operations typically end here.
	## Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','utility_2018_kW_load.csv')) as f:
		demand_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','open-meteo-denverCO-noheaders.csv')) as f:
		temperature_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','TODrate66a13566e90ecdb7d40581d2.csv')) as f:
		wholesale_rate_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','TODrate66a13566e90ecdb7d40581d2.json')) as jsonFile:
		wholesale_rate_structure = json.load(jsonFile)
	#responseFilename = 'TODrate66a13566e90ecdb7d40581d2.json' ## TOD rate JSON file (created using instructions from https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates)
	#responseFilename = 'TOUrate5b311c595457a3496d8367be.json' ## TOU rate JSON file (created using instructions from https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates)
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','utility_monthly_demand_charges.csv')) as f:
		monthly_demand_charges = f.read()

	defaultInputs = {
		## TODO: maybe incorporate float, int, bool types on the html side instead of only strings
		## OMF inputs:
		'user' : 'admin',
		'modelType': modelName,
		'created': str(datetime.datetime.now()),

		## REopt inputs:
		'latitude' : '39.969753', ## Brighton, CO
		'longitude' : '-104.812599', ## Brighton, CO
		'year': '2018',
		'fileName': 'utility_2018_kW_load.csv',
		'demandCurve': demand_curve,
		'temperatureFileName': 'open-meteo-denverCO-noheaders.csv',
		'temperatureCurve': temperature_curve,
		'useWholesaleJSONBool': True,
		'wholesaleRateCurveFileName': 'TODrate66a13566e90ecdb7d40581d2.csv',
		'wholesaleRateCurve': wholesale_rate_curve,
		'wholesaleRateStructureFileName': 'TODrate66a13566e90ecdb7d40581d2.json',
		'wholesaleRateStructure': wholesale_rate_structure,
		'monthlyDemandChargesFileName': 'utility_monthly_demand_charges.csv',
		'monthlyDemandCharges': monthly_demand_charges,

		## Fossil Fuel Generator Inputs
		## Modeled after Generac 20 kW diesel model with max tank of 95 gallons
		'fossilGenerator': 'Yes',
		'number_devices_GEN': '5',
		'existing_gen_kw': '20',
		'fuel_type': '3', 
		'fuel_avail': '95', 
		'fuel_cost': '3.49', ## $3.49 is based on fuel cost of diesel fuel in March 2025

		## Chemical Battery Inputs
		## Modeled after residential Tesla Powerwall 3 battery specs
		'enableBESS': 'Yes',
		'number_devices_BESS': '20000',
		'BESS_kw': '5.0',
		'BESS_kwh': '13.5',

		## Financial Inputs
		#'demandChargeCost': '50', ## this input is used by vbatDispatch
		'projectionLength': '25',
		'rateCompensation': '0.02', ## unit: $/kWh
		'discountRate': '2',
		'startupCosts': '200000',
		'TESS_subsidy_onetime_ac': '25.0',
		'TESS_subsidy_ongoing_ac': '0.0',
		'TESS_subsidy_onetime_hp': '100.0',
		'TESS_subsidy_ongoing_hp': '0.0',
		'TESS_subsidy_onetime_wh': '25.0',
		'TESS_subsidy_ongoing_wh': '0.0',
		'BESS_subsidy_onetime': '100.0',
		'BESS_subsidy_ongoing': '0.0',
		'GEN_subsidy_onetime': '25.0',
		'GEN_subsidy_ongoing': '0.0',
		'operationalCosts_ongoing': '1000.0',
		'operationalCosts_onetime': '20000.0',

		## Home Air Conditioner inputs (for vbatDispatch):
		'load_type_ac': '1', 
		'number_devices_ac': '33000',
		'power_ac': '5.6',
		'capacitance_ac': '2',
		'resistance_ac': '2',
		'cop_ac': '2.5',
		'setpoint_ac': '22.5',
		'deadband_ac': '0.625',

		## Home Heat Pump inputs (for vbatDispatch):
		'load_type_hp': '2', 
		'number_devices_hp': '16500',
		'power_hp': '5.6',
		'capacitance_hp': '2',
		'resistance_hp': '2',
		'cop_hp': '3.5',
		'setpoint_hp': '19.5',
		'deadband_hp': '0.625',

		## Home Water Heater inputs (for vbatDispatch):
		'load_type_wh': '4', 
		'number_devices_wh': '33000',
		'power_wh': '4.5',
		'capacitance_wh': '0.4',
		'resistance_wh': '120',
		'cop_wh': '1',
		'setpoint_wh': '48.5',
		'deadband_wh': '3',
	}
	
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	# Location
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
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
	pass