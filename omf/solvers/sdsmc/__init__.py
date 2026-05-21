"""
Package Sandia distribution-system model-calibration algorithms for phase identification
and transformer pairing.
"""

if __package__ in [None, '']:
    import MeterTransformerPairing
    import PhaseIdentification
else:
    from . import MeterTransformerPairing
    from . import PhaseIdentification

def _run_all_tests():
    """
    Internal helper for run all tests processing.
    """
    pass #TODO: maybe add code to test each of the submodules here? I.e. just call some of the functions in the submodules on the existing sample data to make sure they don't crash.
