''' Walk the omf submodules, run _tests() in all modules. '''

import sys, platform, pkgutil, importlib, omf, traceback

# master override disabling testing.
IGNORE_FILES = ['omf.runAllTests', 'omf.webProd', 'omf.web', 'omf.omfStats', 'omf.models.phaseId', 'omf.models.solarDisagg', 'omf.tests', 'omf.models.forecastTool', 'omf.models.transmission', 'omf.models.cvrStatic', 'omf.models.smartSwitching', 'omf.models.flisr']

# Different platforms like to name the python binary differently
PY_BIN_NAME = 'python3'
# some tests are very finicky on windows
if platform.system()=='Windows':
	NO_WINDOWS_SUPPORT = ['omf.cymeToGridlab', 'omf.models.rfCoverage', 'omf.models.solarEngineering', 'omf.models.phaseBalance', 'omf.models.forecastTool', 'omf.distNetViz', 'omf.models.derInterconnection', 'omf.models.networkStructure', 'omf.models.smartSwitching']
	PY_BIN_NAME = 'python'
	IGNORE_FILES.extend(NO_WINDOWS_SUPPORT)

def get_all_testable_modules():
	''' Find all modules in the OMF with ._tests() functions defined, minus the ignored modules. '''
	# get all module names recursively
	mod_names = []
	for _, modname, _ in pkgutil.walk_packages(path=omf.__path__, prefix=omf.__name__+'.'):
		mod_names.append(modname)
	# filter out broken tests.
	good_mod_names = set(mod_names) - set(IGNORE_FILES)
	# get all test funcs
	test_funcs = []
	for mod_name in good_mod_names:
		try:
			this_mod = importlib.import_module(mod_name)
			sub_names = dir(this_mod)
			if '_tests' in sub_names:
				test_funcs.append(mod_name)
		except ImportError:
			pass
	return test_funcs

def run_tests_on_module(mod_name):
	''' e.g. run_tests_on_module('omf.models.pvWatts')'''
	import importlib
	my_mod = importlib.import_module(mod_name)
	test_func = getattr(my_mod, '_tests')
	test_func()

def _print_header(header):
	print('\n+------------------------+')
	print(f'{header.upper()}')
	print('+------------------------+\n')

def run_all_tests():
	''' Run every test in the OMF and return results.'''
	all_testable_mods = get_all_testable_modules()
	misfires = []
	for mod in all_testable_mods:
		print(f'!!!!! NOW TESTING {mod} !!!!!')
		try:
			run_tests_on_module(mod)
		except:
			misfires.append(mod)
			traceback.print_exc()
	_print_header('regular tests report')
	print(f'Number of modules tested: {len(all_testable_mods)}')
	print(all_testable_mods)
	_print_header('failed tests report')
	print(f'Number of tests failed: {len(misfires)}')
	print(misfires)
	_print_header('untested modules report')
	print(f'Number of untested modules: {len(IGNORE_FILES)}')
	print(IGNORE_FILES)
	if len(misfires) > 0:
		sys.exit(1) # trigger build failure.

if __name__ == "__main__"  :
	run_all_tests()