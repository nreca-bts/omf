### Introduction

This model takes in historical demand data (hourly for a year) and calculates what demand changes in residential customers could be expected due to demand response programs. Program types the model can calculate are time of use pricing (TOU), peak time rebates (PTR), direct load control (DLC) or critical peak pricing (CPP). These calculations are done using the Brattle Group's [PRISM](https://brattlefiles.blob.core.windows.net/files/5645_prism_simulating_the_impact_of_demand_charges_in_the_absence_of_empirical_data.pdf) model.

### Walkthrough

1. Fill in the inputs that are blank. The rest are reasonable defaults. You can change them if you want.
2. The demand curve file must be a comma separated value file (.csv). Microsoft Excel can output this format. It must have 1 column with no title. The power values must be integer substation demand measurements in **kW**. The power values must be a full year of data with measurements every 1 hour. There should be a total of 8760 rows in a single column.

```csv
1981
1903
... [8760 rows total] ...
1921
```

If you would like to just try out the model, [an example demand file is available here](./images/demandExampleWinterPeak.csv).

### FAQs

* How are commercial and industrial loads handled? The PRISM model does not support industrial and commercial loads. In general, each C&I load is unique, so modeling them is prone to error unless there is lots of data on their behavior. If you input hourly demand data that includes C&I loads, you can exclude them (approximately) from the analysis by reducing the "Load Managed by the Program" input by the amount that those loads contribute to the data set. The best approach, if detailed metering data is available, is to only input demand data from residential loads.

* What are good values for the price elasticities? Many studies have been done that estimate elasticities for given circuits/climates/locations. We few collected [some example elasticities here](./images/DR%20Elasticity%20Estimates.xlsx).

* What are the details behind this implementation of PRISM? PNNL contributed an Excel implementation and ported that to Python in support of this effort. The [source spreadsheet](./images/PRISM%20Model%20Implementation%20by%20PNNL%20-%20Basis%20for%20prismDR.xls) is available at that link.

### Example Demand Response Program Parameters

CPP days:
- 18 days (https://www.sdge.com/sites/default/files/documents/cpp_factsheet.pdf)
- 12 days (https://www.sce.com/NR/rdonlyres/B73F4175-162B-4C4F-B953-4E0A94863390/0/CPPFactSheet0407.pdf)
- 15 days (http://www.pge.com/en/mybusiness/rates/tvp/peakdaypricing.page?)
- CPP tariff overview for CA (http://www.ecova.com/media/746011/ecova-cpp-8-27.pdf)
- 120 hours per season (http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf)

Start time:
- 11am (https://www.sdge.com/sites/default/files/documents/cpp_factsheet.pdf)
- 12pm (https://www.sce.com/NR/rdonlyres/B73F4175-162B-4C4F-B953-4E0A94863390/0/CPPFactSheet0407.pdf)
- 2pm (http://www.pge.com/en/mybusiness/rates/tvp/peakdaypricing.page?)
- 12pm (http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf)

Stop time:
- 6pm (https://www.sdge.com/sites/default/files/documents/cpp_factsheet.pdf)
- 6pm (https://www.sce.com/NR/rdonlyres/B73F4175-162B-4C4F-B953-4E0A94863390/0/CPPFactSheet0407.pdf)
- 6pm (http://www.pge.com/en/mybusiness/rates/tvp/peakdaypricing.page?)
- 7pm (http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf)

Start month:
- June 1 (https://www.sce.com/NR/rdonlyres/B73F4175-162B-4C4F-B953-4E0A94863390/0/CPP
FactSheet0407.pdf)
- May 1 (http://www.pge.com/en/mybusiness/rates/tvp/peakdaypricing.page?)
- June1 (http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf)

Stop month:
- Oct 1 (https://www.sce.com/NR/rdonlyres/B73F4175-162B-4C4F-B953-4E0A94863390/0/CPPFactSheet0407.pdf)
- Oct 31 (http://www.pge.com/en/mybusiness/rates/tvp/peakdaypricing.page?)
- Sept 30 (http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf)

TOU Rates:
PG&E http://www.pge.com/en/mybusiness/rates/tvp/toupricing.page
(interesting source, eh)
Off-peak: $0.223/kWh
On-peak: $0.260/kWh
Flat rate: $0.240/kWh

SDG&E http://my.teslamotors.com/forum/forums/tou-electricity-rates
Off-peak: $0.16/kWh
On-peak: $0.44/kWh

NYConEd http://my.teslamotors.com/forum/forums/tou-electricity-rates
Off-peak: $0.03/kWh
On-peak: $0.33/kWh

NV Energy (N. Nevada)
https://www.nvenergy.com/home/paymentbilling/timeofuse.cfm
Plan A
Off-peak: $0.0616/kWh
On-peak: $0.365/kWh
Flat rate: $0.04225
Plan B
Off-peak: $0.0628/kWh
On-peak: $0.505/kWh
Flat rate: $0.0505

http://www.alabamapower.com/residential/pricing-rates/pdf/cpp.pdf
CPP: $0.3167/kWh
On-peak: $0.1417/kWh