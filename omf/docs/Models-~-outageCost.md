## Introduction

The outageCost model takes in a feeder system and a .csv file containing outage data, then computes the SAIDI/SAIFI/MAIFI metrics of the system and graphs an outage timeline to better illustrate the fault data. It then can create a set of random faults from this outage data and graph a leaflet map of the original data, the new data, or both.

## Walkthrough

The model takes in a feeder system in the form of a .omd file. It also takes in a set of outage data in the form of a .csv file. The outage data must contain the following columns and format for each column:

Start - the time a fault begins, must be in the format: YYYY-MM-DD HH:mm:ss (ex: 2000-11-16 16:15:00)

Finish - the time a fault ends, must be in the format: YYYY-MM-DD HH:mm:ss (ex: 2000-11-16 16:15:00)

Location - the location a fault occurs, must be in the format: latitude longitude (ex: -103.64543643634 90.345534636436)

Cause - the cause of the fault, must be in the format of a string (ex: bird)

(optional) Meters Affected - a list of the meters affected by the fault, must be in the format: meter1 meter2 meter3... (ex: 3 64 2 65) Note: This input is mandatory if the user is generating synthetic faults.

(optional) Fault Type - the type of fault induced (ex: TLG) Note: This input is mandatory if the user is generating synthetic faults.

(optional) Component Type - the component affected by the fault (ex: overhead_line) Note: This input is mandatory if the user is generating synthetic faults.

The 'Data to be Graphed' input dictates whether all faults (both original and newly generated) will be graphed on the leaflet map, or if only the old or only the synthetic faults will be graphed.

'Sustained Outage Threshold' is the minimum length (in seconds)  of an outage for it to be considered a sustained outage. Every sustained outage is considered in the outage cost calculation and SAIDI/SAIFI metrics. Every temporary outage (occurring for a time below this threshold) is considered as a part of the MAIFI metric. The 'Number of Customers' is the total number of meters in the feeder system being considered.

It is possible to filter the data shown on the leaflet map with the other 'Filter' inputs, limiting things like cause, component type, fault type, time in which the fault occurs, duration of the fault, and the number of meters affected. These filters are all inputs for the model.

## Synthetic Fault Generation

The model is capable of generating a new set of outage data that is derived statistically from the input outages. This allows for generating statistics and performing engineering analysis with larger test sets.

The 'Generate Faults?' input dictates whether or not a new set of faults will be generated with the set of input data from the .csv file. This input also dictates whether the simple method will be used, in which locations of new faults will be generated from the set of pre-existing fault locations, or the lattice method will be used, in which the 2-dimensional space the feeder system occupies is split up into an NxN grid, allowing for many more potential locations depending on the size of N. 

![lattice1](https://user-images.githubusercontent.com/54141633/71652615-09fd9200-2ce4-11ea-9112-cf12abdccd00.png)

A heat map is created, where the associated likelihood of any lattice point being selected is inversely proportional to the distance from the lattice point to the fourth nearest input outage. Note that, in the example below, the yellow lattice point will be assigned a higher probability in the heat map since it is nearer to its fourth nearest neighbor than the red lattice point.

![lattice2](https://user-images.githubusercontent.com/54141633/71652618-0c5fec00-2ce4-11ea-8c02-0719e5324e22.png)

Once the heat map is created, a lattice point is selected based on the heat map and the nearest point on a line of the input component type is where the new synthetic outage location will be. In the picture below, we assume the red lattice point has been selected and show the point on the line where the synthetic fault will be.

![lattice3](https://user-images.githubusercontent.com/54141633/71652621-0e29af80-2ce4-11ea-8cf6-30f77bcbe65a.png)

The 'Number of Grid Lines' input is the number of grid lines to be used in the lattice method. Note: the larger the input, the more possibilities for locations of new faults, but the more time the model will take to run. The 'Number of Faults Generated' argument specifies how many new faults will be generated.

The 'Duration Distribution Generator' option determines how to find a distribution to generate new durations. If 'Input Durations" is selected, the model will randomly assign one of the input fault durations to each new duration. 'Chi-Squared Test' and 'Kolmogorov-Smirnov Test' each assume that the input fault durations are independently and identically distributed and try to match the set of all input fault durations with a best-fitting distribution function. New synthetic fault durations are chosen based on this distribution function. 'Dependent Normal Distributions' assumes that fault duration is dependent on other variables. If the latter is selected, the user can also specify which dependencies exist for fault durations with 'Dependent Variables for Distributions'. Cause of the fault, date/time of the fault, and location of the fault are all possible dependencies. 

## Model Results

Reliability Metrics - Shows the calculated SAIDI/SAIFI/MAIFI/CAIDI/ASAI values.

![metrics](https://user-images.githubusercontent.com/54141633/63953205-e6cd8800-ca4e-11e9-9e18-96871473508c.png)

Outage Timeline for Input Data - Bar graph timeline showing all the faults generated over the period of a year for the system, based on the input data.

![outage timeline](https://user-images.githubusercontent.com/54141633/63953312-1bd9da80-ca4f-11e9-87ef-2977a0bd0750.png)

Outage Timeline for Randomly Generated Faults - Bar graph timeline showing all the faults generated over the period of a year for the system, based on the synthetic data.

<img width="720" alt="new outages" src="https://user-images.githubusercontent.com/54141633/71652692-78daeb00-2ce4-11ea-8bc1-b0c391492373.png">

Outage Map - Leaflet map showing the feeder system and faults that occurred over the year. A popup demonstrates all the information regarding the fault. Old faults that are taken directly from the input .csv file are blue on the map, where new faults generated from the input data are red.

![leaflet map](https://user-images.githubusercontent.com/54141633/67285009-b9c4b100-f4a4-11e9-9ccc-6155a90d3af0.png)