"""
This model provides an interactive visualization of radio frequency coverage from a
tower to assist with communications planning.
"""

import datetime, shutil, requests, tempfile, xml.etree.ElementTree as ET, base64
from zipfile import ZipFile
from os.path import join as pJoin
from PIL import Image
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers import splat as splat_solver

# Model metadata:
tooltip = "The rfCoverage model provides a visualization of radio frequency propogation"
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def work(modelDir, inputDict):

	"""
	Run the rf coverage model analysis and return the output data used by the OMF
	interface.
	"""
	sourceQth = [
		"Source Name",
		str(inputDict['towerLatitude']),
		str(inputDict['towerLongitude']),
		str(inputDict['towerHeight']) + 'm'
		]

	with open(pJoin(modelDir, "siteLocation.qth"),'w') as qthFile:
		for i in sourceQth:
			qthFile.write(i)
			qthFile.write("\n")

	sourceLrp = [
		"15.000 ; Earth Dielectric Constant (Relative permittivity)",
		"0.005 ; Earth Conductivity (Siemens per meter)",
		"301.000 ; Atmospheric Bending Constant (N-units)",
		str(inputDict['frequency']),
		"5 ; Radio Climate",
		str(inputDict['polarization']),
		"0.50 ; Fraction of situations (50 % of locations)",
		"0.90 ; Fraction of time (90% of the time)"
		]

	with open(pJoin(modelDir, "siteLocation.lrp"),'w') as lrpFile:
		for i in sourceLrp:
			lrpFile.write(i)
			lrpFile.write("\n")

	#US based lat/lon guide
	#longitude max = 180W
	#longitude min = 043W
	#latitude min = 10N
	#latitude max = 60N
	#get the terrain files from hgt in zips and convert to sdf on as needed basis. Will not need if all are stored in static
	#temp directory for sdf files to use in splat but dont save in output due to size - pull from dds each time splat is run
	sdfDir = tempfile.mkdtemp()
	if inputDict["elevation"] == "digitalElevationModel":
		#sdf dir
		#Set ranges for hgt files to pull - may change on further analysis
		latitudeInt = int(round(float(inputDict['towerLatitude'])))
		latitudeMax = min(latitudeInt+3, 61)
		latitudeMin = max(latitudeInt-2, 10)
		longitudeInt = int(round(float(inputDict['towerLongitude'])))
		longitudeMax = min(longitudeInt+4, 181)
		longitudeMin = max(longitudeInt-3, 43)
		hgtDir = tempfile.mkdtemp()
		for lat in range(latitudeMin, latitudeMax):
			strLat = str(lat)
			for lon in range(longitudeMin, longitudeMax):
				if len(str(lon)) < 3:
					strLon = '0' + str(lon)
				else:
					strLon =  str(lon)
				#the zip files from the site are missing the period before hgt in the zip file name beginning with latitude 55
				if lat >= 55:
					currentUrl = "https://dds.cr.usgs.gov/srtm/version2_1/SRTM3/North_America/N" + strLat + "W" + strLon +"hgt.zip"
				else:
					currentUrl = "https://dds.cr.usgs.gov/srtm/version2_1/SRTM3/North_America/N" + strLat + "W" + strLon +".hgt.zip"
				response = requests.get(currentUrl)
				if response.status_code == 200:
					#print('valid lat lon zip')
					with tempfile.TemporaryFile() as tmp:
						tmp.write(response.content)
						with ZipFile(tmp, 'r') as zipper:
							zipper.extractall(hgtDir)
							hgtFile = "N" + strLat + "W" + strLon + ".hgt"
							splat_solver.run_srtm2sdf(pJoin(hgtDir, hgtFile), cwd=sdfDir)
	#Can add in -R switch for area to cover
	args = ["-t", pJoin(modelDir, "siteLocation.qth"), "-o", pJoin(modelDir, "coverageMap.ppm"), "-kml", "-ngs", "-d", sdfDir]

	#change inputs based on analysis type
	if inputDict["analysisType"] == "lineOfSight":
		args += ["-c", "10", "-metric"]
	else:
		args += ["-L", "10", "-metric"]
		if inputDict["analysisType"] != "pathLoss":
			args += ["-erp", inputDict["erp"]]
			if inputDict["analysisType"] == "recievedPower":
				args += ["-dbm"]

	splat_solver.run(args, cwd=pJoin(modelDir))

	outData = {}

	#Convert the image file to use in leaflet
	im = Image.open(pJoin(modelDir, "coverageMap.ppm"))
	im = im.convert("RGBA")
	datas = im.getdata()

	newData = []
	for item in datas:
	    if item[0] == 255 and item[1] == 255 and item[2] == 255:
	        newData.append((255, 255, 255, 0))
	    else:
	        newData.append(item)

	im.putdata(newData)
	im.save(pJoin(modelDir,"coverageMap.png"))
	if inputDict["analysisType"] != "lineOfSight":
		scale = Image.open(pJoin(modelDir, "coverageMap-ck.ppm"))
		scale.save(pJoin(modelDir,"rfScale.png"))
		with open(pJoin(modelDir,"rfScale.png"),"rb") as inFile:
			outData["rfScale"] = base64.standard_b64encode(inFile.read()).decode()


	#parse kml for image bounding box
	kml = pJoin(modelDir, "coverageMap.kml")
	tree = ET.parse(kml)
	root = tree.getroot()
	all_descendants = list(tree.iter())
	for i in all_descendants:
		if i.tag == '{http://earth.google.com/kml/2.1}south':
			south = i.text
		elif i.tag == '{http://earth.google.com/kml/2.1}north':
			north = i.text
		elif i.tag == '{http://earth.google.com/kml/2.1}east':
			east = i.text
		elif i.tag == '{http://earth.google.com/kml/2.1}west':
			west = i.text

	# Stdout/stderr.
	outData['towerLatitude'] = inputDict['towerLatitude']
	outData['towerLongitude'] = inputDict['towerLongitude']
	with open(pJoin(modelDir,"coverageMap.png"),"rb") as inFile:
		outData["coverageMap"] = base64.standard_b64encode(inFile.read()).decode()
	outData['north'] = north
	outData['south'] = south
	outData['west'] = west
	outData['east'] = east
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"modelType": modelName,
		"towerLatitude": "36.42708056",
		"towerLongitude": "103.48500000",
		"towerHeight":"50",
		"frequency":"900.000",
		"polarization":"0",
		"analysisType": "recievedPower",
		"elevation": "seaLevel",
		"erp": "30000",
		"created":str(datetime.datetime.now())
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
	# Create New.
	new(modelLoc)
	# Pre-run.
	__neoMetaModel__.renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
