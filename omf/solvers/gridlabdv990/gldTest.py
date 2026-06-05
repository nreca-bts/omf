"""
Smoke-test the bundled GridLAB-D v9.9.0 executable from OMF solver packaging.
"""

import subprocess, os

myEnv = os.environ.copy()
myEnv['GLPATH'] = '/home/osboxes/Desktop/omf/omf/solvers/gridlabdv990/'
proc = subprocess.Popen('/home/osboxes/Desktop/omf/omf/solvers/gridlabdv990/gridlabd.bin /home/osboxes/Desktop/omf/omf/scratch/feeder.glm', stdout=subprocess.PIPE, shell=True, env=myEnv)
(out, err) = proc.communicate()