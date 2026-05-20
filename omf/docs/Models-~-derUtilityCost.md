omf.models.derUtilityCost is a new model currently under development. Check back in the coming months for updates!


# Introduction
(Describes the purpose of the model and the use cases it was developed to address.)

The derUtilityCost model evaluates the financial costs of enrolling and controlling behind-the-meter distributed energy resources (DERs) using the National Renewable Energy Laboratory (NREL) Renewable Energy Optimization Tool (REopt) and the OMF virtual battery dispatch module (vbatDispatch).

The estimated runtime of the model (for the first time; including building and compiling the REopt Julia system image) is about 8.5 minutes for MacOS running with an Apple M2 cpu. On a Windows machine, building the REopt Julia system image can take about 1.5 hours. Fortunately, after this initial run the model should compile much faster (on the order of 30 seconds to 1 min for the same MacOS system). 
 
# Walkthrough
(Descriptions of required input formats, how to prepare a custom model. Inputs from the default model are used as illustrative examples.)

## Inputs

### General Model Inputs
<ul>
<li> <b> Demand Curve </b> (.csv file) — Default: utility_2018_kW_load.csv. The demand curve should be formatted as a .csv file with a length of 8760 values representing the hourly demand (kW) for one entire year beginning on January 1. Power generation from any existing utility-owned photovoltaic installations and/or existing chemical battery storage systems should be removed such that only the remaining (net) demand is portrayed. An example of a valid .csv (shortened for brevity):
</li>

```csv
283416
275434
267785
263793
262463
262790
266827
269988
268817
...
318861
329671
320786
314194
306755
300396
291301
```

<li> <b> Temperature Curve </b> (.csv file) —  Default: open-meteo-denverCO-noheaders.csv. This is assumed to be the outdoor air temperature corresponding to the utility’s service area and time of the provided Demand Curve. The format is the same as the Demand Curve: a .csv file with a length of 8760 values representing the hourly temperature data in degrees Fahrenheit for the entire year. An example of a valid .csv (shortened for brevity):

```csv
4.6
3.3
2.7
2.8
3.6
4.4
2.8
5.1
5.2
6
...
17.9
17.9
18.4
17.4
16
11.4
10.8
10.7
10.6
10.6
10.4
```

A temperature curve .csv can be obtained using the following steps: 

[OpenMeteo Historical Weather Data API](https://open-meteo.com/en/docs/historical-weather-api#latitude=39.986&longitude=-104.812&start_date=2018-01-01&end_date=2018-12-31&temperature_unit=fahrenheit&timezone=America%2FDenver) 

<ul> 
<li> Enter the latitude and longitude of the utility or cooperative service area. </li>
<li> The timezone should be the local time corresponding to the Demand Curve data. </li>
<li> Enter the Start Date (ex. 2018-01-01) and End Date (ex. 2018-12-31). </li>
<li> Under the Hourly Weather Variables section, select “Temperature” only. </li>
<li> Under Settings, select the Temperature Unit to be Fahrenheit. The other options may be left as the default values.</li>
<li> Under API Response, reload the chart by pressing the “Reload Chart” button. </li>
<li> Download the .csv file by clicking the “Download CSV” button located under the API Response Chart that was just reloaded. </li>
<br>
<b> AFTER DOWNLOADING THE .CSV, YOU MUST EDIT THE .CSV FILE BY DOING THE FOLLOWING:</b>
<ul>
<li> Open the .csv file after downloading. It may be in your Downloads folder, or wherever your files go when they are downloaded. You want to be able to make changes and edit the file (e.g. the easiest way would be to open the file in Excel, Google Sheets, CryptPad Spreadsheet, OnlyOffice Spreadsheet, or some other spreadsheet program). The .csv file should look like this: </li>
<img width="703" alt="open-meteo-googlesheet-example" src="https://github.com/user-attachments/assets/3ebdecc0-7b0c-4e6e-93e3-f7e23a7b19bd" />
<li> Delete the header rows and the timestamp column. The .csv file should look like this when you upload it to derUtilityCost:</li>
<img width="704" alt="open-meteo-googlesheets-example-edited" src="https://github.com/user-attachments/assets/3f844fba-bd95-458b-a6c0-c591e6e871d3" />
<li> Be sure that there are 8760 rows total. Save the file (e.g. if you’re using Google Sheets, go to File > Download > Comma Separated Values (.csv). Now you can upload the .csv file to the Temperature Curve input!</li>

</ul>
</ul>

</li>

<li> <b> Latitude </b> (decimal) — Default: 39.986771. The latitude coordinate of the utility’s approximate service area. </li>
<li> <b> Longitude </b> (decimal) — Default: -104.812599. The longitude coordinate of the utility’s approximate service area. </li>
<li> <b> Year </b> (int) — Default: 2018. The corresponding year for the Demand Curve values. </li>
</ul>

### Financial Inputs
* <b> Energy Rate Curve </b> (.csv file) — Default: TOU_rate_schedule.csv. A .csv file containing 8760 rows representing the hourly $/kWh rate that the utility or cooperative pays to the wholesale energy supplier. An example of a valid .csv (shortened for brevity):
```csv
0.02369
0.02369
0.02369
0.02369
0.02369
0.02369
0.13758
0.13758
0.13758
0.13758
...
0.02369
0.02369
0.02369
0.02369
0.02369
```



* <b> Residential Rate Structure </b> (.json file) — Default: TODrate66a13566e90ecdb7d40581d2.json. This is a .json file describing the energy rate structure that a residential customer pays to the utility or cooperative. This input allows a utility to upload a custom rate structure if the URDB Label is not known or is incorrect. An example of a valid .json file: 

```json
{"energyweekdayschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1]],
"energyweekendschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1]],
"energyratestructure":[[{"rate":0,"unit":"kWh"}],[{"rate":0.06,"unit":"kWh"}],[{"rate":0.1525,"unit":"kWh"}]],
"demandratestructure":[[{"rate":0,"unit":"kW"}],[{"rate":4.0,"unit":"kW"}]],
"demandweekdayschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]],
"demandweekendschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]]}
```
The example above was created using the REopt Web Tool custom electric rate tariff generator following their instructions: https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates. The rate structure information was based on a Colorado utility's Time of Day residential rate structure found at https://apps.openei.org/USURDB/rate/view/66a13566e90ecdb7d40581d2#3__Energy.

* <b> URDB Label (optional) </b> (string) —  Default: 612ff9c15457a3ec18a5f7d3. The Utility Rate Database (URDB) label is the combination of letters and numbers found at the end of the URDB webpage URL. The URDB label is  REopt to run a financial analysis using this utility rate information. To obtain a URDB label for the utility rate of interest, follow these steps: go to the [OpenEI Utility Rate Database](https://openei.org/wiki/Utility_Rate_Database) and look up the utility rate by entering the zip code, utility name, or country. 

<ol>

  <img width="1120" alt="OpenEI_URDB" src="https://github.com/user-attachments/assets/0e6d7b99-f406-4d78-98d2-5cb47e8faaa9" />
  <img width="1120" alt="OpenEI_URDB_example" src="https://github.com/user-attachments/assets/f8160910-50bb-4282-8226-d9a3f2a57fb5" />

</ol>

For example, this URDB rate webpage https://openei.org/apps/IURDB/rate/view/5b75cfe95457a3454faf0aea would yield the URDB label 5b75cfe95457a3454faf0aea.
<ul>
<li> <b> Demand Charge Cost ($/kW) </b> (decimal) - Default: 50. The cost in USD of the demand charge that the utility pays per kW for the maximum monthly peak demand (kW). </li>
<li> <b> Financial Projection Length </b> (years) — Default: 25. The number of years to project out estimated financial savings. Must be between 1 and 75 years. Note that the financial analysis only takes into account the first year (since only a one year demand curve is provided) and project those financial findings out for all subsequent years. </li>
<li> <b> Energy Cost </b> ($/kWh) — Default: 0.05. Cost of energy consumption bought by the utility. i.e. wholesale (not retail) cost. </li>
<li> <b> Energy Compensation Rate </b> ($/kWh) — Default: 0.02. The dollar amount per kWh that will be compensated to the member-consumer for BESS, TESS, and GEN distributed energy resources. </li>
<li> <b> Discount Rate </b> (%) — Default: 2. The discount rate used in the financial analysis for calculating the Net Present Value (NPV). </li>
<li> <b> Program Startup Costs </b> ($) — Default: 200000. The total costs to the utility for the DER programs. </li>
<li> <b> Ongoing Operational Costs </b> ($/month) — Default: 500. The total monthly costs to the utility for all operational costs (e.g. API calls per month). </li>
<li> <b> One-time Operational Costs </b> ($) — Default: 20000. The total one-time costs to the utility for all operational costs (e.g. contracted agreements for DER device usage, etc.). </li>
<li> [Add subsidies here] </li>




</ul>

### Home Fossil Fuel Device Inputs
<ul>
<li> <b> Number of Home Fossil Fuel Generators </b> (int) — Default: 1000. Total number of home fossil fuel generators to model.</li>
<li> <b> Average Generator Capacity (kW) </b> (float) — Default: 20. The average capacity size (kW) of each home fossil fuel generator. The default value is based on a Generac 20 kW diesel generator. </li>
<li> <b> Available Fuel (gal) </b> (float) — Default: 95. Specify the maximum amount of generator fuel available (gallons) per device. The default value is based on a Generac 20 kW diesel model with a fuel tank capacity of 95 gallons.  </li>

<li> <b> Fuel Cost ($/gal) </b> (float) — Default: 3.49. Specify the cost in USD per gallon of fuel used for the generator. </li>

</ul>



### Chemical Energy Storage Device Inputs
* <b> Number of Home Chemical Batteries </b> (int) — Default: 100. Total number of residential chemical batteries to model.
* <b> Can grid charge? </b> (Yes/No) — Total number of residential chemical batteries to model.
* <b> Operational Power Capacity Cost </b> ($/kW) — Default: 20. Specify the operational cost per kW of enrolling and controlling a member-consumer's battery (e.g. the API usage cost).
* <b> Operational Energy Capacity Cost </b> ($/kWh) — Default: 60. Specify the operational cost per kWh of enrolling and controlling a member-consumer's battery (e.g. the API usage cost).
* <b> Battery Power Capacity </b> (kW) — Default: 5 kW. Specify the battery power capacity in kW for each individual battery enrolled by a member-consumer.
* <b> Battery Energy Capacity </b> (kWh) — Default: 13.5 kWh. Specify the battery energy capacity in kWh for each individual battery enrolled by a member-consumer.

### Home Air Conditioner Device Inputs
<ul> 
<li> <b> Enable Air Conditioner? </b> (Yes/No) — Default: Yes. If Yes, the model will run with a home central air conditioner. If No, the model will not run with a home air conditioner. 
<li> <b> Rated Power </b> (kW) — Default: 5.6. Maximum input power of the air conditioner. Must be a positive rational number between 0.1 and 7.2.  
<li> <b> Retrofit Cost </b> ($) — Default: 13. Cost to equip air conditioner to respond to utility load control signals. E.g. for a virtual power plant program, this would be the cost of installing a Wi-Fi enabled air conditioner control unit, typically about \$13. [[5]](#5)
<li> <b> Thermal Capacitance </b> (kWh/°C) — Default: 2. Thermal capacitance of the air conditioner. Must be between 0.2 and 2.5 with exactly one decimal digit.  
<li> <b> Thermal Resistance </b> (°C/kW) — Default: 2. Thermal resistance of the air conditioner. Must be between 1.5 and 140.  
<li> <b> Coefficient of Performance </b> — Default: 2.5. Coefficient of performance for the air conditioner. Must be between 1 and 3.5.
<li> <b> Temperature Setpoint </b> (°C) — Default: 22.5. Target temperature for the air conditioner, set at the thermostat. Must be between 1.7 and 54.  
<li> <b> Temperature Deadband </b> (°C) — Default: 0.625. Deadband around the setpoint temperature to alleviate temperature swings. Must be between 0.125 and 2.  
</ul> 

### Home Heat Pump Device Inputs
<ul> 
<li> <b> Enable Heat Pump? </b> (Yes/No) — Default: Yes. If Yes, the model will run with a home air-source heat pump.  
<li> <b> Rated Power </b> (kW) — Default: 5.6. Maximum input power of the heat pump. Must be a positive rational number between 0.1 and 7.2.  
<li> <b> Retrofit Cost </b> ($) — Default: 150. Cost to equip heat pump to respond to utility load control signals. 
<li> <b> Thermal Capacitance </b> (kWh/°C) — Default: 2. Thermal capacitance of the heat pump. Must be between 0.2 and 2.5 with exactly one decimal digit. 
<li> <b> Thermal Resistance </b> (°C/kW) — Default: 2. Thermal resistance of the heat pump. Must be between 1.5 and 140.  
<li> <b> Coefficient of Performance </b> — Default: 3.5. Coefficient of performance for the heat pump. Must be between 1 and 3.5 
<li> <b> Temperature Setpoint </b> (°C) — Default: 19.5. Target temperature for the tank, set at the thermostat. Must be between 1.7 and 54.  
<li> <b> Temperature Deadband </b> (°C) — Default: 0.625. Deadband around the setpoint; avoids excessive cycling of heat pump. Must be between 0.125 and 2.  
</ul> 

### Home Water Heater Device Inputs
<ul> 
<li> <b> Enable Water Heater? </b> (Yes/No) — If yes, model will run with a home water heater.  
<li> <b> Rated Power </b> (kW) — Default: 4.5. Maximum input power of the water heater. Must be a positive rational number between 0.1 and 7.2.  
<li> <b> Retrofit Cost </b> (\$) — Default: 175. Cost to equip water heater to respond to utility load control signals. E.g. for a virtual power plant program, this would be the cost of installing a Wi-Fi enabled water heater control unit, typically about \$175 (see [Aquanta Smart Electric Water Heater Controller](https://www.nysegsmartsolutions.com/Water-Fixtures/I-AQCAG100E-01-XXXX-XXXX-V1.html?srsltid=AfmBOoo--7Idu156g5c0j01oWowfjP4G50-wJW0ENwo3sZHoE7iQsvuL)). 
<li> <b> Thermal Capacitance </b> (kWh/°C) — Default: 0.4. Thermal capacitance of the water tank. Must be between 0.2 and 2.5 with exactly one decimal digit.  
<li> <b> Thermal Resistance </b> (°C/kW) — Default: 120. Thermal resistance of the water tank. Must be between 1.5 and 140.  
<li> <b> Coefficient of Performance </b> — Default: 1. Coefficient of performance for the water heater. Must be between 1 and 3.5 
<li> <b> Temperature Setpoint </b> (°C) — Default: 48.5. Target temperature for the tank, set at the thermostat. Must be between 1.7 and 54.  
<li> <b> Temperature Deadband </b> (°C) — Default: 3. Deadband around the setpoint temperature to alleviate swings in temperature. Must be between 0.125 and 3.
</ul> 


## Model Results
(Descriptions of model outputs and how to interpret them in context of the model use case(s).)

The chosen color schemes used for these plots are based on the following guide for color-blind friendly color schemes: [2022 NCEAS Science Communication Resource Corner by Alexandra Phillips](https://www.nceas.ucsb.edu/sites/default/files/2022-06/Colorblind%20Safe%20Color%20Schemes.pdf)

### Plot: DER Serving Load Overview

### Plot: Thermal Battery Power Profile

### Plot: Chemical BESS State of Charge

### Table: Monthly Cost Comparison

### Plot: Cash Flow Projection

### Raw Input and Output Files
* vbatResults.json
* temp.csv
* demand.csv
* Scenario_test_POST.json (need to remove)
* REoptInputs.json
* reopt_input_scenario.json
* results.json
* Plot_DerServingLoadOverview.html
* PPID.txt
* allInputData.json
* allOutputData.json

# Caveats
- This model does not consider leap years. The month of February is assumed to have 28 days.
- This model does not consider real time market fluctuations.
