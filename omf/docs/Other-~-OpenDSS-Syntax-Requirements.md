### Introduction
OpenDSS has very permissive syntax rules, some of which can cause trouble when converting .dss files to other formats or using .dss files with tools other than OpenDSS. For the purposes of OMF models, .dss files must align with the following syntax rules.

***
### Syntax Rules

1. Object definitions must be of the following structure:  
    ```
    Command object=objectType.uniqueName property1=value1 property2=value2 propertyN=valueN
    ```
    For example:  
    ```
    New object=Line.L1 phases=1 bus1=busB.3 bus2=busA.3 length=257 units=Ft linecode=UGtype1
    ```  

    | Example Placeholders      | Can Be Replaced With |
    | ----------- | ----------- |
    | `Command`      | `Clear`, `New`, `Edit`, `Open`/`Close` (a switch), `MakeBusList`, `Set`, `SetBusXY`, `More` (usually abbreviated as `~` ) |
    | `objectType`   | Any OpenDSS-defined object type |
    | `uniqueName` | Any valid opendss object identifier (letters, numbers, and underscores only) |
    | `propertyN` | Any OpenDSS-defined object parameter |
    | `valueN` | Single numeric values must be entered as raw floating point numbers:<br>&nbsp;&nbsp;&nbsp;&nbsp;`%R=0.0001`<br>Array values must be defined as an array:<br>&nbsp;&nbsp;&nbsp;&nbsp;`buses=[bus1,bus2]`<br>Matrix values must be defined as an array of arrays:<br>&nbsp;&nbsp;&nbsp;&nbsp;`cmatrix=[[1,2,3],[4,5,6]]`<br>Note that a property can be edited later in the file using the `Edit` command and redefining only those properties to be altered:<br>&nbsp;&nbsp;&nbsp;&nbsp;`Edit object=Line.L1 length=80 linecode=UGtype2`|  

2. To define transformer winding properties, the array syntax must be used:  
    ```
    New object=Transformer.T4 Phases=1 Windings=3 XHL=2.76  XHT=2.76  XLT=1.84 Buses=[bus1014.2.0,T_bus1014_L.1.0,T_bus1014_L.0.2] conns=[wye,wye,wye] kVs=[7.9677,0.120,0.120] kvas=[25,25,25] %Rs=[0.7,1.4,1.4]
    ```  
    When defining buses, the high winding of a transformer is first in the `buses` array. This winding is also electrically closest to the substation.  

    Note that some of the property names are pluralized (`buses`, `conns`, `kvs`, `kvas`, `%rs`).  

    > `RdcOhms` cannot be defined for multiple windings. This is an issue with OpenDSS that may be remedied in the future. The `RdcOhms` property is not notably mentioned in the OpenDSS primer, the manual, or the online discussion forum. The most information comes from the in-software help files, which state that the `RdcOhms` transformer property represents the "Winding dc resistance in OHMS. Useful for GIC analysis. From transformer test report. Defaults to 85% of %R property."<br>   
    It appears this is a value that is set automatically when the circuit is loaded into OpenDSS, and may be explicitly stated by OpenDSS if the circuit definition is then exported. It seems that `RdcOhms` is typically not defined by users, as there have been no observed instances of such in the OpenDSS IEEE example files on SourceForge.<br>  
    It is suggested that a multi-winding definition of `RdcOhms` property not be supported. In the seemingly rare case that someone would want to define RdcOhms for each winding, they may not be able to do so.

3. For `load` objects, the reactive portion of its demand must be defined using either `pf` or `kvar` throughout the circuit; mixed usage is not supported.  

4. Connectivity information (e.g. values of properties `bus=`, `bus1=`, `buses=`) must explicitly define individual node connections using the `.` syntax:  
    - `bus1=busA.1.2.3 bus2=busB.1.2.3`
    - `buses=[busA.1.2.3, busB.1.2.3]`  

    Additionally, connectivity must be defined such that the `from` bus (the one closest to the source) is indicated by the following properties:
    - `bus`
    - `bus1`
    - `buses` (first member)	

5. All text shall be lowercase.

6. All buses must be declared using the following syntax:
    ```
    MakeBusList
    SetBusXY bus=bus1 X=xcoord1 Y=ycoord1
    SetBusXY bus=bus2 X=xcoord2 Y=ycoord2
    SetBusXY bus=busN X=xcoordN Y=ycoordN
    ```

<!--
Secret 7th point! Not from the DSS Parsing paint points powerpoint, but something Saeed specifically found breaks PowerModelsONM: 

7. Single-phase elements must use a single node reference consistent with the declared phase identity. (The following example is using .omd format)  
    ```
    Yes:
    "object": "pvsystem", 
    "name": "yes_example",
    "phases": "1",
    "!CONNCODE": ".1", ...

    No:
    "object": "pvsystem", 
    "name": "no_example",
    "phases": "1",
    "!CONNCODE": ".1.2", ...

    ```
    -->

***
### Unsupported Syntax
Anything not expressed as being supported by the OMF .dss parser should be assumed unsupported. This includes but is not limited to:

1. Multi-file circuit definitions:
    - `Compile transformers.dss`
    - `Redirect transformers.dss`
    - `New Loadshape.Shape_4 mult=(file=profiles\Loadprofile4.t xt)`

2. Reverse polish notation.

3. Scientific notation.

4. Positional parameter definitions (i.e. unnamed properties):
    - `New   "Line.First Line",  b1240   32   336ACSR`

5. Object-relative definitions (`like=`) syntax:  
    ```
    New object=Transformer.T4 Phases=1 Windings=3 XHL=2.76  XHT=2.76  XLT=1.84 Buses=[bus4.2.0,T_bus4_L.1.0,T_bus4_L.0.2] conns=[wye,wye,wye] kVs=[7.9677,0.120,0.120] kvas=[25,25,25] %R=[0.7,1.4,1.4]
    New object=Transformer.T5 like=T4 Buses=[bus5.2.0,T_bus5_L.1.0,T_bus5_L.0.2] %R=[0.7,1.4,1.4]
    ```

6. Per-winding transformer definition (`wdg=`) syntax:  
    ```
    New object=Transformer.T4 Phases=1 Windings=3 XHL=2.76 XHT=2.76 XLT=1.84 wdg=1 Bus=bus1014.2.0 conn=wye kV=7.9677 kva=25 %R=0.7 wdg=2 Bus=T_bus1014_L.1.0 conn=wye kV=0.120 kva=25 %R=1.4 wdg=3 Bus=T_bus1014_L.0.2 conn=wye kV=0.120 kva=25 %R=1.4. 
    ```

7. Repeated key-value pairs within an object definition (used to redefine a property’s value).

8. Use of period characters within the `uniqueName` of an object declaration.






