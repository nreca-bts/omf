# Installation Instructions

Install OMF from GitHub in a Python environment with Git available. The integration tests use Python 3.11 on Ubuntu 24.04.

```bash
python -m pip install 'git+https://github.com/nreca-bts/omf'
```

To run the integration suite from that environment, use the same command as CI.

```bash
python -m omf.runAllTests
```

The repository also provides an [OMF Dockerfile](https://github.com/nreca-bts/omf/blob/master/omf.dockerfile). The hosted version is available at [omf.coop](https://omf.coop/).
