"""
Provide shared lifecycle, metadata, rendering, process, and filesystem helpers used by
OMF model modules.
"""

import json, os, tempfile, webbrowser, math, shutil, datetime, multiprocessing, traceback, hashlib, re, pathlib
from os.path import join as pJoin
from os.path import split as pSplit
from functools import wraps
from jinja2 import Template
import pandas as pd
import omf.models
from omf import web

# Locational variables so we don't have to rely on OMF being in the system path.
_myDir = os.path.dirname(os.path.abspath(__file__))
_omfDir = os.path.dirname(_myDir)

def metadata(fileUnderObject):
	''' Get the model name and template for a given model from its filename and associated .html file.
	The argument fileUnderObject should always be __file__.'''
	fileName = os.path.basename(fileUnderObject)
	modelName = fileName[0:fileName.rfind('.')]
	with open(pJoin(_myDir, modelName+".html")) as f:
		template = Template(f.read()) #HTML Template for showing output.
	return modelName, template

def heavyProcessing(modelDir, test_mode=False):
	''' Wrapper to handle model running safely and uniformly. '''
	try:
		# Start a timer.
		startTime = datetime.datetime.now()
		# Get the inputs.
		with web.locked_open(pJoin(modelDir, 'allInputData.json')) as f:
			inputDict = json.load(f)
		# Place run start time.
		inputDict['runStartTime'] = startTime.isoformat()
		# Estimate runtime if possible.
		try:
			inputDict['runtimeEst_min'] = getattr(omf.models, inputDict['modelType']).runtimeEstimate(modelDir)
		except:
			pass
		# Write input with new synth inputs.
		with web.locked_open(pJoin(modelDir,"allInputData.json"),"w") as inFile:
			json.dump(inputDict, inFile, indent=4)
		# Remove old outputs.
		try:
			os.remove(pJoin(modelDir,"allOutputData.json"))
		except Exception as e:
			pass
		# Get the function and run it.
		work = getattr(omf.models, inputDict['modelType']).work
		#This grabs the new outData model
		outData = work(modelDir, inputDict)
		#print("!!!!!!! thing !!!!!!!!") # DEBUG
	except Exception as e:
		# cancel(modelDir)
		if test_mode == True:
			raise e
		# If input range wasn't valid delete output, write error to disk.
		thisErr = traceback.format_exc()
		print('ERROR IN MODEL', modelDir, thisErr)
		inputDict['stderr'] = thisErr
		with web.locked_open(os.path.join(modelDir,'stderr.txt'),'w') as errorFile:
			errorFile.write(thisErr)
	else:
		# No errors, so update the runTime in the input file.
		endTime = datetime.datetime.now()
		inputDict["runTime"] = str(datetime.timedelta(seconds=int((endTime - startTime).total_seconds())))
		# Write output.
		modelType = inputDict["modelType"]
		#Get current file hashes and dd to the output
		with open(pJoin(_myDir, modelType+".html")) as f:
			htmlFile = f.read()
		currentHtmlHash = hashlib.sha256(htmlFile.encode('utf-8')).hexdigest()
		with open(pJoin(_myDir, modelType+".py")) as f:
			pythonFile = f.read()
		currentPythonHash = hashlib.sha256(pythonFile.encode('utf-8')).hexdigest()
		outData['htmlHash'] = currentHtmlHash
		outData['pythonHash'] = currentPythonHash
		outData['oldVersion'] = False
		# Raw input/output file names.
		outData['fileNames'] = os.listdir(modelDir)
		outData['fileNames'].append('allOutputData.json')
		with web.locked_open(pJoin(modelDir, "allOutputData.json"),"w") as outFile:
			json.dump(outData, outFile, indent=4)
	finally:
		# Clean up by updating input data.
		try:
			with web.locked_open(pJoin(modelDir,"allInputData.json"),"w") as inFile:
				json.dump(inputDict, inFile, indent=4)
		except: pass
		try: os.remove(pJoin(modelDir,"PPID.txt"))
		except: pass

def run(modelDir):
	''' Run the model in a separate process. web.py calls this to run the model.
	This function will return fast, but results take a while to hit the file system.'''
	backProc = multiprocessing.Process(target = heavyProcessing, args = (modelDir,))
	backProc.start()
	with web.locked_open(pJoin(modelDir, "PPID.txt"),"w+") as pPidFile:
		pPidFile.write(str(backProc.pid))
	print("SENT TO BACKGROUND", modelDir)

def runForeground(modelDir):
	''' Run all model work immediately in the same thread. '''
	with web.locked_open(pJoin(modelDir, "PPID.txt"),"w+") as pPidFile:
		pPidFile.write('-999') # HACK: put in an invalid PID to indicate the model is running.
	print("FOREGROUND RUNNING", modelDir)
	heavyProcessing(modelDir)

def renderTemplate(modelDir, absolutePaths=False, datastoreNames={}):
	''' Render the model template to an HTML string.
	By default render a blank one for new input.
	If modelDir is valid, render results post-model-run.
	If absolutePaths, the HTML can be opened without a server. '''
	try:
		with web.locked_open(pJoin(modelDir, 'allInputData.json')) as f:
			inJson = json.load(f)
		modelPath, modelName = pSplit(modelDir)
		deepPath, modelOwner = pSplit(modelPath)
		inJson["modelName"] = modelName
		inJson["user"] = modelOwner
		modelType = inJson["modelType"]
		template = getattr(omf.models, modelType).template
		allInputData = json.dumps(inJson)
		# Get hashes for model python and html files 
		with open(pJoin(_myDir, modelType+".html")) as f:
			htmlFile = f.read()
		currentHtmlHash = hashlib.sha256(htmlFile.encode('utf-8')).hexdigest()
		with open(pJoin(_myDir, modelType+".py")) as f:
			pythonFile = f.read()
		currentPythonHash = hashlib.sha256(pythonFile.encode('utf-8')).hexdigest()
	except IOError:
		allInputData = None
		inJson = None
	try:
		with web.locked_open(pJoin(modelDir,"allOutputData.json")) as f:
			allOutputData = f.read()
		with web.locked_open(pJoin(modelDir, "allOutputData.json")) as f:
			outJson = json.load(f)
		try:
			#Needed? Should this be handled a different way? Add hashes to the output if they are not yet present
			if ('pythonHash' not in outJson) or ('htmlHash' not in outJson):
				outJson['htmlHash'] = currentHtmlHash
				outJson['pythonHash'] = currentPythonHash
				outJson['oldVersion'] = False
			#If the hashes do not match, mark the model as an old version
			elif outJson['htmlHash'] != currentHtmlHash or outJson['pythonHash'] != currentPythonHash:
				outJson['oldVersion'] = True
			#If the hashes match, mark the model as up to date
			else:	
				outJson['oldVersion'] = False
		except (UnboundLocalError, KeyError) as e:
			print((traceback.print_exc()))
			print(('error:' + str(e)))
	except IOError:
		allOutputData = None
		outJson = None
	if absolutePaths:
		# Parent of current folder.
		pathPrefix = _omfDir
	else:
		pathPrefix = ""
	# Generate standard raw output files.
	rawFilesTemplate = '''
		<p class="reportTitle">Raw Input and Output Files</p>
		<div id="rawOutput" class="content" style="margin-top:0px">
			{% for name in allOutputDataDict['fileNames'] %}
				{% if loop.index > 1 %}&mdash; {% endif %}<a href="/downloadModelData/{{allInputDataDict['user']}}/{{allInputDataDict['modelName']}}/{{name}}">{{name}}</a>
			{% endfor %}
		</div>
	'''
	rawOutputFiles = Template(rawFilesTemplate).render(allOutputDataDict=outJson, allInputDataDict=inJson)
	# Generate standard model buttons.
	omfModelButtonsTemplate = '''
		<div class="wideInput" style="text-align:right">
		{% if modelStatus != 'running' and (loggedInUser == modelOwner or loggedInUser == 'admin') %}
		<button id="deleteButton" type="button" onclick="deleteModel()">Delete</button>
		<button id="runButton" type="submit">Run Model</button>
		{% endif %}
		{% if modelStatus == "finished" and (loggedInUser == modelOwner or loggedInUser == 'admin') %}
		<button id="shareButton" type="button" onclick="shareModel()">Share</button>
		{% endif %}
		{% if modelStatus == "finished" %}
		<button id="duplicateButton" type="button" onclick="duplicateModel()">Duplicate</button>
		{% endif %}
		{% if modelStatus == "running" and (loggedInUser == modelOwner or loggedInUser == 'admin') %}
		<button id="cancelButton" type="button" onclick="cancelModel()">Cancel Run</button>
		{% endif %}
	</div>
	'''
	# Generate standard OMF headers.
	modelStatus = getStatus(modelDir)
	loggedInUser = datastoreNames.get('currentUser', 'test')
	omfHeadersTemplate = '''
		<title>Open Modeling Framework - {{allInputDataDict.modelType}} - {{allInputDataDict.modelName}}</title>
		<meta charset="utf-8">
		<link href="{{pathPrefix}}/static/omf.css" type="text/css" rel="stylesheet"/>
		<link rel="shortcut icon" href="{{pathPrefix}}/static/favicon.ico">
		{% if modelStatus == "running" %}<meta http-equiv="refresh" content="5"/>{% endif %}
		<script type="text/javascript" src="{{pathPrefix}}/static/omf.js"></script>
		<script type="text/javascript" src="{{pathPrefix}}/static/jquery-1.9.1.js"></script>
		<script>allInputData={% if allInputDataDict %}{{allInputDataDict | tojson}}{% else %}null{% endif %}</script>
		<script>allOutputData={% if allOutputDataDict %}{{allOutputDataDict | tojson}}{% else %}null{% endif %}</script>
		<script>currentUser="{{loggedInUser}}"</script>
		<script>modelStatus="{{modelStatus}}"</script>'''
	omfHeaders = Template(omfHeadersTemplate).render(modelStatus=modelStatus, loggedInUser=loggedInUser, allInputDataDict=inJson, allOutputDataDict=outJson, pathPrefix=pathPrefix)
	# Generate standard OMF model title.
	omfModelTitleTemplate = '''
		<div id="header">
			<div id="headInnerBlock">
				<div id="menuLeft">
					<a style="color:white" href="/">Open Modeling Framework</a>
					<p id="titleText" style="display:inline">&#187;&nbsp; {{allInputDataDict.modelType}} &#187;&nbsp; &#8220;{{allInputDataDict.modelName}}&#8221;</p>
				</div>
			</div>
		</div>
		<div id="triangle-parent">
			<div id="triangle-message">New Version<span class="classic-triangle">A new version of the model has been added to the OMF. To get the new outputs, please fill in any missing inputs and hit "Run Model". You can also just look at the old inputs, outputs.</span></div>
			<div id="triangle-topright"></div>
		</div>
		<script>{% if allOutputDataDict['oldVersion'] %}document.getElementById("triangle-parent").style.visibility = "visible";{% endif %}</script>
		'''
	omfModelTitle = Template(omfModelTitleTemplate).render(allInputDataDict=inJson, allOutputDataDict=allOutputData)
	# Generate standard status content.
	omfModelButtons = Template(omfModelButtonsTemplate).render(modelStatus=modelStatus, loggedInUser=loggedInUser, modelOwner=modelOwner)
	now = datetime.datetime.now()
	try:
		mod_start = datetime.datetime.fromisoformat(inJson.get('runStartTime'))
	except:
		mod_start = now
	elapsed_dt = now - mod_start
	elapsed_min = elapsed_dt.total_seconds() / 60.0
	model_estimate_min = float(inJson.get('runtimeEst_min', '2.0'))
	remain_min = model_estimate_min - elapsed_min 
	runDebugTemplate = '''
		{% if modelStatus == 'running' %}
		<div id ="runIndicator" class="content">
			Model has run for {{elapsed_min}} minutes. {{remain_min}} minutes estimated until completion. Results updated every 5 seconds.
		</div>
		{% endif %}
		{% if modelStatus == 'stopped' and stderr != '' %}
		<div id ="stopIndicator" class="content">
			<pre id='errorText' style='overflow-x:scroll'>MODEL ENCOUNTERED AN ERROR AS FOLLOWS:\n\n{{stderr}}</pre>
		</div>
		{% endif %}
		'''
	omfRunDebugBlock = Template(runDebugTemplate).render(modelStatus=modelStatus, stderr=inJson.get('stderr', ''), elapsed_min=round(elapsed_min,2), remain_min=round(remain_min,2))
	# Raw input output include.
	return template.render(allInputData=allInputData, allOutputData=allOutputData, modelStatus=modelStatus, pathPrefix=pathPrefix,
		datastoreNames=datastoreNames, modelName=modelType, allInputDataDict=inJson, allOutputDataDict=outJson, rawOutputFiles=rawOutputFiles, omfModelButtons=omfModelButtons, omfRunDebugBlock=omfRunDebugBlock, omfHeaders=omfHeaders, omfModelTitle=omfModelTitle)

def renderAndShow(modelDir, datastoreNames={}):
	''' Render and open a template (blank or with output) in a local browser. '''
	with tempfile.NamedTemporaryFile('w', suffix=".html", delete=False) as temp:
		temp.write(renderTemplate(modelDir, absolutePaths=True))
		temp.flush()
		webbrowser.open("file://" + temp.name)

def renderTemplateToFile(model_dir, datastoreNames={}):
	''' Render and open a template (blank or with output) in a local browser. '''
	html = omf.models.__neoMetaModel__.renderTemplate(model_dir, absolutePaths=False)
	ptrn = r'<(?:\w+) (.*)(?:href=|src=)(?:\'|\")(\/static[^\'\"]*)(?:\'|\")'
	lines = html.splitlines()
	for idx, line in enumerate(lines):
		mo = re.search(ptrn, line)
		if mo:
			attrs = mo.group(1)
			path = mo.group(2).lstrip('/')
			if path[-4:] == '.css':
				with (pathlib.Path(omf.omfDir) / path).resolve(True).open() as f:
					content = f.read()
				lines[idx] = f'<style>\n{content}\n</style>'
			elif path[-3:] == '.js':
				with (pathlib.Path(omf.omfDir) / path).resolve(True).open() as f:
					content = f.read()
				lines[idx] = f'<script>\n{content}\n</script>'
			elif path[-5:] == '.html':
				with (pathlib.Path(omf.omfDir) / path).resolve(True).open() as f:
					content = f.read()
				lines[idx] = f'<iframe {attrs}>\n{content}\n</iframe>'
	with open(f'{model_dir}/inlineTemplate.html', 'w') as f:
		for line in lines:
			f.write(line + '\n')

def getStatus(modelDir):
	''' Is the model stopped, running or finished? '''
	try:
		modFiles = os.listdir(modelDir)
	except:
		modFiles = []
	hasPID = "PPID.txt" in modFiles
	hasOutput = "allOutputData.json" in modFiles
	if hasPID:
		return 'running'
	elif hasOutput:
		return 'finished'
	else:
		return 'stopped'

def new(modelDir, defaultInputs):
	''' Create a new instance of a model. Returns true on success, false on failure. '''
	alreadyThere = os.path.isdir(modelDir) or os.path.isfile(modelDir)
	try:
		if not alreadyThere:
			os.makedirs(modelDir)
		else:
			defaultInputs["created"] = str(datetime.datetime.now())
			with web.locked_open(pJoin(modelDir, "allInputData.json"),"w") as inputFile:
				json.dump(defaultInputs, inputFile, indent = 4)
			return False
		defaultInputs["created"] = str(datetime.datetime.now())
		with web.locked_open(pJoin(modelDir, "allInputData.json"),"w") as inputFile:
			json.dump(defaultInputs, inputFile, indent = 4)
		return True
	except:
		return False

def cancel(modelDir):
	''' Try to cancel a currently running model. '''
	# Kill the GridLAB-D process if it has already been created. If GridLAB-D hasn't created a PID.txt file, or GridLAB-D never ran, keep going
	try:
		with web.locked_open(pJoin(modelDir,"PID.txt"),"r") as pidFile:
			pid = int(pidFile.read())
		# print "pid " + str(pid)
		os.kill(pid, 15)
		print("PID KILLED")
	except:
		pass
	# Kill the runForeground process if it has already been created. If __neoMetaModel__.py hasn't created a PPID.txt file yet, keep going
	try:
		with web.locked_open(pJoin(modelDir, "PPID.txt"), "r") as pPidFile:
			pPid = int(pPidFile.read())
		os.kill(pPid, 15)
		print("PPID KILLED")
	except:
		pass
	# Remove PID, PPID, and allOutputData file if existed
	for fName in ['PID.txt', 'PPID.txt', 'allOutputData.json']:
		try: 
			os.remove(pJoin(modelDir,fName))
		except:
			pass
	print("CANCELED", modelDir)

def roundSig(x, sig=3):
	''' Round to a given number of sig figs. '''
	roundPosSig = lambda y,sig: round(y, sig-int(math.floor(math.log10(y)))-1)
	if x == 0: return 0
	elif x!=x: return 0 # This is handling float's NaN.
	elif x < 0: return -1*roundPosSig(-1*x, sig)
	else: return roundPosSig(x, sig)

def safe_assert(bool_statement, error_str, keep_running):
	"""
	Perform safe assert processing for the neo meta model model.
	"""
	if keep_running:
		if not bool_statement:
			print(error_str)
	else:
		assert bool_statement, error_str


def csvValidateAndLoad(file_input, modelDir, header=0, nrows=8760, ncols=1, dtypes=[], return_type='list_by_col', ignore_nans=False, save_file=None, ignore_errors=False):
	"""
		Safely validates, loads, and saves user's file input for model's use.

		Parameters:
		file_input: stream from input_dict to be read
		modelDir: a temporary or permanent file saved to given location
		header: row of header, enter "None" if no header provided.
		nrows: skip confirmation if None
		ncols: skip confirmation if None
		dtypes: dtypes as columns should be parsed. If empty, no parsing. 
						Use "False" for column index where there should be no parsing.
					 	This can be used as any mapping function.
		return_type: options: 'dict', 'df', 'list_by_col', 'list_by_row'
		ignore_nans: Ignore NaN values
		save_file: if not None, save file with given *relative* pathname. It will be appended to modelDir
		ignore_errors (bool): if True, allow program to keep running when errors found and print

		Returns:
		Datatype as dictated by input parameters
	"""

	# save temporary file
	temp_path = os.path.join(modelDir, 'csv_temp.csv') if save_file == None else os.path.join(modelDir, save_file)
	with open(temp_path, 'w') as f:
		f.write(file_input)
	df = pd.read_csv(temp_path, header=header)
	
	if nrows != None:
		safe_assert( df.shape[0] == nrows, (
			f'Incorrect CSV size. Required: {nrows} rows. Given: {df.shape[0]} rows.'
		), ignore_errors)

	if ncols != None:
		safe_assert( df.shape[1] == ncols, (
			f'Incorrect CSV size. Required: {ncols} columns. Given: {df.shape[1]} columns.'
		), ignore_errors)
	
	# NaNs
	if not ignore_nans:
		d = df.isna().any().to_dict()
		nan_columns = [k for k, v in d.items() if v]
		safe_assert( 
			len(nan_columns) == 0, 
			f'NaNs detected in columns {nan_columns}. Please adjust your CSV accordingly.',
			ignore_errors
		)
	
	# parse datatypes
	safe_assert(
		(len(dtypes) == 0) or (len(dtypes) == ncols), 
		f"Length of dtypes parser must match ncols, you've entered {len(dtypes)}. If no parsing, provide empty array.",
		ignore_errors
	)
	for t, x in zip(dtypes, df.columns):
		if t != False:
			df[x] = df[x].map(lambda x: t(x))
	
	# delete file if requested
	if save_file == None:
		os.remove(temp_path)

	# return proper type
	OPTIONS = ['dict', 'df', 'list_by_col', 'list_by_row']
	safe_assert(
		return_type in OPTIONS, 
		f'return_type not recognized. Options are {OPTIONS}.',
		ignore_errors
	)
	if return_type == 'list_by_col':
		return [df[x].tolist() for x in df.columns]
	elif return_type == 'list_by_row':
		return df.values.tolist()
	elif return_type == 'df':
		return df
	elif return_type == 'dict':
		return [{k: v for k, v in row.items()} for _, row in df.iterrows()]


def neoMetaModel_test_setup(function):
	"""
	Prepare a model test to run through the shared OMF model lifecycle.
	"""
	@wraps(function)
	def test_setup_wrapper(*args, **kwargs):
		heavyProcessing.__defaults__ = (True,)
		return function()
	return test_setup_wrapper


def _test():
	""" No test required for this file. """
	pass
