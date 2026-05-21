"""
Install and run the protection-settings optimization solver used by OMF protection
studies.
"""

import os, sys
import platform

thisDir = os.path.abspath(os.path.dirname(__file__))


def install_pso(system : list = platform.system()):
    ''' installs dependency for protsetopt'''
    instantiated_path = os.path.normpath(os.path.join(thisDir,"instantiated.txt"))
    if not os.path.isfile(instantiated_path):
        try:
            os.system(f"{sys.executable} -m pip install -e git+https://github.com/lilycatolson/Protection-settings-optimizer.git#egg=RSO_pack")
            if system == "Windows":
                os.system(f'copy nul {instantiated_path}')
            else:
                os.system(f'touch "{instantiated_path}"')
            print(f'protsetopt installed - to reinstall remove file: {thisDir}/instantiated.txt')
        except Exception as e:
            print(e)
            print("error - unable to install protsetopt")


def run_pso(testPath, testFile, Fres=['0.001','1'], Fts=['3ph','SLG','LL'], Force_NOIBR = 1, enableIT = 0, CTI = 0.25, OTmax = 10,
        type_select = False, Fault_Res = ['R0_001','R1'], Min_Ip = [0.1,0.1], Substation_bus = 'sourcebus'):
    ''' run ProtectionSettingsOptimizer with OpenDSS '''
    install_pso()
    try:
        import RSO_pack
    except (ImportError, ModuleNotFoundError):
        from . import RSO_pack

    RSO_pack.run(testPath, testFile, Fres=Fres, Fts=Fts, Force_NOIBR = Force_NOIBR, enableIT = enableIT, CTI = CTI, OTmax = OTmax, 
                 type_select = type_select, Fault_Res = Fault_Res, Min_Ip = Min_Ip, Substation_bus = Substation_bus)

def _test():
    """
    Run this module's local smoke tests or debugging workflow.
    """
    testPath = os.path.normpath(os.path.join(thisDir, 'testFiles'))
    testFile = 'IEEE34Test.dss'
    run_pso(testPath, testFile)

if __name__ == "__main__":
    _test()
