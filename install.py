import platform, os, sys, subprocess, pathlib

source_dir = str(pathlib.Path(__file__).resolve().parent)

# Check that we're only using python3
if sys.version_info[0] != 3:
	print(f'You are using python version {sys.version}')
	print('We only support python major version 3. Install aborted.')
	sys.exit()

# Detect platform
major_platform = platform.system()
if major_platform == "Linux":
	linux_distro = subprocess.run(['cat', '/etc/os-release'], stdout=subprocess.PIPE, universal_newlines=True).stdout.lower()
else:
	linux_distro = "NOT-LINUX"

if major_platform == "Linux" and "ubuntu" in linux_distro:
	os.system("sudo ACCEPT_EULA=Y apt-get -yq install mssql-tools msodbcsql") # workaround for the package EULA, which otherwise breaks upgrade!!
	os.system("sudo apt-get -y update")# && sudo apt-get -y upgrade") # Make sure apt-get is updated to prevent any weird package installation issues
	os.system("sudo apt-get -y install language-pack-en") # Install English locale 
	os.system("sudo DEBIAN_FRONTEND=noninteractive apt-get -y install git python3-pip python3-dev python3-numpy unixodbc-dev libfreetype6-dev pkg-config python3-pydot python3-tk libblas-dev liblapack-dev libatlas-base-dev gfortran")
	os.system("sudo apt-get -y install python3-cairocffi") # Separate from above to better support debian.
	# os.system(f"{sys.executable} -m pip install --upgrade pip setuptools")
	os.system(f"{sys.executable} -m pip install --ignore-installed -e {source_dir}")
    # - If using Docker, this configuration should be done in the Dockerfile
	print('*****\nRun $ export LC_ALL=C.UTF-8 $ if running phaseId._tests() gives an ascii decode error.\n*****')
elif major_platform == "Linux" and "ubuntu" not in linux_distro:
	# Amazon Linux (CentOS) install, but not RedHat Docker ubi
	os.system("sudo yum -y update") # Make sure yum is updated to prevent any weird package installation issues
	os.system("sudo yum -y install git gcc xerces-c python-devel tkinter")
	os.system("sudo yum --enablerepo=extras install epel-release")
	os.system("sudo yum -y install python-pip")
	os.system(f"{sys.executable} -m pip install --upgrade pip")
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
    # - If using Docker, this configuration should be done in the Dockerfile
	print('*****\nRun $ export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib $ if opendsscmd gives a shared library error.\n*****')
elif major_platform == 'Windows':
	os.system(f"{sys.executable} -m pip install --upgrade pip")
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
	os.system(f'{source_dir}\\omf\\solvers\\opendss\\opendsscmd-1.7.4-windows-installer.exe --mode unattended')
elif major_platform == "Darwin": # MacOS
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
	print('Please go to System Preferences to finish installing OpenDSS on Mac')
else:
	print("Your operating system is not currently supported. Platform detected: " + str(platform.system()) + str(platform.linux_distribution()))
