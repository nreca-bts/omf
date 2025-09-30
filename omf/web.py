''' Web server for model-oriented OMF interface. '''

import json, os, hashlib, random, time, datetime as dt, shutil, csv, sys, platform, errno, io, signal
from contextlib import contextmanager
from multiprocessing import Process
from passlib.hash import pbkdf2_sha512
from functools import wraps
from flask import (Flask, send_from_directory, request, redirect, render_template, session, abort, jsonify, url_for)
import flask_login, boto3
from flask_compress import Compress
from jinja2 import Template
import dateutil
from subprocess import Popen
import re
from urllib.parse import urlparse, urljoin
from werkzeug.utils import secure_filename
from pathlib import Path
try:
	import fcntl
except:
	#We're on windows, where we don't support file locking.
	fcntl = type('', (), {})()
	def flock(fd, op):
		return
	fcntl.flock = flock
	(fcntl.LOCK_EX, fcntl.LOCK_SH, fcntl.LOCK_UN, fcntl.LOCK_NB) = (0, 0, 0, 0)
import omf
from omf import (models, feeder, transmission, milToGridlab, cymeToGridlab, weather, anonymization, distNetViz, loadModelingScada, omfStats, loadModeling,
	loadModelingAmi, geo, comms)
from omf.solvers.opendss import dssConvert

app = Flask("web")
Compress(app)
URL = "http://www.omf.coop"

# Ensure HttpOnly flags on cookies (session + Flask-Login remember cookie)
# Explicit even if framework defaults cover session, to satisfy security review.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_DURATION'] = dt.timedelta(days=7)  # Expire remember_token after 1 week
_omfDir = os.path.dirname(os.path.abspath(__file__))

###################################################
# HELPER FUNCTIONS
###################################################

def safeListdir(path):
	''' Helper function that returns [] for dirs that don't exist. Otherwise new users can cause exceptions. '''
	try: return [x for x in os.listdir(path) if not x.startswith(".")]
	except:	return []

def getDataNames():
	''' Query the OMF datastore to get names of all objects.'''
	try:
		currUser = User.cu()
	except:
		currUser = "public"
	climates = [x[:-5] for x in safeListdir("./data/Climate/")]
	feeders = []
	circuitFiles = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "data","Model", currUser)):
		for fname in filenames:
			if fname.endswith('.omd') and fname != 'feeder.omd':
				feeders.append({'name': fname[:-4], 'model': dirpath.split('/')[-1]})
			# TODO: possibly expand circuit file editor to include more than just openDSS files
			elif fname.endswith('.dss') and fname != 'feeder.dss':
				# circuitFiles.append({'name': fname[:-4], 'model': dirpath.split('/')[-1]})
				circuitFiles.append({'name': fname, 'model': dirpath.split('/')[-1]})
	networks = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "scratch","transmission", "outData")):
		for fname in filenames:
			if fname.endswith('.omt') and fname != 'feeder.omt':
				networks.append({'name': fname[:-4], 'model': 'DRPOWER'})
	# Public feeders too.
	publicFeeders = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "static","publicFeeders")):
		for fname in filenames:
			if fname.endswith('.omd') and fname != 'feeder.omd':
				publicFeeders.append({'name': fname[:-4], 'model': dirpath.split('/')[-1]})
	return {"climates":sorted(climates), "feeders":feeders, "networks":networks, "publicFeeders":publicFeeders, "currentUser":currUser}

ALLOWED_ORIGINS = {
	"https://omf.coop",
	"https://www.omf.coop",
	"http://localhost:5001",
	"http://127.0.0.1:5001"
}

def _is_same_origin():
	origin = request.headers.get("Origin")
	if origin:
		return origin in ALLOWED_ORIGINS
	# Fallback to Referer (some clients may omit Origin)
	referer = request.headers.get("Referer", "")
	return any(referer.startswith(o + "/") for o in ALLOWED_ORIGINS)

@app.before_request
def only_same_origin():
	if request.method in ("POST", "PUT", "PATCH", "DELETE"):
		if not _is_same_origin():
			abort(403)

###################################################
# AUTHENTICATION AND USER FUNCTIONS
###################################################


class User:
	def __init__(self, jsonBlob): self.username = jsonBlob["username"]
	# Required flask_login functions.
	def is_admin(self): return self.username == "admin"
	def get_id(self): return self.username
	def is_authenticated(self): return True
	def is_active(self): return True
	def is_anonymous(self): return False
	@classmethod
	def cu(self):
		"""Returns current user's username"""
		return flask_login.current_user.username


def cryptoRandomString():
	''' Generate a cryptographically secure random string for signing/encrypting cookies. '''
	# Use pre-defined COOKIE_KEY if provided at runtime (e.g., via injection in globals),
	# otherwise generate a pseudo-random value (note: for stronger randomness consider secrets.token_hex).
	ck = globals().get('COOKIE_KEY')
	if ck:
		return ck
	return hashlib.md5(str(random.random()).encode('utf-8') + str(time.time()).encode('utf-8')).hexdigest()


login_manager = flask_login.LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login_page"
app.secret_key = cryptoRandomString()


def _send_email(recipient, subject, message):
	c = boto3.client('ses', region_name='us-east-1')
	email_content = {
		'Source': 'admin@omf.coop',
		'Destination': {'ToAddresses': [recipient]},
		'Message': {
			'Subject': {'Data': subject, 'Charset': 'UTF-8'},
			'Body': {'Text': {'Data': message, 'Charset': 'UTF-8' }}
		}
	}
	c.send_email(**email_content)

def send_link(email, message, u=None):
	'''Send message to email using Amazon SES.'''
	if u is None:
		u = {}
	try:
		reg_key = hashlib.md5(str(random.random()).encode('utf-8') + str(time.time()).encode('utf-8')).hexdigest()
		_send_email(email, 'OMF Registration Link', message.replace('reg_link', URL + '/register/' + email + '/' + reg_key))
		u["reg_key"] = reg_key
		u["timestamp"] = dt.datetime.strftime(dt.datetime.now(), format="%c")
		u["registered"] = False
		u["email"] = email
		with locked_open(os.path.join(_omfDir, 'data', 'User', email + '.json'), 'w') as f:
			json.dump(u, f, indent=4)
		return "Success"
	except:
		return "Failed"


@login_manager.user_loader
def load_user(username):
	''' Required by flask_login to return instance of the current user '''
	with locked_open(os.path.join(_omfDir, 'data', 'User', username + '.json')) as f:
		data = json.load(f)
	return User(data)


def _is_safe_url(target: str) -> bool:
	"""Return True if the target URL is a local URL we can safely redirect to.

	Rules:
	- Allow empty -> treated as '/'
	- Allow relative paths starting with single '/'
	- Allow same-origin absolute URLs (scheme http/https, netloc matches request.host)
	- Disallow protocol-relative ('//example.com'), different host, or control chars.
	"""
	if not target:
		return True
	# Strip surrounding whitespace / control chars
	target = target.strip()
	# Reject obvious protocol-relative or backslash escapes
	if target.startswith('//') or target.startswith('\\'):
		return False
	# Simple relative path
	if target.startswith('/'):
		return True
	# For absolute URLs, ensure same host
	ref = urlparse(request.host_url)
	test = urlparse(urljoin(request.host_url, target))
	if test.scheme in ('http', 'https') and ref.netloc == test.netloc:
		return True
	return False


def safe_redirect(target: str):
	"""Redirect to target if safe, else fallback to '/'."""
	if not _is_safe_url(target):
		target = '/'
	# Normalize empty
	if not target:
		target = '/'
	return redirect(target)


@app.route("/login", methods = ["POST"])
def login():
	''' Authenticate a user and send them to the URL they requested. '''
	username, password, remember = map(request.form.get, ["username", "password", "remember"])
	userJson = None
	for u in safeListdir(os.path.join(_omfDir, 'data', 'User')):
		if u.lower() == username.lower() + ".json":
			with locked_open(os.path.join(_omfDir, 'data', 'User', u)) as f:
				userJson = json.load(f)
			break
	if userJson and pbkdf2_sha512.verify(password, userJson["password_digest"]):
		user = User(userJson)
		flask_login.login_user(user, remember = remember == "on")
	nextUrl = str(request.form.get("next","/") or "/")
	return safe_redirect(nextUrl)


@app.route("/login_page")
def login_page():
	nextUrl = str(request.args.get("next","/") or "/")
	if not _is_safe_url(nextUrl):
		nextUrl = "/"
	if flask_login.current_user.is_authenticated():
		return redirect(nextUrl)
	return render_template("clusterLogin.html", next=nextUrl)


@app.route("/logout")
def logout():
	flask_login.logout_user()
	return redirect("/")


@app.route("/deleteUser", methods=["POST"])
@flask_login.login_required
def deleteUser():
	if User.cu() != "admin":
		return "You are not authorized to delete users"
	username = request.form.get("username")
	# Clean up user data.
	try:
		shutil.rmtree("data/Model/" + username)
	except Exception as e:
		print("USER DATA DELETION FAILED FOR", e)
	os.remove("data/User/" + username + ".json")
	print("SUCCESFULLY DELETE USER", username)
	return "Success"


@app.route("/new_user", methods=["POST"])
def new_user():
	email = request.form.get("email")
	if email == "": return "EMPTY"
	if email in [f[0:-5] for f in safeListdir(os.path.join(_omfDir, 'data', 'User'))]:
		with locked_open(os.path.join(_omfDir, 'data', 'User', email + '.json')) as f:
			u = json.load(f)
		if u.get("password_digest") or not request.form.get("resend"):
			return "Already Exists"
	message = "Click the link below to register your account for the OMF.  This link will expire in 24 hours:\n\nreg_link"
	return send_link(email, message)


@app.route("/forgotPassword/<email>", methods=["GET"])
def forgotpwd(email):
	try:
		with locked_open(os.path.join(_omfDir, 'data', 'User', email + '.json')) as f:
			user = json.load(f)
		message = "Click the link below to reset your password for the OMF.  This link will expire in 24 hours.\n\nreg_link"
		code = send_link(email, message, user)
		if code == "Success":
			return "We have sent a password reset link to " + email
		else:
			raise Exception
	except Exception as e:
		print("ERROR: failed to password reset user", email, "with exception", e)
		return "We do not have a record of a user with that email address. Please click back and create an account."


@app.route("/fastNewUser/<email>")
def fastNewUser(email):
	''' Create a new user, email them their password, and immediately create a new model for them.'''
	if email in [f[0:-5] for f in safeListdir(os.path.join(_omfDir, 'data', 'User'))]:
		return "User with email {} already exists. Please log in or go back and use the 'Forgot Password' link. Or use a different email address.".format(email)
	else:
		randomPass = ''.join([random.choice('abcdefghijklmnopqrstuvwxyz') for x in range(15)])
		user = {"username":email, "password_digest":pbkdf2_sha512.encrypt(randomPass)}
		flask_login.login_user(User(user))
		with locked_open(os.path.join(_omfDir, 'data', 'User', user['username'] + '.json'), 'w') as f:
			json.dump(user, f, indent=4)
		message = "Thank you for registering an account on OMF.coop.\n\nYour password is: " + randomPass + "\n\n You can change this password after logging in."
		_send_email(email, 'OMF.coop User Account', message)
		nextUrl = str(request.args.get("next","/") or "/")
		return safe_redirect(nextUrl)


@app.route("/register/<email>/<reg_key>", methods=["GET", "POST"])
def register(email, reg_key):
	if flask_login.current_user.is_authenticated():
		return redirect("/")
	try:
		with locked_open(os.path.join(_omfDir, 'data', 'User', email + '.json')) as f:
			user = json.load(f)
	except Exception:
		user = None
	if not (user and
			reg_key == user.get("reg_key") and
			user.get("timestamp") and
			dt.timedelta(1) > dt.datetime.now() - dateutil.parser.parse(user.get("timestamp"))):
		return "This page either expired, or you are not supposed to access it. It might not even exist"
	if request.method == "GET":
		return render_template("register.html", email=email)
	password, confirm_password = map(request.form.get, ["password", "confirm_password"])
	if password == confirm_password and request.form.get("legalAccepted","") == "on":
		user["username"] = email
		user["password_digest"] = pbkdf2_sha512.encrypt(password)
		flask_login.login_user(User(user))
		with locked_open(os.path.join(_omfDir, 'data', 'User', user['username'] + '.json'), 'w') as f: # Need 'w' mode to create new users? I would prefer r+ mode
			json.dump(user, f, indent=4)
	else:
		return "Passwords must both match and you must accept the Terms of Use and Privacy Policy. Please go back and try again."
	return redirect("/")


@app.route("/changepwd", methods=["POST"])
@flask_login.login_required
def changepwd():
	old_pwd, new_pwd, conf_pwd = map(request.form.get, ['old_pwd', 'new_pwd', 'conf_pwd'])
	user_filepath = os.path.join(_omfDir, 'data', 'User', User.cu() + '.json')
	with locked_open(user_filepath) as f:
		user = json.load(f)
	if pbkdf2_sha512.verify(old_pwd, user["password_digest"]):
		if new_pwd == conf_pwd:
			user["password_digest"] = pbkdf2_sha512.encrypt(new_pwd)
			with locked_open(user_filepath, 'r+') as f:
				f.truncate(0)
				json.dump(user, f, indent=4)
			return "Success"
		else:
			return "not_match"
	else:
		return "not_auth"


@app.route("/adminControls")
@flask_login.login_required
def adminControls():
	''' Render admin controls. '''
	if User.cu() != "admin":
		return redirect("/")
	users = [{'username':f[0:-5]} for f in safeListdir(os.path.join(_omfDir, 'data', 'User')) if f not in ['admin.json', 'public.json']]
	for user in users:
		with locked_open(os.path.join(_omfDir, 'data', 'User', user['username'] + '.json')) as f:
			userDict = json.load(f)
		tStamp = userDict.get("timestamp","")
		if userDict.get("password_digest"):
			user["status"] = "Registered"
		elif dt.timedelta(1) > dt.datetime.now() - dateutil.parser.parse(tStamp):
			user["status"] = "emailSent"
		else:
			user["status"] = "emailExpired"
	return render_template("adminControls.html", users = users)


@app.route("/omfStats")
@flask_login.login_required
def omfStatsView():
	'''Render log visualizations.'''
	if User.cu() != "admin":
		return redirect("/")
	return render_template("omfStats.html")


@app.route("/regenOmfStats")
@flask_login.login_required
def regenOmfStats():
	'''Regenarate stats images.'''
	if User.cu() != "admin":
		return redirect("/")
	genImagesProc = Process(target=omfStats.genAllImages, args=[])
	genImagesProc.start()
	return redirect("/omfStats")


@app.route("/myaccount")
@flask_login.login_required
def myaccount():
	''' Render account info for any user. '''
	return render_template("myaccount.html", user=User.cu())


@app.route("/robots.txt")
def static_from_root():
	return send_from_directory(app.static_folder, request.path[1:])


def read_permission_function(func):
	"""Run the route if the user has read permission for the model and the model exists, otherwise redirect to home page."""
	@wraps(func)
	def wrapper(*args, **kwargs):
		owner = kwargs.get('owner') if kwargs.get('owner') is not None else request.form.get('user')
		if owner is None:
			return redirect("/")
		model_name = kwargs.get('modelName') if kwargs.get('modelName') is not None else request.form.get('modelName')
		if model_name is None:
			return redirect("/")
		if model_name == 'publicFeeders':
			# Public feeders in the static/publicFeeders directory have no model associated with them, so they are a special case. Public feeders are
			# accessed from a variety of routes, including uniqObjName and loadFeeder. Any user can read from a public feeder.
			return func(*args, **kwargs)
		# Check for the existence of the model. This is not strictly the task of this function, but it is convenient to check here
		model_metadata_path = os.path.join(_omfDir, 'data/Model', owner, model_name, 'allInputData.json')
		if not os.path.isfile(model_metadata_path):
			return redirect('/')
		if owner == 'public':
			# Any user can view a public model
			return func(*args, **kwargs)
		if owner == User.cu() or _is_authorized_model_viewer(owner, model_name) or "admin" == User.cu():
			# Only owners, authorized viewers, and the admin can view a user-owned model
			return func(*args, **kwargs)
		return redirect('/')
	return wrapper


def _is_authorized_model_viewer(owner, model_name):
	"""Return True if the current user is authorized to view the specified model, else False."""
	model_metadata = get_model_metadata(owner, model_name)
	authorized_viewers = model_metadata.get("viewers")
	if authorized_viewers is not None and User.cu() in authorized_viewers:
		return True
	return False


def write_permission_function(func):
	"""Run the route if the user has write permission for the model, otherwise redirect to the home page."""
	@wraps(func)
	def wrapper(*args, **kwargs):
		owner = kwargs.get("owner")
		if owner is None:
			owner = request.form.get("user")
		if owner is None:
			# The owner could not be determined, so set it to be the current user. I don't think this is an authentication vulnerability.
			owner = User.cu()
		if owner == "public":
			if User.cu() == "admin":
				# Only the admin can run and edit public models
				return func(*args, **kwargs)
		else:
			if owner == User.cu() or User.cu() == "admin":
				# Only the model owner and admin can run and edit a user-owned model
				return func(*args, **kwargs)
		return redirect("/")
	return wrapper


###################################################
# MODEL FUNCTIONS
###################################################


@app.route("/model/<owner>/<modelName>")
@flask_login.login_required
@read_permission_function
def showModel(owner, modelName):
	''' Render a model template with saved data. '''
	modelType = get_model_metadata(owner, modelName).get('modelType', '')
	thisModel = getattr(models, modelType)
	return thisModel.renderTemplate(os.path.join(_omfDir, 'data', 'Model', owner, modelName), absolutePaths=False, datastoreNames=getDataNames())


@app.route("/newModel/<modelType>/<modelName>", methods=["POST","GET"])
@flask_login.login_required
@write_permission_function
def newModel(modelType, modelName):
	''' Create a new model with given name. '''
	modelDir = os.path.join(_omfDir, "data", "Model", User.cu(), modelName)
	thisModel = getattr(models, modelType)
	thisModel.new(modelDir)
	return redirect("/model/" + User.cu() + "/" + modelName)

@app.route("/runModel/", methods=["POST"])
@flask_login.login_required
@write_permission_function
def runModel():
	''' Start a model running and redirect to its running screen. '''
	pData = request.form.to_dict()
	modelModule = getattr(models, pData["modelType"])
	# Handle the user.
	if User.cu() == "admin" and pData["user"] == "public":
		user = "public"
	elif User.cu() == "admin" and pData["user"] != "public" and pData["user"] != "":
		user = pData["user"].replace('/','')
	else:
		user = User.cu()
	del pData["user"]
	# Handle the model name.
	modelName = pData["modelName"]
	del pData["modelName"]
	modelDir = os.path.join(_omfDir, "data", "Model", user, modelName)
	# File upload handling
	# print(f"FILES?, length={len(request.files)} and {request.files}")
	if len( request.files ) > 0:
		for file_field, file in request.files.items():
			safeFileName = secure_filename( file.filename )
			safeFileField = secure_filename( file_field )
			if safeFileName != '':
				file_save_path = os.path.join(modelDir, safeFileField)
				fileSavePathAsPath = Path(file_save_path)
				if fileSavePathAsPath.resolve().parent != Path(modelDir):
					raise Exception("runModel() :: FilePathParent != modelDir")
				file.save(file_save_path)
			#else:
			#	print( "File not found: ", file_field, "file info: ", file)
	# Get existing model viewers and add them to pData if they exist, then write pData to update allInputData.json
	filepath = os.path.join(modelDir, "allInputData.json")
	with locked_open(filepath, 'r+') as f:
		model_metadata = json.load(f)
		viewers = model_metadata.get('viewers')
		if viewers is not None:
			pData['viewers'] = viewers
		f.seek(0)
		f.truncate(0)
		json.dump(pData, f, indent=4)
	# Start a background process and return.
	modelModule.run(modelDir)
	time.sleep(2)
	return redirect("/model/" + user + "/" + modelName)


@app.route("/cancelModel/", methods=["POST"])
@flask_login.login_required
@write_permission_function
def cancelModel():
	''' Cancel an already running model. '''
	pData = request.form.to_dict()
	modelModule = getattr(models, pData["modelType"])
	modelModule.cancel(os.path.join(_omfDir,"data","Model",pData["user"],pData["modelName"]))
	return redirect("/model/" + pData["user"] + "/" + pData["modelName"])


@app.route("/duplicateModel/<owner>/<modelName>/", methods=["POST"])
@flask_login.login_required
@read_permission_function
def duplicateModel(owner, modelName):
	newName = request.form.get("newName","")
	destination_path = os.path.join(_omfDir, 'data', 'Model', User.cu(), newName)
	shutil.copytree(os.path.join(_omfDir, 'data', 'Model', owner, modelName), destination_path)
	with locked_open(os.path.join(destination_path, 'allInputData.json')) as f:
		new_model_metadata = json.load(f)
	if new_model_metadata.get('viewers') is not None:
		del new_model_metadata['viewers']
	new_model_metadata['created'] = str(dt.datetime.now())
	with locked_open(os.path.join(destination_path, 'allInputData.json'), 'r+') as f:
		f.truncate(0)
		json.dump(new_model_metadata, f, indent=4)
	return redirect(url_for('showModel', owner=User.cu(), modelName=newName))


@app.route("/shareModel", methods=["POST"])
@flask_login.login_required
@write_permission_function
def shareModel():
	# Check for nonexistant users
	emails = list(set(request.form.getlist("email"))) if len(request.form.getlist("email")) != 0 else None
	if emails is not None:
		invalid_emails = [e for e in emails if e == User.cu() or e == 'admin' or not os.path.isfile(os.path.join(_omfDir, 'data', 'User', e + '.json'))]
		if len(invalid_emails) != 0:
			response = jsonify(invalid_emails)
			response.status_code = 400
			return response
	# Check the state of the model
	owner = request.form.get("user")
	model_name = request.form.get("modelName")
	status = models.__neoMetaModel__.getStatus(os.path.join(_omfDir, 'data', 'Model', owner, model_name))
	if status == 'running':
		return ("The model cannot be shared while it is running. Please wait until the model finishes running.", 409)
	# Load the list of old viewers
	model_metadata = get_model_metadata(owner, model_name)
	old_viewers = model_metadata.get("viewers")
	# If there are no new emails to add, and there are no old emails to remove, don't do anything
	if emails is not None or old_viewers is not None:
		if emails is not None:
			model_metadata["viewers"] = emails
		elif old_viewers is not None:
			del model_metadata["viewers"]
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, model_name, 'allInputData.json')
		with locked_open(filepath, 'r+') as f:
			f.truncate(0)
			json.dump(model_metadata, f, indent=4) # Could an email be a malicious string of code?
		# All viewers who previously had access to this model, but had that access revoked, must have their JSON file updated
		if old_viewers is not None:
			for v in old_viewers:
				if emails is None or v not in emails:
					revoke_viewership(owner, model_name, v)
		# All viewers who were newly granted access to this model must have their JSON file updated
		if emails is not None:
			for e in emails:
				grant_viewership(owner, model_name, e)
	response = jsonify(emails)
	response.status_code = 200
	return response


def revoke_viewership(owner, model_name, username):
	"""Given a model named <model_name> of <owner>, revoke the ability of <username> to view the model in the dashboard"""
	filepath = os.path.join(_omfDir, 'data', 'User', username + ".json")
	if os.path.isfile(filepath):
		with locked_open(filepath) as f:
			viewer_metadata = json.load(f)
		sharing_users = viewer_metadata.get("readonly_models")
		if sharing_users is not None:
			shared_models = sharing_users.get(owner)
			if shared_models is not None and model_name in shared_models:
				shared_models.remove(model_name)
				if len(shared_models) == 0:
					del sharing_users[owner]
				if len(sharing_users.keys()) == 0:
					del viewer_metadata["readonly_models"]
				with locked_open(filepath, 'r+') as f:
					f.truncate(0)
					json.dump(viewer_metadata, f)


def grant_viewership(owner, model_name, username):
	filepath = os.path.join(_omfDir, 'data', 'User', username + '.json')
	if os.path.isfile(filepath):
		with locked_open(filepath) as f:
			viewer_metadata = json.load(f)
		if viewer_metadata.get("readonly_models") is None:
			viewer_metadata["readonly_models"] = {}
		sharing_users = viewer_metadata.get("readonly_models")
		if sharing_users.get(owner) is None:
			sharing_users[owner] = []
		shared_models = sharing_users.get(owner)
		if model_name not in shared_models:
			shared_models.append(model_name) # Could model_name be a malicious string of code?
			with locked_open(filepath, 'r+') as f:
				f.truncate(0)
				json.dump(viewer_metadata, f, indent=4)


def get_model_metadata(owner, model_name):
	filepath = os.path.join(_omfDir, "data/Model", owner, model_name, "allInputData.json")
	with locked_open(filepath) as f:
		model_metadata = json.load(f)
	return model_metadata


@contextmanager
def locked_open(filepath, mode='r', timeout=180, **io_open_args):
	'''
	Open a file and lock it depending on the file access mode. An IOError will be raised if the lock cannot be acquired within the timeout. If the
	filepath does not exist, this function should thrown the exception upwards and not try to handle it
	'''
	# __enter__()
	if 'r' in mode and '+' not in mode:
		lock_mode = fcntl.LOCK_SH # LOCK_SH == 1
	else:
		lock_mode = fcntl.LOCK_EX # LOCK_EX == 2
	f = open(filepath, mode, **io_open_args)
	start_time = time.time()
	while True:
		try:
			fcntl.flock(f, lock_mode | fcntl.LOCK_NB)
			break
		except IOError as e:
			# Ignore any IOError regarding the resource being unavailabe, but raise any other IOError
			if e.errno != errno.EACCES and e.errno != errno.EAGAIN:
				raise
		if time.time() >= start_time + timeout:
			raise IOError("{timeout}-second file lock timeout reached. Either a file-locking operation is taking more than {timeout} seconds "
				"or there was a programmer error that would have resulted in deadlock.".format(timeout=timeout))
	yield f
	# __exit___()
	fcntl.flock(f, fcntl.LOCK_UN)
	f.close() 


###################################################
# FEEDER FUNCTIONS
###################################################


def writeToInput(workDir, entry, key):
	try:
		with locked_open(os.path.join(workDir, 'allInputData.json'), 'r+') as f:
			allInput = json.load(f)
			allInput[key] = entry
			f.seek(0)
			f.truncate(0)
			json.dump(allInput, f, indent=4)
	except:
		return "Failed"


@app.route("/gridEdit/<owner>/<modelName>/<feederNum>")
@flask_login.login_required
@read_permission_function
def feederGet(owner, modelName, feederNum):
	''' Editing interface for feeders. '''
	allData = getDataNames()
	yourFeeders = allData["feeders"]
	publicFeeders = allData["publicFeeders"]
	feederName = get_model_metadata(owner, modelName).get('feederName' + str(feederNum))
	# MAYBEFIX: fix modelFeeder
	return render_template(
		"gridEdit.html", feeders=yourFeeders, publicFeeders=publicFeeders, modelName=modelName, feederName=feederName,
		feederNum=feederNum, ref=request.referrer, is_admin=User.cu()=="admin", modelFeeder=False,
		public=owner=="public", currUser=User.cu(), owner=owner
	)

@app.route("/network/<owner>/<modelName>/<networkNum>")
@flask_login.login_required
@read_permission_function
def networkGet(owner, modelName, networkNum):
	''' Editing interface for networks. '''
	allData = getDataNames()
	yourNetworks = allData["networks"]
	publicNetworks = allData["networks"]
	networkName = get_model_metadata(owner, modelName).get('networkName1')
	network_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, networkName + '.omt')
	with locked_open(network_filepath) as f:
		data = json.load(f)
	networkData = json.dumps(data)
	#Currently unused template variables: networks, publicNetworks, currUser, 
	return render_template("transEdit.html", networks=yourNetworks, publicNetworks=publicNetworks, modelName=modelName, networkData=networkData,
		networkName=networkName, networkNum=networkNum, ref=request.referrer, is_admin=User.cu()=="admin", public=owner=="public",
		currUser=User.cu(), owner=owner)


@app.route('/feeder/<owner>/<modelName>/<feeder_num>/test')
@app.route('/feeder/<owner>/<modelName>/<feeder_num>')
@flask_login.login_required
@read_permission_function
def distribution_get(owner, modelName, feeder_num):
	'''Render the editing interface for distribution networks.'''
	feeder_dict = get_model_metadata(owner, modelName)
	feeder_name = feeder_dict.get('feederName' + str(feeder_num))
	feeder_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, feeder_name + '.omd')
	with locked_open(feeder_filepath) as f:
		data = json.load(f)
	feeder = json.dumps(data)
	jasmine = spec = None
	if request.path.endswith('/test') and User.cu() == 'admin':
		from omf.static.testFiles.test_distNetVizInterface import helper
		tests = helper.load_test_files(['spec_distNetVizInterface.js'])
		jasmine = tests['jasmine']
		spec = tests['spec']
	all_data = getDataNames()
	user_feeders = all_data['feeders']
	# Must get rid of the 'u' for unicode strings before passing the strings to JavaScript
	for dictionary in user_feeders:
		dictionary['model'] = str(dictionary['model'])
		dictionary['name'] = str(dictionary['name'])
	public_feeders = all_data['publicFeeders']
	show_file_menu = User.cu() == owner or User.cu() == 'admin'
	dssSchema = True if data.get('syntax','') == 'DSS' else False
	if dssSchema:
		component_json = get_components(schema='dss')
	else:
		component_json = get_components()
	return render_template(
		'distNetViz.html', thisFeederData=feeder, thisFeederName=feeder_name, thisFeederNum=feeder_num,
		thisModelName=modelName, thisOwner=owner, components=component_json, jasmine=jasmine, spec=spec,
		publicFeeders=public_feeders, userFeeders=user_feeders, showFileMenu=show_file_menu, currentUser=User.cu(), dssSchema=dssSchema
	)

@app.route('/rawTextEdit/<owner>/<modelName>/<fileName>/test')
@app.route('/rawTextEdit/<owner>/<modelName>/<fileName>')
@flask_login.login_required
@read_permission_function
def distribution_text_get(owner, modelName, fileName):
	'''Render the raw text editing interface for distribution networks.'''
	file_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, fileName)
	try:
		with locked_open(file_filepath) as f:
			data = f.read()
	except FileNotFoundError:
		with locked_open(os.path.join(_omfDir, 'solvers', 'opendss', fileName)) as f:
			data = f.read()
	file = data
	jasmine = spec = None
	if request.path.endswith('/test') and User.cu() == 'admin':
		from omf.static.testFiles.test_distNetVizInterface import helper
		tests = helper.load_test_files(['spec_distNetVizInterface.js'])
		jasmine = tests['jasmine']
		spec = tests['spec']
	all_data = getDataNames()
	user_files = all_data['feeders']
	# Must get rid of the 'u' for unicode strings before passing the strings to JavaScript
	for dictionary in user_files:
		dictionary['model'] = str(dictionary['model'])
		dictionary['name'] = str(dictionary['name'])
	public_files = all_data['publicFeeders']
	show_file_menu = User.cu() == owner or User.cu() == 'admin'
	return render_template(
		'distText.html', thisFileData=file, thisFileName=fileName,
		thisModelName=modelName, thisOwner=owner, jasmine=jasmine, spec=spec,
		publicFiles=public_files, userFiles=user_files, showFileMenu=show_file_menu, currentUser=User.cu()
	)


@app.route("/getComponents/")
@app.route("/getComponents/<schema>")
@flask_login.login_required
def get_components(schema='gld'):
	if schema == 'dss':
		directory = os.path.join(_omfDir, 'data', 'ComponentDss')
	else: #schema == 'gld'
		directory = os.path.join(_omfDir, 'data', 'Component')
	components = {}
	for dirpath, dirnames, file_names in os.walk(directory):
		for name in file_names:
			if name.endswith(".json"):
				path = os.path.join(dirpath, name)
				with locked_open(path) as f:
					components[name[0:-5]] = json.load(f) # Load the file as a regular object into the dictionary
	return json.dumps(components) # Turn the dictionary of objects into a string


@app.route("/checkConversion/<modelName>/<owner>", methods=["POST","GET"])
@flask_login.login_required
@read_permission_function # Viewers can load a feeder, and all feeders check for ongoing conversions, so this route must have read permissions
def checkConversion(modelName, owner):
	"""
	If the path exists, then the conversion is ongoing and the client can't reload their browser yet. If the path does not exist, then either 1) the
	conversion hasn't started yet or 2) the conversion is finished because the ZPID.txt file is gone. If an error file exists, the the conversion
	failed and the client should be notified.
	"""
	print(modelName)
	# First check for error files
	for filename in ['gridError.txt', 'error.txt', 'weatherError.txt', 'matError.txt', 'rawError.txt']:
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename)
		if os.path.isfile(filepath):
			with locked_open(filepath) as f:
				errorString = f.read()
			return errorString
	# Check for process ID files AFTER checking for error files
	for filename in ["ZPID.txt", "APID.txt", "WPID.txt", "NPID.txt", "CPID.txt"]:
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename)
		if os.path.isfile(filepath):
			return jsonify(exists=True)
	return jsonify(exists=False)


@app.route("/milsoftImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def milsoftImport(owner):
	''' API for importing a milsoft feeder. '''
	modelName = request.form.get("modelName","")
	model_dir, error_filepath = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('', 'gridError.txt')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in safeListdir(model_dir):
		if filename.endswith(".glm") or filename.endswith(".std") or filename.endswith(".seq"):
			os.remove(os.path.join(model_dir, filename))
	if os.path.isfile(error_filepath):
		os.remove(error_filepath)
	feederName = str(request.form.get('feederNameM', 'feeder'))
	feederNum = request.form.get("feederNum",1)
	std_filepath, seq_filepath = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in (feederName + '.std', feederName + '.seq')]
	request.files.get('stdFile').save(std_filepath)
	request.files.get('seqFile').save(seq_filepath)
	importProc = Process(target=milImportBackground, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def milImportBackground(owner, modelName, feederName, feederNum):
	''' Function to run in the background for Milsoft import. '''
	try:
		std_filepath, seq_filepath, pid_filepath, feeder_filepath, model_dir, error_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in
				[feederName + '.std',
				feederName + '.seq',
				'ZPID.txt',
				feederName + '.omd',
				'', 'gridError.txt']
		]
		with open(std_filepath) as f:
			stdString = f.read()
		with open(seq_filepath) as f:
			seqString = f.read()
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		newFeeder = dict(**feeder.newFeederWireframe)
		newFeeder["tree"] = milToGridlab.convert(stdString, seqString)
		with locked_open(os.path.join(_omfDir, 'static', 'schedules.glm')) as schedFile:
			newFeeder['attachments'] = {'schedules.glm':schedFile.read()}
		with locked_open(feeder_filepath, 'w') as f:
			json.dump(newFeeder, f, indent=4)
		feederTree = newFeeder
		if len(feederTree['tree']) < 12:
			with locked_open(error_filepath, 'w') as errorFile:
				errorFile.write('milError')
		os.remove(pid_filepath)
		removeFeeder(owner, modelName, feederNum)
		writeToInput(model_dir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write("milError")


@app.route("/matpowerImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def matpowerImport(owner):
	''' API for importing a MATPOWER network. '''
	modelName = request.form.get('modelName', '')
	model_dir, con_file_path = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('', 'ZPID.txt')]
	error_paths = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('matError.txt', 'rawError.txt')]
	# Delete existing .m files to not clutter model.
	for filename in safeListdir(model_dir):
		if filename.endswith(".m"):
			os.remove(os.path.join(model_dir, filename))
	for error_path in error_paths:
		if os.path.isfile(error_path):
			os.remove(error_path)
	with locked_open(con_file_path, 'w') as conFile:
		conFile.write("WORKING")
	networkName = str(request.form.get('networkNameM', 'network1'))
	networkNum = request.form.get("networkNum", 1)
	network_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, networkName + '.m')
	request.files['matFile'].save(network_filepath)
	importProc = Process(target=matImportBackground, args=[owner, modelName, networkName, networkNum])
	importProc.start()
	return 'Success'


def matImportBackground(owner, modelName, networkName, networkNum):
	''' Function to run in the background for Matpower import. '''
	try:
		network_filepath, model_dir, pid_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in [networkName + '.m', '', 'ZPID.txt']
		]
		newNet = transmission.parse(network_filepath, filePath=True)
		transmission.layout(newNet)
		with locked_open(network_filepath, 'w') as f:
			json.dump(newNet, f, indent=4)
		os.rename(network_filepath, os.path.join(model_dir, networkName + '.omt'))
		os.remove(pid_filepath)
		removeNetwork(owner, modelName, networkNum)
		writeToInput(model_dir, networkName, 'networkName' + str(networkNum))
	except ValueError:
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'matError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('matError')
		os.remove(pid_filepath)
	except:
		os.remove(pid_filepath)

@app.route("/rawImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def rawImport(owner):
	''' API for importing a RAW network. '''
	modelName = request.form.get('modelName', '')
	model_dir, con_file_path = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('', 'ZPID.txt')]
	error_paths = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('matError.txt', 'rawError.txt')]
	# Delete existing .raw and .m files to not clutter model.
	for filename in safeListdir(model_dir):
		if filename.endswith(".raw") or filename.endswith(".m"):
			os.remove(os.path.join(model_dir, filename))
	for error_path in error_paths:
		if os.path.isfile(error_path):
			os.remove(error_path)
	with locked_open(con_file_path, 'w') as conFile:
		conFile.write("WORKING")
	networkName = str(request.form.get('networkNameR', 'network1'))
	networkNum = request.form.get("networkNum", 1)
	network_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, networkName + '.raw')
	request.files['rawFile'].save(network_filepath)
	importProc = Process(target=rawImportBackground, args=[owner, modelName, networkName, networkNum])
	importProc.start()
	return 'Success'

def rawImportBackground(owner, modelName, networkName, networkNum):
	''' Function to run in the background for Raw import. '''
	try:
		network_filepath, model_dir, pid_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in [networkName + '.raw', '', 'ZPID.txt']
		]
		newNet = transmission.parseRaw(network_filepath, filePath=True)
		transmission.layout(newNet)
		with locked_open(network_filepath, 'w') as f:
			json.dump(newNet, f, indent=4)
		os.rename(network_filepath, os.path.join(model_dir, networkName + '.omt'))
		os.remove(pid_filepath)
		removeNetwork(owner, modelName, networkNum)
		writeToInput(model_dir, networkName, 'networkName' + str(networkNum))
	except ValueError:
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'rawError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('rawError')
	except Exception:
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'rawError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('octaveError')
	finally:
		os.remove(pid_filepath)


@app.route("/gridlabdImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def gridlabdImport(owner):
	'''This function is used for gridlabdImporting'''
	modelName = request.form.get("modelName","")
	error_path, modelDir = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('gridError.txt', '')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in safeListdir(modelDir):
		if filename.endswith(".glm") or filename.endswith(".std") or filename.endswith(".seq"):
			os.remove(os.path.join(modelDir, filename))
	if os.path.isfile(error_path):
		os.remove(error_path)
	# Handle request objects
	feederName = str(request.form.get("feederNameG",""))
	glm_path = os.path.join(_omfDir, 'data', 'Model', owner, modelName, feederName + '.glm')
	request.files['glmFile'].save(glm_path)
	feederNum = request.form.get("feederNum", 1)
	importProc = Process(target=gridlabImportBackground, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def gridlabImportBackground(owner, modelName, feederName, feederNum):
	''' Function to run in the background for Gridlabd import. '''
	try:
		feeder_path, glm_path, modelDir, pid_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', feederName + '.glm', '', 'ZPID.txt']
		]
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		# Save .glm file to model folder
		with locked_open(glm_path) as glmFile:
			glmString = glmFile.read()
		newFeeder = dict(**feeder.newFeederWireframe)
		newFeeder["tree"] = feeder.parse(glmString, False)
		if not distNetViz.contains_valid_coordinates(newFeeder["tree"]):
			distNetViz.insert_coordinates(newFeeder["tree"])
		with locked_open(os.path.join(_omfDir, 'static', 'schedules.glm')) as schedFile:
			newFeeder["attachments"] = {"schedules.glm":schedFile.read()}
		with locked_open(feeder_path, 'w') as f: # Use 'w' mode because we're creating a new .omd file according to feederName
			json.dump(newFeeder, f, indent=4)
		os.remove(pid_filepath)
		removeFeeder(owner, modelName, feederNum)
		writeToInput(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'gridError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('glmError')


@app.route("/opendssImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def dssImport(owner):
	'''This function is used for opendss importing in distnetviz'''
	modelName = request.form.get("modelName","")
	error_path, modelDir = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('gridError.txt', '')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in safeListdir(modelDir):
		if filename.endswith(".dss"):
			os.remove(os.path.join(modelDir, filename))
	if os.path.isfile(error_path):
		os.remove(error_path)
	feederName = str(request.form.get("feederNameOpendss",""))
	feederNum = request.form.get("feederNum", 1)
	dss_path = os.path.join(_omfDir, 'data', 'Model', owner, modelName, feederName + '.dss')
	request.files['dssFile'].save(dss_path)
	importProc = Process(target=dssImportBackground, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def dssImportBackground(owner, modelName, feederName, feederNum):
	''' Function to run in the background for OpenDSS import. '''
	try:
		feeder_path, dss_path, modelDir, pid_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', feederName + '.dss', '', 'ZPID.txt']
		]
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		newFeeder = dict(**feeder.newFeederWireframe)
		newFeeder['syntax'] = 'DSS'
		dss_tree = dssConvert.dssToTree(dss_path)
		glm_tree = dssConvert.evilDssTreeToGldTree(dss_tree)
		newFeeder["tree"] = glm_tree
		if not distNetViz.contains_valid_coordinates(newFeeder["tree"]):
			distNetViz.insert_coordinates(newFeeder["tree"])
		with locked_open(feeder_path, 'w') as f: # Use 'w' mode because we're creating a new .omd file according to feederName
			json.dump(newFeeder, f, indent=4)
		os.remove(pid_filepath)
		# Remove a feeder from input data.
		allInput = get_model_metadata(owner, modelName)
		oldFeederName = str(allInput.get('feederName'+str(feederNum)))
		os.remove(os.path.join(modelDir, oldFeederName +'.omd'))
		allInput.pop("feederName" + str(feederNum))
		with locked_open(os.path.join(modelDir, 'allInputData.json'), 'r+') as f:
			f.truncate(0)
			json.dump(allInput, f, indent=4)
		writeToInput(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'gridError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('dssError')


@app.route("/scadaLoadshape/<owner>/<feederName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def scadaLoadshape(owner, feederName):
	#feederNum = request.form.get("feederNum",1)
	loadName = 'calibration'
	modelName = request.form.get("modelName","")
	# delete calibration csv, calibration folder, and error file if they exist
	filepaths = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('error.txt', 'calibration.csv', 'calibration')]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
		elif os.path.isdir(fp):
			shutil.rmtree(fp)
	request.files['scadaFile'].save(os.path.join(_omfDir, 'data', 'Model', owner, modelName, loadName + '.csv'))
	dirpath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'calibration', 'gridlabD')
	if not os.path.isdir(dirpath):
		os.makedirs(dirpath)
	# Run omf calibrate in background
	importProc = Process(target=backgroundScadaLoadshape, args=[owner, modelName, feederName, loadName])
	importProc.start()
	return 'Success'


def backgroundScadaLoadshape(owner, modelName, feederName, loadName):
	# heavy lifting background process/omfCalibrate and then deletes PID file
	try:
		pid_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'CPID.txt')
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		workDir, feederPath, scadaPath, modelDir = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ['calibration', feederName + '.omd', loadName + '.csv', '']
		]
		# TODO: parse the csv using .csv library, set simStartDate to earliest timeStamp, length to number of rows, units to difference between first 2
		# timestamps (which is a function in datetime library). We'll need a link to the docs in the import dialog and a short blurb saying how the CSV
		# should be built.
		with locked_open(scadaPath, newline='') as csv_file:
			#reader = csv.DictReader(csvFile, delimiter='\t')
			rows = [row for row in csv.DictReader(csv_file)]
			#reader = csv.DictReader(csvFile)
			#rows = [row for row in reader]
		firstDateTime = dt.datetime.strptime(rows[1]["timestamp"], "%m/%d/%Y %H:%M:%S")
		secondDateTime = dt.datetime.strptime(rows[2]["timestamp"], "%m/%d/%Y %H:%M:%S")
		csvLength = len(rows)
		units = (secondDateTime - firstDateTime).total_seconds()
		if abs(units/3600) == 1.0:
			simLengthUnits = 'hours'
		simDate = firstDateTime
		simStartDate = {"Date":simDate, "timeZone":"PST"}
		simLength = csvLength
		solver = 'FBS'
		calibrateError = (0.05, 5)
		trim = 5
		loadModelingScada.omfCalibrate(workDir, feederPath, scadaPath, simStartDate, simLength, simLengthUnits, solver, calibrateError, trim)
		# move calibrated file to model folder, old omd files are backedup
		if feederPath.endswith('.omd'):
			os.rename(feederPath, feederPath + '.backup')
		os.rename(os.path.join(workDir, 'calibratedFeeder.omd'), feederPath)
		# shutil.move(workDir+"/"+feederFileName, modelDirec)
		os.remove(pid_filepath)
	except Exception as error:
		#errorString = ''.join(error)
		with locked_open(os.path.join(modelDir, 'error.txt'), 'w') as errorFile:
		 	errorFile.write('The CSV used is incorrectly formatted. Please refer to the OMF Wiki for CSV formatting information. '
				'The Wiki can be access by clicking the Help button on the toolbar.')


@app.route("/loadModelingAmi/<owner>/<feederName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def loadModelingAmi(owner, feederName):
	#feederNum = request.form.get('feederNum', 1)
	loadName = 'ami'
	modelName = request.form.get('modelName', '')
	filepaths = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('amiError.txt', 'amiLoad.csv')]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
	ami_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, loadName + '.csv')
	request.files['amiFile'].save(ami_filepath)
	importProc = Process(target=backgroundLoadModelingAmi, args=[owner, modelName, feederName, loadName])
	importProc.start()
	return 'Success'


def backgroundLoadModelingAmi(owner, modelName, feederName, loadName):
	try:
		pid_filepath, ami_filepath, omdPath, outDir, error_filepath = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in 
			['APID.txt', loadName + '.csv', feederName + '.omd', 'amiOutput', 'error.txt']
		]
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		loadModelingAmi.writeNewGlmAndPlayers(omdPath, ami_filepath, outDir)
		os.remove(pid_filepath)
	except Exception:
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write('amiError')


# TODO: Check if rename mdb files worked
@app.route("/cymeImport/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def cymeImport(owner):
	''' API for importing a cyme feeder. '''
	modelName = request.form.get("modelName","")
	error_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, 'gridError.txt')
	if os.path.isfile(error_filepath):
		os.remove(error_filepath)
	feederNum = request.form.get("feederNum",1)
	feederName = str(request.form.get("feederNameC",""))
	mdbFileObject = request.files["mdbNetFile"]
	mdb_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, feederName + '.mdb')
	mdbFileObject.save(mdb_filepath)
	print(mdbFileObject.filename)
	importProc = Process(target=cymeImportBackground, args=[owner, modelName, feederNum, feederName])
	importProc.start()
	return 'Success'


def cymeImportBackground(owner, modelName, feederNum, feederName):
	''' Function to run in the background for Milsoft import. '''
	try:
		pid_filepath, error_filepath, mdb_filepath, feeder_filepath, modelDir = [os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in 
			['ZPID.txt', 'gridError.txt', feederName + '.mdb', feederName + '.omd', '']
		]
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		newFeeder = dict(**feeder.newFeederWireframe)
		newFeeder["tree"] = cymeToGridlab.convertCymeModel(mdb_filepath, modelDir)
		with locked_open(os.path.join(_omfDir, 'static', 'schedules.glm')) as schedFile:
			newFeeder["attachments"] = {"schedules.glm": schedFile.read()}
		# Use 'w' mode becuase the feederName is the name of a completely NEW feeder file
		with locked_open(feeder_filepath, 'w') as f: 
			json.dump(newFeeder, f, indent=4)
		os.remove(pid_filepath)
		removeFeeder(owner, modelName, feederNum) # remove the old feeder file that had the same feeder number
		writeToInput(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception:
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write('cymeError')


@app.route("/newSimpleFeeder/<owner>/<modelName>/<feederNum>/<writeInput>", methods=["POST", "GET"])
@flask_login.login_required
@write_permission_function
def newSimpleFeeder(owner, modelName, feederNum=1, writeInput=False, feederName='feeder1'):
	modelDir = os.path.join(_omfDir, "data", "Model", owner, modelName)
	for i in range(2,6):
		if not os.path.isfile(os.path.join(modelDir, feederName + '.omd')):
			with open(os.path.join(_omfDir, 'static', 'SimpleFeeder.json')) as f:
				feeder_string = f.read()
			with locked_open(os.path.join(modelDir, feederName + '.omd'), 'w') as f:
				f.write(feeder_string)
			break
		else:
			feederName = 'feeder' + str(i)
	if writeInput:
		writeToInput(modelDir, feederName, 'feederName' + str(feederNum))
	return 'Success'


@app.route("/newSimpleNetwork/<owner>/<modelName>/<networkNum>/<writeInput>", methods=["POST", "GET"])
@flask_login.login_required
@write_permission_function
def newSimpleNetwork(owner, modelName, networkNum=1, writeInput=False, networkName='network1'):
	modelDir = os.path.join(_omfDir, "data", "Model", owner, modelName)
	for i in range(2, 6):
		if not os.path.isfile(os.path.join(modelDir, networkName + '.omt')):
			with open(os.path.join(_omfDir, 'static', 'SimpleNetwork.json')) as f:
				network_string = f.read()
			with locked_open(os.path.join(modelDir, networkName + '.omt'), 'w') as f:
				f.write(network_string)
			break
		else:
			networkName = 'network' + str(i)
	if writeInput:
		writeToInput(modelDir, networkName, 'networkName' + str(networkNum))
	return 'Success'


@app.route("/newBlankFeeder/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def newBlankFeeder(owner):
	'''This function is used for creating a new blank feeder.'''
	modelName = request.form.get("modelName","")
	feederName = str(request.form.get("feederNameNew"))
	feederNum = request.form.get("feederNum",1)
	if feederName == '': feederName = 'feeder'
	modelDir = os.path.join(_omfDir, "data","Model", owner, modelName)
	try:
		os.remove("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt")
		print("removed, ", ("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt"))
	except: pass
	removeFeeder(owner, modelName, feederNum)
	newSimpleFeeder(owner, modelName, feederNum, False, feederName)
	writeToInput(modelDir, feederName, 'feederName'+str(feederNum))
	if request.form.get("referrer") == "distribution":
		return redirect(url_for("distribution_get", owner=owner, modelName=modelName, feeder_num=feederNum))
	return redirect(url_for('feederGet', owner=owner, modelName=modelName, feederNum=feederNum))

# @app.route("/newBlankFile/<owner>", methods=["POST"])
# @flask_login.login_required
# @write_permission_function
# def newBlankFile(owner):
# 	'''This function is used for creating a new blank feeder.'''
# 	modelName = request.form.get("modelName","")
# 	fileName = str(request.form.get("fileNameNew"))
# 	fileNum = request.form.get("fileNum",1)
# 	if fileName == '': fileName = 'feeder'
# 	modelDir = os.path.join(_omfDir, "data","Model", owner, modelName)
# 	try:
# 		os.remove("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt")
# 		print("removed, ", ("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt"))
# 	except: pass
# 	removeFeeder(owner, modelName, feederNum)
# 	removeFile(owner, modelName, fileNum)
# 	newSimpleFeeder(owner, modelName, feederNum, False, feederName)
# 	newSimpleFile(owner, modelName, fileNum, False, fileName)
# 	writeToInput(modelDir, feederName, 'feederName'+str(feederNum))
# 	writeToInput(modelDir, fileName, 'feederName'+str(fileNum))
# 	if request.form.get("referrer") == "distribution":
# 		return redirect(url_for("distribution_text_get", owner=owner, modelName=modelName, file_num=fileNum))
# 	return redirect(url_for('fileGet', owner=owner, modelName=modelName, feederNum=feederNum))


@app.route("/newBlankNetwork/<owner>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def newBlankNetwork(owner):
	'''This function is used for creating a new blank network.'''
	modelName = request.form.get("modelName","")
	networkName = str(request.form.get("networkNameNew"))
	networkNum = request.form.get("networkNum",1)
	if networkName == '': networkName = 'network1'
	modelDir = os.path.join(_omfDir, "data","Model", owner, modelName)
	try:
		os.remove("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt")
		print("removed, ", ("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt"))
	except: pass
	removeNetwork(owner, modelName, networkNum)
	newSimpleNetwork(owner, modelName, networkNum, False, networkName)
	writeToInput(modelDir, networkName, 'networkName'+str(networkNum))
	return redirect(url_for('networkGet', owner=owner, modelName=modelName, networkNum=networkNum))


@app.route("/feederData/<owner>/<modelName>/<feederName>/")
@app.route("/feederData/<owner>/<modelName>/<feederName>/<modelFeeder>")
@flask_login.login_required
@read_permission_function
def feederData(owner, modelName, feederName, modelFeeder=False):
	#MAYBEFIX: fix modelFeeder capability.
	filepath = os.path.join(_omfDir, 'data/Model', owner, modelName, feederName + '.omd')
	with locked_open(filepath) as feedFile:
		return feedFile.read()


@app.route("/networkData/<owner>/<modelName>/<networkName>/")
@flask_login.login_required
@read_permission_function
def networkData(owner, modelName, networkName):
	filepath = os.path.join(_omfDir, 'data/Model', owner, modelName, networkName + '.omt')
	with locked_open(filepath) as netFile:
		thisNet = json.load(netFile)
	return json.dumps(thisNet)
	# return jsonify(netFile.read())


@app.route("/saveFeeder/<owner>/<modelName>/<feederName>/<int:feederNum>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def saveFeeder(owner, modelName, feederName, feederNum):
	"""Save feeder data. Also used for cancelling a file import, file conversion, or feeder-load overwrite."""
	print("Saving feeder for:%s, with model: %s, and feeder: %s"%(owner, modelName, feederName))
	model_dir = os.path.join(_omfDir, "data/Model", owner, modelName)
	for filename in ["gridError.txt", "error.txt", "weatherError.txt"]:
		error_file = os.path.join(model_dir, filename)
		if os.path.isfile(error_file):
			try:
				os.remove(error_file)
			except FileNotFoundError as e:
				if e.errno ==2:
					# Tried to remove a nonexistant file
					pass
	# Do NOT cancel any PPID.txt or PID.txt processes.
	for filename in ["ZPID.txt", "APID.txt", "NPID.txt", "CPID.txt", "WPID.txt"]:
		pid_filepath = os.path.join(model_dir, filename)
		if os.path.isfile(pid_filepath):
			try:
				with locked_open(pid_filepath) as f:
					pid = f.read()
				os.remove(pid_filepath)
				os.kill(int(pid), signal.SIGTERM)
			except FileNotFoundError as e:
				if e.errno == 2:
					# Tried to open a nonexistent file. Presumably, some other process opened the used the pid file and deleted it before this process
					# could use it
					pass
				else:
					raise
			except ProcessLookupError as e:
				if e.errno == 3:
					# Tried to kill a process with a pid that doesn't map to an existing process.
					pass
				else:
					raise
	writeToInput(model_dir, feederName, 'feederName' + str(feederNum))
	payload = json.loads(request.form.get('feederObjectJson', '{}'))
	if isinstance(payload, dict) and payload.get('type') == 'FeatureCollection':
		payload = omf.geo.convert_featurecollection_to_omd(payload)
	feeder_file = os.path.join(model_dir, feederName + ".omd")
	if os.path.isfile(feeder_file):
		with locked_open(feeder_file, 'r+') as f:
			f.truncate(0)
			json.dump(payload, f, indent=4) # This route is slow only because this line takes forever. We want the indentation so we keep this line
	else:
		# The feeder_file should always exist, but just in case there was an error, we allow the recreation of the file
		with locked_open(feeder_file, 'w') as f:
			json.dump(payload, f, indent=4)
	return 'Success'

@app.route("/saveFile/<owner>/<modelName>/<fileName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def saveFile(owner, modelName, fileName):
	"""Save file data. Also used for cancelling a file import, file conversion, or file-load overwrite."""
	model_dir = os.path.join(_omfDir, "data/Model", owner, modelName)
	for filename in ["gridError.txt", "error.txt", "weatherError.txt"]:
		error_file = os.path.join(model_dir, filename)
		if os.path.isfile(error_file):
			try:
				os.remove(error_file)
			except FileNotFoundError as e:
				if e.errno ==2:
					# Tried to remove a nonexistant file
					pass
	# Do NOT cancel any PPID.txt or PID.txt processes.
	for filename in ["ZPID.txt", "APID.txt", "NPID.txt", "CPID.txt", "WPID.txt"]:
		pid_filepath = os.path.join(model_dir, filename)
		if os.path.isfile(pid_filepath):
			try:
				with locked_open(pid_filepath) as f:
					pid = f.read()
				os.remove(pid_filepath)
				os.kill(int(pid), signal.SIGTERM)
			except FileNotFoundError as e:
				if e.errno == 2:
					# Tried to open a nonexistent file. Presumably, some other process opened the used the pid file and deleted it before this process
					# could use it
					pass
				else:
					raise
			except ProcessLookupError as e:
				if e.errno == 3:
					# Tried to kill a process with a pid that doesn't map to an existing process.
					pass
				else:
					raise
	writeToInput(model_dir, fileName, 'circuitFileNameDSS') # TODO: Incorporate other files, not just dss
	payload = request.form.get('fileContents', '')
	file_file = os.path.join(model_dir, fileName)
	if os.path.isfile(file_file):
		with locked_open(file_file, 'r+') as f:
			f.truncate(0)
			f.write(payload)
	else:
		# The file_file should always exist, but just in case there was an error, we allow the recreation of the file
		with locked_open(file_file, 'w') as f:
			f.write(payload)
	return 'Success'


@app.route("/saveNetwork/<owner>/<modelName>/<networkName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def saveNetwork(owner, modelName, networkName):
	''' Save network data. '''
	print("Saving network for:%s, with model: %s, and network: %s"%(owner, modelName, networkName))
	filepath = os.path.join(_omfDir, 'data/Model', owner, modelName, networkName + '.omt')
	payload = json.loads(request.form.get('networkObjectJson', '{}'))
	with locked_open(filepath, 'r+') as f:
		f.truncate(0)	
		json.dump(payload, f, indent=4)
	return 'Success'


@app.route("/renameFeeder/<owner>/<modelName>/<oldName>/<newName>/<feederNum>", methods=["GET", "POST"])
@flask_login.login_required
@write_permission_function
def renameFeeder(owner, modelName, oldName, newName, feederNum):
	''' rename a feeder. '''
	model_dir_path = os.path.join(_omfDir, "data/Model", owner, modelName)
	new_feeder_filepath = os.path.join(model_dir_path, newName + ".omd")
	old_feeder_filepath = os.path.join(model_dir_path, oldName + ".omd")
	if os.path.isfile(new_feeder_filepath) or not os.path.isfile(old_feeder_filepath):
		return "Failure"
	with locked_open(old_feeder_filepath, 'r+'):
		os.rename(old_feeder_filepath, new_feeder_filepath)
	writeToInput(model_dir_path, newName, 'feederName' + str(feederNum))
	return 'Success'


@app.route("/renameNetwork/<owner>/<modelName>/<oldName>/<networkName>/<networkNum>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def renameNetwork(owner, modelName, oldName, networkName, networkNum):
	''' rename a feeder. '''
	model_dir, new_network_filepath, old_network_filepath = [
		os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in ('', networkName + '.omt', oldName + '.omt')
	]
	if os.path.isfile(new_network_filepath) or not os.path.isfile(old_network_filepath):
		return "Failure"
	with locked_open(old_network_filepath, 'r+'):
		os.rename(old_network_filepath, new_network_filepath)
	writeToInput(model_dir, networkName, 'networkName' + str(networkNum))
	return 'Success'

def removeFeeder(owner, modelName, feederNum, feederName=None):
	'''Remove a feeder from input data.'''
	try:
		allInput = get_model_metadata(owner, modelName)
		modelDir = os.path.join(_omfDir, 'data', 'Model', owner, modelName)
		try:
			feederName = str(allInput.get('feederName'+str(feederNum)))
			os.remove(os.path.join(modelDir, feederName +'.omd'))
		except: 
			print("Couldn't remove feeder file in web.removeFeeder().")
		allInput.pop("feederName" + str(feederNum))
		with locked_open(os.path.join(modelDir, 'allInputData.json'), 'r+') as f:
			f.truncate(0)
			json.dump(allInput, f, indent=4)
		return 'Success'
	except:
		return 'Failed'

@app.route("/removeFeeder/<owner>/<modelName>/<feederNum>", methods=["GET", "POST"])
@app.route("/removeFeeder/<owner>/<modelName>/<feederNum>/<feederName>", methods=["GET", "POST"])
@flask_login.login_required
@write_permission_function
def removeFeederRequest(owner, modelName, feederNum, feederName=None):
	''' Remove feeder from web.'''
	removeFeeder(owner, modelName, feederNum, feederName=None)

@app.route("/loadFeeder/<frfeederName>/<frmodelName>/<modelName>/<feederNum>/<frUser>/<owner>", methods=["GET", "POST"])
@flask_login.login_required
@write_permission_function
def loadFeeder(frfeederName, frmodelName, modelName, feederNum, frUser, owner):
	'''Load a feeder from one model to another.'''
	if frUser != "public":
		frUser = User.cu()
		frmodelDir = os.path.join(_omfDir, 'data/Model', frUser, frmodelName)
	elif frUser == "public":
		frmodelDir = os.path.join(_omfDir, 'static/publicFeeders')
	print("Entered loadFeeder with info: frfeederName %s, frmodelName: %s, modelName: %s, feederNum: %s"%(frfeederName, frmodelName, str(modelName), str(feederNum)))
	# I can't use shutil.copyfile() becasue I need locks on the source and destination file
	#shutil.copyfile(os.path.join(frmodelDir, frfeederName + '.omd'), os.path.join(modelDir, feederName + '.omd'))
	with locked_open(os.path.join(frmodelDir, frfeederName + '.omd')) as inFeeder:
		feeder_string = inFeeder.read()
	modelDir = os.path.join(_omfDir, 'data/Model', owner, modelName)
	feederName = get_model_metadata(owner, modelName).get('feederName' + str(feederNum))
	with locked_open(os.path.join(modelDir, feederName + '.omd'), 'r+') as outFile:
		outFile.truncate(0)
		outFile.write(feeder_string)
	if request.form.get("referrer") == "distribution":
		return redirect(url_for("distribution_get", owner=owner, modelName=modelName, feeder_num=feederNum))
	return redirect(url_for('feederGet', owner=owner, modelName=modelName, feederNum=feederNum))

@app.route("/loadFile/<frfileName>/<frmodelName>/<modelName>/<fileNum>/<frUser>/<owner>", methods=["GET", "POST"])
@flask_login.login_required
@write_permission_function
def loadFile(frfileName, frmodelName, modelName, fileNum, frUser, owner):
	'''Load a file from one model to another.'''
	if frUser != "public":
		frUser = User.cu()
		frmodelDir = os.path.join(_omfDir, 'data/Model', frUser, frmodelName)
	elif frUser == "public":
		frmodelDir = os.path.join(_omfDir, 'solvers/opendss')
	print("Entered loadFile with info: frfileName %s, frmodelName: %s, modelName: %s, fileNum: %s"%(frfileName, frmodelName, str(modelName), str(fileNum)))
	# I can't use shutil.copyfile() becasue I need locks on the source and destination file
	#shutil.copyfile(os.path.join(frmodelDir, frfileName + '.omd'), os.path.join(modelDir, fileName + '.omd'))
	# with locked_open(os.path.join(frmodelDir, frfileName + '.dss')) as inFile:
	with locked_open(os.path.join(frmodelDir, frfileName)) as inFile:
		file_string = inFile.read()
	modelDir = os.path.join(_omfDir, 'data/Model', owner, modelName)
	fileName = get_model_metadata(owner, modelName).get('fileName' + str(fileNum))
	# with locked_open(os.path.join(modelDir, fileName + '.dss'), 'r+') as outFile:
	with locked_open(os.path.join(modelDir, fileName), 'r+') as outFile:
		outFile.truncate(0)
		outFile.write(file_string)
	if request.form.get("referrer") == "distribution":
		return redirect(url_for("distribution_text_get", owner=owner, modelName=modelName, file_num=fileNum))
	return redirect(url_for("distribution_text_get", owner=owner, modelName=modelName, file_num=fileNum)) # TODO: Figure out where this should actually redirect
	# return redirect(url_for('fileGet', owner=owner, modelName=modelName, fileNum=fileNum))


@app.route("/cleanUpFeeders/<owner>/<modelName>", methods=["GET", "POST"])
@flask_login.login_required
@write_permission_function
def cleanUpFeeders(owner, modelName):
	'''Go through allInputData and fix feeder Name keys'''
	allInput = get_model_metadata(owner, modelName)
	feeders = {}
	feederKeys = ['feederName1', 'feederName2', 'feederName3', 'feederName4', 'feederName5']
	import pprint as pprint
	pprint.pprint(allInput)
	for key in feederKeys:
		feederName = allInput.get(key,'')
		if feederName != '':
			feeders[key] = feederName
		allInput.pop(key,None)
	for i,key in enumerate(sorted(feeders)):
		allInput['feederName'+str(i+1)] = feeders[key]
	pprint.pprint(allInput)
	modelDir = "./data/Model/" + owner + "/" + modelName
	with locked_open(modelDir + "/allInputData.json", "r+") as f:
		f.truncate(0)
		json.dump(allInput, f, indent=4)
	return redirect(url_for('showModel', owner=owner, modelName=modelName))


@app.route("/removeNetwork/<owner>/<modelName>/<networkNum>", methods=["GET","POST"])
@app.route("/removeNetwork/<owner>/<modelName>/<networkNum>/<networkName>", methods=["GET","POST"])
@flask_login.login_required
@write_permission_function
def removeNetwork(owner, modelName, networkNum, networkName=None):
	'''Remove a network from input data.'''
	try:
		allInput = get_model_metadata(owner, modelName)
		modelDir = os.path.join(_omfDir, "data","Model", owner, modelName)
		try:
			networkName = str(allInput.get('networkName'+str(networkNum)))
			os.remove(os.path.join(modelDir, networkName +'.omt'))
		except: 
			print("Couldn't remove network file in web.removeNetwork().")
		allInput.pop("networkName"+str(networkNum))
		with locked_open(modelDir + "/allInputData.json", 'r+') as f:
			f.truncate(0)
			json.dump(allInput, f, indent=4)
		return 'Success'
	except:
		return 'Failed'


@app.route("/climateChange/<owner>/<feederName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def climateChange(owner, feederName):
	model_name = request.form.get('modelName')
	# Remove files that could be left over from a previous run
	filepaths = [
		os.path.join(_omfDir, 'data', 'Model', owner, model_name, filename) for filename in ['error.txt', 'weatherAirport.csv', 'uscrn-weather-data.csv']
	]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
	# Don't bother writing WPID.txt here because /checkConversion doesn't distinguish between non-started processes and non-existant processes
	importOption = request.form.get('climateImportOption')
	zipCode = request.form.get('zipCode')
	station = request.form.get("uscrnStation")
	year_str = request.form.get("uscrnYear")
	importProc = Process(target=backgroundClimateChange, args=[owner, model_name, feederName, importOption, zipCode, station, year_str])
	importProc.start()
	return "Success"


def backgroundClimateChange(owner, modelName, feederName, importOption, zipCode, station, year_str):
	try:
		omdPath, pid_filepath, error_filepath = [
			os.path.join(_omfDir, 'data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', 'WPID.txt', 'error.txt']
		]
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		if importOption is None:
			raise Exception("Invalid weather import option selected.")
		if importOption == "USCRNImport":
			try:
				year = int(year_str)
			except:
				raise Exception("Invalid year was submitted.")
			if station is None or len(station) == 0:
				raise Exception("Invalid station was submitted.")
			weather.attachHistoricalWeather(omdPath, year, station)
		elif importOption == 'tmyImport':
			# Old calibration logic. Preserve for the sake of the 'tmyImport' option
			with locked_open(omdPath) as inFile:
				feederJson = json.load(inFile)
			for key in feederJson['tree'].keys():
				if (feederJson['tree'][key].get('object') == 'climate') or (feederJson['tree'][key].get('name') == 'weatherReader'):
					del feederJson['tree'][key]
			for key in feederJson['attachments'].keys():
				if (key.endswith('.tmy2')) or (key == 'weatherAirport.csv'):
					del feederJson['attachments'][key]
			# Old tmy2 weather operation
			climateName = weather.zipCodeToClimateName(zipCode)
			tmyFilePath = 'data/Climate/' + climateName + '.tmy2'
			feederJson['tree'][feeder.getMaxKey(feederJson['tree'])+1] = {'object':'climate','name':'Climate','interpolate':'QUADRATIC', 'tmyfile':'climate.tmy2'}
			with locked_open(tmyFilePath) as tmyFile:
				feederJson['attachments']['climate.tmy2'] = tmyFile.read()
			with locked_open(omdPath, 'r+') as f:
				f.truncate(0)
				json.dump(feederJson, f, indent=4)
		try:
			os.remove(pid_filepath)
		except:
			pass
	except Exception as e:
		with locked_open(error_filepath, 'w') as errorFile:
			message = 'climateError' if len(e.args) == 0 else e.args[0]
			errorFile.write(message)


@app.route("/anonymize/<owner>/<feederName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def anonymize(owner, feederName):
	modelName = request.form.get('modelName')
	modelDir = 'data/Model/' + owner + '/' + modelName
	omdPath = modelDir + '/' + feederName + '.omd'
	# form variables
	nameOption = request.form.get('anonymizeNameOption')
	locOption = request.form.get('anonymizeLocationOption')
	new_center_coords = request.form.get('new_center_coords')
	translationRight = request.form.get('translateRight')
	translationUp = request.form.get('translateUp')
	rotation = request.form.get('rotate')
	shufPerc = request.form.get('shufflePerc')
	noisePerc = request.form.get('noisePerc')
	modifyLengthSize = request.form.get('modifyLengthSize')
	smoothLoadGen = request.form.get('smoothLoadGen')
	shuffleLoadGen = request.form.get('shuffleLoadGen')
	addNoise = request.form.get('addNoise')
	scale = request.form.get('scale')
	# start background process
	importProc = Process(target=backgroundAnonymize, args=[modelDir, omdPath, owner, modelName, nameOption, locOption, new_center_coords, translationRight, translationUp, rotation, shufPerc, noisePerc, modifyLengthSize, smoothLoadGen, shuffleLoadGen, addNoise, scale])
	importProc.start()
	return 'Success'


def backgroundAnonymize(modelDir, omdPath, owner, modelName, nameOption, locOption, new_center_coords, translationRight, translationUp, rotation, shufPerc, noisePerc, modifyLengthSize, smoothLoadGen, shuffleLoadGen, addNoise, scale):
	try:
		pid_filepath = os.path.join(_omfDir, "data/Model", owner, modelName, "NPID.txt")
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		with locked_open(omdPath, 'r') as inFile:
			inFeeder = json.load(inFile)
		# Name Option
		newNameKey = None
		if nameOption == 'pseudonymize':
			newNameKey = anonymization.distPseudomizeNames(inFeeder)
		elif nameOption == 'randomize':
			anonymization.distRandomizeNames(inFeeder)
		# Location Option
		if locOption == 'translation':
			#anonymization.distTranslateLocations(inFeeder, translationRight, translationUp, rotation)
			geo.insert_missing_nodes(inFeeder)
			geo.insert_wgs84_coordinates(inFeeder)
			geo.transform_wgs84_coordinates(inFeeder, new_center_coords, translationUp, translationRight, rotation)
		elif locOption == 'randomize':
			anonymization.distRandomizeLocations(inFeeder)
		elif locOption == 'forceLayout':
			#distNetViz.insert_coordinates(inFeeder["tree"])
			geo.insert_missing_nodes(inFeeder)
			geo.insert_wgs84_coordinates(inFeeder, force_layout=True, scale=scale)
		# Electrical Properties
		if modifyLengthSize == 'modifyLengthSize':
			anonymization.distModifyTriplexLengths(inFeeder)
			anonymization.distModifyConductorLengths(inFeeder)
		if smoothLoadGen == 'smoothLoadGen':
			anonymization.distSmoothLoads(inFeeder)
		if shuffleLoadGen == 'shuffleLoadGen':
			anonymization.distShuffleLoads(inFeeder, shufPerc)
		if addNoise == 'addNoise':
			anonymization.distAddNoise(inFeeder, noisePerc)
		with locked_open(omdPath, 'r+') as f:
			f.truncate(0)
			json.dump(inFeeder, f, indent=4)
		os.remove(pid_filepath)
		if newNameKey:
			return newNameKey
	except Exception as error:
		with locked_open("data/Model/"+owner+"/"+modelName+"/gridError.txt", "w") as errorFile:
			errorFile.write('anonymizeError')


@app.route("/zillowHouses", methods=["POST"])
@flask_login.login_required
@write_permission_function
def zillow_houses():
	owner = request.form.get("owner")
	model_name = request.form.get("modelName")
	model_dir = os.path.join(_omfDir, "data/Model", owner, model_name)
	error_filepath = os.path.join(model_dir, "error.txt")
	if os.path.isfile(error_filepath):
		os.remove(error_filepath)
	payload_filepath = os.path.join(model_dir, "zillow_houses.json")
	if os.path.isfile(payload_filepath):
		os.remove(payload_filepath)
	# Write the ZPID.txt file now so there is no way the client will get a 404 when they check for an ongoing process. Process hasn't started yet though.
	zpid_filepath = os.path.join(model_dir, "ZPID.txt")
	with locked_open(zpid_filepath, 'w'):
		pass
	triplex_objects = json.loads(request.form.get("triplexObjects"))
	importProc = Process(target=background_zillow_houses, args=[model_dir, triplex_objects])
	importProc.start()
	return ""


def background_zillow_houses(model_dir, triplex_objects):
	try:
		pid_filepath = os.path.join(model_dir, "ZPID.txt")
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		zillow_houses = {}
		for obj in triplex_objects:
			house = loadModeling.get_zillow_configured_new_house(obj['latitude'], obj['longitude'])
			if house is None:
				# If a request for some house fails, get a random house
				house = loadModeling.get_random_new_house()
			zillow_houses[obj['key']] = house
			# The APIs we use require us to limit our requests to a maximum of 1 per second. Exceeding that throughput will get us IP banned faster.
			time.sleep(1)
		payload_filepath = os.path.join(model_dir, "zillow_houses.json")
		with locked_open(payload_filepath, 'w') as f:
			json.dump(zillow_houses, f)
		os.remove(pid_filepath)
	except Exception as e:
		with locked_open(os.path.join(model_dir, "error.txt"), 'w') as error_file:
			message = 'zillowError' if len(e.args) == 0 else e.args[0]
			error_file.write(message)


@app.route("/checkZillowHouses", methods=["POST"])
@flask_login.login_required
@write_permission_function
def check_zillow_houses():
	owner = request.form.get("owner")
	model_name = request.form.get("modelName")
	model_dir = os.path.join(_omfDir, "data/Model", owner, model_name)
	if owner == User.cu() or "admin" == User.cu():
		error_filepath = os.path.join(model_dir, "error.txt")
		if os.path.isfile(error_filepath):
			with locked_open(error_filepath) as f:
				error_message = f.read()
			return (error_message, 500)
		pid_filepath = os.path.join(model_dir, "ZPID.txt")
		if os.path.isfile(pid_filepath):
			return ("", 202)
		payload_filepath = os.path.join(model_dir, "zillow_houses.json")
		if os.path.isfile(payload_filepath):
			with locked_open(payload_filepath) as f:
				data = json.load(f)
			return jsonify(data)
	abort(404)


@app.route("/anonymizeTran/<owner>/<networkName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def anonymizeTran(owner, networkName):
	modelName = request.form.get('modelName')
	modelDir = 'data/Model/' + owner + '/' + modelName
	omtPath = modelDir + '/' + networkName + '.omt'
	nameOption = request.form.get('anonymizeNameOption')
	locOption = request.form.get('anonymizeLocationOption')
	translationRight = request.form.get('translateRight')
	translationUp = request.form.get('translateUp')
	rotation = request.form.get('rotate')
	shufPerc = request.form.get('shufflePerc')
	noisePerc = request.form.get('noisePerc')
	shuffleLoadGen = request.form.get('shuffleLoadGen')
	addNoise = request.form.get('addNoise')
	importProc = Process(target=backgroundAnonymizeTran, args = [modelDir, omtPath, nameOption, locOption, translationRight, translationUp, rotation, shufPerc, noisePerc, shuffleLoadGen, addNoise])
	importProc.start()
	pid = str(importProc.pid)
	with locked_open(modelDir + '/TPPID.txt', 'w') as outFile:
		outFile.write(pid)
	return 'Success'


def backgroundAnonymizeTran(modelDir, omtPath, nameOption, locOption, translationRight, translationUp, rotation, shufPerc, noisePerc, shuffleLoadGen, addNoise):
	with locked_open(omtPath, 'r') as inFile:
		inNetwork = json.load(inFile)
	# Name Options
	if nameOption == 'pseudonymize':
		newBusKey = anonymization.tranPseudomizeNames(inNetwork)
	elif nameOption == 'randomize':
		anonymization.tranRandomizeNames(inNetwork)
	# Location Options
	if locOption == 'translation':
		anonymization.tranTranslateLocations(inNetwork, translationRight, translationUp, rotation)
	elif locOption == 'randomize':
		anonymization.tranRandomizeLocations(inNetwork)
	# Electrical Properties
	if shuffleLoadGen:
		anonymization.tranShuffleLoadsAndGens(inNetwork, shufPerc)
	if addNoise:
		anonymization.tranAddNoise(inNetwork, noisePerc)
	with locked_open(omtPath, 'w') as outFile:
		# I don't know if the outFile already exists or not, which is why I haven't switched to r+ and truncate()
		json.dump(inNetwork, outFile, indent=4)
	os.remove(modelDir + '/TPPID.txt')
	if newBusKey:
		return newBusKey


@app.route("/checkAnonymizeTran/<owner>/<modelName>", methods=["POST","GET"])
@flask_login.login_required
@write_permission_function
def checkAnonymizeTran(owner, modelName):
	pidPath = ('data/Model/' + owner + '/' + modelName + '/TPPID.txt')
	# print 'Check conversion status:', os.path.exists(pidPath), 'for path', pidPath
	# checks to see if PID file exists, if theres no PID file process is done.
	return jsonify(exists=os.path.exists(pidPath))


@app.route('/displayMap/<owner>/<modelName>/<feederNum>', methods=["GET"])
@flask_login.login_required
@read_permission_function
def displayOmdMap(owner, modelName, feederNum):
	'''API to render omd on a leaflet map using a new template '''
	feeder_dict = get_model_metadata(owner, modelName)
	feeder_name = feeder_dict.get('feederName' + str(feederNum))
	feeder_filepath = os.path.join(_omfDir, 'data', 'Model', owner, modelName, feeder_name + '.omd')
	with locked_open(feeder_filepath) as f:
		omd = json.load(f)
	omf.geo.insert_missing_nodes(omd)
	omf.geo.insert_wgs84_coordinates(omd) # Place coordinate-less OMDs in Lousiana
	feature_collection = omf.geo.convert_omd_to_featurecollection(omd)
	featureCollection = json.dumps(feature_collection)
	components_collection = omf.geo.get_component_featurecollection()
	componentsCollection = json.dumps(components_collection)
	# - The csrf token is automatically passed to all template
	all_data = getDataNames()
	user_feeders = all_data['feeders']
	# - Must get rid of the 'u' for unicode strings before passing the strings to JavaScript
	for dictionary in user_feeders:
		dictionary['model'] = str(dictionary['model'])
		dictionary['name'] = str(dictionary['name'])
	public_feeders = all_data['publicFeeders']
	show_file_menu = User.cu() == owner or User.cu() == 'admin'
	return render_template(
		'geoJson.html',
		featureCollection=featureCollection,
		componentsCollection=componentsCollection,
		thisOwner=owner,
		thisModelName=modelName,
		thisFeederName=feeder_name,
		thisFeederNum=feederNum,
		publicFeeders=public_feeders,
		userFeeders=user_feeders,
		currentUser=User.cu(),
		showFileMenu=json.dumps(show_file_menu),
		isOnline=json.dumps(True),
		showAddNewObjectsButton=json.dumps(True),
		showAttachmentsButton=json.dumps(True),
		showAddGeojsonButton=json.dumps(True))


def omdToGeoJson(feederName, modelDir):
	''' Function to run in the background for displaying omd on leaflet map, by converting omd to geojson. '''
	try:
		geojsonFile, feederFile, conFile = [os.path.join(modelDir, filename) for filename in (feederName + '.geojson', feederName + '.omd', 'ZPID.txt')]
		geojson = geo.omdGeoJson(feederFile)
		with locked_open(geojsonFile, 'w') as f:
			json.dump(geojson, f, indent=4)
		os.remove(conFile)
	except Exception as e:
		filepath = os.path.join(modelDir, 'error.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write(e)
		os.remove(conFile)

@app.route('/commsMap/<owner>/<modelName>/<feederNum>', methods=["GET"])
@flask_login.login_required
@read_permission_function
def commsMap(owner, modelName, feederNum):
	'''Function to render omc on a leaflet map using a new template '''
	#handle commsGeoJson.js load so it doesn't throw 500 error - this line is there to load geojson variable when not rendering with flask
	if feederNum == 'commsGeoJson.js':
		return ""
	else:
		feederDict = get_model_metadata(owner, modelName)
		feederName = feederDict.get('feederName' + str(feederNum))
		modelDir = os.path.join(_omfDir, "data","Model", owner, modelName)
		feederFile = os.path.join(modelDir, feederName + ".omc")
		with locked_open(feederFile) as commsGeoJson:
			geojson = json.load(commsGeoJson)
		return render_template('commsNetViz.html', geojson=geojson, owner=owner, modelName=modelName, feederNum=feederNum, feederName=feederName)


@app.route('/redisplayGrid', methods=["POST"])
@flask_login.login_required
def redisplayGrid():
	'''Redisplay comms grid on edits'''
	geoDict = request.get_json()
	nxG = comms.omcToNxg(geoDict)
	comms.clearFiber(nxG)
	comms.clearRFEdges(nxG)
	comms.setFiber(nxG)
	comms.setRF(nxG)
	comms.setFiberCapacity(nxG)
	comms.setRFEdgeCapacity(nxG)
	comms.calcBandwidth(nxG)
	#need to runs comms updates here
	geoJson = comms.graphGeoJson(nxG)
	return jsonify(newgeojson=geoJson)


@app.route('/saveCommsMap/<owner>/<modelName>/<feederName>/<feederNum>', methods=["POST"])
@flask_login.login_required
@write_permission_function
def saveCommsMap(owner, modelName, feederName, feederNum):
	try:
		geoDict = request.get_json()
		model_dir = os.path.join(_omfDir, 'data', 'Model', owner, modelName)
		comms.saveOmc(geoDict, model_dir, feederName)
		return jsonify(savemessage='Communications network saved')
	except:
		return jsonify(savemessage='Error saving communications network')


###################################################
# OTHER FUNCTIONS
###################################################

def _fast_input_scan(file_path):
	# quickly get key info from input data.
	keys = {'runTime':None, 'modelType':None, 'created':None}
	hits = 0
	with open(file_path, 'r') as file_data:
		for line in file_data:
			if hits == 3:
				break
			for key in keys:
				if key in line:
					keys[key] = line
					hits += 1
	for key in keys:
		val = str(keys[key])
		try:
			clean_val = re.findall('"(.*?)"', val)[1]
		except:
			clean_val = ''
		keys[key] = clean_val
	return keys

@app.route("/")
@flask_login.login_required
def root():
	''' Render the home screen of the OMF. '''
	# Gather object names.
	publicModels = [{"owner":"public","name":x} for x in safeListdir("data/Model/public/")]
	userModels = [{"owner":User.cu(), "name":x} for x in safeListdir("data/Model/" + User.cu())]
	allModels = publicModels + userModels
	# Get models that have been shared with this user
	filepath = os.path.join(_omfDir, "data/User", User.cu() + ".json")
	with locked_open(filepath) as f:
		user_metadata = json.load(f)
	sharing_users = user_metadata.get("readonly_models")
	if sharing_users is not None:
		shared_models = []
		for email, model_list in sharing_users.items():
			shared_models.extend([{"owner": email, "name": model_name} for model_name in model_list])
		allModels.extend(shared_models)
	# Allow admin to see all model instances.
	isAdmin = User.cu() == "admin"
	if isAdmin:
		allModels = [{"owner":owner,"name":mod} for owner in safeListdir("data/Model/")
			for mod in safeListdir("data/Model/" + owner)]
	# Grab metadata for model instances.
	for mod in allModels:
		modPath = "data/Model/" + mod["owner"] + "/" + mod["name"]
		key_vals = _fast_input_scan(modPath + '/allInputData.json')
		mod["runTime"] = key_vals.get("runTime","")
		mod["modelType"] = key_vals.get("modelType","")
		creation = key_vals.get("created","")
		try:
			mod["status"] = getattr(models, mod["modelType"]).getStatus(modPath)
			mod["created"] = creation[0:creation.rfind('.')]
			# mod["editDate"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(os.stat(modPath).st_ctime))
		except: # the model type was deprecated, so the getattr will fail.
			mod["created"] = creation
			mod["status"] = "stopped"
			mod["editDate"] = "N/A"
	allModels.sort(key=lambda x:x.get('created',''), reverse=True)
	# Get tooltips for model types.
	modelTips = {}
	for name in [x for x in dir(models) if not x.startswith('_')]:
		try:
			modelTips[name] = getattr(models, name).tooltip
		except:
			pass
	# Generate list of model types.
	modelNames = []
	for modelName in [x for x in dir(models) if not x.startswith('_')]:
		thisModel = getattr(models, modelName)
		hideFlag = thisModel.__dict__.get('hidden', False)
		#HACK: support for old underscore hiding.
		hideChar = modelName.startswith('_')
		if not(hideFlag or hideChar):
			modelNames.append(modelName)
	modelNames.sort()
	return render_template("home.html", models=allModels, current_user=User.cu(), is_admin=isAdmin, modelNames=modelNames, modelTips=modelTips)

@app.route("/delete/<objectType>/<owner>/<objectName>", methods=["POST"])
@flask_login.login_required
@write_permission_function
def delete(objectType, objectName, owner):
	''' Delete models or feeders. '''
	if objectType == "Feeder":
		feeder_filepath = os.path.join(_omfDir, 'data', 'Model', owner, objectName, 'feeder.omd')
		if os.path.isfile(feeder_filepath):
			os.remove(feeder_filepath)
		return redirect("/#feeders")
	elif objectType == "Model":
		filepath = os.path.join(_omfDir, "data/Model", owner, objectName, "allInputData.json")
		if os.path.isfile(filepath):
			model_metadata = get_model_metadata(owner, objectName)
			old_viewers = model_metadata.get("viewers")
			if old_viewers is not None:
				for v in old_viewers:
					revoke_viewership(owner, objectName, v)
			shutil.rmtree(os.path.join(_omfDir, 'data', 'Model', owner, objectName))
	return redirect("/")


@app.route("/downloadModelData/<owner>/<modelName>/<path:fullPath>")
@flask_login.login_required
@read_permission_function
def downloadModelData(owner, modelName, fullPath):
	pathPieces = fullPath.split('/')
	dirPath = "data/Model/"+owner+"/"+modelName+"/"+"/".join(pathPieces[0:-1])
	fileName = pathPieces[-1]
	if os.path.isdir(f'{dirPath}/{fileName}'):
		shutil.make_archive(f'{dirPath}/{fileName}', 'zip', f'{dirPath}/{fileName}')
		fileName =  pathPieces[-1] + '.zip'
	return send_from_directory(dirPath, fileName)

@app.route("/uniqObjName/<objtype>/<owner>/<name>")
@app.route("/uniqObjName/<objtype>/<owner>/<name>/<modelName>")
@flask_login.login_required
@read_permission_function # This route needs read permissions because duplicate model uses it
def uniqObjName(objtype, owner, name, modelName=False):
	"""Checks if a given object type/owner/name is unique. More like checks if a file exists on the server"""
	print("Entered uniqobjname", owner, name, modelName)
	path_prefix = os.path.join(_omfDir, 'data', 'Model', owner)
	if objtype == 'Model':
		path = os.path.join(path_prefix, name)
	elif objtype == 'Feeder':
		if name == 'feeder':
			return jsonify(exists=True)
		if owner != 'public':
			path = os.path.join(path_prefix, modelName, name + '.omd')
		else:
			path = os.path.join(_omfDir, 'static', 'publicFeeders', name + '.omd')
	elif objtype == 'Network':
		path = os.path.join(path_prefix, modelName, name + '.omt')
		if name == 'feeder':
			return jsonify(exists=True)
	elif objtype == 'circuitFile':
		if name == 'feeder':
			return jsonify(exists=True)
		if owner != 'public':
			# path = os.path.join(path_prefix, modelName, name + '.dss')
			path = os.path.join(path_prefix, modelName, name)
		else:
			# path = os.path.join(_omfDir, 'solvers', 'opendss', name + '.dss')
			path = os.path.join(_omfDir, 'solvers', 'opendss', name)
	return jsonify(exists=os.path.exists(path))


if __name__ == "__main__":
	if platform.system() == "Darwin":  # MacOS
		os.environ['no_proxy'] = '*' # Workaround for macOS fork behavior with multiprocessing and urllib.
		os.environ['NO_PROXY'] = '*' # Workaround for above in python3.
		import multiprocessing
		multiprocessing.set_start_method('forkserver') # Workaround for new Catalina exec/fork behavior
	template_files = ["templates/"+ x  for x in safeListdir("templates")]
	model_files = ["models/" + x for x in safeListdir("models")]
	print('App starting with gunicorn. Errors are going to omf.error.log.')
	appProc = Popen(['gunicorn', '-w', '5', '-b', '0.0.0.0:5001', '--preload', 'web:app','--worker-class=sync', '--access-logfile', 'omf.access.log', '--error-logfile', 'omf.error.log', '--capture-output','--timeout=100'])
	appProc.wait()
	# app.run(debug=True, host="0.0.0.0", port=5001, extra_files=template_files + model_files)