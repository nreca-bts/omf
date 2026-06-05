# Introduction

The networkStructure model takes in a feeder system and a .csv file containing voltage data, then compares the actual connectivity of the system to connectivity arrived at by minimizing distances and difference in voltages between nodes. It can also take in a list of training data as a .csv file and train a machine learning model to determine connectivity using support vector machines.

# Walkthrough

The model takes in a feeder system in the form of a .omd file. It also takes in a set of voltage data in the form of a .csv file. The voltage data must contain the following columns and format for each column:
node_name - the name of a node, exactly as it appears in the .omd file
voltA_real - the real part of voltage A
voltA_imag - the imaginary part of voltage A
voltB_real - the real part of voltage B
voltB_imag - the imaginary part of voltage B
voltC_real - the real part of voltage C
voltC_imag - the imaginary part of voltage C

Note: All voltage values are floats. Also, if a given node does not have three phases of voltage, fill in the missing phases with 0.0.

The 'Use Distance?' input dictates whether location/distance data will be used in determining expected connectivity.

The 'Use Voltage?' input dictates whether voltage data will be used in determining expected connectivity.

The 'Use Support Vector Machine' input dictates whether support vector machines will be employed to check the validity of the connectivity of the input .omd using training data.

The 'Training Data' input is a .csv file with two columns and the following format:
omd_path - the end of the path to an .omd file which will be used as training data (ex: /static/publicFeeders/ieee37nodeFaultTester.omd)
csv_path - the end of the path to a .csv file containing voltage data for the system at a given time and formatted in the way described above to be used as training data (ex: /scratch/smartSwitching/volt1.csv)

# Model Results

Actual Connectivity Graph - A visual representation of the actual connectivity of the system

<img width="675" alt="actual" src="https://user-images.githubusercontent.com/54141633/71657626-f101da80-2cfd-11ea-93f4-f86657e4bd1c.png">

Distance Connectivity Graph - A visual representation of the expected connectivity arrived at by minimizing the total distance between each node. Note: the dotted lines illustrate the actual connectivity of the system and how much it differs from the expected connectivity due to distances

<img width="660" alt="distance" src="https://user-images.githubusercontent.com/54141633/71657629-f2cb9e00-2cfd-11ea-8373-839b09412ab2.png">

Voltage Connectivity Graph - A visual representation of the expected connectivity arrived at by minimizing the total voltage between each node. Note: the dotted lines illustrate the actual connectivity of the system and how much it differs from the expected connectivity due to voltages

<img width="600" alt="voltage" src="https://user-images.githubusercontent.com/54141633/71657630-f4956180-2cfd-11ea-9129-e0ea953ecf8b.png">

Results and Tests - The distance/voltage tests are passed if there is reasonable certainty that the true connectivity and the connectivity arrived at by minimizing distance and/or voltage are similar enough that the connectivity cannot be random. The distance/voltage percent similar gives the percentage of similarity between the true connectivity and the connectivity arrived at by minimizing distance and/or voltage. The support vector machine tests provide accuracy, precision, and recall measures of the model.

<img width="755" alt="results" src="https://user-images.githubusercontent.com/54141633/71657633-f65f2500-2cfd-11ea-91de-2ec0c4494be3.png">