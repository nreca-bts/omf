"""
Implement Steinmetz-inspired inverter-control routines for GridLAB-D feeder studies.
"""

# imports
import os, random as rand, math, glob, shutil, tempfile
from shutil import copyfile
import numpy

def moveAndCreateDir(sourcePath, dstDir):
	"""
	Perform move and create dir processing for the wrapped solver workflow.
	"""
	if os.path.isdir(dstDir) == False:
		os.makedirs(dstDir)
	else:
		shutil.rmtree(dstDir)
		os.makedirs(dstDir)

	shutil.copy(sourcePath, dstDir)

class PV_information:
	"""
	Store photovoltaic system metadata used by Steinmetz controller workflows.
	"""
	Parent = ""
	Phase = ""
	Rating = 0 
	P_Out = 0
	Q_Max = 0.0
	Name = " "
	Q_Out = 0.0

	def __init__(self,parent,phase,rating,P_out,Q_max,name,Q_out):
		"""
		Internal helper for steinmetz controller init processing.
		"""
		self.Parent = parent
		self.Phase = phase
		self.Rating = rating
		self.P_Out = P_out
		self.Q_Max = Q_max
		self.Name = name
		self.Q_Out = Q_out

def complexToString(complexNumber):
	"""
	Perform complex to string processing for the wrapped solver workflow.
	"""
	if complexNumber.imag>0:
		return str(complexNumber.real) + '+' + str(complexNumber.imag) + 'j'
	elif complexNumber.imag ==0:
		return str(complexNumber.real) + '+0j' 
	else:
		return str(complexNumber.real) + str(complexNumber.imag) + 'j'

class StreamInfo:
	"""
	Store stream metadata used when exchanging Steinmetz controller time-series data.
	"""
	Entities = []
	Connectivity = []
	RootDic = {}
	LeafDic = {}
	LineDic = {}
	GeneralLineDic = {}
	NodePhaseDic = {}

	def __init__(self):
		"""
		Internal helper for steinmetz controller init processing.
		"""
		pass

# establish stream vector (leaf/node dictionary)
def CreateStreamInfo(glmFileName, sourceNode):
	# 
	"""
	Perform create stream info processing for the wrapped solver workflow.
	"""
	connectivity = []
	# all entities
	# excluding capacitor, load, lines, regulators
	entities = []
	# root dictionary for each entity
	# key: entity, value: direct root of the entity
	rootDic = {}
	# leaf dictionary for each entity with leaves
	# key: entity, value: direct leaves of the entity
	leafDic = {}
	# node phase dictionary
	# general node: node, triplex_node, meter, triplex meter (can be expanded)
	# load and capacitor not included
	nodePhaseDic = {}
	# ol/ul line connectivity dictionary
	# key: line name, value: [line connectivity]
	linesDic = {}
	# general line connectivity dictionary
	# fuse, xfmr
	gLinesDic = {}
	dangLineCnt = 0
	with open(glmFileName, 'r') as fp:
		searchFlag = 0
		hasConn = False
		isNode = False
		isLine = False
		isGeneralLine = False
		content = fp.readlines()
		tempConnectivity = {}
		temp_name = ''
		temp_phase = ''
		# parser: loop through lines
		for line in content:
			if '{' in line.strip():
				searchFlag = searchFlag + 1 
				if 'object node' in line.strip() or 'object triplex_node' in line.strip():
					# node
					isNode = True
				elif 'object meter' in line.strip() or 'object triplex_meter' in line.strip():
					isNode = True
				elif 'object transformer' in line.strip() or 'object fuse' in line.strip():
					isGeneralLine = True
				elif '_line' in line.strip():
					isLine = True
			elif 'phases ' in line.strip():
				if isNode == True:
					#isNodeThreePhase = True
					temp_phase = line.strip().strip('phase').strip().strip(';')
			elif 'from ' in line.strip():
				tempConnectivity['from'] = line.strip().strip('from').strip().strip(';')
				hasConn = True
			elif 'to ' in line.strip():
				tempConnectivity['to'] = line.strip().strip('to').strip().strip(';')
				hasConn = True
			elif 'name ' in line.strip():
				temp_name = line.strip().strip('name').strip().strip(';')
			elif 'parent ' in line.strip():
				if isNode == True:
					# meters/triplex meter to node and triplex_node 
					tempConnectivity['from'] = line.strip().strip('parent').strip().strip(';')
					tempConnectivity['to'] = temp_name
					hasConn = True
					# print 'parent conn:', tempConnectivity['from'], tempConnectivity['to']
			elif '}' in line.strip():
				searchFlag = searchFlag - 1
				if isNode == True:
					# add general node into dictionary
					nodePhaseDic[temp_name] = temp_phase
				if searchFlag == 0 and hasConn == True:
					# have both from and to
					connectivity.append([tempConnectivity['from'], tempConnectivity['to']])
					# add entities
					if not tempConnectivity['from'] in entities:
						entities.append(tempConnectivity['from'])
					if not tempConnectivity['to'] in entities:
						entities.append(tempConnectivity['to'])
					# add ol/ul lines
					if isLine == True:
						linesDic[temp_name] = set([tempConnectivity['from'], tempConnectivity['to']])
					# add fuse/xfmr
					if isGeneralLine == True:
						gLinesDic[temp_name] = set([tempConnectivity['from'], tempConnectivity['to']])
				elif searchFlag != 0 and hasConn == True:
					print('dangling line!')
					dangLineCnt = dangLineCnt + 1
				# reset flags
				searchFlag = 0
				hasConn = False
				isNode = False
				isLine = False
				isGeneralLine = False
				temp_name = ''
				temp_phase = ''

	result = StreamInfo()
	# save connectivity
	result.Connectivity = connectivity
	result.NodePhaseDic = nodePhaseDic
	rootDic[sourceNode] = 'SOURCE'
	leafNodes = []
	leafNodes.append(sourceNode)
	rootNodes = []

	# establish line vectors: rootDic, leafDic
	# assuming each leaf has only one root..
	while len(connectivity) > 0 and len(leafNodes) > 0:
		# set new roots
		#print len(connectivity), leafNodes
		rootNodes = leafNodes
		leafNodes = []
		elemToRemove = []
		# find leaves for each root
		for root in rootNodes:
			#initLen = len(connectivity)
			leafDic[root] = []
			for elem in connectivity:
				# record root-leaf relationship
				if root == elem[0]:
					rootDic[elem[1]] = root
					leafDic[root].append(elem[1])
					leafNodes.append(elem[1])
					elemToRemove.append(elem)
				elif root == elem[1]:
					rootDic[elem[0]] = root
					leafDic[root].append(elem[0])
					leafNodes.append(elem[0])
					elemToRemove.append(elem)
			# remove found root-leaves connection from connectivity
			connectivity = [e for e in connectivity if e not in elemToRemove]
	result.Entities = entities
	result.RootDic = rootDic
	result.LeafDic = leafDic
	result.LineDic = linesDic
	result.GeneralLineDic = gLinesDic
	return result


# find general upstream node
def GetUpstreamNodes(targetNode, nPhaseQualifierList, streamInfo):
# find upstream nodes of the target node
# go to source, collect leaves along the path
# TODO: validate nodePhaseList
	"""
	Perform get upstream nodes processing for the wrapped solver workflow.
	"""
	leafNode = targetNode
	upstreamNodes = []
	while streamInfo.RootDic[leafNode] != 'SOURCE':
		# find root
		root = streamInfo.RootDic[leafNode]
		# add to array if it meet phase criteria
		#if root in streamInfo.NodePhaseDic and streamInfo.RootDic[root] != 'SOURCE':
		if nPhaseQualifierList != []:
			if root in streamInfo.NodePhaseDic.keys() and streamInfo.NodePhaseDic[root] in nPhaseQualifierList and streamInfo.RootDic[root] != 'SOURCE':
				upstreamNodes.append(root)
		else:
			if root in streamInfo.NodePhaseDic.keys() and streamInfo.RootDic[root] != 'SOURCE':
				upstreamNodes.append(root)
		# find leaves of the found root
		prevLeaves = streamInfo.LeafDic[root]
		prevLeaves.remove(leafNode)
		while len(prevLeaves) > 0:
			#print len(prevLeaves)
			# prev leaf -> curr root
			currRoots = prevLeaves
			prevLeaves = []
			for rRoot in currRoots:
				# for each curr root, find its leaves
				if rRoot in streamInfo.LeafDic:
					# if leaf exist
					for rRootLeaf in streamInfo.LeafDic[rRoot]:
						# append leaf to prevLeaves
						prevLeaves.append(rRootLeaf)
						if nPhaseQualifierList != []:
							if rRootLeaf in streamInfo.NodePhaseDic.keys() and streamInfo.NodePhaseDic[rRootLeaf] in nPhaseQualifierList:
							# add qualified node to output
								upstreamNodes.append(rRootLeaf)
						else:
							if rRootLeaf in streamInfo.NodePhaseDic.keys():
								# if it is a general node
								upstreamNodes.append(rRootLeaf)
		leafNode = root
	return upstreamNodes

def GetDownStreamNodes(targetNode, nPhaseQualifierList, streamInfo):
# find downstream nodes
	"""
	Perform get down stream nodes processing for the wrapped solver workflow.
	"""
	downstreamNodes = []
	prevLeaves = []
	prevLeaves.append(targetNode)
	while len(prevLeaves) > 0:
		#print len(prevLeaves)
		# prev leaf -> curr root
		currRoots = prevLeaves
		prevLeaves = []
		for rRoot in currRoots:
			# for each curr root, find its leaves
			if rRoot in streamInfo.LeafDic:
				# if leaf exist
				for rRootLeaf in streamInfo.LeafDic[rRoot]:
					# append leaf to prevLeaves
					prevLeaves.append(rRootLeaf)
					if nPhaseQualifierList != []:
						if rRootLeaf in streamInfo.NodePhaseDic.keys() and streamInfo.NodePhaseDic[rRootLeaf] in nPhaseQualifierList:
						# add qualified general node to output
							downstreamNodes.append(rRootLeaf)
					else:
						if rRootLeaf in streamInfo.NodePhaseDic.keys():
							downstreamNodes.append(rRootLeaf)

	# add targetNode itself
	downstreamNodes.append(targetNode)
	return downstreamNodes

def FindLine(node1, node2, streamInfo):
	"""
	Perform find line processing for the wrapped solver workflow.
	"""
	for key, value in streamInfo.LineDic.items():
		if value == set([node1, node2]):
			return key
	return None

# find cloest qualified upstream node 
def GetCloestUpstreamNode(inputItem, nPhaseQualifierList, streamInfo):
	"""
	Perform get cloest upstream node processing for the wrapped solver workflow.
	"""
	if inputItem in streamInfo.Entities:
		# general node item
		targetNode = inputItem
	elif inputItem in streamInfo.GeneralLineDic:
		# xfmr..
		connNodes = GeneralLineDic[inputItem]
		if streamInfo.RootDic[connNodes[0]] == connNodes[1]:
			# if connNodes[1] is the root node of connNodes[0]
			targetNode = connNodes[1]
		else:
			targetNode = connNodes[0]
	else:
		# TODO: other input items or invalid input
		print('Input item invalid or not supported')
		return
	leafNode = targetNode
	while streamInfo.RootDic[leafNode] != 'SOURCE':
		root = streamInfo.RootDic[leafNode]
		# check if root is a three phase node
		if streamInfo.NodePhaseDic[root] in nPhaseQualifierList:
			return root
		leafNode = root
	return leafNode


def FindSlack(sourceFileName):
	"""
	Perform find slack processing for the wrapped solver workflow.
	"""
	temp_Name = ''
	sourceNode = ''
	IsSwing = 0
	IsNode = 0
	with open(sourceFileName,'r') as fp:
		content = fp.readlines()
		
		for line in content:
			
			if 'object' in line.strip():
				IsSwing = 0
				if 'node' in line.strip():
					IsNode = 1
				else :
					IsNode = 0
				continue
			
			if IsNode == 1 :
				if 'name' in line.strip():
					temp_Name = line.strip().strip('name').strip(' ').strip(";")
				if 'SWING' in line.strip():
					IsSwing = 1
					
			if '}' in line.strip() and IsSwing == 1:
				sourceNode = temp_Name
				break
				
	return sourceNode
def GetDeltaPVdata(sourceFileName,streamInfo):
	"""
	Perform get delta pvdata processing for the wrapped solver workflow.
	"""
	PV = []
	PV_index = {}
	PV_rating = 0
	name_temp = ''
	phase_temp = ''
	parent_name = ''
	parent_temp = ''
	IsTrpMeter = 0
	with open(sourceFileName) as fp:
		content = fp.readlines()

		for line in content:
			if 'object' in line.strip():
				if 'inverter' in line.strip():
					IsTrpMeter = 1
					
				else :
					IsTrpMeter = 0
				continue
			if IsTrpMeter == 1:
				if 'name' in line.strip():
					name_temp = line.strip().strip('name').strip(' ').strip(";")
				if 'parent' in line.strip():
					parent_temp = line.strip().strip('parent').strip(' ').strip(";")
				if 'phases' in line.strip():
					
					phase_temp = line.strip().strip("phases").strip(' ').strip(";")
					if 'A' in phase_temp:
						phase_temp ='ABD'
					elif 'B' in phase_temp:
						phase_temp ='BCD'
					elif 'C' in phase_temp:
						phase_temp ='ACD'
				if 'P_Out' in line.strip():
					P_out = int(line.strip().strip("P_Out").strip(' ').strip(";"))
				if 'rated_power' in line.strip():
					PV_rating = int(line.strip().strip("rated_power").strip(' ').strip(";"))
				if '}' in line.strip():
					parent_name = GetCloestUpstreamNode(parent_temp, ['ABCN','ABC','ACB','BAC','BCA','CAB','CBA'], streamInfo)
					Q_max = math.sqrt(PV_rating**2-P_out**2)
					PV.append(PV_information(parent_name,phase_temp,PV_rating,P_out,Q_max,name_temp,0.0))
					PV_index[name_temp] = len(PV) - 1
					IsTrpMeter = 0
	return PV,PV_index


def CreateDeltaPVfile(sourceFileName,PV):

	"""
	Perform create delta pvfile processing for the wrapped solver workflow.
	"""
	outputFilename = sourceFileName.strip('.glm')+'DeltaPV.glm'
	with open(sourceFileName, 'r') as inputFile, open(outputFilename, 'w+') as outputFile:
		isPV = 0
		delay = 0
		contentIn = inputFile.readlines()
		tempString = ''
		for line in contentIn:
			if 'object inverter' in line.strip():
				isPV = 1
			elif 'object solar' in line.strip():
				isPV = 1
			else:
				pass
			if isPV == 0:
				tempString = tempString + line

			if '}' in line.strip():
				if isPV ==1:
					delay = 1
			if line.strip() == '' and delay == 1:
				delay = 0
				isPV = 0
		outputFile.write(tempString)

	for i in range(0,len(PV)):
		with open(outputFilename,'a+') as fp:
			fp.writelines(['object load {\n', '    phases '+PV[i].Phase+';\n', '    name '+ PV[i].Name+';\n', '    parent '+ PV[i].Parent+';\n'])
			if PV[i].Phase == 'ABD':
				fp.writelines(['    groupid deltaPVAB;\n','    constant_power_A '+complexToString(complex(-PV[i].P_Out,0)) +';\n','};\n\n'])
			elif PV[i].Phase == 'BCD':
				fp.writelines(['    groupid deltaPVBC;\n','    constant_power_B '+complexToString(complex(-PV[i].P_Out,0)) +';\n','};\n\n'])
			elif PV[i].Phase == 'ACD':
				fp.writelines(['    groupid deltaPVCA;\n','    constant_power_C '+complexToString(complex(-PV[i].P_Out,0)) +';\n','};\n\n'])

	return outputFilename


def SteinmetzDeltaQ_VUF(voltage,current,Q_pre):
	"""
	Perform steinmetz delta q vuf processing for the wrapped solver workflow.
	"""
	Q = {}
	voltage_A = voltage['A']
	voltage_B = voltage['B']
	voltage_C = voltage['C']

	current_A = current['A']
	current_B = current['B']
	current_C = current['C']

	voltage_AB = voltage_A - voltage_B
	voltage_BC = voltage_B - voltage_C
	voltage_AC = voltage_C - voltage_A

	current_AB = 2.0/3*current_A+1.0/3*current_C
	current_BC = 1.0/3*current_A+2.0/3*current_B
	current_AC = 1.0/3*current_B+2.0/3*current_C

	power_AB = voltage_AB * current_AB.conjugate() - complex(0,Q_pre['AB'])
	power_BC = voltage_BC * current_BC.conjugate() - complex(0,Q_pre['BC'])
	power_AC = voltage_AC * current_AC.conjugate() - complex(0,Q_pre['AC'])

	Q['AB'] = 1.0/3*(-2*power_AB.imag + power_BC.imag + power_AC.imag + math.sqrt(3)*power_BC.real - math.sqrt(3)*power_AC.real)
	Q['BC'] = 1.0/3*(power_AB.imag -2*power_BC.imag + power_AC.imag + math.sqrt(3)*power_AC.real - math.sqrt(3)*power_AB.real)
	Q['AC'] = 1.0/3*(power_AB.imag + power_BC.imag -2* power_AC.imag + math.sqrt(3)*power_AB.real - math.sqrt(3)*power_BC.real)


	return Q

# Steinmetz circuit design (Wye) to decrease VUF
def SteinmetzWyeQ_VUF(voltage,current,Q_pre):
	"""
	Perform steinmetz wye q vuf processing for the wrapped solver workflow.
	"""
	Q = {}
	a = complex(-0.5, math.sqrt(3)/2)
	voltage_A = voltage['A']
	voltage_B = voltage['B']
	voltage_C = voltage['C']

	current_A = current['A']
	current_B = current['B']
	current_C = current['C']

	power_A = voltage_A * current_A.conjugate() - complex(0,Q_pre['A'])
	power_B = voltage_B * current_B.conjugate() - complex(0,Q_pre['B'])
	power_C = voltage_C * current_C.conjugate() - complex(0,Q_pre['C'])
	# compute steinmetz reactive power
	X_A = numpy.array([[(complex(0,1)/voltage_A.conjugate()).real,(complex(0,1)/voltage_B.conjugate()*a**2).real,(complex(0,1)/voltage_C.conjugate()*a).real],[(complex(0,1)/  voltage_A.conjugate()).imag,(complex(0,1)/voltage_B.conjugate()*a**2).imag,(complex(0,1)/voltage_C.conjugate()*a).imag],[1.0, 1.0, 1.0]])
	X_B = numpy.array([((power_A/voltage_A).conjugate()+a**2*(power_B/voltage_B).conjugate()+a*(power_C/voltage_C).conjugate()).real,((power_A/voltage_A).conjugate()+a**2*(power_B/voltage_B).conjugate()+a*(power_C/voltage_C).conjugate()).imag,0.0])
	X = numpy.linalg.solve(X_A,X_B)
	Q['A'] = X[0]
	Q['B'] = X[1]
	Q['C'] = X[2]
	
	return Q


# Steinmetz circuit design to decrease V0
def SteinmetzWyeQ_V0(voltage,current,Q_pre):
	"""
	Perform steinmetz wye q v0 processing for the wrapped solver workflow.
	"""
	Q = {}
	a = complex(-0.5, math.sqrt(3)/2)
	voltage_A = voltage['A']
	voltage_B = voltage['B']
	voltage_C = voltage['C']
	current_A = current['A']
	current_B = current['B']
	current_C = current['C']
	power_A = voltage_A * current_A.conjugate() - complex(0,Q_pre['A'])
	power_B = voltage_B * current_B.conjugate() - complex(0,Q_pre['B'])
	power_C = voltage_C * current_C.conjugate() - complex(0,Q_pre['C'])

	# compute steinmetz reactive power
	X_A = numpy.array([[(complex(0,1)/voltage_A.conjugate()).real,(complex(0,1)/voltage_B.conjugate()).real,(complex(0,1)/voltage_C.conjugate()).real],[(complex(0,1)/ voltage_A.conjugate()).imag,(complex(0,1)/voltage_B.conjugate()).imag,(complex(0,1)/voltage_C.conjugate()).imag],[1.0, 1.0, 1.0]])

	X_B = numpy.array([((power_A/voltage_A).conjugate()+(power_B/voltage_B).conjugate()+(power_C/voltage_C).conjugate()).real,((power_A/voltage_A).conjugate()+(power_B/voltage_B).conjugate()+(power_C/voltage_C).conjugate()).imag,0.0])

	X = numpy.linalg.solve(X_A,X_B)
	Q['A'] = X[0]
	Q['B'] = X[1]
	Q['C'] = X[2]

	return Q


def ReadVoltage(voltageFileName):
	"""
	Perform read voltage processing for the wrapped solver workflow.
	"""
	with open(voltageFileName, 'r') as fp1:
		contentVoltage = fp1.readlines()
		voltage = {}
		for line in contentVoltage:
			if '#' not in line.strip() and len(line.strip()) > 0:
				voltage['A'] = complex(line.split(',')[1])
				voltage['B'] = complex(line.split(',')[2])
				voltage['C'] = complex(line.split(',')[3])
		return voltage

def ReadCurrent(currentFileName):
	"""
	Perform read current processing for the wrapped solver workflow.
	"""
	with open(currentFileName, 'r') as fp2:
		contentCurrent = fp2.readlines()
		current = {}
		for line in contentCurrent:
			if '#' not in line.strip() and len(line.strip()) > 0:
				current['A'] = complex(line.split(',')[1])
				current['B'] = complex(line.split(',')[2])
				current['C'] = complex(line.split(',')[3])

		return current

def AddRecorder(sourceFileName,criticalNode,line_name):
	"""
	Perform add recorder processing for the wrapped solver workflow.
	"""
	with open(sourceFileName,'a+') as fp:
		fp.writelines(['object recorder {\n','    parent '+ criticalNode+ ';\n','    interval 10;\n','    limit 1440;\n', '    file  "Node_voltage.csv";\n','    property "voltage_A,voltage_B,voltage_C";\n};\n\n'])
		fp.writelines(['object recorder {\n','    parent '+ line_name+ ';\n','    interval 10;\n','    limit 1440;\n', '    file  "Node_current.csv";\n','    property "current_out_A,current_out_B,current_out_C";\n};\n\n'])


def AddPVWyeRecorder(sourceFileName,suffix):
	"""
	Perform add pvwye recorder processing for the wrapped solver workflow.
	"""
	with open(sourceFileName,'a+') as fp:
		fp.writelines(['object group_recorder {\n','    group class=inverter;\n','    interval 10;\n','    limit 1440;\n', '    file  "all_inverters_VA_Out_AC'+suffix+'.csv";\n','    property VA_Out;\n};\n\n'])
		


def AddPVDeltaRecorder(sourceFileName,suffix):
	"""
	Perform add pvdelta recorder processing for the wrapped solver workflow.
	"""
	with open(sourceFileName,'a+') as fp:
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=deltaPVAB;\n','    interval 10;\n','    limit 1440;\n', '    file  "all_inverters_VA_Out_AC_A'+suffix+'.csv";\n','    property power_A;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=deltaPVBC;\n','    interval 10;\n','    limit 1440;\n', '    file  "all_inverters_VA_Out_AC_B'+suffix+'.csv";\n','    property power_B;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=deltaPVCA;\n','    interval 10;\n','    limit 1440;\n', '    file  "all_inverters_VA_Out_AC_C'+suffix+'.csv";\n','    property power_C;\n};\n\n'])
		

def addOutputCSV(sourceFileName,suffix):
	"""
	Perform add output csv processing for the wrapped solver workflow.
	"""
	with open(sourceFileName,'a+') as fp:
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephaseMotor_Voltage_A'+suffix+'.csv";\n','    property voltage_A;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephaseMotor_Voltage_B'+suffix+'.csv";\n','    property voltage_B;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephaseMotor_Voltage_C'+suffix+'.csv";\n','    property voltage_C;\n};\n\n'])

		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephase_VA_A'+suffix+'.csv";\n','    property power_A;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephase_VA_B'+suffix+'.csv";\n','    property power_B;\n};\n\n'])
		fp.writelines(['object group_recorder {\n','    group class=load AND groupid=threePhase;\n','    interval 10;\n','    limit 1440;\n', '    file  "threephase_VA_C'+suffix+'.csv";\n','    property power_C;\n};\n\n'])
		
		fp.writelines(['object collector {\n','    group class=transformer;\n','    interval 10;\n','    limit 1440;\n', '    file  "Zlosses_transformer'+suffix+'.csv";\n','    property sum(power_losses_A.real),sum(power_losses_B.real),sum(power_losses_C.real);\n};\n\n'])
		fp.writelines(['object collector {\n','    group class=underground_line;\n','    interval 10;\n','    limit 1440;\n', '    file  "Zlosses_underground_line'+suffix+'.csv";\n','    property sum(power_losses_A.real),sum(power_losses_B.real),sum(power_losses_C.real);\n};\n\n'])
		fp.writelines(['object collector {\n','    group class=overhead_line;\n','    interval 10;\n','    limit 1440;\n', '    file  "Zlosses_overhead_line'+suffix+'.csv";\n','    property sum(power_losses_A.real),sum(power_losses_B.real),sum(power_losses_C.real);\n};\n\n'])
		fp.writelines(['object collector {\n','    group class=triplex_line;\n','    interval 10;\n','    limit 1440;\n', '    file  "Zlosses_triplex_line'+suffix+'.csv";\n','    property sum(power_losses_A.real),sum(power_losses_B.real),sum(power_losses_C.real);\n};\n\n'])
		fp.writelines(['object collector {\n','    group class=load;\n','    interval 10;\n','    limit 1440;\n', '    file  "load'+suffix+'.csv";\n','    property sum(power_A.real),sum(power_B.real),sum(power_C.real),sum(power_A.imag),sum(power_B.imag),sum(power_C.imag);\n};\n\n'])
		fp.writelines(['object collector {\n','    group class=triplex_node;\n','    interval 10;\n','    limit 1440;\n', '    file  "triplexload'+suffix+'.csv";\n','    property sum(power_12.real),sum(power_12.imag);\n};\n\n'])

def FindSlack(sourceFileName):
	"""
	Perform find slack processing for the wrapped solver workflow.
	"""
	temp_Name = ''
	sourceNode = ''
	IsSwing = 0
	IsNode = 0
	with open(sourceFileName,'r') as fp:
		content = fp.readlines()
		
		for line in content:
			
			if 'object' in line.strip():
				IsSwing = 0
				if 'node' in line.strip():
					IsNode = 1
				else :
					IsNode = 0
				continue
			
			if IsNode == 1 :
				if 'name' in line.strip():
					temp_Name = line.strip().strip('name').strip(' ').strip(";")
				if 'SWING' in line.strip():
					IsSwing = 1
					
			if '}' in line.strip() and IsSwing == 1:
				sourceNode = temp_Name
				break
				
	return sourceNode




def GetWyePVdata(sourceFileName):
	"""
	Perform get wye pvdata processing for the wrapped solver workflow.
	"""
	PV = []
	PV_index = {}
	PV_rating = 0
	name_temp = ''
	phase_temp = ''
	parent_temp = ''
	IsTrpMeter = 0
	with open(sourceFileName) as fp:
		content = fp.readlines()

		for line in content:
			if 'object' in line.strip():
				if 'inverter' in line.strip():
					IsTrpMeter = 1
					
				else :
					IsTrpMeter = 0
				continue
			if IsTrpMeter == 1:
				if 'name' in line.strip():
					name_temp = line.strip().strip('name').strip(' ').strip(";")
				if 'parent' in line.strip():
					parent_temp = line.strip().strip('parent').strip(' ').strip(";")
				if 'phases' in line.strip():
					phase_temp = line.strip().strip("phases ").strip(";")	
				if 'P_Out' in line.strip():
					P_out = int(line.strip().strip("P_Out ").strip(";"))
				if 'rated_power' in line.strip():
					PV_rating = int(line.strip().strip("rated_power ").strip(";"))
				if '}' in line.strip():
					Q_max = math.sqrt(PV_rating**2-P_out**2)
					PV.append(PV_information(parent_temp,phase_temp,PV_rating,P_out,Q_max,name_temp,0.0))
					PV_index[name_temp] = len(PV) - 1
					IsTrpMeter = 0
	return PV,PV_index

def ChangeGlmFileWye(inputFileName,outputFileName,PV,PV_index):
	"""
	Perform change glm file wye processing for the wrapped solver workflow.
	"""
	with open(inputFileName, 'r') as inputFile, open(outputFileName, 'w+') as outputFile:

		isPV = 0
		contentIn = inputFile.readlines()
		tempString = ''

		for line in contentIn:
			tempLine = line
			# write by object block
			# identify object
			if 'object inverter' in line.strip():
				isPV = 1
			else:
				# not inverter, just copy
				pass
						
			# within load	
			if isPV == 1:
				if 'name' in line.strip():
					PV_name = line.strip().strip('name').strip(' ').strip(';')
					m = PV_index[PV_name]
				if '}' in line.strip():
					tempLine = '\tQ_Out' + ' ' +  str(PV[m].Q_Out) + ';\n};\n'
					isPV = 0
							
			if 'Q_Out' not in line.strip():
				tempString = tempString + tempLine

		outputFile.write(tempString)

def ChangeGlmFileDelta(inputFileName,outputFileName,PV,PV_index):
	"""
	Perform change glm file delta processing for the wrapped solver workflow.
	"""
	with open(inputFileName, 'r') as inputFile, open(outputFileName, 'w+') as outputFile:
		isLoad = 0
		isPV = 0
		contentIn = inputFile.readlines()
		tempString = ''
		power_string = ''
		for line in contentIn:
	# write by object block
	# identify object
			if 'object load' in line.strip():
				isLoad = 1
			elif '}' in line.strip():
				isLoad = 0
				isPV = 0
				power_string = ''
			else:
		# not load, just copy
				pass
	# within load
			if isLoad == 1:
				if 'name' in line.strip():
					load_name = line.strip().strip('name').strip(' ').strip(';')
				if 'groupid deltaPV' in line.strip():
					isPV = 1
					m = PV_index[load_name]
					#print complex(-PV[m].P_Out,-PV[m].Q_Out)
					power_string = complexToString(complex(-PV[m].P_Out,-PV[m].Q_Out))
				if isPV == 1 and 'constant_power' in line.strip():
					line = '\t' + line.strip(';').split()[0] + ' ' + power_string + ';\n'
			tempString = tempString + line

		outputFile.write(tempString)


def addIdtoThreephaseload(inputFileName,outputFileName):

	"""
	Perform add idto threephaseload processing for the wrapped solver workflow.
	"""
	with open(inputFileName, 'r') as inputFile, open(outputFileName, 'w+') as outputFile:
		isLoad = 0
		isThreephase = 0
		hasGroupid = 0

		contentIn = inputFile.readlines()
		tempString = ''

		for line in contentIn:
			if 'starttime' in line.strip():
					line =" 	starttime '2000-01-01 0:00:00';\n" 
			if 'stoptime' in line.strip():
					line =" 	stoptime '2000-01-01 0:01:00';\n"
			if 'object load' in line.strip():
				isLoad =1
			else:
				# not inverter, just copy
				pass

			if isLoad == 1 :
				if 'ABCN' in line.strip():
					isThreephase = 1
				if 'groupid' in line.strip():
					hasGroupid = 1
					if isThreephase == 1:
						line = '    groupid threePhase;\n'
			if '}' in line.strip():
				if isThreephase == 1 and hasGroupid == 0 :
					line = '    groupid threePhase;\n};\n'
				hasGroupid = 0
				isThreephase = 0
				isLoad = 0

			tempString = tempString + line

		outputFile.write(tempString)

def SteinmetzController(sourceFileName,connectionPV,criticalNode,iterNum,objective,destDir):
	

	#Find the swing bus of the feeder
	"""
	Perform steinmetz controller processing for the wrapped solver workflow.
	"""
	sourceNode = FindSlack(sourceFileName)
	# establish streaminfo first
	streamInformation = CreateStreamInfo(sourceFileName, sourceNode)
	#
	# find the upstream nodes of the critical node and the upstream line connect to the critical node

	criticalNodeRoot = streamInformation.RootDic[criticalNode]
	criticalLine = FindLine(criticalNode, criticalNodeRoot, streamInformation)

	#get the downstream node information
	downstreamNodes = GetDownStreamNodes(criticalNode,[],streamInformation)

	# file names
	# moveAndCreateDir(sourceFileName, destDir)
	os.chdir(destDir)
	outputFileName = sourceFileName.strip('.glm') + '_Step_0.glm'
	#set the running time only to be 1s and add groupid to threephase load
	addIdtoThreephaseload(sourceFileName,outputFileName)
	#add recorders to the end of the file
	AddRecorder(outputFileName,criticalNode,criticalLine)
	#compute VUF
	a = complex(-0.5, math.sqrt(3)/2)

	VUF = numpy.zeros(30)
	I0  = numpy.zeros(30)
	voltageFileName = 'Node_voltage.csv'
	currentFileName = 'Node_current.csv'





	if connectionPV == 'Wye':
		inputStartFileName = sourceFileName.strip('.glm') + '_Wye_Start.glm'
		copyfile(outputFileName,inputStartFileName)
		AddPVWyeRecorder(inputStartFileName,'_base')
		PV,PV_index = GetWyePVdata(outputFileName)
		
		PV_A_total_rating = 0
		PV_B_total_rating = 0
		PV_C_total_rating = 0
		
		for m in range(0,len(PV)):
			if PV[m].Parent in downstreamNodes	:
				if 'A' in PV[m].Phase:
					PV_A_total_rating = PV_A_total_rating + PV[m].Rating
				if 'B' in PV[m].Phase :
					PV_B_total_rating = PV_B_total_rating + PV[m].Rating
				if 'C' in PV[m].Phase:
					PV_C_total_rating = PV_C_total_rating + PV[m].Rating
		
		#print PV_A_total_rating/10000, PV_B_total_rating/10000, PV_C_total_rating/10000
		cmdString = 'gridlabd ' + '"' + outputFileName + '"'
		for i in range(6):
			outCode = os.system(cmdString)
			if outCode == 0:
				break

		# Read .csv from gridlabd to get voltage and current information at node 17
		voltage  = ReadVoltage(voltageFileName)
		current  = ReadCurrent(currentFileName)
		VUF[0] = abs(voltage['A'] + a**2 * voltage['B'] + a * voltage['C'])/abs(voltage['A'] + a * voltage['B'] + a**2 * voltage['C']) *100
		I0[0] = abs(current['A']/3 + current['B']/3 + current['C']/3)
		#print abs(voltage['A']-voltage['B']),abs(voltage['B']-voltage['C']),abs(voltage['C']-voltage['A'])
		#print 'Initial VUF at', criticalNode, '{:.4E}'.format(VUF[0]), '%'
		#print 'Initial |I0| at', criticalNode, '{:.4E}'.format(I0[0]), 'A'
	
		Q_pre = {}
		Q_pre['A'] = 0
		Q_pre['B'] = 0
		Q_pre['C'] = 0
		max_delta = 100.0
		for iter in range(0,iterNum,1):
			if max_delta > 1E-5:
				PV_at_QMAX = 0
				inputFileName = sourceFileName.strip('.glm') + '_Step_' + str(iter) + '.glm'
				outputFileName = sourceFileName.strip('.glm') + '_Step_' + str(iter + 1) + '.glm'
			
				if objective == 'VUF':

					Q_steinmetz = SteinmetzWyeQ_VUF(voltage,current,Q_pre)

				elif objective == 'I0':
					Q_steinmetz = SteinmetzWyeQ_V0(voltage,current,Q_pre)

			
				Q_pre = Q_steinmetz
				
				#print Q_steinmetz
				PV_at_QMAX = 0
				for m in range(0,len(PV)):
		
					if 'A' in PV[m].Phase :
						
						if PV[m].Parent in downstreamNodes	:
							Q_A_each = Q_steinmetz['A'] * PV[m].Rating / PV_A_total_rating
							if (Q_A_each > 0.0) and (Q_A_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							elif (Q_A_each < 0.0) and (Q_A_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_A_each

					if 'B' in PV[m].Phase:
						Q_B_each = Q_steinmetz['B'] * PV[m].Rating / PV_B_total_rating
						if PV[m].Parent in downstreamNodes	:
							if (Q_B_each > 0.0) and (Q_B_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							
							elif (Q_B_each < 0.0) and (Q_B_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_B_each
						
					if  'C' in PV[m].Phase:
						Q_C_each = Q_steinmetz['C'] * PV[m].Rating / PV_C_total_rating
						if PV[m].Parent in downstreamNodes	:
							if (Q_C_each > 0.0) and (Q_C_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							elif (Q_C_each < 0.0) and (Q_C_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_C_each

				ChangeGlmFileWye(inputFileName,outputFileName,PV,PV_index)
				cmdString = 'gridlabd ' + '"' + outputFileName + '"'
				for i in range(6):
					outCode = os.system(cmdString)
					if outCode == 0:
						break
			
				#update voltage and current information from gridlabd
				voltage = ReadVoltage(voltageFileName)
				current = ReadCurrent(currentFileName)
				VUF[iter+1] = abs(voltage['A'] + a ** 2 * voltage['B'] + a * voltage['C'])/abs(voltage['A'] + a * voltage['B'] + a**2 * voltage['C']) *100
				#print abs(voltage['A']-voltage['B']),abs(voltage['B']-voltage['C']),abs(voltage['C']-voltage['A'])
				#print 'Final VUF at', criticalNode, '{:.5E}'.format(VUF[iter+1]), '%'
				I0[iter+1] = abs(current['A']/3 + current['B']/3 + current['C']/3)
				if objective == 'VUF':
					max_delta = abs(VUF[iter+1]-VUF[iter])
				elif objective == 'I0':
					max_delta = abs(I0[iter+1]-I0[iter])
			else:
				break
		
		
		#print 'Initial |I0| at', criticalNode, '{:.5E}'.format(I0[iter]), 'A'
		finalOutputfile = sourceFileName.strip('.glm') + '_Final.glm'
		copyfile(outputFileName,finalOutputfile)
		#AddPVWyeRecorder(finalOutputfile,'_csolar')

	if connectionPV == 'Delta':
		#get wye PV information
		renameFilename = sourceFileName.strip('.glm') + '_New.glm'
		copyfile(outputFileName,renameFilename)
		PV,PV_index = GetDeltaPVdata(renameFilename,streamInformation)
		#transform wye PV to delta negative load
		deltaPVfile = CreateDeltaPVfile(renameFilename,PV)
		inputStartFileName = deltaPVfile.strip('.glm') + '_Start.glm'
		copyfile(deltaPVfile,inputStartFileName)
		AddPVDeltaRecorder(inputStartFileName,'_base')
		outputFileName = deltaPVfile.strip('.glm') + '_Step_0.glm'
		copyfile(deltaPVfile,outputFileName)


		PV_A_total_rating = 0
		PV_B_total_rating = 0
		PV_C_total_rating = 0

		for m in range(0,len(PV)):
			if PV[m].Parent in downstreamNodes	:
				if 'AB' in PV[m].Phase:
					PV_A_total_rating = PV_A_total_rating + PV[m].Rating
				if 'BC' in PV[m].Phase :
					PV_B_total_rating = PV_B_total_rating + PV[m].Rating
				if 'AC' in PV[m].Phase:
					PV_C_total_rating = PV_C_total_rating + PV[m].Rating
		
		cmdString = 'gridlabd ' + '"' + outputFileName + '"'
		for i in range(6):
			outCode = os.system(cmdString)
			if outCode == 0:
				break
		# os.system(cmdString)

		# Read .csv from gridlabd to get voltage and current information at node 17
		voltage  = ReadVoltage(voltageFileName)
		current  = ReadCurrent(currentFileName)
		VUF[0] = abs(voltage['A'] + a**2 * voltage['B'] + a * voltage['C'])/abs(voltage['A'] + a * voltage['B'] + a**2 * voltage['C']) *100
		I0[0] = abs(current['A']/3 + current['B']/3 + current['C']/3)
	
		#print 'Initial VUF at', criticalNode, '{:.4E}'.format(VUF[0]), '%'
		#print 'Initial |I0| at', criticalNode, '{:.4E}'.format(I0[0]), 'A'
	
		Q_pre = {}
		Q_pre['AB'] = 0
		Q_pre['BC'] = 0
		Q_pre['AC'] = 0
		max_delta = 100.0
		for iter in range(0,iterNum,1):
			if max_delta > 1E-5:
				PV_at_QMAX = 0
				inputFileName = deltaPVfile.strip('.glm') + '_Step_' + str(iter) + '.glm'
				outputFileName = deltaPVfile.strip('.glm') + '_Step_' + str(iter + 1) + '.glm'
			
				if objective == 'VUF':

					Q_steinmetz = SteinmetzDeltaQ_VUF(voltage,current,Q_pre)

				elif objective == 'I0':
					print('Mitigate phase-to-ground unbalance is not supported using delta-connected PV')
					break

			
				Q_pre = Q_steinmetz
				
				#print Q_steinmetz
				PV_at_QMAX = 0
				for m in range(0,len(PV)):
					if 'AB' in PV[m].Phase :
						
						if PV[m].Parent in downstreamNodes	:
							Q_A_each = Q_steinmetz['AB'] * PV[m].Rating / PV_A_total_rating
							if (Q_A_each > 0.0) and (Q_A_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							elif (Q_A_each < 0.0) and (Q_A_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_A_each

					elif 'BC' in PV[m].Phase:
						Q_B_each = Q_steinmetz['BC'] * PV[m].Rating / PV_B_total_rating
						if PV[m].Parent in downstreamNodes	:
							if (Q_B_each > 0.0) and (Q_B_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							
							elif (Q_B_each < 0.0) and (Q_B_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_B_each
						
					elif  'AC' in PV[m].Phase:
						Q_C_each = Q_steinmetz['AC'] * PV[m].Rating / PV_C_total_rating
						if PV[m].Parent in downstreamNodes	:
							if (Q_C_each > 0.0) and (Q_C_each > PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = -PV[m].Q_Max
							elif (Q_C_each < 0.0) and (Q_C_each < -PV[m].Q_Max):
								PV_at_QMAX = PV_at_QMAX +1
								PV[m].Q_Out = PV[m].Q_Max
							else:
								PV[m].Q_Out = -Q_C_each
				ChangeGlmFileDelta(inputFileName,outputFileName,PV,PV_index)
				cmdString = 'gridlabd ' + '"' + outputFileName + '"'
				for i in range(6):
					outCode = os.system(cmdString)
					if outCode == 0:
						break
				# os.system(cmdString)
			
				#update voltage and current information from gridlabd				   
				voltage = ReadVoltage(voltageFileName)
				current = ReadCurrent(currentFileName)
				
				VUF[iter+1] = abs(voltage['A'] + a ** 2 * voltage['B'] + a * voltage['C'])/abs(voltage['A'] + a * voltage['B'] + a**2 * voltage['C']) *100
				#print 'Final VUF at', criticalNode, '{:.4E}'.format(VUF[iter+1]), '%'
				I0[iter+1] = abs(current['A']/3 + current['B']/3 + current['C']/3)
				if objective == 'VUF':
					max_delta = abs(VUF[iter+1]-VUF[iter])
				elif objective == 'I0':
					max_delta = abs(I0[iter+1]-I0[iter])
			else:
				break
		
		finalOutputfile = deltaPVfile.strip('.glm') + '_Final.glm'
		copyfile(outputFileName,finalOutputfile)
		#AddPVDeltaRecorder(finalOutputfile,'_csolar')



	#output the required csv file
	#addOutputCSV(inputStartFileName,'_base')
	#addOutputCSV(finalOutputfile,'_csolar')

	#moveAndCreateDir(inputStartFileName, destDir)
	
	#os.chdir(destDir)
	#cmdString_start = 'gridlabd ' + inputStartFileName
	#os.system(cmdString_start)
	#cmdString_out = 'gridlabd ' + finalOutputfile
	#os.system(cmdString_out)

def testing():
	#example 1
	"""
	Perform testing processing for the wrapped solver workflow.
	"""
	sourceFileName = os.path.abspath(os.path.join(os.path.dirname(__file__), '../static/testFiles/R1-12.47-1-AddSolar-Wye.glm'))
	criticalNode = 'R1-12-47-1_node_17'

	#example 2
	#sourceFileName = os.path.join(path_prefix, 'R1-12.47-2-AddSolar-Wye.glm')
	#criticalNode= 'R1-12-47-2_node_21'

	#sourceFileName = 'turkey_solar.glm'
	#criticalNode= 'nodeOH9975-S1862OH29955x2'

	#sourceFileName = 'bavarian_solar.glm'
	#criticalNode= 'node2246822703'
	#curDir = os.getcwd()
	#destDir = curDir+'/MPUPV output file'
	destDir = tempfile.mkdtemp()
	print('Testing MPUPV in:', destDir)
	SteinmetzController(sourceFileName,'Delta',criticalNode,5,'VUF',destDir)

if __name__ == '__main__':
	testing()
