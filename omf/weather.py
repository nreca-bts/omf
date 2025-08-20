'''
Pull weather data from various sources.
Source options include NOAA's USCRN, Iowa State University's METAR, and Weather Underground (currently deprecated).
'''


import os, csv, re, json, sys
from math import sqrt, exp, cos, radians
import numpy as np
from os.path import join as pJoin
import datetime as dt
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
import requests
from dateutil.parser import parse as parse_dt
from omf import feeder
import platform
import pandas as pd
from tempfile import mkdtemp
import pysolar
import pytz
import xml.etree.ElementTree as ET
import xmltodict
from pathlib import Path

omfDir = os.path.dirname(os.path.abspath(__file__))

#pirateweather key
_key_pirateweather = "xclxUibBDfg2pVwjHkfDBVVyMrFTTfc0"

def pullAsos(year, station, datatype):
	'''This model pulls hourly data for a specified year and ASOS station. 
	* ASOS is the Automated Surface Observing System, a network of about 900 
		weater stations, they collect data at hourly intervals, they're run by 
		NWS, FAA, and DOD, and there is data going back to 1901 in some sites.
	* AKA METAR data, which is the name of the format its stored in.
	* For ASOS station code see https://www.faa.gov/air_traffic/weather/asos/
	* For datatypes see bottom of https://mesonet.agron.iastate.edu/request/download.phtml
	* Note for USA stations (beginning with a K) you must NOT include the 'K' 
	'''
	url = ('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?'
		'station={}&data={}&year1={}&month1=1&day1=1&year2={}&month2=1&day2=1'
		'&tz=Etc%2FUTC&format=onlycomma&latlon=no&direct=no&report_type=1'
		'&report_type=2').format(station, datatype, year, int(year)+1)
	r = requests.get(url)
	assert r.status_code != 404, "Dataset URL does not exist. " + url
	data = [x.split(',') for x in r.text.splitlines()[1:]]
	verifiedData = [-9999.0] * 8760
	firstDT = dt.datetime(int(year), 1, 1)
	for r in data:
		if 'M' not in r:
			deltatime = parse_dt(r[1]) - firstDT
			verifiedData[int(deltatime.total_seconds()/3600)] = float(r[2])	
	return verifiedData

#is this used?
def pullAsosStations(filePath):
	"""Build a station list for the ASOS data. Put them in filePath with their details. """
	stations = []
	states = """AK AL AR AZ CA CO CT DE FL GA HI IA ID IL IN KS KY LA MA MD ME
	 MI MN MO MS MT NC ND NE NH NJ NM NV NY OH OK OR PA RI SC SD TN TX UT VA VT
	 WA WI WV WY"""
	networks = []
	for state in states.split():
		networks.append("%s_ASOS" % (state,))
	with open(filePath, 'w',  newline='') as csvfile:
		fieldnames = ['Station Id', 'Station Name', 'County', 'State', 'Latitude', 'Longitude', 'Elevation', 'Time Zone']
		csvwriter = csv.DictWriter(csvfile, delimiter=',', fieldnames=fieldnames)
		for network in networks:
			current = []
			current.append(network)
			uri = ("https://mesonet.agron.iastate.edu/"
			"geojson/network/%s.geojson") % (network,)
			with urlopen(uri) as f:
				jdict = json.load(f)
			#map attribute to entry in csv
			csvwriter.writeheader()
			for site in jdict['features']:
				currentSite = {}
				currentSite['Station Id'] = site['properties']['sid']
				currentSite['Station Name'] = site['properties']['sname']
				currentSite['County'] = site['properties']['county']
				currentSite['State'] = site['properties']['state']
				currentSite['Latitude'] = site['geometry']['coordinates'][0]
				currentSite['Longitude'] = site['geometry']['coordinates'][1]
				currentSite['Elevation'] = site['properties']['elevation']
				currentSite['Time Zone'] = site['properties']['tzname']
				csvwriter.writerow(currentSite)


def pullPirateWeather(year, lat, lon, datatype, units='si', api_key=_key_pirateweather, path = None):
	'''Returns hourly weather data from the PirateWeather API as array.

	* For more on the Pirate Weather API: https://docs.pirateweather.net/en/latest/API/
	
	* year, lat, lon: may be numerical or string
	* datatype: string, must be one of the available datatypes (case-sensitive)
	* api_key: string
	* units: string, either 'us' or 'si'
	* path: string, must be a path to a folder if provided.
		* if a path is provided, the data for all datatypes for the given year and location will be cached there as a csv.'''
	from pandas import date_range
	print("Pirate Weather is Running")
	lat, lon = float(lat), float(lon)
	int(year) # if year isn't castable... something's up
	coords = '%0.2f,%0.2f' % (lat, lon) # this gets us 11.1 km unc <https://gis.stackexchange.com/questions/8650/measuring-accuracy-of-latitude-and-longitude>
	if path:
		assert os.path.isdir(path), 'Path does not exist'
		filename = coords + "_" + str(year) + ".csv"
		filename = pJoin(path, filename)
		try:
			with open(filename, 'r', newline='') as csvfile:
				reader = csv.reader(csvfile)
				in_csv = [row for row in reader]
			index = in_csv[0].index(datatype)
		except IndexError:
			print('Requested datatype not present in cache, an attempt will be made to fetch from the API')
		except IOError:
			print('Cache not found, data will be fetched from the API')	
	# Now we begin the actual scraping. Behold: a convoluted way to get a list of days in a year
	times = list(date_range('{}-01-01'.format(year), '{}-12-31'.format(year)))
	#time.isoformat() has no tzinfo in this case, so it is parsed as local time
	urls = ['https://timemachine.pirateweather.net/forecast/%s/%s,%s?exclude=daily&units=%s' % ( api_key, coords, time.isoformat(), units ) for time in times]
	data = [requests.get(url) for url in urls]
	for i in range(len(data)):
		if data[i].status_code != 200:
			raise Exception(f"Pirate Weather Request Failed :: Request Code :: {data[i].status_code}")
	data = [i.json() for i in data]
	# print(data)
	#a fun little annoyance: let's de-unicode those strings
	#def ascii_me(obj):
	#	if isinstance(obj, unicode):
	#		return obj.encode('ascii','ignore')
	#	if isinstance(obj, list):
	#		return map(ascii_me, obj)
	#	if isinstance(obj, dict):
	#		new_dict = dict()
	#		for k, v in obj.iteritems():
	#			k = k.encode('ascii','ignore') if type(k) is type(u'') else k
	#			new_dict[k] = ascii_me(v)
	#		return new_dict
	#	else:
	#		return obj
	#data = ascii_me(data)
	out = []
	if path:
			# determine the columns from the first day of data
			columns = list(data[0]['hourly']['data'][0].keys())
			out_csv = [columns]
	# parse our json-dict
	for day in data:
		print(day)
		for hour in day['hourly']['data']:
			print(hour)
			if path:
				out_csv.append( [hour.get(key) for key in columns] )
			out.append(hour.get(datatype))
	if path:
		with open(filename, 'w', newline='') as csvfile:
			writer = csv.writer(csvfile)
			for row in out_csv:
				writer.writerow(row)
	return out


def pullUscrn(year, station, datatype):
	'''Returns hourly weather data from NOAA's quality-controlled USCRN dataset as array.
	* Documentation: https://www1.ncdc.noaa.gov/pub/data/uscrn/products/hourly02/README.txt
	* List of available stations: https://www1.ncdc.noaa.gov/pub/data/uscrn/products/hourly02'''
	url = ('https://www1.ncdc.noaa.gov/pub/data/uscrn/products/hourly02/{0}/'
		'CRNH0203-{0}-{1}.txt'.format(year, station))
	r = requests.get(url)
	assert r.status_code != 404, "Dataset URL does not exist. " + url 
	# Columns name and index (subtracted 1 from readme's Field #)
	datatypeDict = {
		"T_CALC": 8,
		"T_HR_AVG": 9,
		"T_MAX": 10,
		"T_MIN": 11,
		"P_CALC": 12,
		"SOLARAD": 13,
		"SOLARAD_MAX": 15,
		"SOLARAD_MIN": 17,
		"SUR_TEMP": 20,
		"SUR_TEMP_MAX": 22,
		"SUR_TEMP_MIN": 24,
		"RH_HR_AVG": 26,
		"SOIL_MOISTURE_5": 28,
		"SOIL_MOISTURE_10": 29,
		"SOIL_MOISTURE_20": 30,
		"SOIL_MOISTURE_50": 31,
		"SOIL_MOISTURE_100": 32,
		"SOIL_TEMP_5": 33,
		"SOIL_TEMP_10": 34,
		"SOIL_TEMP_20": 35,
		"SOIL_TEMP_50": 36,
		"SOIL_TEMP_100": 37
		}
	#IF datatype is "irradiance estimate", then run the diffuse/direct_seperator method 
	assert datatype in datatypeDict, "This datatype isn't listed in options!"
	datatypeID = datatypeDict[datatype]
	rawData = [float(x.split()[datatypeID]) for x in r.text.splitlines() if len(x) != 0]
	if datatype == "IRRADIENCE_DIFFUSE":
		#Now get diffuse component, write in place in data array
		diffuse = list(map(get_diffuse_solar_component, rawData))
		# #Subtract diffuse from raw to get direct component
		direct = list(map(lambda x, y: x-y,rawData, diffuse))
		direct_diffuse = list(zip(direct, diffuse))
		raw_diffuse = list(zip(rawData, diffuse))
		return raw_diffuse #direct_diffuse
	return rawData


def _pullWeatherWunderground(start, end, airport, workDir):
	'''	NOTE: WeatherUnderground moved behind a paywall but we'll keep this in case we get a license. 
	Download weather CSV data to workDir. 1 file for each day between start and 
	end (YYYY-MM-DD format). Location is set by airport (three letter airport code, e.g. DCA). '''
	# Parse start and end dates.
	start_dt = dt.datetime.strptime(start, "%Y-%m-%d")
	end_dt = dt.datetime.strptime(end, "%Y-%m-%d")
	# Calculate the number of days to fetch.
	num_days = (end_dt - start_dt).days
	work_day = start_dt
	# HACK: urllib proxy auto-detection crashes hard in Mac OS X, so force a dummy proxy that will then cause fallback to direct request.
	os.environ["dummy_proxy"] = "NONE"
	# Generate URLs and get data.
	for i in range(num_days):
		year = work_day.year
		month = work_day.month
		day = work_day.day
		address = "http://www.wunderground.com/history/airport/{}/{:d}/{:d}/{:d}/DailyHistory.html?format=1".format(airport, year, month, day)
		filename = pJoin(workDir,"weather_{}_{:d}_{:d}_{:d}.csv".format(airport, year, month, day))
		if os.path.isfile(filename):
			continue # We have the file already, don't re-download it.
		try:
			with urlopen(address) as f:
				data = str(f.read(), 'utf-8')
			with open(filename) as f:
				f.write(data)
			#f = urlretrieve(address, filename)
		except:
			print("ERROR: unable to get data from URL " + address)
			continue # Just try to grab the next one.
		work_day = work_day + dt.timedelta(days = 1) # Advance one day


def airportCodeToLatLon(airport):
	''' Airport three letter code -> lat/lon of that location. 
		Dataset: https://opendata.socrata.com/dataset/Airport-Codes-mapped-
			to-Latitude-Longitude-in-the-/rxrh-4cxm '''
	with open(pJoin(omfDir, 'static/Airports.csv'), newline='') as f:
		for m in list(csv.reader(f))[1:]:
			if m[0] == airport:
				return (m[1], m[2])
	print('Airport not found: ', airport)
	lat = float(input('Please enter latitude manually:'))
	lon = float(input('Please enter longitude manually:'))
	return (lat, lon)


def zipCodeToClimateName(zipCode):
	''' Given a zipcode, return the closest city for which there's weather data. 
	* This will give nearest data within state. If zip code is in NJ on
		border of NYC, Hoboken (07030) for example, it will return Newark
		instead of NYC.
	* Zip code lat/lon/city/state data taken from https://www.gaslampmedia.com
		/download-zip-code-latitude-longitude-city-state-county-csv/ '''
	assert isinstance(zipCode, str), "To prevent leading zero errors, input zipcode as string"
	zipCsvPath = pJoin(omfDir, "static", "zip_codes_altered.csv")
	# Find the state, city, lat, lon for given zipcode
	with open(zipCsvPath, 'r', newline='') as f:
		try:
			'''All zipcodes are unique. len(row) will be either 1 or 0. Error 
				would be raised by calling the zero index on an empty array.'''
			row = [r for r in list(csv.reader(f))[1:] if r[0] == zipCode][0]
		except:
			raise Exception("Data not available: " + zipCode)
		zipState = row[4]
		ziplatlon = row[1], row[2]
	# Collect data from every zipcode in state
	with open(zipCsvPath, 'r', newline='') as f:
		cityData = [r for r in csv.reader(f) if r[4] == zipState]
	# Collect all names of cities with data from state. Remove the state abbr. from beginning and '.tmy2' from end.
	citiesInState = [cn[3:-5] for cn in os.listdir(pJoin(omfDir, 'data', 'Climate')) if zipState == cn[:2]]
	# Approximate closest city with data to given zipcode
	foundCity, lowestDistance = None, float('inf')
	for cCity in citiesInState:
		for row in cityData:
			city = row[3].replace(' ', '_')
			if row[4].lower() == zipState.lower() and city.lower() == cCity.lower():
				# Using pyth on globe is not accurate. Consider updating w spherical distance function
				# E.g. Brick, NJ (08724) is closer to Newark, but this function recommends AC.
				climatelatlon = row[1], row[2]
				differenceLat = float(climatelatlon[0]) - float(ziplatlon[0])
				differenceLon = float(climatelatlon[1]) - float(ziplatlon[1])
				distance = differenceLat ** 2 + differenceLon ** 2
				if distance < lowestDistance: 
					lowestDistance = distance
					foundCity = cCity
	assert foundCity != None, "A city is spelled differently between two datasets. Please notify the OMF team."
	return '{}-{}'.format(zipState, foundCity)

########################
### aGosedWeather.py ###
########################


def attachHistoricalWeather(omd_path, year, station):
	"""
	Get USCRN data for a year and station, write it to a CSV, then calibrate the .omd to use the CSV.

	:param omd_path: the path to the .omd file to calibrate
	:type omd_path: str
	:param year: the year to get USCRN data for
	:type year: int
	:param station: the name of the USCRN station
	:type station: str
	"""
	csv_path = os.path.join(os.path.dirname(omd_path), "uscrn-weather-data.csv")
	temperature = USCRNDataType(8, -9999.0, flag_index=None, transformation_function=lambda x: round(_celsius_to_fahrenheit(x), 1))
	humidity = USCRNDataType(26, -9999, flag_index=27, transformation_function=lambda x: round(x / 100, 2))
	solar_dir = USCRNDataType(13, -99999, flag_index=14, transformation_function=lambda x: int(round(_watts_per_meter_sq_to_watts_per_ft_sq(x) * 0.75, 0)))
	solar_diff = USCRNDataType(13, -99999, flag_index=14, transformation_function=lambda x: int(round(_watts_per_meter_sq_to_watts_per_ft_sq(x) * 0.25, 0)))
	solar_global = USCRNDataType(13, -99999, flag_index=14, transformation_function=lambda x: int(round(_watts_per_meter_sq_to_watts_per_ft_sq(x), 0)))
	hourly_data_types = [temperature, humidity, solar_dir, solar_diff, solar_global]
	wind_speed = USCRNDataType(21, -99.00, flag_index=22, transformation_function=lambda x: round(x, 2))
	subhourly_data_types = [wind_speed]
	_write_USCRN_csv(csv_path, year, station, hourly_data_types, subhourly_data_types)
	start_date = dt.datetime(year, 1, 1)
	_calibrate_omd(start_date, omd_path, csv_path)


def _calibrate_omd(start_date, omd_path, csv_path):
	"""
	Modify an .omd file so that it will run in GridLAB-D with the CSV of USCRN weather data.

	:param start_date: the starting date of the GridLAB-D simulation
	:type start_date: datetime
	:param omd_path: an absolute path to the .omd file to modify
	:type omd_path: str
	:param csv_path: an absolute path to the CSV file that contains USCRN weather data
	:type csv_path: str
	"""
	with open(omd_path, 'r') as f:
		omd = json.load(f)
	tree = omd["tree"]
	# Delete all climate objects from the feeder. Also delete any csv_reader objects that are also named "WeatherReader"
	weather_reader_name = "WeatherReader"
	for key in list(tree.keys()):
		object_type = tree[key].get("object")	
		object_name = tree[key].get("name")
		if object_type == "climate" or (object_type == "csv_reader" and object_name == weather_reader_name):
			del tree[key]
	# Reinsert a new climate object and an associated csv_reader object
	oldMax = feeder.getMaxKey(tree)
	tree[oldMax + 1] = {'omftype':'module', 'argument':'tape'}
	tree[oldMax + 2] = {'omftype':'module', 'argument':'climate'}
	csv_name = os.path.basename(csv_path)
	tree[oldMax + 3] = {'object':'csv_reader', 'name': weather_reader_name, 'filename': csv_name}
	climate_name = "MyClimate"
	tree[oldMax + 4] = {'object':'climate', 'name':climate_name, 'reader': weather_reader_name, 'tmyfile': csv_name}
	# Set the time correctly. Modify certain objects in the feeder (e.g. recorder and clock)
	feeder.adjustTime(tree, 240, 'hours', '{}-{}-{}'.format(start_date.year, start_date.month, start_date.day)) 
	omd["tree"] = tree
	# Add the weather attachment
	with open(csv_path, 'r') as f:
		weatherString = f.read()
	if omd.get("attachments") is None:
		omd["attachments"] = {}
	omd['attachments'][csv_name] = weatherString
	with open(omd_path, 'w') as f:
		json.dump(omd, f, indent=4)


def _write_USCRN_csv(csv_path, year, station, hourly_data_types, subhourly_data_types):
	"""
	Get data as .txt files from the USCRN server, process the data, and write the processed data to a CSV.

	:param csv_path: the absolute path at which to write the CSV file
	:type csv_path: str
	:param year: the year to get USCRN data from
	:type year: int
	:param station: the station to get USCRN data from
	:type station: str
	"""
	# Get hourly data and process it
	hourly_rows = _get_USCRN_data(year, station, "hourly")
	if hourly_rows is None:
		raise Exception("Failed to get USCRN data for year \"{}\" and station \"{}\"".format(year, station))
	if hourly_data_types is not None:
		first_valid_row = _get_first_valid_row(hourly_rows, hourly_data_types)
		last_valid_row = _get_first_valid_row(hourly_rows, hourly_data_types, reverse=True)
		if first_valid_row is None or last_valid_row is None:
			raise ValueError("Relevant hourly data values are missing from the USCRN data for year: \"{}\" and station: \"{}\"".format(year, station))
		hourly_processed_data = _extract_data(first_valid_row, last_valid_row, hourly_rows, hourly_data_types, is_subhourly_data=False)
	else:
		hourly_processed_data = None
	# Get subhourly data and process it
	subhourly_rows = _get_USCRN_data(year, station, "subhourly")
	if subhourly_rows is None:
		raise ValueError("Failed to get USCRN data for year \"{}\" and station \"{}\"".format(year, station))
	if subhourly_data_types is not None:
		first_valid_row = _get_first_valid_row(subhourly_rows, subhourly_data_types)
		last_valid_row = _get_first_valid_row(subhourly_rows, subhourly_data_types, reverse=True)
		if first_valid_row is None or last_valid_row is None:
			raise ValueError("Relevant subhourly data values are missing from the USCRN data for year: \"{}\" and station: \"{}\"".format(year, station))
		subhourly_processed_data = _extract_data(first_valid_row, last_valid_row, subhourly_rows, subhourly_data_types, is_subhourly_data=True)
	else:
		subhourly_processed_data = None
	# Merge the hourly and subhourly data
	if hourly_processed_data is not None and subhourly_processed_data is not None:
		all_data = _merge_hourly_subhourly(hourly_processed_data, subhourly_processed_data, 1)
	else:
		if hourly_processed_data is not None:
			all_data = hourly_processed_data
		elif subhourly_processed_data is not None:
			all_data = subhourly_processed_data
		else:
			raise ValueError('There was no processed data to write to the CSV')
	# Write the CSV
	with open(csv_path, 'w', newline='') as f:
		writer = csv.writer(f)
		writer.writerows(all_data)


def _get_USCRN_data(year, station, frequency):
	"""Get a .txt file from the USCRN server and return the data as a list of lists."""
	url = "https://www1.ncdc.noaa.gov/pub/data/uscrn/products/"
	if frequency == "hourly":
		url += "hourly02/{year}/CRNH0203-{year}-{station}.txt".format(year=year, station=station)
	elif frequency == "subhourly":
		url += "subhourly01/{year}/CRNS0101-05-{year}-{station}.txt".format(year=year, station=station)
	else:
		raise Exception("Please specify a 'hourly' or 'subhourly' frequency.")
	r = requests.get(url)
	if r.status_code == 404:
		return
	return [re.split("\s+", line) for line in r.text.splitlines()]


def _str_to_num(data):
	"""Convert a string to its int or float equivalent."""
	if isinstance(data, str):
		if _get_precision(data) == 0:
			return int(data)
		return float(data)
	return data


def _get_precision(data):
	"""Get the decimal precision of a number as an int."""
	if not isinstance(data, str):
		data = str(data)
	if data.find(".") == -1:
		return 0
	return len(re.split("[.]", data)[1])


def _get_processed_row(data_types, row):
	"""
	Extract the datum for each USCRNDataType from the row of raw data into a new row.

	The ordering of the USCRNDataTypes in the data_types array determines the final ordering in the written CSV.

	:param data_types: a list of USCRNDataType objects
	:type data_types: list
	:param row: a row of raw data from the USCRN .txt file
	:type row: list
	:returns: a subset of the raw data from the USCRN .txt file
	:rtype: list
	"""
	processed_row = []
	for d_type in data_types:
		processed_row.append(d_type._get_value(row))
	return processed_row


def _add_row_to_hourly_avg(row, hourly_avg):
	"""
	Add the values from a row of subhourly data into the row that represents the hourly average of the subhourly measurements.

	We need this function because not all data is represented as numbers, so we have to try-except the adding operation.

	:param row: a row of data that contains subhourly measurements. There are 12 subhourly measurements taken per hour
	:type row: list
	:param hourly_avg: a row of data that contains the sum of 12 subhourly measurements for an hour
	:type hourly_avg: list
	"""
	for j in range(len(row)):
		val = row[j]
		try:
			val = _str_to_num(val)
			hourly_avg[j] += val
		except:
			hourly_avg[j] = val


def _get_first_valid_row(rows, data_types, reverse=False):
	"""
	Iterate over the USCRN .txt file represented as a list of lists and return the first row that has all valid data for the given USCRNDataTypes.

	:param rows: a list of lists that represents the USCRN .txt file
	:type rows: list
	:param data_types: the USCRNDataTypes to use to validate each row
	:type data_types: list
	:param reverse: determines whether to parse from the beginning to end of the .txt file or from the end to beginning
	:type reverse: bool
	:return: a row of data that has all valid values for the given USCRNDataTypes
	:rtype: list
	"""
	#  Don't return a composite row because it's possible that a composite row would have values that don't make any sense together (e.g. 0 relative
	#  humidity and 12 inches of precipitation, each pulled from different datetimes and merged into a single row)
	if reverse:
		rows = reversed(rows)
	for row in rows:
		valid = True
		for d_type in data_types:
			if not d_type._is_valid(row):
				valid = False	
		if valid:
			return row


def _extract_data(first_valid_row, last_valid_row, rows, data_types, is_subhourly_data=False):
	"""
	Extract the desired columns of data from the USCRN .txt file that is represented as a list of lists.

	:param first_valid_row: a row of that contains all valid data values. May or may not be a row from the .txt file that is being parsed
	:type first_valid_row: list
	:param last_valid_row: a row that contains all valid data values. May or may not be a row from the .txt file that is being parsed
	:type last_valid_row: list
	:param rows: the USCRN .txt file represented as a list of lists
	:type rows: list
	:param data_types: a list of USCRNDataTypes that will be used to parse the the USCRN .txt file
	:type data_types: list
	:param is_subhourly_data: whether or not the .txt file that is being parsed is hourly or subhourly data.
	:type is_subhourly_data: bool
	:return: a subset of the data from the original USCRN .txt file that has had erronous data values corrected
	:rtype: list
	"""
	most_recent_valid_row = first_valid_row
	processed_data = []
	if is_subhourly_data:
		hourly_avg = [0] * len(rows[0])
	for i in range(len(rows)):
		row = rows[i]
		for d_type in data_types:
			if not d_type._is_valid(row):
				end_row_index, next_valid_value = d_type._get_next_valid_value(rows, i)
				if end_row_index is None:
					end_row_index = len(rows) - 1
					next_valid_value = _str_to_num(last_valid_row[d_type.data_index])
				d_type._correct_data(rows, i, end_row_index - 1, _str_to_num(most_recent_valid_row[d_type.data_index]), next_valid_value)
		most_recent_valid_row = row
		if is_subhourly_data:
			_add_row_to_hourly_avg(row, hourly_avg)
			if (i + 1) % 12 == 0:
				for j in range(len(row)):
					try:
						hourly_avg[j] = hourly_avg[j] / 12
					except:
						pass
				processed_data.append(_get_processed_row(data_types, hourly_avg))
				hourly_avg = [0] * len(row)
		else:
			processed_data.append(_get_processed_row(data_types, row))
	return processed_data


def _watts_per_meter_sq_to_watts_per_ft_sq(w_m_sq):
	"""Convert a W/m^2 measurements to a W/ft^2 measurement."""
	if isinstance(w_m_sq, str):
		w_m_sq = _str_to_num(w_m_sq)
	return (w_m_sq / ((1 / .3048) ** 2))


def _celsius_to_fahrenheit(c):
	"""Convert a celsius measurement to a fahrenheit measurement."""
	if isinstance(c, str):
		c = _str_to_num(c)
	return c * 9 / 5 + 32


def _merge_hourly_subhourly(hourly, subhourly, insert_idx):
	"""
	Merge the hourly and subhourly USCRN data into a single list of lists and add datetimes and add a header row for GridLAB-D. 

	:param hourly: the list of lists of hourly data
	:type hourly: list
	:param subhourly: the list of lists of averaged subhourly data
	:type subhourly: list
	:param insert_idx: the column index of the hourly data within which to insert the subhourly data
	:type insert_idx: int
	:return: a single merged list of lists
	:rtype: list
	"""
	assert len(hourly) == len(subhourly)
	assert len(hourly[0]) > 0 and len(subhourly[0]) > 0
	# Add headers
	merged_rows = [
		["temperature", "wind_speed", "humidity", "solar_dir", "solar_diff", "solar_global"]
	]
	start_date = dt.datetime(2000, 1, 1, 0, 0, 0) # arbitrary datetime, this could be any year
	hour = dt.timedelta(hours=1)
	for i in range(len(hourly)):
		dt = start_date + hour * i
		gridlabd_date = '{}:{}:{}:{}:{}'.format(dt.month, dt.day, dt.hour, dt.minute, dt.second)
		row = [gridlabd_date]
		for j in range(len(hourly[i])):
			if insert_idx == j:
				row.extend(subhourly[i])
			row.append(hourly[i][j])			
		merged_rows.append(row)
	return merged_rows


class USCRNDataType(object):
	"""
	Each instance of this class represents a particular column of data that we want to parse, validate, and retrieve from the .txt file. The
	programmer need only create instances of this class, append them to a list, and pass that list to the _extract_data() function that is in this
	module. The programmer shouldn't need to use any of the methods in the class directly. Due to the behavior of _get_processed_rows() that is called
	within _extract_data(), the ordering of the USCRNDataTypes inside of the list that is passed to _extract_data() will determine the ordering of the CSV
	columns.
	"""

	def __init__(self, data_index, missing_data_value, flag_index=None, transformation_function=None):
		"""
		Set up an object that encapsulates the validation and data retrieval logic that is needed to parse a .txt file from USCRN into a usable CSV for
		GridLAB-D.
		
		:param data_index: the 0-indexed column in the USCRN .txt file where the data for this data type is written
		:type data_index: int
		:param missing_data_value: the int or float used by USCRN to indicate that a value is missing and was not propery recorded in the .txt file
		:type missing_data_value: int or float
		:flag_index: the 0-indexed column in the USCRN .txt file where the quality control flag for this data type is recorded. Not all data types
			have a quality control flag
		:type flag_index: int
		:param transformation_function: a function that should be applied to each datum that is parsed from the .txt file before it is written to the
			CSV file
		:type transformation_function: function
		"""
		self.data_index = int(data_index)
		if isinstance(missing_data_value, str):
			missing_data_value = _str_to_num(missing_data_value)
		self.missing_data_value = missing_data_value
		if flag_index is not None:
			flag_index = int(flag_index)
		self.flag_index = flag_index
		self.transformation_function = transformation_function

	def _is_valid(self, row):
		"""
		Return True if the row has a valid datum value for this USCRNDataType, otherwise False.

		:param row: a row of data from the USCRN .txt file
		:rtype: bool
		"""
		if _str_to_num(row[self.data_index]) == self.missing_data_value:
			return False
		if self.flag_index is not None and _str_to_num(row[self.flag_index]) != 0:
			return False
		return True

	def _get_next_valid_value(self, rows, start_row_idx):
		"""
		Return the next valid value for this USCRNDataType and the row index at which is was found.

		Parse the list of rows and find the closest row after or including the current row that contains a valid datum for this USCRNDataType, then
		return that datum and its row index.

		:param rows: the USCRN .txt file represented as a list of lists
		:param start_row_idx: the index of the row that we want to start looking for a valid value for this USCRNDataType.
		:rtype: tuple
		"""
		for i in range(start_row_idx, len(rows)):
			row = rows[i]
			if self._is_valid(row):
				return (i, _str_to_num(row[self.data_index]))
		return (None, None)

	def _correct_data(self, rows, start_row_idx, end_row_idx, initial_val, final_val):
		"""
		Parse the rows specified by the starting and ending row indexes, and modify the datum corresponding to this USCRNDataType in each row.

		The datum in each row is modified according to a linear interpolation between the initial_val and final_val. start_row_idx and end_row_idx are
		both inclusive of modification.
		:param rows: a list of lists that represents the USCRN .txt file
		:param start_row_idx: the index of the first row to start modifying data
		:type start_row_idx: int
		:param end_row_idx: the index of the last row to modify data
		:type end_row_idx: int
		:param initial_val: the starting value of the linear interpolation
		:param final_val: the final value of the linear interpolation
		"""
		start_row_idx = int(start_row_idx)
		end_row_idx = int(end_row_idx)
		if type(initial_val) is str:
			initial_val = _str_to_num(initial_val)
		if type(final_val) is str:
			final_val = _str_to_num(final_val)
		precision = _get_precision(initial_val)
		increment = (1.0 * final_val - initial_val) / (end_row_idx - start_row_idx + 2)
		count = 1
		for i in range(start_row_idx, end_row_idx + 1):
			row = rows[i]
			val = round((initial_val + increment * count), precision)
			if precision == 0:
				val = int(val)
			row[self.data_index] = val
			if self.flag_index is not None:
				row[self.flag_index] = 0
			count += 1

	def _get_value(self, row):
		"""
		Return the datum stored in the USCRN .txt file for this USCRNDataType at the specified row.

		:param row: a list of data
		:rtype: int or float
		"""
		value = row[self.data_index]
		if isinstance(value, str):
			value = _str_to_num(value)
		if self.transformation_function is not None:
			return self.transformation_function(value)
		return value

def lat_lon_diff(lat1, lat2, lon1, lon2):
	'''Get the euclidean distance between two sets of latlon coordinates'''
	dist = sqrt((float(lat1) - float(lat2))**2 + (float(lon1) - float(lon2))**2)
	return dist

# NSRDB
def nsrbd_latlon_to_wkt(longitude, latitude):
	if latitude < -90 or latitude > 90:
		raise ValueError('invalid latitude')
	elif longitude < -180 or longitude > 180:
		raise ValueError('invalid longitude')  
	return 'POINT({} {})'.format(longitude, latitude)

def get_nrsdb_data(data_set, longitude, latitude, year, api_key, utc='true', leap_day='false', email='admin@omf.coop', interval=None, filename=None):
	'''Create nrsdb factory and execute query. Optional output to file or return the response object.'''
	print("NRSDB found")
	base_url = 'https://developer.nrel.gov'
	request_url = ""
	params = {}
	params['api_key'] = api_key
	params['wkt'] = nsrbd_latlon_to_wkt(latitude=latitude, longitude=longitude)
	params['names'] = str(year)
	params['utc'] = utc
	params['leap_day'] = leap_day
	params['email'] = email

	# Physical Solar Model
	if data_set == 'psm':
		params["interval"] = interval
		request_url = os.path.join( base_url, 'api/solar/nsrdb_psm3_download.csv' )
	# physical solar model v3 tsm
	elif data_set == 'psm_tmy':
		request_url = os.path.join( base_url, 'api/nsrdb_api/solar/nsrdb_psm3_tmy_download.csv' )
	# SUNY International
	elif data_set == 'suny':
		request_url = os.path.join( base_url, 'api/solar/suny_india_download.csv' )
	# spectral tmy
	elif data_set == 'spectral_tmy':
		request_url = os.path.join( base_url,' api/nsrdb_api/solar/spectral_tmy_india_download.csv' )
	data = requests.get( url=request_url, params=params)

	if data.status_code != 200:
		# This means something went wrong.
		raise Exception(f'status code: {data.status_code} ' + data.text)
	csv_lines = [line.decode() for line in data.iter_lines()]
	reader = csv.reader(csv_lines, delimiter=',')
	if filename is not None:
		with open(filename, 'w', newline='') as csvfile:
			for i in reader:
				csvwriter = csv.writer(csvfile, delimiter=',')
				csvwriter.writerow(i)
		return data
	else:
		#Transform data, and resubmit in friendly format for frontend
		data = pd.DataFrame(reader)
		colNames = (data.iloc[2][:].values)
		print(data)
		data.rename(columns={key:val for key, val in enumerate(colNames)}, inplace=True)
		#Maybe change depending on what's easy/flexible but this gives good display
		return data


SURFRAD_COLUMNS = [
    'year', 'jday', 'month', 'day', 'hour', 'minute', 'dt', 'zen',
    'dw_solar', 'dw_solar_flag', 'uw_solar', 'uw_solar_flag', 'direct_n',
    'direct_n_flag', 'diffuse', 'diffuse_flag', 'dw_ir', 'dw_ir_flag',
    'dw_casetemp', 'dw_casetemp_flag', 'dw_dometemp', 'dw_dometemp_flag',
    'uw_ir', 'uw_ir_flag', 'uw_casetemp', 'uw_casetemp_flag', 'uw_dometemp',
    'uw_dometemp_flag', 'uvb', 'uvb_flag', 'par', 'par_flag', 'netsolar',
    'netsolar_flag', 'netir', 'netir_flag', 'totalnet', 'totalnet_flag',
    'temp', 'temp_flag', 'rh', 'rh_flag', 'windspd', 'windspd_flag',
    'winddir', 'winddir_flag', 'pressure', 'pressure_flag']

def getRadiationYears(radiation_type, site, year):
	'''Pull solard or surfrad data and aggregate into a year. '''
	print("getRadiationRunning~!!!!!!!**********")
	URL = 'ftp://aftp.cmdl.noaa.gov/data/radiation/{}/{}/{}/'.format(radiation_type, site, year)
	#FILE = 'tbl19001.dat' - example
	# Get directory contents.
	dirReq = Request(URL)
	with urlopen(dirReq) as f:
		text = f.read()
	dirLines = [bytes_.decode() for bytes_ in text.split(b'\r\n')]
	allFileNames = [x[56:] for x in dirLines if x!='']
	accum = []
	for fName in allFileNames:
		req = Request(URL + fName)
		with urlopen(req) as f:
			page = f.read()
		lines = [bytes_.decode() for bytes_ in page.split(b'\n')]
		siteName = lines[0]
		latLonVersion = lines[1].split()
		data = [x.split() for x in lines[2:]]
		minuteIntervals = ['0']
		hourlyReads = [x for x in data if len(x) >= 5 and x[5] in minuteIntervals]
		hourlyReadsSub = [{'col{}'.format(c): row[c] for c in range(len(row))} for row in hourlyReads]
		accum.extend(hourlyReadsSub)
		print('processed file {}'.format(fName))
	return accum

def create_tsv(data, radiation_type, site, year):
	'''Create tsv file from dict. '''
	column_count = len(data[0])
	with open('{}-{}-{}.tsv'.format(radiation_type, site, year), 'w', newline='') as f:
		output = csv.DictWriter(f, fieldnames=['col{}'.format(x) for x in range(column_count)], delimiter='\t')
		for item in data:
			output.writerow(item)

def get_radiation_data(radiation_type, site, year, out_file=None):
	print("radiation found!")
	'''Get solard or surfrad data. Optional export to csv with out_file option
		Data is returned in a list w/ ~8760 elements. Each element is a dictionary
		with ~47 keys value pairs. 
	'''
	allYears = getRadiationYears(radiation_type, site, year)
	if out_file is not None:
		create_tsv(allYears, radiation_type, site, year)
	else:
		df= pd.DataFrame(allYears)
		df.columns = SURFRAD_COLUMNS
		# return allYears
		return df

####### GHI/DHI/DNI Estimator Code Below #######
"""
GHI/DHI/DNI Estimator Code by:
Tuomas Talvitie 2020
tpt5cu@virginia.edu

Original Code at 

https://github.com/tpt5cu/solarIrradiancePredictor

"""


Station_Dict = {
	"AK_Cordova_14_ESE":(60.473, -145.35,'US/Alaska'),
	"AK_Deadhorse_3_S":(70.161,-148.46,'US/Alaska'),
	"AK_Denali_27_N":(63.451,-150.87,'US/Alaska'),
	"AK_Fairbanks_11_NE":(64.973,-147.51,'US/Alaska'),
	"AK_Glennallen_64_N":(63.029,-145.50,'US/Alaska'),
	"AK_Gustavus_2_NE":(58.429,-135.69,'US/Alaska'),
	"AK_Ivotuk_1_NNE":(68.484,-155.75,'US/Alaska'),
	"AK_Kenai_29_ENE":(60.723,-150.44,'US/Alaska'),
	"AK_King_Salmon_42_SE":(58.207,-155.92,'US/Alaska'),
	"AK_Metlakatla_6_S":(55.045,-131.58,'US/Alaska'),
	"AK_Port_Alsworth_1_SW":(60.195,-154.31,'US/Alaska'),
	"AK_Red_Dog_Mine_3_SSW":(68.027,-162.92,'US/Alaska'),
	"AK_Ruby_44_ESE":(64.501,-154.12,'US/Alaska'),
	"AK_Sand_Point_1_ENE":(55.347,-160.46,'US/Alaska'),
	"AK_Selawik_28_E":(66.561,-159.00,'US/Alaska'),
	"AK_Sitka_1_NE":(57.057,-135.32,'US/Alaska'),
	"AK_St._Paul_4_NE":(57.157,-170.21,'US/Alaska'),
	"AK_Tok_70_SE":(62.736,-141.20,'US/Alaska'),
	"AK_Toolik_Lake_5_ENE":(68.648,-149.39,'US/Alaska'),
	"AK_Yakutat_3_SSE":(59.508,-139.68,'US/Alaska'),
	"AL_Brewton_3_NNE":(31.144,-87.05,'US/Central'),
	"AL_Clanton_2_NE":(32.851,-86.61,'US/Central'),
	"AL_Courtland_2_WSW":(34.660,-87.34,'US/Central'),
	"AL_Cullman_3_ENE":(34.195,-86.79,'US/Central'),
	"AL_Fairhope_3_NE":(30.548,-87.87,'US/Central'),
	"AL_Gadsden_19_N":(34.285,-85.96,'US/Central'),
	"AL_Gainesville_2_NE":(32.836,-88.13,'US/Central'),
	"AL_Greensboro_2_WNW":(32.716,-87.62,'US/Central'),
	"AL_Highland_Home_2_S":(31.915,-86.31,'US/Central'),
	"AL_Muscle_Shoals_2_N":(34.772,-87.64,'US/Central'),
	"AL_Northport_2_S":(33.212,-87.59,'US/Central'),
	"AL_Russellville_4_SSE":(34.453,-87.71,'US/Central'),
	"AL_Scottsboro_2_NE":(34.693,-86.00,'US/Central'),
	"AL_Selma_6_SSE":(32.456,-87.24,'US/Central'),
	"AL_Selma_13_WNW":(32.335,-86.97,'US/Central'),
	"AL_Talladega_10_NNE":(33.571,-86.05,'US/Central'),
	"AL_Thomasville_2_S":(31.881,-87.73,'US/Central'),
	"AL_Troy_2_W":(31.789,-86.00,'US/Central'),
	"AL_Valley_Head_1_SSW":(34.565,-85.61,'US/Central'),
	"AR_Batesville_8_WNW":(35.820,-91.78,'US/Central'),
	"AZ_Elgin_5_S":(31.590,-110.50,'US/Mountain'),
	"AZ_Tucson_11_W":(32.239,-111.16,'US/Mountain'),
	"AZ_Williams_35_NNW":(35.755,-112.33,'US/Mountain'),
	"AZ_Yuma_27_ENE":(32.834,-114.18,'US/Mountain'),
	"CA_Bodega_6_WSW":(38.320,-123.07,'US/Pacific'),
	"CA_Fallbrook_5_NE":(33.438,-117.19,'US/Pacific'),
	"CA_Merced_23_WSW":(37.237,-120.88,'US/Pacific'),
	"CA_Redding_12_WNW":(40.650,-122.60,'US/Pacific'),
	"CA_Santa_Barbara_11_W":(34.413,-119.87,'US/Pacific'),
	"CA_Stovepipe_Wells_1_SW":(36.601,-117.14,'US/Pacific'),
	"CA_Yosemite_Village_12_W":(37.759,-119.82,'US/Pacific'),
	"CO_Boulder_14_W":(40.035,-105.54,'US/Mountain'),
	"CO_Cortez_8_SE":(37.255,-108.50,'US/Mountain'),
	"CO_Dinosaur_2_E":(40.244,-108.96,'US/Mountain'),
	"CO_La_Junta_17_WSW":(37.863,-103.82,'US/Mountain'),
	"CO_Montrose_11_ENE":(38.543,-107.69,'US/Mountain'),
	"CO_Nunn_7_NNE":(40.806,-104.75,'US/Mountain'),
	"FL_Everglades_City_5_NE":(25.899,-81.31,'US/Eastern'),
	"FL_Sebring_23_SSE":(27.152,-81.36,'US/Eastern'),
	"FL_Titusville_7_E":(28.615,-80.69,'US/Eastern'),
	"GA_Brunswick_23_S":(30.807,-81.45,'US/Eastern'),
	"GA_Newton_8_W":(31.312,-84.47,'US/Eastern'),
	"GA_Newton_11_SW":(31.192,-84.44,'US/Eastern'),
	"GA_Watkinsville_5_SSE":(33.783,-83.38,'US/Eastern'),
	"HI_Hilo_5_S":(None, None,None),
	"HI_Mauna_Loa_5_NNE":(None,None,None),
	"IA_Des_Moines_17_E":(41.556,-93.28,'US/Central'),
	"ID_Arco_17_SW":(43.461,-113.55,'US/Mountain'),
	"ID_Murphy_10_W":(43.204,-116.75, 'US/Mountain'),
	"IL_Champaign_9_SW":(40.052,-88.37,'US/Central'),
	"IL_Shabbona_5_NNE":(41.842,-88.85, 'US/Central'),
	"IN_Bedford_5_WNW":(38.888,-86.5, 'US/Central'),
	"KS_Manhattan_6_SSW":(39.102,-96.61, 'US/Central'),
	"KS_Oakley_19_SSW":(38.870,-100.96, 'US/Central'),
	"KY_Bowling_Green_21_NNE":(37.250,-86.23,'US/Eastern'),
	"KY_Versailles_3_NNW":(38.094,-84.74,'US/Eastern'),
	"LA_Lafayette_13_SE":(30.091,-91.87,'US/Central'),
	"LA_Monroe_26_N":(32.883,-92.11,'US/Central'),
	"ME_Limestone_4_NNW":(46.960,-67.88,'US/Eastern'),
	"ME_Old_Town_2_W":(44.928,-68.70, 'US/Eastern'),
	"MI_Chatham_1_SE":(46.334,-86.92,'US/Michigan'),
	"MI_Gaylord_9_SSW":(46.334,-86.92, 'US/Michigan'),
	"MN_Goodridge_12_NNW":(48.305,-95.87,'US/Central'),
	"MN_Sandstone_6_W":(46.113,-92.99, 'US/Central'),
	"MO_Chillicothe_22_ENE":(39.866,-93.14,'US/Central'),
	"MO_Joplin_24_N":(37.427,-94.58,'US/Central'),
	"MO_Salem_10_W":(37.634,-91.72, 'US/Central'),
	"MS_Holly_Springs_4_N":(34.822,-89.43, 'US/Central'),
	"MS_Newton_5_ENE":(32.337,-89.07, 'US/Central'),
	"MT_Dillon_18_WSW":(45.158,-113.00, 'US/Mountain'),
	"MT_Lewistown_42_WSW":(46.884,-110.28,'US/Mountain'),
	"MT_St._Mary_1_SSW":(48.741,-113.43,'US/Mountain'),
	"MT_Wolf_Point_29_ENE":(48.308,-105.10,'US/Mountain'),
	"MT_Wolf_Point_34_NE":(48.488,-105.20,'US/Mountain'),
	"NC_Asheville_8_SSW":(35.494,-82.61,'US/Eastern'),
	"NC_Asheville_13_S":(35.418,-82.55,'US/Eastern'),
	"NC_Durham_11_W":(35.970,-79.09,'US/Eastern'),
	"ND_Jamestown_38_WSW":(46.770,-99.47, 'US/Central'),
	"ND_Medora_7_E":(46.894,-103.37,'US/Central'),
	"ND_Northgate_5_ESE":(48.967,-102.17,'US/Central'),
	"NE_Harrison_20_SSE":(42.424,-103.73,'US/Eastern'),
	"NE_Lincoln_8_ENE":(40.848,-96.56,'US/Eastern'),
	"NE_Lincoln_11_SW":(40.695,-96.85,'US/Eastern'),
	"NE_Whitman_5_ENE":(42.067,-101.44,'US/Eastern'),
	"NH_Durham_2_N":(43.171,-70.92,'US/Eastern'),
	"NH_Durham_2_SSW":(43.108,-70.94,'US/Eastern'),
	"NM_Las_Cruces_20_N":(32.613,-106.74,'US/Mountain'),
	"NM_Los_Alamos_13_W":(35.858,-106.52,'US/Mountain'),
	"NM_Socorro_20_N":(34.355,-106.88,'US/Mountain'),
	"NV_Baker_5_W":(39.011,-114.20, 'US/Pacific'),
	"NV_Denio_52_WSW":(41.848,-119.63,'US/Pacific'),
	"NV_Mercury_3_SSW":(36.623,-116.02,'US/Pacific'),
	"NY_Ithaca_13_E":(42.440,-76.24,'US/Eastern'),
	"NY_Millbrook_3_W":(42.440,-76.24,'US/Eastern'),
	"OH_Wooster_3_SSE":(40.763,-81.91, 'US/Eastern'),
	"OK_Goodwell_2_E":(36.599,-101.59, 'US/Central'),
	"OK_Goodwell_2_SE":(36.568,-101.60,'US/Central'),
	"OK_Stillwater_2_W":(36.118,-97.09,'US/Central'),
	"OK_Stillwater_5_WNW":(36.134,-97.10,'US/Central'),
	"ON_Egbert_1_W":(44.232,-79.78, 'US/Eastern'),
	"OR_Coos_Bay_8_SW":(43.271,-124.31, 'US/Pacific'),
	"OR_Corvallis_10_SSW":(44.418,-123.32,'US/Pacific'),
	"OR_John_Day_35_WNW":(44.555,-119.64,'US/Pacific'),
	"OR_Riley_10_WSW":(43.471,-119.69,'US/Pacific'),
	"PA_Avondale_2_N":(39.859,-75.78,'US/Eastern'),
	"RI_Kingston_1_NW":(41.490,-71.54,'US/Eastern'),
	"RI_Kingston_1_W":(41.478,-71.54,'US/Eastern'),
	"SA_Tiksi_4_SSE":(None,None,None),
	"SC_Blackville_3_W":(33.355,-81.32,'US/Eastern'),
	"SC_McClellanville_7_NE":(33.153,-79.36,'US/Eastern'),
	"SD_Aberdeen_35_WNW":(45.711,-99.12, 'US/Central'),
	"SD_Buffalo_13_ESE":(45.515,-103.30,'US/Central'),
	"SD_Pierre_24_S":(44.019,-100.35,'US/Central'),
	"SD_Sioux_Falls_14_NNE":(43.734,-96.62,'US/Central'),
	"TN_Crossville_7_NW":(36.013,-85.13,'US/Eastern'),
	"TX_Austin_33_NW":(30.621,-98.08,'US/Central'),
	"TX_Bronte_11_NNE":(32.040,-100.24,'US/Central'),
	"TX_Edinburg_17_NNE":(26.525,-98.06,'US/Central'),
	"TX_Monahans_6_ENE":(31.621,-102.80,'US/Central'),
	"TX_Muleshoe_19_S":(33.955,-102.77,'US/Central'),
	"TX_Palestine_6_WNW":(31.779,-95.72,'US/Central'),
	"TX_Panther_Junction_2_N":(29.348,-103.20,'US/Central'),
	"TX_Port_Aransas_32_NNE":(28.304,-96.82,'US/Central'),
	"UT_Brigham_City_28_WNW":(41.616,-112.54,'US/Mountain'),
	"UT_Torrey_7_E":(38.302,-111.29, 'US/Mountain'),
	"VA_Cape_Charles_5_ENE":(37.290,-75.92, 'US/Eastern'),
	"VA_Charlottesville_2_SSE":(37.997,-78.46, 'US/Eastern'),
	"WA_Darrington_21_NNE":(48.540,-121.44, 'US/Pacific'),
	"WA_Quinault_4_NE":(47.513,-123.81,'US/Pacific'),
	"WA_Spokane_17_SSW":(47.417,-117.52,'US/Pacific'),
	"WI_Necedah_5_WNW":(44.060,-90.17, 'US/Central'),
	"WV_Elkins_21_ENE":(39.012,-79.47, 'US/Eastern'),
	"WY_Lander_11_SSE":(42.675,-108.66, 'US/Mountain'),
	"WY_Moose_1_NNE":(43.661,-110.71, 'US/Mountain'),
	"WY_Sundance_8_NNW":(44.516,-104.43, 'US/Mountain')
}



def _getUscrnData(year='2018', location='TX_Austin_33_NW', dataType="SOLARAD"):
	ghiData = pullUscrn(year, location, dataType)
	return ghiData

#Standard positional arguments are for TX_Austin
def _getPWCloudCoverForYear(year='2018', lat=30.581736, lon=-98.024098, key=_key_pirateweather, units='si'):
	cloudCoverByHour = {}
	pressureByHour = {}
	coords = '%0.2f,%0.2f' % (lat, lon)
	times = list(pd.date_range('{}-01-01'.format(year), '{}-12-31'.format(year), freq='D'))
	while times:
		time = times.pop(0)
		print(time)
		url = 'https://timemachine.pirateweather.net/forecast/%s/%s,%s?exclude=daily,alerts,minutely,currently&units=%s' % (key, coords, time.isoformat(), units ) 
		res = requests.get(url).json()
		try:
			dayData = res['hourly']['data']
		except KeyError:
			print("No day data!!!!!!")
			continue
		for hour in dayData:
			try:
				cloudCoverByHour[hour['time']] = hour['cloudCover']
				#Darksky result in hpascals, model trained in mbar. 1 - 1 transformation.
				pressureByHour[hour['time']] = hour['pressure']
			except KeyError:
				print("No Cloud Cover Data")
				pass
	return cloudCoverByHour, pressureByHour


def getSolarZenith(lat, lon, datetime, timezone):
    date = pytz.timezone(timezone).localize(datetime)
    solar_altitude = pysolar.solar.get_altitude(lat,lon,date)
    solar_zenith = 90 - solar_altitude
    return solar_zenith


def preparePredictionVectors(year='2018', lat=30.581736, lon=-98.024098, station='TX_Austin_33_NW', timezone='US/Central'):
    cloudCoverData, pressureData = _getPWCloudCoverForYear(year, lat, lon)
    ghiData = _getUscrnData(year, station, dataType="SOLARAD")
    #for each 8760 hourly time slots, make a timestamp for each slot, look up cloud cover by that slot
    #then append cloud cover and GHI reading together
    start_time = dt.datetime(int(year),1,1,0)
    cosArray = []
    input_array = []
    for i in range(len(ghiData)): #Because ghiData is leneth 8760, one for each hour of a year
        time = start_time + dt.timedelta(minutes=60*i)
        tstamp = int(dt.datetime.timestamp(time))
        hour = time.hour
        minute = time.minute
        try:
            cloudCover = cloudCoverData[tstamp]
            pressure = pressureData[tstamp]
        except KeyError:
            cloudCover = 0
            pressure = 0
        #I have my cloud cover, iterate over my ghi and cosine arrays
        solar_zenith = getSolarZenith(lat, lon, time, timezone)
        #Get cosine of solar zenith, this is going to be used later in dni calculation. Make sure its in radians.
        cosOfSolarZenith = cos(solar_zenith*0.0175)
        ghi = ghiData[i]
        input_array.append([ghi, cloudCover, hour, minute, solar_zenith, pressure])
        cosArray.append(cosOfSolarZenith)
    return input_array, ghiData, cosArray

def predictNeuralNet(input_array, model_path):
    from tensorflow import keras
    model = keras.models.load_model(model_path)
    #Takes in numpy array of proper shape
    """
    Ghi
    Cloud Cover 
    Hours
    Minutes
    Solar Zenith
    Pressure
    DHI"""
    preds = model.predict(input_array)
    return preds

def get_synth_dhi_dni(uscrn_station='TX_Austin_33_NW', year='2020'):
    lat = Station_Dict[uscrn_station][0]
    lon = Station_Dict[uscrn_station][1]
    timezone = Station_Dict[uscrn_station][2]
    input_array, ghi_array, cos_array = preparePredictionVectors(year, lat, lon, uscrn_station, timezone)
    print("input array created")
    dhi_preds = list(predictNeuralNet(input_array, f'{omfDir}/static/Neural_Net_National'))
    dhi_preds = [float(i) for i in dhi_preds]
    print("preds made")
    dniXCosTheta = [ghi_array[i] - dhi_preds[i] for i in range(0, len(ghi_array))] #This is cos(theta) * DNI
    print("cos theta calculation made")
    dni_array = ([dniXCosTheta[i]/cos_array[i] for i in range(len(dniXCosTheta))])
    result = list(zip((dhi_preds), (ghi_array), (dni_array)))
    assert len(result) == len(input_array)
    return result


def easy_solar_tests(uscrn_station='TX_Austin_33_NW'):
	print("********EASY SOLAR TEST STARTED************")
	print(get_synth_dhi_dni())
	print("Easy Solar Test Suceeded.........")


########### NDFD API #################

"""
NDFD code written by Tuomas Talvitie, 2020
tpt5cu@viriginia.edu

Based on code from:
https://github.com/tpt5cu/pyNDFD-fetcher
"""

"""
Single Point Unsummarized Data: Returns DWML-encoded NDFD data for a point
"""
#Works
def _singlePointDataQuery(lat1, lon1, product, begin, end, Unit='m', optional_params=['wspd', 'wdir']):
	params = {
		'lat':lat1,
		'lon':lon1,
		'product':product
	}
	params2 = {'begin':begin,
	'end':end
	}
	params3 = {
		'Unit':Unit,
	}
	urlString = urlencode(params)
	subString = ''
	for key, value in params2.items():
		subString += '&'+str(key) + '=' + str(value)
	urlString+=subString
	for i in optional_params:
		params3[i] = i
	urlString +='&' + urlencode(params3)
	return urlString

"""Subgrid defined by center point and lat/lon horizontal distance"""

def _subGrid(centerPointLat, centerPointLon, distanceLat, distanceLon, resolutionSquare, product, begin, end, Unit='m', optional_params=['wspd', 'wdir']):
	#Split into 3 dictionaries, each are encoded in a different manner
	params = {
		'centerPointLat':centerPointLat,
		'centerPointLon':centerPointLon,
		'distanceLat':distanceLat,
		'distanceLon':distanceLon,
		'resolutionSquare':resolutionSquare,
		'product':product
	}
	#Begin/end has special encoding
	params2 = {'begin':begin,
	'end':end
	}
	params3 = {
		'Unit':Unit,
	}

	urlString = urlencode(params)
	subString = ''
	for key, value in params2.items():
		subString += '&'+str(key) + '=' + str(value)
	urlString+=subString
	for i in optional_params:
		params3[i] = i
	urlString +='&' + urlencode(params3)

	return urlString

#Main URL path
def _ndfd_url(path=''):
    return 'http://www.weather.gov/forecasts/xml/sample_products/browser_interface/ndfdXMLclient.php?' + path


#This function acts as a general xml parser
def _generalParseXml(data):
	o = xmltodict.parse(data.content)
	d = json.dumps(o)
	d = json.loads(d)
	return d

def _run_ndfd_request(q):
	print(_ndfd_url(q))
	resp = requests.get(_ndfd_url(q))
	if resp.status_code != 200:
		# This means something went wrong.
		print(resp.status_code)
		raise Exception(f'status code: {resp.status_code} ' + resp.text)
	return resp


#Gets predictions from current moment to 10 weeks in future. Data not avaliable for past dates, not avaliable for too long in future
def get_ndfd_data(lat1, lon1, optional_params=['wspd'], begin=str(dt.datetime.now().isoformat()), end=(dt.datetime.now()+dt.timedelta(weeks=+10)).isoformat(), product='time-series', unit='m'):
	query = _singlePointDataQuery(lat1, lon1, product, begin, end, unit, optional_params)
	res = _run_ndfd_request(query)
	data = _generalParseXml(res)
	return data

#Wrapper to call _subGrid, return parsed dict
def getSubGridData(centerLat, centerLon, distanceLat, distanceLon, resolutionSquare, product='time-series', begin=str(dt.datetime.now().isoformat()), end=(dt.datetime.now()+dt.timedelta(weeks=+10)).isoformat(), Unit='m', optional_params=['critfireo', 'dryfireo']):
	data = _run_ndfd_request(_subGrid(centerLat, centerLon, distanceLat, distanceLon, resolutionSquare, product, begin, end, Unit, optional_params))
	outData = _generalParseXml(data)
	return outData
	
##################### Climate Data Store/Copernicus API #####################

# Getting the data
def api_request( request, target ):
	import cdsapi
	dataset = "reanalysis-era5-single-levels"
	client = cdsapi.Client()
	client.retrieve(dataset, request=request, target=target)

async def async_api_request(request, target):
	import asyncio
	await asyncio.to_thread(api_request, request, target)

# Default year if not given is last year
async def format_request(variable="default", year:str=str(dt.date.today().year - 1), latitude=None, longitude=None, dataDir="./"):
	import asyncio
	request_params = { 
		"data_format": "netcdf",
		"download_format": "zip",
		"product_type": ["reanalysis"],
		"day": [
				"01", "02", "03",
				"04", "05", "06",
				"07", "08", "09",
				"10", "11", "12",
				"13", "14", "15",
				"16", "17", "18",
				"19", "20", "21",
				"22", "23", "24",
				"25", "26", "27",
				"28", "29", "30",
				"31"
		],
		"time": [
				"00:00", "01:00", "02:00",
				"03:00", "04:00", "05:00",
				"06:00", "07:00", "08:00",
				"09:00", "10:00", "11:00",
				"12:00", "13:00", "14:00",
				"15:00", "16:00", "17:00",
				"18:00", "19:00", "20:00",
				"21:00", "22:00", "23:00"
		],
		"year": [year]
	}
	if variable == "default":
		variable = {"variable": [
			"10m_u_component_of_wind",
			"10m_v_component_of_wind",
			"2m_temperature",
			"surface_pressure",
			"100m_u_component_of_wind",
			"100m_v_component_of_wind",
			"surface_solar_radiation_downwards",
			"total_sky_direct_solar_radiation_at_surface",
			"forecast_surface_roughness"
		]}
	request_params.update( variable )
	# 0.01 of a degree works btw
	#Process latitude and longitude
	if latitude != None or longitude != None:
		if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
			# North, West, South, East
			area = [latitude + 0.01, longitude - 0.01, latitude - 0.01, longitude + 0.01]
			if area[0] > 90:
				area[0] = 90
				# Logging
				print("North value for sub-region area greater than 90 degrees - setting it to 90")
			if area[2] < -90:
				area[2] = -90
				print("South value for sub-region area less than -90 degrees - setting it to -90")
			if area[1] < -360:
				area[1] = -360
				print("West value for sub-region area less than -360 degrees - setting it to -360")
			if area[3] > 360:
				area[3] = 360
				print("East value for sub-region area greater than 360 degrees - setting it to 360")
			if abs(area[0]) + abs(area[2]) > 180:
				raise ValueError("Latitude Range cannot exceed 180")
			if abs(area[1]) + abs(area[3]) > 360:
				raise ValueError("Longitude Range cannot exceed 360")
	area_dict = {"area": "/".join(str(e) for e in area)}
	request_params.update(area_dict)

	# Each request will pull 2 months worth of data
	months = []
	fileNameByMonth = []
	for duo_month in range(1,12,2):
		months.append( {"month": [f"0{duo_month}", f"0{duo_month+1}"]})
		fileNameByMonth.append( f"month-{duo_month}-{duo_month+1}-data.zip")
	tasks = []
	for i in range(len(months)):
		from copy import deepcopy
		request_copy = deepcopy(request_params)
		request_copy.update(months[i])
		file_name = dataDir + '/' + fileNameByMonth[i]
		tasks.append(async_api_request(request=request_copy, target=file_name))
	await asyncio.gather( *tasks )

# This is the function to call to trigger getting the data
def get_cds_coper_data(latitude, longitude, year, modelDir):
	import asyncio
	requestSuccess = False

	key = '2fb47bd4-ed07-4961-bd15-ff1e51d1c8fe'
	# get user home directory
	home_dir = os.path.expanduser("~")
	print('HOME_DIR: ', home_dir)
	with open(f'{home_dir}/.cdsapirc','w') as keyFile:
		keyFile.write(
			'url: https://cds.climate.copernicus.eu/api\n' + 
			f'key: {key}' )
	os.environ['EIA_KEY'] = '431b0c60584d74a1ba22c60dbd929619'
	print(f'\nGetting new ERA5 data for ERA5_weather_data_{year}_{latitude}_{longitude}.zip')
	directory_name = modelDir + "/copernicusData"
	os.mkdir(directory_name)
	files = os.listdir(directory_name)
	if len(files) == 6:
		requestSuccess = True
	else:
		asyncio.run( format_request(
			variable='default',
			year=str(year),
			latitude=latitude,
			longitude=longitude,
			dataDir=directory_name )
		)
		requestSuccess = True
	return requestSuccess

# Processing the zip files into one nice large CSV
def process_weather_data():
	from zipfile import ZipFile
	import xarray as xr
	modelDir = Path()
	total_weather_data_ds = xr.Dataset()
	total_weather_data_df = pd.DataFrame()
	# For each file we downloaded ( month-1-2-data.zip )
	for zipfiles in Path(modelDir,"./copernicus_raw_data").iterdir():
		with ZipFile(zipfiles) as zObject:
			# extract it to unzipped_data
			zObject.extractall(path="./copernicus_unzipped_data/")
				#"data_stream-oper_stepType-accum.nc"
				#"data_stream-oper_stepType-instant.nc"
			unzippedDir = Path(modelDir, "./copernicus_unzipped_data")
			for file in unzippedDir.iterdir():
				file_accum = Path(unzippedDir, "data_stream-oper_stepType-accum.nc")
				file_instant = Path(unzippedDir, "data_stream-oper_stepType-instant.nc")
				weather_ds_accum = xr.open_dataset(file_accum, engine="netcdf4")
				weather_ds_instant = xr.open_dataset(file_instant, engine="netcdf4")
				month_weather_data = weather_ds_accum.combine_first(weather_ds_instant)
				total_weather_data_ds.update(month_weather_data)
				month_weather_data_df = month_weather_data.to_dataframe()
				total_weather_data_df = pd.concat([total_weather_data_df, month_weather_data_df])
	total_weather_data_df.to_csv(Path(modelDir, "total_weather_data.csv"), index=False)
	return [total_weather_data_ds, total_weather_data_df]

# Cool stuff with data
def get_solar(copernicus_csv_path):

	import PySAM.Pvwattsv8 as pvwatts

	copernicus_df = pd.read_csv(copernicus_csv_path)
	copernicus_df["Timestamp"] = pd.DatetimeIndex(pd.to_datetime(copernicus_df["valid_time"], utc=True))
	copernicus_df = copernicus_df.set_index("Timestamp")
	# DNI - Direct Normal
	# GHI - Global Horizontal
	# DHI - Diffuse Horizontal
	from pvlib.irradiance import erbs
	copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"] = (copernicus_df.ssrd / 3600.0)
	copernicus_df["dirhi"] = (copernicus_df.fdir / 3600.0)
	copernicus_df["CDS Diffusal Horizonal Irradiance (DHI) (W/m²_irr)"] = (copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"] - copernicus_df.dirhi)
	dni_data = erbs(copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"], zenith=30, datetime_or_doy=copernicus_df.index )
	copernicus_df["CDS Direct Normal Irradiance (DNI) (W/m²_irr)"] = dni_data["dni"]
	copernicus_df["CDS Wind Speed"] = np.sqrt(copernicus_df["u10"] ** 2 + copernicus_df["v10"] ** 2)
	copernicus_df["CDS Temp"] = copernicus_df.t2m - 273.15
	weather_data = np.array([
    copernicus_df.index.year,
    copernicus_df.index.month,
    copernicus_df.index.day,
    copernicus_df.index.hour,
    copernicus_df.index.minute,
    copernicus_df['CDS Direct Normal Irradiance (DNI) (W/m²_irr)'], #5 = dn
    copernicus_df["CDS Diffusal Horizonal Irradiance (DHI) (W/m²_irr)"],
    copernicus_df["CDS Global Horizonal Irradiance (GHI) (W/m²_irr)"],
    copernicus_df["CDS Wind Speed"],
    copernicus_df['CDS Temp']
	])
	sys_design = {
    "ModelParams": {
        "SystemDesign": {
            "array_type": 2.0,
            "azimuth": 180.0,
            "dc_ac_ratio": 1.08,
            "gcr": 0.592,
            "inv_eff": 97.5,
            "losses": 15.53,
            "module_type": 2.0,
            "system_capacity": 720,
            "tilt": 0.0
        },
        "SolarResource": {
        }
    },
    "Other": {
        "lat": copernicus_df.iloc[0][1],
        "lon": copernicus_df.iloc[0][2],
        "elev": 1829
    }
	}  
	model_params = sys_design['ModelParams']
	elev = sys_design['Other']['elev']
	lat = sys_design['Other']['lat']
	lon = sys_design['Other']['lon']
	tz = copernicus_df.index[0].utcoffset().total_seconds()/60/60

	system_model = pvwatts.new()
	system_model.assign(model_params)
	solar_resource_data = {
		'tz': tz, # timezone
		'elev': elev, # elevation
		'lat': lat, # latitude
		'lon': lon, # longitude
		'year': tuple(weather_data[0]), # year
		'month': tuple(weather_data[1]), # month
		'day': tuple(weather_data[2]), # day
		'hour': tuple(weather_data[3]), # hour
		'minute': tuple(weather_data[4]), # minute
		'dn': tuple(weather_data[5]), # direct normal irradiance
		'df': tuple(weather_data[6]), # diffuse irradiance
		'gh': tuple(weather_data[7]), # global horizontal irradiance
		'wspd': tuple(weather_data[8]), # windspeed
		'tdry': tuple(weather_data[9]) # dry bulb temperature
		}
	system_model.SolarResource.assign({'solar_resource_data': solar_resource_data})
	system_model.AdjustmentFactors.assign({'adjust_constant': 0})
	resource = system_model.SolarResource.export()
	# Convert and write JSON object to file
	with open("solar_resource.json", "w") as outfile: 
			json.dump(resource, outfile)
	system_model.execute()
	out = system_model.Outputs.export()
	ac = np.array(out['ac']) / 1000
	dc = np.array(out['dc']) / 1000
	ac_dc_df = pd.DataFrame({"ac": ac, "dc": dc}, columns = ['ac','dc'])
	ac_dc_df = ac_dc_df.set_index(copernicus_df.index.copy())
	return ac_dc_df

def format_windpowerlib(ds):
    """
    Code from feedinlib
    Format dataset to dataframe as required by the windpowerlib's ModelChain.

    The windpowerlib's ModelChain requires a weather DataFrame with time
    series for

    - wind speed `wind_speed` in m/s,
    - temperature `temperature` in K,
    - roughness length `roughness_length` in m,
    - pressure `pressure` in Pa.

    The columns of the DataFrame need to be a MultiIndex where the first level
    contains the variable name as string (e.g. 'wind_speed') and the second
    level contains the height as integer in m at which it applies (e.g. 10,
    if it was measured at a height of 10 m).

    Parameters
    ----------
    ds : xarray.Dataset
        Dataset with ERA5 weather data.

    Returns
    --------
    pd.DataFrame
        Dataframe formatted for the windpowerlib.

    """

    # compute the norm of the wind speed
    ds["wnd100m"] = np.sqrt(ds["u100"] ** 2 + ds["v100"] ** 2).assign_attrs(
        units=ds["u100"].attrs["units"], long_name="100 metre wind speed"
    )

    ds["wnd10m"] = np.sqrt(ds["u10"] ** 2 + ds["v10"] ** 2).assign_attrs(
        units=ds["u10"].attrs["units"], long_name="10 metre wind speed"
    )
    # drop not needed variables
    windpowerlib_vars = ["wnd10m", "wnd100m", "sp", "t2m", "fsr"]
    ds_vars = list(ds.variables)
    drop_vars = [
        _
        for _ in ds_vars
        if _ not in windpowerlib_vars + ["latitude", "longitude", "time"]
    ]
    ds = ds.drop(drop_vars)
    # convert to dataframe
    df = ds.to_dataframe().reset_index()
    # the time stamp given by ERA5 for mean values (probably) corresponds to
    # the end of the valid time interval; the following sets the time stamp
    # to the middle of the valid time interval
    df['valid_time'] = pd.to_datetime(df['valid_time'])
    df["time"] = df["valid_time"] - pd.Timedelta(minutes=60)

    df.set_index(["time", "latitude", "longitude"], inplace=True)
    df.sort_index(inplace=True)
    df = df.tz_localize("UTC", level=0)

    # reorder the columns of the dataframe
    df = df[windpowerlib_vars]

    # define a multiindexing on the columns
    midx = pd.MultiIndex(
        levels=[
            ["wind_speed", "pressure", "temperature", "roughness_length"],
            # variable
            [0, 2, 10, 100],  # height
        ],
        codes=[
            [0, 0, 1, 2, 3],  # indexes from variable list above
            [2, 3, 0, 1, 0],  # indexes from the height list above
        ],
        names=["variable", "height"],  # name of the levels
    )
    df.columns = midx
    df.dropna(inplace=True)
    return df

def get_wind(weather_dataset):
	from omf.solvers import feedinlib_custom

	bergey_turbine_data = {
		'nominal_power': 15600, # in W
		'hub_height': 24, # in meters  
		'power_curve': pd.DataFrame( # https://github.com/wind-python/windpowerlib <-- for info on adding custom loadshapes 
			data={'value': [p * 1000 for p in [0, 0, 0.108, 0.679, 2.074, 3.824, 6.089, 8.500, 11.265, 13.664, 15.612, 16.876, 18.212, 19.096, 20.355, 20.611, 19.687]],  # kW -> W
			'wind_speed': [1.0, 2.01, 2.99, 4.01, 5.00, 6.00, 7.00, 8.00, 9.00, 9.99, 11.01, 11.97, 12.99, 13.99, 15.00, 15.97, 16.47]})  # in m/s
	}
	wind_turbine = feedinlib_custom.powerplants.WindPowerPlant(**bergey_turbine_data)
	windpowerlib_df = format_windpowerlib(weather_dataset)  
	windpowerlib_df = windpowerlib_df.droplevel([1,2])
	wind_output_ds = wind_turbine.feedin(
		weather = windpowerlib_df,
		density_correction = True,
		scaling = 'nominal_power',
	)
	wind_output_ds.reset_index(drop=True, inplace=True)
	return wind_output_ds

def _tests():
	# import traceback
	# print('weather.py tests currently disabled to keep them from sending too many HTTP requests.')
	# tmpdir = mkdtemp()
	# print("Beginning to test weather.py in", tmpdir)
	# # # Testing ASOS (Works)
	# try:
	# 	# res = pullAsos('2015','LWD', 'presentwx') # Does not write to a file by itself
	# 	# res = pullAsos('1900','LWD', 'dwpc') # Does not write to a file by itself
	# 	print(res)
	# 	if len(res) > 8760:
	# 		print("ASOS data corrupted")
	# 		raise Exception
	# except:
	# 	val = traceback.format_exc()
	# 	e = sys.exc_info()[0]
	# 	print(val)
	# 	print(e)

	# # # print('ASOS (Iowa) data pulled to ' + tmpdir)
	# # # pullAsosStations(os.path.join(tmpdir, 'asosStationTable.csv'))


	# # Testing USCRN (Works)
	# print('USCRN (NOAA) data pulled to ' + tmpdir)
	# data = pullUscrn('2001', 'TX_Austin_33_NW', "zz") # Does not write to a file by itself
	# print(data)
	# try:
	# 	# data = pullUscrn('2017', 'KY_Versailles_3_NNW', "IRRADIENCE_DIFFUSE") # Does not write to a file by itself
	# except:
	# 	val = traceback.format_exc()
	# 	e = sys.exc_info()[0]
	# 	print(val)
	# 	print(e)

#	Testing DarkSky (Works as long as you have an API key)
	# d=(pullDarksky(1900, 36.64, -93.30, 'temperature', api_key= _key_darksky, path=tmpdir))
	# try:
	# 	d=(pullDarksky(1900, 30, -90, 'temperature', api_key= _key_darksky))
	# 	print(d)
	# except:
	# 	val = traceback.format_exc()
	# 	e = sys.exc_info()[0]
	# 	print(val)
	# 	print(e)

	#Testing NSRDB (Works)
	# nsrdbkey = 'rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56'
	# try:
	# #Test For Austin, TX
	# 	d=get_nrsdb_data('psm',-90.0,30.00,'2018', nsrdbkey, interval=60)
	# 	print(d)
	# except:
	# 	val = traceback.format_exc()
	# 	e = sys.exc_info()[0]
	# 	print(val)
	# 	print(e)

#	Testing tmy3 (Works)
	# if platform.system() != 'Windows':
	# 	try:
	# 		data=tmy3_pull(nearest_tmy3_station(31.00, -90.00))
	# 		print(data)
	# 		if len(data) == 0:
	# 			print("too early a year")
	# 			raise Exception
	# 	except:
	# 		val = traceback.format_exc()
	# 		e = sys.exc_info()[0]
	# 		print(val)
	# 		print(e)

#	NDFD tests
	# try:
	# # 	d = get_ndfd_data('39.0000', '-77000.0000',['wspd'])
	# # 	print(d)
	# 	d = getSubGridData('40.758701', '-111.876183', '20', '20', '20', 'time-series')
	# 	print(d)
	# except:
	# 	val = traceback.format_exc()
	# 	e = sys.exc_info()[0]
	# 	print(val)
	# 	print(e)
	
#	Easy Solar Tests
	# easy_solar_tests()


	# Testing zipCodeToClimateName (Certain cases fail)
	# print(zipCodeToClimateName('75001'))
	# print(zipCodeToClimateName('07030')) # Doesn't work
	# print(zipCodeToClimateName('64735'))
	# assert ('MO-KANSAS_CITY', 30) == zipCodeToClimateName('64735') # Assertion Fails
	# print(airportCodeToLatLon("IAD"))

#	Testing getRadiationYears (Works, but not used anywhere)
	# try:
	# 	print(get_radiation_data('surfrad', 'Boulder_CO', 2019))
	# 	get_radiation_data('solrad', 'bis', 2019)
	# except:
	# 	e = sys.exc_info()[0]
	# 	print(e)
	print("testing finished")
	

if __name__ == "__main__":
	_tests()