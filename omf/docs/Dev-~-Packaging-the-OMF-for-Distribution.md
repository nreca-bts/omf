### Packaging OMF

OMF uses standard Python project metadata in `pyproject.toml`.

To install OMF from a checkout:

```bash
python -m pip install -e .
```

To install directly from GitHub:

```bash
python -m pip install git+https://github.com/nreca-bts/omf
```

Optional machine-learning workflows use TensorFlow. Install those dependencies with:

```bash
python -m pip install ".[ml]"
```

Package data is configured in `pyproject.toml` under `tool.setuptools.package-data`
and `tool.setuptools.exclude-package-data`. Keep those rules broad enough to include
model templates, static assets, and bundled solver resources, but exclude generated
or local-only folders such as `omf/scratch`, `omf/build`, and `omf/dist`.

To build a local wheel for inspection:

```bash
python -m pip wheel --no-deps -w dist .
```

To uninstall:

```bash
python -m pip uninstall omf
```
