## Introduction

The smartSwitching model takes in a feeder system and the line location for a new recloser to be added, then compares the expected outage costs and SAIDI/SAIFI/MAIFI metrics of the system without the recloser to the system with the recloser. It is possible to randomly generate fault data, or to use pre-existing fault data for the model. smartSwitching makes use of the reliability module in GridLAB-D and bases the outage cost calculation on customer cost, restoration cost, and hardware cost.

## Walkthrough

The model takes in a feeder system in the form of a .glm file. Random faults will be generated over the period of a year on lines 'Line for Faults' and the additional recloser will be added in 'Recloser Location.' The 'Failure Distribution' and  'Restoration Distribution' inputs as well as the associated parameters and 'Maximum Fault Length' determine the probability distributions with which random faults are generated and how long each fault occurs. For more information, see the Reliability Module Wiki. If the user provides a .csv file with outage data (containing columns of 'Start' or the time an outage begins, 'Finish' or the time an outage ends, and 'Location' or the latitude and longitude of the outage in the form of a string with a space between the values). The option of 'Generate Random Faults?' determines whether a .csv file or set of distribution data will be used to generate faults on the feeder system. Note: If the user decides to not generate random faults, a valid .csv file must be provided and distribution inputs will be disregarded. Likewise, if the user decides to generate random faults, distribution data must be provided and any .csv data will be disregarded. For the calculation of the outage cost, the user must provide the input 'KWH Cost' which is used to calculate customer cost, 'Restoration Cost' (in the form of dollars per hour) which is used to calculate restoration cost, and  'Average Hardware Cost' which is used to find the overall hardware cost. The 'Simulation Start Time' is the date and time at which the simulation is run. 'Fault Type' specifies the type of fault which will occur on the designated line type. The 'Sustained Outage Threshold' is the minimum length (in seconds)  of an outage for it to be considered a sustained outage. Every sustained outage is considered in the outage cost calculation and SAIDI/SAIFI metrics. Every temporary outage (occurring for a time below this threshold) is considered as a part of the MAIFI metric.

## Model Results

Note: there is currently a bug where every once in a while the before and after SAIDI/SAIFI/MAIFI values are exactly the same. The model has likely not run to completion in this case and it is advised for the user to re-run the model.

Recloser Diagram - A diagram showing the feeder system with the recloser highlighted as hot pink.

![feeder chart](https://user-images.githubusercontent.com/54141633/63951420-b6d0b580-ca4b-11e9-9820-6e66a80b37a2.png)

Outage Cost Comparison - Shows the initial outage cost (with data generated from the system without the recloser) and the final outage cost (with data generated from the system with the recloser). It also shows the initial and final customer costs, restoration costs, and hardware costs.

![outage stats](https://user-images.githubusercontent.com/54141633/63951589-057e4f80-ca4c-11e9-9b5e-0b47a5fcfe7c.png)

Change in SAIDI/SAIFI and MAIFI Values - Chart comparing SAIDI/SAIFI/MAIFI metrics on the system with and without the recloser, taking into account the Sustained Outage Threshold (user input).

![saidi chart](https://user-images.githubusercontent.com/54141633/63951633-19c24c80-ca4c-11e9-85ad-c0af0469c1e0.png)

Outage Distribution Data - Graphical representations of the distributions used to generate the random faults. The independent variable is seconds until a given event (the fault or restoration) occurs, and the dependent variable is the probability distribution function associated with each event.

![distributions](https://user-images.githubusercontent.com/54141633/63951528-e7b0ea80-ca4b-11e9-9ed2-f70f416dff0a.png)

Outage Timeline - Bar graph timeline showing all the faults generated over the period of a year for the system.

![without recloser](https://user-images.githubusercontent.com/54141633/63951667-2ba3ef80-ca4c-11e9-94bf-defef5246a1b.png)