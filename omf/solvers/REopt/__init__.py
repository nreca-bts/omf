"""
Call the hosted NLR REopt API and normalize optimization and resilience-analysis
results for OMF models.

2026-06-02 - REopt in the OMF has transitioned to the julia-based API in reopt_jl.
This module wraps around developer.nlr.gov's REopt API v2 which is deprecated.
https://developer.nlr.gov/docs/energy-optimization/reopt/v3/
"""

import json
import requests
import random
from omf.solvers.REopt import logger
from omf.solvers.REopt import results_poller

REOPT_API_KEYS = (
    'WhEzm6QQQrks1hcsdN0Vrd56ZJmUyXJxTJFg6pn9', # OMF KEY. REPLACE WITH YOUR API KEY
    'Y8GMAFsqcPtxhjIa1qfNj5ILxN5DH5cjV3i6BeNE',
    'etg8hytwTYRf4CD0c4Vl9U7ACEQnQg6HV2Jf4E5W',
    'BNFaSCCwz5WkauwJe89Bn8FZldkcyda7bNwDK1ic',
    'L2e5lfH2VDvEm2WOh0dJmzQaehORDT8CfCotaOcf',
    '08USmh2H2cOeAuQ3sCCLgzd30giHjfkhvsicUPPf'
)

def run(inJSONPath, outputPath, api_key):
	"""
	Run the wrapped solver workflow and return its results or status.
	"""
	root_url = 'https://developer.nlr.gov/api/reopt'
	post_url = root_url + '/v2/job/?api_key=' + api_key
	results_url = root_url + '/v2/job/<run_uuid>/results/?api_key=' + api_key
	with open(inJSONPath) as f:
		post = json.load(f)
	response = requests.post(post_url, json=post)
	raise_if_unsuccessful(response, outputPath)
	#logger.log.info(f'Status code: {response.status_code} - url: {post_url}')
	run_id = json.loads(response.text)['run_uuid']
	response = results_poller.poller(url=results_url.replace('<run_uuid>', run_id))
	raise_if_unsuccessful(response, outputPath)
	response_json = json.loads(response.text)
	response_json['api_key'] = api_key
	with open(outputPath, 'w') as f:
		json.dump(response_json, f, indent=4)
	#logger.log.info("Saved results to {}".format(outputPath))


def runResilience(runID, outputPath, api_key):
	"""
	Run the resilience workflow and return its results.
	"""
	root_url = 'https://developer.nlr.gov/api/reopt'
	post_url = root_url + '/v2/outagesimjob/?api_key=' + api_key
	results_url = root_url + '/v2/job/<RUN_ID>/resilience_stats/?api_key=' + api_key
	response = requests.post(post_url, json={'run_uuid': runID, 'bau': False})
	raise_if_unsuccessful(response, outputPath)
	#logger.log.info(f'Status code: {response.status_code} - url: {post_url}')
	run_id = json.loads(response.text)['run_uuid']
	response = results_poller.rez_poller(url=results_url.replace('<RUN_ID>', run_id))
	response_json = json.loads(response.text)
	response_json['api_key'] = api_key
	raise_if_unsuccessful(response, outputPath)
	with open(outputPath, 'w') as f:
		json.dump(response_json, f, indent=4)
	#logger.log.info("Saved results to {}".format(outputPath))


def raise_if_unsuccessful(response, outputPath):
	'''
	Raise a custom exception if the response did not successfully complete. If the response only contains a "run_uuid" key, it was successful. If it
	contains other keys, it was unsuccessful

	:param response: a Requests response object
	:return: None
	'''
	response_json = json.loads(response.text)
	if response_json.get('messages') is not None and response_json.get('messages').get('error') is not None:
		if response_json['messages'].get('input_errors') is not None:
			#logger.log.error(f'Status code: {response.status_code} - url: {response.url}')
			#logger.log.error(f'Warning: unsuccessful response from {response.url}')
			#logger.log.error(f'{response_json["messages"]["error"]}: {response_json["messages"]["input_errors"]}')
			with open(outputPath, 'w') as f:
				json.dump(response_json, f, indent=4)
			raise Exception(f'{response_json["messages"]["error"]}: {response_json["messages"]["input_errors"]}')
		else:
			#logger.log.error(f'Status code: {response.status_code} - url: {response.url}')
			#logger.log.error(f'Warning: unsuccessful response from {response.url}')
			#logger.log.error(f'{response_json["messages"]["error"]}')
			with open(outputPath, 'w') as f:
				json.dump(response_json, f, indent=4)
			raise Exception(f'{response_json["messages"]["error"]}')
	if not response.ok:
		#logger.log.error(f'Status code: {response.status_code} - url: {response.url}')
		#logger.log.error(f'Warning: unsuccessful response from {response.url}')
		with open(outputPath, 'w') as f:
			json.dump(response_json, f, indent=4)
		raise Exception(response_json)


def _test():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	run('Scenario_POST40.json', 'results_S40.json', random.choice(REOPT_API_KEYS))
	with open('results_S40.json') as jsonFile:
		results = json.load(jsonFile)
	test_ID = results['outputs']['Scenario']['run_uuid']

	print("PV size_kw:", results['outputs']['Scenario']['Site']['PV']['size_kw'])
	print("Storage size_kw:", results['outputs']['Scenario']['Site']['Storage']['size_kw'])
	print("Storage size_kwh:", results['outputs']['Scenario']['Site']['Storage']['size_kwh'])
	# print("Wind size_kw:", results['outputs']['Scenario']['Site']['Wind']['size_kw'])
	print("Generator fuel_used_gal:", results['outputs']['Scenario']['Site']['Generator']['fuel_used_gal'])
	print("Generator fuel_used_gal_bau:", results['outputs']['Scenario']['Site']['Generator']['fuel_used_gal_bau'])
	print("Generator size_kw:", results['outputs']['Scenario']['Site']['Generator']['size_kw'])
	print("Generator average_yearly_energy_produced_kwh:", results['outputs']['Scenario']['Site']['Generator']['average_yearly_energy_produced_kwh'])
	print("Generator average_yearly_energy_exported_kwh:", results['outputs']['Scenario']['Site']['Generator']['average_yearly_energy_exported_kwh'])
	print("Generator existing_gen_total_fuel_cost_us_dollars:", results['outputs']['Scenario']['Site']['Generator']['existing_gen_total_fuel_cost_us_dollars'])
	#print("Generator year_one_emissions_lb_C02:", results['outputs']['Scenario']['Site']['Generator']['year_one_emissions_lb_C02'])
	#print("Generator year_one_emissions_bau_lb_C02:", results['outputs']['Scenario']['Site']['Generator']['year_one_emissions_bau_lb_C02'])
	print("npv_us_dollars:", results['outputs']['Scenario']['Site']['Financial']['npv_us_dollars'])
	print("initial_capital_costs:", results['outputs']['Scenario']['Site']['Financial']['initial_capital_costs'])
	# print("CHP size_kw:", results['outputs']['Scenario']['Site']['CHP']['size_kw'])
	# print("CHP year_one_fuel_used_mmbtu:", results['outputs']['Scenario']['Site']['CHP']['year_one_fuel_used_mmbtu'])
	# print("CHP year_one_electric_energy_produced_kwh:", results['outputs']['Scenario']['Site']['CHP']['year_one_electric_energy_produced_kwh'])

	runResilience(test_ID, 'resultsResilience_S40.json')


if __name__ == '__main__':
	_test()
