### Introduction
Computation times to process complex circuit models can be reduced by simplifying them to smaller but electrically-equivalent versions using this command-line tool.

***
### How To Use

<!-- An API interface has been built and is under review.
When that has been accepted, add documentation for that here.-->

#### _Requirements_
Users must first have the [OMF downloaded and installed](https://github.com/nreca-bts/omf/wiki/Dev-~-Installation-Instructions), along with all of its requirements.

#### _Usage_
This tool is a python script that can be run from the command line. The script is located at `omf/omf/scratch/reduceFeeder.py` and can be run from any directory using the full path.  
This script does not alter the .dss file given as input. Once run, a new .dss file containing the reduced feeder will exist in the same directory as the input file.   
| OS          | Command |  New File Created |
|-            |-        | -                 |
| Windows     | `python C:/example/path/to/omf/omf/scratch/reduceFeeder.py feederToReduce.dss`| `feederToReduce_reduced.dss` |
| macOS/Linux | `python3 /example/path/to/omf/omf/scratch/reduceFeeder.py feederToReduce.dss` | `feederToReduce_reduced.dss` |

#### _CLI Example Usage_
```
C:\Users\demoUser> python C:/Users/demoUser/omf/omf/scratch/reduceFeeder.py C:/Users/demoUser/Desktop/feederToReduce.dss 

Performed feeder reduction, reducing the size of the feeder by 24 objects (oldsz=1324, newsz=1300)

C:\Users\demoUser> python C:/Users/demoUser/omf/omf/scratch/reduceFeeder.py -h
usage: reduceFeeder.py [-h] dssFileName

Simplify openDSS circuit models to smaller but electrically-equivalent versions. For more information, visit
https://github.com/nreca-bts/omf/wiki/Other-~-modelReduction

positional arguments:
  dssFileName  Path to the .dss file to be reduced.

optional arguments:
  -h, --help   show this help message and exit
```


***
### How It Works
This model simplification method uses 3 reduction techniques in sequence to maximize reductions: 
1. mergeContigLines
2. rollUpTriplex
3. rollUpLoadTransformer

#### _mergeContigLines_
Adjacent line elements that are similar in all properties except length and connectivity are combined into a single line element. This is performed until no more candidate line pairs exist.  
__Process:__ 
* Line lengths are summed
* Connections are adjusted
* Ensures relevant line properties are equal
* Avoids switches
* Ensures no other elements being disconnected from bus

__Notes:__
* This method is performed iteratively until there are no more candidates to act upon.
* Note that opendss defines line resistances and reactances per unit length.
* Code also works the same for lines with fewer conductors.
<br><br>
#### _rollUpTriplex_
Multiple loads connect to a single line which connects to a transformer. The line is removed and its losses captured in the load’s demand through an approximate method (0.81% loss applied).  
__Process:__
* Load kw increased by 0.81%
* Connections are adjusted
* Ensures no other elements being disconnected from bus

__Notes:__
* Corrections to power factor are negligible because triplex lines are short. 
* Also works for fewer conductors.
<br><br>
#### _rollUpLoadTransformer_
Multiple loads connect to a transformer. The transformer is removed and its losses captured in the load’s demand through an approximate method.  
__Process:__
* Load kw increased by 2.5%
* kv is set to transformer primary winding voltage
* Connections are adjusted
* Phases are corrected
* Considers delta vs wye connected transformers
* Ensures no other elements being disconnected from bus

__Notes:__
* This method does not check for regulators or other devices associated with the transformer being removed. This is reasonable because load-serving transformers are rarely voltage controlled by regulators.




