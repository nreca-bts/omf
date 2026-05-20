## Tests
Every .py file shall define a _tests() function. When that file is executed from the command line (e.g. ```python /omf/omf/feeder.py```) the tests shall execute.

To run all the tests in the project, ```python /omf/omf/runAllTests.py```

We run all tests on every commit using github actions. **If the build breaks, the code must be fixed or the changes rolled back within 24 hours**.

## Coding Style Guide

1. Spaces or tabs? Tabs.
2. Single quotes or double? Single.
3. Module, function, class, etc. names? camelCase for all names. InitialCapsCase for class names.
4. Zero trailing spaces.
5. Every function, module and class needs a docstring inside triple quotes.
6. Remove the #!/bin/python because nobody's running this stuff as shell scripts.
7. Use unicode literals e.g. & # x2192; instead of →.
8. Variable name lengths? Aim for shorter. Do not use uncommon abbreviations. This is tricky and a judgment call.
Then document the conventions and clean up the code to match them.
9. Indenting dictionaries or long lists? See longDict below.
10. Nesting functions: try not to do it. This is tricky and a judgment call.

```python
longDict = {
    'item':3,
    'other': {
        'x':3
        'z':2 },
    ...
    'end':6 }
```

## System Architecture

**/omf/** - Packaging and installation files.

**/omf/omf/** - Libraries used across multiple modules. Weather, geospatial, load modeling, forecasting, circuit conversion, etc.

**/omf/web.py** - The web server code. Each function maps a url (e.g. omf.coop/listAnalayses) to python code that generates the result.

**/omf/omf/templates** - HTML templates for shared interfaces e.g. the home screen, the login screen, the circuit editor.

**/omf/omf/static** - Static files served by the web server, test files, CSS, and javascript libraries.

**/omf/solvers/** - Python libraries to execute different models. As on 7 Mar 2019 includes NREL's SAM, PNNL's Gridlab-D, Cornell's MATPOWER, and 6 other lesser-known solvers. We also keep binaries for the models in here so we know exactly what code we executed to get what results.

**/omf/scratch/** - Prototypes and tests for future development.

**/omf/data/** - The main OMF data store. Feeders, users, weather, saved model results, etc., etc. Each data objects is typically a .json file.

**/omf/models/** - Code for each of the models built on top of the framework. Each model is defined in a pair of files: one .html for the frontend, and one .py for the backend.