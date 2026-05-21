# -*- coding: utf-8 -*-
"""
Implement Sandia sensor-based AMI meter phase-assignment and confidence-score routines.

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



This file has functions related to pairing customers with substation data or  sensor
data.

Function List:     - AssignPhasesUsingSensors     - CCSensVoting     -
CalcConfidenceScores4Sensors     - AssignPhasesUsingSubstation

Publications Associated with this work:     L. Blakely, M. J. Reno, B. Jones, and A.
Furlani Bastos, “Leveraging Additional Sensors for Phase Identification in Systems with
Voltage Regulators,” presented at the Power and Energy Conference at Illinois (PECI),
Apr. 2021.


"""

# Import Python Libraries
import numpy as np
from copy import deepcopy
from scipy import stats


# Import custom libraries
if __package__ in [None, '']:
    import PhaseIdent_Utils as PIUtils
else:
    from . import PhaseIdent_Utils as PIUtils


###############################################################################
#
#                       CCSensVoting
#
def AssignPhasesUsingSensors(voltageCust,voltageSens,custIDInput, sensIDInput, 
                             phaseLabelsSens,windowSize,numVotes=5,
                             dropLowCCSepFlag=False,ccSepThresh=-1,
                             minWindowThreshold=7):
    """ This function takes customer voltage timeseries and voltage timeseries
        from other sensors and assigns a phase label to the customer based on 
        votes from the highest correlated sensors.  For more details, see
        the paper listed above.
            
            Parameters
            ---------
                voltageCust:  numpy array of float (measurements,customers) 
                    AMI voltage timeseries for each customer.  Each column
                    corresponds to a single customers timeseries.  This data
                    should be in per-unit, difference (delta) representation. 
                    That preprocessing is a critical step.
                voltageSens:  numpy array of float (measurements,sensors*phases*datastreams) 
                    voltage timeseries for the sensor datastream.  Each column
                    corresponds to a sensor datastream timeseries.  This data
                    should be in per-unit, difference (delta) representation.
                    The measurements dimension should match in length and 
                    measurement interval with voltageCust
                custIDInput: list of str - the list of customer IDs.  The 
                    length and indexing should match with the customer dimension
                    (axis 1) of voltageCust
                sensIDInput: list of str - the list of sensor IDs.  Each sensor will
                    likely have measurements for all three phases, so this list
                    will have repeating groups in that case.  The length and
                    indexing should match axis 1 of voltageSens
                phaseLabelsSens: numpy array of int (1,sensors*3) - the phase 
                    labels for each sensor.  This assumes that each sensor will 
                    have measurements for all three phases.
                windowSize: int - the number of samples to use in each window
                numVotes: int - the number of sensor to use in making the
                    phase prediction for each customer.  The default for this
                    parameter is 5.  Make sure this number is less than or 
                    equal to the total number of sensors available.  
                dropLowCCSepFlag: boolean - If true this flag calls the 
                    function to drop CC values where the CC Separation is below the
                    ccSepThresh value.  The default value is False, mean all
                    CC values are considered.
                ccSepThresh: float - if dropLowCCSepFlag is set to True, then
                    this parameter must also be passed.  CC values in each 
                    window, where the CC Separation is below this value are dropped.
                minWindowThreshold: int - the minimum number of windows that 
                    must be available for each customer.  If a customer has 
                    fewer windows then they are omitted from the analysis.  
            Returns
            -------
                newPhaseLabels: numpy array of int (1,customers) - the 
                    predicted phase labels for each customer
                ccMatrix: numpy array of float (customers,customers) - the final,
                    median, correlation coefficients for all customers over
                    all windows
                custIDFound: list of str - the customer IDs for customers
                    which were predicted, i.e. not eliminated due to missing
                    data.  This list will match the dimensions of all other
                    outputs of this function
                noVotesIndex: list of int - the indices of customers who were
                    removed from all windows
                noVotesIDs: list of str - the customer IDs of customers who 
                    were removed from all windows
                omittedCust: dict - two keys minWindows and missDataOrFiltered
                    minWindows is a list of customer IDs which were omitted 
                    from the analysis because they did not meet the minimum 
                    number of windows, and missDataOrFiltered is a list of 
                    customer IDs which were omitted due, either to missing data
                    or being filtered due to the CC Separation filter
                sensVotesConfScore: list of float - each entry is the percentage of sensors 
                    which agree on the phase prediction for that customer
                winVotesConfScore: list of float - each entry is the percentage of windows 
                    which have the same phase vote for each customer.  This is 
                    calculated by considering the phase of the sensor datastream with 
                    the highest CC in each window as a vote
                ccSeparation: list of float - each entry is the difference between the 
                    highest CC and the next highest CC, considering the mean CC across
                    windows.
                confScoreCombined: list of float - the combination of the sensVotes and
                    the ccSeparation.  Obtained by multiplying those scores together    
                custWindowCounts: numpy array of int (customers) - the count,
                    for each customer, of the number of windows that were
                    included in the analysis, i.e. the number of windows that 
                    were not excluded due to missing data.  This count is 
                    significantly affected by the value chosen for the 
                    windowSize parameter
            """    
        
    if numVotes > len(sensIDInput)/3:
        print('Error!  You have specified more votes than there are sensors in the system.  There are ' + str(int(len(sensIDInput) / 3)) + ' sensors in the system')
        return -1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1
    
    ensTotal = int(np.floor(voltageCust.shape[0] / windowSize))
    ccMatrixAll = np.zeros((voltageCust.shape[1],voltageSens.shape[1],ensTotal),dtype=float)
    ccMatrix = np.zeros((voltageCust.shape[1],voltageSens.shape[1]),dtype=float)
    newPhaseLabels = np.zeros((1,voltageCust.shape[1]),dtype=int)
    pairedSensIDs = []
    noVotesIndex = []
    noVotesIDs = []
    numSensProfiles = voltageSens.shape[1]
    numCust = len(custIDInput)
    custWindowCounts = np.zeros((len(custIDInput)),dtype=int)
    allWindowVotes = np.zeros((len(custIDInput),ensTotal),dtype=int)
    allWindowVotes[:] = -999
    allSensVotes = []
    omittedCust = {}
    omittedCust['minWindows'] = []
    omittedCust['missDataOrFiltered'] = []
    omittedCust['sensVoteCriteria'] = []
    
    # Calculate all correlation coefficients for all windows
    for ensCtr in range(0,ensTotal):
        #Customer Voltage - Select the next time series window and remove customers with missing data in that window
        vWindow = PIUtils.GetVoltWindow(voltageCust,windowSize,ensCtr)
        vWindow,currentIDs = PIUtils.CleanVoltWindowNoLabels(deepcopy(vWindow), deepcopy(custIDInput))
        custWindowCounts = PIUtils.UpdateCustWindowCounts(custWindowCounts,currentIDs,custIDInput)
        # Check if any customer has all zeros
        allZerosCustFlag = False
        for ctr in range(0,len(currentIDs)):
            currV = np.array(vWindow)[:,ctr]
            indices = np.where(currV==0)[0]
            if len(indices) == windowSize:
                allZerosCustFlag = True
        
        # Sensor Voltage - Select the next time series window and remove customers with missing data in that window
        sensWindow = PIUtils.GetVoltWindow(voltageSens,windowSize,ensCtr)
        # Check if any sensor datastream contains all zeros
        sensSums = np.sum(sensWindow,axis=0)
        sensSumFlags = np.where(sensSums==0)[0]
        nanCount = np.sum(np.isnan(sensWindow))
        if nanCount > 0:
            print('The sensor data had ' + str(nanCount) + ' NaN values in this window (window: ' + str(ensCtr) + ').  This implementation skipped this window altogether.  I am assuming that the sensor data comes from SCADA and will have few missing values.')
            continue
        elif len(sensSumFlags) != 0:
            print('The sensor data had at least one datastream where the delta voltage was all zeros for this window  This implementation skips this window because the correlation coefficient calculation fails in this case.')
            continue
        elif allZerosCustFlag:
            print('The customer data had at least one customer where the delta voltage was all zeros for this window.  This implementation skips this window because the correlation coefficient calculation fails in this case.')
        
        # Calculate correlation coefficients
        allWindow = np.concatenate((vWindow,sensWindow),axis=1)
        ccMatrixWindow, failFlag = PIUtils.CalcCorrCoef(allWindow)
        if failFlag:
            print('The calculation of the correlation coefficient matrix failed!')
        # Filter the resulting correlation coefficient values using a threshold on the correlation coefficient separation value
        if dropLowCCSepFlag:
            ccMatrixWindowDropped = PIUtils.DropCCUsingLowCCSep(ccMatrixWindow[0:len(currentIDs),len(currentIDs):],ccSepThresh,sensIDInput)
        else:
            ccMatrixWindowDropped = ccMatrixWindow[0:len(currentIDs),len(currentIDs):]
        
        # Get the individual window votes for each customer
        currentPredictions = []
        for custCtr in range(0,len(currentIDs)):
            phasePrediction,votes,voteIndices,voteIDs = CCSensVoting(ccMatrixWindowDropped[custCtr,:], numVotes,phaseLabelsSens,sensIDInput)            
            currentPredictions.append(phasePrediction)
        
        # Insert window cc results into full cc matrix
        if len(currentIDs) == len(custIDInput): #If all customers are present in the window simply put the cc window into the full matrix
            ccMatrixAll[:,:,ensCtr] = ccMatrixWindowDropped
            allWindowVotes[:,ensCtr] = currentPredictions
        else: # if some customers have been removed, match the cc window values to the correct positions in the full cc matrix
            for rowCtr in range(0,len(currentIDs)):
                index1=custIDInput.index(currentIDs[rowCtr])
                numCurrentCust = len(currentIDs)
                ccMatrixAll[index1,:,ensCtr] = ccMatrixWindowDropped[rowCtr,:]
                allWindowVotes[index1,ensCtr] = currentPredictions[rowCtr]
    # End of ensCtr for loop

    # Change all zeros values to NaNs.  A zero value indicates that either the customer was missing for that slot or the window was skipped.
        # These should not be included in the mean calculation
    ccMatrixAll[ccMatrixAll == 0] = np.nan
    # Calculate the mean of values over all the windows
    for rowCtr in range(0,numCust):
        for colCtr in range(0,numSensProfiles):
            currentValues = ccMatrixAll[rowCtr,colCtr,:]
            if np.sum(np.isnan(currentValues)) == ensTotal:
                ccMatrix[rowCtr,colCtr] = np.nan
            else:
                ccMatrix[rowCtr,colCtr] = np.nanmean(currentValues)
    maxCCs = []
    for custCtr in range(0,numCust):
        # If the ccMatrix row is all NaN then the customer was eliminated due to missing data or the CC Separation filter
        if (np.sum(np.isnan(ccMatrix[custCtr,:])) == numSensProfiles):
            noVotesIndex.append(custCtr)
            noVotesIDs.append(custIDInput[custCtr])
            allSensVotes.append([-999,])
            omittedCust['missDataOrFiltered'].append(custIDInput[custCtr])
        elif custWindowCounts[custCtr] < minWindowThreshold: # Check if a customer had fewer windows than the minimum window filter 
            noVotesIndex.append(custCtr)
            noVotesIDs.append(custIDInput[custCtr])
            allSensVotes.append([-999,])
            omittedCust['minWindows'].append(custIDInput[custCtr])
        else:
            # Use voting methodology to determine the phase predictions
            phasePrediction,votes,voteIndices,voteIDs = CCSensVoting(ccMatrix[custCtr,:], numVotes,phaseLabelsSens,sensIDInput)            
            newPhaseLabels[0,custCtr] = phasePrediction
            # If the predicted phase labels = -999 then the customer was eliminated due to voting criteria not being met in CCSensVoting
            if phasePrediction == -999:
                noVotesIndex.append(custCtr)
                noVotesIDs.append(custIDInput[custCtr])
                allSensVotes.append([-999,])
                omittedCust['sensVoteCriteria'].append(custIDInput[custCtr])                
            else:
                allSensVotes.append(votes)
    # Calulate confidence score metrics        
    confScoreCombined,sensVotesConfScore, ccSeparation, winVotesConfScore,numWindows = CalcConfidenceScores4Sensors(ccMatrixAll,
                                                                                                                ccMatrix,
                                                                                                                custIDInput,
                                                                                                                sensIDInput,
                                                                                                                phaseLabelsSens,noVotesIDs,
                                                                                                                numVotes,allWindowVotes,
                                                                                                                allSensVotes,newPhaseLabels)        
    nanSum = np.sum(np.isnan(ccMatrixAll))
    totalCC = voltageCust.shape[1] * voltageCust.shape[1] * ensTotal
    nanDecimal = nanSum / totalCC
    # Remove customers which were not predicted due to missing data or not meeting the voting criteria
    if len(noVotesIndex) > 0:
         newPhaseLabels = np.delete(newPhaseLabels,noVotesIndex,axis=1)
         ccMatrix = np.delete(ccMatrix,noVotesIndex,axis=0)
         ccMatrixAll = np.delete(ccMatrixAll,noVotesIndex,axis=0)
         custIDUsed = list(np.delete(np.array(custIDInput),noVotesIndex))
         confScoreCombined = list(np.delete(np.array(confScoreCombined),noVotesIndex))
         sensVotesConfScore = list(np.delete(np.array(sensVotesConfScore),noVotesIndex))
         ccSeparation = list(np.delete(np.array(ccSeparation),noVotesIndex))
         winVotesConfScore = list(np.delete(np.array(winVotesConfScore),noVotesIndex))
         numWindows = list(np.delete(np.array(numWindows),noVotesIndex))
    else:
         custIDUsed = custIDInput
         
    for ctr in range(0,len(noVotesIDs)):
        print('Warning!  Customers ' + str(noVotesIDs[ctr]) + ' was not predicted due to either missing data, not meeting the voting criteria, or having too few windows available.  Those results omitted.')
         
    return newPhaseLabels,custIDUsed,noVotesIndex,noVotesIDs, omittedCust, \
        confScoreCombined, sensVotesConfScore,ccSeparation,winVotesConfScore, custWindowCounts
# End of AssignPhasesUsingSensors
    




###############################################################################
#
#                       CCSensVoting
#
def CCSensVoting(ccRow, numVotes,phaseLabelsSens,sensIDInput):
    """ This function takes a row of correlation coefficients for one customer,
        and uses the top hightest correlated datastreams to vote on the
        predicted phase based on this row of CC.  If all the votes come from
        different sensors (as they should) then the function takes the mode of 
        votes.  If a sensor has repeated votes this indicates more than one 
        phase of the sensor is highly correlated with this customer.  This 
        sometimes occurs with sensors near the substation but is undesirable. 
        In this case, those sensors are eliminated from voting and only the
        remaining sensors, in the numVotes highest correlated sensors, are
        used for the prediction.
            
            Parameters
            ---------
                ccRow: numpy array of float (numSensors) - the correlation
                    coefficients between one customers and the set of sensors
                numVotes: int - the number of votes to use in the prediction
                phaseLabelsSens: numpy array of int (1,numSensors) - the phase 
                    labels for each sensor.  The dimensions should match the
                    length of ccRow
                sensID: list of str - the list of sensors IDs. The length of
                    this should match the dimensions of ccRow and phaseLabelsSens
            Returns
            -------
                phasePrediction: int - the phase predictions for this customer
                votes: list of int - the votes that led to this prediction
                voteIndices: list of int - the indices of the sensors used
                    in the phase prediction
                voteIDs: list of str - the sensor IDs contributing to the votes

            """       
            
    # Remove any NaNs from the list of correlation coefficients
    nans  = np.isnan(ccRow)
    nanIndices=np.where(nans==1)
    ccRow=np.delete(ccRow,nanIndices)
    sensID=list(np.delete(np.array(sensIDInput),nanIndices))
    phases = np.delete(phaseLabelsSens,nanIndices)
    
    # Remove any zeros from the list of correlation coefficients
    zeroIndices=np.where(ccRow==0)
    ccRow=np.delete(ccRow,zeroIndices)
    sensID=list(np.delete(np.array(sensID),zeroIndices))
    phases = np.delete(phases,zeroIndices)
    phases=np.expand_dims(phases,axis=0)
    totalSensors = len(np.unique(sensID))
    
    # Sort CC and select the votes
    ccSorted = np.sort(ccRow)
    ccArgSorted = np.argsort(ccRow)
    ccVotes = ccSorted[-numVotes:]
    voteIndices = ccArgSorted[-numVotes:]
    voteIDs = list(np.array(sensID)[voteIndices])
    votes = phases[0,voteIndices]
    
    if len(ccSorted)==0: # All CC were eliminated due to NaN (missing data) or 0 (filtered using CC Separation)
        phasePrediction=-999
    # This indicates there are multiple votes from the same sensor which is 
    #   clearly a poor situation, this can occur if the phase datastreams are 
    #   extremely similar, sometimes near the substation        
    elif len(np.unique(voteIDs)) < numVotes: 
        if totalSensors < numVotes: #Reduce the number of votes to the number of available sensors
            if np.mod(totalSensors,2)==0:  # Make number of votes odd
                newNumVotes = totalSensors-1
            else:
                newNumVotes = totalSensors
            ccVotes = ccSorted[-newNumVotes:]
            voteIndices = ccArgSorted[-newNumVotes:]
            voteIDs = list(np.array(sensID)[voteIndices])
            votes = phases[0,voteIndices]                        
        # Find duplicated sensor IDs
        flaggedIDs = []
        foundIDsSet = set({})
        for ctr in range(0,len(voteIDs)):
            if voteIDs[ctr] in foundIDsSet:
                flaggedIDs.append(voteIDs[ctr])
            foundIDsSet.add(voteIDs[ctr])
        flaggedIDs = list(np.unique(flaggedIDs))
        # Remove duplicate sensor datastreams    
        for ctr in range(0,len(flaggedIDs)):
            indices = np.where(np.array(voteIDs)==flaggedIDs[ctr])
            voteIDs = list(np.delete(np.array(voteIDs),indices))
            voteIndices = list(np.delete(np.array(voteIndices),indices))
            votes = np.delete(votes,indices)
        # Use remaining sensor datastreams for prediction
        if votes.shape[0] == 0: # This means that all sensors were eliminated due to having repeated datastreams in the votes.  
            phasePrediction = -999 
        else:
            phasePrediction = stats.mode(votes,axis=0,nan_policy='omit')[0][0]   
    else:
        phasePrediction = stats.mode(votes,axis=0,nan_policy='omit')[0][0]   
    return phasePrediction,votes,voteIndices,voteIDs
# End of CCSensVoting




###############################################################################
#
#                    CalcConfidenceScores4Sensors
def CalcConfidenceScores4Sensors(ccMatrixAllWindows,meanCCMatrix,custIDList,
                                        sensIDInput,sensPhasesInput,noVotesIDs,
                                        numVotes,allWindowVotes,allSensVotes,
                                        newPhaseLabels):
    """ This function calculates 4 per-customer confidence scores for the 
            Sensor/IntelliRupter phase identification method.  1. sensVotes is
            the percentage of sensors which agree on the predicted phase for
            the customers.  Only the sensors included in the votes are
            considered.  2.  winVotes is the percentage of windows which
            agree on the predicted phase.  3.  ccSeparation is the difference
            between the CC on the predicted phase versus the next highest CC.
            4. CombConfScore is the winVotes and the sensVotes multiplied 
            together. 
            Note that these scores measure the consistency
            of the method across windows and do not necessarily imply 
            accuracy.  Note that if any customers were not predicted due to 
            missing data (entries in noVotesIDs) all of the confidence metrics 
            will be recorded as 0 for those customers.  If sensPhasesInput
            only has three entries the function will omit the sensor agreement
            and combined score metrics, assuming that the substation was used
            instead of the sensors.
            
    Parameters
    ---------
        ccMatrixAllWindows: numpy array of float (num customers, number of sensors, number of windows) - 
            the correlation coefficient values between a particular customer and a set of
            sensors. The indexing of axis 0 must match the indexing for
            custIDList.  The indexing of axis 1 must match the indexing for 
            sensIDInput
        meanCCMatrix: numpy array of float (num customers, number of sensors) -
            The mean correlation coefficients over all windows.  If any 
            customers were eliminated due to missing data, then the whole
            column will be NaN
        custIDList: list of str - the list of customer IDs.  This list must
            match the indexing for ccMatrixInput axis 0
        sensIDInput: list of str - the list of sensors IDs.  This list must
            match the indexing for ccMatrixInput axis 1
        sensPhasesInput: numpy array of int (1, sensor datastreams) - the 
            phase labels for each sensor datastream
        noVotesIDs: list of str - the list of customers which were excluded
            from the phase prediction due to missing data
        numVotes: int - the number of sensor votes included in the phase 
            prediction
        allWindowVotes: numpy array of int (customers,windows) - the phase vote
            for each customer in each window.  Windows where the customer was 
            omitted contain -999
        allSensVotes: list of arrays of int - the sensor votes for each customer 
            The length of the main list is the number of customers.  Each list
            item is the sensor votes from the highest correlated sensors, up
            to numVotes sensors.  The length of these arrays may vary if some
            sensors were excluded from voting.  
            analysis
        newPhasLabels: numpy array of int (1,customers) - the predicted phase
            labels for each customer

    Returns
    -------
        sensVotesConfScore: list of float - each entry is the percentage of sensors 
            which agree on the phase prediction for that customer.  This may
            be 0 if sensPhasesInput had 3 entries, i.e. in the substation
            case
        winVotesConfScore: list of float - each entry is the percentage of windows 
            which have the same phase vote for each customer.  This is 
            calculated by considering the phase of the sensor datastream with 
            the highest CC in each window as a vote
        ccSeparation: list of float - each entry is the difference between the 
            highest CC and the next highest CC, considering the mean CC across
            windows.
        confScoreCombined: list of float - the combination of the sensVotes and
            the ccSeparation.  Obtained by multiplying those scores together.
            This may be 0 if sensPhaseInput had 3 entries, i.e. in the substation
            case.
        numWindows: list of int - the number of windows included in each 
            customers window voting score
                
            """
         
    numCust = len(custIDList)
    numWindowsCount = []
    sensVotesConfScore = []
    winVotesConfScore = []
    ccSeparation = []
    
    for custCtr in range(0,numCust):
        currentCustID = custIDList[custCtr]
        if len(noVotesIDs) > 0:
            index = np.where(np.array(noVotesIDs)==currentCustID)[0]
            if len(index) > 0:
                sensVotesConfScore.append(0)
                winVotesConfScore.append(0)
                ccSeparation.append(0)
                numWindowsCount.append(0)
                continue
        
        #######  Calculate winVotesConfScore section
        currWinVotes = allWindowVotes[custCtr,:]
        nanMask = np.where(currWinVotes==-999)[0]
        currWinVotes = np.delete(currWinVotes,nanMask)
        # Calculate voting confidence score
        #Check if all votes were eliminated
        if len(currWinVotes) == 0 :
            winVotesConfScore.append(0)
        # Check of all votes are the same        
        elif len(np.unique(currWinVotes)) == 1:
            winVotesConfScore.append(1)
        else:
            modeValue = stats.mode(currWinVotes)[0]
            # Check if votes are evenly split
            if len(modeValue) > 1:
                confValue = 1 / len(modeValue)
                winVotesConfScore.append(confValue)
            # Calculate voting confidence score using the mode and the total number of votes
            else:
                modeValue = modeValue[0]
                indices = np.where(np.array(currWinVotes)==modeValue)[0]
                confValue = len(indices) / len(currWinVotes)
                winVotesConfScore.append(confValue)
        numWindowsCount.append(len(currWinVotes))
        
        ###### Calculate sensVotesConfScore section
        if sensPhasesInput.shape[1] > 3: # This is a quick and dirty way to omit this section for the substation version
            currSensVotes = allSensVotes[custCtr]
            # Calculate sensor votes confidence score for this customer
            if len(currSensVotes) == 0: # All sensor votes were eliminated
                sensVotesConfScore.append(0)
            elif len(np.unique(currSensVotes))==1:
                sensVotesConfScore.append(1)
            else:
                modeValue = stats.mode(currSensVotes)[0]
                if len(modeValue) > 1:
                    confValue = 1 / len(modeValue)
                    sensVotesConfScore.append(confValue)
                else:
                    modeValue=modeValue[0]
                    indices = np.where(np.array(currSensVotes)==modeValue)[0]
                    confValue = len(indices) / len(currSensVotes)
                    sensVotesConfScore.append(confValue)
        else:
            sensVotesConfScore = [0,]
     
        #### Calculate the ccSeparation section
        currPredictedPhase = newPhaseLabels[0,custCtr]
        currCC = meanCCMatrix[custCtr,:]
        nans  = np.isnan(currCC)
        nanIndices=np.where(nans==1)
        currCC=np.delete(currCC,nanIndices)
        sensIDNoNan=list(np.delete(np.array(sensIDInput),nanIndices))        
        argsortedCC = np.argsort(currCC)
        sortIndex = len(currCC) -1
        while sensPhasesInput[0,argsortedCC[sortIndex]] != currPredictedPhase:
            sortIndex = sortIndex - 1
        currSensor = sensIDInput[argsortedCC[sortIndex]]
        indices = np.where(np.array(sensIDInput)==currSensor)[0]
        ccSet = np.sort(currCC[indices])
        ccDiff = ccSet[-1] - ccSet[-2]
        ccSeparation.append(ccDiff)
       
    # End of custCtr for loop
    confScoreCombined = []
    for ctr in range(0,len(sensVotesConfScore)):
        confScoreCombined.append(sensVotesConfScore[ctr] * winVotesConfScore[ctr])
    
    return confScoreCombined,sensVotesConfScore, ccSeparation, winVotesConfScore,numWindowsCount    
# End of CalcConfidenceScores4Sensors
        



###############################################################################

# The AssignPhasesUsingSubstation function does the phase identification task
#   by simply calculating the correlation coefficients between the customers
#   and each substation datastream (one for each phase) and assigning the 
#   highest correlation substation phase as the predicted phase for each 
#   customer.  This is used in comparison to the sensor-based method above.
#   Substation correlations is a commonly used phase identification method, but
#   it has many downsides, such as poor performance when there are voltage
#   regulators in the system.  



##############################################################################
#
#                   AssignPhasesUsingSubstation
#
def AssignPhasesUsingSubstation(voltageCust,voltageSub,custIDInput,
                                subIDInput,phaseLabelsSub,windowSize):
    """ This function takes customer voltage timeseries and voltage timeseries
        from the substation and assigns a phase label to the customer based on 
        the highest correlation with one of the substation phases.  This is a 
        comparison method to the sensor-based method
            
            Parameters
            ---------
                voltageCust:  numpy array of float (measurements,customers) 
                    full-length voltage timeseries for each customer.  This 
                    should be in per-unit and delta voltage form
                voltageSub:  numpy array of float (measurements,phases) 
                    full-length voltage profiles for each substation phase.  
                    This should be in per-unit and in delta voltage form.
                custIDInput: list of str - the list of customer IDs
                subIDInput: list of str - the list of substation IDs.  This 
                    will likely be the substation name repeated three times.
                    This is necessary for the confidence score function
                phaseLabelsSub: numpy array of int (1,num phases) - the phase 
                    labels for each of the substation datastreams
                windowSize: int - the number of samples to use in each window
            Returns
            -------
                ccMatrixSub: numpy array of float (customers,numPhases) - the final,
                    median, correlation coefficients for all customers over
                    all windows
                custIDUsed: list of str - the list of customer IDs which were
                    predicted.  If no customers were lost due to missing data
                    this will match custIDInput.
                noVotesIndex: list of int - the indices of customers who were
                    removed from all windows
                noVotesIDs: list of str - the customer IDs of customers who 
                    were removed from all windows
                predictedPhases: numpy array of int (1,customers) - the predicted
                    phase labels based on correlation with the substation
                winVotesConfScore: list of float - each entry is the percentage of windows 
                    which have the same phase vote for each customer.  This is 
                    calculated by considering the phase of the sensor datastream with 
                    the highest CC in each window as a vote
                ccSeparation: list of float - each entry is the difference between the 
                    highest CC and the next highest CC, considering the mean CC across
                    windows.
            """    
        
    ensTotal = int(np.floor(voltageCust.shape[0] / windowSize))
    ccMatrixAll = np.zeros((voltageCust.shape[1],voltageSub.shape[1],ensTotal),dtype=float)
    ccMatrix = np.zeros((voltageCust.shape[1],voltageSub.shape[1]),dtype=float)
    newPhaseLabels = np.zeros((1,voltageCust.shape[1]),dtype=int)
    noVotesIndex = []
    noVotesIDs = []
    numSubProfiles = voltageSub.shape[1]
    numCust = len(custIDInput)
    
    # Calculate all correlation coefficients for all windows
    for ensCtr in range(0,ensTotal):
        #print('ensCtr = ' + str(ensCtr))
        #Customer Voltage - Select the next time series window and remove customers with missing data in that window
        vWindow = PIUtils.GetVoltWindow(voltageCust,windowSize,ensCtr)
        vWindow,currentIDs = PIUtils.CleanVoltWindowNoLabels(deepcopy(vWindow), deepcopy(custIDInput))
        # Sub Voltage - Select the next time series window and remove customers with missing data in that window
        subWindow = PIUtils.GetVoltWindow(voltageSub,windowSize,ensCtr)
        nanCount = np.sum(np.isnan(subWindow))
        if nanCount > 0:
            print('The substation data had ' + str(nanCount) + ' NaN values in this window (window: ' + str(ensCtr) + ').  This implementation skipped this window altogether.  I am assuming that this data comes from SCADA and will have few missing values.  If this becomes a problem -> Fix This!')
            continue
        # Calculate correlation coefficients
        allWindow = np.concatenate((vWindow,subWindow),axis=1)
        ccMatrixWindow, failFlag = PIUtils.CalcCorrCoef(allWindow)
        if failFlag:
            print('The calculation of the correlation coefficient matrix failed!')
        
        # Insert window cc results into full cc matrix
        if len(currentIDs) == len(custIDInput): #If all customers are present in the window simply but the cc window into the full matrix
            ccMatrixAll[:,:,ensCtr] = ccMatrixWindow[0:numCust,numCust:]
        else: # if some customers have been removed, match the cc window values to the correct positions in the full cc matrix
            for rowCtr in range(0,len(currentIDs)):
                index1=custIDInput.index(currentIDs[rowCtr])
                numCurrentCust = len(currentIDs)
                #print(str(rowCtr) + ',' + str(index1))
                ccMatrixAll[index1,:,ensCtr] = ccMatrixWindow[rowCtr,numCurrentCust:]
    # End of ensCtr for loop

    # Change all zeros values to NaNs.  A zero value indicates that either the customer was missing for that slot or the window was skipped.
        # These should not be included in the mean calculation
    ccMatrixAll[ccMatrixAll == 0] = np.nan       
    # Calculate the mean of values over all the windows
    for rowCtr in range(0,numCust):
        for colCtr in range(0,numSubProfiles):
            currentValues = ccMatrixAll[rowCtr,colCtr,:]
            if np.sum(np.isnan(currentValues)) == ensTotal:
                ccMatrix[rowCtr,colCtr] = np.nan
            else:
                ccMatrix[rowCtr,colCtr] = np.nanmean(currentValues)
    for custCtr in range(0,numCust):
        if np.sum(np.isnan(ccMatrix[custCtr,:])) == numSubProfiles:
            noVotesIndex.append(custCtr)
            noVotesIDs.append(custIDInput[custCtr])
    maxCCs = []
    for custCtr in range(0,numCust):
        maxIndex = np.argmax(ccMatrix[custCtr,:])
        maxCCs.append(np.max(ccMatrix[custCtr,:]))
        #print('max value = ' + str(np.max(ccMatrix[custCtr,:])) + ', min value = ' + str(np.min(ccMatrix[custCtr,:])))
        newPhaseLabels[0,custCtr] = phaseLabelsSub[0,maxIndex]

    # Calculate confidence score metrics    
    confScoreCombined,sensVotesConfScore, ccSeparation, winVotesConfScore = CalcConfidenceScores4Sensors(ccMatrixAll,
                                                                                                                ccMatrix,
                                                                                                                custIDInput,
                                                                                                                subIDInput,
                                                                                                                phaseLabelsSub,noVotesIDs) 


    # Remove customers which were not predicted due to missing data
    if len(noVotesIndex) > 0:
         newPhaseLabels = np.delete(newPhaseLabels,noVotesIndex,axis=1)
         ccMatrix = np.delete(ccMatrix,noVotesIndex,axis=0)
         custIDUsed = list(np.delete(np.array(custIDInput),noVotesIndex))
         ccSeparation = list(np.delete(np.array(ccSeparation),noVotesIndex))
         winVotesConfScore = list(np.delete(np.array(winVotesConfScore),noVotesIndex))
    else:
         custIDUsed = custIDInput
         
    for ctr in range(0,len(noVotesIDs)):
        print('Warning!  Customers ' + str(noVotesIDs[ctr]) + ' was not predicted due to missing data.  Those results omitted.')
        
    ccMatrixSub=ccMatrix
    predictedPhaseLabels=newPhaseLabels
    return ccMatrixSub,custIDUsed,noVotesIndex,noVotesIDs,predictedPhaseLabels,winVotesConfScore,ccSeparation
# End of AssignPhasesUsingSubstation
    
















