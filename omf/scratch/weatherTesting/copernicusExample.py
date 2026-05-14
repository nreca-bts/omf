from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path
from omf.solvers import pysam

# I made a model called copernicusTest, and ran it to get the data.
modelDir = Path(__neoMetaModel__._omfDir, "scratch", "weatherTesting")
cdsFile = Path(modelDir, "output_cdsWeatherDataFull.csv")
#weather_ds_df = weather.cds_processWeatherData(modelDir=modelDir)
ac_dc_df = pysam.cds_pySAM_getSolar(cdsFile)
print(ac_dc_df.head)

# Not copernicus data but testing the nrel get wind stuff
scratch_dir = Path(__neoMetaModel__._omfDir, "scratch", "weatherTesting")
pysam.nrel_pysamWind(scratch_dir, 2009, latitude=40.770996916, longitude=-73.904663048)

