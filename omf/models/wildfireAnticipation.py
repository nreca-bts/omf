"""
Estimate wildfire risk for user-specified US geographic regions and package map overlays
for OMF resilience workflows.
"""
import base64, requests, shutil
from pathlib import Path
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.weather import getSubGridData
from shapely.geometry import shape

# Model metadata:
tooltip = 'Return wildfire risk for custom geographic regions in the US.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

def process_risk(api_results, forecast_time):
	'''
	Process API results to extract a risk value for a given risk type. 
	risk_type is a string expected to appear in the risk object's '@type' attribute. 
	temperature, wind, and relative humidity
	dry thunderstorms
	'''
	fire_risk_mapping = {
		'No Areas': 0,
		'Elevated Areas': 1,
		'Critical Areas': 2,
		'Extremely Critical Areas': 3
	}
	thunderstorm_risk_mapping = {
		'No Areas': 0,
		'Isolated': 1,
		'Scattered': 2,
	}
	max_numeric_fire_risk = -1
	max_numeric_thunderstorm_risk = -1
	resolution_points = api_results.get('dwml', {}).get('data', {}).get('parameters', [])
	for point in resolution_points:
		fire_weather_list = point.get('fire-weather')
		# if not fire_weather_list:
		# 	continue
		for risk_type_object in fire_weather_list:
			day_forecasts = risk_type_object.get('value', [])
			if forecast_time > len(day_forecasts) - 1:
				raise IndexError(f'{forecast_time} is greater than available days ({len(day_forecasts)} days).')
			risk_str = day_forecasts[forecast_time]
			if risk_type_object.get('@type', '').lower().find('temperature, wind, and relative humidity') != -1:
				max_numeric_fire_risk = max(max_numeric_fire_risk, fire_risk_mapping.get(risk_str, -1))
			elif risk_type_object.get('@type', '').lower().find('dry thunderstorms') != -1:
				max_numeric_thunderstorm_risk = max(max_numeric_thunderstorm_risk, thunderstorm_risk_mapping.get(risk_str, -1))
	rev_fire_risk_mapping = {v: k for k, v in fire_risk_mapping.items()}
	rev_thunderstorm_risk_mapping = {v: k for k, v in thunderstorm_risk_mapping.items()}
	return rev_fire_risk_mapping.get(max_numeric_fire_risk, 'Unknown'), rev_thunderstorm_risk_mapping.get(max_numeric_thunderstorm_risk, 'Unknown')

def get_kmz_base64(forecast_time):
	''' Map forecast_time to the correct URL and Base64-encode the binary content. '''
	if forecast_time == 0:
		url = 'https://www.spc.noaa.gov/products/fire_wx/day1fireotlk.kmz'
	elif forecast_time == 1:
		url = 'https://www.spc.noaa.gov/products/fire_wx/day2fireotlk.kmz'
	else:
		url = 'https://www.spc.noaa.gov/products/fire_wx/day38fireotlk.kmz'
	r = requests.get(url, allow_redirects=True)
	encoded = base64.b64encode(r.content).decode('ascii')
	return encoded

def work(modelDir, inputDict):
	"""
	Run the wildfire anticipation model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	forecast_time = int(inputDict.get('forecastTimeSelect', '0'))
	geojson_input = inputDict.get('geojsonInput', '')
	if not geojson_input:
		outData['fire_risk_from_map'] = {}
		outData['thunderstorm_risk_from_map'] = {}
		outData['kmz_base64'] = get_kmz_base64(forecast_time)
		return outData

	geojson = json.loads(geojson_input)
	# Handle FeatureCollection, Feature, or raw geometry.
	if geojson.get('type') == 'FeatureCollection':
		features = [feature for feature in geojson['features']]
	elif geojson.get('type') == 'Feature':
		features = [geojson]
	else:
		features = [{'geometry': geojson}]
	
	fire_risk_from_map, thunderstorm_risk_from_map = {}, {}
	for feature in features:
		shape_id = feature.get('properties', {}).get('shape_id')
		geometry = shape(feature['geometry'])
		min_lon, min_lat, max_lon, max_lat = geometry.bounds
		center_lat = (min_lat + max_lat) / 2.0
		center_lon = (min_lon + max_lon) / 2.0
		# Use half the height and width as distances.
		distance_lat = (max_lat - center_lat)
		distance_lon = (max_lon - center_lon)
		resolution = 0.1
		api_results = getSubGridData(center_lat, center_lon, distance_lat, distance_lon, resolution)
		processed_fire_risk, processed_thunderstorm_risk = process_risk(api_results, forecast_time)
		fire_risk_from_map[shape_id] = processed_fire_risk
		thunderstorm_risk_from_map[shape_id] = processed_thunderstorm_risk
	outData['fire_risk_from_map'] = fire_risk_from_map
	outData['thunderstorm_risk_from_map'] = thunderstorm_risk_from_map
	outData['kmz_base64'] = get_kmz_base64(forecast_time)
	return outData

def new(modelDir):
	"""
	Create a new wildfire anticipation model instance with default inputs for the OMF
	interface.
	"""
	defaultInputs = {
		'modelType': modelName
    }
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	return creationCode

def _tests():
    # Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = Path(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		pass # No previous test results.
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