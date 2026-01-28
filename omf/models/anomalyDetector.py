""" Anomaly detection. """
import sys, shutil, csv, hashlib, plotly, json
from os.path import isdir, join as pJoin
from io import StringIO
import numpy as np
import pandas as pd
from sklearn.neighbors import LocalOutlierFactor
from sklearn.ensemble import IsolationForest
import plotly.graph_objs as go
from omf import anomalyDetection
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = ('Detect anomalies in meter data.')
hidden = False

def workProphet(modelDir, inputDict):
	'''
	Create models for Prophet monovariate anomaly detector, Peak Forecast T-Test Method, and Elliptic Envelope

	params
	type modelDir: str, path to the directory in which the model is located
	type inputDict: dictionary, {
		'confidence': The required confidence level to classify the data as Gaussian,
		'norm_confidence': confidence interval using a normal distribution?,
		'startDate': start date of data to be used for forecasting,
		'file': csv file of data
		'demandTempBool': optional dictionary containing parameters for Peak Forecast T-test Method,
		'ylabel': demand points	throughout the day
			}
	rtype out: dictionary, {
		'y': demand labels for training data,
		'yhat': predicted demand labels for training data,
		'yhat_upper': upper bound on predicted training data labels,
		'yhat_lower': lower bound on predicted training data labels,
		'prophet_outlier': predicted outlier points from prophet model,
		'elliptic_outlier': predicted outlier points from prophet model,
		'katrina_outlier': predicted outlier points from Peak T-test model
			}
	'''
	cached_file_name = "input_data_{}.csv".format(inputDict["confidence"])
	cached_file_path = pJoin(modelDir, cached_file_name)

	# try to get our cached input
	try:
		with open(cached_file_path, "r") as f:
			cached_hash = f.read()
	except IOError:
		cached_hash = ""

	confidence = float(inputDict["confidence"]) if inputDict.get("confidence") else 0.99
	if confidence >= 1:
		raise Exception(
			"Value for Confidence Level Out of Bounds (must be less than 1)"
		)

		# do we have a cached forecast?
	input_hasher = hashlib.md5()
	input_hasher.update(inputDict["file"].encode())
	cached = (
		"forecasted_{}.csv".format(confidence)
		if cached_hash == input_hasher.hexdigest()
		else None
	)

	with open(cached_file_path, "w") as f:
		f.write(input_hasher.hexdigest())

	out = {}

	# load our csv to df
	f = StringIO(inputDict["file"])
	header = csv.Sniffer().has_header(f.read(1024))
	header = 0 if header else None
	f.seek(0)
	df = pd.read_csv(f, header = header)

	if inputDict.get("demandTempBool"):
		# nn_bool, nn_actual, nn_pred, nn_lower, nn_upper = anomalyDetection.t_test(df, modelDir, inputDict["startDate"], confidence)
		pk_bool, pk_actual, pk_time = anomalyDetection.t_test(df, modelDir, inputDict["startDate"], confidence, model="nextDayPeakKatrina")
		katrina_outliers = [
			(time, demand) if out_bool else None
			for time, out_bool, demand in zip(pk_time, pk_bool, pk_actual)
		]
		katrina_outliers = [a for a in katrina_outliers if a]

	# try to use user input to remap columns for prophet
	df = df.rename(columns={inputDict.get("yLabel",""): "y"})
	if "y" not in df.columns:
		df = df.rename(columns={df.columns[0]: "y"})

		# add our boy for prophet
	df["ds"] = pd.date_range(
		start=inputDict["startDate"], freq="H", periods=df.shape[0]
	)

	prophet_df = anomalyDetection.prophet(
		df[["ds", "y"]], modelDir, confidence=confidence, cached=cached
	)

	elliptic_df = anomalyDetection.elliptic_envelope(df, modelDir, float(inputDict["norm_confidence"]))

	out["y"] = prophet_df.y.values.tolist()
	out["yhat"] = prophet_df.yhat.values.tolist()
	out["yhat_upper"] = prophet_df.yhat_upper.values.tolist()
	out["yhat_lower"] = prophet_df.yhat_lower.values.tolist()
	out["prophet_outlier"] = prophet_df.outlier.values.tolist()

	if elliptic_df is not None:
		# This might be wrong, IDK
		out["elliptic_outlier"] = elliptic_df.outlier.values.tolist()

	if inputDict.get("demandTempBool"):
		"""
		out["nn_outlier"] = list(nn_bool.astype(int))
		out["nn_actual"] = list(nn_actual)
		out["nn_pred"] = list(nn_pred)
		out["nn_lower"] = list(nn_lower)
		out["nn_upper"] = list(nn_upper)
		"""
		out["katrina_outlier"] = katrina_outliers
	out["startDate"] = inputDict["startDate"]
	return out

def workLof(modelDir, inputDict):
	'''
	Create model for Local Outlier Factor, plot it and return the plot.
	params:
	type modelDir: str, path to the directory in which the model is located?
	type inputDict: dictionary,{
								'neighbors': number of neighbors used neighborhood of a given point,
								'contaminationLof': the percent of data expected to be anomalous,
								'file': csv file of data
								}

	rtype plotData: list, containinng scatter plot of original input data and predicted anomalous points.
	'''
	neighbors = int(inputDict['neighbors'])
	contamination = float(inputDict['contaminationLof'])
	if contamination == 0:
		contamination = 'auto'
	clf = LocalOutlierFactor(n_neighbors=neighbors, contamination=contamination)

	# load our csv to df
	f = StringIO(inputDict["file"])
	df = pd.read_csv(f)
	datapoints = df.to_numpy()

	maxVals = np.max(datapoints, axis=0)
	maxVals = np.tile( maxVals, (datapoints.shape[0],1) )
	normalizedDatapoints = np.divide(datapoints,maxVals)

	labels = clf.fit_predict(normalizedDatapoints)
	scores = clf.negative_outlier_factor_

	plotData = []
	x = np.arange(0,datapoints.shape[0])
	data = go.Scatter( x=x, y=datapoints[:,0], name='data', mode='lines+markers' )
	plotData.append(data)
	outliers = go.Scatter( x=x[labels!=1], y=datapoints[labels!=1, 0], name='outliers',
		mode='markers' )
	plotData.append(outliers)

	return plotData

def workIso(modelDir, inputDict):
	'''
	Create Isolation Forest model, and its respective scatterplot.

	params:
	type modelDir: str, path to the directory in which the model is located?
	type inputDict: dictionary,{
								'samples': the percent of data to sample to create each decision tree.,
								'estimators': number of decision tress to generate,
								'contaminationIso': the percent of data expected to be anomalous,
								'file': csv file of data
								}

	rtype plotData: list, containinng scatter plot of original input data and predicted anomalous points.
	'''
	samples = float(inputDict['samples'])
	estimators = int(inputDict['estimators'])
	contamination = float(inputDict['contaminationIso'])
	if contamination == 0:
		contamination = 'auto'
	clf =  IsolationForest(max_samples=samples,	n_estimators=estimators,
		contamination=contamination, random_state=42)

	# load our csv to df
	f = StringIO(inputDict["file"])
	df = pd.read_csv(f)
	datapoints = df.to_numpy()

	maxVals = np.max(datapoints, axis=0)
	maxVals = np.tile( maxVals, (datapoints.shape[0],1) )
	normalizedDatapoints = np.divide(datapoints,maxVals)

	labels = clf.fit_predict(normalizedDatapoints)
	scores = clf.score_samples(normalizedDatapoints)

	plotData = []
	x = np.arange(0,datapoints.shape[0])
	data = go.Scatter( x=x, y=datapoints[:,0], name='data', mode='lines+markers' )
	plotData.append(data)
	outliers = go.Scatter( x=x[labels!=1], y=datapoints[labels!=1, 0], name='outliers',
		mode='markers' )
	plotData.append(outliers)

	return plotData

def workSAX(modelDir, inputDict):
	'''
	Create SAX model, and its respective scatterplot.
	params:
	type modelDir: str, path to the directory in which the model is located?
	type inputDict: dictionary,{
								'windowSize': number of data points to consider for the normalization process,
								'alphabetSize': rhe number of symbols to use in representation,
								'file': csv file of data
								}

	rtype plotData: list, containinng scatter plot of original input data and predicted anomalous points.
	'''
	def cuts_for_asize(a_size):
		"""Generate a set of alphabet cuts for its size."""

		options = {
			2: np.array([-np.inf,  0.00]),
			3: np.array([-np.inf, -0.4307273, 0.4307273]),
			4: np.array([-np.inf, -0.6744898, 0, 0.6744898]),
			5: np.array([-np.inf, -0.841621233572914, -0.2533471031358,
						0.2533471031358, 0.841621233572914]),
			6: np.array([-np.inf, -0.967421566101701, -0.430727299295457, 0,
						0.430727299295457, 0.967421566101701]),
			7: np.array([-np.inf, -1.06757052387814, -0.565948821932863,
						-0.180012369792705, 0.180012369792705, 0.565948821932863,
						1.06757052387814]),
			8: np.array([-np.inf, -1.15034938037601, -0.674489750196082,
						-0.318639363964375, 0, 0.318639363964375,
						0.674489750196082, 1.15034938037601]),
			9: np.array([-np.inf, -1.22064034884735, -0.764709673786387,
						-0.430727299295457, -0.139710298881862, 0.139710298881862,
						0.430727299295457, 0.764709673786387, 1.22064034884735]),
			10: np.array([-np.inf, -1.2815515655446, -0.841621233572914,
						 -0.524400512708041, -0.2533471031358, 0, 0.2533471031358,
						 0.524400512708041, 0.841621233572914, 1.2815515655446]),
			11: np.array([-np.inf, -1.33517773611894, -0.908457868537385,
						 -0.604585346583237, -0.348755695517045,
						 -0.114185294321428, 0.114185294321428, 0.348755695517045,
						 0.604585346583237, 0.908457868537385, 1.33517773611894]),
			12: np.array([-np.inf, -1.38299412710064, -0.967421566101701,
						 -0.674489750196082, -0.430727299295457,
						 -0.210428394247925, 0, 0.210428394247925,
						 0.430727299295457, 0.674489750196082, 0.967421566101701,
						 1.38299412710064]),
			13: np.array([-np.inf, -1.42607687227285, -1.0200762327862,
						 -0.736315917376129, -0.502402223373355,
						 -0.293381232121193, -0.0965586152896391,
						 0.0965586152896394, 0.293381232121194, 0.502402223373355,
						 0.73631591737613, 1.0200762327862, 1.42607687227285]),
			14: np.array([-np.inf, -1.46523379268552, -1.06757052387814,
						 -0.791638607743375, -0.565948821932863, -0.36610635680057,
						 -0.180012369792705, 0, 0.180012369792705,
						 0.36610635680057, 0.565948821932863, 0.791638607743375,
						 1.06757052387814, 1.46523379268552]),
			15: np.array([-np.inf, -1.50108594604402, -1.11077161663679,
						 -0.841621233572914, -0.622925723210088,
						 -0.430727299295457, -0.2533471031358, -0.0836517339071291,
						 0.0836517339071291, 0.2533471031358, 0.430727299295457,
						 0.622925723210088, 0.841621233572914, 1.11077161663679,
						 1.50108594604402]),
			16: np.array([-np.inf, -1.53412054435255, -1.15034938037601,
						 -0.887146559018876, -0.674489750196082,
						 -0.488776411114669, -0.318639363964375,
						 -0.157310684610171, 0, 0.157310684610171,
						 0.318639363964375, 0.488776411114669, 0.674489750196082,
						 0.887146559018876, 1.15034938037601, 1.53412054435255]),
			17: np.array([-np.inf, -1.5647264713618, -1.18683143275582,
						 -0.928899491647271, -0.721522283982343,
						 -0.541395085129088, -0.377391943828554,
						 -0.223007830940367, -0.0737912738082727,
						 0.0737912738082727, 0.223007830940367, 0.377391943828554,
						 0.541395085129088, 0.721522283982343, 0.928899491647271,
						 1.18683143275582, 1.5647264713618]),
			18: np.array([-np.inf, -1.59321881802305, -1.22064034884735,
						 -0.967421566101701, -0.764709673786387,
						 -0.589455797849779, -0.430727299295457,
						 -0.282216147062508, -0.139710298881862, 0,
						 0.139710298881862, 0.282216147062508, 0.430727299295457,
						 0.589455797849779, 0.764709673786387, 0.967421566101701,
						 1.22064034884735, 1.59321881802305]),
			19: np.array([-np.inf, -1.61985625863827, -1.25211952026522,
						 -1.00314796766253, -0.8045963803603, -0.633640000779701,
						 -0.47950565333095, -0.336038140371823, -0.199201324789267,
						 -0.0660118123758407, 0.0660118123758406,
						 0.199201324789267, 0.336038140371823, 0.47950565333095,
						 0.633640000779701, 0.8045963803603, 1.00314796766253,
						 1.25211952026522, 1.61985625863827]),
			20: np.array([-np.inf, -1.64485362695147, -1.2815515655446,
						 -1.03643338949379, -0.841621233572914, -0.674489750196082,
						 -0.524400512708041, -0.385320466407568, -0.2533471031358,
						 -0.125661346855074, 0, 0.125661346855074, 0.2533471031358,
						 0.385320466407568, 0.524400512708041, 0.674489750196082,
						 0.841621233572914, 1.03643338949379, 1.2815515655446,
						 1.64485362695147]),
		}

		return options[a_size]

	def znorm(series, znorm_threshold=0.01):
		"""Znorm implementation."""

		sd = np.std(series)
		if (sd < znorm_threshold):
			return series

		return (series - np.mean(series)) / sd

	def idx2letter(idx):
		"""Convert a numerical index to a char."""

		if 0 <= idx <= 20:
			return chr(96 + idx)
		else:
			raise ValueError('A wrong idx value supplied.')

	def ts_to_string(series, cuts):
		"""A straightforward num-to-string conversion."""

		sax = list()
		for i in range(0, len(series)):

			j = np.searchsorted(cuts,series[i])
			sax.append(idx2letter(j))

		return ''.join(sax)

	def getSaxString(series, win_size, alphabet_size=3, z_threshold=0.01):
		"""Simple via window conversion implementation."""

		cuts = cuts_for_asize(alphabet_size)

		saxString = ''
		for i in range(0, len(series) - win_size):

			sub_section = series[i:(i+win_size)]
			zn = znorm(sub_section, z_threshold)
			curr_word = ts_to_string(zn, cuts)
			saxString += ' ' + curr_word

		return saxString.strip()

	def makeReplacement(stringArray, encodingGrammar, decodingGrammar, ruleNum, occurances):

		ruleString = str(ruleNum)

		# go through each letter in the seq
		for i in range(len(stringArray)-1):

			# print('-------------------------------')
			# print('str: ', stringArray)
			# print('enc:' , encodingGrammar)
			# print('dec:' , decodingGrammar)
			# print('occ:' , occurances)

			# make a digram
			digram = ' '.join(stringArray[i:i+2])

			#print(digram)

			# if digram not in dict, add to dict
			rule = encodingGrammar.get(digram)
			if rule is None:
				encodingGrammar[digram] = ''

			# else if digram in dict, but no rule
			elif rule == '':

				# make rule
				encodingGrammar[digram] = ruleString
				decodingGrammar[ruleString] = digram

				# keep track of the locations of characters
				for letter in digram.split(' '):

					locations = occurances.get(letter)
					if locations is None:
						occurances[letter] = [ruleString]
					else:
						occurances[letter].append( ruleString )

				# replace all occurances of digram with rule, recursive call

				stringSeq = ' '.join(stringArray)
				stringSeq = stringSeq.replace(digram,ruleString)
				stringArray = stringSeq.split(' ')
				ruleNum += 1

				return ( stringArray, encodingGrammar, decodingGrammar, ruleNum,
					occurances )

		return ( stringArray, encodingGrammar, decodingGrammar, ruleNum,
					occurances )

	def sequitur(stringArray, encodingGrammar, decodingGrammar, ruleNum, occurances):

		ruleString = str(ruleNum)
		while len(stringArray) > 1:

			( stringArray, encodingGrammar, decodingGrammar, ruleNum,
			occurances ) = makeReplacement(stringArray, encodingGrammar,
			decodingGrammar, ruleNum, occurances)

		# when length of seq string is 1
		# enforce rule utility
		toDelete = set([])
		for key in occurances.keys():

			numOccurances = len(occurances[key])
			if numOccurances == 1:

				rule = decodingGrammar.get(key)
				if rule is not None:
					replaceLocation = occurances[key][0]
					stringToReplace = decodingGrammar[replaceLocation]
					decodingGrammar[replaceLocation] = stringToReplace.replace(key,rule)
					toDelete.add(key)

		for key in toDelete:
			del decodingGrammar[key]

		return (stringArray, decodingGrammar)

	def findAll( mainString, substring ):

		locations = []
		startPoint = 0

		while True:

			firstLocation = mainString.find(substring, startPoint )
			if firstLocation == -1:
				break
			else:
				index = mainString[:firstLocation].count(' ')
				locations.append(index)
				startPoint = firstLocation + 1

		return locations

	def getCounts(stringSeq, decodingGrammar):

		repeats = np.zeros([len(stringSeq.split(' ')),1])
		occurances = {}

		numReplacements = 1
		while numReplacements != 0:
			numReplacements = 0
			for key in list(decodingGrammar.keys()):
				value = decodingGrammar[key]
				for word in value.split(' '):
					replacement = decodingGrammar.get(word)
					if replacement is not None:
						numReplacements += 1
						decodingGrammar[key] = value.replace(word, replacement)

		originalAlphabet = list(set(stringSeq))
		for letter in originalAlphabet:
			if letter != ' ':
				decodingGrammar[letter] = letter

		for key in decodingGrammar.keys():
			value = decodingGrammar[key]
			occurances[value] = findAll(stringSeq,decodingGrammar[key])
			for location in occurances[value]:
					repeats[location] += len(occurances[value])

		# the occurance of the whole string is also counted above,
		# so remove this count from the total
		repeats[0] -= 1

		return (repeats, occurances)


	# load our csv to df
	f = StringIO(inputDict["file"])
	df = pd.read_csv(f, header=None)
	datapoints = df.to_numpy()

	maxVals = np.max(datapoints, axis=0)
	maxVals = np.tile( maxVals, (datapoints.shape[0],1) )
	normalizedDatapoints = np.divide(datapoints,maxVals)
	normalizedDatapoints = normalizedDatapoints[:,0]

	windowSize = int(inputDict['windowSize'])
	alphabetSize = int(inputDict['alphabetSize'])

	saxString = getSaxString(normalizedDatapoints, windowSize,
		alphabet_size=alphabetSize, z_threshold=0.01)
	saxArray = saxString.split(' ')

	sys.setrecursionlimit(1000)
	(saxArray, decodingGrammar) = sequitur(saxArray, {}, {}, 0, {})
	(repeats, occurances) = getCounts(saxString, decodingGrammar)

	plotData = []
	x = np.arange(0,datapoints[:len(repeats),0].shape[0])
	data = go.Bar(x=x, y=datapoints[:len(repeats),0],
		marker={'color': repeats[:,0], 'colorbar': {'title': 'repeats'},
		'colorscale': 'thermal', 'showscale':True})
	plotData.append(data)
	return plotData

def work(modelDir, inputDict):
	""" Model processing done here. """
	outData = {}
	outData = workProphet(modelDir, inputDict)
	plotData = workLof(modelDir, inputDict)
	outData['plotLof'] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
	plotData = workIso(modelDir, inputDict)
	outData['plotIso'] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
	plotData = workSAX(modelDir, inputDict)
	outData['plotSax'] = json.dumps(plotData, cls=plotly.utils.PlotlyJSONEncoder)
	return outData

def runtimeEstimate(modelDir):
	''' Estimated runtime of model in minutes. '''
	return 8.5

def new(modelDir):
	""" Create a new instance of this model. Returns true on success, false on failure. """
	fName = "ERCOT_south_shortened.csv"
	with open(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", fName)) as f:
		file_ = f.read()
	defaultInputs = {
		"created": "2015-06-12 17:20:39.308239",
		"modelType": modelName,
		"file": file_,
		"fileName": fName,
		"confidence": "0.99",
		"norm_confidence": "0.90",
		"startDate": "2002-01-01",
		"contaminationLof": "0",
		"contaminationIso": "0",
		"neighbors": "20",
		"estimators": "100",
		"samples":"0.1",
		"alphabetSize":"9",
		"windowSize":"12",
		"demandTempBool":"True"
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)


def _debugging():
	modelLoc = pJoin(
		__neoMetaModel__._omfDir,
		"data",
		"Model",
		"admin",
		"Automated Testing of " + modelName,
	)
	# Blow away old test results if necessary.
	if isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc)  # Create New.
	__neoMetaModel__.runForeground(modelLoc)  # Run the model.
	__neoMetaModel__.renderAndShow(modelLoc)  # Show the output.


if __name__ == "__main__":
	_debugging()
