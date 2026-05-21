"""
Coordinate GridLAB-D co-simulation runs by stepping simulators, exchanging values, and
letting agents inspect or perturb the running grid model.
"""
import subprocess, time, warnings
try:
	from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen
from datetime import datetime, timedelta
from http.client import BadStatusLine
import omf
import omf.feeder

def parseDt(dtString):
	'Parse GridLAB-D date time strings'
	return datetime.strptime(dtString, "%Y-%m-%d %H:%M:%S")

def writeDt(dtString):
	'Write GridLAB-D date time strings.'
	return datetime.strftime(dtString, "%Y-%m-%d %H:%M:%S")

class Coordinator(object):
	"""
	Coordinate time-stepped co-simulation objects and advance shared simulation time.
	"""
	__slots__ = 'agents', 'glw', 'log'

	def __init__(self, agents, cosimProps):
		"""
		Internal helper for cosim init processing.
		"""
		self.agents = agents
		# Start the simulation
		self.glw = GridLabWorld(cosimProps['port'],cosimProps['hostname'],cosimProps['glmPath'],cosimProps['startTime'])
		self.glw.start()
		# Make a list of all the timesteps we are communicating on.
		startDt = parseDt(cosimProps['startTime'])
		endDt = parseDt(cosimProps['endTime'])
		stepDelta = timedelta(seconds=cosimProps['stepSizeSeconds'])
		stepNum = (endDt - startDt).total_seconds() / cosimProps['stepSizeSeconds']
		stepDts = [startDt + stepDelta * x  for x in range(int(stepNum))]
		# Initialize the log.
		self.log = []
		# Step through each time step.
		for now in stepDts:
			logEntry = {'time':now, 'entries':[]}
			# At each time step each agent acts.
			for a in agents:
				# Send agent's request to GridLAB-D
				nowStr = writeDt(now)
				readRequests = a.readStep(nowStr)
				readResults = self.glw.doRequests(readRequests)
				#logEntry.append([readRequests, readResults])
				# Send results from GridLAB-D back to agent for write step.
				writeRequests = a.writeStep(nowStr, readResults)
				writeResults = self.glw.doRequests(writeRequests)
				logEntry['entries'].append({'agent': a.agentName, 'requests': readRequests + writeRequests, 'results': readResults + writeResults})
			self.log.append(logEntry)
			self.glw.waitUntil(writeDt(now + stepDelta))
		self.glw.shutdown()

	def returnLog(self):
		# for testing purposes
		"""
		Implement return log behavior for Coordinator instances.
		"""
		return self.log

	def drawResults(self, outputPath=None):
		#return self.log
		"""
		Create a plot or display artifact for results results.
		"""
		html_str = """
		<!DOCTYPE html>
		<html>
			<head>
				<style>
					table, th, td { border: 1px solid black; 
					text-align: center;}
				</style>
			</head>
			<body>
				<table>
					<tr>
						<th>Time</th>"""
						
		for x in range(len(self.agents)):
			temp_str = "<th>Agent"+str(x)+"_Read</th><th>Agent"+str(x)+"_ReadRes</th><th>Agent"+str(x)+"_Write</th><th>Agent"+str(x)+"_WriteRes</th>"
			html_str += temp_str
		html_str += """
					</tr>"""
		for row in self.log:
			row_str = "<tr><td>"+row.pop(0).strftime("%Y-%m-%d %H:%M:%S")+"</td>"
			for col in row:
				row_str += "<td>"+str(col[0])+"</td><td>"+str(col[1])+"</td>"
			row_str += "</tr>"
			html_str += row_str
		html_str += """
				</table>
			</body>
		</html>"""
		if outputPath is None:
			Html_file = open("output.html", "w")
		else:
			Html_file = open(outputPath, "w")
		Html_file.write(html_str)
		Html_file.close()

	def drawPrettyResults(self, outputPath=None):
		#return self.log
		"""
		Create a plot or display artifact for pretty results results.
		"""
		html_str = """
		<!DOCTYPE html>
		<html>
			<head>
				<title>Pretty Results</title>
				<style>
					table, th, td { border: 1px solid black; 
					text-align: center;}
				</style>
				<link href="css/960.css" rel="stylesheet" media="screen" />
				<link href="css/defaultTheme.css" rel="stylesheet" media="screen" />
				<link href="css/myTheme.css" rel="stylesheet" media="screen" />
				<script src="https://ajax.googleapis.com/ajax/libs/jquery/1.5.2/jquery.min.js"></script>

				<script src="jquery.fixedheadertable.js"></script>
				<script src="prettyResults.js"></script>
			</head>
			<body>
				<div class="container_whole">
					<div class="grid_whole height_whole">
						<table class="fancyTable" id="myTable" cellpadding="0" cellspacing="0">
							<thead>
								<tr>
									<th>Time</th>"""
						
		for agent in self.agents:
			temp_str = "<th>"+agent.agentName+" Requests</th><th>"+agent.agentName+" Results</th>"
			html_str += temp_str
		html_str += """
								</tr>
							</thead>
							<tbody>"""
		for row in self.log:
			row_str = "<tr><td>"+row.get('time').strftime("%Y-%m-%d %H:%M:%S")+"</td>"
			for agentEntry in row.get('entries'):
				reqs_str = "<td><p>"
				agent_reqs = agentEntry.get('requests')
				if not agent_reqs: #if it's empty (no requests made at the given time)
					reqs_str += "None"
				else:
					for req in agent_reqs:
						cmd = req.get('cmd')
						if cmd == 'readClock':
							reqs_str += "<b>READCLOCK</b><br/>"
						elif cmd == 'read':
							temp_str = "<b>READ</b> " + req.get('obName') + " &rarr; " + req.get('propName') + "<br/>"
							reqs_str += temp_str
						elif cmd == 'write':
							temp_str = "<b>WRITE</b> " + req.get('obName') + " &rarr; " + req.get('propName') + " = " + req.get('value') + "<br/>"
							reqs_str += temp_str
				reqs_str += "</p></td>"
				res_str = "<td><p>"
				agent_res = agentEntry.get('results')
				if not agent_res: #if it's empty (no results at the given time)
					res_str += "None"
				else:
					for res in agent_res:
						if 'status' in res:
							temp_str = "<b>" + res.get('status') + "</b> : " + res.get('obName') + " &rarr; " + res.get('propName') + " = " + res.get('value') + "<br/>"
						else:
							temp_str = res.get('obName') + " &rarr; " + res.get('propName') + " = " + str(res.get('value')) + "<br/>"
						res_str += temp_str 
				res_str += "</p></td>"
				row_str += reqs_str + res_str
			row_str += "</tr>"
			html_str += row_str
		html_str += """
							</tbody>
						</table>
					</div>
				</div>
			</body>
		</html>"""
		if outputPath is None:
			Html_file = open("./output.html", "w")
		else:
			Html_file = open(outputPath, "w")
		Html_file.write(html_str)
		Html_file.close()

class GridLabWorld(object):
	"""
	Represent a GridLAB-D simulation world controlled through the OMF co-simulation
	coordinator.
	"""
	__slots__ = 'PORT', 'HOST', 'GLM_PATH', 'START_PAUSE', 'baseUrl', 'procObject'

	def __init__(self, PORT, HOST, GLM_PATH, START_PAUSE):
		"""
		Internal helper for cosim init processing.
		"""
		self.PORT = PORT
		self.HOST = HOST
		self.GLM_PATH = GLM_PATH
		self.START_PAUSE = START_PAUSE
		# Derived global.
		self.baseUrl = 'http://' + HOST + ':' + PORT + '/'

	def doRequests(self, reqList):
		'Do multiple requests.'
		# E.g. reqList = [{'cmd':'readClock|findByType|read|write', 'obName':'', 'propName':'', 'value':''}]
		results = []
		for req in reqList:
			reqType = req.get('cmd','')
			obName = req.get('obName', '')
			propName = req.get('propName', '')
			value = req.get('value', '')
			if reqType == 'readClock':
				results.append(self.readClock())
			elif reqType == 'findByType':
				reuslts.append({'obType':obType, 'obNameList':self.findByType(obType)})
			elif reqType == 'read':
				results.append({'obName':obName, 'propName':propName, 'value':self.read(obName, propName)})
			elif reqType == 'write':
				results.append({'obName':obName, 'propName':propName, 'value':value, 'status':self.write(obName, propName, value)})
		return results

	def waitUntil(self, targetTime):
		'Step to targetTime in current simulation.'
		try:
			# HACK: we don't need full URL encoding right?
			niceUrl = self.baseUrl + 'control/pauseat=' + targetTime.replace(' ','%20')
			with request.urlopen(niceUrl) as f:
				f.read()
			currentTime = None
			while currentTime != targetTime:
				time.sleep(0.2)
				#HACK: Read clock and also drop the timezone because it causes problems.
				with request.urlopen(self.baseUrl + 'raw/clock') as f:
					currentTime = (f.read()[0:-4]).decode()
		except:
			warnings.warn("Wait until " + targetTime + " failed!")

	def findByType(self, obType):
		'Find all instances of an object type and return a list of those object names'
		path = self.GLM_PATH
		try:
			if path.endswith('.glm'):
				tree = omf.feeder.parse(path)
				attachments = []
			elif path.endswith('.omd'):
				with open(path) as f:
					omd = json.load(f)
				tree = omd.get('tree', {})
				attachments = omd.get('attachments',[])
			else:
				raise Exception('Invalid input file type. We require a .glm or .omd.')
			#create an empty list to fill with names of objects of type obType
			nameList = []
			#for each of the elements in the circuit, check object type
			for key in list(tree.keys()):
				tempObType = tree[key].get("object","")
				if tempObType == obType:
					#add matched object's name to nameList
					nameList.append(tree[key].get("name",""))
			return nameList
		except:
			warnings.warn("Failed to find objects of type " + obType)
			return "ERROR"

	def read(self, obName, propName):
		'Read a value from the GLD simulation.'
		try:
			# print obName + "  " + propName
			with request.urlopen(self.baseUrl + 'raw/' + obName + '/' + propName) as f:
				return f.read()
		except:
			warnings.warn("Failed to read " + propName + " of " + obName)
			return "ERROR"

	def readClock(self):
		'Read the clock'
		try:
			with request.urlopen(self.baseUrl + 'raw/clock') as f:
				return f.read()
		except:
			warnings.warn("Failed to read the clock.")
			return "ERROR"

	def shutdown(self):
		'Stop simulation.'
		try:
			with request.urlopen(self.baseUrl + 'control/shutdown') as f:
				f.read()
		except:
			# For those hard-to-stop servers.
			self.procObject.kill()
		# Final output
		print('===GRIDLAB-D STDOUT===')
		# self.procObject.stdout.flush()
		print(self.procObject.stdout.read().strip())
		print('===GRIDLAB-D STDERR===')
		# self.procObject.stderr.flush()
		print(self.procObject.stderr.read())

	def resume(self):
		"""
		Implement resume behavior for GridLabWorld instances.
		"""
		try:
			with request.urlopen(self.baseUrl + 'control/resume') as f:
				f.read()
		except:
			warnings.warn("Resume failed!")

	def write(self, obName, propName, value):
		'Write a value back to the simulation'
		try:
			with request.urlopen(self.baseUrl + 'raw/' + obName + '/' + propName + '=' + value) as f:
				f.read()
			return "WRITE_SUCCESS"
		except:
			warnings.warn("Failed to write " + value + " to " + propName + " of " + obName)
			return "WRITE_FAILURE"

	def start(self, timeout = 30):
		#TODO: watch out for in-use port.
		"""
		Implement start behavior for GridLabWorld instances.
		"""
		self.procObject = subprocess.Popen(['gridlabd', self.GLM_PATH, '--server', '-P', self.PORT, '-q','--define','pauseat="' + self.START_PAUSE + '"'], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
		# print 'MY START PID!', self.procObject.pid
		# Wait for the dang server to start up and simulate.
		while timeout > 0:
			try:
				with request.urlopen(self.baseUrl + 'raw/clock') as f:
					x = f.read()
				# print 'clock', type(x), x
				if x != 'ERROR':
					return
					# print 'Startup Success'
			except:
				pass
				# print 'clock read failed'
			time.sleep(1)
			timeout = timeout - 1
		self.shutdown()
		raise Exception('GridLAB-D startup failed. Please check GLM.')

def _test1():
	"""
	Internal helper for cosim test1 processing.
	"""
	glw = GridLabWorld('6267', 'localhost', omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', '2000-01-02 00:00:00')
	glw.start()
	# Read the clock, solar output voltage, battery state of charge, and inverter voltage input.
	print('* Reading clock:', glw.readClock())
	print('* Bunch of requests:', glw.doRequests([{'cmd':'read', 'obName':'solar_1', 'propName':'V_Out'},{'cmd':'readClock'}]))
	print('* Reading solar_1 output voltage (V_Out):', glw.read('solar_1', 'V_Out'))
	# print '* Reading battery_1 state of charge:', glw.read('battery_1' + 'battery_state')
	print('* Reading inverter_1 input voltage (V_In):', glw.read('inverter_1','V_In'))
	# Step the simulation.
	glw.waitUntil('2000-01-02 12:00:00')
	print('* Stepped ahead 12 hours.')
	# Get the value and clock again.
	print('* Reading solar_1 output voltage (V_Out):', glw.read('solar_1','V_Out'))
	#	print '* Reading battery_1 state of charge:', glw.read('battery_1' + 'battery_state')
	print('* Reading inverter_1 input voltage (V_In):', glw.read('inverter_1','V_In'))
	print('* Reading clock again:', glw.readClock())
	# # Set a value.
	glw.write('waterheater1','temperature','110.0')
	print('* Setting temp to 110.')
	# Finish the simulation and see final values.
	print('* Resuming simulation.')
	glw.resume()
	print('* Reading solar_1 output volatage (V_Out):', glw.read('solar_1','V_Out'))
	print('* Reading final temp:', glw.read('waterheater1','temperature'))
	#	print '* Reading battery_1 state of charge:', glw.read('battery_1' + 'battery_state')
	print('* Reading inverter_1 input voltage (V_In):', glw.read('inverter_1','V_In'))
	# Stop the simulation.
	glw.shutdown()

def _test2():
	# test with AlertAgent, ReadAttackAgent
	"""
	Internal helper for cosim test2 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 12:00:00', 'stepSizeSeconds':3600} #error with having 
	agents = [cyberAttack.AlertAgent('AlertAgent', '2000-01-03 12:00:00')] 
	print('Starting co-sim with 1 agent.')
	coord = Coordinator(agents, cosimProps)
	# print coord.drawResults()

def _test3():
	# test with AlertAgent, ReadAttackAgent
	"""
	Internal helper for cosim test3 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = [
		cyberAttack.AlertAgent('AlertAgent', '2000-01-03 12:00:00'),
		cyberAttack.ReadAttackAgent('ReadAttackAgent', '2000-01-02 10:00:00', 'tm_1', 'measured_power')
	]
	print('Starting co-sim with 2 agents.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawResults())

def _test4():
	# test with AlertAgent, ReadAttackAgent, and ReadAttackIntervalAgent
	"""
	Internal helper for cosim test4 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = [
		cyberAttack.AlertAgent('2000-01-03 04:00:00'),
		cyberAttack.ReadAttackAgent('2000-01-02 10:00:00', 'tm_1', 'measured_power'),
		cyberAttack.ReadIntervalAttackAgent('2000-01-02 08:00:00', '2000-01-03 08:00:00', 'tm_1', 'measured_real_energy')
	]
	print('Starting co-sim with 3 agents.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawResults())

def _test5():
	# test with AlertAgent, ReadAttackAgent, ReadIntervalAttackAgent, and WriteAttackAgent
	# shows how WriteAttackAgent and WriteIntervalAttackAgent interact with ReadAttackAgent and ReadIntervalAttackAgent
	"""
	Internal helper for cosim test5 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = []
	agents.append(cyberAttack.AlertAgent('Joe', '2000-01-03 04:00:00'))
	agents.append(cyberAttack.ReadAttackAgent('Sue', '2000-01-02 10:00:00', 'tm_1', 'measured_power'))
	agents.append(cyberAttack.ReadIntervalAttackAgent('David', '2000-01-02 08:00:00', '2000-01-03 08:00:00', 'tm_1', 'measured_real_energy'))
	agents.append(cyberAttack.WriteAttackAgent('Shammya', '2000-01-02 16:00:00', 'tm_1', 'measured_real_energy', '0.0'))
	agents.append(cyberAttack.WriteIntervalAttackAgent('Dan', '2000-01-03 20:00:00', '2000-01-04 08:00:00', 'inverter_1', 'power_factor', '0.4'))
	agents.append(cyberAttack.ReadIntervalAttackAgent('Dan2.0', '2000-01-03 12:00:00', '2000-01-04 12:00:00', 'tm_2', 'measured_reactive_power'))
	agents.append(cyberAttack.DefendByValueAgent('Dan.biz', 'battery_1', 'generator_status', 'ONLINE'))
	agents.append(cyberAttack.WriteAttackAgent('Alice', '2000-01-01 04:00:00', 'battery_1', 'generator_status', 'OFFLINE'))
	print('Starting co-sim with 8 agents.')
	coord = Coordinator(agents, cosimProps)
	# print coord.drawResults()
	print(coord.drawPrettyResults())

def _test6():
	"""
	Internal helper for cosim test6 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = []
	agents.append(cyberAttack.DefendByValueAgent('defendAreaAgent', 'solar_2', 'area', '+323 sf'))
	agents.append(cyberAttack.CopycatAgent('copycat1', '2000-01-02 12:00:00', 'solar_1', 'area', [{'obNameToPaste':'solar_2', 'obPropToPaste': 'area'}]))
	#agents.append(cyberAttack.ReadIntervalAttackAgent('2000-01-02 06:00:00', '2000-01-02 18:00:00', 'inverter_2', 'V_In'))
	print('Starting co-sim with a DefendByValueAgent and a CopycatAgent.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

def _test7():
	# test with ReadMultAttackAgent
	"""
	Internal helper for cosim test7 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = [cyberAttack.ReadMultAttackAgent('ReadMult', '2000-01-01 01:00:00', 'tm_1', ['measured_power','measured_real_energy'])]
	print('Starting co-sim with 1 ReadMultAttackAgent.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

def _test8():
	# test with ReadMultAttackAgent and WriteMultAttackAgent
	"""
	Internal helper for cosim test8 processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm', 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	agents = []
	agents.append(cyberAttack.ReadMultAttackAgent('ReadMultAttackAgent_1', '2000-01-01 01:00:00', 'tm_1', ['measured_power','measured_real_energy']))
	agents.append(cyberAttack.WriteMultAttackAgent('WriteMultAttackAgent_1', '2000-01-01 02:00:00', 'tm_1', [{'obPropToAttack':'measured_power', 'value':'0.0'}, {'obPropToAttack':'measured_real_energy', 'value':'0.0'}]))
	print('Starting co-sim with 1 ReadMultAttackAgent and 1 WriteMultAttackAgent.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

def _test9():
	# test KillAllAtTime agent
	"""
	Internal helper for cosim test9 processing.
	"""
	glmPath = omf.omfDir + '/scratch/CIGAR/test_smsSingle.glm'
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':glmPath, 'startTime':'2000-01-01 00:00:00','endTime':'2000-01-05 00:00:00', 'stepSizeSeconds':3600}
	# Gather the things to attack
	from omf import feeder
	tree = feeder.parse(glmPath)
	namesOfInverters = []
	for key in tree:
		ob = tree[key]
		if ob.get('object','') == 'inverter' and 'name' in ob:
			namesOfInverters.append(ob['name'])
	# Set up the agents and the simulation
	agents = []
	agents.append(cyberAttack.KillAllAtTime('KillAllInverters', '2000-01-01 12:00:00', 'MagnitudeOfKillInput', namesOfInverters))
	print('Starting co-sim with the KillAllInverters agent.')
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

def _testfault():
	"""
	Internal helper for cosim testfault processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_Exercise_4_2_1.glm', 'startTime':'2000-01-01 05:00:00','endTime':'2000-01-01 05:30:00', 'stepSizeSeconds':60}
	agents = []
	agents.append(cyberAttack.ReadIntervalAttackAgent('FaultChecker', '2000-01-01 05:02:00', '2000-01-01 05:12:00', 'node711-741', 'conductor_resistance'))
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

def _testInverterAttack():
	"""
	Internal helper for cosim test inverter attack processing.
	"""
	from omf import cyberAttack
	cosimProps = {'port':'6267', 'hostname':'localhost', 'glmPath':omf.omfDir + '/scratch/CIGAR/test_R1-12.47-1-AddSolar-Wye.glm', 'startTime':'2000-01-01 05:00:00','endTime':'2000-01-01 05:30:00', 'stepSizeSeconds':60}
	agents = []
	agents.append(cyberAttack.AttackAllObTypeAgent('InverterAttacker1', '2000-01-01 05:02:00', 'inverter', [{"obPropToAttack":"power_factor", "value":"0.5"}]))
	#agents.append(cyberAttack.AttackAllInverterAgent('InverterAttacker2', '2000-01-01 05:02:00', [{"obPropToAttack":"power_factor", "value":"0.5"}]))
	coord = Coordinator(agents, cosimProps)
	print(coord.drawPrettyResults())

if __name__ == '__main__':
	# _test3()
	# _testfault()
	_testInverterAttack()
	# thisDir = os.path.dirname(__file__)
	# webbrowser.open_new("file://" + thisDir + "/AgentLog/output.html")