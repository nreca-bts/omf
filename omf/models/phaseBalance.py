"""
The phaseBalance tool will allow co-ops to better evaluate and simulate the consequences
of implementing distributed Steinmetz control methods to their specific feeder. The tool
will enable its users not only to see how distributed generation impacts their feeder
overall, but also the financial consequences of the implementation.
"""

import json, os, shutil, math, base64
from os.path import join as pJoin
import numpy as np
import pandas as pd

# OMF imports 
from omf import feeder
from omf.models import voltageDrop
from omf.solvers import SteinmetzController
from omf.models import __neoMetaModel__
from omf.models.__neoMetaModel__ import *

# Model metadata:
modelName, template = __neoMetaModel__.metadata(__file__)
tooltip = "Calculate phase unbalance and determine mitigation options."
# hidden = True

def get_loss_items(tree):
	"""
	Return the loss items needed by this workflow.
	"""
	s = set()
	for i, d in tree.items():
		s.add(d.get('object', ''))
	return [l for l in ['transformer', 'underground_line', 'overhead_line', 'triplex_line'] if any([l in x for x in s])]

def motor_efficiency(x):
	"""
	Perform motor efficiency processing for the phase balance model.
	"""
	return .0179 + .402*x + .134*x**2 # curve fit from data from NREL analysis

def lifespan(x, ind):
	''' x is unabalance at the motor bus, ind['motor_lifetime'] is the lifetime of the motor, good default is 25 (years). '''
	return float(ind['motor_lifetime'])-19.8*math.exp(-.679*x) # curve fit from data from NREL analysis

def pf(real, var):
	"""
	Perform pf processing for the phase balance model.
	"""
	real = floats(real) if type(real) == str else float(real)
	var = floats(var) if type(var) == str else float(var)
	return float(real) / math.sqrt(real**2 + var**2)

def n(num):
	"""
	Perform n processing for the phase balance model.
	"""
	return "{:,.2f}".format(num)

def floats(f):
	"""
	Perform floats processing for the phase balance model.
	"""
	return float(f.replace(',', ''))

def parse_complex(x):
    """
    Parse complex data into an OMF-friendly representation.
    """
    if 'd' not in x:
        return complex(x) if x != '+0+0i' else complex(0)
    else:
        polar = complex(x.replace('d', 'j'))
        h = polar.real
        rad = math.radians(polar.imag)
        transformed = complex(h*math.cos(rad), h*math.sin(rad))
        return transformed

def respect_pf(x, constant_pf):
	"""
	Perform respect pf processing for the phase balance model.
	"""
	m = parse_complex(x)
	rating_VA = m.real
	if constant_pf < 1:
		# Lagging PF setting on inverters.
		newWatts = constant_pf * rating_VA
		newVARs = math.sqrt(rating_VA**2 - newWatts**2)
		new_complex = complex(newWatts, newVARs)
		return "{}+{}j".format(new_complex.real, new_complex.imag)
	elif constant_pf > 1:
		# Leaing PF setting on inverters.
		newWatts = (2 - constant_pf) * rating_VA
		newVARs = math.sqrt(rating_VA**2 - newWatts**2)
		new_complex = complex(newWatts, newVARs)
		return "{}{}j".format(new_complex.real, new_complex.imag)

def work(modelDir, ind):
	''' Run the model in its directory. '''
	o = {}
	
	assert not (ind['pvConnection'] == 'Delta' and ind['objectiveFunction'] == 'I0'), (
		'Delta function does not currently support I0 minimization function.'
	)

	SIGN_CORRECTION = -1 if ind['pvConnection'] == 'Delta' else 1
	
	neato = False if ind.get("layoutAlgorithm", "geospatial") == "geospatial" else True
	edgeColValue = ind.get("edgeCol", None) if ind.get("edgeCol") != "None" else None
	nodeColValue = ind.get("nodeCol", None) if ind.get("nodeCol") != "None" else None
	edgeLabsValue = ind.get("edgeLabs", None) if ind.get("edgeLabs") != "None" else None
	nodeLabsValue = ind.get("nodeLabs", None) if ind.get("nodeLabs") != "None" else None
	customColormapValue = True if ind.get("customColormap", "True") == "True" else False

	# -------------------------- BASE CHART --------------------------- #
	with open(pJoin(modelDir, [x for x in os.listdir(modelDir) if x.endswith('.omd')][0])) as f:
		tree_base = json.load(f)['tree']
	
	with open(pJoin(modelDir, 'input.glm'), 'w') as f:
		treeString = feeder.sortedWrite(tree_base)
		f.write(treeString)

	base_suffix = "_base"
	tree_base = _turnOffSolar(tree_base)
	tree_base = _addCollectors(tree_base, suffix=base_suffix, pvConnection=ind['pvConnection'])
	with open(pJoin(modelDir, '_base.glm'), 'w') as f:
		treeString = feeder.sortedWrite(tree_base)
		f.write(treeString)
	
	voltageDrop.drawPlot(
		pJoin(modelDir, "_base.glm"), workDir=modelDir, neatoLayout=neato, 
		edgeCol=edgeColValue, nodeCol=nodeColValue, nodeLabs=nodeLabsValue, 
		edgeLabs=edgeLabsValue, customColormap=customColormapValue, rezSqIn=int(ind["rezSqIn"]), 
			scaleMin=float(ind['colorMin']) if ind['colorMin'].lower() != 'auto' else None, 
			scaleMax=float(ind['colorMax']) if ind['colorMax'].lower() != 'auto' else None
	).savefig(pJoin(modelDir,"output" + base_suffix + ".png"))
	with open(pJoin(modelDir,"output" + base_suffix + ".png"),"rb") as f:
		o['base_image'] = base64.standard_b64encode(f.read()).decode()
	os.rename(pJoin(modelDir, "voltDump.csv"), pJoin(modelDir, "voltDump_base.csv"))
	
	# ---------------------------- CONTROLLED CHART ----------------------------- #
	
	controlled_suffix = '_controlled'
	
	SteinmetzController.SteinmetzController(pJoin(modelDir, 'input.glm'),
		ind['pvConnection'], ind['criticalNode'], 
		int(ind['iterations']), ind['objectiveFunction'], modelDir)

	if ind["pvConnection"] == 'Delta':
		glmPath = pJoin(modelDir, 'input_NewDeltaPV_Final.glm')
	else:
		glmPath = pJoin(modelDir, 'input_Final.glm')
	omdPath = pJoin(modelDir, '_controlled.omd')
	feeder.glmToOmd(glmPath, omdPath)
	
	with open(omdPath) as f:
		tree_controlled = json.load(f)['tree']
	
	constant_pf = float(ind['constant_pf'])
	for k, v in tree_controlled.items():
		if ('PV' in v.get('groupid', '')) and v.get('object', '') == 'load':
			if ind['strategy'] == 'constant':
				if v.get('constant_power_C', '') != '':
					v['constant_power_C'] = respect_pf(v['constant_power_C'], constant_pf)
				elif v.get('constant_power_B', '') != '':
					v['constant_power_B'] = respect_pf(v['constant_power_B'], constant_pf)
				elif v.get('constant_power_A', '') != '':
					v['constant_power_A'] = respect_pf(v['constant_power_A'], constant_pf)
			
			v['groupid'] = 'PV'


	tree_controlled = _addCollectors(tree_controlled, suffix=controlled_suffix, pvConnection=ind['pvConnection'])
	
	with open(pJoin(modelDir, '_controlled.glm'), 'w') as f:
		treeString = feeder.sortedWrite(tree_controlled)
		f.write(treeString)
	
	voltageDrop.drawPlot(
		pJoin(modelDir, "_controlled.glm"), workDir=modelDir, neatoLayout=neato, 
		edgeCol=edgeColValue, nodeCol=nodeColValue, nodeLabs=nodeLabsValue, 
		edgeLabs=edgeLabsValue, customColormap=customColormapValue, rezSqIn=int(ind["rezSqIn"]), 
			scaleMin=float(ind['colorMin']) if ind['colorMin'] != 'auto' else None,
			scaleMax=float(ind['colorMax']) if ind['colorMax'] != 'auto' else None
	).savefig(pJoin(modelDir,"output" + controlled_suffix + ".png"))
	with open(pJoin(modelDir,"output" + controlled_suffix + ".png"),"rb") as f:
		o['controlled_image'] = base64.standard_b64encode(f.read()).decode()

	os.rename(pJoin(modelDir, "voltDump.csv"), pJoin(modelDir, "voltDump_controlled.csv"))
	
	# ---------------------------- SOLAR CHART ----------------------------- #

	if ind["pvConnection"] == 'Delta':
		glmPath = pJoin(modelDir, 'input_NewDeltaPV_Start.glm')
	else:
		glmPath = pJoin(modelDir, 'input_Wye_Start.glm')
	omdPath = pJoin(modelDir, '_solar.omd')
	feeder.glmToOmd(glmPath, omdPath)
	
	with open(omdPath) as f:
		tree_solar = json.load(f)['tree']

	for k, v in tree_solar.items():
		if ('PV' in v.get('groupid', '')) and v.get('object', '') == 'load':
			v['groupid'] = 'PV'

	solar_suffix = "_solar"
	tree_solar = _addCollectors(tree_solar, suffix=solar_suffix, pvConnection=ind['pvConnection'])
	with open(modelDir + '/_solar.glm', 'w') as f:
		treeString = feeder.sortedWrite(tree_solar)
		f.write(treeString)
	
	voltageDrop.drawPlot(
		pJoin(modelDir, "_solar.glm"), workDir=modelDir, neatoLayout=neato, 
		edgeCol=edgeColValue, nodeCol=nodeColValue, nodeLabs=nodeLabsValue, 
		edgeLabs=edgeLabsValue, customColormap=customColormapValue, rezSqIn=int(ind["rezSqIn"]), 
			scaleMin=float(ind['colorMin']) if ind['colorMin'] != 'auto' else None,
			scaleMax=float(ind['colorMax']) if ind['colorMax'] != 'auto' else None
	).savefig(pJoin(modelDir,"output" + solar_suffix + ".png"))
	with open(pJoin(modelDir,"output" + solar_suffix + ".png"),"rb") as f:
		o['solar_image'] = base64.standard_b64encode(f.read()).decode()

	os.rename(pJoin(modelDir, "voltDump.csv"), pJoin(modelDir, "voltDump_solar.csv"))

	# --------------------------- SERVICE TABLE ----------------------------- 
	
	df_invs = {}
	sums = {}
	for suffix in [base_suffix, solar_suffix, controlled_suffix]:
		df_invs[suffix] = { phase: _readCSV(pJoin(modelDir, 'all_inverters_VA_Out_AC_' + phase + suffix + '.csv')) for phase in 'ABC' }

	for suffix in [base_suffix, solar_suffix, controlled_suffix]:
		df_invs[suffix] = {}
		sums[suffix] = 0
		for phase in 'ABC':
			df = _readCSV(pJoin(modelDir, 'all_inverters_VA_Out_AC_' + phase + suffix + '.csv'))
			df_invs[suffix][phase] = df
			sums[suffix] += complex(df['real'].sum(), df['imag'].sum())

	loss_items = get_loss_items(tree_base)

	o['service_cost'] = {
		'load': {
			'base': n(_totals(pJoin(modelDir, 'load' + base_suffix + '.csv'), 'real') + _totals(pJoin(modelDir, 'load_node' + base_suffix + '.csv'), 'real')),
			'solar': n(_totals(pJoin(modelDir, 'load' + solar_suffix + '.csv'), 'real') + _totals(pJoin(modelDir, 'load_node' + solar_suffix + '.csv'), 'real')),
			'controlled': n(_totals(pJoin(modelDir, 'load' + controlled_suffix + '.csv'), 'real') + _totals(pJoin(modelDir, 'load_node' + controlled_suffix + '.csv'), 'real'))
		},
		'distributed_gen': {
			'base': n(sums[base_suffix].real),
			'solar': n(SIGN_CORRECTION*sums[solar_suffix].real),
			'controlled': n(SIGN_CORRECTION*sums[controlled_suffix].real)
		},
		'losses': {
			'base': n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + base_suffix + '.csv'), 'real') for loss in 
				loss_items])),
			'solar': n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + solar_suffix + '.csv'), 'real') for loss in 
				loss_items])),
			'controlled':n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + controlled_suffix + '.csv'), 'real') for loss in 
				loss_items])),
		},
		'VARs': {
			'base': n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + base_suffix + '.csv'), 'imag') for loss in 
				loss_items]) + sums[base_suffix].imag +
				_totals(pJoin(modelDir, 'load' + base_suffix + '.csv'), 'imag') + _totals(pJoin(modelDir, 'load_node' + base_suffix + '.csv'), 'imag')
			),
			'solar': n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + solar_suffix + '.csv'), 'imag') for loss in 
				loss_items]) + sums[solar_suffix].imag +
				_totals(pJoin(modelDir, 'load' + solar_suffix + '.csv'), 'imag') + _totals(pJoin(modelDir, 'load_node' + solar_suffix + '.csv'), 'imag')
			),
			'controlled': n(sum([_totals(pJoin(modelDir, 'Zlosses_' + loss + controlled_suffix + '.csv'), 'imag') for loss in 
				loss_items]) + sums[controlled_suffix].imag +
				_totals(pJoin(modelDir, 'load' + controlled_suffix + '.csv'), 'imag') + _totals(pJoin(modelDir, 'load_node' + controlled_suffix + '.csv'), 'imag')
			)
		},
		# Motor derating and lifespan below.
		'motor_derating': {},
		'lifespan': {}
	}

	# hack correction
	if ind['pvConnection'] == 'Delta':
		o['service_cost']['load']['controlled'] = n(floats(o['service_cost']['load']['controlled']) + floats(o['service_cost']['distributed_gen']['controlled']))
		o['service_cost']['load']['solar'] = n(floats(o['service_cost']['load']['solar']) + floats(o['service_cost']['distributed_gen']['solar']))

	# power factor
	sub_df = {
		'base': _readCSV('substation_power' + base_suffix + '.csv', voltage=False),
		'solar': _readCSV('substation_power' + solar_suffix + '.csv', voltage=False),
		'controlled': _readCSV('substation_power' + controlled_suffix + '.csv', voltage=False),
	}
	o['service_cost']['power_factor'] = {
		'base': n(pf(sub_df['base']['real'].sum(), sub_df['base']['imag'].sum())),
		'solar': n(pf(sub_df['solar']['real'].sum(), sub_df['solar']['imag'].sum())),
		'controlled': n(pf(sub_df['controlled']['real'].sum(), sub_df['controlled']['imag'].sum()))
	}
	# ----------------------------------------------------------------------- #
	
	# -------------------------- INVERTER TABLE ----------------------------- #
	if ind['pvConnection'] == 'Wye':
		inverter_list = set(
			list(df_invs[controlled_suffix]['A'].index) + list(df_invs[controlled_suffix]['B'].index) + list(df_invs[controlled_suffix]['C'].index)
		)
	else:
		inverter_list = df_invs[controlled_suffix]['A'].index
	inverter_rows = {
		inverter: {
			'_solarA': '0j',
			'_solarB': '0j',
			'_solarC': '0j',
			'_controlledA': '0j',
			'_controlledB': '0j',
			'_controlledC': '0j',
		} for inverter in inverter_list
	}

	for suffix in [solar_suffix, controlled_suffix]:
		for phase in 'ABC':
			for inverter, row in df_invs[suffix][phase].iterrows():
				inverter_rows[inverter][suffix + phase] = str(
					SIGN_CORRECTION*complex(row['real'], row['imag'])
				).strip('()')

	o['inverter_table'] = ''.join([(
		"<tr>"
			"<td>{}</td><td style='border-left: solid black 1px;'>{}</td><td>{}</td><td>{}</td><td style='border-left: solid black 1px;'>{}</td><td>{}</td><td>{}</td>"
		"</tr>"
	).format(inverter, v['_solarA'], v['_solarB'], v['_solarC'], v['_controlledA'], v['_controlledB'], v['_controlledC']) for (inverter, v) in inverter_rows.items()])
	# ----------------------------------------------------------------------- #


	# ----------------- MOTOR VOLTAGE and IMBALANCE TABLES ------------------ #
	df_vs = {}
	for suffix in [base_suffix, solar_suffix, controlled_suffix]:
		df_v = pd.DataFrame()
		for phase in ['A', 'B', 'C']:
			df_phase = _readCSV(pJoin(modelDir, 'threephase_VA_'+ phase + suffix + '.csv'))
			df_phase.columns = [phase + '_' + str(c) for c in df_phase.columns]
			if df_v.shape[0] == 0:
				df_v = df_phase
			else:
				df_v = df_v.join(df_phase)
		df_vs[suffix] = df_v

	motor_names = [motor for motor, r in df_v.iterrows()]

	all_motor_unbalance = {}
	for suffix in [base_suffix, solar_suffix, controlled_suffix]:
		df_all_motors = pd.DataFrame()

		df_all_motors = _readVoltage(pJoin(modelDir, 'voltDump' + suffix + '.csv'), motor_names, ind['objectiveFunction'])
		
		o['motor_table' + suffix] = ''.join([(
			"<tr>"
				"<td>{0}</td><td>{1}</td><td>{2}</td><td>{3}</td><td>{4}</td><td>{5}</td><td>{6}</td><td>{7}</td><td>{8}</td>"
			"</tr>" 
				if r['node_name'] != ind['criticalNode'] or ind['strategy'] == 'constant' else 
			"<tr>"
				"<td {9}>{0}</td><td {9}>{1}</td><td {9}>{2}</td><td {9}>{3}</td><td {9}>{4}</td><td {9}>{5}</td><td {9}>{6}</td><td {9}>{7}</td><td {9}>{8}</td>"
			"</tr>"
		).format(r['node_name'], 
					n(r2['A_real'] + r2['B_real'] + r2['C_real']),
					n(r2['A_imag'] + r2['B_imag'] + r2['C_imag']),
					n(r['voltA']), n(r['voltB']), n(r['voltC']), 
					n(r['unbalance']), n(motor_efficiency(r['unbalance'])), n(lifespan(r['unbalance'], ind)), "style='background:yellow'") 
				for (i, r), (j, r2) in zip(df_all_motors.iterrows(), df_vs[suffix].iterrows()) if r2['A_real'] > 0.0])
		#HACK: we only check for non-zero real power.
		all_motor_unbalance[suffix] = [r['unbalance'] for i, r in df_all_motors.iterrows()]

		o['service_cost']['motor_derating'][suffix[1:]] = n(df_all_motors['unbalance'].apply(motor_efficiency).max())
		o['service_cost']['lifespan'][suffix[1:]] = n(df_all_motors['unbalance'].apply(lambda x: lifespan(x, ind)).mean())

	# ----------------------------------------------------------------------- #

	# ---------------------------- COST TABLE ------------------------------- #
	cost = float(ind['productionCost'])
	revenue = float(ind['retailCost'])
	pf_p = float(ind['pf_penalty'])
	pf_t = float(ind['pf_threshold'])
	motor_v = float(ind['motor_value'])

	o['cost_table'] = {
		'energy_cost': {
			'base': '-$' + n(cost*floats(o['service_cost']['load']['base'])),
			'solar': '-$' + n(cost*floats(o['service_cost']['load']['solar'])),
			'controlled': '-$' + n(cost*floats(o['service_cost']['load']['controlled'])),
		},
		'energy_revenue': {
			'base': '$' + n(revenue*floats(o['service_cost']['load']['base']) - cost*floats(o['service_cost']['distributed_gen']['base'])),
			'solar': '$' + n(revenue*floats(o['service_cost']['load']['solar']) - cost*floats(o['service_cost']['distributed_gen']['solar'])),
			'controlled': '$' + n(revenue*floats(o['service_cost']['load']['controlled']) - cost*floats(o['service_cost']['distributed_gen']['controlled'])),
		},
		'pf_penalty': {
			'base': '-$' + n(pf_p if floats(o['service_cost']['power_factor']['base']) <= pf_t else 0),
			'solar': '-$' + n(pf_p if floats(o['service_cost']['power_factor']['solar']) <= pf_t else 0),
			'controlled': '-$' + n(pf_p if floats(o['service_cost']['power_factor']['controlled']) <= pf_t else 0),
		},
		'motor_inefficiency': {
			'base': '-$' + n(motor_v*len([m for m in all_motor_unbalance['_base']])),
			'solar': '-$' + n(motor_v*len([m for m in all_motor_unbalance['_solar']])),
			'controlled': '-$' + n(motor_v*len([m for m in all_motor_unbalance['_controlled']])),
		},
	}

	# ----------------------------------------------------------------------- #

	if ind['pvConnection'] == 'Delta':
		o['inverter_header'] = "<tr><th>Name</th><th>AB (VA)</th><th>BC (VA)</th><th>AC (VA)</th><th>AB (VA)</th><th>BC (VA)</th><th>AC (VA)</th></tr>"
	else:
		o['inverter_header'] = "<tr><th>Name</th><th>A (VA)</th><th>B (VA)</th><th>C (VA)</th><th>A (VA)</th><th>B (VA)</th><th>C (VA)</th></tr>"
		
	return o

def _addCollectors(tree, suffix=None, pvConnection=None):
	"""
	Internal helper for phase balance add collectors processing.
	"""
	for x in tree.values():
		if 'object' in x and ('load' in x['object'].lower() or 'node' in x['object'].lower()) and all([phase in x['phases'] for phase in 'ABC']):
			x['groupid'] = 'threePhase'

	loss_items = get_loss_items(tree)

	# load on system and inverters
	all_power = 'sum(power_A.real),sum(power_A.imag),sum(power_B.real),sum(power_B.imag),sum(power_C.real),sum(power_C.imag)'
	
	tree[len(tree)] = {'property': all_power, 'object': 'collector', 'group': 'class=load', 'limit': '0', 'file': 'load' + suffix + '.csv'}
	tree[len(tree)] = {'property': 'sum(power_12.real),sum(power_12.imag)', 'object': 'collector', 'group': 'class=triplex_node', 'limit': '0', 'file': 'load_node' + suffix + '.csv'}

	# Load on motor phases
	for phase in 'ABC':
		tree[len(tree)] = {'property':'power_' + phase, 'object':'group_recorder', 'group':'groupid=threePhase', 'limit': '1', 'file':'threephase_VA_'+ phase + suffix + '.csv'}
	
	# Loss across system
	all_losses = 'sum(power_losses_A.real),sum(power_losses_A.imag),sum(power_losses_B.real),sum(power_losses_B.imag),sum(power_losses_C.real),sum(power_losses_C.imag)'
	for loss in loss_items:
		tree[len(tree)] = {'property': all_losses, 'object': 'collector', 'group': 'class='+loss, 'limit': '0', 'file': 'Zlosses_'+loss + suffix +'.csv'}

	solar_A, solar_B, solar_C = False, False, False
	if suffix not in ['_controlled', '_solar'] or pvConnection == 'Wye':
		for x in tree.values():
			if x.get('object', '') == 'inverter':
				if 'A' in x['phases']:
					x['groupid'] = 'PVA'
					solar_A = True
				elif 'B' in x['phases']:
					x['groupid'] = 'PVB'
					solar_B = True
				elif 'C' in x['phases']:
					x['groupid'] = 'PVC'
					solar_C = True

		if solar_A:
			tree[len(tree)] = {'property':'VA_Out', 'object':'group_recorder', 'group':'class=inverter AND groupid=PVA', 'limit':'1', 'file':'all_inverters_VA_Out_AC_A' + suffix + '.csv'}
		if solar_B: 
			tree[len(tree)] = {'property':'VA_Out', 'object':'group_recorder', 'group':'class=inverter AND groupid=PVB', 'limit':'1', 'file':'all_inverters_VA_Out_AC_B' + suffix + '.csv'}
		if solar_C:
			tree[len(tree)] = {'property':'VA_Out', 'object':'group_recorder', 'group':'class=inverter AND groupid=PVC', 'limit':'1', 'file':'all_inverters_VA_Out_AC_C' + suffix + '.csv'}
		
	else:
		tree[len(tree)] = {'property':'constant_power_A', 'object':'group_recorder', 'group':'class=load AND groupid=PV', 'limit':'1', 'file':'all_inverters_VA_Out_AC_A' + suffix + '.csv'}
		tree[len(tree)] = {'property':'constant_power_B', 'object':'group_recorder', 'group':'class=load AND groupid=PV', 'limit':'1', 'file':'all_inverters_VA_Out_AC_B' + suffix + '.csv'}
		tree[len(tree)] = {'property':'constant_power_C', 'object':'group_recorder', 'group':'class=load AND groupid=PV', 'limit':'1', 'file':'all_inverters_VA_Out_AC_C' + suffix + '.csv'}


	substation = None
	for x in tree.values():
		if x.get('bustype', '') == 'SWING':
			substation = x['name']
			x['object'] = 'meter'
	assert substation != None, "substation not found"

	tree[len(tree)] = {
		'object': 'recorder',
		'parent': substation,
		'interval': '10',
		'limit': '1440',
		'file': 'substation_power' + suffix + '.csv',
		'property': 'measured_power_A,measured_power_B,measured_power_C'
	}

	return tree

def _turnOffSolar(tree):
	"""
	Internal helper for phase balance turn off solar processing.
	"""
	for k, v in tree.items():
		if v.get("object", "") in ["solar", "inverter"]:
			tree[k]["generator_status"] = "OFFLINE"
	return tree

def _readVoltage(filename, motor_names, objectiveFunction):
	"""
	Internal helper for phase balance read voltage processing.
	"""
	return_df = pd.DataFrame()
	df = pd.read_csv(filename, skiprows=1)
	df_motors = df[df['node_name'].isin(motor_names)]
	return_df['node_name'] = df_motors['node_name']
	for phase in ['voltA', 'voltB', 'voltC']:
		return_df[phase] = np.sqrt(df_motors[phase + '_imag']**2 + df_motors[phase + '_real']**2)

	if objectiveFunction == 'VUF':
		return_df['unbalance'] = df_motors.apply(unbalanceVUF, axis=1)
	else:
		return_df['unbalance'] = return_df.apply(unbalanceI, axis=1)
	return return_df

def unbalanceVUF(r):
	"""
	Perform unbalance vuf processing for the phase balance model.
	"""
	a = complex(r['voltA_real'], r['voltA_imag'])
	b = complex(r['voltB_real'], r['voltB_imag'])
	c = complex(r['voltC_real'], r['voltC_imag'])
	j = complex(-0.5, math.sqrt(3)/2)
	V_p = (a + j*b + j*j*c)/3
	V_n = (a + j*j*b + j*c)/3
	return abs(V_n)/abs(V_p)*100

def unbalanceI(r):
	"""
	Perform unbalance i processing for the phase balance model.
	"""
	a = float(r['voltA'])
	b = float(r['voltB'])
	c = float(r['voltC'])
	avgVolts = (a + b + c)/3
	maxDiff = max([abs(a-b), abs(a-c), abs(b-c)])
	return maxDiff/avgVolts*100

def _readCSV(filename, voltage=True):
	"""
	Internal helper for phase balance read csv processing.
	"""
	df = pd.read_csv(filename, skiprows=8)
	df = df.T
	if voltage:
		df = df[df.columns[:-2]]
	df = df[~df.index.str.startswith('#')]
	df[0] = [parse_complex(i) for i in df[0]]
	df['imag'] = df[0].to_numpy().imag
	df['real'] = df[0].to_numpy().real
	df = df.drop([0], axis=1)
	return df

def _totals(filename, component=None):
	"""
	Internal helper for phase balance totals processing.
	"""
	df = pd.read_csv(filename, skiprows=8)
	df = df.T
	df = df[~df.index.str.startswith('#')]
	if component == "real":
		return sum(df[df.index.str.contains('real')][0])
	else:
		return sum(df[df.index.str.contains('imag')][0])

def new(modelDir):
	''' Create a new instance of this model. Returns true on success, false on failure. '''
	defaultInputs = {
		"feederName1": "phase_balance_test",
		"criticalNode": "R1-12-47-1_node_17",
		"pvConnection": "Delta",
		"layoutAlgorithm": "geospatial",
		# ---------------------------------------- #
		# "feederName1": "phase_balance_test_2",
		# "criticalNode": 'R1-12-47-2_node_28',
		# "pvConnection": 'Wye',
		# "layoutAlgorithm": "forceDirected",
		# ---------------------------------------- #
		# "feederName1": 'bavarian_solar',
		# "criticalNode": "node2283458290",
		# "pvConnection": 'Delta',
		# "layoutAlgorithm": "geospatial",
		# ---------------------------------------- #
		# "feederName1": 'turkey_solar',
		# "criticalNode": "nodeOH5041-S1689OH15730",
		# "pvConnection": 'Delta',
		# "layoutAlgorithm": "geospatial",
		# ---------------------------------------- #
		# "feederName1": 'swaec',
		# "criticalNode": "nodespan_192258span_177328",
		# "pvConnection": 'Wye',
		# "layoutAlgorithm": "geospatial",
		# ---------------------------------------- #
		"strategy": "constant", # constant
		"constant_pf": "1.10",
		"modelType": modelName,
		"runTime": "",
		"zipCode": "64735",
		"retailCost": "0.05",
		"productionCost": "0.03",
		"pf_penalty": "50000",
		"pf_threshold": "0.95",
		"motor_value": "67000",
		"motor_lifetime": "20",
		"discountRate": "7",
		"edgeCol" : "None",
		"nodeCol" : "perUnitVoltage", #"VoltageImbalance"
		"nodeLabs" : "None",
		"edgeLabs" : "None",
		"customColormap" : "False",
		"rezSqIn" : "225",
		"colorMin": "0.92",
		"colorMax": "1.08",
		"objectiveFunction": 'VUF', #'I0'
		"iterations": "5"
	}
	creationCode = __neoMetaModel__.new(modelDir, defaultInputs)
	try:
		shutil.copyfile(pJoin(__neoMetaModel__._omfDir, "static", "testFiles", defaultInputs["feederName1"]+'.omd'), pJoin(modelDir, defaultInputs["feederName1"]+'.omd'))
	except:
		return False
	return creationCode

@neoMetaModel_test_setup
def _tests():
	"""
	Run this module's local smoke tests or debugging workflow.
	"""
	modelLoc = pJoin(__neoMetaModel__._omfDir,"data","Model","admin","Automated Testing of " + modelName)
	if os.path.isdir(modelLoc):
		shutil.rmtree(modelLoc)
	new(modelLoc)
	# __neoMetaModel__.renderAndShow(modelLoc)
	__neoMetaModel__.runForeground(modelLoc)
	__neoMetaModel__.renderAndShow(modelLoc)

if __name__ == '__main__':
	_tests()
