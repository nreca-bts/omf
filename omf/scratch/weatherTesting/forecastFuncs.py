import requests
import omf
from pandas import date_range
from datetime import datetime, timedelta
import json
_key_pirateweather = "xclxUibBDfg2pVwjHkfDBVVyMrFTTfc0"

def pirateWeatherForecast(days: int, lat, lon, units="si", api_key=_key_pirateweather) -> list:
	'''
	days: how many days ahead/behind current date will be looked. Artificially locked @ 10
	'''
	from pandas import date_range
	from datetime import datetime, timedelta

	# Want to check this better
	lat, lon = float(lat), float(lon)

	base_url = "https://api.pirateweather.net/forecast/"
	todays_date = datetime.now().date()
	if days < 0 or days > 10:
		raise Exception("pirateWeatherForecast(): days variable must be within range of 0 and 10")
	days_past = todays_date - timedelta(days=days)
	days_ahead = todays_date + timedelta(days=days)
	coords = '%0.2f,%0.2f' % (lat, lon)
	times = list(date_range(days_past, days_ahead))
	urls = ['https://timemachine.pirateweather.net/forecast/%s/%s,%s?exclude=daily&units=%s' % ( _key_pirateweather, coords, time.isoformat(), units ) for time in times]
	data = [requests.get(url) for url in urls]
	for i in enumerate(data):
		if i[1].status_code != 200:
			raise Exception(f" pirateWeatherForecast(): Pirate Weather API Request Failed :: Request Code: {i[1].status_code} :: Reason: {i[1].reason}\n Response Body: {i[1].text}")
	try:
		data = [i.json() for i in data]
	except:
		raise Exception("pirateWeatherForecast(): The response was not parsed as JSON successfully.")
	return data

# pirateWeatherForecast(3, 42, -73)

def weatherGridpointRequest(latitude: float, longitude: float) -> tuple:
	'''

	Converts Latitude and Longitude to api.weather.gov gridpoint system
	Used in newsWeatherForecast function
	Returns: Tuple of string (gridX, gridY)

	'''
	base_url = "https://api.weather.gov/points/"
	request_for_grid = base_url + f"{latitude},{longitude}"
	grid_data = requests.get(request_for_grid)
	if grid_data.status_code != 200:
		raise Exception(f"weatherGridpointRequest(): API request failed :: Request Code: {grid_data.status_code} :: Reason: {grid_data.reason}")
	grid_data_json = grid_data.json()
	gridX = grid_data_json["properties"]["gridX"]
	gridY = grid_data_json["properties"]["gridY"]
	if gridX == "null" or gridY == "null":
		print(f"weatherGridpointRequest(): gridX and/or gridY returned null. Lat/Long coordinates inputted are invalid")
		exit(1)
	gridCoords = (str(gridX), str(gridY))
	return gridCoords

	# if gridx and gridy are null it wasn't valid lat/long coordinates?

def newsWeatherForecast(latitude: float, longitude: float, interval="", nws_code=""):
	'''
		Pulls hourly data from the National Weather Service
		Docs: https://weather-gov.github.io/api/
		Forecast Formats: [forecast, forecastHourly, forecastGridData]
		* 6.5 days of forecast data is provided.
		* Timezone data is encoded in the response as UTC with offset. We strip it.
		* Temperature is in Fahrenheit
	'''

	import pandas as pd

	base_url = "https://api.weather.gov/gridpoints"
	gridCoords = weatherGridpointRequest(latitude=latitude, longitude=longitude)
	if interval.lower() == "hourly":
		request_url = f"{base_url}/{nws_code}/{gridCoords[0]},{gridCoords[1]}/forecast/hourly"
	elif interval.lower == "":
		request_url = f"{base_url}/{nws_code}/{gridCoords[0]},{gridCoords[1]}/forecast"
	else:
		print(f"newsWeatherForecast(): interval value inputted is not 'hourly' or '' - the only 2 accepted values")
	# print(f"request_url: {request_url}")
	response = requests.get(request_url)
	if response.status_code == 404:
		raise Exception(f"newsWeatherForecast(): API Request Failed. :: Dataset URL does not exist: {response.url}. Hint: Check coords/grid values")
	elif response.status_code != 200:
		raise Exception(f"newsWeatherForecast(): API request failed :: Request Code: {response.status_code} :: Reason: {response.reason}")
	else:
		json_response = json.loads(response.text)
		dict_list = []
		for item in json_response["properties"]["periods"]:
			item = {
					# Removing tz info from timestamp. This makes the strong assumption
					#  that NWS will always correctly provide data in the timezone of
					#  the station we're pulling from.
					"timestamp": pd.to_datetime(item["startTime"]).replace(tzinfo=None),
					"tempc": item["temperature"]
			}
			dict_list.append(item)
	df = pd.DataFrame(dict_list)
	return df

news_df = newsWeatherForecast(latitude=40.744308, longitude=-73.941856, interval="hourly", nws_code="LWX")
print(news_df.head)