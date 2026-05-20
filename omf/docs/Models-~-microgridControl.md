The Microgrid Control model uses the PowerONM solver from Los Alamos National Labs to find the optimal series of control actions by which a microgrid can support loads in the case of an outage, in concert with an outage cost model for estimating the member and utility costs of user-specified outage scenarios.

  The Microgrid Control model seeks to answer the following questions:  

* For a given set of microgrid hardware and (optionally) specified load priorities, what is the optimal series of control actions to keep critical loads available?

* If I install <X> microgrid hardware, how will this effect the availability of loads, and costs to the utility and consumer-members, in the case of <Y> outage?

The Microgrid Control module requires the user to provide the following inputs:   

1. A model name.
2. A distribution feeder (in OMD format).
3. An events file, which specifies the outage being simulated. The schema for this file is available at: [input-events.schema.json](https://github.com/lanl-ansi/PowerModelsONM.jl/blob/main/schemas/input-events.schema.json). Outages are generally modeled as switches that are opened, and set to non-dispatchable.   This file can be manually generated, or, alternatively, can be generated from a CSV file in the format: Asset,timestep,state,despatchable, where: “Asset” is the name of the switch,  “Timestep” is the point in the simulation where the switching action occurs,  “State” is the state of the switch (open or closed), and  “Dispatchable” specifies whether the switch can be dispatched by the control algorithm.
4. The utility’s profit margin on energy sales, as a percentage.
5. The hardware cost for the microgrid under consideration, in USD.
6. The restoration cost for outages, which is the cost of restoration labor in $/hr.
7. Solution Fidelity, which trades off model runtime for precision in the results.

Optionally, the user may also provide:
1. A load priorities file, which permits the user to specify the relative importance of loads on the system.
2. A microgrid tagging file, which labels various microgrids for easier analysis of results.
3. A customer data file, specifying the class of load on the feeder, the name of the customer, and the peaking season for each load. This is a CSV file with the format: Customer Name, Season, Business Type, Load Name. In the absence of this file, the microgridControl model estimates the load type based on load size, and sets the Customer Name equal to the Load Name on the feeder.
4. A custom settings file, specified here: [input-settings.schema.json](https://github.com/lanl-ansi/PowerModelsONM.jl/blob/main/schemas/input-settings.schema.json)