# Update this OMF install to the latest from the source tree.
if [ "$(id -u)" != "0" ]; then
	echo "This script must be run as root" 1>&2
	exit 1
else
	echo "** Stopping the service."
	systemctl stop omf
	# Local backup disabled since we use a more durable AWS backup now.
	# echo "** Backing up data folder."
	# tar -czf ~/dataBackup.tgz /omf/omf/data
	echo "** Backing up credentials."
	cp /omf/omf/data/User/admin.json ~/admin.json
	cp /omf/omf/emailCredentials.key ~/emailCredentials.key
	echo "** Pulling the latest source from git."
	git reset --hard
	git pull
	echo "** Restoring our admin user and keys."
	cp ~/admin.json /omf/omf/data/User/admin.json
	cp ~/emailCredentials.key /omf/omf/emailCredentials.key	
	echo "** Setting permissions."
	chown -R omf:omf /omf
	echo "** Re-run install to handle any missing requirements."
	python3 -m pip install /omf/
	echo "** Restarting the service."
	systemctl start omf
fi