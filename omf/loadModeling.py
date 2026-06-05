"""
Generate and attach residential load models from archetypes, address metadata, building
characteristics, and feeder context.
"""
import json, xml.etree.ElementTree as ET, random, os
from functools import lru_cache
import requests
import omf
from omf import feeder


def get_zillow_configured_new_house(lat=None, lon=None, address=None):
	'''Attempt to get a house archetype dictionary that has additional properties supplied by Zillow'''
	if address is not None and (lat is not None or lon is not None):
		raise ValueError('Address XOR (lat and lon) must be provided.')
	try:
		if address: # An address was provided
			components = _get_address_components_from_string(address)
		else:
			components = _get_address_components_from_coordinates(lat, lon)
			address = components['address'] # Nominatim found an address
		zillow_specs = _get_zillow_house_specs(components['street_number'], components['zip_code'])
		if zillow_specs.get('address'):
			address = zillow_specs.get('address') # Zillow found an address
		new_house = {}
		# The 'name', 'parent', 'latitude', and 'longitude' attributes are all replaced on the frontend
		new_house['name'] = address
		new_house['parent'] = 'REPLACE_ME'
		#new_house['latitude'] = lat
		#new_house['longitude'] = lon
		new_house['object'] = 'house'
		#new_house['address'] = address # The 'address' attribute isn't used on the frontend
		new_house['schedule_skew'] = str(random.gauss(2000, 500))
		new_house['floor_area'] = zillow_specs.get('sqft') if zillow_specs.get('sqft') else '2700'
		year_built = zillow_specs.get('yearBuilt') # could be '', a string, or an int
		try:
			year_built = int(year_built)
		except:
			year_built = 1980
		if not zillow_specs.get('lotSize'):
			# Make an apartment
			if year_built < 1960:
				new_house = {**_house_maker('R1_Apartment_Pre-1960'), **new_house}
			elif 1960 <= year_built < 1990:
				new_house = {**_house_maker('R1_Apartment_1960-1989'), **new_house}
			elif year_built >= 1990:
				new_house = {**_house_maker('R1_Apartment_1990-2005'), **new_house}
		else:
			# Make a house
			if year_built < 1940:
				new_house = {**_house_maker('R1_SingleFamilyHome_Pre-1940'), **new_house}
			elif 1940 <= year_built < 1950:
				new_house = {**_house_maker('R1_SingleFamilyHome_1940-1949'), **new_house}
			elif 1950 <= year_built < 1960:
				new_house = {**_house_maker('R1_SingleFamilyHome_1950-1959'), **new_house}
			elif 1960 <= year_built < 1970:
				new_house = {**_house_maker('R1_SingleFamilyHome_1960-1969'), **new_house}
			elif 1970 <= year_built < 1980:
				new_house = {**_house_maker('R1_SingleFamilyHome_1970-1979'), **new_house}
			elif 1980 <= year_built < 1990:
				new_house = {**_house_maker('R1_SingleFamilyHome_1980-1989'), **new_house}
			elif year_built >= 1990:
				new_house = {**_house_maker('R1_SingleFamilyHome_1990-2005'), **new_house}
		return new_house
	except Exception as e:
		return None


def get_random_new_house():
	"""
	Return the random new house needed by this workflow.
	"""
	houseArchetypes = _get_house_archetypes()
	new_house = dict(random.choice(list(houseArchetypes.values())))
	# The 'name' and 'parent' attributes are replaced on the frontend
	new_house['name'] = 'REPLACE_ME'
	new_house['parent'] = 'REPLACE_ME'
	new_house['schedule_skew'] = str(random.gauss(2000,600))
	# NOTE: average size of US house used below is from http://money.cnn.com/2014/06/04/real_estate/american-home-size/
	new_house['floor_area'] = str(random.gauss(2600,500))
	return new_house


def _house_maker(name):
	'''New dict by name from the houseArchetypes.'''
	houseArchetypes = _get_house_archetypes()
	return dict(houseArchetypes[_get_by_key_val(houseArchetypes, 'name', name)])


@lru_cache(maxsize=1)
def _get_house_archetypes():
	"""
	Internal helper for load modeling get house archetypes processing.
	"""
	return feeder.parse(os.path.join(omf.omfDir, "static/testFiles/houseArchetypes.glm"))


def _get_address_components_from_string(address):
	'''
	Get address components.

	Not all components are currently used, so unused components are commented out.
	'''
	addr_ptrn = address.split(', ')
	return {
		'street_number': addr_ptrn[0],
		'zip_code': addr_ptrn[2].split(' ')[1],
		#'city_name': addr_ptrn[1],
		#'state_name': addr_ptrn[2].split(' ')[0],
		#'country_name' = addr_ptrn[3]
	}


def _get_address_components_from_coordinates(lat, lon):
	'''Return an address by using open street map for reverse geocoding'''
	response = requests.get(
		'https://nominatim.openstreetmap.org/reverse?format=json&lat={}&lon={}&zoom=18&addressdetails=1'.format(lat, lon),
		headers={'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.13; rv:71.0) Gecko/20100101 Firefox/71.0'}
	)
	response.raise_for_status()
	response_data = response.json()
	return {
		'address': response_data['display_name'], # Always present
		'street_number': response_data['address']['house_number'], # Always present
		'zip_code': response_data['address']['postcode'], # Always present
		#'state_name' = response_data['address']['state'], # Always present. We don't use it currently
		#'country_name': response_data['address']['country'], # Always present. We don't use it currently
		#'city_name': response_data['address']['city'] # Not always present. We don't use it currently
	}


def _get_zillow_house_specs(street_number, zip_code):
	'''House details lookup via http://www.zillow.com/howto/api/GetDeepSearchResults.htm'''
	zwsID = 'X1-ZWz1dvjlzatudn_5m9vn'  # TODO: change to a new one
	response = requests.get(
		'http://www.zillow.com/webservice/GetDeepSearchResults.htm',
		params={
			'zws-id': zwsID,
			'address': street_number,
			'citystatezip': zip_code
		}
	)
	root = ET.fromstring(response.content)
	# Depending on the address that was passed to Zillow, a single result or multiple results can be returned. We only return the first result
	results = list(root.iterfind('response/results/result'))
	match_count = len(results) # We warn user by putting # of matches in the output.
	result = results[0]
	address_subtree = result.find('address')
	try:
		# Try to get the address used by Zillow instead of the one used by Nominatim
		address = '{}, {}, {} {}'.format(
			address_subtree.find('street').text,
			address_subtree.find('city').text,
			address_subtree.find('state').text,
			address_subtree.find('zipcode').text
		)
	except:
		address = None
	def safeText(key):
		try:
			return result.find(key).text
		except:
			return ''
	# At the moment, we only seem to be interested in lotSizeSqFt, yearBuilt, and finishedSqFt
	# - lotSizeSqFt is used to choose between a house or apartment, but is not directly stored on the new house
	# - yearBuilt is used to determine the year of the house archetype, but is not directly stored on the new house
	# - sqft is stored directly on the new house as the "floor_area" attribute
	house_info = {
		'matching_properties_count': match_count,
		'address': address,
		'lotSize':safeText('lotSizeSqFt'),
		'yearBuilt': safeText('yearBuilt'), # Not always present
		'sqft': safeText('finishedSqFt'), # Not always present
		'bathrooms':safeText('bathrooms'), # Not always present
		'bedrooms': safeText('bedrooms'), # Not always present
	}
	return house_info


def _get_by_key_val(tree, key, value, getAll=False):
	''' Return (one or more) keys to the first item in tree where that objects key=val.'''
	allMatches = [k for k in tree if tree[k].get(key,'') == value]
	if getAll:
		return allMatches
	elif (not getAll) and len(allMatches) > 0:
		return allMatches[0]
	else:
		return None

def addScaledRandomHouses(inFeed):
	''' Take a feeder, translate each triplex_node under a meter in to a scaled, semi-randomized house object. '''
	houseArchetypes = _get_house_archetypes()
	childrenPath = os.path.join(omf.omfDir, 'static', 'testFiles', 'houseChildren.glm')
	childrenArchetypes = feeder.parse(childrenPath)
	tripNodeKeys = _get_by_key_val(inFeed, 'object', 'triplex_node', getAll=True)
	tripLoadKeys = [k for k in tripNodeKeys if 'parent' in inFeed[k]]
	maxKey = feeder.getMaxKey(inFeed) + 1
	inFeed[maxKey] = {'omftype': 'module', 'argument': 'residential'}
	maxKey += 1
	inFeed[maxKey] = {'omftype': '#include','argument': '\"schedulesResponsiveLoads.glm\"'}
	maxKey += 1
	for tripKey in tripLoadKeys:
		tMeter = inFeed[_get_by_key_val(inFeed, 'name', inFeed[tripKey]['parent'])]
		tPower = complex(inFeed[tripKey]['power_12']).real
		newHouse = dict(random.choice(list(houseArchetypes.values())))
		newHouse['name'] += '_' + str(tripKey)
		newHouse['parent'] = tMeter['name']
		newHouse['schedule_skew'] = str(random.gauss(2000,500))
		newHouse['floor_area'] = str(500.0 + 0.50*tPower) # Add 500 because very small floor_areas break GLD.
		newHouse['latitude'] = tMeter.get('latitude','0.0')
		newHouse['longitude'] = tMeter.get('longitude','0.0')
		inFeed[maxKey] = newHouse
		maxKey += 1
		for childKey in childrenArchetypes:
			newChild = dict(childrenArchetypes[childKey])
			newChild['name'] += '_' + str(tripKey) + '_' + str(childKey)
			newChild['parent'] = newHouse['name']
			newChild['latitude'] = tMeter.get('latitude','0.0')
			newChild['longitude'] = tMeter.get('longitude','0.0')
			newChild['schedule_skew'] = str(random.gauss(8000,1000))
			inFeed[maxKey] = newChild
			maxKey += 1
		del inFeed[tripKey]


def _tests():
	'''
	testFeedPath = os.path.join(omf.omfDir, 'static', 'testFiles', 'inTest_R4-25.00-1_CLEAN.glm')
	testFeed = feeder.parse(testFeedPath)
	addScaledRandomHouses(testFeed)
	outFilePath = os.path.join(omf.omfDir, 'static', 'testFiles', 'inTest_R4_modified.glm')
	with open(outFilePath,'w+') as outFile:
		outFile.write(feeder.sortedWrite(testFeed))
	tests = [
		('Arlington test 1:', (38.883611, -77.088899)), # 916 N Cleveland St
		('Arlington test 2:', (38.883565, -77.090033)), # 914 N Danville St
		('Arlington test 3:', (38.88315759, -77.0879)), # 2507 9th St N
	]
	for test in tests:
		components = _get_address_components_from_coordinates(*test[1])
		print(test[0], _get_zillow_house_specs(components['street_number'], components['zip_code']), '\n')
	tests = [
		('Arlington test 1:', (38.883611, -77.088899)), # 916 N Cleveland St
		('Arlington test 2:', (38.883565, -77.090033)), # 914 N Danville St
		('Arlington test 3:', (38.88315759, -77.0879)) # 2507 9th St N
	]
	for test in tests:
		print(test[0], get_zillow_configured_new_house(*test[1]), '\n')
	print(get_random_new_house())
	print('Apt test:', get_zillow_configured_new_house(address='3444 N Fairfax Dr, Arlington, VA 22201, USA'))
	print('Error test:', get_zillow_configured_new_house(10000, 10000)) # None
	'''
	pass # Zillow API is blocking us.


if __name__ == '__main__':
	_tests()