### Introduction

The storageArbitrage model calculates the costs and benefits of using energy storage to buy energy in times of low prices and sell that energy at times of high prices.

### Walkthrough

The model requires the energy storage system’s technical specifications and cost, market characteristics (Demand Charge and Electricity Cost), and Price curve data for one year in a .csv file.

When the value entered in the Price Threshold for Discharge input is reached or exceeded in the price curve data, the model discharges the battery. Similarly, when the price drops below the Price Threshold for Charge input, the model charges the battery.

##### Demand File CSV Format

The demand file must be a comma separated value file (.csv). Microsoft Excel can output this format. It must have 1 columns for power values. The power values must be hourly integer substation demand measurements in **kW** for every hour of one year.The result should be 1 column of 8760 rows.

An example of a valid .csv:
```csv
1981
1903
1917
...
2436
2280
```

If you would like to just try out the model, [an example demand file is available here](./images/demandExampleWinterPeak.csv).

#### Price Curve CSV Format

The price curve file must be a comma seperated value file (.csv). Microsoft Excel can output this format. It must have 1 column. The price values must be hourly decimals representing dollar price per kWh (15 cents per kWh would be 0.15) for every hour of one year. The result should be 1 column of 8760 rows.

An example of a valid .csv:
```csv
0.15
0.16
0.16
...
0.20
0.17
```

## Model Results

**Monthly Cost Comparison**- Shows for each month how much demand is reduced by using the battery and the total savings from this reduction.  Uses this information to calculate Net Present Value (NPV) and Simple Payback Period (SPP) for the length for the total length of the project.


**Demand Before and After Storage** is a graph showing the system’s demand with and without the energy storage system operating.


**Cash Flow** is a visual reference for the value of the ESS.   The net benefits are calculated on an annual basis while the cumulative return takes into account the entire lifetime of the system.
