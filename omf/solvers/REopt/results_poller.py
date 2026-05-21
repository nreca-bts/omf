"""
Poll REopt API result endpoints until optimization jobs finish or fail.
"""
import json, time
import requests
from omf.solvers.REopt import logger


def poller(url, poll_interval=10):
    """
    Function for polling the REopt API Economic results URL until status is not "Optimizing..."

    :param url: results url to poll
    :param poll_interval: seconds
    :return: a Requests response object once status is not "Optimizing..."
    :rtype: Response
    """
    key_error_count = 0
    key_error_threshold = 4
    status = "Optimizing..."
    #logger.log.info("Polling {} for results with interval of {}s...".format(url, poll_interval))
    while True:
        response = requests.get(url=url)
        response_json = json.loads(response.text)
        try:
            status = response_json['outputs']['Scenario']['status']
        except KeyError:
            key_error_count += 1
            if key_error_count > key_error_threshold:
                #logger.log.info(f"KeyError count {key_error_count}: response_json['outputs']['Scenario'] did not contain a ['status'] key")
                #logger.log.info(f'Breaking polling loop due to KeyError count threshold of {key_error_threshold} exceeded.')
                #break
                raise Exception('A REopt financial scenario was successfully started, but the REopt API did not return the status of the scenario.')
        if status != "Optimizing...":
            break
        else:
            time.sleep(poll_interval)
    return response


def rez_poller(url, poll_interval=10):
    """
    Function for polling the REopt Resilience API results URL until status is not "Optimizing..."

    :param url: results url to poll
    :param poll_interval: seconds
        420 seconds / 10 seconds = 42 attempts
    :return: dictionary response (once status is not "Optimizing...")
    """
    key_error_count = 0
    key_error_threshold = 42
    status = ""
    #logger.log.info("Polling {} for results with interval of {}s...".format(url, poll_interval))
    while True:
        response = requests.get(url=url)
        response_json = json.loads(response.text)
        try:
            status = str(response_json['outage_sim_results'])
        except KeyError:
            key_error_count += 1
            if key_error_count > key_error_threshold:
                #logger.log.info(f"KeyError count {key_error_count}: resp_dict did not contain an ['outage_sim_results'] key")
                #logger.log.info(f'Breaking polling loop due to KeyError count threshold of {key_error_threshold} exceeded.')
                #break
                raise Exception('A REopt resilience scenario was successfully started, but the REopt API did not return the status of the scenario.')
        if status != "":
            break
        else:
            time.sleep(poll_interval)
    return response
