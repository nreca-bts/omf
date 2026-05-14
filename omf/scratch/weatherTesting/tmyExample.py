from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path


modelDir = Path.cwd()
long = -97.1292
lat = 33.2164
attributes = ['dni','dhi','ghi','wind_speed','air_temperature']
		
nrlAPIResponse = weather.nrl_get_nsrdb_data(data_set="goes_tmy", longitude=long, latitude=lat, year="tmy", api_key="rnvNJxNENljf60SBKGxkGVwkXls4IAKs1M8uZl56", attributes=attributes, filename=Path(modelDir,"output_tmy_data.csv"))
import pandas as pd
df = pd.read_csv("output_tmy_data.csv")