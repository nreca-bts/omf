import argparse
from pathlib import Path

# OMF imports
from omf.solvers.opendss.dssConvert import dssToTree
from omf.solvers.opendss.dssConvert import _treeToDss_toBeTested as treeToDss
from omf.solvers.opendss.__init__ import reduceCircuit

def dssFile(pathStr: str) -> str:
    '''
    Validate that the provided path is a valid .dss file.
    
    :param pathStr: Path to the .dss file
    :type pathStr: str
    :return: Validated path to the .dss file
    :rtype: str
    '''
    path = Path(pathStr)
    if not path.exists():
        raise argparse.ArgumentTypeError("file does not exist")
    if path.suffix.lower() != ".dss":
        raise argparse.ArgumentTypeError("file must be a .dss file")
    return pathStr

def main(dssFileName: str):
    '''
    Reduce the feeder from the given dss file and save the reduced feeder to a new dss file.

    :param dssFileName: Path to the .dss file
    :type dssFileName: str
    '''
    tree = dssToTree(dssFileName)
    oldsz = len(tree)
    tree = reduceCircuit(tree)
    newsz = len(tree)
    cutsz = oldsz-newsz
    treeToDss(tree, dssFileName.replace('.dss', '_reduced.dss'))
    print(f'\nPerformed feeder reduction, reducing the size of the feeder by {cutsz} objects (oldsz={oldsz}, newsz={newsz})')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Simplify openDSS circuit models to smaller but electrically-equivalent versions. For more information, visit \n https://github.com/nreca-bts/omf/wiki/Other-~-modelReduction"
    )
    parser.add_argument(
        "dssFileName",
        type=dssFile,
        help="Path to the .dss file to be reduced.",
    )
    args = parser.parse_args()
    main(args.dssFileName)

