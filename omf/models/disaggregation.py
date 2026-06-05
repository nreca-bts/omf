"""
The Disaggregation model breaks down provided power consumption data from a given meter
into the constituent appliances. This model relies on training data to make accurate
predictions and returns both an overall appliance level disaggregation and a
disaggregation over time.
"""
import subprocess, pickle, warnings, os, base64, pathlib, time, sys
from os.path import join as pJoin
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

try:
	from omf.solvers.nilmtk.nilm_metadata.nilm_metadata import save_yaml_to_datastore
	from omf.solvers.nilmtk.nilmtk.nilmtk import DataSet, TimeFrame, MeterGroup, HDFDataStore
	from omf.solvers.nilmtk.nilmtk.nilmtk.legacy.disaggregate import fhmm_exact
	from omf.solvers.nilmtk.nilmtk.nilmtk.legacy.disaggregate import CombinatorialOptimisation
	from omf.solvers.nilmtk.nilmtk.nilmtk.datastore import Key
	from omf.solvers.nilmtk.nilmtk.nilmtk.measurement import LEVEL_NAMES
	from omf.solvers.nilmtk.nilmtk.nilmtk.utils import get_datastore
	from omf.solvers.nilmtk.nilm_metadata.nilm_metadata import save_yaml_to_datastore
except Exception as e:
	pass
	# raise Exception('need to install nilmtk')
	# installNilm()

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "The Disaggregation model performs analysis to appliance level power consumption given a site meter."
hidden = False

def work(modelDir, inputDict):
	''' Run the model in its directory. '''

	#print(inputDict)
	
	# initialize variables
	outData = {}
	trainBuilding =  int(inputDict['trainBuilding'])
	testBuilding = int(inputDict['testBuilding'])
	algorithm = str(inputDict['disaggAlgo'])

	# convert train data csv into nilmtk format or load nilmtk data
	if (inputDict['trainSet'] == 'CSV'): 
		trainPath = convertTrainData(modelDir,inputDict['trainingData'], \
			pJoin(modelDir,'trainData.h5') )
	else:
		trainPath = getPath(inputDict['trainSet'])

	# convert test data csv into nilmtk format or load nilmtk data
	if (inputDict['testSet'] == 'CSV'): 
		testPath = convertTestData(modelDir, inputDict['testingData'], \
			pJoin(modelDir,'testData.h5') )
	else:
		testPath = getPath(inputDict['testSet'])

	# if nilmtk is not installed, install it
	if not(os.path.isdir('./solvers/nilmtk/nilmtk')):
		installNilm()

	# load data
	train = DataSet(trainPath)
	test = DataSet(testPath)

	train_elec = train.buildings[trainBuilding].elec
	test_elec = test.buildings[testBuilding].elec

	# select the larger sampling period between the train and the test set
	samplePeriod = next(iter(train.metadata['meter_devices'].values()))['sample_period']
	testSamples = next(iter(test.metadata['meter_devices'].values()))['sample_period']
	if samplePeriod < testSamples:
		samplePeriod = testSamples

	# train the appropriate algorithm
	clf = ''
	if algorithm == 'fhmm':
		clf = fhmm_exact.FHMM()
	elif algorithm == 'combOpt':
		clf = CombinatorialOptimisation()

	start = time.time()
	clf.train(train_elec, sample_period=samplePeriod)
	end = time.time()
	print('Training runtime =', end-start, 'seconds.')

	# make predicitons
	pred = {}
	testChunks = test_elec.mains().load(sample_period=samplePeriod)
	for i, chunk in enumerate(testChunks):
	    chunk_drop_na = chunk.dropna()
	    pred[i] = clf.disaggregate_chunk(chunk_drop_na)
	print('---------------------------------')
	print('Testing done')
	print('---------------------------------')
	
	# If everything can fit in memory
	pred_overall = pd.concat(pred)
	pred_overall.index = pred_overall.index.droplevel()

	# use appliance names as the labels
	appliance_labels = []
	for m in pred_overall.columns.values:
	    name = m.appliances[0].metadata['original_name']
	    name = name.replace('_',' ')
	    name = name.capitalize()
	    appliance_labels.append(name)
	pred_overall.columns = appliance_labels

	# compute the total predicted usage as well as the appliance level breakdown
	totalDisagg = pred_overall.sum(1)
	totalByApp = pred_overall.sum()
	totalByApp.sort_values(inplace=True, ascending=False)
	percent = 100.*totalByApp/totalByApp.sum()

	print(train_elec)

	# plot training data using appliance names as labels
	top_k_train_elec = train_elec.submeters().select_top_k(k=5)
	appliance_labels = []
	for m in top_k_train_elec.meters:
	    name = m.appliances[0].metadata['original_name']
	    name = name.replace('_',' ')
	    name = name.capitalize()
	    appliance_labels.append(name)
	print('-----------------------------------------')
	print(appliance_labels)
	print('-------------------------------------------')
	
	top_k_train_elec.plot()
	ax = plt.gca()
	plt.legend(labels=appliance_labels, bbox_to_anchor=(0,1.02,1,0.2), loc="lower left", 
		mode="expand", borderaxespad=0, ncol=3)
	plt.savefig(modelDir + '/trainPlot.png', dpi=600)
	plt.clf()

	# plot the test data as well as the sum of the disag 
	totalDisagg.plot()
	test_elec.dataframe_of_meters().plot()
	ax = plt.gca();
	lgd = plt.legend(bbox_to_anchor=(0,1.02,1,0.2), loc="lower left", 
		mode="expand", borderaxespad=0, ncol=3)
	lgd.get_texts()[0].set_text('total disaggregation output')
	plt.savefig(modelDir + '/testPlot.png', dpi=600)
	plt.clf()

	# plot disagg time series
	pred_overall.plot()
	ax = plt.gca();
	lgd = plt.legend(bbox_to_anchor=(0,1.02,1,0.2), loc="lower left", 
		mode="expand", borderaxespad=0, ncol=3)
	plt.savefig(modelDir + '/disaggPlot.png', 
		bbox_extra_artists=(lgd,), bbox_inches='tight', dpi=600)
	plt.clf()

	# plot % use by appliance
	patches, texts = plt.pie(totalByApp, startangle=180,  counterclock=False)
	labels = ['{0} - {1:1.2f} %'.format(i,j) for i,j in zip(totalByApp.index, percent)]
	lgd = plt.legend(patches, labels, loc='center left', bbox_to_anchor=(-0.1, 1))
	plt.savefig(modelDir + '/disaggPie.png', 
		bbox_extra_artists=(lgd,), bbox_inches='tight', dpi=600)
	plt.clf()

	# open image outputs and add them to the dictionary used by the html page
	with open(pJoin(modelDir,"trainPlot.png"),"rb") as inFile:
		outData["trainPlot"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	with open(pJoin(modelDir,"testPlot.png"),"rb") as inFile:
		outData["testPlot"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	with open(pJoin(modelDir,"disaggPlot.png"),"rb") as inFile:
		outData["disaggPlot"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	with open(pJoin(modelDir,"disaggPie.png"),"rb") as inFile:
		outData["disaggPie"] = base64.standard_b64encode(inFile.read()).decode('ascii')
	return outData

def getPath(dataSet):
	'''logic for returning the data file associated with the specified dataset'''
	path = ''
	if (dataSet == 'REDD'):
		path = './solvers/nilmtk/nilmtk/data/redd.h5'
	return path

def convertTestData(modelDir, data, outputFilename):

	"""
	Convert test data data between solver or OMF representations.
	"""
	watts = []
	timeStamps = []
	samplePeriod = ''

	# parse provided csv files
	data = data.split('\r\n')
	firstRow = True
	for row in data:
		if str(row) != '':
			dataPoint = row.split(',')
			if firstRow:
				samplePeriod = dataPoint[0]
				firstRow = False
			else:
				timeStamps.append(dataPoint[0])
				watts.append(dataPoint[1])

	# format dataframe data structure and save in nilmtk format
	store = get_datastore(outputFilename, 'HDF', mode='w')
	df = pd.DataFrame({('power', 'apparent'): watts}, dtype=float)
	df.columns.set_names(LEVEL_NAMES, inplace=True)
	df.index = pd.to_datetime(timeStamps, format='%Y-%m-%d %H:%M:%S', exact=False, utc=True)
	df = df.tz_convert('US/Eastern')
	df = df.sort_index()
	key = Key(building=1, meter=1)
	store.put(str(key), df)

	## create the metadata files in accordance with nilmtk guidelines

	# building metatdata
	if not os.path.exists(pJoin(modelDir,'test')):
	    os.makedirs(pJoin(modelDir,'test'))
	f = open(pJoin(modelDir,'test','building1.yaml'), 'w')
	f.write('instance: 1\n')
	f.write('elec_meters:\n')
	f.write( '  ' + '1: &generic\n')
	f.write( '    ' + 'site_meter: true\n')
	f.write( '    ' + 'device_model: generic\n')
	f.write('\nappliances: []')
	f.close()

	# dataset metadata
	f = open(pJoin(modelDir,'test','dataset.yaml'), 'w')
	f.write('name: testData\n')
	f.close()

	# meter device metadata
	f = open(pJoin(modelDir,'test','meter_devices.yaml'), 'w')
	f.write('generic:\n')
	f.write('  ' + 'model: generic\n')
	f.write('  ' + 'sample_period: ' + samplePeriod + '\n')
	f.write('  ' + 'max_sample_period: ' + samplePeriod + '\n')
	f.write('  ' + 'measurements:\n')
	f.write('  ' + '- physical_quantity: power\n')
	f.write('    ' + 'type: apparent\n')
	f.write('    ' + 'upper_limit: 1000000000\n')
	f.write('    ' + 'lower_limit: -100000000\n')
	f.close()

	# save data and metadata
	save_yaml_to_datastore(pJoin(modelDir,'test'), store)
	store.close()
	
	return outputFilename

def convertTrainData(modelDir, data, outputFilename):

	"""
	Convert train data data between solver or OMF representations.
	"""
	watts = []
	timeStamps = []
	appliances = []
	samplePeriod = ''

	# parse provided csv files
	data = data.split('\r\n')
	firstRow = True
	for row in data:
		if str(row) != '':
			dataPoint = row.split(',')
			if firstRow:
				samplePeriod = dataPoint[0]
				firstRow = False
			else:
				timeStamps.append(dataPoint[0])
				watts.append(dataPoint[1])
				appliances.append(dataPoint[2])


	watts = np.array(watts)
	appliances = np.array(appliances)
	timeStamps = np.array(timeStamps)

	store = get_datastore(outputFilename, 'HDF', mode='w')

	# breakdown the data by appliance and set every time point where
	# the appliance wasnt used to 0
	
	uniqueAppliances = list(np.unique(appliances))
	meterIndex = uniqueAppliances.index('meter')

	for index, app in enumerate(uniqueAppliances):
		
		# get the time points where a given appliance is on and 
		# also where it is off
		appIndices = np.where(appliances == app)[0]
		nonAppIndices = np.where(appliances != app)[0]
		
		# keep only the data for when the appliance is on
		wattsFiltered = np.delete(np.copy(watts),nonAppIndices)
		timeFiltered = np.delete(np.copy(timeStamps),nonAppIndices)

		# create zeroed data when the appliance is off
		timeFiller = np.setdiff1d(np.copy(timeStamps),timeFiltered)
		wattsFiller = np.zeros(timeFiller.shape)

		# combine the on and off data
		timeAll = np.append(timeFiller,timeFiltered)
		wattsAll = np.append(wattsFiller,wattsFiltered)

		# format dataframe data structure and save in nilmtk format
		df = pd.DataFrame({('power', 'apparent'): wattsAll}, dtype=float)
		df.index = pd.to_datetime(timeAll, format='%Y-%m-%d %H:%M:%S', exact=False, utc=True)
		df.columns.set_names(LEVEL_NAMES, inplace=True)
		df = df.tz_convert('US/Eastern')
		df = df.sort_index()

		if index == meterIndex:
			key = Key(building=1, meter=1)
		elif index < meterIndex:
			key = Key(building=1, meter=index+2)
		else:
			key = Key(building=1, meter=index+1)			
		
		store.put(str(key), df)

	## create the metadata files in accordance with nilmtk guidelines
	if meterIndex != -1:
		del(uniqueAppliances[meterIndex])

	# building metatdata
	if not os.path.exists(pJoin(modelDir,'train')):
	    os.makedirs(pJoin(modelDir,'train'))
	f = open(pJoin(modelDir,'train', 'building1.yaml'), 'w')
	f.write('instance: 1\n')
	f.write('elec_meters:\n')
	f.write('  ' + '1: &mainMeter\n')
	f.write('    ' + 'site_meter: true\n')
	f.write('    ' + 'device_model: generic\n')
	for index, app in enumerate(uniqueAppliances):
		if index == 0:
			f.write('  ' + '2: &generic\n')
			f.write('    ' + 'submeter_of: 0\n')
			f.write('    ' + 'device_model: generic\n')
		else:
			f.write('  ' + str(index +2) + ': *generic\n')	
	f.write('\nappliances:')
	for index, app in enumerate(uniqueAppliances):
		f.write('\n- ' + 'original_name: ' + app + '\n')
		f.write('  ' + 'type: unknown\n')
		f.write('  ' + 'instance: ' + str(index + 1) + '\n')
		f.write('  ' + 'meters: ['  + str(index + 2) + ']\n')
	f.close()

	# dataset metadata
	f = open(pJoin(modelDir,'train', 'dataset.yaml'), 'w')
	f.write('name: trainData\n')
	f.close()

	# meterdevices metadata
	f = open(pJoin(modelDir,'train', 'meter_devices.yaml'), 'w')
	f.write('generic:\n')
	f.write('  ' + 'model: generic\n')
	f.write('  ' + 'sample_period: ' + samplePeriod + '\n')
	f.write('  ' + 'max_sample_period: ' + samplePeriod + '\n')
	f.write('  ' + 'measurements:\n')
	f.write('  ' + '- physical_quantity: power\n')
	f.write('    ' + 'type: apparent\n')
	f.write('    ' + 'upper_limit: 1000000000\n')
	f.write('    ' + 'lower_limit: -100000000\n')
	f.close()

	# save data and metadata
	save_yaml_to_datastore(pJoin(modelDir,'train'), store)
	store.close()
	
	return outputFilename

def installNilm():
	"""
	Perform install nilm processing for the disaggregation model.
	"""
	print('------------------------------------------------------------------')
	print('------------------------------------------------------------------')
	print('------------------------------------------------------------------')
	print('------------------------------------------------------------------')


	# install nilmtk
	os.chdir("./solvers/nilmtk/")
	os.system("yes | sudo apt-get install python3-tk git libhdf5-serial-dev python-dev postgresql postgresql-contrib postgresql-server-dev-all python3-pip")
	os.system("sudo pip3 install numpy scipy==0.19.1 six scikit-learn==0.19.2 pandas numexpr tables matplotlib networkx future psycopg2 nose coveralls coverage git+https://github.com/hmmlearn/hmmlearn.git@ae1a41e4d03ea61b7a25cba68698e8e2e52880ad#egg=hmmlearn")
	os.system("git clone https://github.com/nilmtk/nilm_metadata/")
	os.chdir("nilm_metadata")
	os.system("yes | rm -r .git*")
	os.system("sudo python3 setup.py develop")
	os.chdir("..")
	os.system("git clone https://github.com/nilmtk/nilmtk.git")
	os.chdir("nilmtk")
	os.system("yes | rm -r .git*")
	os.system("sudo python3 setup.py develop")
	print('------------------------------------------------------------------')
	print(os.getcwd())
	print('------------------------------------------------------------------')
	os.rename('../convTrainPython3.py','./convTrainPython3.py')
	os.rename('../convTestPython3.py','./convTestPython3.py')
	os.rename('../dissagScript.py','./dissagScript.py')
	os.chdir('../../../')

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		'modelType': modelName,
		'created': '', 
		'runTime': '', 
		'disaggAlgo': 'combOpt', 
		'testFileName': '', 
		'trainFileName': '', 
		'trainingData': '', 
		'testingData': '', 
		'testSet': 'REDD', 
		'trainSet': 'REDD', 
		'testBuilding': '1', 
		'trainBuilding': '1'
	}
	
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

def _debugging():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	pass
	## Location
	#modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	## Blow away old test results if necessary.
	#try:
	#	shutil.rmtree(modelLoc)
	#except:
	#	# No previous test results.
	#	pass
	## Create New.
	#new(modelLoc)
	## Pre-run.
	## renderAndShow(modelLoc)
	## Run the model.
	#__neoMetaModel__.runForeground(modelLoc)
	## Show the output.
	#__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_debugging()
