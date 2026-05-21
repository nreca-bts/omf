"""
Serve the OMF web application, including users, feeders, model runs, file management,
API routes, and deployment utilities.
"""

import json, os, hashlib, time, datetime as dt, shutil, csv, sys, platform, errno, io, signal, secrets, base64, hmac, binascii, gzip, collections
from contextlib import contextmanager
from multiprocessing import Process
from passlib.hash import pbkdf2_sha512
from functools import lru_cache, wraps
from flask import (Flask, send_from_directory, request, redirect, render_template, session, abort, jsonify, url_for, g, has_request_context)
import boto3
from jinja2 import Template
import markdown
import dateutil
from subprocess import Popen
import re
from urllib.parse import urlsplit
from werkzeug.local import LocalProxy
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

_omfDir = os.path.dirname(os.path.abspath(__file__))
app = Flask("web", template_folder=os.path.join(_omfDir, "templates"), static_folder=os.path.join(_omfDir, "static"))
URL = "http://www.omf.coop"

# Ensure HttpOnly flags on cookies (session + remember cookie)
# Explicit even if framework defaults cover session, to satisfy security review.
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_DURATION'] = dt.timedelta(days=7)  # Expire remember_token after 1 week

COMPRESS_MIN_SIZE = 500
COMPRESS_MIMETYPES = {
	'text/html',
	'text/css',
	'text/plain',
	'text/xml',
	'text/csv',
	'application/json',
	'application/javascript',
	'application/x-javascript',
	'application/xml',
	'image/svg+xml'
}

OMF_STATS_LOG_NAMES = ('omf.access.log', 'omf.error.log')
OMF_STATS_DEFAULT_LOG_LINES = 250
OMF_STATS_MAX_LOG_LINES = 1000


def _add_vary_header(response, value):
	"""
	Internal helper for web add vary header processing.
	"""
	current_vary = response.headers.get('Vary')
	if not current_vary:
		response.headers['Vary'] = value
		return
	if value.lower() not in [x.strip().lower() for x in current_vary.split(',')]:
		response.headers['Vary'] = current_vary + ', ' + value


def _is_compressible_mimetype(mimetype):
	"""
	Internal helper for web is compressible mimetype processing.
	"""
	return (
		mimetype.startswith('text/') or
		mimetype in COMPRESS_MIMETYPES or
		mimetype.endswith('+json') or
		mimetype.endswith('+xml')
	)


def _bounded_log_line_count():
	"""
	Internal helper for web bounded log line count processing.
	"""
	try:
		line_count = int(request.args.get('lines', OMF_STATS_DEFAULT_LOG_LINES))
	except (TypeError, ValueError):
		line_count = OMF_STATS_DEFAULT_LOG_LINES
	return max(1, min(line_count, OMF_STATS_MAX_LOG_LINES))


def _tail_log_file(log_name, line_count):
	"""
	Internal helper for web tail log file processing.
	"""
	log_path = os.path.join(_omfDir, log_name)
	log_info = {
		'name': log_name,
		'path': log_path,
		'lines': [],
		'exists': os.path.exists(log_path),
		'size': 0,
		'modified': None,
		'error': None
	}
	if not log_info['exists']:
		log_info['error'] = 'Log file not found.'
		return log_info
	try:
		stat = os.stat(log_path)
		log_info['size'] = stat.st_size
		log_info['modified'] = dt.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
		with open(log_path, 'r', encoding='utf-8', errors='replace') as log_file:
			log_info['lines'] = [line.rstrip('\n') for line in collections.deque(log_file, maxlen=line_count)]
	except OSError as e:
		log_info['error'] = str(e)
	return log_info


def _get_omf_stats_logs():
	"""
	Internal helper for web get omf stats logs processing.
	"""
	line_count = _bounded_log_line_count()
	return {
		'line_count': line_count,
		'max_line_count': OMF_STATS_MAX_LOG_LINES,
		'logs': [_tail_log_file(log_name, line_count) for log_name in OMF_STATS_LOG_NAMES]
	}


@app.after_request
def gzip_response(response):
	'''Gzip eligible responses without depending on flask-compress.'''
	if 'gzip' not in request.headers.get('Accept-Encoding', '').lower():
		return response
	if response.status_code < 200 or response.status_code in (204, 304):
		return response
	if response.direct_passthrough or response.is_streamed:
		return response
	if response.headers.get('Content-Encoding'):
		return response
	if not _is_compressible_mimetype(response.mimetype or ''):
		return response
	data = response.get_data()
	if len(data) < COMPRESS_MIN_SIZE:
		return response
	compressed = gzip.compress(data)
	if len(compressed) >= len(data):
		return response
	response.set_data(compressed)
	response.headers['Content-Encoding'] = 'gzip'
	response.headers['Content-Length'] = str(len(compressed))
	_add_vary_header(response, 'Accept-Encoding')
	return response


class _AnonymousUser:
	"""
	Represent  anonymous user data used by this OMF workflow.
	"""
	username = None
	is_authenticated = False
	is_active = False
	is_anonymous = True

	def get_id(self):
		"""
		Return the id needed by this workflow.
		"""
		return None


class _LoginManager:
	"""
	Represent  login manager data used by this OMF workflow.
	"""
	def __init__(self):
		"""
		Internal helper for web init processing.
		"""
		self.login_view = None
		self._user_callback = None

	def init_app(self, app):
		"""
		Implement init app behavior for _LoginManager instances.
		"""
		app.after_request(_update_remember_cookie)

	def user_loader(self, callback):
		"""
		Implement user loader behavior for _LoginManager instances.
		"""
		self._user_callback = callback
		return callback


def _login_cookie_secret():
	"""
	Internal helper for web login cookie secret processing.
	"""
	secret = app.secret_key or ''
	if isinstance(secret, bytes):
		return secret
	return str(secret).encode('utf-8')


def _encode_remember_cookie(user_id):
	"""
	Internal helper for web encode remember cookie processing.
	"""
	payload = base64.urlsafe_b64encode(str(user_id).encode('utf-8')).decode('ascii').rstrip('=')
	signature = hmac.new(_login_cookie_secret(), payload.encode('ascii'), hashlib.sha512).hexdigest()
	return payload + '|' + signature


def _decode_remember_cookie(cookie_value):
	"""
	Internal helper for web decode remember cookie processing.
	"""
	try:
		payload, signature = str(cookie_value).split('|', 1)
	except ValueError:
		return None
	expected = hmac.new(_login_cookie_secret(), payload.encode('ascii'), hashlib.sha512).hexdigest()
	if not secrets.compare_digest(signature, expected):
		return None
	try:
		padding = '=' * (-len(payload) % 4)
		return base64.urlsafe_b64decode((payload + padding).encode('ascii')).decode('utf-8')
	except (binascii.Error, UnicodeDecodeError):
		return None


def _remember_cookie_name():
	"""
	Internal helper for web remember cookie name processing.
	"""
	return app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')


def _remember_cookie_duration_seconds():
	"""
	Internal helper for web remember cookie duration seconds processing.
	"""
	duration = app.config.get('REMEMBER_COOKIE_DURATION', dt.timedelta(days=365))
	if isinstance(duration, dt.timedelta):
		return int(duration.total_seconds())
	return int(duration)


def _update_remember_cookie(response):
	"""
	Internal helper for web update remember cookie processing.
	"""
	action = session.pop('_remember', None)
	cookie_name = _remember_cookie_name()
	cookie_path = app.config.get('REMEMBER_COOKIE_PATH', '/')
	if action == 'set':
		user_id = session.get('_user_id')
		if user_id:
			response.set_cookie(
				cookie_name,
				_encode_remember_cookie(user_id),
				max_age=_remember_cookie_duration_seconds(),
				path=cookie_path,
				secure=request.is_secure,
				httponly=app.config.get('REMEMBER_COOKIE_HTTPONLY', True),
				samesite=app.config.get('REMEMBER_COOKIE_SAMESITE', 'Lax')
			)
	elif action == 'clear':
		response.delete_cookie(cookie_name, path=cookie_path)
	return response


def _get_current_user():
	"""
	Internal helper for web get current user processing.
	"""
	if not has_request_context():
		return _AnonymousUser()
	if hasattr(g, '_login_user'):
		return g._login_user
	user = None
	user_id = session.get('_user_id')
	if not user_id:
		remember_cookie = request.cookies.get(_remember_cookie_name(), '')
		user_id = _decode_remember_cookie(remember_cookie)
		if user_id:
			session['_user_id'] = user_id
		elif remember_cookie:
			session['_remember'] = 'clear'
	if user_id and login_manager._user_callback is not None:
		user = login_manager._user_callback(user_id)
	if user is None:
		session.pop('_user_id', None)
		if user_id:
			session['_remember'] = 'clear'
		user = _AnonymousUser()
	g._login_user = user
	return user


def _is_authenticated(user):
	"""
	Internal helper for web is authenticated processing.
	"""
	is_authenticated = user.is_authenticated
	if callable(is_authenticated):
		return is_authenticated()
	return bool(is_authenticated)


def login_user(user, remember=False):
	"""
	Perform login user processing for OMF helper-library workflows.
	"""
	user_id = user.get_id()
	if user_id is None:
		return False
	session['_user_id'] = str(user_id)
	session['_fresh'] = True
	g._login_user = user
	session['_remember'] = 'set' if remember else 'clear'
	return True


def logout_user():
	"""
	Perform logout user processing for OMF helper-library workflows.
	"""
	session.pop('_user_id', None)
	session.pop('_fresh', None)
	session['_remember'] = 'clear'
	g._login_user = _AnonymousUser()


def login_required(func):
	"""
	Perform login required processing for OMF helper-library workflows.
	"""
	@wraps(func)
	def decorated_view(*args, **kwargs):
		if _is_authenticated(current_user):
			return func(*args, **kwargs)
		if login_manager.login_view:
			next_url = request.full_path if request.query_string else request.path
			return redirect(url_for(login_manager.login_view, next=next_url))
		abort(401)
	return decorated_view


current_user = LocalProxy(_get_current_user)

PASSWORD_DIGEST_SECRET_ENV = 'OMF_PASSWORD_DIGEST_KEY'
PASSWORD_DIGEST_PREFIX = 'omf_pwd_v1$'
PASSWORD_HASH_PBKDF2_ROUNDS = 210000
PASSWORD_DIGEST_PBKDF2_ROUNDS = 200000
PASSWORD_DIGEST_SALT_BYTES = 16
PASSWORD_DIGEST_NONCE_BYTES = 16
PASSWORD_DIGEST_TAG_BYTES = 32
_PASSWORD_HASHER = pbkdf2_sha512.using(rounds=PASSWORD_HASH_PBKDF2_ROUNDS)


###################################################
# HELPER FUNCTIONS
###################################################


def _safe_list_dir(path):
	''' Helper function that returns [] for dirs that don't exist. Otherwise new users can cause exceptions. '''
	try: return [x for x in os.listdir(path) if not x.startswith(".")]
	except:	return []


def _get_data_names():
	''' Query the OMF datastore to get names of all objects.'''
	try:
		currUser = User.cu()
	except:
		currUser = "public"
	climates = [x[:-5] for x in _safe_list_dir("./data/Climate/")]
	feeders = []
	circuitFiles = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "data", "Model", currUser)):
		for fname in filenames:
			if fname.endswith('.omd') and fname != 'feeder.omd':
				feeders.append({'name': fname[:-4], 'model': dirpath.split('/')[-1]})
			# TODO: possibly expand circuit file editor to include more than just openDSS files
			elif fname.endswith('.dss') and fname != 'feeder.dss':
				# circuitFiles.append({'name': fname[:-4], 'model': dirpath.split('/')[-1]})
				circuitFiles.append({'name': fname, 'model': dirpath.split('/')[-1]})
	networks = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "scratch", "transmission", "outData")):
		for fname in filenames:
			if fname.endswith('.omt') and fname != 'feeder.omt':
				networks.append({'name': fname[:-4], 'model': 'DRPOWER'})
	# Public feeders too.
	publicFeeders = []
	for (dirpath, dirnames, filenames) in os.walk(os.path.join(_omfDir, "static", "publicFeeders")):
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
	"""
	Internal helper for web is same origin processing.
	"""
	origin = request.headers.get("Origin")
	if origin:
		return origin in ALLOWED_ORIGINS
	# Fallback to Referer (some clients may omit Origin)
	referer = request.headers.get("Referer", "")
	return any(referer.startswith(o + "/") for o in ALLOWED_ORIGINS)


def _get_request_csrf_token():
	'''Return a CSRF token supplied via header, form body, or JSON body.'''
	token = request.headers.get('X-CSRFToken') or request.headers.get('X-CSRF-Token')
	if token:
		return token
	token = request.form.get('_csrf_token')
	if token:
		return token
	if request.is_json:
		payload = request.get_json(silent=True)
		if isinstance(payload, dict):
			return payload.get('_csrf_token')
	return None


def _csrf_failure_response():
	'''Return a JSON error for AJAX/API requests, otherwise abort with 403.'''
	if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
		return jsonify(error='CSRF validation failed.'), 403
	abort(403)


@app.before_request
def only_same_origin():
	"""
	Perform only same origin processing for OMF helper-library workflows.
	"""
	if request.method in ("POST", "PUT", "PATCH", "DELETE"):
		if not _is_same_origin():
			abort(403)


class PathManager:
	'''Manages safe file paths and prevents CWE-22 Path Traversal.'''

	class PathTraversalError(Exception):
		pass

	def __init__(self, root):
		# Establish the absolute, resolved root jail
		"""
		Internal helper for web init processing.
		"""
		self._root = Path(root).resolve()

	_WINDOWS_RESERVED = frozenset(
		['CON', 'PRN', 'AUX', 'NUL'] +
		[f'COM{i}' for i in range(1, 10)] +
		[f'LPT{i}' for i in range(1, 10)]
	)
	_WINDOWS_ILLEGAL = set('<>:"|?*')

	def _sanitize_component(self, part):
		'''Sanitize a single path component: block traversal while preserving
		legitimate characters (spaces, _, @, parens, etc.).'''
		s = str(part) if part is not None else ""
		s = s.replace('\x00', '')
		s = ''.join(c for c in s if ord(c) < 128 and c not in self._WINDOWS_ILLEGAL)
		s = s.strip()
		if '/' in s or '\\' in s:
			raise self.PathTraversalError(f"Path separator in component: '{part}'")
		if s == '..' or s == '.':
			raise self.PathTraversalError(f"Traversal component: '{part}'")
		if s.startswith('.'):
			raise self.PathTraversalError(f"Leading dot in component: '{part}'")
		if s.split('.')[0].upper() in self._WINDOWS_RESERVED:
			raise self.PathTraversalError(f"Windows reserved name in component: '{part}'")
		return s

	def join(self, *parts):
		"""
		Implement join behavior for PathManager instances.
		"""
		full_path = self._root
		for p in parts:
			safe_p = self._sanitize_component(p)
			if not safe_p and (str(p) if p is not None else "").strip():
				raise self.PathTraversalError(f"Input '{p}' resulted in an empty or invalid filename.")
			if safe_p:
				full_path = full_path / safe_p
		# Normalize without following symlinks (resolve() breaks symlinked dirs)
		normalized = Path(os.path.normpath(str(full_path)))
		try:
			normalized.relative_to(self._root)
		except ValueError:
			raise self.PathTraversalError("Path traversal attempted: Final path escaped root directory.")
		return str(normalized)


@app.errorhandler(PathManager.PathTraversalError)
def _handle_pathtraversalerror(e):
	"""
	Internal helper for web handle pathtraversalerror processing.
	"""
	return 'Bad Request', 400


path_manager = PathManager(_omfDir)
docs_path_manager = PathManager(os.path.join(_omfDir, "docs"))
DOC_PATH_ALIASES = {
	"Models-~-flisr": "README",
	"Models-~-microgridPlan": "Models-~-microgridDesign",
	"Models-~-modelSkeleton": "Dev-~-How-to-Create-Your-First-Model-Type",
	"Models-~-solarDisagg": "Models-~-disaggregation"
}


def _normalize_doc_path(doc_path):
	'''Normalize old GitHub wiki page slugs to migrated markdown filenames.'''
	doc_path = (doc_path or "").strip("/")
	if doc_path == "":
		return "README"
	doc_path = doc_path.replace("Models:-~-", "Models-~-")
	doc_path = doc_path.replace("Models:-", "Models-~-")
	doc_path = doc_path.replace("Tools-~-", "Other-~-")
	if doc_path == "Home":
		return "README"
	if doc_path in DOC_PATH_ALIASES:
		return DOC_PATH_ALIASES[doc_path]
	return doc_path


def _safe_docs_path(doc_path):
	"""
	Internal helper for web safe docs path processing.
	"""
	path_pieces = [piece for piece in doc_path.split("/") if piece]
	return docs_path_manager.join(*path_pieces)


def _get_doc_candidates(doc_path):
	"""
	Internal helper for web get doc candidates processing.
	"""
	doc_path = _normalize_doc_path(doc_path)
	candidates = [doc_path]
	root, ext = os.path.splitext(doc_path)
	if ext == "":
		candidates.append(doc_path + ".md")
		if doc_path.endswith("2"):
			candidates.extend([doc_path[:-1], doc_path[:-1] + ".md"])
	candidates.append(os.path.join(doc_path, "README.md"))
	return candidates


def _resolve_doc_path(doc_path):
	"""
	Internal helper for web resolve doc path processing.
	"""
	for candidate in _get_doc_candidates(doc_path):
		try:
			full_path = _safe_docs_path(candidate)
		except PathManager.PathTraversalError:
			continue
		if os.path.isfile(full_path):
			return full_path
	return None


def _doc_title(markdown_text, source_path):
	"""
	Internal helper for web doc title processing.
	"""
	for line in markdown_text.splitlines():
		line = line.strip()
		if line.startswith("# "):
			return line[2:].strip()
	return os.path.splitext(os.path.basename(source_path))[0].replace("-~-", ": ").replace("-", " ")


def _render_markdown_doc(source_path):
	"""
	Internal helper for web render markdown doc processing.
	"""
	with open(source_path, "r", encoding="utf-8") as doc_file:
		markdown_text = doc_file.read()
	content = markdown.markdown(
		markdown_text,
		extensions=["extra", "sane_lists", "toc"],
		output_format="html5")
	return render_template("docs.html", title=_doc_title(markdown_text, source_path), content=content)


@lru_cache(maxsize=1)
def _get_valid_model_types():
	'''Return the set of valid model type names (computed once, cached).'''
	return frozenset(
		name for name in dir(models)
		if not name.startswith('_') and hasattr(getattr(models, name), 'new'))


def _get_model_module(model_type):
	'''Safely resolve a model module name, preventing CWE-470 unsafe reflection.'''
	if model_type not in _get_valid_model_types():
		abort(400)
	return getattr(models, model_type)


def _get_model_metadata(owner, model_name):
	"""
	Internal helper for web get model metadata processing.
	"""
	filepath = path_manager.join("data", "Model", owner, model_name, "allInputData.json")
	with locked_open(filepath) as f:
		model_metadata = json.load(f)
	return model_metadata


###################################################
# AUTHENTICATION AND USER FUNCTIONS
###################################################


def _get_password_digest_secret():
	'''Return the password-digest encryption secret from runtime config, or None if encryption is disabled. '''
	configured_secret = os.environ.get(PASSWORD_DIGEST_SECRET_ENV) or globals().get('PASSWORD_DIGEST_KEY')
	if configured_secret:
		return str(configured_secret).encode('utf-8')
	return None


def _password_digest_encryption_enabled():
	"""
	Internal helper for web password digest encryption enabled processing.
	"""
	return _get_password_digest_secret() is not None


def _is_encrypted_password_digest(password_digest):
	"""
	Internal helper for web is encrypted password digest processing.
	"""
	return isinstance(password_digest, str) and password_digest.startswith(PASSWORD_DIGEST_PREFIX)


def _derive_password_digest_keys(salt):
	"""
	Internal helper for web derive password digest keys processing.
	"""
	secret = _get_password_digest_secret()
	if secret is None:
		raise ValueError('Password digest encryption secret is not configured.')
	key_material = hashlib.pbkdf2_hmac(
		'sha256',
		secret,
		salt,
		PASSWORD_DIGEST_PBKDF2_ROUNDS,
		dklen=64
	)
	return key_material[:32], key_material[32:]


def _password_digest_keystream(enc_key, nonce, length):
	"""
	Internal helper for web password digest keystream processing.
	"""
	stream = bytearray()
	counter = 0
	while len(stream) < length:
		stream.extend(hmac.new(enc_key, nonce + counter.to_bytes(8, 'big'), hashlib.sha256).digest())
		counter += 1
	return bytes(stream[:length])


def encrypt_password_digest(password_digest):
	'''
	Encrypt a stored password hash using an authenticated envelope built from PBKDF2-HMAC-SHA256 and HMAC-SHA256.
	If no encryption secret is configured, the plaintext digest is returned unchanged.
	'''
	if not password_digest or _is_encrypted_password_digest(password_digest) or not _password_digest_encryption_enabled():
		return password_digest
	plaintext = str(password_digest).encode('utf-8')
	salt = secrets.token_bytes(PASSWORD_DIGEST_SALT_BYTES)
	nonce = secrets.token_bytes(PASSWORD_DIGEST_NONCE_BYTES)
	enc_key, mac_key = _derive_password_digest_keys(salt)
	keystream = _password_digest_keystream(enc_key, nonce, len(plaintext))
	ciphertext = bytes(a ^ b for a, b in zip(plaintext, keystream))
	payload = salt + nonce + ciphertext
	tag = hmac.new(mac_key, payload, hashlib.sha256).digest()
	return PASSWORD_DIGEST_PREFIX + base64.urlsafe_b64encode(payload + tag).decode('ascii')


def decrypt_password_digest(password_digest):
	'''Return the plaintext password hash from either a legacy plaintext value or an encrypted value. '''
	if not password_digest or not _is_encrypted_password_digest(password_digest):
		return password_digest
	if not _password_digest_encryption_enabled():
		raise ValueError('Encrypted password digest requires {} to be configured.'.format(PASSWORD_DIGEST_SECRET_ENV))
	encoded_payload = password_digest[len(PASSWORD_DIGEST_PREFIX):].encode('ascii')
	raw_payload = base64.urlsafe_b64decode(encoded_payload)
	minimum_length = PASSWORD_DIGEST_SALT_BYTES + PASSWORD_DIGEST_NONCE_BYTES + PASSWORD_DIGEST_TAG_BYTES
	if len(raw_payload) < minimum_length:
		raise ValueError('Encrypted password digest is malformed.')
	salt_end = PASSWORD_DIGEST_SALT_BYTES
	nonce_end = salt_end + PASSWORD_DIGEST_NONCE_BYTES
	tag_start = len(raw_payload) - PASSWORD_DIGEST_TAG_BYTES
	salt = raw_payload[:salt_end]
	nonce = raw_payload[salt_end:nonce_end]
	ciphertext = raw_payload[nonce_end:tag_start]
	tag = raw_payload[tag_start:]
	enc_key, mac_key = _derive_password_digest_keys(salt)
	expected_tag = hmac.new(mac_key, salt + nonce + ciphertext, hashlib.sha256).digest()
	if not secrets.compare_digest(tag, expected_tag):
		raise ValueError('Encrypted password digest failed integrity validation.')
	keystream = _password_digest_keystream(enc_key, nonce, len(ciphertext))
	plaintext = bytes(a ^ b for a, b in zip(ciphertext, keystream))
	return plaintext.decode('utf-8')


def verify_user_password(password, user_json):
	'''Verify a login password against a legacy or encrypted stored password digest. '''
	stored_digest = user_json.get('password_digest')
	if not stored_digest:
		return False
	try:
		return pbkdf2_sha512.verify(password, decrypt_password_digest(stored_digest))
	except (TypeError, ValueError, UnicodeDecodeError, binascii.Error):
		return False


def set_user_password_digest(user_json, password):
	'''Hash a password and store the resulting digest in encrypted form. '''
	user_json['password_digest'] = encrypt_password_digest(_PASSWORD_HASHER.hash(password))


def migrate_legacy_user_password_digests(usernames=None):
	'''
	Encrypt legacy plaintext password digests in data/User/*.json.
	Pass a username string, an iterable of usernames, or leave usernames=None to migrate every user file.
	Returns a summary dict with migrated, skipped, and failed usernames. If no secret is configured,
	plaintext digests are left unchanged and reported as skipped.
	'''
	user_dir = path_manager.join('data', 'User')
	if usernames is None:
		target_usernames = [filename[:-5] for filename in _safe_list_dir(user_dir) if filename.endswith('.json')]
	elif isinstance(usernames, str):
		target_usernames = [usernames]
	else:
		target_usernames = list(usernames)
	results = {'migrated': [], 'skipped': [], 'failed': []}
	for username in target_usernames:
		user_filepath = os.path.join(user_dir, username + '.json')
		if not os.path.isfile(user_filepath):
			results['failed'].append(username)
			continue
		try:
			with locked_open(user_filepath) as f:
				user_json = json.load(f)
			stored_digest = user_json.get('password_digest')
			if not stored_digest or _is_encrypted_password_digest(stored_digest):
				results['skipped'].append(username)
				continue
			if not _password_digest_encryption_enabled():
				results['skipped'].append(username)
				continue
			user_json['password_digest'] = encrypt_password_digest(stored_digest)
			with locked_open(user_filepath, 'r+') as f:
				f.seek(0)
				f.truncate(0)
				json.dump(user_json, f, indent=4)
			results['migrated'].append(username)
		except Exception:
			results['failed'].append(username)
	return results


class User:
	"""
	Represent an authenticated OMF web user loaded from persisted user metadata.
	"""
	def __init__(self, jsonBlob):
		"""
		Initialize the user wrapper from a stored user JSON object.
		"""
		self.username = jsonBlob["username"]

	# Required login user functions.
	def is_admin(self):
		"""
		Return whether this user has OMF administrator privileges.
		"""
		return self.username == "admin"

	def get_id(self):
		"""
		Return the stable login identifier for this user.
		"""
		return self.username

	def is_authenticated(self):
		"""
		Return whether this user represents an authenticated session.
		"""
		return True

	def is_active(self):
		"""
		Return whether this user account is active for login purposes.
		"""
		return True

	def is_anonymous(self):
		"""
		Return whether this user is the anonymous-user placeholder.
		"""
		return False

	@classmethod
	def cu(self):
		"""Returns current user's username"""
		return current_user.username


def cryptoRandomString():
	''' Generate a cryptographically secure random string for signing/encrypting cookies. '''
	ck = globals().get('COOKIE_KEY')
	if ck:
		return ck
	return secrets.token_hex(32)


login_manager = _LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login_page"
app.secret_key = cryptoRandomString()


def csrf_token():
	'''Return the current session CSRF token, creating it if needed.'''
	if '_csrf_token' not in session:
		session['_csrf_token'] = secrets.token_urlsafe(32)
	return session['_csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protect_against_csrf():
	'''Require a valid CSRF token on all state-changing requests.'''
	if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
		return
	expected_token = session.get('_csrf_token')
	provided_token = _get_request_csrf_token()
	if not expected_token or not provided_token or not secrets.compare_digest(str(provided_token), str(expected_token)):
		return _csrf_failure_response()


@app.after_request
def set_csrf_cookie(response):
	'''Expose the CSRF token to same-origin JavaScript for AJAX/header submission.'''
	token = csrf_token()
	response.set_cookie(
		'_csrf_token',
		token,
		samesite='Lax',
		secure=request.is_secure,
		httponly=False,
		path='/'
	)
	return response


def _send_email(recipient, subject, message):
	"""
	Internal helper for web send email processing.
	"""
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


def _send_link(email, message, u=None):
	'''Send message to email using Amazon SES.'''
	if u is None:
		u = {}
	try:
		reg_key = secrets.token_hex(32)
		_send_email(email, 'OMF Registration Link', message.replace('reg_link', URL + '/register/' + email + '/' + reg_key))
		u["reg_key"] = reg_key
		u["timestamp"] = dt.datetime.strftime(dt.datetime.now(), format="%c")
		u["registered"] = False
		u["email"] = email
		with locked_open(path_manager.join('data', 'User',email + '.json'), 'w') as f:
			json.dump(u, f, indent=4)
		return "Success"
	except:
		return "Failed"


@login_manager.user_loader
def load_user(username):
	'''Return the current user instance, or None if the account no longer exists.'''
	try:
		with locked_open(path_manager.join('data', 'User', username + '.json')) as f:
			data = json.load(f)
		return User(data)
	except (FileNotFoundError, PathManager.PathTraversalError):
		return None


def _is_safe_url(target: str) -> bool:
	''' Return True only for redirects that stay inside this app. '''
	if not target:
		return True
	if not isinstance(target, str):
		return False
	target = target.strip()
	if not target:
		return True
	if any(ord(ch) < 32 or ord(ch) == 127 for ch in target): # reject URLs with control characters
		return False
	if '\\' in target:
		return False
	parts = urlsplit(target)
	if parts.scheme or parts.netloc:
		return False
	return target.startswith('/') and not target.startswith('//')


def _safe_redirect(target: str):
	"""Redirect to target if safe, else fallback to '/'."""
	if not _is_safe_url(target):
		target = '/'
	# Normalize empty
	if not target:
		target = '/'
	return redirect(target)


def _current_user_is_authenticated():
	'''Return whether the current request has an authenticated user.'''
	return _is_authenticated(current_user)


@app.route("/login", methods = ["POST"])
def login():
	''' Authenticate a user and send them to the URL they requested. '''
	username, password, remember = map(request.form.get, ["username", "password", "remember"])
	userJson = None
	for u in _safe_list_dir(os.path.join(_omfDir, 'data', 'User')):
		if u.lower() == username.lower() + ".json":
			with locked_open(os.path.join(_omfDir, 'data', 'User', u)) as f:
				userJson = json.load(f)
			break
	if userJson and verify_user_password(password, userJson):
		user = User(userJson)
		login_user(user, remember = remember == "on")
	nextUrl = str(request.form.get("next","/") or "/")
	return _safe_redirect(nextUrl)


@app.route("/login_page")
def login_page():
	"""
	Perform login page processing for OMF helper-library workflows.
	"""
	nextUrl = str(request.args.get("next","/") or "/")
	if not _is_safe_url(nextUrl):
		nextUrl = "/"
	if urlsplit(nextUrl).path == request.path:
		nextUrl = "/"
	if _current_user_is_authenticated():
		return redirect(nextUrl)
	return render_template("clusterLogin.html", next=nextUrl)


@app.route("/logout", methods=["POST"])
def logout():
	"""
	Perform logout processing for OMF helper-library workflows.
	"""
	logout_user()
	return redirect("/")


@app.route("/deleteUser", methods=["POST"])
@login_required
def deleteUser():
	"""
	Perform delete user processing for OMF helper-library workflows.
	"""
	if User.cu() != "admin":
		return "You are not authorized to delete users"
	username = request.form.get("username")
	if username in ('admin', 'public'):
		return "Cannot delete protected system account", 400
	# Clean up user data.
	try:
		shutil.rmtree(path_manager.join('data', 'Model', username))
	except Exception as e:
		print("USER DATA DELETION FAILED FOR", e)
	os.remove(path_manager.join('data', 'User', f'{username}.json'))
	print("SUCCESFULLY DELETE USER", username)
	return "Success"


@app.route("/new_user", methods=["POST"])
def new_user():
	"""
	Perform new user processing for OMF helper-library workflows.
	"""
	email = request.form.get("email")
	if email == "": return "EMPTY"
	path_manager.join('data', 'User', email + '.json')
	if email.lower() in [f[0:-5].lower() for f in _safe_list_dir(os.path.join(_omfDir, 'data', 'User'))]:
		with locked_open(path_manager.join('data', 'User', f'{email}.json')) as f:
			u = json.load(f)
		if u.get("password_digest") or not request.form.get("resend"):
			return "Already Exists"
	message = "Click the link below to register your account for the OMF.  This link will expire in 24 hours:\n\nreg_link"
	return _send_link(email, message)


@app.route("/forgotPassword/<email>", methods=["POST"])
def forgotpwd(email):
	"""
	Perform forgotpwd processing for OMF helper-library workflows.
	"""
	try:
		with locked_open(path_manager.join('data', 'User', f'{email}.json')) as f:
			user = json.load(f)
		message = "Click the link below to reset your password for the OMF.  This link will expire in 24 hours.\n\nreg_link"
		code = _send_link(email, message, user)
		if code == "Success":
			return "We have sent a password reset link to " + email, 200, {'Content-Type': 'text/plain'}
		else:
			raise Exception
	except Exception as e:
		print("ERROR: failed to password reset user", email, "with exception", e)
		return "We do not have a record of a user with that email address. Please click back and create an account."


@app.route("/fastNewUser/<email>", methods=["POST"])
def fastNewUser(email):
	''' Create a new user, email them their password, and immediately create a new model for them.'''
	if email.lower() in [f[0:-5].lower() for f in _safe_list_dir(os.path.join(_omfDir, 'data', 'User'))]:
		return "User with email {} already exists. Please log in or go back and use the 'Forgot Password' link. Or use a different email address.".format(email), 200, {'Content-Type': 'text/plain'}
	else:
		randomPass = ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for x in range(15))
		user = {"username": email}
		set_user_password_digest(user, randomPass)
		with locked_open(path_manager.join('data', 'User', f'{user["username"]}.json'), 'w') as f:
			json.dump(user, f, indent=4)
		message = "Thank you for registering an account on OMF.coop.\n\nYour password is: " + randomPass + "\n\n You can change this password after logging in."
		_send_email(email, 'OMF.coop User Account', message)
		login_user(User(user))
		nextUrl = str(request.args.get("next","/") or "/")
		return _safe_redirect(nextUrl)


@app.route("/register/<email>/<reg_key>", methods=["GET", "POST"])
def register(email, reg_key):
	"""
	Perform register processing for OMF helper-library workflows.
	"""
	if current_user.is_authenticated:
		return redirect("/")
	try:
		with locked_open(path_manager.join('data', 'User', f'{email}.json')) as f:
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
		set_user_password_digest(user, password)
		user.pop("reg_key", None)
		user.pop("timestamp", None)
		login_user(User(user))
		with locked_open(path_manager.join('data', 'User', f'{user["username"]}.json'), 'w') as f: # Need 'w' mode to create new users? I would prefer r+ mode
			json.dump(user, f, indent=4)
	else:
		return "Passwords must both match and you must accept the Terms of Use and Privacy Policy. Please go back and try again."
	return redirect("/")


@app.route("/changepwd", methods=["POST"])
@login_required
def changepwd():
	"""
	Perform changepwd processing for OMF helper-library workflows.
	"""
	old_pwd, new_pwd, conf_pwd = map(request.form.get, ['old_pwd', 'new_pwd', 'conf_pwd'])
	user_filepath = os.path.join(_omfDir, 'data', 'User', User.cu() + '.json')
	with locked_open(user_filepath) as f:
		user = json.load(f)
	if verify_user_password(old_pwd, user):
		if new_pwd == conf_pwd:
			set_user_password_digest(user, new_pwd)
			with locked_open(user_filepath, 'r+') as f:
				f.seek(0)
				f.truncate(0)
				json.dump(user, f, indent=4)
			return "Success"
		else:
			return "not_match"
	else:
		return "not_auth"


@app.route("/adminControls")
@login_required
def adminControls():
	''' Render admin controls. '''
	if User.cu() != "admin":
		return redirect("/")
	users = [{'username':f[0:-5]} for f in _safe_list_dir(os.path.join(_omfDir, 'data', 'User')) if f not in ['admin.json', 'public.json']]
	for user in users:
		with locked_open(os.path.join(_omfDir, 'data', 'User', f'{user["username"]}.json')) as f:
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
@login_required
def omfStatsView():
	'''Render log visualizations.'''
	if User.cu() != "admin":
		return redirect("/")
	log_context = _get_omf_stats_logs()
	return render_template("omfStats.html", **log_context)


@app.route("/regenOmfStats", methods=["POST"])
@login_required
def regenOmfStats():
	'''Regenarate stats images.'''
	if User.cu() != "admin":
		return redirect("/")
	genImagesProc = Process(target=omfStats.genAllImages, args=[])
	genImagesProc.start()
	return redirect("/omfStats")


@app.route("/myaccount")
@login_required
def myaccount():
	''' Render account info for any user. '''
	return render_template("myaccount.html", user=User.cu())


@app.route("/robots.txt")
def static_from_root():
	"""
	Perform static from root processing for OMF helper-library workflows.
	"""
	return send_from_directory(app.static_folder, request.path[1:])


@app.route("/docs")
@app.route("/docs/")
@app.route("/docs/<path:doc_path>")
def docs(doc_path=""):
	'''Render migrated wiki markdown docs and serve local doc assets.'''
	source_path = _resolve_doc_path(doc_path)
	if source_path is None:
		abort(404)
	if source_path.lower().endswith(".md"):
		return _render_markdown_doc(source_path)
	return send_from_directory(os.path.dirname(source_path), os.path.basename(source_path))


def read_permission_function(func):
	"""Run the route if the user has read permission for the model and the model exists, otherwise redirect to home page."""
	@wraps(func)
	def wrapper(*args, **kwargs):
		owner = kwargs.get('owner')
		if owner is None:
			owner = request.form.get('user')
		if owner is None:
			owner = request.form.get('owner')
		if owner is None:
			return redirect("/")
		model_name = kwargs.get('modelName') if kwargs.get('modelName') is not None else request.form.get('modelName')
		if model_name is None:
			return redirect("/")
		if model_name == 'publicFeeders' and owner == 'public':
			# Public feeders in the static/publicFeeders directory have no model associated with them, so they are a special case. Public feeders are
			# accessed from a variety of routes, including uniqObjName and loadFeeder. Any user can read from a public feeder.
			return func(*args, **kwargs)
		# Check for the existence of the model. This is not strictly the task of this function, but it is convenient to check here
		model_metadata_path = path_manager.join('data', 'Model', owner, model_name, 'allInputData.json')
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
	model_metadata = _get_model_metadata(owner, model_name)
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
			owner = request.form.get("owner")
		if owner is None:
			return redirect("/")
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
@login_required
@read_permission_function
def showModel(owner, modelName):
	''' Render a model template with saved data. '''
	modelType = _get_model_metadata(owner, modelName).get('modelType', '')
	thisModel = _get_model_module(modelType)
	return thisModel.renderTemplate(
		path_manager.join('data', 'Model', owner, modelName),
		absolutePaths=False,
		datastoreNames=_get_data_names())


@app.route("/newModel/<modelType>/<modelName>", methods=["POST"])
@login_required
# - Do not use @write_permission_function because the user is always writing to their own model directory
def newModel(modelType, modelName):
	''' Create a new model with given name. '''
	modelDir = path_manager.join("data", "Model", User.cu(), modelName)
	thisModel = _get_model_module(modelType)
	thisModel.new(modelDir)
	return redirect(url_for('showModel', owner=User.cu(), modelName=modelName))


@app.route("/runModel/", methods=["POST"])
@login_required
@write_permission_function
def runModel():
	''' Start a model running and redirect to its running screen. '''
	pData = request.form.to_dict()
	modelModule = _get_model_module(pData["modelType"])
	form_user = pData.pop("user")
	user = form_user if (User.cu() == "admin" and form_user) else User.cu()
	modelName = pData.pop("modelName")
	# Remove internal keys that the form should never set
	pData.pop("_csrf_token", None)
	pData.pop("viewers", None)
	modelDir = path_manager.join("data", "Model", user, modelName)
	# File upload handling
	for file_field, file in request.files.items():
		if secure_filename(file.filename):
			safeFileField = secure_filename(file_field)
			if safeFileField in _RESERVED_FILENAMES:
				continue
			file.save(path_manager.join('data', 'Model', user, modelName, safeFileField))
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
	return redirect(url_for('showModel', owner=user, modelName=modelName))


@app.route("/cancelModel/", methods=["POST"])
@login_required
@write_permission_function
def cancelModel():
	''' Cancel an already running model. '''
	pData = request.form.to_dict()
	modelModule = _get_model_module(pData["modelType"])
	modelModule.cancel(path_manager.join("data", "Model", pData["user"], pData["modelName"]))
	return redirect(url_for('showModel', owner=pData["user"], modelName=pData["modelName"]))


@app.route("/duplicateModel/<owner>/<modelName>/", methods=["POST"])
@login_required
@read_permission_function
def duplicateModel(owner, modelName):
	"""
	Perform duplicate model processing for OMF helper-library workflows.
	"""
	newName = secure_filename(request.form.get("newName","")) or 'model'
	destination_path = path_manager.join('data', 'Model', User.cu(), newName)
	shutil.copytree(path_manager.join('data', 'Model', owner, modelName), destination_path)
	# Remove transient PID and error files so the duplicate doesn't appear
	# "running" and cancelling it won't kill the original model's process.
	for name in ['ZPID.txt', 'APID.txt', 'NPID.txt', 'CPID.txt', 'WPID.txt', 'TPPID.txt', 'PPID.txt',
			'gridError.txt', 'error.txt', 'weatherError.txt', 'matError.txt', 'cimError.txt']:
		p = os.path.join(destination_path, name)
		if os.path.isfile(p):
			os.remove(p)
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
@login_required
@write_permission_function
def shareModel():
	''' Share a model with other users by granting them read-only access. '''
	owner = request.form.get("user")
	model_name = request.form.get("modelName")
	# Parse and deduplicate the email list (None if empty)
	raw_emails = request.form.getlist("email")
	emails = list(set(raw_emails)) if raw_emails else None
	# Validate all emails before proceeding — use a single generic error to prevent user enumeration
	if emails is not None:
		invalid_emails = [e for e in emails if e == User.cu() or e == 'admin' or not os.path.isfile(path_manager.join('data', 'User', e + '.json'))]
		if invalid_emails:
			return 'One or more emails are invalid or not registered', 400
	# Reject sharing while the model is running
	status = models.__neoMetaModel__.getStatus(path_manager.join('data', 'Model', owner, model_name))
	if status == 'running':
		return ("The model cannot be shared while it is running. Please wait until the model finishes running.", 409)
	# Determine what changed
	model_metadata = _get_model_metadata(owner, model_name)
	old_viewers = model_metadata.get("viewers")
	if emails is None and old_viewers is None:
		return jsonify(emails), 200
	# Update the viewers list in metadata
	if emails is not None:
		model_metadata["viewers"] = emails
	else:
		del model_metadata["viewers"]
	filepath = path_manager.join('data', 'Model', owner, model_name, 'allInputData.json')
	serialized = json.dumps(model_metadata, indent=4)
	with locked_open(filepath, 'r+') as f:
		f.truncate(0)
		f.write(serialized)
	# Revoke access for viewers who were removed
	if old_viewers is not None:
		for v in old_viewers:
			if emails is None or v not in emails:
				_revoke_viewership(owner, model_name, v)
	# Grant access for new viewers
	if emails is not None:
		for e in emails:
			_grant_viewership(owner, model_name, e)
	return jsonify(emails), 200


def _revoke_viewership(owner, model_name, username):
	"""Revoke <username>'s read-only access to <owner>/<model_name>."""
	filepath = path_manager.join('data', 'User', username + ".json")
	if not os.path.isfile(filepath):
		return
	with locked_open(filepath) as f:
		viewer_metadata = json.load(f)
	readonly = viewer_metadata.get("readonly_models", {})
	models_for_owner = readonly.get(owner, [])
	if model_name not in models_for_owner:
		return
	models_for_owner.remove(model_name)
	# Clean up empty containers
	if not models_for_owner:
		del readonly[owner]
	if not readonly:
		viewer_metadata.pop("readonly_models", None)
	serialized = json.dumps(viewer_metadata, indent=4)
	with locked_open(filepath, 'r+') as f:
		f.truncate(0)
		f.write(serialized)


def _grant_viewership(owner, model_name, username):
	"""Grant <username> read-only access to <owner>/<model_name>."""
	filepath = path_manager.join('data', 'User', username + '.json')
	if not os.path.isfile(filepath):
		return
	with locked_open(filepath) as f:
		viewer_metadata = json.load(f)
	readonly = viewer_metadata.setdefault("readonly_models", {})
	models_for_owner = readonly.setdefault(owner, [])
	if model_name in models_for_owner:
		return
	models_for_owner.append(model_name)
	serialized = json.dumps(viewer_metadata, indent=4)
	with locked_open(filepath, 'r+') as f:
		f.truncate(0)
		f.write(serialized)


@contextmanager
def locked_open(filepath, mode='r', timeout=180, **io_open_args):
	'''
	Open a file and lock it depending on the file access mode. An IOError will be raised if the lock cannot be acquired within the timeout. If the
	filepath does not exist, this function should throw the exception upwards and not try to handle it.
	'''
	if 'r' in mode and '+' not in mode:
		lock_mode = fcntl.LOCK_SH
	else:
		lock_mode = fcntl.LOCK_EX
	# Avoid 'w' mode before locking: open(path, 'w') truncates the file
	# instantly, destroying contents for any concurrent reader/writer that
	# already holds the lock. Open in 'a' mode instead (creates the file if
	# missing, does not truncate), then truncate after the lock is acquired.
	deferred_truncate = False
	open_mode = mode
	if mode == 'w':
		open_mode = 'a'
		deferred_truncate = True
	f = open(filepath, open_mode, **io_open_args)
	try:
		start_time = time.time()
		while True:
			try:
				fcntl.flock(f, lock_mode | fcntl.LOCK_NB)
				break
			except IOError as e:
				if e.errno != errno.EACCES and e.errno != errno.EAGAIN:
					raise
			if time.time() >= start_time + timeout:
				raise IOError(f"{timeout}-second file lock timeout reached. Either a file-locking operation is taking more than {timeout} seconds "
					"or there was a programmer error that would have resulted in deadlock.")
			time.sleep(0.01)
		if deferred_truncate:
			f.seek(0)
			f.truncate(0)
		yield f
	finally:
		fcntl.flock(f, fcntl.LOCK_UN)
		f.close()


###################################################
# FEEDER FUNCTIONS
###################################################


def _write_to_input(workDir, entry, key):
	"""
	Internal helper for web write to input processing.
	"""
	try:
		with locked_open(os.path.join(workDir, 'allInputData.json'), 'r+') as f:
			allInput = json.load(f)
			allInput[key] = entry
			f.seek(0)
			f.truncate(0)
			json.dump(allInput, f, indent=4)
	except:
		return "Failed"


@app.route("/gridEdit/<owner>/<modelName>/<int:feederNum>")
@login_required
@read_permission_function
def feederGet(owner, modelName, feederNum):
	''' Editing interface for feeders. '''
	allData = _get_data_names()
	yourFeeders = allData["feeders"]
	publicFeeders = allData["publicFeeders"]
	feederName = _get_model_metadata(owner, modelName).get('feederName' + str(feederNum))
	return render_template(
		"gridEdit.html", feeders=yourFeeders, publicFeeders=publicFeeders, modelName=modelName, feederName=feederName,
		feederNum=feederNum, ref=request.referrer, is_admin=User.cu()=="admin",
		public=owner=="public", currUser=User.cu(), owner=owner)


@app.route("/network/<owner>/<modelName>/<int:networkNum>")
@login_required
@read_permission_function
def networkGet(owner, modelName, networkNum):
	''' Editing interface for networks. '''
	allData = _get_data_names()
	yourNetworks = allData["networks"]
	publicNetworks = allData["networks"]
	networkName = _get_model_metadata(owner, modelName).get('networkName1')
	network_filepath = path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	with locked_open(network_filepath) as f:
		data = json.load(f)
	networkData = json.dumps(data)
	#Currently unused template variables: networks, publicNetworks, currUser, 
	return render_template("transEdit.html", networks=yourNetworks, publicNetworks=publicNetworks, modelName=modelName, networkData=networkData,
		networkName=networkName, networkNum=networkNum, ref=request.referrer, is_admin=User.cu()=="admin", public=owner=="public",
		currUser=User.cu(), owner=owner)


@app.route('/feeder/<owner>/<modelName>/<feeder_num>/test')
@app.route('/feeder/<owner>/<modelName>/<feeder_num>')
@login_required
@read_permission_function
def distribution_get(owner, modelName, feeder_num):
	'''Render the editing interface for distribution networks.'''
	feeder_dict = _get_model_metadata(owner, modelName)
	feeder_name = feeder_dict.get('feederName' + str(feeder_num))
	feeder_filepath = path_manager.join('data', 'Model', owner, modelName, feeder_name + '.omd')
	with locked_open(feeder_filepath) as f:
		data = json.load(f)
	feeder = json.dumps(data)
	jasmine = spec = None
	if request.path.endswith('/test') and User.cu() == 'admin':
		from omf.static.testFiles.test_distNetVizInterface import helper
		tests = helper.load_test_files(['spec_distNetVizInterface.js'])
		jasmine = tests['jasmine']
		spec = tests['spec']
	all_data = _get_data_names()
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
		publicFeeders=public_feeders, userFeeders=user_feeders, showFileMenu=show_file_menu, currentUser=User.cu(), dssSchema=dssSchema)


@app.route('/rawTextEdit/<owner>/<modelName>/<fileName>/test')
@app.route('/rawTextEdit/<owner>/<modelName>/<fileName>')
@login_required
@read_permission_function
def distribution_text_get(owner, modelName, fileName):
	'''Render the raw text editing interface for distribution networks.'''
	file_filepath = path_manager.join('data', 'Model', owner, modelName, fileName)
	try:
		with locked_open(file_filepath) as f:
			data = f.read()
	except FileNotFoundError:
		with locked_open(path_manager.join('solvers', 'opendss', fileName)) as f:
			data = f.read()
	file = data
	jasmine = spec = None
	if request.path.endswith('/test') and User.cu() == 'admin':
		from omf.static.testFiles.test_distNetVizInterface import helper
		tests = helper.load_test_files(['spec_distNetVizInterface.js'])
		jasmine = tests['jasmine']
		spec = tests['spec']
	all_data = _get_data_names()
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
		publicFiles=public_files, userFiles=user_files, showFileMenu=show_file_menu, currentUser=User.cu())


@app.route("/getComponents/")
@app.route("/getComponents/<schema>")
@login_required
def get_components(schema='gld'):
	"""
	Return the components needed by this workflow.
	"""
	if schema == 'dss':
		directory = path_manager.join('data', 'ComponentDss')
	else: #schema == 'gld'
		directory = path_manager.join('data', 'Component')
	components = {}
	for dirpath, dirnames, file_names in os.walk(directory):
		for name in file_names:
			if name.endswith(".json"):
				path = os.path.join(dirpath, name)
				with locked_open(path) as f:
					components[name[0:-5]] = json.load(f) # Load the file as a regular object into the dictionary
	return json.dumps(components) # Turn the dictionary of objects into a string


@app.route("/checkConversion/<modelName>/<owner>", methods=["GET"])
@login_required
@read_permission_function # Viewers can load a feeder, and all feeders check for ongoing conversions, so this route must have read permissions
def checkConversion(modelName, owner):
	"""
	If the path exists, then the conversion is ongoing and the client can't reload their browser yet. If the path does not exist, then either 1) the
	conversion hasn't started yet or 2) the conversion is finished because the ZPID.txt file is gone. If an error file exists, the the conversion
	failed and the client should be notified.
	"""
	print(modelName)
	# First check for error files
	for filename in ['gridError.txt', 'error.txt', 'weatherError.txt', 'matError.txt', 'cimError.txt']:
		filepath = path_manager.join('data', 'Model', owner, modelName, filename)
		if os.path.isfile(filepath):
			with locked_open(filepath) as f:
				errorString = f.read()
			return jsonify(error=errorString)
	# Check for process ID files AFTER checking for error files
	for filename in ["ZPID.txt", "APID.txt", "WPID.txt", "NPID.txt", "CPID.txt"]:
		filepath = path_manager.join('data', 'Model', owner, modelName, filename)
		if os.path.isfile(filepath):
			return jsonify(exists=True)
	return jsonify(exists=False)


@app.route("/milsoftImport/<owner>", methods=["POST"])
@login_required
@write_permission_function
def milsoftImport(owner):
	''' API for importing a milsoft feeder. '''
	modelName = request.form.get("modelName","")
	model_dir, error_filepath = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('', 'gridError.txt')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in _safe_list_dir(model_dir):
		if filename.endswith(".glm") or filename.endswith(".std") or filename.endswith(".seq"):
			os.remove(os.path.join(model_dir, filename))
	if os.path.isfile(error_filepath):
		os.remove(error_filepath)
	feederName = secure_filename(str(request.form.get('feederNameM', 'feeder'))) or 'feeder'
	feederNum = secure_filename(str(request.form.get("feederNum", '1'))) or '1'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')):
		return 'Name already exists', 409
	std_filepath, seq_filepath = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in (feederName + '.std', feederName + '.seq')]
	request.files.get('stdFile').save(std_filepath)
	request.files.get('seqFile').save(seq_filepath)
	importProc = Process(target=_mil_import_background, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def _mil_import_background(owner, modelName, feederName, feederNum):
	''' Function to run in the background for Milsoft import. '''
	try:
		std_filepath, seq_filepath, pid_filepath, feeder_filepath, model_dir, error_filepath = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in
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
		_remove_feeder(owner, modelName, feederNum)
		_write_to_input(model_dir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write("milError")


@app.route("/matpowerImport/<owner>", methods=["POST"])
@login_required
@write_permission_function
def matpowerImport(owner):
	''' API for importing a MATPOWER network. '''
	modelName = request.form.get('modelName', '')
	model_dir, con_file_path = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('', 'ZPID.txt')]
	error_paths = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('matError.txt', 'cimError.txt')]
	# Delete existing .m files to not clutter model.
	for filename in _safe_list_dir(model_dir):
		if filename.endswith(".m"):
			os.remove(os.path.join(model_dir, filename))
	for error_path in error_paths:
		if os.path.isfile(error_path):
			os.remove(error_path)
	with locked_open(con_file_path, 'w') as conFile:
		conFile.write("WORKING")
	networkName = secure_filename(str(request.form.get('networkNameM', 'network1'))) or 'network'
	networkNum = secure_filename(str(request.form.get("networkNum", '1'))) or '1'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')):
		return 'Name already exists', 409
	network_filepath = path_manager.join('data', 'Model', owner, modelName, networkName + '.m')
	request.files['matFile'].save(network_filepath)
	importProc = Process(target=_mat_import_background, args=[owner, modelName, networkName, networkNum])
	importProc.start()
	return 'Success'


def _mat_import_background(owner, modelName, networkName, networkNum):
	''' Function to run in the background for Matpower import. '''
	try:
		network_filepath, model_dir, pid_filepath = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in [networkName + '.m', '', 'ZPID.txt']
		]
		newNet = transmission.parse(network_filepath, filePath=True)
		transmission.layout(newNet)
		with locked_open(network_filepath, 'w') as f:
			json.dump(newNet, f, indent=4)
		os.rename(network_filepath, path_manager.join('data', 'Model', owner, modelName, networkName + '.omt'))
		os.remove(pid_filepath)
		_remove_network(owner, modelName, networkNum)
		_write_to_input(model_dir, networkName, 'networkName' + str(networkNum))
	except ValueError:
		filepath = path_manager.join('data', 'Model', owner, modelName, 'matError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('matError')
		os.remove(pid_filepath)
	except:
		os.remove(pid_filepath)


@app.route("/cimImport/<owner>", methods=["POST"])
@login_required
@write_permission_function
def cimImport(owner):
	''' API for importing a CGMES/CIM network through pandapower. '''
	modelName = request.form.get('modelName', '')
	model_dir = path_manager.join('data', 'Model', owner, modelName)
	con_file_path = path_manager.join('data', 'Model', owner, modelName, 'ZPID.txt')
	error_paths = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('matError.txt', 'cimError.txt')]
	for filename in _safe_list_dir(model_dir):
		if filename.startswith('cim_import_'):
			os.remove(os.path.join(model_dir, filename))
	for error_path in error_paths:
		if os.path.isfile(error_path):
			os.remove(error_path)
	networkName = secure_filename(str(request.form.get('networkNameC', 'network1'))) or 'network'
	networkNum = secure_filename(str(request.form.get("networkNum", '1'))) or '1'
	cgmes_version = request.form.get('cgmesVersion', '2.4.15')
	if cgmes_version not in ['2.4.15', '3.0']:
		cgmes_version = '2.4.15'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')):
		return 'Name already exists', 409
	cim_filepaths = []
	for i, cim_file in enumerate(request.files.getlist('cimFiles')):
		if cim_file is None or cim_file.filename == '':
			continue
		filename = secure_filename(cim_file.filename) or ('file' + str(i))
		filepath = path_manager.join('data', 'Model', owner, modelName, 'cim_import_' + str(i) + '_' + filename)
		cim_file.save(filepath)
		if not _is_safe_cim_upload(filepath):
			for saved_filepath in cim_filepaths + [filepath]:
				if os.path.isfile(saved_filepath):
					os.remove(saved_filepath)
			return 'Unsupported or unsafe file', 400
		cim_filepaths.append(filepath)
	if len(cim_filepaths) == 0:
		return 'No files provided', 400
	with locked_open(con_file_path, 'w') as conFile:
		conFile.write("WORKING")
	importProc = Process(target=_cim_import_background, args=[owner, modelName, networkName, networkNum, cgmes_version, cim_filepaths])
	importProc.start()
	return 'Success'


def _is_safe_cim_upload(filepath):
	"""
	Internal helper for web is safe cim upload processing.
	"""
	extension = os.path.splitext(filepath)[1].lower()
	if extension not in ['.xml', '.rdf', '.zip']:
		return False
	if extension != '.zip':
		return True
	import zipfile
	try:
		with zipfile.ZipFile(filepath) as zip_file:
			for member in zip_file.namelist():
				member_path = Path(member)
				if member_path.is_absolute() or '..' in member_path.parts:
					return False
	except zipfile.BadZipFile:
		return False
	return True


def _cim_import_background(owner, modelName, networkName, networkNum, cgmes_version, cim_filepaths):
	''' Function to run in the background for CGMES/CIM import. '''
	model_dir = path_manager.join('data', 'Model', owner, modelName)
	pid_filepath = path_manager.join('data', 'Model', owner, modelName, 'ZPID.txt')
	new_network_filepath = path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	error_filepath = path_manager.join('data', 'Model', owner, modelName, 'cimError.txt')
	try:
		newNet = transmission.parseCim(cim_filepaths, cgmes_version=cgmes_version)
		if not any('latitude' in bus and 'longitude' in bus for bus in newNet.get('bus', {}).values()):
			transmission.layout(newNet)
		with locked_open(new_network_filepath, 'w') as f:
			json.dump(newNet, f, indent=4)
		_remove_network(owner, modelName, networkNum)
		_write_to_input(model_dir, networkName, 'networkName' + str(networkNum))
	except ImportError:
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write('pandapowerCimError')
	except Exception:
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write('cimError')
	finally:
		if os.path.isfile(pid_filepath):
			os.remove(pid_filepath)
		for filepath in cim_filepaths:
			if os.path.isfile(filepath):
				os.remove(filepath)


@app.route("/gridlabdImport/<owner>", methods=["POST"])
@login_required
@write_permission_function
def gridlabdImport(owner):
	'''This function is used for gridlabdImporting'''
	modelName = request.form.get("modelName","")
	error_path, modelDir = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('gridError.txt', '')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in _safe_list_dir(modelDir):
		if filename.endswith(".glm") or filename.endswith(".std") or filename.endswith(".seq"):
			os.remove(os.path.join(modelDir, filename))
	if os.path.isfile(error_path):
		os.remove(error_path)
	# Handle request objects
	feederName = secure_filename(str(request.form.get("feederNameG",""))) or 'feeder'
	feederNum = secure_filename(str(request.form.get("feederNum", '1'))) or '1'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')):
		return 'Name already exists', 409
	glm_path = path_manager.join('data', 'Model', owner, modelName, feederName + '.glm')
	request.files['glmFile'].save(glm_path)
	importProc = Process(target=_gridlab_import_background, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def _gridlab_import_background(owner, modelName, feederName, feederNum):
	''' Function to run in the background for Gridlabd import. '''
	try:
		feeder_path, glm_path, modelDir, pid_filepath = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', feederName + '.glm', '', 'ZPID.txt']
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
		_remove_feeder(owner, modelName, feederNum)
		_write_to_input(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		filepath = path_manager.join('data', 'Model', owner, modelName, 'gridError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('glmError')


@app.route("/opendssImport/<owner>", methods=["POST"])
@login_required
@write_permission_function
def dssImport(owner):
	'''This function is used for opendss importing in distnetviz'''
	modelName = request.form.get("modelName","")
	error_path, modelDir = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('gridError.txt', '')]
	# Delete exisitng .std and .seq, .glm files to not clutter model file
	for filename in _safe_list_dir(modelDir):
		if filename.endswith(".dss"):
			os.remove(os.path.join(modelDir, filename))
	if os.path.isfile(error_path):
		os.remove(error_path)
	feederName = secure_filename(str(request.form.get("feederNameOpendss",""))) or 'feeder'
	feederNum = secure_filename(str(request.form.get("feederNum", '1'))) or '1'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')):
		return 'Name already exists', 409
	dss_path = path_manager.join('data', 'Model', owner, modelName, feederName + '.dss')
	request.files['dssFile'].save(dss_path)
	importProc = Process(target=_dss_import_background, args=[owner, modelName, feederName, feederNum])
	importProc.start()
	return 'Success'


def _dss_import_background(owner, modelName, feederName, feederNum):
	''' Function to run in the background for OpenDSS import. '''
	try:
		feeder_path, dss_path, modelDir, pid_filepath = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', feederName + '.dss', '', 'ZPID.txt']
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
		_remove_feeder(owner, modelName, feederNum)
		_write_to_input(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception: 
		filepath = path_manager.join('data', 'Model', owner, modelName, 'gridError.txt')
		with locked_open(filepath, 'w') as errorFile:
			errorFile.write('dssError')


@app.route("/scadaLoadshape/<owner>/<feederName>", methods=["POST"])
@login_required
@write_permission_function
def scadaLoadshape(owner, feederName):
	#feederNum = request.form.get("feederNum", '1')
	"""
	Perform scada loadshape processing for OMF helper-library workflows.
	"""
	loadName = 'calibration'
	modelName = request.form.get("modelName","")
	# delete calibration csv, calibration folder, and error file if they exist
	filepaths = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('error.txt', 'calibration.csv', 'calibration')]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
		elif os.path.isdir(fp):
			shutil.rmtree(fp)
	request.files['scadaFile'].save(path_manager.join('data', 'Model', owner, modelName, loadName + '.csv'))
	dirpath = path_manager.join('data', 'Model', owner, modelName, 'calibration', 'gridlabD')
	if not os.path.isdir(dirpath):
		os.makedirs(dirpath)
	# Run omf calibrate in background
	importProc = Process(target=_background_scada_loadshape, args=[owner, modelName, feederName, loadName])
	importProc.start()
	return 'Success'


def _background_scada_loadshape(owner, modelName, feederName, loadName):
	# heavy lifting background process/omfCalibrate and then deletes PID file
	"""
	Internal helper for web background scada loadshape processing.
	"""
	try:
		pid_filepath = path_manager.join('data', 'Model', owner, modelName, 'CPID.txt')
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		workDir, feederPath, scadaPath, modelDir = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in ['calibration', feederName + '.omd', loadName + '.csv', '']
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
@login_required
@write_permission_function
def loadModelingAmi(owner, feederName):
	#feederNum = request.form.get('feederNum', '1')
	"""
	Load modeling ami data for OMF processing.
	"""
	loadName = 'ami'
	modelName = request.form.get('modelName', '')
	filepaths = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('amiError.txt', 'amiLoad.csv')]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
	ami_filepath = path_manager.join('data', 'Model', owner, modelName, loadName + '.csv')
	request.files['amiFile'].save(ami_filepath)
	importProc = Process(target=_background_load_modeling_ami, args=[owner, modelName, feederName, loadName])
	importProc.start()
	return 'Success'


def _background_load_modeling_ami(owner, modelName, feederName, loadName):
	"""
	Internal helper for web background load modeling ami processing.
	"""
	try:
		pid_filepath, ami_filepath, omdPath, outDir, error_filepath = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in 
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
@login_required
@write_permission_function
def cymeImport(owner):
	''' API for importing a cyme feeder. '''
	modelName = request.form.get("modelName","")
	error_filepath = path_manager.join('data', 'Model', owner, modelName, 'gridError.txt')
	if os.path.isfile(error_filepath):
		os.remove(error_filepath)
	feederNum = secure_filename(str(request.form.get("feederNum", '1'))) or '1'
	feederName = secure_filename(str(request.form.get("feederNameC",""))) or 'feeder'
	if os.path.isfile(path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')):
		return 'Name already exists', 409
	mdbFileObject = request.files["mdbNetFile"]
	mdb_filepath = path_manager.join('data', 'Model', owner, modelName, feederName + '.mdb')
	mdbFileObject.save(mdb_filepath)
	print(mdbFileObject.filename)
	importProc = Process(target=_cyme_import_background, args=[owner, modelName, feederNum, feederName])
	importProc.start()
	return 'Success'


def _cyme_import_background(owner, modelName, feederNum, feederName):
	''' Function to run in the background for Milsoft import. '''
	try:
		pid_filepath, error_filepath, mdb_filepath, feeder_filepath, modelDir = [path_manager.join('data', 'Model', owner, modelName, filename) for filename in 
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
		_remove_feeder(owner, modelName, feederNum) # remove the old feeder file that had the same feeder number
		_write_to_input(modelDir, feederName, 'feederName' + str(feederNum))
	except Exception:
		with locked_open(error_filepath, 'w') as errorFile:
			errorFile.write('cymeError')


def _new_simple_feeder(owner, modelName, feederNum=1, writeInput=False, feederName='feeder1'):
	'''Create a simple feeder file in the model directory.'''
	modelDir = path_manager.join("data", "Model", owner, modelName)
	for i in range(2,6):
		feederPath = path_manager.join("data", "Model", owner, modelName, feederName + '.omd')
		if not os.path.isfile(feederPath):
			with open(os.path.join(_omfDir, 'static', 'SimpleFeeder.json')) as f:
				feeder_string = f.read()
			with locked_open(feederPath, 'w') as f:
				f.write(feeder_string)
			break
		else:
			feederName = 'feeder' + str(i)
	if writeInput:
		_write_to_input(modelDir, feederName, 'feederName' + str(feederNum))
	return 'Success'


@app.route("/newSimpleFeeder/<owner>/<modelName>/<int:feederNum>/<writeInput>", methods=["POST"])
@login_required
@write_permission_function
def newSimpleFeederRequest(owner, modelName, feederNum=1, writeInput=False, feederName='feeder1'):
	'''Route handler for creating a simple feeder.'''
	return _new_simple_feeder(owner, modelName, feederNum, writeInput, feederName)


def _new_simple_network(owner, modelName, networkNum=1, writeInput=False, networkName='network1'):
	'''Create a simple network file in the model directory.'''
	modelDir = path_manager.join("data", "Model", owner, modelName)
	for i in range(2, 6):
		networkPath = path_manager.join("data", "Model", owner, modelName, networkName + '.omt')
		if not os.path.isfile(networkPath):
			with open(os.path.join(_omfDir, 'static', 'SimpleNetwork.json')) as f:
				network_string = f.read()
			with locked_open(networkPath, 'w') as f:
				f.write(network_string)
			break
		else:
			networkName = 'network' + str(i)
	if writeInput:
		_write_to_input(modelDir, networkName, 'networkName' + str(networkNum))
	return 'Success'


@app.route("/newSimpleNetwork/<owner>/<modelName>/<int:networkNum>/<writeInput>", methods=["POST"])
@login_required
@write_permission_function
def newSimpleNetworkRequest(owner, modelName, networkNum=1, writeInput=False, networkName='network1'):
	'''Route handler for creating a simple network.'''
	return _new_simple_network(owner, modelName, networkNum, writeInput, networkName)


@app.route("/newBlankFeeder/<owner>", methods=["POST"])
@login_required
@write_permission_function
def newBlankFeeder(owner):
	'''This function is used for creating a new blank feeder.'''
	modelName = request.form.get("modelName","")
	feederName = secure_filename(str(request.form.get("feederNameNew",""))) or 'feeder'
	feederNum = secure_filename(str(request.form.get("feederNum", '1'))) or '1'
	modelDir = path_manager.join("data", "Model", owner, modelName)
	try:
		zpid_path = path_manager.join("data", "Model", owner, modelName, "ZPID.txt")
		os.remove(zpid_path)
		print("removed, ", zpid_path)
	except: pass
	_remove_feeder(owner, modelName, feederNum)
	_new_simple_feeder(owner, modelName, feederNum, False, feederName)
	_write_to_input(modelDir, feederName, 'feederName'+str(feederNum))
	if request.form.get("referrer") == "distribution":
		return redirect(url_for("distribution_get", owner=owner, modelName=modelName, feeder_num=feederNum))
	return redirect(url_for('feederGet', owner=owner, modelName=modelName, feederNum=feederNum))


# @app.route("/newBlankFile/<owner>", methods=["POST"])
# @login_required
# @write_permission_function
# def newBlankFile(owner):
# 	'''This function is used for creating a new blank feeder.'''
# 	modelName = request.form.get("modelName","")
# 	fileName = str(request.form.get("fileNameNew"))
# 	fileNum = request.form.get("fileNum",1)
# 	if fileName == '': fileName = 'feeder'
# 	modelDir = path_manager.join("data","Model", owner, modelName)
# 	try:
# 		os.remove("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt")
# 		print("removed, ", ("data/Model/"+owner+"/"+modelName+'/' + "ZPID.txt"))
# 	except: pass
# 	_remove_feeder(owner, modelName, feederNum)
# 	removeFile(owner, modelName, fileNum)
# 	newSimpleFeeder(owner, modelName, feederNum, False, feederName)
# 	newSimpleFile(owner, modelName, fileNum, False, fileName)
# 	_write_to_input(modelDir, feederName, 'feederName'+str(feederNum))
# 	_write_to_input(modelDir, fileName, 'feederName'+str(fileNum))
# 	if request.form.get("referrer") == "distribution":
# 		return redirect(url_for("distribution_text_get", owner=owner, modelName=modelName, file_num=fileNum))
# 	return redirect(url_for('fileGet', owner=owner, modelName=modelName, feederNum=feederNum))


@app.route("/newBlankNetwork/<owner>", methods=["POST"])
@login_required
@write_permission_function
def newBlankNetwork(owner):
	'''This function is used for creating a new blank network.'''
	modelName = request.form.get("modelName","")
	networkName = secure_filename(str(request.form.get("networkNameNew",""))) or 'network'
	networkNum = secure_filename(str(request.form.get("networkNum", '1'))) or '1'
	modelDir = path_manager.join("data","Model", owner, modelName)
	try:
		zpid_path = path_manager.join("data", "Model", owner, modelName, "ZPID.txt")
		os.remove(zpid_path)
		print("removed, ", zpid_path)
	except: pass
	_remove_network(owner, modelName, networkNum)
	_new_simple_network(owner, modelName, networkNum, False, networkName)
	_write_to_input(modelDir, networkName, 'networkName'+str(networkNum))
	return redirect(url_for('networkGet', owner=owner, modelName=modelName, networkNum=networkNum))


@app.route("/feederData/<owner>/<modelName>/<feederName>/")
@login_required
@read_permission_function
def feederData(owner, modelName, feederName):
	"""
	Perform feeder data processing for OMF helper-library workflows.
	"""
	filepath = path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')
	with locked_open(filepath) as feedFile:
		return feedFile.read(), 200, {'Content-Type': 'application/json'}


@app.route("/networkData/<owner>/<modelName>/<networkName>/")
@login_required
@read_permission_function
def networkData(owner, modelName, networkName):
	"""
	Perform network data processing for OMF helper-library workflows.
	"""
	filepath = path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	with locked_open(filepath) as netFile:
		thisNet = json.load(netFile)
	return json.dumps(thisNet), 200, {'Content-Type': 'application/json'}


def _cleanup_error_files(model_dir):
	'''Remove leftover error files from previous runs.'''
	for name in ['gridError.txt', 'error.txt', 'weatherError.txt']:
		try:
			os.remove(os.path.join(model_dir, name))
		except FileNotFoundError:
			pass


_RESERVED_FILENAMES = frozenset([
	'ZPID.txt', 'APID.txt', 'NPID.txt', 'CPID.txt', 'WPID.txt', 'TPPID.txt', 'PPID.txt',
	'allInputData.json', 'gridError.txt', 'error.txt', 'weatherError.txt',
	'matError.txt', 'cimError.txt',
])


def _cancel_pid_processes(model_dir):
	'''Kill background processes and remove their PID files.'''
	for name in ['ZPID.txt', 'APID.txt', 'NPID.txt', 'CPID.txt', 'WPID.txt']:
		pid_path = os.path.join(model_dir, name)
		try:
			with locked_open(pid_path) as f:
				pid = int(f.read())
			os.remove(pid_path)
			os.kill(pid, signal.SIGTERM)
		except (FileNotFoundError, ProcessLookupError, ValueError):
			pass


@app.route("/saveFeeder/<owner>/<modelName>/<feederName>/<int:feederNum>", methods=["POST"])
@login_required
@write_permission_function
def saveFeeder(owner, modelName, feederName, feederNum):
	"""Save feeder data. Also used for cancelling a file import, file conversion, or feeder-load overwrite."""
	model_dir = path_manager.join("data", "Model", owner, modelName)
	_cleanup_error_files(model_dir)
	_cancel_pid_processes(model_dir)
	# Validate the feeder path BEFORE writing metadata to prevent second-order injection
	feeder_file = path_manager.join("data", "Model", owner, modelName, feederName + ".omd")
	_write_to_input(model_dir, feederName, 'feederName' + str(feederNum))
	payload = json.loads(request.form.get('feederObjectJson', '{}'))
	if isinstance(payload, dict) and payload.get('type') == 'FeatureCollection':
		payload = omf.geo.convert_featurecollection_to_omd(payload)
	serialized = json.dumps(payload, indent=4)
	mode = 'r+' if os.path.isfile(feeder_file) else 'w'
	with locked_open(feeder_file, mode) as f:
		f.truncate(0)
		f.write(serialized)
	return 'Success'


@app.route("/saveFile/<owner>/<modelName>/<fileName>", methods=["POST"])
@login_required
@write_permission_function
def saveFile(owner, modelName, fileName):
	"""Save file data. Also used for cancelling a file import, file conversion, or file-load overwrite."""
	# Strip before checking: PathManager strips whitespace, so "ZPID.txt " would
	# bypass an exact-match blocklist but resolve to the reserved name.
	if fileName.strip() in _RESERVED_FILENAMES:
		return 'Reserved filename', 400
	model_dir = path_manager.join("data", "Model", owner, modelName)
	_cleanup_error_files(model_dir)
	_cancel_pid_processes(model_dir)
	# Validate the file path BEFORE writing metadata to prevent second-order injection
	file_file = path_manager.join("data", "Model", owner, modelName, fileName)
	_write_to_input(model_dir, fileName, 'circuitFileNameDSS') # TODO: Incorporate other files, not just dss
	payload = request.form.get('fileContents', '')
	mode = 'r+' if os.path.isfile(file_file) else 'w'
	with locked_open(file_file, mode) as f:
		f.truncate(0)
		f.write(payload)
	return 'Success'


@app.route("/saveNetwork/<owner>/<modelName>/<networkName>/<int:networkNum>", methods=["POST"])
@login_required
@write_permission_function
def saveNetwork(owner, modelName, networkName, networkNum):
	''' Save network data. '''
	model_dir = path_manager.join('data', 'Model', owner, modelName)
	# Validate the network path BEFORE writing metadata to prevent second-order injection
	filepath = path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	_write_to_input(model_dir, networkName, 'networkName' + str(networkNum))
	payload = json.loads(request.form.get('networkObjectJson', '{}'))
	serialized = json.dumps(payload, indent=4)
	mode = 'r+' if os.path.isfile(filepath) else 'w'
	with locked_open(filepath, mode) as f:
		f.truncate(0)
		f.write(serialized)
	return 'Success'


@app.route("/renameFeeder/<owner>/<modelName>/<oldName>/<newName>/<int:feederNum>", methods=["POST"])
@login_required
@write_permission_function
def renameFeeder(owner, modelName, oldName, newName, feederNum):
	''' rename a feeder. '''
	newName = secure_filename(newName) or 'feeder'
	model_dir_path = path_manager.join("data", "Model", owner, modelName)
	new_feeder_filepath = path_manager.join("data", "Model", owner, modelName, newName + ".omd")
	old_feeder_filepath = path_manager.join("data", "Model", owner, modelName, oldName + ".omd")
	if os.path.isfile(new_feeder_filepath) or not os.path.isfile(old_feeder_filepath):
		return "Failure"
	with locked_open(old_feeder_filepath, 'r+'):
		os.rename(old_feeder_filepath, new_feeder_filepath)
	_write_to_input(model_dir_path, newName, 'feederName' + str(feederNum))
	return 'Success'


@app.route("/renameNetwork/<owner>/<modelName>/<oldName>/<networkName>/<int:networkNum>", methods=["POST"])
@login_required
@write_permission_function
def renameNetwork(owner, modelName, oldName, networkName, networkNum):
	''' rename a network. '''
	networkName = secure_filename(networkName) or 'network'
	model_dir, new_network_filepath, old_network_filepath = [
		path_manager.join('data', 'Model', owner, modelName, filename) for filename in ('', networkName + '.omt', oldName + '.omt')
	]
	if os.path.isfile(new_network_filepath) or not os.path.isfile(old_network_filepath):
		return "Failure"
	with locked_open(old_network_filepath, 'r+'):
		os.rename(old_network_filepath, new_network_filepath)
	_write_to_input(model_dir, networkName, 'networkName' + str(networkNum))
	return 'Success'


def _remove_feeder(owner, modelName, feederNum, feederName=None):
	'''Remove a feeder .omd file and its key from allInputData.json.
	Raises on unexpected errors (PathTraversalError, IOError, etc.).'''
	allInput = _get_model_metadata(owner, modelName)
	modelDir = path_manager.join('data', 'Model', owner, modelName)
	feederName = allInput.get('feederName' + str(feederNum))
	if feederName is not None:
		omd_path = path_manager.join('data', 'Model', owner, modelName, str(feederName) + '.omd')
		try:
			os.remove(omd_path)
		except FileNotFoundError:
			pass
	allInput.pop('feederName' + str(feederNum), None)
	with locked_open(os.path.join(modelDir, 'allInputData.json'), 'r+') as f:
		f.truncate(0)
		json.dump(allInput, f, indent=4)


@app.route("/removeFeeder/<owner>/<modelName>/<int:feederNum>", methods=["POST"])
@app.route("/removeFeeder/<owner>/<modelName>/<int:feederNum>/<feederName>", methods=["POST"])
@login_required
@write_permission_function
def removeFeederRequest(owner, modelName, feederNum, feederName=None):
	''' Remove feeder from web.'''
	_remove_feeder(owner, modelName, feederNum)
	return 'Success', 200


@app.route("/loadFeeder/<frfeederName>/<frmodelName>/<modelName>/<int:feederNum>/<frUser>/<owner>", methods=["POST"])
@login_required
@write_permission_function
def loadFeeder(frfeederName, frmodelName, modelName, feederNum, frUser, owner):
	'''Load a feeder from one model to another.'''
	if frUser != "public":
		frUser = User.cu()
		frFeederPath = path_manager.join('data', 'Model', frUser, frmodelName, frfeederName + '.omd')
	else:
		frFeederPath = path_manager.join('static', 'publicFeeders', frfeederName + '.omd')
	print("Entered loadFeeder with info: frfeederName %s, frmodelName: %s, modelName: %s, feederNum: %s"%(frfeederName, frmodelName, str(modelName), str(feederNum)))
	# I can't use shutil.copyfile() becasue I need locks on the source and destination file
	#shutil.copyfile(os.path.join(frmodelDir, frfeederName + '.omd'), os.path.join(modelDir, feederName + '.omd'))
	with locked_open(frFeederPath) as inFeeder:
		feeder_string = inFeeder.read()
	feederName = _get_model_metadata(owner, modelName).get('feederName' + str(feederNum))
	destPath = path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')
	mode = 'r+' if os.path.isfile(destPath) else 'w'
	with locked_open(destPath, mode) as outFile:
		outFile.truncate(0)
		outFile.write(feeder_string)
	if request.form.get("referrer") == "distribution":
		return redirect(url_for("distribution_get", owner=owner, modelName=modelName, feeder_num=feederNum))
	return redirect(url_for('feederGet', owner=owner, modelName=modelName, feederNum=feederNum))


@app.route("/loadFile/<frfileName>/<frmodelName>/<modelName>/<int:fileNum>/<frUser>/<owner>", methods=["POST"])
@login_required
@write_permission_function
def loadFile(frfileName, frmodelName, modelName, fileNum, frUser, owner):
	'''Load a file from one model to another.'''
	if frUser != "public":
		frUser = User.cu()
		frFilePath = path_manager.join('data', 'Model', frUser, frmodelName, frfileName)
	else:
		frFilePath = path_manager.join('solvers', 'opendss', frfileName)
	print("Entered loadFile with info: frfileName %s, frmodelName: %s, modelName: %s, fileNum: %s"%(frfileName, frmodelName, str(modelName), str(fileNum)))
	# I can't use shutil.copyfile() because I need locks on the source and destination file
	#shutil.copyfile(os.path.join(frmodelDir, frfileName + '.omd'), os.path.join(modelDir, fileName + '.omd'))
	with locked_open(frFilePath) as inFile:
		file_string = inFile.read()
	fileName = _get_model_metadata(owner, modelName).get('fileName' + str(fileNum))
	destPath = path_manager.join('data', 'Model', owner, modelName, fileName)
	mode = 'r+' if os.path.isfile(destPath) else 'w'
	with locked_open(destPath, mode) as outFile:
		outFile.truncate(0)
		outFile.write(file_string)
	return redirect(url_for('distribution_text_get', owner=owner, modelName=modelName, fileName=fileName))


@app.route("/cleanUpFeeders/<owner>/<modelName>", methods=["POST"])
@login_required
@write_permission_function
def cleanUpFeeders(owner, modelName):
	'''Go through allInputData and fix feeder Name keys'''
	allInput = _get_model_metadata(owner, modelName)
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
	modelDir = path_manager.join("data", "Model", owner, modelName)
	with locked_open(os.path.join(modelDir, "allInputData.json"), "r+") as f:
		f.truncate(0)
		json.dump(allInput, f, indent=4)
	return redirect(url_for('showModel', owner=owner, modelName=modelName))


def _remove_network(owner, modelName, networkNum):
	'''Remove a network .omt file and its key from allInputData.json.
	Raises on unexpected errors (PathTraversalError, IOError, etc.).'''
	allInput = _get_model_metadata(owner, modelName)
	modelDir = path_manager.join('data', 'Model', owner, modelName)
	networkName = allInput.get('networkName' + str(networkNum))
	if networkName is not None:
		omt_path = path_manager.join('data', 'Model', owner, modelName, str(networkName) + '.omt')
		try:
			os.remove(omt_path)
		except FileNotFoundError:
			pass
	allInput.pop('networkName' + str(networkNum), None)
	with locked_open(os.path.join(modelDir, 'allInputData.json'), 'r+') as f:
		f.truncate(0)
		json.dump(allInput, f, indent=4)


@app.route("/removeNetwork/<owner>/<modelName>/<int:networkNum>", methods=["POST"])
@login_required
@write_permission_function
def removeNetworkRequest(owner, modelName, networkNum):
	'''Remove network from web.'''
	_remove_network(owner, modelName, networkNum)
	return 'Success', 200


@app.route("/climateChange/<owner>/<feederName>", methods=["POST"])
@login_required
@write_permission_function
def climateChange(owner, feederName):
	"""
	Perform climate change processing for OMF helper-library workflows.
	"""
	model_name = request.form.get('modelName')
	# Remove files that could be left over from a previous run
	filepaths = [
		path_manager.join('data', 'Model', owner, model_name, filename) for filename in ['error.txt', 'weatherAirport.csv', 'uscrn-weather-data.csv']
	]
	for fp in filepaths:
		if os.path.isfile(fp):
			os.remove(fp)
	# Don't bother writing WPID.txt here because /checkConversion doesn't distinguish between non-started processes and non-existant processes
	importOption = request.form.get('climateImportOption')
	zipCode = request.form.get('zipCode')
	station = request.form.get("uscrnStation")
	year_str = request.form.get("uscrnYear")
	importProc = Process(target=_background_climate_change, args=[owner, model_name, feederName, importOption, zipCode, station, year_str])
	importProc.start()
	return "Success"


def _background_climate_change(owner, modelName, feederName, importOption, zipCode, station, year_str):
	"""
	Internal helper for web background climate change processing.
	"""
	try:
		omdPath, pid_filepath, error_filepath = [
			path_manager.join('data', 'Model', owner, modelName, filename) for filename in [feederName + '.omd', 'WPID.txt', 'error.txt']
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
@login_required
@write_permission_function
def anonymize(owner, feederName):
	"""
	Perform anonymize processing for OMF helper-library workflows.
	"""
	modelName = request.form.get('modelName')
	# Validate paths before spawning background process
	path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')
	options = {
		'nameOption': request.form.get('anonymizeNameOption'),
		'locOption': request.form.get('anonymizeLocationOption'),
		'new_center_coords': request.form.get('new_center_coords'),
		'translationRight': request.form.get('translateRight'),
		'translationUp': request.form.get('translateUp'),
		'rotation': request.form.get('rotate'),
		'shufPerc': request.form.get('shufflePerc'),
		'noisePerc': request.form.get('noisePerc'),
		'modifyLengthSize': request.form.get('modifyLengthSize'),
		'smoothLoadGen': request.form.get('smoothLoadGen'),
		'shuffleLoadGen': request.form.get('shuffleLoadGen'),
		'addNoise': request.form.get('addNoise'),
		'scale': request.form.get('scale'),
	}
	importProc = Process(target=_background_anonymize, args=[owner, modelName, feederName, options])
	importProc.start()
	return 'Success'


def _background_anonymize(owner, modelName, feederName, options):
	"""
	Internal helper for web background anonymize processing.
	"""
	try:
		omdPath = path_manager.join('data', 'Model', owner, modelName, feederName + '.omd')
		pid_filepath = path_manager.join('data', 'Model', owner, modelName, 'NPID.txt')
		with locked_open(pid_filepath, 'w') as pid_file:
			pid_file.write(str(os.getpid()))
		with locked_open(omdPath, 'r') as inFile:
			inFeeder = json.load(inFile)
		# Name option
		newNameKey = None
		if options['nameOption'] == 'pseudonymize':
			newNameKey = anonymization.distPseudomizeNames(inFeeder)
		elif options['nameOption'] == 'randomize':
			anonymization.distRandomizeNames(inFeeder)
		# Location option
		if options['locOption'] == 'translation':
			geo.insert_missing_nodes(inFeeder)
			geo.insert_wgs84_coordinates(inFeeder)
			geo.transform_wgs84_coordinates(inFeeder, options['new_center_coords'], options['translationUp'], options['translationRight'], options['rotation'])
		elif options['locOption'] == 'randomize':
			anonymization.distRandomizeLocations(inFeeder)
		elif options['locOption'] == 'forceLayout':
			geo.insert_missing_nodes(inFeeder)
			geo.insert_wgs84_coordinates(inFeeder, force_layout=True, scale=options['scale'])
		# Electrical properties
		if options['modifyLengthSize'] == 'modifyLengthSize':
			anonymization.distModifyTriplexLengths(inFeeder)
			anonymization.distModifyConductorLengths(inFeeder)
		if options['smoothLoadGen'] == 'smoothLoadGen':
			anonymization.distSmoothLoads(inFeeder)
		if options['shuffleLoadGen'] == 'shuffleLoadGen':
			anonymization.distShuffleLoads(inFeeder, options['shufPerc'])
		if options['addNoise'] == 'addNoise':
			anonymization.distAddNoise(inFeeder, options['noisePerc'])
		with locked_open(omdPath, 'r+') as f:
			f.truncate(0)
			json.dump(inFeeder, f, indent=4)
		os.remove(pid_filepath)
		if newNameKey:
			return newNameKey
	except Exception:
		error_path = path_manager.join('data', 'Model', owner, modelName, 'gridError.txt')
		with locked_open(error_path, 'w') as errorFile:
			errorFile.write('anonymizeError')


@app.route("/zillowHouses", methods=["POST"])
@login_required
@write_permission_function
def zillow_houses():
	"""
	Perform zillow houses processing for OMF helper-library workflows.
	"""
	owner = request.form.get("user")
	model_name = request.form.get("modelName")
	model_dir = path_manager.join("data", "Model", owner, model_name)
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
	importProc = Process(target=_background_zillow_houses, args=[model_dir, triplex_objects])
	importProc.start()
	return ""


def _background_zillow_houses(model_dir, triplex_objects):
	"""
	Internal helper for web background zillow houses processing.
	"""
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
@login_required
@read_permission_function
def check_zillow_houses():
	"""
	Perform check zillow houses processing for OMF helper-library workflows.
	"""
	owner = request.form.get("user")
	model_name = request.form.get("modelName")
	model_dir = path_manager.join("data", "Model", owner, model_name)
	error_filepath = os.path.join(model_dir, "error.txt")
	if os.path.isfile(error_filepath):
		with locked_open(error_filepath) as f:
			error_message = f.read()
		return jsonify(error=error_message), 500
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
@login_required
@write_permission_function
def anonymizeTran(owner, networkName):
	"""
	Perform anonymize tran processing for OMF helper-library workflows.
	"""
	modelName = request.form.get('modelName')
	# Validate path before spawning background process
	path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	options = {
		'nameOption': request.form.get('anonymizeNameOption'),
		'locOption': request.form.get('anonymizeLocationOption'),
		'translationRight': request.form.get('translateRight'),
		'translationUp': request.form.get('translateUp'),
		'rotation': request.form.get('rotate'),
		'shufPerc': request.form.get('shufflePerc'),
		'noisePerc': request.form.get('noisePerc'),
		'shuffleLoadGen': request.form.get('shuffleLoadGen'),
		'addNoise': request.form.get('addNoise'),
	}
	importProc = Process(target=_background_anonymizeTran, args=[owner, modelName, networkName, options])
	importProc.start()
	pid_path = path_manager.join('data', 'Model', owner, modelName, 'TPPID.txt')
	with locked_open(pid_path, 'w') as outFile:
		outFile.write(str(importProc.pid))
	return 'Success'


def _background_anonymizeTran(owner, modelName, networkName, options):
	"""
	Internal helper for web background anonymize tran processing.
	"""
	omtPath = path_manager.join('data', 'Model', owner, modelName, networkName + '.omt')
	pid_path = path_manager.join('data', 'Model', owner, modelName, 'TPPID.txt')
	with locked_open(omtPath, 'r') as inFile:
		inNetwork = json.load(inFile)
	# Name options
	newBusKey = None
	if options['nameOption'] == 'pseudonymize':
		newBusKey = anonymization.tranPseudomizeNames(inNetwork)
	elif options['nameOption'] == 'randomize':
		anonymization.tranRandomizeNames(inNetwork)
	# Location options
	if options['locOption'] == 'translation':
		anonymization.tranTranslateLocations(inNetwork, options['translationRight'], options['translationUp'], options['rotation'])
	elif options['locOption'] == 'randomize':
		anonymization.tranRandomizeLocations(inNetwork)
	# Electrical properties
	if options['shuffleLoadGen']:
		anonymization.tranShuffleLoadsAndGens(inNetwork, options['shufPerc'])
	if options['addNoise']:
		anonymization.tranAddNoise(inNetwork, options['noisePerc'])
	with locked_open(omtPath, 'w') as outFile:
		json.dump(inNetwork, outFile, indent=4)
	os.remove(pid_path)
	if newBusKey:
		return newBusKey


@app.route("/checkAnonymizeTran/<owner>/<modelName>", methods=["GET"])
@login_required
@read_permission_function
def checkAnonymizeTran(owner, modelName):
	# print 'Check conversion status:', os.path.exists(pidPath), 'for path', pidPath                                  
    # checks to see if PID file exists, if theres no PID file process is done.         
	"""
	Perform check anonymize tran processing for OMF helper-library workflows.
	"""
	pidPath = path_manager.join('data', 'Model', owner, modelName, 'TPPID.txt')
	return jsonify(exists=os.path.exists(pidPath))


@app.route('/displayMap/<owner>/<modelName>/<int:feederNum>', methods=["GET"])
@login_required
@read_permission_function
def displayOmdMap(owner, modelName, feederNum):
	'''API to render omd on a leaflet map using a new template '''
	feeder_dict = _get_model_metadata(owner, modelName)
	feeder_name = feeder_dict.get('feederName' + str(feederNum))
	feeder_filepath = path_manager.join('data', 'Model', owner, modelName, feeder_name + '.omd')
	with locked_open(feeder_filepath) as f:
		omd = json.load(f)
	omf.geo.insert_missing_nodes(omd)
	omf.geo.insert_wgs84_coordinates(omd) # Place coordinate-less OMDs in Lousiana
	feature_collection = omf.geo.convert_omd_to_featurecollection(omd)
	featureCollection = json.dumps(feature_collection)
	components_collection = omf.geo.get_component_featurecollection()
	componentsCollection = json.dumps(components_collection)
	# - The csrf token is automatically passed to all template
	all_data = _get_data_names()
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


# - (2026-04-13): This function currently isn't called from anywhere
#def omdToGeoJson(feederName, modelDir):
#	''' Function to run in the background for displaying omd on leaflet map, by converting omd to geojson. '''
#	try:
#		geojsonFile, feederFile, conFile = [os.path.join(modelDir, filename) for filename in (feederName + '.geojson', feederName + '.omd', 'ZPID.txt')]
#		geojson = geo.omdGeoJson(feederFile)
#		with locked_open(geojsonFile, 'w') as f:
#			json.dump(geojson, f, indent=4)
#		os.remove(conFile)
#	except Exception as e:
#		filepath = os.path.join(modelDir, 'error.txt')
#		with locked_open(filepath, 'w') as errorFile:
#			errorFile.write(e)
#		os.remove(conFile)


@app.route('/commsMap/<owner>/<modelName>/<int:feederNum>', methods=["GET"])
@login_required
@read_permission_function
def commsMap(owner, modelName, feederNum):
	'''Render omc on a leaflet map.'''
	feederDict = _get_model_metadata(owner, modelName)
	feederName = feederDict.get('feederName' + str(feederNum))
	feederFile = path_manager.join('data', 'Model', owner, modelName, feederName + '.omc')
	with locked_open(feederFile) as commsGeoJson:
		geojson = json.load(commsGeoJson)
	return render_template('commsNetViz.html', geojson=geojson, owner=owner, modelName=modelName, feederNum=feederNum, feederName=feederName)


@app.route('/redisplayGrid', methods=["POST"])
@login_required
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


@app.route('/saveCommsMap/<owner>/<modelName>/<feederName>/<int:feederNum>', methods=["POST"])
@login_required
@write_permission_function
def saveCommsMap(owner, modelName, feederName, feederNum):
	# Validate feederName before passing to comms.saveOmc (which uses os.path.join)
	"""
	Save comms map data produced by this workflow.
	"""
	path_manager.join('data', 'Model', owner, modelName, feederName + '.omc')
	try:
		geoDict = request.get_json()
		model_dir = path_manager.join('data', 'Model', owner, modelName)
		comms.saveOmc(geoDict, model_dir, feederName)
		return jsonify(savemessage='Communications network saved')
	except:
		return jsonify(savemessage='Error saving communications network')


###################################################
# OTHER FUNCTIONS
###################################################


_HOME_MODEL_METADATA_RE = re.compile(r'"(runTime|modelType|created)"\s*:\s*"([^"]*)"')

def _fast_input_scan(file_path):
	'''Quickly read only the home-page metadata from allInputData.json.'''
	keys = {'runTime':'', 'modelType':'', 'created':''}
	with open(file_path, 'r') as file_data:
		pending = set(keys)
		tail = ''
		while pending:
			chunk = file_data.read(8192)
			if not chunk:
				break
			text = tail + chunk
			for key, val in _HOME_MODEL_METADATA_RE.findall(text):
				if key in pending:
					keys[key] = val
					pending.remove(key)
			tail = text[-100:]
	return keys

def _model_status_from_filenames(file_names):
	'''Return the same status used by the default model getStatus without an extra listdir.'''
	file_names = set(file_names)
	if "PPID.txt" in file_names:
		return 'running'
	elif "allOutputData.json" in file_names:
		return 'finished'
	else:
		return 'stopped'

def _admin_model_dirs():
	'''Yield all user-owned model directories with their already-listed files.'''
	model_root = path_manager.join('data', 'Model')
	try:
		owner_entries = os.scandir(model_root)
	except OSError:
		return
	with owner_entries:
		for owner_entry in owner_entries:
			if owner_entry.name.startswith('.') or not owner_entry.is_dir():
				continue
			try:
				model_entries = os.scandir(owner_entry.path)
			except OSError:
				continue
			with model_entries:
				for model_entry in model_entries:
					if model_entry.name.startswith('.') or not model_entry.is_dir():
						continue
					try:
						file_entries = os.scandir(model_entry.path)
					except OSError:
						continue
					with file_entries:
						file_names = [entry.name for entry in file_entries]
					yield {
						'owner': owner_entry.name,
						'name': model_entry.name,
						'path': model_entry.path,
						'file_names': file_names
					}


@app.route("/")
@login_required
def root():
	''' Render the home screen of the OMF. '''
	# Gather object names.
	publicModels = [{"owner":"public","name":x} for x in _safe_list_dir("data/Model/public/")]
	userModels = [{"owner":User.cu(), "name":x} for x in _safe_list_dir("data/Model/" + User.cu())]
	allModels = publicModels + userModels
	# Get models that have been shared with this user
	filepath = path_manager.join("data", "User",User.cu() + ".json")
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
	# Grab metadata for model instances.
	safe_models = []
	if isAdmin:
		for mod_info in _admin_model_dirs():
			if 'allInputData.json' not in mod_info['file_names']:
				continue
			mod = {'owner': mod_info['owner'], 'name': mod_info['name']}
			key_vals = _fast_input_scan(os.path.join(mod_info['path'], 'allInputData.json'))
			mod["runTime"] = key_vals.get("runTime","")
			mod["modelType"] = key_vals.get("modelType","")
			creation = key_vals.get("created","")
			mod["created"] = creation.split('.', 1)[0]
			mod["status"] = _model_status_from_filenames(mod_info['file_names'])
			safe_models.append(mod)
	else:
		for mod in allModels:
			try:
				# In the event of a poisoned .json file, skip the poisoned model.
				modPath = path_manager.join('data', 'Model', mod['owner'], mod['name'])
			except PathManager.PathTraversalError:
				continue
			metadata_path = os.path.join(modPath, 'allInputData.json')
			if not os.path.isfile(metadata_path):
				continue
			safe_models.append(mod)
			key_vals = _fast_input_scan(metadata_path)
			mod["runTime"] = key_vals.get("runTime","")
			mod["modelType"] = key_vals.get("modelType","")
			creation = key_vals.get("created","")
			try:
				mod["status"] = getattr(models, mod["modelType"]).getStatus(modPath)
				mod["created"] = creation.split('.', 1)[0]
				# mod["editDate"] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(os.stat(modPath).st_ctime))
			except: # the model type was deprecated, so the getattr will fail.
				mod["created"] = creation
				mod["status"] = "stopped"
				mod["editDate"] = "N/A"
	safe_models.sort(key=lambda x:x.get('created',''), reverse=True)
	allModels = safe_models
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
@login_required
@write_permission_function
def delete(objectType, objectName, owner):
	''' Delete models or feeders. '''
	if objectType == "Feeder":
		feeder_filepath = path_manager.join('data', 'Model', owner, objectName, 'feeder.omd')
		if os.path.isfile(feeder_filepath):
			os.remove(feeder_filepath)
		return redirect("/#feeders")
	elif objectType == "Model":
		model_dir = path_manager.join("data", "Model", owner, objectName)
		filepath = os.path.join(model_dir, "allInputData.json")
		if os.path.isfile(filepath):
			_cancel_pid_processes(model_dir)
			model_metadata = _get_model_metadata(owner, objectName)
			old_viewers = model_metadata.get("viewers")
			if old_viewers is not None:
				for v in old_viewers:
					_revoke_viewership(owner, objectName, v)
			shutil.rmtree(model_dir)
	return redirect("/")


@app.route("/downloadModelData/<owner>/<modelName>/<path:fullPath>")
@login_required
@read_permission_function
def downloadModelData(owner, modelName, fullPath):
	"""
	Perform download model data processing for OMF helper-library workflows.
	"""
	pathPieces = fullPath.split('/')
	fullValidatedPath = path_manager.join("data", "Model", owner, modelName, *pathPieces)
	dirPath = os.path.dirname(fullValidatedPath)
	fileName = os.path.basename(fullValidatedPath)
	if os.path.isdir(fullValidatedPath):
		shutil.make_archive(fullValidatedPath, 'zip', fullValidatedPath)
		fileName = fileName + '.zip'
	return send_from_directory(dirPath, fileName, as_attachment=True)


@app.route("/uniqObjName/<objtype>/<owner>/<modelName>")
@app.route("/uniqObjName/<objtype>/<owner>/<modelName>/<name>")
@login_required
def uniqObjName(objtype, owner, modelName=None, name=None):
	"""Checks if a given object type/owner/name is unique. More like checks if a file exists on the server"""
	print("Entered uniqobjname", owner, modelName, name)
	# Inline authorization (replaces @read_permission_function).
	# Model checks only need ownership — the model may not exist yet.
	# Feeder/Network/circuitFile checks need the parent model to exist
	# and the user to have read access.
	if objtype == 'Model':
		if owner != User.cu() and User.cu() != 'admin':
			return redirect('/')
	else:
		if owner == 'public':
			pass  # Any authenticated user can check public resources
		else:
			model_metadata_path = path_manager.join('data', 'Model', owner, modelName, 'allInputData.json')
			if not os.path.isfile(model_metadata_path):
				return redirect('/')
			if owner != User.cu() and not _is_authorized_model_viewer(owner, modelName) and User.cu() != 'admin':
				return redirect('/')
	# For Model type, the 3-segment route puts the name-to-check in modelName.
	if objtype == 'Model':
		name = modelName
	original_name = name
	# Sanitize the name the same way creation routes do so the uniqueness
	# check matches the actual filename that would be written to disk.
	FALLBACKS = {'Model': 'model', 'Feeder': 'feeder', 'circuitFile': 'feeder', 'Network': 'network'}
	name = secure_filename(name) or FALLBACKS.get(objtype, 'file')
	# If the name collapsed to its reserved fallback, it always "exists" (reserved).
	if name == FALLBACKS.get(objtype):
		return jsonify(exists=True)
	def _build_path(n):
		if objtype == 'Model':
			return path_manager.join('data', 'Model', owner, n)
		if objtype == 'Feeder':
			if owner == 'public':
				return path_manager.join('static', 'publicFeeders', n + '.omd')
			return path_manager.join('data', 'Model', owner, modelName, n + '.omd')
		if objtype == 'Network':
			return path_manager.join('data', 'Model', owner, modelName, n + '.omt')
		if objtype == 'circuitFile':
			if owner == 'public':
				return path_manager.join('solvers', 'opendss', n)
			return path_manager.join('data', 'Model', owner, modelName, n)
	# Check sanitized path first, then fall back to original name for legacy files.
	exists = os.path.exists(_build_path(name))
	if not exists and original_name != name:
		try:
			exists = os.path.exists(_build_path(original_name))
		except path_manager.PathTraversalError:
			# - There shouldn't be any legacy filenames with malicious characters, but if there are, they're orphaned
			pass
	return jsonify(exists=exists)


if __name__ == "__main__":
	if platform.system() == "Darwin":  # MacOS
		os.environ['no_proxy'] = '*' # Workaround for macOS fork behavior with multiprocessing and urllib.
		os.environ['NO_PROXY'] = '*' # Workaround for above in python3.
		import multiprocessing
		multiprocessing.set_start_method('forkserver') # Workaround for new Catalina exec/fork behavior
	template_files = ["templates/"+ x  for x in _safe_list_dir("templates")]
	model_files = ["models/" + x for x in _safe_list_dir("models")]
	print('App starting with gunicorn. Errors are going to omf.error.log.')
	appProc = Popen(['gunicorn', '-w', '5', '-b', '0.0.0.0:5001', '--preload', 'web:app','--worker-class=sync', '--access-logfile', 'omf.access.log', '--error-logfile', 'omf.error.log', '--capture-output','--timeout=100'])
	appProc.wait()
	# app.run(debug=True, host="0.0.0.0", port=5001, extra_files=template_files + model_files)
