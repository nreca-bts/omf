''' Performs a cost-benefit analysis for a utility or cooperative member interested in 
controlling behind-the-meter distributed energy resources (DERs). '''

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
tooltip = ('Performs a cost-benefit analysis for a utility or cooperative member interested in controlling behind-the-meter distributed energy resources (DERs).')
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True ## Keep the model hidden=True during active development

def calculate_fval(peak, adjusted_peak, DER_contribution):
	""" 
	Calculates linear scaling factor, Fval, to quantify the impact of DERs on the total peak demand savings when the peak is shifted by the contribution from DERs.
	Fval is calculated as follows = (peak - adjusted_peak) / DER_contribution. Fval is set to zero in cases where the DER_contribution is zero.
	
	Inputs:
	 - peak (array): The peak demand (e.g. kW) or peak demand cost ($) for the demand curve without DERs.
	 - adjusted_peak (array): The adjusted peak demand (e.g. kW) or adjusted peak demand cost ($) for the demand curve including DERs.
	 - DER_contribution (array): The contribution (in units of kW or $) from all DERs at the location of the peak demand for the demand curve without DERs.

	Outputs:
	 - fval (array): Returns an array of float values representing the scaling factor for each peak to be applied to each DER individually.
	"""

	numerator = peak - adjusted_peak
	denominator = DER_contribution
	fval = np.zeros_like(peak) ## Initialize monthly array for fval as all zeros
	nonzero_case = denominator != 0 ## If the DER contribution is nonzero, then calculate Fval
	fval[nonzero_case] = numerator[nonzero_case] / denominator[nonzero_case]

	return fval

def construct_monthly_demand_charge_array(response_file, timestamps, demand, monthHours):
	"""
	Extracts demand charge information contained in the JSON response_file and calculates the total monthly demand charge cost ($) based on the demand rate structure and monthly facility demand charge, if present. 
	This function accounts for demand rate tiers on an hourly level (e.g. a weekday window of 2-8pm is charged at some $/kW rate, whereas a weekend window could be 5-10pm at a different $/kW rate, and so on).

	Inputs:
	- response_file (dict): Dictionary representing the JSON output from the NREL REopt Custom Tariff Builder (requires a free account) https://reopt.nrel.gov/tool/custom_tariffs/new that contains information about the TOU Energy Charges, TOU Demand Charges, and facility demand charges, if applicable.
	- timestamps (array, length 8760): Hourly timestamps for the year used to identify the proper weekdays and weekends when building the rate schedules.
	- demand (array, length 8760): The hourly utility demand curve (kW) for the entire year.
	- monthHours (list of tuples, length 12): A list of tuples defining the beginning hour index number and end hour index number for each month. For example, January would have monthHours=[(0,744)] where January 1 00:00:00 has index number 0 and January 31 23:59:00 has the index number 744. The monthHours is used to define the limits of each month in which to calculate the maximum monthly peak kW.

	Outputs:
	- monthly_demand_charge (array of length 12, units: $/kW): The monthly demand charges ($/kW) for an entire year.
	- monthly_demand_charge_cost (array of length 12, units: $): The resulting monthly cost ($) from the monthly demand charge ($/kW) x monthly peak demand (kW).
	- monthly_demand_peak_kw (array of length 12, units: kW): The peak kW for each month.
	- period_max_dollar_indices (list of lists, e.g. [[index of max $ in rate window 1, max $ of rate window 1, rate ($/kW) of window 1],[index of max $ of window 2, max $ of window 2, rate ($/kW) of window 2], etc]). 
		where 'index of max $' is the index of the max (demand kW * rate $/kW = $ amount) for each window (consecutive 1's or 2's or whatever the rate period is, as defined in the JSON response file demandrateschedule), 
		the 'max $ of the rate window' is the actual dollar amount corresponding to that index, and the 'rate ($/kW) of the window' is the rate ($/kW) corresponding to that period window from which the maximum $ amount was determined.
	"""

	## --- Demand Rate Construction ---
	monthly_demand_charge_cost = np.zeros(12) ## Initialize array
	monthly_total_kW = np.zeros(12)
	period_max_dollar_indices = []
	if 'demandratestructure' in response_file:
		demand_weekday_schedule = response_file['demandweekdayschedule']
		demand_weekend_schedule = response_file['demandweekendschedule']
		demand_rate_structure_flattened = [item[0] for item in response_file['demandratestructure']]
		period_rates = [item['rate'] for item in demand_rate_structure_flattened] ## NOTE: does not account for multiple tiers within a period

		## Construct an array of 8760 elements with the demand period number (e.g. 1,2) for each hour using the weekday and weekend demand rate schedule
		hourly_period_array = np.zeros(8760)
		for i, date in enumerate(timestamps):
			## Use the weekday schedule list of tiers if it's a weekday, else use the weekend schedule
			schedule = demand_weekday_schedule if date.weekday() < 5 else demand_weekend_schedule
			month_index = date.month - 1 ## Python uses zero indexing (i.e. January = 0)
			period = schedule[month_index][date.hour]
			hourly_period_array[i] = period

		## For each month, define the hourly demand period windows (e.g. 1's, 2's, etc)
		for month_number, (month_beginning, month_ending) in enumerate(monthHours):
			## month number: 0=Jan, 1=Feb, 2=Mar
			## month_beginning: index for the starting hour of the month. month_ending: index for the last hour of the month.
			periods_in_this_month = hourly_period_array[month_beginning:month_ending]
			demands_in_this_month = demand[month_beginning:month_ending]

			## Define the consecutive hours in each period window
			## Select out each period window and take the maximum kW in that window multiplied by the corresponding period rate
			window_start_index = 0 ## Begin the first window at the first index of this month's array
			#period_max_kw_indices = []
			while window_start_index < len(periods_in_this_month):
				current_period = int(periods_in_this_month[window_start_index])

				window_end_index = window_start_index + 1 ## set the initial window_end_index to be the following index. NOTE: window_start_index is the beginning of the period window, window_end_index will become the last index of the period window
				while (window_end_index < len(periods_in_this_month)) and (periods_in_this_month[window_end_index] == current_period):
					window_end_index += 1  ## keep extending the end_index of the period window until the period number is no longer the same or the month ends.
				
				## In each rate period window, calculate the demand cost of each hour based on the demand rate for that period. Then, select out the maximum $ amount (instead of max kW) within that period window.
				## NOTE: The max $ amount is sought instead of max kW because this is a better comparison between different rate periods with different kW. The goal is to find the maximum $ benefit to the utility, which is not always the max kW because the demand rates could vary.
				kw_window = demands_in_this_month[window_start_index:window_end_index] ## Define the window of demands (kW)
				dollar_window = kw_window * period_rates[current_period]
				max_dollar_index = np.argmax(dollar_window) ## index of the max dollar amount within the period window
				max_dollar = dollar_window[max_dollar_index] ## max dollar amount within the period window
				max_kw_of_max_dollar = demand[window_start_index+max_dollar_index] 
				period_max_dollar_indices.append([month_beginning+window_start_index+max_dollar_index, max_dollar, period_rates[current_period]]) ## NOTE: These indices correspond to the hourly array of 8760 elements for the year, not the period window
				monthly_demand_charge_cost[month_number] += max_dollar
				
				## In each rate period window, calculate the max kW and add it to the monthly_total_kW output
				kw_window_max_index = window_start_index + np.argmax(kw_window) ## Gives the demand curve array index for the maximum kW within the rate period window
				kw_window_max = demand[month_beginning+kw_window_max_index] ## Gives the associated maximum kW within the rate period window
				monthly_total_kW[month_number] += kw_window_max
				#period_max_kw_indices.append([max_kw_index, max_kw, period_rates[current_period]])
				#demand_charge = max_kw * period_rates[current_period] ## demand_charge units: $
				#monthly_demand_charge_cost[month] += demand_charge ## Add the total demand charge to the corresponding month

				window_start_index = window_end_index ## Restart the window using the last index of the previous window

	## Maximum monthly peak kW demand
	#monthly_demand_peak_kw = [demand[np.argmax(demand[s:f])] for s, f in monthHours]

	## --- Facility Demand Charge Construction ---
	#if 'flatdemandmonths' in response_file and len(response_file['flatdemandmonths']) != 0:
	#	demand_rate_structure_flattened = [item[0] for item in response_file['flatdemandstructure']]
	#	monthly_demand_rates = [item['rate'] for item in demand_rate_structure_flattened]
	#	del monthly_demand_rates[0] ## Drop the first element which is a value of 0 due to zero-indexing structure
	#	flat_monthly_peak_demand_cost = np.array(monthly_demand_peak_kw) * np.array(monthly_demand_rates)
	#	monthly_demand_charge_cost += flat_monthly_peak_demand_cost ## TODO: Update this to be mutually exclusive with the demandratestructure, not additive
	#	monthly_demand_charge = monthly_demand_rates[:]
	#else:
	#	warnings.warn("No monthly Facility Demand Charge detected in JSON response file. Setting the monthly peak demand charges ($/kW) to zero.")
	#	monthly_demand_charge = np.zeros(12)
		
	## TODO: Add fixed charges
	## --- Fixed charges $/day/meter ---

	return monthly_demand_charge_cost, monthly_total_kW, period_max_dollar_indices #period_max_kw_indices

def adjust_charging_and_discharging(df, priority_order, available_priority_tech):
	"""
	Adjusts the charging and discharging arrays for TESS technologies that compete for charge time.
	When two or more TESS technologies compete for charge time at a given hour, the highest priority tech will prevail. All other low priority tech will have the charge (kW) set to zero, and subsequent discharge will be removed to reflect the amount of charge that was removed.

	Inputs:
	- df (dataFrame): Contains the hourly charging, discharging, and total power columns for each TESS technology for an entire year.
	- priority_order (dict): Priority order mapping between the tech name and the priority number with 0 corresponding to the highest priority technology (e.g. {vbatResults_wh_charging: 0, vbatResults_ac_charging: 1}).

	Outputs:
	- df (dataFrame): Contains the adjusted hourly charging, discharging, and total power for each TESS technology based on the charge priorization scheme.
	
	"""
	for index in df.index:
		competing_technologies = [tech for tech in available_priority_tech if df.at[index, tech] > 0]

		if len(competing_technologies) > 1:
			## Identify the highest priority technology
			highest_priority_tech = sorted(competing_technologies, key=lambda x: priority_order[x])[0]
			charge_removal_amounts = {tech: df.at[index, tech] for tech in competing_technologies if tech != highest_priority_tech}

			## Process lower priority technologies
			for tech, amount in charge_removal_amounts.items():
				discharge_col_name = tech.replace('charging', 'discharging')
				df.at[index, tech] = 0  ## Set charge to zero at the current index

				## Accumulate the amount of discharge to be removed
				total_charge_removed = amount

				## Iterate through subsequent indices to remove the discharge up to and including the amount of charge that was removed
				next_index = index + 1
				while total_charge_removed > 0 and next_index < len(df):
					current_discharging = df.at[next_index, discharge_col_name]
					if current_discharging > 0:
						if current_discharging <= total_charge_removed:
							total_charge_removed -= current_discharging
							df.at[next_index, discharge_col_name] = 0  ## Remove all discharge
						else:
							df.at[next_index, discharge_col_name] -= total_charge_removed
							total_charge_removed = 0  ## Discharge removal met
					next_index += 1

	## Update the total power for each technology
	for tech in available_priority_tech:
		discharge_col_name = tech.replace('charging', 'discharging')
		total_power_col_name = tech.replace('charging', 'totalpower')
		df[total_power_col_name] = df[discharge_col_name] - df[tech]  ## New total power (after priority adjustments) = discharge - charge 
	return df

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	
	## Delete output file every run if it exists
	outData = {}

	########################################################################################################################
	## Handle and save user input files
	########################################################################################################################
	## Remove old input files if necessary
	inputFileNames = ['input_demand.csv', 'input_temperature.csv', 'input_wholesale_energy_rate_structure.json',
				'input_wholesale_rate_curve.csv','input_monthly_demand_charges.csv',
				'vbatDispatch_inputs_ac.json', 'vbatDispatch_results_ac.json', 
				'vbatDispatch_inputs_hp.json', 'vbatDispatch_results_hp.json',
				'vbatDispatch_inputs_wh.json', 'vbatDispatch_results_wh.json',
				'PuLP_random_seeds.csv']
	for FileName in inputFileNames:
		try:
			os.remove(pJoin(modelDir, FileName))
		except OSError:
			pass

	## Save all input files
	with open(pJoin(modelDir, 'input_demand.csv'), 'w') as f:
		f.write(inputDict['demandCurve'].replace('\r', ''))
	with open(pJoin(modelDir, 'input_temperature.csv'), 'w') as f:
		f.write(inputDict['temperatureCurve'].replace('\r', ''))
	if inputDict.get('useWholesaleJSONBool'): 
		with open(pJoin(modelDir, 'input_wholesale_rate_structure.json'), 'w') as jsonFile:
			json.dump(inputDict['wholesaleRateStructure'], jsonFile)
	else:
		with open(pJoin(modelDir, 'input_wholesale_rate_curve.csv'), 'w') as f:
			f.write(inputDict['wholesaleRateCurve'].replace('\r', ''))
		with open(pJoin(modelDir, 'input_monthly_demand_charges.csv'), 'w') as f:
			f.write(inputDict['monthlyDemandCharges'].replace('\r', ''))

	########################################################################################################################
	## Process input demand, temperature, and other input variables
	########################################################################################################################
	## Convert user provided demand and temperature data from str to float
	## NOTE: assumes the input temperature curve is in degrees Fahrenheit. The degrees Celsius conversion is used later for vbatDispatch, which expects deg C. 
	temperatures_degF = [float(value) for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	temperatures_degC = [(float(value)-32.0)/(9/5) for value in inputDict['temperatureCurve'].split('\n') if value.strip()]
	demand = [float(value) for value in inputDict['demandCurve'].split('\n') if value.strip()]
	demand[demand == -0.0] = 0.0 ## avoid sign errors
	
	## Check if the demand and temperature curves are the correct length and account for leap years by removing Dec 31 data.
	if len(demand) != 8760:
		raise Exception(f'Demand Curve must have exactly 8760 elements, but got {len(demand)}. If this is a leap year, remove December 31 and ensure there are 8760 elements.')
	if len(temperatures_degF) != 8760:
		raise Exception(f'Temperature Curve must have exactly 8760 elements, but got {len(temperatures_degF)}. If this is a leap year, remove December 31 and ensure that there are 8760 elements.')

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
	## Construct the wholesale energy and demand rate arrays using either the Wholesale Tariff JSON response file or user-provided .csv files
	########################################################################################################################################################
	if inputDict.get('useWholesaleJSONBool'): ## Checkbox to use the .json file is True by default
		## Load the Wholesale Energy Rate Structure JSON file
		try:
			## Try to normally parse the JSON file and use it as a Python dictionary
			response_file = json.loads(inputDict['wholesaleRateStructure'])
		except json.JSONDecodeError:
			## Convert single quotes to double quotes for proper JSON formatting, then parse the JSON and use it as a Python dictionary
			try: 
				fixed = inputDict['wholesaleRateStructure'].replace("'", '"')
				response_file = json.loads(fixed)
			except json.JSONDecodeError:
				raise Exception('Try re-uploading the JSON file and running the model again.')
		except TypeError:
			## If the wholesale_rate_curve is already a Python dictionary, use it directly
			if isinstance(inputDict['wholesaleRateStructure'], dict):
				response_file = inputDict['wholesaleRateStructure']
		
		## --- Energy Rate Construction ---
		## Construct the energy rate array from the REopt JSON response file
		#energy_rate_array, monthly_demand_charge, demand_rate_array = construct_tou_tariff_arrays(response_file, timestamps)
		#energy_rate_array = construct_energy_rate_array(response_file, timestamps)
		energy_rate_array = np.zeros(8760)
		if 'energyratestructure' in response_file:
			## The energy rate structure refers to a nested list of dictionary items with "rate" and "unit" keys
			## For example: response_file['energyratestructure'] = [[{'rate': 0, 'unit': 'kWh'}], [{'rate': 0.1, 'unit': 'kWh'}], [{'rate': 0.2, 'unit': 'kWh'}]]
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
					raise ValueError(f'Period number {period_number} not found in energyratestructure in the Wholesale Energy & Demand Rate Structure (.json) file.')

				thresholds = tier_thresholds_by_period[period_number]
				monthly_kwh = energy_monthly_cumulative_sum[hour_index]

				## Apply the energy rate within the proper tier thresholds
				for max_kwh, rate in thresholds:
					if monthly_kwh <= max_kwh:
						energy_rate_array[hour_index] = rate
						break
		else:
			raise Exception('No energy rate structure information was found in the Wholesale Energy & Demand Rate Structure (.json) file. Please include this information when creating the JSON or select a different method for input.')

	else: ## Use the user-provided Wholesale Energy Rate Curve (.csv) and Monthly Demand Charge (.csv) files instead of the Wholesale Energy Rate Structure (.json) file
		energy_rate_array = np.array([float(value) for value in inputDict['wholesaleRateCurve'].split('\n') if value.strip()])
		#demand_rate_array = np.fill(12,inputDict['demandChargeCost'])
		if len(energy_rate_array) != 8760:
			raise ValueError(f'Energy Rate Curve must have exactly 8760 values, but got {len(energy_rate_array)}.')
		
		peakDemandCharge = np.array([float(value) for value in inputDict['monthlyDemandCharges'].split('\n') if value.strip()])
		if np.sum(peakDemandCharge) == 0.0:
			warnings.warn('The Monthly Demand Charges CSV file contains all zeros. This will cause the DER demand charge savings to be zero as well.')
		if len(peakDemandCharge) != 12:
			raise ValueError(f'The Monthly Demand Charges CSV file must have 12 values, but got {len(peakDemandCharge)} instead.')

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
		scenario['ElectricTariff']['tou_energy_rates_per_kwh'] = energy_rate_array.tolist()
		scenario['ElectricTariff']['monthly_demand_rates'] = peakDemandCharge.tolist()

	## Add fossil fuel generator to input scenario, if enabled
	if inputDict['fossilGenerator'] == 'Yes' and int(inputDict['number_devices_GEN']) > 0:
		GENcheck = 'enabled'
		scenario['Generator'] = {
			'existing_kw': float(inputDict['existing_gen_kw']) * int(inputDict['number_devices_GEN']),
			'max_kw': 0.0, ## New generator minumum
			'min_kw': 0.0, ## New generator maximum
			'only_runs_during_grid_outage': False,
			'fuel_avail_gal': float(inputDict['fuel_avail']) * int(inputDict['number_devices_GEN']),
			'fuel_cost_per_gallon': float(inputDict['fuel_cost']),
		}
	else:
		GENcheck = 'disabled'

	## Add a Battery Energy Storage System (BESS) section to REopt input scenario, if enabled 
	if inputDict['enableBESS'] == 'Yes' and int(inputDict['number_devices_BESS']) > 0:
		BESScheck = 'enabled'
		utility_BESS_fraction = float(inputDict['utility_BESS_portion'])/100. ## convert percentage to decimal (e.g. 20% -> 0.20)
		scenario['ElectricStorage'] = {
			'min_kw': float(inputDict['BESS_kw']) * int(inputDict['number_devices_BESS']) * utility_BESS_fraction,
			'max_kw': float(inputDict['BESS_kw']) * int(inputDict['number_devices_BESS']) * utility_BESS_fraction,
			'min_kwh': float(inputDict['BESS_kwh']) * int(inputDict['number_devices_BESS']) * utility_BESS_fraction,
			'max_kwh': float(inputDict['BESS_kwh']) * int(inputDict['number_devices_BESS']) * utility_BESS_fraction,
			'can_grid_charge': True,
			'total_rebate_per_kw': 0.0,
			'macrs_option_years': 0,
			'installed_cost_per_kw': 0.0,
			'installed_cost_per_kwh': 0.0,
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
	## NOTE: reopt_jl currently requires a path for the input file, so the file must be saved to a location - preferrably in the modelDir directory
	with open(pJoin(modelDir, 'reopt_input_scenario.json'), 'w') as jsonFile:
		json.dump(scenario, jsonFile)

	########################################################################################################################
	## Run REopt.jl
	########################################################################################################################
	reopt_jl.run_reopt_jl(modelDir, 'reopt_input_scenario.json', run_with_sysimage=False)

	## Load the REopt results once it is finished running
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
			raise Exception(f'No BESS found in REopt. An error may have occurred, see REopts warning list: {reoptErrorMsgs}.')
		
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
	## TODO: Add handling for giving vbatDispatch monthlyDemandCharges based on the different user input methods (CSV, JSON flatdemand, None)
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
		'unitUpkeepCost': '0.0', ## set to zero: assuming utility does not pay for this
		'monthlyDemandCharges': inputDict['monthlyDemandCharges'], ## NOTE: This is for the CSV input file only, not the JSON response file. vbatDispatch only calculates the peakDeamndCharge and adjustedPeakDemandCharge with this info (it is not used in the optimization and should not affect the thermal technology dispatch behavior)
		'projectionLength': inputDict['projectionLength'],
		'discountRate': inputDict['discountRate'],
		'fileName': inputDict['fileName'],
		'temperatureFileName': inputDict['temperatureFileName'],
		'demandCurve': inputDict['demandCurve'],
		'temperatureCurve': '\n'.join(f'{temperature:.2f}' for temperature in temperatures_degC), ## Convert temperatures_degC into the expected format for vbatDispatch
		'energyRateCurve': '\n'.join(f'{rate:.2f}' for rate in energy_rate_array), ## Convert energy_rate_array into the expected format for vbatDispatch
		'set_random_numbers': inputDict['set_random_numbers'],
		#'random_seed_PuLP': inputDict['random_seed_PuLP'],
		'randomNumbersFileName': inputDict['randomNumbersFileName'],
		'randomNumbers': inputDict['randomNumbers'],
	}

	## Define thermal variables that change depending on the thermal technology(ies) enabled by the user
	thermal_suffixes = ['_ac', '_hp', '_wh'] ## heat pump, air conditioner, water heater - (Add more suffixes here after establishing inputs in the defaultInputs and derUtilityCost.html)
	thermal_variables=['load_type','number_devices','power','capacitance','resistance','cop','setpoint','deadband','TESS_subsidy_ongoing','TESS_subsidy_onetime','random_seed_PuLP']

	all_device_suffixes = []
	single_device_results = {} 
	for suffix in thermal_suffixes:
		## Include only the thermal devices specified by the user
		if float(inputDict['load_type'+suffix]) > 0: ## NOTE: The load_type_X variable will be 0 if the user has disabled that technology
			all_device_suffixes.append(suffix)

			## Add the appropriate thermal device variables to the inputDict_vbatDispatch dictionary
			for i in thermal_variables:
				inputDict_vbatDispatch[i] = inputDict[i+suffix]

			## Convert setpoint and deadband from Fahrenheit to Celsius
			inputDict_vbatDispatch['setpoint'] = str((float(inputDict_vbatDispatch['setpoint'])-32.0)/(9/5))
			inputDict_vbatDispatch['deadband'] = str(float(inputDict_vbatDispatch['deadband'])/1.8)

			## Save the vbatDispatch inputs
			with open(pJoin(modelDir, 'vbatDispatch_inputs'+suffix+'.json'), 'w') as jsonFile:
				json.dump(inputDict_vbatDispatch, jsonFile)
			
			## Run vbatDispatch for the thermal device
			vbatResults = vb.work(modelDir,inputDict_vbatDispatch)
			
			## Update the vbatResults to include subsidies (for easier usage later)
			vbatResults['TESS_subsidy_onetime'] = float(inputDict_vbatDispatch['TESS_subsidy_onetime'])*int(inputDict['number_devices'+suffix])
			vbatResults['TESS_subsidy_ongoing'] = float(inputDict_vbatDispatch['TESS_subsidy_ongoing'])*int(inputDict['number_devices'+suffix])

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
			with open(pJoin(modelDir, 'PuLP_random_seeds.csv'), 'a') as f:
				f.write(tech_name + ': ' + str(vbatResults['random_seed_PuLP'] + '\n'))

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
	adjusted_vbat_power_df = adjust_charging_and_discharging(vbat_power_df, priority_order, available_priority_tech)

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
	combined_device_results['vbat_discharge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series >= 0.0, 0.0) ##positive values = discharging
	combined_device_results['vbat_charge'] = combined_TESS_vbatPower_series.where(combined_TESS_vbatPower_series < 0.0, 0.0) ##negative values = charging
	combined_device_results['vbat_charge_flipsign'] = combined_device_results['vbat_charge'].mul(-1.0)

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

		## Add up all the costs for the total TESS
		costs_year1_monthly_single_device = single_device_subsidy_year1_array #+ single_device_compensation_year1_array
		costs_allyears_single_device = single_device_subsidy_allyears_array #+ single_device_compensation_allyears_array 

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

		## Savings Breakdown Per Thermal Technology cost variables
		## NOTE: This is where the html variables outData['vbatResults_wh_costs_allyears'], outData['vbatResults_hp_costs_allyears'], and outData['vbatResults_ac_costs_allyears'] are saved.
		outData[device_result+'_costs_allyears'] = list(costs_allyears_single_device*-1.0) ## Multiply by negative one for displaying in the plot as a cost
		outData[device_result+'_check'] = 'enabled'

	## vbatDispatch variables
	vbat_discharge_component = np.array(combined_device_results['vbat_discharge'])
	vbat_charge_component = np.array(combined_device_results['vbat_charge_flipsign'])
	vbat_charge_component[vbat_charge_component == -0.0] = 0.0 ## convert all -0 to just 0 for precaution

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
	### Calculate the monthly consumption (kWh) costs and savings
	## NOTE: "base" demand curve = no DERs in the demand curve
	## NOTE: "adjusted" demand curve = DERs included in the demand curve 
	#########################################################################################################################################################

	## Base demand curve energy consumption cost ($/kWh)
	consumptionCost = [float(a) * float(b) for a, b in zip(demand, energy_rate_array)]
	monthlyEnergyConsumption = [sum(demand[s:f]) for s, f in monthHours] ## The total energy in kWh for each month
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

	if inputDict.get('useWholesaleJSONBool'):  ## Use the user-provided JSON response file
		## Peak demand charge cost ($) for the base demand curve (w/o DERs). 
		monthly_demand_charge_cost_withoutDERs, monthly_total_kw_withoutDERs, period_max_dollar_indices_withoutDERs = construct_monthly_demand_charge_array(response_file, timestamps, demand, monthHours)

		## Peak demand charge cost ($) for the adjusted demand curve (with DERs)
		monthly_demand_charge_cost_withDERs, monthly_total_kw_withDERs, period_max_dollar_indices_withDERs = construct_monthly_demand_charge_array(response_file, timestamps, adjusted_demand, monthHours)

		## NOTE: the monthly demand charge rate ($/kW) is the same for both w/ and w/o DERs; it comes from the response file if flatdemandstructure is defined, else it's all zeros.
		
		peakDemandCharge = np.zeros(12) ## TODO: update this if flatdemandstructure is defined in JSON file. Setting to zero for now until Lisa has looked at the JSON inputs from coops. In theory, the flat facility demand input in JSON response file could be used as a monthly demand charge here.

		## Perform the Fval-corrected savings calculations between the demand charge cost w/ DERs and w/o DERs
		if 'demandratestructure' in response_file:
			## Re-stack tuples into arrays
			## max dollar indices for demand curve array, the max dollar amounts, and the demand rates ($/kW)
			noDERs_restacked = list(zip(*period_max_dollar_indices_withoutDERs)) 
			withDERs_restacked = list(zip(*period_max_dollar_indices_withDERs))

			index_withDERs = np.array(withDERs_restacked[0])
			dollar_withDERs = np.array(withDERs_restacked[1]) ##this is the total demand charge cost dollar amount including all DERs for each period window
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

			fval_hourly = calculate_fval(demand_baseP, demand_adjP, totalDER_at_baseP_dollars)

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
				## NOTE: For JSON tariff input, Savings Breakdown of Thermal Technologies plot variables: vbatResults_ac_peakDemand_savings_allyears, vbatResults_wh_peakDemand_savings_allyears, vbatResults_hp_peakDemand_savings_allyears
				device_peakDemand_savings_monthly[device_peakDemand_savings_monthly == -0.0] = 0.0 ## avoid sign errors
				device_peakDemand_savings_allyears = np.full(projectionLength, sum(device_peakDemand_savings_monthly))
				outData[device_name+'_peakDemand_savings_allyears'] = device_peakDemand_savings_allyears.tolist()

				## Consumption (kWh) savings
				## NOTE: Savings Breakdown of Thermal Technologies plot variables: vbatResults_ac_consumption_savings_allyears, vbatResults_wh_consumption_savings_allyears, vbatResults_hp_consumption_savings_allyears
				device_consumption_savings_monthly = thermal_device_savings[device_name]['consumption_cost_monthly']
				device_consumption_savings_allyears = thermal_device_savings[device_name]['consumption_cost_allyears']
				outData[device_name+'_consumption_savings_allyears'] = device_consumption_savings_allyears.tolist()

				## Total savings (demand savings + consumption savings)
				#outData[device_name+'_total_savings_allyears'] = (device_consumption_savings_allyears + device_peakDemand_savings_allyears).tolist()

		## Calculate the monthly peak demand costs for the base demand curve (w/o DERs) and adjusted demand curve (w/ DERs)
		outData['monthlyPeakDemand'] = monthly_total_kw_withoutDERs.tolist()
		outData['monthlyPeakDemandCost'] = monthly_demand_charge_cost_withoutDERs.tolist()
		outData['monthlyAdjustedPeakDemand'] = monthly_total_kw_withDERs.tolist()
		outData['monthlyAdjustedPeakDemandCost'] = monthly_demand_charge_cost_withDERs.tolist()
		outData['monthlyPeakDemandSavings'] = (monthly_demand_charge_cost_withoutDERs - monthly_demand_charge_cost_withDERs).tolist()

	else: ## Use the user-provided .CSV demand charge file
		
		## Get the indices of each month's peak kW demand with respect to the annual demand curve arrays (8760 elements)
		peak_demand_indices = [0]*12 ## demand curve w/o DERs
		adjusted_demand_indices = [0]*12 ## demand curve w/ DERs
		for month_number, (month_begin_index, month_end_index) in enumerate(monthHours):
			demand_this_month = demand[month_begin_index:month_end_index] ## kW demand for each hour of the month
			adjusted_demand_this_month = adjusted_demand[month_begin_index:month_end_index] ## adjusted kW demand for each hour of the month
			index_of_peak_demand_this_month = np.argmax(demand_this_month) 
			index_of_peak_adjusted_demand_this_month = np.argmax(adjusted_demand_this_month)
			peak_demand_indices[month_number] = int(month_begin_index) + index_of_peak_demand_this_month ## indices of every monthly peak demand for the demand curve w/o DERs
			adjusted_demand_indices[month_number] = int(month_begin_index) + index_of_peak_adjusted_demand_this_month ## indices of every monthly peak demand for the demand curve with DERs

		## Calculate the fval-corrected monthly peak demand savings for individual BESS, TESS, and GEN technologies
		peak_demand_at_monthly_baseP = demand[peak_demand_indices] ## baseP = monthly peaks of the baseline demand (without DERs)
		peak_demand_at_monthly_adjP = adjusted_demand[adjusted_demand_indices] ## adjP = monthly peaks of the adjusted demand curve (with DERs)
		
		BESS_demand_at_monthly_baseP = BESS_demand[peak_demand_indices]
		BESS_demand_at_monthly_adjP = BESS_demand[adjusted_demand_indices]
		TESS_demand_at_monthly_baseP = TESS_demand[peak_demand_indices]
		TESS_demand_at_monthly_adjP = TESS_demand[adjusted_demand_indices]
		GEN_demand_at_monthly_baseP = GEN_demand[peak_demand_indices]
		GEN_demand_at_monthly_adjP = GEN_demand[adjusted_demand_indices]

		BESS_demand_at_baseP_cost = BESS_demand_at_monthly_baseP * peakDemandCharge ## e.g. 1000 kW x $50/kW 
		TESS_demand_at_baseP_cost = TESS_demand_at_monthly_baseP * peakDemandCharge
		GEN_demand_at_baseP_cost = GEN_demand_at_monthly_baseP * peakDemandCharge

		allDER_at_baseP = BESS_demand_at_monthly_baseP + TESS_demand_at_monthly_baseP + GEN_demand_at_monthly_baseP
		allDER_at_adjP = BESS_demand_at_monthly_adjP + TESS_demand_at_monthly_adjP + GEN_demand_at_monthly_adjP

		## Calculate linear scaling factor Fval to properly calculate individual DER peak demand savings due to peak shifting
		demand_without_DERs = np.array(peak_demand_at_monthly_baseP) 
		demand_with_DERs = np.array(peak_demand_at_monthly_adjP) 
		DERs_at_demand_peak = np.array(allDER_at_baseP)
		fval_monthly = calculate_fval(demand_without_DERs, demand_with_DERs, DERs_at_demand_peak)

		## Apply the monthly Fval correction to the monthly BESS, TESS, GEN peak demand savings
		BESS_monthly_demand_savings = BESS_demand_at_baseP_cost*fval_monthly
		TESS_monthly_demand_savings = TESS_demand_at_baseP_cost*fval_monthly
		GEN_monthly_demand_savings = GEN_demand_at_baseP_cost*fval_monthly
		#allDevices_peakDemand_savings_monthly = [a+b+c for a,b,c in zip(BESS_monthly_demand_savings,TESS_monthly_demand_savings,GEN_monthly_demand_savings)]

		## Calculate the consumption and fval-corrected demand savings
		for device_name in single_device_results:
			device_demand = thermal_device_savings[device_name]['demand']
			device_demand[device_demand == -0.0] = 0.0 ## avoid sign errors
			device_demand_at_baseP = device_demand[peak_demand_indices]
			device_demand_at_baseP_cost = device_demand_at_baseP * peakDemandCharge

			## Demand (kW) savings
			## NOTE: Assigns the following Savings Breakdown of Thermal Technologies plot variables: vbatResults_ac_peakDemand_savings_allyears, vbatResults_wh_peakDemand_savings_allyears, vbatResults_hp_peakDemand_savings_allyears
			device_peakDemand_savings_monthly = device_demand_at_baseP_cost * fval_monthly
			device_peakDemand_savings_monthly[device_peakDemand_savings_monthly == -0.0] = 0.0 ## avoid sign errors
			device_peakDemand_savings_allyears = np.full(projectionLength, sum(device_peakDemand_savings_monthly))
			outData[device_name+'_peakDemand_savings_allyears'] = device_peakDemand_savings_allyears.tolist()

			## Consumption (kWh) savings
			device_consumption_savings_monthly = thermal_device_savings[device_name]['consumption_cost_monthly']
			device_consumption_savings_allyears = thermal_device_savings[device_name]['consumption_cost_allyears']
			outData[device_name+'_consumption_savings_allyears'] = device_consumption_savings_allyears.tolist()

			## Total savings (demand savings + consumption savings)
			#outData[device_name+'_total_savings_allyears'] = (device_consumption_savings_allyears + device_peakDemand_savings_allyears).tolist()
			
		## Output monthly peak demand costs and savings
		outData['monthlyPeakDemand'] = demand[peak_demand_indices].tolist()
		outData['monthlyPeakDemandCost'] = (peakDemandCharge*np.array(outData['monthlyPeakDemand'])).tolist()  ## peak demand charge before including DERs
		outData['monthlyAdjustedPeakDemand'] = adjusted_demand[adjusted_demand_indices].tolist() ## monthly peak demand hours (including DERs)
		outData['monthlyAdjustedPeakDemandCost'] = (peakDemandCharge * np.array(outData['monthlyAdjustedPeakDemand'])).tolist() ## peak demand charge after including all DERs
		outData['monthlyPeakDemandSavings'] = (np.array(outData['monthlyPeakDemandCost']) - np.array(outData['monthlyAdjustedPeakDemandCost'])).tolist()

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
	BESS_savings_year1_monthly_array = np.array(BESS_consumption_savings_monthly) + np.array(BESS_monthly_demand_savings)
	BESS_savings_allyears = BESS_peakDemand_savings_allyears + np.array(BESS_consumption_savings_allyears)

	TESS_peakDemand_savings_allyears = np.full(projectionLength, sum(TESS_monthly_demand_savings))
	TESS_consumption_savings_allyears = np.full(projectionLength, sum(TESS_consumption_savings_monthly))
	TESS_savings_year1_monthly_array = np.array(TESS_consumption_savings_monthly) + np.array(TESS_monthly_demand_savings)
	TESS_savings_allyears = TESS_peakDemand_savings_allyears + TESS_consumption_savings_allyears

	GEN_peakDemand_savings_allyears = np.full(projectionLength, sum(GEN_monthly_demand_savings))
	GEN_consumption_savings_allyears = np.full(projectionLength, sum(GEN_consumption_savings_monthly))
	GEN_savings_year1_monthly_array = np.array(GEN_consumption_savings_monthly) + np.array(GEN_monthly_demand_savings)
	GEN_savings_allyears = GEN_peakDemand_savings_allyears + GEN_consumption_savings_allyears

	######################################################################################################################################################
	## COSTS
	## Calculate the financial costs of controlling member-consumer DERs
	## e.g. subsidies, operational costs, startup costs
	######################################################################################################################################################

	## If the DER tech is disabled or the discharge array is empty, then set all its subsidies equal to zero.
	if BESScheck == 'enabled' and np.sum(BESS) > 0.0:
		BESS_subsidy_ongoing = float(inputDict['BESS_subsidy_ongoing'])*int(inputDict['number_devices_BESS'])
		BESS_subsidy_onetime = float(inputDict['BESS_subsidy_onetime'])*int(inputDict['number_devices_BESS'])
	else:
		BESS_subsidy_ongoing = 0
		BESS_subsidy_onetime = 0

	if GENcheck == 'enabled' and np.sum(generator) > 0.0:
		GEN_subsidy_ongoing = float(inputDict['GEN_subsidy_ongoing'])*int(inputDict['number_devices_GEN'])
		GEN_subsidy_onetime = float(inputDict['GEN_subsidy_onetime'])*int(inputDict['number_devices_GEN'])
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

	## Calculate ongoing and onetime operational costs
	## NOTE: This includes costs for things like API calls to control the DERs
	operationalCosts_ongoing = float(inputDict['operationalCosts_ongoing'])
	operationalCosts_onetime = float(inputDict['operationalCosts_onetime'])
	operationalCosts_year1_total = operationalCosts_onetime + (operationalCosts_ongoing*12.0)
	operationalCosts_year1_monthly_array = np.full(12, operationalCosts_ongoing)
	operationalCosts_year1_monthly_array[0] += operationalCosts_onetime
	operationalCosts_allyears_array = np.full(projectionLength, operationalCosts_ongoing*12.0)
	operationalCosts_allyears_array[0] += operationalCosts_onetime

	## Calculate startup costs
	startupCosts = float(inputDict['startupCosts'])
	startupCosts_year1_monthly_array = np.zeros(12)
	startupCosts_year1_monthly_array[0] += startupCosts
	startupCosts_allyears_array = np.full(projectionLength, 0.0)
	startupCosts_allyears_array[0] += startupCosts

	## Calculate total utility costs for year 1 and all years
	utilityCosts_year1_total = operationalCosts_year1_total + allDevices_subsidy_year1_total + startupCosts #+ allDevices_compensation_year1_total 
	utilityCosts_year1_monthly_array = operationalCosts_year1_monthly_array + allDevices_subsidy_year1_monthly_array #+ allDevices_compensation_year1_monthly_array 
	utilityCosts_year1_monthly_array[0] += startupCosts ## Add startup costs to the first year in the total cost array
	utilityCosts_allyears_array = operationalCosts_allyears_array + allDevices_subsidy_allyears_array #+ allDevices_compensation_allyears_array 
	utilityCosts_allyears_array[0] += startupCosts ## Add startup costs to the first year in the total cost array
	utilityCosts_allyears_total = np.sum(utilityCosts_allyears_array)

	## Calculate total costs for BESS, TESS, and GEN
	totalCosts_GEN_allyears_array = GEN_subsidy_allyears_array #+ GEN_compensation_allyears_array
	totalCosts_BESS_allyears_array = BESS_subsidy_allyears_array #+ BESS_compensation_allyears_array
	totalCosts_TESS_allyears_array = combinedTESS_subsidy_allyears_array #+ TESS_compensation_allyears_array

	######################################################################################################################################################
	## SAVINGS
	## Calculate the financial savings of controlling member-consumer DERs
	## NOTE: The savings are the sum of the energy consumption savings and peak demand savings
	######################################################################################################################################################
	utilitySavings_year1_monthly_array = np.array(outData['monthlyPeakDemandSavings']) + monthlyEnergyConsumptionSavings
	utilitySavings_year1_total = np.sum(utilitySavings_year1_monthly_array)
	utilitySavings_allyears_array = np.full(projectionLength, utilitySavings_year1_total)
	utilitySavings_allyears_total = np.sum(utilitySavings_allyears_array)

	## Calculating total utility net savings (savings minus costs)
	#utilityNetSavings_year1_total =  utilitySavings_year1_total - utilityCosts_year1_total
	utilityNetSavings_year1_array = utilitySavings_year1_monthly_array - utilityCosts_year1_monthly_array
	utilityNetSavings_allyears_total = utilitySavings_allyears_total - utilityCosts_allyears_total
	utilityNetSavings_allyears_array = utilitySavings_allyears_array - utilityCosts_allyears_array
	
	######################################################################################################################################################
	## Monthly Cost Comparison Plot Variables
	## TODO: hook in the new fval-corrected demand savings to the relevant variables here
	######################################################################################################################################################
	## Calculate Net Present Value (NPV) and Simple Payback Period (SPP)
	initialInvestment = startupCosts + operationalCosts_onetime + allDevices_subsidy_onetime
	utilityCosts_year1_minus_onetime_costs = (operationalCosts_ongoing*12.0) + (allDevices_subsidy_ongoing*12.0) #+ allDevices_compensation_year1_total
	utilityNetSavings_year1_total_minus_onetime_costs = utilitySavings_year1_total - utilityCosts_year1_minus_onetime_costs
	SPP = initialInvestment/utilityNetSavings_year1_total_minus_onetime_costs
	outData['SPP'] = SPP
	outData['NPV'] = npv(float(inputDict['discountRate'])/100., utilityNetSavings_allyears_array)

	## Energy consumption variables ($/kW)
	outData['monthlyEnergyConsumption'] = monthlyEnergyConsumption
	outData['monthlyAdjustedEnergyConsumption'] = monthlyAdjustedEnergyConsumption
	outData['monthlyEnergyConsumptionCost'] = monthlyEnergyConsumptionCost
	outData['monthlyAdjustedEnergyConsumptionCost'] = monthlyAdjustedEnergyConsumptionCost
	outData['monthlyEnergyConsumptionSavings'] = monthlyEnergyConsumptionSavings.tolist()

	## NOTE: The demand variables below are calculated differently depending on the input method for demand rate information (JSON response file vs. CSV file)
	##allOutputData.monthlyPeakDemand
	##allOutputData.monthlyAdjustedPeakDemand
	##allOutputData.monthlyPeakDemandCost
	##allOutputData.monthlyAdjustedPeakDemandCost
	##allOutputData.monthlyTotalCostService
	##allOutputData.monthlyTotalCostAdjustedService
	##allOutputData.monthlyPeakDemandSavings

	#outData['totalCost_paidToConsumer'] = (allDevices_compensation_year1_monthly_array + allDevices_subsidy_year1_monthly_array).tolist()
	outData['totalCost_paidToConsumer'] = allDevices_subsidy_year1_monthly_array.tolist()
	startup_and_operational_costs_year1_array = startupCosts_year1_monthly_array + operationalCosts_year1_monthly_array ## Combine the startup and operational costs for displaying in the Monthly Cost Comparison table
	outData['startupAndOperationalCosts_year1'] = startup_and_operational_costs_year1_array.tolist()
	
	## Monthly Cost Comparison Chart utility costs, utility savings, utility net savings
	outData['totalCosts_year1'] = utilityCosts_year1_monthly_array.tolist()
	outData['totalSavings_year1'] = utilitySavings_year1_monthly_array.tolist()
	outData['totalNetSavings_year1'] = utilityNetSavings_year1_array.tolist() ## (total cost of service - adjusted total cost of service) - (operational costs + subsidies + startup costs)

	## NOTE: The following are not used in the output HTML plot, but could potentially be useful later
	#outData['operationalCosts_allyears'] = list(operationalCosts_allyears_array*-1.)
	#outData['operationalCosts_year1'] = list(operationalCosts_year1_array*-1.)
	#outData['startupCosts_year1'] = list(startupCosts_year1_array*-1.)
	#outData['startupCosts_allyears'] = list(startupCosts_allyears_array*-1.)
	#outData['totalNetSavings_allyears'] = list(utilityNetSavings_allyears_array)

	######################################################################################################################################################
	## CashFlow Projection Plot variables
	## NOTE: The utility costs are shown as negative values
	######################################################################################################################################################
	outData['savingsAllYears'] = utilitySavings_allyears_array.tolist()
	outData['costsAllYears'] = (-1.0*utilityCosts_allyears_array).tolist() ## Show as negative for plotting purposes
	outData['cumulativeCashflow_total'] = np.cumsum(utilityNetSavings_allyears_array).tolist()
	
	## NOTE: The following variables are not used in output HTML plot, but could potentially be useful later
	#outData['subsidies'] = list(allDevices_subsidy_allyears_array*-1.) 
	#outData['BESS_compensation_to_consumer_allyears'] = list(BESS_compensation_allyears_array*-1.)
	#outData['TESS_compensation_to_consumer_allyears'] = list(TESS_compensation_allyears_array*-1.)
	#outData['GEN_compensation_to_consumer_allyears'] = list(GEN_compensation_allyears_array*-1.)
  
	######################################################################################################################################################
	## Savings Breakdown Per Technology Plot variables
	######################################################################################################################################################

	outData['savings_consumption_BESS_allyears'] = BESS_consumption_savings_allyears.tolist()
	outData['savings_consumption_TESS_allyears'] = TESS_consumption_savings_allyears.tolist()
	outData['savings_consumption_GEN_allyears'] = GEN_consumption_savings_allyears.tolist()

	outData['savings_peakDemand_BESS_allyears'] = BESS_peakDemand_savings_allyears.tolist()
	outData['savings_peakDemand_TESS_allyears'] = TESS_peakDemand_savings_allyears.tolist()
	outData['savings_peakDemand_GEN_allyears'] = GEN_peakDemand_savings_allyears.tolist()

	outData['totalCosts_BESS_allyears'] = (-1.0*totalCosts_BESS_allyears_array).tolist() ## Costs are negative for plotting purposes
	outData['totalCosts_TESS_allyears'] =(-1.0*totalCosts_TESS_allyears_array).tolist() ## Costs are negative for plotting purposes
	outData['totalCosts_GEN_allyears'] = (-1.0*totalCosts_GEN_allyears_array).tolist() ## Costs are negative for plotting purposes
	outData['cumulativeSavings_total'] = np.cumsum(utilitySavings_allyears_array).tolist()
	
	## Add a flag for the case when no DER technology is specified. The Savings Breakdown plot will then display a placeholder plot with no available data.
	outData['techCheck'] = float(sum(BESS) + sum(vbat_discharge_component) + sum(generator))

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
			stackgroup='withgrid'  ## Stack all the discharging DERs together
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
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','exampleWholesaleRateStructure.json')) as jsonFile:
		wholesale_rate_structure = json.load(jsonFile)
	#responseFilename = 'TODrate66a13566e90ecdb7d40581d2.json' ## TOD rate JSON file (created using instructions from https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates)
	#responseFilename = 'TOUrate5b311c595457a3496d8367be.json' ## TOU rate JSON file (created using instructions from https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates)
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','utility_monthly_demand_charges.csv')) as f:
		monthly_demand_charges = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','derUtilityCost','water_heater_random_numbers.csv')) as f:
		random_numbers = f.read()

	defaultInputs = {
		## TODO: maybe incorporate float, int, bool types on the html side instead of only strings
		
		## OMF inputs:
		'user' : 'admin',
		'modelType': modelName,
		'created': str(datetime.datetime.now()),

		## General Model Inputs:
		'set_random_numbers': 'No',
		'randomNumbersFileName': 'water_heater_random_numbers.csv',
		'randomNumbers': random_numbers,
		'random_seed_PuLP_ac': '2581590327', #max=10000000000
		'random_seed_PuLP_hp': '4757181440', #max=10000000000
		'random_seed_PuLP_wh': '7148702924', #max=10000000000

		## REopt inputs:
		'latitude': '39.969753', ## Brighton, CO
		'longitude': '-104.812599', ## Brighton, CO
		'year': '2018',
		'fileName': 'utility_2018_kW_load.csv',
		'demandCurve': demand_curve,
		'temperatureFileName': 'open-meteo-denverCO-noheaders.csv',
		'temperatureCurve': temperature_curve,
		'useWholesaleJSONBool': False,
		'wholesaleRateCurveFileName': 'TODrate66a13566e90ecdb7d40581d2.csv',
		'wholesaleRateCurve': wholesale_rate_curve,
		'wholesaleRateStructureFileName': 'exampleWholesaleRateStructure.json',
		'wholesaleRateStructure': wholesale_rate_structure,
		'monthlyDemandChargesFileName': 'utility_monthly_demand_charges.csv',
		'monthlyDemandCharges': monthly_demand_charges,

		## Fossil Fuel Generator Inputs (for REopt)
		## Modeled after Generac 20 kW diesel model with max tank of 95 gallons
		'fossilGenerator': 'No',
		'number_devices_GEN': '5',
		'existing_gen_kw': '20',
		'fuel_type': '3', 
		'fuel_avail': '95', 
		'fuel_cost': '3.49', ## $3.49 is based on fuel cost of diesel fuel in March 2025

		## Chemical Battery Inputs (for REopt)
		## Modeled after residential Tesla Powerwall 3 battery specs
		'enableBESS': 'Yes',
		'number_devices_BESS': '20000',
		'utility_BESS_portion': '20.0',
		'BESS_kw': '5.0',
		'BESS_kwh': '13.5',

		## Financial Inputs
		'projectionLength': '25',
		#'rateCompensation': '0.02', ## unit: $/kWh
		'discountRate': '2',
		'startupCosts': '200000',
		'BESS_subsidy_onetime': '100.0',
		'BESS_subsidy_ongoing': '55.0',
		'TESS_subsidy_onetime_ac': '25.0',
		'TESS_subsidy_ongoing_ac': '5.0',
		'TESS_subsidy_onetime_hp': '25.0',
		'TESS_subsidy_ongoing_hp': '5.0',
		'TESS_subsidy_onetime_wh': '25.0',
		'TESS_subsidy_ongoing_wh': '5.0',
		'GEN_subsidy_onetime': '25.0',
		'GEN_subsidy_ongoing': '5.0',
		'operationalCosts_ongoing': '1000.0',
		'operationalCosts_onetime': '20000.0',
		
		## Home Air Conditioner inputs (for vbatDispatch):
		'load_type_ac': '1', 
		'number_devices_ac': '33000',
		'power_ac': '5.6',
		'capacitance_ac': '2',
		'resistance_ac': '2',
		'cop_ac': '2.5',
		'setpoint_ac': '72.5',
		'deadband_ac': '2',

		## Home Heat Pump inputs (for vbatDispatch):
		'load_type_hp': '2', 
		'number_devices_hp': '16500',
		'power_hp': '5.6',
		'capacitance_hp': '2',
		'resistance_hp': '2',
		'cop_hp': '3.5',
		'setpoint_hp': '65',
		'deadband_hp': '2',

		## Home Water Heater inputs (for vbatDispatch):
		'load_type_wh': '4', 
		'number_devices_wh': '33000',
		'power_wh': '4.5',
		'capacitance_wh': '0.4',
		'resistance_wh': '120',
		'cop_wh': '1',
		'setpoint_wh': '125.0', 
		'deadband_wh': '5.4',
	}
	
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName) # Model Location
	try: 	
		# Blow away old test results if necessary.
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
	
	new(modelLoc) # Create New.
	__neoMetaModel__.renderAndShow(modelLoc) # Pre-run.
	__neoMetaModel__.runForeground(modelLoc) # Run the model.
	__neoMetaModel__.renderAndShow(modelLoc) # Show the output.

if __name__ == '__main__':
	_tests()
	pass