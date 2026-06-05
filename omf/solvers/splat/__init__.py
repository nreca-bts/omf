"""
Install and run SPLAT! radio-propagation studies for OMF RF coverage models.
"""

import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from os.path import join as pJoin

_SPLAT_AUTO_INSTALL_ENV = "OMF_SPLAT_AUTO_INSTALL"
_splat_install_checked = False

def _command_on_path(command):
	"""
	Internal helper for command on path processing.
	"""
	return shutil.which(command) is not None

def _splat_available():
	"""
	Internal helper for splat available processing.
	"""
	return _command_on_path("splat") and _command_on_path("srtm2sdf")

def _run_installer_command(command, cwd=None):
	"""
	Internal helper for run installer command processing.
	"""
	try:
		return subprocess.call(command, cwd=cwd) == 0
	except Exception as err:
		print("Unable to run SPLAT! installer command:", err)
		return False

def _download(url, destination):
	"""
	Internal helper for download processing.
	"""
	opener = urllib.request.build_opener()
	opener.addheaders = [('User-agent', 'Mozilla/5.0')]
	urllib.request.install_opener(opener)
	urllib.request.urlretrieve(url, destination)

def _linux_distro_text():
	"""
	Internal helper for linux distro text processing.
	"""
	try:
		with open("/etc/os-release") as os_release:
			return os_release.read().lower()
	except OSError:
		return ""

def _install_splat_on_macos():
	"""
	Internal helper for install splat on macos processing.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		archive = pJoin(temp_dir, "splat-1.4.2-osx.tgz")
		_download("https://www.qsl.net/kd2bd/splat-1.4.2-osx.tgz", archive)
		if not _run_installer_command(["tar", "-xvzf", archive], cwd=temp_dir):
			return
		source_dir = pJoin(temp_dir, "splat-1.4.2")
		configure = pJoin(source_dir, "configure")
		try:
			with open(configure) as configure_file:
				configure_text = configure_file.read()
			with open(configure, "w") as configure_file:
				configure_file.write(configure_text.replace('ans=""', 'ans="2"'))
		except OSError as err:
			print("Unable to patch SPLAT! configure script:", err)
			return
		_run_installer_command(["sudo", "bash", "configure"], cwd=source_dir)

def _install_splat_if_missing():
	'''Best-effort SPLAT! install for platforms with known install commands.'''
	global _splat_install_checked
	if _splat_install_checked:
		return
	_splat_install_checked = True
	if os.environ.get(_SPLAT_AUTO_INSTALL_ENV, "1").lower() in ("0", "false", "no"):
		return
	if _splat_available():
		return
	system = platform.system()
	print("SPLAT! was not found on PATH; attempting SPLAT! install.")
	if system == "Linux":
		if "ubuntu" in _linux_distro_text():
			_run_installer_command(["sudo", "apt-get", "-y", "update"])
			_run_installer_command(["sudo", "apt-get", "-y", "install", "splat"])
		else:
			print("Automatic SPLAT! install is only configured for Ubuntu Linux.")
	elif system == "Darwin":
		_install_splat_on_macos()
	elif system == "Windows":
		print("Automatic SPLAT! install is not configured for Windows.")
	if not _splat_available():
		print("SPLAT! install did not add `splat` and `srtm2sdf` to PATH.")

def _require_command(command):
	"""
	Internal helper for require command processing.
	"""
	if not _command_on_path(command):
		raise RuntimeError(
			f"SPLAT! command `{command}` was not found on PATH. "
			f"Install SPLAT! or set {_SPLAT_AUTO_INSTALL_ENV}=1 to allow OMF to try installing it."
		)

def run_srtm2sdf(hgt_file, cwd=None):
	"""
	Run the srtm2sdf workflow and return its results.
	"""
	_require_command("srtm2sdf")
	return subprocess.Popen(["srtm2sdf", hgt_file], cwd=cwd).wait()

def run(args, cwd=None):
	"""
	Run the wrapped solver workflow and return its results or status.
	"""
	_require_command("splat")
	return subprocess.Popen(["splat"] + args, cwd=cwd).wait()

_install_splat_if_missing()
