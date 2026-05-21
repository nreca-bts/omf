# -*- coding: utf-8 -*-
"""
Provide sample scripts for Sandia constrained-agglomerative ensemble phase
identification.

BSD 3-Clause License

Copyright 2021 National Technology & Engineering Solutions of Sandia, LLC (NTESS). Under
the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain
rights in this software.

Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this   list of
conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,   this list
of conditions and the following disclaimer in the documentation   and/or other materials
provided with the distribution.

* Neither the name of the copyright holder nor the names of its   contributors may be
used to endorse or promote products derived from   this software without specific prior
written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY
EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.



This file contains a sample script for running the Co-Association Matrix Ensemble Phase
Identfication algorithm which uses customer advanced metering  infrastructure (AMI) data
with an ensemble spectral clustering algorithm and  co-association matrix to cluster
customers by their service phase.

This script also requires functions that are in CA_Ensemble_Funcs.py and
PhaseIdent_Utils.py

Input Data Formatting:     voltageInput: numpy array of float - This matrix contains the
voltage          measurements (in volts) for all customers under consideration.  The
matrix should be in the form (measurements,customers) where each          column
represents one customer AMI timeseries.  It is recommended that         the timeseries
interval be at least 15-minute sampling, although the         algorithm will still
function using 30-minute or 60-minute interval         sampling     custIDInput: list of
str - This is a list of customer IDs as strings.  The         length of this list should
match the customer dimension of voltageInput     phaseLabelsErrors: numpy array of int -
This contains the phase labels for         each customer in integer form (i.e. 1 - Phase
A, 2 - Phase B,         3 - Phase C).  Any integer notation may be used for this field;
it is          only used to assigned the final phase predictions.  In practice, this
field could even be omitted, the phase identification results from          CAEnsemble
will still be grouped by phase, and the assignment of final         phase labels could
be left for a post-processing step by the utility.         The dimensions of this matrix
should be (1, customers).         These are assumed to be the original, utility labels,
which         may contain some number of errors.  The sample data included with these
scripts has ~9% of phase labels injected with errors.  This can be          seen by
comparing this field with the entries in phaseLabelsTrue which         contains the
ground-truth phase labels     phaseLabelsTrue: numpy array of int (1,customers) - This
contains the          ground-truth phase labels for each customer, if available.  Note
that,         in practice this may not be available, but for testing purposes this
is provided along with functions to evaluate the phase identifcation         accuracy
against the ground-truth labels.          The indexing of each of the input data must
match, i.e. voltageInput[:,1] must     represent the same customer as custIDInput[1],
phaseLabelErrors[0,1] and     phaseLabelsTrue[0,1]


"""

##############################################################################

# Import - Python Libraries
import numpy as np
from pathlib import Path
import pandas as pd

# Import - Custom Libraries

if __package__ in [None, '']:
    import CA_Ensemble_Funcs as CAE
    import PhaseIdent_Utils as PIUtils
else:
    from . import CA_Ensemble_Funcs as CAE
    from . import PhaseIdent_Utils as PIUtils

if __name__ == '__main__':
    ##############################################################################
    #
    #       Flags

    # Use the numPhases field if available
    #   Each datastream ID must be unique, even if there are multiple datastreams 
    #      from the same customer, as in the 3-phase case
    #   If the number of phases is known for each customer that will be used to 
    #      assign unique datastream names (if necessary) and 2-phase and 3-phase
    #      datastreams from the same customer will not be allowed to cluster together
    useNumPhasesField = True

    # This script has the ability to compare the predicted labels to the true labels.  
    #   If true labels are available set this flag True (as in the provided sample data) otherwise set to False
    useTrueLabelsFlag = True

    ##############################################################################
    #                    Load Sample Data

    
    currentDirectory = Path(__file__).parent.resolve()
    filePath = Path(currentDirectory.parent,'SampleData')
    filenameV = Path(filePath,'VoltageData_AMI.csv')
    voltageInputCust = PIUtils.ConvertCSVtoNPY( filenameV )
    
    filenamePLE = Path(filePath,'PhaseLabelsErrors_AMI.csv')
    phaseLabelsErrors = PIUtils.ConvertCSVtoNPY( filenamePLE )
    
    filenameIDs = Path(filePath,'CustomerIDs_AMI.csv')    
    with open(filenameIDs, 'r') as file:
        custIDInput = [x.rstrip() for x in file]

    if useTrueLabelsFlag:
        filenamePLT = Path(filePath,'PhaseLabelsTrue_AMI.csv')        
        phaseLabelsTrue = PIUtils.ConvertCSVtoNPY(filenamePLT)    
    
    if useNumPhasesField:
        filenameNP = Path(filePath,'NumPhases.csv')        
        numPhasesInput = PIUtils.ConvertCSVtoNPY(filenameNP)   





    ##############################################################################
    ###############################################################################
    #
    #
    #         Co-Association Matrix Ensemble Phase Identification
    #                   
    #


    # Data pre-processing steps
    # This converts the original voltage timeseries (assumed to be in volts) into per-unit representation
    vNorm = PIUtils.ConvertToPerUnit_Voltage(voltageInputCust)
    # This filters the timeseries for abnormally high or low voltage values and replaces them with NaN
    vFilt,totalFilt,filtPerCust = PIUtils.BadDataFiltering(vNorm)
    # This takes the difference between adjacent measurements, converting the timeseries into a per-unit, change in voltage timeseries
    vNDV = PIUtils.CalcDeltaVoltage(vFilt)

    # Check that all datastreams have unique IDs
    if useNumPhasesField:
        custIDUnique, numPhases = PIUtils.Ensure3PhaseCustHaveUniqueID(custIDInput,phaseLabelsErrors,numPhasesInput=numPhasesInput)
    else:
        custIDUnique, numPhases = PIUtils.Ensure3PhaseCustHaveUniqueID(custIDInput,phaseLabelsErrors)

    # kFinal is the number of final clusters produced by the algorithm.  Each 
    #   cluster will represent a phase grouping of customers.  Ideally, this value
    #   could be 3, however in practice usually a larger value is required.  Issues
    #   such as customers located on adjancent feeders present in the data, voltage
    #   regulators, or other topology issues may require tuning of this parameter.
    #   This could be done using silhouette score analysis.  7 is likely a good
    #   place to start with this parameter.
    kFinal=7

    # kVector is the number of clusters used internally by the algorithm in each 
    #   window.  
    kVector =[6,12,15,30]
    # windowSize is the number of datapoints used in each window of the ensemble
    windowSize = 384

    # This is the primary phase identification function - See documentation in CA_Ensemble_Funcs.py for details on the inputs/outputs
    finalClusterLabels,noVotesIndex,noVotesIDs,clusteredIDs,caMatrix,custWindowCounts = CAE.CAEnsemble(vNDV,kVector,kFinal,custIDUnique,windowSize,numPhases=numPhases)

    # Remove any omitted customers from the list of phase labels
    if len(noVotesIndex) != 0:
        clusteredPhaseLabels = np.delete(phaseLabelsErrors,noVotesIndex,axis=1)
        custIDFound = list(np.delete(np.array(custIDUnique),noVotesIndex))
        if useTrueLabelsFlag:
            clusteredTruePhaseLabels = np.delete(phaseLabelsTrue,noVotesIndex,axis=1)

    else:
        clusteredPhaseLabels = phaseLabelsErrors
        custIDFound = custIDUnique
        if useTrueLabelsFlag:
            clusteredTruePhaseLabels = phaseLabelsTrue


        
    # Use the phase labels to assign final phase predictions based on the majority vote in the final clusters
    # This assumes that phase labels are both available and believed to be reasonably accurate.
    # In the case where phase labels are unavailable or believed to be highly innacurate, some other method of final phase prediction must be used.
    predictedPhases = PIUtils.CalcPredictedPhaseNoLabels(finalClusterLabels, clusteredPhaseLabels,clusteredIDs)

    # This shows how many of the predicted phase labels are different from the original phase labels
    diffIndices = np.where(predictedPhases!=clusteredPhaseLabels)[1]

    print('')
    print('Spectral Clustering Ensemble Phase Identification Results')
    print('There are ' + str(diffIndices.shape[0]) + ' customers with different phase labels compared to the original phase labeling.')
    print('There are ' + str(len(noVotesIndex)) + ' customers not predicted due to missing data')
    print('')

    # If the ground-truth labels are available, this will calculate a true accuracy
    if useTrueLabelsFlag:
        accuracy, incorrectCustCount = PIUtils.CalcAccuracyPredwGroundTruth(predictedPhases, clusteredTruePhaseLabels,clusteredIDs)
        accuracy = accuracy*100

        print('The accuracy of the predicted phase is ' + str(accuracy) + '% after comparing to the ground truth phase labels')
        print('There are '+ str(incorrectCustCount) + ' incorrectly predicted customers')


    # Calculate and Plot the confidence scores - Modified Silhouette Coefficients
    allSC = PIUtils.Calculate_ModifiedSilhouetteCoefficients(caMatrix,clusteredIDs,finalClusterLabels,predictedPhases,kFinal)
    PIUtils.Plot_ModifiedSilhouetteCoefficients(allSC)

    # Create output list which includes any customers omitted from the analysis due to missing data 
    # Those customers will be at the end of the list and have a predicted phase and silhouette coefficient of -99 to indicate that they were not included in the analysis
    if useTrueLabelsFlag:
        phaseLabelsOrg_FullList, phaseLabelsPred_FullList,allFinalClusterLabels, phaseLabelsTrue_FullList,custID_FullList, allSC_FullList = PIUtils.CreateFullListCustomerResults_CAEns(clusteredPhaseLabels,phaseLabelsErrors,finalClusterLabels,clusteredIDs,custIDUnique,noVotesIDs,predictedPhases,allSC,phaseLabelsTrue=phaseLabelsTrue)
    else:
        phaseLabelsOrg_FullList, phaseLabelsPred_FullList,allFinalClusterLabels, phaseLabelsTrue_FullList,custID_FullList, allSC_FullList = PIUtils.CreateFullListCustomerResults_CAEns(clusteredPhaseLabels,phaseLabelsErrors,finalClusterLabels,clusteredIDs,custIDUnique,noVotesIDs,predictedPhases,allSC)


    # Write outputs to csv file
    df = pd.DataFrame()
    df['customer ID'] = custID_FullList
    df['Original Phase Labels (with errors)'] = phaseLabelsOrg_FullList[0,:]
    df['Predicted Phase Labels'] = phaseLabelsPred_FullList[0,:]
    if useTrueLabelsFlag:
        df['Actual Phase Labels'] = phaseLabelsTrue_FullList[0,:]
    df['Confidence Score'] = allSC_FullList
    df['Final Cluster Label'] = allFinalClusterLabels
    df.to_csv('outputs_CAEnsMethod.csv')
    print('')
    print('Predicted phase labels written to outputs_CAEnsMethod.csv')