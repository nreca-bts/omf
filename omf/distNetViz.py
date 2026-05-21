"""
Prepare OMF feeder data for the distribution-network viewer, including coordinate
insertion, component extraction, and local visualization launch helpers.
"""

import tempfile, shutil, os, fileinput, json, webbrowser, sys
import networkx as nx
from jinja2 import Template
import omf
import omf.feeder
from omf.solvers import opendss
from omf.solvers.opendss import dssConvert

def _tests():
	''' Handle the command line arguments for distNetViz.'''
	argCount = len(sys.argv)
	errorMessage = 'Incorrect inputs. Usage: distNetViz [-f (force layout)] <Path_to_feeder.glm/.omd/.dss>'
	if argCount == 1:
		print('Running tests. Normal usage: distNetViz [-f (force layout)] <Path_to_feeder.glm/.omd/.dss>')
		viz(omf.omfDir + '/static/publicFeeders/Simple Market System.omd', forceLayout=True, open_file=False) # No coordinates
		viz(omf.omfDir + '/static/publicFeeders/Simple Market System.omd', forceLayout=False, open_file=False) # No coordinates
		viz(omf.omfDir + '/static/testFiles/IEEE13.glm', forceLayout=True, open_file=False) # Has coordinates
		viz(omf.omfDir + '/static/testFiles/IEEE13.glm', forceLayout=False, open_file=False) # Has coordinates
		return
	elif argCount == 2:
		print('Beginning display of ' + sys.argv[1])
		DO_FORCE_LAYOUT = False
		FEEDER_PATH = sys.argv[1]
	elif argCount == 3:
		print('Force laying out and displaying ' + sys.argv[2])
		if sys.argv[1] == '-f':
			DO_FORCE_LAYOUT = True
		else:
			print(errorMessage)
		FEEDER_PATH = sys.argv[2]
	elif argCount > 3:
		print(errorMessage)
	viz(FEEDER_PATH, forceLayout=DO_FORCE_LAYOUT, outputPath=None)

def insert_coordinates(tree):
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
			tree[key]['longitude'] = thisPos[0]
			tree[key]['latitude'] = thisPos[1]

def contains_valid_coordinates(tree):
	'''
	Return True if the tree contains at least one object with a latitude or longitude property that can be parsed as a float, otherwise False.
	'''
	for key in tree:
		for sub_key in ['latitude', 'longitude']:
			if sub_key in tree[key]:
				try:
					float(tree[key][sub_key])
				except:
					return False
				else:
					return True
	return False

# - TODO: move this into geo.py once the old editor is deprecated so that this whole file is easier to deprecate. Some imports will need to be changed
def get_components():
	"""
	Return the components needed by this workflow.
	"""
	directory = os.path.join(omf.omfDir, "data/Component")
	components = {}
	for dirpath, dirnames, file_names in os.walk(directory):
		for name in file_names:
			if name.endswith(".json"):
				path = os.path.join(dirpath, name)
				with open(path) as f:
					components[name[0:-5]] = json.load(f) # Load the file as a regular object into the dictionary
	return json.dumps(components) # Turn the dictionary of objects into a string

def viz_mem(feederTreeObj, forceLayout=False, outputPath=None, outputName='viewer.html', open_file=True):
	''' Visualize a distribution system that's already in memory. '''
	tempdir = tempfile.mkdtemp()
	omf.feeder.dump(feederTreeObj, tempdir + '/temp.glm')
	viz(tempdir + '/temp.glm', forceLayout=forceLayout, outputPath=outputPath, outputName=outputName, open_file=open_file)

def viz(pathToOmdOrGlm, forceLayout=False, outputPath=None, outputName='viewer.html', open_file=True):
	''' Vizualize a distribution system.'''
	# HACK: make sure we have our homebrew binaries available.
	os.environ['PATH'] += os.pathsep + '/usr/local/bin'
	# Load in the feeder.
	with open(pathToOmdOrGlm,'r') as feedFile:
		if pathToOmdOrGlm.endswith('.omd'):
			omd = json.load(feedFile)
			thisFeed = {'tree':omd['tree']} # TODO: later bring back attachments.
			dss_schema = True if omd.get('syntax','') == 'DSS' else False
		elif pathToOmdOrGlm.endswith('.glm'):
			thisFeed = {'tree':omf.feeder.parse(pathToOmdOrGlm, filePath=True)}
			dss_schema = False
		elif pathToOmdOrGlm.endswith('.dss'):
			thisTree = dssConvert.dssToTree(pathToOmdOrGlm)
			thisFeed = {'tree':dssConvert.evilDssTreeToGldTree(thisTree)}
			dss_schema = True
		tree = thisFeed['tree']
	## Force layout of feeders with no lat/lon information so we can actually see what's there.
	if forceLayout:
		print('forceLayout was set to True, so force layout is applied regardless of coordinate detection.')
		insert_coordinates(tree)
	elif not contains_valid_coordinates(tree):
		print('Warning: no lat/lon coordinates detected, so force layout required.')
		insert_coordinates(tree)
	# Set up temp directory and copy the feeder and viewer in to it.
	if outputPath is None:
		tempDir = tempfile.mkdtemp()
	else:
		tempDir = os.path.abspath(outputPath)
	#HACK: make sure we get the required files from the right place.
	# shutil.copy(omf.omfDir + '/templates/distNetViz.html', tempDir + '/' + outputName)
	# shutil.copy(omf.omfDir + '/static/svg-pan-zoom.js', tempDir + '/svg-pan-zoom.js')
	# Grab the library we need.
	with open(omf.omfDir + '/static/svg-pan-zoom.js','r') as pzFile:
		pzData = pzFile.read()
	with open(omf.omfDir + '/static/geoJsonMap/v3/lib/chroma.js','r') as chromaFile:
		chromaData = chromaFile.read()
	with open(omf.omfDir + '/static/geoJsonMap/v3/lib/papaparse.js','r') as papaFile:
		papaData = papaFile.read()
	with open(omf.omfDir + '/static/jquery.js', 'r') as jquery_file:
		jquery_data = jquery_file.read()
	with open(omf.omfDir + '/static/jquery-ui.js', 'r') as jquery_ui_file:
		jquery_ui_data = jquery_ui_file.read()
	with open(omf.omfDir + '/static/jquery-ui.css', 'r') as jquery_css_file:
		jquery_css_data = jquery_css_file.read()
	# TEMPLATE HACKING
	with open(omf.omfDir + '/templates/distNetViz.html') as f:
		templateString = f.read()
	template = Template(templateString)
	def id():
		return ""
	component_json = get_components()
	rend = template.render(thisFeederData=json.dumps(thisFeed), thisFeederName=pathToOmdOrGlm, thisFeederNum=1,
		thisModelName="Local Filesystem", thisOwner="NONE", components=component_json, jasmine=None, spec=None,
		publicFeeders=[], userFeeders=[], csrf_token=id, showFileMenu=False, currentUser=None, dssSchema=dss_schema
	)
	with open(tempDir + '/' + outputName, 'w') as outFile:
		outFile.write(rend)
	# Insert the panZoom library.
	# Note: you can't juse open the file in r+ mode because, based on the way the file is mapped to memory, you can only overwrite a line with another
	# of exactly the same length.
	with fileinput.input(tempDir + '/' + outputName, inplace=1) as f:
		for line in f:
			if line.lstrip().startswith('<link rel="stylesheet" href="/static/jquery-ui.css">'):
				print("")
			elif line.lstrip().startswith('<script type="text/javascript" src="/static/jquery.js"></script>'):
				print("")
			elif line.lstrip().startswith('<script type="text/javascript" src="/static/jquery-ui.js"></script>'):
				print("")
			elif line.lstrip().startswith('<script type="text/javascript" src="/static/svg-pan-zoom.js"></script>'):
				print("")
			elif line.lstrip().startswith('<script type="text/javascript" src="/static/geoJsonMap/v3/lib/chroma.js"></script>'):
				print("")
			elif line.lstrip().startswith('<script type="text/javascript" src="/static/geoJsonMap/v3/lib/papaparse.js"></script>'):
				print("")
			elif line.lstrip().startswith('<link rel="shortcut icon" href="/static/favicon.ico"/>'):
				print('<link rel="shortcut icon" href="data:image/x-icon;base64,AAABAAEAEBAQAAAAAAAoAQAAFgAAACgAAAAQAAAAIAAAAAEABAAAAAAAgAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAioqKAGlpaQDU1NQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIiIiIiIiIAAgACAAIAAgACAzIzMjMyMwIDAgMCAwIDAiIiIiIiIgMCAwEDAgMCAwIDMTMyMzIzAgMBAwIDAgMCIiIiIiIiAwIDAQMCAwIDAgMxMzIzMjMCAwEDAgMCAwIiIiIiIiIDAAMAAwADAAMAAzMzMzMzMwAAAAAAAAAAAABwAAd3cAAEABAABVVQAAAAUAAFVVAABAAQAAVVUAAAAFAABVVQAAQAEAAFVVAAAABQAA3d0AAMABAAD//wAA"/>')
			elif line.lstrip().startswith('<script id="panZoomInsert">'):
				print('<script id="panZoomInsert">\n' + pzData) # load up the new feeder.
			elif line.lstrip().startswith('<script id="chromaInsert">'):
				print('<script id="chromaInsert">\n' + chromaData)
			elif line.lstrip().startswith('<script id="papaParseInsert">'):
				print('<script id="papaParseInsert">\n' + papaData)
			elif line.lstrip().startswith('<script id="jqueryInsert">'):
				print('<script id="jqueryInsert">\n' + jquery_data)
			elif line.lstrip().startswith('<script id="jqueryUiInsert">'):
				print('<script id="jqueryUiInsert">\n' + jquery_ui_data)
			elif line.lstrip().startswith('<style id="jqueryCssInsert">'):
				print('<style id="jqueryCssInsert">\n' + jquery_css_data)
			else:
				print(line.rstrip())
	# os.system('open -a "Google Chrome" ' + '"file://' + tempDir + '/' + outputName"')
	# webbrowser.open_new("file://" + tempDir + '/' + outputName)
	if open_file:
		open_browser(tempDir, outputName)

def open_browser(tempDir, outputName):
	"""
	Perform open browser processing for OMF helper-library workflows.
	"""
	webbrowser.open_new("file://" + tempDir + '/' + outputName)

if __name__ == '__main__':
	_tests()
	#viz('/Users/tuomastalvitie/OneDrive/NRECA Code/DEC Robinsonville Original.omd', forceLayout=False, outputPath=None)
	#viz('C:\Users\Tuomas\SkyDrive\NRECA Code\Utility Data\DEC Robinsonville Substation\DEC Robinsonville Original.omd', forceLayout=False, outputPath=None)
	# viz('/Users/dpinney/Desktop/LATERBASE/NRECA/GridBallast/DM1.3.1 Go-No-Go - Demonstration of GridBallast Performance in Simulation - FINISHED/Utility Data/DEC Robinsonville Substation/DEC Robinsonville Original.omd', forceLayout=False, outputPath=None)
	# viz('static/publicFeeders/ieee37fixed.omd', forceLayout=True)
	# viz('static/publicFeeders/DEC Red Base.omd', forceLayout=True)
	# viz('static/publicFeeders/Olin Barre Geo.omd', forceLayout=True)
	# viz('static/publicFeeders/greensboro_NC_rural.omd')
	viz('static/publicFeeders/ieee240.dss.omd', forceLayout=False)
	# viz('/Users/ryanmahoney/omf/omf/scratch/RONM/nreca1824cleanCoords.dss.omd')