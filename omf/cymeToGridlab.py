"""
This script converts a CYME feeder model database to an OMF feeder tree
dictionary object. The output is similar to that produced by milToGridlab.py

An example of how to call the script is shown below:
	from omf.cymeToGridlab import convertCymeModel
	feederTree = convertCymeModel(network_db, modelDir)

where:

network_db is the full path to the CYME network and equipment .mdb database file.
modelDir is the working directory for intermediate file output
"""


import csv, random, math, copy, subprocess, locale, warnings, os, json, traceback, shutil, platform
#import tempfile
from os.path import join as pJoin
import numpy as np
from numpy.linalg import inv
from omf import feeder
from omf.solvers import gridlabd

m2ft = 1.0 / 0.3048  # Conversion factor for meters to feet


def flatten(*args, **kwargs):
	dicty = dict(*args, **kwargs)
	for arg in args:
		if isinstance(arg, dict):
			for k, v in arg.items():
				dicty[k] = v
	if kwargs:
		for k, v in kwargs.items():
			dicty[k] = v
	return dicty


def _csvDump(database_file, modelDir):
	# Get the list of table names with "mdb-tables"
	if platform.system() == "Linux" or platform.system() == "Darwin":
		table_names = subprocess.Popen(
			["mdb-tables", "-1", database_file], stdout=subprocess.PIPE
		).communicate()[0]
		table_names = table_names.decode('utf-8')
		tables = table_names.split('\n')
		if not os.path.isdir((pJoin(modelDir, "cymeCsvDump"))):
			os.makedirs((pJoin(modelDir, "cymeCsvDump")))
			# Dump each table as a CSV file using "mdb-export",
			# converting " " in table names to "_" for the CSV filenames.
		for table in tables:
			if table != "":
				filename = table.replace(' ', '_') + '.csv'
				f = open(pJoin(modelDir, "cymeCsvDump", filename), "w+")
				contents = subprocess.Popen(
					["mdb-export", database_file, table], stdout=subprocess.PIPE
				).communicate()[0]
				contents = contents.decode('utf-8')
				f.write(contents)
				f.close()
	elif platform.system() == "Windows":
		# The following code uses mdb-tables in Windows 10, but requires the creators update and ubuntu
		# One big problem:  after this function dumps the csv files, python crashes. So I have to run this routine twice.
		originaldir = (
			os.getcwd()
		)  # bash command below wouldn't work if I appended path to database_file
		os.chdir(modelDir)
		database_file = database_file.split("\\")[-1]
		table_names = subprocess.Popen(
			["bash", "-c", "mdb-tables -1 " + database_file], stdout=subprocess.PIPE
		).communicate()[0]
		table_names = table_names.decode('utf-8')
		tables = table_names.split('\n')
		if not os.path.isdir((pJoin(modelDir, "cymeCsvDump"))):
			os.makedirs((pJoin(modelDir, "cymeCsvDump")))
			# Dump each table as a CSV file using "mdb-export",
			# converting " " in table names to "_" for the CSV filenames.
		for table in tables:
			if table != "":
				filename = table.replace(" ", "_") + ".csv"
				file = open(pJoin(modelDir, "cymeCsvDump", filename), "w+")
				contents = subprocess.Popen(
					["bash", "-c", "mdb-export " + database_file + " " + table], stdout=subprocess.PIPE, text=True
				).communicate()[0]
				contents = contents.decode('utf-8')
				file.write(contents)
				file.close()
		os.chdir(originaldir)


def _findNetworkId(csvFile):
	networks = []
	with open(csvFile, newline='') as f:
		csvDict = csv.DictReader(f)
		for row in csvDict:
			networks.append(row["NetworkId"])
			# HACK: For multi-source networks (Titanium), select the second source
			# Need to find a way to do this better
	if len(networks) > 1:
		return networks[1]
	else:
		# If single source network, select the only source
		return networks[0]


def _isfloat(value):
	"Helper function for _fixName."
	try:
		float(value)
		return True
	except:
		return False


def _fixName(name):
	"Function that replaces characters not allowed in name with _"
	badChar = [" ", "-", "\\", "//", "/", ":", ".", "''", "&"]
	for char in badChar:
		name = name.replace(char, "_")
		# JOHN FITZGERALD KENNEDY.  Don't allow names that start with a number
	if _isfloat(name[0]):
		name = "x" + name
	return name


phases = ["AN", "BN", "CN", "ABN", "ACN", "BCN", "ABCN"]


def _convertPhase(int_phase):
	"Function that converts a number to a phase"

	try:
		return phases[int_phase - 1]
	except IndexError:
		return None


def _convertRegulatorPhase(int_phase):
	ret = _convertPhase(int_phase)
	return ret[:-1] if ret else None


classes = {
	"Residential1": 0,
	"Residential2": 1,
	"Residential3": 2,
	"Residential4": 3,
	"Residential5": 4,
	"Residential6": 5,
	"Commercial1": 6,
	"Commercial2": 7,
	"Commercial3": 8,
}


def _convertLoadClass(class_from_db):
	"""# Function the converts a load classification string to a number"""
	return classes.get(class_from_db)


def _csvToArray(csvFileName):
	""" Simple .csv data ingester. """
	with open(csvFileName, newline='') as csvFile:
		csvReader = csv.reader(csvFile)
		outArray = []
		for row in csvReader:
			outArray += [row]
		return outArray


def _csvToDictList(csvFileName, feederId):
	included_columns = []
	header = []
	mapped = []
	deleteRows = []
	content = []
	with open(csvFileName, newline='') as f:
		sourceFile = csv.reader(f)
		header = next(sourceFile)
	with open(csvFileName, newline='') as f:
		csvDict = csv.DictReader(f)
		for row in csvDict:
			# Equipment files, all equipment gets added
			if "NetworkId" not in header:
				mapped.append(flatten(row))
			elif row["NetworkId"] == feederId:
				mapped.append(flatten(row))
	return mapped


def checkMissingNodes(
	nodes, sectionDevices, objectList, feederId, modelDir, cymsection
):
	dbNodes = []
	MISSINGNO = {"name": None}
	nodesNotMake = {}
	missingNodes = []
	glmObjs = []
	objNotMiss = []
	toNodesMissing = []
	sectionObjects = []
	otherObjects = []
	nonMissNodes = []
	nodesLen = len(nodes)
	# Make missingNodesReport.txt
	missingNodesReport = pJoin(modelDir, "missingNodesReport.txt")
	with open(missingNodesReport, "w") as inFile:
		inFile.write(
			"Missing nodes report for " + feederId + "\nList of missing nodes:\n"
		)
	node_db = _csvToDictList(pJoin(modelDir, "cymeCsvDump", "CYMNODE.csv"), feederId)
	# Nodes in mdb are compared with nodes in glm and missing nodes is populated with those missing
	for row in node_db:
		dbNodes.append(_fixName(row["NodeId"]))
		if _fixName(row["NodeId"]) not in nodes:
			nodesNotMake[_fixName(row["NodeId"])] = copy.deepcopy(MISSINGNO)
			nodesNotMake[_fixName(row["NodeId"])]["name"] = _fixName(row["NodeId"])
			missingNodes.append(_fixName(row["NodeId"]))
			with open(missingNodesReport, "a") as inFile:
				inFile.write(_fixName(row["NodeId"]) + "\n")
				# All objects in glm are put in a list
	for row in objectList:
		for key in row.keys():
			glmObjs.append(key)
			# Comparing missing nodes names to names of other glm objects to see if they are not nodes but other objects
			# For Titanium these are batteries, diesel dg
	with open(missingNodesReport, "a") as inFile:
		inFile.write(
			"Comparing the names of the missing nodes to the names of other objects in the .glm:\n"
		)
	for row in missingNodes:
		if row in glmObjs:
			with open(missingNodesReport, "a") as inFile:
				inFile.write(
					row
					+ " was found as an existing object in the .glm. Removing it from the list of missing nodes...\n"
				)
			objNotMiss.append(row)
			# remove above objects from missing nodes list
	for row in objNotMiss:
		missingNodes.remove(row)
	with open(missingNodesReport, "a") as inFile:
		inFile.write("Updated list of missing nodes:\n")
	for row in missingNodes:
		with open(missingNodesReport, "a") as inFile:
			inFile.write(row + "\n")
			# check cymsection for the missing device and its corresponding device
	with open(missingNodesReport, "a") as inFile:
		inFile.write(
			"Some nodes get absorbed into the objects that they lead to, checking for this situation now...\n"
		)
	for row in cymsection:
		for missNode in missingNodes:
			if cymsection[row]["to"] == missNode:
				sectionId = cymsection[row]["name"]
				with open(missingNodesReport, "a") as inFile:
					inFile.write(
						"The missing node "
						+ missNode
						+ " is a part of the section "
						+ sectionId
						+ "\n"
					)
				for dev in sectionDevices:
					if sectionDevices[dev]["section_name"] == sectionId:
						sectionObjects.append(sectionDevices[dev]["name"])
						with open(missingNodesReport, "a") as inFile:
							inFile.write(
								"This section corresponds to the device "
								+ sectionDevices[dev]["name"]
								+ "\n"
							)
							# check to see if that device is in the glm
	with open(missingNodesReport, "a") as inFile:
		inFile.write(
			"Comparing those devices to objects that already exist in the .glm:\n"
		)
	for row in sectionObjects:
		for obj in glmObjs:
			if row in obj and "config" not in obj and "_" not in obj:
				if row not in otherObjects:
					otherObjects.append(row)
					with open(missingNodesReport, "a") as inFile:
						inFile.write(
							row
							+ " was found as the existing object "
							+ obj
							+ " in the .glm. Removing its parent node from the list of missing nodes...\n"
						)
						# Removing nodes with devices in the glm from this missing nodes list
	for row in otherObjects:
		nonMissNodes.append(cymsection[sectionDevices[row]["section_name"]]["to"])
	for row in nonMissNodes:
		missingNodes.remove(row)
	with open(missingNodesReport, "a") as inFile:
		inFile.write("Updated list of missing nodes:\n")
	for row in missingNodes:
		with open(missingNodesReport, "a") as inFile:
			inFile.write(row + "\n")


def _readSource(feederId, _type, modelDir):
	"""store information for the swing bus"""
	# Stores information found in CYMSOURCE or CYMEQUIVALENTSOURCE in the network database
	cymsource = {}
	struct = {
		"name": None,  # information structure for each object found in struct
		"bustype": "SWING",
		"nominal_voltage": None,
		"phases": None,
	}

	if _type == 1:
		# Check to see if the network database contains models for more than one database and if we chose a valid feeder_id to convert
		feeder_db = _csvToDictList(
			pJoin(modelDir, "cymeCsvDump", "CYMSOURCE.csv"), feederId
		)
	elif _type == 2:
		# Check to see if the network database contains models for more than one database and if we chose a valid feeder_id to convert
		feeder_db = _csvToDictList(
			pJoin(modelDir, "cymeCsvDump", "CYMEQUIVALENTSOURCE.csv"), feederId
		)
		# feeder_db_net =  networkDatabase.execute("SELECT NetworkId FROM CYMNETWORK").fetchall()
		feeder_db_net = _csvToDictList(
			pJoin(modelDir, "cymeCsvDump", "CYMNETWORK.csv"), feederId
		)
		if feeder_db_net == None:
			raise RuntimeError(
				"No source node was found in struct: {:s}.\n".format(feederId)
			)

	if feeder_db == None:
		raise RuntimeError(
			"No source node was found in CYMSOURCE: {:s}.\n".format(feederId)
		)
	else:
		try:
			print("NetworkId", feeder_db_net)
		except:
			pass
	"""MICHAEL JACKSON debug"""
	# if feederId arg is none (from findNetworkId call on CYMNETWORK.csv)
	if feederId == None:
		print("NO FEEDER ID\n")
		if len(feeder_db) == 1:
			try:
				row = feeder_db[0]
				feederId = row["NetworkId"]
				node_id = _fixName(row["NodeId"])
				cymsource[node_id] = copy.deepcopy(struct)
				cymsource[node_id]["name"] = node_id
				cymsource[node_id]["nominal_voltage"] = str(
					float(row["DesiredVoltage"]) * 1000.0 / math.sqrt(3)
				)
			except:
				for row in feeder_db_net:
					feederId = row["NetworkId"]
					node_id = _fixName(row["NodeId"])
					cymsource[node_id] = copy.deepcopy(struct)
					cymsource[node_id]["name"] = node_id
					cymsource[node_id]["nominal_voltage"] = str(
						float(row["OperatingVoltage1"]) * 1000.0 / math.sqrt(3)
					)
		elif len(feeder_db) > 1:
			raise RuntimeError(
				"The was no feeder id given and the network database contians more than one feeder. Please specify a feeder id to extract."
			)
	else:
		print("FEEDER ID", feederId)
		try:
			feeder_index = [
				row["NetworkId"] for row in (feeder_db if _type == 1 else feeder_db_net)
			].index(feederId)
		except ValueError:
			raise RuntimeError(
				"The feeder id provided is not in the network database. Please specify a valid feeder id to extract."
			)

		if _type == 1:
			row = feeder_db[feeder_index]
			feeder_id = feederId
			node_id = _fixName(row["NodeId"])
			cymsource[node_id] = copy.deepcopy(struct)
			cymsource[node_id]["name"] = node_id
			cymsource[node_id]["nominal_voltage"] = str(
				float(row["DesiredVoltage"]) * 1000.0 / math.sqrt(3)
			)
			swingBus = node_id
		elif _type == 2:
			feederId_equivalent = "SOURCE_" + feederId
			for row in feeder_db:
				if row["NodeId"] in feederId_equivalent:
					# JOHN FITZGERALD KENNEDY.  logic was backwards.
					feeder_id = feederId
					node_id = _fixName(row["NodeId"])
					cymsource[node_id] = copy.deepcopy(struct)
					cymsource[node_id]["name"] = node_id
					# JOHN FITZGERALD KENNEDY. Differentiating between nominal voltage and voltage setpoint at the source.  Otherwise, per unit calcs get messy later.  Also, more accurate for capacitors.
					cymsource[node_id]["nominal_voltage"] = str(
						float(row["KVLL"]) * 1000.0 / math.sqrt(3)
					)  # JOHN FITZGERALD KENNEDY.
					cymsource[node_id]["source_voltage"] = str(
						float(row["OperatingVoltage1"]) * 1000.0
					)  # JOHN FITZGERALD KENNEDY
					swingBus = node_id
	return cymsource, feeder_id, swingBus


def _readNode(feederId, modelDir):
	"""store lat/lon information on nodes"""
	# Helper for lat/lon conversion.
	x_pixel_range = 1200
	y_pixel_range = 800
	cymnode = {}
	struct = {"name": None, "latitude": None, "longitude": None}

	node_db = _csvToDictList(pJoin(modelDir, "cymeCsvDump", "CYMNODE.csv"), feederId)
	if len(node_db) == 0:
		warnings.warn(
			"No information node locations were found in CYMNODE for feeder id: "
			+ feederId,
			RuntimeWarning,
		)
	else:
		x = [float(row["X"]) for row in node_db]
		y = [float(row["Y"]) for row in node_db]
		try:
			x_scale = x_pixel_range / (max(x) - min(x))
			x_b = -x_scale * min(x)
			y_scale = y_pixel_range / (max(x) - min(y))
			y_b = -y_scale * min(y)
		except:
			x_scale, x_b, y_scale, y_b = (0, 0, 0, 0)
		for row in node_db:
			row["NodeId"] = _fixName(row["NodeId"])
			if row["NodeId"] not in cymnode:
				cymnode[row["NodeId"]] = copy.deepcopy(struct)
				cymnode[row["NodeId"]]["name"] = row["NodeId"]
				cymnode[row["NodeId"]]["latitude"] = str(
					x_scale * float(row["X"]) + x_b
				)
				cymnode[row["NodeId"]]["longitude"] = str(
					y_pixel_range - (y_scale * float(row["Y"]) + y_b)
				)
	return cymnode, x_scale, y_scale


def _readOverheadByPhase(feederId, modelDir):
	"""store information from CYMOVERHEADBYPHASE"""
	data_dict = {}
	# Stores information found in CYMOVERHEADBYPHASE in the network database
	olc = {}
	uniqueSpacing = []
	overheadConductors = []  # Stores the unique conductor equipment Ids
	struct = {
		"name": None,  # Information structure for each object found in CYMOVERHEADBYPHASE
		"length": None,
		"configuration": None,
	}

	overheadbyphase_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMOVERHEADBYPHASE.csv"), feederId
	)
	if len(overheadbyphase_db) == 0:
		warnings.warn(
			"No information on phase conductors, spacing, and lengths were found in CYMOVERHEADBYPHASE for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		# Add all phase conductors to the line configuration dictionary.
		for row in overheadbyphase_db:
			device_no = _fixName(row["DeviceNumber"])
			if row["DeviceNumber"] not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				overheadLineConfiguration = {}

				for P in "ABC":
					if row["PhaseConductorId" + P] != "NONE":
						c_name = _fixName(row["PhaseConductorId" + P])
						overheadLineConfiguration["conductor_" + P] = c_name
						if c_name not in overheadConductors:
							overheadConductors.append(c_name)

				if row["NeutralConductorId"] != "NONE":
					c_name = _fixName(row["NeutralConductorId"])
					overheadLineConfiguration["conductor_N"] = c_name
					if c_name not in overheadConductors:
						overheadConductors.append(c_name)

				tmp = _fixName(row["ConductorSpacingId"])
				overheadLineConfiguration["spacing"] = tmp
				if tmp not in uniqueSpacing:
					uniqueSpacing.append(tmp)

				tmp = float(row["Length"]) * m2ft
				data_dict[device_no]["length"] = tmp if tmp != 0 else 1.0

				for key, config in olc.items():
					if overheadLineConfiguration == config:
						data_dict[device_no]["configuration"] = key
				if data_dict[device_no]["configuration"] is None:
					key = "olc" + str(len(olc))
					olc[key] = copy.deepcopy(overheadLineConfiguration)
					data_dict[device_no]["configuration"] = key
	return overheadConductors, data_dict, olc, uniqueSpacing


def _readGenericLine(csvName, feederId, modelDir, underground=False):
	"""store information from csvName"""
	data_dict = {}
	# Stores information found in CYMOVERHEADLINEUNBALANCED in the network database
	conductors = []  # Stores the unique underground conductor equipment Ids
	struct = {
		"name": None,  # Information structure for each object found in CYMOVERHEADLINEUNBALANCED
		"length": None,
	}

	struct["cable_id" if underground else "configuration"] = None

	db = _csvToDictList(pJoin(modelDir, "cymeCsvDump", csvName), feederId)
	if len(db) == 0:
		warnings.warn(
			"No line objects were found in {} for feeder_id: {}.".format(
				csvName, feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no

				if underground:
					tmp = _fixName(row["CableId"])
					data_dict[device_no]["cable_id"] = tmp
				else:
					tmp = _fixName(row["LineId"])
					data_dict[device_no]["configuration"] = tmp

				if tmp not in conductors:
					conductors.append(tmp)

				tmp = float(row["Length"]) * m2ft
				data_dict[device_no]["length"] = tmp if tmp != 0 else 1.0
	return conductors, data_dict


def _readOverheadLineUnbalanced(feederId, modelDir):
	"""store information from CYMOVERHEADLINEUNBALANCED"""
	return _readGenericLine("CYMOVERHEADLINEUNBALANCED.csv", feederId, modelDir)


def _readOverheadLine(feederId, modelDir):
	return _readGenericLine("CYMOVERHEADLINE.csv", feederId, modelDir)


def _readUndergroundLine(feederId, modelDir):
	return _readGenericLine(
		"CYMUNDERGROUNDLINE.csv", feederId, modelDir, underground=True
	)


def _readQOverheadLine(feederId, modelDir):
	data_dict = {}
	struct = {
		"name": None,  # Information structure for each object found in CYMOVERHEADBYPHASE
		"configuration": None,
	}
	spacingIds = []
	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQOVERHEADLINE.csv"), feederId
	)
	if len(db) == 0:
		warnings.warn(
			"No overheadline objects were found in CYMEQCONDUCTOR for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			spacingIds.append(_fixName(row["ConductorSpacingId"]))
			if eq_id not in data_dict:
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["configuration"] = _fixName(row["PhaseConductorId"])
				data_dict[eq_id]["spacing"] = _fixName(row["ConductorSpacingId"])
				data_dict[eq_id]["conductor_N"] = _fixName(row["NeutralConductorId"])
	return data_dict, spacingIds


def _readReactors(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "configuration": None}
	reactorIds = []
	seriesreactor_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSERIESREACTOR.csv"), feederId
	)
	if len(seriesreactor_db) == 0:
		warnings.warn(
			"No series reactor objects were found in CYMSERIESREACTOR for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in seriesreactor_db:
			device_no = _fixName(row["DeviceNumber"])
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in reactorIds:
				reactorIds.append(eq_id)
			if device_no not in data_dict:
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["configuration"] = eq_id
	return data_dict, reactorIds


def _readEqReactors(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "reactance": None}
	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQSERIESREACTOR.csv"), feederId
	)
	if len(db) == 0:
		warnings.warn(
			"No reactor equipment was found in CYMEQREACTOR for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict:
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["reactance"] = row["ReactanceOhms"]
	return data_dict


def _readSection(feederId, modelDir):
	"""store information from CYMSECTION"""
	data_dict = {}  # Stores information found in CYMSECTION in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMSECTION
		"from": None,
		"to": None,
		"phases": None,
	}
	# section_db = networkDatabase.execute("SELECT SectionId, FromNodeId, ToNodeId, Phase FROM CYMSECTION WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	section_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSECTION.csv"), feederId
	)
	if len(section_db) == 0:
		warnings.warn(
			"No section information was found in CYMSECTION for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in section_db:
			sect_id = _fixName(row["SectionId"])
			if sect_id not in data_dict.keys():
				data_dict[sect_id] = copy.deepcopy(struct)
				data_dict[sect_id]["name"] = sect_id
				data_dict[sect_id]["from"] = _fixName(row["FromNodeId"])
				data_dict[sect_id]["to"] = _fixName(row["ToNodeId"])
				data_dict[sect_id]["phases"] = _convertPhase(int(row["Phase"]))
	return data_dict


def _readSectionDevice(feederId, modelDir):
	"""store information from CYMSECTIONDEVICE"""
	data_dict = (
		{}
	)  # Stores information found in CYMSECTIONDEVICE in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMSECTIONDEVICE
		"device_type": None,
		"section_name": None,
		"location": None,
	}
	# section_device_db = networkDatabase.execute("SELECT DeviceNumber, DeviceType, SectionId, Location FROM CYMSECTIONDEVICE WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	section_device_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSECTIONDEVICE.csv"), feederId
	)
	if len(section_device_db) == 0:
		warnings.warn(
			"No section device information was found in CYMSECTIONDEVICE for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in section_device_db:
			sect_id = _fixName(row["SectionId"])
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["device_type"] = int(row["DeviceType"])
				data_dict[device_no]["section_name"] = sect_id
				data_dict[device_no]["location"] = int(row["Location"])
			else:
				# JOHN FITZGERALD KENNEDY. A better fix is needed.
				print("Found duplicate device ID: " + device_no + ".  Rename device in Cyme or the device will be overwritten.")
	return data_dict


def _splitLinkObjects(sectionDict, deviceDict, linkDict, overheadDict, undergroundDict):
	"""Split multiple link objects from the line that they are folded into"""
	# JOHN FITZGERALD KENNEDY.  Several changes in here related to the following problem.  Old code assume that each section (linkDict) would
	# only have one device or link object per section.  I found that this wasn't true for solar PV and switches.
	# Later in the code, linkDicts for these objects have lists as their values.
	# This code now reflects this possiblity.  But it makes it kind of inconsistent and hacky.
	for link in linkDict:
		if link in overheadDict or link in undergroundDict:
			# if true the link is embedded in a line object and must be separated
			lineId = link

			tmp = linkDict[link]
			newLinkIds = tmp if type(tmp) == list else [tmp]

			for newLinkId in newLinkIds:  # JOHN FITZGERALD KENNEDY
				at_from = deviceDict[newLinkId]["location"] == 1
				to_of = newLinkId if at_from else lineId
				from_of = lineId if at_from else newLinkId

				sectionDict[newLinkId] = copy.deepcopy(sectionDict[lineId])
				sectionDict[newLinkId]["name"] = newLinkId

				sectionDict[to_of]["to"] = "node" + newLinkId
				sectionDict[from_of]["from"] = "node" + newLinkId

				a = "to" if at_from else "from"
				b = "from" if at_from else "to"

				sectionDict[newLinkId][a + "X"] = str(
					float(sectionDict[lineId][b + "X"]) + random.uniform(-10, 10)
				)
				sectionDict[newLinkId][a + "Y"] = str(
					float(sectionDict[lineId][b + "Y"]) + random.uniform(-10, 10)
				)
				sectionDict[lineId][b + "X"] = sectionDict[newLinkId][a + "X"]
				sectionDict[lineId][b + "Y"] = sectionDict[newLinkId][a + "Y"]

				for phase in ["N", "D"]:
					sectionDict[newLinkId]["phases"] = sectionDict[newLinkId][
						"phases"
					].replace(phase, "")
				deviceDict[newLinkId]["section_name"] = newLinkId
				deviceDict[newLinkId]["location"] = 0


def _findParents(sectionDict, deviceDict, loadDict):
	"""store parent information for load type objects"""
	for lineId, loaddevices in loadDict.items():
		# if it's not a list, put it into a list on len 1
		loaddevices = loaddevices if type(loaddevices) == list else [loaddevices]
		for loaddevice in loaddevices:
			tmp = "to" if deviceDict[loaddevice]["location"] == 2 else "from"
			deviceDict[loaddevice]["parent"] = sectionDict[lineId][tmp]
			deviceDict[loaddevice]["phases"] = sectionDict[lineId]["phases"]


def _readSwitch(feederId, modelDir):
	data_dict = {}  # Stores information found in CYMSWITCH in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMSWITCH
		"equipment_name": None,
		"status": None,
	}
	# switch_db = networkDatabase.execute("SELECT DeviceNumber, EquipmentId, ClosedPhase FROM CYMSWITCH WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	switch_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSWITCH.csv"), feederId
	)
	if len(switch_db) == 0:
		warnings.warn(
			"No switch objects were found in CYMSWITCH for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in switch_db:
			device_no = _fixName(row["DeviceNumber"])
			eq_id = _fixName(row["EquipmentId"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_name"] = eq_id
				data_dict[device_no]["status"] = (
					0 if float(row["ClosedPhase"]) == 0 else 1
				)
	return data_dict


def _readSectionalizer(feederId, modelDir):
	data_dict = (
		{}
	)  # Stores information found in CYMSECTIONALIZER in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMSECTIONALIZER
		"status": None,
	}
	# sectionalizer_db = networkDatabase.execute("SELECT DeviceNumber, NormalStatus FROM CYMSECTIONALIZER WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	sectionalizer_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSECTIONALIZER.csv"), feederId
	)
	if len(sectionalizer_db) == 0:
		warnings.warn(
			"No sectionalizer objects were found in CYMSECTIONALIZER for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in sectionalizer_db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["status"] = (
					0 if float(row["NormalStatus"]) == 0 else 1
				)
	return data_dict


def _readFuse(feederId, modelDir):
	data_dict = {}  # Stores information found in CYMFUSE in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMFUSE
		"status": None,
		"equipment_id": None,
	}
	# fuse_db = networkDatabase.execute("SELECT DeviceNumber, EquipmentId, NormalStatus FROM CYMFUSE WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	fuse_db = _csvToDictList(pJoin(modelDir, "cymeCsvDump", "CYMFUSE.csv"), feederId)
	if len(fuse_db) == 0:
		warnings.warn(
			"No fuse objects were found in CYMFUSE for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in fuse_db:
			device_no = _fixName(row["DeviceNumber"])
			eq_id = _fixName(row["EquipmentId"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_id"] = eq_id
				data_dict[device_no]["status"] = (
					0 if float(row["NormalStatus"]) == 0 else 1
				)
	return data_dict


def _readRecloser(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "status": None}
	recloser_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMRECLOSER.csv"), feederId
	)
	if len(recloser_db) == 0:
		warnings.warn(
			"No recloser objects were found in CYMRECLOSER for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in recloser_db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["status"] = (
					0 if float(row["NormalStatus"]) == 0 else 1
				)
	return data_dict


def _readRegulator(feederId, modelDir):
	data_dict = {}
	# Stores information found in CYMREGULATOR in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMREGULATOR
		"equipment_name": None,
		"regulation": None,
		"band_width": None,
		"tap_pos_A": None,
		"tap_pos_B": None,
		"tap_pos_C": None,
	}
	# regulator_db = networkDatabase.execute("SELECT DeviceNumber, EquipmentId, BandWidth, BoostPercent, TapPositionA, TapPositionB, TapPositionC FROM CYMREGULATOR WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	regulator_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMREGULATOR.csv"), feederId
	)
	if len(regulator_db) == 0:
		warnings.warn(
			"No regulator objects were found in CYMREGULATOR for feeder_id: {:s}".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in regulator_db:
			device_no = _fixName(row["DeviceNumber"])
			eq_id = _fixName(row["EquipmentId"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_name"] = eq_id
				# data_dict[device_no]['band_width'] = float(row["BandWidth"])/120.0 #does not exist in database.  now forwardbandwidth in regulator equipment
				data_dict[device_no]["regulation"] = float(row["BoostPercent"]) / 100.0
				for p in "ABC":
					data_dict[device_no]["tap_pos_" + p] = row["TapPosition" + p]
	return data_dict


def _readShuntCapacitor(feederId, modelDir):
	data_dict = {}
	# Stores information found in CYMSHUNTCAPACITOR in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMSHUNTCAPACITOR
		"equipment_name": None,
		"status": None,
		"phases": None,
		"capacitor_A": None,
		"capacitor_B": None,
		"capacitor_C": None,
		"capacitor_ABC": None,
		"kV_line_neutral": None,  # kV. for consistency
		"control": None,
		"voltage_set_high": None,
		"voltage_set_low": None,
		"VAr_set_high": None,
		"VAr_set_low": None,
		"current_set_high": None,
		"current_set_low": None,
		"pt_phase": None,
		"remote_sense": None,
		"control_level": None,
	}

	shuntcapacitor_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMSHUNTCAPACITOR.csv"), feederId
	)
	if len(shuntcapacitor_db) == 0:
		warnings.warn(
			"No capacitor objects were found in CYMSHUNTCAPACITOR for feeder_id: {:s}".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		# if shunt capacitor table has KVARBC as a column use this block:
		for row in shuntcapacitor_db:
			device_no = _fixName(row["DeviceNumber"])
			if "EquipmentId" not in row:
				row["EquipmentId"] = "DEFAULT"
			eq_id = _fixName(row["EquipmentId"])

			if device_no not in data_dict:
				data_dict[device_no] = struct.copy()
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_name"] = eq_id
				data_dict[device_no]["status"] = row["Status"]

				if float(row["KVLN"]) > 0.0:
					data_dict[device_no]["kV_line_neutral"] = float(row["KVLN"]) * 1000

					# if CCT is 2 or 3, we make set the phase and offvalue under the if below
				if int(row["CapacitorControlType"]) == 2:
					data_dict[device_no]["control"] = "VAR"
					data_dict[device_no]["VAr_set_high"] = float(row["OnValue"]) * 1000
				elif int(row["CapacitorControlType"]) == 3:
					data_dict[device_no]["control"] = "CURRENT"
					data_dict[device_no]["current_set_high"] = row["OnValue"]
					# NOTE: should the above be cast to float?
				elif int(row["CapacitorControlType"]) == 7:
					data_dict[device_no]["control"] = "VOLT"
					controlledphase = _convertPhase(
						int(row["ControlledPhase"])
					).replace("N", "")
					data_dict[device_no]["voltage_set_low"] = float(
						row.get("OnValue" + controlledphase, 0)
					)
					data_dict[device_no]["voltage_set_high"] = float(
						row.get("OffValue" + controlledphase, 0)
					)
					data_dict[device_no]["pt_phase"] = controlledphase
					data_dict[device_no]["remote_sense"] = _fixName(
						row["ControlledNodeId"]
					)
				else:
					data_dict[device_no]["control"] = "MANUAL"
					data_dict[device_no]["pt_phase"] = "ABCN"
					data_dict[device_no]["voltage_set_high"] = float(row["KVLN"]) * 1000
					data_dict[device_no]["voltage_set_low"] = float(row["KVLN"]) * 1000

				if float(row.get("SwitchedKVARA", 0)) == 0:
					data_dict[device_no]["phases"] = "ABC"
					# _convertPhase(int(row["Phase"]))
					# JOHN FITZGERALD KENNEDY. Painful change.  Phase doesn't exist in my capacitor tables.

					for p in ("A", "B", "C", "ABC"):
						row["KVAR" + p] = float(row["KVAR" + p])

					if all([row["KVAR" + p] == 0 for p in "ABC"]):
						for p in "ABC":
							data_dict[device_no]["capacitor_" + p] = (
								row["KVARABC"] * 1000 / 3
							)
					else:
						for p in "ABC":
							if row["KVAR" + p] > 0:
								data_dict[device_no]["capacitor_" + p] = (
									row["KVAR" + p] * 1000
								)

					if int(row["CapacitorControlType"]) == 2:
						data_dict[device_no]["VAr_set_low"] = (
							float(row["OffValue"]) * 1000
						)
						data_dict[device_no]["pt_phase"] = _convertPhase(
							int(row["Phase"])
						)
					elif int(row["CapacitorControlType"]) == 3:
						data_dict[device_no]["current_set_low"] = row["OffValue"]
						data_dict[device_no]["pt_phase"] = _convertPhase(
							int(row["Phase"])
						)
				else:
					if row["SwitchingMode"] == "2":
						data_dict[device_no]["control_level"] = "BANK"
					elif row["SwitchingMode"] == "1":
						data_dict[device_no]["control_level"] = "INDIVIDUAL"
					else:
						print("could not find capacitor switching mode.  defaulting to INDIVIDUAL")
						data_dict[device_no]["control_level"] = "INDIVIDUAL"
					for p in "ABC":
						if float(row["SwictchedKVAR" + p]) > 0:
							data_dict[device_no]["capacitor_" + p] = (
								float(row["SwitchedKVAR" + p]) * 1000
							)

					if int(row["CapacitorControlType"]) == 2:
						data_dict[device_no]["VAr_set_low"] = (
							float(row["OffValueA"]) * 1000
						)
						data_dict[device_no]["pt_phase"] = "ABCN"
					elif int(row["CapacitorControlType"]) == 3:
						data_dict[device_no]["current_set_low"] = row["OffValueA"]
						data_dict[device_no]["pt_phase"] = "ABCN"
	return data_dict


def _determineLoad(l_type, l_v1, l_v2, conKVA):
	l_real = 0
	l_imag = 0
	conKVA = float(conKVA)
	if l_type == 0:  # information was stored as kW & kVAR
		l_real = l_v1 * 1000.0
		l_imag = abs(l_v2) * 1000.0
	elif l_type == 1:  # information was stored as kVA & power factor
		l_real = l_v1 * abs(l_v2) / 100.0 * 1000.0
		l_imag = l_v1 * math.sqrt(1 - (abs(l_v2) / 100.0) ** 2) * 1000.0
	else:  # information was stored as kW and power factor
		l_real = l_v1 * 1000.0
		if l_v2 != 0.0:
			l_imag = (
				l_real / (abs(l_v2) / 100.0) * math.sqrt(1 - (abs(l_v2) / 100.0) ** 2)
			)
	if l_real == 0.0 and l_imag == 0.0:
		l_real = conKVA * abs(l_v2) / 100.0 * 1000.0
		l_imag = conKVA * math.sqrt(1 - (abs(l_v2) / 100.0) ** 2) * 1000.0
	if l_v2 < 0.0:
		l_imag *= -1.0
	return l_real, l_imag


def _setConstantPower(l_v2, l_real, l_imag):
	if l_v2 >= 0.0:
		cp_string = "{:0.3f}+{:0.3f}j".format(l_real, l_imag)
	else:
		cp_string = "{:0.3f}-{:0.3f}j".format(l_real, abs(l_imag))
	return cp_string


def _cleanPhases(phases):
	p = ""
	if "A" in phases:
		p = p + "A"
	if "B" in phases:
		p = p + "B"
	if "C" in phases:
		p = p + "C"
	return p


def _readCustomerLoad(feederId, modelDir):
	data_dict = (
		{}
	)  # Stores information found in CYMCUSTOMERLOAD in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMCUSTERLOAD
		"phases": None,
		"constant_power_A": None,
		"constant_power_B": None,
		"constant_power_C": None,
		"load_realA": 0.0,
		"load_imagA": 0.0,
		"load_realB": 0.0,
		"load_imagB": 0.0,
		"load_realC": 0.0,
		"load_imagC": 0.0,
		"load_class": None,
	}
	load_real = 0
	load_imag = 0
	# customerload_db = networkDatabase.execute("SELECT DeviceNumber, DeviceType, ConsumerClassId, Phase, LoadValueType, Phase, LoadValue1, LoadValue2, ConnectedKVA FROM CYMCUSTOMERLOAD WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	customerload_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMCUSTOMERLOAD.csv"), feederId
	)
	if len(customerload_db) == 0:
		warnings.warn(
			"No load objects were found in CYMCUSTOMERLOAD for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in customerload_db:
			device_no = _fixName(row["DeviceNumber"])
			load_real, load_imag = _determineLoad(
				int(row["LoadValueType"]),
				float(row["LoadValue1"]),
				float(row["LoadValue2"]),
				row["ConnectedKVA"],
			)
			row_phases = _cleanPhases(_convertPhase(int(row["Phase"])))
			if device_no not in data_dict.keys():
				# check for 0 load
				if (
					row["Status"] == "1"
				):  # JOHN FITZGERALD KENNEDY.  Set disconnected loads to zero.
					load_real = 0
					load_imag = 0

				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				# _cleanPhases essentially removes N in this case
				data_dict[device_no]["phases"] = row_phases

				# prior code only allowed 'A', 'B', 'C', or 'ABC'
				for p in row_phases:
					# temp vars
					lr = float(load_real / len(row_phases))
					li = float(load_imag / len(row_phases))
					data_dict[device_no]["load_real" + p] = lr
					data_dict[device_no]["load_imag" + p] = li
					data_dict[device_no]["constant_power_" + p] = _setConstantPower(
						float(row["LoadValue2"]), lr, li
					)

					# Determine the load classification (default is residential)
				if "commercial" in (row["ConsumerClassId"]).lower():
					data_dict[device_no]["load_class"] = "C"
				else:
					data_dict[device_no]["load_class"] = "R"
				convert_class = _convertLoadClass(row["ConsumerClassId"])
				if convert_class is not None:
					data_dict[device_no]["load_class"] = convert_class

			else:
				# device_no alr exists in data_dict
				device_ps = data_dict[device_no]["phases"] + row_phases
				data_dict[device_no]["phases"] = _cleanPhases(device_ps)

				# again, prior code only allowed 'A', 'B', 'C', or 'ABC'
				for p in row_phases:
					data_dict[device_no]["load_real" + p] += float(
						load_real / len(row_phases)
					)
					data_dict[device_no]["load_imag" + p] += float(
						load_imag / len(row_phases)
					)
					data_dict[device_no]["constant_power_" + p] = _setConstantPower(
						float(row["LoadValue2"]),
						data_dict[device_no]["load_real" + p],
						data_dict[device_no]["load_imag" + p],
					)
	return data_dict


def _readThreeWindingTransformer(feederId, modelDir):
	data_dict = {}  # Stores information found in CYMREGULATOR in the network database
	struct = {
		"name": None,  # Information structure for each object found in CYMREGULATOR
		"equipment_name": None,
	}
	# threewxfmr_db = networkDatabase.execute("SELECT DeviceNumber, EquipmentId FROM CYMTHREEWINDINGTRANSFORMER WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	threewxfmr_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMTHREEWINDINGTRANSFORMER.csv"), feederId
	)
	if len(threewxfmr_db) == 0:
		warnings.warn(
			"No three-winding transformer objects were found in CYMTHREEWINDINGTRANSFORMER for feeder_id: {:s}".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in threewxfmr_db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_name"] = _fixName(row["EquipmentId"])
	return data_dict


def _readTransformer(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "equipment_name": None}
	# xfmrDb = networkDatabase.execute("SELECT DeviceNumber, EquipmentId FROM CYMTRANSFORMER WHERE NetworkId = '{:s}'".format(feederId)).fetchall()
	xfmrDb = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMTRANSFORMER.csv"), feederId
	)
	if len(xfmrDb) == 0:
		warnings.warn(
			"No transformer objects were found in CYMTRANSFORMER for feeder id: {:s}".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in xfmrDb:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["equipment_name"] = _fixName(row["EquipmentId"])
	return data_dict


def _readEqConductor(feederId, modelDir):
	data_dict = (
		{}
	)  # Stores information found in CYMEQCONDUCTOR in the equipment database
	struct = {
		"name": None,  # Information structure for each object found in CYMEQCONDUCTOR
		"rating.summer_continuous": None,
		"geometric_mean_radius": None,
		"resistance": None,
	}
	db = _csvToDictList(pJoin(modelDir, "cymeCsvDump", "CYMEQCONDUCTOR.csv"), feederId)
	if len(db) == 0:
		warnings.warn(
			"No conductor objects were found in CYMEQCONDUCTOR for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["rating.summer_continuous"] = row["FirstRating"]
				data_dict[eq_id]["geometric_mean_radius"] = (
					float(row["GMR"]) * m2ft / 100
				)
				# GMR is stored in cm. Must convert to ft.
				data_dict[eq_id]["resistance"] = (
					float(row["R50"]) * 5280 / (m2ft * 1000)
				)
				# R50 is stored in Ohm/km. Must convert to Ohm/mile
	return data_dict


def _readEqOverheadLineUnbalanced(feederId, modelDir):
	"""store information from CYMEQOVERHEADLINEUNBALANCED"""
	data_dict = (
		{}
	)  # Stores information found in CYMEQOVERHEADLINEUNBALANCED in the network database
	struct = {
		"object": "line_configuration",
		"name": None,
		"z11": None,
		"z12": None,
		"z13": None,
		"z21": None,
		"z22": None,
		"z23": None,
		"z31": None,
		"z32": None,
		"z33": None,
	}
	# ug_line_db = networkDatabase.execute("SELECT EquipmentId, SelfResistanceA, SelfResistanceB, SelfResistanceC, SelfReactanceA, SelfReactanceB, SelfReactanceC, MutualResistanceAB, MutualResistanceBC, MutualResistanceCA, MutualReactanceAB, MutualReactanceBC, MutualReactanceCA FROM CYMEQOVERHEADLINEUNBALANCED WHERE EquipmentId = '{:s}'".format("LINE606")).fetchall()
	oh_line_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQOVERHEADLINEUNBALANCED.csv"), feederId
	)
	if len(oh_line_db) == 0:
		warnings.warn(
			"No underground_line configuration objects were found in CYMEQOVERHEADLINEUNBALANCED for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in oh_line_db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = _fixName(eq_id)

				# in source, split between two entries: Resistance and Reactance
				source = [
					"Self%sA",
					"Self%sB",
					"Self%sC",
					"Mutual%sAB",
					"Mutual%sBC",
					"Mutual%sCA",
				]
				target = ["z11", "z22", "z33", "z12", "z23", "z13"]
				for s, t in zip(source, target):
					data_dict[eq_id][t] = "{:0.6f}{:+0.6}j".format(
						float(row[s % "Resistance"]) * 5280 / (m2ft * 1000),
						float(row[s % "Reactance"]) * 5280 / (m2ft * 1000),
					)

					# glm has entries with the phase order swapped. cym doesn't, so we duplicate.
				reverses = [("z12", "z21"), ("z23", "z32"), ("z13", "z31")]
				for v1, v2 in reverses:
					data_dict[eq_id][v2] = data_dict[eq_id][v1]
	return data_dict


def _readEqGeometricalArrangement(feederId, modelDir):
	data_dict = {}
	# Stores information found in CYMEQGEOMETRICALARRANGEMENT in the equipment database
	struct = {
		"name": None,  # Information structure for each object found in CYMEQGEOMETRICALARRANGEMENT
		"distance_AB": None,
		"distance_AC": None,
		"distance_AN": None,
		"distance_BC": None,
		"distance_BN": None,
		"distance_CN": None,
	}
	# db = equipmentDatabase.execute("SELECT EquipmentId, ConductorA_Horizontal, ConductorA_Vertical, ConductorB_Horizontal, ConductorB_Vertical, ConductorC_Horizontal, ConductorC_Vertical, NeutralConductor_Horizontal, NeutralConductor_Vertical FROM CYMEQGEOMETRICALARRANGEMENT").fetchall()
	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQGEOMETRICALARRANGEMENT.csv"), feederId
	)
	if len(db) == 0:
		warnings.warn(
			"No geometric spacing information was found in CYMEQGEOMETRICALARRANGEMENT for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:

		def _dist(phase_pair):
			first, second = phase_pair[0], phase_pair[1]
			first = "Conductor" + first
			second = "Conductor" + second if second != "N" else "NeutralConductor"
			H1, H2 = row[first + "_Horizontal"], row[second + "_Horizontal"]
			V1, V2 = row[first + "_Vertical"], row[second + "_Vertical"]
			return math.sqrt(
				(float(H1) - float(H2)) ** 2 + (float(V1) - float(V2)) ** 2
			)

		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				for phase_pair in ("AB", "AC", "AN", "BC", "BN", "CN"):
					data_dict[eq_id]["distance_" + phase_pair] = _dist(phase_pair)
	return data_dict


def _readUgConfiguration(feederId, modelDir):
	from itertools import product

	data_dict = {}
	# Defaults, need defaults for all values
	struct = {
		"name": None,
		"rating.summer_continuous": None,
		"outer_diameter": 0.0640837,
		"conductor_resistance": 14.87200,
		"conductor_gmr": 0.020800,
		"conductor_diameter": 0.0640837,
		"neutral_resistance": 14.87200,
		"neutral_gmr": 0.020800,
		"neutral_diameter": 0.0640837,
		"neutral_strands": 10,
		"distance_AB": 0.05,
		"distance_AC": 1.0,
		"distance_AN": 0.0,
		"distance_BC": 0.5,
		"distance_BN": 0.0,
		"distance_CN": 0.0,
		"z11": 0 + 1j,
		"z12": 0 + 1j,
		"z13": 0 + 1j,
		"z21": 0 + 1j,
		"z22": 0 + 1j,
		"z23": 0 + 1j,
		"z31": 0 + 1j,
		"z32": 0 + 1j,
		"z33": 0 + 1j,
	}
	try:
		undergroundcable = _csvToDictList(
			pJoin(modelDir, "cymeCsvDump", "CYMEQCABLE.csv"), feederId
		)
		undergroundcableconductor = _csvToDictList(
			pJoin(modelDir, "cymeCsvDump", "CYMEQCABLECONDUCTOR.csv"), feederId
		)
	except:
		undergroundcableconductor = {}
		warnings.warn(
			"No underground_line configuration objects were found in CYMEQCABLE for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	if len(undergroundcable) == 0:
		warnings.warn(
			"No underground_line configuration objects were found in CYMEQCABLE for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		# declare some conversion matrices for impedance conversion later
		a_s = 1 * np.exp(1j * np.deg2rad(120))
		As = np.array([[1, 1, 1], [1, a_s ** 2, a_s], [1, a_s, a_s ** 2]])
		for row in undergroundcable:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["rating.summer_continuous"] = row["FirstRating"]
				data_dict[eq_id]["outer_diameter"] = row.get(
					"OverallDiameter", 0.0640837
				)
				data_dict[eq_id]["conductor_resistance"] = row[
					"PositiveSequenceResistance"
				]
				# leaving as is since z matrix overwrites

				# potential bad values: None, "", "0"
				tmp = row.get("ArmorOuterDiameter")
				tmp = float(tmp) if tmp else 0
				if tmp != 0:
					data_dict[eq_id]["conductor_diameter"] = row["ArmorOuterDiameter"]
					data_dict[eq_id]["conductor_gmr"] = tmp / 3

					# conversion from cyme's ZeroSequenceResistance/Reactance -> Gridlabd's self/mutual impedances
				z00 = complex(
					float(row["ZeroSequenceResistance"]),
					float(row["ZeroSequenceReactance"]),
				)
				z11 = complex(
					float(row["PositiveSequenceResistance"]),
					float(row["PositiveSequenceReactance"]),
				)
				Z012 = (
					np.array([[z00, 0, 0], [0, z11, 0], [0, 0, z11]])
					* 5280
					/ (m2ft * 1000)
				)
				Zabc = As.dot(Z012).dot(inv(As))
				for p1, p2 in product([1, 2, 3], [1, 2, 3]):
					data_dict[eq_id]["z%d%d" % (p1, p2)] = (
						"{:0.6f}".format(Zabc[p1 - 1][p2 - 1].real)
						+ "{:+0.6f}".format(Zabc[p1 - 1][p2 - 1].imag)
						+ "j"
					)

					# Still missing these properties, will have default values for all objects
					# data_dict[eq_id]]['neutral_resistance'] = row["ZeroSequenceResistance"]
					# data_dict[eq_id]]['distance_AB'] = row["OverallDiameter"]
					# data_dict[eq_id]]['distance_AC'] = row["OverallDiameter"]
					# data_dict[eq_id]]['distance_AN'] = row["OverallDiameter"]
					# data_dict[eq_id]]['distance_BC'] = row["OverallDiameter"]
					# data_dict[eq_id]]['distance_BC'] = row["OverallDiameter"]
					# data_dict[eq_id]]['distance_CN'] = row["OverallDiameter"]
	for row in undergroundcableconductor:
		eq_id = _fixName(row["EquipmentId"])
		if eq_id in data_dict.keys():
			data_dict[eq_id]["neutral_diameter"] = row["Diameter"]
			data_dict[eq_id]["neutral_strands"] = row["NumberOfStrands"]
			data_dict[eq_id]["neutral_gmr"] = float(row["Diameter"]) / 3
	return data_dict


def _readEqAvgGeometricalArrangement(feederId, modelDir):
	data_dict = {}
	struct = {
		"name": None,
		"distance_AB": None,
		"distance_AC": None,
		"distance_AN": None,
		"distance_BC": None,
		"distance_BN": None,
		"distance_CN": None,
	}
	# cymeqaveragegeoarrangement_db = equipmentDatabase.execute("SELECT EquipmentId, GMDPhaseToPhase, GMDPhaseToNeutral FROM CYMEQAVERAGEGEOARRANGEMENT").fetchall()
	cymeqaveragegeoarrangement_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQAVERAGEGEOARRANGEMENT.csv"), feederId
	)
	if len(cymeqaveragegeoarrangement_db) == 0:
		warnings.warn(
			"No average spacing information was found in CYMEQAVERAGEGEOARRANGEMENT for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymeqaveragegeoarrangement_db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id

				phase_to_phase = ("AB", "AC", "BC")
				phase_to_neutral = ("AN", "BN", "CN")
				for pp in phase_to_phase:
					data_dict[eq_id]["distance_" + pp] = (
						float(row["GMDPhaseToPhase"]) * m2ft
					)  # information is stored in meters. must convert to feet.
				for pn in phase_to_neutral:
					data_dict[eq_id]["distance_" + pn] = (
						float(row["GMDPhaseToNeutral"]) * m2ft
					)
	return data_dict


def _readEqRegulator(feederId, modelDir):
	data_dict = (
		{}
	)  # Stores information found in CYMEQREGULATOR in the equipment database
	struct = {
		"name": None,  # Information structure for each object found in CYMEQREGULATOR
		"raise_taps": None,
		"lower_taps": None,
		"nominal_voltage": None,
		"bandwidth": None,
	}
	# db = equipmentDatabase.execute("SELECT EquipmentId, NumberOfTaps FROM CYMEQREGULATOR").fetchall()
	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQREGULATOR.csv"), feederId
	)

	if len(db) == 0:
		warnings.warn(
			"No regulator equipment was found in CYMEQREGULATOR for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["raise_taps"] = str(
					int(float(row["NumberOfTaps"]) * 0.5)
				)
				data_dict[eq_id]["lower_taps"] = str(
					int(float(row["NumberOfTaps"]) * 0.5)
				)
				data_dict[eq_id]["nominal_voltage"] = row["RatedKVLN"]
				data_dict[eq_id]["bandwidth"] = row.get("ForwardBandwidth")
				# TODO: figure out how to determine bandwidth. this should be there, but isn't
	return data_dict


def _readEqThreeWAutoXfmr(feederId, modelDir):
	data_dict = {}
	# Stores information found in CYMEQOVERHEADLINE in the equipment database
	struct = {
		"name": None,  # Information structure for each object found in CYMEQOVERHEADLINE
		"PrimaryRatedCapacity": None,
		"PrimaryVoltage": None,
		"SecondaryVoltage": None,
		"impedance": None,
	}

	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQTHREEWINDAUTOTRANSFORMER.csv"), feederId
	)
	if len(db) == 0:
		warnings.warn(
			"No average spacing information was found in CYMEQTHREEWINDAUTOTRANSFORMER for feeder_id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["PrimaryRatedCapacity"] = float(
					row["PrimaryRatedCapacity"]
				)
				data_dict[eq_id]["PrimaryVoltage"] = (
					float(row["PrimaryVoltage"]) * 1000.0 / math.sqrt(3.0)
				)
				data_dict[eq_id]["SecondaryVoltage"] = (
					float(row["SecondaryVoltage"]) * 1000.0 / math.sqrt(3.0)
				)
				if (
					data_dict[eq_id]["PrimaryVoltage"]
					== data_dict[eq_id]["SecondaryVoltage"]
				):
					data_dict[eq_id]["SecondaryVoltage"] += 0.1
				z1mag = float(row["PrimarySecondaryZ1"]) / 100.0
				if z1mag == 0:
					r = 0.000333
					x = 0.00222
				else:
					xr1_ratio = float(row["PrimarySecondaryXR1Ratio"])
					r = z1mag / math.sqrt(1 + xr1_ratio ** 2)
					x = r * xr1_ratio
				data_dict[eq_id]["impedance"] = "{:0.6f}{:+0.6f}j".format(r, x)
	return data_dict


def _readEqAutoXfmr(feederId, modelDir):
	return _readEqXfmr(feederId, modelDir, _auto=True)


def _readEqXfmr(feederId, modelDir, _auto=False):
	transformer_text = "AUTOTRANSFORMER" if _auto else "TRANSFORMER"
	data_dict = {}
	struct = {
		"name": None,
		"PrimaryRatedCapacity": None,
		"PrimaryVoltage": None,
		"SecondaryVoltage": None,
		"impedance": None,
	}
	db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQ{}.csv".format(transformer_text)), feederId
	)
	if len(db) == 0:
		warnings.warn(
			"No average {:s} equipment information was found in CYMEQ{:s} for feeder id: {:s}.".format(
				transformer_text.lower(), transformer_text, feederId
			),
			RuntimeWarning,
		)
	else:
		for row in db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["PrimaryRatedCapacity"] = float(
					row["NominalRatingKVA"]
				)
				data_dict[eq_id]["PrimaryVoltage"] = (
					float(row["PrimaryVoltageKVLL"]) * 1000.0 / math.sqrt(3.0)
				)
				data_dict[eq_id]["SecondaryVoltage"] = (
					float(row["SecondaryVoltageKVLL"]) * 1000.0 / math.sqrt(3.0)
				)
				if (
					data_dict[eq_id]["PrimaryVoltage"]
					== data_dict[eq_id]["SecondaryVoltage"]
				):
					data_dict[eq_id]["SecondaryVoltage"] += 0.001
				z1mag = float(row["PosSeqImpedancePercent"]) / 100.0
				r = z1mag / math.sqrt(1 + (float(row["XRRatio"])) ** 2)
				if r == 0.0:
					r = 0.000333
					x = 0.00222
				else:
					x = r * float(row["XRRatio"])
				data_dict[eq_id]["impedance"] = "{:0.6f}{:+0.6f}j".format(r, x)
	return data_dict


def _readPhotovoltaic(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "configuration": None}
	cymphotovoltaic_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMPHOTOVOLTAIC.csv"), feederId
	)
	if len(cymphotovoltaic_db) == 0:
		warnings.warn(
			"No photovoltaic information was found in CYMPHOTOVOLTAIC for feeder id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymphotovoltaic_db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["configuration"] = _fixName(row["EquipmentId"])
	return data_dict


def _readEqPhotovoltaic(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "current": 4.59, "voltage": 17.30, "efficiency": 0.155}
	cymeqphotovoltaic_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQPHOTOVOLTAIC.csv"), feederId
	)
	if len(cymeqphotovoltaic_db) == 0:
		warnings.warn(
			"No photovoltaic information was found in CYMEQPHOTOVOLTAIC for feeder id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymeqphotovoltaic_db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["current"] = row["MPPCurrent"]
				data_dict[eq_id]["voltage"] = row["MPPVoltage"]
	return data_dict


def _readEqBattery(feederId, modelDir):
	data_dict = {}
	struct = {
		"name": None,
		"rated_storage_energy": None,
		"max_charging_power": None,
		"max_discharging_power": None,
		"charge_efficiency": None,
		"discharge_efficiency": None,
	}
	cymeqbattery_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMEQBESS.csv"), feederId
	)
	if len(cymeqbattery_db) == 0:
		warnings.warn(
			"No battery information was found in CYMEQBATTERY for feeder id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymeqbattery_db:
			eq_id = _fixName(row["EquipmentId"])
			if eq_id not in data_dict.keys():
				data_dict[eq_id] = copy.deepcopy(struct)
				data_dict[eq_id]["name"] = eq_id
				data_dict[eq_id]["rated_storage_energy"] = float(
					row["RatedStorageEnergy"]
				)
				data_dict[eq_id]["max_charging_power"] = row["MaxChargingPower"]
				data_dict[eq_id]["max_discharging_power"] = row["MaxDischargingPower"]
				data_dict[eq_id]["round_trip_efficiency"] = (
					float(row["ChargeEfficiency"])
					/ 1000
					* float(row["DischargeEfficiency"])
					/ 1000
				)
	return data_dict


def _readBattery(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "configuration": None, "phase": None}
	cymbattery_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMBESS.csv"), feederId
	)
	if len(cymbattery_db) == 0:
		warnings.warn(
			"No battery information was found in CYMBESS for feeder id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymbattery_db:
			device_no = _fixName(row["DeviceNumber"])
			if device_no not in data_dict.keys():
				data_dict[device_no] = copy.deepcopy(struct)
				data_dict[device_no]["name"] = device_no
				data_dict[device_no]["configuration"] = row["EquipmentId"]
				data_dict[device_no]["phase"] = row["Phase"]
	return data_dict


def _readGenerator(feederId, modelDir):
	data_dict = {}
	struct = {"name": None, "generation": None, "power_factor": None}
	cymgenerator_db = _csvToDictList(
		pJoin(modelDir, "cymeCsvDump", "CYMDGGENERATIONMODEL.csv"), feederId
	)
	if len(cymgenerator_db) == 0:
		warnings.warn(
			"No generator information was found in CYMDGGENERATIONMODEL for feeder id: {:s}.".format(
				feederId
			),
			RuntimeWarning,
		)
	else:
		for row in cymgenerator_db:
			device_no = _fixName(row["DeviceNumber"])
			if row["DeviceType"] == "37":
				if device_no not in data_dict.keys():
					data_dict[device_no] = copy.deepcopy(struct)
					data_dict[device_no]["name"] = device_no
					data_dict[device_no]["generation"] = row["ActiveGeneration"]
					data_dict[device_no]["power_factor"] = row["PowerFactor"]
	return data_dict


def _find_SPCT_rating(load_str):
	spot_load = (
		abs(complex(load_str)) / 1000.0
	)  # JOHN FITZGERALD KENNEDY.  needs to be in kVA for transformer rating estimation
	spct_rating = [
		5,
		10,
		15,
		25,
		30,
		37.5,
		50,
		75,
		87.5,
		100,
		112.5,
		125,
		137.5,
		150,
		162.5,
		175,
		187.5,
		200,
		225,
		250,
		262.5,
		300,
		337.5,
		400,
		412.5,
		450,
		500,
		750,
		1000,
		1250,
		1500,
		2000,
		2500,
		3000,
		4000,
		5000,
	]
	past_rating = max(spct_rating)
	for rating in spct_rating:
		if spot_load <= rating < past_rating:
			past_rating = rating
	return str(past_rating)


def convertCymeModel(network_db, modelDir, test=False, _type=1, feeder_id=None):

	# HACK: manual network ID detection.
	dbflag = 1 if "OakPass" in str(network_db) else 0

	# Dictionary that will hold the feeder model for conversion to .glm format
	glmTree = {}

	# Initialize our other section dicts
	regulator_sections = {}
	recloser_sections = {}
	sectionalizer_sections = {}
	switch_sections = {}
	fuse_sections = {}
	capacitor_sections = {}
	vsc_sections = {}
	threewautoxfmr_sections = {}
	transformer_sections = {}
	overheadline_sections = {}
	undergroundline_sections = {}
	sx_section = []
	reactor_sections = {}
	pv_sections = {}
	load_sections = {}
	threewxfmr_sections = {}
	battery_sections = {}
	syncgen_sections = {}

	# Open the network database file
	# net_db = _openDatabase(network_db)

	# Dumping csv's to folder
	_csvDump(str(network_db), modelDir)

	# import pdb
	# pdb.set_trace()
	# feeder_id =_csvToDictList(pJoin(modelDir,'cymeCsvDump',"CYMNETWORK.csv"),columns=['NetworkId'])
	feeder_id = _findNetworkId(pJoin(modelDir, "cymeCsvDump", "CYMNETWORK.csv"))

	# -1-CYME CYMSOURCE ***
	cymsource, feeder_id, swingBus = _readSource(feeder_id, _type, modelDir)

	# -2-CYME CYMNODE ***
	cymnode, x_scale, y_scale = _readNode(feeder_id, modelDir)

	# -3-CYME OVERHEADBYPHASE ***
	OH_conductors, cymoverheadbyphase, ohConfigurations, uniqueOhSpacing = _readOverheadByPhase(
		feeder_id, modelDir
	)

	# -4-CYME UNDERGROUNDLINE ***
	UG_conductors, cymundergroundline = _readUndergroundLine(feeder_id, modelDir)

	# -5-CYME CYMOVERHEADLINEBALANCED ***
	UOLConfigNames, cymUnbalancedOverheadLine = _readOverheadLineUnbalanced(
		feeder_id, modelDir
	)

	# -5-CYME CYMSWITCH***
	cymswitch = _readSwitch(feeder_id, modelDir)

	# -6-CYME CYMSECTIONALIZER***
	cymsectionalizer = _readSectionalizer(feeder_id, modelDir)

	# -7-CYME CYMFUSE***
	cymfuse = _readFuse(feeder_id, modelDir)

	# -8-CYME CYMRECLOSER***
	cymrecloser = _readRecloser(feeder_id, modelDir)

	# -9-CYME CYMREGULATOR***
	cymregulator = _readRegulator(feeder_id, modelDir)

	# -10-CYME CYMSHUNTCAPACITOR***
	cymshuntcapacitor = _readShuntCapacitor(feeder_id, modelDir)

	# -11-CYME CYMCUSTOMERLOAD***
	cymcustomerload = _readCustomerLoad(feeder_id, modelDir)

	# -12-CYME CYMSECTION ***
	cymsection = _readSection(feeder_id, modelDir)
	for section in cymsection.keys():
		fromNode = cymsection[section]["from"]
		toNode = cymsection[section]["to"]
		cymsection[section]["fromX"] = (
			cymnode[fromNode]["latitude"] if fromNode in cymnode.keys() else 0
		)
		cymsection[section]["fromY"] = (
			cymnode[fromNode]["longitude"] if fromNode in cymnode.keys() else 800
		)
		cymsection[section]["toX"] = (
			cymnode[toNode]["latitude"] if toNode in cymnode.keys() else 0
		)
		cymsection[section]["toY"] = (
			cymnode[toNode]["longitude"] if toNode in cymnode.keys() else 800
		)

		# -13-CYME CYMSECTIONDEVICE ***
	cymsectiondevice = _readSectionDevice(feeder_id, modelDir)
	# OVERHEAD LINES
	cymoverheadline, lineIds = _readOverheadLine(feeder_id, modelDir)
	# OVERHEAD LINE CONFIGS
	cymeqoverheadline, spacingIds = _readQOverheadLine(feeder_id, modelDir)
	# PV
	cymphotovoltaic = _readPhotovoltaic(feeder_id, modelDir)
	# PV CONFIGS
	cymeqphotovoltaic = _readEqPhotovoltaic(feeder_id, modelDir)

	try:
		# BATTERY
		cymbattery = _readBattery(feeder_id, modelDir)
		# BATTERY CONFIGS
		cymeqbattery = _readEqBattery(feeder_id, modelDir)
	except:
		pass  # TODO: better way to handle generator failure.
	try:
		# GENERATOR
		cymgenerator = _readGenerator(feeder_id, modelDir)
	except:
		pass  # TODO: give this a more detailed way to handle generator failure.
		# Check that the section actually is a device.

	for link in cymsection.keys():
		link_exists = False
		for device in cymsectiondevice.keys():
			if cymsectiondevice[device]["section_name"] == link:
				link_exists = True
				break

		if not link_exists:
			cymsection[link]["connector"] = ""
			warnings.warn(
				"There is no device associated with section:{:s} in network database:{:s}. This will be modeled as a switch.".format(
					link, network_db
				),
				RuntimeWarning,
			)

		if "connector" in cymsection[link].keys():
			cymsectiondevice[link] = {
				"name": link,
				"device_type": 13,
				"section_name": link,
				"location": 0,
			}
			cymswitch[link] = {
				"name": link,  # Information structure for each object found in CYMSWITCH
				"equipment_name": None,
				"status": 1,
			}
			del cymsection[link]["connector"]

			# Remove islands from the network database
	fromNodes = []
	toNodes = []
	cleanToNodes = []
	for link, section in cymsection.items():
		if "from" in section:
			if section["from"] not in fromNodes:
				fromNodes.append(section["from"])
			if section["to"] not in toNodes:
				toNodes.append(section["to"])
				cleanToNodes.append(section["to"])

	islandNodes = set()
	for node in fromNodes:
		if node not in toNodes and node != swingBus:
			islandNodes.add(node)
	islands = 0
	nislands = len(islandNodes)
	while nislands != islands:
		islands = len(islandNodes)
		for link, section in cymsection.items():
			if "from" in section.keys():
				if section["from"] in islandNodes and section["to"] not in islandNodes:
					islandNodes.add(section["to"])
		nislands = len(islandNodes)

	deleteSections = set()
	for node in islandNodes:
		for link, section in cymsection.items():
			if (
				node == section["from"] or node == section["to"]
			) and link not in deleteSections:
				deleteSections.add(link)

				# TODO: uncomment this and actually delete orphaned nodes
	"""
	# for section in deleteSections:
	# 	 del cymsection[section]
	# for device in cymsectiondevice.keys():
	# 	 if cymsectiondevice[device]['section_name'] in deleteSections:
	# 		 del cymsectiondevice[device]
		"""

	# Group each type of device.
	for device, value in cymsectiondevice.items():
		dType = value["device_type"]
		sName = value["section_name"]

		if dType == 1:
			undergroundline_sections[sName] = device
		elif dType == 3 or dType == 2:
			overheadline_sections[sName] = device
		elif dType == 4:
			regulator_sections[sName] = device
		elif dType == 10:
			recloser_sections[sName] = device
		elif dType == 12:
			sectionalizer_sections[sName] = device
		elif dType == 13:
			if sName not in switch_sections.keys():
				switch_sections[sName] = [
					device
				]  # JOHN FITZGERALD KENNEDY. could use default dict to make this cleaner
			else:
				switch_sections[sName].append(device)
				# switch_sections[value['section_name']] = key #sometimes have two switches on a section!  this overwrite the first!
		elif dType == 14:
			fuse_sections[sName] = device
		elif dType == 16:
			# sx_section.append(value['section_name']) #this was not needed for PECO files
			reactor_sections[sName] = device
		elif dType == 17:
			capacitor_sections[sName] = device
		elif dType == 20:
			load_sections[sName] = device
		elif dType == 37:
			syncgen_sections[sName] = device
		elif dType == 45:
			if sName not in pv_sections.devices():
				pv_sections[sName] = [device]  # JOHN FITZGERALD KENNEDY
			else:
				pv_sections[sName].append(device)
		elif (
			dType == 47 or dType == 5
		):  # JOHN FITZGERALD KENNEDY.  added check for 5, another transformer device
			transformer_sections[sName] = device
		elif dType == 48:
			if dbflag == 0:
				threewautoxfmr_sections[sName] = device
			elif dbflag == 1:
				threewxfmr_sections[sName] = device
		elif dType == 80:
			battery_sections[sName] = device

			# find the parent of capacitors, loads, and pv
	for x in [
		capacitor_sections,
		load_sections,
		pv_sections,
		syncgen_sections,
		battery_sections,
	]:
		if len(x) > 0:
			_findParents(cymsection, cymsectiondevice, x)

			# split out fuses, regulators, transformers, switches, reclosers, and sectionalizers from the lines.
			# MICHAEL JACKSON debug: check these phases
	for x in [
		fuse_sections,
		regulator_sections,
		threewxfmr_sections,
		threewautoxfmr_sections,
		transformer_sections,
		switch_sections,
		recloser_sections,
		sectionalizer_sections,
		reactor_sections,
	]:
		if len(x) > 0:
			_splitLinkObjects(
				cymsection,
				cymsectiondevice,
				x,
				overheadline_sections,
				undergroundline_sections,
			)

			# -14-CYME CYMTRANSFORMER***
	cymxfmr = _readTransformer(feeder_id, modelDir)
	# -15-CYME CYMTHREEWINDINGTRANSFORMER***
	cym3wxfmr = _readThreeWindingTransformer(feeder_id, modelDir)
	# -16-CYME CYMEQCONDUCTOR***
	cymeqconductor = _readEqConductor(feeder_id, modelDir)
	# -17-CYME CYMEQCONDUCTOR***
	cymeqoverheadlineunbalanced = _readEqOverheadLineUnbalanced(feeder_id, modelDir)
	# -17-CYME CYMEQGEOMETRICALARRANGEMENT***
	if dbflag == 0:
		cymeqgeometricalarrangement = _readEqGeometricalArrangement(feeder_id, modelDir)
	elif dbflag == 1:
		cymeqgeometricalarrangement = _readEqAvgGeometricalArrangement(
			feeder_id, modelDir
		)
		# -18-CYME convertCymeModelXLSX Sheet***
	cymcsvundergroundcable = _readUgConfiguration(feeder_id, modelDir)
	# -19-CYME CYMEQREGULATOR***
	cymeqregulator = _readEqRegulator(feeder_id, modelDir)
	# -20-CYME CYMEQTHREEWINDAUTOTRANSFORMER***
	cymeq3wautoxfmr = _readEqThreeWAutoXfmr(feeder_id, modelDir)
	# -21-CYME CYMEQAUTOTRANSFORMER***
	cymeqautoxfmr = _readEqAutoXfmr(feeder_id, modelDir)
	# -22-CYME CYME REACTORS***
	cymreactor, reactorIds = _readReactors(feeder_id, modelDir)
	# -23-CYME CYMEQREACTORS***
	cymeqreactor = _readEqReactors(feeder_id, modelDir)
	# -24-CYME CYMEQTRANSFORMER***
	cymeqxfmr = _readEqXfmr(feeder_id, modelDir)

	# Check number of sources
	meters = {}
	if len(cymsource) > 1:
		print("There is more than one swing bus for feeder_id ", feeder_id, "\n")
	for x in cymsource.keys():
		meters[x] = {
			"object": "meter",
			"name": "{:s}".format(cymsource[x]["name"]),
			# 'bustype' : 'SWING',
			"nominal_voltage": cymsource[x]["nominal_voltage"],
			"latitude": cymnode[x]["latitude"],
			"longitude": cymnode[x]["longitude"],
		}
		feeder_VLN = cymsource[x]["nominal_voltage"]

		# Check for parallel links and islands
	fromTo = []
	fromNodes = []
	toNodes = []
	parallelLinks = []
	for link in cymsection.keys():
		if "from" in cymsection[link].keys() and "to" in cymsection[link].keys():
			if {cymsection[link]["from"], cymsection[link]["to"]} in fromTo:
				for key, value in cymsectiondevice.items():
					if value["section_name"] == link:
						parallelLinks.append(key)
						break
			else:
				fromTo.append({cymsection[link]["from"], cymsection[link]["to"]})
			if cymsection[link]["from"] not in fromNodes:
				fromNodes.append(cymsection[link]["from"])
			if cymsection[link]["to"] not in toNodes:
				toNodes.append(cymsection[link]["to"])
				# islandNodes = []
				# for node in fromNodes:
				# 	 if node not in toNodes and node != swingBus and node not in islandNodes:
				# 		 islandNodes.append(node)
				# for node in islandNodes:
				# 	 if node != swingBus:
				# 		 print "Feeder islanded\n"
				# Pass from, to, and phase information from cymsection to cymsectiondevice
	nodes = {}
	for key in cymsectiondevice.keys():
		value = cymsectiondevice[key]
		sName = value["section_name"]

		value["fromLatitude"] = cymsection[sName]["fromX"]
		value["fromLongitude"] = cymsection[sName]["fromY"]
		value["toLatitude"] = cymsection[sName]["toX"]
		value["toLongitude"] = cymsection[sName]["toY"]

		if "parent" not in value.keys():
			value["from"] = cymsection[sName]["from"]
			value["to"] = cymsection[sName]["to"]
			value["phases"] = cymsection[sName]["phases"]

			# Create all the node dictionaries
			for a in ("from", "to"):
				if value[a] not in nodes.keys() and value[a] != swingBus:
					nodes[value[a]] = {
						"object": "node",
						"name": value[a],
						"phases": value["phases"],
						"nominal_voltage": str(feeder_VLN),
						"latitude": value[a + "Latitude"],
						"longitude": value[a + "Longitude"],
					}
		else:
			if value["parent"] not in nodes.keys() and value["parent"] != swingBus:
				nodes[value["parent"]] = {
					"object": "node",
					"name": value["parent"],
					"phases": value["phases"],
					"nominal_voltage": str(feeder_VLN),
				}
				if value["location"] == 2:
					nodes[value["parent"]]["latitude"] = value["toLatitude"]
					nodes[value["parent"]]["longitude"] = value["toLongitude"]
				else:
					nodes[value["parent"]]["latitude"] = value["fromLatitude"]
					nodes[value["parent"]]["longitude"] = value["fromLongitude"]

					# Create overhead line conductor dictionaries
	ohl_conds = {}
	print("REACHED")
	for src in (OH_conductors, cymeqconductor):
		for olc in src:
			if olc in cymeqconductor:
				if olc in ohl_conds:
					continue
				ohl_conds[olc] = {
					"object": "overhead_line_conductor",
					"name": olc,
					"resistance": "{:0.6f}".format(cymeqconductor[olc]["resistance"]),
					"geometric_mean_radius": "{:0.6f}".format(
						cymeqconductor[olc]["geometric_mean_radius"]
					),
				}
			else:
				print("There is no conductor spec for ", olc, " in the equipment database provided.\n")

	ohl_configs = {}
	for ohlc in cymeqoverheadline:
		if ohlc in lineIds:
			if ohlc not in ohl_configs.keys():
				ohl_configs[ohlc] = {
					"object": "line_configuration",
					"name": ohlc + "conf",
					"spacing": cymeqoverheadline[ohlc]["spacing"]
					+ "ohsps",  # uhhh? is this meant to be like this
					"conductor_A": cymeqoverheadline[ohlc]["configuration"],
					"conductor_B": cymeqoverheadline[ohlc]["configuration"],
					"conductor_C": cymeqoverheadline[ohlc]["configuration"],
					"conductor_N": cymeqoverheadline[ohlc]["conductor_N"],
				}

	ohl_spcs = {}
	# Create overhead line spacing dictionaries
	for src in (uniqueOhSpacing, spacingIds):
		for ols in uniqueOhSpacing:
			if ols in cymeqgeometricalarrangement.keys():
				if ols in ohl_spcs:
					continue

				ohl_spcs[ols] = {"object": "line_spacing", "name": ols}

				# if we are iterating over spacingIds, we add "ohsps"
				if src is spacingIds:
					ohl_spcs[ols]["name"] += "ohsps"

				for pp in ("AB", "AC", "AN", "BC", "BN", "CN"):
					ohl_spcs[ols]["distance_" + pp] = "{:0.6f}".format(
						cymeqgeometricalarrangement[ols]["distance_" + pp]
					)
			else:
				print("There is no line spacing spec for ", ols, "in the equipment database provided.\n")

				# Create overhead line configuration dictionaries
	ohl_cfgs = {}
	ohl_neutral = []
	for ohl_cfg in ohConfigurations:
		if ohl_cfg not in ohl_cfgs.keys():
			ohl_cfgs[ohl_cfg] = copy.deepcopy(ohConfigurations[ohl_cfg])
			ohl_cfgs[ohl_cfg]["name"] = ohl_cfg
			ohl_cfgs[ohl_cfg]["object"] = "line_configuration"
			if "conductor_N" in ohl_cfgs[ohl_cfg].keys():
				ohl_neutral.append(ohl_cfg)

	for ohl_cfg in UOLConfigNames:
		if ohl_cfg in cymeqoverheadlineunbalanced.keys():
			if ohl_cfg not in ohl_cfgs.keys():
				ohl_cfgs[ohl_cfg] = copy.deepcopy(cymeqoverheadlineunbalanced[ohl_cfg])
		else:
			print("There is no overhead line configuration for", ohl_cfg, " in the equipment database provided.")

	def split_parallel(target_dict, line_key, struct, nodes):
		# if a line is a parallel link, split it in two and add a parNode
		# struct contains all of the parameters of the line prior to being split
		if line_key not in parallelLinks:
			target_dict[line_key] = struct
		else:
			target_dict[line_key + "par1"] = struct.copy()
			target_dict[line_key + "par1"]["name"] += "par1"
			target_dict[line_key + "par1"]["to"] = line_key + "parNode"
			target_dict[line_key + "par1"]["length"] = "{:0.6f}".format(
				float(struct["length"]) / 2
			)

			target_dict[line_key + "par2"] = struct.copy()
			target_dict[line_key + "par2"]["name"] += "par2"
			target_dict[line_key + "par2"]["from"] = line_key + "parNode"
			target_dict[line_key + "par2"]["length"] = "{:0.6f}".format(
				float(struct["length"]) / 2
			)
			nodes[line_key + "parNode"] = {
				"object": "node",
				"name": line_key + "parNode",
				"phases": cymsectiondevice[line_key]["phases"],
				"nominal_voltage": str(feeder_VLN),
				"latitude": str(
					(
						float(cymsectiondevice[line_key]["fromLatitude"])
						+ float(cymsectiondevice[line_key]["toLatitude"])
					)
					/ 2.0
				),
				"longitude": str(
					(
						float(cymsectiondevice[line_key]["fromLongitude"])
						+ float(cymsectiondevice[line_key]["toLongitude"])
					)
					/ 2.0
				),
			}

			# Create underground line conductor, and spacing dictionaries

	ugl_conds = {}
	ugl_sps = {}
	for ulc in UG_conductors:
		if (
			ulc in cymcsvundergroundcable.keys()
			and ulc + "cond" not in ugl_conds.keys()
		):
			cable_dict = cymcsvundergroundcable[ulc]

			ugl_conds[ulc + "cond"] = {
				"object": "underground_line_conductor",
				"name": ulc + "cond",
			}

			to_copy = [
				"conductor_resistance",
				"neutral_gmr",
				"outer_diameter",
				"neutral_strands",
				"neutral_resistance",
				"neutral_diameter",
				"conductor_diameter",
				"conductor_gmr",
			]
			for field in to_copy:
				ugl_conds[ulc + "cond"][field] = cable_dict[field]

			if ulc + "sps" not in ugl_sps.keys():
				ugl_sps[ulc + "sps"] = {
					"object": "line_spacing",
					"name": ulc + "sps",
					"distance_AB": cable_dict["distance_AB"],
					"distance_AC": cable_dict["distance_AC"],
					"distance_BC": cable_dict["distance_BC"],
				}
		else:
			warnings.warn(
				"No configuration spec for {:s} in the underground csv file provided.".format(
					ulc
				),
				RuntimeWarning,
			)

			# We are going to loop over cymsectiondevice and populate these dictionaries with their respective devices
			# Names were not changed, but maybe they should be?
	ohls = {}
	ugl_cfgs = {}
	ugls = {}
	swObjs = {}
	rcls = {}
	sxnlrs = {}
	fuses = {}
	reactors = {}
	caps = {}
	loads = {}
	spct_cfgs = {}
	spcts = {}
	tpns = {}
	tpms = {}
	loadNames = []
	reg_cfgs = {}
	regs = {}
	pv_sec = {}
	bat_sec = {}
	gen_secs = {}
	xfmr_cfgs = {}
	xfmrs = {}

	# JOHN FITZGERALD KENNEDY.  I can't find the band_center anywhere in the cyme databaes files.
	# Unfortunately, the only way to deal with this is by looking at the cyme user interfrace.
	# Create regulator and regulator configuration dictionaries
	# Now, I just have the values hardcoded in.  For example...
	regulator_bandcenters = {
		"REG_BOYD_000_105581299": 126,  # newlinville
		"REG_HIGHLAND_000_105563434": 126,
		"REG_PARKESBURG_001_105599479": 126,
		"REG_PARKESBURG_002_105581381": 126,
		"REG_2449_36H5B19983": 124,
		"REG_7305_45D3A4_0806": 124,
		"REG_7526_45D3C3": 124,
		"REG_40701_52B3F3": 124,
		"REG_STOTTSVILLE_000_105581307": 125,
		"6": 126,  # chestnust
		"BOOT_JACK_000_105622980": 125,  # bootjack
		"REG_BOOT_JACK_000_105622980": 125,
		"REG_4631_52D4C7": 124,
		"REG_4955_52C4H83614": 124,
		"REG_41221_52D4C7": 124,
		"REG_49925_52D4C8": 124,
		"REG_60926_52E3A8": 124,
	}

	# Create overhead line dictionaries
	for dev_key, dev_dict in cymsectiondevice.items():
		if dev_dict["device_type"] == 3:
			if dev_key not in cymoverheadbyphase.keys():
				print("There is no line spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in ohls.keys():
				struct = {
					"object": "overhead_line",
					"name": dev_key,
					"phases": dev_dict["phases"],
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"length": "{:0.6f}".format(cymoverheadbyphase[dev_key]["length"]),
					"configuration": cymoverheadbyphase[dev_key]["configuration"],
				}
				split_parallel(ohls, dev_key, struct, nodes)

		elif dev_dict["device_type"] == 2:
			if dev_key not in cymoverheadline.keys():
				print("There is no line spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in ohls.keys():
				if dev_key not in parallelLinks:
					ohls[dev_key] = {
						"object": "overhead_line",
						"name": dev_key,
						"phases": dev_dict["phases"],
						"from": dev_dict["from"],
						"to": dev_dict["to"],
						"length": "{:0.6f}".format(cymoverheadline[dev_key]["length"]),
						"configuration": cymoverheadline[dev_key]["configuration"]
						+ "conf",
					}

		elif dev_dict["device_type"] == 23:
			# very similar to device 3
			if dev_key not in cymUnbalancedOverheadLine.keys():
				print("There is no line spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in ohls.keys():
				struct = {
					"object": "overhead_line",
					"name": dev_key,
					"phases": dev_dict["phases"],
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"length": "{:0.6f}".format(
						cymUnbalancedOverheadLine[dev_key]["length"]
					),
					"configuration": cymUnbalancedOverheadLine[dev_key][
						"configuration"
					],
				}
				split_parallel(ohls, dev_key, struct, nodes)

				# Creat Underground line configuration, and link objects.
		elif dev_dict["device_type"] == 1:
			ph = dev_dict["phases"]
			if dev_key not in cymundergroundline.keys():
				print("There is no line spec for ", dev_key, " in the network database provided.\n")
			else:
				ph = _cleanPhases(ph)
				config_name = cymundergroundline[dev_key]["cable_id"] + "ph" + ph
				if config_name not in ugl_cfgs.keys():
					ref_dict = cymundergroundline[dev_key]
					cable_dict = cymcsvundergroundcable[ref_dict["cable_id"]]

					ugl_cfgs[config_name] = {
						"object": "line_configuration",
						"name": config_name,
						"spacing": ref_dict["cable_id"] + "sps",
						"z11": cable_dict["z11"],
						"z12": cable_dict["z12"],
						"z13": cable_dict["z13"],
						"z21": cable_dict["z21"],
						"z22": cable_dict["z22"],
						"z23": cable_dict["z23"],
						"z31": cable_dict["z31"],
						"z32": cable_dict["z32"],
						"z33": cable_dict["z33"],
					}
					for p in ph:
						ugl_cfgs[config_name]["conductor_" + p] = (
							ref_dict["cable_id"] + "cond"
						)

				if dev_key not in ugls.keys():
					struct = {
						"object": "underground_line",
						"name": dev_key,
						"phases": dev_dict["phases"],
						"from": dev_dict["from"],
						"to": dev_dict["to"],
						"length": "{:0.6f}".format(ref_dict["length"]),
						"configuration": config_name,
					}
					split_parallel(ugls, dev_key, struct, node)

					# Create switch dictionaries
					gableid = ref_dict["cable_id"]
		elif dev_dict["device_type"] == 13:
			if dev_key not in cymswitch.keys():
				print("There is no switch spec for  ", dev_key, " in the network database provided.\n")
			elif dev_key not in swObjs.keys():
				swObjs[dev_key] = {
					"object": "switch",
					"name": dev_key,
					"phases": dev_dict["phases"].replace("N", ""),
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"operating_mode": "BANKED",
				}
				if cymswitch[dev_key]["status"] == 0:
					status = "OPEN"
					# JOHN FITZGERALD KENNEDY.  This was CLOSED.  Must have been a typo?
				else:
					status = "CLOSED"
				for phase in swObjs[dev_key]["phases"]:
					swObjs[dev_key]["phase_{:s}_state".format(phase)] = status

					# Create recloser dictionaries
		elif dev_dict["device_type"] == 10:
			if dev_key not in cymrecloser.keys():
				print("There is no recloster spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in rcls.keys():
				rcls[dev_key] = {
					"object": "recloser",
					"name": dev_key,
					"phases": dev_dict["phases"].replace("N", ""),
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"operating_mode": "BANKED",
				}
				if cymrecloser[dev_key]["status"] == 0:
					status = "OPEN"
					# was 'CLOSED'  #JOHN FITZGERALD KENNEDY.  Mistake seemed intentional. Maybe it was just a typo?
				else:
					status = "CLOSED"
				for phase in rcls[dev_key]["phases"]:
					rcls[dev_key]["phase_{:s}_state".format(phase)] = status

					# Create sectionalizer dictionaries
		elif dev_dict["device_type"] == 12:
			if dev_key not in cymsectionalizer.keys():
				print("There is no sectionalizer spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in sxnlrs.keys():
				sxnlrs[dev_key] = {
					"object": "sectionalizer",
					"name": dev_key,
					"phases": dev_dict["phases"].replace("N", ""),
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"operating_mode": "BANKED",
				}
				if cymsectionalizer[dev_key]["status"] == 0:
					status = "OPEN"  # 'CLOSED' #JOHN FITZGERALD KENNEDY
				else:
					status = "CLOSED"
				for phase in sxnlrs[dev_key]["phases"]:
					sxnlrs[dev_key]["phase_{:s}_state".format(phase)] = status

					# Create fuse dictionaries
		elif dev_dict["device_type"] == 14:
			if dev_key not in cymfuse.keys():
				print("There is no fuse spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in fuses.keys():
				fuses[dev_key] = {
					"object": "fuse",
					"name": dev_key,
					"phases": dev_dict["phases"].replace("N", ""),
					"from": dev_dict["from"],
					"to": dev_dict["to"],
					"repair_dist_type": "EXPONENTIAL",
					"mean_replacement_time": "3600",
					"current_limit": "9999",
				}
				if cymfuse[dev_key]["status"] == 0:
					status = "GOOD"
				else:
					status = "GOOD"
				for phase in fuses[dev_key]["phases"]:
					fuses[dev_key]["phase_{:s}_status".format(phase)] = status

					# JOHN FITZGERALD KENNEDY.  added all this reactor code
		elif dev_dict["device_type"] == 16:
			if dev_key not in cymreactor.keys():
				print("There is no reactor spec for ", dev_key, " in the network database provice. \n")
			elif dev_key not in reactors.keys():
				reactors[dev_key] = {
					"object": "series_reactor",
					"name": dev_key,
					"phases": dev_dict["phases"].replace("N", ""),
					"from": dev_dict["from"],
					"to": dev_dict["to"],
				}
				equipmentId = cymreactor[dev_key]["configuration"]
				Zohms = float(reactors[dev_key][equipmentId]["reactance"])
				for ph in reactors[dev_key]["phases"]:
					reactors[dev_key]["phase_" + ph + "_reactance"] = "{:0.6f}".format(
						Zohms
					)

					# Create capacitor dictionaries
		elif dev_dict["device_type"] == 17:
			if dev_key not in cymshuntcapacitor.keys():
				print("There is no capacitor spec for ", dev_key, " in the network database provided.\n")
			elif dev_key not in caps.keys():
				# a temporary variable to shorten some of these long lookups
				ref_dict = cymshuntcapacitor[dev_key]
				caps[dev_key] = {
					"object": "capacitor",
					"name": dev_key,
					"phases": dev_dict["phases"],
					"phases_connected": dev_dict["phases"],  # JOHN FITZGERALD KENNEDY
					"parent": dev_dict["parent"],
					# 'control_level' : 'INDIVIDUAL', #JOHN FITZGERALD KENNEDY
					"control": ref_dict["control"],  #'MANUAL',
					# 'cap_nominal_voltage' : str(feeder_VLN),
					"nominal_voltage": ref_dict["kV_line_neutral"],
					"time_delay": "2",
					"dwell_time": "3",
					"latitude": str(
						float(nodes[dev_dict["parent"]]["latitude"])
						+ random.uniform(-5, 5)
					),
					"longitude": str(
						float(nodes[dev_dict["parent"]]["longitude"])
						+ random.uniform(-5, 5)
					),
				}

				# This needs to be expanded for other control types too.
				if caps[dev_key]["control"] == "VOLT":
					caps[dev_key]["remote_sense"] = "n" + str(ref_dict["remote_sense"])
					# JOHN FITZGERALD KENNEDY.  hacky.  have to add 'n' because it's added later to nodes.
					caps[dev_key]["voltage_set_high"] = str(
						ref_dict["voltage_set_high"] * (1 / 120.0) * float(feeder_VLN)
					)
					caps[dev_key]["voltage_set_low"] = str(
						ref_dict["voltage_set_low"] * (1 / 120.0) * float(feeder_VLN)
					)
					caps[dev_key]["pt_phase"] = ref_dict["pt_phase"]
					caps[dev_key]["control_level"] = ref_dict["control_level"]
					for phase in caps[dev_key]["phases"]:
						if phase not in ["N", "D"]:
							caps[dev_key]["capacitor_" + phase] = str(
								ref_dict["capacitor_" + phase]
							)

				if ref_dict["status"] == "1":
					status = "OPEN"
				else:
					status = "CLOSED"
				for phase in caps[dev_key]["phases"]:
					if phase not in ["N", "D"]:
						caps[dev_key]["switch" + phase] = status
						caps[dev_key]["capacitor_" + phase] = str(
							ref_dict["capacitor_" + phase]
						)

						# Create load dictionaries
		elif dev_dict["device_type"] == 20:
			if dev_key not in cymcustomerload.keys():
				print("There is no load spec for ", dev_key, " in the network database provided.\n")
				continue

			ref_dict = cymcustomerload[dev_key]
			if dev_key not in loads.keys() and ref_dict["load_class"] == "commercial":
				loads[dev_key] = {
					"object": "load",
					"name": dev_key,
					"phases": dev_dict["phases"],
					"parent": dev_dict["parent"],
					"nominal_votlage": str(feeder_VLN),
					"load_class": "C",
				}
				for phase in loads[dev_key]["phases"]:
					if phase not in ["N", "D"]:
						loads[dev_key]["constant_power_" + phase] = ref_dict[
							"constant_power_" + phase
						]
			elif dev_key not in tpns.keys() and dev_dict["name"] not in loadNames:
				loadNames.append(dev_dict["name"])

				for phase in ref_dict["phases"]:  # JOHN FITZGERALD KENNEDY
					if phase in ["N", "D"]:
						continue

					if "constant_power_" + phase not in ref_dict.keys():
						ref_dict["constant_power_" + phase] = ref_dict[
							"constant_power_A"
						]
					spctRating = _find_SPCT_rating(
						str(ref_dict["constant_power_" + phase])
					)

					spct_cfg_name = "SPCTconfig{:s}{:s}".format(dev_key, phase)
					spct_name = "SPCT{:s}{:s}".format(dev_key, phase)
					tpm_name = "tpm{:s}{:s}".format(dev_key, phase)
					tpn_name = "tpn{:s}{:s}".format(dev_key, phase)

					spct_cfgs[spct_cfg_name] = {
						"object": "transformer_configuration",
						"name": spct_cfg_name,
						"connect_type": "SINGLE_PHASE_CENTER_TAPPED",
						"install_type": "POLETOP",
						"primary_voltage": str(feeder_VLN),
						"secondary_voltage": "120",
						"power_rating": spctRating,
						"power{:s}_rating".format(phase): spctRating,
						"impedance": "0.00033+0.0022j",
					}

					spcts[spct_name] = {
						"object": "transformer",
						"name": spct_name,
						"phases": "{:s}S".format(phase),
						"from": dev_dict["parent"],
						"to": tpm_name,
						"configuration": spct_cfg_name,
					}

					tpms[tpm_name] = {
						"object": "triplex_meter",
						"name": tpm_name,
						"phases": "{:s}S".format(phase),
						"nominal_voltage": "120",
						"latitude": str(
							float(nodes[dev_dict["parent"]]["latitude"])
							+ random.uniform(-5, 5)
						),
						"longitude": str(
							float(nodes[dev_dict["parent"]]["longitude"])
							+ random.uniform(-5, 5)
						),
					}

					tpns[tpn_name] = {
						"object": "triplex_node",
						"name": tpn_name,
						"phases": "{:s}S".format(phase),
						"nominal_voltage": "120",
						"parent": tpm_name,
						"power_12": ref_dict["constant_power_" + phase],
						"latitude": str(
							float(tpms[tpm_name]["latitude"]) + random.uniform(-5, 5)
						),
						"longitude": str(
							float(tpms[tpm_name]["longitude"]) + random.uniform(-5, 5)
						),
					}

					# Create regulator dictionaries
		elif dev_dict["device_type"] == 4:
			if dev_key not in cymregulator.keys():
				print("There is no regulator spec for ", dev_key, " in the network database provided.\n")
			else:
				# NOTE: by the way we construct cymregulator, this should be the same as dev_key (the equipmentId)
				regEq = cymregulator[dev_key]["equipment_name"]
				ref_dict = cymeqregulator[regEq]

				raiseTaps = ref_dict.get("raise_taps", "16")
				lowerTaps = ref_dict.get("lower_taps", "16")
				reg_nominalvoltage = float(ref_dict["nominal_voltage"]) * 1000.0

				# HACK: bandwidth sometimes set to none (likely bc it is not being read properly in _readCymRegulator)
				# HACK: just choose 10% of nominal. Good idea? TBD.
				safeRegBand = float(
					ref_dict["bandwidth"]
					if ref_dict["bandwidth"]
					else 0.10 * reg_nominalvoltage
				)
				reg_bandwidth = str(safeRegBand * reg_nominalvoltage / 120.0)

				# JOHN FITZGERALD KENNEDY. Need to have separate regulator configurations for each regulator
				# Cyme holds tap position in regulator, but Gridlabd holds tap position in configuration
				# NOTE: this seems incorrect. as the above note mentions, regEq seems to be the same as dev_key
				regEq = regEq + "_" + dev_key
				if dev_key in regulator_bandcenters.keys():
					band_center120 = regulator_bandcenters[dev_key]
				else:
					warnings.warn(
						"Bandcenter info not provided. Setting bandcenter to 1.05."
					)
					band_center120 = 126.0
				warnings.warn("Regulators hardcoded to OUTPUT_VOLTAGE.")

				ph = dev_dict["phases"].replace("N", "")
				if regEq not in reg_cfgs.keys():
					reg_cfgs[regEq] = {
						"object": "regulator_configuration",
						"name": regEq,  # JOHN FITZGERALD KENNEDY
						"connect_type": "WYE_WYE",
						"band_center": str(
							float(reg_nominalvoltage) * (band_center120 / 120.0)
						),
						"band_width": reg_bandwidth,
						"regulation": str(cymregulator[dev_key]["regulation"]),
						"time_delay": "30.0",
						"dwell_time": "5",
						"Control": "OUTPUT_VOLTAGE",  #'MANUAL' #
						"control_level": "INDIVIDUAL",
						"raise_taps": raiseTaps,
						"lower_taps": lowerTaps,
					}
					for phase in ph:
						reg_cfgs[regEq]["tap_pos_" + phase] = str(
							cymregulator[dev_key]["tap_pos_" + phase]
						)
				if dev_key not in reg_cfgs.keys():
					regs[dev_key] = {
						"object": "regulator",
						"name": dev_key,
						"phases": ph,
						"from": dev_dict["from"],
						"to": dev_dict["to"],
						"configuration": regEq,
					}  # JOHN FITZGERALD KENNEDY

					# Create photovoltaic, inverter, and meter dictionaries
		elif dev_dict["device_type"] == 45:
			if dev_key not in cymphotovoltaic.keys():
				print("There is no PV spec for ", dev_key, " in the network database provided.\n")
			else:
				config = cymeqphotovoltaic[cymphotovoltaic[dev_key]["configuration"]]
				pv_sec[dev_key + "meter"] = {
					"object": "meter",
					"name": dev_key + "meter",
					"parent": dev_dict["parent"],
					"latitude": dev_dict["toLatitude"],
					"longitude": dev_dict["toLongitude"],
				}
				pv_sec[dev_key + "inv"] = {
					"object": "inverter",
					"name": "n" + dev_key + "inv",
					"parent": dev_key + "meter",
					"latitude": dev_dict["toLatitude"],
					"longitude": dev_dict["toLongitude"],
				}
				pv_sec[dev_key] = {
					"object": "solar",
					"name": dev_key,
					"efficiency": config["efficiency"],
					"area": 1000
					* 0.075
					* float(config["voltage"])
					* float(config["current"]),
					"parent": dev_key + "inv",
					"latitude": dev_dict["toLatitude"],
					"longitude": dev_dict["toLongitude"],
				}

				# Create battery dictionaries
		elif dev_dict["device_type"] == 80:
			if dev_key not in cymbattery.keys():
				print("There is no battery spec for ", dev_key, " in the network database provided.\n")
			else:
				config = cymeqbattery[cymbattery[dev_key]["configuration"]]
				bat_sec[dev_dict["section_name"]] = {
					"object": "meter",
					"name": dev_dict["section_name"],
					"parent": dev_dict["parent"],
				}
				bat_sec[dev_key + "inv"] = {
					"object": "inverter",
					"name": "n" + dev_key + "inv",
					"generator_mode": "CONSTANT_PQ",
					"parent": dev_dict["section_name"],
					"phases": "BS",
					"four_quadrant_control_mode": "LOAD_FOLLOWING",
					"generator_status": "ONLINE",
					"inverter_type": "FOUR_QUADRANT",
					"discharge_off_threshold": 7454,
					"rated_power": config["rated_storage_energy"],
					"charge_off_threshold": 6148,
					"max_charge_rate": config["max_charging_power"],
					"max_discharge_rate": config["max_discharging_power"],
					"discharge_lockout_time": 60,
					"charge_lockout_time": 60,
					"inverter_efficiency": config["round_trip_efficiency"],
				}
				bat_sec[dev_key] = {
					"object": "battery",
					"name": dev_key,
					"state_of_charge": 1.0,
					"parent": dev_key + "inv",
					"latitude": dev_dict["toLatitude"],
					"longitude": dev_dict["toLongitude"],
					"round_trip_efficiency": config["round_trip_efficiency"],
					"generator_mode": "SUPPLY_DRIVEN",
					"generator_status": "ONLINE",
					"battery_state": 1.0,
					"battery_capacity": config["rated_storage_energy"],
					"battery_type": "LI_ION",
					"use_internal_battery_model": "TRUE",
				}

				# Create generator dictionaries
		elif dev_dict["device_type"] == 37:
			if dev_key not in cymgenerator.keys():
				print("There is no generator spec for ", dev_key, " in the network database provided.\n")
			else:
				gen_secs[dev_key] = {
					"object": "diesel_dg",
					"name": dev_key,
					"parent": dev_dict["parent"],
					"Gen_type": 2,
					"Gen_mode": 1,
					"TotalRealPow": cymgenerator[dev_key]["generation"],
					"pf": cymgenerator[dev_key]["power_factor"],
				}

				# Create transformer and transformer configuration dictionaries
		elif dev_dict["device_type"] in [47, 5, 48]:
			# Selecting which cymeq dict and cym dict to get data from
			if dev_dict["device_type"] == 47:
				cymeq_dict = cymeqautoxfmr
				threeway = False
			elif dev_dict["device_type"] == 5:
				cymeq_dict = cymeqxfmr
				threeway = False
			elif dev_dict["device_type"] == 48:
				cymeq_dict = cymeq3wautoxfmr
				threeway = True

			cym_dict = cym3wxfmr if threeway else cymxfmr

			if dev_key not in cym_dict.keys():
				print("There is no xmfr spec for ", dev_key, " in the network database provided.\n")
			else:
				xfmrEq = cym_dict[dev_key]["equipment_name"]
				if xfmrEq == dev_key:
					suffix = "cfg"
				else:
					suffix = ""

				ph = dev_dict["phases"]
				phNum = len(_cleanPhases(ph))

				if xfmrEq not in cymeq_dict.keys():
					print("There is no xmfr spec for ", xfmrEq, " in the network database provided.\n")
				else:
					if xfmrEq not in xfmr_cfgs.keys():
						xfmr_cfgs[xfmrEq] = {
							"object": "transformer_configuration",
							"name": xfmrEq + suffix,
							"connect_type": "WYE_WYE",
							"primary_voltage": (cymeq_dict[xfmrEq]["PrimaryVoltage"]),
							"secondary_voltage": (
								cymeq_dict[xfmrEq]["SecondaryVoltage"]
							),
							"impedance": cymeq_dict[xfmrEq]["impedance"],
							"power_rating": "{:0.0f}".format(
								cymeq_dict[xfmrEq]["PrimaryRatedCapacity"]
							),
						}

						if threeway:
							xfmr_cfgs[xfmrEq]["primary_voltage"] = "{:0.6f}".format(
								cymeq_dict[xfmrEq]["PrimaryVoltage"]
							)
							xfmr_cfgs[xfmrEq]["secondary_voltage"] = "{:0.6f}".format(
								cymeq_dict[xfmrEq]["SecondaryVoltage"]
							)
						else:
							xfmr_cfgs[xfmrEq]["primary_voltage"] = "{:0.6f}".format(
								cymeq_dict[xfmrEq]["PrimaryVoltage"] * math.sqrt(3)
							)
							xfmr_cfgs[xfmrEq]["secondary_voltage"] = "{:0.6f}".format(
								cymeq_dict[xfmrEq]["SecondaryVoltage"] * math.sqrt(3)
							)

						for phase in ph:
							xfmr_cfgs[xfmrEq][
								"power{:s}_rating".format(phase)
							] = "{:0.6f}".format(
								cymeq_dict[xfmrEq]["PrimaryRatedCapacity"] / phNum
							)

				if dev_key not in xfmrs.keys():
					xfmrs[dev_key] = {
						"object": "transformer",
						"name": dev_key,
						"phases": ph,
						"from": dev_dict["from"],
						"to": dev_dict["to"],
						"configuration": xfmrEq + suffix,
					}

					# Add dictionaries to feeder tree object
					# JOHN FITZGERALD KENNEDY.  giving an hour for everything to settle down.  needed for regulators and verification
	genericHeaders = [
		{
			"timezone": "PST+8PDT",
			"stoptime": "'2000-01-01 01:00:00'",
			"starttime": "'2000-01-01 00:00:00'",
			"clock": "clock",
		},
		{"omftype": "#set", "argument": "minimum_timestep=60"},
		{"omftype": "#set", "argument": "profiler=1"},
		{"omftype": "#set", "argument": "relax_naming_rules=1"},
		{"omftype": "module", "argument": "generators"},
		{"omftype": "module", "argument": "tape"},
		{"module": "residential", "implicit_enduses": "NONE"},
		{"solver_method": "NR", "NR_iteration_limit": "50", "module": "powerflow"},
	]
	for headId in range(len(genericHeaders)):
		glmTree[headId] = genericHeaders[headId]
	key = len(glmTree)
	objectList = [
		ohl_conds,
		ugl_conds,
		ohl_spcs,
		ohl_configs,
		ugl_sps,
		ohl_cfgs,
		ugl_cfgs,
		xfmr_cfgs,
		spct_cfgs,
		reg_cfgs,
		meters,
		nodes,
		loads,
		tpms,
		tpns,
		ohls,
		ugls,
		xfmrs,
		spcts,
		regs,
		swObjs,
		rcls,
		sxnlrs,
		fuses,
		caps,
		bat_sec,
		pv_sec,
		gen_secs,
		reactors,
	]
	for objDict in objectList:
		if len(objDict) > 0:
			for obj in objDict.keys():
				glmTree[key] = copy.deepcopy(objDict[obj])
				key = len(glmTree)

				# Find and fix duplicate names between nodes and links
	for x in glmTree.keys():
		if "object" in glmTree[x].keys() and glmTree[x]["object"] in [
			"node",
			"meter",
			"triplex_meter",
			"triplex_node",
		]:
			glmTree[x]["name"] = "n" + glmTree[x]["name"]
		if "from" in glmTree[x].keys():
			glmTree[x]["from"] = "n" + glmTree[x]["from"]
			glmTree[x]["to"] = "n" + glmTree[x]["to"]
		if "parent" in glmTree[x].keys():
			glmTree[x]["parent"] = "n" + glmTree[x]["parent"]
			# FINISHED CONVERSION FROM THE DATABASES****************************************************************************************************************************************************
			# Deletign malformed lniks
	for key in list(glmTree.keys()):
		if (
			"object" in glmTree[key].keys()
			and glmTree[key]["object"]
			in [
				"overhead_line",
				"underground_line",
				"regulator",
				"transformer",
				"switch",
				"fuse",
				"series_reactor",
			]
			and ("to" not in glmTree[key].keys() or "from" not in glmTree[key].keys())
		):
			del glmTree[key]

			# Create list of all from and to node names
	LinkedNodes = {}
	toNodes = []
	fromNodes = []
	for key in glmTree.keys():
		# JOHN FITZGERALD KENNEDY.  dont want phase information to be passed on by open switches
		# I have scenarios like:  phaseC -/ - phaseB
		if glmTree[key].get("object", "") == "switch":
			if "OPEN" in glmTree[key].values():
				continue

		if "to" in glmTree[key].keys():
			ph = LinkedNodes.get(glmTree[key]["from"], "")
			LinkedNodes[glmTree[key]["from"]] = ph + glmTree[key]["phases"]
			ph = LinkedNodes.get(glmTree[key]["to"], "")
			LinkedNodes[glmTree[key]["to"]] = ph + glmTree[key]["phases"]
			if glmTree[key]["to"] not in toNodes:
				toNodes.append(glmTree[key]["to"])
			if glmTree[key]["from"] not in fromNodes:
				fromNodes.append(glmTree[key]["from"])
	for node in fromNodes:
		if node not in toNodes and node != "n" + swingBus:
			print (node)

			# Find the unique phase information and place them in the node like object dictionaries
	for node in LinkedNodes.keys():
		phase = ""
		ABCphases = 0
		if "A" in LinkedNodes[node]:
			phase = phase + "A"
			ABCphases = ABCphases + 1
		if "B" in LinkedNodes[node]:
			phase = phase + "B"
			ABCphases = ABCphases + 1
		if "C" in LinkedNodes[node]:
			phase = phase + "C"
			ABCphases = ABCphases + 1
		if "S" in LinkedNodes[node] and ABCphases == 1 and node not in fromNodes:
			phase = phase + "S"
		else:
			phase = phase + "N"

		for x in glmTree.keys():
			if "name" in glmTree[x].keys() and glmTree[x]["name"] == node:
				glmTree[x]["phases"] = phase

				# Take care of open switches
	swFromNodes = {}
	swToNodes = {}
	for x in glmTree.keys():
		if "from" in glmTree[x].keys():
			if glmTree[x]["from"] not in swFromNodes.keys():
				swFromNodes[glmTree[x]["from"]] = 1
			else:
				swFromNodes[glmTree[x]["from"]] += 1
			if glmTree[x]["to"] not in swToNodes.keys():
				swToNodes[glmTree[x]["to"]] = 1
			else:
				swToNodes[glmTree[x]["to"]] += 1

	deleteKeys = []
	for x in glmTree.keys():
		if (
			glmTree[x].get("phase_A_state", "") == "OPEN"
			or glmTree[x].get("phase_B_state", "") == "OPEN"
			or glmTree[x].get("phase_C_state", "") == "OPEN"
		):
			if swToNodes[glmTree[x]["to"]] > 1:
				deleteKeys.append(x)
			elif swFromNodes.get(glmTree[x]["to"], 0) > 0:
				for phase in glmTree[x]["phases"]:
					if phase not in ["N", "D"]:
						glmTree[x]["phase_{:s}_state".format(phase)] = "CLOSED"
			else:
				deleteKeys.append(x)
				for y in glmTree.keys():
					if glmTree[y].get("name", "") == glmTree[x]["to"]:
						deleteKeys.append(y)

	for key in deleteKeys:
		del glmTree[key]

	def _fixNominalVoltage(glm_dict, volt_dict):
		for x in glm_dict.keys():
			if (
				"from" in glm_dict[x].keys()
				and glm_dict[x]["from"] in volt_dict.keys()
				and glm_dict[x]["to"] not in volt_dict.keys()
			):
				if glm_dict[x]["object"] == "transformer":
					# get secondary voltage from transformer configuration
					if "SPCT" in glm_dict[x]["name"]:
						nv = "120.0"
					else:
						cnfg = glm_dict[x]["configuration"]
						for y in glm_dict.keys():
							if (
								"name" in glm_dict[y].keys()
								and glm_dict[y]["name"] == cnfg
							):
								nv = glm_dict[y]["secondary_voltage"]
					volt_dict[glm_dict[x]["to"]] = nv
				elif glm_dict[x]["object"] == "regulator":
					volt_dict[glm_dict[x]["to"]] = volt_dict[glm_dict[x]["from"]]
					cnfg = glm_dict[x]["configuration"]
					nv = volt_dict[glm_dict[x]["from"]]
					for y in glm_dict.keys():
						if glm_dict[y].get("name", "") == cnfg:
							pass
							# glmTree[y]['band_center'] = nv
							# glmTree[y]['band_width'] = str(float(glmTree[y]['band_width'])*float(glmTree[y]['band_center']))
				else:
					volt_dict[glm_dict[x]["to"]] = volt_dict[glm_dict[x]["from"]]
			elif (
				"parent" in glm_dict[x].keys()
				and glm_dict[x]["parent"] in volt_dict.keys()
				and glm_dict[x]["name"] not in volt_dict.keys()
			):
				volt_dict[glm_dict[x]["name"]] = volt_dict[glm_dict[x]["parent"]]

	parent_voltage = {}
	current_parents = len(parent_voltage)
	previous_parents = 0

	for obj in glmTree:
		if "bustype" in glmTree[obj] and glmTree[obj]["bustype"] == "SWING":
			parent_voltage[glmTree[obj]["name"]] = glmTree[obj]["nominal_voltage"]
			current_parents = len(parent_voltage)

	while current_parents > previous_parents:
		_fixNominalVoltage(glmTree, parent_voltage)
		previous_parents = current_parents
		current_parents = len(parent_voltage)

	for x in glmTree.keys():
		if glmTree[x].get("name", "") in parent_voltage.keys():
			glmTree[x]["nominal_voltage"] = parent_voltage[glmTree[x].get("name", "")]

			# Delete nominal_voltage from link objects
	del_nom_volt_list = [
		"overhead_line",
		"underground_line",
		"regulator",
		"transformer",
		"switch",
		"fuse",
		"ZIPload",
		"diesel_dg",
		"solar",
		"inverter",
	]
	for x in glmTree:
		if (
			"object" in glmTree[x].keys()
			and glmTree[x]["object"] in del_nom_volt_list
			and "nominal_voltage" in glmTree[x].keys()
		):
			del glmTree[x]["nominal_voltage"]

			# Delete neutrals from links with no neutrals
	for x in glmTree.keys():
		if "object" in glmTree[x].keys() and glmTree[x]["object"] in [
			"underground_line",
			"regulator",
			"transformer",
			"switch",
			"fuse",
			"capacitor",
			"series_reactor",
		]:
			glmTree[x]["phases"] = glmTree[x]["phases"].replace("N", "")
		elif (
			"object" in glmTree[x].keys()
			and glmTree[x]["object"] == "overhead_line"
			and glmTree[x]["configuration"] not in ohl_neutral
		):
			glmTree[x]["phases"] = glmTree[x]["phases"].replace("N", "")
		if "object" in glmTree[x].keys() and glmTree[x]["object"] in ["node", "meter"]:
			try:
				glmTree[x]["phases"] = glmTree[x]["phases"].replace("S", "")
				if "N" not in glmTree[x]["phases"]:
					glmTree[x]["phases"] = glmTree[x]["phases"] + "N"
			except Exception as e:
				print(e)
				pass
				# TODO: have this missing nodes report not put files all over the place.
				# checkMissingNodes(nodes, cymsectiondevice, objectList, feeder_id, modelDir, cymsection)

				# JOHN FITZGERALD KENNEDY.  add regulator to source
	biggestkey = max(glmTree.keys())
	glmTree[biggestkey + 1] = {
		"object": "node",
		"name": "sourcenode",
		"phases": "ABC",
		"nominal_voltage": cymsource[_fixName(swingBus)]["nominal_voltage"],
		"bustype": "SWING",
	}
	glmTree[biggestkey + 2] = {
		"object": "regulator",
		"name": "sourceregulator",
		"phases": "ABC",
		"from": "sourcenode",
		"to": "n" + swingBus,
		"configuration": "ss_regconfiguration",
	}
	glmTree[biggestkey + 3] = {
		"object": "regulator_configuration",
		"name": "ss_regconfiguration",
		"band_center": cymsource[_fixName(swingBus)][
			"nominal_voltage"
		],  # HACK: source_voltage set to nominal.
		"Control": "OUTPUT_VOLTAGE",
		"connect_type": "WYE_WYE",
		"raise_taps": "50",  # want to be very close to desired voltage for agreement with cyme
		"lower_taps": "50",
		"band_width": "2.0",  # bandwidth should be very small for all voltage levels
		"regulation": "0.1",
		"dwell_time": "5",
		"tap_pos_A": "0",
		"tap_pos_B": "0",
		"tap_pos_C": "0",
		"time_delay": "30.0",
		"control_level": "INDIVIDUAL",
	}
	# Clean up the csvDump.
	# shutil.rmtree(pJoin(modelDir, "cymeCsvDump"))
	return glmTree


def _tests(keepFiles=True):
	testFile = ["IEEE13.mdb"]
	inputDir = os.path.join(os.path.dirname(__file__), 'static/testFiles/')
	# outputDir = tempfile.mkdtemp()
	outputDir = os.path.join(os.path.dirname(__file__), 'scratch/cymeToGridlabTests/')
	exceptionCount = 0
	try:
		shutil.rmtree(outputDir)
	except:
		pass  # no test directory yet.
	finally:
		os.mkdir(outputDir)
	locale.setlocale(locale.LC_ALL, "")
	for db_network in testFile:
		try:
			# Main conversion of CYME model.
			cyme_base = convertCymeModel(inputDir + db_network, inputDir)
			glmString = feeder.sortedWrite(cyme_base)
			testFilename = db_network[:-4]
			with open(inputDir + testFilename + ".glm", 'w') as f:
				f.write(glmString)
			inFileStats = os.stat(pJoin(inputDir, db_network))
			outFileStats = os.stat(pJoin(inputDir, testFilename + ".glm"))
			inFileSize = inFileStats.st_size
			outFileSize = outFileStats.st_size
			treeObj = feeder.parse(inputDir + testFilename + ".glm")
			print("WROTE GLM FOR " + db_network)
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("WROTE GLM FOR " + testFilename + "\n")
				resultsFile.write(
					"Input .mdb File Size: "
					+ str(locale.format_string("%d", inFileSize, grouping=True))
					+ "\n"
				)
				resultsFile.write(
					"Output .glm File Size: "
					+ str(locale.format_string("%d", outFileSize, grouping=True))
					+ "\n"
				)
		except:
			print("FAILED CONVERTING")
			testFilename = "failed"
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("FAILED CONVERTING " + testFilename + "\n")
			traceback.print_exc()
			exceptionCount += 3
			continue  # No use trying to draw or run if conversion fails.
		try:
			from omf.milToGridlab import (
				phasingMismatchFix,
				missingConductorsFix,
				fixOrphanedLoads,
			)

			treeObj = phasingMismatchFix(treeObj)
			treeObj = missingConductorsFix(treeObj)
			treeObj = fixOrphanedLoads(treeObj)
			# run milToGridlab fixes
		except:
			print("THE DARK LORD'S BEHAVIOR IS OUTRAGEOUS")
			traceback.print_exc()
		try:
			# Draw the GLM.
			myGraph = feeder.treeToNxGraph(cyme_base)
			feeder.latLonNxGraph(myGraph, neatoLayout=False)
			from matplotlib import pyplot as plt
			plt.savefig(outputDir + testFilename + ".png")
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("DREW GLM FOR " + testFilename + "\n")
			print("DREW GLM OF " + db_network)
		except:
			exceptionCount += 1
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("FAILED DRAWING" + testFilename + "\n")
			print("FAILED DRAWING " + db_network)
		try:
			# Run powerflow on the GLM.
			output = gridlabd.runInFilesystem(
				treeObj, keepFiles=True, workDir=outputDir
			)
			if output["stderr"] == "":
				gridlabdStderr = "GridLabD ran successfully without error."
			else:
				gridlabdStderr = output["stderr"]
			with open(outputDir + testFilename + ".JSON", "w") as outFile:
				json.dump(output, outFile, indent=4)
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("RAN GRIDLAB ON " + testFilename + "\n")
				resultsFile.write("STDERR: " + gridlabdStderr + "\n\n")
			print("RAN GRIDLAB ON " + db_network)
		except:
			exceptionCount += 1
			with open(pJoin(outputDir, "convResults.txt"), "a") as resultsFile:
				resultsFile.write("POWERFLOW FAILED FOR " + testFilename + "\n")
			print("POWERFLOW FAILED")
	if not keepFiles:
		shutil.rmtree(outputDir)
	return exceptionCount


if __name__ == "__main__":
	_tests()
