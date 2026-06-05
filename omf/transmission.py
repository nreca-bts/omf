"""
Read, write, lay out, and convert OMF transmission-network models, including CIM and
pandapower representations.
"""

import os, json, tempfile, shutil, fileinput, webbrowser
import networkx as nx
import omf

def parse(inputStr, filePath=True):
	''' Parse a MAT into an omf.network json. This is so we can walk the json, change things in bulk, etc.
	Input can be a filepath or MAT string. Raises ValueError if the MAT file/string does not contain valid data.
	'''
	matDict = _dictConversion(inputStr, filePath)
	return matDict

def parseCim(inputFiles, cgmes_version='2.4.15'):
	''' Parse CGMES/CIM XML or ZIP files into an omf.network json using pandapower's CIM importer.

	Input can be a filepath or a list of filepaths. Raises ValueError if the files cannot be converted.
	'''
	if isinstance(inputFiles, str):
		file_list = [inputFiles]
	else:
		file_list = list(inputFiles or [])
	if not file_list:
		raise ValueError('No CGMES/CIM files were provided.')
	from_cim = _get_pandapower_from_cim()
	try:
		pp_net = from_cim(file_list=file_list, cgmes_version=cgmes_version)
		return _pandapower_net_to_omt(pp_net)
	except ValueError:
		raise
	except Exception as err:
		raise ValueError('CGMES/CIM files could not be converted by pandapower.') from err

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

def _get_pandapower_from_cim():
	''' Return pandapower's from_cim callable across supported pandapower package layouts. '''
	try:
		from pandapower.converter.cim.cim2pp.from_cim import from_cim
	except Exception as first_err:
		try:
			from pandapower.converter.cim import from_cim
			if not callable(from_cim) and hasattr(from_cim, 'from_cim'):
				from_cim = from_cim.from_cim
		except Exception as second_err:
			raise ImportError('The installed pandapower package does not include the CGMES/CIM converter.') from second_err
		if not callable(from_cim):
			raise ImportError('The installed pandapower package does not include the CGMES/CIM converter.') from first_err
	return from_cim

def _pandapower_net_to_omt(pp_net):
	''' Convert a pandapower net into the MATPOWER-shaped OMT dictionary used by transEdit.html. '''
	try:
		from pandapower.converter import to_mpc
	except Exception as err:
		raise ImportError('The installed pandapower package does not include MATPOWER conversion support.') from err
	try:
		mpc_wrapper = to_mpc(pp_net, init='flat', calculate_voltage_angles=True, check_connectivity=False)
	except TypeError:
		mpc_wrapper = to_mpc(pp_net, init='flat')
	mpc = mpc_wrapper.get('mpc', mpc_wrapper)
	network = {
		"baseMVA": _matpower_value_to_string(mpc.get('baseMVA', 100)),
		"mpcVersion": str(mpc.get('version', '2')),
		"bus": {},
		"gen": {},
		"branch": {}
	}
	bus_keys = ['bus_i', 'type', 'Pd', 'Qd', 'Gs', 'Bs', 'area', 'Vm', 'Va', 'baseKV', 'zone', 'Vmax', 'Vmin']
	gen_keys = ['bus', 'Pg', 'Qg', 'Qmax', 'Qmin', 'Vg', 'mBase', 'status', 'Pmax', 'Pmin', 'Pc1', 'Pc2',
		'Qc1min', 'Qc1max', 'Qc2min', 'Qc2max', 'ramp_agc', 'ramp_10', 'ramp_30', 'ramp_q', 'apf']
	branch_keys = ['fbus', 'tbus', 'r', 'x', 'b', 'rateA', 'rateB', 'rateC', 'ratio', 'angle', 'status',
		'angmin', 'angmax']
	for i, row in enumerate(mpc.get('bus', [])):
		network['bus'][str(i + 1)] = _matpower_row_to_dict(row, bus_keys)
	for i, row in enumerate(mpc.get('gen', [])):
		network['gen'][str(i + 1)] = _matpower_row_to_dict(row, gen_keys)
	for i, row in enumerate(mpc.get('branch', [])):
		network['branch'][str(i + 1)] = _matpower_row_to_dict(row, branch_keys)
	if not network['bus']:
		raise ValueError('CGMES/CIM files did not produce any buses.')
	_add_pandapower_bus_coordinates(pp_net, network)
	return network

def _matpower_row_to_dict(row, keys):
	"""
	Internal helper for transmission matpower row to dict processing.
	"""
	return {key: _matpower_value_to_string(row[i]) if i < len(row) else '0' for i, key in enumerate(keys)}

def _matpower_value_to_string(value):
	"""
	Internal helper for transmission matpower value to string processing.
	"""
	try:
		numeric_value = float(value)
	except (TypeError, ValueError):
		return str(value)
	if numeric_value != numeric_value:
		return '0'
	if numeric_value.is_integer():
		return str(int(numeric_value))
	return format(numeric_value, '.12g')

def _add_pandapower_bus_coordinates(pp_net, network):
	''' Preserve CGMES GL/DL coordinates from pandapower when the import provides them. '''
	if not hasattr(pp_net, 'bus') or pp_net.bus is None:
		return
	bus_lookup = getattr(pp_net, '_pd2ppc_lookups', {}).get('bus')
	bus_by_i = {bus.get('bus_i'): bus for bus in network['bus'].values()}
	for pp_bus_index, pp_bus in pp_net.bus.iterrows():
		coords = _extract_pandapower_point(pp_bus.get('geo'))
		if coords is None:
			coords = _extract_pandapower_point(pp_bus.get('diagram'))
		if coords is None:
			continue
		try:
			ppc_bus_index = int(bus_lookup[int(pp_bus_index)])
		except Exception:
			ppc_bus_index = int(pp_bus_index)
		for candidate in [ppc_bus_index, ppc_bus_index + 1]:
			bus = bus_by_i.get(_matpower_value_to_string(candidate))
			if bus is not None:
				bus['longitude'] = coords[0]
				bus['latitude'] = coords[1]
				break

def _extract_pandapower_point(raw_geo):
	"""
	Internal helper for transmission extract pandapower point processing.
	"""
	if raw_geo is None or raw_geo != raw_geo:
		return None
	try:
		geo = json.loads(raw_geo) if isinstance(raw_geo, str) else raw_geo
		coords = geo.get('coordinates') if isinstance(geo, dict) else None
		if not isinstance(coords, list) or len(coords) < 2 or isinstance(coords[0], list):
			return None
		return [float(coords[0]), float(coords[1])]
	except Exception:
		return None

def _dictToString(inDict):
	''' Helper function: given a single dict representing a NETWORK, concatenate it into a string. '''
	return ''

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
	"""
	Return the file contents needed by this workflow.
	"""
	with open(filepath) as f:
		return f.read()

def get_abs_path(relative_path):
	"""
	Return the abs path needed by this workflow.
	"""
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

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
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	networkName = 'case9'
	netPath = os.path.join(omf.omfDir, 'static', 'testFiles', networkName + '.m')
	print('NETPATH', netPath)
	os.system(f'ls {os.path.dirname(netPath)}')
	networkJson = parse(netPath, filePath=True)
	keyLen = len(networkJson.keys())
	print('Parsed MAT file with %s buses, %s generators, and %s branches.'%(len(networkJson['bus']),len(networkJson['gen']),len(networkJson['branch'])))
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
