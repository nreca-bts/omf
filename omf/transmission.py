''' Functions for manipulating electrical transmission network models. '''

import datetime, copy, os, re, json, tempfile, shutil, fileinput, webbrowser, platform, subprocess
from os.path import join as pJoin
import networkx as nx
import omf

def parse(inputStr, filePath=True):
	''' Parse a MAT into an omf.network json. This is so we can walk the json, change things in bulk, etc.
	Input can be a filepath or MAT string. Raises ValueError if the MAT file/string does not contain valid data.
	'''
	matDict = _dictConversion(inputStr, filePath)
	return matDict

def parseRaw(inputStr, filePath=True):
	''' Parse a RAW file into an omf.network json via a matpower file. This is so we can walk the json, 
	change things in bulk, etc. Input can be a filepath or RAW string. Raises ValueError if the RAW 
	file/string does not contain valid data.
	'''
	matfile_name = _rawToMat(inputStr, filePath)
	matDict = _dictConversion(matfile_name, True)
	if not filePath:
		os.remove(matfile_name)
	return matDict

def write(inNet):
	''' Turn an omf.network json object into a MAT-formatted string. '''
	output = ''
	for key in inNet:
		output += _dictToString(inNet[key]) + '\n'
	return output

def save(inNet, outPath):
	''' Write out an .omt for a inNet. '''
	with open(outPath, 'w') as outFile:
		json.dump(inNet, outFile, indent=4)

def layout(inNet):
	''' Add synthetic lat/lon data to a graph to give it a nice human-readable shape. '''
	nxG = netToNxGraph(inNet)
	inNet = latlonToNet(nxG, inNet)

def _dictConversion(inputStr, filePath=True):
	''' Turn a MAT file/string into a dictionary.

	E.g. turn a string like this:
	mpc.bus = [
	1	3	0	0	0	0	1	1	0	135	1	1.05	0.95;
	...
	]

	Into a Python dict like this:
	{"baseMVA":"100.0","mpcVersion":"2.0","bus":[{"1": {"bus_i": 1,"type": 3,"Pd": 0,"Qd": 0,"Gs": 0,"Bs": 0,"area": 1,"Vm": 1,"Va": 0,"baseKV": 135,"zone": 1,"Vmax": 1.05,"Vmin": 0.95}}],"gen":[],
	"branch":[]}

	Raises ValueError if the MAT file/string does not contain valid data.
	'''
	# Wireframe for new network objects:
	newNetworkWireframe = {"baseMVA":"100.0","mpcVersion":"2.0","bus":{},"gen":{}, "branch":{}}
	if filePath:
		with open(inputStr,'r') as matFile:
			data = matFile.readlines()
	else:
		data = inputStr
	# Parse data.
	todo = None
	validData = False
	for i,line in enumerate(data):
		if todo!=None:
			# Parse lines.
			line = line.translate({
				ord('\r'): None,
				ord('\n'): None,
				ord(';'): None
			})
			if "]" in line:
				todo = None
			if todo in ['bus','gen','bus','branch']:
				line = line.split('\t')
			else:
				line = line.split(' ')
			line = [a for a in line if a != '']
			if todo=="version":
				version = float(line[-1][1])
				if version < 2:
					print("MATPOWER VERSION MUST BE 2: %s"%(version))
					break
				todo = None
			elif todo=="mva":
				mva = line[-1]
				newNetworkWireframe['baseMVA'] = str(mva)
				todo = None
			elif todo=="bus":
				maxKey = str(len(newNetworkWireframe['bus'])+1)
				bus = {"bus_i":line[0],"type":line[1],"Pd": line[2],"Qd": line[3],"Gs": line[4],"Bs": line[5],"area": line[6],"Vm": line[7],"Va": line[8],"baseKV": line[9],"zone": line[10],"Vmax": line[11],"Vmin": line[12]}
				newNetworkWireframe['bus'][maxKey] = bus
			elif todo=="gen":
				maxKey = str(len(newNetworkWireframe['gen'])+1)
				gen = {"bus": line[0],"Pg": line[1],"Qg": line[2],"Qmax": line[3],"Qmin": line[4],"Vg": line[5],"mBase": line[6],"status": line[7],"Pmax": line[8],"Pmin": line[9],"Pc1": line[10],"Pc2": line[11],"Qc1min": line[12],"Qc1max": line[13],"Qc2min": line[14],"Qc2max": line[15],"ramp_agc": line[16],"ramp_10": line[17],"ramp_30": line[18],"ramp_q": line[19],"apf": line[20]}
				newNetworkWireframe['gen'][maxKey] = gen
			elif todo=='branch':
				maxKey = str(len(newNetworkWireframe['branch'])+1)
				branch =  {"fbus":line[0],"tbus":line[1],"r": line[2],"x": line[3],"b": line[4],"rateA": line[5],"rateB": line[6],"rateC": line[7],"ratio": line[8],"angle": line[9],"status": line[10],"angmin": line[11],"angmax": line[12]}
				newNetworkWireframe['branch'][maxKey] = branch
		else:
			# Determine what type of data is coming up.
			if "matpower case format" in line.lower():
				todo = "version"
			elif "system mva base" in line.lower():
				todo = "mva"
				validData = True
			elif "mpc.bus = [" in line.lower():
				todo = "bus"
				validData = True
			elif "mpc.gen = [" in line.lower():
				todo = "gen"
				validData = True
			elif "mpc.branch = [" in line.lower():
				todo = "branch"
				validData = True
	if validData == False:
		raise ValueError('MAT file/string does not contain valid data.')
	return newNetworkWireframe

def _dictToString(inDict):
	''' Helper function: given a single dict representing a NETWORK, concatenate it into a string. '''
	return ''

def _rawToMat(inputStr, filePath=True):
	''' Turn a RAW file/string into a MATPOWER case structure. 
	See the following for details: https://matpower.org/docs/ref/matpower5.0/psse2mpc.html
	'''
	#TODO: offer installs below, or at least check for octave + matpower availability.
	# ALSO NEED OCTAVE INSTALL, WILL BE PLATFORM DEPENDENT
	# os.system(f"wget -P {source_dir}/omf/solvers/ 'https://github.com/MATPOWER/matpower/releases/download/7.0/matpower7.0.zip'")
	# os.system(f"unzip '{source_dir}/omf/solvers/matpower7.0.zip' -d {source_dir}/omf/solvers/")
	# os.system(f'octave-cli --no-gui -p "{source_dir}/omf/solvers/matpower7.0" --eval "install_matpower(1,1,1)"')
	if not filePath: # create a temp file location for the RAW string
		now = datetime.datetime.now()
		rawfile_name = pJoin(omf.omfDir, 'temp' + now + '.raw')
		matfile_name = pJoin(omf.omfDir, 'temp' + now + '.m')
		with open(rawfile_name, 'w') as rawFile:
			rawFile.write(inputStr)
	else:
		rawfile_name = inputStr
		matfile_name = os.path.splitext(inputStr)[0] + '.m' 
	# Prepare Octave with correct path.
	matpowerDir =  pJoin(omf.omfDir,'solvers','matpower7.0')
	matPath = _getMatPath(matpowerDir)
	# TODO: Test code on Windows.
	if platform.system() == "Windows":
		# Find the location of octave-cli tool.
		envVars = os.environ["PATH"].split(';')
		octavePath = "C:\\Octave\\Octave-4.2.0"
		for pathVar in envVars:
			if "octave" in pathVar.lower():
				octavePath = pathVar
		# Run Windows-specific Octave command.
		command = 'psse2mpc(\'' + rawfile_name + '\', \'' + matfile_name + '\')'
		args = [octavePath + '\\bin\\octave-cli', '-p', matPath, '--eval', command]
		try:
			mat = subprocess.check_output(args, shell=False)
		except subprocess.CalledProcessError as e:
			raise ValueError('RAW file/string does not contain valid data.')
		finally:
			if not filePath:
				os.remove(rawfile_name)
	else:
		# Run UNIX Octave command.
		command = 'psse2mpc(\'' + rawfile_name + '\', \'' + matfile_name + '\')'
		args = 'octave -p ' + matPath + ' --no-gui --eval "' + command + '"'
		proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False)
		(out, err) = proc.communicate()
		if not filePath:
			os.remove(rawfile_name)
		if len(err) != 0:
			if '\'psse2mpc\' undefined' in err.decode("utf-8"):
				raise Exception('Matpower/Octave setup is incorrect.')
			else: 
				raise ValueError('RAW file/string does not contain valid data.')
	return matfile_name

def netToNxGraph(inNet):
	''' Convert network.omt to networkx graph. '''
	outGraph = nx.Graph()
	for compType in ['bus','gen','branch']:
		for idNum, item in inNet[compType].items():
			if 'fbus' in item.keys():
				outGraph.add_edge(item['fbus'],item['tbus'],attr_dict={'type':'branch'})
			elif compType=='bus':
				if item.get('bus_i',0) in outGraph:
					# Edge already led to node's addition, so just set the attributes:
					outGraph.node[item['bus_i']]['type']='bus'
				else:
					outGraph.add_node(item['bus_i'])
			elif compType=='gen':
				pass
	return outGraph

def latlonToNet(inGraph, inNet):
	''' Add lat/lon information to network json. '''
	cleanG = nx.Graph(inGraph.edges())
	cleanG.add_nodes_from(inGraph)
	# pos = nx.nx_agraph.graphviz_layout(cleanG, prog='neato')
	pos = nx.kamada_kawai_layout(cleanG)
	pos = {k:(1000 * pos[k][0],1000 * pos[k][1]) for k in pos} # get out of array notation
	for idnum, item in inNet['bus'].items():
		obName = item.get('bus_i')
		thisPos = pos.get(obName, None)
		if thisPos != None:
			inNet['bus'][idnum]['longitude'] = thisPos[0]
			inNet['bus'][idnum]['latitude'] = thisPos[1]
	return inNet

def netToMat(inNet, networkName):
	'''Convert a network dict to .m string. '''
	# Write header.
	matStr = []
	matStr.append('function mpc = '+networkName+'\n')
	matStr.append('%'+networkName+'\tThis is an OMF.network() generated .m file created from the transmission network saved in '+networkName+'.omt'+'\n')
	matStr.append('\n')
	matStr.append('%% MATPOWER Case Format : Version '+inNet.get('mpcVersion','2')+'\n')
	matStr.append('mpc.version = \''+inNet.get('mpcVersion','2')+'\';\n')
	matStr.append('\n')
	matStr.append('%%-----  Power Flow Data  -----%%\n')
	# Write bus voltage.
	matStr.append('%% system MVA base\n')
	matStr.append('mpc.baseMVA = '+inNet.get('baseMVA','100')+';\n')
	matStr.append('\n')
	# Write bus/gen/branch data.
	electricalKey = [
		['bus_i', 'type', 'Pd', 'Qd', 'Gs', 'Bs', 'area', 'Vm', 'Va', 'baseKV', 'zone', 'Vmax', 'Vmin'],
		['bus', 'Pg', 'Qg', 'Qmax', 'Qmin', 'Vg', 'mBase', 'status', 'Pmax', 'Pmin', 'Pc1', 'Pc2', 'Qc1min', 'Qc1max', 'Qc2min', 'Qc2max', 'ramp_agc', 'ramp_10', 'ramp_30', 'ramp_q', 'apf'],
		['fbus', 'tbus', 'r', 'x', 'b', 'rateA', 'rateB', 'rateC', 'ratio', 'angle', 'status', 'angmin', 'angmax']]
	for i,electrical in enumerate(['bus','gen','branch']):
		matStr.append('%% '+electrical+' data\n')
		matStr.append('%\t'+'\t'.join(str(x) for x in electricalKey[i])+'\n')
		matStr.append('mpc.'+electrical+' = [\n')
		for j,electricalDict in enumerate(inNet[electrical]):
			valueDict = inNet[electrical][str(electricalDict)]
			electricalValues = '\t'.join(valueDict[val] for val in electricalKey[i])
			matStr.append('\t'+electricalValues+';\n')
		matStr.append('];\n')
		matStr.append('\n')
	return matStr

def get_file_contents(filepath):
	with open(filepath) as f:
		return f.read()

def get_abs_path(relative_path):
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def _getMatPath(matDir):
	# Get paths required for matpower7.0 in octave
	if platform.system() == "Windows":
		pathSep = ";"
	else:
		pathSep = ":"
	relativePaths = ['lib', 'lib/t', 'data', 'mips/lib', 'mips/lib/t', 'most/lib', 'most/lib/t', 'mptest/lib', 'mptest/lib/t', 'extras/maxloadlim', 'extras/maxloadlim/tests', 'extras/maxloadlim/examples', 'extras/misc', 'extras/reduction', 'extras/sdp_pf', 'extras/se', 'extras/smartmarket', 'extras/state_estimator', 'extras/syngrid/lib','extras/syngrid/lib/t']
	paths = [matDir] + [pJoin(matDir, relativePath) for relativePath in relativePaths]
	matPath = '"' + pathSep.join(paths) + '"'
	return matPath

def viz(omt_filepath, output_path=None, output_name="viewer.html", open_file=True):
	"""
	Get a path to an .omt file that was saved on the server after a grip API consumer POSTed their desired .omt file.
	Render the .omt file data using the transEdit.html template and injected library code.
	"""
	if output_path is None:
		viewer_path = os.path.join(tempfile.mkdtemp(), output_name)
	else:
		viewer_path = os.path.join(output_path, output_name)
	shutil.copy(os.path.join(os.path.dirname(__file__), "templates/transEdit.html"), viewer_path)
	for line in fileinput.input(viewer_path, inplace=1):
		if line.lstrip().startswith("<script>networkData="):
			print("<script>networkData={}</script>".format(get_file_contents(omt_filepath)))
		elif line.lstrip().startswith('<script type="text/javascript" src="/static/svg-pan-zoom.js">'):
			print('<script type="text/javascript">{}</script>'.format(get_file_contents(os.path.join(os.path.dirname(__file__), "static/svg-pan-zoom.js"))))
		elif line.lstrip().startswith('<script type="text/javascript" src="/static/omf.js">'):
			print('<script type="text/javascript">{}</script>'.format(get_file_contents(os.path.join(os.path.dirname(__file__), "static/omf.js"))))
		elif line.lstrip().startswith('<script type="text/javascript" src="/static/jquery-1.9.1.js">'):
			print('<script type="text/javascript">{}</script>'.format(get_file_contents(os.path.join(os.path.dirname(__file__), "static/jquery-1.9.1.js"))))
		elif line.lstrip().startswith('<link rel="stylesheet" href="/static/omf.css"/>'):
			print('<style>{}</style>'.format(get_file_contents(os.path.join(os.path.dirname(__file__), "static/omf.css"))))
		elif line.lstrip().startswith('<link rel="shortcut icon" href="/static/favicon.ico"/>'):
			print('<link rel="shortcut icon" href="data:image/x-icon;base64,AAABAAEAEBAQAAAAAAAoAQAAFgAAACgAAAAQAAAAIAAAAAEABAAAAAAAgAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAioqKAGlpaQDU1NQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIiIiIiIiIAAgACAAIAAgACAzIzMjMyMwIDAgMCAwIDAiIiIiIiIgMCAwEDAgMCAwIDMTMyMzIzAgMBAwIDAgMCIiIiIiIiAwIDAQMCAwIDAgMxMzIzMjMCAwEDAgMCAwIiIiIiIiIDAAMAAwADAAMAAzMzMzMzMwAAAAAAAAAAAABwAAd3cAAEABAABVVQAAAAUAAFVVAABAAQAAVVUAAAAFAABVVQAAQAEAAFVVAAAABQAA3d0AAMABAAD//wAA"/>')
		elif line.lstrip().startswith('{%'):
			print("")
		else:
			print(line.rstrip())
	if open_file is True:
		webbrowser.open_new("file://" + viewer_path)


def _tests():
	# Parse mat to dictionary.
	networkName = 'case9'
	netPath = os.path.join(omf.omfDir, 'static', 'testFiles', networkName + '.m')
	print('NETPATH', netPath)
	os.system(f'ls {os.path.dirname(netPath)}')
	networkJson = parse(netPath, filePath=True)
	keyLen = len(networkJson.keys())
	print('Parsed MAT file with %s buses, %s generators, and %s branches.'%(len(networkJson['bus']),len(networkJson['gen']),len(networkJson['branch'])))
	# Parse raw to dictionary.
	# networkNameRaw = 'GO500v2_perfect_0'
	# netPathRaw = os.path.join(os.path.dirname(__file__), 'solvers', 'matpower7.0', 'data', 'test', networkNameRaw + '.raw')
	# networkJsonRaw = parseRaw(netPathRaw, filePath=True)
	# keyLenRaw = len(networkJsonRaw.keys())
	# print('Parsed RAW file with %s buses, %s generators, and %s branches.'%(len(networkJsonRaw['bus']),len(networkJsonRaw['gen']),len(networkJsonRaw['branch'])))
	# Use python nxgraph to add lat/lon to .omt.json.
	nxG = netToNxGraph(networkJson)
	networkJson = latlonToNet(nxG, networkJson)
	import tempfile
	temp_dir = tempfile.mkdtemp()
	omt_path = os.path.join(temp_dir, networkName + '.omt')
	with open(omt_path,'w') as inFile:
	#with open(pJoin(os.getcwd(),'scratch','transmission','outData',networkName+'.omt'),'w') as inFile:
		json.dump(networkJson, inFile, indent=4)
	print('Wrote network to: %s' % (omt_path))
	#print('Wrote network to: %s'%(pJoin(os.getcwd(),'scratch','transmission','outData',networkName+'.omt')))
	# Convert back to .mat and run matpower.
	matStr = netToMat(networkJson, networkName)
	mat_path = os.path.join(temp_dir, networkName + '.m')
	with open(mat_path, 'w') as outMat:
	#with open(pJoin(os.getcwd(),'scratch','transmission','outData',networkName+'.m'),'w') as outMat:
		for row in matStr: outMat.write(row)
	print('Converted .omt back to .m at: %s' % (mat_path))
	# Draw it.
	# viz(omt_path)
	#print('Converted .omt back to .m at: %s'%(pJoin(os.getcwd(),'scratch','transmission','outData',networkName+'.m')))
	#inputDict = {
	#	'algorithm' : 'FDBX',
	#	'model' : 'DC',
	#	'iteration' : 10,
	#	'tolerance' : math.pow(10,-8),
	#	'genLimits' : 0,
	#	}
	#matpower.runSim(os.path.join(temp_dir, networkName), inputDict, debug=False)
	#matpower.runSim(pJoin(os.getcwd(),'scratch','transmission','outData',networkName), inputDict, debug=False)

if __name__ == '__main__':
	_tests()