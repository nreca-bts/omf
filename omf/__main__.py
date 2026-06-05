"""Production command line controls for the OMF."""

import argparse, os, subprocess, sys, pathlib

THIS_FILES_PATH = pathlib.Path(__file__).parent.absolute()

def _is_root():
	""" Check if the current user is root. """
	if hasattr(os, 'geteuid') and os.geteuid() == 0:
		return True
	print('This command must be run as root', file=sys.stderr)
	return False

def prod_install():
	""" Install OMF for production use. WARNING: NOT TESTED. """
	if not _is_root(): return 1
	print('** Creating the omf user and group.')
	subprocess.run(['useradd', '-r', '-s', '/bin/false', 'omf'])
	subprocess.run(['groupadd', '-r', 'omf'])
	print('** Installing the source tree.')
	subprocess.run(['git', 'clone', 'https://github.com/nreca-bts/omf', '/omf'])
	subprocess.run(['python3', '-m', 'pip', 'install', '/omf/'])
	subprocess.run(['chown', '-R', 'omf:omf', '/omf'])
	print('** Setting up the systemd service.')
	service_content = pathlib.Path(f'{THIS_FILES_PATH}/static/omf.service').read_text()
	pathlib.Path('/etc/systemd/system/omf.service').write_text(service_content)
	subprocess.run(['systemctl', 'daemon-reload'])
	subprocess.run(['systemctl', 'enable', 'omf.service'])
	print('** Setting up certs.')
	subprocess.run(['mkdir', '-p', '/omf/omf/.well-known/acme-challenge'])
	subprocess.run(['snap', 'install', 'certbot', '--classic'])
	subprocess.run(['certbot', 'certonly', '--webroot', '-w', '/omf/omf', '-d', 'omf.coop', '-v'])
	print('** Starting the service.')
	subprocess.run(['systemctl', 'start', 'omf'])
	return 0

def prod_update():
	""" Update a prod OMF deployment. """
	if not _is_root(): return 1
	print('** Stopping the service.')
	subprocess.run(['systemctl', 'stop', 'omf'])
	print('** Pulling the latest source from git.')
	subprocess.run(['git', '-C', '/omf', 'reset', '--hard'])
	subprocess.run(['git', '-C', '/omf', 'pull'])
	print('** Setting permissions.')
	subprocess.run(['chown', '-R', 'omf:omf', '/omf'])
	print('** Re-run install to handle any missing requirements.')
	subprocess.run(['python3', '-m', 'pip', 'install', '/omf/'])
	print('** Restarting the service.')
	subprocess.run(['systemctl', 'start', 'omf'])
	return 0

def restart():
	""" Restart the OMF service. """
	if not _is_root(): return 1
	print('** Restarting the service.')
	subprocess.run(['systemctl', 'restart', 'omf'])
	return 0

def logs():
	""" Tail the OMF logs. """
	if not _is_root(): return 1
	subprocess.run(['journalctl', '-u', 'omf', '-r', '-f'])
	return 0

def main(argv=None):
	parser = argparse.ArgumentParser(prog='python3 -m omf')
	subparsers = parser.add_subparsers(dest='command')
	subparsers.add_parser('prod_install', help='Install OMF for production use.')
	subparsers.add_parser('prod_update', help='Update a cloud OMF deployment.')
	subparsers.add_parser('restart', help='Restart the OMF service.')
	subparsers.add_parser('logs', help='Tail the OMF logs.')
	args = parser.parse_args(argv)
	if args.command == 'prod_install':
		return prod_install()
	if args.command == 'prod_update':
		return prod_update()
	if args.command == 'restart':
		return restart()
	if args.command == 'logs':
		return logs()
	parser.print_help()
	return 1

if __name__ == '__main__':
	sys.exit(main())
