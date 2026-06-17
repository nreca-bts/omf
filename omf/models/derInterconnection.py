"""
The Distributed Energy Resource (DER) Interconnection model carries out the key
modelling and analysis steps involved in a DER impact study including Load Flow
computations, Short Circuit Analysis, and Effective Grounding Screenings. This analysis
is presented in a static point-of-view of a 24hr simulation period, and not as a time
series analysis.
"""
import glob, json, os, tempfile, shutil, csv, math, random, copy, base64
from os.path import join as pJoin
import networkx as nx
import matplotlib
from matplotlib import pyplot as plt
from dateutil import parser
from dateutil.relativedelta import *
from omf import feeder
from omf.solvers import gridlabd
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = ('The derInterconnection model runs the key modelling and analysis steps involved '
	'in a DER Impact Study including Load Flow computations, Short Circuit analysis, '
	'and Effective Grounding screenings.')
#hidden = True

def work(modelDir, inputDict):
	''' Run the model in its directory. '''
	
	outData = {}

	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName
	
	with open(pJoin(modelDir,feederName + '.omd')) as f:
		omd = json.load(f)
	if inputDict.get('layoutAlgorithm', 'geospatial') == 'geospatial':
		neato = False
	else:
		neato = True 

	path = pJoin(modelDir,feederName + '.omd')
	if path.endswith('.glm'):
		tree = feeder.parse(path)
		attachments = []
	elif path.endswith('.omd'):
		with open(path) as f:
			omd = json.load(f)
		tree = omd.get('tree', {})
		attachments = omd.get('attachments',[])
	else:
		raise Exception('Invalid input file type. We require a .glm or .omd.')
	
	# dictionary to hold info on lines present in glm
	edge_bools = dict.fromkeys(['underground_line','overhead_line','triplex_line','transformer','regulator', 'fuse', 'switch'], False)
	# Get rid of schedules and climate and check for all edge types:
	for key in list(tree.keys()):
		obtype = tree[key].get('object','')
		if obtype == 'underground_line':
			edge_bools['underground_line'] = True
		elif obtype == 'overhead_line':
			edge_bools['overhead_line'] = True
		elif obtype == 'triplex_line':
			edge_bools['triplex_line'] = True
		elif obtype == 'transformer':
			edge_bools['transformer'] = True
		elif obtype == 'regulator':
			edge_bools['regulator'] = True
		elif obtype == 'fuse':
			edge_bools['fuse'] = True
		elif obtype == 'switch':
			edge_bools['switch'] = True
		if tree[key].get('argument','') == '\"schedules.glm\"' or tree[key].get('tmyfile','') != '':
			del tree[key]

	# print edge_bools
			
	# Make sure we have a voltDump:
	def safeInt(x):
		try: return int(x)
		except: return 0
	biggestKey = max([safeInt(x) for x in tree.keys()])
	tree[str(biggestKey*10)] = {'object':'voltdump','filename':'voltDump.csv'}
	tree[str(biggestKey*10 + 1)] = {'object':'currdump','filename':'currDump.csv'}
	
	# Line rating dumps
	tree[feeder.getMaxKey(tree) + 1] = {'module': 'tape'}
	for key in edge_bools.keys():
		if edge_bools[key]:
			tree[feeder.getMaxKey(tree) + 1] = {
				'object':'group_recorder', 
				'group':'"class='+key+'"',
				'limit':1000,
				'property':'continuous_rating',
				'file':key+'_cont_rating.csv'
			}

	if edge_bools['regulator']:
		tree[feeder.getMaxKey(tree) + 1] = {
			'object':'group_recorder', 
			'group':'"class=regulator"',
			'limit':1000,
			'property':'tap_A',
			'file':'tap_A.csv',
			'interval':0
		}

		tree[feeder.getMaxKey(tree) + 1] = {
			'object':'group_recorder', 
			'group':'"class=regulator"',
			'limit':1000,
			'property':'tap_B',
			'file':'tap_B.csv',
			'interval':0
		}

		tree[feeder.getMaxKey(tree) + 1] = {
			'object':'group_recorder', 
			'group':'"class=regulator"',
			'limit':1000,
			'property':'tap_C',
			'file':'tap_C.csv',
			'interval':0
		}

		tree[feeder.getMaxKey(tree) + 1] = {
			'object':'group_recorder', 
			'group':'"class=regulator"',
			'limit':1000,
			'property':'flow_direction',
			'file':'regulatorFlowDirection.csv',
			'interval':0
		}

	# get start and stop time for the simulation
	[startTime,stopTime] = ['','']
	for key in tree.keys():
		obname = tree[key].get('object','')
		starttime = tree[key].get('starttime','')
		stoptime = tree[key].get('stoptime','')
		if starttime!='' and stoptime!='':
			startTime = tree[key]['starttime']
			stopTime = tree[key]['stoptime']
			break	

	# gridlabd complains if sim and fault start at the same time so
	# add 1 sec to the fault start
	faultStartTime = parser.parse(starttime)
	faultStartTime = faultStartTime + relativedelta(seconds=+1)
	faultStartTime = str(faultStartTime)		

	# Map to speed up name lookups.
	nameToIndex = {tree[key].get('name',''):key for key in tree.keys()}
	
	# find the key of the relavant added DER components  
	addedDerKey = nameToIndex[inputDict['newGeneration']]
	addedDerInverterKey = nameToIndex[tree[addedDerKey]['parent']]
	addedBreakKey = nameToIndex[inputDict['newGenerationBreaker']]
	poi = tree[addedBreakKey]['to']

	# set solar generation to provided insolation value
	insolation = float(inputDict['newGenerationInsolation'])
	if insolation > 1000:
		insolation = 1000
	elif insolation < 0:
		insolation = 0
	# cant set insolation directly but without climate object it defaults to 1000
	# whilch is about 10x max sun output and we can set shading factor between 0 and 1
	# to effectively control insolation
	tree[addedDerKey]['shading_factor'] = insolation/1000
	
	# initialize variables
	flickerViolations = []
	flickerThreshold = float(inputDict['flickerThreshold'])
	voltageViolations = []
	[upperVoltThresh, lowerVoltThresh, lowerVoltThresh600] = [1.05,0.95,0.975]
	thermalViolations = []
	thermalThreshold = float(inputDict['thermalThreshold'])/100
	reversePowerFlow = []
	tapViolations = []
	tapThreshold = float(inputDict['tapThreshold'])
	faults = ['SLG-A','SLG-B','SLG-C','TLG']
	faultLocs = [inputDict['newGenerationBreaker']]
	faultBreaker = [[] for i in range(2*len(faults))] # the 2 is for the 2 load conditions
	faultStepUp = [[] for i in range(2*len(faults))]
	faultCurrentViolations = []
	faultCurrentThreshold = float(inputDict['faultCurrentThreshold'])
	faultPOIVolts = []
	faultVoltsThreshold = float(inputDict['faultVoltsThreshold'])

	# run analysis for both load conditions
	count = 0
	for loadCondition in ['Peak', 'Min']:

		# if a peak load file is provided, use it to set peak loads in the tree
		if (loadCondition == 'Peak') and (inputDict['peakLoadData'] != ''):
			peakLoadData = inputDict['peakLoadData'].split('\r\n')
			for data in peakLoadData:
				if str(data) != '':
					key = data.split(',')[0]
					val = data.split(',')[1]
					tree[key]['power_12'] = val
		
		elif (loadCondition == 'Min'):
			# if a min load file is provided use is to set the min loads
			if inputDict['minLoadData'] != '':
				minLoadData = inputDict['minLoadData'].split('\r\n')
				for data in minLoadData:
					if str(data) != '':
						key = data.split(',')[0]
						val = data.split(',')[1]
						tree[key]['power_12'] = val
		
			else: # if no min load file is provided set min load to be 1/3 of peak + noise				
				for key in tree.keys():
					obtype = tree[key].get('object','')
					if obtype == 'triplex_node':
						load = tree[key].get('power_12','')
						if load != '':
							load = float(load)
							minLoad = (load/3)+(load*0.1*random.triangular(-1,1))
							tree[key]['power_12'] = str(minLoad)

		# initialize variables
		flicker = {}
		[maxFlickerLocation, maxFlickerVal] = ['',0]

		# run analysis with DER on and off under both load conditions
		for der in ['On', 'Off']:


			# if der is Off set added DER offline, if its On set DER online
			if der == 'Off':
				tree[addedDerKey]['generator_status'] = 'OFFLINE'
				tree[addedDerInverterKey]['generator_status'] = 'OFFLINE'
			else: # der is on 
				tree[addedDerKey]['generator_status'] = 'ONLINE'
				tree[addedDerInverterKey]['generator_status'] = 'ONLINE'

			# run gridlab solver
			count += 1
			print('run num', count, 'der', der, 'load', loadCondition)
			data = runGridlabAndProcessData(tree, attachments, edge_bools, workDir=modelDir)
			# print(tree[addedDerKey]);
			# print(tree[addedDerInverterKey]);

			# generate voltage, current and thermal plots
			filename = 'voltageDer' + der + loadCondition
			chart = drawPlot(tree,nodeDict=data['percentChangeVolts'], neatoLayout=neato, nodeFlagBounds=[114, 126], defaultNodeVal=120)
			chart.savefig(pJoin(modelDir, filename + 'Chart.png'))
			with open(pJoin(modelDir,filename + 'Chart.png'),'rb') as inFile:
				outData[filename] = base64.standard_b64encode(inFile.read()).decode('ascii')

			filename = 'currentDer' + der + loadCondition
			chart = drawPlot(tree,nodeDict=data['edgeCurrentSum'], neatoLayout=neato)
			chart.savefig(pJoin(modelDir, filename + 'Chart.png'))
			with open(pJoin(modelDir,filename + 'Chart.png'),'rb') as inFile:
				outData[filename] = base64.standard_b64encode(inFile.read()).decode('ascii')

			filename = 'thermalDer' + der + loadCondition
			chart = drawPlot(tree,nodeDict=data['edgeValsPU'], neatoLayout=neato)
			chart.savefig(pJoin(modelDir, filename + 'Chart.png'))
			with open(pJoin(modelDir,filename + 'Chart.png'),'rb') as inFile:
				outData[filename] = base64.standard_b64encode(inFile.read()).decode('ascii')


			# calculate max and min voltage and track badwidth violations
			[maxVoltsLocation, maxVoltsVal] = ['',0]
			[minVoltsLocation, minVoltsVal] = ['',float('inf')]
			for key in data['nodeVolts'].keys():
				
				voltVal = float(data['nodeVolts'][key])
				nominalVoltVal = float(data['nominalVolts'][key])
				
				if maxVoltsVal <= voltVal:
					maxVoltsVal = voltVal
					maxVoltsLocation = key
				if minVoltsVal >= voltVal:
					minVoltsVal = voltVal
					minVoltsLocation = key

				change = 100*((voltVal-nominalVoltVal)/nominalVoltVal)
				if nominalVoltVal > 600:
					violation = (voltVal >= (upperVoltThresh*nominalVoltVal)) or \
						(voltVal <= (lowerVoltThresh600*nominalVoltVal))
				else:
					violation = (voltVal >= (upperVoltThresh*nominalVoltVal)) or \
						(voltVal <= (lowerVoltThresh*nominalVoltVal))
				content = [key, nominalVoltVal, voltVal, change, \
					loadCondition +' Load, DER ' + der,violation]
				voltageViolations.append(content)

			outData['maxVolts'+loadCondition+'Der'+der] = [maxVoltsLocation, maxVoltsVal]
			outData['minVolts'+loadCondition+'Der'+der] = [minVoltsLocation, minVoltsVal]

			# check for thermal violations
			for key in data['edgeValsPU'].keys():
				thermalVal = float(data['edgeValsPU'][key])
				content = [key, 100*thermalVal,\
					loadCondition+' Load, DER '+der,(thermalVal>=thermalThreshold)]
				thermalViolations.append(content)

			if edge_bools['regulator']:
				# check for reverse regulator powerflow
				for key in data['regulatorFlowDirection']:
					directions = data['regulatorFlowDirection'][key].split('|')
					reverseFlow = ('AR' in directions) or \
						('BR' in directions) or ('CR' in directions)
					powerVal = float(data['edgePower'][key])
					content = [key, powerVal,\
						loadCondition+' Load, DER '+der,reverseFlow]
					reversePowerFlow.append(content)

				# check for tap_position values and violations
				if der == 'On':
					tapPositions = copy.deepcopy(data['tapPositions'])
				else: # der off
					for tapType in ['tapA','tapB','tapC']:
						for key in tapPositions[tapType].keys():
							# calculate tapPositions
							tapDerOn = int(tapPositions[tapType][key])
							tapDerOff = int(data['tapPositions'][tapType][key])
							tapDifference = abs(tapDerOn-tapDerOff)
							# check for violations
							content = [loadCondition, key+' '+tapType, tapDerOn, \
								tapDerOff,tapDifference, (tapDifference>=tapThreshold)]
							tapViolations.append(content)

			#induce faults and measure fault currents
			for faultLocation in faultLocs:
				for faultNum, faultType in enumerate(faults):
					faultIndex = faultNum
					if loadCondition == 'Min':
						faultIndex = faultNum + len(faults)

					treeCopy =  createTreeWithFault( tree, \
						faultType, faultLocation, faultStartTime, stopTime )
					count += 1
					print('run num', count, 'der', der, 'load', loadCondition, \
						'fault Location', faultLocation, 'type', faultType, )
					faultData = runGridlabAndProcessData(treeCopy, attachments, \
						edge_bools, workDir=modelDir)
					faultVolts = faultData['nodeVolts']
					faultCurrents = faultData['edgeCurrentSum']

					# the fault is at the breaker
					if faultLocation == inputDict['newGenerationBreaker']:

						if der == 'On':
						
							# get fault current values at the breaker
							faultBreaker[faultIndex] = [loadCondition, faultType]
							faultBreaker[faultIndex].append(\
								float(faultCurrents[inputDict['newGenerationBreaker']]))
						
							# get fault current values at the transformer
							faultStepUp[faultIndex] = [loadCondition, faultType]
							faultStepUp[faultIndex].append(\
								float(faultCurrents[inputDict['newGenerationStepUp']]))
						
						else: #der off

							# get fault current values at the breaker
							faultBreaker[faultIndex].append(\
								float(faultCurrents[inputDict['newGenerationBreaker']]))
							faultBreaker[faultIndex].append(\
								faultBreaker[faultIndex][2] - \
								faultBreaker[faultIndex][3])

							# get fault current values at the transformer
							faultStepUp[faultIndex].append(\
								float(faultCurrents[inputDict[\
									'newGenerationStepUp']]))
							faultStepUp[faultIndex].append(\
								faultStepUp[faultIndex][2] - \
								faultStepUp[faultIndex][3])
						
						# get fault voltage values at POI
						preFaultval = data['nodeVolts'][poi]
						postFaultVal = faultVolts[poi]
						percentChange = 100*(postFaultVal/preFaultval)
						faultPOIVolts.append(['Der '+ der + ' ' + \
							loadCondition + ' Load', poi, faultType, preFaultval,\
								postFaultVal, percentChange, \
								(percentChange>=faultVoltsThreshold)])

					# get fault violations when der is on
					if der == 'On':
						for key in faultCurrents.keys():
							preFaultval = float(data['edgeCurrentSum'][key])
							postFaultVal = float(faultCurrents[key])
							difference = abs(preFaultval-postFaultVal)
							if preFaultval == 0:
								percentChange = 0
							else:
								percentChange = 100*(difference/preFaultval)

							content = [loadCondition, faultLocation, faultType, key, \
								preFaultval, postFaultVal, percentChange, \
								(percentChange>=faultCurrentThreshold)]
							faultCurrentViolations.append(content)

			# calculate flicker, keep track of max, and violations
			if der == 'On':
				flicker = copy.deepcopy(data['nodeVolts'])
			else: # der off
				for key in flicker.keys():
					# calculate flicker
					derOn = float(flicker[key])
					derOff = float(data['nodeVolts'][key])
					flickerVal = 100*(1-(derOff/derOn))
					flicker[key] = flickerVal
					# check for max
					if maxFlickerVal <= flickerVal:
						maxFlickerVal = flickerVal
						maxFlickerLocation = key
					# check for violations
					content = [key, flickerVal,loadCondition+' Load',\
					(flickerVal>=flickerThreshold)]
					flickerViolations.append(content)

		# plot flicker
		filename = 'flicker' + loadCondition
		chart = drawPlot(tree,nodeDict=flicker, neatoLayout=neato)
		chart.savefig(pJoin(modelDir,filename + 'Chart.png'))
		with open(pJoin(modelDir,filename + 'Chart.png'),"rb") as inFile:
			outData[filename] = base64.standard_b64encode(inFile.read()).decode('ascii')

		# save max flicker info to output dictionary
		outData['maxFlicker'+loadCondition] = [maxFlickerLocation, maxFlickerVal]

	outData['voltageViolations'] = voltageViolations
	outData['flickerViolations'] = flickerViolations
	outData['thermalViolations'] = thermalViolations
	outData['reversePowerFlow'] = reversePowerFlow	
	outData['tapViolations'] = tapViolations
	outData['faultBreaker']	 = faultBreaker
	outData['faultStepUp'] = faultStepUp
	outData['faultCurrentViolations'] = faultCurrentViolations
	outData['faultPOIVolts'] = faultPOIVolts
	
	plt.close('all')
	return outData

def createTreeWithFault( tree, faultType, faultLocation, startTime, stopTime ):
	
	"""
	Create the tree with fault structure used by this workflow.
	"""
	treeCopy = copy.deepcopy(tree)

	# HACK: set groupid for all meters so outage stats are collected.
	noMeters = True
	for key in treeCopy:
		if treeCopy[key].get('object','') in ['meter', 'triplex_meter']:
			treeCopy[key]['groupid'] = "METERTEST"
			noMeters = False
	if noMeters:
		raise Exception("No meters detected on the circuit. \
			Please add at least one meter to allow for collection of outage statistics.")

	treeCopy[feeder.getMaxKey(treeCopy) + 1] = {
		'module': 'reliability ',
		'maximum_event_length': '300 s',
		'report_event_log': 'TRUE'
	}

	faultType = '"'+faultType+'"'
	outageParams = '"'+faultLocation+','+startTime.replace('\'','') + \
		','+stopTime.replace('\'','')+'"'
	treeCopy[feeder.getMaxKey(treeCopy) + 1] = {
		'object': 'eventgen',
		'name': 'ManualEventGen',
		'parent': 'RelMetrics',
		'fault_type': faultType,
		'manual_outages': str(outageParams)
	}

	treeCopy[feeder.getMaxKey(treeCopy) + 1] = {
		'object': 'fault_check ',
		'name': 'test_fault',
		'check_mode': 'ONCHANGE',
		'eventgen_object': 'ManualEventGen',
		'output_filename': 'Fault_check_out.txt'
	}

	treeCopy[feeder.getMaxKey(treeCopy) + 1] = {
		'object': 'metrics',
		'name': 'RelMetrics',
		'report_file': 'Metrics_Output.csv',
		'module_metrics_object': 'PwrMetrics',
		'metrics_of_interest': '"SAIFI,SAIDI,CAIDI,ASAI,MAIFI"',
		'customer_group': '"groupid=METERTEST"',
		'metric_interval': '5 h',
		'report_interval': '5 h'
	}
	
	treeCopy[feeder.getMaxKey(treeCopy) + 1] = {
		'object': 'power_metrics',
		'name': 'PwrMetrics',
		'base_time_value': '1 h'
	}

	return treeCopy

def readGroupRecorderCSV( filename ):

	"""
	Read the group recorder csv data and normalize it for this workflow.
	"""
	dataDictionary = {}
	with open(filename, newline='') as csvFile:
		reader = csv.reader(csvFile)
		# loop past the header, 
		[keys,vals] = [[],[]]
		for row in reader:
			if '# timestamp' in row:
				keys = row
				i = keys.index('# timestamp')
				keys.pop(i)
				vals = next(reader)
				vals.pop(i)
		for pos,key in enumerate(keys):
			dataDictionary[key] = vals[pos]
			
	return dataDictionary	

def runGridlabAndProcessData(tree, attachments, edge_bools, workDir=False):
	
	# Run Gridlab.
	"""
	Run the gridlab and process data workflow and return its results.
	"""
	if not workDir:
		workDir = tempfile.mkdtemp()
	else:
		# print(workDir)
		folderContents = glob.glob(workDir+'/*')
		for item in folderContents:
			if (item[-3:] != 'omd') and (item[-4:] != 'json'):
				# os.remove(item)
				pass

	gridlabOut = gridlabd.runInFilesystem(tree, attachments=attachments, workDir=workDir)

	if os.stat(workDir+'/stderr.txt').st_size > 40:
		print('failed with stderr.txt size', os.stat(workDir+'/stderr.txt').st_size)
		print('--------------------------------------')
		print(gridlabOut['stderr'])
		print('--------------------------------------')
		
	else:
		print('passed with stderr.txt size', os.stat(workDir+'/stderr.txt').st_size)

	# read voltDump values into a dictionary.
	try:
		with open(pJoin(workDir,'voltDump.csv'), newline='') as dumpFile:
			reader = csv.reader(dumpFile)
			next(reader) # Burn the header.
			keys = next(reader)
			voltTable = []
			for row in reader:
				rowDict = {}
				for pos,key in enumerate(keys):
					rowDict[key] = row[pos]
				voltTable.append(rowDict)
	except:
		raise Exception('GridLAB-D failed to run with the following errors:\n' + gridlabOut['stderr'])

	# read currDump values into a dictionary
	with open(pJoin(workDir,'currDump.csv'), newline='') as currDumpFile:
		reader = csv.reader(currDumpFile)
		next(reader) # Burn the header.
		keys = next(reader)
		currTable = []
		for row in reader:
			rowDict = {}
			for pos,key in enumerate(keys):
				rowDict[key] = row[pos]
			currTable.append(rowDict)

	# read line rating values into a single dictionary
	lineRatings = {}
	for key1 in edge_bools.keys():
		if edge_bools[key1]:		
			with open(pJoin(workDir,key1+'_cont_rating.csv'), newline='') as ratingFile:
				reader = csv.reader(ratingFile)
				keys = []
				vals = []
				for row in reader:
					if '# timestamp' in row:
						keys = row
						i = keys.index('# timestamp')
						keys.pop(i)
						vals = next(reader)
						vals.pop(i)
				for pos,key2 in enumerate(keys):
					lineRatings[key2] = abs(float(vals[pos]))				

	# Calculate average node voltage deviation. First, helper functions.
	def digits(x):
		''' Returns number of digits before the decimal in the float x. '''
		return math.ceil(math.log10(x+1))
	def avg(l):
		''' Average of a list of ints or floats. '''
		if len(l) == 0:
			return 0
		return sum(l)/len(l)
	
	# Tot it all up.
	nodeVolts = {}
	for row in voltTable:
		allVolts = []
		for phase in ['A','B','C']:
			realVolt = abs(float(row['volt'+phase+'_real']))
			imagVolt = abs(float(row['volt'+phase+'_imag']))
			phaseVolt = math.sqrt((realVolt ** 2) + (imagVolt ** 2))
			if phaseVolt != 0.0:
				allVolts.append(phaseVolt)
		avgVolts = avg(allVolts)
		nodeVolts[row.get('node_name','')] = float("{0:.2f}".format(avgVolts))
		
	
	nominalVolts = {}
	percentChangeVolts = {}
	for key in nodeVolts.keys():
		for treeKey in tree:
			ob = tree[treeKey]
			obName = ob.get('name','')
			if obName==key:
				nominalVolts[key] = float(ob.get('nominal_voltage',1))
				percentChangeVolts[key] = (nodeVolts[key] / nominalVolts[key]) * 120

	# find edge currents by parsing currdump
	edgeCurrentSum = {}
	edgeCurrentMax = {}
	for row in currTable:
		allCurr = []
		for phase in ['A','B','C']:
			realCurr = abs(float(row['curr'+phase+'_real']))
			imagCurr = abs(float(row['curr'+phase+'_imag']))
			phaseCurr = math.sqrt((realCurr ** 2) + (imagCurr ** 2))
			allCurr.append(phaseCurr)
		edgeCurrentSum[row.get('link_name','')] = sum(allCurr)
		edgeCurrentMax[row.get('link_name','')] = max(allCurr)
	# When just showing current as labels, use sum of the three lines' current values, when showing the per unit values (current/rating), use the max of the three
	

	#edgeValsPU = current values normalized per unit by line ratings
	edgeValsPU = {}
	edgePower = {}

	for edge in edgeCurrentSum:
		for obj in tree.values():
			obname = obj.get('name','').replace('"','')
			if obname == edge:
				nodeFrom = obj.get('from')
				nodeTo = obj.get('to')
				currVal = edgeCurrentSum.get(edge)
				voltVal = avg([nodeVolts.get(nodeFrom), nodeVolts.get(nodeTo)])
				lineRatings[edge] = lineRatings.get(edge, 10.0**9)
				edgePerUnitVal = (edgeCurrentMax.get(edge))/lineRatings[edge]
				edgeValsPU[edge] = edgePerUnitVal
				edgePower[edge] = ((currVal * voltVal)/1000)

	tapPositions = {}
	regulatorFlowDirection = {}
	if edge_bools['regulator']:
		
		# read regulator tap position values values into a single dictionary
		tapPositions['tapA'] = readGroupRecorderCSV(pJoin(workDir,'tap_A.csv'))
		tapPositions['tapB'] = readGroupRecorderCSV(pJoin(workDir,'tap_B.csv'))
		tapPositions['tapC'] = readGroupRecorderCSV(pJoin(workDir,'tap_C.csv'))
		
		# read regulator flow direction values into a single dictionary
		regulatorFlowDirection = readGroupRecorderCSV(pJoin(workDir,'regulatorFlowDirection.csv'))


	return {'nominalVolts':nominalVolts, 'nodeVolts':nodeVolts, 'percentChangeVolts':percentChangeVolts, 
	'edgeCurrentSum':edgeCurrentSum, 'edgePower':edgePower, 'edgeValsPU':edgeValsPU, 'tapPositions':tapPositions,
	'regulatorFlowDirection': regulatorFlowDirection }

def drawPlot(tree, nodeDict=None, edgeDict=None, edgeLabsDict=None, displayLabs=False, customColormap=False, 
	perUnitScale=False, rezSqIn=400, neatoLayout=False, nodeFlagBounds=[-float('inf'), float('inf')], defaultNodeVal=1):
	''' Draw a color-coded map of the voltage drop on a feeder.
	path is the full path to the GridLAB-D .glm file or OMF .omd file.
	workDir is where GridLAB-D will run, if it's None then a temp dir is used.
	neatoLayout=True means the circuit is displayed using a force-layout approach.
	edgeLabs property must be either 'Name', 'Current', 'Power', 'Rating', 'PercentOfRating', or None
	nodeLabs property must be either 'Name', 'Voltage', 'VoltageImbalance', or None
	edgeCol and nodeCol can be set to false to avoid coloring edges or nodes
	customColormap=True means use a one that is nicely scaled to perunit values highlighting extremes.
	Returns a matplotlib object.'''
	# Be quiet matplotlib:
	# warnings.filterwarnings('ignore')

	# Build the graph.
	fGraph = feeder.treeToNxGraph(tree)
	# TODO: consider whether we can set figsize dynamically.
	wlVal = int(math.sqrt(float(rezSqIn)))

	chart = plt.figure(figsize=(wlVal, wlVal))
	plt.axes(frameon = 0)
	plt.axis('off')
	chart.gca().set_aspect('equal')
	plt.tight_layout()

	# Need to get edge names from pairs of connected node names.
	edgeNames = []
	for e in fGraph.edges():
		edgeNames.append((fGraph.edges[e].get('name','BLANK')).replace('"',''))
	
	#set axes step equal
	if neatoLayout:
		# HACK: work on a new graph without attributes because graphViz tries to read attrs.
		cleanG = nx.Graph(fGraph.edges())
		cleanG.add_nodes_from(fGraph)
		# positions = graphviz_layout(cleanG, prog='neato')
		positions = nx.kamada_kawai_layout(cleanG)
		positions = {k:(1000 * positions[k][0],1000 * positions[k][1]) for k in positions} # get out of array notation
	else:
		positions = {n:fGraph.nodes[n].get('pos',(0,0))[::-1] for n in fGraph}
	
	#create custom colormap
	if customColormap:
		custom_cm = matplotlib.colors.LinearSegmentedColormap.from_list('custColMap',[(0.0,'blue'),(0.15,'darkgray'),(0.7,'darkgray'),(1.0,'red')])
		custom_cm.set_under(color='black')
	else:
		custom_cm = plt.colormaps.get_cmap('viridis')
	
	drawColorbar = False
	emptyColors = {}
	
	#draw edges with or without colors
	if edgeDict != None:
		drawColorbar = True
		edgeList = [edgeDict.get(n,1) for n in edgeNames]
	else:
		edgeList = [emptyColors.get(n,.6) for n in edgeNames]

	edgeIm = nx.draw_networkx_edges(fGraph,
		pos = positions,
		edge_color = edgeList,
		width = 1,
		edge_cmap = custom_cm)

	#draw edge labels
	if displayLabs:
		edgeLabelsIm = nx.draw_networkx_edge_labels(fGraph,
			pos = positions,
			edge_labels = edgeLabsDict,
			font_size = 8)

	# draw nodes with or without color
	if nodeDict != None:
		nodeList = [nodeDict.get(n,defaultNodeVal) for n in fGraph.nodes()]
		drawColorbar = True
	else:
		nodeList = [emptyColors.get(n,.6) for n in fGraph.nodes()]
	
	if perUnitScale:
		vmin = 0
		vmax = 1.25
	else:
		vmin = None
		vmax = None

	edgecolors = ['None'] * len(nodeList)
	for i in range(len(nodeList)):
		if nodeList[i] < nodeFlagBounds[0]:
			edgecolors[i] = '#ffa500'
		if nodeList[i] > nodeFlagBounds[1]:
			edgecolors[i] = 'r'
	nodeIm = nx.draw_networkx_nodes(fGraph,
		pos = positions,
		node_color = nodeList,
		edgecolors = edgecolors,
		linewidths = 2,
		node_size = 30,
		vmin = vmin,
		vmax = vmax,
		cmap = custom_cm)

	#draw node labels
	if displayLabs and nodeDict != None:
		nodeLabelsIm = nx.draw_networkx_labels(fGraph,
			pos = positions,
			labels = nodeDict,
			font_size = 8)
	
	plt.sci(nodeIm)
	# plt.clim(110,130)
	if drawColorbar:
		plt.colorbar()
	return chart

def glmToModel(glmPath, modelDir):
	''' One shot model creation from glm. '''
	tree = feeder.parse(glmPath)
	# Run powerflow. First name the folder for it.
	# Remove old copy of the model.
	shutil.rmtree(modelDir, ignore_errors=True)
	# Create the model directory.
	new(modelDir)
	# Create the .omd.
	os.remove(modelDir + '/Olin Barre Geo.omd')
	with open(modelDir + '/Olin Barre Geo.omd','w') as omdFile:
		omd = dict(feeder.newFeederWireframe)
		omd['tree'] = tree
		json.dump(omd, omdFile, indent=4)

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		'feederName1': 'Olin Barre Geo Modified DER',
		'modelType': modelName,
		'runTime': '',
		'layoutAlgorithm': 'forceDirected',
		'flickerThreshold': '2',
		'newGeneration': 'addedDer',
		'newGenerationStepUp': 'addedDerStepUp',
		'newGenerationBreaker': 'addedDerBreaker',
		'thermalThreshold': '100',
		'peakLoadData': '',
		'minLoadData': '',
		'tapThreshold': '2',
		'faultCurrentThreshold': '10',
		'faultVoltsThreshold': '138',
		'newGenerationInsolation': '30'
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _testingPlot():
	"""
	Internal helper for der interconnection testing plot processing.
	"""
	PREFIX = os.path.join(os.path.dirname(__file__), '../scratch/CIGAR/')
	#PREFIX = omf.omfDir + '/scratch/CIGAR/'

	FNAME = 'test_base_R4-25.00-1.glm_CLEAN.glm'
	# FNAME = 'test_Exercise_4_2_1.glm'
	# FNAME = 'test_ieee37node.glm'
	# FNAME = 'test_ieee123nodeBetter.glm'
	# FNAME = 'test_large-R5-35.00-1.glm_CLEAN.glm'c
	# FNAME = 'test_medium-R4-12.47-1.glm_CLEAN.glm'
	# FNAME = 'test_smsSingle.glm'

	tree = feeder.parse(PREFIX + FNAME)
	chart = drawPlot(tree, neatoLayout=True, perUnitScale=False, rezSqIn=400)
	#chart = drawPlot(PREFIX + FNAME, neatoLayout=True, edgeCol=True, nodeLabs="Voltage", edgeLabs="Current", perUnitScale=False, rezSqIn=400)

	chart.savefig(PREFIX + "YO_WHATS_GOING_ON.png")
	plt.show()

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
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
	#_testingPlot()
