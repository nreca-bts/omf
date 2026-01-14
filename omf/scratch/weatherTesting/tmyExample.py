from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path


modelDir = Path.cwd()
longitude = -97.1292
lati = 33.2164
attributes = ['dni','dhi','ghi','wind_speed','air_temperature']
		
weather.nrel_getTMYData(modelDir=modelDir, attributes=attributes, longitude=longitude, latitude=lati)
import pandas as pd

df = pd.read_csv("output_tmy_data.csv")