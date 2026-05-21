"""
Register OMF grid-technology analysis models for the web application and command-line
tooling.
"""

import os as _os

# Make sure this module is on the path regardless of where its imported from.
_myDir = _os.path.dirname(_os.path.abspath(__file__))

from omf.models import storageArbitrage
from omf.models import rfCoverage
from omf.models import phaseBalance
from omf.models import solarSunda
from omf.models import cvrStatic
from omf.models import networkStructure
from omf.models import weatherPull
from omf.models import phaseId
from omf.models import gridlabMulti
from omf.models import vbatDispatch
from omf.models import cvrDynamic
from omf.models import solarDisagg
from omf.models import hostingCapacity
from omf.models import resilientDist
from omf.models import evInterconnection
from omf.models import solarEngineering
from omf.models import solarConsumer
from omf.models import forecastLoad
from omf.models import microgridControl
from omf.models import cyberInverters
from omf.models import transmission
from omf.models import smartSwitching
from omf.models import anomalyDetector
from omf.models import solarFinancial
from omf.models import derInterconnection
from omf.models import storagePeakShave
from omf.models import forecastTool
from omf.models import commsBandwidth
from omf.models import microgridDesign
from omf.models import voltageDrop
from omf.models import modelSkeleton
from omf.models import solarCashflow
from omf.models import demandResponse
from omf.models import pvWatts
from omf.models import storageDeferral
from omf.models import circuitRealTime
from omf.models import flisr
from omf.models import outageCost
from omf.models import faultAnalysis
from omf.models import vbatStacked
from omf.models import disaggregation
from omf.models import restoration
from omf.models import resilientCommunity
from omf.models import transformerPairing
from omf.models import derConsumer
from omf.models import derUtilityCost
from omf.models import wildfireAnticipation
from omf.models import evRange
from omf.models import hostingExpansion
from omf.models import pvWatts
#from omf.models import microgridPlan
