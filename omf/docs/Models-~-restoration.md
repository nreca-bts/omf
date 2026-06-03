omf.models.restoration is a new model currently under development. Check back in the coming months for updates!


***

### Introduction
The Restoration model uses the PowerModelsONM optimization library from Los Alamos National Labs to find the optimal series of control actions by which microgrids can support loads in an outage scenario. The Restoration model can be informed by social considerations in addition to traditional  financial and technical factors. Users can upload their own load priorities and choose to include metrics for social vulnerability in the restoration approach used. 

The Restoration model seeks to answer the following questions:
* For a given set of microgrid hardware and (optionally) specified load priorities, what is the optimal series of control actions to keep critical loads available?
* How does the incorporation of outage impact potential affect the availability of loads, the costs to the utility and consumer-members, and the ability to recover in the case of outage?


***

### Walkthrough
![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_inputs.png)

The Restoration model requires the following user inputs:

1. A model name (chosen at time of creation)

_Model Specifications_

2. A distribution feeder (in OMD format)
    * Simulation time steps are defined in the OMD file by `npts` and the dimensions of `mult` and `qmult` variables in loadshapes, which must all match. Due to restrictions from PowerModelsONM, `interval` must be set to `1`, indicating that each point represents one hour. These definitions will be utilized by the model according to the OpenDSS usage. For example: in a 24-hour simulation window, each loadshape should have `"npts": "24"`, `"interval": "1"`,  and each `mult` and `qmult` should contain 24 values.
    * PV scaling can be defined as a loadshape used by PV systems in the OMD file. [PVWatts](https://pvwatts.nrel.gov/) and [PySoda](https://github.com/Ignacio-Losada/SoDa) are available tools to use for generating PV profiles. 
    * Loadshapes must be assigned to other circuit objects through the `daily` property due to the timescale of interest for this model and PowerModelsONM.
    * Loadshapes must not use the `useactual` property or they must have it set to `"useactual": "no"`. If you have loadshapes with `"useactual": "yes"`, you can convert them to electrically equivalent definitions in the following way:
        * Replace all `mult` and `qmult` values in loadshapes that have `"useactual": "yes"` with half of their original values like so: `"mult": "(2,4,6)"` &rarr; `"mult": "(1,2,3)"`.
        * For all loads that use those loadshapes, set `"kw": "2"`.
        * Replace `"useactual": "yes"` with `"useactual": "no"`
        * Since `mult` values are multipliers for the `kw` values, the above method is equivalent to just using the `mult` values as `kw` values, per `"useactual": "yes"`. The simpler approach of setting `"kw": "1"` and not dividing `mult` and `qmult` values in half is not  viable because PowerModelsONM struggles with loads having `"kw": "1"`.
    * The OMD file must not contain any InvControl objects because they are not supported by PowerModelsONM.  
    * Single-phase elements must use a single node reference consistent with the declared phase identity. 
        ```
        Yes:
        "object": "pvsystem", 
        "name": "yes_example",
        "phases": "1",
        "!CONNCODE": ".1", ...
        ```
        ```
        No:
        "object": "pvsystem", 
        "name": "no_example",
        "phases": "1",
        "!CONNCODE": ".1.2", ...
        ```  
    * A feeder can be converted from DSS format in the feeder editor by clicking "File" &rarr; "OpenDSS conversion" 
    
    > ℹ️ To reduce simulation runtimes, users can process their feeder file through this [model reduction code](https://github.com/nreca-bts/omf/blob/master/omf/docs/Other-~-modelReduction) before uploading. The larger the feeder, the more drastic the improvement is likely to be since feeder complexity increases simulation runtime non-linearly. 
3. A Customer Information file, specifying the class of each load on the feeder, the name of the customer, and the peaking season for each load.
    * This is a CSV with the header: \
      `Customer Name,Season,Business Type,Load Name`
    * This file is required and must contain entries for all loads on the feeder.
4. An events file, which specifies the outage being simulated. The schema for this file is available [here](https://lanl-ansi.github.io/PowerModelsONM.jl/stable/schemas/input-events.schema.html). Outages are modeled by switches set to open and non-dispatchable, representing actions taken to isolate a fault down the line. A fault being cleared is then represented by the switch being set to dispatchable (but not explicitly open - when to open it is determined by the simulation). 
<!--- COMMENT NOTE: uncomment the below block (and delete repetitive text above) when the quirks of fault duration are better understood.
Outages can be modeled in one of two ways: 
    * `"event_type": "switch"`, for which switches are opened and set to non-dispatchable, representing actions taken to isolate a fault down the line. 
    * `"event_type": "fault"`, for which faults are defined for pieces of equipment with durations in ms, and switch actions will be taken by the simulation to isolate the faults when it runs. The variable `duration_ms` can only accept values in multiples of `3.6e6`, the amount of ms in an hour, and does not accept `-1` to indicate a permanent fault. 
--->
5. Solution Fidelity, which trades off model runtime for precision in the results.
6. A load priorities file, which permits the user to specify the relative importance of loads on the system.
    * Loads should be given the following priority values according to their importance:\
        `1.0` for typical loads\
        `10.0` for essential loads \
        `100.0` for critical loads
    * Any load priorities not explicitly assigned in the file are given a value of `1.0` (typical) by default. Consequently, the user only has to explicitly denote the priority of non-typical loads. 
    <!--- COMMENT NOTE: The above is done explicitly in our code, though it's not 100% clear if that is true within PowerModelsONM. If the restoration code changes, adjust this appropriately -->
    * Example load priorities file contents: \
      `{ load_1002: 1.0, load_1003: 10.0, load_3004: 100.0 }`
7. A microgrid tagging file, which labels various microgrids for easier analysis of results. 
    * Any buses not explicitly assigned a microgrid label are labeled automatically based on the layout of the circuit, agnostic to the microgrid labels assigned to other buses in this file. Loads are assigned microgrid labels based on the microgrid of the bus to which they most closely connect. To have all microgrid labels assigned automatically, the user can upload a .JSON file containing only the contents `{}`.
    * Microgrid labels should only be assigned in such a way that there are switches on the circuit at the boundary of two microgrids, and all buses labeled as belonging to the same microgrid should be reachable from each other without passing through a different microgrid. Labeling infeasible microgrids (such as a microgrid consisting of two buses at opposite ends of the circuit, separated by a different microgrid) may result in erroneous simulation output. 
    * Note: the microgrid of every bus on the feeder, both those labeled explicitly and automatically, can be found in the file microgridOutputAssignments.csv generated when the model is run.
    * Example microgrid tagging file contents: \
      `{ bus1001: 1, bus1002: 1, bus2001: 2, bus2002: 2 }`


_Include Locational Data in Analysis_

8. A JSON file which contains metrics summarizing locational data like weather hazard risks and customer statistics for loads on the feeder. More information about Locational Criticality Index (LCI) can be found at the [resilientCommunity wiki page](https://github.com/nreca-bts/omf/blob/master/omf/docs/Models-~-resilientCommunity.md).
    * This file can be generated by running the resilientCommunity model with the same feeder and customer information file as used in restoration.
    * The version of this file generated by a successful run of resilientCommunity will be called loadData4RestorationModel.json and will be located in the "Raw Input and Output Files" output at the bottom of the model. 
9. Use LCI, a selection for whether the information in the file upload described by 8. should be considerd in the restoration analysis.
    * If you don't want to include locational data or you don't have a file to upload, selecting "No" will cause whatever file, including the default file in the field described by 12, to be disregarded. 
10. Impact of LCI, which determines the level of impact LCI should have on the results of the simulation compared to user-selected load priorities as described by 6. 
    * Ratio of `LCI:Load Priorities` for each option: \
    `High: 1:1`, `Medium: 1:2.5`, `Low: 1:10`, `None: 0:1`
    * Selecting "None" excludes LCI from the simulation but includes it in the output for the sake of analysis. 


***

### Model Results

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_1_gen_volt_demand.png)

11. A graph of generator profiles for the whole system over the course of the simulation. 

12. A series of graphs of generator profiles for each microgrid. This also includes a graph of generator profiles in areas that are considered to be part of no microgrids. 

13. A graph of voltage per-unit over the course of the simulation. 

14. A graph of demand served over the course of the simulation.  
    * <u>% Total Demand Served:</u> The percent of total demand that is successfully served by any resource.
    * <u>% Demand in Microgrids Served:</u> The percent of demand in microgrids that is successfully served by any resource. 
    * <u>% Additional Demand Servable via Microgrids:</u> The percent of additional demand that microgrid resources can support outside their predefined microgrid zones.
    * <u>% Demand Served by Grid:</u> The percent of total demand served by the grid.
    <!-- https://github.com/lanl-ansi/PowerModelsONM.jl/blob/bbde2fd915d5c7a114035e60a46d85e9ad90d2dc/schemas/output-load_served.schema.json#L9 -->

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_2_outage_costs.png)

15. A graph of customer outage plots, illustrating estimated outage costs for each load with respect to total outage duration.

    * Outage cost curves for each load are estimated by interpolating data from [this analysis](https://eta-publications.lbl.gov/sites/default/files/lbnl-54365.pdf) by Lawton et al. to match the curve associated with the average kW of that load during the simulation. 
    * That estimated outage cost curve is then scaled based on business type and season using data from that same analysis and subsequently adjusted for inflation from the time that data was collected.
    * Outage cost curves are capped at 25 hours due to the limitations of the data even if outage durations extend past that point.
    
16. A customer outage cost table containing sortable columns of the information graphed in 17.

17. A customer outage cost histogram color-coded by business type to illustrate how many loads incurred different degrees of estimated cost. 

18. A graph of utility outage plots, illustrating lost kWh sales resulting from outages both hourly and cumulatively over the course of the simulation.

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_3_taofi_taodi.png)

19. A histogram of Time Average Outage Frequency Index (TAOFI) values. 
    * Each load has its own TAOFI value, calculated as 
    
    ```math
    \frac{1}{\text{the average period between the onset of outages (hr)}}
    ```
    * A lower TAOFI value indicates more time between outages on average for a load.
    * TAOFI is undefined for loads that experience fewer than two outages during the simulation window.

20. A scatter plot of TAOFI vs LCI for each load with a TAOFI value.
    * This plot appears conditionally when the Use LCI dropdown in 9. is set to "Yes".
    * This plot includes a correlation coefficient and a trendline that can be hovered for more details. 
    * Note that while this can be helpful in analyzing the relationship between the factors that contribute to LCI and the freqency of outages for each load during the simulation, the relationship between those variables is complex and should be analyzed in context of other information available.
        * If the Annualized Frequency of Lightning was heavily weighted when LCI was generated, we may naturally see a higher correlation during a simulated lightning storm. This is an example where causality may be more confidently inferred.
        * If % Age 65+ was heavily weighted when LCI was generated, it may be harder to infer causality, but observing a high correlation could aid in decision making about where to direct resources during outage events to better support the needs of older customers. 
        * The granularity of feeder areas that can be islanded while others are powered can also impact the relationship between these factors and should be accounted for when interpreting this plot. On one extreme, a circuit with only one switch that would cut the whole feeder off from vsource when repairs need to be conducted downline would likely show a very low correlation. On the other extreme, a circuit with point-of-load switches and generation resources at every load may yield a very informative plot since sections can be islanded with extreme granularity.
 
21. A histogram of Time Average Outage Duration Index (TAODI) values. 
    * Each load has its own TAODI value, calculated as the percent of the total simulation time during which that load is experiencing an outage.

22. A scatter plot of TAODI vs LCI for each load. 
    * This plot appears conditionally when the Use LCI dropdown in 9. is set to "Yes".
    * This plot includes a correlation coefficient and a trendline that can be hovered for more details.
    * Note that while this can be helpful in analyzing the the relationship between the factors that contribute to LCI and the total relative duration of outages for each load during the simulation, the relationship between those variables is complex and should be analyzed in context of other information available.
        * See the examples laid out in 20. 

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_4_OI_and_metrics.png)

23. A plot of outage incidence for the whole system over the course of the simulation. Outage incidence is the percent of loads on a feeder experiencing an outage at a given time. The plot contains both unweighted and weighted outage incidence at each timestep as well as a mean line for each.
    * Unweighted outage incidence at each timestep is calculated as 
    ```math
    \frac{\text{\# loads experiencing an outage}}{\text{\# loads on the feeder}}
    ```
    * Unweighted outage incidence can also be thought of as the average load status at a timestep where
    ```math
    \text{status}(Load) = \begin{cases} 
    1 & \text{if } Load \text{ is experiencing an outage} \\ 
    0 & \text{otherwise}
    \end{cases}
    ```
    * Weighted outage incidence is calculated by taking the weighted average load status at a timestep. Weights are taken from the load priorities that a user can upload in 6. with 1 as the default weight for loads that do not have an explicitly assigned priority. 
    * Weighted outage incidence can be used to analyze how effectively simulated restoration actions support the user's priorities compared to unweighted outage incidence which considers all loads identically.  

24. A series of plots of outage incidence for each microgrid over the course of the simulation. This also includes a plot of outage incidence in areas that are considered to be part of no microgrids. 

25. A table of simulation-constrained (SC) metrics for the whole system, for each microgrid, and for areas considered to be part of no microgrid. SC metrics are calculated for the course of the simulation, unlike their annual counterparts.
    * The columns "Est. People Served", "LCI of Average Load", and "Avg. Load Priorities modified by LCI" rely on locational data and only appear conditionally when the Use LCI  dropdown in 13. is set to "Yes".
    * Metrics that rely on locational data only consider loads in each microgrid that have locational data. 

26. A table of simulation-constrained (SC) metrics organized by LCI quartiles. As in 25., SC metrics are calculated for the course of the simulation, unlike their annual counterparts.
    * This table only appears conditionally when the Use LCI dropdown in 9. is set to "Yes".
    * All metrics in this table only consider loads that have locational data. 

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_5_Timeline_Map.png)

27. A timeline of device actions taken during the simulation period for loads, switches, batteries, and generators. Actions include load shed, load pickup, switch opening, switch closing, battery control, and generator control.

28. An outage map and time slider that allow users to visualize the device actions taken during the simulation that are detailed in the table in 27. 
    * <u>Map Key:</u> A base feeder map is drawn with black lines and grey nodes. As device actions are taken, those lines and nodes are drawn over in color to indicate the action taken. 
        | Appearance | Device Action |
        | :------------: | :------------ |
        | <span title="Black Line" style="color:#000000; font-size:1.4em; font-weight:bold;">━</span> | No Action Taken - Line |
        | <span title="Orange Line" style="color:#f97e08; font-size:1.4em; font-weight:bold;">━</span> | Switch Opening |
        | <span title="Purple Line" style="color:#9470d5; font-size:1.4em; font-weight:bold;">━</span> | Switch Closing |
        | <span title="Grey Circle" style="color:#808080; font-size:1.4em;">●</span> | No Action Taken - Other Circuit Object |
        | <span title="Blue Circle" style="color:#0000FF; font-size:1.4em;">●</span> | Load Shed |
        | <span title="Green Circle" style="color:#00C957; font-size:1.4em;">●</span> | Load Pickup |
        | <span title="Yellow Circle" style="color:#FFFF00; font-size:1.4em;">●</span> | Battery Control |
        | <span title="White Circle" style="color:#E0FFFF; font-size:1.4em;">●</span> | Generator Control |
    * <u>Tooltips:</u> Users can click on a circuit object to bring up a tooltip detailing the device's coordinates, name, and microgrid ID if it has one. If a device action has been taken within the range of timesteps set with the two-way time slider, the tooltip for that device will also contain the latest action for the device in that range, at what timestep it occurred, and the device's state before and after that action. 
    * <u>Time Slider:</u> A two-way time slider is located at the top of the map which sets the earliest and latest timestep for which device actions should be displayed. A feeder map with black lines and grey nodes is always drawn, then different colored lines and circles are drawn on top of that map to represent different device actions with ones that occur later in the timeline being drawn over earlier ones. This allows the feeder to be used in 3 different ways:
        * To visualize the state of all circuit objects on the map at a particular timestep, keep the left slider at 0 and move the right slider to the desired timestep. Since later device actions are drawn over earlier ones, the most recent actions for each device will be visible. For example, any loads that are grey or green are powered because since the start of the simulation, they were never shed (grey) or were shed at one point but their most recent action was load pickup. Likewise, any loads that are blue are not powered because their most recent action since the start of the simulation was load shed. 
        * To visualize device actions that occurred between two timesteps, adjust the the left slider to the lower timestep and the right slider to the higher timestep. Any actions that occurred before or after that range will not be visible on the map.
        * To visualize device actions that occurred at a specific timestep, move both the left and right sliders to that same timestep. 

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/restoration_screenshots/resto_outputs_6_Files.png)

29. A Raw Input and Output Files block present in every OMF model. Input files used in and output files generated by an instance of this model can be downloaded from here.