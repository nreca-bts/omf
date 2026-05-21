# -*- coding: utf-8 -*-
"""
BSD 3-Clause License

Copyright 2021 National Technology & Engineering Solutions of Sandia, LLC (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S. Government retains certain rights in this software.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


This file contains misc helper functions for the phase identification task
"""



import sys
import numpy as np
import warnings
from copy import deepcopy
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import datetime
from scipy import stats
import pandas as pd

def _mode_value(values, **kwargs):
    mode_result = stats.mode(values, **kwargs)
    return np.asarray(mode_result.mode).reshape(-1)[0]

###############################################################################
#
# ConvertToPerUnit_Voltage
#
def ConvertToPerUnit_Voltage(timeseries):
    ''' This function takes a voltage timeseries and converts it into a per
            unit representation.  This function looks at each customer's 
            timeseries individual mean, rounds the mean of the measurements and 
            compares that to a list of known base voltages.  Voltage levels may
            need to be added to that list as more voltages levels are used.  
            This allows for the case where some customers run at 240V and some
            run at 120V in the same dataset. The function will print a warning 
            if some customers have all NaN values, but it will complete 
            successfully in that case with that customer having all NaN values
            in the per-unit timeseries as well.  Supported base voltages are
            120, 240, 7200.  

        Parameters
        ----------
            timeseries: numpy array of float (measurements,customers) - the 
                raw AMI voltage measurements

        Returns:
            voltagePU: numpy array of float (measurements,customers) -  the 
                voltage timeseries converted into per-unit representation
                
        '''
    
    voltageMismatchThresh = .8
    voltageLevels = np.array([120, 208, 277, 240, 480, 7200])
    voltagePU = np.zeros((timeseries.shape),dtype=float)
    dataLength = timeseries.shape[0]
    
    for custCtr in range(0, timeseries.shape[1]):
        currentCust = timeseries[:,custCtr]
        # Check for the case a customer only has NaN values in the timeseries
        if np.sum(np.isnan(currentCust)) == dataLength:
            print('Warning!  Customer index ' + str(custCtr) + ' only had NaN values in the timeseries. ')
            voltagePU[:,custCtr] = currentCust
            continue
        else:
            meanValue = np.round(np.nanmean(currentCust),decimals=0)
            vDiff = np.abs(voltageLevels - meanValue)
            index = np.argmin(vDiff)
            
            if index == 0:
                print('Customer index ' + str(custCtr) + ' is a 120V customer')
            # Check for the case where the correct voltage level is not listed
            if np.abs(vDiff[index]) > (voltageMismatchThresh*voltageLevels[index]):
                print('Error!  Customer# ' + str(custCtr) + 'has a mean voltage value of ' + str(meanValue) + '.  This voltage level is not supported in the function.  Please add this voltage level to the source code of the function')
                return (-1)
            voltagePU[:,custCtr] = np.divide(currentCust, voltageLevels[index])
    return voltagePU
# End of ConvertToPerUnit_Voltage


##############################################################################
#
#                           CalcDeltaVoltage
#
def CalcDeltaVoltage(voltage):
    ''' This function takes a voltage timeseries and takes the difference
        between adjacent measurements, converting each measurement into a 
        change in voltage between timesteps.

        Parameters
        ----------
            timeseries: numpy array (measurements,customers), the voltage
                measurements

        Returns:
            deltaVoltage: numpy array (measurements,customers), the voltage 
                timeseries converted into the difference representation, ie
                the change in voltage at each timestep
        '''

    deltaVoltage = np.diff(voltage, n=1, axis=0)
    return deltaVoltage
# End of CalcDelta Voltage



##############################################################################
#
# GetVoltWindow
# 
def GetVoltWindow(voltage,windowSize,windowCtr):
    """ This function takes the voltage time series and retrieves a particular
        window based on the windowCtr parameter
            
            Parameters
            ---------
                voltage: numpy array of float (measurements,customers) time 
                    series voltage measurements
                windowSize: int scalar representing the desired window size
                windowCtr: int scalar representing which window to use

                
                
            Returns
            -------
                voltBatch: numpy array of float (windowSize, customers)
                    one window of the voltage time series
            """
                    
    start = windowCtr * windowSize
    end = windowSize * (windowCtr + 1)
    voltBatch = voltage[start:end,:]
    return voltBatch
# End of GetVoltWindow



##############################################################################
#
# CleanVoltWindow
#
def CleanVoltWindow(voltWindow,currentCustIDs,currentPhaseLabels):
    """ This function takes a window of voltage time series and removes customers
        which contain missing data during that window.  This function is for 
        the phase identification task and does not include transformer labels.
        Use CleanVoltWindowTrans for the transformer pairing task
            
            Parameters
            ---------
                voltWindow: numpy array of float (measurements,customers) time 
                    series voltage measurements
                currentCustIDs: numpy array of strings (customers) with the 
                    IDs of the customers currently in use
                currentPhaseLabels: numpy array of int (1,customers) with the
                    phase labels of the current customers in use

                
                
            Returns
            -------
                voltWindow: numpy array of float (measurements, customers) the
                    same volt window with the customers which had missing data
                    during the window removed
                currentCustIDs: numpy array of strings (customers) same list
                    of customers without the 'cleaned' customers
                currentPhaseLabels: numpy array of in (1,customers) same list
                    of phase labels without the 'cleaned customers
            """
                              
    badIndices = []
    for custCtr in range(0,voltWindow.shape[1]):
        temp = voltWindow[:,custCtr]
        indices = np.where(np.isnan(temp))
        if len(indices[0]) != 0:
            badIndices.append(custCtr)
    voltWindow = np.array(voltWindow)
    voltWindow = np.delete(voltWindow,badIndices,axis=1)
    currentCustIDs = np.delete(currentCustIDs,badIndices)
    currentPhaseLabels = np.delete(currentPhaseLabels,badIndices,axis=1)
    #voltWindow = pd.DataFrame(voltWindow)
    return voltWindow,currentCustIDs,currentPhaseLabels
# End of CleanVoltWindow


##############################################################################
#
# CleanVoltWindowNoLabels
#
def CleanVoltWindowNoLabels(voltWindow,currentCustIDs):
    """ This function takes a window of voltage time series and removes customers
        which contain missing data during that window.  This function is for 
        the phase identification task and does not include transformer labels.
        Use CleanVoltWindowTrans for the transformer pairing task.  This version
        of the function does not include the utility phase labels
            
            Parameters
            ---------
                voltWindow: numpy array of float (measurements,customers) time 
                    series voltage measurements
                currentCustIDs: numpy array of strings (customers) with the 
                    IDs of the customers currently in use
            
            Returns
            -------
                voltWindow: numpy array of float (measurements, customers) the
                    same volt window with the customers which had missing data
                    during the window removed
                currentCustIDs: numpy array of strings (customers) same list
                    of customers without the customers which had missing data
                    during the window removed
            """
                              
    badIndices = []
    for custCtr in range(0,voltWindow.shape[1]):
        temp = voltWindow[:,custCtr]
        indices = np.where(np.isnan(temp))
        if len(indices[0]) != 0:
            badIndices.append(custCtr)
    voltWindow = np.array(voltWindow)
    voltWindow = np.delete(voltWindow,badIndices,axis=1)
    currentCustIDs = np.delete(currentCustIDs,badIndices)
    #voltWindow = pd.DataFrame(voltWindow)
    return voltWindow,currentCustIDs
# End of CleanVoltWindowNoLabels
                         

##############################################################################
#
#       CreateAggWeightMatrix
#
def CreateAggWeightMatrix(custID):
    """ This function takes list of customer IDs and returns an empty (all zero)
        weight matrix for the phase identification case where existing phase
        labels are not used.  
            
            Parameters
            ---------
                custID: list of string containing the IDs of each customer
                
                
            Returns
            -------
                aggWM: ndarray of float the aggregated weight matrix initialized
                    to all zeros.  This will update with weights from each window,
                    tracking paired/unpaired customer information
            """
    aggWM = np.zeros((len(custID),len(custID)),dtype=float)
    return aggWM
# End of CreateAggWeightMatrix
    

###############################################################################
#
# CalcCorrCoef
#
def CalcCorrCoef(voltageWin):
    ''' This function takes a voltage window, calculates the correlation
        coefficients, checks for failure of calculating good correlation
        coefficients (if the resulting matrix is not positive definite, the
        function returns and error), and returns the CC matrix.

        Parameters
        ----------
            voltageWin: numpy array of floats (customers, measurements), the
                window of voltage measurements

        Returns:
            corrCoef: numpy array of floats (customers, customers), the
                resulting correlation coefficient matrix, will be mirrored
                across the diagonal, with 1's on the diagonal
            failFlag: boolean - true if correlation coefficient matrix is
                not positive definite
        '''

    failFlag = 0
    voltageWin = np.array(voltageWin)
    voltageWin = voltageWin.transpose()
    warnings.simplefilter("error", RuntimeWarning)
    try:
        corrCoef = np.corrcoef(voltageWin)
    except RuntimeWarning:
        print('RuntimeWarning caught in CalCorrCoefDistances')
        failFlag = 1
        corrCoef = 0

    return corrCoef,failFlag
# End of CalcCorrCoef
                    

##############################################################################
#
#       UpdateAggWM
#
def UpdateAggWM(clusterLabels,custID,currentIDs,aggWM,windowCtr):
    """ This function takes cluster labels resulting from the spectral clustering
        of a window, the existing weight matrix and the customer ids to update
        the weights based on the current window results.  Paired customers' 
        (based on the spectral clustering labels) weights are incremented. 
            
            Parameters
            ---------
                clusterLabels: ndarray of int representing the cluster labeling
                    of each customer from the spectral clustering algorithm
                custID: list of string containing the IDs of each customer
                currentCustID: list of strings containing the IDs of each customer
                    clustered in the current window (does not include customers
                    with missing data in this window)
                aggWM: ndarray of float, shape (customers,customers) the 
                    aggregated weight matrix previously initialized
                windowCtr: ndarray of int, shape (customers,customers) list containing 
                    a count of how many windows each customer was clustered in
            Returns
            -------
                aggWM: ndarray of float the aggregated weight matrix previously
                    initialized and updated with the new informaiton from this window.
                windowCtr: ndarray of int, shape (1,customers) list containing 
                    a count of how many windows each customer was clustered in
            """
    
    allIndices = []
    for custCtr in range(0,len(currentIDs)):
        custIDStr = np.array(custID,dtype=str)
        custIndex = np.where(currentIDs[custCtr]==custIDStr)[0][0]
        allIndices.append(custIndex)
        updateIndices = np.where(clusterLabels==clusterLabels[custCtr])[0]
        updateIndicesTrue = np.in1d(custIDStr,currentIDs[updateIndices])
        updateIndicesTrue = np.where(updateIndicesTrue==True)[0]
        aggWM[custIndex,updateIndicesTrue] = aggWM[custIndex,updateIndicesTrue] + 1
    if len(custID) == len(currentIDs):
        windowCtr = windowCtr + 1
    else:
        for custCtr in range(0,len(allIndices)):
            windowCtr[allIndices[custCtr],allIndices] = windowCtr[allIndices[custCtr],allIndices] + 1
    # End of custCtr for loop
    return aggWM, windowCtr
# End of UpdateAggWM function
        
               

##############################################################################
#
#       NormalizeAggWM
#
def NormalizeAggWM(aggWM,windowCtr):
    """ This function takes the finished, aggregated weight matrix and divides
        each entry by the number of windows that customer was clustered in.  
        This removes the factor of some customers being clustered in fewer
        windows than other customers.
            
            Parameters
            ---------
                aggWM: ndarray of float, shape (customers,customers) the 
                    aggregated weight matrix previously initialized
                windowCtr: ndarray of int, shape (1,customers) list containing 
                    a count of how many windows each customer was clustered in
            Returns
            -------
                aggWM: ndarray of float the aggregated weight matrix previously
                    initialized and updated with the new informaiton from this window.
            """
    onesArray = np.ones((1,np.shape(windowCtr)[1]))
    for custCtr in range(0,aggWM.shape[0]):
        numberArray= onesArray * windowCtr[0,custCtr]
        aggWM[custCtr,:] = np.divide(aggWM[custCtr,:],numberArray)
    return aggWM
# End of NormalizeAggWM function

                    
################################################################################
#
#       CalcPredictedPhaseNoLabels
#
def CalcPredictedPhaseNoLabels(finalClusterLabels, clusteredPhaseLabelErrors,clusteredIDs):
    ''' This function takes the final cluster labels from an ensemble spectral 
        clustering run and the original utility labels and assigns a predicted
        phase to each customer based on the utility phase labels.  Note that
        the approach works well if you are reasonably confident in the original
        utility labeling, i.e. if 50% or more of the original phase labels are
        incorrect then these predicted phase will likely be innaccurate even 
        though the final cluster labels produced by the ensemble should still
        reflect the correct phase groups.
        
        Parameters
        ---------
            finalClusterLabels: ndarray, shape (customers) containing the final
                cluster labels representing the phase predictions.  But these 
                label numbers will not match the real phases
            clusteredPhaseLabelErrors: ndarray, shape (1,customers) containing 
                phase labels for the customers which were clustered.  The
                dimensions should match the length of finalClusterLabels.  This
                is the original phase labels and may contain errors in the 
                labeling
            clusteredIDs: ndarray of str, shape(customers) has the customers 
                which recieved a predicted phase

        Returns
        -------
            predictedPhases: ndarray of int, shape (1,customers) containing the 
                predicted phase labels based on the majority vote of the final
                clusters
        '''
    predictedPhases = np.zeros((1,clusteredIDs.shape[0]),dtype=int)
    # Assign a predicted (actual) phase to each cluster
    numberOfClusters = (np.unique(finalClusterLabels)).shape[0]
    uniqueClusters = np.unique(finalClusterLabels)
    for clustCtr in range(0,numberOfClusters):
        currentCluster = uniqueClusters[clustCtr]
        indices1 = np.where(finalClusterLabels==currentCluster)[0]     
        clusterPhases = clusteredPhaseLabelErrors[0,indices1]
        pPhase = _mode_value(clusterPhases)
        predictedPhases[0,indices1] = pPhase        

    return predictedPhases
# End of  CalcPredictedPhaseNoLabels
 
    

################################################################################
#
#       CalcAccuracyPredwGroundTruth
#
def CalcAccuracyPredwGroundTruth(predictedPhases, clusteredPhaseLabels,clusteredIDs):
    ''' This function takes the predicted phase labels, the ground truth labels
        and the list of clustered customers to calculate accuracy.
        
        Parameters
        ---------
            predictedPhases: ndarray of int, shape (1,customers) containing the 
                predicted phase labels based on the majority vote of the final
                clusters
            clusteredPhaseLabels: numpy array of int (1,customers) - the 
                ground truth phase labels for each customer who received a 
                predicted phase.  This dimensions of this should match 
                predictedPhases
            clusteredIDs: ndarray of str, shape(customers) has the customer IDs 
                for customers which recieved a predicted phase

        Returns
        -------
            accuracy: float, decimal accuracy 
            incorrectCustCount: int, number of customers incorrectly classified
        '''
        
    incorrectCustCount = 0
    for custCtr in range(0,len(clusteredIDs)):
        #index = np.where(clusteredIDs[custCtr]==custIDStr)[0][0]
        if predictedPhases[0,custCtr] != clusteredPhaseLabels[0,custCtr]:
            incorrectCustCount = incorrectCustCount + 1
    numNotClust = clusteredPhaseLabels.shape[1] - len(clusteredIDs)
    accuracy = (clusteredPhaseLabels.shape[1]-(incorrectCustCount+numNotClust)) / clusteredPhaseLabels.shape[1]
    return accuracy, incorrectCustCount
# End of CalcAccuracyPredwGroundTruth

              

##############################################################################
#
#       UpdateCustWindowCounts
#
def UpdateCustWindowCounts(custWindowCounts,currentIDs,custIDInput):
    """ This function updates the number of windows that each customer was 
            included in the analysis, i.e. not excluded due to missing data. 
            This function assumes that all entries in currentIDs are contained
            in the list of IDs in custIDInput and does not do error check for
            that fact.
            
            Parameters
            ---------
                custWindowCounts: numpy array of int (total number of customers)- the
                    window count for each customer
                currentIDs: list of str (current number of customers) - the list of 
                    customers IDs included in the current window to be added
                    to the custWindowCounts
                custIDInput: list of str (total number of customers) - the 
                    complete list of customer IDs. The length of this should
                    match the length/indexing of custWindowCounts
            Returns
            -------
                custWindowCounts: numpy array of int (total number of customers)
                    the window count for each customer that has been updated
                    with the new information in currentIDs
            """
    
    for custCtr in range(0,len(currentIDs)):
        index = np.where(np.array(custIDInput)==currentIDs[custCtr])[0][0]
        custWindowCounts[index] = custWindowCounts[index] + 1
    return custWindowCounts
# End of UpdateCustWindowCounts function
                    

#############################################################################
#
#                           DropCCUsingLowCCSep
#
def DropCCUsingLowCCSep(ccMatrixInput,lowCCSepThresh,sensIDInput):
    """ This function takes the correlation coefficient results from a single window, 
        assuming that the window is from a mix of customers to sensors and removes any
        CC that have a lower CC Separation Score than the specified threshold
            
            Parameters
            ---------
                ccMatrixInput: numpy array of float (customer,sensors)
                    the CC between customers and sensors for a single window
                lowCCSepThresh: float - the CC Separation threshold, any
                    CC values with CC Separation lower than this are discarded
                sensIDInput: list of str - the list of sensor IDs
                
            Returns
            -------
                ccMatrixAdjusted: numpy array of float (customers,sensors) -
                    The CC Matrix with CC values with CC Separation less than
                    the threshold discarded

            """                
        
    ccMatrixAdjusted = deepcopy(ccMatrixInput)
    sensUnique = np.unique(sensIDInput)
    for custCtr in range(0,ccMatrixAdjusted.shape[0]):
        #### Calculate the ccSeparation section
        currCC = ccMatrixAdjusted[custCtr,:]
        for sensCtr in range(0,len(sensUnique)):
            currSensor = sensUnique[sensCtr]
            indices = np.where(np.array(sensIDInput)==currSensor)[0]
            ccSet = np.sort(currCC[indices])
            ccDiff = ccSet[-1] - ccSet[-2]            
            if ccDiff < lowCCSepThresh:
                ccMatrixAdjusted[custCtr,indices] = 0
    return ccMatrixAdjusted
# End of DropCCUsingLowCCSep




##############################################################################
#
# FilterPredictedCustomersByConf
# 
def FilterPredictedCustomersByConf(custIDPredInc,custIDInput,newPhaseLabels,orgDiffPhaseLabels,winVotesConfScore=-1,
                                   ccSeparation=-1,sensVotesConfScore=-1,combConfScore=-1,winVotesThresh=-1, 
                                   ccSepThresh=-1,sensVotesThresh=-1,combConfThresh=-1):
    """ This function takes a list of customers predicted to have incorrect 
            phases and filters them by confidence scores using provided 
            thresholds.  Any provided confidence scores and threshold provided
            are used, otherwise they are ignored
            
            Parameters
            ---------
                custIDPredInc: list of str - the list of customer IDs that 
                    we are predicted to have incorrect phase labels
                custIDInput: list of str - the full list of customer IDS
                newPhaseLabels: numpy array of int (1,customers) - the 
                    predicted phase labels for the customers in custIDPredInc
                orgDiffPhaseLabels: numpy array of int (1,customers) - the 
                    original phase labels for the customers in custIDPredInc
                winVotesConfScore: list of float - the window voting confidence
                    score for each customer. 
                ccSeparation: list of float - the correlation coefficient 
                    separation for each customer
                sensVotesConfScore: list of float - the sensor agreement
                    score for each customer
                combConfScore: list of float - the combined confidence score
                    for each customer
                winVotesThresh: float - the threshold to use for the window
                    voting score
                ccSepThresh: float - the threshold to use for the CC separation
                    score
                sensVotesThresh: float - the threshold to use for the 
                    sensor agreement score
                combConfThresh: float - the threshold to use for the combined
                    confidence score
            Returns
            -------
                filteredCustIDPredInc: list of str - the custIDPredInc list
                    filtered by confidence scores.  The remaining customers
                    will have confidence scores above the specified thresholds
                filteredNewPhaseLabels: numpy array of int (1,customers) - the
                    predicted phase labels for the customers in filteredCustIDPredInc
                filteredOrgPhaseLabels: numpy array of int (1,customers) - the
                    original phase labels for the customers in filteredCustIDPredInc
                    
            """
                    
    deleteList = set({})
    for custCtr in range(0, len(custIDPredInc)):
        currIndex = custIDInput.index(custIDPredInc[custCtr])
        
        if type(winVotesThresh) != int:
            if winVotesConfScore[currIndex] < winVotesThresh:
                deleteList.add(custCtr)
        if type(ccSepThresh) != int:
            if ccSeparation[currIndex] < ccSepThresh:
                deleteList.add(custCtr)
        if type(sensVotesThresh) != int:
            if sensVotesConfScore[currIndex] < sensVotesThresh:
                deleteList.add(custCtr)
        if type(combConfThresh) != int:
            if combConfScore[currIndex] < combConfThresh:
                deleteList.add(custCtr)
    deleteList = list(deleteList)
    filteredCustIDPredInc = list(np.delete(np.array(custIDPredInc),deleteList))
    filteredNewPhaseLabels = np.delete(newPhaseLabels,deleteList)
    filteredOrgPhaseLabels = np.delete(orgDiffPhaseLabels,deleteList)
    return filteredCustIDPredInc, filteredNewPhaseLabels,filteredOrgPhaseLabels
# End of FilterPredictedCustomersByConf

#############################################################################
#
#                           CountClusterSizes
#
def CountClusterSizes(clusterLabels):
    """ This function takes the labels produced by spectral clustering (or
        other clustering algorithm) and counts the members in each cluster.  
        This is primarily to see the distribution of cluster sizes over all
        windows, particularly to see if there singleton clusters or a significant
        number of clusters with a small number of members.
            
            Parameters
            ---------
                clusterLabels: numpy array of int (clustered customers) - the cluster 
                    label of each customer
                
            Returns
            -------
                clusterCounts: numpy array of int (0,k) - the number of customers
                    in each cluster
            """                
        
    currentK = len(np.unique(clusterLabels))
    clusterCounts = np.zeros((1,currentK),dtype=int)
    for clustCtr in range(0,currentK):
        indices = np.where(clusterLabels==clustCtr)[0]
        clusterCounts[0,clustCtr] = len(indices)
    return clusterCounts
# End of CountClusterSizes


# Start of the PlotHistogramOfWinVotesConfScore function.
def PlotHistogramOfWinVotesConfScore(winVotesConfScore,savePath=-1):
    """ This function takes the list of the window votes score which is a confidence
            score based on the percentage of window votes which were the same
            for each customer, and plots a histogram.  For example, if each
            window were taken individually (not in an ensemble) and a predicted
            phase was assigned for each customer in each window, the window 
            votes confidence score for a particular customer would be the percentage
            of windows which agree on the phase.  
            
    Parameters
    ---------
        winVotesConfScore: list of float - the list containing the decimal
            confidence score defined as the mode of the phase votes over all
            windows divided by the total number of windows
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory
                
    Returns
    -------
        None
                
            """
    
    plt.figure(figsize=(12,9))
    sns.histplot(winVotesConfScore)
    plt.xlabel('Window Votes Confidence Score', fontweight = 'bold',fontsize=32)
    plt.ylabel('Count', fontweight = 'bold',fontsize=32)
    plt.yticks(fontweight='bold',fontsize=20)
    plt.xticks(fontweight='bold',fontsize=20)
    plt.title('Histogram of Window Votes Confidence Score',fontweight='bold',fontsize=12)
    plt.show()
    plt.tight_layout()    
    today = datetime.datetime.now()
    timeStr = today.strftime("%Y-%m-%d_%H-%M-%S")
    filename = 'WinVotesConfScore_HIST'
    filename = filename + timeStr + '.png'
    # Save Figure
    if type(savePath) is int:   
        plt.savefig(filename)
    else:
        plt.savefig(Path(savePath,filename))  
#End of PlotHistogramOfWinVotesConfScore



# Start of the PlotHistogramOfCombinedConfScore function.
def PlotHistogramOfCombinedConfScore(confScoreCombined,savePath=-1):
    """ This function takes the list of the score which is the combination 
            (multiplied together) of the window voting score and the 
            sensor agreement confidence socre and plots a histogram
            
    Parameters
    ---------
        confScoreCombined: list of float - the list containing combination of
            the winVotesConfScore and the sensVotesConfScore by multiplying
            them together
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory
                
    Returns
    -------
        None
                
            """
    
    plt.figure(figsize=(12,9))
    sns.histplot(confScoreCombined)
    plt.xlabel('Combined Confidence Score', fontweight = 'bold',fontsize=32)
    plt.ylabel('Count', fontweight = 'bold',fontsize=32)
    plt.yticks(fontweight='bold',fontsize=20)
    plt.xticks(fontweight='bold',fontsize=20)
    plt.title('Histogram of Combined Confidence Score',fontweight='bold',fontsize=12)
    plt.show()
    plt.tight_layout()    
    today = datetime.datetime.now()
    timeStr = today.strftime("%Y-%m-%d_%H-%M-%S")
    filename = 'CombinedConfScore_HIST'
    filename = filename + timeStr + '.png'
    # Save Figure
    if type(savePath) is int:   
        plt.savefig(filename)
    else:
        plt.savefig(Path(savePath,filename))  
#End of PlotHistogramOfCombinedConfScore
   
    

# Start of the PlotHistogramOfSensVotesConfScore function.
def PlotHistogramOfSensVotesConfScore(sensVotesConfScore,savePath=-1):
    """ This function takes the list of the scores representing the percentage
            of sensors which agreed in the phase prediction for each customer
            
    Parameters
    ---------
        sensVotesConfScore: list of float - the list containing the decimal 
            value for the percentage of sensors which agreed in the phase
            prediction for each customers.  This will be 1 if all sensors 
            agree on the prediction
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory
                
    Returns
    -------
        None
                
            """
    
    percentages = np.array(sensVotesConfScore) * 100
    plt.figure(figsize=(12,9))
    sns.histplot(percentages)
    plt.xlabel('Percentage of Sensor Agreement', fontweight = 'bold',fontsize=32)
    plt.ylabel('Count', fontweight = 'bold',fontsize=32)
    plt.yticks(fontweight='bold',fontsize=20)
    plt.xticks(fontweight='bold',fontsize=20)
    plt.title('Histogram of Sensor Agreement',fontweight='bold',fontsize=12)
    plt.show()
    plt.tight_layout()    
    today = datetime.datetime.now()
    timeStr = today.strftime("%Y-%m-%d_%H-%M-%S")
    filename = 'SensorAgreementConfScore_HIST'
    filename = filename + timeStr + '.png'
    # Save Figure
    if type(savePath) is int:   
        plt.savefig(filename)
    else:
        plt.savefig(Path(savePath,filename))  
#End of PlotHistogramOfSensVotesConfScore
    





# Start of the PlotHistogramOfCCSeparation function.
def PlotHistogramOfCCSeparation(ccSeparation,xLim=0.2,savePath=-1):
    """ This function takes the list of the correlation coefficient separation
            confidence scores and plots a histogram.  
            
    Parameters
    ---------
        ccSeparation: list of float - the list containing the separation 
            between the labeled phase CC and the next highest CC for each 
            customer.  This is used as a type of confidence score
        xLim: float - the value for the x-axis limit for the figure.  0.2 is
            the default because that works well with the our utility data. If -1 is 
            used, the function will not specify an x-axis limit.
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory
                
    Returns
    -------
        None
                
            """
            
    plt.figure(figsize=(12,9))
    sns.histplot(ccSeparation)
    plt.xlabel('Correlation Coefficient Separation', fontweight = 'bold',fontsize=32)
    plt.ylabel('Count', fontweight = 'bold',fontsize=32)
    plt.yticks(fontweight='bold',fontsize=20)
    plt.xticks(fontweight='bold',fontsize=20)
    if xLim != -1:
        plt.xlim(0,xlim=xLim)
    plt.title('Histogram of Correlation Coefficient Separation',fontweight='bold',fontsize=12)
    plt.show()
    plt.tight_layout()    
    today = datetime.datetime.now()
    timeStr = today.strftime("%Y-%m-%d_%H-%M-%S")
    filename = 'CCSeparation_HIST'
    filename = filename + timeStr + '.png'
    # Save Figure
    if type(savePath) is int:   
        plt.savefig(filename)
    else:
        plt.savefig(Path(savePath,filename))
    plt.close()
#End of PlotHistogramOfCCSeparation
    



def Calculate_ModifiedSilhouetteCoefficients(caMatrix,clusteredIDs,finalClusterLabels,predictedPhases,kFinal):
    """ This function takes the results from running the Ensemble Spectral Cluster
        Phase Identification algorithm, calculates a modified version of the
        Silhouette Score for each customer.
        
        The Silhouette Coefficient/Score is well-established and further details
        can be found in P.J. Rousseeuw, "Silhouettes: a graphical aid to the 
        interpretation and validation of cluster analysis".  Journal of Computational
        and Applied Mathematics, Jun 1986. 
        General definition of the Silhouette Coefficient:
            s = (b-a) / max(a,b)
            a: The mean distance between a sample and all other points in the same cluster
            b:The mean distance between a sample and all other points in the next nearest cluster
        
        This function implements a phase-aware version of the silhouette 
        coefficient, where the next nearest cluster for b is required to be a cluster
        predicted to be a different phase from the cluster of the current sample.  
        This provides a more informative coefficient for this use case.  
            

    Parameters
    ---------
        caMatrix: ndarray of float (customers,customers) - the co-association
            matrix produced by the spectral clustering ensemble.  This is an
            affinity matrix.  Note that the indexing of all variables must
            match in customer order.
        clusteredIDs: list of str - the list of customer ids for which a predicted
            phase was produced
        finalClusterLabels: list of int - the integer cluster label for each 
            customer
        predictedPhases: ndarray of int (1,customers) - the integer predicted
            phase label for each customer
        kFinal: int - the number of final clusters
                
    Returns
    -------
        allSC: list of float - the silhouette coefficients for each customer
                
            """
        
    aggWMDist = 1 - caMatrix   
    allSC = []
    # Loop through each customer to calculate individual silhouette coefficients
    for custCtr in range(0,len(clusteredIDs)):
        currCluster = finalClusterLabels[custCtr]
        clusterPhase = predictedPhases[0,custCtr]
        # Find all customers in the same cluster as current customer and calculate the value for a
        currInClustIndices = np.where(finalClusterLabels==currCluster)[0]
        a = np.mean(aggWMDist[custCtr,currInClustIndices])
        allBs = []
        allBsAff = []
        allClusterPhases = []
        # Loop through the other clusters and calculate the value for b for each cluster, relative to the current customer
        for clustCtr in range(0,kFinal):
            if clustCtr == currCluster:
                allBs.append(1)
                allBsAff.append(0)
                allClusterPhases.append(clusterPhase)
            else:
                indices = np.where(finalClusterLabels == clustCtr)[0]
                if len(indices) == 0:
                    continue
                currB = np.mean(aggWMDist[custCtr,indices])
                currBAff = np.mean(caMatrix[custCtr,indices])
                allBs.append(currB)
                allBsAff.append(currBAff)
                currPhase = predictedPhases[0,indices[0]]
                allClusterPhases.append(currPhase)
        # Find the next closest cluster predicted to be a different phase from the current customers cluster
        sortedBs = np.sort(np.array(allBs))
        argsortedBs = np.argsort(np.array(allBs))
        argsortedPhases = np.array(allClusterPhases)[argsortedBs]
        minCtr = 0
        while (argsortedPhases[minCtr] == clusterPhase) and (sortedBs[minCtr] != 1):
            minCtr = minCtr + 1
        nextClosestDiffPhase = argsortedPhases[minCtr]
        nextClosestDiffB = sortedBs[minCtr]
        b = sortedBs[minCtr]
        # Calculate Silhouette Coefficient
        s = (b-a) / max(a,b)
        allSC.append(s)

    return allSC
# End of Calculate_ModifiedSilhouetteCoefficients Function   



def Plot_ModifiedSilhouetteCoefficients(allSC,savePath=-1):
    """ This function takes the results from the 
        Calculate_ModifiedSilhouetteCoefficients function to plot and save
        a histogram of the Modified Silhouette Coefficients which act as a 
        confidence score.

    Parameters
    ---------
        allSC: list of float - the silhouette coefficients for each customer
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory        
                
    Returns
    -------
        None
            """
        
    # Plot and save histogram
    plt.figure(figsize=(12,9))
    sns.histplot(allSC)
    plt.xlabel('Modified Silhouette Score (values < 0.2 should be considered low confidence)', fontweight = 'bold',fontsize=15)
    plt.ylabel('Number of Customers', fontweight = 'bold',fontsize=20)
    plt.title('Histogram of Silhouette Coefficients (Larger values indicate higher confidence in phase predictions)',fontweight='bold',fontsize=12)
    plt.tight_layout()
    #plt.show()
    figName =  'ModifiedSC_HIST.png' 
    
    if type(savePath) != int:
        plt.savefig(Path(savePath,figName))
    else:
        plt.savefig(figName)
# End of Plot_ModifiedSilhouetteCoefficients Function   





def CreateFullListCustomerResults_CAEns(clusteredPhaseLabels,phaseLabelsOriginal,finalClusterLabels,clusteredIDs,custID,noVotesIDs,predictedPhases,allSC,phaseLabelsTrue=-1):
    """ This function takes the results from the co-association matrix ensemble
            and adds back the customers which were omitted due to missing data.
            Those customers are given a predictedPhase and silhouette coefficient
            of -99 to indicate that they were not processed.  If noVotesID
            is empty (i.e. no customers were omitted) then the function simply 
            returns the fields as-is.
            

    Parameters
    ---------
        clusteredPhaseLabels: ndarray of int (1,clustered customers) - the 
            original phase labels for the customers processed by the phase
            identification algorithm.  These phase labels may contain errors. 
        phaseLabelsOriginal: ndarray of int (1,customers) - the full list of
            original phase labels.  These phase labels may contain errors.
        finalClusterLabels: ndarray of int (customers) - the integer label for
            which final cluster a customer was placed in.  These clusters will
            represent phase groupings without necessarily knowing which phase
            these customers are
        clusteredIDs: list of str - the list of customer ids for which a predicted
            phase was produced
        custID: list of str - the complete list of customer ids
        noVotesIDs: list of str - the list of customers ids which were omitted
            due to missing data
        predictedPhases: ndarray of int (1,clustered customers) - the integer predicted
            phase label for each customer
        allSC: list of float - the modified silhouette coefficients for each 
            customers included in the results
        phaseLabelsTrue: ndarray of int (1,customers) - the full list of the
            true phase labels for each customer.  This parameter is optional
            if this is not available for your dataset.

    Returns
    -------
        phaseLabelsOrg_FullList: ndarray of int (1,customers) - the complete
            list of the original phase labels.  Customers which were omitted
            due to missing data are moved to the end of the list
        phaseLabelsPred_FullList: ndarray of int (1,customers) - the complete
            list of predicted phase labels.  Customers which were omitted 
            due to missing data are moved to the end of the list and given
            a predicted label of -99 to indicate they were not included
        allFinalClusterLabels: list of int - the list of final cluster labels
            for each customer.  Omitted customers will have a placeholder of
            -99 to indicate they were not included in the results
        phaseLabelsTrue_FullList: ndarray of int - the full list of true
            phase labels for each customer.  The customers omitted from the
            results are moved to the end of the array.  If phaseLabelsTrue was
            not passed as a parameter, this returns -1
        custID_FullList: list of str - the list of customer ids with customers
            omitted due to missing data moved to the end of the list
        allSC_FullList: list of float - the list of silhouette coefficients.
            Customers omitted due to missing data are added to the end and given
            a value of -99 to indicate they were not included in the results
                
            """
            
    if len(noVotesIDs) != 0: # Check if any customers were omitted
        numCust = phaseLabelsOriginal.shape[1]
        numClusteredCust = len(clusteredIDs)
        
        phaseLabelsOrg_FullList = np.zeros((1,numCust),dtype=int)
        phaseLabelsPred_FullList = np.zeros((1,numCust),dtype=int)
        custID_FullList = list(deepcopy(clusteredIDs))
        allSC_FullList = deepcopy(allSC)
        allFinalClusterLabels = list(deepcopy(finalClusterLabels))
        if type(phaseLabelsTrue) != int:
            phaseLabelsTrue_FullList = np.zeros((1,numCust),dtype=int)
        else:
            phaseLabelsTrue_FullList = -1
    
    
        phaseLabelsPred_FullList[0,0:numClusteredCust] = predictedPhases
        
        # Reshape customers included in the results
        for custCtr in range(0,numClusteredCust):
            currID = clusteredIDs[custCtr]
            index = custID.index(currID)
            phaseLabelsOrg_FullList[0,custCtr] = phaseLabelsOriginal[0,index]
            if type(phaseLabelsTrue) != int:
                phaseLabelsTrue_FullList[0,custCtr] = phaseLabelsTrue[0,index]
            
        # Add the omitted customers
        for custCtr in range(0,len(noVotesIDs)):
            currID = noVotesIDs[custCtr]
            index = custID.index(currID)
            phaseLabelsOrg_FullList[0,(custCtr+numClusteredCust)] = phaseLabelsOriginal[0,index]
            if type(phaseLabelsTrue) != int:
                phaseLabelsTrue_FullList[0,(custCtr+numClusteredCust)] = phaseLabelsTrue[0,index]
            
            phaseLabelsPred_FullList[0,(custCtr+numClusteredCust)] = -99
            custID_FullList.append(currID)
            allSC_FullList.append(-99)
            allFinalClusterLabels.append(-99)
            
    else: # Copy the original fields and return them as-is
        phaseLabelsOrg_FullList = deepcopy(phaseLabelsOriginal)
        phaseLabelsPred_FullList = deepcopy(predictedPhases)
        custID_FullList = deepcopy(clusteredIDs)
        allSC_FullList = deepcopy(allSC)
        allFinalClusterLabels = list(deepcopy(finalClusterLabels))
        if type(phaseLabelsTrue) != int:
            phaseLabelsTrue_FullList = deepcopy(phaseLabelsTrue)
        else:
            phaseLabelsTrue_FullList = -1
        

    return phaseLabelsOrg_FullList, phaseLabelsPred_FullList,allFinalClusterLabels, phaseLabelsTrue_FullList,custID_FullList, allSC_FullList
# End of CreateFullListCustomerResults_CAEns



def CreateFullListCustomerResults_SensMeth(clusteredPhaseLabels,phaseLabelsOriginal, 
                                           phaseLabelsTrue,clusteredIDs,custID,noVotesIDs,  
                                           predictedPhases,ccSeparation, winVotesConf, 
                                           sensVotesConf,confScoreCombined):
    """ This function takes the results from the co-association matrix ensemble
            and adds back the customers which were omitted due to missing data.
            Those customers are given a predictedPhase and silhouette coefficient
            of -99 to indicate that they were not processed.  
            

    Parameters
    ---------
        clusteredPhaseLabels: ndarray of int (1,clustered customers) - the 
            original phase labels for the customers processed by the phase
            identification algorithm.  These phase labels may contain errors. 
        phaseLabelsOriginal: ndarray of int (1,customers) - the full list of
            original phase labels.  These phase labels may contain errors.
        phaseLabelsTrue: ndarray of int (1,customers) - the full list of the
            true phase labels for each customer
        clusteredIDs: list of str - the list of customer ids for which a predicted
            phase was produced
        custID: list of str - the complete list of customer ids
        noVotesIDs: list of str - the list of customers ids which were omitted
            due to missing data
        predictedPhases: ndarray of int (1,clustered customers) - the integer predicted
            phase label for each customer
        ccSeparation: list of float - the Correlation Coefficient Separation 
            score for each customer
        winVotesConf: list of float - the Window Voting Confidence Score for 
            each customer
        sensVotesConf: list of float - the Sensor Voting Confidence Score for
            each customer
        confScoreCombined: list of float - the Combined Confidence Score for
            each customer

    Returns
    -------
        phaseLabelsOrg_FullList: ndarray of int (1,customers) - the complete
            list of the original phase labels.  Customers which were omitted
            due to missing data are moved to the end of the list
        phaseLabelsPred_FullList: ndarray of int (1,customers) - the complete
            list of predicted phase labels.  Customers which were omitted 
            due to missing data are moved to the end of the list and given
            a predicted label of -99 to indicate they were not included
        phaseLabelsTrue_FullList: ndarray of int - the full list of true
            phase labels for each customer.  The customers omitted from the
            results are moved to the end of the array
        custID_FullList: list of str - the list of customer ids with customers
            omitted due to missing data moved to the end of the list
        ccSep_FullList: list of float - the list of customer CC Separation
            Score with customers omitted due to missing data moved to the end 
            of the list and given a value of -99
        winVotes_FullList: list of float - the list of customer Window Voting
            Scores with customers omitted due to missing data moved to the end
            of the list and given a value of -99
        sensVotes_FullList: list of float - the list of Sensor Voting Scores
            with customers omitted due to missing data moved to the end of the
            list and given a value of -99
        combConf_FullList: list of float - the list of Combined Confidence
            Scores for each custome with customers omitted due to missing dat
            moved to the end of the list and given a value of -99.
                
            """
        
    numCust = phaseLabelsTrue.shape[1]
    numClusteredCust = len(clusteredIDs)
    
    phaseLabelsOrg_FullList = np.zeros((1,numCust),dtype=int)
    phaseLabelsPred_FullList = np.zeros((1,numCust),dtype=int)
    phaseLabelsTrue_FullList = np.zeros((1,numCust),dtype=int)
    custID_FullList = list(deepcopy(clusteredIDs))
    ccSep_FullList = deepcopy(ccSeparation)
    winVotes_FullList = deepcopy(winVotesConf)
    sensVotes_FullList = deepcopy(sensVotesConf)
    combConf_FullList = deepcopy(confScoreCombined)

    phaseLabelsPred_FullList[0,0:numClusteredCust] = predictedPhases
    
    # Reshape customers included in the results
    for custCtr in range(0,numClusteredCust):
        currID = clusteredIDs[custCtr]
        index = custID.index(currID)
        phaseLabelsOrg_FullList[0,custCtr] = phaseLabelsOriginal[0,index]
        phaseLabelsTrue_FullList[0,custCtr] = phaseLabelsTrue[0,index]
        
    # Add the omitted customers
    for custCtr in range(0,len(noVotesIDs)):
        currID = noVotesIDs[custCtr]
        index = custID.index(currID)
        phaseLabelsOrg_FullList[0,(custCtr+numClusteredCust)] = phaseLabelsOriginal[0,index]
        phaseLabelsTrue_FullList[0,(custCtr+numClusteredCust)] = phaseLabelsTrue[0,index]
        
        phaseLabelsPred_FullList[0,(custCtr+numClusteredCust)] = -99
        custID_FullList.append(currID)
        ccSep_FullList.append(-99)
        winVotes_FullList.append(-99)
        sensVotes_FullList.append(-99)
        combConf_FullList.append(-99)

    return phaseLabelsOrg_FullList, phaseLabelsPred_FullList, phaseLabelsTrue_FullList,custID_FullList, ccSep_FullList, winVotes_FullList,sensVotes_FullList,combConf_FullList







def Ensure3PhaseCustHaveUniqueID(custIDOriginal,phaseLabelsInput,numPhasesInput = -1,savePath=-1):
    """ This function takes as input the original list of customer IDs.  This
            list may contain repeated entries for 2-phase or 3-phase customers.
            Meaning, that there is one entry per datastream and a 3-phase 
            may have three datastreams.  The phase identification algorithm
            requires a unique ID for each datastream.  This will append a 
            1,2,3 based on the customer phase label to those customers.
            Customer IDs with multiple datastreams and different original phase
            labels are considered to be 2-phase or 3-phase customers and will
            not be allowed to cluster together. 
            Alternatively, customer IDs with multiple datastreams with matching
            phase labels will be assigned unique IDs but will still be allowed
            to cluster together.  These are considered to be the case where
            one premise has multiple meters (for example a house and a barn).
            
            Note!  2-phase and 3-phase datastreams must be adjacent to each 
            other!  Meaning for a three phase customer the three datastreams
            must be contiguous in index, i.e. indices 2,3,4
            
            This function will also print the customers which have been assigned
            new IDs and save a csv with the alterations.

    Parameters
    ---------
        custIDOriginal: list of str - the list of original customer IDs
        phaseLabelsInput: ndarray of float (1,customers) - the original phase
            labels for each customer
        numPhasesInput: ndarray of int (1,customers)  - the number of phases 
            for each customer.  The indexing should match custIDOriginal.
            1 - single-phase,2 - 2-phase, 3 - 3-phase.  This parameter is 
            optional; if it is not specified the numPhases field will be 
            estimated based on the original phase labels
            
        savePath: str or pathlib object - the path to save the histogram 
            figure.  If none is specified the figure is saved in the current
            directory                   
    Returns
    -------
        custIDUnique: list of str - the list of updated customer IDs such that
            there are no repeated IDs
        numPhasesNew: ndarray of int (1,customers) - 1,2,3 for if each 
            datastream/customer is 1,2,or 3-phase customer
            
            """
    
    print('Check if all datastreams have a unique ID')
    
    
    uniqueList = np.unique(custIDOriginal)
    # If there are no duplicates and numPhases is not supplied, then no action 
    #    is necessary and all customers are treated as single-phase
    if (len(uniqueList) == len(custIDOriginal)) and (type(numPhasesInput) == int):
        print('No duplicate customer IDs found')
        numPhasesNew = np.ones((1,len(custIDOriginal)),dtype=int)
        return custIDOriginal, numPhasesNew
    # If there are no duplicates and numPhases IS supplied, then no action is required
    elif (len(uniqueList) == len(custIDOriginal)) and (type(numPhasesInput) != int):
        print('No duplicate customer IDs found')
        numPhasesNew = numPhasesInput
        return custIDOriginal, numPhasesNew
    
    else:
                
        custIDUnique = []
        changedIndices = []
        numPhasesNew = np.zeros((1,len(custIDOriginal)),dtype=int)
        appendCtr = 0 # This is used to ensure that labels will definitely be unique
        
        # Loop through each original ID
        for custCtr in range(0,len(custIDOriginal)):
            currCust = custIDOriginal[custCtr]  
            indices = np.where(np.array(custIDOriginal)==currCust)[0]
            # Standard case, single phase, already has a unique id
            if len(indices) == 1:  
                numPhasesNew[0,custCtr] = 1
                custIDUnique.append(currCust)
            elif len(indices) == 2: 
                # Only change the name if numPhases was supplied by the user
                if type(numPhasesInput) != int:
                    newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr]) + '_' + str(appendCtr)
                    appendCtr = appendCtr + 1
                    custIDUnique.append(newStr)
                    changedIndices.append(custCtr)                    
                # Otherwise create/estimate numPhases from the original phase labels
                else:
                    # This is the barn case -> two meters, same premise, probably the same phase
                    if phaseLabelsInput[0,indices[0]] == phaseLabelsInput[0,indices[1]]:
                        numPhasesNew[0,custCtr] = 1
                        newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr]) + '_' + str(appendCtr)
                        appendCtr = appendCtr + 1
                        custIDUnique.append(newStr)
                        changedIndices.append(custCtr)
                    # This is the 2-phase case -> one meter, two datastreams, probably different phases
                    else:
                        numPhasesNew[0,custCtr] = 2
                        newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr])
                        custIDUnique.append(newStr)
                        changedIndices.append(custCtr)
            elif len(indices) == 3:
                # Only change the name if numPhases was supplied by the user
                if type(numPhasesInput) != int:                
                    newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr]) + '_' + str(appendCtr)
                    appendCtr = appendCtr + 1
                    custIDUnique.append(newStr)
                    changedIndices.append(custCtr)
                
                # Otherwise create/estimate numPhases from the original phase labels                
                else:  
                    # Allow for a possible barn case, although this seems less likely
                    if phaseLabelsInput[0,indices[0]] == phaseLabelsInput[0,indices[1]] == phaseLabelsInput[0,indices[2]]:
                        numPhasesNew[0,custCtr] = 1
                        newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr]) + '_' + str(appendCtr)
                        appendCtr = appendCtr + 1
                        custIDUnique.append(newStr)
                        changedIndices.append(custCtr)
                    # Three-phase case
                    else:
                        numPhasesNew[0,custCtr] = 3
                        newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr])
                        custIDUnique.append(newStr)
                        changedIndices.append(custCtr)                
            else: # This would be an odd situation.  In this case, just assign a unique id and leave it alone
                if type(numPhasesInput) != int:    
                    numPhasesNew[0,custCtr] = 1
                newStr = currCust + '_' + str(phaseLabelsInput[0,custCtr]) + '_' + str(appendCtr)
                appendCtr = appendCtr + 1
                custIDUnique.append(newStr)
                changedIndices.append(custCtr)
        # End of custCtr for loop
    # End of else statement

    # If numPhases was supplied by the user, this function will just return that as numPhasesNew
    if type(numPhasesInput) != int:
        numPhasesNew = numPhasesInput
        
    indices1 = len(np.where(numPhasesInput[0,:] == 1)[0])
    indices2 = len(np.where(numPhasesInput[0,:] == 2)[0])
    indices3 = len(np.where(numPhasesInput[0,:] == 3)[0])
    
    twoMod = np.mod(indices2,2)
    threeMod = np.mod(indices3,3)
    if (twoMod != 0) or (threeMod != 0):
        print('Error!  The number of datastreams provided does not match the number of phases specified in the numPhases field.  You must fix this before proceeding.  See the pdf documentation for more details.')
        sys.exit()

    # Print changed customers
    if len(changedIndices) > 0:
        print('#########')
        print('')
        print(str(len(changedIndices)) + ' customer IDs were changed to give them unique IDs')
        if type(numPhasesInput) == int:
            print('Repeated customer IDs with differing original phase labels are considered to be 2-phase or 3-phase customers, and those datastreams will not be allowed to cluster together in the phase identification algorithm.  Repeated customer IDs with multiple datastreams with matching original phase labels are considered to be single-phase, possibly multiple meters at a single premise.')
            print('Please review the following printout of altered customer IDs or the saved csv file to ensure that this is the desired behavior for your customers.')
            print('Further details are available in the pdf documentation file included in the repository')
        else:
            print('Repeated IDs were altered to be unique, but numPhases was supplied by the user')
        print('')
        for changeCtr in range(0,len(changedIndices)):
            print('Original ID:  ' + str(custIDOriginal[changedIndices[changeCtr]]))
            print('Unique ID:  ' + str(custIDUnique[changedIndices[changeCtr]]))
            print('Original Phase:  ' + str(phaseLabelsInput[0,changedIndices[changeCtr]]))
            print('Number of Phases Label:  ' + str(numPhasesNew[0,changedIndices[changeCtr]]))
            print('')                                             

        # pretty print changed customer IDs
        changedIDs = []
        newIDs = []
        changedPhases = []
        changedNumPhases = []
        for changeCtr in range(0,len(changedIndices)):
            changedIDs.append(custIDOriginal[changedIndices[changeCtr]])
            newIDs.append(custIDUnique[changedIndices[changeCtr]])
            changedPhases.append(phaseLabelsInput[0,changedIndices[changeCtr]])
            changedNumPhases.append(numPhasesNew[0,changedIndices[changeCtr]])
    
        # Save changed customers to csv file
        df = pd.DataFrame()
        df['Original Customer ID'] = changedIDs
        df['Unique Customer ID'] = newIDs
        df['Original Phase Label'] = changedPhases
        df['Given Number of Phases'] = changedNumPhases
        if type(savePath) == int:
            df.to_csv('ChangedCustomerIDs.csv')
        else:df.to_csv(Path(savePath,'ChangedCustomerIDs.csv'))
        print('Customers given new, unique IDs written to ChangedCustomerIDs.csv')
        print('')
        print('#########')
    return custIDUnique, numPhasesNew    
# End of Ensure3PhaseCustHaveUniqueID Function   

##############################################################################
#
#       ConvertCSVtoNPY
#

def ConvertCSVtoNPY( csv_file ):
    dataSet = pd.read_csv( csv_file, header=None )
    return np.array( pd.DataFrame(dataSet).values )

# End ConvertCSVtoNPY function      




##############################################################################
#
#       BadDataFiltering
#    
def BadDataFiltering(timeseries,highValue=1.1,lowValue=0.8):
    ''' This function takes a array of timeseries with high and low thresholds
        and any values outside of those thresholds become NaN.  The timeseries
        values MUST be in per-unit if you use the default thresholds.
        
        Parameters
        ---------
            timeseries: ndarray of float (measurements,customers) - the 
                timeseries to filter
            highValue: float - the upper threshold.  The default is 1.1, 
                which gives a 10% variation off of the norm.  This default 
                works well for being conservative on throwing out values 
                 for voltage because within 5% is acceptable per standards, so
                 this is double the acceptable range
            lowValue: float - the lower threshold.  The default is 0.8, 
                         
        Returns
        -------
            filteredTimeseries: ndarray of float (measurements,customers) 
                the filtered timeseries.  Any values outside of the thresholds
                replaced with NaN
            nanCount: int - the total number of values filtered
            nanCountPerCust: list of int - the number of values filtered per
                customer
        '''
        
    filteredTimeseries = deepcopy(timeseries)
    nanCount = 0
    nanCountPerCust = []
    for custCtr in range(0,timeseries.shape[1]):
        currCol = filteredTimeseries[:,custCtr]
        indices = np.where(currCol>=highValue)[0]
        indices2 = np.where(currCol<=lowValue)[0]
        allIndices = np.concatenate((indices,indices2))
        nans = len(allIndices)
        currCol[allIndices] = np.nan
        filteredTimeseries[:,custCtr] = currCol
        nanCount = nanCount + nans
        nanCountPerCust.append(nans)
        
    return filteredTimeseries, nanCount, nanCountPerCust
# End of BadDataFiltering
    









