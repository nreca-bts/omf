import logging
root_logger = logging.getLogger()
gun_err = logging.getLogger('gunicorn.error')
if getattr(gun_err, 'handlers', None):
	# If there are any existing Gunicorn handlers, get them into the root logger
	for h in gun_err.handlers:
		root_logger.addHandler(h)
else:
	# If there are no Gunicorn handlers configure to sys.stderr
	# This still works with Gunicorn with --capture-output
	handler = logging.StreamHandler(sys.stderr)
	handler.setFormatter(logging.Formatter('%(asctime)s %(name)s: %(message)s'))
	root_logger.addHandler(handler)
root_logger.setLevel(logging.DEBUG)  # Lowest level