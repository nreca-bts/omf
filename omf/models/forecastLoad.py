"""
The various load forecasters in forecastLoad take in some combination of forecasted
temperature, date, and historical demand data to predict future demand data.
"""
import json
from os.path import join as pJoin
from datetime import datetime as dt
import numpy as np
import pandas as pd
from omf import forecast as loadForecast
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Forecasts hourly load day-ahead using multiple methods"
hidden = False


def work(modelDir, inputDict):
	""" Run the model in its directory."""
	outData = {}
	rawData = []
	actual = []

	# write input file to modelDir sans carriage returns
	with open(pJoin(modelDir, "demandTemp.csv"), "w") as demandTempFile:
		demandTempFile.write(inputDict["demandTemp"].replace("\r", ""))

	try:
		with open(pJoin(modelDir, 'hist.csv'), 'w') as f:
			f.write(inputDict['nn'].replace('\r', ''))
		df = pd.read_csv(pJoin(modelDir, 'hist.csv'))
		assert df.shape[0] >= 26280 # must be longer than 3 years
		if 'dates' not in df.columns:
			df['dates'] = df.apply(
				lambda x: dt(
					int(x['year']), 
					int(x['month']), 
					int(x['day']), 
					int(x['hour'])), 
				axis=1
			)
	except:
		raise Exception("Neural Net CSV file is incorrect format.")

	# neural net time
	all_X, all_y = loadForecast.makeUsefulDf(df)
	nn_pred, nn_accuracy = loadForecast.neural_net_predictions(all_X, all_y)
	outData["actual_nn"] = df['load'][-8760:].tolist()

	# read it in as a list of lists
	try:
		with open(pJoin(modelDir, "demandTemp.csv")) as inFile:
			df = pd.read_csv(inFile, header=None)
			df.columns = ["load", "tempc"]
			df["dates"] = pd.date_range(
				start=inputDict["simStartDate"], freq="H", periods=df.shape[0]
			)
			print(df.shape[0])
	except ZeroDivisionError:
		errorMessage = "CSV file is incorrect format. Please see valid format definition at <a target='_blank' href = 'https://github.com/dpinney/omf/wiki/Models-~-storagePeakShave#demand-file-csv-format'>\nOMF Wiki storagePeakShave - Demand File CSV Format</a>"
		raise Exception(errorMessage)


	rawData = df[["load", "tempc"]].fillna(0).values.tolist()
	del df

	"""
	# None -> 0, float-> string
	for i in range(len(rawData)):
		rawData[i] = [a if a else 0 for a in rawData[i]]
	rawData = list(np.float_(rawData))
	"""

	# populate actual list
	for x in range(len(rawData)):
		actual.append(float(rawData[x][0]))

	(forecasted, MAPE) = loadForecast.rollingDylanForecast(
		rawData, float(inputDict["upBound"]), float(inputDict["lowBound"])
	)

	(exp, exp_MAPE) = loadForecast.exponentiallySmoothedForecast(
		rawData, float(inputDict["alpha"]), float(inputDict["beta"])
	)

	# parse json params for nextDayPeakKatrina
	try:
		params = json.loads(inputDict.get("katSpec", "{}"))
	except ValueError:
		params = {}

	pred_demand = loadForecast.nextDayPeakKatrinaForecast(
		rawData, inputDict["simStartDate"], modelDir, params
	)
	pred_demand = np.transpose(np.array(pred_demand)).tolist()

	# zucc it up
	prophet_partitions = int(inputDict.get("prophet", 0))
	if prophet_partitions > 1:
		prophet, prophet_low, prophet_high = loadForecast.prophetForecast(
			rawData, inputDict["simStartDate"], modelDir, inputDict["prophet"]
		)

		# write our outData
	outData["startDate"] = inputDict["simStartDate"]
	outData["actual"] = actual
	outData["forecasted"] = forecasted
	outData["doubleExp"] = exp
	outData["neuralNet"] = nn_pred
	outData["MAPE"] = "%0.2f%%" % (MAPE*100)
	outData["MAPE_exp"] = "%0.2f%%" % (exp_MAPE*100)
	outData["MAPE_nn"] = "%0.2f%%" % nn_accuracy["test"]
	outData["peakDemand"] = pred_demand
	if prophet_partitions > 1:
		outData["prophet"] = prophet
		outData["prophetLow"] = prophet_low
		outData["prophetHigh"] = prophet_high
	return outData


def new(modelDir):
	""" Create a new instance of this model. Returns true on success, false on failure. """
	with open(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", "d_Texas_17yr_TempAndLoad.csv")) as f:
		nn = f.read()
	with open(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", "ERCOT_south_shortened.csv")) as f:
		demand_temp = f.read()
	defaultInputs = {
		"user": "admin",
		"demandTemp": demand_temp,
		"fileName": "ERCOT_south_shortened.csv",
		"nn": nn,
		"nnFileName": "d_Texas_17yr_TempAndLoad.csv",
		"lowBound": 0.95,
		"upBound": 1.05,
		"rollingWindow": 4,
		"alpha": 0.95,
		"beta": 0.05,
		"simStartDate": "2002-01-01",
		"modelType": modelName,
		"prophet": 0
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	return creationCode


def _debugging():
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
	try:
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
		# Create New.
	new(modelLoc)
	# Pre-run.
	# renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)


if __name__ == "__main__":
	_debugging()