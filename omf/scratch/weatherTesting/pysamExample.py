from omf import weather
from omf.models import __neoMetaModel__
from pathlib import Path

# Not copernicus data but testing the nrel get wind stuff
scratch_dir = Path(__neoMetaModel__._omfDir, "scratch", "weatherTesting")
weather.nrel_pysamWind(scratch_dir, 2009, latitude=40.770996916, longitude=-73.904663048)