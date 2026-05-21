mmm.solvers.der-cam

Solver for Lawrence Berkeley National Laboratory (LBNL) DER-CAM API

Before running:
- acquire an API key : request a DER-CAM account here: https://dercam-app.lbl.gov/
- set the API key in the environment: `export DER_CAM_API_KEY=...`
  - alternatively, pass `apiKey` directly to `run(...)`

# Functions (WIP)
`__init__.py`
```
>> run ( path, modelFile="", reoptFile="", apiKey="", timeout=0 )

>> print_existing_models ( userKey )
```

# Input options:

- modelFile : single-node or multi-node input (Excel file)
- reoptFile : REopt.jl input (json file) -> Scenario_test_POST.json

# Outputs:

- results.csv
- results-nodes.csv 
