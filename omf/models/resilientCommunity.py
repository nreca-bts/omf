''' Calculates Outage Impact Potential for a given Circuit '''
# warnings.filterwarnings("ignore")
from logging import raiseExceptions
import urllib.request
import shutil, datetime
from os.path import join as pJoin
from os.path import isfile
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
from collections import OrderedDict

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

#================================================== !!! CURRENTLY UNUSED !!! ======================================================
############################## NRI Data Code ##################################
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
			outfile = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database.json')
			with open(outfile, 'w') as f:
				json.dump(geojson_data, f,indent=4)
				return outfile
	except Exception as e:
		print("Error trying to retrieve FEMA NRI Census Data in GeoJson format")
		print(e)

def stripDownCensusNRI(properties2Keep):
	''' Strips down census NRI data from 8.6 GB file, creating a json file with tractFIPS as keys and only the properties for each tract in properties2Keep
		Data Dictionary for choosing properties: https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload/NRIDataDictionary.csv
	'''
	infile = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database.json')
	outfile = infile.replace('2023','2023_properties_by_tractFIPS')
	with open(infile) as f:
		geoJsonData = json.load(f)
	propsByTractFIPS = {}
	for feature in geoJsonData['features']:
		tractFIPS = feature['properties']['TRACTFIPS']
		propsByTractFIPS[tractFIPS] = {}
		for prop in properties2Keep:
			propsByTractFIPS[tractFIPS][prop] = feature['properties'][prop]
	with open(outfile, 'w') as f:
		json.dump(propsByTractFIPS,f,indent=4)
############################## End NRI Data Code ##############################

############################## Coord Transform Code ##################################
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
############################## End Coord Transform Code ##############################

############################## Zillow Code ##################################
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
############################## End Zillow Code ##############################

############################## Statistical Distribution of CCS Code ##################################
def getSectionsDistribution(sectionsDict, omd):
	'''
	Calculates and displays the distribution of Community Criticality Scores (CCS) for each section.
	
	sectionsDict: Dictionary mapping section names to lists of object keys in OMD.
	omd: Dictionary containing the parsed JSON OMD data.
	'''
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
############################## End Statistical Distribution of CCS Code ##############################

############################## Run Calculations Code ##################################
def testRunCalculations():
	pathToOmd = "C:/Users/louis/NRECA/omf/omf/static/testFiles/resilientCommunity/ieee37_LBL_simplified.omd"
	modelDir = "C:/Users/louis/NRECA/omf/omf/static/testFiles/resilientCommunity"
	feederName = "ieee37_LBL_simplified"
	custInfoPath = pJoin(omf.omfDir,'static','testFiles','resilientCommunity','restorationLoads.csv')
	avgPeakDemand = 1
	equipmentList = ['lines', 'transformers', 'fuses']
	oipInputDict = {'oip_poverty':1, 'oip_employed':1, 'oip_income':1}
	oipAggMethod = 'Average of Min-Max-Normalized'
	runCalculations(modelDir, pathToOmd, custInfoPath, avgPeakDemand, equipmentList, oipInputDict, oipAggMethod, feederName)

def runCalculations(modelDir, pathToOmd, custInfoPath, avgPeakDemand, equipmentList, oipInputDict, oipAggMethod, feederName):
	'''
	Runs computations on circuit for different loads and equipment.
	Creates a CSV called resilientCommunityOutput.csv in the modelDir
	with section, bcs, bci, lcs, lci, and type (load or equipment) for each object. 

	pathToOmd -> file path to omd
	modelDir -> modelDirectory to store csv
	equipmentList -> specify list of equipment to use in analysis: example : ['line', 'fuse', 'transformer]
	'''

	acceptableKeys = {'oip_poverty', 'oip_employed', 'oip_income', 'oip_nongrad', 'oip_age65', 
				'oip_below19', 'oip_disabled', 'oip_lim_eng', 'oip_multi', 'oip_mobile', 'oip_crowding', 
				'oip_no_vehicle', 'oip_af_avln', 'oip_af_cwav', 'oip_af_drgt', 'oip_af_erqk', 
				'oip_af_hail', 'oip_af_hwav', 'oip_af_hrcn', 'oip_af_istm', 'oip_af_lnds', 'oip_af_ltng', 
				'oip_af_swnd', 'oip_af_wfir', 'oip_af_wntw'}
	givenKeys = set(oipInputDict.keys())
	unacceptableKeys = givenKeys-acceptableKeys
	if not givenKeys:
		raise Exception('ERROR: oipInputDict cannot be empty.')
	elif unacceptableKeys:
		raise Exception(f'ERROR: The following keys in oipInputDict are not accepted:{unacceptableKeys}.\nOnly keys from the following list will be accepted:{acceptableKeys}.')

	with open(pathToOmd) as f:
		omd = json.load(f)
	# Section code
	sectionsDict, distanceDict, totalSections = runSections(pathToOmd, omd)
	# create loadDicts
	custInfoDF = pd.read_csv(custInfoPath)
	restrictToResidential = useOipCustVars(oipInputDict)
	loadDict, loadCoordsDict = makeLoadDicts(omd, sectionsDict, distanceDict, custInfoDF, restrictToResidential)
	# create blockgroupDicts with Outage Impact Metric (OIP) for each blockgroup and provide messages about what variables had to be removed from the analysis
	blockgroupDict, loads2BgDict = makeBlockgroupDicts(modelDir, loadCoordsDict, feederName)
	addOipToBlockgroups(blockgroupDict, oipInputDict, oipAggMethod)
	# Add blockgroup info to loads and process it into new metrics in loadDict
	addBgInfoToLoads(loadDict, blockgroupDict, loads2BgDict, avgPeakDemand)
	# Create equipmentDict with equipment metrics based on downline load metrics
	equipmentDict = makeEquipmentDict(pathToOmd, omd, sectionsDict, loadDict, equipmentList)

	# Do loads
	loadNames = list(loadDict.keys())
	sections1 = [value.get('section') for value in loadDict.values()]
	bcsVals1 = [value.get('base crit score') for value in loadDict.values()]
	bciVals1 = [value.get('base crit index') for value in loadDict.values()]
	lcsVals1 = [value.get('locational crit score') for value in loadDict.values()]
	lciVals1 = [value.get('locational crit index') for value in loadDict.values()]
	types1 = ['load']*len(bcsVals1)
	loadsList = list(zip(loadNames, types1,  sections1,  bcsVals1, bciVals1, lcsVals1, lciVals1))
	# Do equipment
	equipNames = list(equipmentDict.keys())
	sections2 = [value.get('section') for value in equipmentDict.values()]
	bcsVals2 = [value.get('base crit score') for value in equipmentDict.values()]
	bciVals2 = [value.get('base crit index') for value in equipmentDict.values()]
	lcsVals2 = [value.get('locational crit score') for value in equipmentDict.values()]
	lciVals2 = [value.get('locational crit index') for value in equipmentDict.values()]
	types2 = ['equipment']*len(bcsVals2)
	equipList = list(zip(equipNames, types2, sections2, bcsVals2, bciVals2, lcsVals2, lciVals2))
	
	cols = ['Object Name', 'Type', 'Section', 'Base Criticality Score', 'Base Criticality Index',
			'Locational Criticality Score', 'Locational Criticality Index']
	finList = loadsList + equipList
	newDF = pd.DataFrame(finList, columns = cols)
	newDF.to_csv(pJoin(modelDir, 'resilientCommunityOutput.csv'))  
############################## End Run Calculations Code ##############################

############################## Unused Helper Function Code ######################################
def all_vals(obj):
	''' helper method that retrieves all values in nested dictionary'''
	if isinstance(obj, dict):
		for v in obj.values():
			yield from all_vals(v)
	else:
		yield obj
############################## End Unused Helper Function Code ##################################
#================================================== !!! END CURRENTLY UNUSED !!! ==================================================

############################## Sections Code ##################################
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
############################## End Sections Code ##############################

############################## makeLoadDicts Code ##################################
def useOipCustVars(oipInputDict):
	''' Check if any of the OIP Customer Variables have nonzero weights. Return True if so, False otherwise.'''
	# TODO: Add in 'oip_single_par' once the calc for that is corrected and it's added to the inputs
	custVarList = ['oip_employed', 'oip_age65', 'oip_crowding', 'oip_poverty', 'oip_disabled', 'oip_lim_eng', 'oip_mobile', 'oip_multi', 'oip_no_vehicle', 'oip_nongrad', 'oip_below19', 'oip_income']
	doLimit = False
	for custVar in custVarList:
		if float(oipInputDict[custVar]) != 0:
			doLimit = True
			break
	return doLimit

def loadIsResidential(custInfoDF,loadName):
	''' Checks if there's a single entry for a load in custInfoDF and if so, returns whether it's residential or not.'''
	loadRowsDf = custInfoDF[custInfoDF["Load Name"] == loadName]
	if len(loadRowsDf) > 1:
		raise Exception(f"ERROR: Your Customer Information (.csv file) contains more than 1 entry for the load {loadName}")
	elif len(loadRowsDf) == 0:
		raise Exception(f"ERROR: Your Customer Information (.csv file) contains no entry for the load {loadName}")
	else:
		return loadRowsDf["Business Type"].iloc[0].lower() == 'residential'

def getPowerMeasures(ob):
	''' Retrieves kw, kvar, and kva from a load object
		Input: ob -> a load object 
		Return: -> [kw, kvar, kva]
	'''
	kw = ob.get('kw',None)
	kvar = ob.get('kvar',None)
	kva = ob.get('kva',None)
	pf = ob.get('pf',None)
	if None not in [kw,kvar]:
		kw = float(kw)
		kvar = float(kvar)
		kva = math.sqrt(kw**2 + kvar**2)
	elif None not in [kw,pf]:
		kw = float(kw)
		kva = kw/float(pf)
		kvar = math.sqrt(kva**2 - kw**2)
	elif None not in [kva,pf]:
		kw = float(kva)*float(pf)
		kva = float(kva)
		kvar = math.sqrt(kva**2 + kw**2)
	else:
		raise Exception(f'Load {ob["name"]} does not have necessary information to calculate kw, kva, and kvar')
	return kw, kvar, kva

def makeLoadDicts(omd, sectionsDict, distanceDict, custInfoDF, restrictToResidential):
	''' Constructs and returns loadDict and loadCoordsDict.
		loadCoordsDict is a seprate dict because we don't want to carry coords along into places where loadDict is used later.

		When returned, loadDict contains loads as keys and dictionaries as values for each load recorded with the following keys:
		'kva', 'distance_from_source', 'section'

		When returned, loadCoordsDict contains loads as keys and dictionaries as values for each load recorded with the following keys:
		'long', 'lat'
	'''
	loadDict = {}
	loadCoordsDict = {}
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		obKey = f'{obType}.{obName}'
		if (obType == 'load') and (loadIsResidential(custInfoDF, obName) or not restrictToResidential):
			loadDict[obKey] = {}
			kw, kvar, kva = getPowerMeasures(ob)
			loadDict[obKey]['kva'] = kva
			loadDict[obKey]['distance_from_source'] = int(distanceDict.get(obName, 0))
			loadDict[obKey]['section'] = sectionsDict.get(obName)
			loadCoordsDict[obKey] = {
				'long':	float(ob['longitude']),
				'lat':	float(ob['latitude'])
			}
	return loadDict, loadCoordsDict
############################## End makeLoadDicts Code ##############################

############################## makeBlockgroupDicts Code ######################################
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

def findCensusBlockgroup(lat,lon):
	'''
	Finds Census Block at a given lon / lat incorporates US Census Geolocator API
	Input: lat -> specified latitude value
	Input: lon -> specified longitude value
	return censusBlockGroup ->  census block group found at location
	'''
	
	def getCensusJson(request_url):
		''' Helper function to get the json from request_url'''
		opener = urllib.request.build_opener()
		opener.addheaders = [('User-agent', 'Mozilla/5.0')]
		resp = opener.open(request_url, timeout=100)
		censusJson = json.loads(resp.read())
		return censusJson
	
	try:
		# Requested for API Key to bypass api load limits
		request_url = f'https://geo.fcc.gov/api/census/block/find?latitude={lat}&longitude={lon}&censusYear=2020&format=json&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b'
		censusJson = getCensusJson(request_url)
		censusBlockGroup = censusJson['Block']['FIPS'][:-3]
		return censusBlockGroup
	except Exception as e1:
		try:
			# Documentation on geocoding API: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.pdf
			request_url = f'https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x={lon}&y={lat}&benchmark=8&vintage=820&format=json'
			censusJson = getCensusJson(request_url)
			censusBlockGroup = censusJson['result']['geographies']['Census Blocks'][0]['GEOID'][:-3]
			return censusBlockGroup
		except Exception as e2:
			print('\nErrors trying to retrieve block group information from Census APIs')
			print(f'Error for geo.fcc.gov:\n{e1}')
			print(f'Error for geocoding.geo.census.gov:\n{e2}\n')

def repeatFindCensusBlockgroup(lat, long, lim=10, wait=3):
	''' Repeatedly attempts to retrieve census blockgroup, returning the info as soon as it is successful, and raising an exception after a certain number of attempts.
		Args:
			Input: lat -> specified latitude value
			Input: lon -> specified longitude value
			Input: lim -> num attempts before an exception is raised
			Input: wait -> num sec between attempts to avoid overwhelming server
		Return: censusBlockGroup ->  census Tract found at location
	'''
	for i in range(0,lim):
		censusBlockGroup = findCensusBlockgroup(lat,long)
		if censusBlockGroup:
			break
		elif i == lim-1:
			raise Exception(f'ERROR - Could not get census block group in {lim} calls to the server')
		else:
			time.sleep(wait)
	return censusBlockGroup

def buildBlockgroup(blockgroupFIPS):
	'''
	Build a blockgroup with the OIP cust var data pulled from the web.
	Returns a dict of blockgroup information.
	'''
	# Cust Var Components for OIP
	# Socioeconomic
	# Household
	# Housing Type

	# SOCIOECONOMIC VARS
	# Name of feature | Feature name (short): Variable name

	# Percent Individuals Below Poverty Level | Poverty level: pct_Prs_Blw_Pov_Lev_ACS_16_20
	# Percent Individuals 16+ Employed | Employed: pct_Civ_emp_16p_ACS_16_20
	# Avg Aggregate Household Income | Income: avg_Agg_HH_INC_ACS_16_20
	# Percent non highschool grads | Highschool: pct_Not_HS_Grad_ACS_16_20

	# HOUSEHOULD COMPOSITION / DISABILITY VARS

	#Percent Age 65+ |Age 65+ : Percentage calculated by dividing Pop_65plus_ACS_16_20 by Tot_Population_ACS_16_20
	# Noninstitutionalized People under 19 | under19: Civ_noninst_pop_U19_ACS_16_20
	# Non Institutionalized People | noninstitution: Civ_Noninst_Pop_ACS_16_20
	# Percent population under 19 | under19 : Civ_noninst_pop_U19_ACS_16_20 / Civ_Noninst_Pop_ACS_16_20
	# Percent population disabled | disabled: pct_Pop_Disabled_ACS_16_20
	# Limited English speaking household | limited english: ENG_VW_ACS_16_20
	# Total occupied housing units | units: Tot_Occp_Units_ACS_16_20
	# Percent households speaking Limited English | households: ENG_VW_ACS_16_20 / Tot_Occp_Units_ACS_16_20
	# <------------------> THESE VARS ARE IN ACS DATASET REST ARE IN PLANNING DATABASE DATASET <---------------->
	# Estimate!!Total:!!6 to 17 years:!!Living with one parent: | singleparent6-17: B23008_021E
	# Estimate!!Total:!!Under 6 years:!!Living with one parent: | singleparentu6: B23008_008E
	# Total single parents with u18 child | singleparentu18: B23008_021E + B23008_008E
	# Total familes | family: B23008_001E
	# Percent of single parent families | singleparent: (B23008_021E + B23008_008E)/(B23008_001E)
	# TODO: Fix this calculation. Currently, we conflate (# children living with 1 parent) with (# single parents with u18 children), which are not the same thing because there are single parents with multiple children. 
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
	pdb_vars = ['pct_Prs_Blw_Pov_Lev_ACS_16_20', 'avg_Agg_HH_INC_ACS_16_20','pct_Not_HS_Grad_ACS_16_20',
				'Pop_65plus_ACS_16_20', 'Tot_Population_ACS_16_20',
				'pct_MLT_U10p_ACS_16_20', 'pct_Mobile_Homes_ACS_16_20', 'pct_Crowd_Occp_U_ACS_16_20', 'ENG_VW_ACS_16_20', 'Tot_Occp_Units_ACS_16_20', 'LAND_AREA', 'avg_Tot_Prns_in_HHD_ACS_16_20']
	# household composition / disability variables
	acs_vars = ['B23008_021E', 'B23008_008E', 'B23008_001E',
				'B08014_002E','B01001_001E']
	# add url for census tract to add variables that arent in blockgroup
	tractpdb_vars = ['Civ_Noninst_Pop_ACS_16_20', 'pct_Civ_emp_16p_ACS_16_20', 'pct_Pop_Disabled_ACS_16_20', 'Civ_noninst_pop_U19_ACS_16_20']

	stateID = blockgroupFIPS[:2] # state identifier
	countyID = blockgroupFIPS[2:5] # county identifier
	tractID = blockgroupFIPS[5:11] # tract identifier
	blockID = blockgroupFIPS[11:12] # block identifier
	# build url to use api
	acs_request_url = "https://api.census.gov/data/2022/acs/acs5?get=" + ",".join(acs_vars) + "&for=block%20group:" + str(blockID) + "&in=state:"+str(stateID)+"%20county:" +  str(countyID) + "%20tract:" + str(tractID)+"&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	pdb_request_url = "https://api.census.gov/data/2022/pdb/blockgroup?get="+ ",".join(pdb_vars) + "&for=block%20group:" + str(blockID) + "&in=state:"+str(stateID)+"%20county:" +  str(countyID) + "%20tract:" + str(tractID)+"&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	tractpdb_request_url = "https://api.census.gov/data/2022/pdb/tract?get="+ ",".join(tractpdb_vars)+ "&for=tract:"+str(tractID)+"&in=state:"+str(stateID)+"%20county:"+ str(countyID) + "&key=bc86c8cfc930e7c10b81d6683c6a316f5fcb857b"
	#acs  data
	opener = urllib.request.build_opener()
	opener.addheaders = [('User-agent', 'Mozilla/5.0')]
	resp = opener.open(acs_request_url, timeout=50)
	acsJson = json.loads(resp.read())
	acsDict = dict(zip(*acsJson))
	#pdb data
	resp = opener.open(pdb_request_url, timeout=50)
	pdbJson = json.loads(resp.read())
	pdbDict = dict(zip(*pdbJson))
	# extra tract data
	resp = opener.open(tractpdb_request_url, timeout=50)
	tractpdbJson = json.loads(resp.read())
	tractpdbDict = dict(zip(*tractpdbJson))

	def accountForNa(func, *args):
		''' Helper function to just return 'Not Applicable' if any args are None, otherwise execute the given function '''
		return 'Not Applicable' if None in args else func(*args)
		
	bgVarsDict = {
		# socioeconomic vars
		'oip_poverty': 	accountForNa(float, pdbDict['pct_Prs_Blw_Pov_Lev_ACS_16_20']),
		'oip_employed': accountForNa(float, tractpdbDict['pct_Civ_emp_16p_ACS_16_20']),
		'oip_income': 	accountForNa(lambda x: float(str(x).replace('$','').replace(',','')), pdbDict['avg_Agg_HH_INC_ACS_16_20']),
		'oip_nongrad': 	accountForNa(float, pdbDict['pct_Not_HS_Grad_ACS_16_20']),
		# household compisiton/ disability vars
		'oip_age65': 	accountForNa(lambda x,y: float(x)/float(y), pdbDict['Pop_65plus_ACS_16_20'], pdbDict['Tot_Population_ACS_16_20']),
		'oip_below19': 	accountForNa(lambda x,y: float(x)/float(y), tractpdbDict['Civ_noninst_pop_U19_ACS_16_20'], tractpdbDict['Civ_Noninst_Pop_ACS_16_20']),
		'oip_disabled': accountForNa(float, tractpdbDict['pct_Pop_Disabled_ACS_16_20']),
		'oip_lim_eng': 	accountForNa(lambda x,y: float(x)/float(y), pdbDict['ENG_VW_ACS_16_20'], pdbDict['Tot_Occp_Units_ACS_16_20']),
		# The following is commented out because the calc is wrong as detailed in the earlier TODO
		#'oip_single_par': accountForNa(lambda x,y,z: (float(x)+float(y))/max(0.0000000000001,float(z)), acsDict['B23008_021E'], acsDict['B23008_008E'], acsDict['B23008_001E']),
		#housing/transportation
		'oip_multi': 	accountForNa(float, pdbDict['pct_MLT_U10p_ACS_16_20']),
		'oip_mobile': 	accountForNa(float, pdbDict['pct_Mobile_Homes_ACS_16_20']),
		'oip_crowding': accountForNa(float, pdbDict['pct_Crowd_Occp_U_ACS_16_20']),
		'oip_no_vehicle': accountForNa(lambda x,y: float(x)/float(y), acsDict['B08014_002E'], acsDict['B01001_001E']),
		# Land Area in sq.mi. Not used for OIP but needed later for weather data calculations. Deleted after use before OIP calculation. 
		'LAND_AREA': 	accountForNa(float, pdbDict['LAND_AREA']),
		# Average numer of occupants per household. Not used for OIP but needed later for calculating BCS
		'avg_hh_occupants': accountForNa(float, pdbDict['avg_Tot_Prns_in_HHD_ACS_16_20'])
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
	bgVarsDict['blockgroupFIPS'] = str(blockgroupFIPS)
	bgVarsDict['geometry'] = coordList
	return bgVarsDict

def addWeatherToBlockgroups(blockgroupDict):
	''' Adds weather hazard data used for calculating OIP to the input blockgroupDict and removes LAND_AREA data which was included for use in this function.
	'''
	# Coastal Flooding, Riverine Flooding, Tornado, Tsunami, and Volcanic Activity removed until we can find a good way to estimate them at bg resolution
	# Unlike most variables, they're not broad enough sized events to span the entire tract and thus all blockgroups (thus bg resolution can be approximated with tract resolution value)
	# And unlike Avalanche, Landslide, and Lightning, they're not localized enough that their bg resolution value could be estimated by multiplying frequency by bg_area/tract_area
	# missingVals = ['CFLD_AFREQ','RFLD_AFREQ', 'TRND_AFREQ', 'TSUN_AFREQ', 'VLCN_AFREQ']
	weatherTypes = ['AVLN_AFREQ', 'CWAV_AFREQ', 'DRGT_AFREQ', 'ERQK_AFREQ', 'HAIL_AFREQ', 'HWAV_AFREQ', 'HRCN_AFREQ', 'ISTM_AFREQ', 
					'LNDS_AFREQ', 'LTNG_AFREQ', 'SWND_AFREQ', 'WFIR_AFREQ', 'WNTW_AFREQ']
	
	# weatherfile is a stripped down version of a file that was originally 8.6GB taken from the census website. 
	# There does not seem to be a more granular way to download the desired data, hence using a stored stripped down version instead of redownloading an 8.6GB file ever run.
	# The retrieval and stripping were done with retrieveCensusNRI() and stripDownCensusNRI() at the top of this file
	weatherFile = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database_properties_by_tractFIPS.json')
	with open(weatherFile) as f:
		weatherDict = json.load(f)
	for bg in blockgroupDict.keys():
		tractFIPS = bg[:11]
		tractArea = weatherDict[tractFIPS]['AREA']
		blockgroupArea = blockgroupDict[bg].pop('LAND_AREA')
		for wt in weatherTypes:
			weatherData = weatherDict[tractFIPS].get(wt,'Not Applicable')
			if weatherData == -9999.0:
				weatherData = 'Not Applicable'
			elif wt in ['AVLN_AFREQ', 'LNDS_AFREQ', 'LTNG_AFREQ']:
				# Avalanche, Landslide, and Lightning are localized enough hazards that we scale the tract-wide value by the proportion of the tract made up by the blockgroup to estimate blockgroup resolution
				weatherData *= blockgroupArea/tractArea
			weatherCode = wt.replace('_AFREQ','').lower()
			blockgroupDict[bg][f'oip_af_{weatherCode}'] = weatherData

def makeBlockgroupDicts(modelDir, loadCoordsDict, feederName):
	''' Constructs and returns blockgroupDict and loads2BgDict.

		When returned, blockgroupDict contains blockgroups as keys and dictionaries as values for each blockgroup recorded with the following keys:
		'oip_poverty', 'oip_employed', 'oip_income', 'oip_nongrad', 'oip_age65', 'oip_below19', 'oip_disabled', 'oip_lim_eng', 'oip_multi', 'oip_mobile', 'oip_crowding',
		'oip_no_vehicle', 'blockgroupFIPS', 'geometry', 'oip_af_avln', 'oip_af_cwav', 'oip_af_drgt', 'oip_af_erqk', 'oip_af_hail', 'oip_af_hwav', 'oip_af_hrcn', 
		'oip_af_istm', 'oip_af_lnds', 'oip_af_ltng', 'oip_af_swnd', 'oip_af_wfir', 'oip_af_wntw', 'avg_hh_occupants'

		When returned, loads2BgDict contains loadKeys (e.g. load.s733) as keys and blockgroups as values.

		Saves and loads blockgroupDict to/from a json file in modelDir to avoid redundant web calls across multiple runs. 
		Does not load if feederName has changed between runs to avoid cross-feeder contamination when new feeder is used.

	'''
	blockgroupDict = {}
	loads2BgDict = {}
	# desired keys is all the non-weather keys that normally get pulled from the web.
	desiredKeys = [	'oip_poverty', 'oip_employed', 'oip_income', 'oip_nongrad', 'oip_age65', 'oip_below19', 'oip_disabled', 'oip_lim_eng', 'oip_multi', 'oip_mobile', 
					'oip_crowding','oip_no_vehicle', 'blockgroupFIPS', 'geometry', 'avg_hh_occupants']

	# Load blockgroupDict (if the feederName hasn't changed since last run and if it has all the desired keys for each blockgroup)
	blockgroupDictFilePath = pJoin(modelDir, 'blockgroupDictData.json')
	if isfile(blockgroupDictFilePath):
		with open(blockgroupDictFilePath, 'r') as f:
			bgAndFeederNameDict = json.load(f)
		prevBgDict = bgAndFeederNameDict.get('blockgroupDict',{})
		hasDesKeys = lambda inDict: all(key in inDict for key in desiredKeys)
		desKeysInAllBg = all(hasDesKeys(bgProps) for bgProps in prevBgDict.values())
		prevFeederName = bgAndFeederNameDict.get('feederName')
		if feederName == prevFeederName and desKeysInAllBg:
			blockgroupDict = prevBgDict
	# Build blockgroup entries that aren't already populated
	webDataUpdated = False
	for loadKey, coordsDict in loadCoordsDict.items():
		long = coordsDict['long']
		lat = coordsDict['lat']
		if blockgroupDict:
			bg = coordCheck(long, lat, blockgroupDict)
			if bg:
				loads2BgDict[loadKey] = bg
				continue
		bg = repeatFindCensusBlockgroup(lat, long)
		blockgroupDict[bg] = buildBlockgroup(bg)
		loads2BgDict[loadKey] = bg
		webDataUpdated = True
	# Save blockgroupDict if web-sourced contents were updated
	if webDataUpdated:
		with open(blockgroupDictFilePath, 'w') as f:
			bgAndFeederNameDict = {
				'feederName': feederName,
				'blockgroupDict': blockgroupDict
			}
			json.dump(bgAndFeederNameDict, f)
	# Add weather data to blockgroupDict. Done here rather than in the loop because it loads and unloads a big file and we only want to do that once per run. 
	addWeatherToBlockgroups(blockgroupDict)
	return blockgroupDict, loads2BgDict
############################## End makeBlockgroupDicts Code ##################################

############################## Outage Impact Potential Code ######################################
def minmaxNorm(nums, doInvert):
	''' Returns a minmax-normalized version of the input list'''
	mn = min(nums)
	mx = max(nums)
	if mn != mx:
		mmnList = [(x-mn)/(mx-mn) for x in nums] if not doInvert else [1-((x-mn)/(mx-mn)) for x in nums]
	else:
		# Reasoning: If all values are the same, they shouldn't contribute to any of the values being summarized. Their weights are captured in the denomenators of those summary functions.
		mmnList = [0]*len(nums)
	return mmnList

def arithMean(nums, weights):
	''' Returns the weighted arithmetic mean of numbers in the input list'''
	weightedNums = [nums[i]*weights[i] for i in range(len(nums))]
	return sum(weightedNums)/sum(weights)

def rms(nums, weights):
	''' Returns the weighted rms of numbers in the input list'''
	weightedSquaredNums = [(nums[i]**2)*weights[i] for i in range(len(nums))]
	return (sum(weightedSquaredNums)/sum(weights))**0.5

def buildOIPRating(row):
	''' Computes OIP rating for the OIP Index column row entries'''
	oipIndex = row['OIP Index']
	if oipIndex <= 0.2:
		rating = 'Very Low'
	elif oipIndex <= 0.4:
		rating = 'Relatively Low'
	elif oipIndex <= 0.6:
		rating = 'Relatively Moderate'
	elif oipIndex <= 0.8:
		rating = 'Relatively High'
	else:
		rating = 'Very High'
	return rating

def addOipToBlockgroups(blockgroupDict, oipInputDict, oipAggMethod):
	''' Creates Outage Impact Potential (OIP) Score and Index then adds them to blockgroupDict.
		Args:
			Input: blockgroupDict -> dict with format blockgroup:dict, where the dict in each value has information about each blockgroup
			Input: oipInputDict -> dict mapping oip_var names to weights; should be a subset of the model inputDict containing only keys that start with 'oip_'
			Input: oipAggMethod -> string containing which aggregation method to use for calculating OIP
		Return: rmMsgs -> list of strings which are messages about which variables were removed from analysis and which blockgroups had 'Not Applicable' for those variables
	'''
	# Create a DF from blockgroupDict to easily operate on it
	bgDF = pd.DataFrame.from_dict(blockgroupDict, orient='index')
	# Create dict of vars that have 'Not Applicable' for at least one blockgroup
	rmVarsToNaBgs = {}
	for varName in bgDF.columns:
		varNaDF = bgDF[bgDF[varName] == 'Not Applicable']
		naBgs = varNaDF['blockgroupFIPS'].tolist()
		if len(naBgs) == bgDF.shape[0]:
			rmVarsToNaBgs[varName] = 'all'
		elif len(naBgs) != 0:
			rmVarsToNaBgs[varName] = naBgs
	# Create a version of bgDF with normalized columns, removing ones with 'Not Applicable' entries
	normDict = {}
	for varName in bgDF.drop(list(rmVarsToNaBgs.keys()), axis=1).columns:
		if varName in oipInputDict:
			doInvert = varName in ['oip_employed', 'oip_income']
			normDict[varName] = minmaxNorm(list(bgDF[varName].apply(float)), doInvert)
	normDF = pd.DataFrame(normDict)
	# Create OIP Score and OIP Index
	if oipAggMethod == 'Average of Min-Max-Normalized':
		oipAggFunc = arithMean
	elif oipAggMethod == 'RMS of Min-Max-Normalized':
		oipAggFunc = rms
	else:
		raise Exception('ERROR: Unexpected value for oip Aggregation Method')
	orderedVars = []
	orderedWeights = []
	for varName, weight in oipInputDict.items():
		if varName not in rmVarsToNaBgs:
			orderedVars.append(varName)
			orderedWeights.append(weight)
	oipSeries = normDF[orderedVars].agg(oipAggFunc, 1, orderedWeights)
	bgDF['OIP Score'] = oipSeries.fillna(0).values
	bgDF['OIP Index'] = bgDF['OIP Score'].rank(pct=True, method='max')
	bgDF['OIP Rating'] = bgDF.apply(buildOIPRating, axis=1)
	# Add OIP Score and OIP Index to blockgroupDict
	for bg, data in blockgroupDict.items():
		data['OIP Score'] = bgDF.loc[bgDF['blockgroupFIPS'] == bg, 'OIP Score'].iloc[0]
		data['OIP Index'] = bgDF.loc[bgDF['blockgroupFIPS'] == bg, 'OIP Index'].iloc[0]
		data['OIP Rating'] = bgDF.loc[bgDF['blockgroupFIPS'] == bg, 'OIP Rating'].iloc[0]
	# Create a list of messages about which vars were removed because they contain 'Not Applicable'
	vars2Plaintext = {
		'oip_employed': '% Age 16+ Employed',
		'oip_age65': '% Age 65+',
		'oip_crowding': '% Crowding',
		'oip_poverty': '% Individuals Below Poverty Level',
		'oip_disabled': '% Individuals Disabled',
		'oip_lim_eng': '% Limited English Speaking Households',
		'oip_mobile': '% Mobile Home',
		'oip_multi': '% Multi-Unit Structure',
		'oip_no_vehicle': '% No Vehicle',
		'oip_nongrad': '% Non-HS Grads',
		'oip_below19': '% Non-Institutionalized Below Age 19',
		'oip_income': 'Avg Aggregate Household Income (USD)',
		'oip_af_avln': 'Avalanche',
		'oip_af_cwav': 'Cold Wave',
		'oip_af_drgt': 'Drought',
		'oip_af_erqk': 'Earthquake',
		'oip_af_hail': 'Hail',
		'oip_af_hwav': 'Heat Wave',
		'oip_af_hrcn': 'Hurricane',
		'oip_af_istm': 'Ice Storm',
		'oip_af_lnds': 'Landslide',
		'oip_af_ltng': 'Lightning',
		'oip_af_swnd': 'Strong Wind',
		'oip_af_wfir': 'Wildfire',
		'oip_af_wntw': 'Winter Weather'
	}
	rmMsgs = []
	for varName, bgs in rmVarsToNaBgs.items():
		msg = f'"{vars2Plaintext[varName]}" removed from analysis because the source data does not contain a value for the following blockgroups: {bgs}.'
		rmMsgs.append(msg)
	return rmMsgs
############################## End Outage Impact Potential Code ##################################

def addPctlToDict(inDict, varName, tieBreaker = None):
	''' Gets percentile of specified variable, resolving ties with optional tie-breaker

		Args:
			Input: inDict -> Dictionary of circuit objects with keys in the format type.name (e.g. load.s733) and dicts of their attributes as values
			Input: varName -> The name of the attribute in loadDict to calculate percentiles for, chosen from 'base crit score' or 'locational crit score'
			Input: tieBreaker -> The name of the attribute in loadDict to use as a tie-breaker
	'''
	# Validate inputs
	if not isinstance(inDict, dict):
		raise ValueError("The 'loadDict' argument must be a dictionary.")
	if not isinstance(varName, str) or not varName:
		raise ValueError("The 'varName' argument must be a non-empty string.")
	if tieBreaker and not isinstance(tieBreaker, str):
		raise ValueError("The 'tieBreaker' argument must be a string if provided.")
	# Retrieve variable values and handle missing data
	obServedVals = [v.get(varName) for k, v in inDict.items()]
	if None in obServedVals:
		raise ValueError(f"Missing values detected in '{varName}'.")
	# Retrieve tie-breaker values or default to zeros
	if tieBreaker:
		tieBreakerVals = [v.get(tieBreaker, 0) for k, v in inDict.items()]
		if None in tieBreakerVals:
			raise ValueError(f"Missing values detected in tie-breaker '{tieBreaker}'.")
	else:
		tieBreakerVals = [0] * len(inDict)
	# Ensure consistent lengths
	if len(obServedVals) != len(tieBreakerVals):
		raise ValueError("Mismatch in lengths of primary and tie-breaker values.")
	# Rank values with tiebreakers
	rankingDf = pd.DataFrame({
		'primaryVals': obServedVals,
		'tiebreakerVals': tieBreakerVals
	})
	rankingDf['pct_rank'] = rankingDf[['primaryVals', 'tiebreakerVals']].apply(tuple, axis=1).rank(pct=True, method='max')
	# Assign percentiles to the loads dictionary
	if varName in ['base crit score', 'locational crit score']:
		newVarName = varName.replace('score', 'index')
	else:
		raise ValueError('Variable varName must be equal to \'base crit score\' or \'locational crit score\'')
	for i, (k, v) in enumerate(inDict.items()):
		if not isinstance(v, dict):
			raise ValueError(f"Invalid load format for key '{k}'. Expected a dictionary.")
		inDict[k][newVarName] = rankingDf.loc[i, 'pct_rank']

def addBgInfoToLoads(loadDict, blockgroupDict, loads2BgDict, avgPeakDemand):
	''' Add blockgroup, OIP Score, and OIP Index to loadDict for each load in each blockgroup.
		Calculate 'base crit score' based on load kva, feeder avgPeakDemand, and blockgroup avgNumOccupants.
		Calculate 'locational crit score' based on 'base crit score' and OIP Score.
		Then calculate base crit index (bci) and locational crit index (lci)  and add them to loadDict. 
	'''
	# Add blockgroup values to loads and calculate base and locational crit scores based on blockgroup values
	for loadKey, loadData in loadDict.items():
		blockgroup = loads2BgDict[loadKey]
		loadData['blockgroup'] = blockgroup
		
		avgNumOccupants = blockgroupDict[blockgroup]['avg_hh_occupants']
		avgPeakDemand	= float(avgPeakDemand)
		kva 			= loadData['kva']
		BCS				= (kva / avgPeakDemand) * avgNumOccupants
		loadData['base crit score'] = BCS
		
		oipScore 	= blockgroupDict[blockgroup]['OIP Score']
		oipIndex 	= blockgroupDict[blockgroup]['OIP Index']
		LCS			= BCS * oipScore
		loadData['oip score'] = oipScore
		loadData['oip index'] = oipIndex
		loadData['locational crit score'] = LCS
	addPctlToDict(loadDict, 'base crit score', 'distance_from_source')
	addPctlToDict(loadDict, 'locational crit score', 'distance_from_source')

def organizeInfoIntoDFs (loadDict, blockgroupDict, totalSections):
	''' Returns 3 dataframes (bgDF, bgGeoDF, sectionLoadSummaryDF) from the information in loadDict, blockgroupDict, and totalSections.

		bgDF contains all info from blockgroupDict except geometry + a summary of info about loads in each blockgroup

		bgGeoDF is a geoDataFrame containing all info from bgDF with columns renamed to names that should be displayed in tooltips for map polygons

		sectionLoadSummaryDF contains a summary of info about loads in each section with filled None values in sections that lack loads
	'''
	# Create bgDF with blockgroup info + summarized load info for each blockgroup
	loadDF = pd.DataFrame.from_dict(loadDict, orient='index')
	loadDF = loadDF.rename(columns={'blockgroup':'blockgroupFIPS'})
	aggKwargs = {
		'avg_BCS':('base crit score', 'mean'),
		'avg_LCS':('locational crit score', 'mean'),
		'avg_BCI':('base crit index', 'mean'),
		'avg_LCI':('locational crit index', 'mean'),
		'load_count':('base crit score', 'count'),
		'load_amount':('kva', 'sum') 
	}
	bgLoadSummaryDF = loadDF.groupby('blockgroupFIPS').agg(**aggKwargs).reset_index()
	bgDF = pd.DataFrame.from_dict(blockgroupDict, orient='index')
	bgDF = bgDF.merge(bgLoadSummaryDF, on='blockgroupFIPS', how='left')
	# Order bgDF columns and create a geoDF with variables given display names for the map tooltip
	orderedVar2DisplayName = OrderedDict([
		('OIP Rating','OIP Rating'),
		('OIP Score','OIP Score'),
		('OIP Index','OIP Index'),
		('avg_BCS','Avg BCS'),
		('avg_LCS','Avg LCS'),
		('avg_BCI','Avg BCI'),
		('avg_LCI','Avg LCI'),
		('avg_hh_occupants', 'Avg Household Occupants'),
		('load_count','Load Count'),
		('load_amount','Demand (kva)'),
		('blockgroupFIPS','Blockgroup FIPS'),
		('oip_poverty','_____________ % Individuals Below Poverty Level'),
		('oip_employed','_____________ % Age 16+ Employed'),
		('oip_income','_____________ Avg Aggregate Household Income (USD)'),
		('oip_nongrad','_____________ % Non-HS Grads'),
		('oip_age65','_____________ % Age 65+'),
		('oip_below19','_____________ % Non-Institutionalized Below Age 19'),
		('oip_disabled','_____________ % Individuals Disabled'),
		('oip_lim_eng','_____________ % Limited English Speaking Households'),
		('oip_multi','_____________ % Multi-Unit Structure'),
		('oip_mobile','_____________ % Mobile Home'),
		('oip_crowding','_____________ % Crowding'),
		('oip_no_vehicle','_____________ % No Vehicle'),
		('oip_af_avln','_____________ Annual Freq: Avalanche'),
		('oip_af_cwav','_____________ Annual Freq: Cold Wave'),
		('oip_af_drgt','_____________ Annual Freq: Drought'),
		('oip_af_erqk','_____________ Annual Freq: Earthquake'),
		('oip_af_hail','_____________ Annual Freq: Hail'),
		('oip_af_hwav','_____________ Annual Freq: Heat Wave'),
		('oip_af_hrcn','_____________ Annual Freq: Hurricane'),
		('oip_af_istm','_____________ Annual Freq: Ice Storm'),
		('oip_af_lnds','_____________ Annual Freq: Landslide'),
		('oip_af_ltng','_____________ Annual Freq: Lightning'),
		('oip_af_swnd','_____________ Annual Freq: Strong Wind'),
		('oip_af_wfir','_____________ Annual Freq: Wildfire'),
		('oip_af_wntw','_____________ Annual Freq: Winter Weather'),
		('geometry','geometry')
	])
	bgDF = bgDF[list(orderedVar2DisplayName.keys())]
	bgDF['geometry'] = bgDF['geometry'].apply(Polygon)
	bgGeoDF = gpd.GeoDataFrame(bgDF, geometry=bgDF['geometry'], crs='EPSG:4326')
	bgGeoDF = bgGeoDF.rename(columns=orderedVar2DisplayName)
	bgDF = bgDF.drop(columns=['geometry'])
	# Create sectionLoadSummaryDF, filling in any missing values that may occur
	aggKwargs['avg_OIP_Score'] = ('oip score', 'mean')
	sectionLoadSummaryDF = loadDF.groupby('section').agg(**aggKwargs).reset_index()
	existingSections = set(sectionLoadSummaryDF['section'])
	for section in range(1,totalSections+1):
		if section not in existingSections:
			fillVals = {'section':[section], **{k:[None] for k in aggKwargs.keys()}}
			sectionLoadSummaryDF = pd.concat([sectionLoadSummaryDF,	pd.DataFrame(fillVals)], ignore_index=True)
	sectionLoadSummaryDF = sectionLoadSummaryDF.sort_values(by='section').reset_index(drop=True)
	return bgDF, bgGeoDF, sectionLoadSummaryDF

def makeEquipmentDict(pathToOmd, omd, sectionsDict, loadDict, equipmentList):
	''' Returns a dictionary with entries for all equipment on the feeder in equipmentList.
		In addition to data already present in the feeder, equipment also has the following data added to it:

		'section', 'downlineObs', 'downlineLoads', 'base crit score', 'locational crit score', 'base crit index', 'locational crit index'
	'''
	# Make a dict of all objects in the omd and a namesToKeys dict
	obDict = {}
	namesToKeys = {}
	for ob in omd.get('tree', {}).values():
		obType = ob['object']
		obName = ob['name']
		obKey = f'{obType}.{obName}'
		namesToKeys[obName] = obKey
		# Add ob section and ob data from omd to all obs
		obDict[obKey] = ob
		fromField = ob.get('from', None)
		toField = ob.get('to', None)
		sectionKey = str((fromField, toField))
		if sectionKey in sectionsDict and fromField and toField:
			obDict[obKey]['section'] = sectionsDict[sectionKey]
		else: 
			# .get because we DO want None if obName isn't in sectionsDict
			obDict[obKey]['section'] = sectionsDict.get(obName)
	# Add downline loads and downline obs (which includes loads) to each object in obDict using networkX
	digraph = createGraph(pathToOmd)
	nodes = digraph.nodes()
	for ob in obDict.values():
		obName = ob['name']
		obTo = ob.get('to')
		if obName in nodes:
			startingPoint = obName
		elif obTo in nodes:
			startingPoint = obTo
		else:
			continue
		descendants = nx.descendants(digraph, startingPoint)
		ob['downlineObs'] = set()
		ob['downlineLoads'] = set()
		if ob['object'] in equipmentList:
			for desName in descendants:
				desKey = namesToKeys.get(desName)
				if desKey == None:
					raise Exception(f'ERROR: Element {desName} referenced by another object does not have its own entry in the omd')
				ob['downlineObs'].add(desKey)
				if desKey.split('.')[0] == 'load':
					ob['downlineLoads'].add(desKey)
	# Create equipmentDict with equipment metrics based on downline loads
	equipmentDict = {k:v for k,v in obDict.items() if v.get('object') in equipmentList}
	for equipData in equipmentDict.values():
		bcSum = 0
		lcSum = 0
		for dl in equipData['downlineLoads']:
			# This check is done in the case that loadsDict is a strict subset of all loads on the feeder. E.g. only residential loads
			loadData = loadDict.get(dl)
			if loadData:
				bcSum += loadData['base crit score']
				lcSum += loadData['locational crit score']
		equipData['base crit score'] = bcSum
		equipData['locational crit score'] = lcSum
	addPctlToDict(equipmentDict, 'base crit score')
	addPctlToDict(equipmentDict, 'locational crit score')
	return equipmentDict

############################## Add Info to Omd Tree Code ######################################
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
			ob['section'] 					= loadsDict.get(k,{}).get('section')
			ob['base crit score'] 			= loadsDict.get(k,{}).get('base crit score')
			ob['base crit index'] 			= loadsDict.get(k,{}).get('base crit index')
			ob['locational crit score']	= loadsDict.get(k,{}).get('locational crit score')
			ob['locational crit index']	= loadsDict.get(k,{}).get('locational crit index')
			ob['kva']						= loadsDict.get(k,{}).get('kva')
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
			ob['section'] 					= obDict.get(k,{}).get('section')
			ob['base crit score'] 			= obDict.get(k,{}).get('base crit score')
			ob['base crit index'] 			= obDict.get(k,{}).get('base crit index')
			ob['locational crit score'] = obDict.get(k,{}).get('locational crit score')
			ob['locational crit index'] = obDict.get(k,{}).get('locational crit index')
		else:
			continue
	return omdDict

def addEquipLifeData(omdTree, equipLifePath):
	''' Adds available equipment lifetime data from Equipment Lifetime (.csv file) info to items in omdTree. Directly modifies omdTree. 
		Args:
			Input: omdTree -> tree dict representation of omd
			Input: equipLifePath -> Path to equipment lifetime csv
	'''
	equipLifeDF = pd.read_csv(equipLifePath)
	equipNames2Consider = equipLifeDF['equipment name']
	if not equipNames2Consider.is_unique:
		raise Exception('ERROR: All entries in the \'equipment name\' column of Equipment Lifetime (.csv file) must be unique')
	
	equipLifeDF = equipLifeDF.set_index('equipment name')
	for ob in omdTree.get('tree', {}).values():
		obName = ob['name']
		if (obName == equipNames2Consider).any():
			# cols explicitly chosen rather than just looping through existing col names from the file for the sake of controlling what information we display if extraneous cols are included
			ob['% through planned usable lifetime'] = equipLifeDF.loc[obName,'% through planned usable lifetime'].item()
			ob['avg hrs to restore'] 				= equipLifeDF.loc[obName,'avg hrs to restore'].item()
		else:
			continue
############################## End Add Info to Omd Tree Code ##################################

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
	new_df = new_df.fillna(-1)
	new_df[['base crit score','locational crit score','base crit index','locational crit index','section']].to_csv(pJoin(modelDir, 'color_by.csv'), index=True)

def copyInputFilesToModelDir(modelDir, inputDict):
	''' Creates local copies of input files in the model directory modelDir.
		
		Returns a list of paths in the order: 
		
		custInfoPath, equipLifePath
	'''	
	inDictKeys = [
		{	
			'fname':'customerFileName',
			'data':'customerData'
		},
		{
			'fname':'equipLifeFileName',
			'data':'equipLifeData'
		}
	]
	localPaths = []
	for dk in inDictKeys:
		localPath = pJoin(modelDir, inputDict[dk['fname']])
		data = inputDict[dk['data']]
		if data != '':
			with open(localPath, 'w') as file:
				file.write(data)
		else:
			localPath = None
		localPaths.append(localPath)	
	return localPaths

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	outData = {}
	# files
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd') and x != 'color_test.omd'][0][:-4]
	inputDict['feederName1'] = feederName
	pathToOmd = pJoin(modelDir, feederName+'.omd')
	census_nri_path = pJoin(omf.omfDir,'static','testFiles','resilientCommunity', 'census_and_NRI_database.json')
	geoJson_shapes_file = pJoin(modelDir, 'geoshapes.geojson')
	oipDF_file = pJoin(modelDir, 'oipDF.csv')
	custInfoPath, equipLifePath = copyInputFilesToModelDir(modelDir, inputDict)
	zillowPricesPath = pJoin(omf.omfDir,'static','testFiles','resilientCommunity','zillowPrices.json')
	# check if census data json is downloaded
	# if not download
	# make sure computer has 8.59 GB Space for download
	#   if not os.path.exists(census_nri_path):
	#	   retrieveCensusNRI()
	#   elif inputDict['refresh']:
	#	   retrieveCensusNRI()


	#Create a subset of InputDict so we're not passing the entirety of inputDict to a function
	oipInputDict = {varName:float(varWeight) for varName,varWeight in inputDict.items() if 'oip_' == varName[:4]}
	with open(pathToOmd) as f:
		omd = json.load(f)
	# Section the Feeder
	sectionsDict, distanceDict, totalSections = runSections(pathToOmd, omd)
	# Create loadDict
	custInfoDF = pd.read_csv(custInfoPath)
	restrictToResidential = useOipCustVars(oipInputDict)
	loadDict, loadCoordsDict = makeLoadDicts(omd, sectionsDict, distanceDict, custInfoDF, restrictToResidential)
	# Create blockgroupDict
	blockgroupDict, loads2BgDict = makeBlockgroupDicts(modelDir, loadCoordsDict, feederName)
	outData['rmMsgs'] = addOipToBlockgroups(blockgroupDict, oipInputDict, inputDict['oipAggMethod'])
	# Add bg info to loads
	addBgInfoToLoads(loadDict, blockgroupDict, loads2BgDict, inputDict['averageDemand'])
	with open(pJoin(modelDir,'loadData4RestorationModel.json'), 'w') as f:
		json.dump(loadDict,f,indent=4)
	# Create DFs for model outputs
	bgDF, bgGeoDF, sectionDF = organizeInfoIntoDFs(loadDict, blockgroupDict, totalSections)
	# Create equipmentDict
	equipmentList = ['bus']
	for equip in ['line', 'transformer', 'fuse']:
		if inputDict[f'{equip}s'].lower() == 'yes':
			equipmentList.append(equip)
	equipmentDict = makeEquipmentDict(pathToOmd, omd, sectionsDict, loadDict, equipmentList)

	# check downline loads
	# useZillow = False
	# TODO: Add zillow data usage with new source of zillow data

	# color vals based on selected column
	createColorCSVBlockGroup(modelDir, loadDict, equipmentDict)
	if(inputDict['loadCol'] == 'Base Criticality Score'):
		colVal = "1"
	elif (inputDict['loadCol'] == 'Locational Criticality Score'):
		colVal = "2"
	elif(inputDict['loadCol'] == 'Base Criticality Index'):
		colVal = "3"
	elif(inputDict['loadCol'] == 'Locational Criticality Index'):
		colVal = "4"
	elif(inputDict['loadCol'] == 'Feeder Sections'):
		colVal = "5"
	else:
		colVal = None
	# Load Geojson file more efficiently
	smartRound = lambda x: round(x,2) if isinstance(x,float) else x
	bgGeoDF = bgGeoDF.map(smartRound)
	bgGeoDF.to_file(geoJson_shapes_file, driver="GeoJSON")
	bgDF.to_csv(oipDF_file)
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
	outData['oipData'] = open(oipDF_file, 'r').read()
	with open(pathToOmd) as file1:
		init_omdJson = json.load(file1)
	newOmdJson = addLoadInfoToOmd(loadDict, init_omdJson)
	omdJson = addEquipmentInfoToOmd(equipmentDict, newOmdJson, equipmentList)
	addEquipLifeData(omdJson, equipLifePath)
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
	for load_names,v in loadDict.items():
		row = (
			load_names,
			v.get('section'),
			round(v.get('base crit score'),2),
			round(v.get('base crit index'),2),
			round(v.get('locational crit score'),2),
			round(v.get('locational crit index'),2),
			round(v.get('oip score'),4),
			round(v.get('oip index'),4),
			round(v.get('kva'),2)
		)
		tableRows1.append(row)
	outData['loadTableHeadings'] = ['Load Name','Section', 'Base Criticality Score', 'Base Criticality Index','Locational Criticality Score', 'Locational Criticality Index', 'Outage Impact Potential Score', 'Outage Impact Potential Index', 'Demand (kva)']
	outData['loadTableValues'] = tableRows1
	
	# Collect Equipment Data Table Info
	tableRows2 = []
	for object_names,v in equipmentDict.items():
		row = (
			object_names,
			v.get('section'),
			round(v.get('base crit score'),2),
			round(v.get('base crit index'),2),
			round(v.get('locational crit score'),2),
			round(v.get('locational crit index'),2)
			)
		tableRows2.append(row)
	outData['loadTableHeadings2'] = ['Equipment Name', 'Section', 'Base Criticality Score', 'Base Criticallity Index', 'Locational Criticality Score', 'Locational Criticality Index']
	outData['loadTableValues2'] = tableRows2
	
	# Collect Sections Data Table Info
	headers3 = ['Section', 'Base Criticality Score', 'Base Criticallity Index', 'Locational Criticality Score', 'Locational Criticality Index','Outage Impact Potential Score','Load Count', 'Demand (kva)']
	cols = ['section', 'avg_BCS', 'avg_BCI', 'avg_LCS', 'avg_LCI', 'avg_OIP_Score', 'load_count', 'load_amount']
	sectionDF[['load_count','load_amount']] = sectionDF[['load_count','load_amount']].fillna(0)
	sectionDF[cols[1:]] = sectionDF[cols[1:]].fillna('None').map(smartRound)
	tableRows3 = list(sectionDF[cols].itertuples(index=False, name=None))
	outData['loadTableHeadings3'] = headers3
	outData['loadTableValues3'] = tableRows3
	return outData

def new(modelDir):
	#omdfileName = 'iowa240_in_Florida_copy2'
	#omdfileName = 'iowa240_dwp_22_no_show_voltage.dss'
	#omdfileName = 'ieee37_LBL_simplified'
	omdfileName = 'iowa240_in_Florida_copy2_no_show_voltage.dss'

	# Establish Default Files
	customerFileName = 	[omf.omfDir,'static','testFiles','resilientCommunity','restorationLoads.csv']
	customerData = open(pJoin(*customerFileName)).read()
	equipLifeFileName = [omf.omfDir,'static','testFiles','resilientCommunity','equipLifeExample.csv']
	equipLifeData = open(pJoin(*equipLifeFileName)).read()

	defaultInputs = {
		"modelType": modelName,
		"feederName1": omdfileName,
		"customerFileName": customerFileName[-1],
		"customerData": customerData,
		"equipLifeFileName": equipLifeFileName[-1],
		"equipLifeData": equipLifeData,
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
		"agriculture": "yes",
		"oipAggMethod": "Average of Min-Max-Normalized",
		"oip_employed":1,
		"oip_age65":1,
		"oip_crowding":1,
		"oip_poverty":1,
		"oip_disabled":1,
		"oip_lim_eng":1,
		"oip_mobile":1,
		"oip_multi":1,
		"oip_no_vehicle":1,
		"oip_nongrad":1,
		"oip_below19":1,
		"oip_single_par":1,
		"oip_income":1,
		"oip_af_avln":1,
		"oip_af_cwav":1,
		"oip_af_drgt":1,
		"oip_af_erqk":1,
		"oip_af_hail":1,
		"oip_af_hwav":1,
		"oip_af_hrcn":1,
		"oip_af_istm":1,
		"oip_af_lnds":1,
		"oip_af_ltng":1,
		"oip_af_swnd":1,
		"oip_af_wfir":1,
		"oip_af_wntw":1
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		#shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
		#shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "testFiles","resilientCommunity", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile(pJoin(*customerFileName), pJoin(modelDir, defaultInputs["customerFileName"]))
		shutil.copyfile(pJoin(*equipLifeFileName), pJoin(modelDir, defaultInputs["equipLifeFileName"]))
	except:
		return False
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
	#stripDownCensusNRI(['AVLN_AFREQ', 'CFLD_AFREQ', 'CWAV_AFREQ', 'DRGT_AFREQ', 'ERQK_AFREQ', 'HAIL_AFREQ', 'HWAV_AFREQ', 'HRCN_AFREQ', 'ISTM_AFREQ', 
	#		'LNDS_AFREQ', 'LTNG_AFREQ', 'RFLD_AFREQ', 'SWND_AFREQ', 'TRND_AFREQ', 'TSUN_AFREQ', 'VLCN_AFREQ', 'WFIR_AFREQ', 'WNTW_AFREQ', 'AREA'])
	#print("done")
	#tests()
	#getDistributionSection(
	#sectionExample("/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/iowa240_in_Florida_copy2.omd")
	#newSection("/Users/davidarmah/Documents/omf/omf/static/testFiles/resilientCommunity/iowa240_in_Florida_copy2.omd")
	#getDistribution()
	#testRunCalculations()