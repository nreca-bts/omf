''' Communications network modeling and visualization.'''
import json, os, shutil, math, tempfile, random, webbrowser
from os.path import join as pJoin
from collections import defaultdict
from pyproj import Proj, transform, Geod
from scipy.spatial import ConvexHull, Delaunay
import networkx as nx
import numpy as np
import omf

def treeToNxGraph(inTree):
	''' Convert feeder tree to networkx graph. '''
	outGraph = nx.Graph()
	for key in inTree:
		item = inTree[key]
		if 'name' in item.keys():
			if 'parent' in item.keys():
				outGraph.add_edge(item['name'], item['parent'], type='parentChild')
				outGraph.nodes[item['name']]['type'] = item['object']
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
				# Note that attached houses via gridEdit.html won't have lat/lon values, so this try is a workaround.
				try:
					outGraph.nodes[item['name']]['pos'] = (float(item.get('latitude', 0)), float(item.get('longitude', 0)))
				except:
					outGraph.nodes[item['name']]['pos'] = (0.0, 0.0)
			elif 'from' in item.keys():
				outGraph.add_edge(item['from'], item['to'], name=item.get('name', ''), type=item['object'])
			elif item['name'] in outGraph:
				# Edge already led to node's addition, so just set the attributes:
				outGraph.nodes[item['name']]['type'] = item['object']
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
			else:
				outGraph.add_node(item['name'], type=item['object'])
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
			if 'latitude' in item.keys() and 'longitude' in item.keys():
				# Ignore lines that have "latitude" and "longitude" properties
				if 'from' not in item.keys():
					try:
						outGraph.nodes[item['name']]['pos'] = (float(item['latitude']), float(item['longitude'])) 
					except:
						outGraph.nodes[item['name']]['pos'] = (0.0, 0.0)
	return outGraph


def treeToCommsDiNxGraph(inTree):
	''' Convert feeder tree to a DIRECTED networkx graph. '''
	outGraph = nx.DiGraph()
	network_objects = ['regulator', 'overhead_line', 'underground_line', 'transformer', 'fuse', 'switch', 'triplex_line', 'node', 'triplex_node', 'meter', 'triplex_meter', 'load', 'triplex_load', 'series_reactor']
	for key in inTree:
		item = inTree[key]
		if 'object' in item:
			if item['object'] == 'switch':
				if 'OPEN' in item.values(): #super hacky
					continue
		if 'name' in item.keys():#sometimes network objects aren't named!
			if 'parent' in item.keys():
				outGraph.add_edge(item['parent'], item['name'], type='parentChild', length=0) # jfk. swapped from,to
				outGraph.nodes[item['name']]['type'] = item['object']
				outGraph.nodes[item['name']]['pos'] = (float(item.get('latitude', 0)), float(item.get('longitude', 0)))
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
			elif 'from' in item.keys():
				outGraph.add_edge(item['from'], item['to'], type=item['object'], length=float(item.get('length', 0)))
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
			elif item['name'] in outGraph:
				# Edge already led to node's addition, so just set the attributes:
				outGraph.nodes[item['name']]['type'] = item['object']
				if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
			else:
				outGraph.add_node(item['name'], type=item['object'])
			if 'latitude' in item.keys() and 'longitude' in item.keys():
				if 'from' not in item.keys(): # Ignore lines that have "latitude" and "longitude" properties
					outGraph.nodes[item['name']]['pos'] = (float(item['latitude']), float(item['longitude']))
			if 'bustype' in item.keys():
					outGraph.nodes[item['name']]['substation'] = True
		elif 'object' in item.keys() and item['object'] in network_objects: # when name doesn't exist
			if 'from' in item.keys():
				outGraph.add_edge(item['from'], item['to'], type=item['object'], length=float(item.get('length', 0)))
			if 'latitude' in item.keys() and 'longitude' in item.keys():
				# This line of code is wrong. How can we look up a node inside of outGraph if 1) it doesn't have a name 2) it was never added to
				# the outGraph in the first place? This line returns an empty dict and does nothing. Hopefully this code should never be invoked.
				outGraph.nodes.get(item['name'], {})['pos'] = (float(item['latitude']), float(item['longitude']))
			if 'bustype' in item.keys():
				outGraph.nodes[item['name']]['substation'] = True
	return outGraph


def createGraph(pathToOmdFile):
	'''Create networkxgraph from omd'''
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)['tree']
	nxG = treeToCommsDiNxGraph(tree)
	#use conversion for testing other feeders
	nxG = graphValidator(pathToOmdFile, nxG)
	return nxG


def getSubstation(nxG):
	'''Get the substation node from a feeder'''
	return [sub for sub in nx.get_node_attributes(nxG, 'substation') if nxG.nodes[sub].get('substation', False)][0]


def getDistance(nxG, start, end):
	'''Get the distance between two points in a graph'''
	dist = math.sqrt( (nxG.nodes[end]['pos'][1] - nxG.nodes[start]['pos'][1])**2 + (nxG.nodes[end]['pos'][0] - nxG.nodes[start]['pos'][0])**2 )
	return dist


def findNearestPoint(nxG, smartMeter, rfCollectors):
	'''Find the nearest point for a smartMeter based on a list of rfCollectors'''
	nearest = min(rfCollectors, key = lambda rfCollector: getDistance(nxG, smartMeter, rfCollector))
	return nearest


def setSmartMeters(nxG):
	'''sets all nodes with type meter or triplex meter to smartMeters''' 
	#to do add in other areas where needed
	for meter in nx.get_node_attributes(nxG, 'type'):
		if nxG.nodes[meter]['type'] in ['meter', 'triplex_meter']:
			nxG.nodes[meter]['smartMeter'] = True


def setSmartMeterBandwidth(nxG, packetSize=10):
	'''sets all smartMeter bandwidth and capacity to the packetSize'''
	for meter in nx.get_node_attributes(nxG, 'smartMeter'):
		if nxG.nodes[meter].get('smartMeter', False):
			nxG.nodes[meter]['bandwidthCapacity'] = packetSize
			nxG.nodes[meter]['bandwidthUse'] = packetSize


def setRFCollectors(nxG, edgeType='switch'):
	'''Set fiber on path between certain edgeType (switch is the defualt for now) and the substation'''
	node_positions = {nodewithPosition: nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')}
	edge_types = {edge: nxG[edge[0]][edge[1]]['type'] for edge in nx.get_edge_attributes(nxG, 'type')}
	substation = getSubstation(nxG)
	#collector position will validate that only one collector is added at each position
	collector_positions = []
	for node in node_positions:
		for edge in nxG.out_edges(node):
			if edge_types.get(edge, '') == edgeType:
				if nxG.nodes[node]['pos'] not in collector_positions:
					collector_positions.append(nxG.nodes[node]['pos']) 
					nxG.nodes[node]['rfCollector'] = True


def setRFCollectorCapacity(nxG, rfBandwidthCap=1000):
	for rfCollector  in nx.get_node_attributes(nxG, 'rfCollector'):
		if nxG.nodes[rfCollector].get('rfCollector', False):
			nxG.nodes[rfCollector]['bandwidthCapacity'] = rfBandwidthCap


def setFiber(nxG):
	'''Set fiber between rfcollectors and substation'''
	substation = getSubstation(nxG)
	for rfCollector in nx.get_node_attributes(nxG, 'rfCollector'):
		if nxG.nodes[rfCollector].get('rfCollector', False):
			shortestPath = nx.bidirectional_shortest_path(nxG, substation, rfCollector)
			for i in range(len(shortestPath)-1):
				nxG[shortestPath[i]][shortestPath[i+1]]['fiber'] = True
				nxG[shortestPath[i]][shortestPath[i+1]]['bandwidthUse'] = 0


def setFiberCapacity(nxG, fiberBandwidthCap=1000000, setSubstationBandwidth=False):
	'''Set fiber capacity'''
	substation = getSubstation(nxG)
	#fiber capacity for line is stored in the substation bansdwidth capacity
	if setSubstationBandwidth:
		nxG.nodes[substation]['bandwidthCapacity'] = fiberBandwidthCap
	fiberCapacity = nxG.nodes[substation].get('bandwidthCapacity', 0)
	for edge in nx.get_edge_attributes(nxG, 'fiber'):
		if nxG[edge[0]][edge[1]].get('fiber', False): 
			nxG[edge[0]][edge[1]]['bandwidthCapacity'] = fiberCapacity
			#print(nxG[edge[0]][edge[1]])


def setRF(nxG):
	'''Add rf edges between smartMeters and the nearest rfCollector'''
	rfCollectors = [rfCollector for rfCollector  in nx.get_node_attributes(nxG, 'rfCollector') if nxG.nodes[rfCollector].get('rfCollector', False)]
	for smartMeter in nx.get_node_attributes(nxG, 'smartMeter'):
		if nxG.nodes[smartMeter].get('smartMeter', False):
			rfCollector = findNearestPoint(nxG, smartMeter, rfCollectors)
			nxG.add_edge(rfCollector, smartMeter, rf=True, type='rf')


def setRFEdgeCapacity(nxG):
	'''Calculate bandwidth use for all rf collectors and '''
	rfCollectors = [rfCollector for rfCollector in nx.get_node_attributes(nxG, 'rfCollector') if nxG.nodes[rfCollector].get('rfCollector', False)]
	for rfCollector in rfCollectors:
		#reset bandwidth calculation to 0
		nxG.nodes[rfCollector]['bandwidthUse'] = 0
		#calculate bandwidth use of each rf connection edge between rfcollectors and smartMeters
		if len(list(nxG.successors(rfCollector))) > 0:
			splitCapacity = nxG.nodes[rfCollector].get('bandwidthCapacity', 0) / len(list(nxG.successors(rfCollector)))
			for smartMeter in nxG.successors(rfCollector):
				if nxG[rfCollector][smartMeter].get('rf', False):
					nxG[rfCollector][smartMeter]['bandwidthCapacity'] = splitCapacity


def calcEdgeLengths(nxG):
	'''Calculate the lengths of edges based on lat/lon position'''
	G = Geod(ellps='WGS84')
	for edge in nx.edges(nxG):
		nxG[edge[0]][edge[1]]['length'] = G.inv(nxG.nodes[edge[0]]['pos'][1], nxG.nodes[edge[0]]['pos'][0], nxG.nodes[edge[1]]['pos'][1], nxG.nodes[edge[1]]['pos'][0])[2]


def getFiberCost(nxG, fiberCostPerMeter):
	'''Calculate the cost of fiber'''
	fiber_cost = sum((nxG[edge[0]][edge[1]]['length'])*fiberCostPerMeter for edge in nx.get_edge_attributes(nxG, 'fiber') if nxG[edge[0]][edge[1]].get('fiber', False))
	return fiber_cost


def getrfCollectorsCost(nxG, rfCollectorCost):
	'''Calculate the cost of RF rfCollector equipment'''
	rfCollector_cost = len([rfCollector for rfCollector in nx.get_node_attributes(nxG, 'rfCollector') if nxG.nodes[rfCollector].get('rfCollector', False)])*rfCollectorCost
	return rfCollector_cost


def getsmartMetersCost(nxG, smartMeterCost):
	'''Calculate the cost of RF smartMeter equipment'''
	smartMeter_cost = len([smartMeter for smartMeter in nx.get_node_attributes(nxG, 'smartMeter') if nxG.nodes[smartMeter].get('smartMeter', False)])*smartMeterCost
	return smartMeter_cost


def calcBandwidth(nxG):
	#go through rfCollectors and smartMeters
	#adust later to accept different lengh of rfCollectors
	substation = getSubstation(nxG)
	nxG.nodes[substation]['bandwidthUse'] = 0
	rfCollectors = [rfCollector for rfCollector in nx.get_node_attributes(nxG, 'rfCollector') if nxG.nodes[rfCollector].get('rfCollector', False)]
	for rfCollector in rfCollectors:
		#reset bandwidth calculation to 0
		nxG.nodes[rfCollector]['bandwidthUse'] = 0
		#calculate bandwidth use of each rf connection edge between rfcollectors and smartMeters
		for smartMeter in nxG.successors(rfCollector):
			if nxG[rfCollector][smartMeter].get('rf', False):
				nxG[rfCollector][smartMeter]['bandwidthUse'] = nxG.nodes[smartMeter]['bandwidthUse']
				nxG.nodes[rfCollector]['bandwidthUse'] += nxG.nodes[smartMeter]['bandwidthUse']
		shortestPath = nx.bidirectional_shortest_path(nxG, substation, rfCollector)
		for i in range(len(shortestPath)-1):
			nxG[shortestPath[i]][shortestPath[i+1]]['bandwidthUse'] += nxG.nodes[rfCollector]['bandwidthUse']
		nxG.nodes[substation]['bandwidthUse'] += nxG.nodes[rfCollector]['bandwidthUse']


def clearRFEdges(nxG):
	'''Delete all rf edges'''
	nxG.remove_edges_from(edge for edge in nx.get_edge_attributes(nxG, 'rf') if nxG[edge[0]][edge[1]].get('rf', False))


def clearFiber(nxG):
	'''Set all fiber to false in prep for recalculation'''
	for edge in nx.edges(nxG):
		if nxG[edge[0]][edge[1]].get('fiber', False):
			nxG[edge[0]][edge[1]]['fiber'] = False

'''Mesh network calculations'''

#add a mesh level - check if it can reach the point
#if count mesh level == 0, then end
#if count in mesh level == 1, draw a line, 
#if count > 1, create convex hull
#do you need to interconnect within convex hull?
#create a queue add the substation
#go into loop
	#while the queue is not empty
	#pop the 0 index
	#add mesh level
	#add convex hull that includes the previous mesh (add from start)

#keep track if node on convex hull attaches to another node (basicaly extending outward)

def setMeshLevel(nxG):
	'''Setting mesh level of substation to 0 to start'''
	substation = getSubstation(nxG)
	nxG.nodes[substation]['meshLevel'] = 0


def addMeshLevel(nxG, hull, radius):
	rfRange = radius * 2
	#go through all smart meters
	for start in hull:
		for smartMeter in nx.get_node_attributes(nxG, 'smartMeter'):
			if nxG.nodes[smartMeter]['smartMeter']:
				if nxG.nodes[smartMeter].get('meshLevel', float('inf')) > nxG.nodes[start]['meshLevel']:
					if getDistance(nxG, start, smartMeter) <= rfRange:
						addedLevel = True
						#nxG.add_edge(start, smartMeter, attr_dict={'rf': True, 'type': 'rf'})
						nxG.nodes[smartMeter]['meshLevel'] = nxG.nodes[start]['meshLevel'] + 1
						nxG.nodes[smartMeter]['meshOrigin'] = start
						#add marker that this is connector
						nxG.nodes[start]['connector'] = True


def convexMesh(nxG, meshLevel, geoJsonDict=dict()):
	'''marks nodes that make up the edges of the convex hull'''
	#meshPoints = [nxG.nodes[node]['pos'] for node in nx.get_node_attributes(nxG, 'meshLevel') if nxG.nodes[node].get('meshLevel',-1) == meshLevel]
	#mesh hull is list of points on outer hull
	meshHull = []
	#all points in the same mesh level 
	meshPoints = [(node, node[1]['pos']) for node in nxG.nodes(data=True) if node[1].get('meshLevel', float('inf')) <= meshLevel]
	points = np.array([pos[1] for pos in meshPoints])
	hull = ConvexHull(points)
	concaveBoundary = stitch_boundaries(alpha_shape(points, .0019))[0]
	concaveHull = [points.tolist()[i[0]] for i in concaveBoundary]
	polygon = points[hull.vertices].tolist()
	for node in nxG.nodes(data=True):
		if node[1].get('meshLevel', float('inf')) <= meshLevel:
			if list(node[1]['pos']) in polygon:
				nxG.nodes[node[0]]['hullEdge'] = True
				meshHull.append(node[0])
	for point in concaveHull:
		point.reverse()
	#Add first node to beginning to comply with geoJSON standard
	concaveHull.append(concaveHull[0])
	#Create dict and bump to json file
	concaveHullFeature = {
			"type": "Feature", 
			"geometry":{
				"type": "Polygon",
				"coordinates": [concaveHull]
			},
			"properties": {
				"meshLevel": meshLevel
			}
		}
	geoJsonDict['features'].append(concaveHullFeature)
	return meshHull


'''
def convexHullMesh(nxG, meshLevel, previousMeshHull):
	#meshPoints = [nxG.nodes[node]['pos'] for node in nx.get_node_attributes(nxG, 'meshLevel') if nxG.nodes[node].get('meshLevel',-1) == meshLevel]
	#mesh hull is list of points on outer hull
	if len(previousMeshHull) > 1:
		previousMeshHull.pop()

	meshHull = []
	#all points in the same mesh level 
	meshPoints = [(node, node[1]['pos']) for node in nxG.nodes(data=True) if node[1].get('meshLevel',float('inf')) <= meshLevel]
	points = np.array([pos[1] for pos in meshPoints])
	hull = ConvexHull(points)
	polygon = points[hull.vertices].tolist()
	for point in polygon:
		point.reverse()
	#Add first node to beginning to comply with geoJSON standard
	polygon.append(polygon[0])
	#Create dict and bump to json file
	geoJsonDict = {"type": "FeatureCollection",
		"features": [{
			"type": "Feature", 
			"geometry":{
				"type": "Polygon",
				"coordinates": [polygon]
			},
			"properties": {
				"meshLevel": meshLevel
			}
		}]
	}
	return geoJsonDict'''


def levelCount(nxG, meshLevel):
	'''return number of nodes at a certain mesh level'''
	return len([node for node in nxG.nodes(data=True) if node[1].get('meshLevel', float('inf')) == meshLevel])


def caclulateMeshNetwork(nxG, geoJsonMesh):
	meshLevel = 1
	setMeshLevel(nxG)
	radius = .0005
	hulls = [getSubstation(nxG)]
	addMeshLevel(nxG, hulls, radius)
	while(levelCount(nxG, meshLevel)>0):
		hulls = convexMesh(nxG, meshLevel, geoJsonMesh)
		addMeshLevel(nxG, hulls, radius)
		meshLevel += 1


def meshMap(nxG):
	'''Display a comms network with a mesh map showing minimum jumps'''
	setSmartMeters(nxG)
	geoJsonMesh = {
		"type": "FeatureCollection",
		"features": []
	}
	caclulateMeshNetwork(nxG, geoJsonMesh)
	commsGeoJson = graphGeoJson(nxG)
	commsGeoJson['features'].extend(geoJsonMesh['features'])
	showOnMap(commsGeoJson)


def convexDiff(nxG):
	pass
	#get the previous convex hull = cvx1
	#get the current convex hull = cvx2
	#get the points cvx2 that connect to next level - has edge
		#can networkx get edges that originate from point (successors)? yes and successor is mesh level + 1
	#get the points of cvx1 that dont connect
		#
	#points with successors
	#how to find intersection points
		#if points are in both, then remove, except connection points
		#mark point as
	#get points that are connected onward (marking off in addMeshLevel)


def graphGeoJson(nxG):
	'''Create geojson dict for omc file type for communications network'''
	geoJsonDict = {
		"type": "FeatureCollection",
		"features": []
	}
	node_positions = {nodewithPosition: nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')}
	node_types = {nodewithType: nxG.nodes[nodewithType]['type'] for nodewithType in nx.get_node_attributes(nxG, 'type')}
	for node in node_positions:
		geoJsonDict['features'].append({
			"type": "Feature", 
			"geometry":{
				"type": "Point",
				"coordinates": [node_positions[node][1], node_positions[node][0]]
			},
			"properties":{
				"name": node,
				"pointType": node_types.get(node, ''),
				"substation": nxG.nodes[node].get('substation', False),
				"rfCollector": nxG.nodes[node].get('rfCollector', False),
				"smartMeter": nxG.nodes[node].get('smartMeter', False),
				"bandwidthUse": nxG.nodes[node].get('bandwidthUse', ''),
				"bandwidthCapacity": nxG.nodes[node].get('bandwidthCapacity', '')
			}
		})
	#Add edges to geoJSON
	edge_types = {edge: nxG[edge[0]][edge[1]]['type'] for edge in nx.get_edge_attributes(nxG, 'type')}
	for edge in nx.edges(nxG):
		geoJsonDict['features'].append({
			"type": "Feature", 
			"geometry":{
				"type": "LineString",
				"coordinates": [[node_positions[edge[0]][1], node_positions[edge[0]][0]],[node_positions[edge[1]][1], node_positions[edge[1]][0]]]
			},
			"properties":{
				"edgeType": edge_types.get(edge, ''),
				"fiber": nxG[edge[0]][edge[1]].get('fiber', False),
				"rf": nxG[edge[0]][edge[1]].get('rf', False),
				"bandwidthUse": nxG[edge[0]][edge[1]].get('bandwidthUse', ''),
				"bandwidthCapacity": nxG[edge[0]][edge[1]].get('bandwidthCapacity', ''),
				"source": edge[0],
				"target": edge[1]
			}
		})
	return geoJsonDict


def omcToNxg(omc, fromFile=False):
	'''Convert omc to networkx graph to run calculations. Used when graph is edited in the commsNetViz.html template'''
	outGraph = nx.DiGraph()
	if fromFile:
		with open(omc) as omcFile:
			geoJsonDict = json.load(omcFile)
	else:
		geoJsonDict = omc
	geoNodes = [x for x in geoJsonDict['features'] if x['geometry']['type'] == 'Point']
	geoEdges = [x for x in geoJsonDict['features'] if x['geometry']['type'] == 'LineString']
	for node in geoNodes:
		node_attrs = {
			'substation': node['properties']['substation'],
			'smartMeter': node['properties']['smartMeter'],
			'rfCollector': node['properties']['rfCollector'],
			'type': node['properties']['pointType'],
			'bandwidthCapacity': node['properties']['bandwidthCapacity'],
			'bandwidthUse': node['properties']['bandwidthUse'],
			'pos': tuple(reversed(node['geometry']['coordinates']))
		}
		outGraph.add_node(node['properties']['name'], **node_attrs)
	for edge in geoEdges:
		edge_attrs = {
			'type': edge['properties']['edgeType'],
			'fiber': edge['properties']['fiber'],
			'rf': edge['properties']['rf'],
			'bandwidthUse': edge['properties']['bandwidthUse'],
			'bandwidthCapacity': edge['properties']['bandwidthCapacity']
		}
		outGraph.add_edge(edge['properties']['source'],edge['properties']['target'], **edge_attrs)
	return outGraph


def showOnMap(geoJson):
	'''Open a browser to display a geoJSON object on a map.'''
	tempDir = tempfile.mkdtemp()
	shutil.copy(pJoin(omf.omfDir, 'templates', 'commsNetViz.html'), tempDir)
	with open(pJoin(tempDir, 'commsGeoJson.js'), 'w') as outFile:
		outFile.write('var geojson =')
		json.dump(geoJson, outFile, indent=4)
	webbrowser.open('file://' + pJoin(tempDir, 'commsNetViz.html'))


def saveOmc(geoJson, outputPath, fileName=None):
	'''Save comms geojson dict as .omc proprietary format (it is a geojson)'''
	if fileName is None:
		fileName = 'commsGeoJson'
	if not os.path.exists(outputPath):
		os.makedirs(outputPath)
	with open(pJoin(outputPath, fileName + '.omc'),"w") as outFile:
		json.dump(geoJson, outFile, indent=4)


def graphValidator(pathToOmdFile, inGraph):
	'''If the nodes/edges positions are not in the tree, the spurces and targets in the links key of the omd.json are used. '''
	try:
		node_positions = {nodewithPosition: inGraph.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')}
		for edge in nx.edges(inGraph):
			validator = (node_positions[edge[0]] or nxG.nodes[edge[1]])
	except KeyError:
		raise Exception('Network coordinates are not in the .omd tree. Use the anonymize menu in the circuit editor to generate a circuit with valid coordinates.')
		'''
		This code creates random positional information
		try:
			nxG = latLonValidation(convertOmd(pathToOmdFile))
		except ValueError:
			#No nodes have positions, so create random ones
			nxG = inGraph
			for nodeToChange in nxG.nodes:
				nxG.nodes[nodeToChange]['pos'] = (random.uniform(36.9900, 38.8700), random.uniform(-102.0500,-94.5900))
		return nxG'''
	#should invalid lat/lons be included
	nxG = latLonValidation(inGraph)
	return nxG


'''
def convertOmd(pathToOmdFile):
	with open(pathToOmdFile) as inFile:
		omdFile = json.load(inFile)
		links = omdFile['links']
		tree = omdFile['tree']
	nxG = nx.DiGraph()
	objectNodes = set()
	for key in links:
		objectNodes.add(key['objectType'])
		#Account for nodes that are missing names when creating edges
		try:
			sourceEdge = key['source']['name']
		except KeyError:
			try:
				sourceEdge = str(key['target']['name']) + ' Source'
			except KeyError:
				sourceEdge = str(key['source']) + ' Missing Name'
		try:
			targetEdge = key['target']['name']
		except KeyError:
			try:
				targetEdge = key['target']['name'] + ' Target'
			except KeyError:
				targetEdge = str(key['target']) + ' Missing Name'

		#nxG.add_edge(key['source']['name'], key['target']['name'])
		nxG.add_edge(sourceEdge, targetEdge)
		nxG.nodes[sourceEdge]['pos'] = (float(key['source']['y']), float(key['source']['x']))
		nxG.nodes[targetEdge]['pos'] = (float(key['target']['y']), float(key['target']['x']))
		sourceTreeIndex = str(key['source']['treeIndex'])
		targetTreeIndex = str(key['target']['treeIndex'])
		try:
			nxG.nodes[sourceEdge]['type'] = tree[sourceTreeIndex]['object']
			nxG.nodes[sourceEdge]['name'] = key['source']['name']
			#Get substation - fix later because this seems a little hacky
			if tree[sourceTreeIndex]['bustype'] == 'SWING':
				nxG.nodes[sourceEdge]['substation'] = True
		except KeyError:
			nxG.nodes[sourceEdge]['type'] = 'Undefined'
		try:
			nxG.nodes[targetEdge]['type'] = tree[targetTreeIndex]['object']
			nxG.nodes[targetEdge]['name'] = key['target']['name']
		except KeyError:
			nxG.nodes[targetEdge]['type'] = 'Undefined'
	for nodeToChange in nx.get_node_attributes(nxG, 'pos'):
		#nxG.nodes[nodeToChange]['pos'] = (latitudeCenter + nxG.nodes[nodeToChange]['pos'][1]/latitude_max, longitudeCenter 
		#								+ nxG.nodes[nodeToChange]['pos'][0]/longitude_max)
		#print(nxG.nodes[nodeToChange]['pos'][1], nxG.nodes[nodeToChange]['pos'][0])
		#print(statePlaneToLatLon(nxG.nodes[nodeToChange]['pos'][1], nxG.nodes[nodeToChange]['pos'][0]))
		nxG.nodes[nodeToChange]['pos'] = statePlaneToLatLon(nxG.nodes[nodeToChange]['pos'][1], nxG.nodes[nodeToChange]['pos'][0])
	#print(nxG.nodes)
	return nxG'''


def latLonValidation(inGraph):
	'''Checks if an omd has invalid latlons, and if so, converts to stateplane coordinates or generates random values '''
	latitude_min = min([inGraph.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	longitude_min = min([inGraph.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	latitude_max = max([inGraph.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	longitude_max = max([inGraph.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	if latitude_min < -180 or latitude_max > 180 or longitude_min < -90 or longitude_max > 90:
		for nodeToChange in nx.get_node_attributes(inGraph, 'pos'):
			inGraph.nodes[nodeToChange]['pos'] = statePlaneToLatLon(inGraph.nodes[nodeToChange]['pos'][1], inGraph.nodes[nodeToChange]['pos'][0])
	return inGraph


def statePlaneToLatLon(easting, northing, epsg = None):
	if not epsg:
		# Center of the USA default
		epsg = 26978
	inProj = Proj(init = 'EPSG:' + str(epsg), preserve_units = True)
	outProj = Proj(init = 'EPSG:4326')
	lon, lat = transform(inProj, outProj, easting, northing)
	return (lat, lon)


def alpha_shape(points, alpha, only_outer=True):
	"""
	Compute the alpha shape (concave hull) of a set of points.
	:param points: np.array of shape (n,2) points.
	:param alpha: alpha value.
	:param only_outer: boolean value to specify if we keep only the outer border
	or also inner edges.
	:return: set of (i,j) pairs representing edges of the alpha-shape. (i,j) are
	the indices in the points array.
	"""
	assert points.shape[0] > 3, "Need at least four points"

	def add_edge(edges, i, j):
		"""
		Add an edge between the i-th and j-th points,
		if not in the list already
		"""
		if (i, j) in edges or (j, i) in edges:
			# already added
			assert (j, i) in edges, "Can't go twice over same directed edge right?"
			if only_outer:
				# if both neighboring triangles are in shape, it's not a boundary edge
				edges.remove((j, i))
			return
		edges.add((i, j))

	tri = Delaunay(points)
	edges = set()
	# Loop over triangles:
	# ia, ib, ic = indices of corner points of the triangle
	for ia, ib, ic in tri.vertices:
		pa = points[ia]
		pb = points[ib]
		pc = points[ic]
		# Computing radius of triangle circumcircle
		# www.mathalino.com/reviewer/derivation-of-formulas/derivation-of-formula-for-radius-of-circumcircle
		a = np.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2)
		b = np.sqrt((pb[0] - pc[0]) ** 2 + (pb[1] - pc[1]) ** 2)
		c = np.sqrt((pc[0] - pa[0]) ** 2 + (pc[1] - pa[1]) ** 2)
		s = (a + b + c) / 2.0
		area = np.sqrt(s * (s - a) * (s - b) * (s - c))
		circum_r = a * b * c / (4.0 * area)
		if circum_r < alpha:
			add_edge(edges, ia, ib)
			add_edge(edges, ib, ic)
			add_edge(edges, ic, ia)
	return edges

def find_edges_with(i, edge_set):
	'''helper function for stitch_boundaries '''
	i_first = [j for (x,j) in edge_set if x==i]
	i_second = [j for (j,x) in edge_set if x==i]
	return i_first, i_second

def stitch_boundaries(edges):
	'''stitch edges together for creating geojson shape'''
	edge_set = edges.copy()
	boundary_lst = []
	while len(edge_set) > 0:
		boundary = []
		edge0 = edge_set.pop()
		boundary.append(edge0)
		last_edge = edge0
		while len(edge_set) > 0:
			i,j = last_edge
			j_first, j_second = find_edges_with(j, edge_set)
			if j_first:
				edge_set.remove((j, j_first[0]))
				edge_with_j = (j, j_first[0])
				boundary.append(edge_with_j)
				last_edge = edge_with_j
			elif j_second:
				edge_set.remove((j_second[0], j))
				edge_with_j = (j, j_second[0])  # flip edge rep
				boundary.append(edge_with_j)
				last_edge = edge_with_j

			if edge0[0] == last_edge[1]:
				break

		boundary_lst.append(boundary)
	return boundary_lst

def _tests():
	#setup a comms network, run calculations and display
	nxG = createGraph(omf.omfDir + '/static/publicFeeders/Olin Barre LatLon.omd')
	#Create a comms network
	setSmartMeters(nxG)
	setRFCollectors(nxG)
	setFiber(nxG)
	setRF(nxG)
	setSmartMeterBandwidth(nxG)
	setRFCollectorCapacity(nxG)
	setFiberCapacity(nxG, setSubstationBandwidth=True)
	setRFEdgeCapacity(nxG)
	calcBandwidth(nxG)
	print('cost of rf rfCollector equipment: ' + str(getrfCollectorsCost(nxG, 10000)))
	print('cost of rf smartMeter equipment: ' + str(getsmartMetersCost(nxG, 100)))
	print('cost of fiber: ' + str(getFiberCost(nxG, 4)))
	saveOmc(graphGeoJson(nxG), 'output')
	showOnMap(graphGeoJson(nxG))
	#load an omc, recalculate (as if refresh), redisplay
	newNxg = omcToNxg('output/commsGeoJson.omc', fromFile=True)
	clearFiber(newNxg)
	clearRFEdges(newNxg)
	setFiber(newNxg)
	setRF(newNxg)
	setFiberCapacity(newNxg)
	setRFEdgeCapacity(newNxg)
	calcBandwidth(newNxg)
	showOnMap(graphGeoJson(newNxg))
	#Display mesh network levels on a leaflet map
	nxG = createGraph(omf.omfDir + '/static/publicFeeders/Olin Barre LatLon.omd')
	setSmartMeters(nxG)
	try:
		meshMap(nxG)
	except Exception as e:
		print('Ignored exception: ' + str(e))
	
if __name__ == '__main__':
	_tests()
