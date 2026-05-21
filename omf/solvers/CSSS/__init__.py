"""
Install and expose the contextual source-separation solver used for solar
disaggregation.
"""

def pull_from_upstream():
	''' pull down the upstream package. we cache a specific version though, so this is not usually run. '''
	# get the latest code from https://github.com/slacgismo/CSSS
	source_url = 'https://github.com/slacgismo/CSSS/archive/refs/heads/master.zip'
	# pull the source.
	wget(source_url, f'{this_dir}/csss.zip')

def install(clean=False):
	''' create a venv for this finicky package and install there. '''
	# optionally remove entire venv first
	if clean:
		shutil.rmtree(f'{this_dir}/csss_env', ignore_errors=True)
	# create the venv
	os.system(f'{sys.executable} -m venv "{this_dir}/csss_env"')
	# pip install the requirements inside the venv
	os.system(f'source "{this_dir}/csss_env/bin/activate"; python -m pip install -r "{this_dir}/venv_reqs.txt"')

def run(cmd=''):
	''' Run a command against the venv. '''
	out = check_output([f'source "{this_dir}/csss_env/bin/activate"; cd "{this_dir}"; pwd; python -c "import CSSS; help(csss)"'], shell=True)
	return out.decode('utf-8')