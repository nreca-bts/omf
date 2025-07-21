import platform, os, sys, urllib, subprocess, pathlib
from urllib.request import urlretrieve as wget

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
	os.system("sudo ACCEPT_EULA=Y apt-get -yq install mssql-tools msodbcsql mdbtools") # workaround for the package EULA, which otherwise breaks upgrade!!
	os.system("sudo apt-get -y update")# && sudo apt-get -y upgrade") # Make sure apt-get is updated to prevent any weird package installation issues
	os.system("sudo apt-get -y install language-pack-en") # Install English locale 
	os.system("sudo DEBIAN_FRONTEND=noninteractive apt-get -y install git python3-pip python3-dev python3-numpy unixodbc-dev libfreetype6-dev pkg-config alien python3-pydot python3-tk libblas-dev liblapack-dev libatlas-base-dev gfortran splat")
	os.system("sudo apt-get -y install ffmpeg python3-cairocffi") # Separate from above to better support debian.
	os.system(f"sudo alien -i {source_dir}/omf/static/gridlabd-4.0.0-1.el6.x86_64.rpm")
	os.system("sudo apt-get install -f")
	# os.system(f"{sys.executable} -m pip install --upgrade pip setuptools")
	# os.system(f"{sys.executable} -m pip install 'Flask-Login<0.3'")
	os.system(f"{sys.executable} -m pip install --ignore-installed -r {source_dir}/requirements.txt")
	os.system(f"{sys.executable} -m pip install --ignore-installed -e {source_dir}")
	os.system(f'sudo chmod 755 {source_dir}/omf/solvers/opendss/opendsscmd-1.7.4-linux-x64-installer.run && sudo {source_dir}/omf/solvers/opendss/opendsscmd-1.7.4-linux-x64-installer.run --mode unattended')
    # - If using Docker, this configuration should be done in the Dockerfile
	print('*****\nRun $ export LC_ALL=C.UTF-8 $ if running phaseId._tests() gives an ascii decode error.\n*****')
elif major_platform == "Linux" and "ubuntu" not in linux_distro:
	# Amazon Linux (CentOS) install, but not RedHat Docker ubi
	os.system("sudo yum -y update") # Make sure yum is updated to prevent any weird package installation issues
	os.system("sudo yum -y install git gcc xerces-c python-devel tkinter")
	os.system("sudo yum --enablerepo=extras install epel-release")
	os.system("sudo yum -y install mdbtools")
	os.system("sudo rpm --import http://li.nux.ro/download/nux/RPM-GPG-KEY-nux.ro")
	os.system("sudo rpm -Uvh http://li.nux.ro/download/nux/dextop/el7/x86_64/nux-dextop-release-0-1.el7.nux.noarch.rpm")
	os.system("sudo yum -y install ffmpeg ffmpeg-devel -y")
	os.system("sudo yum -y install python-pip")
	os.system(f"sudo rpm -Uvh {source_dir}/omf/static/gridlabd-4.0.0-1.el6.x86_64.rpm")
	os.system(f"{sys.executable} -m pip install --upgrade pip")
	os.system(f"{sys.executable} -m pip install -r {source_dir}/requirements.txt")
	os.system(f"{sys.executable} -m pip install --ignore-installed six")
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
	os.system(f'sudo chmod 755 {source_dir}/omf/solvers/opendss/opendsscmd-1.7.4-linux-x64-installer.run && sudo {source_dir}/omf/solvers/opendss/opendsscmd-1.7.4-linux-x64-installer.run --mode unattended')
    # - If using Docker, this configuration should be done in the Dockerfile
	print('*****\nRun $ export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib $ if opendsscmd gives a shared library error.\n*****')
elif major_platform == 'Windows':
	os.system("choco install -y --no-progress ffmpeg")
	#TODO: find way to install mdbtools.
	os.system(".\\omf\\static\\gridlabd-4.0_RC1.exe /silent")
	#TODO: install SPLAT
	os.system(f"{sys.executable} -m pip install --upgrade pip")
	os.system(f"{sys.executable} -m pip install -r {source_dir}/requirements.txt")
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
	os.system(f'{source_dir}\\omf\\solvers\\opendss\\opendsscmd-1.7.4-windows-installer.exe --mode unattended')
elif major_platform == "Darwin": # MacOS
	os.system("HOMEBREW_NO_AUTO_UPDATE=1 brew install ffmpeg mdbtools") # Set no-update to keep homebrew from blowing away python3.
	os.system(f"sudo hdiutil attach {source_dir}/omf/static/gridlabd-4.0_RC1.dmg")
	os.system('sudo installer -package "/Volumes/GridLAB-D 4.0.0/gridlabd.mpkg" -target /')
	os.system('sudo hdiutil detach "/Volumes/GridLAB-D 4.0.0"')
	opener = urllib.request.build_opener()
	opener.addheaders = [('User-agent', 'Mozilla/5.0')]
	urllib.request.install_opener(opener)
	wget('https://www.qsl.net/kd2bd/splat-1.4.2-osx.tgz', './splat-1.4.2-osx.tgz')
	os.system("sudo tar -xvzf splat-1.4.2-osx.tgz")
	os.system('''
		cd splat-1.4.2;
		sed -i '' 's/ans=""/ans="2"/g' configure;
		sudo bash configure;
	''') # sed is to hack the build to work without user input.
	os.system(f"{sys.executable} -m pip install -r {source_dir}/requirements.txt")
	os.system(f"{sys.executable} -m pip install -e {source_dir}")
	os.system(f'sudo hdiutil attach {source_dir}/omf/solvers/opendss/opendsscmd-1.7.4-osx-installer.dmg')
	os.system('open /Volumes/OpenDSS/opendsscmd-1.7.4-osx-installer.app')
	print('Please go to System Preferences to finish installing OpenDSS on Mac')
else:
	print("Your operating system is not currently supported. Platform detected: " + str(platform.system()) + str(platform.linux_distribution()))
