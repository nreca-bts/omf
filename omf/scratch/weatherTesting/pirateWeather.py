import requests
import omf
from pandas import date_range
_key_pirateweather = "xclxUibBDfg2pVwjHkfDBVVyMrFTTfc0"
lat = 40
long = -73
base_url = "https://api.pirateweather.net/forecast/"
year = 2022
times = list(date_range('{}-01-01'.format(year), '{}-12-31'.format(year)))
# time_test = requests.get(f'https://timemachine.pirateweather.net/forecast/{_key_pirateweather}/{lat},{long},{times[0].isoformat()}?exclude=daily&units=si')
data = omf.weather.pullPirateWeather(2022, 42, 99, datatype="tmpc", units="si")

