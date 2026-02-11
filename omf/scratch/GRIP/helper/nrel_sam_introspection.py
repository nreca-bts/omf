# https://sam.nrel.gov/images/web_page_files/ssc_guide.pdf#subsection.3.4

''' As of January 2026 - nrelsam2013 is removed from the OMF. Please use PySAM'''


import omf.solvers.nrelsam2013 as sam # This import takes a long time (15 seconds)


def inspect_pvwattsv1():
    '''
    In the GRIP API we only use the pvwattsv1 module
    '''
    ssc = sam.SSCAPI()
    pv = ssc.ssc_module_create("pvwattsv1")
    idx = 0
    pv_var = ssc.ssc_module_var_info(pv, idx)
    while (pv_var is not None):
        print('Name: {}'.format(ssc.ssc_info_name(pv_var)))
        print('Label: {}'.format(ssc.ssc_info_label(pv_var)))
        print('Units: {}'.format(ssc.ssc_info_units(pv_var)))
        print('Meta: {}'.format(ssc.ssc_info_meta(pv_var)))
        print('Group: {}'.format(ssc.ssc_info_group(pv_var)))
        print('Entry description: {}'.format(ssc.ssc_entry_description(pv_var)))
        #print('Entry name: {}'.format(ssc.ssc_entry_name(pv_var))) # Segfault?!
        print('')
        #print(ssc.ssc_info_required(pv_var)) # Only available after 2013 SDK
        #print(ssc.ssc_info_constraints(pv_var)) # Only available after 2013 SDK
        idx += 1
        pv_var = ssc.ssc_module_var_info(pv, idx)
    print('Variable count: {}'.format(idx))


if __name__ == '__main__':
    inspect_pvwattsv1()