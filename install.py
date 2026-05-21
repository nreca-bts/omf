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
	os.system("sudo DEBIAN_FRONTEND=noninteractive apt-get -y install language-pack-en git python3-pip python3-dev python3-numpy unixodbc-dev libfreetype6-dev pkg-config python3-pydot python3-tk libblas-dev liblapack-dev libatlas-base-dev gfortran python3-cairocffi")
elif major_platform == "Linux" and "ubuntu" not in linux_distro:
	# Amazon Linux (CentOS) install, but not RedHat Docker ubi
	os.system("sudo yum -y update") # Make sure yum is updated to prevent any weird package installation issues
	os.system("sudo yum -y install git gcc xerces-c python-devel tkinter")
	os.system("sudo yum --enablerepo=extras install epel-release")
	os.system("sudo yum -y install python-pip")