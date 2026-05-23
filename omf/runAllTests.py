"""
Discover OMF modules with test entrypoints and run their module-level smoke tests in a
repeatable order.
"""

import sys, platform, pkgutil, importlib, omf, traceback

PY_BIN_NAME = 'python3'

# GitHub-hosted runners do not have the system solvers, GUI support, or stable external API access needed by these older integration-style tests.
IGNORE_FILES = ['omf.models.forecastTool', 'omf.models.solarDisagg', 'omf.cymeToGridlab', 'omf.milToGridlab', 'omf.models.transmission', 'omf.loadModelingAmi']

if platform.system()=='Windows':
	NO_WINDOWS_SUPPORT = ['omf.cymeToGridlab', 'omf.models.rfCoverage', 'omf.models.solarEngineering', 'omf.models.phaseBalance', 'omf.models.forecastTool', 'omf.distNetViz', 'omf.models.derInterconnection', 'omf.models.networkStructure', 'omf.models.smartSwitching'] # some tests are very finicky on windows
	PY_BIN_NAME = 'python' # also annoying binary naming on Windows
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
	"""
	Internal helper for run all tests print header processing.
	"""
	print('\n+------------------------+', flush=True)
	print(f'{header.upper()}', flush=True)
	print('+------------------------+\n', flush=True)

def run_all_tests():
	''' Run every test in the OMF and return results.'''
	all_testable_mods = get_all_testable_modules()
	misfires = []
	for mod in all_testable_mods:
		print(f'!!!!! NOW TESTING {mod} !!!!!', flush=True)
		try:
			run_tests_on_module(mod)
		except:
			misfires.append(mod)
			traceback.print_exc()
	_print_header('regular tests report')
	print(f'Number of modules tested: {len(all_testable_mods)}', flush=True)
	print(all_testable_mods, flush=True)
	_print_header('failed tests report')
	print(f'Number of tests failed: {len(misfires)}', flush=True)
	print(misfires, flush=True)
	_print_header('untested modules report')
	print(f'Number of untested modules: {len(IGNORE_FILES)}', flush=True)
	print(IGNORE_FILES, flush=True)
	if len(misfires) > 0:
		sys.exit(1) # trigger build failure.

if __name__ == "__main__"  :
	run_all_tests()
