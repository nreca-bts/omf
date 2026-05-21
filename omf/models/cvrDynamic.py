"""
The cvrDynamic model calculates the expected costs and benefits for implementing
conservation voltage reduction on a given feeder circuit. Compared to the cvrStatic
model, which gives output at one point in time, the dynamic model gives output over a
period of time.
"""

import json, os, shutil, math, calendar
from datetime import datetime as dt, timedelta
from os.path import join as pJoin
from matplotlib import pyplot as plt
# OMF feeder
from omf import feeder
from omf.solvers import gridlabd
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
tooltip = 'The cvrDynamic model calculates the expected costs and benefits for implementing conservation voltage reduction on a given feeder circuit.'
modelName, template = __neoMetaModel__.metadata(__file__)

def work(modelDir,inputDict):
	'''This reads a glm file, changes the method of powerflow and reruns'''
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0][:-4]
	inputDict['feederName1'] = feederName
	feederPath = pJoin(modelDir,feederName+'.omd')
	# Reads a pre-calibrated feeder.
	outData = {}
	with open(feederPath, 'r') as jsonIn:
		feederJson = json.load(jsonIn)
		localTree = feederJson.get('tree', {})
		attachments = feederJson.get('attachments', {})
	for key in localTree:
		if 'solver_method' in localTree[key].keys():
			localTree[key]['solver_method'] = 'FBS'
	#find the swing bus and recorder attached to substation
	try:
		for key in localTree:
			if localTree[key].get('bustype','').lower() == 'swing':
				swingIndex = key
				swingName = localTree[key].get('name')
			if localTree[key].get('object','') == 'regulator' and localTree[key].get('from','') == swingName:
				regIndex = key
				regConfName = localTree[key]['configuration']
	except: raise ValueError('Invalid feeder selected:', str(inputDict['feederName1']))
	#find the regulator and capacitor names and combine to form a string for volt-var control object
	regKeys = []
	accum_reg = ''
	for key in localTree:
		if localTree[key].get('object','') == 'regulator':
			accum_reg += localTree[key].get('name','ERROR') + ','
			regKeys.append(key)
	regstr = accum_reg[:-1]
	capKeys = []
	accum_cap = ''
	for key in localTree:
		if localTree[key].get('object','') == 'capacitor':
			accum_cap += localTree[key].get('name','ERROR') + ','
			capKeys.append(key)
			if localTree[key].get('control','').lower() == 'manual':
				localTree[key]['control'] = 'VOLT'
	capstr = accum_cap[:-1]
	# Attach recorders relevant to CVR.
	recorders = [
			{'object': 'collector',
			'file': 'ZlossesTransformer.csv',
			'group': 'class=transformer',
			'limit': '0',
			'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
			{'object': 'collector',
			'file': 'ZlossesUnderground.csv',
			'group': 'class=underground_line',
			'limit': '0',
			'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
			{'object': 'collector',
			'file': 'ZlossesOverhead.csv',
			'group': 'class=overhead_line',
			'limit': '0',
			'property': 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'},
			{'object': 'recorder',
			'file': 'Zregulator.csv',
			'limit': '0',
			'parent': localTree[regIndex]['name'],
			'property': 'tap_A,tap_B,tap_C,power_in.real,power_in.imag'},
			{'object': 'collector',
			'file': 'ZvoltageJiggle.csv',
			'group': 'class=triplex_meter',
			'limit': '0',
			'property': 'min(voltage_12.mag),mean(voltage_12.mag),max(voltage_12.mag),std(voltage_12.mag)'},
			{'object': 'recorder',
			'file': 'ZsubstationTop.csv',
			'limit': '0',
			'parent': localTree[swingIndex]['name'],
			'property': 'voltage_A,voltage_B,voltage_C'},
			{'object': 'recorder',
			'file': 'ZsubstationBottom.csv',
			'limit': '0',
			'parent': localTree[regIndex]['to'],
			'property': 'voltage_A,voltage_B,voltage_C'}]
	#recorder object for capacitor switching - if capacitors exist
	if capKeys != []:
		for key in capKeys:
			recorders.append({'object': 'recorder',
			'file': 'ZcapSwitch' + str(key) + '.csv',
			'limit': '0',
			'parent': localTree[key]['name'],
			'property': 'switchA,switchB,switchC'})
	#attach recorder process
	biggest = 1 + max([int(k) for k in localTree.keys()])
	for index, rec in enumerate(recorders):
		localTree[biggest + index] = rec
	#run a reference load flow
	HOURS = float(inputDict['simLengthHours'])
	simStartDate = inputDict['simStart']
	feeder.adjustTime(localTree,HOURS,'hours',simStartDate)
	output = gridlabd.runInFilesystem(localTree, attachments, keepFiles=False,workDir=modelDir)
	try: os.remove(pJoin(modelDir,'PID.txt'))
	except: pass
	p = output['Zregulator.csv']['power_in.real']
	q = output['Zregulator.csv']['power_in.imag']
	#calculating length of simulation because it migth be different from the simulation input HOURS
	simRealLength = int(len(p))
	#time delays from configuration files
	time_delay_reg = '30.0'
	time_delay_cap = '300.0'
	for key in localTree:
		if localTree[key].get('object','') == 'regulator_configuration':
			time_delay_reg = localTree[key]['time_delay']
		# if localTree[key].get('object','') == "capacitor":
		# 	time_delay_cap = localTree[key]['time_delay']
	#change the recorder names
	for key in localTree:
		if localTree[key].get('object','') == 'collector' or localTree[key].get('object','') == 'recorder':
			if localTree[key].get('file','').startswith('Z'):
				localTree[key]['file'] = localTree[key].get('file','').replace('Z','NewZ')
	#create volt-var control object
	max_key = max([int(key) for key in localTree.keys()])
	localTree[max_key+1] = {'object' : 'volt_var_control',
		'name' : 'IVVC1',
		'control_method' : 'ACTIVE',
		'capacitor_delay' : str(time_delay_cap),
		'regulator_delay' : str(time_delay_reg),
		'desired_pf' : '0.99',
		'd_max' : '0.6',
		'd_min' : '0.1',
		'substation_link' : str(localTree[regIndex]['name']),
		'regulator_list' : regstr,
		'capacitor_list': capstr,
		'voltage_measurements': str(inputDict.get('voltageNodes', 'IVVC1')),
	}
	#running powerflow analysis via gridalab after attaching a regulator
	feeder.adjustTime(localTree,HOURS,'hours',simStartDate)
	output1 = gridlabd.runInFilesystem(localTree,attachments,keepFiles=True,workDir=modelDir)
	os.remove(pJoin(modelDir,'PID.txt'))
	pnew = output1['NewZregulator.csv']['power_in.real']
	qnew = output1['NewZregulator.csv']['power_in.imag']
	#total real and imaginary losses as a function of time
	def vecSum(u,v):
		''' Add vectors u and v element-wise. Return has len <= len(u) and <=len(v). '''
		return list(map(sum, zip(u,v)))
	def zeroVec(length):
		''' Give a zero vector of input length. '''
		return [0 for x in range(length)]
	(realLoss, imagLoss, realLossnew, imagLossnew) = (zeroVec(int(HOURS)) for x in range(4))
	for device in ['ZlossesOverhead.csv','ZlossesTransformer.csv','ZlossesUnderground.csv']:
		for letter in ['A','B','C']:
			realLoss = vecSum(realLoss, output[device]['sum(power_losses_' + letter + '.real)'])
			imagLoss = vecSum(imagLoss, output[device]['sum(power_losses_' + letter + '.imag)'])
			realLossnew = vecSum(realLossnew, output1['New'+device]['sum(power_losses_' + letter + '.real)'])
			imagLossnew = vecSum(imagLossnew, output1['New'+device]['sum(power_losses_' + letter + '.imag)'])
	#voltage calculations and tap calculations
	def divby2(u):
		'''divides by 2'''
		return u/2
	lowVoltage = []
	meanVoltage = []
	highVoltage = []
	lowVoltagenew = []
	meanVoltagenew = []
	highVoltagenew = []
	tap = {'A':[],'B':[],'C':[]}
	tapnew = {'A':[],'B':[],'C':[]}
	volt = {'A':[],'B':[],'C':[]}
	voltnew = {'A':[],'B':[],'C':[]}
	switch = {'A':[],'B':[],'C':[]}
	switchnew = {'A':[],'B':[],'C':[]}
	for letter in ['A','B','C']:
		tap[letter] = output['Zregulator.csv']['tap_' + letter]
		tapnew[letter] = output1['NewZregulator.csv']['tap_' + letter]
		if capKeys != []:
			switch[letter] = output['ZcapSwitch' + str(int(capKeys[0])) + '.csv']['switch'+ letter]
			switchnew[letter] = output1['NewZcapSwitch' + str(int(capKeys[0])) + '.csv']['switch'+ letter]
		volt[letter] = list(map(returnMag,output['ZsubstationBottom.csv']['voltage_'+letter]))
		voltnew[letter] = list(map(returnMag,output1['NewZsubstationBottom.csv']['voltage_'+letter]))
	lowVoltage = list(map(divby2,output['ZvoltageJiggle.csv']['min(voltage_12.mag)']))
	lowVoltagenew = list(map(divby2,output1['NewZvoltageJiggle.csv']['min(voltage_12.mag)']))
	meanVoltage = list(map(divby2,output['ZvoltageJiggle.csv']['mean(voltage_12.mag)']))
	meanVoltagenew = list(map(divby2,output1['NewZvoltageJiggle.csv']['mean(voltage_12.mag)']))
	highVoltage = list(map(divby2,output['ZvoltageJiggle.csv']['max(voltage_12.mag)']))
	highVoltagenew = list(map(divby2,output1['NewZvoltageJiggle.csv']['max(voltage_12.mag)']))
	#energy calculations
	whEnergy = []
	whLosses = []
	whLoads = []
	whEnergy.append(sum(p)/10**6)
	whLosses.append(sum(realLoss)/10**6)
	whLoads.append((sum(p)-sum(realLoss))/10**6)
	whEnergy.append(sum(pnew)/10**6)
	whLosses.append(sum(realLossnew)/10**6)
	whLoads.append((sum(pnew)-sum(realLossnew))/10**6)
	indices = ['No IVVC', 'With IVVC']
	# energySalesRed = (whLoads[1]-whLoads[0])*(inputDict['wholesaleEnergyCostPerKwh'])*1000
	# lossSav = (whLosses[0]-whLosses[1])*inputDict['wholesaleEnergyCostPerKwh']*1000
	#plots
	ticks = []
	plt.clf()
	plt.title('total energy')
	plt.ylabel('total load and losses (MWh)')
	for element in range(2):
		ticks.append(element)
		bar_loss = plt.bar(element, whLosses[element], 0.15, color= 'red')
		bar_load = plt.bar(element+0.15, whLoads[element], 0.15, color= 'orange')
	plt.legend([bar_load[0],bar_loss[0]],['total load', 'total losses'],bbox_to_anchor=(0., 0.915, 1., .102), loc=3,
			   ncol=2, mode='expand', borderaxespad=0.1)
	plt.xticks([t+0.15 for t in ticks],indices)
	plt.savefig(pJoin(modelDir,'totalEnergy.png'))
	#real and imaginary power
	plt.figure('real power')
	plt.title('Real Power at substation')
	plt.ylabel('substation real power (MW)')
	pMW = [element/10**6 for element in p]
	pMWn = [element/10**6 for element in pnew]
	pw = plt.plot(pMW)
	npw = plt.plot(pMWn)
	plt.legend([pw[0], npw[0]], ['NO IVVC','WITH IVVC'],bbox_to_anchor=(0., 0.915, 1., .102), loc=3,
		ncol=2, mode='expand', borderaxespad=0.1)
	plt.savefig(pJoin(modelDir,'realPower.png'))
	plt.figure('Reactive power')
	plt.title('Reactive Power at substation')
	plt.ylabel('substation reactive power (MVAR)')
	qMVAR = [element/10**6 for element in q]
	qMVARn = [element/10**6 for element in qnew]
	iw = plt.plot(qMVAR)
	niw = plt.plot(qMVARn)
	plt.legend([iw[0], niw[0]], ['NO IVVC','WITH IVVC'],bbox_to_anchor=(0., 0.915, 1., .102), loc=3,
		ncol=2, mode='expand', borderaxespad=0.1)
	plt.savefig(pJoin(modelDir,'imaginaryPower.png'))
	#voltage plots
	plt.figure('voltages as a function of time')
	f,ax = plt.subplots(2,sharex=True)
	f.suptitle('Min and Max voltages on the feeder')
	lv = ax[0].plot(lowVoltage,color = 'cadetblue')
	mv = ax[0].plot(meanVoltage,color = 'blue')
	hv = ax[0].plot(highVoltage, color = 'cadetblue')
	ax[0].legend([lv[0], mv[0], hv[0]], ['low voltage','mean voltage','high voltage'],bbox_to_anchor=(0., 0.915, 1., .1), loc=3,
		ncol=3, mode='expand', borderaxespad=0.1)
	ax[0].set_ylabel('NO IVVC')
	nlv = ax[1].plot(lowVoltagenew,color = 'cadetblue')
	nmv = ax[1].plot(meanVoltagenew,color = 'blue')
	nhv = ax[1].plot(highVoltagenew, color = 'cadetblue')
	ax[1].set_ylabel('WITH IVVC')
	plt.savefig(pJoin(modelDir,'Voltages.png'))
	#tap positions
	plt.figure('TAP positions NO IVVC')
	f,ax = plt.subplots(6,sharex=True)
	f.set_size_inches(10,12.0)
	#f.suptitle("Regulator Tap positions")
	ax[0].plot(tap['A'])
	ax[0].set_title('Regulator Tap positions NO IVVC')
	ax[0].set_ylabel('TAP A')
	ax[1].plot(tap['B'])
	ax[1].set_ylabel('TAP B')
	ax[2].plot(tap['C'])
	ax[2].set_ylabel('TAP C')
	ax[3].plot(tapnew['A'])
	ax[3].set_title('WITH IVVC')
	ax[3].set_ylabel('TAP A')
	ax[4].plot(tapnew['B'])
	ax[4].set_ylabel('TAP B')
	ax[5].plot(tapnew['C'])
	ax[5].set_ylabel('TAP C')
	for subplot in range(6):
		ax[subplot].set_ylim(-20,20)
	f.tight_layout()
	plt.savefig(pJoin(modelDir,'RegulatorTAPpositions.png'))
	#substation voltages
	plt.figure('substation voltage as a function of time')
	f,ax = plt.subplots(6,sharex=True)
	f.set_size_inches(10,12.0)
	#f.suptitle("voltages at substation NO IVVC")
	ax[0].plot(volt['A'])
	ax[0].set_title('Substation voltages NO IVVC')
	ax[0].set_ylabel('voltage A')
	ax[1].plot(volt['B'])
	ax[1].set_ylabel('voltage B')
	ax[2].plot(volt['C'])
	ax[2].set_ylabel('voltage C')
	ax[3].plot(voltnew['A'])
	ax[3].set_title('WITH IVVC')
	ax[3].set_ylabel('voltage A')
	ax[4].plot(voltnew['B'])
	ax[4].set_ylabel('voltage B')
	ax[5].plot(voltnew['C'])
	ax[5].set_ylabel('voltage C')
	f.tight_layout()
	plt.savefig(pJoin(modelDir,'substationVoltages.png'))
	#cap switches
	plt.figure('capacitor switch state as a function of time')
	f,ax = plt.subplots(6,sharex=True)
	f.set_size_inches(10,12.0)
	#f.suptitle("Capacitor switch state NO IVVC")
	ax[0].plot(switch['A'])
	ax[0].set_title('Capacitor switch state NO IVVC')
	ax[0].set_ylabel('switch A')
	ax[1].plot(switch['B'])
	ax[1].set_ylabel('switch B')
	ax[2].plot(switch['C'])
	ax[2].set_ylabel('switch C')
	ax[3].plot(switchnew['A'])
	ax[3].set_title('WITH IVVC')
	ax[3].set_ylabel('switch A')
	ax[4].plot(switchnew['B'])
	ax[4].set_ylabel('switch B')
	ax[5].plot(switchnew['C'])
	ax[5].set_ylabel('switch C')
	for subplot in range(6):
		ax[subplot].set_ylim(-2,2)
	f.tight_layout()
	plt.savefig(pJoin(modelDir,'capacitorSwitch.png'))
	#plt.show()
	#monetization
	monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
		'September', 'October', 'November', 'December']
	monthToSeason = {'January':'Winter','February':'Winter','March':'Spring','April':'Spring',
		'May':'Spring','June':'Summer','July':'Summer','August':'Summer',
		'September':'Fall','October':'Fall','November':'Fall','December':'Winter'}
	#calculate the month and hour of simulation start and month and hour of simulation end
	simStartTimestamp = simStartDate + ' 00:00:00'
	simFormattedDate = dt.strptime(simStartTimestamp,'%Y-%m-%d %H:%M:%S')
	simStartMonthNum = int(simFormattedDate.strftime('%m'))
	simstartMonth = monthNames[simStartMonthNum-1]
	simStartDay = int(simFormattedDate.strftime('%d'))
	if calendar.isleap(int(simFormattedDate.strftime('%Y'))):
		febDays = 29
	else:
		febDays = 28
	monthHours = [int(31*24),int(febDays*24),int(31*24),int(30*24),int(31*24),int(30*24),int(31*24),int(31*24),int(30*24),int(31*24),int(30*24),int(31*24)]
	simStartIndex = int(sum(monthHours[:(simStartMonthNum-1)])+(simStartDay-1)*24)
	temp = 0
	cumulHours = [0]
	for x in range(12):
		temp += monthHours[x]
		cumulHours.append(temp)
	for i in range((simStartMonthNum),13):
		if int(simStartIndex+simRealLength)<=cumulHours[i] and int(simStartIndex+simRealLength)>cumulHours[i-1]:
			simEndMonthNum = i-1
			simEndMonth = monthNames[simEndMonthNum]
	#calculate peaks for the number of months in simulation
	previndex = 0
	monthPeak = {}
	monthPeakNew = {}
	peakSaveDollars = {}
	energyLostDollars = {}
	lossRedDollars = {}
	simMonthList = monthNames[monthNames.index(simstartMonth):(monthNames.index(simEndMonth)+1)]
	for monthElement in simMonthList:
		month = monthNames.index(monthElement)
		index1 = int(previndex)
		index2 = int(min((index1 + int(monthHours[month])), simRealLength))
		monthPeak[monthElement] = max(p[index1:index2])/1000.0
		monthPeakNew[monthElement] = max(pnew[index1:index2])/1000.0
		peakSaveDollars[monthElement] = (monthPeak[monthElement]-monthPeakNew[monthElement])*float(inputDict['peakDemandCost'+str(monthToSeason[monthElement])+'PerKw'])
		lossRedDollars[monthElement] = (sum(realLoss[index1:index2])/1000.0 - sum(realLossnew[index1:index2])/1000.0)*(float(inputDict['wholesaleEnergyCostPerKwh']))
		energyLostDollars[monthElement] = (sum(p[index1:index2])/1000.0  - sum(pnew[index1:index2])/1000.0  - sum(realLoss[index1:index2])/1000.0
			+ sum(realLossnew[index1:index2])/1000.0 )*(float(inputDict['wholesaleEnergyCostPerKwh']) - float(inputDict['retailEnergyCostPerKwh']))
		previndex = index2
	#money charts
	fig = plt.figure('cost benefit barchart',figsize=(10,8))
	ticks = list(range(len(simMonthList)))
	ticks1 = [element+0.15 for element in ticks]
	ticks2 = [element+0.30 for element in ticks]
	eld = [energyLostDollars[month] for month in simMonthList]
	lrd = [lossRedDollars[month] for month in simMonthList]
	psd = [peakSaveDollars[month] for month in simMonthList]
	bar_eld = plt.bar(ticks,eld,0.15,color='red')
	bar_psd = plt.bar(ticks1,psd,0.15,color='blue')
	bar_lrd = plt.bar(ticks2,lrd,0.15,color='green')
	plt.legend([bar_eld[0], bar_psd[0], bar_lrd[0]], ['energyLostDollars','peakReductionDollars','lossReductionDollars'],bbox_to_anchor=(0., 1.015, 1., .102), loc=3,
		ncol=2, mode='expand', borderaxespad=0.1)
	monShort = [element[0:3] for element in simMonthList]
	plt.xticks([t+0.15 for t in ticks],monShort)
	plt.ylabel('Utility Savings ($)')
	plt.savefig(pJoin(modelDir,'spendChart.png'))
	#cumulative savings graphs
	fig = plt.figure('cost benefit barchart',figsize=(10,5))
	annualSavings = sum(eld) + sum(lrd) + sum(psd)
	annualSave = lambda x:(annualSavings - float(inputDict['omCost'])) * x - float(inputDict['capitalCost'])
	simplePayback = float(inputDict['capitalCost'])/(annualSavings - float(inputDict['omCost']))
	plt.xlabel('Year After Installation')
	plt.xlim(0,30)
	plt.ylabel('Cumulative Savings ($)')
	plt.plot([0 for x in range(31)],c='gray')
	plt.axvline(x=simplePayback, ymin=0, ymax=1, c='gray', linestyle='--')
	plt.plot([annualSave(x) for x in range(31)], c='green')
	plt.savefig(pJoin(modelDir,'savingsChart.png'))
	#get exact time stamps from the CSV files generated by Gridlab-D
	timeWithZone =  output['Zregulator.csv']['# timestamp']
	timestamps = [element[:19] for element in timeWithZone]
	#data for highcharts
	outData['timeStamps'] = timestamps
	outData['noCVRPower'] = p
	outData['withCVRPower'] = pnew
	outData['noCVRLoad'] = whLoads[0]
	outData['withCVRLoad'] = whLoads[1]
	outData['noCVRLosses'] = whLosses[0]
	outData['withCVRLosses'] = whLosses[1]
	outData['noCVRTaps'] = tap
	outData['withCVRTaps'] = tapnew
	outData['noCVRSubVolts'] = volt
	outData['withCVRSubVolts'] = voltnew
	outData['noCVRCapSwitch'] = switch
	outData['withCVRCapSwitch'] = switchnew
	outData['noCVRHighVolt'] = highVoltage
	outData['withCVRHighVolt'] = highVoltagenew
	outData['noCVRLowVolt'] = lowVoltage
	outData['withCVRLowVolt'] = lowVoltagenew
	outData['noCVRMeanVolt'] = meanVoltage
	outData['withCVRMeanVolt'] = meanVoltagenew
	#monetization
	outData['simMonthList'] = monShort
	outData['energyLostDollars'] = energyLostDollars
	outData['lossRedDollars'] = lossRedDollars
	outData['peakSaveDollars'] = peakSaveDollars
	outData['annualSave'] = [annualSave(x) for x in range(31)]
	# Generate warnings
	#TODO: Timezone adjustment
	try:
		# Check if times for simulation and scada match.
		scadaDates = []
		with open(pJoin(modelDir,'subScadaCalibrated1.player'),'r') as scadaFile:
			for line in scadaFile:
				(date,val) = line.split(',')
				scadaDates.append(str(date))
		simFormattedEndDate = simFormattedDate + timedelta(hours=HOURS)
		scadaStartDate = dt.strptime(scadaDates[0].split(' PST')[0],"%Y-%m-%d %H:%M:%S")
		scadaEndDate = dt.strptime(scadaDates[len(scadaDates)-1].split(' PST')[0],"%Y-%m-%d %H:%M:%S")
		beginRange = (scadaStartDate - simFormattedDate).total_seconds()
		endRange = (scadaEndDate - simFormattedEndDate).total_seconds()
		# Check if houses exist.
		housesExist, voltageNodeExists = False, False
		for key in localTree:
			if localTree[key].get('object','') == 'house': housesExist = True
			if localTree[key].get('name','') == str(inputDict.get('voltageNodes', 0)): voltageNodeExists = True
		if (beginRange > 0.0 or endRange < 0.0) and not housesExist:
			outData['warnings'] = '<strong>WARNING:</strong> The simulation dates entered are not compatible with the scada curve in the feeder.'
		# Check if voltage node exists.
		if not voltageNodeExists:
			if outData.get('warnings','') != '':
				previousWarning = outData['warnings']
				outData['warnings'] = previousWarning + ' The voltage node: ' + str(inputDict.get('voltageNodes', 0)) + ' does not exist in the feeder.'
			else: outData['warnings'] = '<strong>WARNING:</strong> The voltage node <i>' + str(inputDict.get('voltageNodes', 0)) + '</i> does not exist in the feeder.'
	except:
		pass
	# # Update the runTime in the input file.
	# endTime = dt.now()
	# with open(pJoin(modelDir,"allInputData.json"),"w") as inFile:
	# 	json.dump(inputDict, inFile, indent=4)
	# with open(pJoin(modelDir,"outDataData.json"),"w") as outFile:
	# 	json.dump(outData, outFile, indent=4)
	# # For autotest, there won't be such file.
	# try:
	# 	os.remove(pJoin(modelDir, "PPID.txt"))
	# except Exception, e:
	# 	pass
	return outData

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		'modelType': modelName,
		'user': 'admin',
		'feederName1': 'ABEC Frank pre calib',
		'runTime': '',
		'capitalCost': 30000,
		'omCost': 1000,
		'wholesaleEnergyCostPerKwh': 0.06,
		'retailEnergyCostPerKwh': 0.10,
		'peakDemandCostSpringPerKw': 5.0,
		'peakDemandCostSummerPerKw': 10.0,
		'peakDemandCostFallPerKw': 6.0,
		'peakDemandCostWinterPerKw': 8.0,
		'simStart': '2011-01-01',
		'simLengthHours': 100}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, 'static', 'publicFeeders', defaultInputs['feederName1']+'.omd'), pJoin(modelDir, defaultInputs['feederName1']+'.omd'))
	except:
		return False
	return creationCode

def returnMag(complexStr):
	''' real and imaginary parts of a complex number and returns magnitude
	handles string if the string starts with a '+' or a '-'
	handles negative or positive, real and imaginary parts'''
	if complexStr[0] == '+' or complexStr[0] == '-':
		complexStr1 = complexStr[1:len(complexStr)+1]
		sign = complexStr[0] + '1'
	else:
		complexStr1 = complexStr
		sign = 1
	if complexStr1.find('+')>0:
		real = float(complexStr1[0:complexStr1.find('+')])*float(sign)
		imag = float(complexStr1[complexStr1.find('+')+1:-1])
	else:
		if complexStr1.find('-')>0:
			real = float(complexStr1[0:complexStr1.find('-')])*float(sign)
			imag = float(complexStr1[complexStr1.find('-')+1:-1])*-1
		else:
			if complexStr1.find('j')>0:
				real = 0.0
				imag = float(complexStr1[0:complexStr1.find('j')])*float(sign)
			else:
				real = float(complexStr1)*float(sign)
				imag = 0.0
	return (math.sqrt(real**2+imag**2))/60.0

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,'data','Model','admin','Automated Testing of ' + modelName)
	# Blow away old test results if necessary.
	try:
		shutil.rmtree(modelLoc)
	except:
		# No previous test results.
		pass
	# Create New.
	new(modelLoc)
	# Pre-run.
	__neoMetaModel__.renderAndShow(modelLoc)
	# Run the model.
	__neoMetaModel__.runForeground(modelLoc)
	# Show the output.
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
