from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path

# I made a model called copernicusTest, and ran it to get the data.
modelDir = Path(__neoMetaModel__._omfDir, "data", "Model", "admin", "copernicusTest")
defaultCSVFileName = "output_cdsWeatherDataFull.csv"

weather_ds_df = weather.cds_process_weather_data(modelDir=modelDir)

ac_dc_df = weather.get_solar(Path(modelDir, defaultCSVFileName))
print(ac_dc_df.head)
ds = weather.get_wind(weather_ds_df[0])
print(ds)