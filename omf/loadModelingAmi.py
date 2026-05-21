''' Attach loadshapes from an AMI data file to a OMF distribution model. '''

import csv, json, os, shutil, datetime
from os.path import join as pJoin
from os.path import basename
import omf
from omf import feeder


def amiImport(filepath):
	'''Take in a CSV, return a [{...},{...},...] database of the data.'''
	amiData = []
	with open(filepath, newline='') as inFile:
		dictReader = csv.DictReader(inFile)
		for row in dictReader:
			amiData.append(row)
	return amiData

def createPlayerFile(amiData, meterName, phase, outFileName):
	''' Put a subsection of an amiData object in to a format ready for writing to a csv.'''
	lines = []
	for row in amiData:
		if row.get('meterName','')==meterName and row.get('phase','')==phase:
			newLine = row.get('readDateTime','') + ',' + row.get('wh','') + '+' + row.get('var','') + 'j'
			lines.append(newLine)
	lines.sort(key=lambda x: x[0]) # Sort by datetime.
	with open(outFileName,'w') as outFile:
		outFile.write('\n'.join(lines))

def writeNewGlmAndPlayers(omdPath, amiPath, outputDir):
	''' Take a glm and an AMI data set, and create a new GLM and set of players that combine them. '''
	# Pull in the main data objects.
	with open(omdPath,'r') as jsonFile:
		omdObj = json.load(jsonFile)
	omdName = basename(omdPath)
	feederObj = omdObj['tree']
	amiData = amiImport(amiPath)
	# Make the output directory.
	if not os.path.isdir(outputDir):
		os.mkdir(outputDir)
	# Attach the player class to feeder if needed.
	omfTypes = set([feederObj[k].get('omftype','') for k in feederObj])
	if 'class player' not in omfTypes:
		newKey = feeder.getMaxKey(feederObj)
		feederObj[newKey + 1] = {'omftype':'class player','argument':'{double value;}'}
	# All meter names we have in the AMI data set.
	meterNames = set([x.get('meterName','') for x in amiData])
	# Attach all the players.
	for key in list(feederObj.keys()):
		objName = feederObj[key].get('name','')
		dataPhases = set([x.get('phase','') for x in amiData if x.get('meterName','') == objName])
		# Handle primary system loads.
		if feederObj[key].get('object','') == 'load' and objName in meterNames:
			for phase in dataPhases:
				# Write the player file:
				createPlayerFile(amiData, objName, phase, outputDir + '/player_' + objName + '_' + phase + '.csv')
				# Put the object in the GLM:
				newKey = feeder.getMaxKey(feederObj)
				feederObj[newKey + 1] = {'object':'player', 'property':'constant_power_' + phase, 'file':'player_' + objName + '_' + phase +'.csv', 'parent':objName}
		# Handle secondary system loads.
		elif feederObj[key].get('object','') == 'triplex_node' and objName in meterNames:
			# Write the player file:
			createPlayerFile(amiData, objName, 'S', outputDir + '/player_' + objName + '_S.csv')
			# Put the object in the GLM:
			newKey = feeder.getMaxKey(feederObj)
			feederObj[newKey + 1] = {'object':'player', 'property':'power_12', 'file':'player_' + objName + '_S.csv', 'parent':objName}
	# Write the GLM.
	with open(outputDir + '/out.glm', 'w') as outGlmFile:
		outString = feeder.sortedWrite(feederObj)
		outGlmFile.write(outString)
	#TODO: update omdObj tree object to match feederObj, and insert all .csv files in to the attachments, then write new .omd to outputDir.
	# omd = json.load(open('feederName.omd'))
	for player in os.listdir(outputDir):
		if player.startswith('player'):
			name = basename(player)
			with open(pJoin(outputDir,player),'r') as inFile:
				playerContents = inFile.read()
				omdObj['attachments'][name+'.player'] = playerContents
	oneUp = pJoin(outputDir,'..')
	with open(pJoin(oneUp,omdName),'w') as outFile:
		json.dump(omdObj, outFile, indent=4)

def _tests():
	outFolder = os.path.join(omf.omfDir, 'scratch', 'loadModelingAmiOutput')
	# Delete old output:
	shutil.rmtree(outFolder, ignore_errors=True)
	# Generate new output:
	omdPath = os.path.join(omf.omfDir, 'static', 'testFiles', 'Input - IEEE 13 Node.omd')
	amiPath = os.path.join(omf.omfDir, 'static', 'testFiles', 'Input - AMI measurements 13 node.csv')
	writeNewGlmAndPlayers(omdPath, amiPath, outFolder)

if __name__ == '__main__':
	_tests()