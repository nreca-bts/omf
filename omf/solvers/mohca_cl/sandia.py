"""
Run Sandia model-free photovoltaic hosting-capacity analysis from AMI and feeder
metadata.
"""

import time
import numpy as np
import pandas as pd
from sklearn import linear_model
import logging
from pathlib import Path


def hosting_cap(
        input_csv_path,
        output_csv_path,
        der_pf=None,
        vv_x=None,
        vv_y=None,
        load_pf_est=0.97
):
    """
    Calculate hosting capacity based on input csv
    export results to output_csv_path

    Assert OMF format of file at input_csv_path with required columns:
        busname: [any string]
        datetime: [YY-MM-DDTHH:MMZ]
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

    The optional input variable load_pf_est is utilized when reactive power
        measurements are not available for a customer, and represents an
        estimated average power factor.

    """

    # logging Setup
    logging.basicConfig(filename=Path(input_csv_path).parent.absolute() / 'mohca_sandia.log',
        encoding="utf-8",
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    logger.info('*** Start of Run')

    t1 = time.perf_counter()
    input_data = pd.read_csv(input_csv_path)
    t2 = time.perf_counter()
    logger.info("Elapsed Load Time: %f", t2-t1)

    # set the upper bound voltage limit
    vpu_upperbound = 1.05

    # accomodate optional power factor
    # sign convention: capacitive PF (+), inductive PF (-)
    if der_pf is None:
        der_pf = 1.0

    # accomodate optional Volt-VAR mode
    # sign convention: capacitive VAR (+), inductive VAR (-)
    if vv_x is not None and vv_y is not None:
        # Check for valid length
        if len(vv_x) != len(vv_y):
            logger.warning('vv_x and vv_y are different lengths.')
            der_pf = 1.0

        else:
            # find intercept
            qpu = np.interp(vpu_upperbound, vv_x, vv_y)
            if qpu == 0:
                der_pf = 1.0
            else:
                der_pf = np.sign(qpu)*(1-qpu**2)**(1/2)

    logger.info('Using der_pf = %f', der_pf)

    # set the estimated X/R ratio
    # used with load_pf_est when kVAR measurements are unavailable
    xr_est = 0.5

    # ensure numeric values
    numeric_cols = ['v_reading', 'kw_reading', 'kvar_reading']
    for numeric_col in numeric_cols:
        if numeric_col in input_data.columns:
            input_data[numeric_col] = pd.to_numeric(input_data[numeric_col])

    if 'kvar_reading' not in input_data.columns:
        # handle case where kvar reading is not provided.
        input_data['kvar_reading'] = np.nan

    # ensure datetime column
    # NOTE: assume local time. If z offset included, applied to timestamp
    input_data['datetime'] = pd.to_datetime(input_data['datetime'], utc=True)

    # convert to category for more performant masking
    input_data['busname'] = input_data['busname'].astype('category')

    # Identify unique buses
    unique_buses = input_data['busname'].unique()  # list of buses/customers
    n_unique_buses = len(unique_buses)

    data_all = []  # storing data for all buses
    fix_reports = []

    # Handle each bus seperately
    n_skipped = 0
    n_hc_est = 0

    for bus_name in unique_buses:
        single_bus = input_data[input_data['busname'] == bus_name].copy()

        # ensure sort by datetime
        single_bus.sort_values('datetime', inplace=True)

        # dataframe to modify and include other necessary variables
        df_edit = pd.DataFrame()

        # modify data for algorithm
        # sign convention: negative for load, positive for PV injections
        df_edit['datetime'] = single_bus['datetime']
        df_edit['V'] = single_bus['v_reading']
        df_edit['P'] = -1 * single_bus['kw_reading']

        # account for no input Q
        has_input_q = get_has_input_q(single_bus)
        if has_input_q:
            df_edit['Q'] = -1 * single_bus['kvar_reading']

        # check for and correct inconsisent index
        try:
            df_edit = fix_inconsistent_time_index(df_edit)
        except ValueError:
            warning_str = (
                f"Warning in hosting_cap():  Skipped busname '{bus_name}' " +
                "- unrecoverable datetime issue"
            )
            logger.warning(warning_str)
            n_skipped += 1
            data_single = [bus_name, 'E01']
            data_all.append(data_single)
            continue

        # print warning if time index was corrected.
        if not compare_columns(
                df_edit['datetime'].values, single_bus['datetime'].values):
            # notify of correction, but continue procssing
            warning_str = (
                f"Warning in hosting_cap():  Fixed datetime of busname '{bus_name}' - " +
                "was originally inconsistent"
            )
            logger.warning(warning_str)

        # check for nan data in any column
        nan_mask = get_nan_mask(df_edit)

        # check for held data
        held_mask = get_held_value_mask(df_edit)

        # check voltage range
        # NOTE: v_base and vpu stored in df_edit in case useful later
        df_edit['v_base'] = get_v_base(df_edit)
        df_edit['vpu'] = get_vpu(df_edit)
        bad_voltage_mask = get_bad_voltage_mask(df_edit)

        # combine bad data masks
        bad_data_mask = nan_mask | held_mask | bad_voltage_mask

        # create error blocks (for length checks)
        error_blocks = get_error_blocks(bad_data_mask)

        # fix data, with report
        fixed_data, single_fix_report = fix_error_blocks(
            df_edit,
            error_blocks
        )

        # ignore empty fix reports
        if len(single_fix_report) > 0:
            single_fix_report['busname'] = bus_name
            fix_reports.append(single_fix_report)

        # count n of np.nan (for data quality check)
        remaining_bad_data_mask = get_nan_mask(fixed_data)

        # Check if a large number of datapoints were elminated
        required_data_quality = 85  # NOTE: arbitrary required percent
        n_bad_pts = remaining_bad_data_mask.sum()
        data_quality = round((1 - (n_bad_pts / len(fixed_data))) * 100, 2)

        if data_quality < required_data_quality:
            # skip processing
            warning_str = (
                f"Warning in hosting_cap():  Skipped busname '{bus_name}' " +
                f"- data quality of {data_quality}%"
            )
            logger.warning(warning_str)

            #nan_str = 'bad data at index ['
            #for _, row, in single_fix_report.iterrows():
            #    if row['action'] == 'nand':
            #        nan_str += f"{row['start_ndx']}:{row['end_ndx']}, "

            #nan_str = '* ' + nan_str[:-2] + ']'
            #logger.info(nan_str)  # NOTE: removed logging of skipped data rows
            n_skipped += 1
            data_single = [bus_name, 'E02']
            data_all.append(data_single)
            continue

        # check for PV via kw injections and set has_pv flag
        has_pv = False
        injection_noise_threshold = 0.05
        injection_count_threshold = 10

        n_kw_injections = fixed_data['P'] >= injection_noise_threshold
        if n_kw_injections.sum() > injection_count_threshold:
            has_pv = True
            logger.info('found %d injections', n_kw_injections.sum())

        # Calcualte deltas
        fixed_data['p_diff'] = fixed_data['P'].diff()
        fixed_data['v_diff'] = fixed_data['V'].diff()

        # handle optional Q
        has_static_pf = False
        if has_input_q:
            fixed_data['S'] = -1 * np.sqrt(
                fixed_data['P']**2 + fixed_data['Q']**2
            )
            fixed_data['PF'] = fixed_data['P'] / fixed_data['S']
            fixed_data['q_diff'] = fixed_data['Q'].diff()
            fixed_data['pf_diff'] = abs(fixed_data['PF'].diff())

            # handle static power factor
            max_pf_dif = fixed_data['pf_diff'].max()
            # NOTE: arbitrary threshold selected
            static_pf_threshold = 1e-3
            if max_pf_dif < static_pf_threshold:
                has_static_pf = True
                # skip processing
                warning_str = (
                    f"Warning in hosting_cap():  busname '{bus_name}' " +
                    "- has static PF - " +
                    f"maximum abs dif doesn't exceed {max_pf_dif}"
                )
                logger.warning(warning_str)

        remaining_bad_data_mask = get_nan_mask(fixed_data)

        # fixed data may include nan - removing with this mask
        clean_df = fixed_data[~remaining_bad_data_mask].copy()
        if ~has_input_q or has_static_pf:

            # static_pf_val from static PF
            if has_static_pf:
                static_pf_val = fixed_data['pf_diff'].mean()

            # skip processing
            warning_str = (
                f"Warning in hosting_cap():  busname '{bus_name}' " +
                "- Processing as no input Q or static PF"
            )
            logger.warning(warning_str)

        if has_input_q and not has_static_pf:
            # Filter points to fit according to quantiles
            # only large changes in P (larger than 25 quantile)
            filter_1 = (
                clean_df.p_diff > abs(clean_df.p_diff).quantile(.25)) \
                | (
                clean_df.p_diff < -abs(clean_df.p_diff).quantile(.25))

            # only large changes in PF (larger than 10th quantile)
            filter_2 = (
                clean_df.pf_diff > abs(clean_df.pf_diff).quantile(.10)) \
                | (
                clean_df.pf_diff < -abs(clean_df.pf_diff).quantile(.10)) \
                & filter_1

            # remove large dV outliers (inside 99th quantile)
            filter_3 = (
                clean_df.v_diff < abs(clean_df.v_diff).quantile(.99)) \
                & (
                clean_df.v_diff > -abs(clean_df.v_diff).quantile(.99)) \
                & filter_2

            # if customer has PV, the nighttime filter has to be added to the
            # diff filters and applied before the regression
            if has_pv:
                logger.info('\n* Using Night hours')
                before_sunrise = clean_df['datetime'].dt.hour <= 5
                after_sunset = clean_df['datetime'].dt.hour >= 20
                nighttime_mask = before_sunrise | after_sunset
                filter_3 = filter_3 & nighttime_mask

            # linear fit (bias term included)
            filtered_powers = pd.concat(
                [
                    clean_df.p_diff[filter_3],
                    clean_df.q_diff[filter_3]
                ],
                axis=1)
            filtered_v_dif = clean_df.v_diff[filter_3]

            # NOTE: changed to False 20241004
            f_pq = linear_model.LinearRegression(fit_intercept=False)

            # linear fit (V = p00 + p10*P + p01*Q)
            f_pq.fit(filtered_powers, filtered_v_dif)

            sigma_p = f_pq.coef_[0]
            sigma_q = f_pq.coef_[1]

            # Calculate kW_max
            clean_df['kw_max'] = (
                1.05 * clean_df['v_base'] - clean_df['V']) \
                / (sigma_p + (sigma_q*np.tan(np.arccos(der_pf))))

        # Modifications for missing Q
        # if has_static_pf: load_pf_est gets overwritten to the static PF
        if ~has_input_q or has_static_pf:

            warning_str = (
                f"Warning in hosting_cap():  kVAR measurements for busname '{bus_name}' " +
                "were unavailable or of insufficient quality. " +
                "HC accuracy may be affected. "
            )
            logger.warning(warning_str)

            if has_static_pf:
                # use static pf as load pf estimate
                load_pf_est = static_pf_val

            # Filter points to fit according to quantiles
            # only large changes in P (larger than 25 quantile)
            filter_1_noq = (
                clean_df.p_diff > abs(clean_df.p_diff).quantile(.25)) \
                | (
                clean_df.p_diff < -abs(clean_df.p_diff).quantile(.25))

            # remove large dV outliers (inside 99th quantile)
            filter_3_noq = (
                clean_df.v_diff < abs(clean_df.v_diff).quantile(.99)) \
                & (
                clean_df.v_diff > -abs(clean_df.v_diff).quantile(.99)) \
                & filter_1_noq

            # optional nighttime filter if customer has PV
            if has_pv:
                logger.info('\n* Using Night hours')
                before_sunrise = clean_df['datetime'].dt.hour <= 5
                after_sunset = clean_df['datetime'].dt.hour >= 20
                nighttime_mask = before_sunrise | after_sunset
                filter_3_noq = filter_3_noq & nighttime_mask

            # apply filters
            filtered_p_noq = clean_df.p_diff[filter_3_noq]
            filtered_v_dif_noq = clean_df.v_diff[filter_3_noq]

            # calculate the constant offset factor,
            const_xrpf = (1+xr_est*np.tan(np.arccos(load_pf_est)))

            # apply to offset factor
            filtered_p_noq_offset = const_xrpf * filtered_p_noq

            # linear fit:
            f_p_no_q = linear_model.LinearRegression(fit_intercept=False)
            f_p_no_q.fit(filtered_p_noq_offset.to_frame(), filtered_v_dif_noq)

            sigma_p_noq = f_p_no_q.coef_[0]

            # Calculate kW_max
            clean_df['kw_max'] = (
                1.05 * clean_df['v_base'] - clean_df['V']) \
                / (sigma_p_noq)

        after_sunrise = clean_df['datetime'].dt.hour >= 9
        before_sunset = clean_df['datetime'].dt.hour < 15
        hours_of_interest_mask = after_sunrise & before_sunset

        hc_kw = min(clean_df.kw_max[hours_of_interest_mask])
        hc_kw = max(hc_kw, 0)  # Ensures negative HC set to zero

        # collect individual HC result
        data_single = [bus_name, hc_kw]
        data_all.append(data_single)
        n_hc_est += 1

    hc_results = pd.DataFrame(
        data_all,
        columns=['busname', 'kw_hostable'],
    )

    # Output CSV File of Results
    hc_results.to_csv(output_csv_path, index=False)

    # NOTE: printing of fix report 'temporary' solution
    logger.info('')
    if len(fix_reports) > 0:
        fix_report_df = pd.concat(fix_reports, ignore_index=True)
        fix_report_df = fix_report_df[[
            'busname',
            'start_ndx',
            'duration',
            'end_ndx',
            'action'
        ]]
        logger.info('* Data Fix Report')
        logger.info(fix_report_df)
    else:
        fix_report_df = '* No Data Fixes Executed'

    logger.info("Identified %d unique buses in input data.", n_unique_buses)
    logger.info("HC calculated for: %d", n_hc_est)
    logger.info("Skipped: %d", n_skipped)
    logger.info('*** End of Run')
    logging.shutdown()

    return hc_results


def sanity_check(model_free_result_path, external_result_path):
    """
    Checks results to confirm percent differences are less than 20%

    ASSERT csv columns of:
        busname: [any string]
        kW_hostable: [any float]

    ASSERT external results are 'truth'

    """
    model_free_results = pd.read_csv(model_free_result_path)
    external_results = pd.read_csv(external_result_path)

    results = pd.merge(
        model_free_results,
        external_results,
        how='left',
        left_on='busname',
        right_on='busname'
    )
    results['dif'] = results['kw_hostable_x'] - results['kw_hostable_y']
    results['abs_dif'] = results['dif'].abs()
    results['percent_dif'] = (
        results['abs_dif'] / external_results['kw_hostable'] * 100
    )

    largest_dif = results['percent_dif'].max()

    return largest_dif <= 20


# Error checking functionality modifed from TEA
def get_consistent_time_index(index_col):
    """
    Return consistent and full date range based on passed in column
    where the time step is determined by the time delta between the
    first and second data point, and total length based on first and
    last points.

    Modified from TEA to accomodate timedelta64 types and UTC requirement

    ASSERT time index is sorted in ascending time order
    """
    if len(index_col) < 2:
        raise ValueError("** datetime is less than 2 in length")

    first_step = index_col[0]
    second_step = index_col[1]
    last_step = index_col[-1]
    time_step = second_step - first_step

    if time_step < 1:
        raise ValueError("** time_step < 1")

    time_step = int(time_step / np.timedelta64(1, 's'))
    freq = str(time_step) + 's'
    duration = (last_step - first_step) / np.timedelta64(1, 's')

    n_periods = int(duration / time_step + 1)

    return pd.date_range(first_step, periods=n_periods, freq=freq, tz='UTC')


def fix_inconsistent_time_index(input_data):
    """
    Creates consistent time index

    Modified from TEA to accomodate datetime and input data format

    ASSERT time index is sorted in ascending time order
    """
    index_name = 'datetime'
    bad_index = input_data[index_name].values
    correct_index = get_consistent_time_index(bad_index)

    fixed_df = pd.merge(
        pd.Series(correct_index, name=index_name),
        input_data,
        left_on=index_name,
        right_on=index_name,
        how='left')

    return fixed_df


def get_nan_mask(df):
    """
    Return single bool series of rows that contains nan
    """
    return df.isna().sum(axis=1) > 0


def get_held_value_mask(
        df,
        held_n_threshold=4,
        held_value_threshold=0
):
    """
    Return single bool series of rows that are within held value limits
    Ignores nan data

    """
    mask = pd.Series(data=False, index=df.index)
    columns_to_check = ['P', 'Q', 'V']
    columns_to_check = [x for x in columns_to_check if x in df.columns]

    for column_name in columns_to_check:
        column_data = df[column_name]
        # drop nans from nan check
        column_data = column_data[~column_data.isna()]

        # Identify where absolute value changes by diffs and value_threshold
        value_changes = abs(column_data.diff()).gt(held_value_threshold)
        # Group consecutive identical values
        groups = value_changes.cumsum()
        # Count occurrences in each group and filter based on n_threshold
        filtered_groups = groups.value_counts()[
            groups.value_counts() >= held_n_threshold]

        # set mask locations of error to true for any column
        for group_label in filtered_groups.index:
            group_indices = groups[groups == group_label].index
            mask[group_indices] = True

    return mask


def get_has_input_q(input_data):
    """
    check if input data has q, return false if no q
    assumes input column is empty.
    """
    return ~(len(input_data) == input_data['kvar_reading'].isna().sum())


def compare_columns(ndx_a, ndx_b):
    """
    Compare length and value of two columns
    """
    if len(ndx_a) != len(ndx_b):
        return False
    for a, b in zip(ndx_a, ndx_b):
        if a != b:
            return False
    return True


def get_error_blocks(bad_data_mask):
    """
    Analyze bad data bask to identify blocks of bad data.
    returns dictionary of error blocks.

    Modified from TEA for simplier input and output
    """
    error_cum_sum = (~bad_data_mask).cumsum()
    error_blocks = {}

    block_n = 1

    for _, block in bad_data_mask.groupby(error_cum_sum[bad_data_mask]):

        start_ndx = block.index[0]
        end_ndx = block.index[-1]

        duration = end_ndx - start_ndx + 1  # for inclusive math

        error_blocks[block_n] = {}
        error_blocks[block_n]['duration'] = duration
        error_blocks[block_n]['start_ndx'] = start_ndx
        error_blocks[block_n]['end_ndx'] = end_ndx + 1

        block_n += 1

    return error_blocks


def get_v_base(df_edit):
    """
    identify voltage base as either 120 or 240
    """
    v_mask = abs(df_edit['V'] - 120) < abs(df_edit['V'] - 240)
    df_edit.loc[v_mask, 'v_base'] = 120
    df_edit.loc[~v_mask, 'v_base'] = 240
    return df_edit['v_base']


def get_vpu(df_edit):
    """
    Calculate per unit voltage based
    """
    df_edit['vpu'] = df_edit['V'] / df_edit['v_base']
    return df_edit['vpu']


def get_bad_voltage_mask(df_edit, pu_threshold=0.2):
    """
    return mask of voltages outside give per-unit threshold
    """
    high_voltage = df_edit['vpu'] >= (1 + pu_threshold)
    low_voltage = df_edit['vpu'] <= (1 - pu_threshold)
    bad_voltage_mask = high_voltage | low_voltage
    return bad_voltage_mask


def fix_by_interpolation(df, error_block, kind='linear'):
    """
    interpolate missing values based on known data
    kind can be any valid entry to a pandas dataframe.interpolate method

    Modified from TEA for known input format
    """
    start_ndx = error_block['start_ndx']
    end_ndx = error_block['end_ndx']
    adj_start = start_ndx - 1

    # only interpolate data columns
    columns_to_nan = ['P', 'Q', 'V']
    columns_to_nan = [x for x in columns_to_nan if x in df.columns]
    for col in columns_to_nan:
        data_to_interpolate = df.loc[adj_start:end_ndx, col].copy()
        data_to_interpolate.loc[start_ndx:end_ndx-1] = np.nan
        df.loc[adj_start:end_ndx, col] = data_to_interpolate.interpolate(kind)

    return df


def replace_with_nan(df, error_block, replacement_data=np.nan):
    """"
    Modifed from TEA to handle nan replacements in known inputs
    """
    start_ndx = error_block['start_ndx']
    end_ndx = error_block['end_ndx'] - 1  # to accomodate for inclusive slice

    columns_to_nan = ['P', 'Q', 'V']
    columns_to_nan = [x for x in columns_to_nan if x in df.columns]
    for col in columns_to_nan:
        df.loc[start_ndx:end_ndx, col] = replacement_data

    return df


def fix_error_blocks(input_df, error_blocks, interpolation_threshold=4):
    """
    Fix error blocks, return data df and error_report df
    """
    df = input_df.copy()
    block_report = {}
    block_n = 0

    for error_block in error_blocks.values():

        if error_block['duration'] <= interpolation_threshold:
            df = fix_by_interpolation(df, error_block)
            error_block['action'] = 'fixed'
            block_report[block_n] = error_block
        else:
            df = replace_with_nan(df, error_block)
            error_block['action'] = 'nand'
            block_report[block_n] = error_block
        block_n += 1

    error_df = pd.DataFrame.from_dict(block_report, orient='index')
    return df, error_df
