### A quick instructions:

1. A proper layout of omf is suggested for packaging distribution.

	```bash
	│
	├───omf
	│   ├───calibration
	│   ├───...
	...
	├───setup.py
	├───requirements.txt
	├───MANIFEST.in
	└───omf.egg-info
	```
	
2. Editing _setup.py_ file
	There are two standard way to edit _setup.py_ file, one is from __distutils.core__ and another is from __setuptools__ package.
	Both of them are suitable for setup() function, indeed, setuptools is an extension of distutils.core package.
	Check here for how to write the setup script: [link](https://docs.python.org/2/distutils/setupscript.html)
		
3. Create a source distribution package
	To create a release, you source code needs to be packaged into a single archive file.
	```bash
	$ python setup.py sdist
	```
	It will create a package file in __dist__ directory, either .zip(default in Windows) or .tar.gz(default in Linux).
	If you want to change it into a tar file for Linux distributions, you can add a format option `$ python setup.py sdist --formats=gztar`
	
	1. Editing MANIFEST.in file
	A MANIFEST.in file can be added in a project to define the list of files to include in the distribution built by the `sdist` command. This file will help us to maintain not only .py files in our project, but all other related files into the distribution package, for example the data files and other .dll files.
	A detailed instruction of how to write MANIFEST.in file is available [here](https://docs.python.org/2/distutils/sourcedist.html#the-manifest-in-template).
	
4. Create a build distribution package
	This is useful for Windows build distributions, which is executable installation file.
	`$ python setup.py bdist_wininst`
	A more detailed instruction of build distribution is available [here](https://docs.python.org/2/distutils/builtdist.html).
	
5. Install the distribution package on other machines.
	You can also check [Developer Documentation](./Developer-Documentation#getting-started) page
	1. For Windows
		1. Check version of python
			You need have python installed in your machine, and both 32-bit are 64-bit are suitable. And you'd better have your python environment setted in the system environment variables.
			```bash
			C:\Users\CRN\Downloads>python
			Python 2.7.6 (default, Nov 10 2013, 19:24:18) [MSC v.1500 32 bit (Intel)] on win32
			Type "help", "copyright", "credits" or "license" for more information.
			>>>
			```
			
		2. Install pip
			```bash
			C:\Users\CRN\Downloads>python get-pip.py
			Downloading/unpacking pip
			Downloading/unpacking setuptools
			Installing collected packages: pip, setuptools
			Successfully installed pip setuptools
			Cleaning up...
			```
		3. Install matplotlib and numpy
			It is suggested to install [matplotlib](http://matplotlib.org/downloads.html) and [numpy](http://sourceforge.net/projects/numpy/files/) separately from Windows binary installation files.
		
		4. Install gridlab-d and nrel-sam
			Get the installation file from [gridlab-d](http://sourceforge.net/projects/gridlab-d/files/) and [NREL SAM](https://sam.nrel.gov/content/downloads)
		
		5. Install omf
			Get the omf-0.1.zip file, unzip it, locate into omf-0.1 directory.
			```
			C:\Users\CRN\Downloads\omf-0.1\omf-0.1>python setup.py develop
			...
			Using c:\python27\lib\site-packages
			Finished processing dependencies for omf==0.1
			```
		6. Install visual C++ package
			It is required to install MC C++ compiler from [VCREDIST](http://www.microsoft.com/en-us/download/details.aspx?id=30679#)
		
		7. Test OMF
			```bash
			C:\Users\CRN\Downloads>python
			Python 2.7.6 (default, Nov 10 2013, 19:24:18) [MSC v.1500 32 bit (Intel)] on win
			32
			Type "help", "copyright", "credits" or "license" for more information.
			>>> import omf
			>>>
			```
		8. Run OMF
			```bash
			C:\Users\CRN\Downloads\omf-0.1\omf-0.1\omf>python web.py
			 * Running on http://127.0.0.1:5000/
			 * Restarting with reloader
			```
			OK, congratulations, you have omf deployed in your machine.
		
		9. Uninstall OMF
			If you want to uninstall OMF from you machine
			```bash
			C:\Users\CRN\Downloads\omf-0.1\omf-0.1>python setup.py develop --uninstall
			```
			It will remove the link in the site-packages directory, which you cannot import omf in other python scripts. But when locate into the source directory, it is still available for running.
			
	2. For Linux
		1. Check the version of python
			```bash
			crn@debian:~$ python 
			Python 2.7.3 (default, Mar 13 2014, 11:03:55) 
			[GCC 4.7.2] on linux2
			Type "help", "copyright", "credits" or "license" for more information.
			>>> 
			```

		2. Install pip
			```bash
			crn@debian:~$ sudo python get-pip.py 
			[sudo] password for crn: 
			Downloading/unpacking pip
			  Downloading pip-1.5.6-py2.py3-none-any.whl (1.0MB): 1.0MB downloaded
			Downloading/unpacking setuptools
			  Downloading setuptools-4.0.1-py2.py3-none-any.whl (549kB): 549kB downloaded
			Installing collected packages: pip, setuptools
			Successfully installed pip setuptools
			Cleaning up...
			```

		3. Download ZIP file and unzip it
			```bash
			crn@debian:~$ wget .../omf-0.1.zip
			crn@debian:~$ unzip omf-0.1.zip 
			```

		4. Install from `setup.py`. 
			```bash
			crn@debian:~$ sudo python setup.py develop # suggested to install in develop mode
			...
			Using /usr/lib/python2.7
			Finished processing dependencies for omf==0.1
			```
			If there is any errors, please refer to FAQ.

		5. Test OMF.
			```bash
			crn@debian:~/omf-0.1$ python
			Python 2.7.3 (default, Mar 13 2014, 11:03:55) 
			[GCC 4.7.2] on linux2
			Type "help", "copyright", "credits" or "license" for more information.
			>>> import omf
			>>> from omf import models
			```
			If there is no error, which means you have installed omf successfully, check for previous steps.
		
		6. Install Gridlab-D.
			Gridlabd-D now has a .rpm package for linux installation. For Debian/Ubuntu based system, you need to convert it into .deb package using `alien`
			```
			$ sudo apt-get install alien
			$ alien gridllabd-3.0.0-1/i386.rpm
			```
			And then install the .deb package.
			
		6. Run OMF.
			```bash
			$ cd omg-0.1/omf
			$ python web.py
			```
			
		7. Uninstall OMF
			```bash
			$ cd omf-0.1$
			$ python setup.py uninstall
			```
			This will remove the link in dist-packages directory, you may still running OMF in the source folder.
			
		8. FAQ:
			NOTE: the following problems happened in a Debian Linux system. The commands may differ from different distribution os Linux systems.

			1. Install matplotlib
				```bash
				============================================================================
										* The following required packages can not be built:
										* freetype
				```
				It is a dependency of matplotlib, and pip won't install a system-level dependencies. You need to install:
				```bash
				crn@debian:~/omf-0.1$ sudo apt-get install libfreetype6-dev 
				```

			2. GCC compile:
				```bash
				gcc: error trying to exec 'cc1plus': execvp: No such file or directory
				error: Setup script exited with error: command 'gcc' failed with exit status 1
				Error in atexit._run_exitfuncs:
				```
				It is because system using `gcc` to compile matplotlib, instead of using `g++`. To fix it:
				```bash
				crn@debian:~/omf-0.1$ sudo apt-get install g++
				```


			3. Python.h missing:
				```bash
				./CXX/WrapPython.h:58:20: fatal error: Python.h: No such file or directory
				compilation terminated.
				error: Setup script exited with error: command 'gcc' failed with exit status 1
				Error in atexit._run_exitfuncs:
				```
				Python.h is nothing but a header file. It is used by gcc to build applications. You need to install a package called python-dev. This package includes header files, a static library and development tools for building Python modules, extending the Python interpreter or embedding Python in applications. To fix it:
				```bash
				crn@debian:~/omf-0.1$ sudo apt-get install python-dev
				```

			4. Missing png libs:
				```bash
				/usr/include/features.h:165:0: note: this is the location of the previous definition
				src/_png.cpp:10:20: fatal error: png.h: No such file or directory
				compilation terminated.
				error: Setup script exited with error: command 'gcc' failed with exit status 1
				Error in atexit._run_exitfuncs:
				```

			5. Nonetype error:
				```bash
				File "/usr/lib/python2.7/distutils/command/config.py", line 248, in try_link
					self._check_compiler()
				  File "/tmp/easy_install-w3AiAT/numpy-1.8.1/numpy/distutils/command/config.py", line 46, in _check_compiler
				  File "/usr/lib/python2.7/distutils/command/config.py", line 103, in _check_compiler
					customize_compiler(self.compiler)
				  File "/tmp/easy_install-CbBzw1/matplotlib-1.3.1/setupext.py", line 194, in my_customize_compiler
				TypeError: 'NoneType' object is not callable
				Error in atexit._run_exitfuncs:
				Traceback (most recent call last):
				  File "/usr/lib/python2.7/atexit.py", line 24, in _run_exitfuncs
					func(*targs, **kargs)
				  File "/usr/lib/python2.7/multiprocessing/util.py", line 284, in _exit_function
					info('process shutting down')
				TypeError: 'NoneType' object is not callable
				Error in sys.exitfunc:
				```
				It is because the when checking the system error, you need to change system encoding from __ascii__ to __utf-8__. To fix it in python command:
				```bash
				crn@debian:~/omf-0.1$ python 
				Python 2.7.3 (default, Mar 13 2014, 11:03:55) 
				[GCC 4.7.2] on linux2
				Type "help", "copyright", "credits" or "license" for more information.
				>>> import sys
				>>> sys.getdefaultencoding()
				'ascii'
				>>> reload(sys)
				<module 'sys' (built-in)>
				>>> sys.setdefaultencoding("UTF-8")
				>>> sys.getdefaultencoding()
				'UTF-8'
				```

			6. `numpy` and `matplotlib` error:
				```bash
				Cannot compile 'Python.h'. Perhaps you need to install python-dev|python-devel.
				```
				It is highly recommended to install numpy and matplotlib separately. Since the compile processing in omf installation is a bit intricate. 
				```bash
				$ sudo pip install numpy, matplotlib
				```		

6. Register PyPI package

7. Upload package to PyPI

__Some useful references of packaging distribution__

* The Hitchhiker's guide to packaging, [link](http://guide.python-distribute.org/index.html)

* setup() function parameters, one from [distutils.core](https://docs.python.org/2/distutils/apiref.html?highlight=setup), and another one is from [setuptools](http://pythonhosted.org/setuptools/setuptools.html?highlight=setup#new-and-changed-setup-keywords)

* A tedious instruction for python distribution [distutils](https://docs.python.org/2/distutils/index.html).