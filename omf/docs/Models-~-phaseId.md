## Overview

Meter phases can change due to transformer maintenance and load balancing. If the phase changes aren't recorded correctly, it makes future load balancing difficult. This model identifies the true phase of AMI meters based on clustering the meters based on voltage correlation. While power line carrier meter reading systems can typically identify meter phase automatically, radio frequency meter reading systems, which are now being widely deployed, cannot.

You can create and run a new instance of the model via our web interface here: http://omf.coop/newModel/phaseId/fromWiki

The model is based on code and results developed by [Logan Blakely](https://energy.sandia.gov/programs/electric-grid/advanced-grid-modeling/key-personnel/logan-blakely/) and [Matthew Reno](https://energy.sandia.gov/programs/electric-grid/advanced-grid-modeling/key-personnel/matthew-j-reno/) at Sandia National Laboratory. For a full overview of the method, please see [the published methodology](https://ietresearch.onlinelibrary.wiley.com/doi/pdf/10.1049/iet-stg.2019.0280) and the [accuracy results](https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9382379) or access the [open source code](https://github.com/sandialabs/distribution-system-model-calibration/tree/main/sdsmc/PhaseIdentification).

The current model is able to detect phasing correctly even in the presence of multiple voltage regulators and distributed solar generation. Prior versions based on older results struggled with phasing these types of systems.

A prior version of this model relied The model is based on code and results developed by [Jeremy Keen](https://www.linkedin.com/in/jeremy-keen-71765125/). Those results are expansions of earlier results by Tom Short [Short]. That model was validated against a meter dataset collected from an African utility, and a set of synthetic meter readings generated from GridLAB-D and the [PNNL Taxonomic Feeders](https://pdfs.semanticscholar.org/b7d2/946e73aa2cba6c321f7802aefb375112439d.pdf) augmented with an NREL AMI meter data set. In each case, the model identified 100% of true phases on meters whose labels were changed as part of the test.

## Input Format and Requirements

The model requires one main input file, a .csv file with readings from AMI meters. The first row should contain the names you would like to use to identity each meter. The second row should contain the current best-known phase, expressed as 1, 2 or 3. The rest of the rows should include voltage readings for each of the meters over time. For an example of the format, please see [this example AMI input](https://github.com/dpinney/omf/blob/master/omf/static/testFiles/phaseID/sandia_test_data_2k_readings.csv).

If you have 3 phase loads on the system and each phase is metered separately, you can include that data in your input by giving each phase a separate column. If a 3 phase load has its voltages metered as single value averaging across the phases, you can include that as a column in the input data, but the output obviously will not be assigned to a phase correctly and should show up in the output as a result with a low confidence score.

A data length of at least 2880 datapoints (1 month of 15 minute reads) is recommended, but hourly readings from a full year (8760 data points) should be sufficient. The algorithm works as an ensemble, thus more data is likely to produce better results, particularly in the case of common data quality issues like intermittent missing values.

## Model Outputs

A confusion matrix, showing any meters whose label did not match the predicted true phase in the off-diagonal entries:

<img width="1136" alt="Screen Shot 2022-04-07 at 9 22 30 AM" src="https://user-images.githubusercontent.com/2131438/162208855-33f02b2e-2adc-4bdd-820b-a4943f869ec3.png">

An overview of the confidence scores for each of the predictions, and the percentage of meters that change:

<img width="1136" alt="Screen Shot 2022-04-07 at 9 22 38 AM" src="https://user-images.githubusercontent.com/2131438/162208902-13bc5f9e-567c-4c07-9cb7-7c422fab04c1.png">

A list of all meters with their input phases and predicted true phases:

<img width="1136" alt="Screen Shot 2022-04-07 at 9 22 44 AM" src="https://user-images.githubusercontent.com/2131438/162208999-27d3b578-bfa7-4e67-aacd-38a744f7d33a.png">

## References

[Therrien] Therrien, Francis, Logan Blakely, and Matthew J. Reno. ["Assessment of Measurement-Based Phase Identification Methods."](https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9382379) IEEE Open Access Journal of Power and Energy 8 (2021): 128-137.

[Blakely 2021] Blakely, Logan, et al. ["Leveraging Additional Sensors for Phase Identification in Systems with Voltage Regulators."](https://www.researchgate.net/profile/Matthew-Reno-2/publication/350845178_Leveraging_Additional_Sensors_for_Phase_Identification_in_Systems_with_Voltage_Regulators/links/6075a128a5c0b34b72ace9cc/Leveraging-Additional-Sensors-for-Phase-Identification-in-Systems-with-Voltage-Regulators.pdf) 2021 IEEE Power and Energy Conference at Illinois (PECI). IEEE, 2021.

[Blakely 2020] Blakely, Logan, and Matthew J. Reno. ["Phase identification using co-association matrix ensemble clustering."](https://ietresearch.onlinelibrary.wiley.com/doi/pdf/10.1049/iet-stg.2019.0280) IET Smart Grid 3.4 (2020): 490-499.

[Pena] Pena, Bethany D., Logan Blakely, and Matthew J. Reno. ["Parameter tuning analysis for phase identification algorithms in distribution system model calibration."](https://ieeexplore.ieee.org/document/9446218) 2021 IEEE Kansas Power and Energy Conference (KPEC). IEEE, 2021.

[Short] Short, Tom. (2013). [Advanced Metering for Phase Identification, Transformer Identification, and Secondary Modeling](http://distributionhandbook.com/papers/ieee_smart_grid_tshort_AMI_for_phase_identification_accepted_draft_2012-07-11.pdf). IEEE Transactions on Smart Grid. 4. 651-8. 10.1109/TSG.2012.2219081.

[Padullaparti] Padullaparti, Harsha, Santosh Veda, Surya Dhulipala, Murali Baggu, Tom Bialek, and Martha Symko-Davies. 2019. [Considerations for AMI-Based Operations for Distribution Feeders: Preprint](https://www.nrel.gov/docs/fy19osti/72773.pdf). Golden, CO: National Renewable Energy Laboratory. NREL/CP-5D00-72773.