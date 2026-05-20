❗<b> NOTE </b> ❗ omf.models.derConsumer is a new model currently under development. Check back in the coming months for updates!


# Introduction
TODO: 
* Describe the purpose of the model and the use cases it was developed to address.

The derConsumer model evaluates the financial cost-benefit for a residential consumer interested in installing or enrolling behind-the-meter distributed energy resources (DERs) with their electric utility or cooperative.

This model uses the National Renewable Energy Laboratory's Renewable Energy Optimization Tool (REopt) and the OMF virtual battery dispatch module (vbatDispatch).

The estimated runtime of the model (for the first time; including building and compiling the REopt Julia system image) is about 8.5 minutes for MacOS running with the Apple M2 architecture. On a Windows machine, building the REopt Julia system image can take about 1.5 hours. Fortunately, after this initial run the model should compile much faster (on the order of 30 seconds for the same MacOS system). 
 
# Walkthrough
(Descriptions of required input formats, how to prepare a custom model. Inputs from the default model are used as illustrative examples.)

## Inputs
### General Model Inputs
<ul>
<li> <b> Demand Curve </b> (.csv file) — Default: residential_PV_load_tenX.csv. The demand curve should be formatted as a .csv file with a length of 8760 values representing the hourly demand (kW) for one entire year beginning on January 1. You may be able to obtain a demand curve from your electric utility or cooperative. 

```csv
8.538
8.7564
8.6784
8.6524
9.11
10.0928
11.2472
10.8624
9.8068
9.0112
...
8.1844
8.1272
8.3768
10.5712
12.3236
12.8072
12.724
12.7188
11.7568
10.5036
10.7324
```

<li> <b> Temperature Curve </b> (.csv file) —  Default: open-meteo-denverCO-noheaders.csv. This is assumed to be the outdoor air temperature corresponding to your utility’s service area and year of the provided Demand Curve. The format is the same as the Demand Curve: a .csv file with a length of 8760 values representing the hourly temperature data in degrees Fahrenheit for the entire year. An example of a valid .csv (shortened for brevity):

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

<li> <b> Latitude </b> (decimal) — Default: 39.969753. The latitude coordinate of the member-consumer’s house or meter. The default case assumes the latitude for Brighton, CO.
<li> <b> Longitude </b> (decimal) — Default: -104.812599. The longitude coordinate of the member-consumer’s house or meter. The default case assumes the latitude for Brighton, CO.
<li> <b> Year </b> (int) — Default: 2018. The year corresponding to the Demand Curve values.
</ul>

### Financial Inputs
<ul>
<li> <b> Use URDB Label? </b> (checkbox) — Default: Checked. If this input is checked, the model will use the provided URDB Label to obtain energy rate structure information for the analysis. If it is unchecked, the model will instead use the Residential Rate Structure file as the energy rate structure for the analysis. 
<li> <b> URDB Label </b> (string) — Default: 66a13566e90ecdb7d40581d2. The Utility Rate Database (URDB) is a free Open Energy Information database containing rate structures for utilities and cooperatives across Turtle Island (a.k.a the United States). The default case is a Residential Time of Day rate structure. You can obtain the URDB label by copying the string of letters and numbers found at the end of the Utility Rate Database (URDB) URL. For example, 

`https://openei.org/apps/IURDB/rate/view/66a13566e90ecdb7d40581d2`

would yield the URDB label:  `66a13566e90ecdb7d40581d2` 

> NOTE: Remove the suffix 
`“#3__Energy”, “#2__Demand”, or “#1__Basic_Information”` 
in the URDB label, if needed. This can be seen at the end of the website link when retrieving your URDB label: 
`https://apps.openei.org/USURDB/rate/view/66a13566e90ecdb7d40581d2\#3__Energy` This happens when you have clicked on one of those pages to view the rate information which changes the URL.) 

<li> <b> Residential Rate Structure (Optional) (.json file) </b> (%) — Default: TODrate66a13566e90ecdb7d40581d2.json. This is a .json file describing the energy rate structure that a residential customer pays to the utility or cooperative. This input allows a utility to upload a custom rate structure if the URDB Label is not known or is incorrect. An example of a valid .json file: 

```json
{"energyweekdayschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1]],
"energyweekendschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2,2,2,2,1,1]],
"energyratestructure":[[{"rate":0,"unit":"kWh"}],[{"rate":0.06,"unit":"kWh"}],[{"rate":0.1525,"unit":"kWh"}]],
"demandratestructure":[[{"rate":0,"unit":"kW"}],[{"rate":4.0,"unit":"kW"}]],
"demandweekdayschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]],
"demandweekendschedule":[[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],[1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1]]}
```
The example above was created using the REopt Web Tool custom electric rate tariff generator following their instructions here: https://github.com/NREL/REopt-Analysis-Scripts/wiki/5.-Custom-Electric-Rates. The rate structure information was based on a Colorado utility's Time of Day residential rate structure found at https://apps.openei.org/USURDB/rate/view/66a13566e90ecdb7d40581d2#3__Energy.

<li> <b> Discount Rate </b> (%) — Default: 1. The discount rate is used to devalue future incomes in the financial analysis (e.g. when calculating the Net Present Value). Income received now is generally more valuable than income received later.
<li> <b> Financial Projection Length </b> (years) — Default: 25. Number of years to project out the estimated savings. Must be between 1 and 75 years. Note that since the input Demand Curve and Energy Rate Curve are only given for the first year of the analysis, all subsequent years will duplicate the first year’s costs and savings. For example, if the total savings for the first year amount to $100 and the Financial Projection Length is 10 years, then each year will use $100 as the savings.
<li> <b> Energy Compensation Rate </b> ($/kWh) — Default: 0.1. The dollar amount paid to you by the utility for each kWh borrowed for each DER technology (e.g. fossil fuel generator, chemical BESS, and all thermal technologies). 
<li> <b> Home BESS - Upfront Subsidy Amount </b> ($) — Default: 100.0. The total upfront dollars paid to you by the utility for enrolling your home battery (not including any recurring subsidies).
<li> <b> Home BESS - Monthly Recurring Subsidy Amount </b> ($) — Default: 55.0. The total monthly recurring dollars paid to you by the utility for keeping your home battery enrolled (not including any upfront subsidies).
<li> <b> Home Heat Pump - Upfront Subsidy Amount </b> ($) — Default: 25.0. The total upfront dollars paid to you by the utility for enrolling your heat pump (not including any recurring subsidies).
<li> <b> Home Heat Pump - Monthly Recurring Subsidy Amount </b> ($) — Default: 5.0. The total monthly recurring dollars paid to you by the utility for keeping your home heat pump enrolled (not including any upfront subsidies).
<li> <b> Home Air Conditioner - Upfront Subsidy Amount </b> ($) — Default: 25.0. The total upfront dollars paid to you by the utility for enrolling your air conditioner (not including any recurring subsidies).
<li> <b> Home Air Conditioner - Monthly Recurring Subsidy Amount </b> ($) — Default: 5.0. The total monthly recurring dollars paid to you by the utility for keeping your home air conditioner enrolled (not including any upfront subsidies).
<li> <b> Home Water Heater - Upfront Subsidy Amount </b> ($) — Default: 25.0. The total upfront dollars paid to you by the utility for enrolling your water heater (not including any recurring subsidies).
<li> <b> Home Water Heater - Monthly Recurring Subsidy Amount </b> ($) — Default: 5.0. The total monthly recurring dollars paid to you by the utility for keeping your home water heater enrolled (not including any upfront subsidies).
<li> <b> Home Generator - Upfront Subsidy Amount </b> ($) — Default: 25.0.  The total upfront dollars paid to you by the utility for enrolling your home generator (not including any recurring subsidies). 
<li> <b> Home Generator - Monthly Recurring Subsidy Amount </b> ($) — Default: 5.0. The total monthly recurring dollars paid to you by the utility for keeping your home generator enrolled (not including any upfront subsidies).
</ul>

### Fossil Fuel Generator Device Inputs
The model assumes these default inputs when the specified Fuel Type is selected.

| Fuel Type     | Efficiency    | Fuel Cost[[1]](#1) | Available Fuel |
| :---: | --- | --- | --- |
| Natural Gas | 30\%[[4]](#4) |\$0.00386/cu.ft.| 1000 cu.ft.    |
| Propane  | 25\%[[2]](#2)[[4]](#4)  |\$2.70/gallon   | 1000 gallons   |
| Diesel  | 35\%[[3]](#3)[[4]](#4)  |\$3.80/gallon   | 1000 gallons   |
| Gasoline | 25\%[[3]](#3)[[4]](#4)  |\$3.17/gallon   | 1000 gallons   |

<ul>
<li> <b> Enable Use of Fossil Fuel Generator? </b> (Yes/No) — Default: Yes. If yes, the model will run with a fossil fuel generator. If no, the fossil fuel generator will not be included in the analysis.
<li> <b> Fuel Type </b> (Natural Gas|Propane|Diesel|Gasoline) — Default: Diesel. Type of fossil fuel used for the generator. 
<li> <b> Rated Power Capacity </b> (kW) — Default: 5. Specify the operating power of the fossil fuel generator.
<li> <b> Efficiency </b> (\%) — Default: 35. Specify the efficiency of the generator. The default value assumes a diesel fuel generator. 
<li> <b> Retrofit Cost </b> (\$) — Default: 0.0. Specify the cost to enable the generator for utility control.
<li> <b> Available Fuel </b> — Default: 1000. Specify the annual amount of generator fuel available. For natural gas, this input expects units of cubic feet. For all other liquid fuels, the expected units are gallons. The default value assumes a diesel fuel generator with 1000 gallons of fuel available. 
<li> <b> Fuel Cost </b> — Default: 3.80. Specify the cost of fuel used for the generator. For natural gas, this input expects units of \$/cubic foot. For all other liquid fuels, the expected units are \$/gallon. The default value assumes a diesel fuel generator.
<li> <b> Generator Replacement Cost </b> (\$/kWh) — Default: 450. Specify the cost of replacing the generator in the specified year in \$/kW. 
<li> <b> Generator Lifetime </b> (years) — Default: 15. Specify after how many years in which the generator will be replaced at the cost specified in the Generator Replacement Cost input. Input is an integer less than or equal to the analysis period in years.
</ul>

### Chemical Battery Energy Storage System (BESS)
<ul>
<li> <b> Enable Use of Home Chemical BESS? </b> (Yes/No) — Default: Yes. If Yes, model will run with a home chemical battery. If No, the model will not run with a home chemical battery.
<li> <b> Battery Power Capacity </b> (kW) — Default: 5. Specify the home chemical battery power capacity in kW.
<li> <b> Battery Energy Capacity </b> (kWh) — Default: 13.5. Specify the home chemical battery energy capacity in kWh. 
<li> <b> Retrofit Cost </b> ($) — Default: 0.0. Specify the cost to enable the battery for utility control. Typically, the BESS will already be enabled and this cost will be 0.
<li> <b> Portion of Charge Shared with Utility </b> (%) — Default: 20. The maximum percentage of full charge that you will allow the utility to use at any time.
<li> <b> Battery Replacement Power Cost ($/kW) </b> — Default: 324.0. Specify the cost of replacing the battery inverter at the specified year in $/kW.
<li> <b> Battery Replacement Energy Cost ($/kWh) </b> — Default: 351.0. Specify the cost of replacing the battery capacity at the specified year in $/kWh.  

> NOTE: The total battery replacement cost is modeled as (BESS Power Capacity in kW) * ($324/kW) + (BESS Energy Capacity in kWh) * ($351/kWh). These values were derived by reducing the 2022 values from Figure 4 in [NREL FY23 OSTI](https://www.nrel.gov/docs/fy23osti/85332.pdf) to 90%.

<li> <b>  Battery Lifetime </b> (years) — Default: 10. Specify a year in which the battery cells will be replaced at the cost specified in Battery Replacement Capacity Cost. Input is an integer less than or equal to the analysis period in years.
<li> <b>  Inverter Replacement Cost </b> ($) — Default: 2400. Specify the cost of replacing the inverter.
<li> <b> Inverter Lifetime </b> (years) — Default: 10. Specify a year in which the battery inverter will be replaced at the cost specified in Inverter Replacement Cost. Input is an integer less than or equal to the analysis period in years.
</ul> 

### Home Air Conditioner Device Inputs
<ul> 
<li> <b> Enable Air Conditioner? </b> (Yes/No) — Default: Yes. If Yes, the model will run with an in-window home air conditioner unit. If No, the model will not run with a home air conditioner. 
<li> <b> Rated Power </b> (kW) — Default: 0.5. Maximum input power of the unit. Must be a positive rational number between 0.1 and 7.2.  
<li> <b> Retrofit Cost </b> ($) — Default: 13. Cost to equip air conditioner to respond to utility load control signals. E.g. for a virtual power plant program, this would be the cost of installing a Wi-Fi enabled air conditioner control unit, typically about \$13. [[5]](#5)
<li> <b> Thermal Capacitance </b> (kWh/°C) — Default: 2. Thermal capacitance of the air conditioner unit. Must be between 0.2 and 2.5 with exactly one decimal digit.  
<li> <b> Thermal Resistance </b> (°C/kW) — Default: 2. Thermal resistance of the air conditioner unit. Must be between 1.5 and 140.  
<li> <b> Coefficient of Performance </b> — Default: 2.5. Coefficient of performance for the air conditioner unit. Must be between 1 and 3.5.
<li> <b> Temperature Setpoint </b> (°C) — Default: 22.5. Target temperature for the unit, set at the thermostat. Must be between 1.7 and 54.  
<li> <b> Temperature Deadband </b> (°C) — Default: 0.625. Deadband around the setpoint; avoids excessive cycling of heat pump. Must be between 0.125 and 2.  
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

### Plot: DER dispatch schedule with new BESS

### Plot: DER Serving Load Overview (using REopt)

### Table: Monthly Cost Comparison

### Plot: Cash Flow Projection

## References
<a id=“1”>[1]</a> These values were based on the reported values from NRECA’s [Weekly Fuel Price Watch](https://www.electric.coop/weekly-fuel-price-watch) in March 2025.

<a id=“2”>[2]</a> 
Thermal Efficiency of Propane fuel can range [from 25-34\%.](https://www.researchgate.net/figure/a-Comparisons-between-effective-efficiency-for-Gasoline-and-Propane-for-various_fig18_263874565) Figure 10 of this research article shows the effective thermal efficiencies for various engine speeds, specifically for propane and gasoline. The efficiency ranges from 25-34\% for propane, and 28-33\% for gasoline.

<a id=“3”>[3]</a> 
[The Efficiency of Diesel Generators: A Comprehensive Analysis](https://www.ourmechanicalcenter.com/archives/12117). This resource claims that the thermal efficiency range is 20-30\% for gasoline fuel and 35-45\% for diesel fuel.

<a id=“4”>[4]</a> 
Thermal Efficiency of Gasoline fuel can range [Sustainable Maintenance: How Does Generator Efficiency Vary Across Fuel Types?](https://www.sustainablemaintainance.com/2025/02/how-does-generator-efficiency-vary.html) This resource claims that the thermal efficiencies are 20-30\% for gasoline fuel, 25-35\% for natural gas fuel, 25-30\% for propane fuel, and 30-40\% for diesel fuel. 

<a id=“5”>[5]</a> 
See [Enbrighten 125-Volt-1-Outlet Indoor Smart Plug](https://www.lowes.com/pd/Enbrighten-125-Volt-1-Outlet-Indoor-Smart-Plug/1003202046) About \$13 in April 2025. 

