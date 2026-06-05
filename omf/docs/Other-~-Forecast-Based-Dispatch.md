Some models offer a "prediction" feature, which implements the capabilities of `forecast.py`.

# User Inputs
In order to use the prediction feature, the user is required to provide a CSV of historical data, going back at least 3 years. The model is tested on the latest year given, and trained on all prior years. The CSV should contain the following columns: `load`, `tempc`, `year`, `month`, `day`, `hour`. Temperature must be in Celsius if using Virtual Battery dispatches, otherwise either Celsius and Fahrenheit are acceptable assuming the data is consistent. OMF offers the `WeatherPull` model to aid in curating temperature data if needed.

The user has the option to control the number of epochs (model training cycles). Expect that the model will take approximately 1 minute / 10 epochs. The higher the number of epochs, the more accurate the model will be. There is also an early stopping mechanism if the model doesn't improve in a given time frame (e.g. 100 epochs will be the same runtime as 200 epochs if the model's learning curve levels out at 80 epochs.)

# Structure details
Noise is added to temperature data to replicate day-before uncertainty. The inputs are expanded into a 72-table feature that includes the previous day's load, temperature, temperature<sup>2</sup>, day of the week, year, and holiday data. The neural network is five, fully-connected layers with 72 nodes in each layer. We use a relu activation function.

# Accuracy
Testing on multiple ERCOT inputs show that the model, when given sufficient time, will consistently have better than 95 percent accuracy (5 mean absolute percent error). If unsatisfied with accuracy displayed, it may be worth running the simulation 2-3 times. The model requires a randomized process to find the best prediction methods, and may not find the best model on the first run.