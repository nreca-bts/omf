"""
Meter phases can change due to transformer maintenance and load balancing. If the phase
changes aren't recorded correctly, it makes future load balancing difficult. This model
identifies the true phase of AMI meters based on clustering the meters based on voltage
correlation. While power line carrier meter reading systems can typically identify meter
phase automatically, radio frequency meter reading systems, which are now being widely
deployed, cannot.
"""
import datetime, csv, os, shutil, re, itertools, base64, platform
from os.path import join as pJoin
from base64 import b64decode
from zipfile import ZipFile
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from pathlib import Path
#from plotly import tools
import plotly.offline
from scipy.stats import linregress
from sklearn import preprocessing
from sklearn.metrics import confusion_matrix
from matplotlib import pyplot as plt
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf.solvers import sdsmc

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Identifies true meter phases by clustering AMI data."
hidden = False

def _unzip(zipdir, target):
	"""
	Internal helper for phase id unzip processing.
	"""
	with ZipFile(zipdir, 'r') as zip:
		# zip.printdir()
		shutil.rmtree(target, ignore_errors=True)
		os.mkdir(target)
		zip.extractall(path=target)
	# remove empty '_MACOSX' folder generated after extraction under MAC OS
	MAC_OSX_path = os.path.join(target, '__MACOSX')
	if os.path.exists(MAC_OSX_path):
		os.rmdir(MAC_OSX_path)

def _split(csvPath, newDir):
	''' Split the combined AMI meter data file in to individual ones. '''
	# Make directory
	shutil.rmtree(newDir, ignore_errors=True)
	os.mkdir(newDir)
	# Read data.
	data = pd.read_csv(csvPath)
	# Get filenames.
	fcols = set(data.columns.values) - set(['Timestamp'])
	fnames = list(set([x.split('.')[0] for x in fcols]))
	# Write out subsets with filenames.
	for name in fnames:
		subset = data.filter(items=['Timestamp', name + '.csv-V_A', name + '.csv-V_B', name + '.csv-V_C'])
		clean = subset.rename(index=str, columns={name + '.csv-V_A':'V_A', name + '.csv-V_B':'V_B', name + '.csv-V_C':'V_C'})
		clean.to_csv(newDir + '/' + name + '.csv', index=False)

def _file_transform_gld(METER_DIR, SUB_METER_FILE, modelDir):
	''' This function transform the original Meter and substation voltage files from GridLAB-D to
	... more neat form. More specifically, change all polar or rectangular
	... form of voltage to magnitude'''
	def get_hour(startyear, endTime):
		''' Helper to calculate hour count. '''
		hour = (endTime - datetime.datetime(startyear, 1,1)).days*24
		return hour
	#TODO: handle arbitrary start/end dates.
	import pdb
	startTime = datetime.datetime(2014, 1, 1)
	endTime = datetime.datetime(2015, 1, 1)
	startHour = get_hour(startTime.year, startTime)
	endHour = get_hour(startTime.year, endTime)
	times = np.genfromtxt(SUB_METER_FILE, delimiter=",", usecols=0, skip_header=9, dtype=str)
	# 8784-24 = 8760 since original data ends at 2015-01-01 23:00:00 EST
	times2 = list(times[0:8760])
	filelist = ['./{}/'.format(METER_DIR) + f for f in os.listdir(METER_DIR) if f.endswith('.csv')] + [SUB_METER_FILE]
	for file in filelist:
		vals_ij = np.genfromtxt(file, delimiter=",",usecols=[2,3,4], skip_header = 9, dtype=str)
		vals_ij = np.transpose(vals_ij)
		mags = []
		for column in vals_ij:
			if 'kV' in column[0] and 'kVA' not in column[0]:
				try:
					mag = []
					for volt in column[startHour:endHour]:
						if 'i' in volt or 'j' in volt:
							mag.append(abs(complex(volt.replace(' kV', '').replace('i', 'j'))))
						elif 'd' in volt:
							mag.append(float(volt.replace('-','+').split('+')[1]))
					mags.append(mag)
				except ValueError:
					pdb.set_trace()
		mags = [[np.round(float(i), 4) for i in nested] for nested in mags]
		v_dic = {'Timestamp': times2, 'V_A': mags[0], 'V_B': mags[1],'V_C': mags[2]}
		df_v = pd.DataFrame(v_dic)
		filetype = file.split('.')[-2].split('_')[-2] #split the string to get either 'meter' or 'node'
		if filetype == 'meter':
			meter_index = file.split('.')[-2].split('_')[-1]
			meterV = 'Meter_%d.csv'%int(meter_index)
			newdir = os.path.join(modelDir, 'Revised Meter Voltage Files')
			if not os.path.exists(newdir):
				os.makedirs(newdir)
			file_path = os.path.join(newdir, meterV)
		elif filetype == 'node':
			newdir = os.path.join(modelDir, 'Revised Substation Voltage Files')
			if not os.path.exists(newdir):
				os.makedirs(newdir)
			file_path = os.path.join(newdir, file)
		else:
			pass
		df_v.to_csv(file_path, header=True, index=False, sep=',', mode='w')

def __keen_method(modelDir, inputDict):
	''' Deprecated classical method comparing SCADA-AMI correlation.
	New method performs better with DERs and downline regulators. '''
	INPUT_TYPE = 'Single' # 'Zip', 'GLD' 
	METER_DIR = 'Temp Unzipped Data'
	def unzip():
		pass #todo: create correct .zip extractor function.
	if INPUT_TYPE == 'GLD':
		with open(pJoin(modelDir, "meters_transformed.zip"), "w") as meterZip:
			meterZip.write(b64decode(inputDict["meterZip"]))
		ZIP_FILE = 'meters_gld.zip'
		SUB_METER_FILE = 'rec_R1-12-47-3_node_53.csv'
		unzip(ZIP_FILE, 'Temp Unzipped Data')
		_file_transform_gld(pJoin(modelDir, METER_DIR), pJoin(modelDir, SUB_METER_FILE))
		ssdir = os.path.join(modelDir, 'Revised Substation Voltage Files', SUB_METER_FILE)
	elif INPUT_TYPE == 'Zip':
		ZIP_FILE = 'meters_transformed.zip'
		SUB_METER_FILE = 'rec_sub_meter.csv'
		unzip(pJoin(modelDir, ZIP_FILE), pJoin(modelDir, 'Revised Meter Voltage Files'))
		ssdir = os.path.join(modelDir, SUB_METER_FILE)
	elif INPUT_TYPE == 'Single':
		# write. 
		ami_contents = inputDict['amiMeterData']
		with open(pJoin(modelDir, "combined.csv"), "w") as amiFile:
			amiFile.write(ami_contents)
		_split(pJoin(modelDir, 'combined.csv'), pJoin(modelDir, 'Revised Meter Voltage Files'))
		ssdir = os.path.join(modelDir, 'rec_sub_meter.csv')
	# Perform linear regression and make output csv file.
	# Read transformed files and perform regression
	# Ignore scipy warnings.
	# warnings.filterwarnings('ignore', category=RuntimeWarning)
	df_ss = pd.read_csv(ssdir)
	min_max_scaler = preprocessing.MinMaxScaler()
	df_ss[['V_A', 'V_B', 'V_C']] = min_max_scaler.fit_transform(df_ss[['V_A', 'V_B', 'V_C']])
	newdir = os.path.join(modelDir, 'Revised Meter Voltage Files')
	meters = os.listdir(newdir)
	 # sort meter names based on number
	meters = sorted(meters, key=lambda x: int(re.sub('\D', '', x)))
	# meters.remove('Meter_22.csv') # this is power-bus meter, I would not consider it.
	# perform voltage correlation between meter voltage and substation voltage
	# to make predictions for meter phase. Finally, it writes the the result to an csv file.
	volt = ['V_A','V_B','V_C']
	result_path = pJoin(modelDir, 'output-regression-result.csv')
	# write the header of the output csv file
	with open(result_path, 'w') as f:   
		f.write('Meter Name,M_A ~ SS_A,M_A ~ SS_B,M_A ~ SS_C, M_B ~ SS_A,M_B ~ SS_B,M_B ~ SS_C,'                +'M_C ~ SS_A,M_C ~ SS_B,M_C ~ SS_C,Input Phase,Predicted Phase\n')
	# read and scale the transformed meter files
	for meter in meters:
		meterdir = os.path.join(newdir, meter)
		df_m = pd.read_csv(meterdir)        
		# MinMaxScaler scale the number to (0,1) without distort the characteristics of original data
		min_max_scaler = preprocessing.MinMaxScaler() 
		df_m[['V_A', 'V_B', 'V_C']] = min_max_scaler.fit_transform(df_m[['V_A', 'V_B', 'V_C']])
		# check the scaled data, only print first 4 rows of each file
		#print meter
		#print df_m.iloc[1:5,:]
		#print '========================='
		#list to store R^2 value
		rr_list = [] 
		# this is a temp list to store R^2 values of each meter. This is appended to rr_list during each iteration.
		phase_rr = []
		# double for loop to perform voltage correlation
		for v1 in volt:
			v_meter_rgre = df_m[v1]
			if phase_rr:
				phase_rr = [round(i, 3) for i in phase_rr]
				rr_list.append(phase_rr)
				phase_rr = []
			for v2 in volt:
				v_ss_rgre = df_ss[v2]
				r = list(linregress(v_meter_rgre,v_ss_rgre))[2]
				rsqre = r**2
				phase_rr.append(rsqre)
		phase_rr = [round(i, 3) for i in phase_rr] 
		rr_list.append(phase_rr)
		sum_rr = [] # store the sum R^2 value in all sublists.
		count = 0 # this represent number of non-zero phases.
		for ls in rr_list:
			sum_rr.append(sum(ls))
			if sum(ls) == 0:
				count = count + 1
		phase_pred = []
		if count == 0:
			actual_ph = 'ABC'
			for rr in rr_list:
				max_index = rr.index(max(rr))
				if max_index == 0:
					phase_pred.append('A')
				elif max_index == 1:
					phase_pred.append('B')
				else:
					phase_pred.append('C')
			ph_out = phase_pred[0]+phase_pred[1]+phase_pred[2]
		elif count == 2:
			ph_temp = ['A','B','C']
			sum_rr_i = [i for i, e in enumerate(sum_rr) if e!=0][0] # get the index of non-zero value
			actual_ph = ph_temp[sum_rr_i]
			rr = rr_list[sum_rr_i]
			max_index = rr.index(max(rr))
			if max_index == 0:
				phase_pred.append('A')
			elif max_index == 1:
				phase_pred.append('B')
			else:
				phase_pred.append('C')
			ph_out = phase_pred[0]
		else:
			pass
		with open(result_path, 'a') as f:
			# write the header of the outfile
			f.write('%s,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%s,%s\n'%(meter,rr_list[0][0], rr_list[0][1], rr_list[0][2], rr_list[1][0], rr_list[1][1], rr_list[1][2],rr_list[2][0], rr_list[2][1],rr_list[2][2],actual_ph,ph_out))
	# basic confusion matrix form sklearn
	result_path = pJoin(modelDir, 'output-regression-result.csv')
	df_final = pd.read_csv(result_path)
	y_true = df_final['Input Phase']
	y_pred = df_final['Predicted Phase']
	classes=['A', 'B','C', 'ABC']
	confusion_matrix(y_true, y_pred, labels=['A', 'B', 'C','ABC'])
	cnf_matrix = confusion_matrix(y_true, y_pred, labels=['A', 'B','C', 'ABC'])
	np.set_printoptions(precision=2)
	plt.figure(dpi=200, figsize=(10,5))
	plt.grid(False)
	plot_confusion_matrix(cnf_matrix, classes=['A', 'B', 'C','ABC'])
	plt.savefig(pJoin(modelDir,'output-conf-matrix.png'))
	# Offline Plotly plot
	df_test = pd.read_csv(os.path.join(modelDir, 'Revised Meter Voltage Files', inputDict['checkMeter']))
	min_max_scaler = preprocessing.MinMaxScaler()
	selectedPhase = 'V_A'
	for phase in ['V_A','V_B','V_C']:
		df_test[[phase]] = min_max_scaler.fit_transform(df_test[[phase]])
		# Check for non-zero data.
		if max(df_test[phase]) > 0.0:
			selectedPhase = phase
	y0 = df_ss['V_A']
	y1 = df_ss['V_B']
	y2 = df_ss['V_C']
	y3 = df_test[selectedPhase]
	new_x = list(range(len(y0)))
	# Create traces
	trace0 = go.Scatter(
		x = new_x,
		y = y0,
		# xaxis='x4',
		# yaxis='y1',
		mode = 'lines',
		name = 'SS_PH_A'
	)
	trace1 = go.Scatter(
		x = new_x,
		y = y1,
		# xaxis='x4',
		# yaxis='y2',
		mode = 'lines',
		name = 'SS_PH_B'
	)
	trace2 = go.Scatter(
		x = new_x,
		y = y2,
		# xaxis='x4',
		# yaxis='y3',
		mode = 'lines',
		name = 'SS_PH_C'
	)
	trace3 = go.Scatter(
		x = new_x,
		y = y3,
		# xaxis='x4',
		# yaxis='y4',
		mode = 'lines',
		name = inputDict['checkMeter'] + ' ' + selectedPhase
	)
	data = [trace0, trace1, trace2, trace3]
	# Create layout
	meterDetailLayout = go.Layout(
		width=1000,
		height=500,
		xaxis=dict(
			showgrid=False,
			title="Time Step"
		),
		yaxis=dict(
			title="Volts (PU)",
		),
		legend=dict(
			x=0,
			y=1.1,
			orientation="h"
		),
		margin=go.layout.Margin(
			l=60,
			r=20,
			b=70,
			t=0,
			pad=4
	    ),
	)
	# For non-jupyter plotting.
	plotly.offline.plot(data, filename=pJoin(modelDir, 'output-chart.html'), auto_open=False)

def plot_confusion_matrix(
		cm,
		classes,
		cmap=plt.cm.Blues
	):
	'''Self-defined function for better illustrating confusion matrix.'''
	plt.imshow(cm, interpolation='nearest', cmap=cmap, aspect='auto')
	plt.colorbar()
	tick_marks = np.arange(len(classes))
	plt.xticks(tick_marks, classes, rotation=45)
	plt.yticks(tick_marks, classes)
	fmt = 'd'
	thresh = cm.max() / 2.
	for i, j in itertools.product(range(cm.shape[0]), range(cm.shape[1])):
		plt.text(j, i, format(cm[i, j], fmt),
				horizontalalignment="center",
				color="white" if cm[i, j] > thresh else "black")
	plt.ylabel('Input Label')
	plt.xlabel('Predicted Label')
	plt.tight_layout()

def _to_percentage( val ):
    """
    Internal helper for phase id to percentage processing.
    """
    percentage = val * 100
    return "{:.4g}%".format(percentage)

def predicted_phase_labels_warning( df ):
	''' Returns a list whether a warning present and if so, which predicted meter label(s) caused the warning.

	If the first value is False, there is no warning.
	If the first value is True, second value contains information regarding which phase label and its percentage.
	'''
	retVal = [False]
	values = df['Predicted Phase Labels'].value_counts()
	for val in values.index:
		if val < 0: # One of the outputs has a meter that's -99
			values = values.drop(labels=[val])
	total_meters = len(df)
	percentages_total = ( values / total_meters ) * 100
	if (percentages_total < 5).any():
		percentages_total.to_dict()
		# These are int64, need to convert to python standard int/float
		filtered_values = { int(key): round( float(value), 2) for key, value in percentages_total.items() if value < 5}
		retVal = [True, filtered_values]
	if percentages_total.iloc[0] >= 80:
		retVal = [True, { int(percentages_total.index[0]): round( float(percentages_total.iloc[0]), 2) }]
	return retVal

def work(modelDir, inputDict):
	""" Run the model in its directory."""
	outData = {}
	# write input file to modelDir
	with open(pJoin(modelDir, inputDict["amiMeterDataName"]), "w") as amiFile:
		amiFile.write(inputDict["amiMeterData"])
	# run core algorithm
	# Jenny
	phaseLabelsTrueFile = Path(omf.omfDir, 'static', 'testFiles', 'phaseID', 'PhaseLabelsTrue_AMI.csv')
	numPhasesFile = Path(omf.omfDir, 'static', 'testFiles', 'phaseID', 'NumPhases.csv')
	outputPath = Path( modelDir, 'outputs_PI_CAEns.csv')
	sdsmc.PhaseIdentification.PhaseIdentification_CAEnsemble.run(
		pJoin(modelDir, inputDict["amiMeterDataName"]),
		phaseLabelsTrue_csv = phaseLabelsTrueFile,
		numPhases_csv = numPhasesFile,
		saveResultsPath = outputPath,
		kFinal=int(inputDict["kFinal"]),
		windowSize=inputDict["windowSize"],
		useTrueLabelsFlag=False,
		useNumPhasesField=False
	)
	# generate "confusion matrix"
	df_final = pd.read_csv( outputPath )
	y_true = df_final['Original Phase Labels (with errors)']
	y_pred = df_final['Predicted Phase Labels']
	classes=[1,2,3]
	cnf_matrix = confusion_matrix(y_true, y_pred, labels=classes)
	np.set_printoptions(precision=2)
	plt.figure(dpi=200, figsize=(10,5))
	plt.grid(False)
	plot_confusion_matrix(cnf_matrix, classes=classes)
	plt.savefig(pJoin(modelDir,'output-conf-matrix.png'))
	# write our outData
	warning = predicted_phase_labels_warning( df=df_final )
	if warning[0] == False:
		outData['warningFlag'] = warning[0]
	else:
		outData['warningFlag'] = warning[0]
		outData['warningData'] = warning[1]
		outData['warningInfo'] = f" Meter distribution is resulting in over 80% of meters falling under a single phase and/or a phase has less than 5% of all total meters. Could potentially be due to small or insufficient input file.\nIn order to determine correct phase, you need to determine the real phase for 1 meter in each cluster and use that to determine the actual final phasing."

	df_final['Confidence Score'] = df_final['Confidence Score'].apply(_to_percentage)
	df_final = df_final.iloc[:, 1:]
	outData["phasingResults"] = ( list(df_final.itertuples(index=False, name=None)) )
	outData["phasingResultsTableHeadings"] = df_final.columns.values.tolist()
	with open(pJoin(modelDir,"output-conf-matrix.png"),"rb") as inFile:
		outData["confusionMatrixImg"] = base64.standard_b64encode(inFile.read()).decode()
	with open(pJoin(modelDir,"ModifiedSC_HIST.png"),"rb") as inFile:
		outData["confidenceHistogramImg"] = base64.standard_b64encode(inFile.read()).decode()
	# with open(pJoin(modelDir,"PercentagePlot.png"),"rb") as inFile:
	# 	outData["PercentagePlotImg"] = base64.standard_b64encode(inFile.read()).decode()
	return outData

def new(modelDir):
	""" Create a new instance of this model. Returns true on success, false on failure. """
	with open(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", "phaseID", "sandia_test_data_2k_readings.csv")) as f:
		ami_meter_data = f.read()
	defaultInputs = {
		"user": "admin",
		"amiMeterData": ami_meter_data,
		"amiMeterDataName": "sandia_test_data_2k_readings.csv",
		"kFinal": "7",
		"windowSize": "default",
		"modelType": modelName
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	return creationCode

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(
		__neoMetaModel__._omfDir,
		"data",
		"Model",
		"admin",
		"Automated Testing of " + modelName,
	)
	# Blow away old test results if necessary.
	shutil.rmtree(modelLoc, ignore_errors=True)
	# Create New.
	new(modelLoc)
	# Pre-run.
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == "__main__":
	_tests()
