### Introduction

The various load forecasters in forecastLoad take in some combination of forecasted temperature, date, and historical demand data to predict future demand data.

The Hourly Day Of Week Forecasting (shortened loadForecast) model takes in the day of week (in addition to forecasted temperature and historical data), to do a linear regression for the last four weeks to predict the next week's demand.

The Daily Peak Demand model uses forecasted temperature and previous day's demand to predict the time and size of the peak demand for a given day. 

The Prophet Forecaster uses only historical demand and date to predict future demand.  

More on the Neural Network model can be read [here](https://www.kmcelwee.com/load-forecasting/).

### Walkthrough
The model requires a .csv file containing historical demand and temperature as well as upper and lower bounds which are set as constraints to limit highly unlikely projected values.

##### Demand and Temp Curve File CSV Format
This file is a .csv file with 8760 hourly demand values in kW in the first single column and temperature in Celsius in the second Do not add a column title.

An example of a valid .csv:
```csv
1981,9.5
1903,10.2
1917,10.9
...
2436,7.6
2280,5.9
```
##### Lower and Upper Bounds
For certain specific edge cases this forecasting method does not work. In these cases the projected values sometimes exceed the historical peak by two times or are very low. To maintain this erroneous behavior, users can set upper and lower bounds where all of the values outside of those bounds will be set to 0.

##### Number of partitons for Prophet training

This value specifies the number of partitions the data is split into for Prophet's cross-validation. If it is set to 0, the Prophet Forecast does not run at all (to reduce runtime and overhead). Note that a non-zero value will cause the Prophet Forecast to be run, which is rather slow, so don't panic.

##### ML Specifications

This file allows the user to specify some of the specific meta-parameters for the machine learning model used by the Daily Peak Demand Forecasted Plot.

An example format is shown below.

```json
{
  "peakSize": {
    "C": [1,10],
    "epsilon": [0.05,0.25],
    "gamma": 0.05
  },
  "peakTimeClassifier": {
    "C": 0.5,
    "gamma": 0.3
  },
  "peakTimeRegressorMorning": {
    "C": 0.5,
    "epsilon": 0.15,
    "gamma": 0.2
  },
  "peakTimeRegressorAfternoon": {
    "C": 0.3,
    "epsilon": 0.25,
    "gamma": 0.1
  }
}
```

Note that any of the fields shown can be omitted, in which case their default values will be used instead, and if a list of values is given, a [grid-search](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GridSearchCV.html) will be performed to determine the best set of configurations within the options provided.

For a complete review of parameters that can be specified for `peakSize`,  `peakTimeRegressorMorning`, or `peakTimeRegressorAfternoon` see [the sklearn documentation for SVR](https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVR.html). For `peakTimeClassifier`, see [the sklearn documentation for SVC](https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVC.html).



### Model Results

Hourly Day of Week Forecasted Plot - This plot shows a graph of the actual data that the user input and in blue the forecasted data using the Hourly Day of Week Forecast.

Mean Absolute Error (MAE) - This metric is shown to indicate what the error is throughout the year for the Hourly Day of Week Forecast. Note: The hours for which the forecasted demand is set to 0 are included in this calculation.

![](https://raw.githubusercontent.com/kilofarad/omf/41d3b95d6bc06aad299515b3b7d5eb1c1e6752e2/hourlyDayofWeek.png)

Daily Peak Demand Forecasted Plot - This plot shows a graph of the actual data that the user input and in blue the forecasted peak demand at the forecasted time for each day.

![](https://raw.githubusercontent.com/kilofarad/omf/41d3b95d6bc06aad299515b3b7d5eb1c1e6752e2/dailyPeakDemand.png)

Prophet Forecasted Plot - This plot shows a graph of the actual data that the user input and in blue the forecasted data using the Prophet Forecast.

![](https://raw.githubusercontent.com/kilofarad/omf/41d3b95d6bc06aad299515b3b7d5eb1c1e6752e2/prophet.png)
