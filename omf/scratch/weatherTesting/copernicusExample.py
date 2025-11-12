from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path

# I made a model called copernicusTest, and ran it to get the data.
modelDir = Path(__neoMetaModel__._omfDir, "scratch", "weatherTesting")
cdsFile = Path(modelDir, "output_cdsWeatherDataFull.csv")
#weather_ds_df = weather.cds_processWeatherData(modelDir=modelDir)
ac_dc_df = weather.cds_pySAM_getSolar(cdsFile)
print(ac_dc_df.head)
