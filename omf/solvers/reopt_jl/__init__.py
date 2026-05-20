import json, time
import os, platform, shutil
import random
import subprocess
from os.path import join as pJoin


thisDir = str(os.path.abspath(os.path.dirname(__file__)))
JULIA_VERSION = '1.9.4'
JULIA_CACHE_HOME = os.path.normpath(os.path.expanduser(os.environ.get(
	'OMF_JULIA_HOME',
	pJoin('~', '.cache', 'omf', f'julia-{JULIA_VERSION}')
)))

def _env_flag_false(name):
	value = os.environ.get(name)
	return value is not None and value.lower() in ('0', 'false', 'no', 'off')

def _julia_executable_name():
	return 'julia.exe' if platform.system() == 'Windows' else 'julia'

def _julia_version_matches(julia_executable):
	try:
		version_check = subprocess.run([julia_executable, '--version'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)
		return version_check.returncode == 0 and f'version {JULIA_VERSION}' in version_check.stdout
	except OSError:
		return False

def _prepend_to_path(path):
	path = os.path.abspath(os.path.expanduser(path))
	path_entries = os.environ.get('PATH', '').split(os.pathsep)
	if path not in path_entries:
		os.environ['PATH'] = os.pathsep.join([path] + [entry for entry in path_entries if entry])

def _julia_bin_candidates():
	candidates = []
	for env_name in ('OMF_JULIA_BINDIR', 'JULIA_BINDIR'):
		if os.environ.get(env_name):
			candidates.append(os.environ[env_name])
	for env_name in ('OMF_JULIA_HOME', 'JULIA_HOME'):
		if os.environ.get(env_name):
			candidates.append(pJoin(os.environ[env_name], 'bin'))
	candidates += [
		pJoin(JULIA_CACHE_HOME, 'bin'),
		pJoin(thisDir, f'julia-{JULIA_VERSION}', 'bin'),
		'/usr/local/bin'
	]
	return candidates

def _julia_on_path():
	julia_executable = shutil.which('julia')
	return julia_executable is not None and _julia_version_matches(julia_executable)

def _ensure_julia_on_path():
	if _julia_on_path():
		return True
	executable_name = _julia_executable_name()
	for bin_dir in _julia_bin_candidates():
		julia_executable = pJoin(os.path.expanduser(bin_dir), executable_name)
		if os.path.isfile(julia_executable) and _julia_version_matches(julia_executable):
			_prepend_to_path(bin_dir)
			return True
	return False

def _run_install_commands(commands):
	for command in commands:
		exit_code = os.system(command)
		if exit_code != 0:
			raise RuntimeError(f"reopt_jl install command failed with exit code {exit_code}: {command}")

def make_julia_script_file(juliaStr : str, cleanFileFormatting = True):
	''' Creates a Julia File containing the script in juliaStr, cleans up file location formatting (optional), and returns:
	
		A string containing the file location

		A string containing a command to delete that file formatted depending on the operating system. 

		Leads to far fewer permissions and formatting issues than running a julia script directly in a commandline command
	'''
	if cleanFileFormatting:
		juliaStr = juliaStr.replace('\\','/')
	# time.time() is added for the sake of uniqueness to avoid collisions between things running at the same time
	juliaFileLocation = pJoin(thisDir, f'temp_julia_script_{time.time()}.jl')
	with open(juliaFileLocation, 'w') as juliaFile:
		juliaFile.write(juliaStr)

	OSName = platform.system()
	if OSName in ['Darwin','Linux']:
		delCommand = f'rm "{juliaFileLocation}"'
	elif OSName == 'Windows':
		delCommand = f'del "{juliaFileLocation}"'
	else:
		raise Exception("Operating System is not Darwin, Linux, or Windows")
	
	return juliaFileLocation, delCommand


def install_reopt_jl(system : list = platform.system(), build_sysimage=True):
	''' Installs dependencies necessary for running REoptSolver and creates sysimage to reduce precompile time '''
	instantiated_path = str(os.path.normpath(os.path.join(thisDir,"instantiated.txt")))
	project_path = str(os.path.normpath(os.path.join(thisDir,"REoptSolver")))
	sysimage_path = str(os.path.normpath(os.path.join(thisDir,"reopt_jl.so")))
	precompile_path = str(os.path.normpath(os.path.join(thisDir,"precompile_reopt.jl")))

	if os.path.isfile(instantiated_path) and _ensure_julia_on_path():
		if not os.path.isfile(sysimage_path) and build_sysimage:
			print("error: reopt_jl.so not found - remove instantiated.txt to build \n attempting to run without sysimage... ")
			return False
		else:
			print("reopt_jl dependencies installed - to reinstall remove instantiated.txt")
			return build_sysimage
	elif os.path.isfile(instantiated_path):
		print("reopt_jl instantiated.txt found but julia is not on PATH; installing julia before continuing")
	
	try:
		install_pyjulia = [
				'pip show julia >null 2>&1 || pip install julia ',
				'python -c "import julia; julia.install()" '
		] if system == 'Windows' else [
				'pip3 show julia 1>/dev/null 2>/dev/null || pip3 install julia ',
				'''python3 -c 'import julia; julia.install()' '''
		]
		#adding abilty to use pre-made sysimage (not instantiated)
		if os.path.exists(sysimage_path) and build_sysimage:
			print("pre-built reopt_jl.so sysimage found")
			build_julia_image = [
				f'chmod +x "{sysimage_path}"'
			]
		elif build_sysimage:
			build_julia_image = [
				f'''julia --project="{project_path}" -e '
				import Pkg; Pkg.instantiate();
				import REoptSolver; using PackageCompiler;
				PackageCompiler.create_sysimage(["REoptSolver"]; sysimage_path="{sysimage_path}", 
				precompile_execution_file="{precompile_path}", cpu_target="generic;sandybridge,-xsaveopt,clone_all;haswell,-rdrnd,base(1)")
				' '''
			]
		else:
			build_julia_image = [
				f'''julia --project="{project_path}" -e '
				import Pkg; Pkg.instantiate();
				import REoptSolver;
				' '''
			]
		if system == "Darwin":
			commands = [] if _ensure_julia_on_path() else [ '''
				HOMEBREW_NO_AUTO_UPDATE=1 brew list julia 1>/dev/null 2>/dev/null || 
				{ brew tap homebrew/core; brew install julia; }
				'''
			]
			commands += install_pyjulia
			commands += build_julia_image
			commands += [ f'touch "{instantiated_path}"' ]
		elif system == "Linux":
			if _ensure_julia_on_path():
				commands = []
			else:
				julia_tarball_path = pJoin('/tmp', f'julia-{JULIA_VERSION}-linux-x86_64.tar.gz')
				commands = [
					'sudo apt-get -y install wget',
					f'mkdir -p "{JULIA_CACHE_HOME}"',
					f'wget -q -O "{julia_tarball_path}" https://julialang-s3.julialang.org/bin/linux/x64/1.9/julia-{JULIA_VERSION}-linux-x86_64.tar.gz',
					f'tar -xzf "{julia_tarball_path}" -C "{JULIA_CACHE_HOME}" --strip-components 1'
				]
				_prepend_to_path(pJoin(JULIA_CACHE_HOME, 'bin'))
				_run_install_commands(commands)
				if os.path.isfile(instantiated_path) and _ensure_julia_on_path():
					if not os.path.isfile(sysimage_path) and build_sysimage:
						print("error: reopt_jl.so not found - remove instantiated.txt to build \n attempting to run without sysimage... ")
						return False
					print("reopt_jl dependencies installed after restoring cached Julia - to reinstall remove instantiated.txt")
					return build_sysimage
				commands = []
			commands += install_pyjulia
			commands += build_julia_image
			commands += [ f'touch "{instantiated_path}"' ]
		elif system == "Windows":
			commands = [
				f'cd "{thisDir}" & if exist julia-1.9.4-win64.zip del julia-1.9.4-win64.zip',
				f'cd "{thisDir}" & curl -o julia-1.9.4-win64.zip https://julialang-s3.julialang.org/bin/winnt/x64/1.9/julia-1.9.4-win64.zip',
				f'cd "{thisDir}" & tar -x -f julia-1.9.4-win64.zip' ]
			commands += install_pyjulia
			if build_sysimage:
				juliaStr = f'''import Pkg; Pkg.instantiate();
					import REoptSolver; using PackageCompiler;
					PackageCompiler.create_sysimage(["REoptSolver"]; sysimage_path="{sysimage_path}", 
					precompile_execution_file="{precompile_path}", cpu_target="generic;sandybridge,-xsaveopt,clone_all;haswell,-rdrnd,base(1)")
					'''
				juliaFileLocation, delCommand = make_julia_script_file(juliaStr)
				commands += [
					f'cd "{thisDir}\\julia-1.9.4\\bin" & julia --project="{project_path}" "{juliaFileLocation}"',
					delCommand
				]
			else:
				commands += [f'cd "{thisDir}\\julia-1.9.4\\bin" & julia --project="{project_path}" -e "import Pkg; Pkg.instantiate(); import REoptSolver;"']
			commands += [ f'copy nul "{instantiated_path}"' ]
		else:
			raise ValueError(f'No installation script available yet for {system}')

		_run_install_commands(commands)

		return build_sysimage

	except (ImportError, OSError, SystemError) as e:
		if build_sysimage:
			print(f"error while building reopt_jl.so: {e} \n attempting install again without building sysimage... ")
			return install_reopt_jl(build_sysimage=False)
		else:
			print(e)
			return
		
	except Exception as e:
		print(e)
		return 
	
########################################################
#functions for converting REopt input to REopt.jl input 
#	-> used for integration testing purposes
########################################################

def init_reopt_to_julia_dict():
	''' dictionary mapping REopt variable name to REopt.jl variable name, plus necessary information on parent section & data type
		( translated variable name , section(s)(/none) , datatype(None if multiple types) )'''
	to_jl_dict = { "Site":("Site", {None}, dict),
		"latitude":("latitude",{"Site"},float),
		"longitude":("longitude",{"Site"},float),

		"ElectricTariff":("ElectricTariff", {None}, dict), 
		"wholesale_rate_us_dollars_per_kwh":("wholesale_rate", {"ElectricTariff"}, None),
		"blended_annual_rates_us_dollars_per_kwh":
		("blended_annual_energy_rate", {"ElectricTariff"}, None),
		"blended_annual_demand_charges_us_dollars_per_kw":
		("blended_annual_demand_rate", {"ElectricTariff"}, None),
		"urdb_label":("urdb_label",{"ElectricTariff"},str),

		"LoadProfile":("ElectricLoad", {None}, dict),
		"critical_loads_kw":("critical_loads_kw",{"ElectricLoad"},list),
		"critical_load_pct":("critical_load_fraction",{"ElectricLoad"}, float),
		"loads_kw":("loads_kw",{"ElectricLoad"},list), "year":("year",{"ElectricLoad"},int), 
		"loads_kw_is_net":("loads_kw_is_net",{"ElectricLoad"},bool),

		"Financial":("Financial", {None}, dict),
		"value_of_lost_load_us_dollars_per_kwh":("value_of_lost_load_per_kwh", {"Financial"}, float), 
		"om_cost_escalation_pct":("om_cost_escalation_rate_fraction", {"Financial"}, float),
		"offtaker_discount_pct":("offtaker_discount_rate_fraction",{"Financial"}, float),
		"analysis_years":("analysis_years",{"Financial"}, int),

		#PV, ElectricStorage, Wind & Generator shared variables:
		"installed_cost_us_dollars_per_kw":
		("installed_cost_per_kw", {"PV","Wind","ElectricStorage","Generator"} ,float),
		"min_kw":("min_kw", {"PV","Wind","ElectricStorage","Generator"}, float),
		"max_kw":("max_kw", {"PV","Wind","ElectricStorage","Generator"}, float), 
		"macrs_option_years":("macrs_option_years", {"PV","Wind","ElectricStorage","Generator"}, int),

		#PV, Wind, Generator shared:
		"can_export_beyond_site_load":("can_export_beyond_nem_limit", {"PV","Wind","Generator"}, bool),
		"federal_itc_pct":("federal_itc_fraction", {"PV","Wind","Generator"}, float),

		#Generator & ElectricStorage shared:
		"replace_cost_us_dollars_per_kw":("replace_cost_per_kw",{"Generator","ElectricStorage"},float),

		#PV & Generator shared:
		"can_curtail":("can_curtail", {"PV", "Generator"}, bool), 
		"existing_kw":("existing_kw", {"PV", "Generator"}, float), 
		"om_cost_us_dollars_per_kw":("om_cost_per_kw", {"PV", "Generator"}, float),

		"PV":("PV", {None}, dict),

		"Storage":("ElectricStorage", {None}, dict),
		"replace_cost_us_dollars_per_kwh":("replace_cost_per_kwh", {"ElectricStorage"}, float),
		"total_itc_percent":("total_itc_fraction", {"ElectricStorage"}, float),
		"inverter_replacement_year":("inverter_replacement_year", {"ElectricStorage"}, int),
		"battery_replacement_year":("battery_replacement_year", {"ElectricStorage"}, int), 
		"min_kwh":("min_kwh", {"ElectricStorage"}, float), 
		"max_kwh":("max_kwh", {"ElectricStorage"}, float),
		"installed_cost_us_dollars_per_kwh":("installed_cost_per_kwh", {"ElectricStorage"}, float),

		"Wind":("Wind", {None}, dict),

		"Generator":("Generator", {None}, dict),
		"generator_only_runs_during_grid_outage":("only_runs_during_grid_outage",{"Generator"}, bool),
		"fuel_avail_gal":("fuel_avail_gal", {"Generator"}, float), 
		"min_turn_down_pct":("min_turn_down_fraction", {"Generator"}, float),
		"diesel_fuel_cost_us_dollars_per_gallon":("fuel_cost_per_gallon", {"Generator"}, float),
		"emissions_factor_lb_CO2_per_gal":("emissions_factor_lb_CO2_per_gal", {"Generator"}, float),
		"om_cost_us_dollars_per_kwh":("om_cost_per_kwh", {"Generator"}, float),

		#### ElectricUtility (not used in REopt)
		"outage_start_time_step":("outage_start_time_step", {"ElectricUtility"}, int), 
		"outage_end_time_step":("outage_end_time_step", {"ElectricUtility"}, int)
	}

	#variables in reopt that aren't used in reopt.jl
	not_included_in_jl = { "outage_is_major_event", "wholesale_rate_above_site_load_us_dollars_per_kwh" }

	return (to_jl_dict, not_included_in_jl)

def check_key(key, to_jl_dict, not_included_in_jl):
	''' checks if variable name is used in REopt.jl '''
	if key in not_included_in_jl:
		return False
	elif key not in to_jl_dict:
		raise ValueError(f"Key not found in API -> Julia JSON translator: {key}")
	else:
		return True
	
# 
def check_input(key,var,to_jl_dict):
	''' returns data value if it is the correct data type or converts if feasible '''
	if key in to_jl_dict:
		var_type = to_jl_dict[key][2]
		if var_type == type(var) or var_type == None:
			return var
		elif var_type == int:
			return int(var)
		elif var_type == float:
			return float(var)
	else:
		raise ValueError(f"Key not found in API -> Julia JSON translator: {key}")

def get_section(key,section,to_jl_dict):
	''' returns converted section name if used in REopt.jl '''
	section_to_jl = to_jl_dict[section][0]
	new_sections = to_jl_dict[key][1]
	if section_to_jl in new_sections:
		return section_to_jl
	elif len(new_sections) == 1:
		return list(new_sections)[0]
	else:
		raise ValueError(f"No sections found for key: {key} in API -> Julia JSON translator")

def add_variable(section,key,value,jl_json,to_jl_dict):
	''' converts variable into REopt.jl version of variable and adds to json '''
	new_section = get_section(key,section,to_jl_dict)
	new_var_name = to_jl_dict[key][0]
	if not new_section in jl_json:
		jl_json[new_section] = dict()
	jl_json[new_section][new_var_name] = check_input(key,value,to_jl_dict)
	return jl_json

def convert_to_jl(reopt_json):
	''' converts an input json for REopt to the equivalent version for REopt.jl
			REopt json: {Scenario: { Site: {lat, lon, ElectricTariff:{}, LoadProfile:{}, etc. }}}
			REopt.jl json: { Site: { lat, lon }, ElectricTariff:{}, LoadProfile:{}, etc. } '''
	(to_jl_dict,not_included_in_jl) = init_reopt_to_julia_dict()
	new_jl_json = {}
	try:
		scenario = reopt_json["Scenario"]["Site"]
		for key in scenario:
			if not check_key(key,to_jl_dict,not_included_in_jl):
				continue 
			value = scenario[key]
			if not type(value) == dict:
				new_jl_json = add_variable("Site",key,value,new_jl_json,to_jl_dict)
			else:
				for sub_key in value:
					if not check_key(sub_key,to_jl_dict,not_included_in_jl): 
							continue
					else:
						new_jl_json = add_variable(key,sub_key,value[sub_key],new_jl_json,to_jl_dict)
	except Exception as e:
		print(e)
	return new_jl_json

##########################################################################
# run_reopt_jl 
##########################################################################

def get_randomized_api_key():
	'''returns a random API key'''
	REOPT_API_KEYS = [
		'WhEzm6QQQrks1hcsdN0Vrd56ZJmUyXJxTJFg6pn9',
		'Y8GMAFsqcPtxhjIa1qfNj5ILxN5DH5cjV3i6BeNE',
		'etg8hytwTYRf4CD0c4Vl9U7ACEQnQg6HV2Jf4E5W',
		'BNFaSCCwz5WkauwJe89Bn8FZldkcyda7bNwDK1ic',
		'L2e5lfH2VDvEm2WOh0dJmzQaehORDT8CfCotaOcf',
		'08USmh2H2cOeAuQ3sCCLgzd30giHjfkhvsicUPPf'
	]
	key_index = random.randint(0,5)
	return REOPT_API_KEYS[key_index]

#potential optional inputs (for solver): ratio_gap, threads, max_solutions, verbosity
#potential other inputs (ease of use): load csv file path ("path_to_csv") => check if "loads_kw" already exists
def run_reopt_jl(path, inputFile="", loadFile="", default=False, outages=False, microgrid_only=False, max_runtime_s=None, 
				 run_with_sysimage=True, tolerance=0.05, random_seed=None):
	''' calls 'run' function through run_reopt.jl (Julia file) '''
	if _env_flag_false('OMF_REOPT_BUILD_SYSIMAGE'):
		run_with_sysimage = False
	
	if inputFile == "" and not default:
		print("Invalid inputs: inputFile needed if default=False")
		return

	#runs reopt differently based on success of sysimage build
	built_sysimage = install_reopt_jl(build_sysimage=run_with_sysimage)

	constant_file = "Scenario_test_POST.json"
	constant_path = os.path.normpath(os.path.join(path,constant_file))

	if inputFile != constant_file:
		inputPath = os.path.normpath(os.path.join(path,inputFile))
		if default == True:
			inputPath = os.path.normpath(os.path.join(thisDir,"testFiles","julia_default.json"))
		with open(inputPath) as j:
			input_json = json.load(j)
			if default == True:
				input_json["ElectricLoad"]["path_to_csv"] = os.path.normpath(os.path.join(thisDir,"testFiles","loadShape.csv"))
			elif loadFile != "":
				input_json["ElectricLoad"]["path_to_csv"] = os.path.normpath(os.path.join(path,loadFile))
			with open(constant_path, "w") as j:
				json.dump(input_json, j)

	try:
		microgrid_only_jl = "false" if not microgrid_only else "true"
		outages_jl = "false" if not outages else "true"
		max_runtime_s_jl = "nothing" if max_runtime_s == None else max_runtime_s
		random_seed_jl = "nothing" if random_seed == None else random_seed

		api_key = get_randomized_api_key()

		if built_sysimage:
			sysimage_path = os.path.normpath(os.path.join(thisDir,"reopt_jl.so"))

			juliaStr = f'''using .REoptSolver;
				ENV["NREL_DEVELOPER_API_KEY"]="{api_key}";
				REoptSolver.run("{path}", {outages_jl}, {microgrid_only_jl}, {max_runtime_s_jl}, "{api_key}", {tolerance}, {random_seed_jl})
				'''
			juliaFileLocation, delCommand = make_julia_script_file(juliaStr)
			command = f'julia --sysimage="{sysimage_path}" "{juliaFileLocation}"'
		else:
			project_path = os.path.normpath(os.path.join(thisDir,"REoptSolver"))

			juliaStr = f'''using Pkg; Pkg.instantiate();
				import REoptSolver;
				ENV["NREL_DEVELOPER_API_KEY"]="{api_key}";
				REoptSolver.run("{path}", {outages_jl}, {microgrid_only_jl}, {max_runtime_s_jl}, "{api_key}", {tolerance}, {random_seed_jl})
				'''
			juliaFileLocation, delCommand = make_julia_script_file(juliaStr)  
			command = f'julia --project="{project_path}" "{juliaFileLocation}"'

		OSName = platform.system()
		if OSName in ['Darwin','Linux']:
			command += f' ; {delCommand}'
		elif OSName == 'Windows':
			command = f'cd "{thisDir}\\julia-1.9.4\\bin" & {command} & {delCommand}'
		else:
			raise Exception("Operating System is not Darwin, Linux, or Windows")

		# As each line becomes available, print to terminal and append to return variable.
		output = []
		process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
		for line in process.stdout:
			print(line, end="")
			output.append(line)
		return ''.join(output)
	
	except Exception as e:
		print(e)


def _test():
	run_reopt_jl(os.path.normpath(os.path.join(thisDir,"testFiles")), default=True)

if __name__ == "__main__":
	_test()
