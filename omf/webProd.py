"""
Configure the production OMF web service entrypoint around the shared web application.
"""
import web, pathlib
from subprocess import Popen
from flask import request, send_from_directory

# Note: sudo python webProd.py on macOS since this will open low numbered ports.
# If you need some test certs: openssl req -x509 -newkey rsa:4096 -nodes -out omfDevCert.pem -keyout omfDevKey.pem -days 365 -subj '/CN=localhost/O=NoCompany/C=US'

reApp = web.Flask('OMFR')
THIS_FILES_PATH = pathlib.Path(__file__).parent.absolute()

@reApp.route('/')
def index():
	"""
	Perform index processing for OMF helper-library workflows.
	"""
	return 'NA'

@reApp.before_request
def before_request():
	"""
	Perform before request processing for OMF helper-library workflows.
	"""
	if '/.well-known/acme-challenge' in request.url:
		try:
			filename = request.url.split('/')[-1]
		except Exception:
			filename = 'none'
		return send_from_directory(f'{THIS_FILES_PATH}/.well-known/acme-challenge', filename)
	if web.request.url.startswith('http://'):
		url = web.request.url.replace('http://', 'https://', 1)
		return web.redirect(url, code=301)

if __name__ == "__main__":
	# Start redirector:
	redirProc = Popen(['gunicorn', '-w', '5', '-b', '0.0.0.0:80', 'webProd:reApp'])
	# Start application:
	appProc = Popen(['gunicorn', '-w', '5', '-b', '0.0.0.0:443', '--certfile=/etc/letsencrypt/live/omf.coop/fullchain.pem', '--keyfile=/etc/letsencrypt/live/omf.coop/privkey.pem', '--preload', 'web:app','--worker-class=sync', '--access-logfile', 'omf.access.log', '--error-logfile', 'omf.error.log', '--capture-output', '--timeout=100'])
	appProc.wait()