omf.models.resilientCommunity is a new model currently under development. Check back in the coming months for updates!


### Introduction

Social vulnerability is a concept that provides a comprehensive overview of the factors influencing community resilience in the face of disasters. It highlights the importance of understanding vulnerability beyond physical infrastructure damage to encompass societal elements such as socioeconomic status, demographics, and access to resources. By recognizing these social dimensions, omf.models.resilientCommunity enhances disaster preparedness and response efforts to better support communities disproportionately affected by disasters. This introduction sets the stage for exploring how social vulnerability assessments can inform mitigation strategies and promote equitable resilience across diverse populations.

This model uses data from Federal Emergency Management Agency National Risk Index (FEMA NRI) that contains information for each census tract regarding relative risk indices, percentiles, and ratings that summarize: 
>  * Social vulnerability
>  * Community resilience
>  * Risk of severe weather (e.g. wildfire, ice storm, hurricane, lightning, heat/cold wave, etc.)
>  * Expected financial loss due to natural hazards.

_Learn more about the [Federal Emergency Management Agency National Risk Index](https://hazards.fema.gov/nri/determining-risk)_


omf.models.resilientCommunity can be used to:
>  * Assess community need during emergency preparedness planning
>  * Decide how many emergency personnel are required to assist people.
>  * Identify areas and pieces of equipment in need of assistance in emergencies.
>  * Create a plan to evacuate people, accounting for those who have special needs, such as those without vehicles, the elderly, or people who do not speak English well.
>  * Identify communities that will need continued support to recover following an emergency or natural disaster.



***

 
### Walkthrough

![image](https://github.com/dpinney/omf/assets/111519747/9c4eec32-718d-47a6-8f07-694c270e7f57 "An image depicting the resilientCommunity default model inputs")

_An image depicting the resilientCommunity default model inputs_

**Model Requirements**

For the resilientCommunity model, users must specify whether they want to include Lines, Transformers, or Fuses within the analysis. 

As well as whether there should be a data refresh, this is where the associated Fema NRI File should be updated or not

The “Loads Coloring By” selection is optional and up to the user to select from the following choices.


![image](https://github.com/dpinney/omf/assets/111519747/78170501-9500-4911-9fbe-342a7732712a)

_various options for loads coloring by_


### Model Results

A map displaying the circuit along with social vulnerability index 

#### Circuit Map

![image](https://github.com/dpinney/omf/assets/111519747/d9f95617-aebd-4148-b010-e28b41f0e305)

_image displaying example circuit map_


#### Object Table

![image](https://github.com/dpinney/omf/assets/111519747/c1e381b3-2caa-41c0-bf64-d5b60f0b4d60)

_table listing all the objects within the given circuit, and their base and community criticality values_

##### Calculation / Process


Social Vulnerability Calculation:

Datasets Used:

1. US Census Planning Database
2. US Census ACS Data

US Census Planning Database Variables:
Socioeconomic variables
* Percent Individuals Below Poverty Level | Poverty level: pct_Prs_Blw_Pov_Lev_ACS_16_20
* Percent Individuals 16+ Unemployyed | Unemployed: pct_Civ_emp_16p_ACS_16_20
* Per capita Income | Income: avg_Agg_HH_INC_ACS_16_20
Housing Composition / Transposition
* Percent non highschool grads | Highschool: pct_Not_HS_Grad_ACS_16_20
* Noninstituionalized People under 19 | under19: Civ_noninst_pop_U19_ACS_16_20
* Non Instituionalized People | noninstitution: Civ_Noninst_Pop_ACS_16_20
* Percent population under 19 | under19 : Civ_noninst_pop_U19_ACS_16_20 / Civ_Noninst_Pop_ACS_16_20
* Percent population disabled | disabled: pct_Pop_Disabled_ACS_16_20
Housing / Transportation
* Percent Multi-unitstructure | multi: pct_MLT_U10p_ACS_16_20
* Percent mobile home | mobile: pct_Mobile_Homes_ACS_16_20
* Percent crowding | crowd: pct_Crowd_Occp_U_ACS_16_20





US Census ACS Data Variables:

* Estimate!!Total:!!6 to 17 years:!!Living with one parent: | singleparent6-17: B23008_021E
* Estimate!!Total:!!Under 6 years:!!Living with one parent: | singleparentu6: B23008_008E
* Total single parents with u18 child | singleparentu18: B23008_021E + B23008_008E
* Total families | family: B23008_001E
* Percent of single parent families | single-parent: (B23008_021E + B23008_008E)/(B23008_001E)




### Code Dependencies:

#### Python Packages:
* import [urllib.request](https://docs.python.org/3/library/urllib.html)
* import [shutil](https://docs.python.org/3/library/shutil.html), [datetime](https://docs.python.org/3/library/datetime.html)
* from [os.path](https://docs.python.org/3/library/os.path.html) import join as pJoin
* import [requests](https://pypi.org/project/requests/)
* import [zipfile](https://docs.python.org/3/library/zipfile.html)
* import [shapefile](https://pypi.org/project/pyshp/)
* from [io](https://docs.python.org/3/library/io.html) import BytesIO
* import [numpy](https://numpy.org/doc/stable/) as np
* import [json](https://docs.python.org/3/library/json.html)
* import [math](https://docs.python.org/3/library/math.html)
* import [pandas](https://pandas.pydata.org/docs/) as pd
* from [shapely.geometry](https://pypi.org/project/shapely/) import Polygon, Point
* import [geopandas](https://geopandas.org/en/stable/docs.html) as gpd
* import [pygris](https://walker-data.com/pygris/)
* import [networkx](https://networkx.org/documentation/latest/) as nx

#### OMF packages:
* from omf import geo
* from omf.models import __neoMetaModel__
* from omf.models.__neoMetaModel__ import *

* from omf.solvers.opendss import *
* from omf.comms import *
* from omf.solvers.opendss.dssConvert import *

#### Base Criticality Evaluation

The Base Criticality Score (BCS) is an estimation representing the impact to a community should that equipment lose functionality leading to outage for downline loads.

It currently reflects the number of individuals served by a piece of equipment within an electrical system. This value is given either as a Base Criticality Score, which is a raw count of total individuals served, or by a Base Criticality Index (BCI), which is a percentile value determined by comparing the BCS’s for all circuit equipment to one another and ranking them from 1 to 100, where 1 represents the lowest criticality and 100 represents the highest criticality.


The Base Criticality Score for a load is calculated by the following : 

```math

\text{Base Criticality}_{Load} = \frac{\sqrt{kw^2 + kvar^2}}{pd} * N
```

where, 

*  _kw_, opendss property used to compute active (real) power, portion of power that is absorbed and used by the load.
*  _kvar_, opendss property represents the reactive (imaginary) power, power that is not used that flows throughout a grid.
*  _pd_, peak demand (in 𝑘𝑣𝑎) for the average served by the system
*  _N_, average number of occupants per home.







The Base Criticality Score for a piece of equipment is calculated by the following : 

```math

\text{Base Criticality}_{Equipment} = \sum_{i=0}^{n}BCS_{Load_{i}}
```

where, 

*  $BCS_{Load}$, the Base Criticality of the given load

#### Community Criticality Evaluation

The Community Criticality Score (CCS) is an estimation that is similar to the BCS, but weighted according to the associated social vulnerability score from the relevant census tract. 

This value is given either as a score which is a raw count, or as an index, which is a percentile value


#### Calculation / Process

The Community Criticality Score for a load is calculated by the following : 

```math

\text{Community Criticality}_{Load} = BCS_{Load} * SVI_{Score}
```
where, 

* $BCS_{Load}$, the Base Criticality of the given load
* $SOVI_{Score}$, the Social Vulnerability score at the location of the load



The Community Criticality Score for a piece of equipment is calculated by the following : 

```math

\text{Community Criticality}_{Equipment} = \frac{1}{\sum\limits_{j=0}^{n}SVI_{SCORE_{j}}} * \sum_{x=0}^{k} CCS_{Load_{x}}
```

where, 

* $CCS_{Load}$, the Community Criticality of the given load
* $SOVI_{Score}$, the Social Vulnerability at the location of the given load
