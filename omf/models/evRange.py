"""
Map public electric-vehicle charging stations and compute reachable service areas from
configurable range assumptions.
"""
import random, requests
from pathlib import Path

from shapely.geometry import Point, mapping
from shapely.ops import unary_union, transform
from pyproj import Transformer

from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
tooltip = 'Display up-to-date map of public EV charging locations with an editable EV range radius at each location.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

class NRELAltFuelStationsAPIError(Exception):
	'''Raised when the API call to NREL fails.'''
	pass

class FuelStationCacheError(Exception):
	'''Raised when there is a problem reading or writing the cache file.'''
	pass

def get_randomized_api_key():
	'''returns a random API key'''
	REOPT_API_KEYS = [
		'WhEzm6QQQrks1hcsdN0Vrd56ZJmUyXJxTJFg6pn9',
		'Y8GMAFsqcPtxhjIa1qfNj5ILxN5DH5cjV3i6BeNE',
		'etg8hytwTYRf4CD0c4Vl9U7ACEQnQg6HV2Jf4E5W',
		'BNFaSCCwz5WkauwJe89Bn8FZldkcyda7bNwDK1ic',
		'L2e5lfH2VDvEm2WOh0dJmzQaehORDT8CfCotaOcf',
		'08USmh2H2cOeAuQ3sCCLgzd30giHjfkhvsicUPPf'
	]
	return random.choice(REOPT_API_KEYS)

def filter_fuel_stations(full_results):
	"""
	Perform filter fuel stations processing for the ev range model.
	"""
	keys_to_keep = ['station_name', 'latitude', 'longitude', 'street_address', 'city', 'state']
	# keys_to_keep = ['id', 'station_name', 'latitude', 'longitude', 'street_address', 'city', 'state', 'zip']
	# keys_to_keep = ['id', 'station_name', 'latitude', 'longitude', 'street_address', 'city', 'state', 'zip', 'ev_network', 'ev_connector_types', 'ev_pricing', 'maximum_vehicle_class', 'ev_level1_evse_num', 'ev_level2_evse_num', 'ev_dc_fast_num', 'access_days_time', 'station_phone', 'date_last_confirmed']
	filtered = []
	for station in full_results:
		filtered_station = { key: station.get(key) for key in keys_to_keep }
		filtered.append(filtered_station)
	return filtered

def call_api():
	"""
	Perform call api processing for the ev range model.
	"""
	api_key = get_randomized_api_key()
	url = 'https://developer.nrel.gov/api/alt-fuel-stations/v1.json'
	params = {
		# 'limit': 50,
        'api_key': api_key,
		'access':'public',
		'fuel_type':'ELEC',
		'ev_network': 'all',
		'ev_charging_level': 'all',
		'ev_connector_type': 'all'
    }
	response = requests.get(url, params=params)
	if response.ok:
		data = response.json()
		fuel_stations = data.get('fuel_stations', [])
		# return fuel_stations
		return filter_fuel_stations(fuel_stations)
	else:
		raise NRELAltFuelStationsAPIError(f'API call failed with status code {response.status_code}: {response.text}')
	
def get_cache_filepath():
    """
    Return the cache filepath needed by this workflow.
    """
    app_root = Path(__neoMetaModel__._omfDir).resolve()
    return app_root / 'static' / 'ev_fueling_stations.json'

def get_cached_results():
	"""
	Return the cached results needed by this workflow.
	"""
	cache_file = get_cache_filepath()
	try:
		if cache_file.exists():
			return json.loads(cache_file.read_text())
		else:
			raise FuelStationCacheError('Cache file does not exist.')
	except Exception as e:
		raise FuelStationCacheError(f'Error reading cached results: {e}')

def cache_new_results(results):
	"""
	Perform cache new results processing for the ev range model.
	"""
	cache_file = get_cache_filepath()
	cache_file.parent.mkdir(parents=True, exist_ok=True)
	try:
		with tempfile.NamedTemporaryFile('w', dir=str(cache_file.parent), delete=False, encoding='utf-8') as tmp_file:
			json.dump(results, tmp_file)
			temp_path = Path(tmp_file.name)
		temp_path.replace(cache_file)
	except Exception as e:
		raise FuelStationCacheError(f'Failed to cache new results: {e}')

def compute_union_for_group(ev_range_meters, group, transformer_from, transformer_to):
    """
    Perform compute union for group processing for the ev range model.
    """
    buffers = []
    for station in group:
        try:
            lat = float(station['latitude'])
            lon = float(station['longitude'])
            pt = Point(lon, lat)
            pt_proj = transform(transformer_from.transform, pt)
            buff_proj = pt_proj.buffer(ev_range_meters)
            buff = transform(transformer_to.transform, buff_proj)
            buffers.append(buff)
        except Exception:
            continue
    if buffers:
        return unary_union(buffers)
    else:
        return None

def compute_union_polygon_by_region(stations, ev_range_miles):
	'''
	Partition stations by region and compute union buffers for each.
	Returns a FeatureCollection with separate features for each region.
	'''
	# Convert range from miles to meters.
	ev_range_meters = ev_range_miles * 1609.34
	# Separate stations based on state.
	contiguous = [s for s in stations if s.get('state') not in ('AK', 'HI', 'PR')]
	alaska = [s for s in stations if s.get('state') == 'AK']
	hawaii = [s for s in stations if s.get('state') == 'HI']
	puerto_rico = [s for s in stations if s.get('state') == 'PR']
	features = []
	# Initialize ransformers for each region.
	# Contiguous US: Albers Equal Area
	transformer_contiguous_to_proj = Transformer.from_crs(
		"EPSG:4326",
		{"proj": "aea", "lat_1": 29.5, "lat_2": 45.5, "lat_0": 37.5, "lon_0": -96},
		always_xy=True
		)
	transformer_contiguous_from_proj = Transformer.from_crs(
		{"proj": "aea", "lat_1": 29.5, "lat_2": 45.5, "lat_0": 37.5, "lon_0": -96}, 
		"EPSG:4326", 
		always_xy=True
		)
	# Alaska, Hawaii, Puerto Rico: Mercator
	transformer_global_to = Transformer.from_crs(
		"EPSG:4326", 
		"EPSG:3857", 
		always_xy=True
		)
	transformer_global_from = Transformer.from_crs(
		"EPSG:3857", 
		"EPSG:4326", 
		always_xy=True
		)
	# Union for contiguous US.
	union_contiguous = compute_union_for_group(ev_range_meters, contiguous, transformer_contiguous_to_proj, transformer_contiguous_from_proj)
	if union_contiguous:
		features.append({
			"type": "Feature",
			"properties": {"region": "contiguous"},
			"geometry": mapping(union_contiguous)
		})
	# Union for Alaska, Hawaii, and Puerto Rico.
	for region, group in (("alaska", alaska), ("hawaii", hawaii), ("puerto_rico", puerto_rico)):
		union_region = compute_union_for_group(ev_range_meters, group, transformer_global_to, transformer_global_from)
		if union_region:
			features.append({
				"type": "Feature",
				"properties": {"region": region},
				"geometry": mapping(union_region)
			})
	# Return GeoJSON FeatureCollection.
	return {"type": "FeatureCollection", "features": features}
	
def work(modelDir, inputDict):
	"""
	Run the ev range model analysis and return the output data used by the OMF interface.
	"""
	outData = {}
	refresh_requested = inputDict.get('refreshCachedResults', False)
	if refresh_requested:
		try:
			results = call_api()
			cache_new_results(results)
			update_message = 'Cache updated successfully.'
		except Exception as e:
			results = get_cached_results()
			update_message = f'Cache update failed: {e}'
	else:
		try:
			results = get_cached_results()
			update_message = 'Using cached results.'
		except Exception as e:
			results = []
			update_message = f'Error retrieving cached results: {e}'
	initial_range_miles = float(inputDict.get('initialRangeMiles', 100))
	coverage_polygon = compute_union_polygon_by_region(results, initial_range_miles)
	outData['initial_range_miles'] = initial_range_miles
	outData['fuel_stations'] = results
	outData['cache_message'] = update_message
	outData['coverage_polygon'] = coverage_polygon
	return outData
	
def new(modelDir):
	"""
	Create a new ev range model instance with default inputs for the OMF interface.
	"""
	defaultInputs = {
		'modelType': modelName,
		'initialRangeMiles': 100
    }
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	return creationCode

def _tests():
    # Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = Path(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
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