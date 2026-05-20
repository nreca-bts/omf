### Docker

Because our list of [required python packages](https://github.com/dpinney/omf/blob/master/requirements.txt) and [operating system packages](https://github.com/dpinney/omf/blob/master/install.py) is extensive, the easiest approach to running the OMF is via Docker. Here is our [Docker file](https://github.com/dpinney/omf/blob/master/Dockerfile) with instructions on usage embedded.

### Windows Installation Instructions

1. Some requirements need to be installed before running the OMF installation script.
	* [git](https://www.git-scm.com/download/win)
	* [Chocolatey](https://chocolatey.org/install)
	* [Python 3.6.8](https://www.python.org/downloads/). Make sure you select the one optional installation component that adds Python to the path and install in the C:\Python36\ directory

2. Get the OMF source with git:
	```
	git clone https://github.com/dpinney/omf.git
	```

3. With your cmd or powershell application run as administrator (right-click + run as administrator), run the installation script:

	```
	python install.py
	```

4. Test by starting the web server with ```cd omf; python web.py```. You should then be able to access the login page at http://127.0.0.1:5000/. The default user/pass is admin/admin.

### Unix (apt-based) Installation Instructions

1. Install the pre-requisite packages:
	```
	sudo apt-get install git python
	```

2. Get the OMF source with git:
	```
	git clone https://github.com/dpinney/omf.git
	```

3. Run the installation script in the omf directory

	```
	sudo python install.py 
	```

4. Test by starting the web server with `python web.py` in the omf directory. You should then be able to access the login page at http://127.0.0.1:5000/. The default user/pass is admin/admin.

### Red Hat/CentOS Installation Instructions

Make sure your distro has Python 3.6 or later.

1. Install the pre-requisite packages:
	```
	sudo yum install git python
	```

2. Get the OMF source with git:
	```
	git clone https://github.com/dpinney/omf.git
	```

3. Run the installation script in the omf directory

	```
	sudo python install.py 
	```

4. Test by starting the web server with `python web.py` in the omf directory. You should then be able to access the login page at http://127.0.0.1:5000/. The default user/pass is admin/admin.

### Mac OS X Installation Instructions

1. Some requirements need to be installed before running the OMF installation script.
	* [git](https://git-scm.com/download/mac)
	* [Xcode Command-line Tools](https://developer.apple.com/xcode/)
	* [homebrew](https://brew.sh)

2. Install the homebrew version of python 3:
	```
	brew install python3
	```

3. Get the OMF source with git:
	```
	git clone https://github.com/dpinney/omf.git
	```
4. Run the installation script in the omf directory

	```
	python3 install.py 
	```

4. Test by starting the web server with `python web.py` in the omf directory. You should then be able to access the login page at http://127.0.0.1:5000/. The default user/pass is admin/admin.

### Contributing Back

To contribute your changes back to the OMF, follow the above steps on a forked copy of the repo and send us a pull request. Full details on the process are at https://help.github.com/articles/fork-a-repo/.

### Uninstall
	
Both Windows and Linux OMF can be uninstalled by running the following command in the OMF directory.

```
python setup.py uninstall
```

The link in the site-packages (Windows) or dist-packages (Linux) folder will be removed. The code will remain where you cloned it until you delete it.