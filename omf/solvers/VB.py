"""
Implement PNNL virtual-battery device and aggregation models used for demand-response
dispatch studies.
"""

import pandas as pd
import pulp
import numpy as np
from numpy import *
import math

class VirtualBattery(object):
    """ Base class for abstraction. """
    def __init__(self, ambient_temp, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number):
        # C :thermal capacitance
        # R : thermal resistance
        # P: rated power (kW) of each TCL
        # eta: COP
        # delta: temperature deadband
        # theta_s: temperature setpoint
        # N: number of TCL
        # ambient: ambient temperature
        """
        Internal helper for vb init processing.
        """
        self.ambient = ambient_temp
        self.C = capacitance
        self.R = resistance
        self.P = rated_power
        self.eta = COP
        self.delta = deadband
        self.theta_s = setpoint
        self.N = tcl_number

    def generate(self, participation_number, P0_number):

        """ Main calculation happens here. """
        #heuristic function of participation
        atan = np.arctan
        participation = participation_number
        P0 = P0_number

        P0[P0 < 0] = 0.0 # set negative power consumption to 0
        p_lower = self.N*participation*P0 # aggregated baseline power consumption considering participation

        p_upper = self.N*participation*(self.P - P0)
        p_upper[p_upper < 0] = 0.0 # set negative power upper bound to 0
        e_ul = self.N*participation*self.C*self.delta/2/self.eta
        return p_lower, p_upper, e_ul

class AC(VirtualBattery):
    """ Derived Class for specifically AC Virtual Battery. """
    def __init__(self, theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number):
        """
        Internal helper for vb init processing.
        """
        super(AC, self).__init__(theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number)

    # self.tcl_idx = tcl_idx
        self.theta_a = self.ambient  # theta_a == ambient temperature

    def generate(self):
        #heuristic function of participation
        """
        Implement generate behavior for AC instances.
        """
        atan = np.arctan
        # participation for AC
        Ta = np.linspace(20, 45, num=51)
        participation = (atan(self.theta_a-27) - atan(Ta[0]-27))/((atan(Ta[-1]-27) - atan(Ta[0]-27)))

        participation = np.clip(participation, 0, 1)

        #P0 for AC
        P0 = (self.theta_a - self.theta_s)/self.R/self.eta # average baseline power consumption for the given temperature setpoint

        return super(AC, self).generate(participation, P0)

class HP(VirtualBattery):
    """ Derived Class for specifically HP Virtual Battery. """
    def __init__(self, theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number):
        """
        Internal helper for vb init processing.
        """
        super(HP, self).__init__(theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number)

    #  self.tcl_idx = tcl_idx
        self.theta_a = self.ambient  # theta_a == ambient temperature

    def generate(self):
        #heuristic function of participation
        """
        Implement generate behavior for HP instances.
        """
        atan = np.arctan
        # participation for HP
        Ta = np.linspace(0, 25, num=51)
        participation = 1-(atan(self.theta_a-10) - atan(Ta[0]-10))/((atan(Ta[-1]-10) - atan(Ta[0]-10)))

        participation = np.clip(participation, 0, 1)

        #P0 for HP
        P0 = (self.theta_s - self.theta_a)/self.R/self.eta

        return super(HP, self).generate(participation, P0)

class RG(VirtualBattery):
    """ Derived Class for specifically RG Virtual Battery. """
    def __init__(self, theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number):
        """
        Internal helper for vb init processing.
        """
        super(RG, self).__init__(theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number)
    # self.tcl_idx = tcl_idx
        self.theta_a = self.ambient  # theta_a == ambient temperature
    def generate(self):
        #heuristic function of participation
        """
        Implement generate behavior for RG instances.
        """
        atan = np.arctan
        # participation for RG
        participation = np.ones(self.theta_a.shape)

        participation = np.clip(participation, 0, 1)

        #P0 for RG
        P0 = (self.theta_a - self.theta_s)/self.R/self.eta # average baseline power consumption for the given temperature setpoint

        return super(RG, self).generate(participation, P0)

class WH(VirtualBattery):
    """ Derived class for specifically Water Heater Virtual Battery. """
    N_wh = 50

    def __init__(self, theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number,Tout, water, random_numbers=None):
        """
        Internal helper for vb init processing.
        """
        super(WH, self).__init__(theta_a, capacitance, resistance, rated_power, COP, deadband, setpoint, tcl_number)

        self.C_wh = self.C*np.ones((self.N_wh, 1))  # thermal capacitance, set in parent class
        self.R_wh = self.R*np.ones((self.N_wh, 1))  # thermal resistance
        self.P_wh = self.P*np.ones((self.N_wh, 1))   # rated power (kW) of each TCL
        self.delta_wh = self.delta*np.ones((self.N_wh, 1)) # temperature deadband
        self.theta_s_wh = self.theta_s*np.ones((self.N_wh, 1)) # temperature setpoint
        self.Tout=Tout
        self.water = water
        self.random_numbers = random_numbers ## for determining the water draw rate
        # self.N = self.para[6] # number of TCL

    def calculate_twat(self,tout_avg,tout_madif):
        """
        Calculate twat for this analysis.
        """
        tout_avg=tout_avg/5*9+32

        tout_madif=tout_madif/5*9

        ratio = 0.4 + 0.01 * (tout_avg - 44)

        lag = 35 - 1.0 * (tout_avg - 44)

        twat = 1*np.ones((365*24*60,1))

        for i in range(365):
              for j in range(60*24):
                    twat[i*24*60+j]= (tout_avg+6)+ratio*(tout_madif/ 2) * sin((0.986 * (i - 15 - lag) - 90)/180*3.14)

        twat=(twat-32.)/9.*5.

        return twat

    def prepare_pare_for_calculate_twat(self,tou_raw):
    
        """
        Implement prepare pare for calculate twat behavior for WH instances.
        """
        tout_avg = sum(tou_raw)/len(tou_raw)
        
        mon=[31,28,31,30,31,30,31,31,30,31,30,31]
        
        mon_ave=1*np.ones((12,1))

        mon_ave[1]=sum(tou_raw[0:mon[1]*24])/mon[1]/24
        
        stop=mon[1]*24
        
        for idx in range(1,len(mon)):
             mon_ave[idx]=sum(tou_raw[stop:stop+mon[idx]*24])/mon[idx]/24;

        tou_madif=max(mon_ave)- min(mon_ave) 

        return tout_avg, tou_madif
    
    
    def generate(self):
        # theta_a is the ambient temperature
        # theta_a = (72-32)*5.0/9*np.ones((365, 24*60))   # This is a hard-coded 72degF, converted to degCel
        """
        Implement generate behavior for WH instances.
        """
        theta_a = self.ambient#*np.ones((365, 24*60))  # theta_a == ambient temperature
        #nRow, nCol = theta_a.shape
        nRow, nCol = 365, 24*60
        theta_a = np.reshape(theta_a, [nRow*nCol, 1])
                        
        Tout1min= np.zeros((size(theta_a)));
        for i in range(len(self.Tout)):
            theta_a[i]= (self.Tout[i]+self.ambient[i])/2; # CHANGED THIS

        # h is the model time discretization step in seconds
        h = 60
        #T is the number of time step considered, i.e., T = 365*24*60 means a year
        # with 1 minute time discretization
        T = len(theta_a)
        tou_avg,maxdiff=self.prepare_pare_for_calculate_twat(self.Tout)
        twat=self.calculate_twat(tou_avg,maxdiff)
        # print twat
        
        # theta_lower is the temperature lower bound
        theta_lower_wh = self.theta_s_wh - self.delta_wh/2.0
        # theta_upper is the temperature upper bound
        theta_upper_wh = self.theta_s_wh + self.delta_wh/2.0

        # m_water is the water draw in unit of gallon per minute
        m_water = self.water#np.genfromtxt("Flow_raw_1minute_BPA.csv", delimiter=',')[1:, 1:]
        where_are_NaNs = isnan(m_water)
        m_water[where_are_NaNs] = 0	
        m_water = m_water *0.00378541178*1000/h
        m_water_row, m_water_col = m_water.shape    

        ## Calculate the water draw rate using "Flow_raw_1minute_BPA.csv" file and the use of random numbers
        water_draw = np.zeros((m_water_row, int(self.N_wh)))    
        if self.random_numbers is None: ## If no user-provided random numbers .csv file, model-generate them
            ## Create an array of 3 columns for all the random numbers needed for the water draw matrix
            ## NOTE: The three types of random numbers below are remnants from how the previous vbatDispatch code was written
            col_random_number_1 = np.random.randint(m_water_col, size=self.N_wh)
            col_random_number_2 = np.random.randint(-14, 1, size=self.N_wh)
            col_random_number_3 = np.random.random(size=self.N_wh)
            wh_random_numbers = np.column_stack((col_random_number_1, col_random_number_2, col_random_number_3))
        else: ## Use the user-provided random numbers file
            wh_random_numbers = np.array(self.random_numbers)

        ## Generate the water draw matrix using the random numbers that were either generated or user-provided
        random_numbers_1 = wh_random_numbers[:, 0].astype(int)
        random_numbers_2 = wh_random_numbers[:, 1].astype(int)
        random_numbers_3 = wh_random_numbers[:, 2].astype(float)
        for i in range(int(self.N_wh)):
            water_draw[:, i] = (np.roll(m_water[:, random_numbers_1[i]], (1, random_numbers_2[i])) + m_water[:, random_numbers_1[i]] * 0.1 * (random_numbers_3[i] - 0.5))

        first = -(
            np.matmul(theta_a, np.ones((1, self.N_wh)))
            - np.matmul(np.ones((T, 1)), self.theta_s_wh.transpose())
        )
    #    print(np.argwhere(np.isnan(first)))
        second = np.matmul(np.ones((T, 1)), self.R_wh.transpose())
    #    print(np.argwhere(np.isnan(second)))
        Po = (
            first
            / second
            - 4.2
            * np.multiply(water_draw, (55-32) * 5/9.0 - np.matmul(np.ones((T, 1)), self.theta_s_wh.transpose()))
        )
    #    print(water_draw.shape)
    #    print(len(water_draw[:1]))
        # Po_total is the analytically predicted aggregate baseline power
        Po_total = np.sum(Po, axis=1)
        upper_limit = np.sum(self.P_wh, axis=0)

    #    print(np.argwhere(np.isnan(water_draw)))
        Po_total[Po_total > upper_limit[0]] = upper_limit


        # theta is the temperature of TCLs
        theta = np.zeros((self.N_wh, T))
        theta[:, 0] = self.theta_s_wh.reshape(-1)

        # m is the indicator of on-off state: 1 is on, 0 is off
        m = np.ones((self.N_wh, T))
        m[:int(self.N_wh*0.8), 0] = 0

        for t in range(T - 1):
            theta[:, t+1] = (
                (1 - h/(self.C_wh * 3600) / self.R_wh).reshape(-1)
                * theta[:, t]
                + (h / (self.C_wh * 3600) / self.R_wh).reshape(-1)
                * theta_a[t]
                + ((h/(self.C_wh * 3600))*self.P_wh).reshape(-1)*m[:, t]
            )

            m[theta[:, t+1] > (theta_upper_wh).reshape(-1), t+1] = 0
            m[theta[:, t+1] < (theta_lower_wh).reshape(-1), t+1] = 1

            m[(theta[:, t+1] >= (theta_lower_wh).reshape(-1)) & (theta[:, t+1] <= (theta_upper_wh).reshape(-1)), t+1] = m[(theta[:, t+1] >= (theta_lower_wh).reshape(-1)) & (theta[:, t+1] <= (theta_upper_wh).reshape(-1)), t]


        theta[:, 0] = theta[:, -1]
        m[:, 0] = m[:, -1]

        # Po_total_sim is the predicted aggregate baseline power using simulations
        Po_total_sim = np.zeros((T, 1))
        Po_total_sim[0] = np.sum(m[:, 0]*(self.P_wh.reshape(-1)))

        for t in range(T - 1):
            # print t
            theta[:, t+1] = (1 - h/(self.C_wh * 3600)/self.R_wh).reshape(-1) * theta[:, t] + (h/(self.C_wh * 3600)/self.R_wh).reshape(-1)*theta_a[t] + (h/(self.C_wh*3600)).reshape(-1)*m[:, t]*self.P_wh.reshape(-1) + h*4.2*water_draw[t, :].transpose() * (twat[t] -theta[:, t]) / ((self.C_wh*3600).reshape(-1))
            m[theta[:, t+1] > (theta_upper_wh).reshape(-1), t+1] = 0
            m[theta[:, t+1] < (theta_lower_wh).reshape(-1), t+1] = 1
            m[(theta[:, t+1] >= (theta_lower_wh).reshape(-1)) & (theta[:, t+1] <= (theta_upper_wh).reshape(-1)), t+1] = m[(theta[:, t+1] >= (theta_lower_wh).reshape(-1)) & (theta[:, t+1] <= (theta_upper_wh).reshape(-1)), t]
            Po_total_sim[t+1] = np.sum(m[:, t+1] * self.P_wh.reshape(-1))

        index_available = np.ones((self.N_wh, T))

        for t in range(T - 1):
            index_available[(theta[:, t] < (theta_lower_wh-0.5).reshape(-1)) | (theta[:, t] > (theta_upper_wh+0.5).reshape(-1)), t] = 0

        # Virtual battery parameters
        p_upper_wh1 = np.sum(self.P_wh) - Po_total_sim
        p_lower_wh1 = Po_total_sim
        e_ul_wh1 = np.sum((np.matmul(self.C_wh, np.ones((1, T))) * np.matmul(self.delta_wh, np.ones((1, T))) / 2 * index_available).transpose(), axis=1)

        # calculate hourly average data from minute output for power
        p_upper_wh1 = np.reshape(p_upper_wh1, [8760,60])			
        p_upper_wh = np.mean(p_upper_wh1, axis=1)*float(self.N)/float(self.N_wh)       
        p_lower_wh1 = np.reshape(p_lower_wh1, [8760,60])
        p_lower_wh = np.mean(p_lower_wh1, axis=1)*float(self.N)/float(self.N_wh)
        # extract hourly data from minute output for energy
        e_ul_wh = e_ul_wh1[59:len(e_ul_wh1):60]*float(self.N)/float(self.N_wh)
        return p_lower_wh, p_upper_wh, e_ul_wh, wh_random_numbers

# ------------------------STACKED CODE FROM PNNL----------------------------- #

def run_fhec(ind, gt_demand, Input):
    
    """
    Run the fhec workflow and return its results.
    """
    use_hour = int(ind["userHourLimit"]) # number of VB use hours specified by the user
    epsilon  = 1 #float(ind["energyReserve"]) # energy reserve parameter, range: 0 - 1

    fhec_kwh_rate = float(ind["electricityCost"]) # $/kW
    fhec_peak_mult = float(ind["peakMultiplier"])

    s = sorted(gt_demand)

    # peak hours calculation
    perc = float(ind["peakPercentile"])
    fhec_gt98 = s[int(perc*len(s))]

    fhec_peak_hours = []
    for idx, val in enumerate(gt_demand):
        if  val > fhec_gt98:
            fhec_peak_hours.extend([idx+1])
            
    fhec_off_peak_hours = []
    for i in range(len(gt_demand)):
        if  i not in fhec_peak_hours:
            fhec_off_peak_hours.extend([i+1])

    # read the input data, including load profile, VB profile, and regulation price
    # Input = pd.read_csv(input_csv, index_col=['Hour'])

    # VB model parameters
    C = float(ind["capacitance"]) # thermal capacitance
    R = float(ind["resistance"]) # thermal resistance
    deltaT = 1
    alpha = math.exp(-deltaT/(C*R)) # hourly self discharge rate

    E_0 = 0 # VB initial energy state

    arbitrage_option = ind["use_arbitrage"] == "on"
    regulation_option = ind["use_regulation"] == "on"
    deferral_option = ind["use_deferral"] == "on"
    
    # calculate the predicted profits for all 8760 hours
    use_prft = []
    for hour in Input.index:
        temp = 0
        if arbitrage_option or deferral_option:
            if hour in fhec_peak_hours:
                temp += fhec_peak_mult*fhec_kwh_rate*(Input.loc[hour, "VB Energy upper (kWh)"]-Input.loc[hour, "VB Energy lower (kWh)"])
            if hour in fhec_off_peak_hours:
                temp += fhec_kwh_rate*(Input.loc[hour, "VB Energy upper (kWh)"]-Input.loc[hour, "VB Energy lower (kWh)"])
        if regulation_option:
            temp += (Input.loc[hour, "Reg-up Price ($/MW)"]+Input.loc[hour, "Reg-dn Price ($/MW)"])/1000*(Input.loc[hour, "VB Energy upper (kWh)"]-Input.loc[hour, "VB Energy lower (kWh)"])
        use_prft.append({'Hour': hour, 'Profit': temp})
    
    # sort the predicted profits from the highest to the lowest
    use_prft = sorted(use_prft, reverse = True, key = lambda i : i['Profit'])
    
    # get the indices of the first use_hour hours, and the optimization will be scheduled only for those hours
    use_list = []
    for index in range(use_hour):
        use_list.append(use_prft[index]['Hour'])
    
    ###############################################################################

    # start demand charge reduction LP problem
    model = pulp.LpProblem("Demand charge minimization problem FHEC-Knievel", pulp.LpMinimize)

    # decision variable of VB charging power; dim: 8760 by 1
    VBpower = pulp.LpVariable.dicts("ChargingPower", ((hour) for hour in Input.index))
    # set bound
    for hour in Input.index:
        if hour in use_list:
            VBpower[hour].lowBound = Input.loc[hour, "VB Power lower (kW)"]
            VBpower[hour].upBound  = Input.loc[hour, "VB Power upper (kW)"]
        if hour not in use_list:
            VBpower[hour].lowBound = 0
            VBpower[hour].upBound  = 0
    
    # decision variable of VB energy state; dim: 8760 by 1
    VBenergy = pulp.LpVariable.dicts("EnergyState", ((hour) for hour in Input.index))
    # set bound
    for hour in Input.index:
        VBenergy[hour].lowBound = Input.loc[hour, "VB Energy lower (kWh)"]
        VBenergy[hour].upBound  = Input.loc[hour, "VB Energy upper (kWh)"]
    
    # decision variable of annual peak demand
    PeakDemand = pulp.LpVariable("annual peak demand", lowBound=0)
    
    # decision variable: hourly regulation up capacity; dim: 8760 by 1
    reg_up = pulp.LpVariable.dicts("hour reg up", ((hour) for hour in Input.index), lowBound=0)
    # decision variable: hourly regulation dn capacity; dim: 8760 by 1
    reg_dn = pulp.LpVariable.dicts("hour reg dn", ((hour) for hour in Input.index), lowBound=0)
    for hour in Input.index:
        if hour not in use_list:
            reg_up[hour].upBound = 0
            reg_dn[hour].upBound = 0

    # objective functions
    if (arbitrage_option == False and regulation_option == False and deferral_option == False):
        model += 0, "an arbitrary objective function"

    if (arbitrage_option == True and regulation_option == False and deferral_option == False):
        model += pulp.lpSum([fhec_peak_mult*fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_peak_hours]
                            + [fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_off_peak_hours])

    if (arbitrage_option == False and regulation_option == True and deferral_option == False):
        model += pulp.lpSum([-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index])

    if (arbitrage_option == False and regulation_option == False and deferral_option == True):
        model += pulp.lpSum(1E03*PeakDemand)

    if (arbitrage_option == True and regulation_option == True and deferral_option == False):
        model += pulp.lpSum([fhec_peak_mult*fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_peak_hours]
                            + [fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_off_peak_hours]
                            + [-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index])

    if (arbitrage_option == True and regulation_option == False and deferral_option == True):
        model += pulp.lpSum([fhec_peak_mult*fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_peak_hours]
                            + [fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_off_peak_hours]
                            + 1E03*PeakDemand)

    if (arbitrage_option == False and regulation_option == True and deferral_option == True):
        model += pulp.lpSum([-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index]
                            + 1E03*PeakDemand)
        
    if (arbitrage_option == True and regulation_option == True and deferral_option == True):
        model += pulp.lpSum([fhec_peak_mult*fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_peak_hours]
                            + [fhec_kwh_rate*(Input.loc[hour, "Load (kW)"]+VBpower[hour]) for hour in fhec_off_peak_hours]
                            + [-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index]
                            + 1E03*PeakDemand)
    
    # VB energy state as a function of VB power
    for hour in Input.index:
        if hour==1:
            model += VBenergy[hour] == alpha*E_0 + VBpower[hour]*deltaT
        else:
            model += VBenergy[hour] == alpha*VBenergy[hour-1] + VBpower[hour]*deltaT
    
    # hourly regulation constraints
    for hour in Input.index:
        if regulation_option:
            model += reg_up[hour] == reg_dn[hour] # regulation balance
            model += VBenergy[hour] - epsilon*reg_up[hour]*deltaT >= VBenergy[hour].lowBound
            model += VBenergy[hour] + epsilon*reg_dn[hour]*deltaT <= VBenergy[hour].upBound
        else:
            model += reg_up[hour] == 0
            model += reg_dn[hour] == 0
    
    # extra constraints
    for hour in Input.index:
        model += PeakDemand >= Input.loc[hour, "Load (kW)"] + VBpower[hour]
    
    model.solve()

    ###############################################################################
    
    use_hour_indicator = []
    for hour in Input.index:
        if VBpower[hour].varValue != 0 or reg_up[hour].varValue != 0:
            use_hour_indicator.append({'Hour': hour, 'Use': 1})
        else:
            use_hour_indicator.append({'Hour': hour, 'Use': 0})
    
    output = []
    for hour in Input.index:
        var_output = {
            'Hour': hour,
            'VB energy (kWh)': int(100*VBenergy[hour].varValue)/100,
            'VB power (kW)': int(100*VBpower[hour].varValue)/100,
            'Load (kW)': int(100*Input.loc[hour, "Load (kW)"])/100,
            'Net load (kW)': int(100*(VBpower[hour].varValue+Input.loc[hour, "Load (kW)"]))/100,
            'Hour used': use_hour_indicator[hour-1]['Use']
        }
        if regulation_option:
            var_regulation = {'Regulation (kW)': int(100*reg_up[hour].varValue)/100}
            var_output.update(var_regulation)
        output.append(var_output)
    
    output_df = pd.DataFrame.from_records(output)
    
    # output_df.to_csv('fhec_output.csv', index=False)
    
    return output_df

def run_okec(ind, Input):

    # Input.to_csv('okec_input.csv', index=False)
    
    """
    Run the okec workflow and return its results.
    """
    use_hour = int(ind["userHourLimit"]) # number of VB use hours specified by the user
    epsilon  = 1 #float(ind["energyReserve"]) # energy reserve parameter, range: 0 - 1

    okec_peak_charge = float(ind["annual_peak_charge"]) # annual peak demand charge $100/kW
    okec_avg_demand_charge = float(ind["avg_demand_charge"]) # $120/kW
    okec_fuel_charge = float(ind["fuel_charge"]) # total energy $/kWh

    # VB model parameters
    C = float(ind["capacitance"]) # thermal capacitance
    R = float(ind["resistance"]) # thermal resistance
    deltaT = 1
    alpha = math.exp(-deltaT/(C*R)) # hourly self discharge rate

    E_0 = 0 # VB initial energy state

    arbitrage_option = ind["use_arbitrage"] == "on"
    regulation_option = ind["use_regulation"] == "on"
    deferral_option = ind["use_deferral"] == "on"
    
    # calculate the predicted profits for all 8760 hours
    use_prft = []
    for hour in Input.index:
        temp = 0
        if arbitrage_option or deferral_option:
            temp += okec_avg_demand_charge/len(Input.index)*(Input.loc[hour, "VB Energy upper (kWh)"]-Input.loc[hour, "VB Energy lower (kWh)"])
        if regulation_option:
            temp += (Input.loc[hour, "Reg-up Price ($/MW)"]+Input.loc[hour, "Reg-dn Price ($/MW)"])/1000*(Input.loc[hour, "VB Energy upper (kWh)"]-Input.loc[hour, "VB Energy lower (kWh)"])
        use_prft.append({'Hour': hour, 'Profit': temp})
    
    # sort the predicted profits from the highest to the lowest
    use_prft = sorted(use_prft, reverse = True, key = lambda i : i['Profit'])
    
    # get the indices of the first use_hour hours, and the optimization will be scheduled only for those hours
    use_list = []
    for index in range(use_hour):
        use_list.append(use_prft[index]['Hour'])
    # start demand charge reduction LP problem
    model = pulp.LpProblem("Demand charge minimization problem OKEC-Buffett", pulp.LpMinimize)

    # decision variable of VB charging power; dim: 8760 by 1
    VBpower = pulp.LpVariable.dicts("ChargingPower", ((hour) for hour in Input.index))
    # set bound
    for hour in Input.index:
        if hour in use_list:
            VBpower[hour].lowBound = Input.loc[hour, "VB Power lower (kW)"]
            VBpower[hour].upBound  = Input.loc[hour, "VB Power upper (kW)"]
        if hour not in use_list:
            VBpower[hour].lowBound = 0
            VBpower[hour].upBound  = 0
    
    # decision variable of VB energy state; dim: 8760 by 1
    VBenergy = pulp.LpVariable.dicts("EnergyState", ((hour) for hour in Input.index))
    # set bound
    for hour in Input.index:
        VBenergy[hour].lowBound = Input.loc[hour, "VB Energy lower (kWh)"]
        VBenergy[hour].upBound  = Input.loc[hour, "VB Energy upper (kWh)"]
    
    # decision variable of annual peak demand
    PeakDemand = pulp.LpVariable("annual peak demand", lowBound=0)
    
    # decision variable: hourly regulation up capacity; dim: 8760 by 1
    reg_up = pulp.LpVariable.dicts("hour reg up", ((hour) for hour in Input.index), lowBound=0)
    # decision variable: hourly regulation dn capacity; dim: 8760 by 1
    reg_dn = pulp.LpVariable.dicts("hour reg dn", ((hour) for hour in Input.index), lowBound=0)
    for hour in Input.index:
        if hour not in use_list:
            reg_up[hour].upBound = 0
            reg_dn[hour].upBound = 0

    # objective function: sum of monthly demand charge
    if (arbitrage_option == False and regulation_option == False and deferral_option == False):
        model += 0, "an arbitrary objective function"

    if (arbitrage_option == True and regulation_option == False and deferral_option == False):
        model += pulp.lpSum(okec_peak_charge*PeakDemand
                            + [okec_avg_demand_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])/len(Input.index) for hour in Input.index]
                            + [okec_fuel_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])*deltaT for hour in Input.index])

    if (arbitrage_option == False and regulation_option == True and deferral_option == False):
        model += pulp.lpSum([-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index])

    if (arbitrage_option == False and regulation_option == False and deferral_option == True):
        model += pulp.lpSum(1E03*PeakDemand)

    if (arbitrage_option == True and regulation_option == True and deferral_option == False):
        model += pulp.lpSum(okec_peak_charge*PeakDemand
                            + [okec_avg_demand_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])/len(Input.index) for hour in Input.index]
                            + [okec_fuel_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])*deltaT for hour in Input.index]
                            + [-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index])

    if (arbitrage_option == True and regulation_option == False and deferral_option == True):
        model += pulp.lpSum(okec_peak_charge*PeakDemand
                            + [okec_avg_demand_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])/len(Input.index) for hour in Input.index]
                            + [okec_fuel_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])*deltaT for hour in Input.index]
                            + 1E03*PeakDemand)

    if (arbitrage_option == False and regulation_option == True and deferral_option == True):
        model += pulp.lpSum([-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index]
                            + 1E03*PeakDemand)
        
    if (arbitrage_option == True and regulation_option == True and deferral_option == True):
        model += pulp.lpSum(okec_peak_charge*PeakDemand
                            + [okec_avg_demand_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])/len(Input.index) for hour in Input.index]
                            + [okec_fuel_charge*(Input.loc[hour, "Load (kW)"]+VBpower[hour])*deltaT for hour in Input.index]
                            + [-Input.loc[hour, "Reg-up Price ($/MW)"]/1000*reg_up[hour] for hour in Input.index]
                            + [-Input.loc[hour, "Reg-dn Price ($/MW)"]/1000*reg_dn[hour] for hour in Input.index]
                            + 1E03*PeakDemand)
    
    # VB energy state as a function of VB power
    for hour in Input.index:
        if hour==1:
            model += VBenergy[hour] == alpha*E_0 + VBpower[hour]*deltaT
        else:
            model += VBenergy[hour] == alpha*VBenergy[hour-1] + VBpower[hour]*deltaT
    
    # hourly regulation constraints
    for hour in Input.index:
        if regulation_option:
            model += reg_up[hour] == reg_dn[hour] # regulation balance
            model += VBenergy[hour] - epsilon*reg_up[hour]*deltaT >= VBenergy[hour].lowBound
            model += VBenergy[hour] + epsilon*reg_dn[hour]*deltaT <= VBenergy[hour].upBound
        else:
            model += reg_up[hour] == 0
            model += reg_dn[hour] == 0
    
    # extra constraints
    for hour in Input.index:
        model += PeakDemand >= Input.loc[hour, "Load (kW)"] + VBpower[hour]
    
    model.solve()

    ###############################################################################
    
    use_hour_indicator = []
    for hour in Input.index:
        if VBpower[hour].varValue != 0 or reg_up[hour].varValue != 0:
            use_hour_indicator.append({'Hour': hour, 'Use': 1})
        else:
            use_hour_indicator.append({'Hour': hour, 'Use': 0})
    
    output = []
    for hour in Input.index:
        var_output = {
            'Hour': hour,
            'VB energy (kWh)': int(100*VBenergy[hour].varValue)/100,
            'VB power (kW)': int(100*VBpower[hour].varValue)/100,
            'Load (kW)': int(100*Input.loc[hour, "Load (kW)"])/100,
            'Net load (kW)': int(100*(VBpower[hour].varValue+Input.loc[hour, "Load (kW)"]))/100,
            'Hour used': use_hour_indicator[hour-1]['Use']
        }
        if regulation_option:
            var_regulation = {'Regulation (kW)': int(100*reg_up[hour].varValue)/100}
            var_output.update(var_regulation)
        output.append(var_output)
    
    output_df = pd.DataFrame.from_records(output)
    return output_df
