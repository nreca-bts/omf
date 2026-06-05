"""
The forecastTool model attempts to predict the next day’s electric consumption.
Furthermore, it attempts to place tomorrow's peak in a monthly context, giving the
statistical likelihood that tomorrow will be the monthly peak.
"""

import shutil, base64
from datetime import datetime as dt, timedelta
from os.path import isdir, join as pJoin
import pandas as pd
import numpy as np
from scipy.stats import norm
from omf import forecast as lf
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "This model predicts whether the following day will be a monthly peak."

def peak_likelihood(hist=None, tomorrow=None, tomorrow_std=None, two_day=None, two_day_std=None, three_day=None, three_day_std=None):
	"""
	Perform peak likelihood processing for the forecast tool model.
	"""
	A = norm(tomorrow, tomorrow_std).cdf(hist)
	B = norm(0, 1).cdf(-(tomorrow - two_day) / ((tomorrow_std**2 + two_day_std**2)**.5))
	C = norm(0, 1).cdf(-(tomorrow - three_day) / ((tomorrow_std**2 + three_day_std**2)**.5))
	return round((1 - A)*(1 - B)*(1 - C)*100, 2)

def highest_peak_this_month(df, predicted_day):
	"""
	Perform highest peak this month processing for the forecast tool model.
	"""
	y = predicted_day.year
	m = predicted_day.month
	d = predicted_day.day
	return_v = df[(df['year'] == y) & (df['month'] == m) & (df['day'] != d)]['load'].max()
	return 0 if np.isnan(return_v) else return_v

def work(modelDir, ind):
	''' Model processing done here. '''
	import tensorflow as tf
	epochs = int(ind['epochs'])
	o = {}  # See bottom of file for out's structure
	try:
		with open(pJoin(modelDir, 'hist.csv'), 'w') as f:
			f.write(ind['histCurve'].replace('\r', ''))
		df = pd.read_csv(pJoin(modelDir, 'hist.csv'))
		assert df.shape[0] >= 26280, 'At least 3 years of data is required'

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
		raise Exception("Load CSV file is incorrect format.")

	try:
		weather = [float(i) for i in ind['tempCurve'].split('\n') if i != '']
		assert len(weather) == 72, "weather csv in wrong format"
	except:
		raise Exception(ind['tempCurve'])

	# ---------------------- MAKE PREDICTIONS ------------------------------- #

	df = df.sort_values(by='dates')
	# df = autofill(df)
	d = dict(df.groupby(df.dates.dt.date)['dates'].count())
	df = df[df['dates'].dt.date.apply(lambda x: d[x] == 24)] # find all non-24

	df, tomorrow = lf.add_day(df, weather[:24])
	all_X, all_y = lf.makeUsefulDf(df, structure="3D")

	if ind['newModel'] == 'False':
		for day in ['one_day_model', 'two_day_model', 'three_day_model']:
			with open(pJoin(modelDir, ind[day+'_filename']), 'wb') as f:
					f.write(base64.standard_b64decode(ind[day]))
	
	tomorrow_load, model, tomorrow_accuracy = lf.neural_net_next_day(
		all_X, all_y, 
		epochs=epochs, save_file=pJoin(modelDir, 'one_day_model.h5'),
		model=(None if ind['newModel'] == 'True' else tf.keras.models.load_model(pJoin(modelDir, ind['one_day_model_filename']))),
		structure="3D"
	)

	o['tomorrow_load'] = tomorrow_load
	o['month_start'] = dt(tomorrow.year, tomorrow.month, 1).strftime("%A, %B %-d, %Y")
	o['forecast_start'] = tomorrow.strftime("%A, %B %-d, %Y")
	
	# second day
	df, second_day = lf.add_day(df, weather[24:48])
	if second_day.month == tomorrow.month:
		all_X, all_y = lf.makeUsefulDf(df, hours_prior=48, noise=5, structure="3D")
		two_day_predicted_load, two_day_model, two_day_load_accuracy = lf.neural_net_next_day(
			all_X, all_y, 
			epochs=epochs, hours_prior=48, 
			save_file=pJoin(modelDir, 'two_day_model.h5'),
			model=(None if ind['newModel'] == 'True' else tf.keras.models.load_model(pJoin(modelDir, ind['two_day_model_filename']))),
			structure="3D"
		)
		two_day_peak = max(two_day_predicted_load)

		# third day
		df, third_day = lf.add_day(df, weather[48:72])
		if third_day.month == tomorrow.month:
			all_X, all_y = lf.makeUsefulDf(df, hours_prior=72, noise=15, structure="3D")
			three_day_predicted_load, three_day_model, three_day_load_accuracy = lf.neural_net_next_day(
				all_X, all_y, 
				epochs=epochs, hours_prior=72, 
				save_file=pJoin(modelDir, 'three_day_model.h5'),
				model=(None if ind['newModel'] == 'True' else tf.keras.models.load_model(pJoin(modelDir, ind['three_day_model_filename']))),
				structure="3D"
			)
			three_day_peak = max(three_day_predicted_load)
		else:
			three_day_peak = 0
			three_day_load_accuracy = {'test': np.nan, 'train': np.nan}
			three_day_predicted_load = []
			
	else:
		two_day_peak = 0
		two_day_load_accuracy = {'test': np.nan, 'train': np.nan}
		two_day_predicted_load = []
		three_day_peak = 0
		three_day_load_accuracy = {'test': np.nan, 'train': np.nan}
		three_day_predicted_load = []

	tomorrow_peak = max(tomorrow_load)
	m = df[(df['month'] == tomorrow.month) & (df['year'] != tomorrow.year) ]
	hourly = m
	m = m.groupby(m.dates.dt.date)['load'].max()
	o['quantile'] = round(m[m < tomorrow_peak].shape[0]/float(m.shape[0])*100, 2)
	o['predicted_peak'] = [m.median(), highest_peak_this_month(df, tomorrow), tomorrow_peak, two_day_peak, three_day_peak]
	o['predicted_peak_limits'] = [
		[m.min(), m.max()],
		[0, 0],
		[tomorrow_peak*(1 + tomorrow_accuracy['test']*.01), tomorrow_peak*(1 - tomorrow_accuracy['test']*.01)],
		[two_day_peak*(1 + two_day_load_accuracy['test']*.01), two_day_peak*(1 - two_day_load_accuracy['test']*.01)],
		[three_day_peak*(1 + three_day_load_accuracy['test']*.01), three_day_peak*(1 - three_day_load_accuracy['test']*.01)]
	]
	m = hourly
	previous_months = [{
		'year': y,
		'load': m[m['year'] == y]['load'].tolist()
	} for y in m.year.unique()]

	# ---------------------- FORMAT FOR DISPLAY ------------------------------- #
	l = []
	for d in previous_months:
		l.append({
			'name': d['year'].item(),
			'color': 'lightgrey',
			'data': d['load'],
			'type': 'line',
			'opacity': .05,
			'enableMouseTracking': False
		})

	all_load = tomorrow_load + two_day_predicted_load + three_day_predicted_load
	load_leading_up = df[(df['month'] == tomorrow.month) & (df['year'] == tomorrow.year)]['load'].tolist()
	l.append({'name': tomorrow.year, 'color': 'black', 'data': load_leading_up[:-72], 'type': 'line'})
	l.append({'name':'forecast','color':'blue', 'data': [None]*(len(load_leading_up) - 72) + all_load, 'type': 'line', 'zIndex': 5 })

	# add uncertainty
	uncertainty = [2.02, 2.41, 2.78, 2.91, 3.48, 4.02, 4.2, 3.96, 3.63, 3.68, 4.19, 4.45, 4.77, 4.94, 4.79, 5.22, 5.58, 5.32, 5.44, 4.85, 5.05, 5.51, 5.71, 5.96, 7.84, 8.44, 8.96, 9.06, 8.81, 8.53, 8.4, 8.06, 7.33, 6.5, 6.15, 6.23, 6.43, 6.34, 6.84, 6.76, 7.17, 7.2, 6.93, 6.83, 6.71, 7.39, 8.49, 9.24, 9.36, 10.64, 9.95, 9.4, 9.6, 9.28, 8.52, 8.78, 8.71, 8.59, 8.34, 8.81, 9.12, 9.53, 10.3, 10.67, 10.89, 10.47, 9.67, 8.95, 8.79, 9.18, 9.92, 10.25]
	print(tomorrow_accuracy['test'])
	l.append({
		'name': 'uncertainty',
		'color': '#b3b3ff',
		'data': [None]*(len(load_leading_up) - 72) + [x*u*.01*2 for u, x in zip(uncertainty, all_load)],
	})

	l.append({
		'id': 'transparent',
		'color': 'rgba(255,255,255,0)',
		'data': [None]*(len(load_leading_up) - 72) + [x*(1-u*.01) for u, x in zip(uncertainty, all_load)]
	})
	

	o['previous_months'] = l

	o['load_test_accuracy'] = round(tomorrow_accuracy['test'], 2)
	o['load_train_accuracy'] = round(tomorrow_accuracy['train'], 2)
	o['tomorrow_test_accuracy'] = round(tomorrow_accuracy['test'], 2)
	o['tomorrow_train_accuracy'] = round(tomorrow_accuracy['train'], 2)
	o['two_day_peak_train_accuracy'] = round(two_day_load_accuracy['train'], 2)
	o['two_day_peak_test_accuracy'] = round(two_day_load_accuracy['test'], 2)
	o['three_day_peak_train_accuracy'] = round(three_day_load_accuracy['train'], 2)
	o['three_day_peak_test_accuracy'] = round(three_day_load_accuracy['test'], 2)


	o['peak_percent_chance'] = peak_likelihood(
		hist=highest_peak_this_month(df[:-48], tomorrow), 
		tomorrow=tomorrow_peak,
		tomorrow_std=tomorrow_peak*tomorrow_accuracy['test']*.01,
		two_day=two_day_peak,
		two_day_std=two_day_peak*two_day_load_accuracy['test']*.01,
		three_day=three_day_peak,
		three_day_std=three_day_peak*three_day_load_accuracy['test']*.01
	)

	o['stderr'] = ''

	with open(pJoin(modelDir,'one_day_model.h5'), 'rb') as f:
		one_day_model = base64.standard_b64encode(f.read()).decode()
	with open(pJoin(modelDir,'two_day_model.h5'), 'rb') as f:
		two_day_model = base64.standard_b64encode(f.read()).decode()
	with open(pJoin(modelDir,'three_day_model.h5'), 'rb') as f:
		three_day_model = base64.standard_b64encode(f.read()).decode()

	# re-input values (i.e. modify the mutable dictionary that is used in heavyprocessing!!!!!!)
	ind['newModel'] = 'False',
	ind['one_day_model'] = one_day_model,
	ind['one_day_model_filename'] = 'one_day_model.h5',
	ind['two_day_model'] = two_day_model,
	ind['two_day_model_filename'] = 'two_day_model.h5',
	ind['three_day_model'] = three_day_model,
	ind['three_day_model_filename'] = 'three_day_model.h5',

	return o

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","72hr_TexasTemp.csv")) as f:
		temp_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,"static","testFiles","Texas_1pm.csv")) as f:
		hist_curve = f.read()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','one_day_model.h5'), 'rb') as f:
		one_day_model = base64.standard_b64encode(f.read()).decode()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','two_day_model.h5'), 'rb') as f:
		two_day_model = base64.standard_b64encode(f.read()).decode()
	with open(pJoin(__neoMetaModel__._omfDir,'static','testFiles','three_day_model.h5'), 'rb') as f:
		three_day_model = base64.standard_b64encode(f.read()).decode()

	defaultInputs = {
		'created': '2015-06-12 17:20:39.308239',
		'modelType': modelName,
		'runTime': '0:01:03',
		'epochs': '20',
		'tempFileName': '72hr_TexasTemp.csv',
		'tempCurve': temp_curve,
		# autofill
		'histFileName': 'Texas_tiny.csv',
		"histCurve": hist_curve,
		# upload models
		'newModel': 'False',
		'one_day_model': one_day_model,
		'one_day_model_filename': 'one_day_model.h5',
		'two_day_model': two_day_model,
		'two_day_model_filename': 'two_day_model.h5',
		'three_day_model': three_day_model,
		'three_day_model_filename': 'three_day_model.h5',
	}
	return __neoMetaModel__.new(modelDir, defaultInputs)

@neoMetaModel_test_setup
def _tests():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
	# Blow away old test results if necessary.
	if isdir(modelLoc):
		shutil.rmtree(modelLoc)	
	new(modelLoc)  # Create New.
	__neoMetaModel__.renderAndShow(modelLoc)  # Pre-run.
	__neoMetaModel__.runForeground(modelLoc)  # Run the model.
	__neoMetaModel__.renderAndShow(modelLoc)  # Show the output.

if __name__ == '__main__':
	_tests()
