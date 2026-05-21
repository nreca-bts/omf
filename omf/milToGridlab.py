''' Convert a Milsoft Windmil feeder model into an OMF-compatible version. '''
import os, csv, random, math, copy, locale, json, traceback, shutil, time, datetime, warnings, gc, platform
from os.path import join as pJoin
from io import StringIO
from dateutil.tz import tzlocal
from pytz import reference
import numpy as np
from matplotlib import pyplot as plt

import omf
from omf import feeder, geo
from omf.solvers import gridlabd

def _csvToArray(csvString):
	''' Simple csv data ingester. '''
	csvReader = csv.reader(StringIO(csvString))
	outArray = []
	for row in csvReader:
		outArray += [row]
	return outArray

def _safeGet(arr, pos, default):
	''' Return item at pos in arr, or if it fails return default. '''
	try:
		return arr[pos]
	except:
		return default

def _lineDistances(x1,x2,y1,y2):
	''' Calculate distance between two points. Divice by 12 is for a feet to inches conversion. '''
	return math.sqrt((float(x1) - float(x2)) ** 2 + (float(y1) - float(y2)) ** 2) / 12

def convert(stdString, seqString, rescale=True):
	''' Take in a .std and .seq strings from Milsoft and spit out a json dict. Rescale to a small size if rescale=True. '''
	start_time = time.time()
	warnings.warn('*** Start Conversion %0.3f' % (time.time()-start_time))
	# Get all components from the .std:
	components = _csvToArray(stdString)[1:]
	# Get all hardware stats from the .seq. We dropped the first rows which are metadata (n.b. there are no headers).
	hardwareStats = _csvToArray(seqString)[1:]
	# List of all component names (to make sure we have uniqueness).
	allNames = [x[0] for x in components]
	def statsByName(deviceName):
		''' Helper function to query the hardware csv. '''
		for row in hardwareStats:
			if row[0] == deviceName:
				return row
		return None
	# Use a default for nominal voltage, but try to set it to the source voltage if possible.
	nominal_voltage = 14400
	for ob in components:
		if ob[1] == 9:
			nominal_voltage = str(float(ob[14])*1000)
	# The number of allowable sub objects:
	subObCount = 100
	# Helper for lat/lon conversion.
	def _convertToPixel():
		''' By default, Windmil coords are in map feet. This function tries to fit them in to something that our D3 front end can display. TODO: update this to get a more lat/lon-like coordinate system. '''
		x_list = []
		y_list = []
		x_pixel_range = 1200
		y_pixel_range = 800
		try:
			for component in components:
				x_list.append(float(component[5]))
				y_list.append(float(component[6]))
			warnings.warn('coordinate boundaries: %d %d %d %d' % (min(x_list), max(x_list), min(y_list), max(y_list)))
			# according to convert function  f(x) = a * x + b
			x_a = x_pixel_range / (max(x_list) - min(x_list))
			x_b = -x_a * min(x_list)
			y_a = y_pixel_range / (max(y_list) - min(y_list))
			y_b = -y_a * min(y_list)
		except:
			x_a,x_b,y_a,y_b = (0,0,0,0)
		return x_a, x_b, y_a, y_b
	if rescale:
		[x_scale, x_b, y_scale, y_b] = _convertToPixel()
	else:
		[x_scale, x_b, y_scale, y_b] = [1.0, 0.0, 1.0, 0.0]
	def obConvert(objectList):
		''' take a row in the milsoft .std and turn it into a gridlab-type dict'''
		def _convertGenericObject(objectList):
			''' this converts attributes that are in every milsoft object regardless of hardware type. '''
			newOb = {}
			gridlabFields = {
				1 : 'overhead_line',    # Overhead Line (Type 1)
				2 : 'capacitor',        # Capacitor (Type 2)
				3 : 'underground_line', # Underground Line (Type 3)
				4 : 'regulator',        # Regulator (Type 4)
				5 : 'transformer',      # Transformer (Type 5)
				6 : 'switch',           # Switch (Type 6)
				8 : 'node',             # Node (Type 8)
				9 : 'node',             # Source (Type 9)
				10 : 'fuse',            # Overcurrent Device (Type 10)
				11 : 'ZIPload',         # Motor (Type 11)
				12 : 'diesel_dg',       # Generator (Type 12)
				13 : 'load'             # Consumer (Type 13)
			}
			try:
				# Need to replace invalid characters in names:
				newOb['name'] = objectList[0].replace('.','x')
				newOb['object'] = gridlabFields[int(objectList[1])]
				# Convert lat-lon if we have them.
				# convert to the relative pixel position f(x) = a * x + b
				newOb['latitude'] = str(x_scale * float(objectList[5]) + x_b)
				newOb['longitude'] = str(800 - (y_scale * float(objectList[6]) + y_b))
				# Some non-Gridlab elements:
				newOb['guid'] = objectList[49].replace('{','').replace('}','')
				newOb['parentGuid'] = objectList[50].replace('{','').replace('}','')
				# Make sure names are unique:
				if allNames.count(newOb['name']) > 1:
					newOb['name'] = newOb['guid']
			except:
				warnings.warn('Object creation failed due to missing name, guid, parentGuid, lat, or lon.')
			return newOb

		# -----------------------------------------------
		# Conversion functions for each type of hardware:
		# -----------------------------------------------
		def convertSwitch(switchList):
			switch = _convertGenericObject(switchList)
			switch['status'] = ('OPEN' if switchList[9]=='O' else 'CLOSED')
			switch['phases'] = switchList[2]
			return switch

		def convertOvercurrentDevice(ocDeviceList):
			fuse = _convertGenericObject(ocDeviceList)
			fuse['phases'] = ocDeviceList[2]
			fuse['current_limit'] = '9999.0 A'
			# To supress replacement time warnings that GridLAB-D *LOVES* to print:
			fuse['mean_replacement_time'] = '3600.0'
			# TODO: Figure out why code below causes convergence errors for some feeders.
			# if 'OC' in fuse['name'] or 'FS' in fuse['name'] or 'NF14' in fuse['name']:
			#   ocNameInSEQ = ocDeviceList[7]
			#   if ocNameInSEQ == "": ocNameInSEQ = ocDeviceList[8]
			#   if ocNameInSEQ == "": ocNameInSEQ = ocDeviceList[9]
			#   if ocNameInSEQ == "": ocNameInSEQ = ocDeviceList[10]
			#   try: fuse['current_limit'] = statsByName(ocNameInSEQ)[3]+' A'
			#   except: fuse['current_limit'] = '9999.0 A'
			return fuse

		def convertGenerator(genList):
			generator = _convertGenericObject(genList)
			generator['Gen_mode'] = 'CONSTANTPQ'
			generator['Gen_status'] = ('OFFLINE' if genList[26]=='1' else 'ONLINE')
			generator['phases'] = "ABCN"
			#TODO: add genList[30] = kWOut, genList[31] = maxKwOut
			return generator

		def convertMotor(motorList):
			motor = _convertGenericObject(motorList)
			motor['Gen_mode'] = 'CONSTANTPQ'
			# Convert horsepower to kW:
			motor['base_power'] = float(motorList[27])*0.73549875
			# These constants come from the fan load in simpleMarketSystem:
			motor['power_fraction'] = 0.013500
			motor['impedance_fraction'] = 0.733200
			motor['current_fraction'] = 0.253400
			motor['power_pf'] = -1.000000
			motor['current_pf'] = 0.950000
			motor['impedance_pf'] = 0.970000
			return motor

		def convertConsumer(consList):
			consumer = _convertGenericObject(consList)
			consumer['phases'] = consList[2]
			loadClassMap = {
				0 : 'R',
				1 : 'C',
				2 : 'C',
				3 : 'U',
				4 : 'U',
				5 : 'A',
				6 : 'I',
				7 : 'U',
				8 : 'U',
				9 : 'U',
				10: 'U'
			}
			#HACK: default to residential.
			consumer['load_class'] = loadClassMap.get(int(consList[23]),'R')
			# Determine the commercial load connection wye or delta
			if consumer['load_class'] == 'C':
				load_mix = statsByName(consList[8])
				if load_mix is None:
					pass
				elif load_mix[5] == 'W':#Wye-Wye connected load
					phases = consumer['phases'] + 'N'
					consumer['phases'] = phases
				elif load_mix[5] == 'D':#Delta connected load
					phases = consumer['phases'] + ('D' if len(consList[2]) >= 2 else '')
					consumer['phases'] = phases
			#MAYBEFIX: support kVars.
			consumer['constant_power_A'] = str(float(consList[12])*1000) + ('+' if float(consList[15]) >= 0.0 else '-') + str(abs(float(consList[15])*1000)) + 'j'
			consumer['constant_power_B'] = str(float(consList[13])*1000) + ('+' if float(consList[16]) >= 0.0 else '-') + str(abs(float(consList[16])*1000)) + 'j'
			consumer['constant_power_C'] = str(float(consList[14])*1000) + ('+' if float(consList[17]) >= 0.0 else '-') + str(abs(float(consList[17])*1000)) + 'j'
			consumer['nominal_voltage'] = '120'
			return consumer

		def convertNode(nodeList):
			node = _convertGenericObject(nodeList)
			#Find the connect type
			load_mix = statsByName(nodeList[8])
			if load_mix is None or load_mix[5] == 'W':#Wye connected
				node['phases'] = nodeList[2] + 'N'
			elif load_mix[5] == 'D':#Delta connected
				node['phases'] = nodeList[2] + ('D' if len(nodeList[2]) >= 2 else '')
			else:
				node['phases'] = nodeList[2] + 'N'
			#MAYBEFIX: can we get nominal voltage from the windmil file?
			node['nominal_voltage'] = nominal_voltage
			if nodeList[15] != '0' or nodeList[16] != '0' or nodeList[17] != '0' or nodeList[18] != '0' or nodeList[19] != '0' or nodeList[20] != '0': # this node is actually a load
				node['object'] = 'load'
				node['constant_power_A'] = str(float(nodeList[15])*1000) + ('+' if float(nodeList[18]) >= 0.0 else '-') + str(abs(float(nodeList[18])*1000)) + 'j'
				node['constant_power_B'] = str(float(nodeList[16])*1000) + ('+' if float(nodeList[19]) >= 0.0 else '-') + str(abs(float(nodeList[19])*1000)) + 'j'
				node['constant_power_C'] = str(float(nodeList[17])*1000) + ('+' if float(nodeList[20]) >= 0.0 else '-') + str(abs(float(nodeList[20])*1000)) + 'j'
				node['load_class'] = 'C' #setting all nodes with loads on them as commercial loads as we can't know the load classification. If they want the load to be residential then they need to classify the node as a consumer object in the windmil model.
			return node

		def convertSource(sourceList):
			source = _convertGenericObject(sourceList)
			#Find the connect type
			if sourceList[16] == 'W':
				#Wye connected
				source['phases'] = sourceList[2] + 'N'
			else:
				#Delta connected
				source['phases'] = sourceList[2] + ('D' if len(sourceList[2]) >= 2 else '')
			source['nominal_voltage'] = str(float(sourceList[14])*1000)
			source['bustype'] = 'SWING'
			return source

		def convertCapacitor(capList):
			capacitor = _convertGenericObject(capList)
			if  capList[17] == '1': #Delta connected
				capacitor['phases'] = capList[2] + ('D' if len(capList[2]) >= 2 else '')
			else:
				capacitor['phases'] = capList[2] + 'N'
			#MAYBEFIX: change these from just default values:
			if capList[19] in capacitor['phases']:
				capacitor['pt_phase'] = capList[19]
			capacitor['phases_connected'] = capacitor['phases']
			if capList[12] == '0':
				capacitor['control'] = 'MANUAL'
			elif capList[12] == '1':
				capacitor['control'] = 'VOLT'
				capacitor['voltage_set_high'] = capList[15]
				capacitor['voltage_set_low'] = capList[14]
				capacitor['time_delay'] = '300.0'
				capacitor['dwell_time'] = '0.0'
			else:
				capacitor['control'] = 'MANUAL'
			#MAYBEFIX: Handle the other control types in WindMil Properly
			if 'A' in capacitor['phases']:
				capacitor['capacitor_A'] = str(float(_safeGet(capList, 8, '500'))/1000.0)
				if capList[13] == '1':
					capacitor['switchA'] = 'CLOSED'
				else:
					capacitor['switchA'] = 'OPEN'
			if 'B' in capacitor['phases']:
				capacitor['capacitor_B'] = str(float(_safeGet(capList, 9, '500'))/1000.0)
				if capList[13] == '1':
					capacitor['switchB'] = 'CLOSED'
				else:
					capacitor['switchB'] = 'OPEN'
			if 'C' in capacitor['phases']:
				capacitor['capacitor_C'] = str(float(_safeGet(capList, 10, '500'))/1000.0)
				if capList[13] == '1':
					capacitor['switchC'] = 'CLOSED'
				else:
					capacitor['switchC'] = 'OPEN'
			if len(capacitor['phases']) > 1:
				capacitor['control_level'] = 'BANK'
			else:
				capacitor['control_level'] = 'INDIVIDUAL'
			capacitor['nominal_voltage'] = nominal_voltage
			return capacitor

		def convertOhLine(ohLineList):
			myIndex = components.index(objectList)*subObCount
			overhead = _convertGenericObject(ohLineList)
			# MAYBEFIX: be smarter about multiple neutrals.
			load_mix = statsByName(ohLineList[14])
			if load_mix is None or load_mix[5] == 'W':#Wye connected line
				overhead['phases'] = ohLineList[2] + ('N' if ohLineList[33]=='1' else '')
			else: #Delta connected line
				# Delta connections are breaking things.
				# overhead['phases'] = ohLineList[2] + ('D' if len(ohLineList[2]) >= 2 else '')
				overhead['phases'] = ohLineList[2]

			overhead['length'] = ('10' if float(ohLineList[12])<10 else ohLineList[12])
			overhead[myIndex+1] = { 'omfEmbeddedConfigObject':'configuration object line_configuration',
							'name': overhead['name'] + '-LINECONFIG'}
			overhead[myIndex+1][myIndex+2] = {  'omfEmbeddedConfigObject' : 'spacing object line_spacing',
								'name': overhead['name'] + '-LINESPACING'}
			#Grab line spacing distances
			# Find name of construction code
			if ohLineList[13] == 'NONE':
				construction_description = 'SystemCnstDefault'
			else:
				construction_description = ohLineList[13]
			# Find the construction code in hardwareStats
			construction_stats = statsByName(construction_description)
			if construction_stats is None:
				#Couldn't find construction object. Using defalut phase distances. Distances are from IEEE 4 Node
				Dab = 2.5
				Dac = 7.0
				Dan = 5.656854
				Dbc = 4.5
				Dbn = 4.272002
				Dcn = 5.0
			else:
				# Find the distances in feet between each conductor
				Dab = _lineDistances(construction_stats[19],construction_stats[20], construction_stats[23], construction_stats[24])
				Dac = _lineDistances(construction_stats[19],construction_stats[21], construction_stats[23], construction_stats[25])
				Dan = _lineDistances(construction_stats[19],construction_stats[22], construction_stats[23], construction_stats[26])
				Dbc = _lineDistances(construction_stats[20],construction_stats[21], construction_stats[24], construction_stats[25])
				Dbn = _lineDistances(construction_stats[20],construction_stats[22], construction_stats[24], construction_stats[26])
				Dcn = _lineDistances(construction_stats[21],construction_stats[22], construction_stats[25], construction_stats[26])
			# Add distances to dictionary when appropriate
			if 'A' in overhead['phases'] and 'B' in overhead['phases']:
				if Dab > 0:
					overhead[myIndex+1][myIndex+2]['distance_AB'] = '{:0.6f}'.format(Dab)
				else:
					overhead[myIndex+1][myIndex+2]['distance_AB'] = '{:0.6f}'.format(2.5)
			else:
				overhead[myIndex+1][myIndex+2]['distance_AB'] = '{:0.6f}'.format(0.0)
			if 'A' in overhead['phases'] and 'C' in overhead['phases']:
				if Dac > 0:
					overhead[myIndex+1][myIndex+2]['distance_AC'] = '{:0.6f}'.format(Dac)
				else:
					overhead[myIndex+1][myIndex+2]['distance_AC'] = '{:0.6f}'.format(7.0)
			else:
				overhead[myIndex+1][myIndex+2]['distance_AC'] = '{:0.6f}'.format(0.0)
			if 'A' in overhead['phases'] and 'N' in overhead['phases']:
				if Dan > 0:
					overhead[myIndex+1][myIndex+2]['distance_AN'] = '{:0.6f}'.format(Dan)
				else:
					overhead[myIndex+1][myIndex+2]['distance_AN'] = '{:0.6f}'.format(5.656854)
			else:
				overhead[myIndex+1][myIndex+2]['distance_AN'] = '{:0.6f}'.format(0.0)
			if 'B' in overhead['phases'] and 'C' in overhead['phases']:
				if Dbc > 0:
					overhead[myIndex+1][myIndex+2]['distance_BC'] = '{:0.6f}'.format(Dbc)
				else:
					overhead[myIndex+1][myIndex+2]['distance_BC'] = '{:0.6f}'.format(4.5)
			else:
				overhead[myIndex+1][myIndex+2]['distance_BC'] = '{:0.6f}'.format(0.0)
			if 'B' in overhead['phases'] and 'N' in overhead['phases']:
				if Dbn > 0:
					overhead[myIndex+1][myIndex+2]['distance_BN'] = '{:0.6f}'.format(Dbn)
				else:
					overhead[myIndex+1][myIndex+2]['distance_BN'] = '{:0.6f}'.format(4.272002)
			else:
				overhead[myIndex+1][myIndex+2]['distance_BN'] = '{:0.6f}'.format(0.0)
			if 'C' in overhead['phases'] and 'N' in overhead['phases']:
				if Dcn > 0:
					overhead[myIndex+1][myIndex+2]['distance_CN'] = '{:0.6f}'.format(Dcn)
				else:
					overhead[myIndex+1][myIndex+2]['distance_CN'] = '{:0.6f}'.format(5.0)
			else:
				overhead[myIndex+1][myIndex+2]['distance_CN'] = '{:0.6f}'.format(0.0)
			eqdbIndex = {'A':8,'B':9,'C':10,'N':11}
			condIndex = {'A':3,'B':4,'C':5,'N':6}
			for letter in overhead['phases']:
				lineIndex = eqdbIndex[letter]
				hardware = statsByName(ohLineList[lineIndex])
				if hardware is None:
					res = '0.306'
					geoRad = '0.0244'
					diameter = '0.721'
				else:
					res = hardware[5]
					if res == '0':
						res = '0.306'
					geoRad = hardware[6]
					if geoRad == '0':
						geoRad = '0.0244'
					diameter = hardware[8]
					if diameter == '0':
						diameter = '0.721'
				overhead[myIndex+1][myIndex+condIndex[letter]] = {
					'omfEmbeddedConfigObject':'conductor_' + letter + ' object overhead_line_conductor',
					'name': overhead['name'] + '_conductor_' + letter,
					'resistance': res,
					'geometric_mean_radius': geoRad,
					'diameter' : diameter
				}
			# Check to see if there is distributed load on the line
			# WARNING: distributed load broken in GridLAB-D. Disabled for now.
			if 'A' in overhead['phases'] and (ohLineList[19] != '0' or ohLineList[22] != '0'):
				overhead['distributed_load_A'] = float(ohLineList[19])*1000 + float(ohLineList[22])*1000j
			if 'B' in overhead['phases'] and (ohLineList[20] != '0' or ohLineList[23] != '0'):
				overhead['distributed_load_B'] = float(ohLineList[20])*1000 + float(ohLineList[23])*1000j
			if 'C' in overhead['phases'] and (ohLineList[21] != '0' or ohLineList[24] != '0'):
				overhead['distributed_load_C'] = float(ohLineList[21])*1000 + float(ohLineList[24])*1000j
			return overhead

		def convertUgLine(ugLineList):
			for i in range(len(ugLineList)):
				if ugLineList[i] == '':
					ugLineList[i] = '0'
			myIndex = components.index(objectList)*subObCount
			underground = _convertGenericObject(ugLineList)
			# MAYBEFIX: be smarter about multiple neutrals.
			load_mix = statsByName(ugLineList[14])
			if load_mix is None or load_mix[5] == 'W':#Wye connected line
				underground['phases'] = ugLineList[2] + ('N' if ugLineList[33]=='1' else '')
			else: #Delta connected line
				# Delta loads are breaking things.
				# underground['phases'] = ugLineList[2] + ('D' if len(ugLineList[2]) >= 2 else '')
				underground['phases'] = ugLineList[2]
			underground['length'] = ('10' if float(ugLineList[12])<10 else ugLineList[12])
			underground[myIndex+1] = {
				'omfEmbeddedConfigObject':'configuration object line_configuration',
				'name': underground['name'] + '-LINECONFIG'
			}
			underground[myIndex+1][myIndex+2] = {   'omfEmbeddedConfigObject' : 'spacing object line_spacing',
									'name':underground['name'] + '-LINESPACING'}
			#Grab line spacing distances
			# Find name of construction code
			if ugLineList[13] == 'NONE':
				construction_description = 'SystemCnstDefault'
			else:
				construction_description = ugLineList[13]
			# Find the construction code in hardwareStats
			construction_stats = statsByName(construction_description)
			if construction_stats is None:
				#Couldn't find construction object. Using defalut phase distances. Distances are from IEEE 4 Node
				Dab = 2.5
				Dac = 7.0
				Dan = 5.656854
				Dbc = 4.5
				Dbn = 4.272002
				Dcn = 5.0
			else:
				# Find the distances in feet between each conductor
				Dab = _lineDistances(construction_stats[19],construction_stats[20], construction_stats[23], construction_stats[24])
				Dac = _lineDistances(construction_stats[19],construction_stats[21], construction_stats[23], construction_stats[25])
				Dan = _lineDistances(construction_stats[19],construction_stats[22], construction_stats[23], construction_stats[26])
				Dbc = _lineDistances(construction_stats[20],construction_stats[21], construction_stats[24], construction_stats[25])
				Dbn = _lineDistances(construction_stats[20],construction_stats[22], construction_stats[24], construction_stats[26])
				Dcn = _lineDistances(construction_stats[21],construction_stats[22], construction_stats[25], construction_stats[26])
			# Add distances to dictionary when appropriate
			if 'A' in underground['phases'] and 'B' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_AB'] = '{:0.6f}'.format(Dab)
			else:
				underground[myIndex+1][myIndex+2]['distance_AB'] = '{:0.1f}'.format(0.0)
			if 'A' in underground['phases'] and 'C' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_AC'] = '{:0.6f}'.format(Dac)
			else:
				underground[myIndex+1][myIndex+2]['distance_AC'] = '{:0.1f}'.format(0.0)
			if 'A' in underground['phases'] and 'N' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_AN'] = '{:0.6f}'.format(Dan)
			else:
				underground[myIndex+1][myIndex+2]['distance_AN'] = '{:0.1f}'.format(0.0)
			if 'B' in underground['phases'] and 'C' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_BC'] = '{:0.6f}'.format(Dbc)
			else:
				underground[myIndex+1][myIndex+2]['distance_BC'] = '{:0.1f}'.format(0.0)
			if 'B' in underground['phases'] and 'N' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_BN'] = '{:0.6f}'.format(Dbn)
			else:
				underground[myIndex+1][myIndex+2]['distance_BN'] = '{:0.1f}'.format(0.0)
			if 'C' in underground['phases'] and 'N' in underground['phases']:
				underground[myIndex+1][myIndex+2]['distance_CN'] = '{:0.6f}'.format(Dcn)
			else:
				underground[myIndex+1][myIndex+2]['distance_CN'] = '{:0.1f}'.format(0.0)
			#MAYBEFIX: actually get conductor values!
			eqdbIndex = {'A':8,'B':9,'C':10,'N':11}
			condIndex = {'A':3,'B':4,'C':5,'N':6}
			for letter in underground['phases']:
				lineIndex = eqdbIndex[letter]
				hardware = statsByName(ugLineList[lineIndex])
				if hardware is None:
					# Concentric Neutral 15 kV 2000 circular mil stranded AA
					conductor_resistance = '1.541000'
					conductor_diameter = 0.292
					conductor_gmr = '0.008830'
					neutral_resistance = '14.872200'
					neutral_diameter = 0.0641
					neutral_gmr = '0.002080'
					neutral_strands = '6'
					outer_diameter = 0.98
					insulation_relative_permitivity = '1'
					underground[myIndex+1][myIndex+condIndex[letter]] = {
						'omfEmbeddedConfigObject':'conductor_' + letter + ' object underground_line_conductor',
						'conductor_resistance' : conductor_resistance,
						'shield_resistance' : '0.000000',
						'neutral_gmr' : neutral_gmr,
						'outer_diameter' : '{:0.6f}'.format(outer_diameter),
						'neutral_strands' : neutral_strands,
						'neutral_resistance' : neutral_resistance,
						'neutral_diameter' : '{:0.6f}'.format(neutral_diameter),
						'conductor_diameter' : '{:0.6f}'.format(conductor_diameter),
						'shield_gmr' : '0.000000',
						'conductor_gmr' : conductor_gmr,
						'insulation_relative_permitivitty' : insulation_relative_permitivity
					}
				elif float(hardware[1]) == 2.0:
					conductor_resistance = hardware[4]
					if conductor_resistance == '0':
						conductor_resistance = '1.541000'
					conductor_diameter = float(hardware[17])*12
					if conductor_diameter == 0.0:
						conductor_diameter = 0.292
					conductor_gmr = hardware[5]
					if conductor_gmr == '0':
						conductor_gmr = '0.008830'
					neutral_resistance = hardware[6]
					if neutral_resistance == '0':
						neutral_resistance = '14.087220'
					neutral_diameter = (float(hardware[9]) - float(hardware[12]))*12
					if neutral_diameter == 0.0:
						neutral_diameter = 0.0641
					neutral_gmr = hardware[16]
					if neutral_gmr == '0':
						neutral_gmr = '0.002080'
					neutral_strands = hardware[7]
					if neutral_strands == '0':
						neutral_strands = '6'
					outer_diameter = float(hardware[9])*12
					if outer_diameter == 0.0:
						outer_diameter = 0.98
					insulation_relative_permitivity = hardware[11]
					if insulation_relative_permitivity == '0':
						insulation_relative_permitivity = '1'
					underground[myIndex+1][myIndex+condIndex[letter]] = {
						'omfEmbeddedConfigObject':'conductor_' + letter + ' object underground_line_conductor',
						'conductor_resistance' : conductor_resistance,
						'shield_resistance' : '0.000000',
						'neutral_gmr' : neutral_gmr,
						'outer_diameter' : '{:0.6f}'.format(outer_diameter),
						'neutral_strands' : neutral_strands,
						'neutral_resistance' : neutral_resistance,
						'neutral_diameter' : '{:0.6f}'.format(neutral_diameter),
						'conductor_diameter' : '{:0.6f}'.format(conductor_diameter),
						'shield_gmr' : '0.000000',
						'conductor_gmr' : conductor_gmr,
						'insulation_relative_permitivitty' : insulation_relative_permitivity
					}
			# Check to see if there is distributed load on the line
			if 'A' in underground['phases'] and (ugLineList[19] != '0' or ugLineList[22] != '0'):
				underground['distributed_load_A'] = float(ugLineList[19])*1000 + (float(ugLineList[22]))*1000j
			if 'B' in underground['phases'] and (ugLineList[20] != '0' or ugLineList[23] != '0'):
				underground['distributed_load_B'] = float(ugLineList[20])*1000 + (float(ugLineList[23]))*1000j
			if 'C' in underground['phases'] and (ugLineList[21] != '0' or ugLineList[24] != '0'):
				underground['distributed_load_C'] = float(ugLineList[21])*1000 + (float(ugLineList[24]))*1000j
			return underground

		def convertRegulator(regList):
			myIndex = components.index(objectList)*subObCount
			regulator = _convertGenericObject(regList)
			regulator['phases'] = regList[2]
			# Create an embedded object for the configuration and give it a variable name to make it easy to remember.
			regulator[myIndex+1] = {}
			regConfig = regulator[myIndex+1]
			#MAYBEFIX: figure out whether I'll run into trouble if the previous integer isn't unique.
			# Grab regulator configuration parameters
			reg_hardware = statsByName(regList[11])
			try:
				raise_taps = math.ceil(float(reg_hardware[4])/float(reg_hardware[6]))
				lower_taps = math.ceil(float(reg_hardware[5])/float(reg_hardware[6]))
				# HACK: GridLAB-D doesn't like either of these to be zero.
				if raise_taps <= 0.0:
					raise_taps = 1.0
				if lower_taps <= 0.0:
					lower_taps = 1.0
				raise_taps = str(raise_taps)
				lower_taps = str(lower_taps)
				band_width = str(float(reg_hardware[7])*120)
				if float(reg_hardware[4]) > 0.0:
					regulation = reg_hardware[4]
				elif float(reg_hardware[5]) > 0.0:
					regulation = reg_hardware[5]
				else:
					regulation = '0.1'
				if float(reg_hardware[3]) > 0.0:
					ctr = reg_hardware[3]
				else:
					ctr = '700'
			except:
				ctr = '700'
				band_width = '2'
				raise_taps = '16'
				lower_taps = '16'
				regulation = '0.1'
			# Set control mode:
			if regList[9] == '0':
				# Each phase is controlled independently
				band_center = str(float(regList[14])*120)
				regConfig['control_level'] = 'INDIVIDUAL'
			elif regList[9] == '1':
				# Bank with A as control phase
				band_center = str(float(regList[14])*120)
				regConfig['control_level'] = 'BANK'
				regConfig['CT_phase'] = 'A'
				regConfig['PT_phase'] = 'A'
			elif regList[9] == '2':
				# Bank with B as control phase
				band_center = str(float(regList[15])*120)
				regConfig['control_level'] = 'BANK'
				regConfig['CT_phase'] = 'B'
				regConfig['PT_phase'] = 'B'
			elif regList[9] == '3':
				# Bank with C as control phase
				band_center = str(float(regList[16])*120)
				regConfig['control_level'] = 'BANK'
				regConfig['CT_phase'] = 'C'
				regConfig['PT_phase'] = 'C'
			else:
				# Default to individual control.
				band_center = str(float(regList[14])*120)
				regConfig['control_level'] = 'INDIVIDUAL'
			# Fix wonky band_center
			if float(band_center) == 0.0:
				band_center = '122'
			# Set some additional configuration parameters.
			regConfig['name'] = regulator['name'] + '-CONFIG'
			regConfig['omfEmbeddedConfigObject'] = 'configuration object regulator_configuration'
			regConfig['band_center'] = band_center
			regConfig['band_width'] = band_width
			regConfig['raise_taps'] = raise_taps
			regConfig['lower_taps'] = lower_taps
			regConfig['regulation'] = regulation
			regConfig['Type'] = 'A'
			#MAYBEFIX: change these from just default values:
			regConfig['connect_type'] = 'WYE_WYE'
			regConfig['time_delay'] = '30.0'
			# Line drop compensation settings.
			ldc_r_A = float(regList[17])
			ldc_r_B = float(regList[18])
			ldc_r_C = float(regList[19])
			ldc_x_A = float(regList[20])
			ldc_x_B = float(regList[21])
			ldc_x_C = float(regList[22])
			if ldc_r_A > 0.0 or ldc_r_B > 0.0 or ldc_r_C > 0.0 or ldc_x_A > 0.0 or ldc_x_B > 0.0 or ldc_x_C > 0.0:
				regConfig['Control'] = control = 'LINE_DROP_COMP'
			else:
				regConfig['Control'] = control = 'OUTPUT_VOLTAGE'
			if ctr is not None:
				regConfig['current_transducer_ratio'] = ctr
			if ldc_r_A != 0.0 and 'A' in regulator['phases']:
				regConfig['compensator_r_setting_A'] = str(ldc_r_A*120)
			if ldc_x_A != 0.0 and 'A' in regulator['phases']:
				regConfig['compensator_x_setting_A'] = str(ldc_x_A*120)
			if ldc_r_B != 0.0 and 'B' in regulator['phases']:
				regConfig['compensator_r_setting_B'] = str(ldc_r_B*120)
			if ldc_x_B != 0.0 and 'B' in regulator['phases']:
				regConfig['compensator_x_setting_B'] = str(ldc_x_B*120)
			if ldc_r_C != 0.0 and 'C' in regulator['phases']:
				regConfig['compensator_r_setting_C'] = str(ldc_r_C*120)
			if ldc_x_C != 0.0 and 'C' in regulator['phases']:
				regConfig['compensator_x_setting_C'] = str(ldc_x_C*120)
			# Set tap positions.
			if 'A' in regulator['phases']:
				regConfig['tap_pos_A'] = '1'
			if 'B' in regulator['phases']:
				regConfig['tap_pos_B'] = '1'
			if 'C' in regulator['phases']:
				regConfig['tap_pos_C'] = '1'
			return regulator

		def convertTransformer(transList):
			myIndex = components.index(objectList)*subObCount
			transformer = _convertGenericObject(transList)
			transformer['phases'] = transList[2]
			# transformer['nominal_voltage'] = '2400'
			transformer[myIndex+1] = {}
			# Better name for this.
			transConfig = transformer[myIndex+1]
			transConfig['name'] = transformer['name'] + '-CONFIG'
			transConfig['omfEmbeddedConfigObject'] = 'configuration object transformer_configuration'
			transConfig['primary_voltage'] = str(float(transList[10])*1000)
			transConfig['secondary_voltage'] = str(float(transList[13])*1000)
			# Grab transformer phase hardware. NOTE: the default values were averages from the test files.
			if 'A' in transformer['phases']:
				trans_config = statsByName(transList[24])
				no_load_loss = _safeGet(trans_config, 20, 0)
				percent_z = _safeGet(trans_config, 4, 3)
				x_r_ratio = _safeGet(trans_config, 7, 5)
			elif 'B' in transformer['phases']:
				trans_config = statsByName(transList[25])
				no_load_loss = _safeGet(trans_config, 21, 0)
				percent_z = _safeGet(trans_config, 5, 3)
				x_r_ratio = _safeGet(trans_config, 8, 5)
			else:
				trans_config = statsByName(transList[26])
				no_load_loss = _safeGet(trans_config, 22, 0)
				percent_z = _safeGet(trans_config, 6, 3)
				x_r_ratio = _safeGet(trans_config, 9, 5)
			# Set the shunt impedance
			try:
				f_no_load_loss = float(no_load_loss)
			except:
				f_no_load_loss = 0.0
			if f_no_load_loss > 0.0:
				r_shunt = float(transList[10])*float(transList[10])*1000/f_no_load_loss
				x_shunt = r_shunt*float(x_r_ratio)
				transConfig['shunt_impedance'] = str(r_shunt) + '+' + str(x_shunt) + 'j'
			# Set series impedance
			try:
				r_series = float(percent_z)*0.01/math.sqrt(1+(float(x_r_ratio)*float(x_r_ratio)))
				x_series = r_series*float(x_r_ratio)
				# HACK: we can't have zeros in the impedances.
				if r_series <= 0.0:
					r_series = 0.00033
				if x_series <= 0.0:
					x_series = 0.0022
				transConfig['impedance'] = str(r_series) + '+' + str(x_series) + 'j'
			except:
				transConfig['impedance'] = '0.00033+0.0022j'
			# NOTE: Windmil doesn't export any information on install type, but Gridlab only puts it in there for info reasons.
			# transformer[1]['install_type'] = 'POLETOP'
			# Set the connection type
			transPhases = _safeGet(transList, 2, '')
			if len(transPhases) > 2:
				transConfig['connect_type'] = 'WYE_WYE'
				#MAYBEFIX: support other types of windings (D-D, D-Y, etc.)
			else:
				transConfig['connect_type'] = 'SINGLE_PHASE'
			# Set the power rating.
			try:
				transConfig['power_rating'] = str(float(transList[19]) + float(transList[20]) + float(transList[21]))
				if float(transList[19]) > 0:
					transConfig['powerA_rating'] = transList[19]
				if float(transList[20]) > 0:
					transConfig['powerB_rating'] = transList[20]
				if float(transList[21]) > 0:
					transConfig['powerC_rating'] = transList[21]
				# HACK: a zero power rating makes no sense.
				if float(transConfig['power_rating']) < 1.0:
					raise Exception
			except:
				transConfig['power_rating'] = '500.0'
			return transformer

		# Simple lookup table for which function we need to apply:
		objectToFun = {
			1 : convertOhLine,
			2 : convertCapacitor,
			3 : convertUgLine,
			4 : convertRegulator,
			5 : convertTransformer,
			6 : convertSwitch,
			8 : convertNode,
			9 : convertSource,
			10 : convertOvercurrentDevice,
			11 : convertMotor,
			12 : convertGenerator,
			13 : convertConsumer
		}
		# Apply fun:
		return objectToFun[int(objectList[1])](objectList)

	# If we got numbered phases, convert them to letters.
	for ob in components:
		phaseNumToLetter = {'1':'A','2':'B','3':'C','4':'AB','5':'AC','6':'BC','7':'ABC'}
		# replace numbers, leave letters alone.
		ob[2] = phaseNumToLetter.get(ob[2],ob[2])

	# Convert to a list of dicts:
	convertedComponents = [obConvert(x) for x in components]

	# First, make an index to massively speed up lookups.
	nameToIndex = {convertedComponents[index].get('name',''):index for index in range(len(convertedComponents))}
	def fixCompConnectivity(comp):
		''' Rejigger the connectivity attributes to work with Gridlab '''
		# Different object connectivity classes:
		fromToable = ['overhead_line','underground_line','regulator','transformer','switch','fuse']
		nodable = ['node']
		parentable = ['capacitor','ZIPload','diesel_dg','load']
		# Update our name index:
		# Use GUID index.
		def getByGuid(guid):
			try:
				targetIndex = guidToIndex[guid]
				return convertedComponents[targetIndex]
			except:
				return {}
		# Use name index.
		def getByName(name):
			targetIndex = nameToIndex[name]
			return convertedComponents[targetIndex]
		def parentType(ob):
			thing = getByGuid(ob['guid'])
			parent = getByGuid(thing['parentGuid'])
			if 'object' in parent.keys():
				return parent['object']
			else:
				pass
		def phaseMerge(*arg):
			concated = ''.join(arg)
			return ''.join(sorted(set(concated)))
		# If we already stripped the GUID, don't process:
		if 'guid' not in comp.keys():
			return False
		# Hang on to the component's parent:
		parent = getByGuid(comp['parentGuid'])
		# Rejigger the attributes:
		if comp['object'] in parentable and parentType(comp) in nodable:
			comp['parent'] = parent['name']
		elif comp['object'] in fromToable and parentType(comp) in nodable:
			comp['from'] = parent['name']
		elif comp['object'] in parentable and parentType(comp) in fromToable:
			if 'to' in parent.keys():
				comp['parent'] = parent['to']
				# Making sure our nodes have the superset of connected phases:
				interNode = getByName(parent['to'])
				interNode['phases'] = phaseMerge(interNode['phases'],comp['phases'])
			else:
				# Gotta insert a node between lines and parentable objects:
				nodeName = 'node' + comp['name'] + parent['name']
				newNode = {
					'object': 'node',
					'phases': comp['phases'],
					'name': nodeName,
					'nominal_voltage': nominal_voltage,
					'latitude': comp['latitude'],
					'longitude': comp['longitude']
				}
				convertedComponents.append(newNode)
				nameToIndex[nodeName] = len(convertedComponents) - 1
				parent['to'] = newNode['name']
				comp['parent'] = newNode['name']
		elif comp['object'] in fromToable and parentType(comp) in fromToable:
			if 'to' in parent.keys():
				comp['from'] = parent['to']
				# Making sure our nodes have the superset of connected phases:
				interNode = getByName(parent['to'])
				interNode['phases'] = phaseMerge(interNode['phases'],comp['phases'])
			else:
				# Gotta insert a node between two lines:
				nodeName = 'node' + comp['name'] + parent['name']
				newNode = {
					'object':'node',
					'phases':comp['phases'],
					'name': nodeName,
					'nominal_voltage':nominal_voltage,
					'latitude': comp['latitude'],
					'longitude': comp['longitude']
				}
				convertedComponents.append(newNode)
				nameToIndex[nodeName] = len(convertedComponents) - 1
				parent['to'] = newNode['name']
				comp['from'] = newNode['name']
		elif comp['object'] in nodable and parentType(comp) in fromToable:
			parent['to'] = comp['name']
		else:
			# Here we're in an error case (like loads connected to loads), so do nothing:
			return False
		return True

	# Fix the connectivity:
	warnings.warn('*** Connectivity fixing start %0.3f' % (time.time()-start_time))
	guidToIndex = {convertedComponents[index].get('guid',''):index for index in range(len(convertedComponents))}
	for comp in convertedComponents:
		fixCompConnectivity(comp)

	# Go to a dictionary format so we have a valid glmTree. Start at 1 so we have room for headers:
	glmTree = {(1+convertedComponents.index(x))*subObCount:x for x in convertedComponents}

	#MAYBEFIX: REMOVE THIS DISASTER HERE AND FIGURE OUT WHY SOME LINKS ARE MALFORMED
	for key in list(glmTree.keys()):
		# if ('from' in glmTree[key].keys() and 'to' not in glmTree[key].keys()) or ('to' in glmTree[key].keys() and 'from' not in glmTree[key].keys()):
		if glmTree[key]['object'] in ['overhead_line','underground_line','regulator','transformer','switch','fuse'] and ('to' not in glmTree[key].keys() or 'from' not in glmTree[key].keys()):
			warnings.warn('Object borked connectivity %s %s' % (glmTree[key]['name'], glmTree[key]['object']))
			del glmTree[key]

	#Strip guids:
	for key in glmTree:
		if 'guid' in glmTree[key]: del glmTree[key]['guid']
		if 'parentGuid' in glmTree[key]: del glmTree[key]['parentGuid']

	# First, make an index to massively speed up lookups.
	nameToIndex = {glmTree[key].get('name',''):key for key in glmTree}
	def fixLinkPhases(comp):
		def getByName(name):
			targetIndex = nameToIndex[name]
			return glmTree[targetIndex]
		if comp['object'] in ['overhead_line','underground_line','regulator','transformer','switch','fuse']:
			fromPhases = getByName(comp['from'])['phases']
			toPhases = getByName(comp['to'])['phases']
			# Minimal set of shared phases:
			comp['phases'] = ''.join(set(fromPhases).intersection(set(toPhases)))
			if 'N' in comp['phases'] and (comp['object'] == 'overhead_line' or comp['object'] == 'underground_line'):
				key = 0
				for y in comp.keys():
					if type(y) is int:
						key = y+5
						if key in comp[y].keys():# line_configuration has a neutral conductor
							pass
						else:
							comp['phases'] = comp['phases'].replace('N','')
			return True
		else:
			return False

	warnings.warn('*** Link phase fixing %0.3f' % (time.time()-start_time))
	for key in glmTree:
		fixLinkPhases(glmTree[key])

	# Convert lines with distributed load
	def convDistLoadLines(glm_dict):
		last_key = max(glm_dict.keys())
		# Grab all the keys of overhead or underground lines that have distributed loads
		dl_line_keys = [x for x in glm_dict if 'distributed_load_A' in glm_dict[x] or 'distributed_load_B' in glm_dict[x] or 'distributed_load_C' in glm_dict[x]]
		warnings.warn("##### %d DISTRIBUTED THINGS ARE HAPPENING" % len(dl_line_keys))
		for y in dl_line_keys:
			load = None
			for x in glm_dict.keys():
				try:
					if glm_dict[x].get('name') == glm_dict[y]['to']:
						load = copy.deepcopy(glm_dict[x])
				except:
					pass
			if load != None:
				load['name'] = glm_dict[y]['name'] + '_distributed_load'
				load['parent'] = glm_dict[y]['to']
				load['phases'] = glm_dict[y]['phases']
				load['object'] = 'load'
				load['load_class'] = 'C'
				for ph in "ABC":
					if 'distributed_load_' + ph in glm_dict[y]:
						load['constant_power_' + ph] = (
								str(glm_dict[y]['distributed_load_' + ph].real)
								+ ('+' if glm_dict[y]['distributed_load_' + ph].imag >= 0.0 else '-')
								+ str(abs(glm_dict[y]['distributed_load_' + ph].imag))
								+ 'j'
							)
						del glm_dict[y]['distributed_load_' + ph]
				glm_dict[last_key*subObCount] = load
		return glm_dict

	# WARNING: this code creates broken GLMs. Disabled by default.
	glmTree = convDistLoadLines(glmTree)
	# Fix nominal voltage
	warnings.warn('*** Nominal voltage fixing %0.3f' % (time.time()-start_time))

	# Make sure we have the latest index.
	nameToIndex = {glmTree[key].get('name',''):key for key in glmTree}
	def fix_nominal_voltage(glm_dict, volt_dict):
		for x in glm_dict:
			if 'parent' in glm_dict[x].keys() and glm_dict[x]['parent'] in volt_dict.keys() and glm_dict[x]['name'] not in volt_dict.keys():
				glm_dict[x]['nominal_voltage'] = volt_dict[glm_dict[x]['parent']]
				volt_dict[glm_dict[x]['name']] = glm_dict[x]['nominal_voltage']
			elif 'from' in glm_dict[x].keys() and glm_dict[x]['from'] in volt_dict.keys() and glm_dict[x]['name'] not in volt_dict.keys():
				if glm_dict[x]['object'] == 'transformer':
					for y in glm_dict[x]:
						if type(y) is int:
							nv = glm_dict[x][y]['secondary_voltage']
					glm_dict[x]['nominal_voltage'] = nv
				else:
					glm_dict[x]['nominal_voltage'] = volt_dict[glm_dict[x]['from']]
				volt_dict[glm_dict[x]['name']] = glm_dict[x]['nominal_voltage']
				# Huh.
				y = nameToIndex.get(glm_dict[x]['to'], None)
				if y is not None:
					glm_dict[y]['nominal_voltage'] = glm_dict[x]['nominal_voltage']
					volt_dict[glm_dict[y]['name']] = glm_dict[y]['nominal_voltage']
			# Regulator_Configuration set to Swing
			try:
				if 'SWING' in glm_dict[x].values():
					nominalVoltageSwing = float(glm_dict[x]['nominal_voltage'])
				if 'regulator' in glm_dict[x].values():
					for key, value in glm_dict[x].items():
						if 'band_center' in glm_dict[x][key]:
							bandWidthRegulator = float(glm_dict[x][key]['band_width'])
							if (glm_dict[x][key]['band_center'] != nominalVoltageSwing):
								glm_dict[x][key]['band_center'] = nominalVoltageSwing
								glm_dict[x][key]['band_width'] =  (bandWidthRegulator * nominalVoltageSwing) / 120
			except:
				pass
				warnings.warn("\n   Couldn't set regulator_configuration to the swing bus nominal_voltage.")

	parent_voltage = {}
	current_parents = len(parent_voltage)
	previous_parents = 0

	for obj in glmTree:
		if 'bustype' in glmTree[obj] and glmTree[obj]['bustype'] == 'SWING':
			parent_voltage[glmTree[obj]['name']] = glmTree[obj]['nominal_voltage']
			current_parents = len(parent_voltage)

	while current_parents > previous_parents:
		fix_nominal_voltage(glmTree, parent_voltage)
		previous_parents = current_parents
		current_parents = len(parent_voltage)

	# figure out the PT rating for regulators
	for x in glmTree.keys():
		if 'object' in glmTree[x].keys() and glmTree[x]['object'] == 'regulator':
			for y in glmTree[x].keys():
				if type(glmTree[x][y]) is dict:
					glmTree[x][y]['power_transducer_ratio'] = str(float(glmTree[x].get('nominal_voltage', 14400)) / 120)

	# Delete nominal_voltage from link objects
	del_nom_volt_list = ['overhead_line', 'underground_line', 'regulator', 'transformer', 'switch', 'fuse', 'ZIPload', 'diesel_dg']
	for x in glmTree:
		if 'object' in glmTree[x].keys() and glmTree[x]['object'] in del_nom_volt_list and 'nominal_voltage' in glmTree[x].keys():
			del glmTree[x]['nominal_voltage']

	warnings.warn('*** Secondary system fixing %0.3f' % (time.time()-start_time))
	def secondarySystemFix(glm):
		def unused_key(dic, key_multiplier):
			free_key = (int(max(dic.keys())/key_multiplier) + 1)*key_multiplier
			return free_key
		allLoadKeys = [x for x in glm if 'object' in glm[x] and 'parent' in glm[x] and glm[x]['object']=='load' and 'load_class' in glm[x] and glm[x]['load_class'] == 'R']
		allNamesNodesOnLoads = list(set([glm[key]['parent'] for key in allLoadKeys]))
		all2ndTransKeys = []
		all2ndLoadKeys = []
		all2ndNodeKeys = []
		def nameToKey(name):
			hits = [x for x in glm if 'name' in glm[x] and glm[x]['name'] == name]
			if len(hits) == 0:
				return []
			else:
				return hits
		for key in glm:
			if 'object' in glm[key] and glm[key]['object'] == 'transformer':
				#fromName = glm[key]['from']
				toName = glm[key]['to']
				#if fromName in allNamesNodesOnLoads:
				#   all2ndTransKeys.append(key)
				#   all2ndNodeKeys.extend(nameToKey(fromName))
				#   all2ndLoadKeys.extend([x for x in glm if 'parent' in glm[x] and 'object' in glm[x] and glm[x]['object'] == 'load' and glm[x]['parent'] == fromName])
				if toName in allNamesNodesOnLoads:
					all2ndTransKeys.append(key)
					all2ndNodeKeys.extend(nameToKey(toName))
					all2ndLoadKeys.extend([x for x in glm if 'parent' in glm[x] and 'object' in glm[x] and glm[x]['object'] == 'load' and glm[x]['parent'] == toName])
				else:
					# this ain't no poletop transformer
					pass
		# Fix da nodes.
		# {'phases': 'BN', 'object': 'node', 'nominal_voltage': '2400', 'name': 'nodeS1806-32-065T14102'}
		# object triplex_meter { phases BS; nominal_voltage 120; };
		for nodeKey in all2ndNodeKeys:
			phases = set(glm[nodeKey]['phases'])
			#if the node has multiple phases we need to split it out to multiple triplex_meters
			for y in phases:
				if y != 'N' and y != 'D':
					new_key = unused_key(glm,subObCount)
					glm[new_key] = {'object' : 'triplex_meter',
									'name' : glm[nodeKey]['name'] + '_' + y,
									'phases' : y + 'S',
									'nominal_voltage' : '120'}
		# Fix da loads.
		#{'phases': 'BN', 'object': 'load', 'name': 'S1806-32-065', 'parent': 'nodeS1806-32-065T14102', 'load_class': 'R', 'constant_power_C': '0', 'constant_power_B': '1.06969', 'constant_power_A': '0', 'nominal_voltage': '120'}
		for loadKey in all2ndLoadKeys:
			phases = set(glm[loadKey]['phases'])
			for y in phases:
				if y != 'N' and y != 'D':
					new_key = unused_key(glm,subObCount)
					glm[new_key] = {
						'object' : 'triplex_node',
						'name' : glm[loadKey]['name'] + '_' + y,
						'phases' : y + 'S',
						'parent' : glm[loadKey]['parent'] + '_' + y,
						'nominal_voltage' : '120'
					}
					if y == 'A':
						glm[new_key]['power_12'] = glm[loadKey]['constant_power_A']
					elif y == 'B':
						glm[new_key]['power_12'] = glm[loadKey]['constant_power_B']
					elif y == 'C':
						glm[new_key]['power_12'] = glm[loadKey]['constant_power_C']
		# Gotta fix the transformer phases too...
		for key in all2ndTransKeys:
			phases = set(glm[key]['phases'])
			for y in phases:
				if y != 'N' and y != 'D':
					new_key = unused_key(glm,subObCount)
					glm[new_key] = {
						'object' : 'transformer',
						'name' : glm[key]['name'] + '_' + y,
						'phases' : y + 'S',
						'from' : glm[key]['from'],
						'to' : glm[key]['to'] + '_' + y
						}
					for z in glm[key]:
						if type(z) is int:
							glm[new_key][new_key+1] = {
								'omfEmbeddedConfigObject' : 'configuration object transformer_configuration',
								'name' : glm[new_key]['name'] + '-CONFIG',
								'primary_voltage' : glm[key][z]['primary_voltage'],
								'secondary_voltage' : '120.0',
								'connect_type' : 'SINGLE_PHASE_CENTER_TAPPED',
								'impedance' : glm[key][z]['impedance']
							}
							if 'shunt_impedance' in glm[key][z]:
								glm[new_key][new_key+1]['shunt_impedance'] = glm[key][z]['shunt_impedance']
							#NOTE: default values are average of all .std data sets we've seen.
							if y == 'A':
								glm[new_key][new_key+1]['power_rating'] = glm[key][z].get('powerA_rating', 250)
								glm[new_key][new_key+1]['powerA_rating'] = glm[key][z].get('powerA_rating', 250)
							elif y == 'B':
								glm[new_key][new_key+1]['power_rating'] = glm[key][z].get('powerB_rating', 250)
								glm[new_key][new_key+1]['powerB_rating'] = glm[key][z].get('powerB_rating', 250)
							elif y == 'C':
								glm[new_key][new_key+1]['power_rating'] = glm[key][z].get('powerC_rating', 250)
								glm[new_key][new_key+1]['powerC_rating'] = glm[key][z].get('powerC_rating', 250)
		# Delete original transformers, nodes and loads that the split phase objects are representing
		for key in all2ndTransKeys:
			del glm[key]
		for key in all2ndLoadKeys:
			del glm[key]
		for key in all2ndNodeKeys:
			del glm[key]
	# Fixing the secondary (triplex) system.
	secondarySystemFix(glmTree)

	def dedupGlm(compName, glmRef):
		'''
		Assume compName is transformer_configuration
		1. pull out a list of all transformer_configuration dicts.
		2. process to make redundant ones into tuples
		3. go through the list backwards and collapse chains of references. or fold carefully until we can't fold any more.
		4. actually replace the names on other objects and then delete the tuples.
		'''
		def isSameMinusName(x,y):
			newX = {val:x[val] for val in x if val != 'name'}
			newY = {val:y[val] for val in y if val != 'name'}
			return newX==newY
		def dupToTup(inList):
			# Go through a list of components, and given two identicals (up to name) in a row, replace the first one with (name1, name2).
			for i in range(0,len(inList)-1):
				if isSameMinusName(inList[i], inList[i+1]):
					inList[i] = (inList[i]['name'], inList[i+1]['name'])
				else:
					pass
		def dechain(tupleList):
			# Go backwards through a list of tuples and change e.g. (1,2),(2,3),(3,4) into (1,4),(2,4),(3,4).
			for i in range(len(tupleList)-1,0,-1):
				if tupleList[i][0] == tupleList[i-1][1]:
					tupleList[i-1] = (tupleList[i-1][0], tupleList[i][1])
				else:
					pass

		# sort the components, ignoring their names:
		compList = sorted(
			[glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] == compName],
			key=lambda x: str({val: x[val] for val in x if val != 'name'})
		)

		dupToTup(compList)

		nameMaps = [x for x in compList if type(x) is tuple]
		realConfigs = [x for x in compList if type(x) is dict]

		dechain(nameMaps)

		#Debug: print the amount of collapse:
		#'WORKING ON ' + compName
		#'Mappings:'
		#len(nameMaps)
		#'Real configs:'
		#len(realConfigs)
		#'Total:'
		#len(nameMaps) + len(realConfigs)

		nameDictMap = {x[0]:x[1] for x in nameMaps}

		# Killing duplicate objects
		iterKeys = list(glmRef.keys())
		for x in iterKeys:
			if 'name' in glmRef[x] and glmRef[x]['name'] in nameDictMap.keys():
				del glmRef[x]

		# Rewiring all objects
		iterKeys = list(glmRef.keys())
		if compName == 'transformer_configuration':
			transformers = [glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] == 'transformer']
			for tranny in transformers:
				if tranny['configuration'] in nameDictMap.keys(): tranny['configuration'] = nameDictMap[tranny['configuration']]
		elif compName == 'regulator_configuration':
			regulators = [glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] == 'regulator']
			for reggy in regulators:
				if reggy['configuration'] in nameDictMap.keys(): reggy['configuration'] = nameDictMap[reggy['configuration']]
		elif compName == 'line_spacing':
			lineConfigs = [glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] == 'line_configuration']
			for config in lineConfigs:
				if config['spacing'] in nameDictMap.keys(): config['spacing'] = nameDictMap[config['spacing']]
		elif compName == 'overhead_line_conductor' or compName == 'underground_line_conductor':
			lineConfigs = [glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] == 'line_configuration']
			for config in lineConfigs:
				if 'conductor_A' in config.keys():
					if config['conductor_A'] in nameDictMap.keys(): config['conductor_A'] = nameDictMap[config['conductor_A']]
				if 'conductor_B' in config.keys():
					if config['conductor_B'] in nameDictMap.keys(): config['conductor_B'] = nameDictMap[config['conductor_B']]
				if 'conductor_C' in config.keys():
					if config['conductor_C'] in nameDictMap.keys(): config['conductor_C'] = nameDictMap[config['conductor_C']]
				if 'conductor_N' in config.keys():
					if config['conductor_N'] in nameDictMap.keys(): config['conductor_N'] = nameDictMap[config['conductor_N']]
		elif compName == 'line_configuration':
			lines = [glmRef[x] for x in glmRef if 'object' in glmRef[x] and glmRef[x]['object'] in ['overhead_line','underground_line']]
			for line in lines:
				if line['configuration'] in nameDictMap.keys(): line['configuration'] = nameDictMap[line['configuration']]

	# Fully disembed and remove duplicate configuration objects:
	warnings.warn('*** Disembed and dedup %0.3f' % (time.time()-start_time))
	feeder.fullyDeEmbed(glmTree)
	dedupGlm('transformer_configuration', glmTree)
	dedupGlm('regulator_configuration', glmTree)
	dedupGlm('line_spacing', glmTree)
	dedupGlm('overhead_line_conductor', glmTree)
	dedupGlm('underground_line_conductor', glmTree)
	# NOTE: This last dedup has to come last, because it relies on doing conductors and spacings first!
	dedupGlm('line_configuration', glmTree)
	# Throw some headers on that:
	genericHeaders = [
		{"timezone":"PST+8PDT","stoptime":"'2000-01-01 00:00:00'","starttime":"'2000-01-01 00:00:00'","clock":"clock"},
		{"omftype":"#set","argument":"minimum_timestep=60"},
		{"omftype":"#set","argument":"profiler=1"},
		{"omftype":"#set","argument":"relax_naming_rules=1"},
		{"omftype":"#include","argument":"\"schedules.glm\""},
		{"omftype":"module","argument":"generators"},
		{"omftype":"module","argument":"tape"},
		{"module":"residential","implicit_enduses":"NONE"},
		{"solver_method":"FBS","module":"powerflow"},
		{"omftype": "module", "argument": "climate"},
		{"object":"climate", "name":"Climate", "interpolate": "QUADRATIC", "tmyfile": "climate.tmy2"}
	]
	for headId in range(len(genericHeaders)):
		glmTree[headId] = genericHeaders[headId]

	# Go through and put lat/lons on meters and loads.
	nameToIndex = {glmTree[key].get('name',''):key for key in glmTree}
	for key in glmTree:
		thisOb = glmTree[key]
		if thisOb.get('object','') == 'transformer':
			fromOb = glmTree.get(nameToIndex.get(thisOb.get('from',''),0),{})
			toOb = glmTree.get(nameToIndex.get(thisOb.get('to',''),0),{})
			if toOb.get('object','') == 'triplex_meter' and 'latitude' in fromOb and 'longitude' in fromOb:
				toOb['latitude'] = str(float(fromOb['latitude']) + random.uniform(-10,10))
				toOb['longitude'] = str(float(fromOb['longitude']) + random.uniform(-10,10))
	for key in glmTree:
		thisOb = glmTree[key]
		if thisOb.get('object','') in ['triplex_node','load']:
			parentOb = glmTree.get(nameToIndex.get(thisOb.get('parent',''),0),{})
			if 'latitude' in parentOb and 'longitude' in parentOb:
				thisOb['latitude'] = str(float(parentOb['latitude']) + random.uniform(-5,5))
				thisOb['longitude'] = str(float(parentOb['longitude']) + random.uniform(-5,5))
	# 8B research fixes
	glmTree = phasingMismatchFix(glmTree)
	glmTree = missingConductorsFix(glmTree)
	glmTree = fixOrphanedLoads(glmTree)
	# Final Output
	warnings.warn('*** DONE! %0.3f' % (time.time()-start_time))
	return glmTree

def stdSeqToGlm(seqPath, stdPath, glmPath):
	'''Convert a pair of .std and .seq files directly to .glm'''
	with open(stdPath) as f:
		stdString = f.read()
	with open(seqPath) as f:
		seqString = f.read()
	tree = convert(stdString, seqString)
	# Remove climate and schedules to enforce running one timestep.
	for key in list(tree.keys()):
		obj = tree[key]
		if 'omftype' in obj and obj['omftype']=='#include':
			del tree[key]
		elif 'object' in obj and obj['object']=='climate':
			del tree[key]
		elif 'module' in obj and obj['module']=='powerflow':
			obj['solver_method'] = 'FBS'
	with open(glmPath, 'w') as outFile:
		outFile.write(omf.feeder.sortedWrite(tree))

def missingConductorsFix(tree):
	'''Fixes the missing conductors issue in the tree'''
	### CHECK IF THERE ARE LINE CONFIGS WITHOUT ANY CONDUCTORS ###
	empty_line_configs = dict()
	#get line configs missing conductors (dict maps name to key w/in tree)
	for k,v in tree.items():
		if v.get('object') == 'line_configuration' and not any('conductor' in vk for vk in v.keys()):
			empty_line_configs[v['name']] = k

	#get keys of lines missing conductors
	empty_lines = [k for k,v in tree.items() if 'line' in v.get('object','') and v.get('configuration') in empty_line_configs]

	for line_key in empty_lines:
		#find sibling lines
		mom_node = tree[line_key]['from']
		dotter_node = tree[line_key]['to']
		brother_key = None
		grandpa_key = None
		grandson_key = None
		for k,v in tree.items():
			if k not in empty_lines and tree[line_key]['object'] == v.get('object'):
				if mom_node == v.get('from','') or dotter_node == v.get('to',''):
					brother_key = k
					break
				if mom_node == v.get('to', ''):
					grandpa_key = k
				if dotter_node == v.get('from', ''):
					grandson_key = k
				if grandpa_key and grandson_key:
					break

		nearby = brother_key if brother_key else (grandson_key if grandson_key else grandpa_key)

		if not nearby:
			#check child lines of the cousins of the mom node
			#AKA second cousin lines
			#first we need to get the parent's cousin's nodes
			ggma_node_names = []
			for k,v in tree.items():
				if 'line' in v.get('object','') and mom_node == v.get('to'):
					ggma_node_names.append(v.get('from'))
			cousin_node_names = [] #dict(name: [] for name in ggma_node_names)
			for k,v in tree.items():
				if v.get('from') in ggma_node_names:
					cousin_node_names.append(v.get('to'))

			for k,v in tree.items():
				if v.get('from') in cousin_node_names and v['object'] == tree[line_key]['object'] and k not in empty_lines:
					nearby = k
					break

		if not nearby:
			#second cousins failed us so check the whole tree for a usable config
			for k,v in tree.items():
				if v.get('object') == tree[line_key]['object'] and k not in empty_lines:
					nearby = k

		if not nearby:
			#there is no usable line_config in the whole tree, so we use our default conductor and stick it in the current line_config
			#find our line config's key and check if we've already inserted our default conductor
			default_name = default_equipment[ tree[line_key]['object'] + '_conductor' ]['name']
			not_inserted = True
			for k, v in tree.items():
				if v.get('name') == tree[line_key]['configuration']:
					lc_key = k
				if v.get('name') == default_name:
					not_inserted = False
					conductor_key = k

			#insert our default conductor if we haven't already
			if not_inserted:
				conductor_key = lc_key
				while( conductor_key in tree.keys() ):
					conductor_key -= 1
				tree[conductor_key] = default_equipment[ tree[line_key]['object'] + '_conductor' ]

			for phase in tree[line_key]['phases']:
				tree[lc_key]['conductor_' + phase] = tree[conductor_key]['name']

			continue

		#grab the conductor from the line configuration
		nearby_line_config = tree[nearby]['configuration']
		for k, v in tree.items():
			if nearby_line_config == v.get('name'):
				nearby_line_config = v
				break
		conductor = [v for k,v in v.items() if 'conductor' in k][0]

		#assign the empty line config this conductor
		for phase in tree[line_key].get('phases'):
			conductor_string = 'conductor_' + phase
			line_config_key = empty_line_configs[tree[line_key]['configuration']]
			tree[line_config_key][conductor_string] = conductor

	### CHECKS IF THERE EXISTS ANY MISMATCH BETWEEN LINE PHASES AND LINE-CONFIG CONDUCTOR PHASES
	namesToKeys = getNamesToKeys(tree)

	buggy_lines = dict() #maps buggy lines to their line config keys

	for k, line in tree.items():
		if 'line' in line.get('object',''):
			try:
				line_config_key = namesToKeys[line['configuration']]
			except KeyError:
				continue
			for phase in line.get('phases',''):
				if not tree[line_config_key].get('conductor_' + phase):
					buggy_lines[k] = line_config_key

	for line_key, line_config_key in buggy_lines.items():
		for attr in tree[line_config_key]:
			if 'conductor' in attr:
				existing_cond = attr
				break

		phases = tree[line_key].get('phases')
		for phase in phases:
			if not tree[line_config_key].get('conductor_'+phase):
				tree[line_config_key]['conductor_'+phase] = tree[line_config_key][existing_cond]
	return tree

def islandCount(tree, csv = True, csv_min_lines = 2):
	'''Walks the tree, counting the number of islands.
	If csv = True, returns a string in which each line represents one island, with the following information on each line (comma separated):
	island root key, num of objects in island, island root name, island root object type
	It will return an empty string if there are fewer than csv_min_lines islands.
	if csv = False, it returns an integer representing the number of islands.'''
	def count(root, toViset):
		size = 0
		toVisit = [root]
		while toVisit:
			current = toVisit.pop(0)
			if current not in toViset:
				continue
			size += 1
			toViset -= set( [current] )
			toVisit.extend( list( getRelatives(tree, current) ) )
		return size
	main_root = getRootKey(tree)
	toViset = set(tree.keys())
	main_size = count(main_root, toViset)
	island_roots = list(toViset)
	for unvisited in toViset:
		#remove items without phases
		if not tree[unvisited].get('phases'):
			island_roots.remove(unvisited)
		#remove items whose parents are in toViset
		parental = getRelatives(tree, unvisited, parent = True)
		if parental and parental in toViset:
			island_roots.remove(unvisited)
		elif parental:
			pass
	island_sizes = []
	for island_root in island_roots:
		island_sizes.append( count(island_root, toViset) )
	island_roots.insert(0, main_root)
	island_sizes.insert(0, main_size)
	if csv and len(island_roots) > csv_min_lines:
		island_root_names = [tree[k].get('name', 'name_not_found') for k in island_roots]
		island_root_types = [tree[k].get('object') for k in island_roots]
		island_info = list( zip(island_roots, island_sizes, island_root_names, island_root_types) )
		island_info = sorted( island_info, key = lambda x: int(x[1]) )
		island_info = [ '%s,%d,%s,%s' % tup for tup in island_info]
		return '\n'.join(island_info)
	elif csv:
		return ''
	else:
		return sum([ 1 if island_sizes[i] > 1 else 0 for i in range(len(island_roots)) ])

def phasingMismatchFix(tree, intermittent_drop_range=5):
	'''Fixes phase mismatch errors in the tree'''
	#for k,v in tree.iteritems():
	#	if v.get('name') == 'NODE150020':
	#		print v
	#		tree[k]['phases'] = 'B'
	#		break

	def _phaseFix(tree, root, toViset):
		current_node = root
		toVisit = [root]
		namesToKeys = getNamesToKeys(tree)
		while toVisit:
			current_node = toVisit.pop(0)
			if current_node not in toViset:
				continue
			toViset -= {current_node}
			try:
				tree[current_node]['phases']
			except KeyError:
				continue
			if tree[current_node]['object'] == 'transformer':
				conf_key = namesToKeys[ tree[current_node]['configuration'] ]
				add_an_s = True if tree[conf_key]['connect_type'] == 'SINGLE_PHASE_CENTER_TAPPED' else False
			else:
				add_an_s = False
			if add_an_s:
				tree[current_node]['phases'] += 'S'
			kids = getRelatives(tree, current_node)
			toVisit.extend(list(kids))
			for kid in kids:
				try:
					if tree[kid]['phases'] == '':
						tree[kid]['phases'] = tree[current_node]['phases']
				except KeyError:
					continue

				#if tree[kid]['object'] == 'transformer':
				#	kid_conf_key = namesToKeys[ tree[kid]['configuration'] ]
				#	connect_type = tree[kid_conf_key]['connect_type']
				#else:
				#	connect_type = None

				kid_phases = set(tree[kid].get('phases',''))
				current_phases = set(tree[current_node].get('phases',''))
				#in the case of the child of a SINGLE_PHASE_CENTER_TAPPED transformer
				if add_an_s and kid_phases != current_phases:
					tree[kid]['phases'] = tree[current_node]['phases']
					continue
				#in the general case
				if not (kid_phases <= current_phases):
					ancestry = [current_node]
					dropped = False
					# We check (intermittent_drop_range) generations above the current_node to see if the phase gained in kid_phases  was dropped within
					# that range. Ancestry is our listy boi of the nodes within (intermittent_drop_range) generations. If we decide that the phases were
					# intermittently dropped, then we will overwrite the phases where they were dropped (the nodes in ancestry).
					# If we decide that the phases were not intermittentely dropped then we set the kid_phases equal to the current_phases
					for j in range(intermittent_drop_range):
						try:
							ancestry.append( getRelatives(tree, ancestry[-1], parent=True) )
							parent_phases = set( tree[ancestry[-1]].get('phases','') )
						except TypeError:
							#TypeError for trying to use the empty list as a key in tree if ancestry is empty
							break
						if parent_phases == kid_phases:
							dropped = True
							for boi in ancestry:
								tree[boi]['phases'] = tree[kid].get('phases','')
					if not dropped:
						intersect = (kid_phases & current_phases)
						if intersect and intersect != set('S'):
							tree[kid]['phases'] = ''.join(intersect)
						else:
							tree[kid]['phases'] = tree[current_node]['phases']
						#fixes + checks for when we modify kid phases
						#if connect_type == 'WYE_WYE' and len(tree[kid]['phases']) == 1:
						#	tree[kid_conf_key]['connect_type'] = 'SINGLE_PHASE'
		return tree, toViset

	current_node = getRootKey(tree)
	toViset= set(tree.keys())
	tree, toViset = _phaseFix(tree, current_node, toViset)
	no_phase = []
	new_roots = list(toViset)
	for unvisited in toViset:
		#remove items without phases
		if not tree[unvisited].get('phases'):
			no_phase.append(unvisited)
			new_roots.remove(unvisited)
		#remove items whose parents are in toViset
		parental = getRelatives(tree, unvisited, parent = True)
		if parental and parental in toViset:
			new_roots.remove(unvisited)
	toViset -= set(no_phase)
	root_name_list = [ tree[key].get('name', 'name_not_found') for key in [current_node] + new_roots ]
	for root in new_roots:
		_phaseFix(tree, root, toViset)

	tree = missingPowerFix(tree)
	return tree

def missingPowerFix(tree):
	'''Fixes incorrect power ratings on single phase transformers'''
	from copy import deepcopy
	namesToKeys = getNamesToKeys(tree)
	incorrect_phases = dict() #maps configkey_phase to transformer keys

	for k,v in tree.items():
		if 'transformer' == v.get('object'):
			config_key = namesToKeys[ v['configuration'] ]
			for phase in v.get('phases'):
				if phase in 'NS':
					continue
				if not tree[config_key].get('power{}_rating'.format(phase)):
					key = str(config_key) + '_' + phase
					try:
						incorrect_phases[key].append(k)
					except KeyError:
						incorrect_phases[key] = [k]
	#create clones of existing transformer configs with the phase of the power rating swapped
	for config_key_phase, transformers in incorrect_phases.items():
		config_key = int(config_key_phase.split('_')[0])
		phase = config_key_phase.split('_')[1]
		clone_key = config_key
		while clone_key in tree.keys():
			clone_key += 1
		tree[clone_key] = deepcopy(tree[config_key])
		tree[clone_key]['name'] += '_{}'.format(phase)
		pr = None
		for attr, value in tree[clone_key].items():
			if attr != 'power_rating' and 'power' in attr and '_rating' in attr: #attr is 'power{}_rating'
				pr = attr
				break
			if attr == 'power_rating':
				pr = attr
		if not pr:
			continue
		tree[clone_key]['power{}_rating'.format(phase)] = tree[clone_key][pr]
		if pr != 'power_rating':
			del tree[clone_key][pr]
		for transformer in transformers:
			tree[transformer]['configuration'] = tree[clone_key]['name']
	return tree

def getRootKey(tree):
	'''Returns the key of the tree's root (the substation)'''
	for k,v in tree.items():
		if v.get('bustype'):
			if not getRelatives(tree, k, parent=True):
				return k

def getRelatives(tree, node_or_line, parent=False):
	'''Returns a list of keys of either parent or children of a given node name.'''
	listy = []

	if tree[node_or_line].get('object') in ['node', 'triplex_meter']:
		searchStr = 'to' if parent else 'from'
		node = node_or_line
		for k,v in tree.items():
			if v.get(searchStr) == tree[node].get('name'):
				listy.append(k)
				#if parent:
					#break
			elif not parent and v.get('parent') == tree[node].get('name'):
				listy.append(k)

	elif tree[node_or_line].get('object') in ['load', 'triplex_node', 'capacitor'] and parent:
		parent_name = tree[node_or_line].get('parent')
		if parent_name:
			for k,v in tree.items():
				if v.get('name') == parent_name:
					return k
		else:
			return []
	elif tree[node_or_line].get('object'):
		searchStr = 'from' if parent else 'to'
		line = node_or_line

		try:
			name = tree[line][searchStr]
		except KeyError:
			return []

		for k,v in tree.items():
			if v.get('name') == name:
				listy.append(k)
				break
	else:
		return []

	if parent and listy:
		if len(listy) > 1:
			warnings.warn('Object with multiple parents detected. Note that this is not fully supported.')
			return listy
		return listy[0]
	return listy

def getNamesToKeys(tree):
	'''Returns a dictionary of names to keys for the tree'''
	ntk = dict()
	for k,v in tree.items():
		if v.get('name'):
			ntk[v['name']] = k
	return ntk

def fixOrphanedLoads(tree):
	'''Fixes orphaned loads and lines in the tree'''
	namesToKeys = getNamesToKeys(tree)
	island_listy = islandCount(tree).split('\n')
	if not island_listy[0]:
		return tree
	island_listy = [line.split(',') for line in island_listy]
	size_1_del = 0
	size_2_del = 0
	for key, size, name, obj_type in island_listy:
		key = int(key)
		size = int(size)
		if size == 1:
			if obj_type != 'load':
				warnings.warn('size 1 island of type ' + obj_type)
				continue
			del tree[key]
			size_1_del += 1
			continue
		if size == 2:
			kiddo = getRelatives(tree, key)[0]
			if tree[kiddo]['object'] != 'load':
				warnings.warn('size 2 island with kid of type ' + tree[kiddo]['object'])
				continue
			if obj_type != 'node':
				warnings.warn('size 2 island with root of type ' + obj_type)
				continue
			del tree[key], tree[kiddo]
			size_2_del += 1
			continue
		if 'line' in obj_type:
			current_from = tree[key]['from']
			for P in 'ABC':
				next_from = current_from + '_' + P
				if namesToKeys.get(next_from):
					tree[key]['from'] = next_from
	warnings.warn('%d size 1 deletions and %d size 2 deletions' % ( size_1_del, size_2_del ))
	return tree

def rewriteStatePlaneToLatLon(tree, epsg = None):
	''' For the input tree, convert state plane coordinates to latLon.
	Note that we need the tree to come from convert(stdString, seqString, rescale=False). Please see the wiki at https://github.com/dpinney/omf/wiki/Other-~-Windmil-Data-Import#transforming-to-latitude-and-longitude-coordinates for the way to get the epsg code; if you don't choose an epsg, we locate the map near the geographical center of the USA.
	'''
	#TODO: double check the x/y order.
	for key in tree:
		if 'latitude' in tree[key] and 'longitude' in tree[key]:
			newCoords = geo.statePlaneToLatLon(tree[key]['longitude'], tree[key]['latitude'], epsg = epsg)
			tree[key]['latitude'], tree[key]['longitude'] = newCoords
	return tree

default_equipment = {
	'underground_line_conductor': {
		'name': "DG_1000ALTRXLPEJ15",
		'object': 'underground_line_conductor',
		'rating.summer.continuous': "725 A",
		'outer_diameter': "1.175 in",
		'conductor_gmr': "0.0395 ft",
		'conductor_diameter': "1.165 in",
		'conductor_resistance': "0.0141 ohm/kft",
		'neutral_gmr': "0.0132 ft",
		'neutral_resistance': "2.3057 ohm/kft",
		'neutral_diameter': "0.0254 in",
		'neutral_strands': "7",
		'shield_gmr': "0.00 ft"
	},
	'overhead_line_conductor': {
		'name': "1000_CU",
		'object': 'overhead_line_conductor',
		'geometric_mean_radius': "1.121921cm",
		'resistance': "0.042875Ohm/km"
	}
}

def _writeResultsCsv(testOutput, outName):
	with open(outName, 'w', newline='') as f:
		w = csv.DictWriter(f, testOutput[0].keys(), delimiter=',', lineterminator='\n')
		w.writeheader()
		w.writerows(testOutput)

def voltDistribution(pathToGlm, pathToVoltdumpCsv):
	with open(pathToGlm, 'r') as f:
		tree = omf.feeder.parse(pathToGlm)
	ntk = getNamesToKeys(tree)

	pu_voltage, na_count = [], 0
	with open(pathToVoltdumpCsv, 'r', newline='') as f:
		w = csv.reader(f)
		for i in range(2):
			next(w)
		for row in w:
			if len(row) != 7:
				continue

			# compute average voltage
			v_sum, cnt = 0, 0
			for i in range(3):
				real = float(row[i*2+1])
				imag = float(row[i*2+2])
				mag = abs(complex(real, imag))
				v_sum += mag
				cnt += 1 if mag else 0

			# determine nominal voltage
			key = ntk.get(row[0])
			if key and 'nominal_voltage' in tree[key]:
				nom = float(tree[key]['nominal_voltage'])
				pu_voltage.append(v_sum/cnt/nom if cnt else 0)
			else:
				na_count += 1
	return pu_voltage, na_count

def crappyhist(a, path, bins=50, width=80):
	# from @tammoippen on github
	a = np.asarray(a)
	h, b = np.histogram(a, bins)
	with open(path, 'w') as f:
		for i in range (0, bins):
			print('{:12.5f}  | {:{width}s} {}'.format(
					b[i],
					'#'*int(width*h[i]/np.amax(h)),
					h[i],
					width=width
			), file=f)

def split(fileToSplit, pathToDir=None):
	'''Splits a large STD into many smaller STDs'''
	from tempfile import mkdtemp
	if not pathToDir:
		pathToDir = mkdtemp()
		print("Split milFiles are in %s" % pathToDir)

	def extend(nodeSet, node):
		# add a node and all descendants to a set
		nodeSet.add(name_to_index[node])

		for kid in parent_to_kids.get(node, []):
			if kid in parent_to_kids.keys():
				extend(nodeSet, kid)
			else:
				nodeSet.add(name_to_index[kid])

	parent_to_kids = dict()
	name_to_index = dict()
	rows = list()
	noots = dict()

	with open(fileToSplit, 'r') as f:
		header = f.readline()
		for i, line in enumerate(f):
			rows.append(line)
			line = line.split(',')
			me, pa = line[0], line[3]
			name_to_index[me] = i
			if pa in parent_to_kids.keys():
				parent_to_kids[pa].append(me)
			else:
				parent_to_kids[pa] = [me]

	for noot in parent_to_kids["ROOT"]:
		members = set() # set of indices of interest
		extend(members, noot)

		if len(members) <= 1:
			continue

		with open(pJoin(pathToDir, noot.replace("/", "-") + '.std'), 'w') as f:
			f.write(header)
			for i, row in enumerate(rows):
				if i in members:
					f.write(row)

def _tests(
	keepFiles=True,
	wipeBefore=False,
	openPrefix=omf.omfDir + '/static/testFiles/',
	outPrefix=omf.omfDir + '/scratch/milToGridlabTests/',
	testFiles=[('Olin-Barre.std', 'Olin.seq'), ('Olin-Brown.std', 'Olin.seq')],
	testAttachments={'schedules.glm': '','climate.tmy2': None},
	voltdumpCsvName='{}_VD.csv',
	logAllWarnings=False
):
	if testAttachments.get('climate.tmy2') is None:
		with open(omf.omfDir + '/data/Climate/KY-LEXINGTON.tmy2') as f:
			testAttachments['climate.tmy2'] = f.read()

	from tempfile import mkdtemp
	''' Test convert every windmil feeder we have (in static/testFiles). '''
	# testFiles = [('INEC-RENOIR.std','INEC.seq'), ('INEC-GRAHAM.std','INEC.seq'),
	#   ('Olin-Barre.std','Olin.seq'), ('Olin-Brown.std','Olin.seq'),
	#   ('ABEC-FRANK.std','ABEC.seq'), ('ABEC-COLUMBIA.std','ABEC.seq'),('OMF_Norfork1.std', 'OMF_Norfork1.seq'),('UE yadkin tabernacle.std','UE yadkin tabernacle.seq')]
	# setlocale lives here to avoid changing it globally
	# locale.setlocale(locale.LC_ALL, 'en_US')

	# Variables for the testing.
	allResults = []
	# Create the work directory.
	if wipeBefore:
		try:
			# Wipe first.
			shutil.rmtree(outPrefix)
		except:
			# Couldn't delete, just keep going.
			pass
		finally:
			os.mkdir(outPrefix)
	else:
		try:
			os.mkdir(outPrefix)
		except:
			# Couldn't create.
			pass

	gridlab_workDir = mkdtemp() if voltdumpCsvName else None
	# Run all the tests.
	for stdString, seqString in testFiles:
		outFilePrefix = pJoin(outPrefix, stdString)[:-4]
		# Output data structure.
		currentResults = {}
		currentResults['circuit_name'] = stdString
		cur_start_time = time.time()
		try:
			# Convert the std+seq and write it out.
			with open(pJoin(openPrefix,stdString),'r') as stdFile, open(pJoin(openPrefix,seqString),'r') as seqFile:
				# Catch warnings too:
				with warnings.catch_warnings(record=True) as caught_warnings:
					warnings.simplefilter("always")
					outGlm = convert(stdFile.read(), seqFile.read())
				if logAllWarnings:
					currentResults['all_warnings'] = ';'.join(
						[str(x.message) for x in caught_warnings]
					)
				if voltdumpCsvName:
					voltdumpCsvName = voltdumpCsvName.format(
						stdString.replace('.std', '')
					)
					next_key = max(outGlm.keys()) + 1
					outGlm[next_key] = {
						'object': 'voltdump',
						'filename': voltdumpCsvName,
					}
			with open(outFilePrefix + ".glm", 'w') as outFile:
				outFile.seek(0)
				outFile.write(feeder.sortedWrite(outGlm))
				outFile.truncate()
				outFileStats = os.stat(outFilePrefix + ".glm")
			print('WROTE GLM FOR', stdString)
			# Write the size of the files as a indicator of how good the conversion was.
			inFileStats = os.stat(pJoin(openPrefix,stdString))
			inFileSize = inFileStats.st_size
			outFileSize = outFileStats.st_size
			percent = float(inFileSize)/float(outFileSize)
			currentResults['glm_size_as_perc_of_std'] = percent
			currentResults['std_size_mb'] = inFileSize / 1000.0 / 1000.0
			currentResults['number_of_load_obj'] = len([x for x in outGlm if outGlm[x].get('object','') in ['load','triplex_load','triplex_node']])
		except:
			print('FAILED CONVERTING', stdString)
			currentResults['glm_size_as_perc_of_std'] = 0.0
		try:
			# Draw the GLM.
			# But first make networkx cool it with the warnings.
			myGraph = feeder.treeToNxGraph(outGlm)
			x = feeder.latLonNxGraph(myGraph, neatoLayout=False)
			plt.savefig(outFilePrefix + ".png")
			# Clear memory since matplotlib likes to eat a lot.
			plt.close()
			del x
			gc.collect()
			print('DREW GLM OF', stdString)
			currentResults['drawing_success'] = True
		except:
			print('FAILED DRAWING', stdString)
			currentResults['drawing_success'] = False
		try:
			# Run powerflow on the GLM.
			currentResults['gridlabd_error_code'] = 'Processing'
			output = gridlabd.runInFilesystem(outGlm, attachments=testAttachments, keepFiles=False, workDir = gridlab_workDir)
			if voltdumpCsvName in output:
				del output[voltdumpCsvName]
			print(output)
			if output['stderr'].startswith('ERROR'):
				# Catch GridLAB-D's errors:
				currentResults['gridlabd_error_code'] = output['stderr'].replace('\n',' ')
				raise Exception
			# Dump powerflow results.
			with open(outFilePrefix + ".json", 'w') as outFile:
				outFile.seek(0)
				json.dump(output, outFile, indent=4)
				outFile.truncate()
			print('RAN GRIDLAB ON', stdString)
			currentResults['powerflow_success'] = True
		except Exception as e:
			print('POWERFLOW FAILED', stdString)
			currentResults['powerflow_success'] = False
		if voltdumpCsvName:
			try:
				# Analyze volt dump
				vpu, na_count = voltDistribution(
						outFilePrefix + ".glm",
						pJoin(gridlab_workDir, voltdumpCsvName)
				)
				currentResults['perc_voltage_in_range'] = "%0.3f" % (sum(1.0 for v in vpu if 0.8<=v<=1.2)/len(vpu))
				currentResults['missing_nominal_voltage_cnt'] = na_count
				crappyhist(
						vpu,
						outFilePrefix + '_voltage_hist.txt'
				)
				print('COMPLETED VOLT DUMP ANALYSIS ON', stdString)
			except Exception as e:
				currentResults['perc_voltage_in_range'] = "NaN"
				currentResults['missing_nominal_voltage_cnt'] = "NaN"
				print('VOLT DUMP ANALYSIS FAILED ON', stdString, type(e))
		# Write stats for all tests.
		currentResults['conversion_time_seconds'] = time.time() - cur_start_time
		_writeResultsCsv([currentResults], outFilePrefix + ".csv")
		# Append to multi-circuit output and continue.
		allResults.append(currentResults)
	if not keepFiles:
		shutil.rmtree(outPrefix)
	return allResults

if __name__ == "__main__":
	print(_tests())
