Data from Milsoft's engineering analysis program [Windmil®](http://www.milsoft.com/utility-solutions/upgrades/milsoft-engineering-analysis-ea-windmil®) can be imported to the OMF. Below are the steps needed to do this.

### ASCII Format Import

To upload directly to [OMF.coop](https://www.omf.coop/):

1. In Windmil, in the "Work Environment" tab on the left side of the screen, make sure only one circuit is checked.
2. Select the File > Export... menu option.
3. Choose "Standard ASCII" and click next.
4. Make sure only two boxes are checked: "Circuit Elements (.STD)" and "Equipment Data (.SEQ)" and click next.
5. For the export options, make sure impedance lengths are in "Feet", and for the check boxes, make sure only one is checked: "Export the GUID of each elements (allows tighter integration)" and click next.
6. For Scope of export, make sure the scope is "Enabled circuits only".
7. Note the export destination and click finish.
8. The resulting .seq and .std files can be uploaded to OMF.coop.

### Native Format Sharing

If you'd like to share a copy of the native Windmil data format instead:

1. In Windmil, the menu option File > View Model Info... will show where the model data is stored.
2. Zip up and share the .wm and eqdb folders.
3. If you’d prefer to send just one circuit instead of the full system, copy the .wm folder first, open that copy in Windmil, and delete anything you wouldn’t like to share. The eqdb should not be modified.

### Debugging Before Import

When preparing a Milsoft WindMil model of a feeder for export to NRECA’s Open Modeling Framework (OMF), the following steps should be taken to “debug” the model and ensure that voltage drop analysis runs correctly.

1. Run Circuit Diagnostics Analysis and correct any errors/warnings. Pay specific attention to:
    1. Undefined conductors—assign equipment from EQDB to all, including secondary
    2. Conductors with these errors/warnings may indicate an equipment definition with no (or missing) conductor properties:
        1. “Zero Distance or Diameter”
        2. “Calculation of Impedance Failed”
        3. “Find Impedance Method”
        4. “calcZrc Failed”
        5. “getCondData Failed”
    3. Undefined distribution/service transformers—assign equipment identifier to all transformers; if transformer size is unknown, use a reasonable standard size
    4. Transformers with “Transformer kVA rating 0.0”—may indicate equipment definition with no transformer properties
    5. Transformer voltage is “XXX.XX percent of parent kV”—indicates transformer defined voltages (or source voltages) are incorrect
        1. Verify source voltage settings, substation power transformer secondary voltages and primary system step-down transformer secondary voltages, then run the “Set Transformer Input Voltages” updateable utility.
    6. Ensure all voltage regulator and capacitor definitions and settings are correct
    7. Ensure sources are set up correctly and impedances defined
        1. If the substation power transformer is modeled, the source should reflect the incoming high-side transmission voltage and Thevenin equivalent impedance for the transmission system.
        2. If the substation power transformer is not modeled, the source should reflect the substation low-side voltage and the source impedance must include the substation power transformer as well as the Thevenin equivalent impedance for the transmission system.
2. Apply consumer billing data to model
    1. Elements in billing file with no matching elements in model should represent fewer than 2% of consumers on the feeder and should not include any larger usage consumers
    2. Elements in billing file that do not match the phasing of the WindMil model will be defaulted to the WindMil model phasing
3. Allocate feeder peak load and verify load allocation is realistic in terms of power factor, load factor, transformer loading and kW per consumer.
4. Run Voltage Drop analysis after checking parameters:
    1. Run Unbalanced
    2. Initiate voltages at “Source Bus V olt”
    3. Identify any areas of the system where the voltages appear unrealistic and compare to field measurements where available to validate the model and load allocation
5. Check phase load balance & consider using Load Balance analysis if unbalance is greater than 10%

The model export should then be run using the options described above in the [ASCII Format Import](#ascii-format-import) section.

### Transforming to Latitude and Longitude Coordinates.

Windmil models usually have their components located in the state plane coordinate system. To translate to latitude and longitude for mapping:

1. Find the state plane your model is using by going to Preferences > Choose Coordinate System and note the zone.
2. In the OMF source code, omf.geo.shortToEpsg will let you translate between the zone and the corresponding EPSG code.
3. You can use the EPSG code to translate the coordinate system via omf.milToGridlab.mapFeetToLatLon