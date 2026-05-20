omf.models.restoration is a new model currently under development. Check back in the coming months for updates!


***

### Introduction
The Restoration model uses the PowerModelsONM optimization library from Los Alamos National Labs to find the optimal series of control actions by which microgrids can support loads in an outage scenario. The Restoration model can be informed by social considerations in addition to traditional  financial and technical factors. Users can upload their own load priorities and choose to include metrics for social vulnerability in the restoration approach used. 

The Restoration model seeks to answer the following questions:
* For a given set of microgrid hardware and (optionally) specified load priorities, what is the optimal series of control actions to keep critical loads available?
* How does the incorporation of social vulnerability affect the availability of loads, the costs to the utility and consumer-members, and the ability to recover in the case of outage?


***

### Walkthrough
The Restoration model requires the following user inputs:

1. A model name (chosen at time of creation)

_Model Specifications_

2. A distribution feeder (in OMD format)
    * Simulation time steps are defined in the OMD file by `npts` and the dimensions of `mult` and `qmult` variables, which must all match. Due to restrictions from PowerModelsONM, `interval` must be set to `1`, indicating that each point represents one hour. These definitions will be utilized by the model according to the OpenDSS usage. For example: in a 24-hour simulation window, each loadshape should have `"npts": "24"`, `"interval": "1"`,  and each `mult` and `qmult` should contain 24 values.
    * PV scaling can be defined as a loadshape used by PV systems in the OMD file. [PVWatts](https://pvwatts.nrel.gov/) and [PySoda](https://github.com/Ignacio-Losada/SoDa) are available tools to use for generating PV profiles. 
    * The OMD file must not contain any InvControl objects because they are not supported by PowerModelsONM.
3. An events file, which specifies the outage being simulated. The schema for this file is available [here](https://lanl-ansi.github.io/PowerModelsONM.jl/stable/schemas/input-events.schema.html). Outages are modeled by switches set to open and non-dispatchable, representing actions taken to isolate a fault down the line. A fault being cleared is then represented by the switch being set to dispatchable (but not explicitly open - when to open it is determined by the simulation). 
<!--- COMMENT NOTE: uncomment the below block (and delete repetitive text above) when the quirks of fault duration are better understood.
Outages can be modeled in one of two ways: 
    * `"event_type": "switch"`, for which switches are opened and set to non-dispatchable, representing actions taken to isolate a fault down the line. 
    * `"event_type": "fault"`, for which faults are defined for pieces of equipment with durations in ms, and switch actions will be taken by the simulation to isolate the faults when it runs. The variable `duration_ms` can only accept values in multiples of `3.6e6`, the amount of ms in an hour, and does not accept `-1` to indicate a permanent fault. 
--->
4. Solution Fidelity, which trades off model runtime for precision in the results.
5. A load priorities file, which permits the user to specify the relative importance of loads on the system.
    * Loads should be given the following priority values according to their importance:\
        `1.0` for typical loads\
        `10.0` for essential loads \
        `100.0` for critical loads
    * Any load priorities not explicitly assigned in the file are given a value of `1.0` (typical) by default. Consequently, the user only has to explicitly denote the priority of non-typical loads. 
    <!--- COMMENT NOTE: The above is done explicitly in our code, though it's not 100% clear if that is true within PowerModelsONM. If the restoration code changes, adjust this appropriately -->
    * Example load priorities file contents: \
      `{ load_1002: 1.0, load_1003: 10.0, load_3004: 100.0 }`
6. A microgrid tagging file, which labels various microgrids for easier analysis of results. 
    * Any buses not explicitly assigned a microgrid label are labeled automatically based on the layout of the circuit, agnostic to the microgrid labels assigned to other buses in this file. Loads are assigned microgrid labels based on the microgrid of the bus to which they most closely connect. To have all microgrid labels assigned automatically, the user can upload a .JSON file containing only the contents `{}`.
    * Microgrid labels should only be assigned in such a way that there are switches on the circuit at the boundary of two microgrids, and all buses labeled as belonging to the same microgrid should be reachable from each other without passing through a different microgrid. Labeling infeasible microgrids (such as a microgrid consisting of two buses at opposite ends of the circuit, separated by a different microgrid) may result in erroneous simulation output. 
    * Note: the microgrid of every bus on the feeder, both those labeled explicitly and automatically, can be found in the file microgridOutputAssignments.csv generated when the model is run.
    * Example microgrid tagging file contents: \
      `{ bus1001: 1, bus1002: 1, bus2001: 2, bus2002: 2 }`
7. Impact of CCI, which determines how much Community Criticality Impact (CCI) is used to weight the importance of each load.
    * CCI reflects an individual’s relative vulnerability to outages at a load. It is calculated at each load by combining the Base Criticality Score, an estimate of the number of people served by that load, with a Social Vulnerability Score determined based on census data.
    * The Impact of CCI determines how heavily to weight CCI values when combined with the load priorities from the load priorities file, where “None” indicates to only use load priorities and “High” indicates to weight CCI and load priorities equally. CCI values are combined with load priorities using a weighted Root Mean Square (RMS) formula. The benefit of this formula is that a high CCI can bring up a low load priority significantly, but a low CCI doesn’t bring down a high load priority very much, so loads considered critical by the user are always considered critical by the model.

_Outage Cost Parameters_

8. A Customer Information file, specifying the class of each load on the feeder, the name of the customer, and the peaking season for each load.
    * This is a CSV with the file format: \
      `Customer Name, Season, Business Type, Load Name`
    * This file is required and must contain entries for all loads on the feeder.
9. The restoration cost for outages, which is the cost of restoration labor in $/hr.
10. The hardware cost for the microgrid under consideration, in USD.
11. The utility's profit margin on energy sales, as a percentage.


***

### Model Results
(Descriptions of model outputs and how to interpret them in context of the model use case(s).)