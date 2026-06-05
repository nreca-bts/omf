"""
Anonymize OMF distribution and transmission data by changing names, coordinates, load
assignments, and equipment details while preserving useful model structure.
"""

import json, math, random, datetime, os
from os.path import join as pJoin

# DISTRIBUTION FEEDER FUNCTIONS
def distPseudomizeNames(inFeeder):
	''' Replace all names in the inFeeder distribution system with pseudonames composed from the object type and a random ID. Return a key with name and ID pairs. '''
	#Works, tested,
	newNameKey = {}
	randomID = random.randint(0,100)
	# Create nameKey dictionary
	for key in inFeeder['tree']:
		if 'name' in inFeeder['tree'][key]:
			oldName = inFeeder['tree'][key]['name']
			newName = inFeeder['tree'][key]['object'] + str(randomID)
			newNameKey.update({oldName:newName})
			inFeeder['tree'][key]['name'] = newName
			randomID += 1
	# Replace names in tree
	for key in inFeeder['tree']:
		if 'parent' in inFeeder['tree'][key]:
			oldParent = inFeeder['tree'][key]['parent']  
			inFeeder['tree'][key]['parent'] = newNameKey[oldParent]
		if ('from' in inFeeder['tree'][key]) and ('to' in inFeeder['tree'][key]):
			oldFrom = inFeeder['tree'][key]['from']
			oldTo = inFeeder['tree'][key]['to']
			inFeeder['tree'][key]['from'] = newNameKey[oldFrom]
			inFeeder['tree'][key]['to'] = newNameKey[oldTo]
		#Line Configs	
		if inFeeder['tree'][key].get('object', '') == 'line_configuration':
			print("activated")
			for prop in inFeeder['tree'][key]:
				slist = {'conductor_N', 'conductor_A', 'conductor_B', 'conductor_C'}
				if prop in slist:
					print("has detected a conductor")
					oldCon = inFeeder['tree'][key][prop]
					inFeeder['tree'][key][prop] = newNameKey[oldCon]
		#Replace Spacing
		if 'spacing' in inFeeder['tree'][key]:
			oldspace = inFeeder['tree'][key]['spacing']
			inFeeder['tree'][key]['spacing'] = newNameKey[oldspace]
	#Replace configs general form
		if 'configuration' in inFeeder['tree'][key]:
			oldConfig = inFeeder['tree'][key]['configuration']
			inFeeder['tree'][key]['configuration'] = newNameKey[oldConfig]
	# Replace names in links
	for i in range(len(inFeeder['links'])):
		for key in inFeeder['links'][i]:
			if (key == 'source') or (key == 'target'):
				oldLink = inFeeder['links'][i][key]['name']
				inFeeder['links'][i][key]['name'] = newNameKey[oldLink]
	# Replace names in 'nodes'
	for i in range(len(inFeeder['nodes'])):
		for key in inFeeder['nodes'][i]:
			if key == 'name':
				oldNode = inFeeder['nodes'][i][key]
				inFeeder['nodes'][i][key] = newNameKey[oldNode]
	return newNameKey

def distRandomizeNames(inFeeder):
	''' Replace all names in the inFeeder distribution system with a random ID number. '''
	#Works, tested, even when addnoise used
	newNameKey = {}
	allKeys = list(range(len(inFeeder['tree'].keys())))
	random.shuffle(allKeys)
	# Create nameKey dictionary
	for count, key in enumerate(inFeeder['tree']):
		if 'name' in inFeeder['tree'][key]:
			oldName = inFeeder['tree'][key]['name']
			newName = str(allKeys[count])
			newNameKey.update({oldName:newName})
			inFeeder['tree'][key]['name'] = newName
	# Replace names in tree
	for key in inFeeder['tree']:
		if 'parent' in inFeeder['tree'][key]:
			oldParent = inFeeder['tree'][key]['parent']
			inFeeder['tree'][key]['parent'] = newNameKey[oldParent]
		if ('from' in inFeeder['tree'][key]) and ('to' in inFeeder['tree'][key]):
			oldFrom = inFeeder['tree'][key]['from']
			oldTo = inFeeder['tree'][key]['to']
			inFeeder['tree'][key]['from'] = newNameKey[oldFrom]
			inFeeder['tree'][key]['to'] = newNameKey[oldTo]
		#Line configs
		if inFeeder['tree'][key].get('object', '') == 'line_configuration':
			print("activated")
			for prop in inFeeder['tree'][key]:
				slist = {'conductor_N', 'conductor_A', 'conductor_B', 'conductor_C'}
				if prop in slist:
					print("has detected a conductor")
					oldCon = inFeeder['tree'][key][prop]
					inFeeder['tree'][key][prop] = newNameKey[oldCon]
	#Replace Spacing
		if 'spacing' in inFeeder['tree'][key]:
			oldspace = inFeeder['tree'][key]['spacing']
			inFeeder['tree'][key]['spacing'] = newNameKey[oldspace]
	#Replace configs general form
		if 'configuration' in inFeeder['tree'][key]:
			oldConfig = inFeeder['tree'][key]['configuration']
			inFeeder['tree'][key]['configuration'] = newNameKey[oldConfig]
	# Replace names in links
	for i in range(len(inFeeder['links'])):
		for key in inFeeder['links'][i]:
			if (key == 'source') or (key == 'target'):
				oldLink = inFeeder['links'][i][key]['name']
				inFeeder['links'][i][key]['name'] = newNameKey[oldLink]
	# Replace names in 'nodes'
	for i in range(len(inFeeder['nodes'])):
		for key in inFeeder['nodes'][i]:
			if key == 'name':
				oldNode = inFeeder['nodes'][i][key]
				inFeeder['nodes'][i][key] = newNameKey[oldNode]	
	
def distRandomizeLocations(inFeeder):
	''' Replace all objects' longitude and latitude positions in the inFeeder distribution system with random values. '''
	inFeeder['nodes'] = []
	inFeeder['links'] = []
	inFeeder['hiddenNodes'] = []
	inFeeder['hiddenLinks'] = []
	for key in inFeeder['tree']:
		if ('longitude' in inFeeder['tree'][key]) or ('latitude' in inFeeder['tree'][key]):
			inFeeder['tree'][key]['longitude'] = random.randint(0,1000)
			inFeeder['tree'][key]['latitude'] = random.randint(0,1000)

def distTranslateLocations(inFeeder, translationRight, translationUp, rotation):
	''' Move the position of all objects in the inFeeder distribution system by a horizontal translation and counter-clockwise rotation. '''
	''' Also rotate feeder around the average point of a feeder '''
	#Handle empty values
	if translationRight == '':
		translationRight = 0
	if translationUp == '':
		translationUp = 0
	if rotation == '':
		rotation = 0
	translationRight = float(translationRight)
	translationUp = float(translationUp)
	#convert from degreeas to radians
	rotation = math.radians(float(rotation))
	biggestLat, biggestLon, smallestLat, smallestLon = 0, 0, 0, 0
	inFeeder['nodes'] = []
	inFeeder['links'] = []
	inFeeder['hiddenNodes'] = []
	inFeeder['hiddenLinks'] = []
	
	for key in inFeeder['tree']:
		if ('longitude' in inFeeder['tree'][key]) or ('latitude' in inFeeder['tree'][key]):
			longitude = float(inFeeder['tree'][key]['longitude'])
			latitude = float(inFeeder['tree'][key]['latitude'])
			#Translate Feeder
			inFeeder['tree'][key]['longitude']=longitude+translationRight
			inFeeder['tree'][key]['latitude']=latitude+translationUp
	#Find composite midpoint to rotate around. It is the average point of the feeder's extrema
	#Find greatest Lat, least lat, great lon, least lon, then midpoint
	for key, value1 in inFeeder['tree'].items():
		if 'latitude' in value1:
			if value1['latitude']>biggestLat:
				biggestLat = value1['latitude']
			if value1['latitude'] < smallestLat:
				smallestLat = value1['latitude']
		if 'longitude' in value1:
			if value1['longitude']>biggestLon:
				biggestLon = value1['longitude']
			if value1['longitude'] < smallestLon:
				smallestLat = value1['longitude']
	midLon = (biggestLon + smallestLon) / 2
	midLat = (biggestLat + smallestLat) / 2
	#Rotate
	for key in inFeeder['tree']:
		if ('longitude' in inFeeder['tree'][key]) or ('latitude' in inFeeder['tree'][key]):
			#Rotate about composite origin (midpoint)
			#qx = ox + math.cos(angle) * (px - ox) - math.sin(angle) * (py - oy)
    		#qy = oy + math.sin(angle) * (px - ox) + math.cos(angle) * (py - oy)
			x = float(inFeeder['tree'][key]['longitude'])
			y = float(inFeeder['tree'][key]['latitude'])
			inFeeder['tree'][key]['longitude'] = (midLon) + (math.cos(rotation)*(x-midLon)) - ((y-midLat)*math.sin(rotation))
			inFeeder['tree'][key]['latitude'] = (midLat) + (math.sin(rotation)*(x-midLon)) + ((y-midLat)* math.cos(rotation))

			

def distAddNoise(inFeeder, noisePerc):
	''' Add random noise to properties with numeric values for all objects in the inFeeder distribution system based on a noisePerc magnitude. '''
	#Works with certain parameters mentioned in brackets below. Others need to check so they don't break machine
	noisePerc = float(noisePerc)
	distModifyTriplexLengths(inFeeder)
	distModifyConductorLengths(inFeeder)
	for key in inFeeder['tree']:
		for prop in inFeeder['tree'][key]:
			# Scramble valid properties
			if prop in ['latitude', 'longitude','climate', 'ambient_temperature']:
				# print(prop)
				val = inFeeder['tree'][key][prop]
				try:
					parseVal = float(val)
					randNoise = random.uniform(-noisePerc, noisePerc)/100
					randVal = parseVal + randNoise*parseVal
					inFeeder['tree'][key][prop] = str(randVal)
				except ValueError:
					try:
						compVal = complex(val)
						realVal = float(compVal.real)
						imagVal = float(compVal.imag)
						randNoise = random.uniform(-noisePerc, noisePerc)/100
						randReal = realVal + randNoise*realVal
						randImag = imagVal + randNoise*imagVal
						randVal = complex(randReal, randImag)
						inFeeder['tree'][key][prop] = str(randVal)
					except ValueError:
						continue
					continue

def distShuffleLoads(inFeeder, shufPerc):
	''' Shuffle the parent properties between all load objects in the inFeeder distribution system. '''
	#Works, tested. even when add noise used
	shufPerc = float(shufPerc)
	houseParents = []
	zipParents = []
	tlParents = []
	# tnParents = []
	for key in inFeeder['tree']:
		if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'house'):
			houseParents.append(inFeeder['tree'][key]['parent'])
		if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'ZIPload'):
			zipParents.append(inFeeder['tree'][key]['parent'])
		if ('from' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'triplex_line'):
			tlParents.append(inFeeder['tree'][key].get('from'))
		# if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'triplex_node'):
		# 	tnParents.append(inFeeder['tree'][key]['parent'])
		#shouldnt work for triplex lines, only work on triplex nodes, house, ziploads, triplex loads, and loads
		#EDIT works on triplex lines because it looks for the froms and tos, which in fact are triplex_nodes
	random.shuffle(houseParents)
	random.shuffle(zipParents)
	random.shuffle(tlParents)
	# random.shuffle(tnParents)
	houseIdx = 0
	zipIdx = 0
	tlIdx = 0
	# tnIdx = 0
	#Switch out parents in feeder with the first parent from the list. If same parent as before, go to second
	#Then pop out parent from list. List is shuffled to begin with so no need to randomly select from list
	#If an index error (because all selections in list removed), ignore and continue
	#Works same way for each type of object
	for key in inFeeder['tree']:
		if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'house'):
			if random.randint(0,100) <= shufPerc:
				houseIdx = 0
				if inFeeder['tree'][key]['parent'] != houseParents[houseIdx]:
					try:
						houseIdx = 0
						inFeeder['tree'][key]['parent'] = houseParents[houseIdx]
						houseParents.pop(houseIdx)
					except IndexError:
						continue
				elif inFeeder['tree'][key]['parent'] == houseParents[houseIdx]:
					try:
						houseIdx = houseIdx + 1
						inFeeder['tree'][key]['parent'] = houseParents[houseIdx]
						houseParents.pop(houseIdx)
					except IndexError:
						continue
		if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'ZIPload'):
			zipIdx = 0
			if random.randint(0,100) <= shufPerc:
				zipIdx = 0
				if inFeeder['tree'][key]['parent'] != zipParents[zipIdx]:
			
					try:
						zipIdx = 0
						inFeeder['tree'][key]['parent'] = zipParents[zipIdx]
						#print(zipParents)
						zipParents.pop(zipIdx)

					except IndexError:
						continue
				elif (inFeeder['tree'][key]['parent']) == zipParents[zipIdx]:
				
					try:
						zipIdx = zipIdx + 1
						inFeeder['tree'][key]['parent'] = zipParents[zipIdx]
						zipParents.pop(zipIdx)
						
					except IndexError:
						continue
		if ('from' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'triplex_line'):
			if random.randint(0,100) <= shufPerc:
				tlIdx = 0
				if (inFeeder['tree'][key]['from']) != (tlParents[tlIdx]):
					tlIdx = 0

					inFeeder['tree'][key]['from'] = tlParents[tlIdx]
					
					tlParents.pop(tlIdx)
				elif (inFeeder['tree'][key]['from']) == (tlParents[tlIdx]):
					tlIdx = tlIdx + 1
					inFeeder['tree'][key]['from'] = tlParents[tlIdx]
					tlParents.pop(tlIdx)
		# if ('parent' in inFeeder['tree'][key]) and (inFeeder['tree'][key].get('object') == 'triplex_node'):
		# 	if random.randint(0,100) < shufPerc:
		# 		inFeeder['tree'][key]['parent'] = tnParents[tnIdx]
		# 		tnIdx += 1

def distModifyTriplexLengths(inFeeder):
	''' Modifies triplex line length and diameter properties while preserving original impedance in the inFeeder distribution system. '''
	print("distModifyTriplexLengths activated!")
	tLookup = {}
	for key in inFeeder['tree']:
		tDict = {}
		if inFeeder['tree'][key].get('object') == 'triplex_line':
			tDict = {
				inFeeder['tree'][key].get('name'): {
					'length': inFeeder['tree'][key].get('length'),
					'configuration': inFeeder['tree'][key].get('configuration')
				}
			}
			tLookup.update(tDict)
	for key in inFeeder['tree']:
		if inFeeder['tree'][key].get('object') == 'triplex_line_configuration':
			for tLine in tLookup:
				if tLookup[tLine].get('configuration') == inFeeder['tree'][key].get('name'):
					tLookup[tLine].update(diameter=inFeeder['tree'][key].get('diameter'))
					tLookup[tLine].update(conductor_1=inFeeder['tree'][key].get('conductor_1'))
					tLookup[tLine].update(conductor_2=inFeeder['tree'][key].get('conductor_2'))
					tLookup[tLine].update(conductor_N=inFeeder['tree'][key].get('conductor_N'))
	for key in inFeeder['tree']:
		if inFeeder['tree'][key].get('object') == 'triplex_line_conductor':
			for tLine in tLookup:
				if (tLookup[tLine].get('conductor_1') == inFeeder['tree'][key].get('name')) or (tLookup[tLine].get('conductor_2') == inFeeder['tree'][key].get('name')) or (tLookup[tLine].get('conductor_N') == inFeeder['tree'][key].get('name')):
					tLookup[tLine].update(resistance=inFeeder['tree'][key].get('resistance'))
	for tLine in tLookup:
		resistivity = ( float(tLookup[tLine].get('resistance'))*math.pi*(float(tLookup[tLine].get('diameter'))/2.0)**2 ) / float(tLookup[tLine].get('length'))
		tLookup[tLine]['length'] = random.uniform( float(tLookup[tLine].get('length'))-float(tLookup[tLine].get('length')), float(tLookup[tLine].get('length'))+float(tLookup[tLine].get('length')) )
		tLookup[tLine]['diameter'] = random.uniform( (float(tLookup[tLine].get('diameter'))-float(tLookup[tLine].get('diameter')))*1000, (float(tLookup[tLine].get('diameter'))+float(tLookup[tLine].get('diameter')))*1000 ) / 1000.0
		tLookup[tLine]['resistance'] = (resistivity*float(tLookup[tLine].get('length'))) / (math.pi*(float(tLookup[tLine].get('diameter'))/2.0)**2)
		for key in inFeeder['tree']:
			if inFeeder['tree'][key].get('name') == tLine:
				inFeeder['tree'][key]['length'] = tLookup[tLine].get('length')
			if inFeeder['tree'][key].get('name') == tLookup[tLine].get('configuration'):
				inFeeder['tree'][key]['diameter'] = tLookup[tLine].get('diameter')
			if (inFeeder['tree'][key].get('name') == tLookup[tLine].get('conductor_1')) or (inFeeder['tree'][key].get('name') == tLookup[tLine].get('conductor_2')) or (inFeeder['tree'][key].get('name') == tLookup[tLine].get('conductor_N')):
				inFeeder['tree'][key]['resistance'] = tLookup[tLine].get('resistance')

def distModifyConductorLengths(inFeeder):
	''' Modifies conductor length and diameter properties while preserving original impedance in the inFeeder distribution system. '''
	#Works totally fine
	uLookup = {}
	oLookup = {}
	for key in inFeeder['tree']:
		uDict = {}
		oDict = {}
		if inFeeder['tree'][key].get('object') == 'underground_line':
			uDict = {
				inFeeder['tree'][key].get('name'): {
					'length': inFeeder['tree'][key].get('length'),
					'configuration': inFeeder['tree'][key].get('configuration')
				}	
			}
			uLookup.update(uDict)
		elif inFeeder['tree'][key].get('object') == 'overhead_line':
			oDict = {
				inFeeder['tree'][key].get('name'): {
					'length': inFeeder['tree'][key].get('length'), 
					'configuration': inFeeder['tree'][key].get('configuration')
				}	
			}
			oLookup.update(oDict)
	for key in inFeeder['tree']:
		if inFeeder['tree'][key].get('object') == 'line_configuration':
			for uLine in uLookup:
				if uLookup[uLine].get('configuration') == inFeeder['tree'][key].get('name'):
					uLookup[uLine].update(conductor_N=inFeeder['tree'][key].get('conductor_N'))
					uLookup[uLine].update(conductor_A=inFeeder['tree'][key].get('conductor_A'))
					uLookup[uLine].update(conductor_B=inFeeder['tree'][key].get('conductor_B'))
					uLookup[uLine].update(conductor_C=inFeeder['tree'][key].get('conductor_C'))
			for oLine in oLookup:
				if oLookup[oLine].get('configuration') == inFeeder['tree'][key].get('name'):
					oLookup[oLine].update(conductor_N=inFeeder['tree'][key].get('conductor_N'))
					oLookup[oLine].update(conductor_A=inFeeder['tree'][key].get('conductor_A'))
					oLookup[oLine].update(conductor_B=inFeeder['tree'][key].get('conductor_B'))
					oLookup[oLine].update(conductor_C=inFeeder['tree'][key].get('conductor_C'))
	for key in inFeeder['tree']:
		if inFeeder['tree'][key].get('object') == 'underground_line_conductor':
			for uLine in uLookup:
				if (uLookup[uLine].get('conductor_N') == inFeeder['tree'][key].get('name')) or (uLookup[uLine].get('conductor_A') == inFeeder['tree'][key].get('name')) or (uLookup[uLine].get('conductor_B') == inFeeder['tree'][key].get('name')) or (uLookup[uLine].get('conductor_C') == inFeeder['tree'][key].get('name')):
					uLookup[uLine].update(conductor_resistance=inFeeder['tree'][key].get('conductor_resistance'))
					uLookup[uLine].update(conductor_diameter=inFeeder['tree'][key].get('conductor_diameter'))

		elif inFeeder['tree'][key].get('object') == 'overhead_line_conductor':
			for oLine in oLookup:
				if (oLookup[oLine].get('conductor_N') == inFeeder['tree'][key].get('name')) or (oLookup[oLine].get('conductor_A') == inFeeder['tree'][key].get('name')) or (oLookup[oLine].get('conductor_B') == inFeeder['tree'][key].get('name')) or (oLookup[oLine].get('conductor_C') == inFeeder['tree'][key].get('name')):
					oLookup[oLine].update(resistance=inFeeder['tree'][key].get('resistance'))
					oLookup[oLine].update(geometric_mean_radius=inFeeder['tree'][key].get('geometric_mean_radius'))
	
	for uLine in uLookup:
		resistivity = ( float(uLookup[uLine].get('conductor_resistance'))*math.pi*(float(uLookup[uLine].get('conductor_diameter'))/2.0)**2 ) / float(uLookup[uLine].get('length'))
		uLookup[uLine]['length'] = random.uniform( float(uLookup[uLine].get('length'))-float(uLookup[uLine].get('length')), float(uLookup[uLine].get('length'))+float(uLookup[uLine].get('length')) )
		uLookup[uLine]['conductor_diameter'] = random.uniform( (float(uLookup[uLine].get('conductor_diameter'))-float(uLookup[uLine].get('conductor_diameter')))*1000, (float(uLookup[uLine].get('conductor_diameter'))+float(uLookup[uLine].get('conductor_diameter')))*1000 ) / 1000.0
		uLookup[uLine]['conductor_resistance'] = (resistivity*float(uLookup[uLine].get('length'))) / (math.pi*(float(uLookup[uLine].get('conductor_diameter'))/2.0)**2)
		for key in inFeeder['tree']:
			if inFeeder['tree'][key].get('name') == uLine:
				inFeeder['tree'][key]['length'] = uLookup[uLine].get('length')
			if (inFeeder['tree'][key].get('name') == uLookup[uLine].get('conductor_N')) or (inFeeder['tree'][key].get('name') == uLookup[uLine].get('conductor_A')) or (inFeeder['tree'][key].get('name') == uLookup[uLine].get('conductor_B')) or (inFeeder['tree'][key].get('name') == uLookup[uLine].get('conductor_C')):
				inFeeder['tree'][key]['conductor_resistance'] = uLookup[uLine].get('conductor_resistance')
				inFeeder['tree'][key]['conductor_diameter'] = uLookup[uLine].get('conductor_diameter')
	for oLine in oLookup:
		resistivity = ( float(oLookup[oLine].get('resistance'))*math.pi*float(oLookup[oLine].get('geometric_mean_radius'))**2 ) / float(oLookup[oLine].get('length'))
		oLookup[oLine]['length'] = random.uniform( float(oLookup[oLine].get('length'))-float(oLookup[oLine].get('length')), float(oLookup[oLine].get('length'))+float(oLookup[oLine].get('length')) )
		oLookup[oLine]['geometric_mean_radius'] = random.uniform( (float(oLookup[oLine].get('geometric_mean_radius'))-float(oLookup[oLine].get('geometric_mean_radius')))*1000, (float(oLookup[oLine].get('geometric_mean_radius'))+float(oLookup[oLine].get('geometric_mean_radius')))*1000 ) / 1000.0
		oLookup[oLine]['resistance'] = (resistivity*float(oLookup[oLine].get('length'))) / (math.pi*float(oLookup[oLine].get('geometric_mean_radius'))**2)
		for key in inFeeder['tree']:
			if inFeeder['tree'][key].get('name') == oLine:
				inFeeder['tree'][key]['length'] = oLookup[oLine].get('length')
			if (inFeeder['tree'][key].get('name') == oLookup[oLine].get('conductor_N')) or (inFeeder['tree'][key].get('name') == oLookup[oLine].get('conductor_A')) or (inFeeder['tree'][key].get('name') == oLookup[oLine].get('conductor_B')) or (inFeeder['tree'][key].get('name') == oLookup[oLine].get('conductor_C')):
				inFeeder['tree'][key]['resistance'] = oLookup[oLine].get('resistance')
				inFeeder['tree'][key]['geometric_mean_radius'] = oLookup[oLine].get('geometric_mean_radius')

def distSmoothLoads(inFeeder):
	''' Reduce the resolution of load shapes by taking all sub-hourly load dispatch data in the inFeeder distribution system and aggregating to the hour level. ''' 
	#FIX THIS FIX THIS FIX THIS. Ask david for help. subScadacalibrate1.player? thing not foundon current data atructure
	agList = []
	outList = []
	scadaFile = inFeeder['attachments']['subScadaCalibrated1.player']
	scadaLines = scadaFile.split('\n')
	scadaPairs = [x.split(',') for x in scadaLines] # [[ts,val],[ts,val],[ts,val],...]
	for pair in scadaPairs:
		s = pair[0]
		s = s[:19]
		try:
			timestamp = datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
		except:
			pass # print 'BAD DATAPOINT:', s
		agAmount = 0
		agHour = timestamp.hour
		if (timestamp.minute == 0) and (timestamp.second == 0) and (timestamp.hour == agHour):
			year = str(timestamp.year)
			month = str(timestamp.month)
			day = str(timestamp.day)
			if len(month) == 1:
				month = '0' + month
			if len(day) == 1:
				day = '0' + day
			agDate = year + '-' + month + '-' + day
			try:
				agAmount = float(pair[1])
			except:
				continue
			agList.append([agDate, agHour, agAmount])
	agZip = list(zip(*agList))
	for i in range(len(agZip[0])):
		date = str(agZip[0][i])
		hr = str(agZip[1][i])
		val = str(agZip[2][i])
		if len(hr) == 1:
			hr = '0' + hr
		scadaPoint = date + ' ' + hr + ':00:00 PST,' + val
		outList.append(scadaPoint)
	scadaAttach = '\n'.join(outList)
	inFeeder['attachments']['subScadaCalibrated1.player'] = scadaAttach

# TRANSMISSION NETWORK FUNCTIONS 
def tranPseudomizeNames(inNetwork):
	#Works totally fine
	''' Replace all names in the inNetwork transmission system with pseudonames composed of the object type and a random ID. Return a key with name and ID pairs. '''
	newBusKey = {}
	randomID = random.randint(0,100)
	# Create busKey dictionary
	for i in list(inNetwork['bus'].keys()):
		if 'bus_i' in inNetwork['bus'][i]:
			oldBus = inNetwork['bus'][i]['bus_i']
			newBus = str(randomID)
			newBusKey.update({oldBus:newBus})
			inNetwork['bus'][i]['bus_i'] = newBus
			inNetwork['bus'][newBus] = inNetwork['bus'].pop(i)
			randomID += 1
# Replace busNames in generators
	for i in inNetwork['gen']:
		if 'bus' in inNetwork['gen'][i]:
			oldBus = inNetwork['gen'][i]['bus']
			inNetwork['gen'][i]['bus'] = newBusKey[oldBus]
# # Replace busNames in branches
	for i in inNetwork['branch']:
		if 'fbus' in inNetwork['branch'][i]:
			oldFrom = inNetwork['branch'][i]['fbus']
			inNetwork['branch'][i]['fbus'] = newBusKey[oldFrom]
		if 'tbus' in inNetwork['branch'][i]:
			oldTo = inNetwork['branch'][i]['tbus']
			inNetwork['branch'][i]['tbus'] = newBusKey[oldTo]
	return newBusKey
def tranRandomizeNames(inNetwork):
	#Works Totally fine
	''' Replace all names in the inNetwork transmission system with pseudonames composed of the object type and a random ID. '''
	'''pretty sure this makes no sense at all, current data structure has no object types'''
	newBusKey = {}
	randomID = random.randint(0,100)
	# Create busKey dictionary
	for i in list(inNetwork['bus'].keys()):
		if 'bus_i' in inNetwork['bus'][i]:
			oldBus = inNetwork['bus'][i]['bus_i']
			newBus = str(randomID)
			newBusKey.update({oldBus:newBus})
			inNetwork['bus'][i]['bus_i'] = newBus
			inNetwork['bus'][newBus] = inNetwork['bus'].pop(i)
			randomID += 1
# Replace busNames in generators
	for i in inNetwork['gen']:
		if 'bus' in inNetwork['gen'][i]:
			oldBus = inNetwork['gen'][i]['bus']
			inNetwork['gen'][i]['bus'] = newBusKey[oldBus]
# # Replace busNames in branches
	for i in inNetwork['branch']:
		if 'fbus' in inNetwork['branch'][i]:
			oldFrom = inNetwork['branch'][i]['fbus']
			inNetwork['branch'][i]['fbus'] = newBusKey[oldFrom]
		if 'tbus' in inNetwork['branch'][i]:
			oldTo = inNetwork['branch'][i]['tbus']
			inNetwork['branch'][i]['tbus'] = newBusKey[oldTo]

def tranRandomizeLocations(inNetwork):
	#FIXED, tested
	''' Replace all objects' longitude and latitude positions in the inNetwork transmission system with random values. '''
	'''make sure dont need to replace lat and longs of gens and branches'''
	# inNetwork['bus'] = []
	# inNetwork['gen'] = []
	# inNetwork['branch'] = []
	for i in inNetwork['bus']:
		if 'longitude' in inNetwork['bus'][i]:
			inNetwork['bus'][i]['longitude'] = random.randint(0,1000)
		if 'latitude' in inNetwork['bus'][i]:
			inNetwork['bus'][i]['latitude'] = random.randint(0,1000)

def tranTranslateLocations(inNetwork, translationRight, translationUp, rotation):
	#Fixed, tested
	''' Move the position of all objects in the inNetwork transmission system by a horizontal translation and counter-clockwise rotation. '''
	# inNetwork['bus'] = []
	# inNetwork['gen'] = []
	# inNetwork['branch'] = []
	if translationRight == '':
		translationRight = 0
	if translationUp == '':
		translationUp = 0
	if rotation == '':
		rotation = 0
	translationRight = float(translationRight)
	translationUp = float(translationUp)
	#convert from degreeas to radians
	rotation = math.radians(float(rotation))
	biggestLat, biggestLon, smallestLat, smallestLon = 0, 0, 0, 0

	#Translate First
	for i in inNetwork['bus']:
		if ('longitude' in inNetwork['bus'][i]) or ('latitude' in inNetwork['bus'][i]):
			longitude = float(inNetwork['bus'][i]['longitude'])
			latitude = float(inNetwork['bus'][i]['latitude'])
			#Translate Feeder
			inNetwork['bus'][i]['longitude']=longitude+translationRight
			inNetwork['bus'][i]['latitude']=latitude+translationUp
	#Find composite midpoint to rotate around. It is the average point of the feeder's extrema
	#Find greatest Lat, least lat, great lon, least lon, then midpoint
	for key, value1 in inNetwork['bus'].items():
		if 'latitude' in value1:
			if value1['latitude']>biggestLat:
				biggestLat = value1['latitude']
			if value1['latitude'] < smallestLat:
				smallestLat = value1['latitude']
		if 'longitude' in value1:
			if value1['longitude']>biggestLon:
				biggestLon = value1['longitude']
			if value1['longitude'] < smallestLon:
				smallestLat = value1['longitude']
	midLon = (biggestLon + smallestLon) / 2
	midLat = (biggestLat + smallestLat) / 2
	#Rotate
	for i in inNetwork['bus']:
		if ('longitude' in inNetwork['bus'][i]) or ('latitude' in inNetwork['bus'][i]):
			#Rotate about composite origin (midpoint)
			#qx = ox + math.cos(angle) * (px - ox) - math.sin(angle) * (py - oy)
    		#qy = oy + math.sin(angle) * (px - ox) + math.cos(angle) * (py - oy)
			x = float(inNetwork['bus'][i]['longitude'])
			y = float(inNetwork['bus'][i]['latitude'])
			inNetwork['bus'][i]['longitude'] = (midLon) + (math.cos(rotation)*(x-midLon)) - ((y-midLat)*math.sin(rotation))
			inNetwork['bus'][i]['latitude'] = (midLat) + (math.sin(rotation)*(x-midLon)) + ((y-midLat)* math.cos(rotation))

def tranAddNoise(inNetwork, noisePerc):
	''' Add random noise to properties with numeric values for all objects in the inNetwork transmission system based on a noisePerc magnitude. '''
	#Fixed, but breaks transmission when it scrambles numbers enough to break MatPower
	noisePerc = float(noisePerc)
	for array in inNetwork:
		if (array == 'bus') or (array == 'gen') or (array == 'branch'):
			arrayId = 0
			for i in inNetwork[array]:
				for key in inNetwork[array][i].keys():
					if ('bus' not in key) and ('status' not in key) and ('type' not in key):
						# print key, inNetwork[array][i][key]
						val = inNetwork[array][i][key]
						try:
							parseVal = float(val)
							randNoise = random.uniform(-noisePerc, noisePerc)/100
							randVal = parseVal + parseVal * randNoise 
							inNetwork[array][i][key] = str(randVal)
						except ValueError:
							print('error')
							continue
			arrayId += 1

def tranShuffleLoadsAndGens(inNetwork, shufPerc):
	#Fixed, tested
	''' Shuffle the parent properties between all load and gen objects in the inNetwork transmission system. '''
	shufPerc = float(shufPerc)
	# Shuffle Qd and Pd
	qParents = []
	pParents = []
	busId = 0
	for i in inNetwork['bus'].keys():
		if 'Qd' in inNetwork['bus'][i].keys():
			qParents.append(inNetwork['bus'][i]['Qd'])
		if 'Pd' in inNetwork['bus'][i].keys():
			pParents.append(inNetwork['bus'][i]['Pd'])
		busId += 1
	random.shuffle(qParents)
	random.shuffle(pParents)
	qIdx = 0
	pIdx = 0
	busId = 0
	for i in inNetwork['bus'].keys():
		if random.randint(0,100) < shufPerc:
			if 'Qd' in inNetwork['bus'][i].keys():
				inNetwork['bus'][i]['Qd'] = qParents[qIdx]
				qIdx += 1
			if 'Pd' in inNetwork['bus'][i].keys():
				inNetwork['bus'][i]['Pd'] = pParents[pIdx]
				pIdx += 1
		busId += 1
	# Shuffle Generators
	genParents = []
	genId = 0
	for i in inNetwork['gen'].keys():
		if 'bus' in inNetwork['gen'][i].keys():
			genParents.append(inNetwork['gen'][i]['bus'])
		genId += 1
	random.shuffle(genParents)
	genId = 0
	genIdx = 0
	for i in inNetwork['gen'].keys():
			if 'bus' in inNetwork['gen'][i].keys():
				if random.randint(0,100) < shufPerc:
					inNetwork['gen'][i]['bus'] = genParents[genIdx]
					genIdx += 1
			genId += 1


def _tests():
	'''TODO: Possible issues with distSmoothLoads()?'''
	import tempfile
	temp_dir = tempfile.mkdtemp()
	print('Working in {}'.format(temp_dir))
	operations = [
		('Simple Market System AnonTest.omd', 'simpleMarket_distPseudomizeNames.omd', distPseudomizeNames), # Works
		('Simple Market System AnonTest.omd', 'simpleMarket_distRandomizeNames.omd', distRandomizeNames), # Works
		('Simple Market System AnonTest.omd', 'simpleMarket_distRandomizeLocations.omd', distRandomizeLocations), # Works
		('Simple Market System AnonTest.omd', 'simpleMarket_distTranslateLocations.omd', lambda inFeeder: distTranslateLocations(inFeeder, translationRight=20, translationUp=20, rotation=20)), # Works
		('Simple Market System AnonTest.omd', 'simpleMarket_distAddNoise.omd', lambda inFeeder: distAddNoise(inFeeder, noisePerc=50)), # This only affects longitude and latitude because they are the only non-string numeric properties
		('Simple Market System AnonTest.omd', 'simpleMarket_distShuffleLoads.omd', lambda inFeeder: distShuffleLoads(inFeeder, shufPerc=100)), # It changes the "parent" property, so I guess it's working
		('Simple Market System AnonTest.omd', 'simpleMarket_distModifyTriplexLengths.omd', distModifyTriplexLengths), # Changes lengths of triplex_lines
		('Olin Barre GH.omd', 'olinBarreGH_distModifyConductorLengths.omd', distModifyConductorLengths), # Changes resistance and geometric_mean_radius of line_conductor objects
		#('Simple Market System AnonTest.omd', 'simpleMarket_distSmoothLoads.omd', distSmoothLoads), # Not working. Requires a calibrated feeder (see omf.calibrate)
		('SimpleNetwork.json', '118_tranPseudomizeNames.omt', tranPseudomizeNames), # Works
		('case9.omt', '118_tranRandomizeNames.omt', tranRandomizeNames), # Works
		('SimpleNetwork.json', '118_tranRandomizeLocations.omt', tranRandomizeLocations), # Works
		('case9.omt', 'case9_transTranslate.omt', lambda inNetwork: tranTranslateLocations(inNetwork, translationRight=100, translationUp=100, rotation=45)), # Works
		('SimpleNetwork.json', 'case9_transAddNoise.omt', lambda inNetwork: tranAddNoise(inNetwork, noisePerc=100)), # Works. Changes almost every property
		('SimpleNetwork.json', '118_tranShuffleLoadsAndGens.omt', lambda inNetwork: tranShuffleLoadsAndGens(inNetwork, shufPerc=100)) # Only changes the 'Pd' property of some objects
	]
	omfDir = os.path.abspath(os.path.dirname(__file__))
	for o in operations:
		input_filename = o[0]
		if input_filename.split('.')[-1] == 'omd':
			input_filepath = os.path.join(omfDir, 'static', 'publicFeeders', input_filename)
		else:
			input_filepath = os.path.join(omfDir, 'static', input_filename)
		with open(input_filepath) as f:
			feeder_or_network = json.load(f)
		o[2](feeder_or_network)
		#output = o[2](inFeeder)
		#print(output)
		output_filepath = os.path.join(temp_dir, o[1])
		with open(output_filepath, 'w') as f:
			json.dump(feeder_or_network, f, indent=4)


if __name__ == '__main__':
	_tests()