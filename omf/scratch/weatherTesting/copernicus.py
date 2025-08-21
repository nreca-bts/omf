from omf import weather

weather_ds_df = weather.process_weather_data()

weather.get_solar(weather_ds_df[1])
weather.get_wind(weather_ds_df[0])