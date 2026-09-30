"""
Estimate distribution hosting-capacity expansion options
& visualize upgrade scenarios for additional DER adoption.
"""

# Python Imports
import shutil
import datetime
import json
import os
import pandas as pd
from pathlib import Path
import logging
import plotly.utils as pu
import plotly.graph_objects as go

# OMF imports
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *
from omf import weather
from omf.solvers import opendss
from omf.solvers import pysam
from omf.solvers import decaf_cl

# Model metadata
modelName, template = __neoMetaModel__.metadata(__file__)
hidden = False

def checkCircuitSolar(modelDir, inputDict: dict):
	'''
	Reviews any pvsystems or batteries in the circuit and sums up their kW values
	'''
	returningKW = 0
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	inputDict['feederName1'] = feederName[:-4]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	pvsystems = [x for x in tree if x.get('object', 'N/A').startswith('pvsystem.')]
	batteries = [x for x in tree if x.get('object', 'N/A').startswith('battery.')]
	if len(pvsystems) == 0 and len(batteries) == 0:
		return returningKW
	if len(pvsystems) != 0:
		kwFromPV = [x['kw'] for x in pvsystems if 'kw' in x]
		for item in kwFromPV:
			returningKW += float(item)
	if len(batteries) != 0:
		kwFromBattery = [x['kw'] for x in batteries if 'kw' in x]
		for item in kwFromBattery:
			returningKW += float(item)
	return returningKW


def processOptimalUpgrades(results: dict) -> dict:
	'''
	Turns the decaf.optimal_upgrades result dict into tables and a figure for the HTML template.
	'''
	outData = {}
	upgrades = results.get("upgrades", []) or []
	baseline = results.get("baseline_hc_mw")
	target = results.get("target_hc_mw")
	postUpgrade = results.get("post_upgrade_hc_mw")
	released = results.get("released_hc_mw")
	totalCost = results.get("total_cost_usd")
	runtime = results.get("runtime_sec")
	upgradeRequired = results.get("upgrade_required")
	targetAchieved = results.get("target_achieved")

	outData["optUpg_success"] = bool(results.get("success", False))
	outData["optUpg_failureReason"] = results.get("failure_reason") or ""
	outData["optUpg_upgradeRequired"] = bool(upgradeRequired)
	outData["optUpg_targetAchieved"] = bool(targetAchieved)

	outData["optUpg_summaryHeadings"] = [
		"Site (Bus)",
		"Baseline HC (MW)",
		"Target HC (MW)",
		"Post Upgrade HC (MW)",
		"HC Released (MW)",
		"Upgrade Required",
		"Target Achieved",
		"Number of Upgrades",
		"Total Upgrade Cost (USD)",
		"Runtime (sec)",
	]
	outData["optUpg_summaryValues"] = [[
		results.get("site_id", "N/A"),
		"N/A" if baseline is None else f"{baseline:,.3f}",
		"N/A" if target is None else f"{target:,.3f}",
		"N/A" if postUpgrade is None else f"{postUpgrade:,.3f}",
		"N/A" if released is None else f"{released:,.3f}",
		"N/A" if upgradeRequired is None else ("Yes" if upgradeRequired else "No"),
		"N/A" if targetAchieved is None else ("Yes" if targetAchieved else "No"),
		len(upgrades),
		"N/A" if totalCost is None else f"${totalCost:,.2f}",
		"N/A" if runtime is None else f"{runtime:,.1f}",
	]]

	# Ranked upgrade table, ordered by iteration
	upgrades = sorted(upgrades, key=lambda upgrade: upgrade.get("iteration", 0))
	outData["optUpg_upgradeHeadings"] = [
		"Rank", "Asset ID", "Asset Type", "Action", "Old Setting", "New Setting",
		"Cost (USD)", "HC Before (MW)", "HC After (MW)", "HC Gain (MW)", "kW Gained per $1k"
	]
	# The table is sorted by this column when the page loads. Clicking any header re sorts it.
	# 0 = Rank, 6 = Cost, 9 = HC Gain, 10 = kW Gained per $1k.
	outData["optUpg_defaultSortColumn"] = 0
	outData["optUpg_defaultSortDirection"] = "asc"
	outData["optUpg_defaultSortNote"] = "Rank is the order in which decaf selected the upgrades. Click any column header to sort by that column."
	upgradeRows = []
	# Unformatted copy of every cell so the table sorts on real numbers instead of display strings
	upgradeSortRows = []
	constraintRows = []
	for upgrade in upgrades:
		cost = upgrade.get("incremental_cost_usd")
		gain = upgrade.get("realized_hc_gain_mw")
		hcBefore = upgrade.get("hc_before_mw")
		hcAfter = upgrade.get("hc_after_mw")
		assetType = str(upgrade.get("asset_type", "N/A"))
		oldState = upgrade.get("old_state") or {}
		newState = upgrade.get("new_state") or {}
		newSettingText = ", ".join(f"{name}: {value}" for name, value in newState.items()) or "N/A"
		# The original network has no voltage regulator, so decaf's tap change is really an
		# installation. Show it that way rather than as a change to an existing tap setting.
		if assetType == "regulator":
			actionText = "Voltage Regulator Installation"
			oldSettingText = "No Regulator"
		else:
			actionText = str(upgrade.get("action_type", "N/A")).replace("_", " ").title()
			oldSettingText = ", ".join(f"{name}: {value}" for name, value in oldState.items()) or "N/A"
		if cost and gain is not None:
			gainPerKRaw = (gain * 1000) / (cost / 1000)
			gainPerK = f"{gainPerKRaw:,.2f}"
		else:
			gainPerKRaw = ""
			gainPerK = "N/A"
		upgradeRows.append([
			upgrade.get("iteration", "N/A"),
			upgrade.get("asset_id", "N/A"),
			assetType.replace("_", " ").title(),
			actionText,
			oldSettingText,
			newSettingText,
			"N/A" if cost is None else f"${cost:,.2f}",
			"N/A" if hcBefore is None else f"{hcBefore:,.3f}",
			"N/A" if hcAfter is None else f"{hcAfter:,.3f}",
			"N/A" if gain is None else f"{gain:,.3f}",
			gainPerK,
		])
		upgradeSortRows.append([
			upgrade.get("iteration", ""),
			str(upgrade.get("asset_id", "")),
			assetType,
			actionText,
			oldSettingText,
			newSettingText,
			"" if cost is None else cost,
			"" if hcBefore is None else hcBefore,
			"" if hcAfter is None else hcAfter,
			"" if gain is None else gain,
			gainPerKRaw,
		])
		for constraint in upgrade.get("binding_constraints_before", []) or []:
			constraintRows.append([
				upgrade.get("iteration", "N/A"),
				upgrade.get("asset_id", "N/A"),
				str(constraint.get("family", "N/A")).title(),
				constraint.get("hour", "N/A"),
				constraint.get("constraint", "N/A"),
			])
	outData["optUpg_upgradeValues"] = upgradeRows
	outData["optUpg_upgradeSortValues"] = upgradeSortRows

	# Binding constraints that the upgrades were chosen to relieve
	outData["optUpg_constraintHeadings"] = [
		"Rank", "Asset ID", "Constraint Family", "Hour", "Constraint"
	]
	outData["optUpg_constraintValues"] = constraintRows

	# Hosting capacity by upgrade step, with the target as a dashed line
	stepLabels = ["Baseline"]
	stepValues = [baseline if baseline is not None else 0]
	for upgrade in upgrades:
		stepLabels.append(f"After #{upgrade.get('iteration', '')} {upgrade.get('asset_id', '')}")
		stepValues.append(upgrade.get("hc_after_mw", 0) or 0)
	# Baseline is the dark green bar. Every bar after an upgrade is the lighter green.
	hcFigure = go.Figure()
	hcFigure.add_trace(go.Bar(
		x=stepLabels,
		y=[stepValues[0]] + [None] * (len(stepValues) - 1),
		name="Baseline (MW)",
		marker=dict(color="#006400"),
		text=[f"{stepValues[0]:.3f}"] + [""] * (len(stepValues) - 1),
		textposition="outside"
	))
	if len(stepValues) > 1:
		hcFigure.add_trace(go.Bar(
			x=stepLabels,
			y=[None] + stepValues[1:],
			name="After Upgrade (MW)",
			marker=dict(color="#66BB6A"),
			text=[""] + [f"{value:.3f}" for value in stepValues[1:]],
			textposition="outside"
		))
	if target is not None:
		hcFigure.add_trace(go.Scatter(
			x=stepLabels,
			y=[target] * len(stepLabels),
			name="Target (MW)",
			mode="lines+markers" if len(stepLabels) == 1 else "lines",
			line=dict(color="red", width=2, dash="dash")
		))
	yMax = max(stepValues + ([target] if target is not None else []))
	hcFigure.update_layout(
		barmode="overlay",
		xaxis_title=None,
		yaxis_title="Hosting Capacity (MW)",
		yaxis=dict(range=[0, yMax * 1.15 if yMax > 0 else 1]),
		legend={
			"orientation": "h",
			"yanchor": "bottom",
			"y": 1.02,
			"xanchor": "right",
			"x": 1
		}
	)
	outData["optUpg_hcFigure"] = json.dumps(hcFigure, cls=pu.PlotlyJSONEncoder)
	return outData


def work(modelDir, inputDict: dict) -> dict:
	''' Run the model in its directory. '''
	# Delete output file every run if it exists
	outData = {}
	# Model operations goes here.
	lat = float( inputDict['latitude'] )
	long = float( inputDict['longitude'] )
	year = int( inputDict['year'] )
	sys_design = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes = ['dni,dhi,ghi,wind_speed,air_temperature']
	nrlAPIResponse = weather.nlr_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_aggregated_data.csv"))
	requestSuccess = True if nrlAPIResponse.status_code == 200 else False
	if requestSuccess:
		pvwatts_model, pvwatts_data = pysam.run_pvwatts(
			modelDir=modelDir,
			sys_design=sys_design,
			dataFile="output_aggregated_data.csv"
		)
	else:
		raise Exception("hostingExpansion.py: API request 1 Failed")
	# For Max Solar - Set tilt = latitude
	inputDict['tilt'] = lat
	sys_design_max = pysam._pysam_sysDesignSetup(inputDict, lat, long)
	attributes_clearsky = ['clearsky_dhi', 'clearsky_dni', 'clearsky_ghi']
	nrlAPIResponse_clearsky = weather.nlr_get_nsrdb_data(data_set="goes_aggregated", longitude=long, latitude=lat, year=year, api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes_clearsky, filename=Path(modelDir,"output_aggregated_clearsky_data.csv"))
	requestSuccess = True if nrlAPIResponse_clearsky.status_code == 200 else False
	if requestSuccess:
		maxSolar_model, maxSolar_data = pysam.run_pvwatts_historical_max(modelDir=modelDir, sys_design=sys_design_max, dataFile="output_aggregated_clearsky_data.csv")
	else:
		raise Exception("hostingExpansion.py: API request 2 Failed")
	amiData = pd.read_csv( Path(modelDir, inputDict["AmiDataFileName"]) )
	# Determine the length of available data (use load data length, should be max 1 year)
	data_length = len(amiData)
	# Slice solar data to match load data length
	pvwatts_data_sliced = pvwatts_data.iloc[:data_length]
	maxSolar_data_sliced = maxSolar_data.iloc[:data_length]
	# Get existing storage capacity on circuit
	storage_output = checkCircuitSolar(modelDir, inputDict)
	full_df = pd.DataFrame({
			'hour': pvwatts_data_sliced.index,
			'total_load': amiData.iloc[:, 1:].sum(axis=1)*1000,  # Convert kW to W
			'pysam_ac_watts': pvwatts_data_sliced['ac'].values,
			'storage_output_w': storage_output * 1000,  # Convert kW to W
			'dc_nameplate_w': float(inputDict["systemCapacity"])*1000,  # kW to W
			'max_solar_ac_watts': maxSolar_data_sliced['ac'].values
	})
	full_df.to_csv(Path(modelDir, "output_LoadvsPySAM.csv"), index=False)
	scatterFigure = go.Figure()
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['storage_output_w'],
		name='Storage Output (W)',
		fill='tozeroy',
		fillcolor='rgba(0, 200, 0, 0.3)',
		line=dict(color='darkgreen', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['pysam_ac_watts'] + full_df['storage_output_w'],
		name='Solar Output (W)',
		line=dict(color='darkgreen', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['total_load'],
		name='Total Load (W)',
		line=dict(color='blue', width=2),
		mode='lines'
	))
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['dc_nameplate_w'],
		name='DC Nameplate Capacity (W)',
		line=dict(color='red', width=2, dash='dash'),
		mode='lines'
	))
	# Add max solar output
	scatterFigure.add_trace(go.Scatter(
		x=full_df['hour'],
		y=full_df['max_solar_ac_watts'] + full_df['storage_output_w'],
		name='Max Solar Output (W)',
		line=dict(color='darkgreen', width=2, dash='dash'),
		mode='lines'
	))
	scatterFigure.update_layout(
	title=None,
		xaxis_title=None,
		yaxis_title=None,
		hovermode='x unified',
		legend={
			"orientation": "h",
			"yanchor": "bottom",
			"y": 1.02,
			"xanchor": "right",
			"x": 1
		}
	)
	outData['scatterFigure'] = json.dumps( scatterFigure, cls=pu.PlotlyJSONEncoder )
	feederName = [x for x in os.listdir(modelDir) if x.endswith('.omd')][0]
	pathToOmd = Path(modelDir, feederName)
	tree = opendss.dssConvert.omdToTree(pathToOmd)
	opendss.dssConvert.treeToDss(tree, Path(modelDir, 'circuit.dss'))

	#TODO: Check if the site_id is an actual bus in the circuit before we call optimal_upgrades
	site_id = inputDict.get("siteID")
	target_hc_mw = float(inputDict.get("targetHCMW"))
	optimalUpgradesResults = decaf_cl.ia_toplevel.optimal_upgrades(site_id=site_id, target_hc_mw=target_hc_mw)
	optiUpgradesFile = Path(modelDir, 'output_optiUpgrResults.json')
	with open(optiUpgradesFile, 'w') as fp:
		json.dump(optimalUpgradesResults, fp)

	outData.update( processOptimalUpgrades( json.load(open(optiUpgradesFile)) ) )

	# Stdout/stderr.
	outData["stdout"] = "Success"
	outData["stderr"] = ""
	return outData


def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	amiFileName = "input_mackelroy.csv"
	amiFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', amiFileName)
	ScadaFileName = "input_ScadaData.csv"
	ScadaFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', ScadaFileName)
	derPipelineFileName = "input_derPipelineData.csv"
	derPipelineFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', derPipelineFileName)
	newInterconnFileName = "input_newInterconnData.csv"
	newInterconnFilePath = Path(omf.omfDir,'static','testFiles', 'hostingExpansion', newInterconnFileName)

	defaultInputs = {
		"user": "admin",
		"modelType": modelName,
		"created": str(datetime.datetime.now()),
		"feederName1": 'iowa240.clean.dss',
		"AmiUIDisplay": amiFileName,
		"AmiDataFileName": amiFileName,
		"ScadaUIDisplay": ScadaFileName,
		"ScadaDataFileName": ScadaFileName,
		"derPipelineUIDisplay": derPipelineFileName,
		"derPipelineDataFileName": derPipelineFileName,
		"newInterconnUIDisplay": newInterconnFileName,
		"newInterconnDataFileName": newInterconnFileName,
		"longitude": "-94.67",
		"latitude": "39.10",
		"year": "2024",
		"azimuth": "180.0",
		"systemCapacity": 800,
		"tilt": 45,
		"losses": 15.5,
		"siteID": "bus3131",
		"targetHCMW": 1.20
	}

	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	# Copy files from the test directory ( or respective places ) and put them in the model for use
	try:
		shutil.copyfile(
			Path(__neoMetaModel__._omfDir, "static", "publicFeeders", defaultInputs["feederName1"]+'.omd'),
			Path(modelDir, defaultInputs["feederName1"]+'.omd'))
		shutil.copyfile( amiFilePath, Path(modelDir, amiFileName) )
		shutil.copyfile( ScadaFilePath, Path(modelDir, ScadaFileName) )
		shutil.copyfile( derPipelineFilePath, Path(modelDir, derPipelineFileName))
		shutil.copyfile( newInterconnFilePath, Path(modelDir, newInterconnFileName))
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _tests():
	# Location
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = Path(__neoMetaModel__._omfDir, "data", "Model", "admin", "Automated Testing of " + modelName)
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
