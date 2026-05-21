"""
Convert feeder models between OpenDSS, GridLAB-D, and OMF tree representations.
"""

# Prereq: `pip install 'git+https://github.com/NREL/ditto.git@master#egg=ditto[all]'`
import os
import json
import warnings
import random
import math
import tempfile
import networkx as nx
from collections import OrderedDict, defaultdict

# Wireframe for new OMD objects:
newFeederWireframe = {
	"links":[],
	"hiddenLinks":[],
	"nodes":[],
	"hiddenNodes":[],
	"layoutVars":{"theta":"0.8","gravity":"0.01","friction":"0.9","linkStrength":"5","linkDistance":"5","charge":"-5"},
	"tree": {},
	"attachments":{}
}

def cyme_to_dss(cyme_dir, out_path, inter_dir=None):
	''' Converts cyme txt files into an opendss file with nrel/ditto.
	Need equipment.txt, load.txt, and network.txt in cyme_dir '''
	if inter_dir:
		tdir = inter_dir
	else:
		tdir = tempfile.mkdtemp()
	print('Ditto Conversion Dir:', tdir)
	root = os.path.abspath(cyme_dir)
	cmd = f'ditto-cli convert --from cyme --input "{root}" --to opendss --output {tdir}'
	os.system(cmd)
	dss_to_clean_via_save(f'{tdir}/Master.dss', out_path)

def gld_to_dss(glm_path, out_path, inter_dir=None):
	''' Converts GridLAB-D files to opendss with nrel/ditto'''
	if inter_dir:
		tdir = inter_dir
	else:
		tdir = tempfile.mkdtemp()
	print('Ditto Conversion Dir:', tdir)
	root = os.path.abspath(glm_path)
	cmd = f'ditto-cli convert --from glm --input "{root}" --to opendss --output {tdir}'
	os.system(cmd)
	dss_to_clean_via_save(f'{tdir}/Master.dss', out_path)

def dss_to_gld(opendss_path, out_path, inter_dir=None):
	''' Converts opendss files to GridLAB-D with nrel/ditto'''
	#TODO: test.
	if inter_dir:
		tdir = inter_dir
	else:
		tdir = tempfile.mkdtemp()
	print('Ditto Conversion Dir:', tdir)
	root = os.path.abspath(opendss_path)
	cmd = f'ditto-cli convert --from opendss --input "{root}" --to glm --output {tdir}'
	os.system(cmd)
	dss_to_clean_via_save(f'{tdir}/Master.dss', out_path)

def fix_repeated_keys(line_str):
	''' Take a DSS transformer line and merge the repeated keys.'''
	line = line_str.split(' ')
	verb = line[0]
	pairs = line[1:]
	pair_pairs = [p.split('=') for p in pairs]
	d = defaultdict(list)
	for k, v in pair_pairs:
		d[k].append(v)
	out_str = f'{verb} '
	for k,v in d.items():
		if len(v) == 1:
			out_str = out_str + f'{k}={v[0]} '
		elif len(v)	> 1:
			if k == 'wdg':
				continue #drop wdg keys
			if k == '%r':
				k = '%rs'
			out_str = out_str + f'{k}=[{",".join(v)}] '
	return out_str

def dss_to_clean_via_save(dss_file, clean_out_path, add_pf_syntax=True, clean_up=False, fix_rptd_keys=True):
	'''Updated function for OpenDSS v1.7.4 which does everything differently from earlier versions...
	Converts raw OpenDSS circuit definition files to the *.clean.dss syntax required by OMF.
	This version uses the opendss save functionality to better preserve dss syntax.'''
	# Execute opendss's save command reliably on a circuit. opendssdirect fails at this.
	import os, re, shutil, subprocess
	dirname = os.path.dirname(dss_file)
	shutil.rmtree(f'{dirname}/SAVED_DSS', ignore_errors=True)
	# Make a dss file that can reliably save a dang circuit.
	contents = open(dss_file,'r').read()
	contents += '\nsave circuit dir=SAVED_DSS'
	with open(f'{dirname}/saver.dss','w') as saver_file:
		saver_file.write(contents)
	# Run that saver file.
	subprocess.run(['opendsscmd', 'saver.dss'], cwd=dirname)
	dss_folder_path = f'{dirname}/SAVED_DSS'
	# Get the object file paths
	ob_files = os.listdir(f'{dss_folder_path}')
	oops_folders = [x for x in ob_files if os.path.isdir(f'{dss_folder_path}/{x}')]
	# HACK: Handle subfolders
	for folder in oops_folders:
		ob_files.extend([f'{folder}/{x}' for x in os.listdir(f'{dss_folder_path}/{folder}')])
		ob_files.remove(folder)
	# Generate clean each of the object files.
	clean_copies = {}
	print('All files detected:', ob_files)
	for fname in ob_files:
		with open(f'{dss_folder_path}/{fname}', 'r') as ob_file:
			ob_data = ob_file.read().lower() # lowercase everything
			ob_data = ob_data.replace('"', '') # remove quote characters
			ob_data = ob_data.replace('\t', ' ') # tabs to spaces
			ob_data = re.sub(r' +', r' ', ob_data) # remove consecutive spaces
			ob_data = re.sub(r'(^ +| +$)', r'', ob_data) # remove leading and trailing whitespace
			ob_data = ob_data.replace('\n~', '') # remove tildes
			ob_data = re.sub(r' *, *', r',', ob_data) # remove spaces around commas
			ob_data = re.sub(r', *(\]|\))', r'\1', ob_data) # remove empty final list items
			ob_data = re.sub(r' +\| +', '|', ob_data) # remove spaces around bar characters
			ob_data = re.sub(r'(\[|\() *', r'\1', ob_data) # remove spaces after list start
			ob_data = re.sub(r' *(\]|\))', r'\1', ob_data) # remove spaces before list end
			ob_data = re.sub(r'(new|edit) ', r'\1 object=', ob_data) # add object= key
			ob_data = re.sub(r'(\d) +(\d|\-)', r'\1,\2', ob_data) # replace space-separated lists with comma-separated
			ob_data = re.sub(r'(\d) +(\d|\-)', r'\1,\2', ob_data) # HACK: second space-sep replacement to make sure it works
			ob_data = re.sub(r'zipv=([\d\.\-,]+)', r'zipv=(\1)', ob_data) # HACK: fix zipv with missing parens
			ob_data = re.sub(r'(redirect |buscoords |giscoords |makebuslist)', r'! \1', ob_data) # remove troublesome Master.dss redirects.
			clean_copies[fname.lower()] = ob_data
	# Move subfolder data into main folder content list
	# Need to loop through list(clean_copies.keys()), not clean_copies because otherwise you may change dict keys while iterating through that dict, causing an error
	for fname in list(clean_copies.keys()):
		if '/' in fname:
			folder, sub_fname = fname.split('/')
			if sub_fname in clean_copies:
				print(f'WARNING! Combining {sub_fname} with other subfolder data')
				clean_copies[sub_fname] += '\n\n\n' + clean_copies[fname]
			else:
				clean_copies[sub_fname] = clean_copies[fname]
			del clean_copies[fname]
	print('CLEAN COPIES AFTER MERGE:', clean_copies.keys())
	# Special handling for buscoords
	if 'buscoords.dss' in clean_copies:
		bus_data = clean_copies['buscoords.dss']
		nice_buses = re.sub(r'([\w_\-\.]+),([\w_\-\.]+),([\w_\-\.]+)', r'setbusxy bus=\1 x=\2 y=\3', bus_data)
		clean_copies['buscoords.dss'] = 'makebuslist\n' + nice_buses
	#HACK: This is the order in which things need to be inserted or opendss errors out. Lame! Also note that pluralized things are from subfolders.
	CANONICAL_DSS_ORDER = ['master.dss', 'loadshape.dss', 'vsource.dss', 'transformer.dss', 'transformers.dss', 'reactor.dss', 'regcontrol.dss', 'cndata.dss', 'wiredata.dss', 'linegeometry.dss', 'linecode.dss', 'spectrum.dss', 'swtcontrol.dss', 'tcc_curve.dss', 'capacitor.dss', 'capacitors.dss', 'growthshape.dss', 'line.dss', 'branches.dss', 'capcontrol.dss', 'generator.dss', 'pvsystem.dss', 'load.dss', 'loads.dss', 'energymeter.dss', 'fault.dss', 'relay.dss', 'recloser.dss', 'fuse.dss', 'indmach012.dss', 'monitor.dss', 'buscoords.dss', 'busvoltagebases.dss']
	# Note files we got that aren't in canonical files:
	for fname in clean_copies:
		if fname not in CANONICAL_DSS_ORDER:
			print(f'File available but ignored: {fname}')
	# Construct output from files, ignoring master, which is bugged in opendss as of 2023-01-17
	clean_out = ''
	for fname in CANONICAL_DSS_ORDER:
		if fname not in clean_copies:
			print(f'Missing file: {fname}')
		else:
			clean_out += f'\n\n!!!{fname}\n'
			clean_out += clean_copies[fname]
	clean_out = clean_out.lower()
	# Optional: include a slug of code to run powerflow
	if add_pf_syntax:
		powerflow_slug = '\n\n!powerflow code\nset maxiterations=1000\nset maxcontroliter=1000\ncalcv\nsolve\nshow quantity=voltage'
		clean_out = clean_out + powerflow_slug
	# Optional: Fix repeated wdg=X keys, where x=2
	if fix_rptd_keys:
		cleaner_out = ''
		for line in clean_out.split('\n'):
			if '\"transformer' in line:
				line = fix_repeated_keys(line)
			cleaner_out += line + '\n'
		clean_out = cleaner_out
	# Optional: remove intermediate files and write a single clean file.
	if clean_up:
		shutil.rmtree(dss_folder_path, ignore_errors=True)
		try:
			os.remove(f'{dirname}/saver.dss')
		except:
			pass
	with open(clean_out_path, 'w') as out_file:
		out_file.write(clean_out)

def _dss_to_clean_via_save_toBeTested(dss_file, clean_out_path, add_pf_syntax=True, clean_up=False, fix_rptd_keys=True):
	''' Contains clearly marked additions that have not been rigorously tested yet.
	
	Updated function for OpenDSS v1.7.4 which does everything differently from earlier versions...
	Converts raw OpenDSS circuit definition files to the *.clean.dss syntax required by OMF.
	This version uses the opendss save functionality to better preserve dss syntax.'''
	# Execute opendss's save command reliably on a circuit. opendssdirect fails at this.
	import os, re, shutil, subprocess
	dirname = os.path.dirname(dss_file)
	shutil.rmtree(f'{dirname}/SAVED_DSS', ignore_errors=True)
	# Make a dss file that can reliably save a dang circuit.
	contents = open(dss_file,'r').read()
	contents += '\nsave circuit dir=SAVED_DSS'
	with open(f'{dirname}/saver.dss','w') as saver_file:
		saver_file.write(contents)
	# Run that saver file.
	subprocess.run(['opendsscmd', 'saver.dss'], cwd=dirname)
	dss_folder_path = f'{dirname}/SAVED_DSS'
	# Get the object file paths
	ob_files = os.listdir(f'{dss_folder_path}')
	oops_folders = [x for x in ob_files if os.path.isdir(f'{dss_folder_path}/{x}')]
	# HACK: Handle subfolders
	for folder in oops_folders:
		ob_files.extend([f'{folder}/{x}' for x in os.listdir(f'{dss_folder_path}/{folder}')])
		ob_files.remove(folder)
	# Generate clean each of the object files.
	clean_copies = {}
	print('All files detected:', ob_files)
	for fname in ob_files:
		with open(f'{dss_folder_path}/{fname}', 'r') as ob_file:
			ob_data = ob_file.read().lower() # lowercase everything
			ob_data = ob_data.replace('"', '') # remove quote characters
			ob_data = ob_data.replace('\t', ' ') # tabs to spaces
			ob_data = re.sub(r' +', r' ', ob_data) # remove consecutive spaces
			ob_data = re.sub(r'(^ +| +$)', r'', ob_data) # remove leading and trailing whitespace
			ob_data = ob_data.replace('\n~', '') # remove tildes
			ob_data = re.sub(r' *, *', r',', ob_data) # remove spaces around commas
			ob_data = re.sub(r', *(\]|\))', r'\1', ob_data) # remove empty final list items

			##########
			# - Austin
			##########
			#ob_data = re.sub(r' +\| +', '|', ob_data) # remove spaces around bar characters
			ob_data = re.sub(r'\s*\|\s*', '|', ob_data) # remove spaces around bar characters
			##########
			# - Austin
			##########

			ob_data = re.sub(r'(\[|\() *', r'\1', ob_data) # remove spaces after list start
			ob_data = re.sub(r' *(\]|\))', r'\1', ob_data) # remove spaces before list end
			ob_data = re.sub(r'(new|edit) ', r'\1 object=', ob_data) # add object= key
			ob_data = re.sub(r'(\d) +(\d|\-)', r'\1,\2', ob_data) # replace space-separated lists with comma-separated
			ob_data = re.sub(r'(\d) +(\d|\-)', r'\1,\2', ob_data) # HACK: second space-sep replacement to make sure it works
			ob_data = re.sub(r'zipv=([\d\.\-,]+)', r'zipv=(\1)', ob_data) # HACK: fix zipv with missing parens
			ob_data = re.sub(r'(redirect |buscoords |giscoords |makebuslist)', r'! \1', ob_data) # remove troublesome Master.dss redirects.
			clean_copies[fname.lower()] = ob_data
	# Move subfolder data into main folder content list
	# Need to loop through list(clean_copies.keys()), not clean_copies because otherwise you may change dict keys while iterating through that dict, causing an error
	for fname in list(clean_copies.keys()):
		if '/' in fname:
			folder, sub_fname = fname.split('/')
			if sub_fname in clean_copies:
				print(f'WARNING! Combining {sub_fname} with other subfolder data')
				clean_copies[sub_fname] += '\n\n\n' + clean_copies[fname]
			else:
				clean_copies[sub_fname] = clean_copies[fname]
			del clean_copies[fname]
	print('CLEAN COPIES AFTER MERGE:', clean_copies.keys())
	# Special handling for buscoords
	if 'buscoords.dss' in clean_copies:
		bus_data = clean_copies['buscoords.dss']
		nice_buses = re.sub(r'([\w_\-\.]+),([\w_\-\.]+),([\w_\-\.]+)', r'setbusxy bus=\1 x=\2 y=\3', bus_data)
		clean_copies['buscoords.dss'] = 'makebuslist\n' + nice_buses
	#HACK: This is the order in which things need to be inserted or opendss errors out. Lame! Also note that pluralized things are from subfolders.
	##########
	# - Saeed
	##########
	# Added 'xycurve.dss', 'invcontrol.dss', 'storage.dss' to  CANONICAL_DSS_ORDER after 'pvsystem.dss' and before 'load.dss'
	# CANONICAL_DSS_ORDER = ['master.dss', 'loadshape.dss', 'vsource.dss', 'transformer.dss', 'transformers.dss', 'reactor.dss', 'regcontrol.dss', 'cndata.dss', 'wiredata.dss', 'linegeometry.dss', 'linecode.dss', 'spectrum.dss', 'swtcontrol.dss', 'tcc_curve.dss', 'capacitor.dss', 'capacitors.dss', 'growthshape.dss', 'line.dss', 'branches.dss', 'capcontrol.dss', 'generator.dss', 'pvsystem.dss', 'load.dss', 'loads.dss', 'energymeter.dss', 'fault.dss', 'relay.dss', 'recloser.dss', 'fuse.dss', 'indmach012.dss', 'monitor.dss', 'buscoords.dss', 'busvoltagebases.dss']
	CANONICAL_DSS_ORDER = ['master.dss', 'loadshape.dss', 'vsource.dss', 'transformer.dss', 'transformers.dss', 'reactor.dss', 'regcontrol.dss', 'cndata.dss', 'wiredata.dss', 'linegeometry.dss', 'linecode.dss', 'spectrum.dss', 'swtcontrol.dss', 'tcc_curve.dss', 'capacitor.dss', 'capacitors.dss', 'growthshape.dss', 'line.dss', 'branches.dss', 'capcontrol.dss', 'generator.dss', 'pvsystem.dss', 'xycurve.dss', 'invcontrol.dss', 'storage.dss', 'load.dss', 'loads.dss', 'energymeter.dss', 'fault.dss', 'relay.dss', 'recloser.dss', 'fuse.dss', 'indmach012.dss', 'monitor.dss', 'buscoords.dss', 'busvoltagebases.dss']
	##########
	# - Saeed
	##########
	# Note files we got that aren't in canonical files:
	for fname in clean_copies:
		if fname not in CANONICAL_DSS_ORDER:
			print(f'File available but ignored: {fname}')
	# Construct output from files, ignoring master, which is bugged in opendss as of 2023-01-17
	clean_out = ''
	for fname in CANONICAL_DSS_ORDER:
		if fname not in clean_copies:
			print(f'Missing file: {fname}')
		else:
			clean_out += f'\n\n!!!{fname}\n'
			clean_out += clean_copies[fname]
	clean_out = clean_out.lower()
	# Optional: include a slug of code to run powerflow
	if add_pf_syntax:
		powerflow_slug = '\n\n!powerflow code\nset maxiterations=1000\nset maxcontroliter=1000\ncalcv\nsolve\nshow quantity=voltage'
		clean_out = clean_out + powerflow_slug
	# Optional: Fix repeated wdg=X keys, where x=2
	if fix_rptd_keys:
		cleaner_out = ''
		for line in clean_out.split('\n'):
			if '\"transformer' in line:
				line = fix_repeated_keys(line)
			cleaner_out += line + '\n'
		clean_out = cleaner_out
	# Optional: remove intermediate files and write a single clean file.
	if clean_up:
		shutil.rmtree(dss_folder_path, ignore_errors=True)
		try:
			os.remove(f'{dirname}/saver.dss')
		except:
			pass
	with open(clean_out_path, 'w') as out_file:
		out_file.write(clean_out)

def dssToTree(pathToDssOrString, is_path=True):
	''' Convert a .dss file to an in-memory, OMF-compatible 'tree' object.
	Note that we only support a VERY specifically-formatted DSS file.'''
	# TODO: Consider removing the handling for 'wdg=' syntax within this block, as we will not support it in an input file. 
	# Ingest file.
	if is_path:
		with open(pathToDssOrString, 'r') as dssFile:
			contents = dssFile.readlines()
	else:
		contents = pathToDssOrString.splitlines()
	# Lowercase everything. OpenDSS is case insensitive.
	contents = [x.lower() for x in contents]
	# Clean up the file.
	for i, line in enumerate(contents):
		# Remove whitespace.
		contents[i] = line.strip()
		# Comment removal
		bangLoc = line.find('!') #NOTE: we don't remove // style quotes, which is a BUG but is also a feature if it's a single line comment and it's still structured as a valid DSS object in our style.
		if bangLoc != -1:
			contents[i] = line[:bangLoc]
		# Join using the tilde (~) syntax
		if line.startswith('~'):
			# Look back to find the first line with content.
			for j in range(i - 1, 0, -1):
				if contents[j] != '':
					contents[j] = contents[j] + contents[i].replace('~', ' ')
					contents[i] = ''
					break
	# Capture original line numbers and drop blanks
	contents = dict([(c,x) for (c, x) in enumerate(contents) if x != ''])
	# Lex it
	for i, line in contents.items():
		jpos = 0
		try:
			#HACK: only support white space separation of attributes.
			contents[i] = line.split()
			#HACK: only support = assignment of values.
			ob = OrderedDict() 
			ob['!CMD'] = contents[i][0]
			if len(contents[i]) > 1:
				for j in range(1, len(contents[i])):
					jpos = j
					k,v = contents[i][j].split('=')
					ob[k] = v
			contents[i] = ob
		except:
			raise Exception(f'Error encountered in group (space delimited) #{jpos+1} of line {i + 1}: {line}')
		contents[i] = ob
	return list(contents.values())

def treeToDss(treeObject, outputPath):
	"""
	Perform tree to dss processing for the wrapped solver workflow.
	"""
	outFile = open(outputPath, 'w')
	for ob in treeObject:
		line = ob['!CMD']
		for key in ob:
			if not key.startswith('!'):
				line = f"{line} {key}={ob[key]}"
			if key.startswith('!TEST'):
				line = f"{line} {ob['!TEST']}"
		outFile.write(line + '\n')
	outFile.close()

def _treeToDss_toBeTested(treeObject, outputPath):
	''' Contains clearly marked additions that have not been rigorously tested yet.'''
	outFile = open(outputPath, 'w')
	for ob in treeObject:
		line = ob['!CMD']
		for key in ob:
			if not key.startswith('!'):
				##########
				# - Saeed
				##########
				if key == 'element' and '.' not in ob.get('element'):
					ob['element'] = f"line.{ob['element']}"
				if key == 'monitoredobj' and '.' not in ob.get('monitoredobj'):
					ob['monitoredobj'] = f"line.{ob['monitoredobj']}"
				##########
				# - Saeed
				##########
				line = f"{line} {key}={ob[key]}"
			if key.startswith('!TEST'):
				line = f"{line} {ob['!TEST']}"
		outFile.write(line + '\n')
	outFile.close()

def _extend_with_exc(from_d, to_d, exclude_list):
	''' Add all items in from_d to to_d that aren't in exclude_list. '''
	good_items = {k: from_d[k] for k in from_d if k not in exclude_list}
	to_d.update(good_items)

def evilDssTreeToGldTree(dssTree):
	''' World's worst and ugliest converter. Hence evil. 
	We built this to do quick-and-dirty viz of openDSS files. '''
	gldTree = {}
	g_id = 1
	# Build bad gld representation of each object
	bus_names = []
	bus_with_coords = []
	# Handle all the components.
	for ob in dssTree:
		try:
			if ob['!CMD'] == 'setbusxy':
				gldTree[str(g_id)] = {
					'object': 'bus',
					'name': ob['bus'],
					'latitude': ob['y'],
					'longitude': ob['x']
				}
				bus_with_coords.append(ob['bus'])
			elif ob['!CMD'] == 'new':
				obtype, name = ob['object'].split('.')
				if 'bus1' in ob and 'bus2' in ob:
					# line-like object. includes reactors.
					fro, froCode = ob['bus1'].split('.', maxsplit=1)
					to, toCode = ob['bus2'].split('.', maxsplit=1)
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'from': fro,
						'to': to,
						'!FROCODE': '.' + froCode,
						'!TOCODE': '.' + toCode
					}
					bus_names.extend([fro, to])
					stuff = gldTree[str(g_id)]
					_extend_with_exc(ob, stuff, ['object','bus1','bus2','!CMD'])
				elif 'buses' in ob:
					#transformer-like object.
					bb = ob['buses']
					bb = bb.replace(']','').replace('[','').split(',')
					b1 = bb[0]
					fro, froCode = b1.split('.', maxsplit=1)
					ob['!FROCODE'] = '.' + froCode
					b2 = bb[1]
					to, toCode = b2.split('.', maxsplit=1)
					ob['!TOCODE'] = '.' + toCode
					gldobj = {
						'object': obtype,
						'name': name,
						'from': fro,
						'to': to
					}
					bus_names.extend([fro, to])
					if len(bb)==3:
						b3 = bb[2]
						to2, to2Code = b3.split('.', maxsplit=1)
						ob['!TO2CODE'] = '.' + to2Code
						gldobj['to2'] = to2
						bus_names.append(to2)
					gldTree[str(g_id)] = gldobj
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','buses','!CMD'])
				elif 'bus' in ob:
					#load-like object.
					bus_root, connCode = ob['bus'].split('.', maxsplit=1)
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'parent': bus_root,
						'!CONNCODE': '.' + connCode
					}
					bus_names.append(bus_root)
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus','!CMD'])
				elif 'bus1' in ob and 'bus2' not in ob:
					#load-like object, alternate syntax
					try:
						bus_root, connCode = ob['bus1'].split('.', maxsplit=1)
						ob['!CONNCODE'] = '.' + connCode
					except:
						bus_root = ob['bus1'] # this shoudln't happen if the .clean syntax guide is followed.
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'parent': bus_root,
					}
					bus_names.append(bus_root)
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus1','!CMD'])
				elif 'element' in ob:
					#control object (connected to another object instead of a bus)
					#cobtype, cobname, connCode = ob['element'].split('.', maxsplit=2)
					cobtype, cobname = ob['element'].split('.', maxsplit=1)
					# if obtype == 'capcontrol':
					# 	obparent = ob['capacitor']
					# else:
					# 	obparent = cobtype + '.' + cobname
					obparent = cobtype + '.' + cobname
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'parent': obparent,
					}
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','element','!CMD'])
				else:
					#config-like object
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name
					}
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','!CMD'])
			elif ob.get('object','').split('.')[0]=='vsource':
				obtype, name = ob['object'].split('.')
				conn, connCode = ob.get('bus1').split('.', maxsplit=1)
				gldTree[str(g_id)] = {
					'object': obtype,
					'name': name,
					'parent': conn,
					'!CONNCODE': '.' + connCode
				}
				_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus1'])
			elif ob['!CMD'] in ['edit','open','close']:
				#TODO: handle edited objects? maybe just extend the 'new' block (excluding vsource) because the functionality is basically the same.
				warnings.warn(f"Ignored 'edit' command: {ob}")
			elif ob['!CMD'] not in ['new', 'setbusxy', 'edit']:
				#command-like objects.
				gldTree[str(g_id)] = {
					'object': '!CMD',
					'name': ob['!CMD']
				}
				_extend_with_exc(ob, gldTree[str(g_id)], ['!CMD', 'object', 'name'])
			else:
				warnings.warn(f"Ignored {ob}")
			g_id += 1
		except:
			raise Exception(f"\n\nError encountered on parsing object {ob}\n")
	# Warn on buses with no coords.
	#no_coord_buses = set(bus_names) - set(bus_with_coords)
	#if len(no_coord_buses) != 0:
		#warnings.warn(f"Buses without coordinates:{no_coord_buses}")
	return gldTree

def _evilDssTreeToGldTree_toBeTested(dssTree):
	''' Contains clearly marked additions that have not been rigorously tested yet.
	
	World's worst and ugliest converter. Hence evil. 
	We built this to do quick-and-dirty viz of openDSS files. '''
	gldTree = {}
	g_id = 1
	# Build bad gld representation of each object
	bus_names = []
	bus_with_coords = []
	# Handle all the components.
	for ob in dssTree:
		try:
			if ob['!CMD'] == 'setbusxy':
				gldTree[str(g_id)] = {
					'object': 'bus',
					'name': ob['bus'],
					'latitude': ob['y'],
					'longitude': ob['x']
				}
				bus_with_coords.append(ob['bus'])
			elif ob['!CMD'] == 'new':
				obtype, name = ob['object'].split('.')
				if 'bus1' in ob and 'bus2' in ob:
					# line-like object. includes reactors.
					fro, froCode = ob['bus1'].split('.', maxsplit=1)
					to, toCode = ob['bus2'].split('.', maxsplit=1)
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'from': fro,
						'to': to,
						'!FROCODE': '.' + froCode,
						'!TOCODE': '.' + toCode
					}
					bus_names.extend([fro, to])
					stuff = gldTree[str(g_id)]
					_extend_with_exc(ob, stuff, ['object','bus1','bus2','!CMD'])
				elif 'buses' in ob:
					#transformer-like object.
					bb = ob['buses']
					bb = bb.replace(']','').replace('[','').split(',')
					##########
					# - Austin
					##########
					# - TODO: how do we handle delta-connected transformer windings? We don't currently
					b1 = bb[0]
					if '.' not in b1:
						if int(ob.get('phases')) == 1:
							b1 += '.1'
						elif int(ob.get('phases')) == 2:
							b1 += '.1.2'
						elif int(ob.get('phases')) == 3:
							b1 += '.1.2.3'
					fro, froCode = b1.split('.', maxsplit=1)
					ob['!FROCODE'] = '.' + froCode
					b2 = bb[1]
					if '.' not in b2:
						if int(ob.get('phases')) == 1:
							b2 += '.1'
						elif int(ob.get('phases')) == 2:
							b2 += '.1.2'
						elif int(ob.get('phases')) == 3:
							b2 += '.1.2.3'
					##########
					# - Austin
					##########
					to, toCode = b2.split('.', maxsplit=1)
					ob['!TOCODE'] = '.' + toCode
					gldobj = {
						'object': obtype,
						'name': name,
						'from': fro,
						'to': to
					}
					bus_names.extend([fro, to])
					if len(bb)==3:
						b3 = bb[2]
						to2, to2Code = b3.split('.', maxsplit=1)
						ob['!TO2CODE'] = '.' + to2Code
						gldobj['to2'] = to2
						bus_names.append(to2)
					gldTree[str(g_id)] = gldobj
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','buses','!CMD'])
				elif 'bus' in ob:
					#load-like object.
					bus_root, connCode = ob['bus'].split('.', maxsplit=1)
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'parent': bus_root,
						'!CONNCODE': '.' + connCode
					}
					bus_names.append(bus_root)
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus','!CMD'])
				elif 'bus1' in ob and 'bus2' not in ob:
					#load-like object, alternate syntax
					try:
						bus_root, connCode = ob['bus1'].split('.', maxsplit=1)
						ob['!CONNCODE'] = '.' + connCode
					except:
						bus_root = ob['bus1'] # this shoudln't happen if the .clean syntax guide is followed.
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'parent': bus_root,
					}
					bus_names.append(bus_root)
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus1','!CMD'])
				elif 'element' in ob:
					#control object (connected to another object instead of a bus)
					#cobtype, cobname, connCode = ob['element'].split('.', maxsplit=2)
					cobtype, cobname = ob['element'].split('.', maxsplit=1)
					# if obtype == 'capcontrol':
					# 	obparent = ob['capacitor']
					# else:
					# 	obparent = cobtype + '.' + cobname
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
				##########
				# - Saeed
				##########
				# TODO: Scrutinize this change extra -Saeed
						'parent': cobname,
					}
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','element','!CMD'])
				elif 'monitoredobj' in ob:
					cobtype, cobname = ob['monitoredobj'].split('.', maxsplit=1)
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name,
						'monitoredobj': cobname,
					}
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','monitoredobj','!CMD'])
				##########
				# - Saeed
				##########
				else:
					#config-like object
					gldTree[str(g_id)] = {
						'object': obtype,
						'name': name
					}
					_extend_with_exc(ob, gldTree[str(g_id)], ['object','!CMD'])
			elif ob.get('object','').split('.')[0]=='vsource':
				obtype, name = ob['object'].split('.')
				##########
				# - Austin
				##########
				if '.' not in ob['bus1']:
					ob['bus1'] += '.1.2.3'
				##########
				# - Austin
				##########
				conn, connCode = ob.get('bus1').split('.', maxsplit=1)
				gldTree[str(g_id)] = {
					'object': obtype,
					'name': name,
					'parent': conn,
					'!CONNCODE': '.' + connCode
				}
				_extend_with_exc(ob, gldTree[str(g_id)], ['object','bus1'])
			elif ob['!CMD'] in ['edit','open','close']:
				#TODO: handle edited objects? maybe just extend the 'new' block (excluding vsource) because the functionality is basically the same.
				warnings.warn(f"Ignored 'edit' command: {ob}")
			elif ob['!CMD'] not in ['new', 'setbusxy', 'edit']:
				#command-like objects.
				gldTree[str(g_id)] = {
					'object': '!CMD',
					'name': ob['!CMD']
				}
				_extend_with_exc(ob, gldTree[str(g_id)], ['!CMD', 'object', 'name'])
			else:
				warnings.warn(f"Ignored {ob}")
			g_id += 1
		except:
			raise Exception(f"\n\nError encountered on parsing object {ob}\n")
	# Warn on buses with no coords.
	#no_coord_buses = set(bus_names) - set(bus_with_coords)
	#if len(no_coord_buses) != 0:
		#warnings.warn(f"Buses without coordinates:{no_coord_buses}")
	return gldTree

def evilGldTreeToDssTree(evil_gld_tree):
	''' Inverse frontend to DSS converter. Still evil. '''
	dssTree = []
	# Put objects in order.
	all_objs = evil_gld_tree.items()
	objs_in_order = [y[1] for y in sorted(all_objs, key=lambda x:int(x[0]))]
	# Process each object.
	for ob in objs_in_order:
		try:
			if ob.get('object') == 'bus':
				new_ob = {
					'!CMD':'setbusxy',
					'bus':ob['name'],
					'x': ob['longitude'],
					'y': ob['latitude']
				}
				dssTree.append(new_ob)
			elif ob.get('object') == 'line':
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob['name'],
					'bus1': ob['from'] + ob.get('!FROCODE',''),
					'bus2': ob['to']+ ob.get('!TOCODE',''),
				}
				_extend_with_exc(ob, new_ob, ['!CMD','from','to','name','object','latitude','longitude','!FROCODE', '!TOCODE'])
				dssTree.append(new_ob)
			elif ob.get('object') == 'transformer':
				buses = f"[{ob['from']}{ob.get('!FROCODE','')},{ob['to']}{ob.get('!TOCODE','')}]" # for 2-winding xfrmrs
				exclist = ['!CMD','from','to','to2','name','object','latitude','longitude','!FROCODE','!TOCODE','windings']
				if ob.get('to2'): # for 3-winding xfrmrs
					exclist.extend(['to2','!TO2CODE'])
					buses = f"[{ob['from']}{ob.get('!FROCODE','')},{ob['to']}{ob.get('!TOCODE','')},{ob['to2']}{ob.get('!TO2CODE','')}]"
				#if ob.get('to3'): # for 4-winding xfrmrs (rare)
				#	exclist.extend(['to3','!TO3CODE'])
				#	buses = f"[{ob['from']}{ob.get('!FROCODE','')},{ob['to']}{ob.get('!TOCODE','')},{ob['to2']}{ob.get('!TO2CODE','')},{ob['to3']}{ob.get('!TO3CODE','')}]"
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob['name'],
				}
				if ob.get('windings','NWP')!='NWP':
					new_ob['windings'] = ob['windings'] # This is required to ensure correct order (because the 'windings' property triggers memory allocation and resets everything to default values)
				new_ob['buses'] = buses # 'buses' must come after 'windings', if existing.
				_extend_with_exc(ob, new_ob, exclist)
				dssTree.append(new_ob)
			elif ob.get('object') == 'reactor':
				#TODO: this block of code is same as for 'line' above. Consider combining.
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob['name'],
					'bus1': ob['from'] + ob.get('!FROCODE',''),
					'bus2': ob['to']+ ob.get('!TOCODE',''),
				}
				_extend_with_exc(ob, new_ob, ['!CMD','from','to','name','object','latitude','longitude','!FROCODE', '!TOCODE'])
				dssTree.append(new_ob)
			elif ob.get('object') == 'regcontrol':
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob.get('name',''),
				}
				if ob.get('parent','NP')!='NP':
					if ob.get('!CONNCODE','NCC')=='NCC':
						new_ob['!CONNCODE'] = '.1' # If no node info is specified, then it defaults to one-phase.
					new_ob['bus'] = ob['parent'] + ob['!CONNCODE']
				_extend_with_exc(ob, new_ob, ['parent','name','object','latitude','longitude','!CONNCODE'])
				dssTree.append(new_ob)
			elif ob.get('object') == 'capcontrol':
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob.get('name',''),
					'element': ob['parent'] + ob.get('!CONNCODE', '')
				}
				_extend_with_exc(ob, new_ob, ['parent','name','object','latitude','longitude','!CONNCODE'])
				dssTree.append(new_ob)
			elif ob.get('object') == 'energymeter':
				#TODO this block of code is the same as 'capcontrol' above. Consider combining.
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob.get('name',''),
					'element': ob['parent'] + ob.get('!CONNCODE', '')
				}
				_extend_with_exc(ob, new_ob, ['parent','name','object','latitude','longitude','!CONNCODE'])
				dssTree.append(new_ob)
			elif ob.get('object') == 'monitor':
				#TODO this block of code is the same as 'capcontrol' above. Consider combining.
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob.get('name',''),
					'element': ob['parent'] + ob.get('!CONNCODE', '')
				}
				_extend_with_exc(ob, new_ob, ['parent','name','object','latitude','longitude','!CONNCODE'])
				dssTree.append(new_ob)
			elif 'parent' in ob:
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob.get('name',''),
					'bus1': ob['parent'] + ob.get('!CONNCODE', '')
				}
				_extend_with_exc(ob, new_ob, ['parent','name','object','latitude','longitude','!CONNCODE'])
				dssTree.append(new_ob)
			elif 'bus' not in ob and 'bus1' not in ob and 'bus2' not in ob and 'buses' not in ob and ob.get('object') != '!CMD':
				# floating config type object.
				new_ob = {
					'!CMD': 'new',
					'object': ob['object'] + '.' + ob['name'],
				}
				_extend_with_exc(ob, new_ob, ['!CMD','name','object','latitude','longitude'])
				dssTree.append(new_ob)
			elif ob.get('object') == '!CMD':
				new_ob = {
					'!CMD': ob['name'],
				}
				_extend_with_exc(ob, new_ob, ['!CMD', 'name', 'object','latitude','longitude'])
				dssTree.append(new_ob)
			else:
				print(f"Unprocessed object: {ob}")
				# warnings.warn(f"Unprocessed object: {ob}")
		except:
			raise Exception(f"\n\nError encountered on parsing object {ob}\n")
	return dssTree

def evilToOmd(evilTree, outPath):
	"""
	Perform evil to omd processing for the wrapped solver workflow.
	"""
	omdStruct = dict(newFeederWireframe)
	omdStruct['syntax'] = 'DSS'
	omdStruct['tree'] = evilTree
	with open(outPath, 'w') as outFile:
		json.dump(omdStruct, outFile, indent=4)

def _name_to_key(glm):
	''' Make fast lookup map by name in a glm.
	WARNING: if the glm changes, the map will no longer be valid.'''
	mapping = {}
	for key, val in glm.items():
		if 'name' in val:
			mapping[val['name']] = key
	return mapping

def dssToOmd(dssFilePath, omdFilePath, RADIUS=0.0002, write_out=True):
	''' Converts the dss file to an OMD, returns the omd tree
	SIDE-EFFECTS: creates the OMD file'''
	# Injecting additional coordinates.
	#TODO: derive sensible RADIUS from lat/lon numbers.
	tree = dssToTree(dssFilePath)
	evil_glm = evilDssTreeToGldTree(tree)
	name_map = _name_to_key(evil_glm)
	# print(name_map)
	for ob in evil_glm.values():
		ob_name = ob.get('name','')
		ob_type = ob.get('object','')
		if 'parent' in ob:
			parent_name = ob['parent']
			if ob_type == 'capcontrol':
				cap_name = ob['capacitor']
				cap_id = name_map[cap_name]
				if 'parent' in evil_glm[cap_id]:
					parent_name = evil_glm[cap_id]['parent']
				else:
					parent_name = ob['parent']
			if ob_type == 'energymeter':
				short_parent_name = parent_name.split('.')[1]
				parent_id = name_map[short_parent_name]
				if 'parent' in evil_glm[parent_id]:
					parent_name = evil_glm[parent_id]['parent']
				elif evil_glm[parent_id].get('object','') == 'line':
					from_name = evil_glm[parent_id].get('from', None)
					to_name = evil_glm[parent_id].get('from', None)
					if from_name is not None:
						parent_name = from_name
					elif to_name is not None:
						parent_name = to_name
					else:
						parent_name = ob['parent']
			# Only do child movement if RADIUS > 0.
			if RADIUS > 0:
				if name_map.get(parent_name): # Dss files without explicity set bus coords will break on this function without this line.
					# get location of parent object.
					parent_loc = name_map[parent_name]
					parent_ob = evil_glm[parent_loc]
					parent_lat = parent_ob.get('latitude', None)
					parent_lon = parent_ob.get('longitude', None)
					# place randomly on circle around parent.
					angle = random.random()*3.14159265*2;
					x = math.cos(angle)*RADIUS;
					y = math.sin(angle)*RADIUS;
					ob['latitude'] = str(float(parent_lat) + x)
					ob['longitude'] = str(float(parent_lon) + y)
	if write_out:
		evilToOmd(evil_glm, omdFilePath)
	return evil_glm

def _dssToOmd_toBeTested(dssFilePath, omdFilePath, RADIUS=0.0002, write_out=True):
	''' Contains clearly marked additions that have not been rigorously tested yet.
	
	Converts the dss file to an OMD, returns the omd tree
	SIDE-EFFECTS: creates the OMD file'''
	# Injecting additional coordinates.
	#TODO: derive sensible RADIUS from lat/lon numbers.
	tree = dssToTree(dssFilePath)
	##########
	# - Saeed
	##########
	evil_glm = _evilDssTreeToGldTree_toBeTested(tree)
	##########
	# - Saeed
	##########
	name_map = _name_to_key(evil_glm)
	# print(name_map)
	for ob in evil_glm.values():
		ob_name = ob.get('name','')
		ob_type = ob.get('object','')
		if 'parent' in ob:
			parent_name = ob['parent']
			if ob_type == 'capcontrol':
				cap_name = ob['capacitor']
				cap_id = name_map[cap_name]
				if 'parent' in evil_glm[cap_id]:
					parent_name = evil_glm[cap_id]['parent']
				else:
					parent_name = ob['parent']
			if ob_type == 'energymeter':
				##########
				# - Saeed
				##########
				# TODO: This is here to catch issues that have arrived in round-trip-conversions (dss->omd->dss->omd). Investigate if this should be reverted when other problems are taken care of.  
				short_parent_name = parent_name.split('.')[1] if len(parent_name.split('.')) == 2 else parent_name
				##########
				# - Saeed
				##########
				parent_id = name_map[short_parent_name]
				if 'parent' in evil_glm[parent_id]:
					parent_name = evil_glm[parent_id]['parent']
				elif evil_glm[parent_id].get('object','') == 'line':
					from_name = evil_glm[parent_id].get('from', None)
					to_name = evil_glm[parent_id].get('from', None)
					if from_name is not None:
						parent_name = from_name
					elif to_name is not None:
						parent_name = to_name
					else:
						parent_name = ob['parent']
			# Only do child movement if RADIUS > 0.
			if RADIUS > 0:
				if name_map.get(parent_name): # Dss files without explicity set bus coords will break on this function without this line.
					# get location of parent object.
					parent_loc = name_map[parent_name]
					parent_ob = evil_glm[parent_loc]
					parent_lat = parent_ob.get('latitude', None)
					parent_lon = parent_ob.get('longitude', None)
					# place randomly on circle around parent.
					angle = random.random()*3.14159265*2;
					x = math.cos(angle)*RADIUS;
					y = math.sin(angle)*RADIUS;
					try:
						ob['latitude'] = str(float(parent_lat) + x)
					except Exception as e:
						raise(e)
					ob['longitude'] = str(float(parent_lon) + y)
	if write_out:
		evilToOmd(evil_glm, omdFilePath)
	return evil_glm

def omdToTree(omdFilePath):
	''' Get a nice opendss tree in memory from an OMD. '''
	omd = json.load(open(omdFilePath))
	evil_tree = omd.get('tree',{})
	dss_tree = evilGldTreeToDssTree(evil_tree)
	return dss_tree

def dss_to_networkx(dssFilePath, tree=None, omd=None):
	''' Return a networkx directed graph from a dss file. If tree is provided, build graph from that instead of the file. '''
	if tree == None:
		tree = dssToTree(dssFilePath)
	if omd == None:
		omd = evilDssTreeToGldTree(tree)
	# Gather edges, leave out source and circuit objects
	edges = [(ob['from'],ob['to']) for ob in omd.values() if 'from' in ob and 'to' in ob]
	edges_sub = [
		(ob['parent'],ob['name']) for ob in omd.values()
		if 'name' in ob and 'parent' in ob and ob.get('object') not in ['circuit', 'vsource']
	]
	full_edges = edges + edges_sub
	G = nx.DiGraph(full_edges)
	for ob in omd.values():
		if 'latitude' in ob and 'longitude' in ob:
			G.add_node(ob['name'], pos=(float(ob['longitude']), float(ob['latitude'])))
		else:
			G.add_node(ob['name'])
	return G

def getDssCoordinates(omdFilePath, outFilePath):
	''' Gets a list of location assignments for loads and buses given an omd with valid coordinates '''
	omd = json.load(open(omdFilePath))
	evil_tree = omd.get('tree',{})
	coordinateDict = {}
	for ob in evil_tree.values():
		obType = ob['object']
		obName = ob['name']
		if obType == 'bus' and obName not in coordinateDict.keys():
			print(obType + " --- " + obName)
			latitude = ob['latitude']
			longitude = ob['longitude']
			coordinateDict[obName] = (latitude, longitude)
	with open(outFilePath, "w") as coordinateListFile:
		for bus in coordinateDict.keys():
			busLat = coordinateDict[bus][0]
			busLon = coordinateDict[bus][1]
			lineStr = "setbusxy bus=" + bus + " x=" + busLon + " y=" + busLat + "\n"
			coordinateListFile.write(lineStr)

def _transformerDssWdgToArrayFormat_toBeTested(opendss_path, out_path):
	''' Takes a dss file formatted with windings defined one at a time using the wdg property for transformers and converts it to the accepted format that sets winding values all at once with arrays of values, saved to the out_path. 
		
		Example with most properties stripped out for conciseness:

		Old: New object=Transformer.t1 windings=2 wdg=1 conn=wye kv=3 wdg=2 conn=wye kv=4

		New: New object=Transformer.t1 windings=2 conns=[wye,wye] kvs=[3,4]
	'''
	listToStr = lambda lst: str(lst).replace("'","").replace(', ',',')
	with open(opendss_path, 'r') as infile:
		inputLines = infile.readlines()
	outStr = ''
	for line in inputLines:
		if 'wdg=' not in line.lower():
			outStr += line
		else:
			propertyList = line.replace('\n','').split(' ')
			propertyDict = {}
			for prop in propertyList:
				try:
					propName,propVal = prop.split('=')
					propertyDict[propName] = propertyDict.get(propName,[])+[propVal]
				except:
					continue
			# wdg = Integer representing the winding which will become the active winding for subsequent data. Not applicable to new format 
			del propertyDict['wdg']
			outLine = propertyList[0]
			for propName,propValList in propertyDict.items():
				if len(propValList) == 1 or propName.lower() == 'emerghkva':
					outLine += f' {propName}={propValList[0]}'
				elif propName == 'bus':
					outLine += f' buses={listToStr(propValList)}'
				else:
					outLine += f' {propName}s={listToStr(propValList)}'
			outStr += f'{outLine}\n'	
	with open(out_path,'w') as outfile:
		outfile.write(outStr)

def _testsFull():
	"""
	Internal helper for dss convert tests full processing.
	"""
	from omf.solvers.opendss import getVoltages, voltageCompare
	import pandas as pd
	from omf import distNetViz
	import omf
	rpt_key_lines = [
		'new object=transformer.t86066_a phases=1 windings=2 xhl=2 buses=[pc-59734.1.0,t86066.1.0] conns=[wye,wye] kvs=[7.2,0.12] kvas=[15,15] taps=[1,1] wdg=1 %r=0 rdcohms=0 wdg=2 %r=0 rdcohms=0',
		'new object=transformer.reg570190_c phases=1 windings=2 xhl=1e-6 buses=[rb133.3,reg570190.3] conns=[wye,wye] kvs=[7.2,7.2] kvas=[4723.2,4723.2] taps=[1,1] wdg=1 %r=1e-6 rdcohms=9.329269e-8 wdg=2 %r=1e-6 rdcohms=9.329269e-8 numtaps=1000 maxtap=1.1 mintap=0.9'
	]
	for line_str in rpt_key_lines:
		out_str = fix_repeated_keys(line_str)
	FNAMES =  ['ieee37.clean.dss', 'ieee123_solarRamp.clean.dss', 'iowa240.clean.dss', 'ieeeLVTestCase.clean.dss', 'ieee8500-unbal_no_fuses.clean.dss']
	for fname in FNAMES:
		fpath = omf.omfDir + '/solvers/opendss/' + fname
		print('!!!!!!!!!!!!!! dssConvert.py testing: ',fpath,' !!!!!!!!!!!!!!')
		# Roundtrip conversion test
		errorLimit = 0.01
		startvolts = getVoltages(fpath, keep_output=False)
		dsstreein = dssToTree(fpath)
		glmtree = evilDssTreeToGldTree(dsstreein)
		dsstreeout = evilGldTreeToDssTree(glmtree)
		outpath = fpath[:-4] + '_roundtrip_test.dss'
		treeToDss(dsstreeout, outpath)
		# Visualization test
		distNetViz.viz_mem(glmtree, open_file=False, forceLayout=False)
		# Voltage comparison after roundtrip test
		endvolts = getVoltages(outpath, keep_output=False)
		percSumm, diffSumm = voltageCompare(startvolts, endvolts, saveascsv=False, with_plots=False)
		maxPerrM = [percSumm.loc['RMSPE',c] for c in percSumm.columns if c.lower().startswith(' magnitude')]
		maxPerrM = pd.Series(maxPerrM).max()
		assert abs(maxPerrM) < errorLimit*100, 'The average percent error in voltage magnitude is %s, which exceeeds the threshold of %s%%.'%(maxPerrM,errorLimit*100)
		# Clean up
		os.remove(outpath)

if __name__ == '__main__':
	_testsFull()