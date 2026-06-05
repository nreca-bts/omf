"""
The networkStructure model takes in a feeder system and a .csv file containing voltage
data, then compares the actual connectivity of the system to connectivity arrived at by
minimizing distances and difference in voltages between nodes. It can also take in a
list of training data as a .csv file and train a machine learning model to determine
connectivity using support vector machines.
"""
import json, os, tempfile, shutil, csv, math, re, base64
from os.path import join as pJoin
import pandas as pd
import networkx as nx
from sklearn import svm
from sklearn import metrics
from numpy import array
from matplotlib import pyplot as plt
from dateutil.relativedelta import *
import omf
from omf import feeder, geo
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
tooltip = 'networkStructure determines whether connectivity information is correct, given voltage and/or distance information.'
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = True
	
def nodeToCoords(outageMap, nodeName):
	'get the latitude and longitude of a given node in string format'
	coords = ''
	for key in outageMap['features']:
		if (nodeName in key['properties'].get('name','')):
			current = key['geometry']['coordinates']
			p = re.compile(r'-?\d+\.\d+')  # Compile a pattern to capture float values
			coords = [float(i) for i in p.findall(str(current))]
			coord1 = coords[0]
			coord2 = coords[1]
	return coord1, coord2

workDir = None

def generateData(pathToOmd, pathToCsv, workDir, useDist, useVolt):
	'create graphs and associated adjacency matrices based on input voltage and distance data'
	with open(pathToOmd) as f:
		omd = json.load(f)
	tree = omd.get('tree', {})
	attachments = omd.get('attachments',[])

	# check to see if work directory is specified
	if not workDir:
		workDir = tempfile.mkdtemp()
		print('@@@@@@', workDir)

	# create outageMap to get the distance data for the given feeder system and actual connectivity data
	outageMap = geo.omdGeoJson(pathToOmd, conversion = False)

	# create a dataframe that stores the location data of each of the nodes in the feeder system
	if useDist == 'True':
		with open(workDir + '/nodes.csv', 'w', newline='') as nodes:

			fieldnames = ['node_name', 'coord1', 'coord2']
			writer = csv.DictWriter(nodes, fieldnames)
			writer.writeheader()

			for key in tree.keys():
				obtype = tree[key].get('object','')
				if obtype.startswith('node') or obtype.startswith('load') or obtype.startswith('capacitor') or obtype.startswith('meter') or obtype.startswith('triplex_node') or obtype.startswith('triplex_meter'):
					coord1, coord2 = nodeToCoords(outageMap, tree[key]['name'])
					writer.writerow({'node_name': tree[key]['name'], 'coord1': coord1, 'coord2': coord2})
		nodes.close()

	# create a dataframe storing data of which nodes are actually connected according to the .omd file
	with open(workDir + '/connectivity.csv', 'w', newline='') as connectivity:

		fieldnames = ['first_node', 'second_node']
		writer = csv.DictWriter(connectivity, fieldnames)
		writer.writeheader()

		for key in tree.keys():
			obtype = tree[key].get('object','')
			if obtype.startswith('underground_line') or obtype.startswith('overhead_line') or obtype.startswith('triplex_line') or obtype.startswith('switch') or obtype.startswith('recloser') or obtype.startswith('transformer') or obtype.startswith('fuse'):
				if 'from' in tree[key].keys() and 'to' in tree[key].keys():
					writer.writerow({'first_node': tree[key]['from'], 'second_node': tree[key]['to']})
	connectivity.close()

	# read in connectivity data
	connectivity = pd.read_csv(workDir + '/connectivity.csv')

	# HACK: read in location data and remove the nodes that are not listed as being connected to any other nodes based on connectivity data
	# the point of this is to make sure that we are finding a viable MST of the largest subgraph representing the system as possible	
	def deleteBad(mc):
		'helper function which deletes all nodes that are not connected from the input dataframe'
		row = 0
		number_of_nodes = mc.shape[0]
		# create a list of bad nodes, the nodes that aren't connected to the rest of the system
		bad_nodes = []
		while row < number_of_nodes:
			if (not connectivity['first_node'].str.contains(mc.loc[row, 'node_name']).any()) and (not connectivity['second_node'].str.contains(mc.loc[row, 'node_name']).any()):
				bad_nodes.append(mc.loc[row, 'node_name'])
			row += 1

		# delete all bad nodes
		row = 0
		number_of_bad = len(bad_nodes)
		while row < number_of_bad:
			delete_row = mc[mc['node_name']==bad_nodes[row]].index
			mc = mc.drop(delete_row)
			row += 1
		return mc

	if useDist == 'True':
		nodes = pd.read_csv(workDir + '/nodes.csv')
		nodes = deleteBad(nodes)
	
		nodes.dropna()
		# sort the location data in alphabetical order for further abstraction
		nodes = nodes.sort_values('node_name')
		nodes.to_csv(workDir + '/nodes1.csv')
		nodes = pd.read_csv(workDir + '/nodes1.csv')

	# HACK: remove bad nodes from voltage data in a similar method to how they were removed from distance data
	if useVolt == 'True':
		volt = pd.read_csv(pathToCsv)
		volt = deleteBad(volt)

		if useDist == 'True':
			number_of_nodes = nodes.shape[0]
			number_of_volt = volt.shape[0]
			new_volt = []
			entry = 0
			while entry < number_of_nodes:
				row = 0
				while row < number_of_volt:
					if volt.loc[row]['node_name'] == nodes.loc[entry]['node_name']:
						break
					row += 1
				if row == number_of_volt:
					new_volt.append(nodes.loc[entry]['node_name'])
				entry += 1

			row = 0
			while row < len(new_volt):
				volt.loc[volt.shape[0] + row] = [0, new_volt[row], 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
				row += 1

		# sort voltage data alphabetically by node names
		volt = volt.sort_values('node_name')
		volt.to_csv(workDir + '/volt2.csv')
		volt = pd.read_csv(workDir + '/volt2.csv')
	
	if useDist == 'True':
		row_count = nodes.shape[0]
	elif useVolt == 'True':
		row_count = volt.shape[0]
	else: raise ValueError('Either voltage or distance data must be used.')

	# create a dictionary that represents node names in terms of integers
	NodeToInt = {}
	row = 0
	while row < row_count:
		if useDist == 'True':
			name = nodes.loc[row]['node_name']
		else:
			name = volt.loc[row]['node_name']
		NodeToInt[name] = row
		row += 1

	# using NodeToInt, create a 2d list that represents the actual connectivity of the system
	outputData = [[100] * row_count for i in range(row_count)]
	connectivity_count = connectivity.shape[0]
	row = 0
	while row < connectivity_count:
		first = NodeToInt[connectivity.loc[row]['first_node']]
		second = NodeToInt[connectivity.loc[row]['second_node']]
		outputData[first][second] = 1
		outputData[second][first] = 1
		row += 1

	# create 2d lists (representing adjacency matrices) to store distance and voltage difference data between each of the nodes
	inputDataDist = [[0 for x in range(row_count)] for y in range(row_count)]
	inputDataVolt = [[0 for x in range(row_count)] for y in range(row_count)]

	# populate the 2d lists/adjacency matrices
	row = 0
	while row < row_count:
		column = row
		while column < row_count:
			if useDist == 'True':
				dataDist = []
				rowName = str(nodes.loc[row, 'node_name'])
				colName = str(nodes.loc[column, 'node_name'])
			if useVolt == 'True':
				dataVolt = []
				rowName = str(volt.loc[row, 'node_name'])
				colName = str(volt.loc[column, 'node_name'])
			
			# find the distances between the different nodes
			if useDist == 'True':
				if ((nodes.loc[row, 'coord1'] - nodes.loc[column, 'coord1'])**2 + (nodes.loc[row, 'coord2'] - nodes.loc[column, 'coord2'])**2) > 10e-15:
					distance = math.sqrt((nodes.loc[row, 'coord1'] - nodes.loc[column, 'coord1'])**2 + (nodes.loc[row, 'coord2'] - nodes.loc[column, 'coord2'])**2)
				else:
					distance = 0.0
				if distance > 10e-15:
					dataDist.append(distance)
				else:
					dataDist.append(0.0)

			# find the voltage differences (of each phase) between the different nodes
			if useVolt == 'True':
				if (math.sqrt((float(volt.loc[row, 'voltA_real']) - float(volt.loc[column, 'voltA_real']))**2 + (float(volt.loc[row, 'voltA_imag']) - float(volt.loc[column, 'voltA_imag']))**2)) > 0:
					dataVolt.append(math.sqrt((float(volt.loc[row, 'voltA_real']) - float(volt.loc[column, 'voltA_real']))**2 + (float(volt.loc[row, 'voltA_imag']) - float(volt.loc[column, 'voltA_imag']))**2))
				else:
					dataVolt.append(0.0)	
				if (math.sqrt((float(volt.loc[row, 'voltB_real']) - float(volt.loc[column, 'voltB_real']))**2 + (float(volt.loc[row, 'voltB_imag']) - float(volt.loc[column, 'voltB_imag']))**2)) > 0:
					dataVolt.append(math.sqrt((float(volt.loc[row, 'voltB_real']) - float(volt.loc[column, 'voltB_real']))**2 + (float(volt.loc[row, 'voltB_imag']) - float(volt.loc[column, 'voltB_imag']))**2))
				else:
					dataVolt.append(0.0)
				if (math.sqrt((float(volt.loc[row, 'voltC_real']) - float(volt.loc[column, 'voltC_real']))**2 + (float(volt.loc[row, 'voltC_imag']) - float(volt.loc[column, 'voltC_imag']))**2)) > 0:
					dataVolt.append(math.sqrt((float(volt.loc[row, 'voltC_real']) - float(volt.loc[column, 'voltC_real']))**2 + (float(volt.loc[row, 'voltC_imag']) - float(volt.loc[column, 'voltC_imag']))**2))
				else:
					dataVolt.append(0.0)
			
			# sum all the differences for ease of working with the data
			if useVolt == 'True':
				inputDataVolt[row][column] = sum(dataVolt)
				inputDataVolt[column][row] = sum(dataVolt)

			if useDist == 'True':
				inputDataDist[row][column] = sum(dataDist)
				inputDataDist[column][row] = sum(dataDist)
			
			column += 1
		row += 1
	
	if useDist == 'False':
		nodes = None
	if useVolt == 'False':
		volt = None
	
	return nodes, volt, tree, workDir, inputDataDist, inputDataVolt, outputData

def prim(graph):
	'use Prims algorithm to find a MST of a graph'
	# initialize the MST and set V to keep track of vertices
	MST = set()
	V = set()

	# choose a vertex to start
	V.add(0)
	while len(V) != len(graph):
		cross = set()
		for v in V:
			for i in range(len(graph)):
				if i not in V and graph[v][i] != 0.0:
					cross.add((v, i))
		
		# find the edge with smallest crossing weight
		if len(cross) == 0: break
		edge = sorted(cross, key=lambda e:graph[e[0]][e[1]])[0]
		# add the edge found to the MST
		MST.add(edge)
		# add the new vertex to V
		V.add(edge[1])
	return MST

def testingSimple(testPath, pathToCsv, workDir, useDist, useVolt):
	'visualize the different MSTs based on distance data, voltage data, and actual connectivity'

	# generate date
	nodes, volt, tree, workDir, inputDataDist, inputDataVolt, outputData = generateData(testPath, pathToCsv, workDir, useDist, useVolt)
	
	if useDist == 'True':
		size = len(inputDataDist)
	else:
		size = len(inputDataVolt)

	# create lists to store the minimally spanning trees
	distMST = [[0 for x in range(size)] for y in range(size)]
	voltMST = [[0 for x in range(size)] for y in range(size)]
	actualMST = [[0 for x in range(size)] for y in range(size)]

	# use Prim's algorithm to find the MSTs
	expectedDist = prim(inputDataDist)
	expectedVolt = prim(inputDataVolt)
	actual = prim(outputData)

	# populate the adjacency matrices representing the MSTs
	for val in expectedDist:
		distMST[val[0]][val[1]] = 1
	for val in expectedVolt:
		voltMST[val[0]][val[1]] = 1
	for val in actual:
		actualMST[val[0]][val[1]] = 1

	def graph(graphname, mst, referenceMST, tree):
		'create a networkx graph of expected connectivity, given the tree of a .omd file and a MST'
		plt.close('all')
		outGraph = nx.Graph()
		for key in tree:
			item = tree[key]
			if 'name' in item.keys():
				obType = item.get('object')
				reclDevices = dict.fromkeys(['recloser'], False)
				if (obType in reclDevices.keys() and 'addedRecloser' in item.get('name', '')):
					# HACK: set the recloser as a swingNode in order to make it hot pink
					outGraph.add_edge(item['from'],item['to'], attr_dict={'type':'swingNode'})
				elif (obType in reclDevices.keys() and 'addedRecloser' not in item.get('name','')):
					outGraph.add_edge(item['from'],item['to'])
				elif 'parent' in item.keys() and obType not in reclDevices:
					outGraph.add_edge(item['name'],item['parent'], attr_dict={'type':'parentChild','phases':1})
					outGraph.nodes[item['name']]['type']=item['object']
					# Note that attached houses via gridEdit.html won't have lat/lon values, so this try is a workaround.
					try: outGraph.nodes[item['name']]['pos']=(float(item.get('latitude',0)),float(item.get('longitude',0)))
					except: outGraph.nodes[item['name']]['pos']=(0.0,0.0)
				elif 'from' in item.keys():
					myPhase = feeder._phaseCount(item.get('phases','AN'))
					# outGraph.add_edge(item['from'],item['to'],attr_dict={'name':item.get('name',''),'type':item['object'],'phases':myPhase})
				elif item['name'] in outGraph:
					# Edge already led to node's addition, so just set the attributes:
					outGraph.nodes[item['name']]['type']=item['object']
				else:
					outGraph.add_node(item['name'],attr_dict={'type':item['object']})
				if 'latitude' in item.keys() and 'longitude' in item.keys():
					try: outGraph.nodes.get(item['name'],{})['pos']=(float(item['latitude']),float(item['longitude']))
					except: outGraph.nodes.get(item['name'],{})['pos']=(0.0,0.0)
		# populate the graph with edges
		size = len(referenceMST)
		row = 0
		while row < size:
			column = 0
			while column < size:
				if referenceMST[row][column] == 1:
					if useDist == 'True':
						outGraph.add_edge(str(nodes.loc[row,'node_name']),str(nodes.loc[column,'node_name']))
					else:
						outGraph.add_edge(str(volt.loc[row,'node_name']),str(volt.loc[column,'node_name']))
				column += 1
			row += 1
		size = len(mst)
		row = 0
		while row < size:
			column = 0
			while column < size:
				if mst[row][column] == 1:
					if useDist == 'True':
						outGraph.add_edge(str(nodes.loc[row,'node_name']),str(nodes.loc[column,'node_name']), attr_dict={'type':'load'})
					else:
						outGraph.add_edge(str(volt.loc[row,'node_name']),str(volt.loc[column,'node_name']), attr_dict={'type':'load'})
				column += 1
			row += 1
		feeder.latLonNxGraph(outGraph, labels=True, neatoLayout=True, showPlot=False)
		plt.savefig(workDir + graphname)

	# graph the actual, distance, and voltage MSTs
	graph('/actual_graph.png', actualMST, actualMST, tree)
	graph('/distance_graph.png', distMST, actualMST, tree)
	graph('/voltage_graph.png', voltMST, actualMST, tree)

	# initialize lists to store 1d versions of the adjacency matrices (useful for learning with an SVM)
	X_test = []
	xdistMST1D = []
	xvoltMST1D = []
	y_test = []

	# populate 1d lists
	row = 0
	while row < size:
		column = 0
		while column < size:
			mstTemp = []
			mstTemp.append(distMST[row][column])
			mstTemp.append(voltMST[row][column])
			X_test.append(mstTemp)
			xdistMST1D.append(distMST[row][column])
			xvoltMST1D.append(voltMST[row][column])
			y_test.append(actualMST[row][column])
			column += 1
		row += 1
	
	# calculate the accuracy ratings between distance/voltage and actual connectivity data
	# ie what percentage of connectivity was the same
	distanceAccuracy = 1.0 - (abs(float(len(actual.difference(expectedDist)))))/float(len(actual))
	voltageAccuracy = 1.0 - (abs(float(len(actual.difference(expectedVolt)))))/float(len(actual))

	def testRandom(numberOfNodes, accuracy):
		'determine whether (within 5 standard deviations) the connectivity accuracy could have been arrived at randomly'
		nodesCorrect = math.floor(numberOfNodes * accuracy)

		# calculate the probability that the number of correctly-guessed edges in the MST could have been arrived at randomly
		s = lambda numberOfNodes, nodesCorrect : sum(pow(numberOfNodes - i, i) / pow(numberOfNodes, numberOfNodes - 2) for i in range(0, int(numberOfNodes - nodesCorrect)))
		if s(numberOfNodes, nodesCorrect) < 3e-7:
			return True
		return False

	distanceTest = 'Failed'
	voltageTest = 'Failed'

	distanceSigma = testRandom(len(inputDataDist), distanceAccuracy)
	if useDist == 'True':
		if distanceSigma is True:
			distanceTest = 'Passed'

	voltageSigma = testRandom(len(inputDataVolt), voltageAccuracy)
	if useVolt == 'True':
		if voltageSigma is True:
			voltageTest = 'Passed'

	def connectivityHTML(distanceAccuracy, voltageAccuracy, distanceTest, voltageTest):
		html_str = """
			<div style="text-align:center">
				<p style="padding-top:10px; padding-bottom:10px;"><b>Distance Test:</b><span style="padding-left:1em">"""+str(distanceTest)+"""</span><span style="padding-left:2em"><b>Voltage Test:</b><span style="padding-left:1em">"""+str(voltageTest)+"""</span><span style="padding-left:2em"><b>Distance Percent Similar:</b><span style="padding-left:1em">"""+str(int(distanceAccuracy * 100))+"""</span><span style="padding-left:2em"><b>Voltage Percent Similar:</b><span style="padding-left:1em">"""+str(int(voltageAccuracy * 100))+"""</span></span></p>
			</div>"""
		return html_str

	connectivityStats = connectivityHTML(
			distanceAccuracy = distanceAccuracy,
			voltageAccuracy = voltageAccuracy,
			distanceTest = distanceTest,
			voltageTest = voltageTest)

	with open(pJoin(workDir, 'statsCalc.html'), 'w') as statsFile:
		statsFile.write(connectivityStats)

	return {'X_test': X_test, 'y_test': y_test, 'distanceAccuracy': distanceAccuracy, 'distanceSigma': distanceSigma, 'voltageAccuracy': voltageAccuracy, 'voltageSigma': voltageSigma}, X_test, y_test

def createTrainingData(trainPath, pathToCsv, workDir, X_train, y_train, useDist, useVolt):
	'create a new set of training data, or append more data on a pre-existing set'

	# generate data to be used as training data
	nodes, volt, tree, workDir, inputDataDist, inputDataVolt, outputData = generateData(trainPath, pathToCsv, workDir, useDist, useVolt)

	# initialize the training lists, only if no previous data exists
	if X_train == None or y_train == None:
		X_train = []
		y_train = []

	# initialize the adjacency matrices
	size = len(inputDataDist)
	distMST = [[0 for x in range(size)] for y in range(size)]
	voltMST = [[0 for x in range(size)] for y in range(size)]
	actualMST = [[0 for x in range(size)] for y in range(size)]

	# using Prim's algorithm, find MSTs
	expectedDist = prim(inputDataDist)
	expectedVolt = prim(inputDataVolt)
	actual = prim(outputData)

	# put MST data in adjacency matrix form
	for val in expectedDist:
		distMST[val[0]][val[1]] = 1

	for val in expectedVolt:
		voltMST[val[0]][val[1]] = 1

	for val in actual:
		actualMST[val[0]][val[1]] = 1

	# append adjacency matrix data to the training lists
	row = 0
	while row < size:
		column = 0
		while column < size:
			mstTemp = []
			mstTemp.append(distMST[row][column])
			mstTemp.append(voltMST[row][column])
			X_train.append(mstTemp)
			y_train.append(actualMST[row][column])
			column += 1
		row += 1

	return X_train, y_train

def work(modelDir, inputDict):
	# Copy specific climate data into model directory
	"""
	Run the network structure model analysis and return the output data used by the OMF
	interface.
	"""
	outData = {}
	# Write the feeder
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName

	with open(pJoin(modelDir, inputDict['voltageFileName']), 'w') as f:
		pathToData = f.name
		f.write(inputDict['voltageData'])

	with open(pJoin(modelDir, inputDict['trainingFileName']), 'w') as f:
		pathToData1 = f.name
		f.write(inputDict['trainingData'])

	plotOuts, X_test, y_test = testingSimple(
		modelDir + '/' + feederName + '.omd', #OMD Path
		pathToData,
		modelDir, #Work directory.
		inputDict['useDist'], # 'True'
		inputDict['useVolt']) # 'True')

	# if using ML, read in training data and perform learning with SVM
	if inputDict['useSVM'] == 'True':
		mc = pd.read_csv(pathToData1)
		row_count_mc = mc.shape[0]
		row = 0
		X_train = None
		y_train = None
		while row < row_count_mc:
			X_train, y_train = createTrainingData(omf.omfDir + str(mc.loc[row]['omd_path']), omf.omfDir + str(mc.loc[row]['csv_path']), modelDir, X_train, y_train, inputDict['useDist'], inputDict['useVolt'])
			row += 1

		# turn data in numpy arrays
		X_train = array(X_train)
		y_train = array(y_train)
		X_test = array(X_test)
		y_test = array(y_test)

		# learn on data using an SVM
		clf = svm.SVC(kernel='sigmoid')

		clf.fit(X_train, y_train)

		y_pred = clf.predict(X_test)

		accuracy = metrics.accuracy_score(y_test, y_pred)
		precision = metrics.precision_score(y_test, y_pred)
		recall = metrics.recall_score(y_test, y_pred)

		def statsHTML(accuracy, precision, recall):
			html_str = """
				<div style="text-align:center">
					<p style="padding-top:10px; padding-bottom:10px;"><b>Accuracy:</b><span style="padding-left:1em">"""+str(accuracy)+"""</span><span style="padding-left:2em"><b>Precision:</b><span style="padding-left:1em">"""+str(precision)+"""</span><span style="padding-left:2em"><b>Recall:</b><span style="padding-left:1em">"""+str(recall)+"""</span></span></p>
				</div>"""
			return html_str

		svmStats = statsHTML(
				accuracy = accuracy,
				precision = precision,
				recall = recall)

		with open(pJoin(modelDir, 'svmCalc.html'), 'w') as statsFile:
			statsFile.write(svmStats)

	# Image outputs.
	with open(pJoin(modelDir,'distance_graph.png'),'rb') as inFile:
		outData['distance_graph.png'] = base64.standard_b64encode(inFile.read()).decode('ascii')
	with open(pJoin(modelDir,'voltage_graph.png'),'rb') as inFile:
		outData['voltage_graph.png'] = base64.standard_b64encode(inFile.read()).decode('ascii')
	with open(pJoin(modelDir,'actual_graph.png'),'rb') as inFile:
		outData['actual_graph.png'] = base64.standard_b64encode(inFile.read()).decode('ascii')

	# Textual outputs of cost statistic
	with open(pJoin(modelDir,'statsCalc.html'),'rb') as inFile:
		outData['statsCalc'] = inFile.read().decode()
	with open(pJoin(modelDir,'svmCalc.html'),'rb') as inFile:
		outData['svmCalc'] = inFile.read().decode()

	# Stdout/stderr.
	outData['stdout'] = 'Success'
	outData['stderr'] = ''
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','smartswitch_volt1.csv')) as f:
		voltage_data = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','smartswitch_training.csv')) as f:
		training_data = f.read()
	defaultInputs = {
		'modelType': modelName,
		'feederName1': 'ieee37nodeFaultTester',
		'useDist': 'True',
		'useVolt': 'True',
		'useSVM': 'True',
		'voltageFileName': 'volt1.csv',
		'voltageData': voltage_data,
		'trainingFileName': 'training.csv',
		'trainingData': training_data,
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
