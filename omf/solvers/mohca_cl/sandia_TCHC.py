"""
Run Sandia thermal-constrained hosting-capacity analysis using transformer and customer
measurements.
"""

import numpy as np
import pandas as pd
import itertools
from sklearn import linear_model
from sklearn.metrics import mean_squared_error


def hosting_cap_tchc(
        input_csv_path,
        output_csv_path,
        Final_results,
        der_pf=None,
        vv_x=None,
        vv_y=None,
        overload_constraint=None,
        xf_lookup=None
):
    """
    Calculate hosting capacity based on input csv
    export results to output_csv_path

    Assert OMF format of file at input_csv_path with required columns:
        busname: [any string]
        datetime: [YY-MM-DDTHH:MM]
        v_reading: [any float, must be actual - not PU]
        kw_reading: [any float, avg over measurement interval]
        kvar_reading: [any float, avg over measurement interval]

    Sign Convention of kW and KVAR:
        Positive for Loading (i.e., flowing into the load bus),
        Negative for Injections (i.e., flowing out of the load bus)

    Sign Convention of optional DER power factor input:
        Positive for capacitve, Negative for inductive

    The optional input variable der_pf corresponds to the advanced inverter
        constant power factor setting for the DER.

    The optional input variables vv_x and vv_y correspond to the x and y
        coordinates,respectively, for a user-defined Volt-VAR curve. The vv_x
        values are per unit voltages and the vv_y values are per unit reactive
        power values, where negative values are inductive and positive values
        are capacitive. The lengths of vv_x and vv_y must be equal. If the user
        provides a Volt-VAR curve using these inputs, it will supersede the
        value of der_pf (if also provided).

    overload_constraint is an optional variable that sets the transformer
        thermal constraint for the hosting capacity analysis. The default
        value is 1.2, which means transformers are allowed to be overloaded
        by up to 120% of their kVA rating for reverse power flows.

    xf_lookup is an optional dataframe that provides a look-up table of known
        service transformer kVA ratings and impedances. If no input is
        provided by the user, a generic look-up table will be used.
        Expected Columns are: 'kVA', 'R_ohms_LV', 'X_ohms_LV'

    Note: kVAR mesurements are required to calculate TCHC

    NOTE: Final_results is a dataframe of busname, Transformer Index, X, Y

    """
    # read in the smart meter data
    input_data = pd.read_csv(input_csv_path)
    # convert to category for more performant masking...
    input_data['busname'] = input_data['busname'].astype('category')

    Final_results['Transformer Index'] = Final_results['Transformer Index'].astype('category')
    Final_results['busname'] = Final_results['busname'].astype('category')

    # set the upper bound voltage limit
    vpu_upperbound = 1.05

    # NOTE:  handle optional volt-var curve

    # accomodate optional power factor
    # sign convention: capacitive PF (+), inductive PF (-)
    if der_pf is None:
        der_pf = 1.0

    # accomodate optional Volt-VAR mode
    # sign convention: capacitive VAR (+), inductive VAR (-)
    if vv_x is not None and vv_y is not None:
        # Check for valid length
        if len(vv_x) != len(vv_y):
            print('warning: vv_x and vv_y are different lengths.')
            der_pf = 1.0
        else:
            # find intercept
            qpu = np.interp(vpu_upperbound, vv_x, vv_y)
            if qpu == 0:
                der_pf = 1.0
            else:
                der_pf = np.sign(qpu)*(1-qpu**2)**(1/2)

    # initialize xfmr thermal limit for TCHC as a multiplier of kVA rating
    if overload_constraint is None:
        overload_constraint = 1.2

    # initialize the xfmr lookup table
    if xf_lookup is None:
        xf_lookup = init_xf_lookup()

    # check whether the user provided location info for the smart meter data
    has_location_info = get_has_location_info(Final_results)

    # estimate the P, Q, and V values at the LV terminals of all xfmrs
    df_xfmr_estimated = get_est_xfmr_measurements(input_data, Final_results)

    # initialize dataframe to log xfmr parameters
    df_xfmr_info = pd.DataFrame()
    unique_xfmr_index = Final_results['Transformer Index'].unique()
    df_xfmr_info['Transformer Index'] = unique_xfmr_index

    # find nearby xfmrs for each target xfmr
    min_nearby_xfmrs = 5

    # if there are less than min total xfmrs, then all xfmrs will be
    # considered "nearby" for each target xfmr
    if len(unique_xfmr_index) >= (min_nearby_xfmrs + 1):

        if has_location_info:
            # set xfmr coordinates to average of its customers coordinates
            xfmr_x_coord = np.full((len(df_xfmr_info), 1), np.nan)
            xfmr_y_coord = np.full((len(df_xfmr_info), 1), np.nan)

            for ii in range(len(df_xfmr_info)):
                xfmr_idx = df_xfmr_info['Transformer Index'][ii]
                xfmr_mask = Final_results['Transformer Index'] == xfmr_idx
                df_now = Final_results[xfmr_mask].copy()
                xfmr_x_coord[ii, 0] = np.mean(df_now['X'].values)
                xfmr_y_coord[ii, 0] = np.mean(df_now['Y'].values)

            df_xfmr_info['x_coord'] = xfmr_x_coord
            df_xfmr_info['y_coord'] = xfmr_y_coord

            dist_mat = get_dist_mat(xfmr_x_coord, xfmr_y_coord)

            # create list of nearby xfmrs for each target xfmr
            df_nearby_xfmrs = get_nearby_xfmr_idx_dist(
                df_xfmr_info,
                dist_mat,
                min_nearby_xfmrs,
                )
            df_xfmr_info['nearby_idx'] = df_nearby_xfmrs['nearby_idx'].copy()

        else:
            # use all:
            df_nearby_xfmrs = get_nearby_xfmr_idx_all(df_xfmr_info)
            df_xfmr_info['nearby_idx'] = df_nearby_xfmrs['nearby_idx'].copy()

    else:
        # all xfmrs considered nearby for eachother
        df_nearby_xfmrs = get_nearby_xfmr_idx_all(df_xfmr_info)
        df_xfmr_info['nearby_idx'] = df_nearby_xfmrs['nearby_idx'].copy()

    df_xfmr_sizes = get_xfmr_sizes(
        df_xfmr_info,
        df_xfmr_estimated,
        xf_lookup,
        )
    df_xfmr_info['kVA_estimated'] = df_xfmr_sizes['kVA_estimated'].copy()
    df_xfmr_info['conf_score'] = df_xfmr_sizes['conf_score'].copy()

    tchc_results = get_customer_tchc(
        Final_results,
        df_xfmr_estimated,
        df_xfmr_info,
        overload_constraint,
        has_location_info,
        der_pf)

    # Output CSV File of Results
    tchc_results.to_csv(output_csv_path, index=False)

    return tchc_results


def get_nearby_xfmr_idx_all(df_xfmr_info):
    """
    returns the nearby xfmr indices assuming all xfmrs are nearby each other
    """
    df_nearby_xfmrs = pd.DataFrame(columns=['nearby_idx'])
    xfmr_idx_all = df_xfmr_info['Transformer Index'].values

    for ii in range(len(xfmr_idx_all)):
        idx_now = xfmr_idx_all[ii]
        idx_nearby = xfmr_idx_all[xfmr_idx_all != idx_now]
        df_nearby_xfmrs.at[ii, 'nearby_idx'] = idx_nearby

    return df_nearby_xfmrs


def get_nearby_xfmr_idx_dist(
        df_xfmr_info,
        dist_mat,
        min_nearby_xfmrs,
        ):
    """
    finds the indices of the nearest xfmrs by distance
    """
    min_plus_self = min_nearby_xfmrs + 1
    df_nearby_xfmrs = pd.DataFrame(columns=['nearby_idx'])
    df_xfmr_all = df_xfmr_info['Transformer Index'].copy()
    for ii in range(len(df_xfmr_info)):
        dist_array = dist_mat[:, ii]
        idx_sorted = np.argsort(dist_array)
        idx_nearby = idx_sorted[0:min_plus_self]
        idx_nearby = idx_nearby[idx_nearby != ii]
        xfmr_idx_nearby = df_xfmr_all[idx_nearby]
        xfmr_idx_nearby = xfmr_idx_nearby.values
        df_nearby_xfmrs.at[ii, 'nearby_idx'] = xfmr_idx_nearby

    return df_nearby_xfmrs


def get_dist_mat(xfmr_x_coord, xfmr_y_coord):
    """
    computes the distance matrix between all xfmrs
    """
    x_mat = np.tile(xfmr_x_coord, len(xfmr_x_coord))
    y_mat = np.tile(xfmr_y_coord, len(xfmr_y_coord))

    x_diff_mat = x_mat - np.transpose(x_mat)
    y_diff_mat = y_mat - np.transpose(y_mat)

    dist_mat = np.sqrt(x_diff_mat**2 + y_diff_mat**2)

    return dist_mat


def init_xf_lookup():
    """
    initializes the xfmr lookup table of sizes and impedances
    """
    xf_lookup = pd.DataFrame(columns=['kVA', 'R_ohms_LV', 'X_ohms_LV'])
    xf_lookup['kVA'] = [5, 10, 15, 25, 37.5, 50, 75, 100, 167, 250]
    xf_lookup['R_ohms_LV'] = [
        0.164960640000000,
        0.0757440000000000,
        0.0398380218181818,
        0.0267029760000000,
        0.0154106880000000,
        0.0114212571428571,
        0.00710254080000000,
        0.00578592000000000,
        0.00287493994047833,
        0.00107136000000000,
        ]
    xf_lookup['X_ohms_LV'] = [
        0.167040000000000,
        0.0952704000000000,
        0.0702541963636364,
        0.0406387200000000,
        0.0287245440000000,
        0.0204861805714286,
        0.0154222080000000,
        0.0137078400000000,
        0.00812263473053892,
        0.00691200000000000,
        ]
    return xf_lookup


def get_has_location_info(Final_results):
    """
    check if Final_results (dataframe with customer-transformer groupings) has
    location info provided by the user.
    ASSERT missing coordinates are ZEROS and will only identify completely
    missing sets of coordinates.

    return false if all buses are missing coordinates
    assumes input column is zeros.

    """
    all_missing_x = Final_results['X'].sum() == 0
    all_missing_y = Final_results['Y'].sum() == 0
    has_missing_coords = all_missing_x | all_missing_y

    return ~has_missing_coords


def get_est_xfmr_measurements(input_data, Final_results):
    """
    estimates the measurements at the LV terminals of each service transformer
    using the smart meter data from each downstream customer

    return a dataframe with the estimated values for each transformer

    """
    df_xfmr_estimated = pd.DataFrame()

    # Identify transformer indices
    unique_xfmrs = Final_results['Transformer Index'].unique()

    # loop through each transformer to estimate its aggregated measurements
    # at its LV terminals using the smart meter data from its downstream
    # customers
    for xfmr_idx in unique_xfmrs:
        xfmr_mask = Final_results['Transformer Index'] == xfmr_idx
        df_now = Final_results[xfmr_mask].copy()

        bus_list = df_now['busname'].copy()

        if len(bus_list) == 1:
            # the aggregated measurements for this xfmr will be set equal to
            # that customer's data (only available data for this xfmr)
            bus_mask = input_data['busname'] == bus_list.iloc[0]
            temp_df = input_data[bus_mask].copy()
            array_temp = np.full(temp_df['busname'].shape, xfmr_idx)

            temp_df.rename(
                columns={'busname': 'Transformer Index'},
                inplace=True)
            temp_df['Transformer Index'] = array_temp.copy()

            df_xfmr_estimated = pd.concat(
                [df_xfmr_estimated, temp_df],
                ignore_index=True)

        else:
            # aggregate P and Q measurements
            bus_mask = input_data['busname'] == bus_list.iloc[0]
            temp_df = input_data[bus_mask].copy()
            xfmr_p_kw_all = np.full(
                (len(temp_df['kw_reading']), len(bus_list)),
                np.nan)
            xfmr_q_kvar_all = np.full(
                (len(temp_df['kw_reading']), len(bus_list)),
                np.nan)

            for ii in range(len(bus_list)):
                bus_mask = input_data['busname'] == bus_list.iloc[ii]
                temp_df = input_data[bus_mask].copy()
                xfmr_p_kw_all[:, ii] = temp_df['kw_reading'].copy()
                xfmr_q_kvar_all[:, ii] = temp_df['kvar_reading'].copy()
            xfmr_p_kw_sum = np.sum(xfmr_p_kw_all, axis=1)
            xfmr_q_kvar_sum = np.sum(xfmr_q_kvar_all, axis=1)

            # estimate the xfmr v measurements iteratively using every unique
            # combination of 2 of the downstream customers' data. The estimate
            # with the highest average voltage will be selected.

            # only consider time points with forward power flow
            filter_keep = (xfmr_p_kw_sum > 0) & (xfmr_q_kvar_sum > 0)

            # create list of all combinations of customer buses
            idx_array = np.arange(0, len(bus_list), 1)
            combinations = list(itertools.combinations(idx_array, 2))

            # pre-allocation to estimate V measurements at Xfmr LV terminals
            xfmr_v_est_all = np.full(
                (len(temp_df['kw_reading']), len(combinations)),
                np.nan)
            xfmr_v_est_all_filtered = np.full(
                (np.sum(filter_keep), len(combinations)),
                np.nan)

            # estimate the voltages at the xfmr LV terminals using each
            # combination of customer buses
            for ii in range(len(combinations)):
                iter_now = combinations[ii]

                bus1_name = bus_list.iloc[iter_now[0]]
                bus1_df = input_data[input_data['busname'] == bus1_name].copy()
                bus1_df_filtered = bus1_df[filter_keep]
                p1_w = 1e3 * (bus1_df_filtered['kw_reading'].values)
                p1_w = np.reshape(p1_w, (len(p1_w), 1))
                q1_var = 1e3 * (bus1_df_filtered['kvar_reading'].values)
                q1_var = np.reshape(q1_var, (len(q1_var), 1))
                v1_v = bus1_df_filtered['v_reading'].values
                v1_v = np.reshape(v1_v, (len(v1_v), 1))
                ir1 = p1_w / v1_v
                ix1 = q1_var / v1_v

                bus2_name = bus_list.iloc[iter_now[1]]
                bus2_df = input_data[input_data['busname'] == bus2_name].copy()
                bus2_df_filtered = bus2_df[filter_keep]
                p2_w = 1e3 * (bus2_df_filtered['kw_reading'].values)
                p2_w = np.reshape(p2_w, (len(p2_w), 1))
                q2_var = 1e3 * (bus2_df_filtered['kvar_reading'].values)
                q2_var = np.reshape(q2_var, (len(q2_var), 1))
                v2_v = bus2_df_filtered['v_reading'].values
                v2_v = np.reshape(v2_v, (len(v2_v), 1))
                ir2 = p2_w / v2_v
                ix2 = q2_var / v2_v

                # format data for linear regression
                # uses filtered data for forward power flow time points only
                y_data = v1_v - v2_v
                x_data = np.concatenate((-1*ir1, -1*ix1, ir2, ix2), axis=1)

                # apply linear fit (v1-v2 = ir1*r1 + ix1*x1 + ir2*r2 + ix2*x2)
                f_r1x1r2x2 = linear_model.LinearRegression(fit_intercept=False)
                f_r1x1r2x2.fit(x_data, y_data)

                r1 = f_r1x1r2x2.coef_[0, 0]
                x1 = f_r1x1r2x2.coef_[0, 1]
                r2 = f_r1x1r2x2.coef_[0, 2]
                x2 = f_r1x1r2x2.coef_[0, 3]

                v0_1 = np.abs(v1_v + (r1 + 1j*x1) * (ir1 + 1j*ix1))
                v0_2 = np.abs(v2_v + (r2 + 1j*x2) * (ir2 + 1j*ix2))
                v0 = (v0_1+v0_2)/2.0

                xfmr_v_est_all_filtered[:, ii] = v0[:, 0]

                # calculate the estimated voltages for all time points
                p1_w_all = 1e3*(bus1_df['kw_reading'].values)
                p1_w_all = np.reshape(p1_w_all, (len(p1_w_all), 1))
                q1_var_all = 1e3*(bus1_df['kvar_reading'].values)
                q1_var_all = np.reshape(q1_var_all, (len(q1_var_all), 1))
                v1_v_all = bus1_df['v_reading'].values
                v1_v_all = np.reshape(v1_v_all, (len(v1_v_all), 1))
                ir1_all = p1_w_all / v1_v_all
                ix1_all = q1_var_all / v1_v_all

                p2_w_all = 1e3 * (bus2_df['kw_reading'].values)
                p2_w_all = np.reshape(p2_w_all, (len(p2_w_all), 1))
                q2_var_all = 1e3*(bus2_df['kvar_reading'].values)
                q2_var_all = np.reshape(q2_var_all, (len(q2_var_all), 1))
                v2_v_all = bus2_df['v_reading'].values
                v2_v_all = np.reshape(v2_v_all, (len(v2_v_all), 1))
                ir2_all = p2_w_all / v2_v_all
                ix2_all = q2_var_all / v2_v_all

                v0_1_all = np.abs(
                    v1_v_all + (r1 + 1j * x1) * (ir1_all + 1j * ix1_all)
                 )
                v0_2_all = np.abs(
                    v2_v_all + (r2 + 1j * x2) * (ir2_all + 1j * ix2_all)
                    )
                v0_all = (v0_1_all + v0_2_all) / 2.0

                xfmr_v_est_all[:, ii] = v0_all[:, 0]

            # select the combination that resulted in the estimate with the
            # highest average voltage
            mean_v_est_filtered = np.mean(xfmr_v_est_all_filtered, axis=0)
            idx_max_mean_v_est = np.argmax(mean_v_est_filtered)
            xfmr_v_est_final = xfmr_v_est_all[:, idx_max_mean_v_est]

            # fill in the temporary df for this xfmr with the summed P and Q
            # values and the estimated voltages
            array_temp = np.full(temp_df['busname'].shape, xfmr_idx)
            temp_df.rename(
                columns={'busname': 'Transformer Index'},
                inplace=True)
            temp_df['Transformer Index'] = array_temp.copy()

            temp_df['v_reading'] = xfmr_v_est_final.copy()
            temp_df['kw_reading'] = xfmr_p_kw_sum.copy()
            temp_df['kvar_reading'] = xfmr_q_kvar_sum.copy()

            # concatenate this df with the full df for all xfmrs
            df_xfmr_estimated = pd.concat(
                [df_xfmr_estimated, temp_df],
                ignore_index=True)

    return df_xfmr_estimated


def get_xfmr_sizes(df_xfmr_info, df_xfmr_estimated, xf_lookup):
    """
    estimates the xfmr kVA ratings of all xfmrs
    """
    xfmr_size_final = np.full((len(df_xfmr_info), 1), np.nan)
    conf_score = np.full((len(df_xfmr_info), 1), np.nan)

    for ii in range(len(df_xfmr_info)):
        # get the estimated measurements for the target xfmr
        target_xfmr_idx = df_xfmr_info['Transformer Index'][ii]
        estimated_xfmr_mask = df_xfmr_estimated['Transformer Index'] == target_xfmr_idx
        df_target_xfmr_pqv = df_xfmr_estimated[estimated_xfmr_mask].copy()

        info_xfmr_mask = df_xfmr_info['Transformer Index'] == target_xfmr_idx
        df_target_xfmr_info = df_xfmr_info[info_xfmr_mask].copy()

        p1_w = 1e3 * (df_target_xfmr_pqv['kw_reading'].values)
        p1_w = np.reshape(p1_w, (len(p1_w), 1))
        q1_var = 1e3 * (df_target_xfmr_pqv['kvar_reading'].values)
        q1_var = np.reshape(q1_var, (len(q1_var), 1))
        v1_v = df_target_xfmr_pqv['v_reading'].values
        v1_v = np.reshape(v1_v, (len(v1_v), 1))
        ir1 = p1_w / v1_v
        ix1 = q1_var / v1_v

        nearby_xfmr_idx_all = df_target_xfmr_info['nearby_idx'].values
        nearby_xfmr_idx_all = nearby_xfmr_idx_all[0]

        kva_estimated = np.full((len(nearby_xfmr_idx_all), 1), np.nan)
        rmse = np.full((len(nearby_xfmr_idx_all), 1), np.nan)
        idx_selected_xfmr = np.full((len(nearby_xfmr_idx_all), 1), np.nan)
        had_neg_z = np.full((len(nearby_xfmr_idx_all), 1), False)

        # estimate the targer xfmr impedances using each nearby xfmr
        for nn in range(len(nearby_xfmr_idx_all)):
            # get the estimated measurements for a nearby xfmr
            nearby_idx_now = nearby_xfmr_idx_all[nn]
            xfmr_mask = df_xfmr_estimated['Transformer Index'] == nearby_idx_now
            df_nearby_xfmr_pqv = df_xfmr_estimated[xfmr_mask].copy()

            p2_w = 1e3 * (df_nearby_xfmr_pqv['kw_reading'].values)
            p2_w = np.reshape(p2_w, (len(p2_w), 1))
            q2_var = 1e3 * (df_nearby_xfmr_pqv['kvar_reading'].values)
            q2_var = np.reshape(q2_var, (len(q2_var), 1))
            v2_v = df_nearby_xfmr_pqv['v_reading'].values
            v2_v = np.reshape(v2_v, (len(v2_v), 1))
            ir2 = p2_w / v2_v
            ix2 = q2_var / v2_v

            # filter for only forward power flow time points
            filter_target_has_forward_power = (p1_w > 0) & (q1_var > 0)
            filter_nearby_has_forward_power = (p2_w > 0) & (q2_var > 0)
            filter_final = (filter_target_has_forward_power & filter_nearby_has_forward_power)

            v1_v_filtered = v1_v[filter_final]
            v1_v_filtered = np.reshape(v1_v_filtered, (len(v1_v_filtered), 1))
            ir1_filtered = ir1[filter_final]
            ir1_filtered = np.reshape(ir1_filtered, (len(ir1_filtered), 1))
            ix1_filtered = ix1[filter_final]
            ix1_filtered = np.reshape(ix1_filtered, (len(ix1_filtered), 1))

            v2_v_filtered = v2_v[filter_final]
            v2_v_filtered = np.reshape(v2_v_filtered, (len(v2_v_filtered), 1))
            ir2_filtered = ir2[filter_final]
            ir2_filtered = np.reshape(ir2_filtered, (len(ir2_filtered), 1))
            ix2_filtered = ix2[filter_final]
            ix2_filtered = np.reshape(ix2_filtered, (len(ix2_filtered), 1))

            # format data for linear regression
            # uses filtered data for forward power flow time points only
            y_data = v1_v_filtered - v2_v_filtered
            x_data = np.concatenate((
                -1*ir1_filtered,
                -1*ix1_filtered,
                ir2_filtered,
                ix2_filtered),
                axis=1)

            # apply linear fit (v1-v2 = ir1*r1 + ix1*x1 + ir2*r2 + ix2*x2)
            f_r1x1r2x2 = linear_model.LinearRegression(fit_intercept=False)
            f_r1x1r2x2.fit(x_data, y_data)

            # calculate the fit of the model
            y_pred = f_r1x1r2x2.predict(x_data)
            mse = mean_squared_error(y_data, y_pred)
            rmse[nn] = np.sqrt(mse)

            # pull out the impedance estimates for the target xfmr
            r_target_est = f_r1x1r2x2.coef_[0, 0]
            x_target_est = f_r1x1r2x2.coef_[0, 1]
            had_neg_z[nn] = np.any(f_r1x1r2x2.coef_ < 0)

            # select the xfmr type from the lookup table that best matches
            # the estimated impedance
            r_abs_error = np.abs(r_target_est - xf_lookup['R_ohms_LV'])
            x_abs_error = np.abs(x_target_est - xf_lookup['X_ohms_LV'])
            error_total = r_abs_error + x_abs_error
            idx_min_error = np.argmin(error_total)
            idx_selected_xfmr[nn] = idx_min_error
            kva_estimated[nn] = xf_lookup['kVA'][idx_min_error]

        # tally the weighted vote totals for each xfmr type from xf_lookup
        mat_1, mat_2 = np.meshgrid(
            range(len(xf_lookup)),
            idx_selected_xfmr,
            indexing='ij')
        mat_votes_filter = mat_1 == mat_2
        mat_votes_weighted = np.zeros(np.shape(mat_votes_filter))
        mat_votes_weighted[mat_votes_filter] = 1
        weights_rmse = (1/rmse)/np.sum(1/rmse)
        weights_rmse = np.reshape(weights_rmse, (len(weights_rmse), 1))
        weights_rmse = np.tile(weights_rmse, len(xf_lookup))
        weights_rmse = np.transpose(weights_rmse)
        mat_votes_weighted = mat_votes_weighted * weights_rmse
        votes_weighted_total = np.sum(mat_votes_weighted, axis=1)

        max_vote_pct = np.max(votes_weighted_total)
        idx_vote_final = np.argmax(votes_weighted_total)
        kva_vote_final = xf_lookup['kVA'][idx_vote_final]

        xfmr_size_final[ii] = kva_vote_final
        conf_score[ii] = max_vote_pct

    df_xfmr_sizes = pd.DataFrame({
        'kVA_estimated': xfmr_size_final.flatten(),
        'conf_score': conf_score.flatten(),
        }
        )

    return df_xfmr_sizes


def get_customer_tchc(
        Final_results,
        df_xfmr_estimated,
        df_xfmr_info,
        overload_constraint,
        has_location_info,
        der_pf):
    """
    calculates the thermal-constrained hosting capacity for each customer
    """
    # initialize the dataframe for the final tchc results
    tchc_results = pd.DataFrame()
    tchc_results['busname'] = Final_results['busname'].copy()
    tchc_results['TCHC (kVA)'] = np.full((len(Final_results), 1), np.nan)
    tchc_results['TCHC (kW)'] = np.full((len(Final_results), 1), np.nan)

    if has_location_info:
        tchc_results['bus X coord'] = Final_results['X'].copy()
        tchc_results['bus Y coord'] = Final_results['Y'].copy()

    tchc_results['Transformer Index'] = Final_results['Transformer Index'].copy()
    tchc_results['Transformer kVA'] = np.full((len(Final_results), 1), np.nan)
    tchc_results['kVA Weighted Voting Score'] = np.full(
        (len(Final_results), 1),
        np.nan)

    # ensure datetime column
    # TODO: check if datetime already, if not, then convert
    df_xfmr_estimated['datetime'] = pd.to_datetime(
        df_xfmr_estimated['datetime'], utc=True)

    # loop through all xfmrs to calculate the tchc
    # assign that value to each downstream bus
    for ii in range(len(df_xfmr_info)):
        xfmr_now_idx = df_xfmr_info['Transformer Index'][ii]
        est_xfmr_mask = df_xfmr_estimated['Transformer Index'] == xfmr_now_idx
        df_target_xfmr_pqv = df_xfmr_estimated[est_xfmr_mask].copy()
        info_xfmr_mask = df_xfmr_info['Transformer Index'] == xfmr_now_idx
        df_target_xfmr_info = df_xfmr_info[info_xfmr_mask].copy()

        # create the "daytime hours" filter
        after_sunrise = df_target_xfmr_pqv['datetime'].dt.hour >= 9
        before_sunset = df_target_xfmr_pqv['datetime'].dt.hour < 15
        hours_of_interest_mask = after_sunrise & before_sunset

        # mask inputs
        df_target_xfmr_pqv = df_target_xfmr_pqv[hours_of_interest_mask]

        xfmr_now_conf = df_target_xfmr_info['conf_score'].values
        xfmr_now_conf = xfmr_now_conf[0]

        xfmr_now_kva = df_target_xfmr_info['kVA_estimated'].values
        xfmr_now_kva = xfmr_now_kva[0]
        kva_limit_val = -1 * overload_constraint * xfmr_now_kva

        p1_kw = df_target_xfmr_pqv['kw_reading'].values
        p1_kw = np.reshape(p1_kw, (len(p1_kw), 1))
        q1_kvar = df_target_xfmr_pqv['kvar_reading'].values
        q1_kvar = np.reshape(q1_kvar, (len(q1_kvar), 1))

        # calculate the existing total kVA loading on this xfmr
        s1_kva = np.sqrt(p1_kw**2 + q1_kvar**2)

        # convert the thermal limit to a time-series
        kva_limit_ts = kva_limit_val * np.ones(np.shape(s1_kva))

        # calculate the thermal headroom for reverse power flow, using der_pf
        if der_pf == 1:
            # Check for negative values and handle them
            q1_temp = np.copy(q1_kvar)
            filter_neg_sqrt = np.abs(q1_temp) > np.abs(kva_limit_ts)
            q1_temp[filter_neg_sqrt] = np.nan

            p_pv_max_ts = np.sqrt((kva_limit_ts**2) - (q1_temp**2)) + p1_kw
            p_pv_max_ts[np.isnan(p_pv_max_ts)] = 0
            s_pv_max_ts = p_pv_max_ts
        else:
            k_pf = der_pf/np.sin(np.arccos(der_pf))
            coef_a = np.tile((1+(1/(k_pf**2))), len(p1_kw))
            coef_a = np.reshape(coef_a, (len(coef_a), 1))
            coef_b = (2*q1_kvar/k_pf) + (2*p1_kw)
            coef_c = (p1_kw**2)+(q1_kvar**2)-(kva_limit_ts**2)

            p_pv_max_ts = np.full((len(p1_kw), 1), np.nan)
            coef_all = np.concatenate([coef_a, coef_b, coef_c], axis=1)

            discriminant = coef_b[:, 0]**2 - (4*coef_a[:, 0]*coef_c[:, 0])
            complex_only_mask = discriminant < 0
            roots = [np.roots(coeff) for coeff in coef_all]

            roots_zero = np.concatenate(
                (roots, np.zeros(np.shape(roots))),
                axis=1)

            p_pv_max_ts = np.min(roots_zero, axis=1)
            p_pv_max_ts[complex_only_mask] = 0

            p_pv_max_ts = np.abs(p_pv_max_ts)
            p_pv_max_ts = p_pv_max_ts.reshape(-1, 1)

            s_pv_max_ts = np.abs(p_pv_max_ts / der_pf)
            s_pv_max_ts = s_pv_max_ts.reshape(-1, 1)

        # Ensures negative HC set to zero
        s_pv_max_ts = np.concatenate(
            (s_pv_max_ts, np.zeros(np.shape(s_pv_max_ts))),
            axis=1)
        s_pv_max_ts = np.max(s_pv_max_ts, axis=1)
        s_pv_max_ts_daytime = np.reshape(s_pv_max_ts, (len(s_pv_max_ts), 1))

        # take the daytime minimum as the hosting capacity limit
        s_pv_tchc_scen2 = np.min(s_pv_max_ts_daytime)
        p_pv_tchc_scen2 = np.abs(s_pv_tchc_scen2*der_pf)

        # store the values in the output dataframe
        filter_xfmr_now = tchc_results['Transformer Index'] == xfmr_now_idx

        tchc_results.loc[filter_xfmr_now, 'Transformer kVA'] = xfmr_now_kva
        tchc_results.loc[filter_xfmr_now, 'kVA Weighted Voting Score'] = xfmr_now_conf
        tchc_results.loc[filter_xfmr_now, 'TCHC (kVA)'] = s_pv_tchc_scen2
        tchc_results.loc[filter_xfmr_now, 'TCHC (kW)'] = p_pv_tchc_scen2

    return tchc_results


def check_results(res, ref_res):
    """
    assumes res is return from sandia_TCHC.hosting_cap_tchc
    ref_res is the reference output to compare too

    will round floats to 4
    """
    for index, row in res.iterrows():
        ref_row = ref_res.loc[index]

        for ref_val, res_val in zip(ref_row.values, row.values):
            if isinstance(res_val, float):
                match = np.round(ref_val, 4) == np.round(res_val, 4)
            else:
                match = ref_val == res_val

            if not match:
                return False
    return True
