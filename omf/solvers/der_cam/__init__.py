"""
Wrap DER-CAM spreadsheet and API workflows for distributed-energy-resource optimization
studies.
"""

import os, time, json
import shutil
import pandas, openpyxl
import requests as req

urlBase = 'https://microgrids1.lbl.gov:4000/api/xls' 
fileMimeType = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
DER_CAM_API_KEY_ENV = 'DER_CAM_API_KEY'

lock_file = "lock_file.txt"

thisDir = os.path.abspath(os.path.dirname(__file__))

def set_credentials(apiKey=""):
    '''Set the DER-CAM API key for the current process. Prefer setting DER_CAM_API_KEY in the environment.'''
    if apiKey == "":
        raise ValueError(
            f"DER-CAM API key required. Set {DER_CAM_API_KEY_ENV} or pass apiKey explicitly."
        )
    os.environ[DER_CAM_API_KEY_ENV] = apiKey
    return apiKey

def get_credentials():
    '''Return the DER-CAM API key from the environment.'''
    userKey = os.environ.get(DER_CAM_API_KEY_ENV)
    if not userKey:
        raise ValueError(
            f"DER-CAM API key required. Set {DER_CAM_API_KEY_ENV} or pass apiKey explicitly."
        )
    return userKey

def testfile_path(fileName):
    ''' returns file path to the given file within testFiles folder '''
    return os.path.normpath(os.path.join(thisDir,"testFiles",fileName))

def check_for_existing_file( der_cam_file ):
    ''' removes previous der_cam input file '''
    if os.path.exists( der_cam_file ):
        os.remove( der_cam_file )

def generate_load_template( path, reopt_file_path ):
    ''' work in progress: generates file with week/weekend/peak loads for der-cam input file '''
    with open(reopt_file_path) as j:
        input_json = json.load(j)

    el = input_json.get("ElectricLoad",None)
    year = el.get("year",0)
    critical_load_fraction = el.get("critical_load_fraction", 0)
    loads = el.get("loads_kw",[])

    #generating load sheets
    load_template_file = testfile_path("der-cam-data-processing-template.xlsx")
    load_template_workbook = openpyxl.load_workbook(load_template_file) #used for writing excel sheets
    load_template = load_template_workbook["1h_TS"]

    #todo: if loads_kw not given => pull in data from load_path
    percentileCol = openpyxl.utils.column_index_from_string('M')
    loadsCol = openpyxl.utils.column_index_from_string('G')

    load_template.cell(row=6, column=1).value = f"{year}-01-01"
    load_template.cell(row=3, column=percentileCol).value = round(critical_load_fraction,2)

    #inputting loads_kw data into template excel sheet
    for i in range(3,load_template.max_row):
        load_template.cell(row=i, column=loadsCol).value = round(float(loads[i-3]),2)

    load_template.cell(row=8, column=1).value = load_template.cell(row=8, column=1).value

    #attempting to make results calculate in sheet 
    '''
    for col in range(startCol, endCol+1):
        for row in range(7,19):
            load_template.cell(row=row,column=col).value = load_template.cell(row=row,column=col).value
        for row in range(22,34):
            load_template.cell(row=row,column=col).value = load_template.cell(row=row,column=col).value
        for row in range(37,49):
            load_template.cell(row=row,column=col).value = load_template.cell(row=row,column=col).value
    '''

    #writing to new template results excel sheet
    template_result_path = os.path.normpath(os.path.join(path,"template_results.xlsx"))
    load_template_workbook.save(template_result_path)

def pull_loads( template_result_path ):
    ''' work in progress: pulls week/weekly/peak loads from pre-populated load template sheet '''
    load_results_workbook = openpyxl.load_workbook(template_result_path, read_only=True)
    load_results = load_results_workbook["1h_TS"]
    
    startCol = openpyxl.utils.column_index_from_string('J')
    endCol = openpyxl.utils.column_index_from_string('AG')
    #note: not working currently unless Excel file was manually opened => python libraries unable to compute formulas
    peak_profile = []
    for row in range(7,19):
        new_row = []
        for col in range(startCol, endCol+1):
            new_row.append(load_results.cell(row=row,column=col).value)
        peak_profile.append(new_row)
    #print(f'peak profile: {peak_profile}')
    week_profile = []
    for row in range(22,34):
        new_row = []
        for col in range(startCol,endCol+1):
            new_row.append(load_results.cell(row=row,column=col).value)
        week_profile.append(new_row)
    #print(f'week profile: {week_profile}')
    weekend_profile = []
    for row in range(37,49):
        new_row = []
        for col in range(startCol,endCol+1):
            new_row.append(load_results.cell(row=row,column=col).value)
        weekend_profile.append(new_row)
    #print(f'weekend profile: {weekend_profile}')
    return peak_profile, week_profile, weekend_profile


def build_input_spreadsheet(path, reopt_input_file, der_cam_file_name, loadTemplate=""):
    ### work in progress
    '''builds file input for der-cam api given REopt input json'''

    reopt_file_path = os.path.normpath(os.path.join(path,reopt_input_file))
    der_cam_file_path = os.path.normpath(os.path.join(path,der_cam_file_name))

    #load default der-cam excel input (test.xlsx)
    base_file = testfile_path("test2.xlsx") #was test.xlsx
    xls = pandas.ExcelFile(base_file)
    sheets = xls.sheet_names

    #load reopt input file (reopt_input_file -> input_json)
    with open(reopt_file_path) as j:
        input_json = json.load(j)

    financial = input_json.get("Financial",None)
    pv = input_json.get("PV",None)
    wind = input_json.get("Wind",None)
    es = input_json.get("ElectricStorage",None)
    generator = input_json.get("Generator",None)

    if loadTemplate != "":
        #template_result_path = generate_load_template(path, reopt_file_path) 
        template_result_path = os.path.normpath(os.path.join(path,"template_results.xlsx"))
        peak_profile, week_profile, weekend_profile = pull_loads(template_result_path)

    check_for_existing_file(der_cam_file_path)
    create_new_file = True

    #sets relevant DER capacities based on reopt inputs 
    def set_invest(df, tech, min, existing, max):
        #for min_kw <= max_kw & existing_kw <= max_kw (todo: input checking for user interface portion)
        if existing > 0:
            df.at[tech,"FixedInvest"] = 0
            df.at[tech,"ForcedInvestCapacity"] = existing
            df.at[tech,"ExistingYN"] = 1
        elif min > 0:
            df.at[tech, "FixedInvest"] = 0
            df.at[tech,"ForcedInvestCapacity"] = min
        elif max > 0:
            df.at[tech,"FixedInvest"] = 0
        return df

    #save each sheet to new der-cam excel input file (der_cam_file_name)
    #with replacements based on relevant reopt input values
    for sheet in sheets:
        hasIndex = True
        hasHeader = False
        if sheet == "FinancialSettings":
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["DiscRate",df.columns[0]] = financial.get("offtaker_discount_rate_fraction")
            df.at["MaxPaybackPeriod",df.columns[0]] = financial.get("analysis_years")

        if sheet == "GeneralReliabilityParams":
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["VOLL",df.columns[0]] = financial.get("value_of_lost_load_per_kwh")

        if sheet == "SolarCostParameters" and pv != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["PV","VariableCost"] = pv.get("installed_cost_per_kw")
            df.at["PV","Lifetime"] = pv.get("macrs_option_years")

        if sheet == "SolarInvestParameters" and pv != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            #hasHeader = True
            df = set_invest(df, "PV", pv.get("min_kw"), pv.get("existing_kw"), pv.get("max_kw"))

        if sheet == "PowerExportOptions" and pv != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            can_export = int(pv.get("can_export_beyond_nem_limit"))
            df.at["NetMetering",df.columns[0]] = can_export 
            df.at["RenewableExport",df.columns[0]] = can_export

        if sheet == "GeneralTechConstrains" and pv != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["allowPVCurtailment",df.columns[0]] = int(pv.get("can_curtail"))

        if sheet == "WindGeneratorPar" and wind != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["WindRateCapacity",df.columns[0]] = 50 #using fixed capacity per wind generator unit for calculation purposes
            df.at["WindCapitalCost",df.columns[0]] = 50 * wind.get("installed_cost_per_kw")
            df.at["WindLifeTime",df.columns[0]] = wind.get("macrs_option_years")

        if sheet == "WindGeneratorForcedInvest" and wind != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df = set_invest(df, "node1", wind.get("min_kw"), 0, wind.get("max_kw"))

        if sheet == "StorageCostParameters" and es != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            hasHeader = True
            df.at["ElectricStorage","VariableCost"] = es.get("installed_cost_per_kw")
            #df.at["ElectricStorage","VariableOM"] = electricStorage.get("replace_cost_per_kwh") * 24 * 30
            df.at["ElectricStorage","Lifetime"] = es.get("battery_replacement_year")
            #df.at["maxs"] = electricStorage.get("max_kw") / 2000
            #df.at["capcost"] = electricStorage.get("replace_cost_per_kw")

        if sheet == "StorageInvestParameters" and es != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            #hasHeader = True
            df = set_invest(df, "ElectricStorage",es.get("min_kw"),0,es.get("max_kw"))

        if sheet == "BattInverterParameters" and es != None:
            #choosing 2000kw inverter type to update (temporary)
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            hasHeader = True
            df.at["BattInverter_2000kw","Lifetime"] = es.get("inverter_replacement_year")

        if sheet == "ElecStorageStationaryParameter" and es != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None, index_col=0)
            df.at["DiscreteSize",df.columns[0]] = es.get("max_kwh")

        if sheet == "LFGenSetOPT" and generator != None:
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            df.at["LFGS01","capcost"] = generator.get("installed_cost_per_kw")
            df.at["LFGS01","OMFix"] = generator.get("om_cost_per_kw")
            df.at["LFGS01","lifetime"] = generator.get("macrs_option_years")
            df.at["LFGS01","BackupOnly"] = int(generator.get("only_runs_during_grid_outage"))
            df.at["LFGS01","Fuel"] = 4
            df.at["LFGS01","Type"] = 3

        if sheet == "EnableInvestment":
            df = pandas.read_excel(base_file, sheet_name=sheet, index_col=0)
            hasHeader = True
            df.at["node1","GenSetInvest"] = int(generator != None)
            df.at["node1","SolarInvest"] = int(pv != None)
            df.at["node1","StorageInvest"] = int(es != None)
            df.at["node1","WindInvest"] = int(wind != None)

        if sheet == "LoadInput_N1_P":
            df = pandas.read_excel(base_file, sheet_name=sheet)
            hasIndex = False
            hasHeader = True
            start_col = openpyxl.utils.column_index_from_string('D') - 1
            end_col = openpyxl.utils.column_index_from_string('AA') - 1
            if loadTemplate != "":
                df.iloc[0:12, start_col:end_col] = week_profile.values
                df.iloc[12:24, start_col:end_col] = peak_profile.values
                df.iloc[24:36, start_col:end_col] = weekend_profile.values
            df.iloc[36:216, start_col:end_col] = 0 #setting all other loads (refrigeration, cooling, etc) to 0

        else:
            df = pandas.read_excel(base_file, sheet_name=sheet, header=None)
            hasIndex = False

        if create_new_file:
            df.to_excel(der_cam_file_path, sheet_name=sheet, index=hasIndex, header=hasHeader)
            create_new_file = False
        else:
            with pandas.ExcelWriter(der_cam_file_path, mode='a') as writer:
                df.to_excel(writer, sheet_name=sheet, index=hasIndex, header=hasHeader)

    print(f"successfully created der-cam input at {path}/{der_cam_file_name}")

#######################################################################
### functions for posting model to API and checking for model results
#######################################################################

def check_timeout(start_time, timeout):
    """
    Perform check timeout processing for the wrapped solver workflow.
    """
    if timeout != 0:
        current_time = time.time()
        if current_time - start_time >= timeout:
            return True
    return False

def check_lock(lock_path, timeout):
    ''' checks if another API call is running and prints statement if so '''
    printed = False
    current_time = time.time()
    while os.path.exists(lock_path):
        if not printed:
            print("30 second wait required between DER-CAM API calls - waiting ...")
            printed = True
        if check_timeout(current_time, 30):
            print("30 seconds have passed: an error may be causing the lock file to not be released correctly")
        if check_timeout(current_time, timeout):
            print(f"error: timeout of {timeout} seconds reached while waiting for lock file to release")
            return 

def release_lock(start_time, lock_path):
    ''' waits for up to 30 seconds before releasing API lock to ensure that API limits are followed '''
    end_time = time.time()
    sleep_time = 30 - ( end_time - start_time )
    if sleep_time > 0:
        print(f'sleeping for {sleep_time} seconds')
        time.sleep(sleep_time)
    os.remove(lock_path)
    print("lock released")

def check_model_status( modelKey, userKey ):
    ''' checks status of posted model '''
    urlKey = f'{urlBase}/{userKey}/model/{modelKey}'
    response = req.get(urlKey)
    model = response.json()['model']
    return model['results_available'], model['status'], model['msg']

def get_model_results( modelKey, userKey, modelHasResults ):
    ''' accesses available results '''
    if modelHasResults == 1:
        urlResults = f'{urlBase}/{userKey}/model/{modelKey}/results'
        resultsResponse =  req.get(urlResults)
        return resultsResponse.json()['model']
    else:
        print(f"error: model results for key {modelKey} were not posted")

#todo: remove any print statements that aren't useful to the user
def solve_model(path, modelFile, apiKey="", timeout=0): 
    ''' 
    posts model file to DER-CAM API, waits to receive results, saves results 
    to {path}/results.csv, and ensures minimum runtime of 30 seconds per call (API limit)
    '''
    userKey = apiKey if apiKey != "" else get_credentials()

    modelFilePath = os.path.normpath(os.path.join(path, modelFile))
    files = {'modelFile': ('model.xlsx', open(modelFilePath, 'rb'), fileMimeType, {'Expires': '0'})}
    urlRequest = f'{urlBase}/{userKey}/model'
    data={ 'label': "example model post request", 'version': 5.9 }
    
    lock_path = os.path.normpath(os.path.join(thisDir,lock_file))
    check_lock(lock_path,timeout)
    
    start_time = time.time()
    modelKey = None
    try:
        if not os.path.exists(lock_path):
            with open(lock_path, 'w') as f:
                f.write(str(os.getpid()))
                print(f"lock acquired at: {lock_path}")
            #posts model to API
            response = req.post(url=urlRequest, data=data, files=files)
            
            modelResponse = response.json()['model']
            #acquires key for given model
            modelKey = modelResponse['model_key']

            modelHasResults, modelStatus, modelMsg = check_model_status( modelKey, userKey )
            if modelStatus == "failed":
                release_lock(start_time, lock_path)
                print(f"error: {modelMsg}")
                return 

            #waits for model to solve
            while modelHasResults != 1:
                #add waiting period between checks? (doesn't seem to have limits on requests, only posting models)
                modelHasResults, modelStatus, modelMsg = check_model_status( modelKey, userKey )
                if modelStatus == "failed":
                    release_lock(start_time, lock_path)
                    print(f"error: {modelMsg}")
                    return
                if check_timeout(start_time, timeout):
                    release_lock(start_time, lock_path)
                    print(f"error: timeout of {timeout} seconds reached while waiting for model results")
                    print(f"results available: {modelHasResults}, status: {modelStatus}, msg: {modelMsg}")
                    return 

            solvedModel = get_model_results( modelKey, userKey, modelHasResults )
            
            #todo: add optional function inputs for output file names
            with open(os.path.normpath(os.path.join(path,"results.csv")), 'w') as f:
                f.write(solvedModel['results'])
                
            #with open(os.path.normpath(os.path.join(path,"results_nodes.csv")), 'w') as f:
            #    f.write(solvedModel['resultsNodes'])

            print(f'model competed: results saved to {path}/results.csv') #and {path}/resultsNodes.csv')
            
            release_lock(start_time, lock_path)
    except Exception as e:
        print(f'Exception occured during der_cam solve_model : {e}')
        release_lock(start_time,lock_path)
        
    return modelKey

def print_existing_models():
    ''' prints all existing models saved to the account associated with the specified API key '''
    userKey = get_credentials()
    response = req.get(f'{urlBase}/{userKey}/model')
    myModels = response.json()['models']
    print("existing models: ")
    print(myModels)


def print_model( modelKey ):
    ''' prints results from the model with the given model API key if it exists in the users account '''
    userKey = get_credentials()
    modelHasResults, modelStatus, modelMsg = check_model_status( modelKey, userKey )
    print(f'(for testing) results = {modelHasResults}, status = {modelStatus}, msg = {modelMsg}')
    if modelHasResults != 1:
        print(f'error: modelStatus = {modelStatus} : modelMsg = {modelMsg}')
    else:
        solvedModel = get_model_results( modelKey, userKey, modelHasResults )
        print(f'solvedModel => {solvedModel}')

def run(path, modelFile="", reoptFile="", apiKey="", loadTemplate="", timeout=0):
    ''' 
    if reoptFile provided (json) : translates to der-cam input sheet and solves model 
    if modelFile provided (xlsx) : solves given modelFile
    '''
    if modelFile == "" and reoptFile == "":
        return "error: enter modelFile and/or reoptFile to translate into modelFile"
    elif modelFile == "":
        build_input_spreadsheet(path, reoptFile, "der_cam_inputs.xlsx", loadTemplate=loadTemplate)
        modelFile = "der_cam_inputs.xlsx"
    modelKey = solve_model(path, modelFile, apiKey=apiKey, timeout=timeout)
    return modelKey


def _test():
    """
    Run this module's local smoke tests or debugging workflow.
    """
    modelKey = run(os.path.normpath(os.path.join(thisDir,"testFiles")), modelFile="test.xlsx")
    print_model( modelKey )

if __name__ == "__main__":
    _test()
