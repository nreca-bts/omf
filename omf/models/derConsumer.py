"""
❗ NOTE ❗ omf.models.derConsumer is a new model currently under development. Check back
in the coming months for updates!
"""

## Python imports
import warnings
#warnings.filterwarnings("ignore")
import shutil, datetime
from os.path import join as pJoin
import numpy as np
import pandas as pd
import plotly.graph_objs as go
import plotly.utils
import requests
from numpy_financial import npv

## OMF imports
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.models import derUtilityCost
from omf.models import vbatDispatch as vb
from omf.solvers import reopt_jl

## Model metadata:
tooltip = ('Performs a cost-benefit analysis for a member-consumer enrolling distributed energy resources (DERs) in a utility DER sharing program.')
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False ## Keep the model hidden=True during active development

def work(modelDir, inputDict):
	''' Run the model in its directory. '''

	## Delete output file every run if it exists
	outData = {}
	
	########################################################################################################################
	## Handle and save user input files
	########################################################################################################################
	## Remove old input files if necessary
	inputFileNames = ['demand_input_derConsumer.csv', 'temperature_input_derConsumer.csv', 
				   'residential_rate_structure_input_derConsumer.json',
				   'urdbLabel_responseFile_input_derConsumer.json',
				   'vbatDispatch_inputs_ac.json', 'vbatDispatch_results_ac.json', 
				   'vbatDispatch_inputs_hp.json', 'vbatDispatch_results_hp.json',
				   'vbatDispatch_inputs_wh.json', 'vbatDispatch_results_wh.json',
				   'random_seeds.csv']
	for FileName in inputFileNames:
		try:
			os.remove(pJoin(modelDir, FileName))
		except OSError:
			pass

	## Save all input files, except the response file (later)
	with open(pJoin(modelDir, 'demand_input_derConsumer.csv'), 'w') as f:
		f.write(inputDict['demandCurve'].replace('\r', ''))
	with open(pJoin(modelDir, 'temperature_input_derConsumer.csv'), 'w') as f:
		f.write(inputDict['temperatureCurve'].replace('\r', ''))

	########################################################################################################################
	## Process input demand, temperature, and other input variables
	########################################################################################################################

	## Convert user provided demand and temp data from str to float
	## NOTE: assumes the input temperature curve is in degrees Fahrenheit. The degrees Celsius conversion is used later for vbatDispatch, which expects deg C. 
	temperatures_degF = [float(value) for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	temperatures_degC = [(float(value)-32.0)*(5/9) for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	demand = [float(value) for value in inputDict['demandCurve'].split('\n') if value.strip()]

	## Check if the demand and temperature curves are the correct length and account for leap years by removing Dec 31 data.
	if len(demand) != 8760:
		raise Exception(f'Demand Curve must have exactly 8760 elements, but got {len(demand)}. If this is a leap year, remove December 31 and ensure there are 8760 elements.')
	if len(temperatures_degF) != 8760:
		raise Exception(f'Temperature Curve must have exactly 8760 elements, but got {len(temperatures_degF)}. If this is a leap year, remove December 31 and ensure that there are 8760 elements.')

	## Gather input variables to pass to the omf.solvers.reopt_jl model
	latitude = float(inputDict['latitude'])
	longitude = float(inputDict['longitude'])
	projectionLength = int(inputDict['projectionLength'])
	year = int(inputDict['year'])

	########################################################################################################################################################
	## Construct the timestamp array
	## If the input year is a leap year, remove the last day in December and keep the extra day in February as recommended in REopt's documentation:
	## https://reopt.nrel.gov/tool/reopt-user-manual.pdf#page=37 (Section 7.1 Actual (Custom) Load Profile)
	########################################################################################################################################################
	start_date = pd.Timestamp(f'{year}-01-01')
	is_leap_year = start_date.is_leap_year
	if is_leap_year == True:
		## If a leap year, include the 29th day of February but not December 31st.
		end_date = f'{year}-12-30 23:59'
		monthHours = [(0, 744), (744, 1440), (1440, 2184), (2184, 2904), 
				(2904, 3648), (3648, 4368), (4368, 5112), (5112, 5856), 
				(5856, 6576), (6576, 7320), (7320, 8040), (8040, 8760)]
	else:
		## If non-leap year, include December 31st
		end_date = f'{year}-12-31 23:59'
		monthHours = [(0, 744), (744, 1416), (1416, 2160), (2160, 2880), 
				(2880, 3624), (3624, 4344), (4344, 5088), (5088, 5832), 
				(5832, 6552), (6552, 7296), (7296, 8016), (8016, 8760)]
	
	timestamps = pd.date_range(start=start_date, end=end_date, freq='h')

	if len(timestamps) != 8760: ## Ensure 8760 elements
		raise Exception(f'The timestamp array should be 8760 elements long. Instead, got {len(timestamps)} elements.')
	
	########################################################################################################################################################
	## Build the energy rate array from the API response information
	########################################################################################################################################################
	if inputDict.get('urdbLabelBool'): ## Checkbox to use the urdb label is True by default
		## NOTE: Uses the URDB label to obtain the energy rate structure .json information via REopt API in order to construct an energy rate array that is used in the analysis.
		## NOTE: This functionality is for cases where the user only has the URDB label but no .csv or .json describing the energy rate structure from their co-op. 
		api_url = 'https://api.openei.org/utility_rates?parameters'
		api_key = '5dFShfSVRt2XJpPYCbzBeLM6nHrOXc0VFPTWxfJJ' ## API key generated by following this website: https://openei.org/services/

		params = {
			'version': '3',
			'format': 'json',
			'getpage': inputDict['urdbLabel'],
			'detail': 'full', ## returns every variable
			'limit': 500, 
			'api_key': api_key
			}
		
		response = requests.get(api_url, params=params)
		if response.status_code == 200:
			try:
				response.raise_for_status() ## Raise an exception for HTTP errors
				data = response.json() ## Gather relevant info from the API response
				response_file = data['items'][0] ## This response_file is a dictionary containing the utility rate structure information
				#print(response_file)
			except requests.exceptions.RequestException as e:
				print('Error:', e)
				return None
		else:
			print(f'Request failed with status code: {response.status_code}')
		
		## Save response file to the model directory
		with open(pJoin(modelDir, 'urdbLabel_responseFile_input_derConsumer.json'), 'w') as jsonFile:
			json.dump(response_file, jsonFile)

	else: ## If the Residential Response File (.json) is chosen and provided, use the user-provided .json response file instead
		try:
			## Try to normally parse the JSON file
			response_file = json.loads(inputDict['residentialRateStructure'])
		except json.JSONDecodeError:
			## Convert single quotes to double quotes for proper JSON formatting
			try:
				fixed = inputDict['residentialRateStructure'].replace("'", '"')
				response_file = json.loads(fixed)
			except json.JSONDecodeError:
				raise Exception('Try re-uploading the JSON file and running the model again.')
		except TypeError:
			## Use the residential_rate_structure if it is already a Python dictionary
			if isinstance(inputDict['residentialRateStructure'], dict):
				response_file = inputDict['residentialRateStructure']

		## Save response file to modelDir
		with open(pJoin(modelDir, 'residential_rate_structure_input_derConsumer.json'), 'w') as jsonFile:
			json.dump(response_file, jsonFile)

	########################################################################################################################################################
	## Construct the residential Energy Rate Array using the JSON response file input
	########################################################################################################################################################
	energy_rate_array = np.zeros(8760)
	if 'energyratestructure' in response_file:
		## NOTE: The energy rate structure refers to a nested list of dictionary items with "rate" and "unit" keys
		## For example: response_file['energyratestructure'] = [[{'rate': 0, 'unit': 'kWh'}], [{'rate': 0.06, 'unit': 'kWh'}], [{'rate': 0.1525, 'unit': 'kWh'}]]
		energy_weekday_schedule = response_file['energyweekdayschedule']
		energy_weekend_schedule = response_file['energyweekendschedule']
		energy_rate_periods = response_file['energyratestructure']

		## For each rate period, assemble the maximum kWh threshold and the corresponding energy rate
		tier_thresholds_by_period = []
		for period in energy_rate_periods:
			cumulative_max = 0
			thresholds = []
			for tier in period:
				if 'max' in tier:
					cumulative_max += tier['max'] ## See Section 6.1 Electric Rate Tariff in the REopt documentation for an explanation of how this max kWh is interpreted: https://reopt.nrel.gov/tool/reopt-user-manual.pdf
					thresholds.append((cumulative_max, tier['rate']))
				else: ## If no max, then the tier rate is applied to all remaining kWh (e.g. No max would be found for the Period 0 rate placeholder, the last tier of a tiered period, or a single tier in a period.)
					thresholds.append((np.inf, tier['rate']))
			tier_thresholds_by_period.append(thresholds)

		## Calculate the maximum cumulative kWh for each hour per month. This is for tiered energy rate structures that include a maximum kWh limit for which the $/kWh rate is applied
		energy_monthly_cumulative_sum = np.zeros_like(demand)
		for s, f in monthHours:
			energy_monthly_cumulative_sum[s:f] = np.cumsum(demand[s:f])

		## Fill the energy_rate_array with hourly energy rates ($/kWh) for the entire year, according to the appropriate rate schedule, period, and tier rate.
		for hour_index, date in enumerate(timestamps):
			month = date.month - 1 ## NOTE: date.month is offset by 1 due to 0 indexing
			if date.weekday() < 5: ## NOTE: Weekdays (Monday=0, Sunday=7) - use the weekday rate schedule
				period_number = energy_weekday_schedule[month][date.hour]
			else: ## Weekends - use the weekend rate schedule
				period_number = energy_weekend_schedule[month][date.hour]

			## Get the tier thresholds for the current rate period
			if period_number >= len(tier_thresholds_by_period):
				raise ValueError(f'Period number {period_number} not found in energyratestructure in the Residential Rate Structure (.json) file.')

			thresholds = tier_thresholds_by_period[period_number]
			monthly_kwh = energy_monthly_cumulative_sum[hour_index]

			## Apply the energy rate within the proper tier thresholds
			for max_kwh, rate in thresholds:
				if monthly_kwh <= max_kwh:
					energy_rate_array[hour_index] = rate
					break
	else:
		raise Exception('No energy rate structure information was found in the Residential Rate Structure (.json) file. Please include this information when creating the JSON or select a different method for input.')

	########################################################################################################################
	## Inputs for REopt.jl solver
	########################################################################################################################

	## Create a REopt input dictionary called 'scenario' (required input for omf.solvers.reopt_jl)
	scenario = {
		'Site': {
			'latitude': latitude,
			'longitude': longitude
		},
		'ElectricTariff': {
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

	## Add either the URDB Label or URDB Response File
	#scenario['ElectricTariff']['tou_energy_rates_per_kwh'] = energy_rate_array
	## TODO: Test the urdb_label against the urdb_response inputs for the same data input. Results are expected to be the same.
	if inputDict.get('urdbLabelBool'):
		scenario['ElectricTariff']['urdb_label'] = inputDict['urdbLabel']
	else:
		scenario['ElectricTariff']['urdb_response'] = response_file #inputDict['residentialRateStructure']

	## Add a Battery Energy Storage System (BESS) section if enabled 
	if inputDict['enableBESS'] == 'Yes':
		BESScheck = 'enabled'
		utility_BESS_fraction = float(inputDict['utility_BESS_portion'])/100. ## convert percentage to decimal (e.g. 20% -> 0.20)
		scenario['ElectricStorage'] = {
			'min_kw': float(inputDict['BESS_kw']) * (1.0 - utility_BESS_fraction),
			'max_kw': float(inputDict['BESS_kw']) * (1.0 - utility_BESS_fraction),
			'min_kwh': float(inputDict['BESS_kwh']) * (1.0 - utility_BESS_fraction),
			'max_kwh': float(inputDict['BESS_kwh']) * (1.0 - utility_BESS_fraction),
			'can_grid_charge': True,
			'total_rebate_per_kw': 0.0,
			'macrs_option_years': 0,
			'installed_cost_per_kw': 0.0,
			'installed_cost_per_kwh': 0.0,
			'replace_cost_per_kw': float(inputDict['replace_cost_per_kw']),
			'replace_cost_per_kwh': float(inputDict['replace_cost_per_kwh']),
			'total_itc_fraction': 0.0,
			'inverter_replacement_year': int(inputDict['inverter_replacement_year']),
			'battery_replacement_year': int(inputDict['battery_replacement_year']),
			#'soc_min_fraction': 1.0 - float(inputDict['utility_BESS_portion'])/100,
			}
	else:
		BESScheck = 'disabled'
	
	## Add fossil fuel (diesel) generator to input scenario (if enabled)
	if inputDict['fossilGenerator'] == 'Yes':
		GENcheck = 'enabled'
		scenario['Generator'] = {
			'existing_kw': float(inputDict['existing_gen_kw']), ## Existing generator
			'max_kw': 0.0, ## New generator minumum
			'min_kw': 0.0, ## New generator maximum
			'only_runs_during_grid_outage': False,
			'replacement_year': int(inputDict['generator_replacement_year']),
			'replace_cost_per_kw': float(inputDict['replace_cost_generator_per_kw']),
			'fuel_avail_gal': float(inputDict['fuel_avail']),
			'fuel_cost_per_gallon': float(inputDict['fuel_cost']),
			#'can_curtail': True,
		}
	else:
		GENcheck = 'disabled'

	## Save the scenario file
	## NOTE: reopt_jl currently requires a path for the input file, so the file must be saved to a location - preferrably in the modelDir directory
	with open(pJoin(modelDir, 'reopt_input_scenario.json'), 'w') as jsonFile:
		json.dump(scenario, jsonFile)
	
	########################################################################################################################
	## Run REopt.jl to model the BESS and GEN technologies
	########################################################################################################################
	## Set the random seed for the HiGHS solver https://ergo-code.github.io/HiGHS/dev/options/definitions/#option-random-seed
	if inputDict['set_random_numbers'] == 'Yes':
		random_seed_HiGHS = int(inputDict['random_seed_HiGHS_REopt'])
	else:
		random_seed_HiGHS = np.random.randint(0,2147483647)

	## Save HiGHS random seed to the output with the rest of the random seeds (e.g. CBC MILP solver seeds for the thermal DERs)
	with open(pJoin(modelDir, 'random_seeds.csv'), 'a') as f:
		f.write('BESS & GEN: ' + str(random_seed_HiGHS) + '\n')
		
	## Run REopt
	reopt_jl.run_reopt_jl(modelDir, 'reopt_input_scenario.json', run_with_sysimage=False,  tolerance=0.0001, random_seed=random_seed_HiGHS)
	
	## Load the REopt results
	try: 
		with open(pJoin(modelDir, 'results.json')) as jsonFile:
			reoptResults = json.load(jsonFile)
		outData.update(reoptResults) ## Update output file with reopt results
		reoptErrorMsgs = reoptResults['Messages']['errors']
	except FileNotFoundError:
		raise Exception(f'REopt did not produce any results. An error may have occurred.')

	## Check if DER technology is enabled by the user and define relevant variables from REopt
	if BESScheck == 'enabled':
		try:
			BESS = reoptResults['ElectricStorage']['storage_to_load_series_kw']
		except KeyError:
			raise Exception(f'No BESS found in REopt results. An error may have occurred, see REopts warning list: {reoptErrorMsgs}.')
		
		grid_charging_BESS = reoptResults['ElectricUtility']['electric_to_storage_series_kw']
		outData['chargeLevelBattery'] = list(np.array(reoptResults['ElectricStorage']['soc_series_fraction']) * 100.)
	else:
		BESS = np.zeros_like(demand)
		grid_charging_BESS = np.zeros_like(demand)
		outData['chargeLevelBattery'] = list(np.zeros_like(demand))

	if GENcheck == 'enabled':
		try:
			generator = np.array(reoptResults['Generator']['electric_to_load_series_kw'])
		except KeyError:
			raise Exception(f'No fossil fuel generator found in REopt results. An error may have occurred, see REopts warning list: {reoptErrorMsgs}.')
	else:
		generator = np.zeros_like(demand)

	########################################################################################################################
	## Run omf.models.vbatDispatch to model the thermal DERs (e.g. AC, HP, WH)
	########################################################################################################################
	demandCharges_temporary = np.zeros(12)
	## NOTE: The demand charges variable is temporarily coded as zero here since vbatDispatch is expecting
	## NOTE (cont.) a monthly demand charge array, but derConsumer does not ingest a monthly demand charge input yet. 
	## NOTE (cont.) The vbatDispatch model only calculates the peakDeamndCharge and adjustedPeakDemandCharge with this info 
	## NOTE (cont.) The demand charges are not used in the optimization and should not affect the thermal tech dispatch behavior.
	
	## Set up base input dictionary for vbatDispatch runs
	inputDict_vbatDispatch = {
		'load_type': '', ## 1=AirConditioner, 2=HeatPump, 3=Refrigerator, 4=WaterHeater (These conventions are from OMF model vbatDispatch.html)
		'number_devices': '1',
		'power': '',
		'capacitance': '',
		'resistance': '',
		'cop': '',
		'setpoint':  '',
		'deadband': '',
		'unitDeviceCost': '', 
		'unitUpkeepCost':  '', 
		'monthlyDemandCharges': '\n'.join(f'{dollar:.2f}' for dollar in demandCharges_temporary), ## see note above
		'projectionLength': inputDict['projectionLength'],
		'discountRate': inputDict['discountRate'],
		'fileName': inputDict['demandFileName'],
		'temperatureFileName': inputDict['temperatureFileName'],
		'demandCurve': inputDict['demandCurve'],
		'temperatureCurve': '\n'.join(f'{temp:.2f}' for temp in temperatures_degC), ## Convert temperatures_degC into the expected format for vbatDispatch
		'energyRateCurve': '\n'.join(f'{rate:.2f}' for rate in energy_rate_array), ## Convert energy_rate_array into the expected format for vbatDispatch
		'set_random_numbers': inputDict['set_random_numbers'],
		#'random_seed_PuLP': inputDict['random_seed_PuLP'],
		'randomNumbersFileName': inputDict['randomNumbersFileName'],
		'randomNumbers': inputDict['randomNumbers'],
	}
	
	## Define thermal variables that change depending on the thermal technology(ies) enabled by the user
	thermal_suffixes = ['_ac', '_hp', '_wh'] ## heat pump, air conditioner, water heater - (Add more suffixes here after establishing inputs in the defaultInputs and derUtilityCost.html)
	thermal_variables=['load_type','power','capacitance','resistance','cop','setpoint','deadband','TESS_subsidy_ongoing','TESS_subsidy_onetime','unitDeviceCost','unitUpkeepCost','random_seed_PuLP']

	all_device_suffixes = []
	single_device_results = {} 
	for suffix in thermal_suffixes:
		## Include only the thermal devices specified by the user
		if float(inputDict['load_type'+suffix]) > 0: ## NOTE: The load_type_X variable will be 0 if the user has disabled that technology
			all_device_suffixes.append(suffix)

			## Add the appropriate thermal device variables to the inputDict_vbatDispatch
			for i in thermal_variables:
				inputDict_vbatDispatch[i] = inputDict[i+suffix]
				
			## Convert setpoint and deadband from Fahrenheit to Celsius
			inputDict_vbatDispatch['setpoint'] = str((float(inputDict_vbatDispatch['setpoint'])-32.0)*(5/9))
			inputDict_vbatDispatch['deadband'] = str(float(inputDict_vbatDispatch['deadband'])/1.8)

			## Save the vbatDispatch inputs
			with open(pJoin(modelDir, 'vbatDispatch_inputs'+suffix+'.json'), 'w') as jsonFile:
				json.dump(inputDict_vbatDispatch, jsonFile)

			## Run vbatDispatch for the thermal device
			vbatResults = vb.work(modelDir,inputDict_vbatDispatch)
			
			## Update the vbatResults to include subsidies (for easier usage later)
			vbatResults['TESS_subsidy_onetime'] = float(inputDict_vbatDispatch['TESS_subsidy_onetime'])
			vbatResults['TESS_subsidy_ongoing'] = float(inputDict_vbatDispatch['TESS_subsidy_ongoing'])

			## Save the vbatDispatch results
			with open(pJoin(modelDir, 'vbatDispatch_results'+suffix+'.json'), 'w') as jsonFile:
				json.dump(vbatResults, jsonFile)
			
			## Save the PuLP random seed to the ouput file
			if suffix == '_hp':
				tech_name = 'Heat Pump'
			if suffix == '_wh':
				tech_name = 'Water Heater'
			if suffix == '_ac':
				tech_name = 'Air Conditioner'
			with open(pJoin(modelDir, 'random_seeds.csv'), 'a') as f:
				f.write(tech_name + ': ' + str(vbatResults['random_seed_PuLP']) + '\n')

			## Store the results in all_device_results dictionary
			single_device_results['vbatResults'+suffix] = vbatResults
	
	########################################################################################################################
	## Enact charge prioritization of TESS devices when there is competition for charge time
	## NOTE: This is hard-coded for the following TESS tech priority order: WH > AC > HP
	## NOTE: This prioritization is meant to account for the TESS tech competing for charge time (due to the decoupled 
	## nature of vbatDispatch runs, where only one kind of thermal tech can be specified in a given run. This can create a 
	## larger, more expensive peak demand when 2+ thermal technologies want to charge at the same time.
	########################################################################################################################
	vbat_power_df = pd.DataFrame(index=None)
	charging_devices = []

	## Separate out the charging and discharging arrays for each TESS device enabled by the user
	for device_name in single_device_results:
		single_device_vbatPower = single_device_results[device_name]['VBpower']
		single_device_vbatPower_series = pd.Series(single_device_vbatPower)
		single_device_vbatPower_series.replace(-0.0, 0.0, inplace=True)
		charge_component = single_device_vbatPower_series.where(single_device_vbatPower_series < 0.0, 0.0) * -1.0
		discharge_component = single_device_vbatPower_series.where(single_device_vbatPower_series > 0.0, 0.0)
		vbat_power_df[device_name + '_totalpower'] = single_device_vbatPower_series
		vbat_power_df[device_name + '_charging'] = charge_component.replace(-0.0, 0.0)
		vbat_power_df[device_name + '_discharging'] = discharge_component
		charging_devices.append(device_name + '_charging') ## record the names of the TESS technologies that will be charging

	## Among the TESS devices available to charge, sort the devices according to the priority order.
	priority_tech = ['vbatResults_wh_charging', 'vbatResults_ac_charging', 'vbatResults_hp_charging'] 
	available_priority_tech = [tech for tech in priority_tech if tech in charging_devices] 

	## Create a priority order mapping between the tech name (str) and an integer (0,1,2) so Python can work with it
	priority_order = {key: i for i, key in enumerate(priority_tech)}

	## The adjusted dataframe for all TESS technolgies based on the priority charging order
	## NOTE: This method is used to account for the TESS tech creating new, expensive peak demands due to decoupled thermal technologies charging at the same time.
	adjusted_vbat_power_df = derUtilityCost.adjust_charging_and_discharging(vbat_power_df, priority_order, available_priority_tech)

	########################################################################################################################
	## Individual and combined Thermal Energy Storage System (TESS) technology calculations 
	## (e.g Water Heater, Heat Pump, Air Conditioner)
	########################################################################################################################
	## Define the consumption rate compensation ($/kWh) paid to member-consumers
	#consumptionCost = float(inputDict['electricityCost'])
	#rateCompensation = float(inputDict['rateCompensation'])

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
		single_device_vbatPower = adjusted_vbat_power_df[device_result+'_totalpower']
		single_device_vbatPower_series = pd.Series(single_device_vbatPower)
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

	## Get the charging and discharging behavior after the total combined TESS has been calculated
	combined_TESS_vbatPower = combined_device_results['vbatPower']
	combined_TESS_vbatPower_series = pd.Series(combined_TESS_vbatPower)
	combined_device_results['vbat_discharge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series >= 0, 0) ##positive values = discharging
	combined_device_results['vbat_charge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series < 0, 0) ##negative values = charging
	combined_device_results['vbat_charge_flipsign'] = combined_device_results['vbat_charge'].mul(-1)

	## Calculate the subsidies, compensation rate, and consumption cost (kWh) for each individual thermal tech device
	## NOTE: This loop must come after the calculation of the combined TESS devices in order to correctly calculate the single_device_vbat_discharge/charge components
	for device_result in single_device_results:
		single_device_vbatPower = adjusted_vbat_power_df[device_result+'_totalpower']
		single_device_vbatPower_series = pd.Series(single_device_vbatPower)
		single_device_vbat_discharge_component = single_device_vbatPower_series.where(combined_TESS_vbatPower_series >= 0, 0) ##positive values = discharging 
		single_device_vbat_charge_component = single_device_vbatPower_series.where(combined_TESS_vbatPower_series < 0, 0) ##negative values = charging
		single_device_vbat_charge_component_flipsign = single_device_vbat_charge_component.mul(-1)
		## select out the original individual TESS discharge/charge values
		orig_single_device_vbat_discharge_component = single_device_vbatPower_series.where(single_device_vbatPower_series > 0.0, 0.0) ##positive values = discharging 
		orig_single_device_vbat_charge_component_flipsign = single_device_vbatPower_series.where(single_device_vbatPower_series < 0.0, 0.0) * -1.0 ##negative values = charging. multiply by -1 for plotting purposes
		orig_single_device_vbat_charge_component_flipsign.replace(-0.0, 0.0, inplace=True) ## replace negative zeros with positive zeros

		## Calculate subsidy for each thermal DER technology
		single_device_subsidy_ongoing = float(single_device_results[device_result]['TESS_subsidy_ongoing'])
		single_device_subsidy_onetime = float(single_device_results[device_result]['TESS_subsidy_onetime'])
		single_device_subsidy_year1_array = np.full(12, single_device_subsidy_ongoing)
		single_device_subsidy_year1_array[0] += single_device_subsidy_onetime
		single_device_subsidy_allyears_array = np.full(projectionLength, single_device_subsidy_ongoing*12.0)
		single_device_subsidy_allyears_array[0] += single_device_subsidy_onetime

		## Calculate the consumer compensation for each thermal DER technology
		#single_device_compensation_year1_array = np.array([sum(single_device_vbat_discharge_component[s:f])*rateCompensation for s, f in monthHours])
		#single_device_compensation_year1_total = np.sum(single_device_compensation_year1_array)
		#single_device_compensation_allyears_array = np.full(projectionLength, single_device_compensation_year1_total)

		## Calculate the consumption cost savings for each DER tech using the input rate structure (hourly data for the whole year)
		single_device_consumption_cost_year1 = [float(a) * float(b) for a, b in zip(single_device_vbatPower, energy_rate_array)]
		single_device_consumption_cost_monthly = [sum(single_device_consumption_cost_year1[s:f]) for s, f in monthHours]
		single_device_consumption_cost_allyears = np.full(projectionLength, sum(single_device_consumption_cost_year1))
		single_device_monthlyTESS_consumption_total = [sum(single_device_vbatPower[s:f]) for s, f in monthHours]

		## Add up all the consumer savings for the total TESS
		#savings_year1_monthly_single_device = single_device_subsidy_year1_array + single_device_compensation_year1_array
		#savings_allyears_single_device = single_device_subsidy_allyears_array + single_device_compensation_allyears_array 

		## Save relevant variables for each TESS device for calculating the demand cost savings later on
		thermal_device_savings[device_result] = {
			'demand': np.array(single_device_vbatPower),
			'vbat_discharge_component': np.array(orig_single_device_vbat_discharge_component),
			'vbat_discharge_component_W': np.array(orig_single_device_vbat_discharge_component) * 1000.,
			'vbat_charge_component_flipsign': np.array(orig_single_device_vbat_charge_component_flipsign),
			'vbat_charge_component_flipsign_W': np.array(orig_single_device_vbat_charge_component_flipsign) * 1000.,
			'consumption_cost_monthly': np.array(single_device_consumption_cost_monthly),
			'consumption_cost_allyears': np.array(single_device_consumption_cost_allyears),
    	}

		## Savings Breakdown Per Thermal Technology savings variables
		## NOTE: This is where the html variables outData['vbatResults_wh_savings_allyears'], outData['vbatResults_hp_savings_allyears'], and outData['vbatResults_ac_savings_allyears'] are saved.
		#outData[device_result+'_savings_allyears'] = list(savings_allyears_single_device)
		outData[device_result+'_check'] = 'enabled'
	
	## vbatDispatch variables
	vbat_discharge_component = np.array(combined_device_results['vbat_discharge'])
	vbat_charge_component = np.array(combined_device_results['vbat_charge_flipsign'])
	vbat_charge_component[vbat_charge_component == -0.0] = 0.0 ## convert all -0 to just 0 for precaution

	#########################################################################################################################################################
	### Calculate the monthly consumption (kWh) costs and savings
	## NOTE: "base" demand curve = no DERs in the demand curve
	## NOTE: "adjusted" demand curve = DERs included in the demand curve 
	#########################################################################################################################################################

	## Base demand curve energy consumption cost ($/kWh)
	monthlyEnergyConsumption = [sum(demand[s:f]) for s, f in monthHours] ## The total energy in kWh for each month
	consumptionCost = [float(a) * float(b) for a, b in zip(demand, energy_rate_array)]
	monthlyEnergyConsumptionCost = [sum(consumptionCost[s:f]) for s, f in monthHours] ## The total energy cost in $$ for each month	

	## Adjusted demand curve energy consumption cost ($/kWh)
	adjusted_demand = np.array(demand) - BESS - vbat_discharge_component - generator + grid_charging_BESS + vbat_charge_component
	adjusted_demand[adjusted_demand == -0.0] = 0.0 ## avoid sign errors
	outData['adjustedDemand'] = list(adjusted_demand)
	#monthly_peak_adjusted_demand = [adjusted_demand[np.argmax(adjusted_demand[s:f])] for s, f in monthHours] 
	monthlyAdjustedEnergyConsumption = [sum(adjusted_demand[s:f]) for s, f in monthHours] ## The total adjusted energy in kWh for each month
	adjustedConsumptionCost = [float(a) * float(b) for a, b in zip(adjusted_demand, energy_rate_array)]
	monthlyAdjustedEnergyConsumptionCost = [sum(adjustedConsumptionCost[s:f]) for s, f in monthHours] ## The total adjusted energy cost in $$ for each month	
	
	## Energy consumption savings ($) = Base Demand Cost - Adjusted Demand Cost
	monthlyEnergyConsumptionSavings = np.array(monthlyEnergyConsumptionCost) - np.array(monthlyAdjustedEnergyConsumptionCost)

	########################################################################################################################
	### Calculate the monthly demand (kW) costs and savings
	## NOTE: The JSON response file should contain either "demandratestructure" or "facilitydemandcharge" information 
	########################################################################################################################
	BESS_demand = np.array(BESS) - np.array(grid_charging_BESS)
	TESS_demand = np.array(combined_TESS_vbatPower)
	GEN_demand = np.array(generator)
	demand = np.array(demand)

	## Convert negative zeros into positive zeros to avoid sign errors
	BESS_demand[BESS_demand == -0.0] = 0.0 
	TESS_demand[TESS_demand == -0.0] = 0.0 
	GEN_demand[GEN_demand == -0.0] = 0.0 

	## Placeholders for total monthly demand savings for BESS, TESS, and GEN
	BESS_monthly_demand_savings = np.zeros(12)
	TESS_monthly_demand_savings = np.zeros(12)
	GEN_monthly_demand_savings  = np.zeros(12)
	
	## Peak demand charge cost ($) for the base demand curve (w/o DERs). 
	## NOTE: the monthly demand charge rate ($/kW) is the same for both w/ and w/o DERs; it comes from the response file if flatdemandstructure is defined, else it's all zeros.
	monthly_demand_charge_cost_withoutDERs, monthly_total_kw_withoutDERs, period_max_dollar_indices_withoutDERs = derUtilityCost.construct_monthly_demand_charge_array(response_file, timestamps, demand, monthHours)

	## Peak demand charge cost ($) for the adjusted demand curve (with DERs)
	monthly_demand_charge_cost_withDERs, monthly_total_kw_withDERs, period_max_dollar_indices_withDERs = derUtilityCost.construct_monthly_demand_charge_array(response_file, timestamps, adjusted_demand, monthHours)

	#peakDemandCharge = np.zeros(12) ## TODO: update this if flatdemandstructure is defined in JSON file. Setting to zero for now until Lisa has looked at the JSON inputs from coops.

	if 'demandratestructure' in response_file:
		## Re-stack tuples into arrays
		## max dollar indices for demand curve array, the max dollar amounts, and the demand rates ($/kW)
		noDERs_restacked = list(zip(*period_max_dollar_indices_withoutDERs)) 
		withDERs_restacked = list(zip(*period_max_dollar_indices_withDERs))

		index_withDERs = np.array(withDERs_restacked[0])
		dollar_withDERs = np.array(withDERs_restacked[1]) ##this is the total demand charge cost in dollars per hourly period window for the demand curve with all DERs
		rate_withDERs = np.array(withDERs_restacked[2])

		index_noDERs = np.array(noDERs_restacked[0])
		dollar_noDERs = np.array(noDERs_restacked[1])
		rate_noDERs = np.array(noDERs_restacked[2])

		## Stack all DER arrays and select out relevant indices
		DERs = np.stack([BESS_demand, TESS_demand, GEN_demand]) ## shape = (3, 8760)
		DERs_at_baseP = DERs[:, index_noDERs]
		DERs_at_adjP = DERs[:, index_withDERs]

		## Calculate linear scaling factor Fval to properly calculate individual DER peak demand savings due to peak shifting
		demand_baseP = np.array(demand[index_noDERs]*rate_noDERs)
		demand_adjP = np.array(adjusted_demand[index_withDERs]*rate_withDERs)
		DERs_at_baseP_dollars = DERs_at_baseP*rate_noDERs
		#DERs_at_adjP_dollars = DERs_at_adjP*rate_withDERs
		totalDER_at_baseP_dollars = np.sum(DERs_at_baseP_dollars, axis=0)
		fval_hourly = derUtilityCost.calculate_fval(demand_baseP, demand_adjP, totalDER_at_baseP_dollars)

		## Apply Fval to each DER peak demand savings
		DERs_peakDemand_savings_year = DERs_at_baseP_dollars * fval_hourly

		## Assemble the monthly demand savings array for each DER technology using the fval-corrected hourly window demand costs
		monthly_savings = np.zeros((3, 12)) ## (3 DERs × 12 months) 
		for m, (month_first_index, month_last_index) in enumerate(monthHours):
			mask = (index_withDERs >= month_first_index) & (index_withDERs <= month_last_index) 
			monthly_savings[:, m] = (DERs_peakDemand_savings_year[:, mask]).sum(axis=1)

		BESS_monthly_demand_savings, TESS_monthly_demand_savings, GEN_monthly_demand_savings = monthly_savings
		totalDERs_monthly_savings = monthly_savings.sum(axis=0)

		## Assemble the yearly demand savings for each DER using the monthly demand savings arrays
		BESS_yearly_demand_savings, TESS_yearly_demand_savings, GEN_yearly_demand_savings = monthly_savings.sum(axis=1)
		totalDERs_yearly_savings = totalDERs_monthly_savings.sum()

		## Calculate fval-corrected monthly savings for individual TESS technologies
		## TODO: combine this code with the code above later in a more Pythonic way (list comprehension) and depends on how many TESS tech are selected - zero arrays if unselected?
		for device_name in single_device_results:
			## Apply Fval to the hourly demand for each thermal device
			device_demand = thermal_device_savings[device_name]['demand']
			device_demand[device_demand == -0.0] = 0.0 ## Convert negative zeros into positive zeros to avoid sign errors
			device_demand_at_baseP = device_demand[index_noDERs]
			device_demand_at_adjP = device_demand[index_withDERs]
			device_at_baseP_dollars = device_demand_at_baseP * rate_noDERs
			device_peakDemand_savings_year = device_at_baseP_dollars * fval_hourly
			device_peakDemand_savings_monthly = np.zeros(12)
			for m, (month_first_index, month_last_index) in enumerate(monthHours):
				mask = (index_withDERs >= month_first_index) & (index_withDERs <= month_last_index) 
				device_peakDemand_savings_monthly[m] = np.sum(device_peakDemand_savings_year[mask])
			
			## Demand (kW) savings
			## NOTE: Savings Breakdown of Thermal Technologies plot variables: vbatResults_ac_peakDemand_savings_allyears, vbatResults_wh_peakDemand_savings_allyears, vbatResults_hp_peakDemand_savings_allyears
			device_peakDemand_savings_monthly[device_peakDemand_savings_monthly == -0.0] = 0.0 ## avoid sign errors
			device_peakDemand_savings_allyears = np.full(projectionLength, sum(device_peakDemand_savings_monthly))
			outData[device_name+'_peakDemand_savings_allyears'] = device_peakDemand_savings_allyears.tolist()

			## Consumption (kWh) savings
			## NOTE: Savings Breakdown of Thermal Technologies plot variables: vbatResults_ac_consumption_savings_allyears, vbatResults_wh_consumption_savings_allyears, vbatResults_hp_consumption_savings_allyears
			device_consumption_savings_monthly = thermal_device_savings[device_name]['consumption_cost_monthly']
			device_consumption_savings_allyears = thermal_device_savings[device_name]['consumption_cost_allyears']
			outData[device_name+'_consumption_savings_allyears'] = device_consumption_savings_allyears.tolist()

	## Calculate the monthly peak demand costs for the base demand curve (w/o DERs) and adjusted demand curve (w/ DERs)
	outData['monthlyPeakDemand'] = monthly_total_kw_withoutDERs.tolist()
	outData['monthlyPeakDemandCost'] = monthly_demand_charge_cost_withoutDERs.tolist()
	outData['monthlyAdjustedPeakDemand'] = monthly_total_kw_withDERs.tolist()
	outData['monthlyAdjustedPeakDemandCost'] = monthly_demand_charge_cost_withDERs.tolist()
	outData['monthlyPeakDemandSavings'] = (monthly_demand_charge_cost_withoutDERs - monthly_demand_charge_cost_withDERs).tolist()
	
	########################################################################################################################
	## Calculate the combined (energy cost + demand cost) savings between the base demand curve and adjusted demand curve
	########################################################################################################################
	outData['monthlyTotalCostService'] = [ec+dcm for ec, dcm in zip(monthlyEnergyConsumptionCost, outData['monthlyPeakDemandCost'])] ## total cost of energy and demand charge prior to DERs
	outData['monthlyTotalCostAdjustedService'] = [eca+dca for eca, dca in zip(monthlyAdjustedEnergyConsumptionCost, outData['monthlyAdjustedPeakDemandCost'])] ## total cost of energy and peak demand from including DERs
	outData['monthlyTotalSavingsAdjustedService'] = [tot-tota for tot, tota in zip(outData['monthlyTotalCostService'], outData['monthlyTotalCostAdjustedService'])] ## total savings from all DERs

	#########################################################################################################################################################
	### Calculate the individual (BESS, TESS, and GEN) contributions to the consumption and peak demand savings
	#########################################################################################################################################################
	## Calculate the monthly energy consumption savings for BESS, TESS, and GEN technologies
	BESS_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(BESS_demand, energy_rate_array)]
	TESS_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(TESS_demand, energy_rate_array)]
	GEN_consumption_savings_year1 = [float(a) * float(b) for a, b in zip(GEN_demand, energy_rate_array)]

	BESS_consumption_savings_monthly = [sum(BESS_consumption_savings_year1[s:f]) for s, f in monthHours]
	TESS_consumption_savings_monthly = [sum(TESS_consumption_savings_year1[s:f]) for s, f in monthHours]
	GEN_consumption_savings_monthly = [sum(GEN_consumption_savings_year1[s:f]) for s, f in monthHours]

	allDevices_consumption_savings_monthly = [a+b+c for a,b,c in zip(BESS_consumption_savings_monthly,TESS_consumption_savings_monthly,GEN_consumption_savings_monthly)]
	allDevices_consumption_savings_total = sum(allDevices_consumption_savings_monthly)

  	## Get the yearly consumption and demand savings for all DERs
	BESS_peakDemand_savings_allyears = np.full(projectionLength, sum(BESS_monthly_demand_savings))
	BESS_consumption_savings_allyears = np.full(projectionLength, sum(BESS_consumption_savings_monthly))
	BESS_savings_allyears = BESS_peakDemand_savings_allyears + BESS_consumption_savings_allyears

	TESS_peakDemand_savings_allyears = np.full(projectionLength, sum(TESS_monthly_demand_savings))
	TESS_consumption_savings_allyears = np.full(projectionLength, sum(TESS_consumption_savings_monthly))
	TESS_savings_allyears = TESS_peakDemand_savings_allyears + TESS_consumption_savings_allyears
	
	GEN_peakDemand_savings_allyears = np.full(projectionLength, sum(GEN_monthly_demand_savings))
	GEN_consumption_savings_allyears = np.full(projectionLength, sum(GEN_consumption_savings_monthly))
	GEN_savings_allyears = GEN_peakDemand_savings_allyears + GEN_consumption_savings_allyears

	######################################################################################################################################################
	## COSTS
	## Calculate the financial costs of enrolling member-consumer DERs into a utility DER-sharing program
	## e.g. Initial Investment = retrofit costs
	## Total consumer costs = generator fuel cost + BESS replacement cost + BESS inverter replacement cost + BESS retrofit costs +  TESS unit cost + TESS upkeep cost
	######################################################################################################################################################
	## Initialize cost arrays for the Cash Flow Projection and Savings Breakdown Per Technology plots
	costs_allyears_BESS = np.zeros(projectionLength)
	costs_allyears_GEN = np.zeros(projectionLength)
	costs_allyears_TESS = np.zeros(projectionLength)
	costs_allyears_wh = np.zeros(projectionLength)
	costs_allyears_hp = np.zeros(projectionLength)
	costs_allyears_ac = np.zeros(projectionLength)
	costs_allyears_array = np.zeros(projectionLength) ## includes all costs for all tech
	costs_year1_array = np.zeros(12)
	retrofit_cost_total = 0.
	monthly_fuel_cost = np.zeros(12)

	if GENcheck == 'enabled':
		## GEN fuel cost
		if 'Generator' in reoptResults:
			gen_annual_fuel_consumption_gal = reoptResults['Generator']['annual_fuel_consumption_gal']
		else:
			
			gen_annual_fuel_consumption_gal = 0.0
		gen_fuel_cost = float(inputDict['fuel_cost'])
		btu_per_kwh = 3412.0 ## constant
		thermal_efficiency = float(inputDict['thermal_efficiency'])/100.
		monthly_GEN_consumption_total = np.array([sum(GEN_demand[s:f]) for s,f in monthHours])
		fuel_type = int(inputDict['fuel_type'])

		if fuel_type == 1: ## Natural Gas
			## Assume the fuel cost input is given in units of $/cubic foot
			price_per_cubic_foot = gen_fuel_cost
			btu_per_cubic_ft = 1030.0

			## Convert the monthly GEN energy consumption from kWh to BTU
			monthly_GEN_consumption_total_btu = monthly_GEN_consumption_total * btu_per_kwh 

			## Calculate the amount of natural gas needed per cubic foot
			## = BTUs required / (BTUs per cubic foot * thermal efficiency)
			monthly_gas_needed_cubic_ft = monthly_GEN_consumption_total_btu / (btu_per_cubic_ft * thermal_efficiency)

			## Total monthly fuel cost
			monthly_fuel_cost += monthly_gas_needed_cubic_ft * gen_fuel_cost
			annual_fuel_cost = np.sum(monthly_fuel_cost)

		if fuel_type == 2: ## Propane
			btu_per_gal = 92000 ## Number chosen from https://portfoliomanager.energystar.gov/pdf/reference/Thermal%20Conversions.pdf
			monthly_gallons_used = (monthly_GEN_consumption_total * btu_per_kwh) / (thermal_efficiency * btu_per_gal)
			monthly_fuel_cost += monthly_gallons_used * gen_fuel_cost

		if fuel_type == 3:  ## Diesel
			btu_per_gal = 138000 ## Number chosen from https://portfoliomanager.energystar.gov/pdf/reference/Thermal%20Conversions.pdf
			monthly_gallons_used = (monthly_GEN_consumption_total * btu_per_kwh) / (thermal_efficiency * btu_per_gal)
			monthly_fuel_cost += monthly_gallons_used * gen_fuel_cost

		if fuel_type == 4: ## Gasoline
			btu_per_gal = 120214 ## Number chosen from https://www.eia.gov/energyexplained/units-and-calculators/energy-conversion-calculators.php
			monthly_gallons_used = (monthly_GEN_consumption_total * btu_per_kwh) / (thermal_efficiency * btu_per_gal)
			monthly_fuel_cost += monthly_gallons_used * gen_fuel_cost

		costs_year1_gen_fuel = gen_fuel_cost * gen_annual_fuel_consumption_gal
		costs_year1_array += monthly_fuel_cost
		costs_allyears_gen_fuel = np.full(projectionLength, costs_year1_gen_fuel)
		costs_allyears_GEN += costs_allyears_gen_fuel
		costs_allyears_array += costs_allyears_gen_fuel

		## GEN replacement cost
		replacement_cost_GEN = float(inputDict['replace_cost_generator_per_kw']) * float(inputDict['existing_gen_kw']) ## units: $
		replacement_year_GEN = int(inputDict['generator_replacement_year'])
		for year in range(0, projectionLength): ## Apply the replacement costs for the specified replacement years
			if replacement_year_GEN != 0 and year % replacement_year_GEN == 0 and year != 0:
				costs_allyears_array[year] += replacement_cost_GEN
				costs_allyears_GEN[year] += replacement_cost_GEN

		## GEN retrofit cost
		retrofit_cost_GEN = float(inputDict['gen_retrofit_cost'])
		costs_allyears_GEN[0] += retrofit_cost_GEN
		retrofit_cost_total += retrofit_cost_GEN

	## Thermal retrofit costs (TODO: Add replacement costs later?)
	if float(inputDict['load_type_wh']) > 0:  ## Check if water heater is enabled
		retrofit_cost_wh = float(inputDict['unitDeviceCost_wh'])
		costs_allyears_wh[0] += retrofit_cost_wh
		costs_allyears_TESS[0] += retrofit_cost_wh
		retrofit_cost_total += retrofit_cost_wh

	if float(inputDict['load_type_ac']) > 0:  ## Check if air conditioner is enabled
		retrofit_cost_ac = float(inputDict['unitDeviceCost_ac'])
		costs_allyears_ac[0] += retrofit_cost_ac
		costs_allyears_TESS[0] += retrofit_cost_ac
		retrofit_cost_total += retrofit_cost_ac

	if float(inputDict['load_type_hp']) > 0:  ## Check if heat pump is enabled
		retrofit_cost_hp = float(inputDict['unitDeviceCost_hp'])
		costs_allyears_hp[0] += retrofit_cost_hp
		costs_allyears_TESS[0] += retrofit_cost_hp
		retrofit_cost_total += retrofit_cost_hp

	## BESS retrofit and replacement costs
	if BESScheck == 'enabled':
		## BESS retrofit cost
		retrofit_cost_BESS = float(inputDict['BESS_retrofit_cost'])
		costs_allyears_BESS[0] += retrofit_cost_BESS

		## BESS replacement cost
		replacement_cost_BESS_kw = float(inputDict['replace_cost_per_kw']) ## units: $
		replacement_cost_BESS_kwh = float(inputDict['replace_cost_per_kwh']) ## units: $
		BESS_kw = float(inputDict['BESS_kw'])
		BESS_kwh = float(inputDict['BESS_kwh'])
		replacement_cost_BESS = BESS_kw * replacement_cost_BESS_kw + BESS_kwh * replacement_cost_BESS_kwh
		replacement_cost_inverter = float(inputDict['replace_cost_inverter'])
		replacement_year_BESS = int(inputDict['battery_replacement_year'])
		replacement_year_inverter = int(inputDict['inverter_replacement_year'])
		for year in range(0, projectionLength): ## Apply the replacement costs for the specified replacement years
			if replacement_year_BESS != 0 and year % replacement_year_BESS == 0 and year != 0:
				costs_allyears_array[year] += replacement_cost_BESS
				costs_allyears_BESS[year] += replacement_cost_BESS
			if replacement_year_inverter != 0 and year % replacement_year_inverter == 0 and year != 0:
				costs_allyears_array[year] += replacement_cost_inverter
				costs_allyears_BESS[year] += replacement_cost_inverter

	## Initial Investment
	initialInvestment = retrofit_cost_total
	costs_allyears_array[0] += initialInvestment
	
	## Calculate cost array for year 1 only
	#costs_year1_adjustedEnergyConsumption = np.sum(outData['monthlyAdjustedEnergyConsumptionCost'])
	#costs_allyears_energyConsumption = np.full(projectionLength,costs_year1_adjustedEnergyConsumption)
	#costs_allyears_array += costs_allyears_energyConsumption
	costs_allyears_total = sum(costs_allyears_array)
	costs_year1_array[0] += initialInvestment
	costs_year1_total = sum(costs_year1_array)
	#costs_allyears_total_minus_initial_investment = costs_allyears_total - initialInvestment

	######################################################################################################################################################
	## SAVINGS
	## Calculate the financial savings of enrolling member-consumer DERs into a utility DER-sharing program
	## Total consumer savings = upfront subsidy + ongoing subsidy + compensation for all DERs 
	######################################################################################################################################################

	## If the DER tech is disabled or the discharge array is empty, then set all its subsidies equal to zero.
	if BESScheck == 'enabled' and np.sum(BESS) > 0.0:
		BESS_subsidy_ongoing = float(inputDict['BESS_subsidy_ongoing'])
		BESS_subsidy_onetime = float(inputDict['BESS_subsidy_onetime'])
	else:
		BESS_subsidy_ongoing = 0
		BESS_subsidy_onetime = 0

	if GENcheck == 'enabled' and np.sum(generator) > 0.0:
		GEN_subsidy_ongoing = float(inputDict['GEN_subsidy_ongoing'])
		GEN_subsidy_onetime = float(inputDict['GEN_subsidy_onetime'])
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
	allDevices_subsidy_year1_monthly_array = np.full(12, allDevices_subsidy_ongoing)
	allDevices_subsidy_year1_monthly_array[0] += allDevices_subsidy_onetime
	allDevices_subsidy_allyears_array = np.full(projectionLength, allDevices_subsidy_ongoing*12.0)
	allDevices_subsidy_allyears_array[0] += allDevices_subsidy_onetime

	## Calculate the compensation per kWh for BESS, TESS, and GEN technologies
	#BESS_compensation_year1_monthly_array = np.array([sum(BESS[s:f])*rateCompensation for s, f in monthHours])
	#BESS_compensation_year1_total = np.sum(BESS_compensation_year1_monthly_array)
	#BESS_compensation_allyears_array = np.full(projectionLength, BESS_compensation_year1_total)
	#GEN_compensation_year1_monthly_array = np.array([sum(generator[s:f])*rateCompensation for s, f in monthHours])
	#GEN_compensation_year1_total = np.sum(GEN_compensation_year1_monthly_array)
	#GEN_compensation_allyears_array = np.full(projectionLength, GEN_compensation_year1_total)
	#TESS_compensation_year1_monthly_array = np.array([sum(vbat_discharge_component[s:f])*rateCompensation for s, f in monthHours])
	#TESS_compensation_year1_total = np.sum(TESS_compensation_year1_monthly_array)
	#TESS_compensation_allyears_array = np.full(projectionLength, TESS_compensation_year1_total)
	#allDevices_compensation_year1_monthly_array = BESS_compensation_year1_monthly_array + GEN_compensation_year1_monthly_array + TESS_compensation_year1_monthly_array
	#allDevices_compensation_year1_total = np.sum(allDevices_compensation_year1_monthly_array)
	#allDevices_compensation_allyears_array = BESS_compensation_allyears_array + GEN_compensation_allyears_array + TESS_compensation_allyears_array

	## Calculate total costs for BESS, TESS, and GEN
	totalSavings_BESS_allyears_array = BESS_subsidy_allyears_array #+ BESS_compensation_allyears_array
	totalSavings_TESS_allyears_array = combinedTESS_subsidy_allyears_array #+ TESS_compensation_allyears_array
	totalSavings_GEN_allyears_array = GEN_subsidy_allyears_array #+ GEN_compensation_allyears_array

	## Calculate total savings
	allDevices_peakDemand_savings_year1_monthly = BESS_monthly_demand_savings + TESS_monthly_demand_savings + GEN_monthly_demand_savings
	#allDevices_consumption_savings_year1_monthly = np.array(BESS_consumption_savings_monthly)+np.array(TESS_consumption_savings_monthly)+np.array(GEN_consumption_savings_monthly)
	allDevices_totalService_savings_year1_monthly = allDevices_peakDemand_savings_year1_monthly + monthlyEnergyConsumptionSavings
	savings_year1_monthly_array = allDevices_subsidy_year1_monthly_array + allDevices_totalService_savings_year1_monthly #+ allDevices_compensation_year1_monthly_array
	savings_year1_total = sum(savings_year1_monthly_array)
	savings_consumption_allyears_array = np.full(projectionLength, sum(monthlyEnergyConsumptionSavings))
	savings_demand_allyears_array = np.full(projectionLength, sum(allDevices_peakDemand_savings_year1_monthly))
	savings_allyears_array = savings_consumption_allyears_array + allDevices_subsidy_allyears_array + savings_demand_allyears_array #+ allDevices_compensation_allyears_array 
	savings_allyears_total = sum(savings_allyears_array)

	## Calculate net savings = savings - costs
	net_savings_year1_total = savings_year1_total - costs_year1_total
	net_savings_year1_array = savings_year1_monthly_array - costs_year1_array
	net_savings_allyears_array = savings_allyears_array - costs_allyears_array
	net_savings_allyears_total = savings_allyears_total - costs_allyears_total

	###################################################################################################################################
	## Plot variables
	###################################################################################################################################
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

	showlegend = True ## either enable or disable the legend toggle in the plot
	#lineshape = 'linear'
	lineshape = 'hv'

	###################################################################################################################################
	## Impact to Demand plot 
	###################################################################################################################################
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

	## NOTE: This opens a window that displays the correct figure with the appropriate patterns. For some reason, the slash-mark patterns are not showing up on the HTML output page otherwise. Eventually we will delete this part.
	#fig.show()
	#outData['derOverviewHtml'] = fig.to_html(full_html=False)
	fig.write_html(pJoin(modelDir, 'Plot_NewDemand.html'))

	## Encode plot data as JSON for showing in the HTML 
	outData['newDemandData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['newDemandLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)

	########################################################################################################################################################
	## DER Serving Load Overview plot 
	########################################################################################################################################################
	fig = go.Figure()

	## vbatDispatch variables
	vbat_discharge_component = np.array(combined_device_results['vbat_discharge'])
	vbat_charge_component = np.array(combined_device_results['vbat_charge_flipsign'])
	vbat_charge_component[vbat_charge_component == -0.0] = 0.0 ## convert all -0 to just 0 for precaution

	## Convert all values from kW to Watts for plotting purposes only
	#try:
	#	grid_to_load = reoptResults['ElectricUtility']['electric_to_load_series_kw']
	#except KeyError:
	#	raise Exception('No ElectricUtility found in REopt outputs. Cannot get electric grid to load series.')
	if 'ElectricUtility' in reoptResults:
		grid_to_load = reoptResults['ElectricUtility']['electric_to_load_series_kw']
	else:
		## NOTE: temporarily let the model finish through this error, even though this means that something is wrong with REopt (infeasible model solve, or otherwise)
		warnings.warn('No ElectricUtility was found in REopt output. Setting Grid Serving Load output series to zero.')
		grid_to_load = np.zeros_like(demand)

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

	## Discharging DERs to plot
	for col in ['Grid Serving Load', 'Home BESS Serving Load', 'Home Generator Serving Load', 'Home TESS Serving Load', 'Grid Charging Home BESS', 'Grid Charging Home TESS']:
		fig.add_trace(go.Scatter(
			x=df['timestamp'],
			y=df[col],
			fill='tonexty',
			mode='none',
			name=col,
			fillcolor=colors[col],
			line_shape=lineshape,			
			stackgroup='discharge'  ## Stack all the discharging DERs together
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
		xaxis_title='Timestamp',yaxis_title='Power (W)',
		yaxis2=dict(title='degrees Fahrenheit',overlaying='y',side='right'),
    	legend=dict(orientation='h',yanchor='bottom', xanchor='right',y=1.02,x=1,)
	)

	## NOTE: This opens a window that displays the correct figure with the appropriate patterns. For some reason, the slash-mark patterns are not showing up on the HTML output page otherwise. Eventually we will delete this part.
	#fig.show()
	#outData['derOverviewHtml'] = fig.to_html(full_html=False)
	fig.write_html(pJoin(modelDir, 'Plot_DerServingLoadOverview.html'))

	## Encode plot data as JSON for showing in the HTML 
	outData['derOverviewData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['derOverviewLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)

	########################################################################################################################################################
	## Thermal DER Serving Load Overview plot 
	## NOTE: This plot is like DER Serving Load Overview but only shows the thermal (AC, WH, HP) technologies
	########################################################################################################################################################
	fig = go.Figure()
	
	df = pd.DataFrame({
		'timestamp': timestamps,
		'Grid Serving Load': grid_to_load_W,
	})

	## Grid Serving Load series
	fig.add_trace(go.Scatter(
			x=df['timestamp'],
			y=df['Grid Serving Load'],
			fill='tonexty',
			mode='none',
			name='Grid Serving Load',
			fillcolor='rgba(128, 128, 128, 0.8)', ## gray at 80% opacity
			line_shape=lineshape,			
			stackgroup='withgrid' ## Stack all DERs together + grid
		))
	
	for thermal_device in single_device_results:
		## thermal_device = 'vbatResults_hp'
		if thermal_device == 'vbatResults_hp':
			label = 'Home Heat Pump'
			discharge_color = 'rgba(58,147,195,1)' ## medium blue
			charge_color = 'rgba(58,147,195,0.5)' ## medium blue at 50% opacity
		if thermal_device == 'vbatResults_ac':
			label = 'Home Air Conditioner'
			discharge_color = 'rgba(142,196,222,1)' ## light blue
			charge_color = 'rgba(142,196,222,0.5)' ## light blue at 50% opacity
		if thermal_device == 'vbatResults_wh':
			label = 'Home Water Heater'
			discharge_color = 'rgba(16,101,171,1)' ## dark blue
			charge_color = 'rgba(16,101,171,0.5)' ## dark blue at 50% opacity

		discharge_W = thermal_device_savings[thermal_device]['vbat_discharge_component_W']
		charge_W = thermal_device_savings[thermal_device]['vbat_charge_component_flipsign_W']

		fig.add_trace(go.Scatter(
			x=df['timestamp'],
			y=discharge_W,
			fill='tonexty',
			mode='none',
			name=label+' Serving Load',
			fillcolor=discharge_color,
			line_shape=lineshape,			
			stackgroup='withgrid' ## Stack all DERs together + grid
		))

		fig.add_trace(go.Scatter(
			x=df['timestamp'],
			y=charge_W,
			fill='tonexty',
			mode='none',
			name='Grid Charging ' + label,
			fillcolor=charge_color,
			line_shape=lineshape,
			stackgroup='withgrid' ## Stack all DERs together + grid
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
		xaxis_title='Timestamp', yaxis_title='Power (W)',
		yaxis2=dict(title='degrees Fahrenheit',overlaying='y',side='right'),
    	legend=dict(orientation='h',yanchor='bottom', xanchor='right',y=1.02,x=1,)
	)

	## NOTE: This opens a window that displays the correct figure with the appropriate patterns. For some reason, the slash-mark patterns are not showing up on the HTML output page otherwise. Eventually we will delete this part.
	#fig.show()
	#outData['derOverviewHtml'] = fig.to_html(full_html=False)
	fig.write_html(pJoin(modelDir, 'Plot_ThermalDERServingLoadOverview.html'))

	## Encode plot data as JSON for showing in the HTML 
	outData['ThermalDEROverviewData'] = json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder)
	outData['ThermalDEROverviewLayout'] = json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder)

	################################################################################################################################################
	## Create Thermal Battery Power plot object 
	################################################################################################################################################
	fig = go.Figure()

	data_names = ['vbatMinPowerCapacity', 'vbatMaxPowerCapacity', 'vbatPower']
	colors = ['green', 'blue', 'black']
	titles = ['Minimum Calculated Power Capacity', 'Maximum Calculated Power Capacity', 'Actual Power Utilized']

	thermalDataCheckList = []
	for data_name, color, title in zip(data_names, colors, titles):
		thermalDataCheck = np.sum(combined_device_results[data_name])
		thermalDataCheckList.append(thermalDataCheck)
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
	outData['thermalDataCheck'] = float(sum(np.array(thermalDataCheckList)))
	
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

	######################################################################################################################################################
	## MONTHLY COST COMPARISON PLOT VARIABLES
	######################################################################################################################################################
	outData['monthlyEnergyConsumption'] = list(monthlyEnergyConsumption)
	outData['monthlyAdjustedEnergyConsumption'] = list(monthlyAdjustedEnergyConsumption)
	outData['monthlyEnergyConsumptionCost'] = list(monthlyEnergyConsumptionCost)
	outData['monthlyAdjustedEnergyConsumptionCost'] = list(monthlyAdjustedEnergyConsumptionCost)
	outData['monthlyEnergyConsumptionSavings'] = list(monthlyEnergyConsumptionSavings)
	outData['monthly_gen_fuel_cost'] = list(monthly_fuel_cost)
	outData['allDevices_subsidy_year1'] = list(allDevices_subsidy_year1_monthly_array)
	#outData['allDevices_compensation_year1'] = list(allDevices_compensation_year1_monthly_array)
	outData['savings_year1_monthly_array'] = list(savings_year1_monthly_array)
	outData['costs_year1_array'] = list(costs_year1_array)
	outData['net_savings_year1_array'] = list(net_savings_year1_array)

	######################################################################################################################################################
	## CashFlow Projection Plot variables
	## NOTE: Costs are converted to a negative value for plotting purposes
	######################################################################################################################################################
	## Calculate Net Present Value (NPV) and Simple Payback Period (SPP)
	outData['NPV'] = npv(float(inputDict['discountRate'])/100., net_savings_allyears_array)
	SPP = initialInvestment/savings_year1_total
	outData['SPP'] = SPP
	outData['savings_allyears_array'] = list(savings_allyears_array)
	outData['costs_allyears_array'] = list(costs_allyears_array*-1.0) ## negative for plotting purposes
	outData['cumulativeCashflow_total'] = list(np.cumsum(net_savings_allyears_array))
	
	######################################################################################################################################################
	## Savings Breakdown Per Technology Plot variables
	## NOTE: Costs are converted to a negative value for plotting purposes
	######################################################################################################################################################
	#outData['savings_allyears_BESS'] = list(totalSavings_BESS_allyears_array)
	#outData['savings_allyears_TESS'] = list(totalSavings_TESS_allyears_array)
	#outData['savings_allyears_GEN'] = list(totalSavings_GEN_allyears_array)
	##TODO: check against the totals above
	outData['savings_consumption_BESS_allyears'] = list(BESS_consumption_savings_allyears)
	outData['savings_consumption_TESS_allyears'] = list(TESS_consumption_savings_allyears)
	outData['savings_consumption_GEN_allyears'] = list(GEN_consumption_savings_allyears)

	outData['savings_peakDemand_BESS_allyears'] = list(BESS_peakDemand_savings_allyears)
	outData['savings_peakDemand_TESS_allyears'] = list(TESS_peakDemand_savings_allyears)
	outData['savings_peakDemand_GEN_allyears'] = list(GEN_peakDemand_savings_allyears)

	outData['costs_allyears_BESS'] = list(-1.0*(costs_allyears_BESS)) 
	outData['costs_allyears_TESS'] = list(-1.0*(costs_allyears_TESS))
	outData['costs_allyears_GEN'] = list(-1.0*(costs_allyears_GEN))
	outData['cumulativeSavings_total'] = list(np.cumsum(savings_allyears_array))

	######################################################################################################################################################
	## Savings Breakdown of Thermal Technology Plot variables
	######################################################################################################################################################
	outData['costs_allyears_wh'] = list(-1.0*(costs_allyears_wh))
	outData['costs_allyears_hp'] = list(-1.0*(costs_allyears_hp))
	outData['costs_allyears_ac'] = list(-1.0*(costs_allyears_ac))

	## Add a flag for the case when no DER technology is specified. The Savings Breakdown plot will then display a placeholder plot with no available data.
	outData['techCheck'] = float(sum(BESS) + sum(vbat_discharge_component) + sum(generator))

	# Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''

	return outData

def new(modelDir):

	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derConsumer','example_load_consumer_10kW.csv')) as f:
		demand_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derConsumer','example_temperatures_open-meteo-denverCO-noheaders.csv')) as f:
		temperature_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derConsumer','example_residential_tariff.json')) as jsonFile:
		residential_rate_structure = json.load(jsonFile)
	#with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','TODrate66a13566e90ecdb7d40581d2.json')) as jsonFile:
	# residential_rate_curve = json.load(jsonFile)
	#with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derConsumer','TOU_rate_schedule.csv')) as f:
	# energy_rates_per_kwh = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derConsumer','example_water_heater_random_numbers.csv')) as f:
		random_numbers = f.read()
	
	defaultInputs = {
		## TODO: maybe incorporate float, int, bool types on the html side instead of only strings?
		
		## OMF inputs:
		'user' : 'admin',
		'modelType': modelName,
		'created': str(datetime.datetime.now()),
		
		## General Model Inputs:
		'set_random_numbers': 'No',
		'randomNumbersFileName': 'example_water_heater_random_numbers.csv',
		'randomNumbers': random_numbers,
		'random_seed_PuLP_ac': '2147483647', #max=2147483647
		'random_seed_PuLP_hp': '2147483647', #max=2147483647
		'random_seed_PuLP_wh': '2147483647', #max=2147483647
		'random_seed_HiGHS_REopt': '2147483647', #max=2147483647
		
		## REopt inputs:
		'urdbLabel': '66a13566e90ecdb7d40581d2',
		'latitude': '39.969753', ## Brighton, CO
		'longitude': '-104.812599', ## Brighton, CO
		'year': '2018',
		'demandFileName': 'example_load_consumer_10kW.csv',
		'demandCurve': demand_curve,
		'temperatureFileName': 'example_temperatures_open-meteo-denverCO-noheaders.csv',
		'temperatureCurve': temperature_curve,
		'urdbLabelBool': False,
		'residentialRateStructureFileName': 'example_residential_tariff.json',
		'residentialRateStructure': residential_rate_structure,
		
		## Financial Inputs
		'projectionLength': '25',
		'discountRate': '1',
		#'rateCompensation': '0.02', ## unit: $/kWh
		'BESS_subsidy_onetime': '50.0',
		'BESS_subsidy_ongoing': '10.0',
		'TESS_subsidy_onetime_ac': '0.0',
		'TESS_subsidy_ongoing_ac': '1.0',
		'TESS_subsidy_onetime_hp': '0.0',
		'TESS_subsidy_ongoing_hp': '1.0',
		'TESS_subsidy_onetime_wh': '0.0',
		'TESS_subsidy_ongoing_wh': '3.0',
		'GEN_subsidy_onetime': '0.0',
		'GEN_subsidy_ongoing': '0.0',

		## Chemical Battery Inputs
		## Modeled after residential Tesla Powerwall 3 battery specs
		'enableBESS': 'Yes',
		'BESS_kw': '5.0',
		'BESS_kwh': '13.5',
		'BESS_retrofit_cost': '0.0',
		'utility_BESS_portion': '20.0',
		'replace_cost_per_kw': '0.0', #'324.0',
		'replace_cost_per_kwh': '0.0', #'351.0',
		'battery_replacement_year': '10',
		'inverter_replacement_year': '10',
		'replace_cost_inverter': '0.0', #'2400',

		## Fossil Fuel Generator
		## NOTE: Generac Guardian models range from 10-26 kW
		'fossilGenerator': 'No',
		'fuel_type': '3',
		'existing_gen_kw': '5',
		'thermal_efficiency': '35',
		'gen_retrofit_cost': '0.0',
		'fuel_avail': '1000',
		'fuel_cost': '3.80',
		'replace_cost_generator_per_kw': '0.0', #'450',
		'generator_replacement_year': '15',

		## Home Air Conditioner inputs (vbatDispatch):
		'load_type_ac': '1',
		'unitDeviceCost_ac': '13',
		'unitUpkeepCost_ac': '0.0', ## NOTE: Input is currently hidden in HTML
		'power_ac': '5.6',
		'capacitance_ac': '2.0',
		'resistance_ac': '2.0',
		'cop_ac': '2.5',
		'setpoint_ac': '72.5',
		'deadband_ac': '2.0',

		## Home Heat Pump inputs (vbatDispatch):
		'load_type_hp': '2',
		'unitDeviceCost_hp': '150',
		'unitUpkeepCost_hp': '0.0', ## NOTE: Input is currently hidden in HTML
		'power_hp': '5.6',
		'capacitance_hp': '2.0',
		'resistance_hp': '2.0',
		'cop_hp': '3.5',
		'setpoint_hp': '67.0',
		'deadband_hp': '2.0',

		## Home Water Heater inputs (vbatDispatch):
		'load_type_wh': '4',
		'unitDeviceCost_wh': '175',
		'unitUpkeepCost_wh': '0.0', ## NOTE: Input is currently hidden in HTML
		'power_wh': '4.5',
		'capacitance_wh': '0.4',
		'resistance_wh': '120.0',
		'cop_wh': '1.0',
		'setpoint_wh': '125.0',
		'deadband_wh': '5.4',
		}

	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _debugging():
	# Model Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
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
	_debugging()