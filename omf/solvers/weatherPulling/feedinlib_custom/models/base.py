# -*- coding: utf-8 -*
"""
Feed-in model classes.

SPDX-FileCopyrightText: Birgit Schachler
SPDX-FileCopyrightText: Uwe Krien <krien@uni-bremen.de>
SPDX-FileCopyrightText: Stephan Günther
SPDX-FileCopyrightText: Stephen Bosch
SPDX-FileCopyrightText: Patrik Schönfeldt <patrik.schoenfeldt@dlr.de>

SPDX-License-Identifier: MIT

This module provides abstract classes as blueprints for classes that implement
feed-in models for weather dependent renewable energy resources. These models
take in power plant and weather data to calculate power plant feed-in.
"""

import warnings
from abc import ABC
from abc import abstractmethod

import pvlib.pvsystem
from windpowerlib import get_turbine_types


class Base(ABC):
    r"""
    The base class of feedinlib models.

    This base class is an abstract class serving as a blueprint for classes
    that implement feed-in models for weather dependent renewable energy
    resources. It forces implementors to implement certain properties and
    methods.

    """

    def __init__(self, **kwargs):
        """
        """
        self._power_plant_requires = kwargs.get("powerplant_requires", None)
        self._requires = kwargs.get("requires", None)

    @property
    @abstractmethod
    def power_plant_requires(self):
        """
        The (names of the) power plant parameters this model requires in
        order to calculate the feed-in.

        As this is an abstract property you have to override it in a subclass
        so that the model can be instantiated. This forces implementors to make
        the required power plant parameters for a model explicit, even if they
        are empty, and gives them a good place to document them.

        By default, this property is settable and its value can be specified
        via an argument upon construction. If you want to keep this
        functionality, simply delegate all calls to the superclass.

        Parameters
        ----------
        names : list(str), optional
            Containing the names of the required power plant parameters.

        """
        return self._power_plant_requires

    @power_plant_requires.setter
    def power_plant_requires(self, names):
        self._power_plant_requires = names

    def _power_plant_requires_check(self, parameters):
        """
        Function to check if all required power plant parameters are provided.

        This function only needs to be implemented in a subclass in case
        required power plant parameters specified in
        :attr:`power_plant_requires` are not a simple list that can be checked
        by :func:`~.power_plants.Base.check_models_power_plant_requirements`.

        """
        raise NotImplementedError

    @property
    @abstractmethod
    def requires(self):
        """
        The (names of the) parameters this model requires in order to
        calculate the feed-in.

        As this is an abstract property you have to override it in a subclass
        so that the model can be instantiated. This forces implementors to make
        the required model parameters explicit, even if they
        are empty, and gives them a good place to document them.

        By default, this property is settable and its value can be specified
        via an argument upon construction. If you want to keep this
        functionality, simply delegate all calls to the superclass.

        Parameters
        ----------
        names : list(str), optional
            Containing the names of the required power plant parameters.

        """
        return self._requires

    @requires.setter
    def requires(self, names):
        self._requires = names

    @abstractmethod
    def feedin(self, weather, power_plant_parameters, **kwargs):
        """
        Calculates power plant feed-in in Watt.

        As this is an abstract method you have to override it in a subclass
        so that the power plant feed-in using the respective model can be
        calculated.

        Parameters
        ----------
        weather :
            Weather data to calculate feed-in. Format and required parameters
            depend on the model.
        power_plant_parameters : dict
            Dictionary with power plant specifications. Keys of the dictionary
            are the power plant parameter names, values of the dictionary hold
            the corresponding value. The dictionary must at least contain the
            power plant parameters required by the respective model and may
            further contain optional power plant parameters. See
            `power_plant_requires` property of the respective model for futher
            information.
        **kwargs :
            Keyword arguments for respective model's feed-in calculation.

        Returns
        -------
        feedin : :pandas:`pandas.Series<series>`
            Series with power plant feed-in for specified time span in Watt.
            If respective model does calculate AC and DC feed-in, AC feed-in
            should be returned by default. `mode` parameter can be used to
            overwrite this default behavior and return DC power output instead
            (for an example see :meth:`~.models.Pvlib.feedin`).

        """
        pass

class WindpowerModelBase(Base):
    """
    Expands model base class :class:`~.models.Base` by wind power specific
    attributes.

    """

    @property
    @abstractmethod
    def nominal_power_wind_power_plant(self):
        """
        Nominal power of wind power plant in Watt.

        As this is an abstract property you have to override it in a subclass
        so that the model can be instantiated. This forces implementors to
        provide a way to retrieve the nominal power of the wind power plant
        that is e.g. used to scale the feed-in by installed capacity.

        """


def get_power_plant_data(dataset, **kwargs):
    r"""
    Function to retrieve power plant data sets provided by feed-in models.

    This function can be used to retrieve power plant data from data sets
    and to get an overview of which modules, inverters and turbine types are
    provided and can be used in feed-in calculations.

    Parameters
    ----------
    dataset : str
        Specifies data set to retrieve. Possible options are:

        * pvlib PV module and inverter datasets: 'sandiamod', 'cecinverter'

          The original data sets are hosted here:
          https://github.com/NREL/SAM/tree/develop/deploy/libraries

          See :pvlib:`retrieve_sam <pvlib.pvsystem.retrieve_sam>` for further
          information.
        * windpowerlib wind turbine dataset: 'oedb_turbine_library'

          See :windpowerlib:`get_turbine_types <windpowerlib.wind_turbine.\
          get_turbine_types>` for further information.

    **kwargs
        See referenced functions for each dataset above for further optional
        parameters.

    Example
    -------
    >>> from feedinlib import get_power_plant_data
    >>> data = get_power_plant_data('sandiamod')
    >>> # list of all provided PV modules
    >>> pv_modules = data.columns
    >>> print(data.loc["Area", data.columns.str.contains('Aleo_S03')])
    Aleo_S03_160__2007__E__    1.28
    Aleo_S03_165__2007__E__    1.28
    Name: Area, dtype: object

    """
    dataset = dataset.lower()
    if dataset in ["sandiamod", "cecinverter"]:
        return pvlib.pvsystem.retrieve_sam(
            name=dataset, path=kwargs.get("path", None)
        )
    elif dataset == "oedb_turbine_library":
        return get_turbine_types(
            turbine_library=kwargs.get("turbine_library", "local"),
            print_out=kwargs.get("print_out", False),
            filter_=kwargs.get("filter_", True),
        )
    else:
        warnings.warn("Unknown dataset {}.".format(dataset))
        return None
