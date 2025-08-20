''' Get power and energy limits from PNNL VirtualBatteries (VBAT) load model.'''
import shutil, csv
from os.path import isdir, join as pJoin
from omf import weather
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from datetime import timedelta, datetime


# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Download historical weather data for a given location for use in other models."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory.
		Model takes in parameters from inputDict, and returns a list of data points of type float.
		'''
	print(inputDict)
	source = inputDict['source']
	lat = inputDict['LatInput']
	long = inputDict['LonInput']
	if source =='ASOS':
		station = inputDict['stationASOS']
		parameter = inputDict['weatherParameterASOS']
		data = weather.pullAsos(inputDict['year'], station, parameter)
	elif source == 'USCRN':
		station = inputDict['stationUSCRN']
		parameter = inputDict['weatherParameterUSCRN']
		data = weather.pullUscrn(inputDict['year'], station, parameter)
	elif source == 'PirateWeather':
		parameter = inputDict['weatherParameterPirateWeather']
		data = weather.pullPirateWeather(inputDict['year'], lat, long, parameter, units='si')
	elif source == 'NRSDB':
		nsrdbkey = 'rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56'
		year = inputDict['year']
		param = inputDict['weatherParameterNRSDB']
		data = weather.get_nrsdb_data('psm', float(long), float(lat), year, nsrdbkey, interval=60)
		#Data must be a list. Extract correct column from returned pandas df, return this column as array of int
		data = list(data[param].values[3:].astype(float))
		print(data)
	elif source in ['easySolarGhi', 'easySolarDhi','easySolarDni'] :
		print("EASYSOLAR FOUND")
		station = inputDict['easySolarStation']
		year = inputDict['year']
		data = weather.get_synth_dhi_dni(station, year)
		if source == 'easySolarDhi':
			data = list([i[0] for i in data])
			print(data)
		elif source == 'easySolarGhi':
			data = list([i[1] for i in data])
			print(data)
		elif source == 'easySolarDni':
			data = list([i[2] for i in data])
			print(data)
	elif source == 'tmy3':
		param = inputDict['weatherParameterTmy3']
		year = int(inputDict['year'])
		data = weather.tmy3_pull(weather.nearest_tmy3_station(float(lat), float(long)))
		#Now get data for the year in question
		data = data.loc[data['year']==year]
		print(data)
		if len(data) == 0:
			raise Exception("No data for the year and location")
		#Extract param from data, convert to int, and pass in values not pandas series
		data = list(data[param].astype(float).values)
	elif source == 'surfrad':
		year = int(inputDict['year'])
		param = inputDict['weatherParameterSurfrad']
		site = inputDict['surfradSite']
		print(year, param, site)
		data = weather.get_radiation_data('surfrad', site, year)
		data = list(data[param].values.astype(float))
		print(data)
	elif source == 'ndfd':
		#This will just just current date for forecast, as it does not support historical forecasts
		#and future forcasts are limited
		param = [inputDict['ndfdParam']]
		d = weather.get_ndfd_data(lat, long, param)
		#data is now an json-like object. Parse it, and get the data ready for presentation
		#get timestamps, to unix times
		timestamps = (d['dwml']['data']['time-layout']['start-valid-time'])
		timestamps = [datetime.fromisoformat(i).timestamp() for i in timestamps]
		#get the parameter in question
		param = list(d['dwml']['data']['parameters'].keys())[-1]
		#get the values for that parameter
		values = d['dwml']['data']['parameters'][param]['value']
		c = zip(timestamps, values)
		# print(c)
		#Date dictionary creation
		start_year=(datetime.today().strftime("%Y"))
		start_year = datetime(int(start_year),1,1,0)
		dateAndDataDict = {}
		for i in range(8761): #Because ghiData is leneth 8760, one for each hour of a year
				time = start_year + timedelta(minutes=60*i)
				tstamp = float(datetime.timestamp(time))
				# time = time.isoformat()
				dateAndDataDict[tstamp] = 0
		#Add in exsisting values
		for i, j in c:
			dateAndDataDict[i] = int(j)
		#Now for filler
		#for 0 values between readings, fill in last read value. 
		#All other 0 values leave at zero

		#get ordered values
		data = list(dateAndDataDict.values())
		#set left and right boundaries at right positions
		left = 0
		right = len(data)-1
		while data[left] == 0 and left < right:
				left+=1
		while data[right] ==0 and right>left:
			right-=1

		#now for filler
		last = data[left]
		for i in range(left,right):
			if data[i] != 0:
				last = int(data[i])
			else:
				data[i] = last

	if inputDict["pullCDSCoperData"] == 'on':
		year = int( inputDict['year'] )
		successful = weather.get_cds_coper_data( latitude=float(lat), longitude=float(long), year=year, modelDir=modelDir)
		if (successful == False):
			raise Exception("CDS Copernicus Weather Pulling Code Failed")

	# station = inputDict['stationASOS'] if source == 'ASOS' else inputDict['stationUSCRN']
	# parameter = inputDict['weatherParameterASOS'] if source == 'ASOS' else inputDict['weatherParameterUSCRN']
	# inputs = [inputDict['year'], station, parameter]
	# data = weather.pullAsos(*inputs) if source == 'ASOS' else weather.pullUscrn(*inputs)
	with open(pJoin(modelDir,'weather.csv'), 'w', newline='') as f:
		csv.writer(f).writerows([[x] for x in data])
	return {
		'rawData': data,
		'errorCount': len([e for e in data if e in [-9999.0, -99999.0, -999.0, -99.0]]),
		'stdout': 'Success' }


def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	source = [
        'ASOS',
        'USCRN',
        'pirateWeather',
        'NRSDB',
        'easySolarGhi',
        'easySolarDhi',
        'easySolarDni',
        #'tmy3',
        #'surfrad',
        #'ndfd'
        ][0]
	defaultInputs = {
		"user": "admin",
		'source': source,
		"year": "2013",
		"stationASOS": "LWD",
		"stationUSCRN": "KY_Versailles_3_NNW",
		"weatherParameterUSCRN": "SOLARAD",
		"weatherParameterASOS": "tmpc",
		'LatInput': '39.828362',
		'LonInput': '-98.579490',
		'weatherParameterPirateWeather': '',
		'weatherParameterNRSDB': 'Pressure',
		'easySolarStation': 'TX_Austin_33_NW',
		'weatherParameterTmy3': 'TBD',
		'weatherParameterSurfrad': '',
		'surfradSite': 'PSU',
		'ndfdParam': '',
		'pullCDSCoperData': 'off',
		"modelType": modelName}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	modelLoc = pJoin(__neoMetaModel__._omfDir, "data", "Model", "admin", "Automated Testing of " + modelName)
	if isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc) # Create New.
	__neoMetaModel__.renderAndShow(modelLoc) # Pre-run.
	try:
		__neoMetaModel__.runForeground(modelLoc) # Run the model.
	except:
		pass # Just ignore errors because sometimes HTTP requests fail.
	__neoMetaModel__.renderAndShow(modelLoc) # Show the output.

if __name__ == '__main__':
	_tests()
