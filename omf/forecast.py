"""
This contains the loadForecast algorithms

"""

import math, pulp
import numpy as np
import pandas as pd
import os
from os.path import join as pJoin
import datetime
from datetime import datetime as dt
from datetime import timedelta, date
from sklearn.model_selection import GridSearchCV
import pickle
from scipy.stats import zscore


class suppress_stdout_stderr(object):
	"""
	A context manager for doing a "deep suppression" of stdout and stderr in
	Python, i.e. will suppress all print, even if the print originates in a
	compiled C/Fortran sub-function.
	   This will not suppress raised exceptions, since exceptions are printed
	to stderr just before a script exits, and after the context manager has
	exited (at least, I think that is why it lets exceptions through).
	"""

	def __init__(self):
		# Open a pair of null files
		self.null_fds = [os.open(os.devnull, os.O_RDWR) for x in range(2)]
		# Save the actual stdout (1) and stderr (2) file descriptors.
		self.save_fds = (os.dup(1), os.dup(2))

	def __enter__(self):
		# Assign the null pointers to stdout and stderr.
		os.dup2(self.null_fds[0], 1)
		os.dup2(self.null_fds[1], 2)

	def __exit__(self, *_):
		# Re-assign the real stdout/stderr back to (1) and (2)
		os.dup2(self.save_fds[0], 1)
		os.dup2(self.save_fds[1], 2)
		# Close the null files
		os.close(self.null_fds[0])
		os.close(self.null_fds[1])


# source: https://www.energygps.com/HomeTools/PowerCalendar
nercHolidays = {
	dt(2019, 1, 1): "New Years",
	dt(2019, 5, 27): "Memorial",
	dt(2019, 7, 4): "Independence",
	dt(2019, 9, 2): "Labor",
	dt(2019, 11, 28): "Thanksgiving",
	dt(2019, 12, 25): "Christmas",
	dt(2020, 1, 1): "New Years",
	dt(2020, 5, 25): "Memorial",
	dt(2020, 7, 4): "Independence",
	dt(2020, 9, 7): "Labor",
	dt(2020, 11, 26): "Thanksgiving",
	dt(2020, 12, 25): "Christmas",
	dt(2021, 1, 1): "New Years",
	dt(2021, 5, 31): "Memorial",
	dt(2021, 7, 5): "Independence",
	dt(2021, 9, 6): "Labor",
	dt(2021, 11, 25): "Thanksgiving",
	dt(2021, 12, 25): "Christmas",
}

_default_params = {
	"peakSize": {"C": 10000, "epsilon": 0.25, "gamma": 0.0001},
	"peakTimeClassifier": {"C": 10, "gamma": 0.001},
	"peakTimeRegressorMorning": {"C": 10, "epsilon": 0.05, "gamma": 0.1},
	"peakTimeRegressorAfternoon": {"C": 10, "epsilon": 0.25, "gamma": 0.1},
}


def rollingDylanForecast(rawData, upBound, lowBound, rolling_window=5, hist_window=8):
	"""
	This model takes the inputs rawData, a dataset that holds 8760 values in two columns with no indexes
	The first column rawData[:][0] holds the hourly demand for one year
	The second column rawData[:][1] holds the hourly temperature for one year
	upBound is the upper limit for forecasted data to not exceed as sometimes the forecasting is wonky
	lowBound is the lower limit for forecasted data to not exceed as sometimes the forecasting is wonky
	when values exceed upBound or go below lowBound they are set to None
	"""
	forecasted = np.repeat(np.nan, 168 * rolling_window)
	rawData = np.asarray(rawData)
	actual = rawData[:, 0]
	temps = rawData[:, 1]
	for w in range(168 * rolling_window, len(rawData)):
		# need to start at 4 weeks+1 hour to get enough data to train so 4*7*24 = 672, the +1 is not necessary due to indexing starting at 0
		training_indices = [w - 168 * (i + 1) for i in range(rolling_window)]
		x = temps[training_indices]
		y = actual[training_indices]
		z = np.polyfit(x, y, 1)
		p = np.poly1d(z)
		# goodbye out of bounds
		hist_indices = [w - 168 * (i + 1) for i in range(rolling_window)]
		hist_data = actual[hist_indices]
		hist_min = np.min(hist_data)
		hist_max = np.max(hist_data)
		floor = lowBound * hist_min
		ceiling = upBound * hist_max
		# make our prediction
		pred = float(p(temps[w]))
		pred = pred if pred > floor else floor
		pred = pred if pred < ceiling else ceiling
		forecasted = np.append(forecasted, pred)
	MAPE = np.nanmean(np.abs(forecasted - actual)/actual)
	nan_indices = np.where(np.isnan(forecasted))
	forecasted = forecasted.tolist()
	for i in nan_indices[0]:
		forecasted[i] = None
	return (forecasted, MAPE)


def exponentiallySmoothedForecast(rawData, alpha, beta):
	"""
	This model takes the inputs rawData, a dataset that holds 8760 values in two columns with no indexes
	The first column rawData[:][0] holds the hourly demand for one year
	The second column rawData[:][1] holds the hourly temperature for one year
	"""
	forecasted = [None] * 2 * 24
	actual = [rawData[i][0] for i in range(2 * 24)]
	smotted = [None] * 2 * 24
	tronds = [None] * 2 * 24

	# initialize the boi

	for w in range(2 * 24, len(rawData)):
		# need to start at 4 weeks+1 hour to get enough data to train so 4*7*24 = 672, the +1 is not necessary due to indexing starting at 0
		actual.append((rawData[w][0]))
		old_smot = (
			smotted[w - 24]
			if smotted[w - 24]
			else np.mean([actual[w - 24], actual[w - 2 * 24]])
		)
		old_trond = (
			tronds[w - 24] if tronds[w - 24] else (actual[w - 24] - actual[w - 2 * 24])
		)
		lovel = alpha * actual[w - 24] + (1 - alpha) * old_smot
		trond = beta * (lovel - old_smot + old_trond) + (1 - beta) * old_trond
		smot = lovel + trond
		tronds.append(trond)
		smotted.append(smot)
		forecasted.append(smot)
	MAPE = 0  # Mean Average Error calculation
	denom = 0
	for i in range(len(forecasted)):
		if forecasted[i] != None:
			MAPE += abs(forecasted[i] - actual[i])/actual[i]
			denom += 1
	MAPE = MAPE / denom
	return (forecasted, MAPE)
	"""
	forecasted is an 8760 list of demand values
	MAPE is an int and is the mean average error of the forecasted/actual data correlation
	"""


def nextDayPeakKatrinaForecast(
	rawData, startDate, modelDir, params, returnActuals=False
):
	"""
	This model takes the inputs rawData, a dataset that holds hourly values in two columns with no indexes
	The first column rawData[:][0] holds the hourly demand
	The second column rawData[:][1] holds the hourly temperature
	modelDir is the directory the model is running in, for the purposes of having somewhere to write the df

	The model returns a tuple of two python lists. 
	The first list of the tuple contains ISO formatted datetime strings of the daily predicted peak times,
	the second list of the tuple contains floats of daily predicted peak demand.
	"""
	from sklearn.model_selection import cross_val_predict
	from sklearn.svm import SVR

	# loading rawData into pandas
	datetime_index = pd.date_range(start=startDate, periods=len(rawData), freq="H")
	input_df = pd.DataFrame(rawData, index=datetime_index)
	input_df.columns = ["demand", "tdy_temp"]
	input_df.to_csv(pJoin(modelDir, "indata.csv"))
	daily_dti = datetime_index.floor("D").unique()
	df = pd.DataFrame(index=daily_dti)

	# finessing the date
	df["tdy_weekend"] = (daily_dti.weekday == 5) | (daily_dti.weekday == 6)
	df["tmr_weekend"] = df.tdy_weekend.shift(-1)

	# finessing the temp
	tmp = input_df.tdy_temp.resample("D").mean()
	df["tdy_temp"] = tmp
	df["tmr_temp"] = tmp.shift(-1)

	# finessing the demand
	de = input_df.demand.resample("H").mean()
	peak_demand = de.resample("D").max()
	peak_time = de.resample("D").aggregate(
		lambda S: S.idxmax().hour + S.idxmax().minute / 60
	)
	# calculating two peaks per day: 0-12, 12-24
	peak_time_12 = de.resample("12H").aggregate(
		lambda S: S.idxmax().hour + S.idxmax().minute / 60
	)
	peak_time_m = peak_time_12[peak_time_12.index.hour == 0]
	peak_time_a = peak_time_12[peak_time_12.index.hour == 12].resample("D").sum()
	afternoon_peak_bool = peak_time >= 12

	df["tdy_peak_demand"] = peak_demand
	df["tmr_peak_demand"] = peak_demand.shift(-1)
	df["tmr_peak_time"] = peak_time.shift(-1)
	df["tmr_morning_peak"] = peak_time_m.shift(-1)
	df["tmr_afternoon_peak"] = peak_time_a.shift(-1)
	df["tmr_afternoon_peak_bool"] = afternoon_peak_bool.shift(-1)

	# cache it and dropNaN
	df = df.dropna()
	df.to_csv(pJoin(modelDir, "train_data.csv"))

	# initiate my model bois
	params, gridsearch = _cleanse_params(params)
	time_model = svmNextDayPeakTime()
	if not gridsearch:
		size_model = SVR(**params["peakSize"])
	else:
		size_model = GridSearchCV(SVR(), param_grid=params["peakSize"])

		# get cross-validated time predictions over the full interval
	forecasted_peak_time = list(time_model._cv_predict(df=df).hour_pred.shift(1))[
		1:
	]  # shift(1) shifts from tmr to tdy

	# convert these float hour values into ISO formatted dates and times
	dates = list(df.index.to_pydatetime())
	dates = dates[1:]
	for i in range(len(dates)):
		dates[i] += timedelta(hours=forecasted_peak_time[i])
	forecasted_peak_time = [date.isoformat() for date in dates]

	# get cross-validated demand predictions over the full interval
	forecasted_peak_demand = list(
		cross_val_predict(
			size_model,
			X=df[["tdy_peak_demand", "tdy_temp", "tmr_temp"]],
			y=df.tmr_peak_demand,
			cv=3,
		)
	)[
		1:
	]  # shifting from tmr to tdy

	if returnActuals:
		dates = list(df.index.to_pydatetime())
		dates = dates[: len(peak_time)]
		for i in range(len(dates)):
			dates[i] += timedelta(hours=peak_time[i])
		actual_peak_time = [date.isoformat() for date in dates]
		return (
			forecasted_peak_time,
			forecasted_peak_demand,
			actual_peak_time[1:],
			list(df.tdy_peak_demand)[1:],
		)
	else:
		return (forecasted_peak_time, forecasted_peak_demand)


def prophetForecast(rawData, startDate, modelDir, partitions):
	"""Forecasting with fbprophet"""
	from fbprophet import Prophet  # type: ignore
	from fbprophet.diagnostics import cross_validation  # type: ignore

	partitions = int(partitions)
	# initiate model
	prophet = Prophet()

	# put dates in df
	dates = pd.date_range(start=startDate, periods=len(rawData), freq="H")
	input_df = pd.DataFrame(rawData, columns=["y", "temp"])
	input_df["ds"] = dates.to_pydatetime()
	input_df.to_csv(pJoin(modelDir, "prophetin.csv"))

	# give prophet the input data
	with suppress_stdout_stderr():
		prophet.fit(input_df)

		# determine partition length for the cross-validation
	total_hours = len(input_df.ds)
	hp = total_hours // partitions  # horizon and period
	init = total_hours % partitions  # total_hours - hp * (partitions - 1)

	# train prophet w/ those partitions
	# take a moment to appreciate this stupid way to pass the durations
	out_df = cross_validation(
		prophet,
		initial="%d hours" % init,
		horizon="%d hours" % hp,
		period="%d hours" % hp,
	)
	out_df.to_csv(pJoin(modelDir, "prophetout.csv"))
	return (list(out_df.yhat), list(out_df.yhat_lower), list(out_df.yhat_upper))


def _cleanse_params(params):
	"""Fills in default values for a single model's params"""
	has_lists = False
	ret = _default_params.copy()
	for k, v in params.items():
		if k == "peakTimeRegressor":
			# overwrite morning & afternoon
			for kwarg, kwvalue in v.items():
				if type(kwvalue) is list:
					has_lists = True
				ret["peakTimeRegressorMorning"][kwarg] = kwvalue
				ret["peakTimeRegressorAfternoon"][kwarg] = kwvalue
		else:
			for kwarg, kwvalue in v.items():
				if type(kwvalue) is list:
					has_lists = True
				ret[k][kwarg] = kwvalue

	if has_lists:
		for k, v in params.items():
			for l, w in v.items():
				if type(w) is not list:
					ret[k][l] = [w]

	return ret, has_lists


class svmNextDayPeakTime:
	def __init__(self, params=_default_params):
		from sklearn.svm import SVC, SVR

		params, gridSearch = _cleanse_params(params)
		if not gridSearch:
			self.classifier = SVC(**params["peakTimeClassifier"])
			self.morning_regressor = SVR(**params["peakTimeRegressorMorning"])
			self.afternoon_regressor = SVR(**params["peakTimeRegressorAfternoon"])
		else:
			self.classifier = GridSearchCV(
				SVC(), param_grid=params["peakTimeClassifier"]
			)
			self.morning_regressor = GridSearchCV(
				SVR(), param_grid=params["peakTimeRegressorMorning"]
			)
			self.afternoon_regressor = GridSearchCV(
				SVR(), param_grid=params["peakTimeRegressorAfternoon"]
			)

	def fit(self, csv):
		"""Fits using all of the given data in csv"""
		df = pd.read_csv(csv).dropna()
		x = df.loc[:, ["tmr_temp", "tmr_weekend"]]
		y = df.tmr_afternoon_peak_bool.astype("bool")

		# fit the models
		self.classifier.fit(x, y)
		self.morning_regressor.fit(x, df.tmr_morning_peak)
		self.afternoon_regressor.fit(x, df.tmr_afternoon_peak)

	def predict(self, csv):
		"""Predicts using all of the given data in csv.
		Returns the csv as a dataframe with an added hour_pred column."""
		df = pd.read_csv(csv, parse_dates=[0])
		x = df.loc[:, ["tmr_temp", "tmr_weekend"]]
		indices = []
		hour_pred = []
		for index, row in x.iterrows():
			classifier_prediction = self.classifier.predict([row])
			if classifier_prediction:
				hour_prediction = self.afternoon_regressor.predict([row])
			else:
				hour_prediction = self.morning_regressor.predict([row])
			indices.append(index)
			hour_pred.append(hour_prediction[0])
		hour_pred = pd.Series(data=hour_pred, index=indices)
		df["hour_pred"] = hour_pred
		return df

	def cv_metrics(self, csv, metric, random_state=None, splits=None, *args, **kwargs):
		"""Computes cross-validated metrics for the model."""
		# imports
		from sklearn.metrics import (
			explained_variance_score,
			mean_absolute_error,
			mean_squared_error,
			mean_squared_log_error,
			median_absolute_error,
			r2_score,
		)

		# dicty boi for passing in metrics as strings
		metric_string_to_function = {
			"explained_variance_score": explained_variance_score,
			"mean_absolute_error": mean_absolute_error,
			"mean_squared_error": mean_squared_error,
			"mean_squared_log_error": mean_squared_log_error,
			"median_absolute_error": median_absolute_error,
			"r2_score": r2_score,
		}
		if metric not in metric_string_to_function.keys():
			print("Metric not recognized")
			return np.nan
		df = pd.read_csv(csv).dropna()
		y = df.tmr_peak_time
		metric = metric_string_to_function.get(metric, np.nan)
		results = self._cv_predict(
			csv, random_state=random_state, splits=splits if splits else 3
		)
		return metric(y, results, **kwargs)

	def _cv_predict(
		self, csv=None, df=None, random_state=None, splits=3
	):  # cross-validated predict
		"""Returns cross validated prediction as column of pandas dataframe"""
		from sklearn.model_selection import StratifiedKFold

		self._cv_classifiers = []
		self._cv_morning_regressors = []
		self._cv_afternoon_regressors = []
		self.skf = StratifiedKFold(
			shuffle=True, random_state=random_state, n_splits=splits
		)

		if csv and not df:
			df = (
				pd.read_csv(csv, parse_dates=[0])
				.dropna()
				.rename(columns={"Unnamed: 0": "Time"})
			)
			df = df.resample("D", on="Time").max()
		ks = df.loc[
			:, ["tmr_temp", "tmr_weekend", "tmr_morning_peak", "tmr_afternoon_peak"]
		]
		y = df.tmr_afternoon_peak_bool.astype("bool")

		hourpred = pd.Series(index=df.index)
		# loop over the splits, training and predicting appropiately
		for train_index, test_index in self.skf.split(ks, y):
			ks_train, ks_test, y_train, y_test = (
				ks.iloc[train_index, :],
				ks.iloc[test_index, :],
				y.iloc[train_index],
				y.iloc[test_index],
			)
			x_train, x_test = (
				ks_train.loc[:, ["tmr_temp", "tmr_weekend"]],
				ks_test.loc[:, ["tmr_temp", "tmr_weekend"]],
			)

			###FITTING ON TRAINING DATA
			self.classifier.fit(x_train, y_train)
			self.morning_regressor.fit(x_train, ks_train.tmr_morning_peak)
			self.afternoon_regressor.fit(x_train, ks_train.tmr_afternoon_peak)

			###PREDICTING ON TESTING DATA
			classifier_predictions = self.classifier.predict(
				x_test
			)  # returns True if afternoon
			x_morning = x_test[~classifier_predictions]
			x_afternoon = x_test[classifier_predictions]

			hour_predictions_morning = (
				self.morning_regressor.predict(x_morning)
				if len(x_morning) > 0
				else np.array([])
			)
			hour_predictions_afternoon = (
				self.afternoon_regressor.predict(x_afternoon)
				if len(x_afternoon) > 0
				else np.array([])
			)

			###APPENDING RESULTS & SKLEARN OBJECTS
			for hpm_index, index_val in enumerate(
				df.index[test_index][~classifier_predictions]
			):
				hourpred[index_val] = hour_predictions_morning[hpm_index]
			for hpm_index, index_val in enumerate(
				df.index[test_index][classifier_predictions]
			):
				hourpred[index_val] = hour_predictions_afternoon[hpm_index]

			self._cv_classifiers.append(self.classifier)
			self._cv_morning_regressors.append(self.morning_regressor)
			self._cv_afternoon_regressors.append(self.afternoon_regressor)
		df["hour_pred"] = hourpred
		return df


# fmt: off


# --------------------------- Kevin's neural net code ----------------------- #
# NERC6 holidays with inconsistent dates. Created with python holidays package
# years 1990 - 2024

def makeUsefulDf(df, noise=2.5, hours_prior=24, structure=None):
	"""
	Turn a dataframe of datetime and load data into a dataframe useful for
	machine learning. Normalize values.
	"""
	def _isHoliday(holiday, df):
		m1 = None
		if holiday == "New Year's Day":
			m1 = (df["dates"].dt.month == 1) & (df["dates"].dt.day == 1)
		if holiday == "Independence Day":
			m1 = (df["dates"].dt.month == 7) & (df["dates"].dt.day == 4)
		if holiday == "Christmas Day":
			m1 = (df["dates"].dt.month == 12) & (df["dates"].dt.day == 25)
		m1 = df["dates"].dt.date.isin(nerc6[holiday]) if m1 is None else m1
		m2 = df["dates"].dt.date.isin(nerc6.get(holiday + " (Observed)", []))
		return m1 | m2
	def _data_transform_3d(data, timesteps=24, var='x'):
		m = []
		s = data.to_numpy()
		for i in range(s.shape[0]-timesteps):
			m.append(s[i:i+timesteps].tolist())
		if var == 'x':
			t = np.zeros((len(m), len(m[0]), len(m[0][0])))
			for i, x in enumerate(m):
				for j, y in enumerate(x):
					for k, z in enumerate(y):
						t[i, j, k] = z
		else:
			t = np.zeros((len(m), len(m[0])))
			for i, x in enumerate(m):
				for j, y in enumerate(x):
					t[i, j] = y
		return t
	# file loading
	this_directory = os.path.dirname(os.path.realpath(__file__))
	with open(pJoin(this_directory, 'static', 'testFiles', 'holidays.pickle'), 'rb') as f:
		nerc6 = pickle.load(f, encoding='latin_1') # Is this the right codec? It might be cp1252
	# add dates
	if 'dates' not in df.columns:
		df['dates'] = df.apply(lambda x: dt(int(x['year']), int(x['month']), int(x['day']), int(x['hour'])), axis=1)
	r_df = pd.DataFrame()
	# load processing
	r_df["load_n"] = zscore(df["load"])
	r_df["load_prev_n"] = r_df["load_n"].shift(hours_prior)
	r_df["load_prev_n"].bfill(inplace=True)
	if structure != '3D':
		def _chunks(l, n):
			return [l[i : i + n] for i in range(0, len(l), n)]
		pre_n = [val for val in _chunks(list(r_df["load_n"]), 24) for _ in range(24)]
		n = np.array(pre_n)
		l = ["l" + str(i) for i in range(24)]
		for i, s in enumerate(l):
			r_df[s] = n[:, i]
			r_df[s] = r_df[s].shift(hours_prior)
			r_df[s] = r_df[s].bfill()
	r_df.drop(['load_n'], axis=1, inplace=True)
	# DATE
	r_df["years_n"] = zscore(df["dates"].dt.year)
	r_df = pd.concat([r_df, pd.get_dummies(df.dates.dt.hour, prefix='hour')], axis=1)
	r_df = pd.concat([r_df, pd.get_dummies(df.dates.dt.dayofweek, prefix='day')], axis=1)
	r_df = pd.concat([r_df, pd.get_dummies(df.dates.dt.month, prefix='month')], axis=1)
	for holiday in ["New Year's Day", "Memorial Day", "Independence Day", "Labor Day", "Thanksgiving", "Christmas Day"]:
		r_df[holiday] = _isHoliday(holiday, df)
	# TEMP
	temp_noise = df['tempc'] + np.random.normal(0, noise, df.shape[0])
	r_df["temp_n"] = zscore(temp_noise)
	r_df['temp_n^2'] = zscore([x*x for x in temp_noise])
	return (r_df, df['load']) if structure != '3D' else (_data_transform_3d(r_df, var='x'), _data_transform_3d(df['load'], var='y'))

def MAPE(predictions, answers):
	assert len(predictions) == len(answers)
	return sum([abs(x-y)/(y+1e-5) for x, y in zip(predictions, answers)])/len(answers)*100

def train_neural_net(X_train, y_train, epochs, HOURS_AHEAD=24, structure=None):
	import tensorflow as tf
	from tensorflow.keras import layers # type: ignore

	if structure != '3D':
		model = tf.keras.Sequential([
			layers.Dense(X_train.shape[1], activation=tf.nn.relu, input_shape=[len(X_train.keys())]),
			layers.Dense(X_train.shape[1], activation=tf.nn.relu),
			layers.Dense(X_train.shape[1], activation=tf.nn.relu),
			layers.Dense(X_train.shape[1], activation=tf.nn.relu),
			layers.Dense(X_train.shape[1], activation=tf.nn.relu),
			layers.Dense(1)
		])
	else:
		model = tf.keras.Sequential([
			layers.Dense(X_train.shape[2], activation=tf.nn.relu, input_shape=(HOURS_AHEAD, X_train.shape[2])),
			layers.Dense(X_train.shape[2], activation=tf.nn.relu),
			layers.Dense(X_train.shape[2], activation=tf.nn.relu),
			layers.Dense(X_train.shape[2], activation=tf.nn.relu),
			layers.Dense(X_train.shape[2], activation=tf.nn.relu),
			layers.Flatten(),
			layers.Dense(X_train.shape[2]*HOURS_AHEAD//2, activation=tf.nn.relu),
			layers.Dense(HOURS_AHEAD)
		])

	nadam = tf.keras.optimizers.Nadam(learning_rate=0.002, beta_1=0.9, beta_2=0.999)
	model.compile(optimizer=nadam, loss='mape')

	x, y = (np.asarray(X_train.values.tolist()), np.asarray(y_train.tolist())) if structure != '3D' else (X_train, y_train)
	model.fit(x, y, epochs=epochs, verbose=0)
	
	return model

def neural_net_predictions(all_X, all_y, epochs=20, model=None, save_file=None):
	X_train, y_train = all_X[:-8760], all_y[:-8760]

	if model == None:
		model = train_neural_net(X_train, y_train, epochs)
	
	predictions = [float(f) for f in model.predict(np.asarray(all_X[-8760:].values.tolist()), verbose=0)]
	train = [float(f) for f in model.predict(np.asarray(all_X[:-8760].values.tolist()), verbose=0)]
	accuracy = {
		'test': MAPE(predictions, all_y[-8760:]),
		'train': MAPE(train, all_y[:-8760])
	}
	
	if save_file != None:
		model.save(save_file)

	return [float(f) for f in model.predict(np.asarray(all_X[-8760:].values.tolist()), verbose=0)], accuracy

def neural_net_next_day(all_X, all_y, epochs=20, hours_prior=24, save_file=None, model=None, structure=None):
	all_X_n, all_y_n = all_X[:-hours_prior], all_y[:-hours_prior]
	X_train = all_X_n[:-8760]
	y_train = all_y_n[:-8760]
	X_test = all_X_n[-8760:]
	y_test = all_y_n[-8760:]

	if model == None:
		model = train_neural_net(X_train, y_train, epochs, structure=structure)

	if structure != '3D':
		predictions_test = [float(f) for f in model.predict(np.asarray(X_test.values.tolist()), verbose=0)]
		train = [float(f) for f in model.predict(np.asarray(X_train.values.tolist()), verbose=0)]	
		accuracy = {
			'test': MAPE(predictions_test, y_test),
			'train': MAPE(train, y_train)
		}
		predictions = [float(f) for f in model.predict(np.asarray(all_X[-24:].values.tolist()), verbose=0)]
	else:
		accuracy = {
			'test': model.evaluate(X_test, y_test),
			'train': model.evaluate(X_train, y_train)
		}
		predictions = [float(f) for f in model.predict(np.array([all_X[-1]]), verbose=0)[0]]

	if save_file != None:
		model.save(save_file)
	
	return predictions, model, accuracy

def add_day(df, weather):
	lr = df.iloc[-1]
	if 'dates' in df.columns:
		last_day = lr.dates
		df.drop(['dates'], axis=1, inplace=True)
	else:
		last_day = date(int(lr.year), int(lr.month), int(lr.day))
	predicted_day = last_day + datetime.timedelta(days=1)

	d_24 = [{
		'load': -999999,
		'tempc': w,
		'year': predicted_day.year,
		'month': predicted_day.month,
		'day': predicted_day.day,
		'hour': i } for i, w in enumerate(weather)]
	
	df = pd.concat([df, pd.DataFrame(d_24)], ignore_index=True)

	return df, predicted_day
