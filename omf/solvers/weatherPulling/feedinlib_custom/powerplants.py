# -*- coding: utf-8 -*-

"""
Power plant classes for specific weather dependent renewable energy resources.

SPDX-FileCopyrightText: Birgit Schachler
SPDX-FileCopyrightText: Uwe Krien <krien@uni-bremen.de>
SPDX-FileCopyrightText: Stephan Günther
SPDX-FileCopyrightText: Lucas Schmeling
SPDX-FileCopyrightText: Keno Oltmanns
SPDX-FileCopyrightText: Patrik Schönfeldt <patrik.schoenfeldt@dlr.de>

SPDX-License-Identifier: MIT

Power plant classes act as data holders for the attributes making up a
power plant's specification. These classes should only contain little logic.
Computing the actual feed-in provided by a power plant is done by the models
(see models.py). The model the feed-in is calculated with is specified in
the `model` attribute.
"""

from abc import ABC
from abc import abstractmethod

from .models.windpowerlib import WindpowerlibTurbine


class Base(ABC):
    """
    The base class of feedinlib power plants.

    The class mainly serves as a data container for power plant attributes.
    Actual calculation of feed-in provided by the power plant is done by the
    chosen model. See model.py module for implemented models.

    This base class is an abstract class serving as a blueprint for classes
    that implement weather dependent renewable energy power plants. It
    forces implementors to implement certain properties and methods.

    Parameters
    ----------
    model : :class:`~feedinlib.models.Base` subclass or instance
        The `model` parameter defines the feed-in model used to calculate
        the power plant feed-in.

        If a class (or in general, any instance of :class:`type`) is
        provided, it is used to create the model instance encapsulating the
        actual mathematical model used to calculate the feed-in provided by
        this power plant.

        In any other case, the provided object is used directly. Note
        though, that a reference to this power plant is saved in the
        provided object, so sharing model instances between two power plant
        objects is not a good idea, as the second power plant will
        overwrite the reference to the first.

        The non-class version is only provided for users who need the extra
        flexibility of controlling model instantiation and who know what
        they are doing. In general, you'll want to provide a class for this
        parameter or just go with the default for the specific subclass you
        are using.

    **attributes :
        Besides `model` parameter provided attributes hold the technical
        specification used to define the power plant. See
        `power_plant_parameters` parameter in respective model's
        :meth:`feedin` method for further information on the model's
        required and optional plant parameters.

    Raises
    ------
    AttributeError
        In case an attribute listed in the given model's required
        parameters is not present in the `parameters` parameter.

    """

    def __init__(self, **attributes):
        """
        """
        model = attributes.pop("model")
        if isinstance(model, type):
            model = model(**attributes)
        self.model = model

        self.parameters = attributes

        # check if all power plant attributes required by the respective model
        # are provided
        self._check_models_power_plant_requirements(attributes.keys())

    @abstractmethod
    def feedin(self, weather, **kwargs):
        """
        Calculates power plant feed-in in Watt.

        This method delegates the actual computation to the model's
        :meth:`feedin` method while giving you the opportunity to override
        some of the inputs used to calculate the feed-in.

        If the respective model does calculate AC and DC feed-in, AC feed-in
        is returned by default. See the model's :meth:`feedin` method for
        information on how to overwrite this default behaviour.

        Parameters
        ----------
        weather :
            Weather data to calculate feed-in. Check the `weather` parameter
            of the respective model's :meth:`feedin` method for required
            weather data parameters and format.
        **kwargs :
            Keyword arguments for respective model's feed-in calculation.
            Check the keyword arguments of the model's :meth:`feedin` for
            further information.

        Returns
        -------
        feedin : :pandas:`pandas.Series<series>`
            Series with power plant feed-in in Watt.

        """
        model = kwargs.pop("model", self.model)

        # in case a different model used to calculate feed-in than originally
        # assigned is given, self.model is overwritten and required power plant
        # parameters for new model are checked
        if not model == self.model:
            model = model(**self.parameters)
            self.model = model
            self._check_models_power_plant_requirements(self.parameters.keys())

        # check if all arguments required by the feed-in model are given
        keys = kwargs.keys()
        for k in model.requires:
            if k not in keys:
                raise AttributeError(
                    "The specified model '{model}' requires model "
                    "parameter '{k}' but it's not provided as an "
                    "argument.".format(k=k, model=model)
                )
        # call respective model's feed-in method
        return model.feedin(
            weather=weather, power_plant_parameters=self.parameters, **kwargs
        )

    def _check_models_power_plant_requirements(self, parameters):
        """
        Checks if given model's required power plant parameters are provided.

        An error is raised if the attributes required by the given model are
        not contained in the provided parameters in `parameters`.

        Parameters
        -----------
        parameters : list(str)
            List of provided power plant parameters.

        Raises
        ------
        AttributeError
            In case an attribute listed in the given model's required
            parameters is not present in the `parameters` parameter.

        """
        try:
            # call the given model's check function if implemented
            self.model._power_plant_requires_check(parameters)
        except NotImplementedError:
            for k in self.required:
                if k not in parameters:
                    raise AttributeError(
                        "The specified model '{model}' requires power plant "
                        "parameter '{k}' but it's not provided as an "
                        "argument.".format(k=k, model=self.model)
                    )

    @property
    def required(self):
        """
        The power plant parameters the specified model requires.

        Check the model's :attr:`power_plant_requires` attribute for further
        information.

        """
        return self.model.power_plant_requires


class WindPowerPlant(Base):
    """
    Class to define a standard set of wind power plant attributes.

    The WindPowerPlant class serves as a data container for wind power plant
    attributes. Actual calculation of feed-in provided by the wind power plant
    is done by the chosen wind power model. So far there are two wind power
    models, :class:`~.models.WindpowerlibTurbine` and
    :class:`~.models.WindpowerlibTurbineCluster`. The
    :class:`~.models.WindpowerlibTurbine` model should be used for
    single wind turbines, whereas the
    :class:`~.models.WindpowerlibTurbineCluster` model can be used
    for wind farm and wind turbine cluster calculations.

    Parameters
    ----------
    model :  A subclass or instance of subclass of \
        :class:`feedinlib.models.WindpowerModelBase`
        The `model` parameter defines the feed-in model used to calculate
        the wind power plant feed-in. It defaults to
        :class:`~.models.WindpowerlibTurbine`.

        `model` is used as the `model` parameter for :class:`Base`.
    **attributes :
        Wind power plant parameters. See `power_plant_parameters` parameter
        in respective model's :meth:`feedin` method for further
        information on the model's required and optional plant parameters.

    """

    def __init__(self, model=WindpowerlibTurbine, **attributes):
        """
        """
        super().__init__(model=model, **attributes)

    def feedin(self, weather, scaling=None, **kwargs):
        """
        Calculates wind power plant feed-in in Watt.

        The feed-in can further be scaled by the nominal power of
        the wind power plant using the `scaling` parameter.

        This method delegates the actual computation to the model's
        meth:`feedin` method while giving you the opportunity to override
        some of the inputs used to calculate the feed-in. See model's
        :meth:`feedin` method for further information on feed-in
        calculation.

        Parameters
        ----------
        weather :
            Weather data to calculate feed-in. Check the `weather` parameter
            of the respective model's :meth:`feedin` method for required
            weather data parameters and format.
        scaling : str
            Specifies what feed-in is scaled by. Possible option is
            'nominal_power'. Defaults to None in which case feed-in is
            not scaled.
        **kwargs
            Keyword arguments for respective model's feed-in calculation.
            Check the keyword arguments of the model's :meth:`feedin` method
            for further information.

        Returns
        -------
        :pandas:`pandas.Series<series>`
            Series with wind power plant feed-in in Watt.

        """
        # delegate feed-in calculation
        feedin = super().feedin(weather, **kwargs)
        # scale feed-in
        if scaling:
            feedin_scaling = {
                "nominal_power": lambda feedin: feedin
                / float(self.nominal_power)
            }
            return feedin_scaling[scaling](feedin)
        return feedin

    @property
    def nominal_power(self):
        """
        Nominal power of wind power plant in Watt.

        See :attr:`nominal_power` attribute of your chosen model for further
        information on how the nominal power is derived.

        """
        return self.model.nominal_power_wind_power_plant
