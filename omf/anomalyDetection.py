"""
Provide reusable anomaly-detection algorithms for demand, meter, and other time-series
data used by OMF models.
"""
import os
from os.path import join as pJoin
import numpy as np
import pandas as pd
import omf
from omf.forecast import suppress_stdout_stderr

def train_prophet(df, modelDir, confidence=0.99):
	# train and cache into modelDir
	"""
	Perform train prophet processing for OMF helper-library workflows.
	"""
	from prophet import Prophet
	m = Prophet(
		yearly_seasonality=True, daily_seasonality=True, interval_width=confidence
	)
	with suppress_stdout_stderr():
		m.fit(df)
		# Predict the future.
	print("PREDICTING!")
	future = m.make_future_dataframe(periods=0)
	forecast = m.predict(future)
	# Merge in the historical data.
	forecast["y"] = df.y.astype(float)
	# Backup the model.
	forecast.to_csv(
		pJoin(modelDir, "forecasted_{}.csv".format(confidence)), index=False
	)
	return forecast

def prophet(df, modelDir, confidence=0.99, cached=""):
	# load cached df if exists, or call train_prophet
	"""
	Perform prophet processing for OMF helper-library workflows.
	"""
	if cached and os.path.isfile(pJoin(modelDir, cached)):
		forecast = pd.read_csv(pJoin(modelDir, cached))
	else:
		forecast = train_prophet(df, modelDir, confidence)
		# detect outliers
	cols = ["y", "yhat", "yhat_lower", "yhat_upper"]
	forecast[cols] = forecast[cols].astype(float)
	forecast["outlier"] = (forecast.y > forecast.yhat_upper) | (
		forecast.y < forecast.yhat_lower
	)
	return forecast

def elliptic_envelope(df, modelDir, norm_confidence=0.95):
	"""
	Perform elliptic envelope processing for OMF helper-library workflows.
	"""
	from sklearn.covariance import EllipticEnvelope
	from scipy.stats import normaltest
	if "ds" in df.columns:
		del df["ds"]
	model = EllipticEnvelope()
	test_stats, p_vals = normaltest(df.values, axis=0)
	normal_cols = p_vals >= (1 - norm_confidence)
	df = df.loc[:, normal_cols]
	if df.shape[1] == 0:
		return None
	df.outlier = model.fit_predict(df.values)
	df.outlier = df.outlier < 0  # 1 if inlier, -1 if outlier
	return df

def t_test(df, modelDir, start_date, confidence=0.99, model="neuralNet"):
	"""Is given a dataframe of demand, temp, and dates (in that order)"""
	from scipy.stats import t
	df = df.copy()
	if model == "neuralNet":
		df["dates"] = pd.date_range(start_date, freq="H", periods = df.shape[0])
		df.columns = ["load", "tempc", "dates"]
		all_X = omf.forecast.makeUsefulDf(df)
		actual = df["load"].values
		pred, acc = omf.forecast.neural_net_predictions(all_X, actual)
	if model == "nextDayPeakKatrina":
		ppt, pred, act_time, actual = omf.forecast.nextDayPeakKatrinaForecast(
			df.values, start_date, modelDir, {}, returnActuals=True
		)
	diff = [p - a for p, a in zip(pred, actual[-8760:])]
	diff = np.asarray(diff)
	alpha = 1 - confidence
	twosigma = -1 * t.ppf(alpha / 2, len(diff)) * np.std(diff)
	diff = np.abs(diff)
	diff = diff > twosigma
	if model == "neuralNet":
		return diff, actual[-8760:], pred, pred - twosigma, pred + twosigma
	if model == "nextDayPeakKatrina":
		return diff, actual, act_time

def percent_error(df, modelDir, start_date, p_error=0.05, model="neuralNet"):
	"""Is given a dataframe of demand, temp, and dates (in that order)"""
	df = df.copy()
	if model == "neuralNet":
		df["dates"] = pd.date_range(start_date, freq="H", periods = df.shape[0])
		df.columns = ["load", "tempc", "dates"]
		all_X = omf.forecast.makeUsefulDf(df)
		actual = df["load"].values
		pred, acc = omf.forecast.neural_net_predictions(all_X, actual)
	if model == "nextDayPeakKatrina":
		ppt, pred, act_time, actual = omf.forecast.nextDayPeakKatrinaForecast(
			df.values, start_date, modelDir, {}, returnActuals=True
		)
	diff = [(p - a)/a for p, a in zip(pred, actual[-8760:])]
	diff = np.asarray(diff)
	diff = np.abs(diff)
	diff = diff > p_error
	if model == "neuralNet":
		lower = (1/p_error) / (1/p_error + 1)
		lower = [lower * p for p in pred]
		upper = (1/p_error) / (1/p_error - 1)
		upper = [upper * p for p in pred]
		return diff, actual[-8760:], pred, lower, upper
	if model == "nextDayPeakKatrina":
		return diff, actual, act_time