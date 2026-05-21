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

"""


# Import Statements
import numpy as np
import warnings
from copy import deepcopy
import matplotlib.pyplot as plt
from pathlib import Path
import datetime
import math
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
import pickle
import pandas as pd


###############################################################################
#
#                           ConvertToPerUnit_Voltage
#
def ConvertToPerUnit_Voltage(timeseries):
    ''' This function takes a voltage timeseries and converts it into a per
            unit representation.  This function looks at each customers 
            individual timeseries, rounds the mean of the measurements and 
            compares that to a list of known base voltages.  Voltage levels may
            need to be added to that list.  
            This allows for the case where some customers run at 240V and some
            run at 120V in the same dataset. The
            function will print a warning if some customers have all NaN 
            values, but it will complete successfully in that case. The
            customer will have all NaN values in the per-unit timeseries as well.

        Parameters
        ----------
            timeseries: numpy array (measurements,customers), the raw voltage
                measurements

        Returns:
            voltagePU: numpy array (measurements,customers), the voltage 
                timeseries converted into per unit representation
        '''
    
    voltageMismatchThresh = .8
    voltageLevels = np.array([120,240,7200])
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
#                           CC_EnsMedian
#
def CC_EnsMedian(voltage,windowSize,custID):
    """ This function uses the window method to calculate correlation coefficients.
        In each window customers with missing data are removed and correlation
        coefficients are calculated for the remaining customers.  The median 
        correlation coefficient is taken for each paring across all windows as
        the final cc.  This is done because are some cases where there
        is odd behavior in the cc in some  individual windows.  Customers who 
        were removed from all windows still have a row/col in the final 
        returned matrix but the correlation coefficient will be marked as 0.
            
            Parameters
            ---------
                voltage:  numpy array of float (measurements,customers) 
                    full-length voltage profiles for each customer
                windowSize: int - the number of samples to use in each window
                custID: list of str - the customer ids
            Returns
            -------
                ccMatrix: numpy array of float (customers,customers) - the final,
                    median, correlation coefficients for all customers over
                    all windows
                noVotesIndex: list of int - the indices of customers who were
                    removed from all windows
                noVotesIDs: list of str - the customer IDs of customers who 
                    were removed from all windows
            """    
        
    #print('Starting Correlation Coefficient calculation')
    ensTotal = int(np.floor(voltage.shape[0] / windowSize))
    ccMatrixAll = np.zeros((voltage.shape[1],voltage.shape[1],ensTotal),dtype=float)
    ccMatrix = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    noVotesIndex = []
    noVotesIDs = []
    
    # Calculate all correlation coefficients for all windows
    for ensCtr in range(0,ensTotal):
        #Select the next time series window and remove customers with missing data in that window
        vWindow = GetVoltWindow(voltage,windowSize,ensCtr)
        vWindow,currentIDs = CleanVoltWindowNoLabels(deepcopy(vWindow), deepcopy(custID))
        ccMatrixWindow, failFlag = CalcCorrCoef(vWindow)
        
        #Check for all/most customers being removed from the window
        if ccMatrixWindow.shape==():
            continue
        
        if ccMatrixWindow.shape[0] == voltage.shape[1]: #If all customers are present in the window simply put the cc window into the full matrix
            ccMatrixAll[:,:,ensCtr] = ccMatrixWindow
        else: # if some customers have been removed, match the cc window values to the correct positions in the full cc matrix
            for rowCtr in range(0,len(currentIDs)):
                index1=custID.index(currentIDs[rowCtr])
                for colCtr in range(0,len(currentIDs)):
                    index2=custID.index(currentIDs[colCtr])
                    ccMatrixAll[index1,index2,ensCtr] = ccMatrixWindow[rowCtr,colCtr]

    # Take the median cc of all windows for each customer
    for custCtr1 in range(0,voltage.shape[1]):
        custCtr2 = custCtr1
        while custCtr2 < voltage.shape[1]:
            ccRow = ccMatrixAll[custCtr1,custCtr2,:]
            zeroIndices = np.where(ccRow==0)
            ccRow = np.delete(ccRow,zeroIndices)
            if len(ccRow) == 0:
                med = 0
            else:
                med = np.median(ccRow)
            ccMatrix[custCtr1,custCtr2] = med
            ccMatrix[custCtr2,custCtr1] = med
            custCtr2 = custCtr2+1         
    # Search for customers which received no cc -> ie were removed in all windows
    # I've chosen to leave those entries in the full CC Matrix instead of removing them
    for custCtr in range(0,voltage.shape[1]):
        if np.sum(ccMatrix[custCtr,:])==0:
            noVotesIndex.append(custCtr)
            noVotesIDs.append(custID[custCtr])           
    return ccMatrix,noVotesIndex,noVotesIDs
# End of CC_EnsMedian
    


##############################################################################
#
# GetVoltWindow
# 
def GetVoltWindow(voltage,windowSize,windowCtr):
    """ This function takes the voltage time series and retrieves a particular
        window based on the windowCtr parameter.
            
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
# CleanVoltWindowNoLabels
#
def CleanVoltWindowNoLabels(voltWindow,currentCustIDs):
    """ This function takes a window of voltage time series and removes customers
        which contain missing data during that window.  
            
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
                    of customers without the 'cleaned' customers
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
              



###############################################################################
#
# CalcCorrCoef
#
def CalcCorrCoef(voltageWin):
    ''' This function takes a voltage window, calculates the correlation
        coefficients, checks for failure of calculating good correlation
        coefficients (if the resulting matrix is not positive definite, the
        function returns an error), and returns the CC matrix.

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
    

###############################################################################
#
#                   ParamEst_LinearRegression
#
def ParamEst_LinearRegression(voltage,pAvg,qAvg,saveFlag=True,savePath=-1):
    ''' Does a linear regression to find the x-values (reactance) and r-values
        (resistance) based on the given voltage, real power, and reactive power
        time series that are given.  Returns a matrix of estimated pairwise resistance
        and reactance values for each customer as well as an r-squared value
        denoting the pairwise 'fit' between customers.  Note that the dimensions of 
        the voltage, real power, and reactive power must match.  This is based
        on Matt Lave's work ("Full-scale Demonstration of Distribution System 
        Parameter Estimation to Improve Low-Voltage Circuit Models") as well as
        Kavya Ashok's work.  General formula: V1 - V2 = IR2(R2) + IX2(X2) - IR1(R1) - IX1(X1) + E
        This function discards pairs of values if one or both of the customers
        have missing data during that timestep, meaning the pairwise regression
        only uses timesteps where both pairs have data.

        Parameters
        ---------
            voltage: (measurements,customers) numpy array of float containing 
                the voltage time series measurements for each customer
                The dimensions of voltage, pAvg, and qAvg must match.
            pAvg: (measurements,customers) numpy array of float containing the
                real power time series measurements for each customer
                The dimensions of voltage, pAvg, and qAvg must match.     
            qAvg: (measurements, customers) numpy array of float containing the
                reactive power measurements for each customer
                The dimensions of voltage, pAvg, and qAvg must match.               
            saveFlag: bool - flag to save the results in pickle files or not
            savePath: pathlib object or str - path to save the pickle
                files.  If none specified the files are saved in the current 
                directory.

        Returns
        -------
            r2Affinity: (customers,customers) numpy array of float with the 
                r-squared, pariwise affinity values from the regression 
                (mirrored across the diagonal)    
            regRDist: (customers,customers) numpy array of float with the pairwise
                resistance 'distances' for each customer (mirrored across the
                diagonal)
             regXDist: (customers,customers) numpy array of float with the pairwise 
                reactance 'distances' for each customer (mirrored across the 
                diagonal)
            regRDistIndiv: (customers,customers) numpy array of float with the 
                resistance for the row customer when paired with the col customer
            regXDistIndiv: (customers,customers) numpy array of float with the
                reactance for the row customer when paired with the col customer
            mseMatrix: (customers,customers) numpy array of float with the 
                mean-squared error between true and predicted values for each 
                regression
            
        '''

    r2Affinity = np.ones((voltage.shape[1],voltage.shape[1]),dtype=float)
    mseMatrix = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regRDist = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regXDist = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regRDistIndiv = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regXDistIndiv = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    # Walk through each customer pairing and do the regression, note that the 
    #resulting matrices are mirrored across the diagonal
    for custCtr in range(0,voltage.shape[1]):
        #if np.mod(custCtr,20)==0:
        #    print('Customer ' + str(custCtr) + '/' + str(voltage.shape[1]))
        ctr = custCtr + 1
        while ctr < voltage.shape[1]:
            #print(str(custCtr) + ' / ' + str(ctr))
            # Grab current customer pair
            v1 = voltage[:,custCtr]
            v2 = voltage[:,ctr]
            p1 = pAvg[:,custCtr]
            p2 = pAvg[:,ctr]
            q1 = qAvg[:,custCtr]
            q2 = qAvg[:,ctr]
            # Remove any nan values from the current pair of customers timeseries
            mask = ~np.isnan(v1) & ~np.isnan(v2) & ~np.isnan(p1) & ~np.isnan(p2) & ~np.isnan(q1) & ~np.isnan(q2)
            v1 = v1[mask]
            v2 = v2[mask]
            p1 = p1[mask]
            p2 = p2[mask]
            q1 = q1[mask]
            q2 = q2[mask]
            #Calculate currents
            ir1 = np.divide(p1,v1)
            ir2 = np.divide(p2,v2)
            ix1 = np.divide(q1,v1)
            ix2 = np.divide(q2,v2)
            
            #Check for all timesteps being eliminated due to NaNs
            if v1.shape[0] == 0:
                r2Affinity[custCtr,ctr] = -1
                r2Affinity[ctr,custCtr] = -1
                mseMatrix[custCtr,ctr] = 1
                mseMatrix[ctr,custCtr] = 1
            else:
                # Setup regression
                y = v1-v2
                x = np.zeros((y.shape[0],4),dtype=float)
                x[:,0] = ir1 * -1
                x[:,1] = ix1 * -1
                x[:,2] = ir2 
                x[:,3] = ix2
                model = LinearRegression().fit(x,y)
                #model = Ridge().fit(x,y)
                #model = HuberRegressor().fit(x,y)
                #slope, intercept, r_value, p_value, std_err = stats.linregress(x,y)            
                yPred = model.predict(x)
                #Save r-squared scores
                r2 = model.score(x,y)
                r2Affinity[custCtr,ctr] = r2
                r2Affinity[ctr,custCtr] = r2
                
                mse = mean_squared_error(y,yPred)
                mseMatrix[custCtr,ctr] = mse
                mseMatrix[ctr,custCtr] = mse
                
                # Save resistance coefficients - added together for an approximate distance between customers
                rDist = model.coef_[0] + model.coef_[2]
                regRDist[custCtr,ctr] = rDist
                regRDist[ctr,custCtr] = rDist
                regRDistIndiv[custCtr,ctr] = model.coef_[0]
                regRDistIndiv[ctr,custCtr] = model.coef_[2]
                #Save x (reactance) coefficients - added together for an approximate distance between customers
                xDist = model.coef_[1] + model.coef_[3]
                regXDist[custCtr,ctr] = xDist
                regXDist[ctr,custCtr] = xDist
                regXDistIndiv[custCtr,ctr] = model.coef_[1]
                regXDistIndiv[ctr,custCtr] = model.coef_[3]
            ctr = ctr + 1
    # End of custCtr for loop
    
    if saveFlag:
        # Save out pickle files of the r2 affinity matrix and the r1 + r2 distance matrix.
        dataFilename = 'r2AffinityMatrix.pkl'
        pickleData(r2Affinity,dataFilename,basePath=savePath)
        dataFilename = 'regRDistMatrix.pkl'
        pickleData(regRDist,dataFilename,basePath=savePath)
        dataFilename = 'regXDistMatrix.pkl'
        pickleData(regXDist,dataFilename,basePath=savePath)
        dataFilename = 'regRDistMatrixIndividual.pkl'
        pickleData(regRDistIndiv,dataFilename,basePath=savePath)
        dataFilename = 'regXDistMatrixIndividual.pkl'
        pickleData(regXDistIndiv,dataFilename,basePath=savePath)    
        dataFilename = 'mseMatrix.pkl'
        pickleData(mseMatrix,dataFilename,basePath=savePath)    
    return r2Affinity,regRDist,regXDist,regRDistIndiv,regXDistIndiv,mseMatrix
# End of ParamEst_LinearRegression function



###############################################################################
#
#                   ParamEst_LinearRegression_NoQ
#
def ParamEst_LinearRegression_NoQ(voltage,p,savePath=-1):
    ''' Does a linear regression to find the x-values (reactance) and r-values
        (resistance) based on the given voltage, real power, and reactive power
        time series that are given.  Returns a matrix of estimated pairwise resistance
        and reactance values for each customer as well as an r-squared value
        denoting the pairwise 'fit' between customers.  Note that the dimensions of 
        the voltage, real power, and reactive power must match.  This is based
        on Matt Lave's work ("Full-scale Demonstration of Distribution System 
        Parameter Estimation to Improve Low-Voltage Circuit Models") as well as
        Kavya Ashok's work.  General formula: V1 - V2 = IR2(R2) + IX2(X2) - IR1(R1) - IX1(X1) + E
        This version does not use reactive power

        Parameters
        ---------
            voltage: ndarray of float:  (measurements,customers) numpy array 
                of float containing the voltage time series measurements for 
                each customer
            p: ndarray of float:  (measurements,customers) numpy array of 
                float containing the real power time series measurements for 
                each customer
            savePath: pathlib object or str - path to save the pickle
                files.  If none specified the files are saved in the current 
                directory

        Returns
        -------
            r2Affinity: ndarray of float: (customers,customers)  
                r-squared, pariwise affinity values from the regression 
                (mirrored across the diagonal)    
            regRDist: ndarray of float:  (customers,customers) - the pairwise
                resistance 'distances' for each customer (mirrored across the
                diagonal)
            regRDistIndiv: ndarray of flaot:  (customers,customers) - 
                resistance for the row customer when paired with the col customer
            mseMatrix:  ndarray of float (customers,customers) -  mean-squared 
                error between true and predicted values for each regression
            
        '''
    
    r2Affinity = np.ones((voltage.shape[1],voltage.shape[1]),dtype=float)
    mseMatrix = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regRDist = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    regRDistIndiv = np.zeros((voltage.shape[1],voltage.shape[1]),dtype=float)
    # Walk through each customer pairing and do the regression, note that the 
    #resulting matrices are mirrored across the diagonal
    for custCtr in range(0,voltage.shape[1]):
        #if np.mod(custCtr,20) == 0:
            # print('Customer ' + str(custCtr) + '/' + str(voltage.shape[1]))
        ctr = custCtr + 1
        while ctr < voltage.shape[1]:
            #print(str(custCtr) + ' / ' + str(ctr))
            # Grab current customer pair
            v1 = voltage[:,custCtr]
            v2 = voltage[:,ctr]
            p1 = p[:,custCtr]
            p2 = p[:,ctr]
            # Remove any nan values from the current pair of customers timeseries
            mask = ~np.isnan(v1) & ~np.isnan(v2) & ~np.isnan(p1) & ~np.isnan(p2) 
            v1 = v1[mask]
            v2 = v2[mask]
            p1 = p1[mask]
            p2 = p2[mask]

            #Calculate currents
            ir1 = np.divide(p1,v1)
            ir2 = np.divide(p2,v2)
            
            #Check for all timesteps being eliminated due to NaNs
            if v1.shape[0] == 0:
                r2Affinity[custCtr,ctr] = -1
                r2Affinity[ctr,custCtr] = -1
                mseMatrix[custCtr,ctr] = 1
                mseMatrix[ctr,custCtr] = 1
            else:
                # Setup regression
                y = v1-v2
                x = np.zeros((y.shape[0],2),dtype=float)
                x[:,0] = ir1 * -1
                x[:,1] = ir2 
                model = LinearRegression().fit(x,y)         
                yPred = model.predict(x)
                #Save r-squared scores
                r2 = model.score(x,y)
                r2Affinity[custCtr,ctr] = r2
                r2Affinity[ctr,custCtr] = r2
                mse = mean_squared_error(y,yPred)
                mseMatrix[custCtr,ctr] = mse
                mseMatrix[ctr,custCtr] = mse
                # Save resistance coefficients - added together for an approximate distance between customers
                rDist = model.coef_[0] + model.coef_[1]
                regRDist[custCtr,ctr] = rDist
                regRDist[ctr,custCtr] = rDist
                regRDistIndiv[custCtr,ctr] = model.coef_[0]
                regRDistIndiv[ctr,custCtr] = model.coef_[1]
                #Save x (reactance) coefficients - added together for an approximate distance between customers
 
            ctr = ctr + 1
    # End of custCtr for loop
    
    # Save out pickle files of the r2 affinity matrix and the r1 + r2 distance matrix.
    dataFilename = 'r2AffinityMatrix.pkl'
    pickleData(r2Affinity,dataFilename,basePath=savePath)
    dataFilename = 'regRDistMatrix.pkl'
    pickleData(regRDist,dataFilename,basePath=savePath)
    dataFilename = 'regRDistMatrixIndividual.pkl'
    pickleData(regRDistIndiv,dataFilename,basePath=savePath)  
    dataFilename = 'mseMatrix.pkl'
    pickleData(mseMatrix,dataFilename,basePath=savePath)    
        
    return r2Affinity,regRDist,regRDistIndiv,mseMatrix
# End of ParamEst_LinearRegression_NoQ function
    
##############################################################################





################################################################################
#
# PlotNumFlaggedTrans_ThresholdSweep
#
def PlotNumFlaggedTrans_ThresholdSweep(thresholdValues,allNumFlagged,transLabelsInput,savePath=-1):
    ''' Plots the number of flagged transformers over a set of threshold values
            probably for the correlation coefficient matrix. This is useful 
            for utility data where fp and fn cannot be used.

        Parameters
        ---------
            thresholdValues: list of float - the values for the xAxis 
                representing the threshold value.  This is likely to be a list
                of correaltion coefficients.  
            allNumFlagged: list of int - the number flagged transformers in each
                simulation
            transLabelsInput: numpy array of int (1, customers) - the 
                transformer labels for each customer
            savePath: pathlib object or str - the folder to save the figure into.
                If this parameter is not specified the figure will save to the
                current working directory.

        Returns
        -------
            None
        '''
    numTrans = len(np.unique(transLabelsInput))
    fig, ax1 = plt.subplots(figsize=(12,9))
    color = 'tab:blue'
    ax1.set_xlabel('Correlation Coefficient Threshold',fontsize=18,fontweight='bold')
    ax1.set_ylabel('Number of Flagged Transformers',fontsize=16,fontweight='bold')
    ax1.plot(thresholdValues,allNumFlagged,color=color,linestyle='solid',linewidth=3)
    textStr = 'Total Transformers = ' + str(numTrans)
    ax1.text(0.1,0.6, textStr, fontweight='bold',fontsize=20,transform=ax1.transAxes)
    plt.xticks(fontsize=13,fontweight='bold')
    plt.yticks(fontsize=13,fontweight='bold')
    fig.tight_layout()
    # plt.show()
    # Save figure to specified path
    today = datetime.datetime.now()
    # timeStr = today.strftime("%Y-%m-%d_%H-%M-%S")
    filename = 'CCThresholdSweep_NumFlaggedTrans_LINE'
    filename = filename + '.png'
    if type(savePath) != int:
        filePath = Path(savePath, filename)
    else:
        filePath = Path(filename)
    fig.savefig(filePath)         
# End of PlotNumFlaggedTrans_ThresholdSweep



###############################################################################
#
# pickleData
def pickleData(data, filename,basePath=-1):
    ''' Takes data and a filename and writes out a pickle file.

        Parameters:
        -----------
            data: any type, container, or object - data to be written to a file
            filename: str - the name of the file
            basePath: pathlib object or str - the folder to save the figure into.
                If this parameter is not specified the figure will save to the
                current working directory.
            
        Returns
        -------
            None
    '''
    
    if type(basePath) != int:
        filePath = Path(basePath,filename)
    else:
        filePath = filename
    fp = open(filePath, 'wb')
    pickle.dump(data, fp)
    fp.close()
# End of pickleData



################################################################################
#
# FindMinMSE
#
def FindMinMSE(mseMatrix,additiveFactor):
    ''' Returns the minimum MSE value from the matrix, excluding the zeros
        on the diagnonal.

        Parameters
        ---------
            mseMatrix: numpy array of float (customers,customers) - the pairwise
                mse values from the linear regression
            additiveFactor: float - the value to add to the min mse value to 
                create the mse threshold

        Returns
        -------
            minMSE: float - the minimum MSE value
            mseThreshold: float - the min mse + the additive factor
        '''
    
    mseNo0 = deepcopy(mseMatrix)
    mseNo0[mseNo0==0] = 1000
    minMSE = np.min(np.min(mseNo0))
    # print('minMSE value =  ' + str(minMSE))
    mseThreshold = minMSE + additiveFactor
    return minMSE, mseThreshold
# End of FindMinMSE


###############################################################################
#
#           CalcTransPredErrors
#
def CalcTransPredErrors(predictedTransLabels,trueTransLabels,custIDList,singleCustMarker=-999):
    """ This function calculates the error from the meter-transformer pairing
    task at the transformer level.  Analyzes the accuracy of the predicted 
    labels incorrect using three different metrics.
    Note that the predictions are the results of a clustering algorithm and 
    will not match the true labels exactly.  This function resolves the 
    groupings themselves.
            
            Parameters
            ---------
                predictedTransLabels: (1,customers) numpy array of integer 
                    cluster label predictions for the transformer groupings.In
                    this function these predicted labels are not intended to 
                    match the true labels, the groupings should match.
                trueTransLabels: (1,customers) numpy array of integer 
                    ground truth transformer labels
                custIDList: List of strings with the customer IDs                    
                singleCustMarker: int representing the placeholder used for
                    single customer transformers (for example DBSCAN may use -1)
                    Value should be -999 if single customer transformers are given
                    unique transformer predictions.

                
            Returns
            -------
                incorrectTrans:  List of true tranformer labels which are 
                    incorrect.  Incorrect here is defined as not having a 
                    grouping in the predicted labels which matches exactly.
                    This will not give insight into 'how wrong' the transformer
                    was just that something was incorrect in that transformer 
                    grouping.  
                incorrectPairedIndices: List of customer indices which are
                    incorrect in the sense that they are not grouped with all 
                    of the customers that they should be.  This is simply 
                    determined by taking all customers within an 
                    'incorrect' transformer.
                incorrectPairedIDs: List of customer IDs from above
            """       
    
    incorrectTrans = set([])
    incorrectPairedIndices = []
    incorrectPairedIDs = []
    predSets = set([])
    
    #If single customer transformers do not already have unique predictions, 
    #this section replaces the 'marker' with decreasing negative numbers to
    # give them unique predictions
    if singleCustMarker != -999:
        marker = -1
        for custCtr in range(0,predictedTransLabels.shape[1]):
            if predictedTransLabels[0,custCtr] == singleCustMarker:
                predictedTransLabels[0,custCtr] = marker
                marker = marker - 1
            
    # Create the set of predicted transformer sets
    for custCtr in range(0,predictedTransLabels.shape[1]):
        currentList = np.where(predictedTransLabels == predictedTransLabels[0,custCtr])[1]
        predSets.add(frozenset(currentList))    
    # Compare the true sets to the predicted sets
    for custCtr in range(0,trueTransLabels.shape[1]):
        currentTrans = trueTransLabels[0,custCtr]
        currentList = np.where(trueTransLabels == currentTrans)[1]
        if set(currentList) not in predSets:
            incorrectTrans.add(currentTrans)
            incorrectPairedIndices.append(custCtr)
            incorrectPairedIDs.append(custIDList[custCtr])
    incorrectTrans = list(incorrectTrans) 
    return incorrectTrans,incorrectPairedIndices, incorrectPairedIDs
# End of CalcTransPredErrors


###############################################################################
#
#           PrettyPrintChangedCustomers
#
def PrettyPrintChangedCustomers(predictedTransLabels,transLabelsErrors,custIDInput):
    """ This function takes the predicted transformer labels and the true 
            transformer labels and pretty prints the ones which have changed
            
            Parameters
            ---------
                predictedTransLabels: (1,customers) numpy array of integer 
                    cluster label predictions for the transformer groupings.In
                    this function these predicted labels are not intended to 
                    match the true labels, the groupings should match.
                transLabelsErrors: (1,customers) numpy array of integer 
                    the transformer labels which may contain errors
                custIDInput: List of str (customers) - the list of customer IDs                    

            Returns
            -------
                None
            """       
    
    print('Customers whose transformer labels/groupings have changed')
    
    
    for custCtr in range(0,predictedTransLabels.shape[1]):
        if predictedTransLabels[0,custCtr] != transLabelsErrors[0,custCtr]:
            print(str(custIDInput[custCtr]) + ' - Predicted Group: ' + str(predictedTransLabels[0,custCtr]) + ', Original Label: ' + str(transLabelsErrors[0,custCtr]))
# End of PrettyPrintChangedCustomers




##############################################################################
#
#       CreateDistanceMatrix
#
def _haversine_distance(loc1, loc2, units='m'):
    """Return great-circle distance between (lat, lon) pairs in the requested units."""
    unit_factors = {
        'm': 1.0,
        'meter': 1.0,
        'meters': 1.0,
        'km': 0.001,
        'kilometer': 0.001,
        'kilometers': 0.001,
        'mi': 1.0 / 1609.344,
        'mile': 1.0 / 1609.344,
        'miles': 1.0 / 1609.344,
        'ft': 3.280839895013123,
        'foot': 3.280839895013123,
        'feet': 3.280839895013123,
    }
    unit_key = str(units).lower()
    if unit_key not in unit_factors:
        raise ValueError("Unsupported haversine distance unit: " + str(units))
    lat1, lon1 = map(math.radians, loc1)
    lat2, lon2 = map(math.radians, loc2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2.0)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0)**2
    distance_m = 6371008.8 * 2.0 * math.asin(min(1.0, math.sqrt(a)))
    return distance_m * unit_factors[unit_key]


def CreateDistanceMatrix(latLonDict, labels,distTypeFlag='euclidean',units='m'):
    """ This function takes a list of x,y coordinates indexed by customer
            and creates a dictionary for lat/lon keyed to the transformer 
            string name.  This function can either calculate euclidean 
            distance or haversine distance.  Haversine distance should only
            be used with true latitude and longitude coordinates.  Euclidean 
            distance is the default.
            
            
            Parameters
            ---------
                latLonDict: dictionary of tuples - lat lon tuples, keyed by a
                    label.  The label could be anything
                labels: The labels which are the keys for the dictionary.  The
                    type of this is left open.  This could be a ndarray of int
                    (1,customers) of transformer labels or a list of str.  
                distTypeFlag: str - controls the type of distance calculation
                    used.  The options are 'euclidean' or 'haversine', with 
                    euclidean being the default.  The haversine distance should
                    only be used with true latitude and longitude coordinates
                units: str - the units for using the haversine distance. The
                    default is m for meters.  ft would also be an acceptable 
                    value

            Returns
            -------
                distMatrix: ndarray of float - The distance between all pairs 
                    of points in labels
                    
            """
    # This forces labelsList into a common form regardless of the type of the labels input
    labelsList = list(np.squeeze(labels))
    
    distMatrix = np.zeros((len(labelsList),len(labelsList)),dtype=float)
    
    if distTypeFlag == 'euclidean':
            
        for custCtr in range(0,len(labelsList)):
            currLabel = labelsList[custCtr]
            loc1 = latLonDict[labelsList[custCtr]]
            ctr = custCtr + 1
            while ctr < len(labelsList):
                loc2 = latLonDict[labelsList[ctr]]
                distance = ( (loc2[0] - loc1[0])**2 + (loc2[1] - loc1[1])**2 ) ** 0.5
                
                distMatrix[custCtr,ctr] = distance
                distMatrix[ctr,custCtr] = distance
                ctr = ctr + 1
    elif distTypeFlag =='haversine':
        for rowCtr in range(0,len(labelsList)):
            currRowLabel = labelsList[rowCtr]
            if currRowLabel not in latLonDict:
                print('Label ' + str(currRowLabel) + ' is not present in the latLonDict.  This label was skipped and NaN placed in the distMatrix')
                continue
            colCtr = rowCtr + 1
            while colCtr < len(labelsList):
                currColLabel = labelsList[colCtr]
                distance = np.round(_haversine_distance(latLonDict[currRowLabel],latLonDict[currColLabel],units=units),decimals=2)
                distMatrix[rowCtr,colCtr] = distance
                distMatrix[colCtr,rowCtr] = distance
                colCtr = colCtr + 1
    else:
        print('Error!  The distTypeFlag must be set to \'euclidean\' or \'haversine\' ')
        return(-1)
        
    return distMatrix
    
# End of CreateDistanceMatrix function        

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
#       ImprovementAnalysis
#
def ImprovementAnalysis(saveResultsPath, predictedTransLabels, transLabelsErrors, transLabelsTrue, custIDInput):
    incorrectTrans, incorrectPairedIndices, incorrectPairedIDs = CalcTransPredErrors(predictedTransLabels,transLabelsTrue,custIDInput,singleCustMarker=-999)
    incorrectTransOrg, incorrectPairedIndicesOrg, incorrectPairedIDsOrg = CalcTransPredErrors(transLabelsErrors,transLabelsTrue,custIDInput, singleCustMarker=-999)
    improvementNum = (len(incorrectTransOrg) - len(incorrectTrans))
    improvementPercent = np.round(((improvementNum  / len(incorrectTransOrg)) * 100),decimals=2)

    stats = {
        'Num of incorrect transformers before': len(incorrectTransOrg),
        'Num of incorrect transformers after': len(incorrectTrans),
        'Total transformer improvement': improvementNum,
        'Improvement percentage': improvementPercent
    }

    df = pd.DataFrame( [stats] )
    df.to_csv( Path(saveResultsPath, 'outputs_ImprovementStats.csv'), index=False)

# End improvementAnalysis function
