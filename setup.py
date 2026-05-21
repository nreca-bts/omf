import os
from setuptools import find_packages, setup

#HACK: keep matplotlib from breaking out of sandboxes on Windows.
os.environ["MPLCONFIGDIR"] = "."

with open("requirements.txt") as requirements_file:
	install_requires = [
		line.strip()
		for line in requirements_file
		if line.strip() and not line.startswith("#")
	]

setup(
	name = 'omf',
	version = '1.0.0',
	description = 'An Open Modeling Framework (omf) for power systems simulation.',
	long_description = open("readme.md", encoding="utf-8").read(),
	long_description_content_type = "text/markdown",
	author = 'David Pinney',
	author_email = 'david.pinney@nreca.coop',	
	url = 'https://github.com/nreca-bts/omf',
	packages = find_packages(include=["omf", "omf.*"], exclude=["omf.scratch*", "omf.build*", "omf.dist*"]),
	include_package_data=True,
	classifiers=[
		'Development Status :: 4 - Beta',
		'Environment :: Web Environment',
		'Intended Audience :: Developers',
		'License :: GPLv2',
		'Operating System :: OS Independent',
		'Programming Language :: Python',
		'Programming Language :: Python :: 3',
		'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
		'Topic :: Software Development :: Libraries :: Python Modules'],
	license = 'GPLv2',
	platforms = 'any',
	zip_safe = False, 
	python_requires = ">=3.9",
	install_requires = install_requires,
	extras_require = {
		"ml": ["tensorflow"],
	},
)
