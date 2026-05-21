"""
Read, write, convert, transform, and analyze OMF distribution feeder models represented
as GridLAB-D files, OpenDSS files, and OMF feeder trees.
"""

import datetime, copy, os, re, warnings, json, platform
from functools import reduce
import networkx as nx
from omf.solvers.opendss import dssConvert
import matplotlib
from matplotlib import pyplot as plt

# Wireframe for new OMD objects:
newFeederWireframe = dssConvert.newFeederWireframe

def load(inPath, attachPaths=[]):
	'''Load a .omd or .glm file in to an in-memory feeder object.
	If you're loading a .glm and it has #include attachments, specify those paths in the optional argument.
	'''
	if inPath.endswith('.omd'):
		with open(inPath, 'r') as inFile:
			return json.load(inFile)
	elif inPath.endswith('.glm'):
		tree = parse(inPath)
		omd = dict(newFeederWireframe)
		omd['tree'] = tree
		for attPath in attachPaths:
			fname = os.path.basename(attPath)
			with open(attPath, 'r') as attFile:
				omd['attachments'][fname] = attFile.read()
		return omd
	else:
		raise Exception('Unsupported filetype at path ' + inPath)


def save(inOmd, outPath):
	'''Save an in-memory OMD to a file, nicely formatted.'''
	with open(outPath, 'w') as outFile:
		json.dump(inOmd, outFile, indent=4)


def dump(inTree, outPath):
	''' Just dump a .glm in a file. '''
	with open(outPath, 'w') as outFile:
		outFile.write(write(inTree))


def parse(inputStr, filePath=True):
	''' Parse a GLM into an omf.feeder tree. This is so we can walk the tree, change things in bulk, etc.
	Input can be a filepath or GLM string.
	'''
	tokens = _tokenizeGlm(inputStr, filePath)
	return _parseTokenList(tokens)


def write(inTree):
	''' Turn an omf.feeder tree object into a GLM-formatted string. '''
	output = ''
	for key in inTree:
		output += _dictToString(inTree[key]) + '\n'
	return output


def sortedWrite(inTree):
	''' Write out a GLM from a tree, and order all tree objects by their key. 
	Sometimes Gridlab breaks if you rearrange a GLM.
	'''
	sortedKeys = sorted(inTree.keys(), key=int)
	output = ''
	try:
		for key in sortedKeys:
			# print inTree[key]
			output += _dictToString(inTree[key]) + '\n'
	except ValueError:
		raise Exception
	return output


def glmToOmd(glmPath, omdPath, attachFilePaths=[]):
	''' Read in a glm file and take a shot at writing an omd. '''
	tree = parse(glmPath, filePath=True)
	omd = dict(newFeederWireframe)
	omd['tree'] = tree
	# Add attachment files.
	for attPath in attachFilePaths:
		dirs, fname = os.path.split(attPath)
		with open(attPath) as f:
			omd['attachments'][fname] = f.read()
	with open(omdPath, 'w') as outFile:
		json.dump(omd, outFile, indent=4)


def omdToGlm(omdPath, outDir):
	''' Write an .omd to a .glm and associated files. '''
	# Read the omd
	with open(omdPath) as f:
		omd = json.load(f)
	# Write attachments and glm.
	attachments = omd.get('attachments','')
	for attach in attachments:
		with open(os.path.join(outDir, attach),'w') as attachFile:
			attachFile.write(attachments[attach])
	# Write the glm.
	glmString = sortedWrite(omd['tree'])
	glmName = os.path.basename(omdPath)[0:-4] + '.glm'
	with open(os.path.join(outDir, glmName),'w') as glmFile:
		glmFile.write(glmString)


def chart(inTree, labels=False, neatoLayout=False, showPlot=False):
	''' Return a matplotlib chart of a feeder.'''
	nxG = treeToNxGraph(inTree)
	return latLonNxGraph(nxG, labels=labels, neatoLayout=neatoLayout, showPlot=showPlot)


def nameIndex(inTree):
	''' Return a dictionary mapping object names to keys in the tree.
	Massively speeds up searches if you need to do them more than once.
	'''
	return {inTree[key].get('name',''):key for key in inTree}


def getMaxKey(inTree):
	''' Find the largest key value in the tree. We need this because de-embedding causes noncontiguous keys. '''
	keys = [int(x) for x in inTree.keys()]
	return max(keys)


def insert(tree, gridlabdObject, index=None):
	''' Add an object to the tree; if index=None put it on the end.
	WARNING: the tree will be modified in-place. Consider making a copy.deepcopy of the original tree. '''
	if index == None:
		tree[str(getMaxKey(tree) + 1)] = gridlabdObject	
	elif tree.get(str(index), None) is None:
		tree[str(index)] = gridlabdObject
	else:
		swap = tree[str(index)]
		tree[str(index)] = gridlabdObject
		tree = insert(tree, swap, index + 1)


def rekey(tree):
	''' Update the keys in the tree to be continues integers (cast as strings for web-safety). '''
	rekeyedTree = {}
	sortedKeys = tree.keys()
	sortedKeys = [int(x) for x in sortedKeys]
	sortedKeys.sort()
	sortedKeys = [str(x) for x in sortedKeys]
	for index, key in enumerate(sortedKeys):
		rekeyedTree[str(index)] = tree[key] 
	return rekeyedTree


def adjustTime(tree, simLength, simLengthUnits, simStartDate):
	''' Adjust a GLM clock and recorders to start/stop/step specified. '''
	# translate LengthUnits to minutes.
	if simLengthUnits == 'seconds':
		lengthInSeconds = simLength
		interval =  1
	elif simLengthUnits == 'minutes':
		lengthInSeconds = simLength * 60
		interval = 60
	elif simLengthUnits == 'hours':
		lengthInSeconds = 3600 * simLength
		interval = 3600
	elif simLengthUnits == 'days':
		lengthInSeconds = 86400 * simLength
		interval = 3600
	try: starttime = datetime.datetime.strptime(simStartDate, '%Y-%m-%d %H:%M:%S')
	except:	starttime = datetime.datetime.strptime(simStartDate, '%Y-%m-%d')
	stoptime = starttime + datetime.timedelta(seconds=lengthInSeconds)
	# alter the clocks and recorders:
	for x in tree:
		leaf = tree[x]
		if 'clock' in leaf:
			# Ick, Gridlabd wants time values wrapped in single quotes:
			leaf['starttime'] = "'" + str(starttime) + "'"
			# Apparently it needs timestamp=starttime. Gross! Bizarre!
			leaf['timestamp'] = "'" + str(starttime) + "'"
			leaf['stoptime'] = "'" + str(stoptime) + "'"
		elif 'object' in leaf and (leaf['object'] == 'recorder' or leaf['object'] == 'collector'):
			leaf['interval'] = str(interval)
			# We're trying limitless for the time being.
			# leaf['limit'] = str(simLength)
			# Also, set the file since we're already inside this data structure.
			if leaf['file'] == 'meterRecorder_XXX.csv':
				leaf['file'] = 'meterRecorder_' + leaf['name'] + '.csv'
		elif 'argument' in leaf and leaf['argument'].startswith('minimum_timestep'):
			leaf['argument'] = 'minimum_timestep=' + str(interval)


def fullyDeEmbed(glmTree):
	''' Take any embedded objects in a GLM and make them top-level objects.

	Example, turns the tree that looks this:
		object house {name myhouse; object ZIPload {inductance bigind; power newpower;}; size 234sqft;}; 

	Into this:
		object house {name myhouse; ZIPload newZIP; size 234sqft;}; 
		object ZIPload {name newZIP; inductance bigind; power newpower;};
	'''
	lenDiff = 1
	while lenDiff != 0:
		currLen = len(glmTree)
		_deEmbedOnce(glmTree)
		lenDiff = len(glmTree) - currLen


def _mergeContigLinesOnce(tree):
	# TODO: Check for switches that prevent valid reduction opportunities
	"""
	Internal helper for feeder merge contig lines once processing.
	"""
	n2k = nameIndex(tree)
	treecopy = tree.copy()
	removedNames = []
	while treecopy:
		o = treecopy.popitem() # destructively iterate through treecopy
		o = o[1]
		if o.get('name') in removedNames:
			continue
		if (not 'to' in o):
			continue
		top = o
		node = tree[n2k[o['to']]] # get downstream node
		# Check that no other objects are attached to this node
		allBottoms = [x for x in tree.values() if (
			x.get('from', None) == node['name'] 
			or x.get('parent', None) == node['name']
			or x.get('to', None) == node['name']
			) and not x == o]
		if len(allBottoms) != 1:
			continue
		bottom = allBottoms[0]
		if (top.get('configuration','NTC') == bottom.get('configuration','NBC')) and ('length' in top) and ('length' in bottom):
			# delete node and bottom line. Make top line length = sum of both lines. Connect the new bottom.
			newLen = float(top['length']) + float(bottom['length']) # get the new length
			removedNames.append(bottom['name'])
			topTree = tree[n2k[o['name']]]
			topTree['length'] = str(newLen)
			topTree['to'] = bottom['to']
			del tree[n2k[node['name']]]
			del tree[n2k[bottom['name']]]
	#for x in removedNames: # DEBUG
	#	print(x)  # DEBUG


def mergeContigLines(tree):
	''' merge all lines that are across nodes and have the same config
	topline --to-> node <-from-- bottomline'''
	removedKeys = 1
	while removedKeys != 0:
		treeKeys = len(tree.keys())
		_mergeContigLinesOnce(tree)
		removedKeys = treeKeys - len(tree.keys())
	

def attachRecorders(tree, recorderType, keyToJoin, valueToJoin):
	''' Walk through a tree an and attach Gridlab recorders to the indicated type of node.'''
	# HACK: the biggestKey assumption only works for a flat tree or one that has a flat node for the last item...
	biggestKey = sorted([int(key) for key in tree.keys()])[-1] + 1
	# Types of recorders we can attach:
	recorders = {	'Regulator':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'Regulator_Y.csv', 'property':'tap_A,tap_B,tap_C,power_in_A.real,power_in_A.imag,power_in_B.real,power_in_B.imag,power_in_C.real,power_in_C.imag,power_in.real,power_in.imag,phases'},
					'Voltage':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'Voltage_Y.csv', 'property':'voltage_1.real,voltage_1.imag,voltage_2.real,voltage_2.imag,voltage_12.real,voltage_12.imag'},
					'Capacitor':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'Capacitor_Y.csv', 'property':'switchA,switchB,switchC,phases'},
					'Climate':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'climate.csv', 'property':'temperature,solar_direct,wind_speed,rainfall,snowdepth,solar_global'},
					'Inverter':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'inverter_Y.csv', 'property':'power_A.real,power_A.imag,power_B.real,power_B.imag,power_C.real,power_C.imag'},
					'Windmill':{'interval':'1', 'parent':'X', 'object':'recorder', 'limit':'0', 'file':'windmill_Y.csv', 'property':'voltage_A.real,voltage_A.imag,voltage_B.real,voltage_B.imag,voltage_C.real,voltage_C.imag,current_A.real,current_A.imag,current_B.real,current_B.imag,current_C.real,current_C.imag'},
					'CollectorVoltage':{'interval':'1', 'object':'collector', 'limit':'0', 'file':'VoltageJiggle.csv', 'group':'class=triplex_meter', 'property':'min(voltage_12.mag),mean(voltage_12.mag),max(voltage_12.mag),std(voltage_12.mag)'},
					'OverheadLosses':{'group':'class=overhead_line', 'interval':'1', 'object':'collector', 'limit':'0', 'file':'OverheadLosses.csv', 'property':'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
					'UndergroundLosses':{'group':'class=underground_line', 'interval':'1', 'object':'collector', 'limit':'0', 'file':'UndergroundLosses.csv', 'property':'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
					'TriplexLosses':{'group':'class=triplex_line', 'interval':'1', 'object':'collector', 'limit':'0', 'file':'TriplexLosses.csv', 'property':'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
					'TransformerLosses':{'group':'class=transformer', 'interval':'1', 'object':'collector', 'limit':'0', 'file':'TransformerLosses.csv', 'property':'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'}
				}
	# If the recorder doesn't have a parent don't walk the tree:
	if 'parent' not in recorders[recorderType]:
		# What class of objects are we trying to attach to?
		objectSet = set([tree[x]['object'] for x in tree.keys() if 'object' in tree[x]])
		groupClass = recorders[recorderType]['group'][6:]
		# Only attach if the right objects are there: 
		if groupClass in objectSet:
			newLeaf = copy.copy(recorders[recorderType])
			tree[biggestKey] = newLeaf
			biggestKey += 1
	# Walk the tree. Don't worry about a recursive walk (yet).
	staticTree = copy.copy(tree)
	for key in staticTree:
		leaf = staticTree[key]
		if keyToJoin in leaf and 'name' in leaf:
			parentObject = leaf['name']
			if leaf[keyToJoin] == valueToJoin:
				# DEBUG:print 'just joined ' + parentObject
				newLeaf = copy.copy(recorders[recorderType])
				newLeaf['parent'] = parentObject
				newLeaf['file'] = recorderType + '_' + parentObject + '.csv'
				tree[biggestKey] = newLeaf
				biggestKey += 1


def groupSwingKids(tree):
	''' Apply group properties to all links attached to swing nodes.'''
	staticTree = copy.copy(tree)
	swingNames = []
	swingTypes = []
	# find the swing nodes:
	for key in staticTree:
		leaf = staticTree[key]
		if 'bustype' in leaf and leaf['bustype'] == 'SWING':
			swingNames += [leaf['name']]
	# set the groupid on the kids:
	for key in staticTree:
		leaf = staticTree[key]
		if 'from' in leaf and 'to' in leaf:
			if leaf['from'] in swingNames or leaf['to'] in swingNames:
				leaf['groupid'] = 'swingKids'
				swingTypes += [leaf['object']]
	# attach the collector:
	biggestKey = sorted([int(key) for key in tree.keys()])[-1] + 1
	collector = {'interval':'1', 'object':'collector', 'limit':'0', 'group':'X', 'file':'Y', 'property':'sum(power_in.real),sum(power_in.imag)'}
	for obType in swingTypes:
		insert = copy.copy(collector)
		insert['group'] = 'class=' + obType + ' AND groupid=swingKids'
		insert['file'] = 'SwingKids_' + obType + '.csv'
		tree[biggestKey] = insert
		biggestKey += 1


def removeNumberRefs(tree):
	''' Mutate a tree to remove the number ref names like "node:13".
	Replaces them with regular names and fixes all the references. '''
	# Generate map subValName -> Key
	subValToKeys = {}
	for key in tree.keys():
		obj = tree[key]
		for sub_key in obj:
			val = obj[sub_key]
			if type(val) is dict:
				continue # avoid sub-dicts.
			if val in subValToKeys:
				subValToKeys[val].append(key)
			else:
				subValToKeys[val] = [key]
	# Rewrite the references.
	for key in tree.keys():
		obj = tree[key]
		obType = obj.get('object','')
		if ':' in obType:
			# If it's missing a name, give it one.
			goodType = obType[0:obType.find(':')]
			if 'name' not in obj:
				goodName = obType.replace(':', '_')
				obj['name'] = goodName
			else:
				goodName = obj['name']
			obj['object'] = goodType
			# Rewrite all the bad obj:number references
			badRefs = subValToKeys.get(obType,[])
			for key in badRefs:
				for subkey in tree[key]:
					val = tree[key][subkey]
					if val == obType and subkey != 'object':
						tree[key][subkey] = goodName

def findParentCoords(inTree, item, defaultCoords):
	"""
	Find the parent coords that satisfies this workflow's search criteria.
	"""
	nameRefTree = {}
	for key in inTree:
		itemOb = inTree[key]
		if 'name' in itemOb.keys():
			itemName = itemOb['name']
			nameRefTree[itemName] = key

	if 'parent' in item.keys():
		parentName = item['parent']
		#check to see if the parent object is in nameRefTree
		if parentName in nameRefTree.keys():
			parentKey = nameRefTree[parentName]
			parentItem = inTree[parentKey]
			try:
				parentCoords = (float(parentItem['latitude']), float(parentItem['longitude']))
				print("Coordinates found for " + parentName + ", parent of " + item['name'] + " : " + str(parentCoords))
			except KeyError:
				print("No coordinates for " + parentName + ", parent of " + item['name'] + ", looking for parent coordinates now...")
				parentCoords = findParentCoords(inTree, parentItem, defaultCoords)
		else:
			print(parentName + ", parent of " + item['name'] + ", was not found in nameRefTree, assigning default coordinates.")
			parentCoords = defaultCoords
	elif 'from' in item.keys():
		#case in which the parent of an object is an edge (transformers are represented this way sometimes)
		fromName = item['from']
		if fromName in nameRefTree.keys():
			fromKey = nameRefTree[fromName]
			fromItem = inTree[fromKey]
			try:
				parentCoords = (float(fromItem['latitude']), float(fromItem['longitude']))
				print("Coordinates found for " + fromName + ", \"from\" of " + item['name'] + " : " + str(parentCoords))
			except KeyError:
				print("No coordinates for " + fromName + ", \"from\" of " + item['name'] + ", looking for parent coordinates now...")
				parentCoords = findParentCoords(inTree, fromItem, defaultCoords)
	else:
		print("No parent found for " + item['name'] + ", assigning default coordinates.")
		parentCoords = defaultCoords
	return parentCoords

def calcDefaultCoords(inTree):
	"""
	Calculate default coords for this analysis.
	"""
	lats = []
	lons = []
	for key in inTree:
		item = inTree[key]
		if 'latitude' in item.keys():
			lats.append(float(item['latitude']))
		if 'longitude' in item.keys():
			lons.append(float(item['longitude']))
	if len(lats) != 0:
		latitude_min = min(lats)
		latitude_max = max(lats)
	else:
		latitude_min = 0.0
		latitude_max = 0.0
	if len(lons) != 0:
		longitude_min = min(lons)
		longitude_max = max(lons)
	else:
		longitude_min = 0.0
		longitude_max = 0.0
	return (latitude_max, longitude_min)

def treeToNxGraph(inTree, digraph=False):
	''' Convert feeder tree to networkx graph. If digraph then make it a directed graph. '''
	if digraph:
		outGraph = nx.DiGraph()
	else:
		outGraph = nx.Graph()
	#TODO: make default coordinates change slightly each time they are assigned to a node to prevent multiple location-less nodes to just be stacked on top of each other
	defaultCoords = calcDefaultCoords(inTree)
	for key in inTree:
		item = inTree[key]
		# This check is why configuration objects never get coordinates. Or maybe this is intentional because configuration objects are added later?
		if 'name' in item.keys():
			item_name = item['name']
			if 'parent' in item.keys():
				# add edge and node for an object with a parent.
				outGraph.add_edge(item_name, item['parent'], type='parentChild', phases=1)
				# set all attributes.
				for k in item:
					outGraph.nodes[item_name][k] = item[k]
				outGraph.nodes[item_name]['type'] = item['object']
				# Note that attached houses via gridEdit.html won't have lat/lon values, so this try is a workaround.
				try:
					outGraph.nodes[item_name]['pos'] = (float(item['latitude']), float(item['longitude']))
				except KeyError:
					#if the grid object doesn't have a lat/lon, give it a lat/lon close or same to that of its parent if it has one
					print("No coordinates found for " + item_name + ", looking for parent coordinates now...")
					outGraph.nodes[item_name]['pos'] = findParentCoords(inTree, item, defaultCoords)
				except:
					outGraph.nodes[item_name]['pos'] = defaultCoords
			elif 'from' in item.keys():
				# add an edge for an edge-type object
				myPhase = _phaseCount(item.get('phases','AN'))
				outGraph.add_edge(item['from'], item['to'], name=item.get('name',''), type=item['object'], phases=myPhase)
				for k in item:
					outGraph.edges[(item['from'], item['to'])][k] = item[k]
			elif item_name in outGraph:
				# Edge already led to node's addition, so just set the attributes:
				outGraph.nodes[item_name]['type'] = item['object']
				for k in item:
					outGraph.nodes[item_name][k] = item[k]
			else:
				# else must be a node, so add it.
				outGraph.add_node(item_name, type=item['object'])
				for k in item:
					outGraph.nodes[item_name][k] = item[k]
			if 'latitude' in item.keys() and 'longitude' in item.keys():
				# Ignore lines that have "latitude" and "longitude" properties
				if 'from' not in item.keys():
					try:
						outGraph.nodes[item_name]['pos'] = (float(item['latitude']), float(item['longitude'])) 
					except:
						outGraph.nodes[item_name]['pos'] = defaultCoords
	return outGraph

def latLonNxGraph(inGraph, labels=False, neatoLayout=False, showPlot=False):
	''' Draw a networkx graph representing a feeder.'''
	# Be quiet Matplotlib.
	# warnings.filterwarnings("ignore",category=matplotlib.cbook.mplDeprecation)
	# Set up figure.
	plt.axis('off')
	plt.tight_layout()
	plt.gca().invert_yaxis()
	plt.gca().set_aspect('equal')
	# Layout the graph via GraphViz neato. Handy if there's no lat/lon data.
	if neatoLayout:
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(inGraph.edges()) # Return a list of edges
		# HACK2: might miss nodes without edges without the following.
		cleanG.add_nodes_from(inGraph)
		# pos = nx.nx_agraph.graphviz_layout(cleanG, prog='neato')
		pos = nx.kamada_kawai_layout(cleanG)
		pos = {k:(1000 * pos[k][0],1000 * pos[k][1]) for k in pos} # get out of array notation
	else:
		pos = {n: inGraph.nodes[n].get('pos', (0, 0)) for n in inGraph}
	# Draw all the edges.
	edge_styles = {'parentChild': 'dotted', 'underground_line': 'dashed'}
	for e in inGraph.edges():
		eType = inGraph.edges[e[0], e[1]].get('type', 'underground_line')
		ePhases = inGraph.edges[e[0], e[1]].get('phases', 1)
		standArgs = {
			'edgelist': [e],
			'edge_color': _obToCol(eType),
			'width': 2,
			'style': edge_styles.get(eType, 'solid')
		}
		if ePhases == 3:
			standArgs.update({'width': 5})
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
			standArgs.update({'width': 3, 'edge_color': 'white'})
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
			standArgs.update({'width': 1, 'edge_color': _obToCol(eType)})
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
		if ePhases == 2:
			standArgs.update({'width': 3})
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
			standArgs.update({'width': 1, 'edge_color': 'white'})
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
		else:
			nx.draw_networkx_edges(inGraph, pos, **standArgs)
	# Draw nodes and optional labels.
	nx.draw_networkx_nodes(
		inGraph,
		pos,
		nodelist=list(pos.keys()),
		node_color=[_obToCol(inGraph.nodes[n].get('type', 'underground_line')) for n in inGraph],
		linewidths=0,
	 	node_size=40
	)
	if labels:
		nx.draw_networkx_labels(
			inGraph,
			pos,
			font_color='black',
			font_weight='bold',
			font_size=0.25
		)
	if showPlot:
		plt.show()


def _tokenizeGlm(inputStr, filePath=True):
	''' Turn a GLM file/string into a linked list of tokens.

	E.g. turn a string like this:
	clock {clockey valley;};
	object house {name myhouse; object ZIPload {inductance bigind; power newpower;}; size 234sqft;}; 

	Into a Python list like this:
	['clock','{','clockey','valley','}','object','house','{','name','myhouse',';',
		'object','ZIPload','{','inductance','bigind',';','power','newpower','}','size','234sqft','}']
	'''
	if filePath:
		with open(inputStr,'r') as glmFile:
			data = glmFile.read()
	else:
		data = inputStr
	# Get rid of http for stylesheets because we don't need it and it conflicts with comment syntax.
	data = re.sub(r'http:\/\/', '', data)  
	# Strip comments.
	data = re.sub(r'\/\/.*\n', '', data)
	# Also strip non-single whitespace because it's only for humans:
	data = data.replace('\n','').replace('\r','').replace('\t',' ')
	# Tokenize around semicolons, braces and whitespace.
	tokenized = re.split(r'(;|\}|\{|\s)',data)
	# Get rid of whitespace strings.
	basicList = [x for x in tokenized if x != '' and x != ' ']
	return basicList


def _parseTokenList(tokenList):
	''' Given a list of tokens from a GLM, parse those into a tree data structure. '''
	def currentLeafAdd(key, value):
		# Helper function to add to the current leaf we're visiting.
		current = tree
		for x in guidStack:
			current = current[x]
		current[key] = value
	def listToString(listIn):
		# Helper function to turn a list of strings into one string with some decent formatting.
		if len(listIn) == 0:
			return ''
		else:
			return reduce(lambda x,y:str(x)+' '+str(y),listIn[1:-1])
	# Tree variables.
	tree = {}
	guid = 0
	guidStack = []
	# Pop off a full token, put it on the tree, rinse, repeat.
	while tokenList != []:
		# Pop, then keep going until we have a full token (i.e. 'object house', not just 'object')
		fullToken = []
		while fullToken == [] or fullToken[-1] not in ['{',';','}']:
			fullToken.append(tokenList.pop(0))
		# Work with what we've collected.
		if fullToken[-1] == ';':
			# Special case when we have zero-attribute items (like #include, #set, module).
			if guidStack == [] and fullToken != [';']:
				tree[guid] = {'omftype':fullToken[0],'argument':listToString(fullToken)}
				guid += 1
			# We process if it isn't the empty token (';')
			elif len(fullToken) > 1:
				currentLeafAdd(fullToken[0],listToString(fullToken))
		elif fullToken[-1] == '}':
			if len(fullToken) > 1:
				currentLeafAdd(fullToken[0],listToString(fullToken))
			try:
				# Need try in case of zero length stack.
				guidStack.pop()
			except:
				pass
		elif fullToken[0] == 'schedule':
			# Special code for those ugly schedule objects:
			while fullToken[-1] not in ['}']:
				fullToken.append(tokenList.pop(0))
			tree[guid] = {'object':'schedule','name':fullToken[1], 'cron':' '.join(fullToken[3:-2])}
			guid += 1
		elif fullToken[0] == 'class':
			# Special code for the weirdo class objects:
			while fullToken[-1] not in ['}']:
				fullToken.append(tokenList.pop(0))
			tree[guid] = {'omftype':'class ' + fullToken[1],'argument':'{\n\t' + ' '.join(fullToken[3:-2]) + ';\n}'}
			guid += 1
		elif fullToken[-1] == '{':
			currentLeafAdd(guid,{})
			guidStack.append(guid)
			guid += 1
			# Wrapping this currentLeafAdd is defensive coding so we don't crash on malformed glms.
			if len(fullToken) > 1:
				# Do we have a clock/object or else an embedded configuration object?
				if len(fullToken) < 4:
					currentLeafAdd(fullToken[0],fullToken[-2])
				else:
					currentLeafAdd('omfEmbeddedConfigObject', fullToken[0] + ' ' + listToString(fullToken))
	return tree


def _gatherKeyValues(inDict, keyToAvoid):
	''' Helper function: put key/value pairs for objects into the format Gridlab needs. '''
	otherKeyValues = ''
	for key in inDict:
		if type(inDict[key]) is dict:
			# WARNING: RECURSION HERE
			otherKeyValues += _dictToString(inDict[key])
		elif key != keyToAvoid:
			if key == 'comment':
				otherKeyValues += (inDict[key] + '\n')
			elif key == 'name' or key == 'parent':
				if len(inDict[key]) <= 62:
					otherKeyValues += ('\t' + key + ' ' + str(inDict[key]) + ';\n')
				else:
					warnings.warn("{:s} argument is longer that 64 characters. Truncating.".format(key), RuntimeWarning)
					otherKeyValues += ('\t' + key + ' ' + str(inDict[key])[0:62] + '; // truncated from {:s}\n'.format(inDict[key]))
			else:
				otherKeyValues += ('\t' + key + ' ' + str(inDict[key]) + ';\n')
	return otherKeyValues


def _dictToString(inDict):
	''' Helper function: given a single dict representing a GLM object, concatenate it into a string. '''
	# Handle the different types of dictionaries that are leafs of the tree root:
	if 'omftype' in inDict:
		return inDict['omftype'] + ' ' + inDict['argument'] + ';'
	elif 'module' in inDict:
		return 'module ' + inDict['module'] + ' {\n' + _gatherKeyValues(inDict, 'module') + '};\n'
	elif 'clock' in inDict:
		## This object has known property order issues writing it out explicitly
		clock_string = 'clock {\n'
		timezone = inDict.get('timezone')
		if timezone is not None:
			clock_string += '\ttimezone ' + timezone + ';\n'
		else:
			warnings.warn('clock object did not have a timezone property', RuntimeWarning)
		clock_string += '\tstarttime ' + inDict['starttime'] + ';\n' + '\tstoptime ' + inDict['stoptime'] + ';\n};\n'
		return clock_string
	elif 'object' in inDict and inDict['object'] == 'schedule':
		return 'schedule ' + inDict['name'] + ' {\n' + inDict['cron'] + '\n};\n'
	elif 'object' in inDict:
		return 'object ' + inDict['object'] + ' {\n' + _gatherKeyValues(inDict, 'object') + '};\n'
	elif 'omfEmbeddedConfigObject' in inDict:
		return inDict['omfEmbeddedConfigObject'] + ' {\n' + _gatherKeyValues(inDict, 'omfEmbeddedConfigObject') + '};\n'
	elif '#include' in inDict:
		return '#include ' + '"' + inDict['#include'] + '"' + '\n'
	elif '#define' in inDict:
		return '#define ' + inDict['#define'] + '\n'
	elif '#set' in inDict:
		return '#set ' + inDict['#set'] + '\n'
	#Following was made to help with gridballast gridlabd functionality, so that frequency player doesn't need to be reopened
	elif 'class' in inDict and inDict['class'] =='player':
		return 'class' + ' ' + inDict['class'] + ' {\n' + '     ' + 'double' + ' ' + inDict['double'] + ';' + '\n};\n'
	# elif 'collector' in inDict and 'group' in inDict and inDict['group'] =='class=ZIPload':
	# 	return 'object' + ' ' + inDict['object'] + ' {\n' + '	' + 'name' + ' ' + 'collector_ZIPloads' + ';'+'\n' +'group' + ' ' + inDict['group']+';'+'\n'+'property' +' '+inDict['property']+';'+'\n'+'interval'+' '+inDict['interval']+';'+'\n'+'file'+' '+inDict['file']+'\n};\n'


def _deEmbedOnce(glmTree):
	''' Take all objects nested inside top-level objects and move them to the top level.
	Note that this function only removes things embedded one level deep. The fullyDeEmbed runs this until
	it can't deEmbed any more. 
	'''
	iterTree = copy.deepcopy(glmTree)
	for x in iterTree:
		for y in iterTree[x]:
			if type(iterTree[x][y]) is dict and 'object' in iterTree[x][y]:
				# set the parent and name attributes:
				glmTree[x][y]['parent'] = glmTree[x]['name']
				if 'name' in glmTree[x][y]:
					pass
				else:
					glmTree[x][y]['name'] = glmTree[x]['name'] + glmTree[x][y]['object'] + str(y)
				# check for key collision, which should technically be impossible:
				if y in glmTree.keys():
					print('KEY COLLISION!')
					z = y
					while z in glmTree.keys():
						z += 1
					# put the embedded object back up in the glmTree:
					glmTree[z] = glmTree[x][y]
				else:
					# put the embedded object back up in the glmTree:
					glmTree[y] = glmTree[x][y]
				# delete the embedded copy:
				del glmTree[x][y]
			if type(iterTree[x][y]) is dict and 'omfEmbeddedConfigObject' in iterTree[x][y]:
				configList = iterTree[x][y]['omfEmbeddedConfigObject'].split()
				# set the name attribute and the parent's reference:
				if 'name' in glmTree[x][y]:
					pass
				else:
					glmTree[x][y]['name'] = glmTree[x]['name'] + configList[2] + str(y)
				glmTree[x][y]['object'] = configList[2]
				glmTree[x][configList[0]] = glmTree[x][y]['name']
				# get rid of the omfEmbeddedConfigObject string:
				del glmTree[x][y]['omfEmbeddedConfigObject']
				# check for key collision, which should technically be impossible BECAUSE Y AND X ARE DIFFERENT INTEGERS IN [1,...,numberOfDicts]:
				if y in glmTree.keys():
					print('KEY COLLISION!')
					z = y
					while z in glmTree.keys():
						z += 1
					# put the embedded object back up in the glmTree:
					glmTree[z] = glmTree[x][y]
				else:
					# put the embedded object back up in the glmTree:
					glmTree[y] = glmTree[x][y]
				# delete the embedded copy:
				del glmTree[x][y]


def _phaseCount(phaseString):
	''' Return number of phases not including neutrals. '''
	return sum([phaseString.lower().count(x) for x in ['a','b','c']])


def _obToCol(obStr):
	''' Graph drawing helper to color by node/edge type. '''
	obToColor = {'node':'gray',
		'house':'#3366FF',
		'load':'#3366FF',
		'ZIPload':'#66CCFF',
		'waterheater':'#66CCFF',
		'triplex_meter':'#FF6600',
		'triplex_node':'#FFCC00',
		'gridNode':'#CC0000',
		'swingNode':'hotpink',
		'parentChild':'gray',
		'underground_line':'black'}
	return obToColor.get(obStr,'black')


def _tests():
	# Parser Test
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	tokens = ['clock','{','clockey','valley','}','object','house','{','name','myhouse',';',
		'object','ZIPload','{','inductance','bigind',';','power','newpower','}','size','234sqft','}']
	obType = type(_parseTokenList(tokens))
	print('Parsed tokens into object of type:', obType)
	assert obType is dict
	# GLM parsing test.
	smsTree = parse(os.path.join(os.path.dirname(__file__), 'static/testFiles/sms.glm'), filePath=True)
	keyLen = len(smsTree.keys())
	print('Parsed a test glm file with', keyLen, 'keys.')
	assert keyLen == 41
	# Recorder Attachment Test
	with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/Olin Barre Geo.omd')) as inFile:
		tree = json.load(inFile)['tree']
	attachRecorders(tree, 'Regulator', 'object', 'regulator')
	attachRecorders(tree, 'Voltage', 'object', 'node')
	print('All the objects after recorder attach: ', set([ob.get('object','') for ob in tree.values()]))
	# Testing The De-Embedding
	with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/13 Node Embedded DO NOT SAVE.omd')) as inFile:
		tree = json.load(inFile)['tree']
	fullyDeEmbed(tree)
	embeddedDicts = 0
	for ob in tree.values():
		for subOb in ob.values():
			if type(subOb) == 'dict':
				embeddedDicts += 1
	print('Number of objects still embedded:', embeddedDicts)
	assert embeddedDicts == 0, 'Some objects failed to disembed.'
	# groupSwingKids test
	with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/13 Node Ref Feeder Flat.omd')) as inFile:
		tree = json.load(inFile)['tree']
	groupSwingKids(tree)
	for ob in tree.values():
		if ob.get('object','') == 'collector':
			print('Swing collector:', ob)
	# Time Adjustment Test
	with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/Simple Market System.omd')) as inFile:
		tree = json.load(inFile)['tree']
	adjustTime(tree, 100, 'hours', '2000-09-01')
	for ob in tree.values():
		if ob.get('object','') in ['recorder','collector']:
			print('Time-adjusted collector:', ob)
	# Graph Test
	with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/Olin Barre Geo.omd')) as inFile:
		tree = json.load(inFile)['tree']
	nxG = treeToNxGraph(tree)
	x = latLonNxGraph(nxG)

	# Contig line merging test
	#with open(os.path.join(os.path.dirname(__file__), 'static/publicFeeders/Olin Barre Geo.omd')) as inFile:
	#	tree = json.load(inFile)['tree']	
	oldsz = len(tree)
	#from omf import distNetViz
	#distNetViz.viz_mem(tree, open_file=True, forceLayout=True)
	mergeContigLines(tree)
	#dump(tree, 'Olin Barre Geo reduced.glm')
	newsz = len(tree)
	print ('Objects removed: %s (of %s). Percent reduction: %s.'%(oldsz, oldsz-newsz, (oldsz-newsz)*100/oldsz))
	

if __name__ == '__main__':
	_tests()
