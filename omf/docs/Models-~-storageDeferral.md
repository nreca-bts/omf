## Introduction

The storageDeferral model calculates the amount of energy storage capacity needed to reduce the load on a substation transformer or line below a user-defined limit. That limit represents a thermal or voltage limit for the hardware in question.

### Walkthrough
The model requires the energy storage system’s technical specifications and cost, market characteristics (Demand Charge and Electricity Cost), and a Demand data for one year in a .csv file.

The default energy storage specifications are based on the Tesla Powerwall 7kWH, daily cycling unit, and a SolarEdge StorEdge inverter. Unit quantity refers to the number of units in the system at the rated unit capacity. 

This model also requires the user to select either substation transformer or transmission line deferral, the capacity threshold of the transformer/line, the replacement cost of the part, time to replacement, and carrying cost percent.

##### Demand File CSV Format

The demand file must be a comma separated value file (.csv). Microsoft Excel can output this format. It must have 1 column containing integer substation demand measurements in **kW**. The time stamps must be a full year of data with measurements every 1 hour. The result should be 8760 rows.

An example of a valid .csv:
```csv
timestamp,power
1981
1903
1917
...
2436
2280
```

If you would like to just try out the model, [an example demand file is available here](./images/demandExampleWinterPeak.csv).

## Model Results

**Demand Before and After Storage** is a graph showing the system’s demand with and without the energy storage system operating.

**Avoided Cost** is a bar graph showing the carrying cost over the remaining life of the equipment, the cost of the batteries, and the net avoided cost.