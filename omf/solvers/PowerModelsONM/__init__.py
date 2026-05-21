"""
Wrap PowerModelsONM Julia workflows for distribution restoration and operational-network
model studies.
"""

import subprocess
import tempfile
import os, platform, json, time
from pathlib import Path
from os.path import join as pJoin

thisDir = os.path.abspath(os.path.dirname(__file__))

def check_instantiated():
	''' Check whether ONM was previously instantiated and working. '''
	return os.path.isfile(f'{thisDir}/instantiated.txt')

def runCommands(commandList : list):
	"""
	Run the commands workflow and return its results.
	"""
	for x in commandList:
		print(f'Running {x}')
		os.system(x)

def run_julia_script(juliaStr : str, cleanFileFormatting = True):
	''' Creates a Julia File containing the script in juliaStr, cleans up file location formatting (optional), runs it from the command line, then deletes it.
		Leads to far fewer permissions and formatting issues than running a julia script directly in a commandline command
	'''
	if cleanFileFormatting:
		juliaStr = juliaStr.replace('\\','/')
	# time.time() is added for the sake of uniqueness to avoid collisions between things running at the same time
	juliaFileLocation = pJoin(thisDir, f'temp_julia_script_{time.time()}.jl')
	with open(juliaFileLocation, 'w') as juliaFile:
		juliaFile.write(juliaStr)
	# Writing the julia code to a .jl file and running that file from the command line is far less prone to formatting snafus than writing the julia code in the cmd commands directly
	cmdString = f'julia "{juliaFileLocation}"'
	# TODO: Test this on Darwin and Linux
	OSName = platform.system()
	if OSName in ['Darwin','Linux']:
		delCommand = f'rm "{juliaFileLocation}"'
	elif OSName == 'Windows':
		delCommand = f'del "{juliaFileLocation}"'
	else:
		raise Exception("Operating System is not Darwin, Linux, or Windows")
	print(f'Saving script to {juliaFileLocation}:\n{juliaStr}')
	runCommands([cmdString,delCommand])

def _run_julia_script_toBeTested(juliaStr : str, cleanFileFormatting = True):
	''' Creates a Julia File containing the script in juliaStr, cleans up file location formatting (optional), runs it from the command line, then deletes it.
		Leads to far fewer permissions and formatting issues than running a julia script directly in a commandline command
	'''
	if cleanFileFormatting:
		juliaStr = juliaStr.replace('\\','/')
	with tempfile.TemporaryDirectory() as tempDir:
		juliaFileLocation = pJoin(tempDir, 'temp_julia_script.jl')
		print(f'Saving script to {juliaFileLocation}:\n{juliaStr}')
		with open(juliaFileLocation, 'w') as juliaFile:
			juliaFile.write(juliaStr)
		subprocess.run(['julia', juliaFileLocation])
	
def install_onm(target : list = platform.system()):
	''' WARNING, WIP. TODO: Linux support, license check, tests. '''
	installCmd = {
		'Darwin' : [
			'sudo cat /Library/gurobi/gurobi.lic',
			'HOMEBREW_NO_AUTO_UPDATE=1 brew install julia',
			'''python3 -c 'from urllib.request import urlretrieve as wget; wget("https://packages.gurobi.com/9.1/gurobi9.1.2_mac64.pkg","./gurobi9.1.2_mac64.pkg")' ''',
			'sudo installer -pkg gurobi9.1.2_mac64.pkg -target /',
			'echo "export GUROBI_HOME=/Library/gurobi912/mac64" >> ~/.zshrc',
			'echo "export PATH=/Library/gurobi912/mac64/bin:$PATH" >> ~/.zshrc',
			'echo "export LD_LIBRARY_PATH=/Library/gurobi912/mac64/lib" >> ~/.zshrc',
			'source ~/.zshrc',
			'''julia -e 'import Pkg; Pkg.add("Gurobi")' ''',
			'''julia -e 'import Pkg; Pkg.build("Gurobi")' ''',
			'''julia -e 'import Pkg; Pkg.add(Pkg.PackageSpec(;name="PowerModelsDistribution", version="0.14.1"));' ''',
			'''julia -e 'import Pkg; Pkg.add(Pkg.PackageSpec(;name="PowerModelsONM", version="3.5.0"));' ''',
			f'touch "{thisDir}/instantiated.txt"'
		],
		'Linux' : [
			'rm "julia-1.7.0-linux-x86_64.tar.gz"',
			'wget "https://julialang-s3.julialang.org/bin/linux/x64/1.7/julia-1.7.0-linux-x86_64.tar.gz"',
			'tar -x -f "julia-1.7.0-linux-x86_64.tar.gz" -C /usr/local --strip-components 1',
			'rm "gurobi9.1.2_linux64.tar.gz"',
			'wget "https://packages.gurobi.com/9.1/gurobi9.1.2_linux64.tar.gz"',
			'tar -x -f "gurobi9.1.2_linux64.tar.gz"',
			f'echo "export GUROBI_HOME={thisDir}/gurobi912/linux64" >> ./bashrc',
			f'echo "export PATH={thisDir}/gurobi912/linux64/bin:$PATH" >> ./bashrc',
			f'echo "export LD_LIBRARY_PATH={thisDir}/gurobi912/linux64/lib:$PATH" >> ./bashrc',
			'source ~/.bashrc',
			'''julia -e 'import Pkg; Pkg.add("Gurobi")' ''',
			'''julia -e 'import Pkg; Pkg.build("Gurobi")' ''',
			'''julia -e 'import Pkg; Pkg.add(Pkg.PackageSpec(;name="PowerModelsDistribution", version="0.14.1"));’ ''',
			'''julia -e 'import Pkg; Pkg.add(Pkg.PackageSpec(;name="PowerModelsONM", version="3.5.0"));' ''',
			f'touch {thisDir}/instantiated.txt'
		],
		'Windows' : [
			# thisDir isn't actually the directory from which os.system is executing these commands, which is why cd {thisDir} prepends various lines
			# IMPORTANT!: Environment variables need to be set manually through your windows gui
			# 	PATH= %PATH%;{thisDir}\julia-1.7.0\bin;{thisDir}\gurobi912\win64\bin
			#	LD_LIBRARY_PATH= {thisDir}\gurobi912\win64\lib;%PATH%
			f'cd {thisDir} & del julia-1.7.0-win64.zip',
			f'cd {thisDir} & curl -o julia-1.7.0-win64.zip https://julialang-s3.julialang.org/bin/winnt/x64/1.7/julia-1.7.0-win64.zip',
			f'cd {thisDir} & tar -x -f "julia-1.7.0-win64.zip',
			#f'set PATH="%PATH%;{thisDir}\julia-1.7.0\\bin"', #path set for just this session with set. setx is permanent but truncates the path which is very bad
			# Despite adding Julia to the path, it wasn't finding it when run from within vscode, hence the cd {thisDir}\julia-1.7.0\bin prepending the lines
			f'cd {thisDir}\julia-1.7.0\\bin & julia -e "import Pkg; Pkg.add(Pkg.PackageSpec(;name=\\"PowerModelsDistribution\\", version=\\"0.14.1\\"));"',
			f'cd {thisDir}\julia-1.7.0\\bin & julia -e "import Pkg; Pkg.add(Pkg.PackageSpec(;name=\\"PowerModelsONM\\", version=\\"3.5.0\\"));"',
			f'copy nul {thisDir}\instantiated.txt'
		]
	}
	runCommands(installCmd.get(target,'Linux'))

def build_settings_file(circuitPath='circuit.dss',settingsPath='settings.json', loadPrioritiesFile='', microgridTaggingFile='', max_switch_actions=1, vm_lb_pu=0.9, vm_ub_pu=1.1, sbase_default=1000.0, line_limit_mult='Inf', vad_deg=5.0):
	#Check for load priorities input
	"""
	Build the settings file artifact used by this workflow.
	"""
	if loadPrioritiesFile: 
		with open(loadPrioritiesFile) as loadPrioritiesJson:
			loadPriorities = json.load(loadPrioritiesJson)
		prioritiesFormatted = ''
		for load in loadPriorities:
			prioritiesFormatted += f'''
				"{load}" => Dict{{String,Any}}(
					"priority" => {loadPriorities[load]},
				),'''
		priorityDictBuilder = f'''
			"load" => Dict{{String,Any}}(
				{prioritiesFormatted}
			),'''
	else:
		loadPriorities = ''
		priorityDictBuilder = ''

	#Check for microgrid tagging input
	if microgridTaggingFile: 
		with open(microgridTaggingFile) as microgridTaggingJson:
			microgridTags = json.load(microgridTaggingJson)
		mgTaggingFormatted = ''
		for bus in microgridTags:
			mgTaggingFormatted += f'''
				"{bus}" => Dict{{String,Any}}(
					"microgrid_id" => "{microgridTags[bus]}",
				),'''
		mgTaggingDictBuilder = f'''
			"bus" => Dict{{String,Any}}(
				{mgTaggingFormatted}
			),'''
	else:
		microgridTags = ''
		mgTaggingDictBuilder = ''

	if loadPrioritiesFile or microgridTaggingFile:
		#Create the custom settings dict builder and custom settings parameter call
		settingsHead = f'''custom_settings = Dict{{String,Any}}('''
		settingsEnd = f'''
			);'''
		customSettingsDictBuilder = settingsHead + priorityDictBuilder + mgTaggingDictBuilder + settingsEnd
		customSettingsSwitch = f'custom_settings=custom_settings,'
	else:
		customSettingsDictBuilder = ''
		customSettingsSwitch = ''

	juliaFileContents = f'''using PowerModelsONM;
		{customSettingsDictBuilder}
		build_settings_file(
			"{circuitPath}",
			"{settingsPath}",
			{customSettingsSwitch}
			max_switch_actions={max_switch_actions}, #actions per time step. should always be 1, could be 2 or 3.
			vm_lb_pu={vm_lb_pu}, # min voltage allowed in per-unit
			vm_ub_pu={vm_ub_pu}, # max voltage allowed in per-unit
			sbase_default={sbase_default}, # between 1k and 100k
			line_limit_mult={line_limit_mult},
			vad_deg={vad_deg}
		)'''
	run_julia_script(juliaFileContents)

def _build_settings_file_toBeTested(circuitPath='circuit.dss',settingsPath='settings.json', loadPrioritiesFile='', microgridTaggingFile='', max_switch_actions=1, vm_lb_pu=0.9, vm_ub_pu=1.1, sbase_default=1000.0, line_limit_mult='Inf', vad_deg=5.0):
	#Check for load priorities input
	"""
	Internal helper for build settings file to be tested processing.
	"""
	if loadPrioritiesFile: 
		with open(loadPrioritiesFile) as loadPrioritiesJson:
			loadPriorities = json.load(loadPrioritiesJson)
		prioritiesFormatted = ''
		for load in loadPriorities:
			prioritiesFormatted += f'''
				"{load}" => Dict{{String,Any}}(
					"priority" => {loadPriorities[load]},
				),'''
		priorityDictBuilder = f'''
			"load" => Dict{{String,Any}}(
				{prioritiesFormatted}
			),'''
	else:
		loadPriorities = ''
		priorityDictBuilder = ''

	#Check for microgrid tagging input
	if microgridTaggingFile: 
		with open(microgridTaggingFile) as microgridTaggingJson:
			microgridTags = json.load(microgridTaggingJson)
		mgTaggingFormatted = ''
		for bus in microgridTags:
			mgTaggingFormatted += f'''
				"{bus}" => Dict{{String,Any}}(
					"microgrid_id" => "{microgridTags[bus]}",
				),'''
		mgTaggingDictBuilder = f'''
			"bus" => Dict{{String,Any}}(
				{mgTaggingFormatted}
			),'''
	else:
		microgridTags = ''
		mgTaggingDictBuilder = ''

	if loadPrioritiesFile or microgridTaggingFile:
		#Create the custom settings dict builder and custom settings parameter call
		settingsHead = f'''custom_settings = Dict{{String,Any}}('''
		settingsEnd = f'''
			);'''
		customSettingsDictBuilder = settingsHead + priorityDictBuilder + mgTaggingDictBuilder + settingsEnd
		customSettingsSwitch = f'custom_settings=custom_settings,'
	else:
		customSettingsDictBuilder = ''
		customSettingsSwitch = ''

	juliaFileContents = f'''using PowerModelsONM;
		{customSettingsDictBuilder}
		build_settings_file(
			"{circuitPath}",
			"{settingsPath}",
			{customSettingsSwitch}
			max_switch_actions={max_switch_actions}, #actions per time step. should always be 1, could be 2 or 3.
			vm_lb_pu={vm_lb_pu}, # min voltage allowed in per-unit
			vm_ub_pu={vm_ub_pu}, # max voltage allowed in per-unit
			sbase_default={sbase_default}, # between 1k and 100k
			line_limit_mult={line_limit_mult},
			vad_deg={vad_deg}
		)'''
	_run_julia_script_toBeTested(juliaFileContents)

def build_events_file(circuitPath='circuit.dss', eventsPath="events.json", custom_events='', default_switch_state='PMD.OPEN', default_switch_dispatchable='PMD.NO', default_switch_status='PMD.ENABLED'):
	# For now, custom_events follows the already established schema in Julia Vector or Dicts format
	"""
	Build the events file artifact used by this workflow.
	"""
	if custom_events: 
		with open(custom_events) as custom_events_file:
			custom_events_data = custom_events_file.read()
		customEventsDictBuilder = f'''custom_events = {custom_events_data};
		'''
		customEventsSwitch = f'custom_events=custom_events,'
	else:
		customEventsDictBuilder = ''
		customEventsSwitch = ''

	juliaFileContents = f'''using PowerModelsONM;
		{customEventsDictBuilder}
		build_events_file(
			"{circuitPath}",
			"{eventsPath}",
			{customEventsSwitch}
			default_switch_state={default_switch_state},
			default_switch_dispatchable={default_switch_dispatchable},
			default_switch_status={default_switch_status}
		)
	'''
	run_julia_script(juliaFileContents)
	# TODO: Print out juliaFileContents within run_julia_script

def run_onm(circuitPath='circuit.dss', settingsPath='settings.json', outputPath="onm_out.json", eventsPath="events.json", faultsPath='', gurobi='false', verbose='true', fixSmallNumbers='true', applySwitchScores='true', skipList='["faults","stability"]', prettyPrint='true', optSwitchFormulation="lindistflow", optSwitchSolver="mip_solver", optSwitchAlgorithm="global", optSwitchProblem="block", optDispFormulation="lindistflow", optDispSolver="mip_solver", mip_solver_gap=0.05):
	#TODO: allow arguments to function for the ones hardcoded!
	"""
	Run the onm workflow and return its results.
	"""
	juliaFileContents = f'''using PowerModelsONM; 
		args = Dict{{String,Any}}( 
			"network"=>"{circuitPath}", 
			"settings"=>"{settingsPath}", 
			"events"=>"{eventsPath}", 
			"faults"=>"{faultsPath}", 
			"output"=>"{outputPath}", 
			"verbose"=>{verbose}, 
			"skip"=>{skipList}, 
			"fix-small-numbers"=>{fixSmallNumbers}, 
			"apply-switch-scores" => {applySwitchScores}, 
			"pretty-print" => {prettyPrint}, 
			"gurobi" => false, 
			"opt-switch-formulation" => "{optSwitchFormulation}", 
			"opt-switch-solver" => "{optSwitchSolver}", 
			"opt-switch-algorithm" => "{optSwitchAlgorithm}", 
			"opt-switch-problem" => "{optSwitchProblem}", 
			"opt-disp-formulation" => "{optDispFormulation}", 
			"opt-disp-solver" => "{optDispSolver}", 
			"mip_solver_gap" => {mip_solver_gap} #0.02 = slow, 0.05 = default, 0.10 = fast 
		); 
		entrypoint(args); '''
	run_julia_script(juliaFileContents)

def _run_onm_toBeTested(circuitPath='circuit.dss', settingsPath='settings.json', outputPath="onm_out.json", eventsPath="events.json", faultsPath='', gurobi='false', verbose='true', fixSmallNumbers='true', applySwitchScores='true', skipList='["faults","stability"]', prettyPrint='true', optSwitchFormulation="lindistflow", optSwitchSolver="mip_solver", optSwitchAlgorithm="global", optSwitchProblem="block", optDispFormulation="lindistflow", optDispSolver="mip_solver", mip_solver_gap=0.05):
	#TODO: allow arguments to function for the ones hardcoded!
	"""
	Internal helper for run onm to be tested processing.
	"""
	juliaFileContents = f'''using PowerModelsONM; 
		args = Dict{{String,Any}}( 
			"network"=>"{circuitPath}", 
			"settings"=>"{settingsPath}", 
			"events"=>"{eventsPath}", 
			"faults"=>"{faultsPath}", 
			"output"=>"{outputPath}", 
			"verbose"=>{verbose}, 
			"skip"=>{skipList}, 
			"fix-small-numbers"=>{fixSmallNumbers}, 
			"apply-switch-scores" => {applySwitchScores}, 
			"pretty-print" => {prettyPrint}, 
			"gurobi" => false, 
			"opt-switch-formulation" => "{optSwitchFormulation}", 
			"opt-switch-solver" => "{optSwitchSolver}", 
			"opt-switch-algorithm" => "{optSwitchAlgorithm}", 
			"opt-switch-problem" => "{optSwitchProblem}", 
			"opt-disp-formulation" => "{optDispFormulation}", 
			"opt-disp-solver" => "{optDispSolver}", 
			"mip_solver_gap" => {mip_solver_gap} #0.02 = slow, 0.05 = default, 0.10 = fast 
		); 
		entrypoint(args); '''
	_run_julia_script_toBeTested(juliaFileContents)

if __name__ == '__main__':
	# Basic Tests
	thisDirPath = Path(thisDir)
	omfDir = thisDirPath.parent.parent.absolute()
	loadPrioritiesPath = ''
	microgridTaggingPath = ''
	circuitFile = 'iowa240_dwp_22.dss'
	settingsFile = 'iowa240_dwp_22.settings.json'
	eventsFile = 'iowa240_dwp_22.events.json'
	outputFile = './onm_out.json'
	# loadPrioritiesPath = f'{omfDir}/static/testFiles/iowa240_dwp_22.loadPriority.basic.json'
	# microgridTaggingPath = f'{omfDir}/static/testFiles/iowa240_dwp_22.microgridTagging.basic.json'
	# circuitFile = 'nreca1824_dwp.dss'
	# eventsFile = 'nreca1824_dwp.events.json'
	# install_onm()
	# build_settings_file(
	# 	circuitPath=f'{omfDir}/static/testFiles/{circuitFile}',
	# 	settingsPath=f'{omfDir}/static/testFiles/{settingsFile}',
	# 	loadPrioritiesFile=f'{loadPrioritiesPath}',
	# 	microgridTaggingFile=f'{microgridTaggingPath}'
	# )
	# build_events_file(
	# 	circuitPath=f'{omfDir}/static/testFiles/{circuitFile}',
	# 	eventsPath=f'{omfDir}/static/testFiles/{eventsFile}',
	# 	default_switch_state='PMD.OPEN',
	# 	default_switch_dispatchable='PMD.NO'
	# )

	run_onm(
		circuitPath=f'{omfDir}/static/testFiles/{circuitFile}',
		settingsPath=f'{omfDir}/static/testFiles/{settingsFile}',
		outputPath=outputFile,
		eventsPath=f'{omfDir}/static/testFiles/{eventsFile}'
	)
