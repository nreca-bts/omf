"""Exercise a basic OMF model and a small OpenDSS circuit after installation."""

from omf.models import modelSkeleton
from omf.solvers import opendss


def check_model():
    result = modelSkeleton.work(None, {'input1': '2', 'input2': '3'})
    assert result['output'] == '5', result


def check_opendss():
    opendss.runDssCommand('clear', strict=True)
    opendss.runDssCommand('new circuit.smoke basekv=12.47 bus1=source', strict=True)
    opendss.runDssCommand('new load.smoke bus1=source phases=3 kv=12.47 kw=30', strict=True)
    opendss.runDssCommand('solve', strict=True)
    assert opendss.dss.Solution.Converged(), 'OpenDSS smoke circuit did not converge'
    assert opendss.dss.Circuit.NumBuses() == 1


if __name__ == '__main__':
    check_model()
    check_opendss()
    print('OMF model and OpenDSS smoke tests passed')
