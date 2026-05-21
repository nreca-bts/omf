"""
Perform geospatial operations for OMF circuits, including coordinate conversion, feeder
shapes, GeoJSON export, and geographic lookup helpers.
"""
import json, os, shutil, math, tempfile, random, webbrowser, re
import pathlib
from os.path import join as pJoin
from pyproj import Proj, transform, Transformer # Remove this import when deprecating other functions
import pyproj
import networkx as nx
import numpy as np
from scipy.spatial import ConvexHull
from sklearn.cluster import KMeans
from jinja2 import Template
from flask import Flask, send_file, render_template
from matplotlib import pyplot as plt

import omf
from omf.solvers import opendss
from omf import feeder
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Source: https://github.com/fitnr/stateplane/blob/master/stateplane/dicts.py
# These are NAD83 EPSG identifiers.
# If you need others like NAD27, try https://epsg.io
shortToEpsg = {"AK_1":26931,"AK_2":26932,"AK_3":26933,"AK_4":26934,"AK_5":26935,"AK_6":26936,"AK_7":26937,"AK_8":26938,"AK_9":26939,"AK_10,":26940,"AL_E":26929,"AL_W":26930,"AR_N":26951,"AR_S":26952,"AZ_C":26949,"AZ_E":26948,"AZ_W":26950,"CA_1":26941,"CA_2":26942,"CA_3":26943,"CA_4":26944,"CA_5":26945,"CA_6":26946,"CO_C":26954,"CO_N":26953,"CO_S":26955,"CT":26956,"DE":26957,"FL_E":26958,"FL_N":26960,"FL_W":26959,"GA_E":26966,"GA_W":26967,"HI_1":26961,"HI_2":26962,"HI_3":26963,"HI_4":26964,"HI_5":26965,"IA_N":26975,"IA_S":26976,"ID_C":26969,"ID_E":26968,"ID_W":26970,"IL_E":26971,"IL_W":26972,"IN_E":26973,"IN_W":26974,"KS_N":26977,"KS_S":26978,"KY_N":2205,"KY_S":26980,"LA_N":26981,"LA_S":26982,"MA_I":26987,"MA_M":26986,"MD":26985,"ME_E":26983,"ME_W":26984,"MI_C":26989,"MI_N":26988,"MI_S":26990,"MN_C":26992,"MN_N":26991,"MN_S":26993,"MO_C":26997,"MO_E":26996,"MO_W":26998,"MS_E":26994,"MS_W":26995,"MT":32100,"NC":32119,"ND_N":32120,"ND_S":32121,"NE":32104,"NH":32110,"NJ":32111,"NM_C":32113,"NM_E":32112,"NM_W":32114,"NV_C":32108,"NV_E":32107,"NV_W":32109,"NY_C":32116,"NY_E":32115,"NY_LI":32118,"NY_W":32117,"OH_N":32122,"OH_S":32123,"OK_N":32124,"OK_S":32125,"OR_N":32126,"OR_S":32127,"PA_N":32128,"PA_S":32129,"RI":32130,"SC":32133,"SD_N":32134,"SD_S":32135,"TN":32136,"TX_C":32139,"TX_N":32137,"TX_NC":32138,"TX_S":32141,"TX_SC":32140,"UT_C":32143,"UT_N":32142,"UT_S":32144,"VA_N":32146,"VA_S":32147,"VT":32145,"WA_N":32148,"WA_S":32149,"WI_C":32153,"WI_N":32152,"WI_S":32154,"WV_N":32150,"WV_S":32151,"WY_E":32155,"WY_EC":32156,"WY_W":32158,"WY_WC":32157}

# Reverse above dict to map in the other direction.
epsgToShort = {v: k for k, v in shortToEpsg.items()}

def statePlaneToLatLon(easting, northing, epsg = None):
	"""
	Perform state plane to lat lon processing for OMF helper-library workflows.
	"""
	if not epsg:
		# Center of the USA default
		epsg = 26978
	inProj = 'EPSG:' + str(epsg)
	outProj = 'EPSG:4326'
	transformer = Transformer.from_crs(inProj, outProj)
	lat, lon = transformer.transform(easting, northing)
	return (lat, lon)

def latLonToStatePlane(lat, lon, epsg = None):
	"""
	Perform lat lon to state plane processing for OMF helper-library workflows.
	"""
	if not epsg:
		# Center of the USA default
		epsg = 26978
	inProj = 'EPSG:4326'
	outProj = 'EPSG:' + str(epsg)
	transformer = Transformer.from_crs(inProj, outProj)
	easting, northing = transformer.transform(lon, lat)
	return (easting, northing)

def dd2dms(dd):
	'Decimal degrees to Degrees/Minutes/Seconds'
	d = int(dd)
	md = abs(dd - d) * 60
	m = int(md)
	sd = (md - m) * 60
	return (d, m, sd)

def dms2dd(degrees, minutes, seconds, direction):
	'Degree/minute/second to decimal degrees'
	dd = float(degrees) + float(minutes)/60 + float(seconds)/(60*60);
	if direction == 'E' or direction == 'N':
		dd *= -1
	return dd

def openInGoogleMaps(lat, lon):
	"Open a browser to the (lat, lon) in Google Maps"
	loc = 'https://www.google.com/maps/place/{}+{}/'.format(lat,lon)
	webbrowser.open_new(loc)

def hullOfOmd(pathToOmdFile, conversion=False):
	'''Convex hull of an omd in the form of a geojson dictionary with a single ploygon.'''
	if not conversion:
		with open(pathToOmdFile) as inFile:
			tree = json.load(inFile)['tree']
		nxG = feeder.treeToNxGraph(tree)
		nxG = graphValidator(pathToOmdFile, nxG)
	#use conversion for testing other feeders
	if conversion:
		nxG = convertOmd(pathToOmdFile)
	points = np.array([nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')])
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
			}
		}]
	}
	return geoJsonDict

def omdGeoJson(pathToOmdFile, conversion=False):
	'''Create a geojson standards compliant file (https://tools.ietf.org/html/rfc7946) from an omd.'''
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)['tree']
	nxG = feeder.treeToNxGraph(tree)
	# Use conversion for testing other feeders
	nxG = graphValidator(pathToOmdFile, nxG)
	if conversion:
		nxG = convertOmd(pathToOmdFile)
	geoJsonDict = {
		"type": "FeatureCollection",
		"features": []
	}
	# Get nodes and edges.
	node_positions = {nodewithPosition: nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')}
	# Add edges to geoJSON
	for edge in nx.edges(nxG):
		try:
			geoJsonDict['features'].append({
				"type": "Feature", 
				"geometry": {
					"type": "LineString",
					"coordinates": [[node_positions[edge[0]][1], node_positions[edge[0]][0]], [node_positions[edge[1]][1], node_positions[edge[1]][0]]]
				},
				"properties": nxG.edges[edge]
			})
		except KeyError:
			print("!!! KeyError exception for edge " + str(edge))
	# Add nodes 2nd so they show up on top of the z-order.
	for node in node_positions:
		geoJsonDict['features'].append({
			"type": "Feature", 
			"geometry":{
				"type": "Point",
				"coordinates": [node_positions[node][1], node_positions[node][0]]
			},
			"properties": nxG.nodes[node]
		})
	return geoJsonDict

def simplifiedOmdShape(pathToOmdFile, conversion=False):
	'''Use kmeans clustering to create simplified geojson object with convex hull and connected clusters from an omd.'''
	if not conversion:
		with open(pathToOmdFile) as inFile:
			tree = json.load(inFile)['tree']
		nxG = feeder.treeToNxGraph(tree)
		nxG = graphValidator(pathToOmdFile, nxG)
		simplifiedGeoDict = hullOfOmd(pathToOmdFile)
	#use conversion for testing other feeders
	if conversion:
		nxG = convertOmd(pathToOmdFile)
		simplifiedGeoDict = hullOfOmd(pathToOmdFile, conversion=True)
	
	#Kmeans clustering function
	numpyGraph = np.array([[node,
		float(nxG.nodes[node]['pos'][0]), float(nxG.nodes[node]['pos'][1])]
		for node in nx.get_node_attributes(nxG, 'pos')], dtype=object)
	Kmean = KMeans(n_clusters=20)
	Kmean.fit(numpyGraph[:,1:3])

	#Set up new graph with cluster centers as nodes to use in output
	centerNodes = Kmean.cluster_centers_
	clusterDict = {i: numpyGraph[np.where(Kmean.labels_ == i)] for i in range(Kmean.n_clusters)}
	simplifiedGraph = nx.Graph()
	for centerNode in clusterDict:
		currentClusterGroup = clusterDict[centerNode]
		simplifiedGraph.add_node(
			'centroid' + str(centerNode),
			type='centroid',
			pos=(centerNodes[centerNode][0], centerNodes[centerNode][1]),
			clusterSize=np.ma.size(currentClusterGroup, axis=0),
			lineCount=0
		)

	#Create edges between cluster centers
	for centerNode in clusterDict:
		currentClusterGroup = clusterDict[centerNode]
		nxG.add_node(
			'centroid' + str(centerNode),
			type='centroid',
			pos=(centerNodes[centerNode][0], centerNodes[centerNode][1])
		)
		intraClusterLines = 0
		for i in currentClusterGroup:
			currentNode = i[0]
			neighbors = nx.neighbors(nxG, currentNode)
			for neighbor in neighbors:
				#connect centroids
				if nxG.nodes[neighbor]['type'] == 'centroid':
					if ('centroid' + str(centerNode), neighbor) not in nx.edges(simplifiedGraph):
						simplifiedGraph.add_edge(
							'centroid' + str(centerNode),
							neighbor,
							type='centroidConnector',
							lineCount=1
						)
					else:
						simplifiedGraph['centroid' + str(centerNode)][neighbor]['lineCount'] += 1
				#connect centroid to nodes in other clusters, which is replaced in subsequent loops
				elif neighbor not in currentClusterGroup[:,0]:
					nxG.add_edge(
						'centroid'+str(centerNode),
						neighbor,
						type='centroidConnector'
					)
				else:
					simplifiedGraph.nodes['centroid' + str(centerNode)]['lineCount'] +=1
			if currentNode in simplifiedGraph:
				simplifiedGraph.remove_node(currentNode)

	#Add nodes and edges to dict with convex hull
	for node in simplifiedGraph.nodes:
		simplifiedGeoDict['features'].append({
			"type": "Feature", 
			"geometry":{
				"type": "Point",
				"coordinates": [simplifiedGraph.nodes[node]['pos'][1], simplifiedGraph.nodes[node]['pos'][0]]
			},
			"properties":{
				"name": node,
				"pointType": simplifiedGraph.nodes[node]['type'],
				"lineCount": simplifiedGraph.nodes[node]['lineCount']
			}
		})
	#Add edges to dict
	for edge in nx.edges(simplifiedGraph):
		simplifiedGeoDict['features'].append({
			"type": "Feature", 
			"geometry":{
				"type": "LineString",
				"coordinates": [[simplifiedGraph.nodes[edge[0]]['pos'][1], simplifiedGraph.nodes[edge[0]]['pos'][0]],
				[simplifiedGraph.nodes[edge[1]]['pos'][1], simplifiedGraph.nodes[edge[1]]['pos'][0]]]
			},
			"properties":{
				"lineCount": simplifiedGraph[edge[0]][edge[1]]['lineCount'],
				"edgeType": simplifiedGraph[edge[0]][edge[1]]['type']
			}
		})
	return simplifiedGeoDict
	'''
	if not os.path.exists(outputPath):
		os.makedirs(outputPath)
	shutil.copy('static/geoPolyLeaflet.html', outputPath)
	with open(pJoin(outputPath,'geoJsonFeatures.json'),"w") as outFile:
		json.dump(simplifiedGeoDict, outFile, indent=4)
	'''


def shortestPathOmd(pathToOmdFile, sourceObjectName, targetObjectName):
	'''Get the shortest path between two points on a feeder'''
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)['tree']
	nxG = feeder.treeToNxGraph(tree)
	nxG = graphValidator(pathToOmdFile, nxG)
	tracePath = nx.bidirectional_shortest_path(nxG, sourceObjectName, targetObjectName)
	return tracePath


def numTiles(z):
	''' Helper function to get number of tiles at a given zoom '''
	return(math.pow(2,z))


def sec(x):
	''' Helper fucntion to get secant '''
	return(1/math.cos(x))


def latlon2relativeXY(lat,lon):
	'''Helper function for latlon2xy'''
	x = (lon + 180) / 360
	y = (1 - math.log(math.tan(math.radians(lat)) + sec(math.radians(lat))) / math.pi) / 2
	return(x,y)


def latlon2xy(lat,lon,z):
	'''Helper function to convert lat/lon coordinate to x/y coordinates'''
	n = numTiles(z)
	x,y = latlon2relativeXY(lat,lon)
	return(n*x, n*y)


def tileXY(lat, lon, z):
	'''Helper function to get the tile that contains a lat/lon coordinate at a given zoom level'''
	x,y = latlon2xy(lat,lon,z)
	return(int(x),int(y))


def latEdges(y,z):
	'''Helper function in tileEdges for latitude'''
	n = numTiles(z)
	unit = 1 / n
	relY1 = y * unit
	relY2 = relY1 + unit
	lat1 = mercatorToLat(math.pi * (1 - 2 * relY1))
	lat2 = mercatorToLat(math.pi * (1 - 2 * relY2))
	return(lat1,lat2)


def lonEdges(x,z):
	'''Helper function in tileEdges for longitude'''
	n = numTiles(z)
	unit = 360 / n
	lon1 = -180 + x * unit
	lon2 = lon1 + unit
	return(lon1,lon2)


def tileEdges(x,y,z):
	'''Helper function to get lat/lon of a tile's edges at a given zoom'''
	lat1,lat2 = latEdges(y,z)
	lon1,lon2 = lonEdges(x,z)
	return((lat2, lon1, lat1, lon2)) # S,W,N,E


def mercatorToLat(mercatorY):
	'''Helper function converting mercator to lat'''
	return(math.degrees(math.atan(math.sinh(mercatorY))))


def rasterTilesFromOmd(pathToOmdFile, outputPath, conversion=False):
	'''Save raster tiles of omd to serve from zoom/x/y directory'''
	if not conversion:
		with open(pathToOmdFile) as inFile:
			tree = json.load(inFile)['tree']
		#networkx graph to work with
		nxG = feeder.treeToNxGraph(tree)
		nxG = graphValidator(pathToOmdFile, nxG)
	#use conversion for testing other feeders
	if conversion:
		nxG = convertOmd(pathToOmdFile)
	#Lat/lon min/max for caluclating tile coverage later
	latitude_min = min([nxG.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')])
	longitude_min = min([nxG.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')])
	latitude_max = max([nxG.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')])
	longitude_max = max([nxG.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')])
	#Set the plot settings
	plt.switch_backend('Agg')
	fig = plt.figure(frameon=False, figsize=[2.56,2.56])
	ax = fig.add_axes([0, 0, 1, 1])
	ax.axis('off')
	#Create the default tile
	if not os.path.exists(outputPath):
		os.makedirs(outputPath)
	plt.savefig(pJoin(outputPath,'default.png'),frameon=False, pad_inches=0, bbox='tight')
	#map latlon to projection
	epsg3857 = Proj(init='epsg:3857')
	wgs84 = Proj(init='EPSG:4326')
	node_positions = {nodewithPosition: nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')}
	for point in node_positions:
		node_positions[point] = transform(wgs84,epsg3857,node_positions[point][1], node_positions[point][0])
	#Go through each zoom level and create tiles for each area covering the feeder
	nx.draw_networkx(nxG, pos=node_positions, nodelist=list(node_positions.keys()), with_labels=False, node_size=2, edge_size=1)
	for zoomLevel in range(0,19):
		#Boundaries covering the omd locations for the current zoom level
		upperRightTile = tileXY(latitude_max, longitude_max, zoomLevel)
		lowerLeftTile = tileXY(latitude_min, longitude_min, zoomLevel)
		firstTileEdges = tileEdges(upperRightTile[0], upperRightTile[1], zoomLevel)
		lastTileEdges = tileEdges(lowerLeftTile[0], lowerLeftTile[1], zoomLevel)
		#Map omd for each x/y tile area
		for tileX in range(lowerLeftTile[0], upperRightTile[0]+1):
			for tileY in range(upperRightTile[1], lowerLeftTile[1]+1):
				currentTileEdges = tileEdges(tileX, tileY, zoomLevel)
				southWest = transform(wgs84,epsg3857,currentTileEdges[1], currentTileEdges[0])
				northEast = transform(wgs84,epsg3857,currentTileEdges[3], currentTileEdges[2])
				# S,W,N,E
				plt.ylim(top=northEast[1], bottom=southWest[1])
				plt.xlim(southWest[0], northEast[0])
				#create directory for tile
				savePath=pJoin(outputPath,str(zoomLevel),str(tileX))
				if not os.path.exists(savePath):
					os.makedirs(savePath)
				plt.savefig(pJoin(savePath,'%s.png' % str(tileY)),frameon=False, pad_inches=0, bbox='tight')

def getTileMapBounds(pathToTiles):
	'''Helper function to pass custom tile lat/lon bounds for setting initial leaflet view for serveTiles'''
	#Get the minimum and maximum x an y tiles from the dirs/files
	xTiles = [dI for dI in os.listdir(pJoin(pathToTiles,'18')) if os.path.isdir(pJoin(pathToTiles,'18',dI))]
	xTileMinimum, xTileMaximum = int(min(xTiles)), int(max(xTiles))
	yTileMinimumFile = min([f for f in os.listdir(pJoin(pathToTiles,'18',min(xTiles))) if os.path.isfile(pJoin(pathToTiles,'18',min(xTiles),f))])
	yTileMinimum = int(os.path.splitext(yTileMinimumFile)[0])
	yTileMaximumFile = max([f for f in os.listdir(pJoin(pathToTiles,'18',max(xTiles))) if os.path.isfile(pJoin(pathToTiles,'18',max(xTiles),f))])
	yTileMaximum = int(os.path.splitext(yTileMaximumFile)[0])

	#Convert tiles to min/max lat lons
	epsg3857 = Proj(init='epsg:3857')
	wgs84 = Proj(init='EPSG:4326')
	northEastTileEdges = tileEdges(xTileMaximum, yTileMinimum, 18)
	southWestTileEdges = tileEdges(xTileMinimum, yTileMaximum, 18)
	return [[northEastTileEdges[2], northEastTileEdges[3]], [southWestTileEdges[0], southWestTileEdges[1]]]

def serveTiles(pathToTiles):
	'''Flask server for raster tiles. Create the custom tileset with the rasterTilesFromOmd function'''
	app = Flask('tileServer')
	tileBounds = getTileMapBounds(pathToTiles)
	@app.route('/', methods=['GET'])
	def home():
		return render_template('tiledMap.html', tileBounds = tileBounds)
	@app.route('/omfTiles/<zoom>/<x>/<y>', methods=['GET'])
	def tiles(zoom, x, y):
		filename = pJoin(pathToTiles, zoom, x, y + '.png')
		default = pJoin(pathToTiles,'default.png')
		if os.path.isfile(filename):
			return send_file(filename)
		else:
			return send_file(default)
	app.run()


def convertOmd(pathToOmdFile):
	"""
	Convert omd data between solver or OMF representations.
	"""
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)['links']
	nxG = nx.Graph()
	for key in tree:
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
		try:
			nxG.nodes[sourceEdge]['type'] = key['source']['objectType']
		except KeyError:
			nxG.nodes[sourceEdge]['type'] = 'Undefined'
		try:
			nxG.nodes[targetEdge]['type'] = key['target']['objectType']
		except KeyError:
			nxG.nodes[targetEdge]['type'] = 'Undefined'
	for nodeToChange in nx.get_node_attributes(nxG, 'pos'):
		#nxG.node[nodeToChange]['pos'] = (latitudeCenter + nxG.node[nodeToChange]['pos'][1]/latitude_max, longitudeCenter 
		#								+ nxG.node[nodeToChange]['pos'][0]/longitude_max)
		#print(nxG.node[nodeToChange]['pos'][1], nxG.node[nodeToChange]['pos'][0])
		#print(statePlaneToLatLon(nxG.node[nodeToChange]['pos'][1], nxG.node[nodeToChange]['pos'][0]))
		nxG.nodes[nodeToChange]['pos'] = statePlaneToLatLon(nxG.nodes[nodeToChange]['pos'][1], nxG.nodes[nodeToChange]['pos'][0])
	return nxG


def graphValidator(pathToOmdFile, inGraph):
	'''If the nodes/edges positions are not in the tree, the sources and targets in the links key of the omd.json are used. '''
	try:
		node_positions = {nodewithPosition: inGraph.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')}
		# print(node_positions)
		for edge in nx.edges(inGraph):
			# validator = (node_positions[edge[0]] or nxG.nodes[edge[1]])
			validator = (node_positions[edge[0]] or inGraph.nodes[edge[1]])
	except KeyError:
		try:
			nxG = latLonValidation(convertOmd(pathToOmdFile))
		except ValueError:
			#No nodes have positions, so create random ones
			nxG = inGraph
			for nodeToChange in nxG.nodes:
				nxG.nodes[nodeToChange]['pos'] = (random.uniform(36.9900, 38.8700), random.uniform(-102.0500,-94.5900))
		return nxG
	nxG = latLonValidation(inGraph)
	return nxG

def fixMissingNodes(pathToOmdFile, pathToCoordsOmdFile, outfilePath):
	'''Function to check if missing nodes in one file are present in an adjacent file (one that represents the same distribution grid, but maybe contains more information), fills in those missing values and saves the complete tree to another omd file'''
	with open(pathToOmdFile) as inFile:
		fullFile = json.load(inFile)
		tree = fullFile['tree']
	inGraph = feeder.treeToNxGraph(tree)

	missingNodes = {}
	edgeStr = "Placeholder"
	node_positions = {nodewithPosition: inGraph.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')}
	# print(nx.edges(inGraph))
	for edge in nx.edges(inGraph):
		try:
			edgePairStr = str(edge)
			edgeStr = str(edge[0])
			validator = node_positions[edge[0]]
			edgeStr = str(edge[1])
			validator = inGraph.nodes[edge[1]]
			validator = (node_positions[edge[0]] or inGraph.nodes[edge[1]])
		except KeyError:
			print("!!!KeyError occurred!!! for " + edgeStr + " in " + edgePairStr)
			missingNodes[edgeStr] = "Missing"
	
	with open(pathToCoordsOmdFile) as inFile2:
		tree2 = json.load(inFile2)['tree']
	for objectKey in tree2:
		objectName = tree2[objectKey]['name']
		if objectName in missingNodes.keys():
			newObjectKey = str(len(tree)+1)
			tree[newObjectKey] = tree2[objectKey]
			missingNodes[objectName] = "Found in " + pathToCoordsOmdFile
	# print(missingNodes)
	fullFile['tree'] = tree
	with open(outfilePath, 'w') as outFile:
		json.dump(fullFile, outFile)

		
def latLonValidation(inGraph):
	'''Checks if an omd has invalid latlons, and if so, converts to stateplane coordinates or generates random values '''
	#try:
	latitude_min = min([inGraph.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	longitude_min = min([inGraph.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	latitude_max = max([inGraph.nodes[nodewithPosition]['pos'][1] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	longitude_max = max([inGraph.nodes[nodewithPosition]['pos'][0] for nodewithPosition in nx.get_node_attributes(inGraph, 'pos')])
	if latitude_min < -180 or latitude_max > 180 or longitude_min < -90 or longitude_max > 90:
		for nodeToChange in nx.get_node_attributes(inGraph, 'pos'):
			inGraph.nodes[nodeToChange]['pos'] = statePlaneToLatLon(inGraph.nodes[nodeToChange]['pos'][1], inGraph.nodes[nodeToChange]['pos'][0])
	return inGraph

def findCorruptNodes(pathToOmdFile, badLat, badLon, exceptNodes):
	'''Helper function that finds and returns a list of nodes within a feeder that have incorrect lat/lon values due to file conversion or corrput data. Does so by targeting nodes/buses that have the same auto-assigned coordinates (badLat, badLon) and adding them to the list to return (ignoring the nodes specified in exceptNodes list).'''
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)["tree"]
	corruptNodes = []
	for key in tree:
		obLat = "500.0"
		obLon = "500.0"
		try:
			obName = tree[key]['name']
			obLat = tree[key]['latitude']
			obLon = tree[key]['longitude']
		except KeyError:
			#Don't need to do anything - if it doesn't have a lat/lon, we shouldn't care
			x = 0
		if obLat == badLat and obLon == badLon and obName not in exceptNodes:
			corruptNodes.append(obName)
	return corruptNodes

def fixCorruptedLatLons(pathToOmdFile, listOfBadNodes, exceptNodes):
	'''This method takes in a path to the omd of the feeder that has corrupted lat/lon values, a list of nodes/buses whose coordinates are incorrect and need to be altered, as well as a list of nodes that should be ignored in the process (might have the same values for the auto-assigned coordinates, but they're the ones the auto-assignment pulled from in the first place) and returns a dictionary of the converterd bad coordinate nodes and their respective correct coordinates'''
	with open(pathToOmdFile) as inFile:
		tree = json.load(inFile)["tree"]
	inGraph = feeder.treeToNxGraph(tree)

	print("listOfBadNodes: " + str(listOfBadNodes))

	#dict - keys are the names of the nodes with corrupted lat/lons and their values are all the other nodes that are 
	allTouchNodes = {}
	for node in listOfBadNodes:
		touchNodes = []
		#Check for lines to other nodes
		for edge in nx.edges(inGraph):
			if str(edge[0]) == node:
				touchNodes.append(str(edge[1]))
			elif str(edge[1]) == node:
				touchNodes.append(str(edge[0]))
		allTouchNodes[node] = touchNodes
	print("allTouchNodes: " + str(allTouchNodes))

	fixedNodes = {}
	keepGoing = True
	count = 0
	while len(listOfBadNodes) > 0 and keepGoing:
		count = count+1
		fixedNodesStart = len(fixedNodes)
		print("Loop iteration #" + str(count))
		for badNode in allTouchNodes.keys():
			if badNode in listOfBadNodes:
				goodTouchNodes = {}
				for node in allTouchNodes[badNode]:
					if node not in listOfBadNodes and node not in exceptNodes:
						print("---------------Looking for coordinates for " + badNode + ":")
						if node in fixedNodes.keys():
							goodTouchNodes[node] = fixedNodes[node]
							print("          ----------------Found coordinates for " + node + " in fixedNodes: " + str(fixedNodes[node]))
						else:
							latLon = inGraph.nodes[node]['pos']
							goodTouchNodes[node] = latLon
							print("          ----------------Found coordinates for " + node + " in inGraph: " + str(latLon))
				if len(goodTouchNodes) >= 1:
					newLatLon = latLonByNeighbor(goodTouchNodes)
					fixedNodes[badNode] = newLatLon
					listOfBadNodes.remove(badNode)
					# allTouchNodes.pop(badNode, None)
		fixedNodesEnd = len(fixedNodes)
		if fixedNodesEnd > fixedNodesStart:
			keepGoing = True
		else:
			keepGoing = False
		print("-----fixedNodesStart: " + str(fixedNodesStart))
		print("-------fixedNodesEnd: " + str(fixedNodesEnd))
		print("-----------keepGoing: " + str(keepGoing))

	print("Fixed Nodes: " + str(fixedNodes))
	print("Unfixed Nodes: " + str(listOfBadNodes))
	return(fixedNodes)

def latLonByNeighbor(dictOfNeighbors):
	'''Helper function for fixCorruptedLatLons() that takes in a dict of nodes/buses that are connected to a specific node (keys) and their respective coordinates and returns the correct coordinates for that node'''
	numNeighbors = len(dictOfNeighbors)
	if numNeighbors == 1:
		neighbor = list(dictOfNeighbors.keys())[0]
		# to avoid putting buses/nodes on top of each other, place it 15 ft NE
		lat = dictOfNeighbors[neighbor][0] + .00004
		lon = dictOfNeighbors[neighbor][1] + .00005
		latLon = (lat, lon)
	elif numNeighbors > 1:
		lat = 0.0
		lon = 0.0
		for neighbor in dictOfNeighbors.keys():
			lat += dictOfNeighbors[neighbor][0]
			lon += dictOfNeighbors[neighbor][1]
		lat = lat/numNeighbors
		lon = lon/numNeighbors
		latLon = (lat, lon)
	return latLon

def createFixedLatLonOmd(pathToOmdFile, fixedLatLonDict, outfilePath, fixUndefinedObs):
	'''This method takes in a path to the omd of the feeder that has corrupted lat/lon values, a dictionary that contains the correct lat/lons (values) for the nodes/buses (keys) that were previously incorrect and creates a new omd file that contains the correct coordinates at the specified output file path (outfilePath)'''
	with open(pathToOmdFile) as inFile:
		fullFile = json.load(inFile)
		tree = fullFile['tree']
	badCoordObs = []
	exceptNodes = []
	for objectKey in tree:
		objectName = tree[objectKey]['name']
		if objectName in fixedLatLonDict.keys():
			origLat = tree[objectKey].get('latitude', "N/A")
			origLon = tree[objectKey].get('longitude', "N/A")
			tree[objectKey]['latitude'] = str(fixedLatLonDict[objectName][0])
			tree[objectKey]['longitude'] = str(fixedLatLonDict[objectName][1])
			print("Changed " + objectName + " coordinates from (" + origLat + ", " + origLon + ") to (" + tree[objectKey]['latitude'] + ", " + tree[objectKey]['longitude'] + ")" )
		else:
			origLat = tree[objectKey].get('latitude', "N/A")
			origLon = tree[objectKey].get('longitude', "N/A")
			if origLat != "N/A" and origLon != "N/A":
				badCoordObs.append(objectName)
	fullFile['tree'] = tree
	with open(outfilePath, 'w') as outFile:
		json.dump(fullFile, outFile)
	if fixUndefinedObs:
		fixedMissingNodes = fixCorruptedLatLons(outfilePath, badCoordObs, exceptNodes)
		createFixedLatLonOmd(outfilePath, fixedMissingNodes, outfilePath, False)

def openInBrowser(pathToFile):
	'''Helper function for mapOmd. Try popular web browsers first because png might open in native application. Othwerwise use default program as fallback'''
	webbrowser.open_new('file://' + os.path.abspath(pathToFile))

def showOnMap(geoJson):
	'''Open a browser to display a geoJSON object on a map.'''
	tempDir = tempfile.mkdtemp()
	shutil.copy(omf.omfDir + '/templates/geoJsonMap.html', tempDir)
	with open(pJoin(tempDir,'geoJsonFeatures.js'),"w") as outFile:
		outFile.write("var geojson =")
		json.dump(geoJson, outFile, indent=4)
	webbrowser.open('file://' + pJoin(tempDir,'geoJsonMap.html'))


def map_omd(omd_path, output_dir, open_browser=False, showAddNewObjectsButton=True, showAttachmentsButton=True, showAddGeojsonButton=True):
	'''
	Create an HTML page of the GeoJSON circuit editor without Flask
	'''
	# - Load feeder data
	with open(omd_path) as f:
		omd = json.load(f)
	omf.geo.insert_missing_nodes(omd)
	omf.geo.insert_wgs84_coordinates(omd)
	feature_collection = omf.geo.convert_omd_to_featurecollection(omd)
	featureCollection = json.dumps(feature_collection)
	components_collection = omf.geo.get_component_featurecollection()
	componentsCollection = json.dumps(components_collection)
	# - Load JavaScript
	main_js_filepath = (pathlib.Path(omf.omfDir).resolve(True) / 'static' / 'geoJsonMap' / 'v3' / 'main.js').resolve(True)
	all_js_filepaths = list((pathlib.Path(omf.omfDir).resolve(True) / 'static' / 'geoJsonMap').glob('**/*.js'))
	# - Filter out .test.js files
	all_js_filepaths = list(filter(lambda p: not str(p).endswith('.test.js'), all_js_filepaths))
	all_js_filepaths.remove(main_js_filepath)
	all_js_filepaths.append(main_js_filepath)
	all_js_file_content = []
	for filepath in all_js_filepaths:
		with pathlib.Path(filepath).open() as f:
			file_content = ''.join(list(filter(lambda line: not re.match(r'^\s*(?:import\s+|export\s+)', line), f.readlines())))
			file_content = f'<script>\n"use strict";\n{file_content}\n</script>\n'
			all_js_file_content.append(file_content)
	js = ''.join(all_js_file_content)
	# - Load CSS
	all_css_file_content = []
	for filepath in (pathlib.Path(omf.omfDir).resolve(True) / 'static' / 'geoJsonMap').glob('**/*.css'):
		with pathlib.Path(filepath).open() as f:
			file_content = ''.join(f.readlines())
			file_content = f'<style>\n{file_content}\n</style>\n'
			all_css_file_content.append(file_content)
	css = ''.join(all_css_file_content)
	# - Write template
	with (pathlib.Path(omf.omfDir).resolve(True) / 'templates' / 'geoJson_offline.html').open() as f:
		template = f.read()
	rendered = Template(template).render(
		featureCollection=featureCollection,
		componentsCollection=componentsCollection,
		thisOwner=None,
		thisModelName=None,
		thisFeederName=None,
		thisFeederNum=None,
		publicFeeders=None,
		userFeeders=None,
		currentUser=None,
		showFileMenu=json.dumps(False),
		isOnline=json.dumps(False),
		showAddNewObjectsButton=json.dumps(showAddNewObjectsButton),
		showAttachmentsButton=json.dumps(showAttachmentsButton),
		showAddGeojsonButton=json.dumps(showAddGeojsonButton),
		css=css,
		js=js)
	output_dir = pathlib.Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	# - Copy PNGs
	for filepath in (pathlib.Path(omf.omfDir).resolve(True) / 'static' / 'geoJsonMap').glob('**/*.png'):
		shutil.copy2(filepath, output_dir)
    # - Copy Gifs
	for filepath in (pathlib.Path(omf.omfDir).resolve(True) / 'static' / 'geoJsonMap').glob('**/*.gif'):
		shutil.copy2(filepath, output_dir)
	with open(output_dir / 'geoJson_offline.html', 'w') as f:
		f.write(rendered)
	if open_browser:
		openInBrowser(str(output_dir / 'geoJson_offline.html'))

def viz(path_to_file, output_path=None, open_browser=True):
	''' Directly visualize arbitrary .dss or .glm (or .omd). '''
	# Set up temp directory for the files.
	if output_path is None:
		out_dir = tempfile.mkdtemp()
	else:
		out_dir = os.path.abspath(output_path)
	omd_path = pJoin(out_dir,'circuit.omd')
	# write a test file to the out_dir
	with open(pJoin(out_dir,'test.txt'), 'w') as f:
		f.write('test')
	# Convert the feeder.
	if path_to_file.endswith('.omd'):
		omd_path = path_to_file
	elif path_to_file.endswith('.glm'):
		feeder.glmToOmd(path_to_file, pJoin(out_dir,'circuit.omd'))
	elif path_to_file.endswith('.dss'):
		opendss.dssConvert.dssToOmd(path_to_file, omd_path, RADIUS=0.0002, write_out=True)
	# Run visualization
	map_omd(omd_path, out_dir, open_browser=open_browser)

def convert_omd_to_featurecollection(omd):
	'''
	Convert an OMD dict into a FeatureCollection dict
		This is an alternative to using omf.feeder.treeToNxGraph(). This function does not handle missing/duplicate nodes or missing coordinates.
		Missing/duplicate nodes are handled by calling insert_missing_nodes() and missing/corrupt coordinates are handled by calling
		insert_coordinates()

	:param omd: an OMD
	:type omd: dict
	:return: a GeoJSON FeatureCollection
	:rtype: dict
	'''
	feature_collection = {'type': 'FeatureCollection', 'features': []}
	# - The meta_feature contains non-tree data like "attachments"
	meta_feature = {'type': 'Feature', 'geometry': {'coordinates': [None, None], 'type': 'Point'}, 'properties': {'treeKey': 'omd'}}
	feature_collection['features'].append(meta_feature)
	# - Add non-tree data
	for k, v in omd.items():
		if k != 'tree':
			meta_feature['properties'][k] = v
	# - Add tree data
	name_to_treekey = NameToTreeKeyMap(omd)
	for k, v in omd['tree'].items():
		# - Existing code base is used to dealing with strings of ints so I'm doing that
		feature = {'type': 'Feature', 'properties': {'treeKey': str(k)}}
		# - The "geo_py_validation_status" property should be kept in the "treeProps" namespace so that the user can delete the property in the
		#   front-end if they want. It's NOT a meta-property
		feature['properties']['treeProps'] = v
		if 'from' in v and 'to' in v:
			src_key = name_to_treekey.get_key(v['from'], v)
			src_lon = float(omd['tree'][src_key]['longitude'])
			src_lat = float(omd['tree'][src_key]['latitude'])
			dst_key = name_to_treekey.get_key(v['to'], v)
			dst_lon = float(omd['tree'][dst_key]['longitude'])
			dst_lat = float(omd['tree'][dst_key]['latitude'])
			feature['geometry'] = {'coordinates': [[src_lon, src_lat], [dst_lon, dst_lat]], 'type': 'LineString'}
		else:
			if _is_configuration_or_special_node(v):
				coordinates = [None, None]
			else:
				coordinates = [float(v['longitude']), float(v['latitude'])]
			feature['geometry'] = {'coordinates': coordinates, 'type': 'Point'}
		feature_collection['features'].append(feature)
	# - I iterate again at the end to remove "latitude" and "longitude" because a line may need to get coordinates from a node before I remove the
	#   node's coordinates
	for k, v in omd['tree'].items():
		for prop in ['latitude', 'longitude']:
			if prop in v:
				del v[prop]
	return feature_collection


def convert_featurecollection_to_omd(feature_collection):
	'''
	Convert a GeoJSON FeatureCollection dict into an OMD dict

	:param feature_collection: a GeoJSON feature collection
	:type feature_collection: dict
	:return: an OMD
	:rtype: dict
	'''
	omd = {'tree': {}}
	for f in feature_collection['features']:
		# - Add non-tree keys
		if f['properties']['treeKey'] == 'omd':
			for k, v in f['properties'].items():
				if k != 'treeKey':
					omd[k] = v
		# - Remove parent-child lines entirely in case they still exist
		elif f['properties']['treeProps'].get('type') == 'parentChild':
			continue
		else:
			# - Ignore 'latitude' and 'longitude' properties present in the <Feature>['properties]['treeProps'] dict
			for p in ['latitude', 'longitude']:
				if p in f['properties']['treeProps']:
					del f['properties']['treeProps'][p]
			# - Add coordinates if we should
			if f['geometry']['type'] == 'Point':
				if not _is_configuration_or_special_node(f['properties']['treeProps']):
					f['properties']['treeProps']['latitude'] = float(f['geometry']['coordinates'][1])
					f['properties']['treeProps']['longitude'] = float(f['geometry']['coordinates'][0])
			omd['tree'][str(f['properties']['treeKey'])] = f['properties']['treeProps']
	return omd


class NameToTreeKeyMap:
	'''
	This class encapsulates a dictionary that maps the "name" property of objects and lines to tree keys. A simple Python dictionary is not sufficient
	because multiple tree objects can share the same name. As a result, the correct tree key that should be returned for a given name depends on which
	object is requesting the tree key
		E.g. if a linecode and bus share a name, and a child node uses that name as its parent reference, then the tree key of the bus should be
		returned, but that's only because a child node was requesting a tree key.
		In the case of unresolvable name collisions (e.g. two buses share a name and a child node uses that name as its parent reference, and we don't
		know which bus to return), we raise an exception
	'''

	def __init__(self, omd):
		'''
		:param omd: an OMD
		:type omd: dict
		:rtype: None
		'''
		self._omd = omd
		self._map = {}
		for k, v in omd['tree'].items():
			name = v.get('name')
			if name is not None:
				if name not in self._map:
					self._map[name] = [k]
				else:
					self._map[name].append(k)

	def get_key(self, name, treeProps):
		'''
		Return a key for the given name, or None if a key cannot be found. Raise an exception if the key can't unambiguously selected from multiple
		possible keys

		:param name: the name of a tree object
		:type name: str
		:param treeProps: a tree object (e.g. a child object or line object) that is requesting the tree object with the given name Nodes and lines
			can be parents.
		:type treeProps: dict
		:return: the key of the object with the provided name
		:rtype: str
		'''
		keys = self._map.get(name)
		if keys is None:
			return None
		elif len(keys) == 1:
			return keys[0]
		# - For recorders, return the first line with the given name. Is this right?
		objects_with_line_parents = ['recorder']
		if treeProps['object'] in objects_with_line_parents:
			line_keys = list(filter(lambda k: 'from' in self._omd['tree'][k] and 'to' in  self._omd['tree'][k], keys))
			if len(line_keys) == 1:
				return line_keys[0]
			else:
				raise ValueError(f'The NameToTreeKeyMap could not unambiguously find a line for the object named "{treeProps["name"]}"')
		else:
			node_keys = list(filter(lambda k: 'from' not in self._omd['tree'][k] and 'to' not in self._omd['tree'][k] and not _is_configuration_or_special_node(self._omd['tree'][k]), keys))
			if len(node_keys) == 1:
				return node_keys[0]
			else:
				#raise ValueError(f'The NameToTreeKeyMap could not unambiguously find a node for the object named "{treeProps["name"]}"')
				# - HACK (David): How to deal with circuit vs. bus object with same name, or duplicate bus objects with same name?
				#   - Always assume that the line or child wants the "bus" object, not the "circuit" object
				#   - If two buses have identical names, just choose the first bus arbitrarily
				bus_keys = list(filter(lambda k: self._omd['tree'][k].get('object') == 'bus', node_keys))
				if len(bus_keys) > 0:
					return bus_keys[0]
				else:
					# - In really weird situations, such as a case of multiple circuit objects with the same name, just return the first object
					return node_keys[0]


def _is_configuration_or_special_node(tree_properties):
	'''
	:param tree_properties: a dict of an OMD object's properties
	:type tree_properties: dict
	:return: whether the tree_properties describe a node that isn't supposed to be visually displayed in the front-end map (i.e. a "configuration
		object" or "special object"). A configuration/special node is converted into a feature that has None latitude and longitude values
	:rtype: bool
	'''
	# - The "circuit" object needs to be vsource object, so it's NOT a configuration node
	#   - The exception with "trilby" is therefore correct. I need to ask David how to resolve that problem
	# - The "energymeter" object is NOT a configuration node
	#   - iowa240c2_working_coords.clean.tie_bus2058_bus3155.omd assigns a parent to it
	# - The "regcontrol" object is NOT a configuration node
	#   - iowa240c1.clean.dss.omd assigns latitude and longitude values to it. So does pvrea_trilby.omd
	#   - 2024-07-05: it is now a configuration object anyway
	# - The "player" object is NOT a configuration node
	#   - ABEC Frank Calibrated With Voltage gives one such object a "parent" attribute
	CONFIGURATION_OBJECTS = (
		'auction',
		'!CMD',
		#'circuit',
		'climate',
		'cndata',
		'csv_reader',
		'currdump',
		#'energymeter',
		'group_recorder',
		'growthshape',
		'line_configuration',
		'line_spacing',
		'linecode',
		'loadshape',
		'overhead_line_conductor',
		#'player',
		'regcontrol',
		'regulator_configuration',
		'schedule',
		'spectrum',
		'swtcontrol',
		'tcc_curve',
		'triplex_line_conductor',
		'transformer_configuration',
		'triplex_line_configuration',
		'underground_line_conductor',
		'volt_var_control',
		'voltdump',
		'wiredata')
	# - These OMD objects lack the "object" property entirely
	SPECIAL_OBJECTS = ('clock', 'omftype', 'module', 'class')
	return ((tree_properties.get('object') is None and len(set(tree_properties.keys()) & set(SPECIAL_OBJECTS)) > 0) or
		re.match(r'($|:)|'.join(CONFIGURATION_OBJECTS) + r'($|:)', tree_properties['object']))


def insert_missing_nodes(omd):
	'''
	Iterate through an OMD's tree and add any missing "parent" nodes, "from" nodes, or "to" nodes
		TODO: add missing configuration nodes???

	:param omd: an OMD
	:type omd: dict
	:rtype: None
	'''
	name_to_treekey = NameToTreeKeyMap(omd)
	max_tree_key = max([int(k) for k in omd['tree'].keys()], default=0)
	new_tree = {}
	for k, v in omd['tree'].items():
		# - Deal with lines that have missing/identical nodes
		if 'from' in v and 'to' in v:
			if v['from'] == v['to']:
				v['geo_py_validation_status'] = 'looped'
			src_key = name_to_treekey.get_key(v['from'], v)
			if src_key is None: 
				max_tree_key += 1
				# - I grepped through all the files and no OMD tree object used "geo_py_validation_status" as a key
				new_tree[max_tree_key] = {'name': v['from'], 'object': 'bus', 'geo_py_validation_status': 'missing'}
				name_to_treekey._map[v['from']] = [max_tree_key]
			dst_key = name_to_treekey.get_key(v['to'], v)
			if dst_key is None:
				max_tree_key += 1
				new_tree[max_tree_key] = {'name': v['to'], 'object': 'bus', 'geo_py_validation_status': 'missing'}
				name_to_treekey._map[v['to']] = [max_tree_key]
		else:
			# - Deal with child nodes that have missing parents
			if 'parent' in v:
				parent_key = name_to_treekey.get_key(v['parent'], v)
				if parent_key is None:
					max_tree_key += 1
					new_tree[max_tree_key] = {'name': v['parent'], 'object': 'bus', 'geo_py_validation_status': 'missing'}
					name_to_treekey._map[v['parent']] = [max_tree_key]
					#print(f'omf.geo.insert_missing_nodes() created a placeholder bus node for the missing node named {v["parent"]}')
	for k in new_tree.keys():
		omd['tree'][str(k)] = new_tree[k]


def insert_wgs84_coordinates(omd, center=(38.92720, -94.95520), spcs_epsg=None, force_layout=False, scale=.01):
	'''
	- Iterate over an OMD's tree in-place and insert WGS 84 "latitude" and "longitude" property values in decimal degrees.
		- If a node is missing latitude or longitude properties, or has non-numeric latitude or longitude properties, or has non-state-plane
		  out-of-bounds coordinates, create new WGS 84 coordinates with a layout algorithm.
		- If a node has state plane coordinates, convert them into WGS 84 coordinates.
			- If an EPSG code is given, perform a proper transformation of state plane coordinates into WGS 84 coordinates.
			- If an EPSG code is not given, convert every state plane coordinate into a WGS 84 coordiante, subtract the minimum latitude from all
			  latitudes and subtract the minimum longitude from all longitudes to convert the WGS 84 coordinates into offset values, then add the
			  "center" latitude to every latitude and the "center" longitude to every longitude to shift the coordinates to the desired location.
	- This function assumes there are no missing nodes. Run the OMD through insert_missing_nodes() first.
	
	:param omd: an OMD
	:type omd: dict
	:param center: a WGS 84 coordinate pair which will serve as the bottom left corner of the circuit coordinates. If force_layout=True, all nodes
		will be centered around these coordinates according to some layout algorithm. If no nodes have coordinates, then all nodes will be centered
		around these coordinates with a layout algorithm regardless of force_layout. If some, but not all, nodes have coordinates and
		force_layout=False, center is ignored and the existing coordinates will be used to determine coordinates for nodes that lack coordinates.
	:type center: tuple
	:param spcs_espg: a state plane coordinate system European Petroleum Survey Group code that should be used to transform the given state plane
		coordinates. E.g. EPSG:26978 is the European Petroleum Survey Group code for the "Kansas South" state plane with the "NAD 83" datum, which
		also has a USA FIPS identifier of 1502. http://gsp.humboldt.edu/olm/Lessons/GIS/03%20Projections/Images2/StatePlane.png. If this argument is
		provided, then the coordinates will be converted, even if they weren't actually state plane coordinates.
	:type spcs_epg: str
	:param force_layout: whether to insert new coordinates using a layout algorithm regardless of existing coordinates. 
	:type force_layout: bool
	:rtype: None
	'''
	# - Iterate the first time to find the min/max latitude/longitude to detect state plane coordinates
	min_lat, max_lat, min_lon, max_lon = _get_min_max_lat_lon(omd)
	if max_lat is not None and max_lon is not None:
		# - If we have huge coordinate values, or the user says we have state plane coordinates, convert existing state plane coordinates into WGS 84
		#   coordinates
		if spcs_epsg is not None or max_lat > 72 or max_lon > -66:
			# - The user knows their EPSG state plane code, so do a proper conversion
			if spcs_epsg is not None:
				in_proj = Proj(init=spcs_epsg, preserve_units=True)
			# - The user did not know their EPSG state plane code, so preserve relative distances between nodes
			else:
				# - Convert from "Kansas South NAD 83 State Plane Coordinate System" to the World Geodetic System 1984. It doesn't really matter which
				#   state plane we use. They should preserve distances between nodes roughly equally
				#in_proj = Proj(init='EPSG:26978') # - This "Kansas South NAD 83 State Plane Coordinate System" projection uses meters. Nodes will be spaced further apart
				in_proj = Proj(init='EPSG:3420', preserve_units=True) # - This "Kansas South NAD 83 State Plane Coordinate System" projection uses the US survey foot. Nodes will be closer together
			out_proj = Proj(init='EPSG:4326')
			transformer = pyproj.Transformer.from_proj(in_proj, out_proj, always_xy=True)
			x_subtrahend, y_subtrahend = transformer.transform(min_lon, min_lat)
			for d in omd['tree'].values():
				try:
					easting = float(d['longitude'])
					northing = float(d['latitude'])
					x, y = transformer.transform(easting, northing)
					if spcs_epsg is None:
						x = (x - x_subtrahend) + center[1]
						y = (y - y_subtrahend) + center[0]
					d['longitude'] = x
					d['latitude'] = y
				except (KeyError, ValueError) as e:
					pass
	name_to_treekey = NameToTreeKeyMap(omd)
	graph = nx.Graph()
	# - Iterate a second time to build the graph for the layout algorithm and determine how a node will get new coordinates if it needs them
	for k, v in omd['tree'].items():
		if 'from' in v and 'to' in v:
			try:
				weight = float(v['length'])
			except (KeyError, ValueError) as e:
				# - Ignore non-numeric values like "1 mile" for the purposes of graph layout
				weight = 1
			graph.add_edge(name_to_treekey.get_key(v['from'], v), name_to_treekey.get_key(v['to'], v), weight=weight)
		else:
			if not _is_configuration_or_special_node(v):
				if 'parent' in v:
					parent_key = name_to_treekey.get_key(v['parent'], v)
					parent = omd['tree'][parent_key]
					graph.add_edge(parent_key, k, weight=1)
					graph.add_node(k, coordinate_source='parent')
				else:
					graph.add_node(k)
	# - Run the layout algorithm to generate coordinates
	try:
		scale = float(scale)
	except:
		scale = .01
	if force_layout:
		# This is really slow. The user must specify force_layout to do this.
		pos = nx.kamada_kawai_layout(graph, scale=scale)
	else:
		pos = nx.circular_layout(graph, scale=scale) # Fast, but ugly!
	# - Is there a fast tree layout somewhere???? They only work with directed graphs, so we could build a directed graph
	#pos = nx.spectral_layout(graph) # Too slow
	#pos = nx.nx_pydot.pydot_layout(graph, prog='neato', root=None) # Requires pydot. Fast, but default looks horrible
	#pos = nx.nx_pydot.graphviz_layout(graph, prog='neato', root=None) # Requires pydot. Fast, but default looks horrible
	#pos = nx.shell_layout(graph, scale=0.1) # Could this work?
	#pos = nx.spring_layout(graph, scale=0.1)
	#pos = nx.planar_layout(graph, scale=0.1)

	# - Iterate a third time to find the valid min/max lat/lon to determine if we need to use the "center" parameter or not
	min_lat, max_lat, min_lon, max_lon = _get_min_max_lat_lon(omd, min_lat=18, max_lat=72, min_lon=-172, max_lon=-66)
	avg_lat = center[0]
	if min_lat is not None and max_lat is not None:
		avg_lat = (max_lat + min_lat) / 2
	avg_lon = center[1]
	if min_lon is not None and max_lon is not None:
		avg_lon = (max_lon + min_lon) / 2
	# - Iterate a fourth time to give coordinates to all nodes that need them
	for k in pos:
		obj = omd['tree'][k]
		# - Mark nodes that are disconnected from the rest of the circuit as "isolated". This can be commented out because I don't which
		#   non-configuration nodes are allowed to be isolated vs. which nodes should never be isolated
		if graph.degree[k] == 0 and not _is_configuration_or_special_node(obj):
			if obj.get('geo_py_validation_status') is None:
				obj['geo_py_validation_status'] = 'isolated'
			else:
				obj['geo_py_validation_status'] += ' & isolated'
		if 'from' not in obj and 'to' not in obj and not _is_configuration_or_special_node(obj):
			if force_layout:
				omd['tree'][k]['latitude'] = float(pos[k][0]) + center[0]
				omd['tree'][k]['longitude'] = float(pos[k][1]) + center[1]
			else:
				if graph.nodes[k].get('coordinate_source') == 'parent':
					parent_key = name_to_treekey.get_key(obj['parent'], obj)
					parent = omd['tree'][parent_key]
				try:
					lat = float(obj['latitude'])
					if not (18 <= lat <= 72):
						raise ValueError
				except (KeyError, ValueError) as e:
					if graph.nodes[k].get('coordinate_source') == 'parent':
						try:
							parent_lat = float(parent['latitude'])
							if not (18 <= parent_lat <= 72):
								raise ValueError
						except (KeyError, ValueError) as e:
							parent_lat = float(pos[parent_key][0]) + avg_lat
							# - Lines that are parents can have coordinates for the sake of their children, but they can't have coordinates themselves
							if 'from' not in obj and 'to' not in obj:
								parent['latitude'] = parent_lat
						obj['latitude'] = parent_lat + round(random.uniform(-.003, .003), 4)
					else:
						obj['latitude'] = float(pos[k][0]) + avg_lat
				try:
					lon = float(obj['longitude'])
					if not (-172 <= lon <= -66):
						raise ValueError
				except (KeyError, ValueError) as e:
					if graph.nodes[k].get('coordinate_source') == 'parent':
						try:
							parent_lon = float(parent['longitude'])
							if not (-172 <= parent_lon <= -66):
								raise ValueError
						except (KeyError, ValueError) as e:
							parent_lon = float(pos[parent_key][1]) + avg_lon
							# - Lines that are parents can have coordinates for the sake of their children, but they can't have coordinates themselves
							if 'from' not in obj and 'to' not in obj:
								parent['longitude'] = parent_lon
						obj['longitude'] = parent_lon + round(random.uniform(-.003, .003), 4)
					else:
						obj['longitude'] = float(pos[k][1]) + avg_lon


def _get_min_max_lat_lon(omd, min_lat=None, max_lat=None, min_lon=None, max_lon=None):
	'''
	- Return the valid minimum latitude, maximum latitude, minimum longitude, and maximum longitude found across all nodes in the omd
	- This helper function is needed twice in insert_coordinates(). It's used the first time to get the actual min/max lat/lons for detecting state
	  plane coordinates. It's used the second time to get valid min/max lat/lons for assigning coordinates to nodes without valid lat/lons
		- Lats outside the range of 18 <= <lat> <= 72 are invalid. Lons outside the range of -172 <= <lon> <= -66 are invalid. Those min/maxes form a
		  bounding box around most of the USA

	:param omd: an OMD
	:type omd: dict
	:param min_lat: the minimum (inclusive) bound of valid latitude values. Latitude values that are less than this are ignored
	:type min_lat: float
	:param max_lat: the maximum (inclusive) bound of valid latitude values. Latitude values that are greater than this are ignored
	:type max_lat: float
	:param min_lon: the minimum (inclusive) bound of valid longitude values. Longitude values that are less than this are ignored
	:type: min_lon: float
	:param max_lon: the maximum (inclusive) bound of valid longitude values. Longitude values that are greater than this are ignored
	:type max_lon: float
	:return: a tuple of (<min lat>, <max lat>, <min lon>, <max lon>)
	:rtype: tuple
	'''
	lats = []
	lons = []
	for d in omd['tree'].values():
		try:
			lat = float(d['latitude'])
			if min_lat is not None:
				if lat >= min_lat:
					if max_lat is not None:
						if lat <= max_lat:
							lats.append(lat)
					else:
						lats.append(lat)
			else:
				if max_lat is not None:
					if lat <= max_lat:
						lats.append(lat)
				else:
					lats.append(lat)
		except (KeyError, ValueError) as e:
			pass
		try:
			lon = float(d['longitude'])
			if min_lon is not None:
				if lon >= min_lon:
					if max_lon is not None:
						if lon <= max_lon:
							lons.append(lon)
					else:
						lons.append(lon)
			else:
				if max_lon is not None:
					if lon <= max_lon:
						lons.append(lon)
				else:
					lons.append(lon)
		except (KeyError, ValueError) as e:
			pass
	min_lat = min(lats, default=None)
	max_lat = max(lats, default=None)
	min_lon = min(lons, default=None)
	max_lon = max(lons, default=None)
	return (min_lat, max_lat, min_lon, max_lon)


def transform_wgs84_coordinates(omd, center=None, vertical_translation=None, horizontal_translation=None, rotation=None):
	'''
	- Perform a transformation on the coordinates of an OMD. This function assumes the omd has entirely valid WGS 84 coordinates (floats or strings)
	  in decimal degrees that are bounded within the USA (contiguous and non-contiguous). Run the omd through insert_wgs84_coordinates() first.
	  Centering is done first, followed by vertical translation, followed by horizontal translation, followed by rotation.

	:param omd: an OMD
	:type omd: dict
	:param center: a new center for all of the coordinates in (<lat>, <lon>) decimal degrees. If it is provided, calculate the existing center of the
		coordinates, calculate the offset from the existing center to the new specified center, then shift all coordinates by that offset amount
	:type center: tuple
	:param vertical_translation: a distance, in meters, that the user wants to move the coordinates upwards by. If it is provided, shift all
		coordinates straight upwards by that many meters
	:type vertical_translation: float
	:param horizontal_translation: a distance, in meters, that the user wants to move the coordinates rightwards. If it is provided, shift all
		coordinates straight rightwards by that many meters
	:type horizontal_translation: an amount, in degrees (not radians!), to rotate the coordinates counterclockwise around their midpoint by
	:param rotation: float
	'''
	center, vertical_translation, horizontal_translation, rotation = _validate_transform_wgs84_coordinates_arguments(center, vertical_translation, horizontal_translation, rotation)
	if center is not None:
		# - If a center was provided, the user wants to translate the entire graph to a new position. First step is to determine the relative center of
		#   the graph
		min_lat, max_lat, min_lon, max_lon = _get_min_max_lat_lon(omd, min_lat=18, max_lat=72, min_lon=-172, max_lon=-66)
		avg_coords = ((max_lat + min_lat) / 2, (max_lon + min_lon) / 2)
		# - Next step is to compute the vertical distance between the existing center and the new center and the horizontal distance between the
		#   existing center and the new center
		coords_diff = (center[0] - avg_coords[0], center[1] - avg_coords[1])
	# - The distance that 1 degree of latitude represents is the same everywhere on earth. Assume the earth has a radius of 6,378 km
	there_are_this_many_meters_in_one_degree_of_latitude = (6378000 * (math.pi / 2)) / 90
	for v in omd['tree'].values():
		if v.get('latitude') is not None:
			if center is not None:
				v['latitude'] = float(v['latitude']) + coords_diff[0]
			if vertical_translation is not None:
				v['latitude'] = float(v['latitude']) + (1 / there_are_this_many_meters_in_one_degree_of_latitude) * vertical_translation
		if v.get('longitude') is not None:
			if center is not None:
				v['longitude'] = float(v['longitude']) + coords_diff[1]
			if horizontal_translation is not None:
				# - The distance that 1 degree of longitude represents depends on the given latitude. Assume the earth has a radius of 6,378 km
				#   - Distance of 1 degree of longitude = cos(<given latitude>) * distance of 1 degree of latitude
				#   - Distance of 1 degree of longitude = cos(<given latitude>) * ((6,378,000 m * (pi / 2)) / 90)
				v['longitude'] = float(v['longitude']) + (1 / (math.cos(math.radians(float(v['latitude']))) * there_are_this_many_meters_in_one_degree_of_latitude)) * horizontal_translation
	if rotation is not None:
		# - Need to get the bounds again just in case anything was shifted
		min_lat, max_lat, min_lon, max_lon = _get_min_max_lat_lon(omd, min_lat=18, max_lat=72, min_lon=-172, max_lon=-66)
		mid_lat = (max_lat + min_lat) / 2
		mid_lon = (max_lon + min_lon) / 2
		# - Convert from degrees to radians
		rotation = math.radians(float(rotation))
		# - If you rotate point (px, py) around point (ox, oy) by angle theta you'll get:
		#   - p'y = sin(theta) * (px-ox) + cos(theta) * (py-oy) + oy
		#   - p'x = cos(theta) * (px-ox) - sin(theta) * (py-oy) + ox
		for v in omd['tree'].values():
			if v.get('latitude') is not None and v.get('longitude') is not None:
				y = float(v['latitude'])
				x = float(v['longitude'])
				v['latitude'] = (math.sin(rotation) * (x - mid_lon)) + (math.cos(rotation) * (y - mid_lat)) + mid_lat
				v['longitude'] = (math.cos(rotation) * (x - mid_lon)) - (math.sin(rotation) * (y - mid_lat)) + mid_lon


def _validate_transform_wgs84_coordinates_arguments(center, vertical_translation, horizontal_translation, rotation):
	'''
	- Temporary hack for dealing with annoying input from the front-end
	'''
	if isinstance(center, str):
		try:
			center = center.replace('(', '')
			center = center.replace(')', '')
			center = center.replace(',', ' ')
			center = center.split()
			assert len(center) == 2
		except:
			center = None
	try:
		center[0] = float(center[0])
		center[1] = float(center[1])
	except:
		center = None
	try:
		vertical_translation = float(vertical_translation)
	except:
		vertical_translation = None
	try:
		horizontal_translation = float(horizontal_translation)
	except:
		horizontal_translation = None
	try:
		rotation = float(rotation)
	except:
		rotation = None
	return (center, vertical_translation, horizontal_translation, rotation)

def get_component_featurecollection():
	"""
	Return the component featurecollection needed by this workflow.
	"""
	feature_collection = {'type': 'FeatureCollection', 'features': []}
	# - This isn't an actual tree key, but it's needed to insert components into a FeatureMap in the front-end
	tree_key = 1
	for p in (pathlib.Path(omf.omfDir).resolve(True) / 'data').glob('Component*/*.json'):
		# - Does having non-numeric tree keys for components break anything?
		feature = {'type': 'Feature', 'properties': {'treeKey': 'component:' + str(tree_key)}}
		if p.parent.name == 'ComponentDss':
			feature['properties']['componentType'] = 'opendss'
		else:
			feature['properties']['componentType'] = 'gridlabd'
		with p.open() as f:
			tree_props = json.load(f)
			# - Use the filename of the component if necessary to identify it
			if 'name' not in tree_props:
				tree_props['name'] = p.stem
		feature['properties']['treeProps'] = tree_props
		if 'from' in tree_props or 'to' in tree_props:
			if 'from' in tree_props and 'to' in tree_props:
				feature['geometry'] = {'coordinates': [[0, 0], [0, 0]], 'type': 'LineString'}
			else:
				# - This exception should never be raised. If it is, there's a typo in a component file
				raise Exception(f'The component {tree_props["name"]} doesn\'t have both the "from" and "to" keys, but has one of them')
		else:
			if _is_configuration_or_special_node(tree_props):
				coordinates = [None, None]
			else:
				coordinates = [0, 0]
			feature['geometry'] = {'coordinates': coordinates, 'type': 'Point'}
		for prop in ['latitude', 'longitude']:
			if prop in tree_props:
				del tree_props[prop]
		feature_collection['features'].append(feature)
		tree_key += 1
	return feature_collection


def _testFixedLatLonOmd():
	"""
	Internal helper for geo test fixed lat lon omd processing.
	"""
	import csv
	omdFilePath = pJoin(__neoMetaModel__._omfDir, 'static', 'testFiles', 'iowa240_dwp_22.dss.omd')
	coordFilePath = pJoin(__neoMetaModel__._omfDir, 'static', 'testFiles', 'BuscoordsLatLon.csv') #coordinate file is csv with each row containing busName, yValue(longitude), xValue(latitude)
	with open(coordFilePath, 'r') as coordFile:
		coordReader = csv.reader(coordFile)
		coordDict = {row[0]:(row[2],row[1]) for row in coordReader}
	outFilePath = pJoin(__neoMetaModel__._omfDir, 'static', 'testFiles', 'iowa240_dwp_22.goodCoords.dss.omd')
	createFixedLatLonOmd(omdFilePath, coordDict, outFilePath, True)


def _testLatLonfix():
	'''Test for fixing a feeder with corrupted auto-assign lat/lon values using findCorruptNodes(), fixCorruptedLatLons(), and createFixedLatLonOmd()'''
	exceptNodes = ['sourcebus', '_hvmv_sub_lsb', 'hvmv_sub_48332', 'hvmv_sub_hsb', 'regxfmr_hvmv_sub_lsb']
	# omdPath = pJoin(__neoMetaModel__._omfDir, 'scratch', 'RONM', 'nreca1824.dss.omd')
	omdPath = pJoin(__neoMetaModel__._omfDir, 'scratch', 'RONM', 'nreca1824cleanishCoords.dss.omd')
	newOmdPath = pJoin(__neoMetaModel__._omfDir, 'scratch', 'RONM', 'nreca1824cleanCoords.dss.omd')
	badNodes = findCorruptNodes(omdPath, '30.134247', '-84.946092', exceptNodes)
	# badNodes = ['l0247160', 'l0247162', 'l0247171']
	print("Number of bad nodes: " + str(len(badNodes)))
	fixedCoords = fixCorruptedLatLons(omdPath, badNodes, exceptNodes)
	createFixedLatLonOmd(omdPath, fixedCoords, newOmdPath, False)
	map_omd(newOmdPath, pJoin(__neoMetaModel__._omfDir, 'scratch', 'RONM'), 'html', openBrowser=True, conversion=False)


def _tests():
	# e, n = 249.2419752733258, 1186.1488466689188
	# lat, lon = statePlaneToLatLon(e, n, 2205)
	#openInGoogleMaps(lat, lon)
	# print (lat, lon) #(37.37267827914456, -89.89482331256504)
	# e2, n2 = latLonToStatePlane(lat, lon, epsg=2205)
	# print (e2, n2) # (249.24197527189972, 1186.1488466408398)
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	prefix = pathlib.Path(__file__).parent
	map_omd(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', './', open_browser=True)
	# viz(str(prefix / 'static/publicFeeders/Olin Barre LatLon.omd'))
	# viz(str(prefix / 'solvers/opendss/iowa240.clean.dss'))
	# showOnMap(hullOfOmd(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', conversion=False))
	# showOnMap(simplifiedOmdShape(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', conversion=False))
	# x = omdGeoJson(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', conversion=False)
	# print(x)
	# import json
	# with open ('scratch/wind/circuit.geojson', 'w') as outFile:
	# 	json.dump(x, outFile, indent=4)
	# showOnMap(omdGeoJson(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', conversion=False))
	# print(shortestPathOmd(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', 'node62474203981T62474203987_B', 'node1667616792'))
	# Server tests.
	# rasterTilesFromOmd(prefix / 'static/publicFeeders/Olin Barre LatLon.omd', prefix / 'scratch/omdTests/tiles', conversion=False)
	# serveTiles(prefix / 'scratch/omdTests/tiles') # Need to launch in correct directory
	# Testing larger feeder
	#map_omd(prefix / 'static/publicFeeders/Autocli Alberich Calibrated.omd', './', open_browser=True)
	#map_omd(prefix / 'static/publicFeeders/ABEC Frank LO Houses.omd', './', open_browser=True)
	# showOnMap(hullOfOmd(prefix / 'static/publicFeeders/Autocli Alberich Calibrated.omd', conversion=True))
	# showOnMap(simplifiedOmdShape(prefix / 'static/publicFeeders/ABEC Frank LO Houses.omd', conversion=False))
	# showOnMap(omdGeoJson(prefix / 'static/publicFeeders/ABEC Frank LO Houses.omd', conversion=False))
	# rasterTilesFromOmd(prefix / 'static/publicFeeders/Autocli Alberich Calibrated.omd', prefix / 'scratch/omdTests/autoclitiles', conversion=True)
	# print(convertOmd(prefix / 'static/publicFeeders/Autocli Alberich Calibrated.omd'))
	# fixMissingNodes(pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', 'iowa240c2_working_coords.clean.omd'), pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', 'iowa240c1.clean.dss.omd'), pJoin(__neoMetaModel__._omfDir, 'scratch', 'MapTestOutput', 'iowa240c2_fixed_coords2.clean.omd'))

if __name__ == '__main__':
	_tests()
	# _testLatLonfix()
	# _testFixedLatLonOmd()