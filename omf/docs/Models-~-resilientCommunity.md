omf.models.resilientCommunity is a new model currently under development. Check back in the coming months for updates!


***

### Introduction

The resilientCommunity model uses technical factors alongside customer and weather hazard statistics to map the potential impact of outages on different parts of a feeder. How different statistics are valued, whether they should be used in the analysis at all, and how statistics should be combined is highly customizable by the user to fit their specific needs. 

Though the customer statistics included in this model were chosen based on the statistics used by FEMA to calculate Social Vulnerability Index in their National Risk Index dataset, the inclusion of weather data and the options to weight and exclude variables evolves the concept for use in more varied applications. 

omf.models.resilientCommunity can be used to:
  * Assess community need during emergency preparedness planning.
  * Decide how many emergency personnel are required to assist people.
  * Identify areas and pieces of equipment in need of assistance in emergencies.
  * Identify pieces of equipment near the end of their projected lifespan in more urgent need of preventative maintenance or replacement due to being in areas with high outage impact potential.
  * Create a plan to evacuate people, accounting for those who have special needs, such as those without vehicles, the elderly, or people who do not speak English well.
  * Identify areas where continued support will be needed to recover following an emergency or natural disaster.

> After running an instance of resilientCommunity for the first time, subsequent runs of the same instance will be much faster, allowing for quick analysis with different input values. This is because data is cached for future use once retrieved from the web. 

***

### Walkthrough

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/resilientCommunity_screenshots/resComInputs.png)


The Resilient Community model requires the following user inputs:

1. A model name (chosen at time of creation)

_System Parameters_

2. A distribution feeder (in OMD format)
    * A feeder can be converted from DSS format in the feeder editor by clicking File &rarr; OpenDSS conversion 
3. A Customer Information file, specifying the class of each load on the feeder, the name of the customer, and the peaking season for each load.
    * This is a CSV with the header: \
      `Customer Name,Season,Business Type,Load Name`
    * The primary use of this file in Resilient Community is to determine which loads are labeled `residential` under the `Business Type` column. The format was chosen to match the format of the same input in the [Restoration model.](https://github.com/nreca-bts/omf/blob/master/omf/docs/Models-~-restoration.md)
    * This file is required and must contain entries for all loads on the feeder.
4. An Equipment Lifetime file, specifying the percentage of the way through the planned usable lifetime and the average restoration time for each piece of equipment listed. 
    * This is a CSV with the header: \
    `equipment name,% through planned usable lifetime,avg hrs to restore`
    * This file is required but does not need to contain entries for every piece of equipment on the feeder. To exclude equipment lifetime data, a CSV containing just a header and no values can be uploaded.
5. A Feeder Map Coloring By dropdown, specifying how loads should be colored in the Resilient Community Map output when the model is run.
   * "No Node Coloring" can be selected to use the default default feeder map editor coloring.
   * "Feeder Sections" can be selected to visualize sections of the feeder bounded by switch locations.
   * The other options can be selected to visualize the distribution of criticality metrics across the feeder.
   * This coloring can be changed after the model is run without rerunning the model by clicking "Edit" &rarr; "Color circuit" in the Resilient Community Map. 
6. The Average Peak Demand (kva) for a household in the area.
7. The Average Number of Occupants for a household in the area.

_Include In Analysis_

8. The choice to include Lines, Transformers, and Fuses in the analysis. Equipment included in the analysis will have criticality metrics calculated for them which can be viewed in their map tooltips and in the Equipment Data Table model output. 
    * Buses are always included in the analysis, while Lines, Transformers, and Fuses are optional. 

_Outage Impact Potential (OIP)_

9. An Aggregation Method dropdown, specifying how the variables whose weights are chosen in 10. and 11. are aggregated to create Outage Impact Potential (OIP) for each census blockgroup.
    * For options containing the phrase "of Min-Max-Normalized", each variable is scaled between 0 and 1 based on their minimum and maximum values so that variables with different units and scales can be meaningfully combined. 
    * "Average of Min-Max-Normalized" uses the weighted arithmetic mean to aggregate variables. Select this option to prioritize the impact of all values with the same weight equally in the aggregation.
    ```math
        \text{OIP}_b = \frac{\sum\limits_{v \in V}w_v n_{v,b}}{\sum\limits_{v \in V}w_v}
    ```
    * "RMS of Min-Max-Normalized" uses the weighted Root-Mean-Square to aggregate variables. Select this option to prioritize the impact of larger values and diminish the impact of smaller values with the same weight in the aggregation. 
    ```math
        \text{OIP}_b = \sqrt{\frac{\sum\limits_{v \in V}w_v n_{v,b}^2}{\sum\limits_{v \in V}w_v}}
    ```
    * Equation Key:
        * $\text{OIP}_b$, the OIP Score for a blockgroup, $b$.
        * $V$, the set of variables used to calculate OIP. 
        * $w_v$ , the weight assigned to a variable $v$.
        * $n_{v,b}$, the normalized value of a variable $v$ for blockgroup $b$.

_Outage Impact Potential - Customer Variables_

10. How heavily weighted each variable relating to customer statistics should be when aggregated to calculate OIP. 
    * These variables only apply to residential loads. If any of these variables are given a non-zero weight, the analysis will be restricted to loads labeled residential in the Customer Information (.csv file) upload.
    * Each weight is represented by $w_v$ in the equations in 9.
    * Values for most listed variables are retrieved per-blockgroup from the web and normalized as described and represented by $n_{v,b}$ in 9. 
    * For variables "% Age 16+ Employed", "% Individuals Disabled", and "% Non-Institutionalized Below Age 19", values are retrieved per-tract and are used as estimates for their blockgroup-resolution values.
    * For "% Age 16+ Employed" and "Avg Aggregate Household Income (USD)", their normalized values are inverted so that higher values before normalization become lower values after normalization. This is done so that they can be combined meaningfully with the other variables that imply a greater difficulty recovering from outages when values are higher. 

_Outage Impact Potential - Weather Hazards Annualized Frequency_

11. How heavily weighted the annualized frequency of each weather hazard should be when aggregated to calculate OIP. 
    * These variables apply to all loads. Including these variables will not impact what loads are analyzed.
    * Each weight is represented by $w_v$ in the equations in 9.
    * Values for each listed variable are retrieved per-tract and normalized as described and represented by $n_{v,b}$ in 9.
    * For most listed variables, their tract-resolution values are used as estimates for their blockgroup-resolution values. This estimate is made on the basis that large-area hazards like heat-waves likely span entire tracts, so the frequency in each blockgroup would match that of the tract that contains them. 
    * For variables "Avalanche", "Landslide", and "Lightning", their blockgroup-resolution values are estimated by scaling their tract-resolution values by the percentage of land area in a tract that a blockgroup makes up. This estimate is made on the basis that these hazards are highly-localized and would only occur in a single place within a particular blockgroup. 

***

### Model Results

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/resilientCommunity_screenshots/resComOutputs1.png)

12. An Important message communicating to users that certain values are calculated relative to each other and only apply within the geographical bounds of the specific system being analyzed. As a result, OIP Rating, OIP Index, LCS, LCI, and BCI values cannot be compared between maps.

13. A Notice to users indicating variables that were removed from the analysis because they lacked entries in the data sources for at least one blockgroup on the map.
    * The list of blockgroups for which data was unavailable will be listed unless it is unavailable for all blockgroups on the map, in which case, it just says it is missing for "all". 
    * This notice will not appear if all variables have entries for all blockgroups. 

14. An interactive Resilient Community Map. This map displays circuit elements colored according to the "Feeder Map Coloring By" rule chosen in 5. Underneath those circuit elements are shapes representing blockgroups, colored according to their OIP scores as noted in the "Outage Impact Potential Legend" in the bottom left of the map.
    * When a circuit element is clicked, a tooltip is brought up containing that element's data from the .omd feeder file with the addition of base crit score, base crit index, locational crit score, locational crit index, and section when applicable. If equipment lifetime information is provided for a circuit element in 4., avg hrs to restore and % through planned usable lifetime will be included in its tooltip. 
    * When a shape is clicked, a tooltip is brought up containing OIP Rating, OIP Score, and OIP Index (the percentile ranking of OIP score among other blockgroups on the map). The average values of BCS, LCS, BCI, and LCI for the blockgroup are also viewable as well as the Load Count, the total Demand (kva) of loads in the blockgroup, and the identifying Blockgroup FIPS. Below those are the blockgroup-specific values for each customer and weather variable, some or all of which may have been used to calculate OIP. 
    * Shapes can be toggled by clicking the checkbox next to "geoshapes.geojson" on the left side of the feeder map. If you are having trouble clicking a line on the map, try toggling shapes off and then reattempting to click on the line.  
    ![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/resilientCommunity_screenshots/resComCircuitMapColoring.png)
    * Feeder map coloring can be changed after the model is run without rerunning the model by clicking "Edit" &rarr; "Color circuit" in the Resilient Community Map, as mentioned in 5.  
    ![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/resilientCommunity_screenshots/resComCircuitMapSearch.png)
    * Circuit elements can be searched for by clicking in the top right corner "Edit" &rarr; "Search objects". Objects found by searching can be visualized on the map by clicking "Highlight search results" on the left side of the feeder map.

![image](https://github.com/nreca-bts/omf/blob/master/omf/docs/images/resilientCommunity_screenshots/resComOutputs2.png)

15. A Loads Data Table containing information on each load included in the analysis. 

16. An Equipment Data Table containing information on each piece of equipment included in the analysis.

17. A Sections Data Table containing metrics summarizing load information in each feeder section. 
    * Sections are portions of the feeder that can be isolated from each other by opening switches. They can be visualized by changing the feeder map coloring to "Feeder Sections". 
    * Most metrics in this table are the mean values across loads in each section.
    * Load Count and Load Amount (kva) in this table are total values across loads in each section. 

18. A Raw Input and Output Files block present in every OMF model. Input files used in and output files generated by an instance of this model can be downloaded from here. 
    * An output file called "loadData4RestorationModel.json" can be downloaded from here and used as an input to the [Restoration model.](https://github.com/nreca-bts/omf/blob/master/omf/docs/Models-~-restoration.md) 

***

### Metric Definitions

#### Outage Impact Potential (OIP)
* <u>OIP</u> is a custom metric that represents the potential impact of an outage in a census blockgroup.
* <u>OIP Score</u> is calculated in various ways per choices made at runtime, as detailed in 9.
* <u>OIP Index</u> is the percentile ranking of an OIP Score among the blockgroups on the feeder map. 
* <u>OIP Rating</u> describes in plaintext how relatively low or high OIP is compared to other blockgroups on the feeder map. It is determined by bucketing OIP Index into 5 evenly spaced groups between 0 and 1. 

#### Base Criticality Score (BCS) & Base Criticality Index (BCI)
* <u>BCS</u> is a criticality metric that estimates the number of people served at a load or by a piece of equipment. For a load, BCS is calculated based on the demand at that load divided by the estimated demand contribution per person. For a piece of equipment, BCS is calculated as the total of the BCS scores for all loads that it serves.   
    ```math
    
    \text{BCS}_{Load} = \frac{kva_{Load}}{(\frac{pd}{N})}
    ```
    ```math

    \text{BCS}_{Equipment} = \sum\limits_{Load \in Loads}BCS_{Load}
    ```
    where, 
    *  $kva_{Load}$, the demand at $Load$.
    *  $pd$, the peak demand (in 𝑘𝑣𝑎) for the average load served by the system.
    *  $N$, the average number of occupants for a household in the area. 
    * $(\frac{pd}{N})$, the estimated demand contribution per person
    * $Loads$, the set of all loads served by a piece of equipment: $Equipment$
* <u>BCI</u> is the percentile ranking of BCS among like circuit elements on the feeder. Loads are ranked among other loads and equipment is ranked among other equipment. Because equipment BCS scores are aggregates of load BCS scores, ranking them seprately prevents loads from purely occupying the lower BCI values. Consequently though, the BCI of an individual load should not be compared with that of an individual piece of equipment. 

#### Locational Criticality Score (LCS) & Locational Criticality Index (LCI)
* <u>LCS</u> is a criticality metric that builds off of BCS by adjusting it to account for the potential impact of outages in an area. For a load, LCS is calculated based on the BCS at that load weighted by the OIP Score for the blockgroup containing that load. For a piece of equipment, LCS is calculated as the total of the LCS scores for all loads that it serves. 
    ```math

    \text{LCS}_{Load} = BCS_{Load} \times OIP_b
    ```
    ```math

    \text{LCS}_{Equipment} = \sum\limits_{Load \in Loads}LCS_{Load}
    ```
    where, 
    *  $OIP_b$, the OIP Score for a blockgroup $b$, which contains $Load$
    * $Loads$, the set of all loads served by a piece of equipment: $Equipment$
* <u>LCI</u> is the percentile ranking of LCS among like circuit elements on the feeder. Like BCI, loads are ranked among other loads and equipment is ranked among other eqipment. Because equipment LCS scores are aggregates of load LCS scores, ranking them seprately prevents loads from purely occupying the lower LCI values. Consequently though, the LCI of an individual load should not be compared with that of an individual piece of equipment. 

***

### Data Sources

Datasets Used:

1. US Census Planning Database (PDB)
2. US Census ACS Data (ACS)
3. US FEMA National Risk Index Dataset (NRI)

| Variable Name in resilientCommunity | Variable Name(s) in Dataset (“ / “ between variable names indicates division) | Dataset |
| :---- | :---- | :---- |
| % Age 16+ Employed | `pct_Civ_emp_16p_ACS_16_20` | PDB |
| % Age 65+ | `Pop_65plus_ACS_16_20` / `Tot_Population_ACS_16_20` | PDB |
| % Crowding | `pct_Crowd_Occp_U_ACS_16_20` | PDB |
| % Individuals Below Poverty Level | `pct_Prs_Blw_Pov_Lev_ACS_16_20` | PDB |
| % Individuals Disabled | `pct_Pop_Disabled_ACS_16_20` | PDB |
| % Limited English Speaking Households | `ENG_VW_ACS_16_20` / `Tot_Occp_Units_ACS_16_20` | PDB |
| % Mobile Home | `pct_Mobile_Homes_ACS_16_20` | PDB |
| % Multi-Unit Structure | `pct_MLT_U10p_ACS_16_20` | PDB |
| % No Vehicle | `B08014_002E` / `B01001_001E` | ACS |
| % Non-HS Grad | `pct_Not_HS_Grad_ACS_16_20` | PDB |
| % Non-Institutionalized Below Age 19 | `Civ_noninst_pop_U19_ACS_16_20` / `Civ_Noninst_Pop_ACS_16_20` | PDB |
| Avg Aggregate Household Income (USD) | `avg_Agg_HH_INC_ACS_16_20` | PDB |
| n/a (not user-facing but used internally) | `LAND_AREA` | PDB |
| Avalanche | `AVLN_AFREQ` | NRI |
| Cold Wave | `CWAV_AFREQ` | NRI |
| Drought | `DRGT_AFREQ` | NRI |
| Earthquake | `ERQK_AFREQ` | NRI |
| Hail | `HAIL_AFREQ` | NRI |
| Heat Wave | `HWAV_AFREQ` | NRI |
| Hurricane | `HRCN_AFREQ` | NRI |
| Ice Storm | `ISTM_AFREQ` | NRI |
| Landslide | `LNDS_AFREQ` | NRI |
| Lightning | `LTNG_AFREQ` | NRI |
| Strong Wind | `SWND_AFREQ` | NRI |
| Wildfire | `WFIR_AFREQ` | NRI |
| Winter Weather | `WNTW_AFREQ` | NRI |