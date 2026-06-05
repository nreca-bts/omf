"""
Analyze fault location, isolation, and service restoration switching options on a
distribution feeder.
"""
import re, json, os, tempfile, shutil
from os.path import join as pJoin
import pandas as pd
import networkx as nx
# OMF imports
from omf import feeder, geo
import omf
import omf.feeder
import omf.geo
import omf.distNetViz
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
tooltip = 'smartSwitching gives the expected reliability improvement from adding reclosers to a circuit.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True

def safeInt(x):
	"""
	Perform safe int processing for the flisr model.
	"""
	try: return int(x)
	except: return 0

def getMaxSubtree(graph, start):
	'helper function that returns all the nodes connected to a starting node in a graph'
	visited, stack = set(), [start]
	while stack:
		vertex = str(stack.pop())
		if vertex not in visited:
			visited.add(vertex)
			stack.extend(graph[vertex] - visited)
	return visited

def findPathToFault(graph, start, finish):
	'helper function that returns a path from the starting point to finishing point in a graph'
	stack = [(start, [start])]
	while stack:
		(vertex, path) = stack.pop()
		for next in graph[(vertex)] - set(path):
			if next == finish:
				yield path + [next]
			else:
				stack.append((next, path + [next]))

def adjacencyList(tree):
	'helper function which creates an adjacency list representation of graph connectivity'
	adjacList = {}
	reclosers = []
	vertices = set()
	for key in tree.keys():
		obtype = tree[key].get('object','')
		if obtype.startswith('underground_line') or obtype.startswith('overhead_line') or obtype.startswith('triplex_line') or obtype.startswith('switch') or obtype.startswith('recloser') or obtype.startswith('transformer') or obtype.startswith('fuse') or obtype.startswith('regulator') or obtype.startswith('relay') or obtype.startswith('link') or obtype.startswith('fromTo') or obtype.startswith('line'):
			if obtype.startswith('recloser'):
				reclosers.append(tree[key])
			if 'switch' in tree[key]:
				if tree[key].get('switch','').startswith('y'):
					reclosers.append(tree[key])
			if 'from' in tree[key].keys() and 'to' in tree[key].keys():
				if not tree[key]['from'] in adjacList.keys():
					adjacList[tree[key]['from']] = set()
					vertices.add(tree[key].get('from', ''))
				if not tree[key]['to'] in adjacList.keys():
					adjacList[tree[key]['to']] = set()
					vertices.add(tree[key].get('to', ''))
				adjacList[tree[key]['from']].add(tree[key]['to'])
				adjacList[tree[key]['to']].add(tree[key]['from'])
	return adjacList, reclosers, vertices

def removeRecloser(tree, treeCopy, recloser, bestReclosers, found):
	'helper function which removes a recloser (closed switch) from the tree'
	found = True
	bestReclosers.append(recloser)
	for key in treeCopy.keys():
		if treeCopy[key] == recloser:
			del (tree[key])
	
	return tree, bestReclosers, found

def cutoffFault(tree, faultedNode, bestReclosers, workDir, radial, buses):	
	'Step 1: isolate the fault from all power sources'
	tree2 = tree.copy()
	if not buses:
		buses = []
		# create a list of all power sources
		for key in tree2.keys():
			if bool(tree2[key].get('bustype','')) is True:
				buses.append(tree[key]['name'])
	# for each power source
	# create a list to hold all the buses that cannot be isolated from the fault
	badBuses = []
	while len(buses) > 0:
		# create an adjacency list representation of tree connectivity
		adjacList, reclosers, vertices = adjacencyList(tree)
		bus = buses[0]
		# check to see if there is a path between the power source and the fault 
		subtree = getMaxSubtree(adjacList, bus)
		if faultedNode in subtree:
			# find a path to the fault
			path = findPathToFault(adjacList, bus, faultedNode)
			for lis in path:
				row = len(lis) - 1
				# for each path, remove the recloser nearest to the fault
				while row > -1:
					found = False
					for recloser in reclosers:
						if recloser['from'] == lis[row]:
							if recloser['to'] == lis[row-1]:
								tree, bestReclosers, found = removeRecloser(tree, tree2, recloser, bestReclosers, found)
								break
						if recloser['to'] == lis[row]:
							if recloser['from'] == lis[row-1]:
								tree, bestReclosers, found = removeRecloser(tree, tree2, recloser, bestReclosers, found)
								break
					if found == True:
						if radial == 'True':
							del (buses[0])
						break
					row -= 1
				break
			# if there is no way to isolate the fault, notify the user!
			if found == False:
				print('This system is unsolvable with respect to FLISR!')
				badBuses.append(buses[0])
				del (buses[0])
		else:
			del (buses[0])
	return tree, bestReclosers, badBuses

def listPotentiallyViable(tree, tieLines, workDir):
	'Step 2: find the powered and unpowered subtrees and the subset of potentially viable open switches'
	# find the adjacency list representation of connectivity
	adjacList, reclosers, vertices = adjacencyList(tree)
	# create the powered and unpowered subtrees
	powered = set()
	for key in tree.keys():
		if (bool(tree[key].get('bustype','')) is True or tree[key].get('name','') == 'sourcebus'):
			powered |= getMaxSubtree(adjacList, tree[key]['name'])
	print(powered)
	unpowered = vertices - powered
	print(unpowered)
	
	# create a list of dict objects that represents the subset of potentially viable open switches
	potentiallyViable = []
	tie_row_count = tieLines.shape[0]
	print(tie_row_count)
	entry = 0
	while entry < tie_row_count:
		if (str(tieLines.loc[entry, 'to']) in unpowered) and (str(tieLines.loc[entry, 'from']) in powered):
			potentiallyViable.append({'object':tieLines.loc[entry, 'object'], 'phases':tieLines.loc[entry, 'phases'], 'name':tieLines.loc[entry, 'name'], 'from':tieLines.loc[entry, 'from'], 'to':tieLines.loc[entry, 'to']})
		if (str(tieLines.loc[entry, 'from']) in unpowered and str(tieLines.loc[entry, 'to']) in powered):
			potentiallyViable.append({'object':tieLines.loc[entry, 'object'], 'phases':tieLines.loc[entry, 'phases'], 'name':tieLines.loc[entry, 'name'], 'from':tieLines.loc[entry, 'from'], 'to':tieLines.loc[entry, 'to']})
		entry += 1

	return unpowered, powered, potentiallyViable

def chooseOpenSwitch(potentiallyViable):
	'Step 3: pick an open switch from the subset of potentially viable open switches'
	if len(potentiallyViable) > 0:
		openSwitch = potentiallyViable[0]
	else:
		openSwitch = None
	return openSwitch

def addTieLines(tree, faultedNode, potentiallyViable, unpowered, powered, openSwitch, tieLines, bestTies, bestReclosers, workDir, goTo2, goTo3, terminate, index, radial):
	'Step 4: Close open switches and open closed switches to power unpowered connected components'
	biggestKey = max([safeInt(x) for x in tree.keys()])
	tree2 = tree.copy()
	# continue the algorithm until there are no more switches in the subset of potentially viable open switches
	if openSwitch != None:
		# find the node of the switch in the unpowered subtree
		if openSwitch.get('to', '') in unpowered:
			tieNode = openSwitch.get('to', '')
		else:
			tieNode = openSwitch.get('from', '')
		while (goTo2 == False) and (goTo3 == False):
			# get an adjacency list representation of tree connectivity
			adjacList, reclosers, vertices = adjacencyList(tree)
			# check if the faulted node is in the same subtree as the node connected to the unpowered subtree
			subtree = getMaxSubtree(adjacList, tieNode)
			if faultedNode in subtree:
				# find a path between the switch and the fault
				path = findPathToFault(adjacList, tieNode, faultedNode)
				for lis in path:
					row = len(lis) - 1
					# open the recloser nearest to the fault
					while row > -1:
						found = False
						for recloser in reclosers:
							if recloser['to'] == lis[row]:
								if recloser['from'] == lis[row-1]:
									tree, bestReclosers, found = removeRecloser(tree, tree2, recloser, bestReclosers, found)
									break
							if recloser['from'] == lis[row]:
								if recloser['to'] == lis[row-1]:
									tree, bestReclosers, found = removeRecloser(tree, tree2, recloser, bestReclosers, found)
									break
						if found == True:
							if radial == 'True':
								goTo2 = True
								bestTies.append(openSwitch)
								index += 1
								tree[str(biggestKey*10 + index)] = {'object':openSwitch.get('object',''), 'phases':openSwitch.get('phases',''), 'name':openSwitch.get('name',''), 'from':openSwitch.get('from',''), 'to':openSwitch.get('to','')}
								entry = 0
								while entry < tieLines.shape[0]:
									if openSwitch.get('name', '') == tieLines.loc[entry, 'name']:
										tieLines.drop(tieLines.index[[entry]], inplace=True)
										tieLines = tieLines.reset_index(drop=True)
										break
									entry += 1
							break
						row -= 1
					break
				# if there is no such recloser, then the switch is deleted from the subset of potentially viable switches
				if found == False:
					goTo3 = True
					del (potentiallyViable[0])
			# if there is no path between the switch and fault, close the switch
			else:
				goTo2 = True
				bestTies.append(openSwitch)
				index += 1
				tree[str(biggestKey*10 + index)] = {'object':openSwitch.get('object',''), 'phases':openSwitch.get('phases',''), 'name':openSwitch.get('name',''), 'from':openSwitch.get('from',''), 'to':openSwitch.get('to','')}
				entry = 0
				while entry < tieLines.shape[0]:
					if openSwitch.get('name', '') == tieLines.loc[entry, 'name']:
						tieLines.drop(tieLines.index[[entry]], inplace=True)
						tieLines = tieLines.reset_index(drop=True)
						break
					entry += 1
	# if the subset of potentially viable switches is empty, end the algorithm
	else:
		terminate = True
	return tree, potentiallyViable, tieLines, bestTies, bestReclosers, goTo2, goTo3, terminate, index

def coordsFromString(entry):
	'helper function to take a location string to two integer values'
	p = re.compile(r'-?\d+\.\d+')  # Compile a pattern to capture float values
	coord = [float(i) for i in p.findall(str(entry))]  # Convert strings to float
	coordLat = coord[0]
	coordLon = coord[1]
	return coordLat, coordLon, coord

def nodeToCoords(outageMap, nodeName):
	'get the latitude and longitude of a given node in string format'
	coords = ''
	for key in outageMap['features']:
		if (nodeName in key['properties'].get('name','')):
			current = key['geometry']['coordinates']
			coord1, coord2, coords = coordsFromString(current)
	return coords

def flisr(pathToOmd, pathToTieLines, faultedLine, workDir, radial, drawMap):
	'run the FLISR algorithm to isolate the fault and restore power'
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)

	# read in the tree
	with open(pathToOmd) as inFile:
		tree = json.load(inFile)['tree']

	# find a node associated with the faulted line
	faultedNode = ''
	faultedNode2 = ''
	for key in tree.keys():
		if tree[key].get('name','') == faultedLine:
			faultedNode = tree[key]['from']
			faultedNode2 = tree[key]['to']

	busNodes = []
	for key in tree.keys():
		if tree[key].get('bustype','') == 'SWING':
			busNodes.append(tree[key]['name'])

	# initialize the list of ties closed and reclosers opened
	bestTies = []
	bestReclosers = []

	# Step 1
	tree, bestReclosers, badBuses = cutoffFault(tree, faultedNode, bestReclosers, workDir, radial, None)

	# read in the set of tie lines in the system as a dataframe
	tieLines = pd.read_csv(pathToTieLines)

	# start the restoration piece of the algorithm
	index = 0
	terminate = False
	goTo4 = False
	goTo3 = False
	goTo2 = True
	while terminate == False:
		# Step 2
		if goTo2 == True:
			goTo2 = False
			goTo3 = True
			unpowered, powered, potentiallyViable = listPotentiallyViable(tree, tieLines, workDir)
		# Step 3
		if goTo3 == True:
			goTo3 = False
			goTo4 = True
			openSwitch = chooseOpenSwitch(potentiallyViable)
		# Step 4
		if goTo4 == True:
			goTo4 = False
			tree, potentiallyViable, tieLines, bestTies, bestReclosers, goTo2, goTo3, terminate, index = addTieLines(tree, faultedNode, potentiallyViable, unpowered, powered, openSwitch, tieLines, bestTies, bestReclosers, workDir, goTo2, goTo3, terminate, index, radial)
	# Run powerflow on the optimal solution
	biggestKey = max([safeInt(x) for x in tree.keys()])
	tree[str(biggestKey*10 + index + 1)] = {'module':'powerflow','solver_method':'FBS'}
	attachments = []
	gridlabOut = omf.solvers.gridlabd.runInFilesystem(tree, attachments=attachments, workDir=workDir)

	def switchStats(tieLines, bestTies):
		new_html_str = """
			<table cellpadding="0" cellspacing="0">
				<thead>
					<tr>
						<th>Name</th>
						<th>Status</th>
						<th>From</th>
						<th>To</th>
					</tr>
				</thead>
				<tbody>"""
		
		for openSwitch in bestTies:
			new_html_str += '<tr><td><b>' + str(openSwitch.get('name', '')) + '</b></td><td>'+'Closed'+'</td><td>'+str(openSwitch.get('from', ''))+'</td><td>'+str(openSwitch.get('to', ''))+'</td></tr>'

		for recloser in bestReclosers:
			new_html_str += '<tr><td><b>' + str(recloser.get('name', '')) + '</b></td><td>'+'Open'+'</td><td>'+str(recloser.get('from', ''))+'</td><td>'+str(recloser.get('to', ''))+'</td></tr>'

		row = 0
		while row < len(tieLines):
			new_html_str += '<tr><td><b>' + str(tieLines.loc[row, 'name']) + '</b></td><td>'+'Open'+'</td><td>'+str(tieLines.loc[row, 'from'])+'</td><td>'+str(tieLines.loc[row, 'to'])+'</td></tr>'
			row += 1

		for key in tree:
			if tree[key].get('object','') == 'recloser':
				new_html_str += '<tr><td><b>' + str(tree[key].get('name', '')) + '</b></td><td>'+'Closed'+'</td><td>'+str(tree[key].get('from', ''))+'</td><td>'+str(tree[key].get('to', ''))+'</td></tr>'
		new_html_str +="""</tbody></table>"""

		return new_html_str

	# print all intermediate and final costs
	switchStatsHtml = switchStats(
		tieLines = tieLines,
		bestTies = bestTies)
	with open(pJoin(workDir, 'switchStats.html'), 'w') as switchFile:
		switchFile.write(switchStatsHtml)

	# Draw a leaflet graph of the feeder with added tie lines and opened reclosers
	if drawMap == 'True':
		for key in bestReclosers:
			print(key)
			index += 1
			tree[str(biggestKey*10 + index)] = {'object':key.get('object',''), 'phases':key.get('phases',''), 'name':key.get('name',''), 'from':key.get('from',''), 'to':key.get('to','')}
		# type: (dict) -> None
		"""Insert additional latitude and longitude data into the dictionary."""
		print("Force laying out the graph...")
		# Use graphviz to lay out the graph.
		inGraph = omf.feeder.treeToNxGraph(tree)
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(inGraph.edges())
		# HACK2: might miss nodes without edges without the following.
		cleanG.add_nodes_from(inGraph)
		# pos = nx.nx_agraph.graphviz_layout(cleanG, prog='neato')
		pos = nx.kamada_kawai_layout(cleanG)
		pos = {k:(1000 * pos[k][0],1000 * pos[k][1]) for k in pos} # get out of array notation
		# # Charting the feeder in matplotlib:
		# feeder.latLonNxGraph(inGraph, labels=False, neatoLayout=True, showPlot=True)
		# Insert the latlons.
		for key in tree:
			obName = tree[key].get('name','')
			thisPos = pos.get(obName, None)
			if thisPos != None:
				# lon, lat = latlon2relativeXY(thisPos[0],thisPos[1])
				tree[key]['longitude'] = thisPos[0]
				tree[key]['latitude'] = thisPos[1]

		'''Create a geojson standards compliant file (https://tools.ietf.org/html/rfc7946) from an omd.'''
		nxG = feeder.treeToNxGraph(tree)
		#use conversion for testing other feeders
		nxG = geo.graphValidator(pathToOmd, nxG)
		# nxG = convertOmd(pathToOmd)
		geoJsonDict = {
			"type": "FeatureCollection",
			"features": []
		}
		#Add nodes to geoJSON
		node_positions = {nodewithPosition: nxG.nodes[nodewithPosition]['pos'] for nodewithPosition in nx.get_node_attributes(nxG, 'pos')}
		node_types = {nodewithType: nxG.nodes[nodewithType]['type'] for nodewithType in nx.get_node_attributes(nxG, 'type')}
		for node in node_positions:
			# geo.latlon2relativeXY(node_positions[node][1], node_positions[node][0])
			geoJsonDict['features'].append({
				"type": "Feature", 
				"geometry":{
					"type": "Point",
					"coordinates": [node_positions[node][1], node_positions[node][0]]
				},
				"properties":{
					"name": node,
					#"pointType": node_types[node],
					# "pointColor": _obToCol(node_types[node])
				}
			})
		#Add edges to geoJSON
		edge_types = {edge: nxG[edge[0]][edge[1]]['type'] for edge in nx.get_edge_attributes(nxG, 'type')}
		edge_phases = {edge: nxG[edge[0]][edge[1]]['phases'] for edge in nx.get_edge_attributes(nxG, 'phases')}
		for edge in nx.edges(nxG):
			geoJsonDict['features'].append({
				"type": "Feature", 
				"geometry": {
					"type": "LineString",
					"coordinates": [[node_positions[edge[0]][1], node_positions[edge[0]][0]], [node_positions[edge[1]][1], node_positions[edge[1]][0]]]
				},
				"properties":{
					#"phase": edge_phases[edge],
					#"edgeType": edge_types[edge],
					#"edgeColor":_obToCol(edge_types[edge])
				}
			})
		outageMap = geoJsonDict

		# outageMap = geo.omdGeoJson(pathToOmd, conversion=False)

		Dict = {}
		Dict['geometry'] = {'type': 'LineString', 'coordinates': [nodeToCoords(outageMap, str(faultedNode)), nodeToCoords(outageMap, str(faultedNode2))]}
		Dict['type'] = 'Feature'
		Dict['properties'] = {'name': 'faultedLine',
							  'edgeColor': 'red'}
		outageMap['features'].append(Dict)

		row = 0
		while row < len(bestTies):
			Dict = {}
			Dict['geometry'] = {'type': 'LineString', 'coordinates': [nodeToCoords(outageMap, str(bestTies[row]['from'])), nodeToCoords(outageMap, str(bestTies[row]['to']))]}
			Dict['type'] = 'Feature'
			Dict['properties'] = {'name': bestTies[row]['name'],
								  'edgeColor': 'yellow'}
			outageMap['features'].append(Dict)
			row += 1

		row = 0
		while row < len(tieLines):
			Dict = {}
			Dict['geometry'] = {'type': 'LineString', 'coordinates': [nodeToCoords(outageMap, str(tieLines.loc[row, 'from'])), nodeToCoords(outageMap, str(tieLines.loc[row, 'to']))]}
			Dict['type'] = 'Feature'
			Dict['properties'] = {'name': str(tieLines.loc[row, 'name']),
								  'edgeColor': 'purple'}
			outageMap['features'].append(Dict)
			row += 1

		row = 0
		while row < len(bestReclosers):
			Dict = {}
			Dict['geometry'] = {'type': 'LineString', 'coordinates': [nodeToCoords(outageMap, str(bestReclosers[row]['from'])), nodeToCoords(outageMap, str(bestReclosers[row]['to']))]}
			Dict['type'] = 'Feature'
			Dict['properties'] = {'name': bestReclosers[row]['name'],
								  'edgeColor': 'cyan'}
			outageMap['features'].append(Dict)
			row += 1

		for key in tree:
			if tree[key].get('object','') == 'recloser':
				Dict = {}
				Dict['geometry'] = {'type': 'LineString', 'coordinates': [nodeToCoords(outageMap, str(tree[key].get('from', ''))), nodeToCoords(outageMap, str(tree[key].get('from', '')))]}
				Dict['type'] = 'Feature'
				Dict['properties'] = {'name': str(tree[key].get('name', '')),
								  'edgeColor': 'blue'}
				outageMap['features'].append(Dict)
			if tree[key].get('name', '') in powered:
				Dict = {}
				Dict['geometry'] = {'type': 'Point', 'coordinates': nodeToCoords(outageMap, str(tree[key].get('name', '')))}
				Dict['type'] = 'Feature'
				Dict['properties'] = {'name': tree[key].get('name', ''),
								  'pointColor': 'silver'}
				outageMap['features'].append(Dict)

		row = 0
		while row < len(busNodes):
			Dict = {}
			Dict['geometry'] = {'type': 'Point', 'coordinates': nodeToCoords(outageMap, str(busNodes[row]))}
			Dict['type'] = 'Feature'
			Dict['properties'] = {'name': 'swingbus' + str(row+1),
								  'pointColor': 'orange'}
			outageMap['features'].append(Dict)
			row += 1

		if not os.path.exists(workDir):
			os.makedirs(workDir)
		shutil.copy(omf.omfDir + '/templates/geoJsonMap.html', workDir)
		with open(pJoin(workDir,'geoJsonFeatures.js'),'w') as outFile:
			outFile.write('var geojson =')
			json.dump(outageMap, outFile, indent=4)

		#Save geojson dict to then read into outdata in work function below
		with open(pJoin(workDir,'geoDict.js'),'w') as outFile:
			json.dump(outageMap, outFile, indent=4)

	return {'bestReclosers':bestReclosers, 'bestTies':bestTies, 'switchStatsHtml': switchStatsHtml, 'powered': powered}

#flisr('C:/Users/granb/omf/omf/static/publicFeeders/Olin Barre Fault Test 2.omd', 'C:/Users/granb/omf/omf/static/testFiles/flisr_test.csv', "19186", None, True)

def work(modelDir, inputDict):
	# Copy specific climate data into model directory
	"""
	Run the flisr model analysis and return the output data used by the OMF interface.
	"""
	outData = {}
	# Write the feeder
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName
	#test the main functions of the program
	with open(pJoin(modelDir, inputDict['tieFileName']), 'w') as f:
		pathToData = f.name
		f.write(inputDict['tieData'])
	plotOuts = flisr(
		modelDir + '/' + feederName + '.omd', #OMD Path
		pathToData, #Tie Line Data Path
		inputDict['faultedLine'], #'19186'
		modelDir, #Work directory.
		inputDict['radial'], #'True'
		inputDict['drawMap']) #'True') 
	
	# Textual outputs of cost statistic
	with open(pJoin(modelDir,'switchStats.html')) as inFile:
		outData['switchStatsHtml'] = inFile.read()

	#The geojson dictionary to load into the outageCost.py template
	if inputDict['drawMap'] == 'True':
		with open(pJoin(modelDir,'geoDict.js'),'rb') as inFile:
			outData['geoDict'] = inFile.read().decode()

	# Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','testOlinBarreFault.csv')) as f:
		tie_data = f.read()
	defaultInputs = {
		'modelType': modelName,
		'feederName1': 'Olin Barre Fault Test 2',
		'faultedLine': '19186',
		'radial': 'True',
		'runPowerflow': 'True',
		'drawMap': 'True',
		'tieFileName': 'testOlinBarreFault.csv',
		'tieData': tie_data
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', defaultInputs['feederName1']+'.omd'), pJoin(modelDir, defaultInputs['feederName1']+'.omd'))
	except:
		return False
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
	# Create New.
	new(modelLoc)
	# Pre-run.
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()

