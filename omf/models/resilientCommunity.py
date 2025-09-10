''' Calculates Social Vulnerability for a given Circuit '''
# warnings.filterwarnings("ignore")
from logging import raiseExceptions
import urllib.request
import shutil, datetime
from os.path import join as pJoin
import requests
import zipfile
#import shapefile
from io import BytesIO
import numpy as np
import json
import math
import pandas as pd
from shapely.geometry import Polygon, Point
import geopandas as gpd
import networkx as nx
import time

# OMF imports
from omf import geo
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

from omf.solvers.opendss import *
from omf.comms import *
from omf.solvers.opendss.dssConvert import *
from omf.solvers.opendss.dssConvert import _dssToOmd_toBeTested as dssToOmd
from omf.solvers.opendss.dssConvert import _evilDssTreeToGldTree_toBeTested as evilDssTreeToGldTree
from omf.solvers.opendss.dssConvert import _treeToDss_toBeTested as treeToDss
from omf.solvers.opendss.dssConvert import _dss_to_clean_via_save_toBeTested as dss_to_clean_via_save

# Model metadata:
tooltip = "Determines the most vulnerable areas and pieces of equipment within a circuit "
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

#UNUSED
def retrieveCensusNRI():
	'''
	Retrieves necessary data from ZIP File and exports to geojson
	Input: dataURL -> URL to retrieve data from
	returns geojson of census NRI data
	'''
	try:
		#headers
		hdr = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko)  Chrome/23.0.1271.64 Safari/537.11','Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3','Accept-Encoding': 'none','Accept-Language': 'en-US,en;q=0.8','Connection': 'keep-alive'}
		#FEMA nri data url
		nridataURL = "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload//NRI_Shapefile_CensusTracts/NRI_Shapefile_CensusTracts.zip"
		r = requests.get(nridataURL, headers=hdr)
		z = zipfile.ZipFile(BytesIO(r.content))
		# get file names needed to build geoJSON
		shpPath = [x for x in z.namelist() if x.endswith('.shp')][0]
		dbfPath = [x for x in z.namelist() if x.endswith('.dbf')][0]
		prjPath = [x for x in z.namelist() if x.endswith('.prj')][0]
		# create geojson from datafiles
		with shapefile.Reader(shp=BytesIO(z.read(shpPath)), dbf=BytesIO(z.read(dbfPath)), prj=BytesIO(z.read(prjPath))) as shp:
			geojson_data = shp.__geo_interface__
			outfile = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database_MAR2023.json')
			with open(outfile, 'w') as f:
				json.dump(geojson_data, f,indent=4)
				return outfile
	except Exception as e:
		print("Error trying to retrieve FEMA NRI Census Data in GeoJson format")
		print(e)

def findCensusBlockGroup(lat,lon):
	'''
	Finds Census Block at a given lon / lat incorporates US Census Geolocator API
	Input: lat -> specified latitude value
	Input: lon -> specified longitude value
	return censusBlockGroup ->  census block group found at location
	'''
	try:
		# Requested for API Key to bypass api load limits
		request_url = "https://geo.fcc.gov/api/census/block/find?latitude="+str(lat)+"&longitude="+str(lon)+ "&censusYear=2020&format=json&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
		opener = urllib.request.build_opener()
		opener.addheaders = [('User-agent', 'Mozilla/5.0')]
		resp = opener.open(request_url, timeout=100)
		censusJson = json.loads(resp.read())
		censusBlockGroup = censusJson['Block']['FIPS'][:-3]
		return  censusBlockGroup
	except Exception as e:
		print("Error trying to retrieve block group information from Census API")
		print(e)

def repeatFindCensusBlockGroup(lat, long, lim=10, wait=3):
	''' Repeatedly attempts to retrieve census blockgroup, returning the info as soon as it is successful, and raising an exception after a certain number of attempts.
		Args:
			Input: lat -> specified latitude value
			Input: lon -> specified longitude value
			Input: lim -> num attempts before an exception is raised
			Input: wait -> num sec between attempts to avoid overwhelming server
		Return: censusBlockGroup ->  census Tract found at location
	'''
	for i in range(0,lim):
		censusBlockGroup = findCensusBlockGroup(lat,long)
		if censusBlockGroup:
			break
		elif i == lim-1:
			raise Exception(f'ERROR - Could not get census block group in {lim} calls to the server')
		else:
			time.sleep(wait)
	return censusBlockGroup

#UNUSED (EXCEPT IN OTHER UNUSED FUNCTION)
def transform(coordList):
	'''
	transform coordinates from WGS_1984_Web_Mercator_Auxiliary_Sphere(EPSG 3857) to EPSG:4326
	Input: coordList -> list of coordinates (geometry)
	return coordList -> transformed coordinates
	'''
	for idx, i in enumerate(coordList):
		lat,lon = i[0], i[1]
		x = (lat * 180) / 20037508.34
		y = (lon * 180) / 20037508.34
		y = (math.atan(math.pow(math.e, y * (math.pi / 180))) * 360) / math.pi - 90
		coordList[idx] = [x,y]
		
	return coordList

#UNUSED
def runTransformation(geos):
	'''
	runs transformations for a list of geometries
	Input: geos -> list of geometry
	return geoTransformed -> transofrmed list of geometries
	'''
	geoTransformed = []
	for i in geos:
		if (isinstance(i[0][0], float)):
			geoTransformed.append(transform(i))
		else:
			geoTransformed.append(transform(i[0]))
	return geoTransformed

def createDF(tractData, columns, geoTransformed):
	'''
	Creates Pandas DF from list of data containing GeoData 
	input: tractData -> Data associated with data
	input: columns -> columns for data
	input: geoTransformed -> EPSG:4326 transformed geometry
	'''
	data = pd.DataFrame(tractData, columns = columns)
	#print(data)
	#print(data.T)
	if (geoTransformed):
		data['geometry'] = geoTransformed
	return data

def createGeoDF(df):
	'''
	Creates GeoPandas DF From pandas DF
	input: df -> pandas df
	return geo -> geodataframe
	'''
	df['geometry'] = df['geometry'].apply(Polygon)
	geo = gpd.GeoDataFrame(df, geometry=df["geometry"], crs="EPSG:4326")
	return geo

def getCoopData(coopgeoJson):
	'''
	Retrieves Cooperative Data From Geo Json and saves to lists to be converted to DataFrame
	coopgeoJson -> cooperative geojson
	returns list of cooperative data, geometry, and column names for the cooperative data
	'''
	data = []
	geom = []
	for i in coopgeoJson['features']:
		currData = (i['properties']['Member_Class'], i['properties']['Cooperative'], i['properties']['Data_Source'],i['properties']['Data_Year'],i['properties']['Shape_Length'], i['properties']['Shape_Area'])
		if (i['geometry']['type'] == 'Polygon'):
			data.append(currData)
			geom.append(i['geometry']['coordinates'][0])
		elif (i['geometry']['type'] == 'MultiPolygon'):
			for j in i['geometry']['coordinates']:
				data.append(currData)
				geom.append(j[0])
	columns = ['Member_Class', 'Cooperative', 'Data_Source','Data_Year','Shape_Length', 'Shape_Area']
	return data, geom, columns

#UNUSED
def getCoopFromList(coopgeoJson, listOfCoops):
	'''
	Gets data for a list of coops
	coopgeoJson -> Coop data
	listOfCoops -> list of cooperatives interested 
	
	'''
	coopData, coopGeo, columns = getCoopData(coopgeoJson)
	coopDF = createDF(coopData,  columns, coopGeo)
	geocoopDF = createGeoDF(coopDF[coopDF['Member_Class'] == 'Distribution'] )
	listOfCoopsDF = geocoopDF[geocoopDF['Cooperative'].isin(listOfCoops)]
	return listOfCoopsDF

#UNUSED
def coopvcensusDF(coopDF, geonriDF):
	'''
	Relates census tract data to cooperative data
	coopDF -> cooperative datafrme
	geonriDF -> nri dataframe
	returns dataframe containing relevant columns and 
	'''
	values = []
	geom = []
	columns = ['Cooperative_Name', 'BUILDVALUE','AGRIVALUE','EAL_VALT','EAL_VALB','EAL_VALP','EAL_VALA','SOVI_SCORE','SOVI_RATNG','RESL_RATNG','RESL_VALUE','AVLN_AFREQ','CFLD_AFREQ','CWAV_AFREQ','DRGT_AFREQ','ERQK_AFREQ','HAIL_AFREQ','HWAV_AFREQ','HRCN_AFREQ','ISTM_AFREQ','LNDS_AFREQ','LTNG_AFREQ','RFLD_AFREQ','SWND_AFREQ','TRND_AFREQ','TSUN_AFREQ','VLCN_AFREQ','WFIR_AFREQ','WNTW_AFREQ']
	for index, row in coopDF.iterrows():
		for j in row['censusTracts']:
			# object information
			#Shape = geonriDF.loc[j]['Shape']
			if(j not in list(geonriDF.index)):
				continue
			BUILDVALUE = geonriDF.loc[j]['BUILDVALUE'] / geonriDF.loc[j]['Shape_Area'] #Building Value
			AGRIVALUE = geonriDF.loc[j]['AGRIVALUE']/ geonriDF.loc[j]['Shape_Area'] #Agriculture Value
			#Exp annual loss metrics
			EAL_VALT = geonriDF.loc[j]['EAL_VALT']/ geonriDF.loc[j]['Shape_Area'] # Expected Annual Loss - Total - Composite
			EAL_VALB = geonriDF.loc[j]['EAL_VALB'] / geonriDF.loc[j]['Shape_Area']# Expected Annual Loss - Building Value - Composite
			EAL_VALP = geonriDF.loc[j]['EAL_VALP']/ geonriDF.loc[j]['Shape_Area'] # Expected Annual Loss - Population - Composite
			EAL_VALA = geonriDF.loc[j]['EAL_VALA']/ geonriDF.loc[j]['Shape_Area'] # Expected Annual Loss - Agriculture Value - Composite
			# Social Vulnerabultiy
			SOVI_SCORE = geonriDF.loc[j]['SOVI_SCORE']/ geonriDF.loc[j]['Shape_Area'] # Social Vulnerability - Score
			SOVI_RATNG = geonriDF.loc[j]['SOVI_RATNG'] # Social Vulnerability - Rating
			# Community Resilience
			RESL_RATNG = geonriDF.loc[j]['RESL_RATNG']# Community Resilience - Rating
			RESL_VALUE = geonriDF.loc[j]['RESL_VALUE']/ geonriDF.loc[j]['Shape_Area'] # Community Resilience - Value
			# Weather/ Natural Disaster Risk
			#Avalanche
			AVLN_AFREQ = geonriDF.loc[j]['AVLN_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Avalanche - Annualized Frequency
			# Coastal Flooding
			CFLD_AFREQ = geonriDF.loc[j]['CFLD_AFREQ'] / geonriDF.loc[j]['Shape_Area']# Coastal Flooding - Annualized Frequency
			# Cold Wave
			CWAV_AFREQ= geonriDF.loc[j]['CWAV_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Cold Wave - Annualized Frequency
			#Drought
			DRGT_AFREQ=geonriDF.loc[j]['DRGT_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Drought - Annualized Frequency
			#EarthQuakes
			ERQK_AFREQ=geonriDF.loc[j]['ERQK_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Earthquake - Annualized Frequency
			#Hail
			HAIL_AFREQ=geonriDF.loc[j]['HAIL_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Hail - Annualized Frequency
			#Heat Wave
			HWAV_AFREQ=geonriDF.loc[j]['HWAV_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Heat Wave - Annualized Frequency
			#Hurricane
			HRCN_AFREQ= geonriDF.loc[j]['HRCN_AFREQ'] / geonriDF.loc[j]['Shape_Area']# Hurricane - Annualized Frequency
			# Ice Storm
			ISTM_AFREQ= geonriDF.loc[j]['ISTM_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Ice Storm - Annualized Frequency
			#LandSlide
			LNDS_AFREQ= geonriDF.loc[j]['LNDS_AFREQ'] / geonriDF.loc[j]['Shape_Area']# Landslide - Annualized Frequency
			#Lightning
			LTNG_AFREQ=geonriDF.loc[j]['LNDS_EVNTS'] / geonriDF.loc[j]['Shape_Area']# Lightning - Annualized Frequency
			#Riverline Flooding
			RFLD_AFREQ = geonriDF.loc[j]['RFLD_AFREQ'] / geonriDF.loc[j]['Shape_Area']# Riverine Flooding - Annualized Frequency
			#Strong Wind
			SWND_AFREQ= geonriDF.loc[j]['SWND_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Strong Wind - Annualized Frequency
			#Tornado
			TRND_AFREQ=geonriDF.loc[j]['TRND_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Tornado - Annualized Frequency
			#Tsunami
			TSUN_AFREQ= geonriDF.loc[j]['TSUN_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Tsunami - Annualized Frequency
			#Volcanic Activity
			VLCN_AFREQ= geonriDF.loc[j]['VLCN_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Volcanic Activity - Annualized Frequency
			#Wildfire
			WFIR_AFREQ= geonriDF.loc[j]['WFIR_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Wildfire - Annualized Frequency
			#Winter Weather
			WNTW_AFREQ= geonriDF.loc[j]['WNTW_AFREQ']/ geonriDF.loc[j]['Shape_Area'] # Winter Weather - Annualized Frequency
			rowVals = [row['Cooperative'],BUILDVALUE,AGRIVALUE,EAL_VALT,EAL_VALB,EAL_VALP,EAL_VALA,SOVI_SCORE,SOVI_RATNG,RESL_RATNG,RESL_VALUE,AVLN_AFREQ,CFLD_AFREQ,CWAV_AFREQ,DRGT_AFREQ,ERQK_AFREQ,HAIL_AFREQ,HWAV_AFREQ,HRCN_AFREQ,ISTM_AFREQ,LNDS_AFREQ,LTNG_AFREQ,RFLD_AFREQ,SWND_AFREQ,TRND_AFREQ,TSUN_AFREQ,VLCN_AFREQ,WFIR_AFREQ,WNTW_AFREQ]
			values.append(rowVals)
			geom.append(row['geometry'])
			finalDF = createDF(values, columns, geom)
			return finalDF.set_index('Cooperative_Name')		 

def all_vals(obj):
	''' helper method that retrieves all values in nested dictionary'''
	if isinstance(obj, dict):
		for v in obj.values():
			yield from all_vals(v)
	else:
		yield obj

def getPercentile(loads, columnName, tieBreaker=None):
	"""
	Gets percentile of specified column, resolving ties with an optional tie-breaker.

	Args:
		loads (dict): Dictionary of loads with their attributes.
		columnName (str): The name of the column to calculate percentiles for.
		tieBreaker (str, optional): Column name used for tie-breaking. Defaults to None.

	Raises:
		ValueError: If `loads` is not a dictionary or if `columnName` is missing from the loads.
		ValueError: If the lengths of primary and tieBreaker values don't match.
	"""
	# Validate inputs
	if not isinstance(loads, dict):
		raise ValueError("The 'loads' argument must be a dictionary.")
	if not isinstance(columnName, str) or not columnName:
		raise ValueError("The 'columnName' argument must be a non-empty string.")
	if tieBreaker and not isinstance(tieBreaker, str):
		raise ValueError("The 'tieBreaker' argument must be a string if provided.")
	# Retrieve column values and handle missing data
	loadServedVals = [v.get(columnName) for k, v in loads.items()]
	if None in loadServedVals:
		raise ValueError(f"Missing values detected in column '{columnName}'.")
	# Retrieve tie-breaker values or default to zeros
	if tieBreaker:
		tieBreakerVals = [v.get(tieBreaker, 0) for k, v in loads.items()]
		if None in tieBreakerVals:
			raise ValueError(f"Missing values detected in tie-breaker column '{tieBreaker}'.")
	else:
		tieBreakerVals = [0] * len(loads)
	# Ensure consistent lengths
	if len(loadServedVals) != len(tieBreakerVals):
		raise ValueError("Mismatch in lengths of primary and tie-breaker values.")
	# Create pairs of (primary value, tie-breaker, original index)
	pairs = list(zip(loadServedVals, tieBreakerVals, range(len(loadServedVals))))
	# Sort pairs by primary value, then by tie-breaker
	pairs.sort(key=lambda p: (p[0], p[1]))
	# Calculate percentiles
	# TODO: Implement percentile calculation that ranks things identically if no tie breaker exists (rather than effectively using original order as tie-breaker by default)
	result = [0 for _ in range(len(loadServedVals))]
	for rank in range(len(loadServedVals)):
		original_index = pairs[rank][2]
		result[original_index] = rank * 100.0 / (len(loadServedVals) - 1) if len(loadServedVals)-1 != 0 else 100
	# Assign percentiles to the loads dictionary
	if columnName == "base crit score":
		new_str = 'base crit index'
	else:
		new_str = 'community crit index'
	for i, (k, v) in enumerate(loads.items()):
		if not isinstance(v, dict):
			raise ValueError(f"Invalid load format for key '{k}'. Expected a dictionary.")
		loads[k][new_str] = result[i]

def coordCheck(long, lat, geoList):
	"""
	Check if a point defined by longitude and latitude intersects any polygons in a given geospatial list.
	
	Args:
		long (float): Longitude of the point.
		lat (float): Latitude of the point.
		geoList (dict): A dictionary containing geospatial data, where keys represent identifiers
						and values include a 'geometry' key with a list of polygon coordinates.
	
	Returns:
		str: The key of the geospatial entry that the point intersects with, or an empty string if none.
	"""
	try:
		# Ensure valid input types
		if not isinstance(long, (int, float)):
			raise ValueError("Longitude must be a number.")
		if not isinstance(lat, (int, float)):
			raise ValueError("Latitude must be a number.")
		if not isinstance(geoList, dict):
			raise ValueError("geoList must be a dictionary.")
		# Create a point from the given coordinates
		point = Point(long, lat)
		# Iterate through the geospatial list
		for k, v in geoList.items():
			if 'geometry' not in v or not isinstance(v['geometry'], list):
				raise KeyError(f"Missing or invalid 'geometry' key in entry {k}.")
			# Handle single polygon or list of polygons
			if len(v['geometry']) == 1:
				coords = v['geometry'][0]
			else:
				coords = v['geometry']
			# Check if the polygon intersects with the point
			try:
				poly = Polygon(coords)
				if poly.intersects(point):
					return k
			except Exception as e:
				# Handle potential errors in creating or processing polygons
				print(f"Error processing polygon for key {k}: {e}")
				continue
		# Return an empty string if no intersection is found
		return ''
	except Exception as e:
		print(f"Error in coordCheck: {e}")
		return ''

def getPowerMeasures(ob):
	''' Retrieves kw, kvar, and kva from a load object
		Input: ob -> a load object 
		Return: -> [kw, kvar, kva]
	'''
	kw = ob.get('kw',None)
	kvar = ob.get('kvar',None)
	kva = ob.get('kva',None)
	pf = ob.get('pf',None)
	if kw and kvar:
		kw = float(kw)
		kvar = float(kvar)
		kva = math.sqrt(kw**2 + kvar**2)
	elif kw and pf:
		kw = float(kw)
		kva = kw/float(pf)
		kvar = math.sqrt(kva**2 - kw**2)
	elif kva and pf:
		kw = float(kva)*float(pf)
		kva = float(kva)
		kvar = math.sqrt(kva**2 + kw**2)
	else:
		raise Exception(f'Load {ob["name"]} does not have necessary information to calculate kw, kva, and kvar')
	return kw, kvar, kva

def getDownLineLoadsEquipmentBlockGroup(pathToOmd, equipmentList,avgPeakDemand, pathToLoadsFile, pathToZillowData = None, useZillowData=False):
	'''
	Retrieves downline loads for specific set of equipment and retrieve nri data for each of the equipment, optionally using zillow data.
	pathToOmd -> path to the omdfile
	equipmentList -> list of equipment of interest
	'''
	# iterate throughout circuit
	# store census information
	omd = json.load(open(pathToOmd))
	loadsDF = pd.read_csv(pathToLoadsFile)
	blockgroupDict = {}
	loadsDict = {}
	valList = []
	geoms = []
	obDict = {}
	
	# DO NOT CHANGE ORDER -> matches order of dictionary in buildSVI(TractFIPS)
	cols = ['pct_Prs_Blw_Pov_Lev_ACS_16_20','pct_Civ_emp_16p_ACS_16_20','avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
			'pct_Pop_65plus_ACS_16_20','pct_u19ACS_16_20','pct_Pop_Disabled_ACS_16_20','pct_singlefamily_u18','pct_MLT_U10p_ACS_16_20',
			'pct_Mobile_Homes_ACS_16_20','pct_Crowd_Occp_U_ACS_16_20','pct_noVehicle','blockgroupFIPS', 'geometry']
	pctile_list = ['pct_Prs_Blw_Pov_Lev_ACS_16_20','pct_Civ_emp_16p_ACS_16_20','avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
			'pct_Pop_65plus_ACS_16_20','pct_u19ACS_16_20','pct_Pop_Disabled_ACS_16_20','pct_singlefamily_u18','pct_MLT_U10p_ACS_16_20',
			'pct_Mobile_Homes_ACS_16_20','pct_Crowd_Occp_U_ACS_16_20','pct_noVehicle']
	
	# Helper function with informative error catching
	def loadIsResidential(loadsDF,obName):
		''' Checks if there's a single entry for a load in the Customer Information file and if so, returns whether it's residential or not.'''
		loadRowsDf = loadsDF[loadsDF["Load Name"] == obName]
		if len(loadRowsDf) > 1:
			raise Exception(f"ERROR: Your Customer Information (.csv file) contains more than 1 entry for the load {obName}")
		elif len(loadRowsDf) == 0:
			raise Exception(f"ERROR: Your Customer Information (.csv file) contains no entry for the load {obName}")
		else:
			return loadRowsDf["Business Type"].iloc[0].lower() == 'residential'

	# Section code
	sectionsDict, distanceDict, totalSections = runSections(pathToOmd, omd)
	# Retrieve data to compute SVI
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		obDict[key] = ob
		from_field = ob.get('from', None)
		to_field = ob.get('to', None)
		section_key = str((from_field, to_field))
		# Check all three rather than just (section_key in sectionsDict) for robustness 
		# in case, for example, there is a "('bus1',None)" in sectionsDict by some error
		if section_key in sectionsDict and from_field and to_field:
			obDict[key]['section'] = sectionsDict[section_key]
		elif obName in sectionsDict:
			obDict[key]['section'] = sectionsDict[obName]
		else:
			obDict[key]['section'] = None
		if (obType == 'load'):
			if loadIsResidential(loadsDF,obName): 
				loadsDict[key] = {}
				loadsDict[key]['section'] = sectionsDict.get(obName)
				kw, kvar, kva = getPowerMeasures(ob)
				loadsDict[key]['kva'] = kva
				loadsDict[key]["base crit score"] = ((math.sqrt(kw**2 + kvar**2))/ float(avgPeakDemand)) * 4
				loadsDict[key]['distance_from_source'] = int(distanceDict.get(obName, 0))
				long = float(ob['longitude'])
				lat = float(ob['latitude'])
				if blockgroupDict:
					check = coordCheck(long, lat, blockgroupDict)
					if check:
						loadsDict[key]['blockgroup'] = check
						continue
				blockgroup = repeatFindCensusBlockGroup(lat,long)
				loadsDict[key]['blockgroup'] = blockgroup
				blockgroupDict[blockgroup] = buildsviBlockGroup(blockgroup)
				valList.append(list(all_vals(blockgroupDict[blockgroup])))
				geoms.append(blockgroupDict[blockgroup]['geometry'])
	
	# compute SVI
	sviDF = createDF(valList, cols, geoms)
	for i in cols:
		if i not in ['blockgroupFIPS', 'geometry']:
			new_str = i + '_pct_rank'
			sviDF[new_str] = sviDF[i].rank(pct=True)
			pctile_list.append(new_str)
	sviDF['SOVI_TOTAL']= sviDF[pctile_list].sum(axis=1)
	sviDF['SOVI_SCORE'] = sviDF['SOVI_TOTAL'].rank(pct=True)
	sviDF['SOVI_RATNG'] = sviDF.apply(buildSVIRating, axis=1)
	
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		if (obType == 'load'):
			if loadIsResidential(loadsDF,obName): 
				currBlockGroup = loadsDict[key]['blockgroup']
				svi_score = sviDF[sviDF['blockgroupFIPS'] == currBlockGroup]['SOVI_SCORE'].values[0]
				loadsDict[key]['SOVI_SCORE'] = svi_score
				if useZillowData:
					with open(pathToZillowData, 'r') as file:
						zillowPrices = json.load(file)
					avgZillowPrice = zillowPrices[currBlockGroup]['avgPrice']
					loadsDict[key]['zillow price'] = avgZillowPrice
					loadsDict[key]["community crit score"] = (loadsDict[key]["base crit score"] * svi_score) / (avgZillowPrice/10000)
					loadsDict[key]["affluence score"] = avgZillowPrice / 1000
				else:
					loadsDict[key]["community crit score"] = (loadsDict[key]["base crit score"] * svi_score)
	if not loadsDict:
		raise Exception('No loads labeled as Residential in Customer Information (.csv file). SVI only applies to residential loads.')
	getPercentile(loadsDict, "base crit score", 'distance_from_source')
	getPercentile(loadsDict, 'community crit score', 'distance_from_source')
	
	# calculate loads data for blockgroups
	df_loads = pd.DataFrame(loadsDict).T
	df_loads.rename(columns={"blockgroup": "blockgroupFIPS"}, inplace=True)
	if useZillowData:
		# Group by 'blockgroup' and calculate desired metrics
		newdf_loads = df_loads.groupby('blockgroupFIPS').agg(
			avg_BCS=('base crit score', 'mean'),
			avg_CCS=('community crit score', 'mean'),
			avg_BCI=('base crit index', 'mean'),
			avg_CCI=('community crit index', 'mean'),
			avg_zillow_price=('zillow price', 'mean'),
			load_count=('base crit score', 'count'),
			load_amount=('kva', 'sum')
			).reset_index()
		newsviDF = sviDF.merge(newdf_loads, on="blockgroupFIPS", how="left")
		newsviDFcols = newsviDF.columns.tolist()
		newsviDFcols = newsviDFcols[-9:]+newsviDFcols[0:-9]
		newsviDF = newsviDF[newsviDFcols]
		sviGeoDF = createGeoDF(newsviDF)
		newsviDF = newsviDF.drop(columns=['geometry'])
		# Group by 'section' and calculate desired metrics
		section_loads = df_loads.groupby('section').agg(
			avg_BCS=('base crit score', 'mean'),
			avg_CCS=('community crit score', 'mean'),
			avg_BCI=('base crit index', 'mean'),
			avg_CCI=('community crit index', 'mean'),
			avg_zillow_price=('zillow price', 'mean'),
			avg_svi_score=('SOVI_SCORE', 'mean'),
			load_count=('base crit score', 'count'),
			load_amount=('kva', 'sum')
			).reset_index()
	else:
		# Group by 'blockgroup' and calculate desired metrics
		newdf_loads = df_loads.groupby('blockgroupFIPS').agg(
			avg_BCS=('base crit score', 'mean'),
			avg_CCS=('community crit score', 'mean'),
			avg_BCI=('base crit index', 'mean'),
			avg_CCI=('community crit index', 'mean'),
			load_count=('base crit score', 'count'),
			load_amount=('kva', 'sum')
			).reset_index()
		newsviDF = sviDF.merge(newdf_loads, on="blockgroupFIPS", how="left")
		newsviDFcols = newsviDF.columns.tolist()
		newsviDFcols = newsviDFcols[-8:]+newsviDFcols[0:-8]
		newsviDF = newsviDF[newsviDFcols]
		sviGeoDF = createGeoDF(newsviDF)
		newsviDF = newsviDF.drop(columns=['geometry'])
		# Group by 'section' and calculate desired metrics
		section_loads = df_loads.groupby('section').agg(
			avg_BCS=('base crit score', 'mean'),
			avg_CCS=('community crit score', 'mean'),
			avg_BCI=('base crit index', 'mean'),
			avg_CCI=('community crit index', 'mean'),
			avg_svi_score=('SOVI_SCORE', 'mean'),
			load_count=('base crit score', 'count'),
			load_amount=('kva', 'sum')
			).reset_index()
	# Leave 'SOVI_RATING' out of this becasuse it's dealt with elsewhere
	readableColsDict = {	'pct_Prs_Blw_Pov_Lev_ACS_16_20': '_____________% Individuals Below Poverty Level',
							'pct_Civ_emp_16p_ACS_16_20': '_____________% Age 16+ Employed',
							'avg_Agg_HH_INC_ACS_16_20': '_____________Per Capita Income (USD)',
							'pct_Not_HS_Grad_ACS_16_20': '_____________% Non-HS Grads',
							'pct_Pop_65plus_ACS_16_20': '_____________% Age 65+',
							'pct_u19ACS_16_20': '_____________% Non-Instituionalized Below Age 19',
							'pct_Pop_Disabled_ACS_16_20': '_____________% Individuals Disabled',
							'pct_singlefamily_u18': '_____________% Single Parent Families',
							'pct_MLT_U10p_ACS_16_20': '_____________% Multi-Unit Structure',
							'pct_Mobile_Homes_ACS_16_20': '_____________% Mobile Home',
							'pct_Crowd_Occp_U_ACS_16_20': '_____________% Crowding',
							'pct_noVehicle': '_____________% No Vehicle',
							'pct_Prs_Blw_Pov_Lev_ACS_16_20_pct_rank': '_____________% Individuals Below Poverty Level (%ile)',
							'pct_Civ_emp_16p_ACS_16_20_pct_rank': '_____________% Age 16+ Employed (%ile)',
							'avg_Agg_HH_INC_ACS_16_20_pct_rank': '_____________Per Capita Income (USD) (%ile)',
							'pct_Not_HS_Grad_ACS_16_20_pct_rank': '_____________% Non-HS Grads (%ile)',
							'pct_Pop_65plus_ACS_16_20_pct_rank': '_____________% Age 65+ (%ile)',
							'pct_u19ACS_16_20_pct_rank': '_____________% Non-Instituionalized Below Age 19 (%ile)',
							'pct_Pop_Disabled_ACS_16_20_pct_rank': '_____________% Individuals Disabled (%ile)',
							'pct_singlefamily_u18_pct_rank': '_____________% Single Parent Families (%ile)',
							'pct_MLT_U10p_ACS_16_20_pct_rank': '_____________% Multi-Unit Structure (%ile)',
							'pct_Mobile_Homes_ACS_16_20_pct_rank': '_____________% Mobile Home (%ile)',
							'pct_Crowd_Occp_U_ACS_16_20_pct_rank': '_____________% Crowding (%ile)',
							'pct_noVehicle_pct_rank': '_____________% No Vehicle (%ile)',
							'SOVI_TOTAL': '_____________SVI Total',
							'blockgroupFIPS': '_____________blockgroupFIPS',
							'SOVI_SCORE': 'SVI',
							'avg_BCS': 'Avg BCS',
							'avg_CCS': 'Avg CCS',
							'avg_BCI': 'Avg BCI',
							'avg_CCI': 'Avg CCI',
							'load_count': 'Load Count',
							'load_amount': 'Load Amount'}
	sviGeoDF = sviGeoDF.rename(columns=readableColsDict)
	# Convert existing sections to a set for quick lookup
	existing_sections = set(section_loads['section'])
	# Iterate from 1 to totalSections to check for missing sections
	for section in range(1, totalSections + 1):  # Inclusive range
		if section not in existing_sections:
			# Append a row with all metrics set to None
			section_loads = pd.concat([
				section_loads,
				pd.DataFrame({
					'section': [section],
					'avg_BCS': [None],
					'avg_CCS': [None],
					'avg_BCI': [None],
					'avg_CCI': [None],
					'avg_zillow_price': [None],
					'load_count': [None],
					'avg_svi_score':[None],
					'load_amount': [None]
				})
			], ignore_index=True)
	# Sort the DataFrame by 'section' to maintain order
	section_loads = section_loads.sort_values(by='section').reset_index(drop=True)	
	del omd
	digraph = createGraph(pathToOmd)
	nodes = digraph.nodes()
	namesToKeys = {v.get('name'):k for k,v in obDict.items()} 
	for obKey, ob in obDict.items():
		obType = ob['object']
		obName = ob['name']
		obTo = ob.get('to')
		if obName in nodes:
			startingPoint = obName
		elif obTo in nodes:
			startingPoint = obTo
		else:
			continue
		successors = nx.dfs_successors(digraph, startingPoint).values()
		ob['downlineObs'] = []
		ob['downlineLoads'] = []
		if obType in equipmentList:
			for listofVals in successors:
				for element in listofVals:
					elementKey = namesToKeys.get(element)
					elementType = elementKey.split('.')[0]
					if elementKey not in ob['downlineObs']:
						ob['downlineObs'].append(elementKey)
					if elementKey not in ob['downlineLoads'] and elementType == 'load':
						ob['downlineLoads'].append(elementKey)
	filteredObDict = {k:v  for k,v in obDict.items() if v.get('object') in equipmentList}
	# add metrics to equipment based on downline loads
	calcEquipmentMetrics(filteredObDict, loadsDict)
	return filteredObDict,loadsDict, sviGeoDF, newsviDF, section_loads

#UNUSED
def getDownLineLoadsBlockGroup(pathToOmd, avgPeakDemand):
	'''
	Retrieves downline loads for a circuit and retrieves nri data for each of the loads within the circuit
	pathToOmd -> path to the omdfile
	'''
	omd = json.load(open(pathToOmd))
	blockgroupDict = {}
	loadsDict = {}
	valList = []
	geoms = []
	obDict = {}
	# Retrieve data to compute SVI
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		obDict[key] = ob
		if (obType == 'load'):
			loadsDict[key] = {"base crit score":None}
			kw = float(ob['kw'])
			kvar = float(ob['kvar']) if ob['kvar'] is not None else kw/avgPeakDemand
			kv = float(ob['kv'])
			loadsDict[key]["base crit score"]= ((math.sqrt((kw * kw) + (kvar * kvar) ))/ (avgPeakDemand)) * 4
			long = float(ob['longitude'])
			lat = float(ob['latitude'])
			if blockgroupDict:
				check = coordCheck(long, lat, blockgroupDict)
				if check:
					loadsDict[key]['blockgroup'] = check
					continue
				else:
					blockgroup = findCensusBlockGroup(lat,long)
			else:
				blockgroup = findCensusBlockGroup(lat,long)
			# Following replaces a potentially infinite loop. Whether it's necessary at all though should be investigated
			blockgroup = repeatFindCensusBlockGroup(lat,long)
			loadsDict[key]['blockgroup'] = blockgroup
			blockgroupDict[blockgroup] = buildsviBlockGroup(blockgroup)
			valList.append(list(all_vals(blockgroupDict[blockgroup])))
			geoms.append(blockgroupDict[blockgroup]['geometry'])
	# compute SVI
	# DO NOT CHANGE ORDER -> matches order of dictionary in buildSVI(blockgroupFIPS)
	cols = ['pct_Prs_Blw_Pov_Lev_ACS_16_20','avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
			'pct_Pop_65plus_ACS_16_20','pct_u19ACS_16_20','pct_singlefamily_u18','pct_MLT_U10p_ACS_16_20',
			'pct_Mobile_Homes_ACS_16_20','pct_Crowd_Occp_U_ACS_16_20','pct_noVehicle','blockgroupFIPS', 'geometry']
	sviDF = createDF(valList,cols, geoms)
	pctile_list = ['pct_Prs_Blw_Pov_Lev_ACS_16_20','avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
			'pct_Pop_65plus_ACS_16_20','pct_u19ACS_16_20','pct_singlefamily_u18','pct_MLT_U10p_ACS_16_20',
			'pct_Mobile_Homes_ACS_16_20','pct_Crowd_Occp_U_ACS_16_20','pct_noVehicle']
	for i in cols:
		if i not in ['blockgroupFIPS', 'geometry']:
			new_str = i + '_pct_rank'
			sviDF[new_str] = sviDF[i].rank(pct=True)
			pctile_list.append(new_str)
	sviDF['SOVI_TOTAL']= sviDF[pctile_list].sum(axis=1)
	sviDF['SOVI_SCORE'] = sviDF['SOVI_TOTAL'].rank(pct=True)
	#sviDF['SOVI_SCORE'] = sviDF[pctile_list].sum(axis=1).rank(pct=True)
	sviDF['SOVI_RATNG'] = sviDF.apply(buildSVIRating, axis=1)
	#sviDF.to_csv('outSVI.csv', index=False)
	sviGeoDF = createGeoDF(sviDF)
	# put all
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		if (obType == 'load'):
			currBlockGroup = loadsDict[key]['blockgroup']
			svi_score = sviDF[sviDF['blockgroupFIPS'] == currBlockGroup]['SOVI_SCORE'].values[0]
			loadsDict[key]["community crit score"] = loadsDict[key]["base crit score"] *  svi_score
			loadsDict[key]['SOVI_SCORE'] = svi_score
	getPercentile(loadsDict, "base crit score")
	getPercentile(loadsDict, 'community crit score')
	del omd
	digraph = createGraph(pathToOmd)
	nodes = digraph.nodes()
	namesToKeys = {v.get('name'):k for k,v in obDict.items()}
	for obKey, ob in obDict.items():
		obType = ob['object']
		obName = ob['name']
		obTo = ob.get('to')
		if obName in nodes:
			startingPoint = obName
		elif obTo in nodes:
			startingPoint = obTo
		else:
			continue
		successors = nx.dfs_successors(digraph, startingPoint).values()
		ob['downlineObs'] = []
		ob['downlineLoads'] = []
		for listofVals in successors:
			for element in listofVals:
				elementKey = namesToKeys.get(element)
				elementType = elementKey.split('.')[0]
				if elementKey not in ob['downlineObs']:
					ob['downlineObs'].append(elementKey)
				if elementKey not in ob['downlineLoads'] and elementType == 'load':
					ob['downlineLoads'].append(elementKey)
	return obDict,loadsDict, sviGeoDF

def calcEquipmentMetrics(obsDict, loadsDict):
	'''
	Calculates bcs, ccs, bci, and cci for equipment on the feeder and adds them to the objects in the input dict obsDict
	
	Args:
		Input: obsDict -> dict of all circuit objects
		Input: loadsDict -> dict of loads
	'''
	for k,v in obsDict.items():
		weights=0
		comm_crit_sum=0
		base_crit_sum = 0
		for j in v['downlineLoads']:
				ob = loadsDict.get(j)
				if ob:
					weights+=ob['SOVI_SCORE']
					comm_crit_sum+=ob['community crit score'] 
					base_crit_sum+=ob['base crit score'] 
		obsDict[k]['base crit score'] = base_crit_sum
		obsDict[k]['community crit score'] = comm_crit_sum/weights if (comm_crit_sum != 0 and weights != 0) else 0
	getPercentile(obsDict, 'base crit score')
	getPercentile(obsDict, 'community crit score')

def addLoadInfoToOmd(loadsDict, omdDict):
	'''
	adds criticality values to omd file for all objects
	loadsDict -> dict of loads
	omdDict -> dict of omd objects
	returns new dict of omd objects
	'''
	for ob in omdDict.get('tree', {}).values():
		if ob['object'] == 'load':
			obType = ob['object']
			obName = ob['name']
			k = obType + '.' + obName
			ob['section'] 				= loadsDict.get(k,{}).get('section')
			ob['base crit score'] 		= loadsDict.get(k,{}).get('base crit score')
			ob['base crit index'] 		= loadsDict.get(k,{}).get('base crit index')
			ob['community crit score'] 	= loadsDict.get(k,{}).get('community crit score')
			ob['community crit index'] 	= loadsDict.get(k,{}).get('community crit index')
		else:
			continue
	return omdDict

def addEquipmentInfoToOmd(obDict, omdDict, equipList):
	'''
	adds criticality values to omd file for all objects
	loadsDict -> dict of loads
	omdDict -> dict of omd objects
	returns new dict of omd objects
	'''
	for ob in omdDict.get('tree', {}).values():
		if (ob['object'] in equipList):
			obType = ob['object']
			obName = ob['name']
			k = obType + '.' + obName
			ob['section'] 				= obDict.get(k,{}).get('section')
			ob['base crit score'] 		= obDict.get(k,{}).get('base crit score')
			ob['base crit index'] 		= obDict.get(k,{}).get('base crit index')
			ob['community crit score'] 	= obDict.get(k,{}).get('community crit score')
			ob['community crit index'] 	= obDict.get(k,{}).get('community crit index')
		else:
			continue
	return omdDict

def createColorCSVBlockGroup(modelDir, loadsDict, objectsDict):
	'''
	Creates colorby CSV to color loads within the circuit
	modelDir -> model directory
	loadsDict -> dict of loads
	'''
	newloadsDict = {k.split('load.')[1]:v for k,v in loadsDict.items()}
	newobjectsDict = {k.split('.')[1]:v for k,v in objectsDict.items()}
	combined_dict = {**newloadsDict, **newobjectsDict}
	new_df = pd.DataFrame.from_dict(combined_dict, orient='index')
	new_df[['base crit score','community crit score','base crit index','community crit index','section']].to_csv(pJoin(modelDir, 'color_by.csv'), index=True)

def buildsviBlockGroup(blockgroupFIPS):
	'''
	Build SVI computation
	block -> blockFIPS code
	'''
	# SVI Components
	# Socioeconomic
	# Household
	# Housing Type

	# SOCIOECONOMIC VARS
	# Name of feature | Feature name (short): Variable name

	# Percent Individuals Below Poverty Level | Poverty level: pct_Prs_Blw_Pov_Lev_ACS_16_20
	# Percent Individuals 16+ Employed | Employed: pct_Civ_emp_16p_ACS_16_20
	# Per capita Income | Income: avg_Agg_HH_INC_ACS_16_20
	# Percent non highschool grads | Highschool: pct_Not_HS_Grad_ACS_16_20

	# HOUSEHOULD COMPOSITION / DISABILITY VARS

	#Percent Age 65+ |Age 65+ : Percentage calculated by dividing Pop_65plus_ACS_16_20 by Tot_Population_ACS_16_20
	# Noninstituionalized People under 19 | under19: Civ_noninst_pop_U19_ACS_16_20
	# Non Instituionalized People | noninstitution: Civ_Noninst_Pop_ACS_16_20
	# Percent population under 19 | under19 : Civ_noninst_pop_U19_ACS_16_20 / Civ_Noninst_Pop_ACS_16_20
	#Percent population disabled | disabled: pct_Pop_Disabled_ACS_16_20
	# <------------------> THESE VARS ARE IN ACS DATASET REST ARE IN PLANNING DATABASE DATASET <---------------->
	# Estimate!!Total:!!6 to 17 years:!!Living with one parent: | singleparent6-17: B23008_021E
	# Estimate!!Total:!!Under 6 years:!!Living with one parent: | singleparentu6: B23008_008E
	# Total single parents with u18 child | singleparentu18: B23008_021E + B23008_008E
	# Total familes | family: B23008_001E
	# Percent of single parent families | singleparent: (B23008_021E + B23008_008E)/(B23008_001E)
	#<------------------>^^^^ THESE VARS ARE IN ACS DATASET REST ARE IN PLANNING DATABASE DATASET^^^^ <---------------->

	# HOUSING / TRANSPORTATION VARS

	# Percent Multi-unitstructure | multi: pct_MLT_U10p_ACS_16_20
	# Percent mobile home | mobile: pct_Mobile_Homes_ACS_16_20
	# Percent crowding | crowd: pct_Crowd_Occp_U_ACS_16_20
	# <------------------> THESE VARS ARE IN ACS DATASET REST ARE IN PLANNING DATABASE DATASET <---------------->
	# People No vehicles | novehicle: B08014_002E
	# Total People | people: B01001_001E
	# Percent non vehicle | (B08014_002E) / (B01001_001E)
	#<------------------>^^^^ THESE VARS ARE IN ACS DATASET REST ARE IN PLANNING DATABASE DATASET^^^^ <---------------->
					#Socioeconomic, household composition, housing /transportation variables
	pdb_svi_vars = ['pct_Prs_Blw_Pov_Lev_ACS_16_20', 'avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
				'Pop_65plus_ACS_16_20', 'Tot_Population_ACS_16_20',
				'pct_MLT_U10p_ACS_16_20', 'pct_Mobile_Homes_ACS_16_20', 'pct_Crowd_Occp_U_ACS_16_20']
				# household composition / disability variables
	acs_svi_vars = ['B23008_021E', 'B23008_008E', 'B23008_001E',
					'B08014_002E','B01001_001E']
	stateID = blockgroupFIPS[:2] # state identifier
	countyID = blockgroupFIPS[2:5] # county identifier
	tractID = blockgroupFIPS[5:11] # tract identifier
	blockID = blockgroupFIPS[11:12] # block identifier
	# SVI computation vals dictionary
	# build url to use api
	acs_request_url = "https://api.census.gov/data/2022/acs/acs5?get=" + ",".join(acs_svi_vars) + "&for=block%20group:" + str(blockID) + "&in=state:"+str(stateID)+"%20county:" +  str(countyID) + "%20tract:" + str(tractID)+"&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	pdb_request_url = "https://api.census.gov/data/2022/pdb/blockgroup?get="+ ",".join(pdb_svi_vars) + "&for=block%20group:" + str(blockID) + "&in=state:"+str(stateID)+"%20county:" +  str(countyID) + "%20tract:" + str(tractID)+"&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	# add url for census tract to add variables that arent in blockgroup
	tractVars = ['pct_Prs_Blw_Pov_Lev_ACS_16_20', 'pct_Civ_emp_16p_ACS_16_20', 'avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
				'Pop_65plus_ACS_16_20', 'Tot_Population_ACS_16_20', 'Civ_noninst_pop_U19_ACS_16_20', 'Civ_Noninst_Pop_ACS_16_20', 'pct_Pop_Disabled_ACS_16_20',
				'pct_MLT_U10p_ACS_16_20', 'pct_Mobile_Homes_ACS_16_20', 'pct_Crowd_Occp_U_ACS_16_20']
	result = [item for item in tractVars if item not in pdb_svi_vars]
	tractpdb_request_url = "https://api.census.gov/data/2022/pdb/tract?get="+ ",".join(result)+ "&for=tract:"+str(tractID)+"&in=state:"+str(stateID)+"%20county:"+ str(countyID) + "&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	#acs  data
	opener = urllib.request.build_opener()
	opener.addheaders = [('User-agent', 'Mozilla/5.0')]
	resp = opener.open(acs_request_url, timeout=50)
	acsJson = json.loads(resp.read())
	acsDict = {k: 0 if v[0] is None else v[0]  for k, *v in zip(*acsJson)}
	#pdb data
	resp = opener.open(pdb_request_url, timeout=50)
	pdbJson = json.loads(resp.read())
	pdbDict = {k: 0 if v[0] is None else v[0]  for k, *v in zip(*pdbJson)}
	# extra tract data
	resp = opener.open(tractpdb_request_url, timeout=50)
	tractpdbJson = json.loads(resp.read())
	tractpdbDict = {k: 0 if v[0] is None else v[0]  for k, *v in zip(*tractpdbJson)}
	combined_dict = {**acsDict, **pdbDict,**tractpdbDict }
	svi_var_dict = {
		# socioeconomic vars
		'pct_Prs_Blw_Pov_Lev_ACS_16_20': float(combined_dict['pct_Prs_Blw_Pov_Lev_ACS_16_20']),
		'pct_Civ_emp_16p_ACS_16_20': float(combined_dict['pct_Civ_emp_16p_ACS_16_20']),
		'avg_Agg_HH_INC_ACS_16_20': float(str(combined_dict['avg_Agg_HH_INC_ACS_16_20']).replace('$', '').replace(',','')),
		'pct_Not_HS_Grad_ACS_16_20': float(combined_dict['pct_Not_HS_Grad_ACS_16_20']),
		# household compisiton/ disability vars
		'pct_Pop_65plus_ACS_16_20': float(combined_dict['Pop_65plus_ACS_16_20'])/float(combined_dict['Tot_Population_ACS_16_20']),
		'pct_u19ACS_16_20': float(combined_dict['Civ_noninst_pop_U19_ACS_16_20'])/float(combined_dict['Civ_Noninst_Pop_ACS_16_20']),
		'pct_Pop_Disabled_ACS_16_20': float(combined_dict['pct_Pop_Disabled_ACS_16_20']),
		'pct_singlefamily_u18': (float(combined_dict['B23008_021E']) + float(combined_dict['B23008_008E']))/max(0.0000000000001,float(combined_dict['B23008_001E'])),
		#housing/transportation
		'pct_MLT_U10p_ACS_16_20': float(combined_dict['pct_MLT_U10p_ACS_16_20']),
		'pct_Mobile_Homes_ACS_16_20': float(combined_dict['pct_Mobile_Homes_ACS_16_20']),
		'pct_Crowd_Occp_U_ACS_16_20': float(combined_dict['pct_Crowd_Occp_U_ACS_16_20']),
		'pct_noVehicle': float(combined_dict['B08014_002E'])/float(combined_dict['B01001_001E'])
	}
	# Define the base URL for the TIGERweb REST Services
	tigris_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2021/MapServer/8/query"
	params = {
	'where': "STATE= '" + stateID +  "' AND COUNTY= '" + countyID + "' AND TRACT= '" + tractID + "' AND BLKGRP= '" + blockID +  "'",
	'outFields': '*',
	'returnGeometry': 'true',
	'f': 'geojson',
	'outSR': 4326  # Ensure we get geometries in WGS84 coordinate system
	}
	tigrisResponse = requests.get(tigris_url, params=params,timeout=50)
	tigrisData = tigrisResponse.json()
	if (tigrisData['features'][0]['geometry']['type'] == 'Polygon'):
		coordList = tigrisData['features'][0]['geometry']['coordinates'][0]
	else:
		coordList = []
		for i in tigrisData['features'][0]['geometry']['coordinates']:
			for j in i:
				coordList.append(j)
	svi_var_dict['blockgroupFIPS'] = str(blockgroupFIPS)
	svi_var_dict['geometry'] = coordList
	return svi_var_dict

def buildSVIRating(row):
	'''computes SVI Rating for SVI_SCORE columns'''
	if row['SOVI_SCORE'] <= .2:
		return 'Very Low'
	elif row['SOVI_SCORE'] > .2 and row['SOVI_SCORE'] <= .4:
		return 'Relatively Low'
	elif row['SOVI_SCORE'] > .4 and row['SOVI_SCORE'] <= .6:
		return 'Relatively Moderate'
	elif row['SOVI_SCORE'] > .6 and row['SOVI_SCORE'] <= .8:
		return 'Relatively High'
	else:
		return 'Very High'

def runCalculations(pathToOmd,pathToLoadsFile,avgPeakDemand, modelDir, equipmentList):
	'''
	Runs computations on circuit for different loads and equipment

	pathToOmd -> file path to omd
	modelDir -> modelDirectory to store csv
	equipmentList -> specify list of equipment to use in analysis: example : ['line', 'fuse', 'transformer]
	'''
	obDict,loads, sviGeoDF, newsviDF, section_loads = getDownLineLoadsEquipmentBlockGroup(pathToOmd, equipmentList, avgPeakDemand, pathToLoadsFile)
	cols = ['Object Name', 'Type','Section', 'Base Criticality Score', 'Base Criticality Index',
			'Community Criticality Score', 'Community Criticality Index']
	load_names = list(loads.keys())
	section1 = [value.get('section') for key, value in loads.items()]
	base_criticality_score_vals1 = [value.get('base crit score') for key, value in loads.items()]
	base_criticity_index_vals1 = [value.get('base crit index') for key, value in loads.items()]
	community_criticality_score_vals1 = [value.get('community crit score') for key, value in loads.items()]
	community_criticity_index_vals1 = [value.get('community crit index') for key, value in loads.items()]
	#sovi_vals1 = [value.get('SOVI_SCORE') for key, value in loads.items()]
	#affluence_vals1 = [value.get('affluence score') for key, value in loads.items()]
	type1 = ['load' for i in range(len(base_criticality_score_vals1))]
	loadsList = list(zip(load_names,type1,  section1,  base_criticality_score_vals1, base_criticity_index_vals1,community_criticality_score_vals1,community_criticity_index_vals1))
	object_names = list(obDict.keys())
	section2 = [value.get('section') for key, value in obDict.items()]
	base_criticality_score_vals2 = [value.get('base crit score') for key, value in obDict.items()]
	base_criticity_index_vals2 = [value.get('base crit index') for key, value in obDict.items()]
	community_criticality_score_vals2 = [value.get('community crit score') for key, value in obDict.items()]
	community_criticity_index_vals2 = [value.get('community crit index') for key, value in obDict.items()]
	type2 = ['equipment' for i in range(len(base_criticality_score_vals2))]

	equipList = list(zip(object_names,type2, section2,  base_criticality_score_vals2, base_criticity_index_vals2,community_criticality_score_vals2,community_criticity_index_vals2 ))
	finList = loadsList + equipList
	newDF = createDF(finList, cols, [])
	newDF.to_csv(pJoin(modelDir, 'resilientCommunityOutput.csv'))  

def get_zillowListings(lat, lon):
	#zillow api
	url = "https://zillow56.p.rapidapi.com/search_coordinates"
	# necessary query string
	querystring = {
	"status":"forSale", ##recentlySold
	"output":"json",
	"sort":"zest",
	"listing_type":"by_agent",
	"isSingleFamily":"True",
	"doz":"any",
	"long":str(lon),
	"lat":str(lat),
	"d":"15"} ## distance in miles
	# other key: '4a7c726a01msh4ca1a1226e51296p1eda4cjsn11e2cc965850'
	#322d8225bfmsh27bf206ed5a9ac1p16fceejsn20980c1afc0b
	# fcceabeb9amshbf564b56f3106afp1ed137jsn86bb664919c2
	headers = {
	"x-rapidapi-key": 'fcceabeb9amshbf564b56f3106afp1ed137jsn86bb664919c2',
	"x-rapidapi-host": "zillow56.p.rapidapi.com"
	}
	time.sleep(1)
	listingJson = requests.get(url, headers=headers, params=querystring)
	newjson = listingJson.json()
	return newjson

#UNUSED
def calculateAvg_prices(data):
	# Extract the list of results
	results = data.get('results', [])
	# Initialize list to store price per square foot
	prices_per_sqft = []
	prices = []
	for result in results:
		# Use zestimate if available, otherwise use price
		price = result.get('zestimate') or result.get('price')
		living_area = result.get('livingArea')
		# Ensure both price and living area are available and valid
		if price:
			prices.append(price)
			if living_area:
				price_per_sqft = price / living_area
				prices_per_sqft.append(price_per_sqft)  # Append the calculated price per square foot
		if prices:
			avg_price = sum(prices) / len(prices)
			if prices_per_sqft:
				avg_price_per_sqft = sum(prices_per_sqft) / len(prices_per_sqft)
				return avg_price, avg_price_per_sqft
			else:
				print("Error calculating prices per sqft")
				return avg_price, None
		else:
			print("Error calculating avg price")
			return None, None

#UNUSED
def cacheZillowData(pathToOmd, pathToLoad):
	omd = json.load(open(pathToOmd))
	loads = json.load(open(pathToLoad))
	zillowDict = {}
	#seenTract = cenTract
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		if (obType == 'load'):
			long = float(ob['longitude'])
			lat = float(ob['latitude'])
			if loads[key]['blockgroup']:
				blockgroup = loads[key]['blockgroup']
			else:
				continue
			if blockgroup in zillowDict:
				continue
			else:
				##  can put this before and add field to use housing data
				time.sleep(30)
				zillowJson = get_zillowListings(lat, long)
				zillowDict[blockgroup] = zillowJson
	with open('/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/zillowOutput.json', 'w') as f:
		json.dump(zillowDict, f)

def runSections(pathToOmd, omd):
	#omd = json.load(open(omdFilePath))
	#dssTree = omdToTree(omdFilePath)
	G = createGraph(pathToOmd)
	disconnected_nodes = [node for node in G.nodes if G.degree[node] == 0]
	# add data to nodes
	for ob in omd.get('tree', {}).values():
		node = ob.get('name', '')
		if node in G.nodes:
			G.nodes[node].update(ob)
		else:
			G.add_node(node, **ob)
		# Add edge data from OMD to the graph, setting weight to 0 for all edges
		if 'from' in ob and 'to' in ob:
			if ob.get('enabled') == 'n':
				G.remove_edge(ob['from'], ob['to'])
			elif not G.has_edge(ob['from'], ob['to']):
				length = float(ob.get('length', 0))
				name = ob.get('name', '')
				G[ob['from']][ob['to']]['name'] = name
				G.add_edge(ob['from'], ob['to'], weight=int(length))
			else:
				length = float(ob.get('length', 0))
				name = ob.get('name', '')
				# conversion to float then int because the string '0.01' for example can't be converted straight into the int 0
				G[ob['from']][ob['to']]['weight'] = int(length)
	# Create edges based on parent relationships
	for node, data in G.nodes(data=True):
		if "parent" in data:
			parent = data["parent"]
			if parent not in G.nodes:
				G.add_node(parent)  # Add the parent node if it doesn't exist
			if not G.has_edge(parent, node):
				G.add_edge(parent, node, weight=0)  # Add an edge with a default weight
				#print(f"Edge created between parent '{parent}' and node '{node}'.")
	# Identify edges with switches
	from_to_tuples_with_switch = [
		(entry.get("from"), entry.get("to"))
		for entry in omd.get('tree', {}).values()
		if str(entry.get("switch")).lower() in ["y","yes","t","true"] and str(entry.get("enabled")).lower() not in ["n","no","f","false"] and "from" in entry and "to" in entry
	]
	for i in from_to_tuples_with_switch:
		G[i[0]][i[1]]['switch'] = True
	# Remove disconnected nodes
	for node in list(nx.isolates(G)):
		G.remove_node(node)
	disconnected_nodes = [node for node in G.nodes if G.degree[node] == 0]
	#print(len(disconnected_nodes))
	sections = section_circuit(G)
	distanceToSource = calculate_distances_to_source(G, 'source')
	#print(distanceToSource)
	# Combine sections into a dictionary
	sectionDict = {}
	for section_number, nodes, edges in sections:  # Unpack section_number
		for node in nodes:
			sectionDict[node] = section_number
		for edge in edges:
			sectionDict[str(edge)] = section_number
	return sectionDict, distanceToSource, len(sections)

def section_circuit(graph):
	visited_edges = set()  # Tracks visited edges
	sections = []		  # List of finalized sections: [(section_number, nodes, edges)]
	locked_nodes = {}
	current_section = None # The current active section
	section_counter = 0	# Counter for section numbering
	def start_new_section(edge):
		"""Start a new section with the given switch edge."""
		nonlocal current_section, section_counter
		section_nodes = set(edge)
		section_edges = {edge}
		current_section = (section_counter, section_nodes, section_edges)
		start_node = str(edge[0])
		if section_counter == 0:
			section_counter += 1
			current_section = (section_counter, section_nodes, section_edges)
			locked_nodes.setdefault(start_node, section_counter)
		else:
			locked_nodes.setdefault(start_node, section_counter - 1)
			section_counter+=1
			current_section = (section_counter, section_nodes, section_edges)
	def finalize_current_section():
		"""Finalize the current active section."""
		nonlocal current_section
		if current_section:
			section_number, section_nodes, section_edges = current_section
			# Filter out locked nodes that belong to a different section
			valid_nodes = set()
			for node in section_nodes:
				if node not in locked_nodes:
					valid_nodes.add(node)  # Node is not locked, include in the section
				elif locked_nodes[node] == section_number:
					valid_nodes.add(node)  # Node is locked and in the correct section
			# Finalize the current section with valid nodes and edges
			sections.append((section_number, valid_nodes, section_edges))
			# Clear the current section after finalizing
			current_section = None
	def traverse_from_node(start_node):
		"""Explore all reachable nodes and edges for the current section."""
		stack = [start_node]
		deferred_switches = []  # Store switch edges to process later
		while stack:
			node = stack.pop()
			for neighbor in graph.neighbors(node):
				edge = (node, neighbor) if (node, neighbor) in graph.edges else (neighbor, node)
				if edge in visited_edges or edge[::-1] in visited_edges:
					continue  # Skip already visited edges
				visited_edges.add(edge)
				visited_edges.add(edge[::-1])
				edge_data = graph.get_edge_data(*edge)
				if edge_data.get("switch", False):
					# Defer handling switches until all non-switch paths are explored
					#print(f"Switch encountered at edge {edge}. Deferring for later.")
					deferred_switches.append((neighbor, edge))
					continue
				# Add non-switch edge to the current section
				if current_section:
					_, section_nodes, section_edges = current_section
					section_nodes.add(neighbor)
					section_edges.add(edge)
					stack.append(neighbor)
		# Process deferred switches for the current section
		for neighbor, switch_edge in deferred_switches:
			finalize_current_section()  # Finalize the current section
			start_new_section(switch_edge)  # Start a new section at the switch
			traverse_from_node(neighbor)  # Explore the new section
	# Main edge traversal
	for u, v, data in graph.edges(data=True):
		edge = (u, v)
		if edge in visited_edges or edge[::-1] in visited_edges:
			continue  # Skip already visited edges
		visited_edges.add(edge)
		visited_edges.add(edge[::-1])
		if data.get("switch", False):
			# Switch edge triggers a new section
			if current_section:
				finalize_current_section()
			start_new_section(edge)
			traverse_from_node(v)  # Start traversal from the v node of (u, v)
		else:
			# Non-switch edge starts or extends the current section
			if current_section:
				_, section_nodes, section_edges = current_section
				section_nodes.update([u, v])
				section_edges.add(edge)
			else:
				# If no current section, start a new one
				start_new_section(edge)
				traverse_from_node(u)
	# Finalize any remaining section
	finalize_current_section()
	return sections

#UNUSED
def getSectionsDistribution(sectionsDict, omd):
	"""
	Calculates and displays the distribution of Community Criticality Scores (CCS) for each section.
	
	sectionsDict: Dictionary mapping section names to lists of object keys in OMD.
	omd: Dictionary containing the parsed JSON OMD data.
	"""
	# Iterate through each section
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		key = obType + '.' + obName
		# Calculate statistics
		mean = np.mean(ccs_list)
		median = np.median(ccs_list)
		std_dev = np.std(ccs_list)
		min_value = np.min(ccs_list)
		max_value = np.max(ccs_list)
		# Print statistics for the section
		print(f"CCS Statistics for Section: {section}")
		print(f"Mean: {mean:.2f}, Median: {median:.2f}, Std Dev: {std_dev:.2f}, Min: {min_value:.2f}, Max: {max_value:.2f}\n")
		# Plot histogram
		plt.figure(figsize=(10, 6))
		plt.hist(ccs_list, bins=20, edgecolor='black', alpha=0.7)
		plt.title(f'CCS Distribution for {section}')
		plt.xlabel('CCS Value')
		plt.ylabel('Frequency')
		plt.grid(True)
		plt.show()

#UNUSED
def getDistribution():
	import json
	import numpy as np
	import matplotlib.pyplot as plt
	# Path to the OMD file
	pathToOmd = '/Users/davidarmah/Documents/omf/omf/data/Model/admin/Automated Testing of resilientCommunity/color_test.omd'
	# Load the JSON data
	try:
		with open(pathToOmd, 'r') as file:
			omd = json.load(file)
	except FileNotFoundError:
		print(f"File not found: {pathToOmd}")
		return
	except json.JSONDecodeError:
		print(f"Error decoding JSON file: {pathToOmd}")
		return
	# Collect CCS values
	ccs_list = []
	for obj in omd.get('tree', {}).values():
		# Check if 'community crit score' exists and add it to the list
		if 'community crit score' in obj and isinstance(obj['community crit score'], (int, float)):
			ccs_list.append(obj['community crit score'])
	# Check if CCS list is empty
	if not ccs_list:
		print("No Community Criticality Scores found in the data.")
		return
	# Calculate statistical distribution
	mean = np.mean(ccs_list)
	median = np.median(ccs_list)
	std_dev = np.std(ccs_list)
	min_value = np.min(ccs_list)
	max_value = np.max(ccs_list)
	# Print statistics
	print(f"CCS Statistics:")
	print(f"Mean: {mean:.2f}")
	print(f"Median: {median:.2f}")
	print(f"Standard Deviation: {std_dev:.2f}")
	print(f"Min: {min_value:.2f}")
	print(f"Max: {max_value:.2f}")
	# Plot histogram
	plt.figure(figsize=(10, 6))
	plt.hist(ccs_list, bins=20, edgecolor='black', alpha=0.7)
	plt.title('Community Criticality Score Distribution')
	plt.xlabel('CCS Value')
	plt.ylabel('Frequency')
	plt.grid(True)
	plt.show()

#UNUSED
def getAverages_loads(loadsDict):
	# Convert JSON data into a DataFrame
	rows = []
	for load_id, load_data in data.items():
		row = load_data.copy()
		row['load_id'] = load_id
		rows.append(row)
	df = pd.DataFrame(rows)
	# Group by census tract and calculate average values
	averages = df.groupby('cen_tract').mean()

def calculate_distances_to_source(graph, source):
	# Reverse the graph to calculate distances to the source.
	# This flips the direction of edges, making it easier to compute distances to the source node.
	reversed_graph = graph.reverse(copy=True)
	# Initialize distances to all nodes as infinity.
	# Distance to the source itself is set to 0 since it's the starting point.
	distance_to_source = {node: float("inf") for node in reversed_graph.nodes}
	distance_to_source[source] = 0
	# Set to keep track of visited nodes to avoid processing the same node multiple times.
	visited = set()
	# Queue for breadth-first search (BFS). Starts with the source node at distance 0.
	queue = [(source, 0)]
	# Perform BFS to compute shortest distances.
	while queue:
		# Dequeue the next node and its current distance.
		current_node, current_distance = queue.pop(0)
		# Mark the current node as visited.
		visited.add(current_node)
		# Process neighbors of the current node in the reversed graph.
		for neighbor in reversed_graph.neighbors(current_node):
			# Get the weight of the edge; default to 1 if not specified.
			edge_weight = reversed_graph[current_node][neighbor].get("weight", 0)
			# Calculate the new potential distance to the neighbor.
			new_distance = current_distance + edge_weight
			# Update the distance if the new distance is shorter.
			if new_distance < distance_to_source[neighbor]:
				distance_to_source[neighbor] = new_distance
				# Add the neighbor to the queue for further processing.
				queue.append((neighbor, new_distance))
		# Process predecessors of the current node in the reversed graph.
		for predecessor in reversed_graph.predecessors(current_node):
			# Get the weight of the edge; default to 0 if not specified.
			edge_weight = reversed_graph[predecessor][current_node].get("weight", 0)
			# Calculate the new potential distance to the predecessor.
			new_distance = current_distance + edge_weight
			# Update the distance if the new distance is shorter.
			if new_distance < distance_to_source[predecessor]:
				distance_to_source[predecessor] = new_distance
				# Add the predecessor to the queue for further processing.
				queue.append((predecessor, new_distance))
	# print statement to show calculated distances to the source.
	# print("Distances to source:", distance_to_source)
	# Return the dictionary of distances to the source node.
	return distance_to_source

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# files
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd') and x != 'color_test.omd'][0][:-4]
	inputDict['feederName1'] = feederName
	omd_file_path = pJoin(modelDir, feederName+'.omd')
	# census_nri_path = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database_MAR2023.json')
	#loads_file_path = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'loads2.json')
	#obs_file_path = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'objects3.json')
	geoJson_shapes_file = pJoin(modelDir, 'geoshapes.geojson')
	sviDF_file = pJoin(modelDir, 'sviDF.csv')
	# Create a copy of the customer info file in modeldir
	custInfoPath = pJoin(modelDir, inputDict['customerFileName'])
	# TODO: Figure out why inputDict['customerData'] is an empty string when work() is run without explicitly uploading something, despite it working when a file is uploaded manually through the gui
	# only do the following if customerData is empty. Part of a workaround for issue with empty customer data file. 
	if inputDict['customerData'] != '':
		with open(custInfoPath, 'w') as ciFile:
			ciFile.write(inputDict['customerData'])
	zillowPricesPath= pJoin(omf.omfDir,'static','testFiles','resilientCommunity','zillowPrices.json')
	# check if census data json is downloaded
	# if not download
	# make sure computer has 8.59 GB Space for download
	#   if not os.path.exists(census_nri_path):
	#	   retrieveCensusNRI()
	#   elif inputDict['refresh']:
	#	   retrieveCensusNRI()

	# check what equipment we want to look for
	equipmentList = ['bus']
	if (inputDict['lines'].lower() == 'yes' ):
		equipmentList.append('line')
	if (inputDict['transformers'].lower() == 'yes' ):
		equipmentList.append('transformer')
	if (inputDict['fuses'].lower() == 'yes' ):
		equipmentList.append('fuse')

	# check downline loads
	useZillow = False
	obDict, loads, geoDF, sviDF, loadSections = getDownLineLoadsEquipmentBlockGroup(omd_file_path, equipmentList,inputDict['averageDemand'], custInfoPath, zillowPricesPath, useZillow)
	# color vals based on selected column
	createColorCSVBlockGroup(modelDir, loads, obDict)
	if(inputDict['loadCol'] == 'Base Criticality Score'):
		colVal = "1"
	elif (inputDict['loadCol'] == 'Community Criticality Score'):
		colVal = "2"
	elif(inputDict['loadCol'] == 'Base Criticality Index'):
		colVal = "3"
	elif(inputDict['loadCol'] == 'Community Criticality Index'):
		colVal = "4"
	elif(inputDict['loadCol'] == 'Feeder Sections'):
		colVal = "5"
	else:
		colVal = None
	# Load Geojson file more efficiently
	smartRound = lambda x: round(x,2) if isinstance(x,float) else x
	geoDF = geoDF.map(smartRound)
	geoDF.to_file(geoJson_shapes_file, driver="GeoJSON")
	sviDF.to_csv(sviDF_file)
	with open(geoJson_shapes_file) as f1:
		geoshapes =  json.load(f1)
	attachment_keys = {
		"coloringFiles": {
			"color_by.csv": {
				"csv": "<content>",
				"colorOnLoadColumnIndex": colVal
			}
		}
		,
		"geojsonFiles":{
			"geoshapes.geojson": {
				"json": json.dumps(geoshapes),
				"displayOnLoad": 'true'
			}
		}
	}
	outData['sviData'] =  open(sviDF_file, 'r').read()
	with open(omd_file_path) as file1:
		init_omdJson = json.load(file1)
	newOmdJson = addLoadInfoToOmd(loads, init_omdJson)
	omdJson = addEquipmentInfoToOmd(obDict, newOmdJson, equipmentList)
	with open(pJoin(modelDir, 'color_by.csv')) as f:
		data =  f.read()
	attachment_keys['coloringFiles']['color_by.csv']['csv'] = data
	new_path = pJoin(modelDir, 'color_test.omd')
	omdJson['attachments'] = attachment_keys
	with open(new_path, 'w+') as out_file:
		json.dump(omdJson, out_file, indent=4)
	geo.map_omd(new_path, modelDir, open_browser=False)
	outData['resilienceMap'] = open( pJoin( modelDir, "geoJson_offline.html"), 'r' ).read()
	outData['geojsonData'] = open(geoJson_shapes_file, 'r').read()
	
	# Collect Loads Data Table Info
	tableRows1 = []
	for load_names,v in loads.items():
		row = (
			load_names,
			v.get('section'),
			round(v.get('base crit score'),2),
			round(v.get('base crit index'),2),
			round(v.get('community crit score'),2),
			round(v.get('community crit index'),2),
			round(v.get('SOVI_SCORE'),4),
			smartRound(v.get('affluence score'))
		)
		tableRows1.append(row)
	outData['loadTableHeadings'] = ['Load Name','Section', 'Base Criticality Score', 'Base Criticality Index','Community Criticality Score', 'Community Criticality Index', 'Social Vulnerability', 'Affluence Score']
	outData['loadTableValues'] = tableRows1
	
	# Collect Equipment Data Table Info
	tableRows2 = []
	for object_names,v in obDict.items():
		row = (
			object_names,
			v.get('section'),
			round(v.get('base crit score'),2),
			round(v.get('base crit index'),2),
			round(v.get('community crit score'),2),
			round(v.get('community crit index'),2)
			)
		tableRows2.append(row)
	outData['loadTableHeadings2'] = ['Equipment Name', 'Section', 'Base Criticality Score', 'Base Criticallity Index', 'Community Criticality Score', 'Community Criticality Index']
	outData['loadTableValues2'] = tableRows2
	
	# Collect Sections Data Table Info
	headers3 = ['Section', 'Base Criticality Score', 'Base Criticallity Index', 'Community Criticality Score', 'Community Criticality Index','Social Vulnerability','Affluent Score', 'Load Count', 'Load Amount']
	cols = ['section', 'avg_BCS', 'avg_BCI', 'avg_CCS', 'avg_CCI', 'avg_svi_score', 'avg_zillow_price', 'load_count', 'load_amount']
	if not useZillow:
		headers3.remove('Affluent Score')
		cols.remove('avg_zillow_price')
	loadSections[['load_count','load_amount']] = loadSections[['load_count','load_amount']].fillna(0)
	loadSections[cols[1:]] = loadSections[cols[1:]].fillna('None').map(smartRound)
	tableRows3 = list(loadSections[cols].itertuples(index=False, name=None))
	outData['loadTableHeadings3'] = headers3
	outData['loadTableValues3'] = tableRows3
	return outData

def test():
	# files
	pathToOmd = "/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/iowa240_in_Florida_copy2.omd"
	modelDir = "/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity"
	pathToLoadsFile = pJoin(omf.omfDir,'static','testFiles','resilientCommunity','restorationLoads.csv')
	equipmentList = ['lines', 'transformers', 'fuses']
	runCalculations(pathToOmd,pathToLoadsFile,1, modelDir, equipmentList)

def new(modelDir):
	omdfileName = 'ieee37_LBL_simplified'
	customerFileName = 	[omf.omfDir,'static','testFiles','resilientCommunity','restorationLoads.csv']
	customerFileData = open(pJoin(*customerFileName)).read()
	#omdfileName = 'iowa240_in_Florida_modified'
	#omdfileName = 'iowa240_dwp_22_no_show_voltage.dss'
	defaultInputs = {
		"modelType": modelName,
		"feederName1": omdfileName,
		"customerFileName": customerFileName[-1],
		"customerFileData": customerFileData,
		"averageDemand": 2.0,
		"lines":'Yes',
		"transformers":'Yes',
		"fuses":'Yes',
		"loadCol": "Base Criticality Index",
		"inputDataFileContent": 'omd',
		"optionalCircuitFile" : 'on',
		"created":str(datetime.datetime.now()),
		"residential":"yes",
		"retail": "yes",
		"agriculture": "yes"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		#shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "testFiles","resilientCommunity", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	# For some reason even though the customer data is being passed correctly from the file into the default inputs, when work is run, the customer data is empty
	custInfoPath = pJoin(modelDir, customerFileName[-1])
	with open(custInfoPath, 'w') as ciFile:
		ciFile.write(customerFileData)
	
	return creationCode

@neoMetaModel_test_setup
def tests():
	# Location
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
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
	print("test")
	#tests()
	#getDistributionSection(
	#sectionExample("/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/iowa240_in_Florida_copy2.omd")
	#newSection("/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/iowa240_in_Florida_copy2.omd")
	#getDistribution()
	#test()