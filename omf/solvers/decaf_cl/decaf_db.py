"""
Loose functions for importing data into a sqlite database.
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path


def execute_query(db_name, query, params=None, fetch=False):
    """
    Execute a query on the SQLite database.

    :param db_name: Name of the SQLite database file.
    :param query: SQL query to execute.
    :param params: Optional parameters to bind to the query.
    :param fetch: Boolean indicating if the query is a read operation.
    :return: Results of the query if fetch is True, otherwise None.
    """
    try:
        # Use a context manager to ensure the connection is closed properly
        with sqlite3.connect(db_name) as conn:
            conn.execute('PRAGMA foreign_keys = ON;')
            cursor = conn.cursor()
            # Execute the query with parameters if provided
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Commit the changes if it's a write operation
            if not fetch:
                conn.commit()
                #  print("Query executed successfully.")
                return None
            # Fetch results if it's a read operation
            results = cursor.fetchall()
            return results

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        return None


def execute_many(db_name, query, data_to_insert):
    """
    Perform an executemany sql command on the SQLite database.

    :param db_name: Name of the SQLite database file.
    :param query: SQL query to execute.
    :param data_to_insert: data to insert in.
    """
    try:
        # Use a context manager to ensure the connection is closed properly
        with sqlite3.connect(db_name) as conn:
            conn.execute('PRAGMA foreign_keys = ON;')
            cursor = conn.cursor()
            cursor.executemany(query, data_to_insert)
            conn.commit()

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")


def pd_query(db_name, query):
    """
    Query db_name with SQL query, retun pandas dataframe
    NOTE: scope of conn semi-ambigous...
    """
    try:
        # Connect to the SQLite database
        with sqlite3.connect(db_name) as conn:
            conn.execute('PRAGMA foreign_keys = ON;')
            # Use pandas to execute the query and return a DataFrame
            df = pd.read_sql_query(query, conn)
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        return None

    return df


def process_time_col(raw_df, time_col):
    """
    process input (or raw) time column into dataframe that matches db schema
    """
    df = pd.DataFrame()
    # NOTE: raises warning if utc=False - local time set as a copy to avoid
    # df['local_time'] = pd.to_datetime(raw_df[time_col])
    df['local_time'] = raw_df[time_col].copy()

    df['utc_time'] = pd.to_datetime(raw_df[time_col], utc=True)

    df['unix_time'] = df['utc_time'].astype('int64') / 1e9

    # NOTE: division to remove extra 'ns' zeros. to_datetime requires unit='s'

    return df


def process_interconnect_input(interconnect_fp):
    """
    Read interconnect input
    Assumes (for now):
    columns are ['busname', 'date', 'kva']
    busname corresponds to the AMI busnames
    date has the same input time requirements as AMI
    kva is the rated kva of the system to be connected

    returns pandas dataframe with correctly formatted columns for time and
    interconnect database tables.
    """
    raw_df = pd.read_csv(interconnect_fp)

    df = pd.DataFrame()
    df['rated_kva'] = pd.to_numeric(raw_df['kva'])
    df['name'] = raw_df['busname']  # now Customer name

    time_df = process_time_col(raw_df, 'date')

    merged_df = time_df.merge(
        df,
        how='left',
        left_index=True,
        right_index=True,
        )

    return merged_df


def process_scada_input(scada_fp):
    """
    Read scada data csv, format columns for numeric type,
    Process time data to UTC
    return dataframe for database handling
    """
    raw_df = pd.read_csv(scada_fp)
    raw_df.columns = raw_df.columns.str.lower()

    # create df of numeric values
    df = pd.DataFrame()
    numeric_cols = [
        'kva', 'kvb', 'kvc',
        'mwa', 'mwb', 'mwc',
        'mvara', 'mvarb', 'mvarc',
        ]
    for numeric_col in numeric_cols:
        if numeric_col in raw_df.columns:
            df[numeric_col] = pd.to_numeric(raw_df[numeric_col])

    # ensure element column exists, create combined name
    if 'element' not in raw_df.columns:
        raw_df['element'] = ''
        raw_df['combined_name'] = raw_df['busname']
    else:
        raw_df['combined_name'] = raw_df['busname'] + '__' + raw_df['element']

    df['busname'] = raw_df['busname']
    df['element'] = raw_df['element']

    # this should allow for a unique index
    df['name'] = raw_df['combined_name'].astype('category')

    time_df = process_time_col(raw_df, 'datetime')
    merged_df = time_df.merge(
        df,
        how='left',
        left_index=True,
        right_index=True,
        )
    return merged_df


def infuse_scada_to_db(db_fp, scada_fp):
    """
    handle raw scada fp to db
    """
    processed_df = process_scada_input(scada_fp)
    add_time_to_db(db_fp, processed_df)

    # add scada_streams to db
    scada_id_df = add_scada_streams_to_db(db_fp, processed_df, return_ids=True)

    # attaching scada id to processed df
    processed_df['scada_id'] = 0
    scada_dict = {
        name: row['scada_id'] for name, row in scada_id_df.iterrows()}
    processed_df['scada_id'] = processed_df['name'].cat.rename_categories(scada_dict)

    # add scada streams to tables
    add_scada_to_db(db_fp, processed_df)


def add_scada_streams_to_db(db_fp, processed_df, return_ids=False):
    """
    add appropriate scada streams to databse
    optionally return ids of streams
    """
    unique_names = processed_df[['name']].drop_duplicates()

    data_to_insert = []

    for df_ndx, scada_name in unique_names.iterrows():
        name = scada_name.values[0]
        bus = processed_df.iloc[df_ndx]['busname']
        element = processed_df.iloc[df_ndx]['element']
        scada_tuple = (
            name,
            bus,
            element,
            )
        data_to_insert.append(scada_tuple)

    insert_query = """
    INSERT INTO SCADA_Stream (name, bus, element)
    VALUES (?, ?, ?)
    ON CONFLICT (name) DO NOTHING;
    """
    execute_many(db_fp, insert_query, data_to_insert)

    if return_ids:
        query = "SELECT scada_id, name FROM SCADA_Stream"
        scada_res = pd_query(db_fp, query)
        scada_res.set_index('name', inplace=True)
        return scada_res.loc[unique_names.values.flatten()]


def add_scada_to_db(db_name, df):
    """
    Add processed scada to database
    assert all columns are formatted and naming convention follows reqs & specs
    """
    scada_column_to_table = {
        'kva': 'kV_a',
        'kvb': 'kV_b',
        'kvc': 'kV_c',
        'mwa': 'MW_a',
        'mwb': 'MW_b',
        'mwc': 'MW_c',
        'mvara': 'MVAR_a',
        'mvarb': 'MVAR_b',
        'mvarc': 'MVAR_c',
    }

    for column, table in scada_column_to_table.items():
        # Prepare the data for insertion
        col_order = ['unix_time', 'scada_id', column]
        ordered_df = df[col_order]

        data_to_insert = list(
            ordered_df.itertuples(
                index=False,
                name=None,
                )
            )

        # Insert data into the SQLite database using executemany
        col_order[-1] = 'input_value'  # rename to match db schema
        insert_query = f'''
            INSERT INTO {table}
            ({', '.join(col_order)}) VALUES ({', '.join(['?']*len(col_order))})
            '''
        # insert time into table
        execute_many(db_name, insert_query, data_to_insert)


def get_interconnect(db_fp):
    """
    return interconnect table as dataframe
    """
    query = "SELECT * FROM Interconnection"
    return pd_query(db_fp, query)


def infuse_interconnect(db_fp, interconnect_fp):
    """
    Collection of functions to infuse, or insert, interconnect data
    into database
    """
    processed_df = process_interconnect_input(interconnect_fp)
    add_time_to_db(db_fp, processed_df)
    cust_names_ids = add_customers_to_db(db_fp, processed_df, return_ids=True)

    # accomodate for duplicates
    processed_df['customer_id'] = 1  # to violate unique
    for customer_info in cust_names_ids:
        cust_mask = processed_df['name'] == customer_info[0]
        processed_df.loc[cust_mask, 'customer_id'] = customer_info[1]

    add_interconnection_to_db(db_fp, processed_df)


def add_time_to_db(db_name, df):
    """
    adds time to database, assumes schema can be extracted from provided df
    """
    # Prepare the data for insertion
    col_order = ['unix_time', 'utc_time', 'local_time']
    ordered_time_df = df[col_order]

    # only insert unique_times
    ordered_time_df = ordered_time_df.drop_duplicates('unix_time')

    # str type used to avoide passing datetime objects to sql query
    data_to_insert = list(
        ordered_time_df.astype(str).itertuples(
            index=False,
            name=None,
            )
        )

    # Insert data into the SQLite database using executemany
    # The on conflict skips already existing unix entries
    insert_query = f'''
    INSERT INTO Time
    ({', '.join(col_order)}) VALUES ({', '.join(['?']*len(col_order))})
    ON CONFLICT (unix_time) DO NOTHING
    '''

    # insert time into table
    execute_many(db_name, insert_query, data_to_insert)


def get_customer_id(db_name, customer_names):
    """
    return associated ids given customer names.
    Results are in order.
    return none if no customer entry has the provided names
    """
    customer_ids = []
    for customer_name in customer_names:
        select_query = f"""
        SELECT customer_id
        FROM Customer
        WHERE name = '{customer_name}'
        """
        result = execute_query(db_name, select_query, fetch=True)
        if result is not None:
            customer_ids.append(result[0][0])
        else:
            customer_ids.append(None)

    return customer_ids


def add_customers_to_db(db_name, df, return_ids=False):
    """
    adds customer name to database,
    assumes schema can be extracted from provided df
    which expects customer name as 'name'
    """
    # Prepare the data for insertion
    ordered_df = df[['name']]
    ordered_df = ordered_df.drop_duplicates('name')

    # str type used to avoid passing datetime objects to sql query
    data_to_insert = list(
        ordered_df.astype(str).itertuples(
            index=False,
            name=None,
            )
        )

    # Insert data into the SQLite database using executemany
    # skip names that are already entered in the table
    insert_query = """
    INSERT INTO Customer (name)
    VALUES (?)
    ON CONFLICT (name) DO NOTHING;
    """

    # insert time into table
    execute_many(db_name, insert_query, data_to_insert)

    if return_ids:
        customer_names = list(ordered_df['name'])
        customer_ids = get_customer_id(db_name, customer_names)
        customer_tuples = [
            (id, name) for id, name in zip(customer_names, customer_ids)
            ]
        return customer_tuples
    return None


def add_interconnection_to_db(db_name, df):
    """
    adds interconnect data to database,
    ASSERT schema can be extracted from provided df
    """
    # Prepare the data for insertion
    col_order = ['unix_time', 'local_time', 'rated_kva', 'customer_id']
    ordered_df = df[col_order]
    col_order[1] = 'interconnect_date'  # rename data to schema
    # str type used to avoide passing datetime objects to sql query
    data_to_insert = list(
        ordered_df.astype(str).itertuples(
            index=False,
            name=None,
            )
        )

    # Insert data into the SQLite database using executemany
    insert_query = f'''
    INSERT INTO Interconnection
    ({', '.join(col_order)}) VALUES ({', '.join(['?']*len(col_order))})
    '''

    # insert time into table
    execute_many(db_name, insert_query, data_to_insert)

    # TODO: update customer table to has_interconnection = 1


def process_ami_input(ami_fp):
    """
    Read ami file and process raw data into expected format for db.

    ASSERT:
    column headers are ['busname', 'datetime', 'v', 'kw', 'kvar']
    order and capitalization does not batter

    busname corresponds to the AMI customer id or other unique identifier
    datetime has the same input time requirements as AMI
    v is voltage reading
    kw is the kw reading
    kvar is the kvar reading (optional)

    returns pandas dataframe with correctly formatted columns for time and
    interconnect database tables.
    """
    raw_df = pd.read_csv(ami_fp)

    # convert columns to lowercase
    raw_df.columns = raw_df.columns.str.lower()

    # convert column names to match expected name
    req_spec_cols = {
        "v": "v_reading",
        "kvar": "kvar_reading",
        "kw": "kw_reading"
    }
    for current_col, code_col in req_spec_cols.items():
        if current_col in raw_df.columns:
            raw_df.rename(columns={current_col: code_col}, inplace=True)

    df = pd.DataFrame()
    numeric_cols = ['v_reading', 'kw_reading', 'kvar_reading']
    for numeric_col in numeric_cols:
        if numeric_col in raw_df.columns:
            df[numeric_col] = pd.to_numeric(raw_df[numeric_col])

    # NOTE: will require a check later for has_kvar...
    if 'kvar_reading' not in raw_df.columns:
        # handle case where kvar reading is not provided.
        df['kvar_reading'] = np.nan

    time_df = process_time_col(raw_df, 'datetime')

    # NOTE: applying schema, unsure if category casting is still required
    df['name'] = raw_df['busname'].astype('category')

    merged_df = time_df.merge(
        df,
        how='left',
        left_index=True,
        right_index=True,
        )

    return merged_df


def infuse_ami_to_db(db_fp, ami_fp):
    """
    takes ami fp, and handles the data into the database.
    """
    processed_df = process_ami_input(ami_fp)
    add_time_to_db(db_fp, processed_df)

    # initialize customer info into db
    cust_names_ids = add_customers_to_db(
        db_fp,
        processed_df,
        return_ids=True)

    # attach customer id to ami
    # accomodate for duplicates
    processed_df['customer_id'] = 1  # to violate unique
    for customer_info in cust_names_ids:
        if customer_info is None:
            print(cust_names_ids)  # NOTE: This should probably be an error..
        cust_mask = processed_df['name'] == customer_info[0]
        processed_df.loc[cust_mask, 'customer_id'] = customer_info[1]

    add_ami_to_db(db_fp, processed_df)


def add_ami_to_db(db_name, df):
    """
    Add known AMI data columns to database tables.
    Assumes passed in df follows reqs & specs schema
    """
    ami_column_tables = {
        'v_reading': 'Voltage',
        'kw_reading': 'kW',
        'kvar_reading': 'kVAR'
    }

    for column, table in ami_column_tables.items():
        # Prepare the data for insertion
        col_order = ['unix_time', 'customer_id', column]
        ordered_df = df[col_order]

        data_to_insert = list(
            ordered_df.itertuples(
                index=False,
                name=None,
                )
            )

        # Insert data into the SQLite database using executemany
        col_order[-1] = 'input_value'  # rename to match db schema
        insert_query = f'''
            INSERT INTO {table}
            ({', '.join(col_order)}) VALUES ({', '.join(['?']*len(col_order))})
            '''
        # insert time into table
        execute_many(db_name, insert_query, data_to_insert)

        # TODO: update  table to has_{table} = 1


def init_db(db_name):
    """
    Initialize the SQLite database and create tables.
    NOTE: table names should always be SINGULAR

    """
    time_table_definition = """
        CREATE TABLE IF NOT EXISTS Time (
        unix_time INTEGER PRIMARY KEY,
        utc_time TEXT,
        local_time TEXT NOT NULL
    )
    """

    customer_table_definition = """
        CREATE TABLE IF NOT EXISTS Customer (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        has_kw INTEGER,
        has_kvar INTEGER,
        has_voltage INTEGER,
        is_average INTEGER,
        average_duration_sec REAL,
        has_direction INTEGER,
        input_data_quality REAL,
        has_errors INTEGER,
        has_corrections INTEGER,
        corrected_data_quality REAL,
        max_demand REAL,
        min_demand REAL,
        zone_id INTEGER,
        has_interconnect INTEGER,
        mohca_vchc_result REAL
    )
    """
    # foreign keys...
    #    cicuit_id TEXT,
    #    substation_id TEXT,
    #    bus_id TEXT,

    ami_table_names = ['Voltage', 'kW', 'kVAR']
    ami_definitions = []
    for ami_table in ami_table_names:
        ami_definition = f"""
            CREATE TABLE IF NOT EXISTS {ami_table} (
            unix_time INTEGER NOT NULL,
            customer_id INTEGER NOT NULL,
            input_value REAL,
            error_binary_code TEXT,
            correction_binary_code TEXT,
            corrected_value REAL,
            PRIMARY KEY (unix_time, customer_id)
        )
        """
        ami_definitions.append(ami_definition)
    # substation_id

    circuit_table_definition = """
        CREATE TABLE IF NOT EXISTS Circuit (
        circuit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        n_customers INTEGER,
        is_single_file_model INTEGER,
        model_file_name TEXT,
        model_path TEXT,
        model_file_data BLOB
    )
    """

    interconnect_table_definition = """
        CREATE TABLE IF NOT EXISTS Interconnection (
        interconnection_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        unix_time INTEGER NOT NULL,
        interconnect_date DATE NOT NULL,
        rated_kva REAL NOT NULL,
        FOREIGN KEY (unix_time) REFERENCES Time(unix_time),
        FOREIGN KEY (customer_id) REFERENCES Customer(customer_id)
    )
    """

    scada_stream_table_definition = """
        CREATE TABLE IF NOT EXISTS SCADA_Stream (
        scada_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        bus TEXT NOT NULL,
        element TEXT,
        is_average INTEGER,
        average_duration_sec REAL,
        has_direction INTEGER,
        unit TEXT
    )
    """

    scada_table_names = [
        'kV_a', 'kV_b', 'kV_c',
        'MW_a', 'MW_b', 'MW_c',
        'MVAR_a', 'MVAR_b', 'MVAR_c',
        ]
    scada_definitions = []
    for scada_table in scada_table_names:
        scada_definition = f"""
            CREATE TABLE IF NOT EXISTS {scada_table} (
            unix_time INTEGER NOT NULL,
            scada_id INTEGER NOT NULL,
            input_value REAL,
            error_binary_code TEXT,
            correction_binary_code TEXT,
            corrected_value REAL,
            PRIMARY KEY (unix_time, scada_id)
        )
        """
        scada_definitions.append(scada_definition)

    init_commands = [
        time_table_definition,
        customer_table_definition,
        interconnect_table_definition,
        circuit_table_definition,
        scada_stream_table_definition,
    ]

    init_commands.extend(ami_definitions)
    init_commands.extend(scada_definitions)

    for command in init_commands:
        execute_query(db_name, command)


def insert_circuit_model(
        db_name,
        model_fp,
        model_name='UNNAMED_CKT',
        is_single_file_model=1,
        ):
    """
    Insert a circuit model into the database.
    has_model, default = 1, assumes single file circuit,
    if has_model is 0, then model path is more 
    """

    with open(model_fp, 'rb') as file:
        model_data = file.read()
        insert_query = '''
            INSERT INTO Circuit (
                name,
                is_single_file_model,
                model_file_name,
                model_path,
                model_file_data
            ) VALUES(?, ?, ?, ?, ?)
        '''
        params = (
            model_name,
            is_single_file_model,
            model_fp.name,
            str(model_fp),
            model_data,
            )
        execute_query(db_name, insert_query, params)


def retrieve_circuit_model(db_name, circuit_id=1, output_fp=None):
    """
    If circuit is single file model:
        Retrieve a ZIP model file from the database 
        save it to output_fp,
        return output_fp
    else cicuit is just a filepath:
        retrieve file path from database
        return file path
    """
    select_query = '''
        SELECT is_single_file_model FROM Circuit WHERE circuit_id = ?
    '''
    params = (circuit_id,)
    result = execute_query(db_name, select_query, params, fetch=True)
    is_single_file_model = result[0][0]

    if is_single_file_model == 1:
        select_query = '''
            SELECT model_file_data FROM Circuit WHERE circuit_id = ?
        '''
        params = (circuit_id,)
        result = execute_query(db_name, select_query, params, fetch=True)

        if result:
            filedata = result[0][0]  # Get the BLOB data
            with open(output_fp, 'wb') as file:
                file.write(filedata)
            # print(f"'{output_fp}' has been retrieved successfully.")
        else:
            print('No Result')
        return Path(output_fp)

    else:
        select_query = '''
            SELECT model_path FROM Circuit WHERE circuit_id = ?
        '''
        params = (circuit_id,)

        result = execute_query(db_name, select_query, params, fetch=True)
        ckt_fp = result[0][0]   # result is list of tuples
        return Path(ckt_fp)

def get_ami(
        db_fp,
        ami_dict=None,
        t_step=None,
        ):
    """
    Returns requested AMI as defined in the ami_dict
    if none, simply returns all default ami (p, q, v)

    which, as of now, is a dictionary describing:
    'cust': a single, group, all
    'unit': related to data types
    'kind': raw, fixed, best
    't_range': time wise, individual, select, range, all

    also, account for consistent t_step
    if none: any
    if integer - select that as time_step
    """
    base_ami_dict = {
        'cust': None,
        'unit': ['kW', 'kVAR', 'Voltage'],
        'kind': 'best',
        't_range': None
        }

    # ensure ami_dict is fully defined
    if ami_dict is None:
        ami_dict = base_ami_dict
    else:
        for key, base_value in base_ami_dict.items():
            if key not in ami_dict:
                ami_dict[key] = base_value

    # TODO: additional handling of units?
    unit_tables = ami_dict['unit']

    # get ami time selection
    # if ami_dict['t_range'] is None:  # For future handling of time selection
    combined_time = _get_combined_time_df(db_fp, unit_tables)

    # rename and index correction
    # TODO: place for additional time selection
    ami_time = combined_time.reset_index(drop=True)  # for later processing

    # get customers to select
    cust_df = _get_ami_cust_df(db_fp, ami_dict['cust'])

    ami_results = _get_ami_dfs(db_fp, unit_tables, ami_time, cust_df)

    return ami_results


def _get_ami_cust_df(db_fp, cust=None):
    """
    retrieve customer df for ami collection based on ami_dict cust value
    """
    if cust is None:
        # select all customer ids
        query = "SELECT customer_id, name FROM Customer"
        cust_df = pd_query(db_fp, query)
    elif isinstance(cust, list):
        cust_str = ', '.join(f"'{s}'" for s in cust)
        query = f"""
            SELECT customer_id, name
            FROM Customer
            WHERE name IN ({cust_str})
            """
        cust_df = pd_query(db_fp, query)
    else:
        # customer is single string
        query = f"""
            SELECT customer_id, name
            FROM Customer
            WHERE name = '{cust}'
            """
        cust_df = pd_query(db_fp, query)

    return cust_df


def _get_ami_dfs(db_fp, unit_tables, ami_time, cust_df):
    """
    retrive unit tables from database
    """
    ami_results = {}

    # for each requested table
    for unit_table in unit_tables:
        # init result df
        ami_results[unit_table] = ami_time.set_index('unix_time')

        unit_results = {}

        # for each customer, qurry db and format result
        for _, row in cust_df.iterrows():
            cust_id = row['customer_id']
            cust_name = row['name']
            query = f"""
                SELECT unix_time, input_value
                FROM {unit_table}
                WHERE customer_id = {cust_id}
                """
            unit_result = pd_query(db_fp, query)
            unit_result.set_index('unix_time', inplace=True)

            unit_results[cust_name] = unit_result

        # combine customer results into unit df
        for cust_name, unit_result in unit_results.items():
            ami_results[unit_table] = pd.merge(
                left=ami_results[unit_table],
                right=unit_result.rename(columns={'input_value': cust_name}),
                how='left',
                left_index=True,
                right_index=True
            )

    return ami_results


def _get_combined_time_df(db_fp, unit_tables):
    """
    retrive unix time from database for specific tables

    This may be different from just selecting all time from time table
    """
    data_time_indices = []
    for unit in unit_tables:
        query = f"SELECT unix_time FROM {unit}"
        result = pd_query(db_fp, query)
        data_time_indices.append(result)
    combined_time = pd.concat(data_time_indices)
    combined_time.drop_duplicates(inplace=True)

    return combined_time


def get_scada(
        db_fp,
        scada_dict=None,
        t_step=None,
        ):
    """
    return dictionary of dataframes of scada data
    """
    base_scada_dict = {
        'stream': None,
        'unit': [
            'MW_a','MW_b','MW_c',
            'MVAR_a','MVAR_b','MVAR_c',
            'kV_a','kV_b','kV_c',
            ],
        'kind': 'best',
        't_range': None
    }
    # ensure scada_dict is fully defined
    if scada_dict is None:
        scada_dict = base_scada_dict
    else:
        for key, base_value in base_scada_dict.items():
            if key not in scada_dict:
                scada_dict[key] = base_value

    unit_tables = scada_dict['unit']

    #  if scada_dict['t_range'] is None:  #  for future time selection
    combined_time = _get_combined_time_df(db_fp, unit_tables)

    # rename and index correction
    # TODO: place for additional time selection
    scada_time = combined_time.reset_index(drop=True)  # for later processing

    scada_stream_df = _get_scada_stream_df(
        db_fp,
        stream=scada_dict['stream'],
        )
    scada_results = _get_scada_dfs(
        db_fp,
        unit_tables,
        scada_time,
        scada_stream_df)

    return scada_results


def _get_scada_stream_df(db_fp, stream=None):
    """
    retrieve scada stream df for scada collection based on stream value
    default behavior to return all stream ids and names
    will accept single string of scada name, or list of scada names
    """
    if stream is None:
        # select all customer ids
        query = "SELECT scada_id, name FROM SCADA_Stream"

    elif isinstance(stream, list):
        stream_str = ', '.join(f"'{s}'" for s in stream)
        query = f"""
            SELECT scada_id, name
            FROM SCADA_Stream
            WHERE name IN ({stream_str})
            """

    else:
        # customer is single string
        query = f"""
            SELECT scada_id, name
            FROM SCADA_Stream
            WHERE name = '{stream}'
            """

    return pd_query(db_fp, query)


def _get_scada_dfs(db_fp, unit_tables, scada_time, scada_stream_df):
    """
    retrive unit tables from database
    """
    scada_results = {}

    # for each requested table
    for unit_table in unit_tables:
        # init result df
        scada_results[unit_table] = scada_time.set_index('unix_time')

        unit_results = {}

        # for each scada stream, qurry db and format result
        for _, row in scada_stream_df.iterrows():
            scada_id = row['scada_id']
            scada_name = row['name']
            query = f"""
                SELECT unix_time, input_value
                FROM {unit_table}
                WHERE scada_id = {scada_id}
                """
            unit_result = pd_query(db_fp, query)
            unit_result.set_index('unix_time', inplace=True)

            unit_results[scada_name] = unit_result

        # combine scada stream results into unit df
        for scada_name, unit_result in unit_results.items():
            scada_results[unit_table] = pd.merge(
                left=scada_results[unit_table],
                right=unit_result.rename(columns={'input_value': scada_name}),
                how='left',
                left_index=True,
                right_index=True
            )

    return scada_results
