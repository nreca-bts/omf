# -*- coding: utf-8 -*
"""
Feed-in model class using windpowerlib.

SPDX-FileCopyrightText: Birgit Schachler
SPDX-FileCopyrightText: Uwe Krien <krien@uni-bremen.de>
SPDX-FileCopyrightText: Stephan Günther
SPDX-FileCopyrightText: Stephen Bosch
SPDX-FileCopyrightText: Patrik Schönfeldt <patrik.schoenfeldt@dlr.de>

SPDX-License-Identifier: MIT

This module holds implementations of feed-in models using the python library
windpowerlib to calculate wind power feed-in.
"""

from copy import deepcopy

import pandas as pd
from windpowerlib import ModelChain as WindpowerlibModelChain
from windpowerlib import (
    TurbineClusterModelChain as WindpowerlibClusterModelChain,
)
from windpowerlib import WindFarm as WindpowerlibWindFarm
from windpowerlib import WindTurbine as WindpowerlibWindTurbine
from windpowerlib import WindTurbineCluster as WindpowerlibWindTurbineCluster

from .base import WindpowerModelBase

# from feedinlib import WindPowerPlant


class WindpowerlibTurbine(WindpowerModelBase):
    r"""
    Model to determine the feed-in of a wind turbine using the windpowerlib.

    The windpowerlib [1]_ is a python library for simulating the performance of
    wind turbines and farms. For more information about the model check the
    documentation of the windpowerlib [2]_.

    Notes
    ------
    In order to use this model various power plant and model parameters have to
    be provided. See :attr:`~.power_plant_requires` as well as
    :attr:`~.requires` for further information. Furthermore, the weather
    data used to calculate the feed-in has to have a certain format. See
    :meth:`~.feedin` for further information.

    References
    ----------
    .. [1] `windpowerlib on github <https://github.com/wind-python/windpowerlib>`_
    .. [2] `windpowerlib documentation <https://windpowerlib.readthedocs.io>`_

    See Also
    --------
    :class:`~.models.Base`
    :class:`~.models.WindpowerModelBase`

    """  # noqa: E501

    def __init__(self, **kwargs):
        """ """
        super().__init__(**kwargs)
        self.power_plant = None

    def __repr__(self):
        return "windpowerlib_single_turbine"

    @property
    def power_plant_requires(self):
        r"""
        The power plant parameters this model requires to calculate a feed-in.

        The required power plant parameters are:

        `hub_height`, `power_curve/power_coefficient_curve/turbine_type`

        hub_height (float)
            Hub height in m.

            See also :wind_turbine:`WindTurbine.hub_height <windpowerlib.\
            wind_turbine.WindTurbine.hub_height>` in windpowerlib
            documentation.
        power_curve (:pandas:`pandas.DataFrame<frame>` or dict)
            DataFrame/dictionary with wind speeds in m/s and corresponding
            power curve value in W.

            See also :wind_turbine:`WindTurbine.power_curve <windpowerlib.\
            wind_turbine.WindTurbine.power_curve>` in windpowerlib
            documentation.
        power_coefficient_curve (:pandas:`pandas.DataFrame<frame>` or dict)
            DataFrame/dictionary with wind speeds in m/s and corresponding
            power coefficient.

            See also :wind_turbine:`WindTurbine.power_coefficient_curve \
            <windpowerlib.wind_turbine.WindTurbine.power_coefficient_curve>`
            in windpowerlib documentation.
        turbine_type (str)
            Name of the wind turbine type as in the oedb turbine library. Use
            :func:`~.get_power_plant_data` with `dataset` =
            'oedb_turbine_library' to get an overview of all provided turbines.
            See the data set metadata [3]_ for further information on provided
            parameters.

        References
        ----------
        .. [3] `oedb wind turbine library <https://openenergy-platform.org/dataedit/view/supply/wind_turbine_library>`_

        """  # noqa: E501
        required = [
            "hub_height",
            ["power_curve", "power_coefficient_curve", "turbine_type"],
        ]
        if super().power_plant_requires is not None:
            required.extend(super().power_plant_requires)
        return required

    @property
    def requires(self):
        r"""
        The parameters this model requires to calculate a feed-in.

        This model does not require any additional model parameters.

        """
        required = []
        if super().requires is not None:
            required.extend(super().requires)
        return required

    @property
    def nominal_power_wind_power_plant(self):
        """
        Nominal power of wind turbine in Watt.

        See :wind_turbine:`WindTurbine.nominal_power <windpowerlib.\
        wind_turbine.WindTurbine.nominal_power>` in windpowerlib for further
        information.

        """
        if self.power_plant:
            return self.power_plant.nominal_power
        else:
            return None

    def _power_plant_requires_check(self, parameters):
        """
        Function to check if all required power plant parameters are provided.

        Power plant parameters this model requires are specified in
        :attr:`~.power_plant_requires`.

        Parameters
        -----------
        parameters : list(str)
            List of provided power plant parameters.

        """
        for k in self.power_plant_requires:
            if not isinstance(k, list):
                if k not in parameters:
                    raise AttributeError(
                        "The specified model '{model}' requires power plant "
                        "parameter '{k}' but it's not provided as an "
                        "argument.".format(k=k, model=self)
                    )
            else:
                # in case one of several parameters can be provided
                if not list(filter(lambda x: x in parameters, k)):
                    raise AttributeError(
                        "The specified model '{model}' requires one of the "
                        "following power plant parameters '{k}' but neither "
                        "is provided as an argument.".format(k=k, model=self)
                    )

    def instantiate_turbine(self, **kwargs):
        """
        Instantiates a :windpowerlib:`windpowerlib.WindTurbine \
        <windpowerlib.wind_turbine.WindTurbine>` object.

        Parameters
        -----------
        **kwargs
            See `power_plant_parameters` parameter in :meth:`~.feedin` for more
            information.

        Returns
        --------
        :windpowerlib:`windpowerlib.WindTurbine \
            <windpowerlib.wind_turbine.WindTurbine>`
            Wind turbine to calculate feed-in for.

        """
        return WindpowerlibWindTurbine(**kwargs)

    def feedin(self, weather, power_plant_parameters, **kwargs):
        r"""
        Calculates power plant feed-in in Watt.

        This function uses the windpowerlib's :windpowerlib:`ModelChain \
        <windpowerlib.modelchain.ModelChain>` to calculate the feed-in for the
        given weather time series and wind turbine.

        Parameters
        ----------
        weather : :pandas:`pandas.DataFrame<dataframe>`
            Weather time series used to calculate feed-in. See `weather_df`
            parameter in windpowerlib's Modelchain :windpowerlib:`run_model \
            <windpowerlib.modelchain.ModelChain.run_model>` method for
            more information on required variables, units, etc.
        power_plant_parameters : dict
            Dictionary with power plant specifications. Keys of the dictionary
            are the power plant parameter names, values of the dictionary hold
            the corresponding value. The dictionary must at least contain the
            required power plant parameters (see
            :attr:`~.power_plant_requires`) and may further contain optional
            power plant parameters (see :windpowerlib:`windpowerlib.\
            WindTurbine <windpowerlib.wind_turbine.WindTurbine>`).
        **kwargs :
            Keyword arguments can be used to overwrite the windpowerlib's
            :windpowerlib:`ModelChain <windpowerlib.modelchain.ModelChain>`
            parameters.

        Returns
        -------
        :pandas:`pandas.Series<series>`
            Power plant feed-in time series in Watt.

        """
        self.power_plant = self.instantiate_turbine(**power_plant_parameters)
        mc = WindpowerlibModelChain(self.power_plant, **kwargs)
        return mc.run_model(weather).power_output


class WindpowerlibTurbineCluster(WindpowerModelBase):
    """
    Model to determine the feed-in of a wind turbine cluster using the
    windpowerlib.

    The windpowerlib [1]_ is a python library for simulating the performance of
    wind turbines and farms. For more information about the model check the
    documentation of the windpowerlib [2]_.

    Notes
    ------
    In order to use this model various power plant and model parameters have to
    be provided. See :attr:`~.power_plant_requires` as well as
    :attr:`~.requires` for further information. Furthermore, the weather
    data used to calculate the feed-in has to have a certain format. See
    :meth:`~.feedin` for further information.

    See Also
    --------
    :class:`~.models.Base`
    :class:`~.models.WindpowerModelBase`

    References
    ----------
    .. [1] `windpowerlib on github <https://github.com/wind-python/windpowerlib>`_
    .. [2] `windpowerlib documentation <https://windpowerlib.readthedocs.io>`_

    """  # noqa: E501

    def __init__(self, **kwargs):
        """ """
        super().__init__(**kwargs)
        self.power_plant = None

    def __repr__(self):
        return "WindpowerlibTurbineCluster"

    @property
    def power_plant_requires(self):
        r"""
        The power plant parameters this model requires to calculate a feed-in.

        The required power plant parameters are:

        `wind_turbine_fleet/wind_farms`

        The windpowerlib differentiates between wind farms as a group of wind
        turbines (of the same or different type) in the same location and
        wind turbine clusters as wind farms and turbines that are assigned the
        same weather data point to obtain weather data for feed-in calculations
        and can therefore be clustered to speed up calculations.
        The `WindpowerlibTurbineCluster` class can be used for both
        :windpowerlib:`windpowerlib.WindFarm <windpowerlib.wind_farm.\
        WindFarm>` and :windpowerlib:`windpowerlib.WindTurbineCluster \
        <windpowerlib.wind_turbine_cluster.WindTurbineCluster>` calculations.
        To set up a :windpowerlib:`windpowerlib.WindFarm <windpowerlib.\
        wind_farm.WindFarm>` please provide a `wind_turbine_fleet`
        and to set up a :windpowerlib:`windpowerlib.WindTurbineCluster \
        <windpowerlib.wind_turbine_cluster.WindTurbineCluster>` please
        provide a list of `wind_farms`. See below for further information.

        wind_turbine_fleet (:pandas:`pandas.DataFrame<frame>`)
            The wind turbine fleet specifies the turbine types and their
            corresponding number or total installed capacity in the wind farm.
            DataFrame must have columns 'wind_turbine' and either
            'number_of_turbines' (number of wind turbines of the same turbine
            type in the wind farm, can be a float) or 'total_capacity'
            (installed capacity of wind turbines of the same turbine type in
            the wind farm in Watt).

            The wind turbine in column 'wind_turbine' can be provided as a
            :class:`~.powerplants.WindPowerPlant` object, a dictionary with
            power plant parameters (see
            :attr:`~.models.WindpowerlibTurbine.power_plant_requires`
            for required parameters) or a :windpowerlib:`windpowerlib.\
            WindTurbine <windpowerlib.wind_turbine.WindTurbine>`.

            See also `wind_turbine_fleet` parameter of
            :windpowerlib:`windpowerlib.WindFarm <windpowerlib.wind_farm.\
            WindFarm>`.

            The wind turbine fleet may also be provided as a list of
            :windpowerlib:`windpowerlib.WindTurbineGroup <windpowerlib.\
            wind_turbine.WindTurbineGroup>` as described there.
        wind_farms (list(dict) or list(:windpowerlib:`windpowerlib.WindFarm <windpowerlib.wind_farm.WindFarm>`))
            List of wind farms in cluster. Wind farms in the list can either
            be provided as :windpowerlib:`windpowerlib.WindFarm \
            <windpowerlib.wind_farm.WindFarm>` or as dictionaries
            where the keys of the dictionary are the wind farm parameter names
            and the values of the dictionary hold the corresponding value.
            The dictionary must at least contain a wind turbine fleet (see
            'wind_turbine_fleet' parameter specifications above) and may
            further contain optional wind farm parameters (see
            :windpowerlib:`windpowerlib.WindFarm <windpowerlib.wind_farm.\
            WindFarm>`).

        """  # noqa: E501
        required = ["wind_turbine_fleet", "wind_farms"]
        if super().power_plant_requires is not None:
            required.extend(super().power_plant_requires)
        return required

    @property
    def requires(self):
        r"""
        The parameters this model requires to calculate a feed-in.

        This model does not require any additional model parameters.

        """
        required = []
        if super().requires is not None:
            required.extend(super().requires)
        return required

    @property
    def nominal_power_wind_power_plant(self):
        """
        Nominal power of wind turbine cluster in Watt.

        The nominal power is the sum of the nominal power of all turbines.
        See `nominal_power` of :windpowerlib:`windpowerlib.WindFarm \
        <windpowerlib.wind_farm.WindFarm>` or
        :windpowerlib:`windpowerlib.WindTurbineCluster \
        <windpowerlib.wind_turbine_cluster.WindTurbineCluster>` for further
        information.

        """
        if self.power_plant:
            return self.power_plant.nominal_power
        else:
            return None

    def _power_plant_requires_check(self, parameters):
        r"""
        Function to check if all required power plant parameters are provided.

        Power plant parameters this model requires are specified in
        :attr:`~.power_plant_requires`.

        Parameters
        -----------
        parameters : list(str)
            List of provided power plant parameters.

        """
        if not any([_ in parameters for _ in self.power_plant_requires]):
            raise KeyError(
                "The specified model '{model}' requires one of the following "
                "power plant parameters: {parameters}".format(
                    model=self, parameters=self.power_plant_requires
                )
            )

    def instantiate_turbine(self, **kwargs):
        """
        Instantiates a :windpowerlib:`windpowerlib.WindTurbine \
        <windpowerlib.wind_turbine.WindTurbine>` object.

        Parameters
        -----------
        **kwargs
            Dictionary with wind turbine specifications. Keys of the dictionary
            are the power plant parameter names, values of the dictionary hold
            the corresponding value. The dictionary must at least contain the
            required turbine parameters (see
            :attr:`~.models.WindpowerlibTurbine.power_plant_requires`) and
            may further contain optional power plant parameters (see
            :windpowerlib:`windpowerlib.WindTurbine \
            <windpowerlib.wind_turbine.WindTurbine>`).

        Returns
        --------
        :windpowerlib:`windpowerlib.WindTurbine \
        <windpowerlib.wind_turbine.WindTurbine>`
            Wind turbine in wind farm or turbine cluster.

        """
        power_plant = WindpowerlibWindTurbine(**kwargs)
        return power_plant

    def instantiate_windfarm(self, **kwargs):
        r"""
        Instantiates a :windpowerlib:`windpowerlib.WindFarm <windpowerlib.\
        wind_farm.WindFarm>` object.

        Parameters
        ----------
        **kwargs
            Dictionary with wind farm specifications. Keys of the dictionary
            are the parameter names, values of the dictionary hold the
            corresponding value. The dictionary must at least contain a wind
            turbine fleet (see 'wind_turbine_fleet' specifications in
            :attr:`~.power_plant_requires`) and may further contain optional
            wind farm parameters (see :windpowerlib:`windpowerlib.WindFarm \
            <windpowerlib.wind_farm.WindFarm>`).

        Returns
        --------
        :windpowerlib:`windpowerlib.WindFarm <windpowerlib.wind_farm.WindFarm>`

        """
        # deepcopy turbine fleet to not alter original turbine fleet
        wind_turbine_fleet = deepcopy(kwargs.pop("wind_turbine_fleet"))

        # if turbine fleet is provided as list, it is assumed that list
        # contains WindTurbineGroups and WindFarm can be directly instantiated
        if isinstance(wind_turbine_fleet, list):
            return WindpowerlibWindFarm(wind_turbine_fleet, **kwargs)

        # if turbine fleet is provided as DataFrame wind turbines in
        # 'wind_turbine' column have to be converted to windpowerlib
        # WindTurbine object
        elif isinstance(wind_turbine_fleet, pd.DataFrame):
            for ix, row in wind_turbine_fleet.iterrows():
                turbine = row["wind_turbine"]
                if not isinstance(turbine, WindpowerlibWindTurbine):
                    # if isinstance(
                    #     turbine, WindPowerPlant
                    # ):
                    #     turbine_data = turbine.parameters
                    if isinstance(turbine, dict):
                        turbine_data = turbine
                    else:
                        raise TypeError(
                            "The WindpowerlibTurbineCluster model requires "
                            "that wind turbines must either be provided as "
                            "WindPowerPlant objects, windpowerlib.WindTurbine "
                            "objects or as dictionary containing all turbine "
                            "parameters required by the WindpowerlibTurbine "
                            "model but type of `wind_turbine` "
                            "is {}.".format(type(row["wind_turbine"]))
                        )
                    # initialize WindpowerlibTurbine instead of directly
                    # initializing windpowerlib.WindTurbine to check required
                    # power plant parameters
                    wind_turbine = WindpowerlibTurbine()
                    wind_turbine._power_plant_requires_check(
                        turbine_data.keys()
                    )
                    wind_turbine_fleet.loc[
                        ix, "wind_turbine"
                    ] = wind_turbine.instantiate_turbine(**turbine_data)
            kwargs["wind_turbine_fleet"] = wind_turbine_fleet
            return WindpowerlibWindFarm(**kwargs)
        else:
            raise TypeError(
                "The WindpowerlibTurbineCluster model requires that the "
                "`wind_turbine_fleet` parameter is provided as a list or "
                "pandas.DataFrame but type of `wind_turbine_fleet` is "
                "{}.".format(type(wind_turbine_fleet))
            )

    def instantiate_turbine_cluster(self, **kwargs):
        r"""
        Instantiates a :windpowerlib:`windpowerlib.WindTurbineCluster \
        <windpowerlib.wind_turbine_cluster.WindTurbineCluster>` object.

        Parameters
        ----------
        **kwargs
            Dictionary with turbine cluster specifications. Keys of the
            dictionary are the parameter names, values of the dictionary hold
            the corresponding value. The dictionary must at least contain a
            list of wind farms (see 'wind_farms' specifications in
            :attr:`~.power_plant_requires`) and may further contain optional
            wind turbine cluster parameters (see
            :windpowerlib:`windpowerlib.WindTurbineCluster \
            <windpowerlib.wind_turbine_cluster.WindTurbineCluster>`).

        Returns
        --------
        :windpowerlib:`windpowerlib.WindTurbineCluster <windpowerlib.wind_turbine_cluster.WindTurbineCluster>`

        """  # noqa: E501
        wind_farm_list = []
        for wind_farm in kwargs.pop("wind_farms"):
            if not isinstance(wind_farm, WindpowerlibWindFarm):
                wind_farm_list.append(self.instantiate_windfarm(**wind_farm))
            else:
                wind_farm_list.append(wind_farm)
        kwargs["wind_farms"] = wind_farm_list
        return WindpowerlibWindTurbineCluster(**kwargs)

    def feedin(self, weather, power_plant_parameters, **kwargs):
        r"""
        Calculates power plant feed-in in Watt.

        This function uses the windpowerlib's
        :windpowerlib:`TurbineClusterModelChain <windpowerlib.\
        turbine_cluster_modelchain.TurbineClusterModelChain>` to calculate the
        feed-in for the given weather time series and wind farm or cluster.

        Parameters
        ----------
        weather : :pandas:`pandas.DataFrame<dataframe>`
            Weather time series used to calculate feed-in. See `weather_df`
            parameter in windpowerlib's TurbineClusterModelChain
            :windpowerlib:`run_model <windpowerlib.turbine_cluster_modelchain.\
            TurbineClusterModelChain.run_model>` method for more information on
            required variables, units, etc.
        power_plant_parameters : dict
            Dictionary with either wind farm or wind turbine cluster
            specifications. For more information on wind farm parameters see
            `kwargs` in :meth:`~.instantiate_windfarm`.
            For information on turbine cluster parameters see `kwargs`
            in :meth:`~.instantiate_turbine_cluster`.
        **kwargs :
            Keyword arguments can be used to overwrite the windpowerlib's
            :windpowerlib:`TurbineClusterModelChain <windpowerlib.\
            turbine_cluster_modelchain.TurbineClusterModelChain>` parameters.

        Returns
        -------
        :pandas:`pandas.Series<series>`
            Power plant feed-in time series in Watt.

        """  # noqa: E501
        # wind farm calculation
        if "wind_turbine_fleet" in power_plant_parameters.keys():
            self.power_plant = self.instantiate_windfarm(
                **power_plant_parameters
            )
        # wind cluster calculation
        else:
            self.power_plant = self.instantiate_turbine_cluster(
                **power_plant_parameters
            )
        mc = WindpowerlibClusterModelChain(self.power_plant, **kwargs)
        return mc.run_model(weather).power_output
