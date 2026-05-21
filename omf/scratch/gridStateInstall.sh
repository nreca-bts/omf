#!/bin/bash

# This script installs the OMF on top of the existing GridState installation. Every Jupyter notebook user gets their own Docker container via
# JupyterHub, so I can't mess up the GridState installation

# Install missing packages
sudo apt-get -y update && sudo apt-get install -y git python-pip locales
# Generate a locale required by Cyme conversion in the OMF
sudo sed -i 's/^# *\(en_US.UTF-8\)/\1/' /etc/locale.gen && sudo locale-gen
# Get the repository
cd /home/jovyan
git clone https://github.com/dpinney/omf.git
cd /home/jovyan/omf
# Set the container environment such that Python commands point to the Python 2 installation
alias pip='sudo /usr/bin/pip2'
alias python='sudo /usr/bin/python2'
sudo mv /usr/local/bin/python /usr/local/bin/python.bkp
sudo mv /usr/local/bin/pip /usr/local/bin/pip.bkp
sudo ln -s /usr/bin/python /usr/local/bin/python
sudo ln -s /usr/bin/pip2 /usr/local/bin/pip
# Run the install script
sudo python install.py
# Install non-standard packages, if possible. Tensorflow is fine, prophet is not
sudo pip install tensorflow
#sudo pip install prophet
# Configure Jupyter notebook
sudo python2 -m pip install ipykernel
# Installing the kernelspec with sudo, but don't use sudo. There is only one user per container, so a system-wide kernelspec vs. a user-specific
# kernelspec is irrelevant regardless
python2 -m ipykernel install --user
# Install requirements.txt again because matplotlib doesn't install
sudo pip install -r requirements.txt
# Restore the original GridState environment
sudo mv /usr/local/bin/python.bkp /usr/local/bin/python
sudo mv /usr/local/bin/pip.bkp /usr/local/bin/pip
unalias python
unalias pip