"""Convert raw FEMM measurements to the public clockwise rotation convention."""
import copy
import math

VERSION = 'coilem.femm_clockwise_reference/v2'
DESCRIPTION = ('theta_public=-theta_FEMM modulo 360; torque_public=-torque_FEMM; '
               'omega_FEMM=-omega_public; e_public(theta)=-e_FEMM(-theta); '
               'gamma_internal=180-gamma_public. No fitted sign, phase or scale.')


def normalize_femm_reference(measurement):
    """Keep the registered torque mapping and convert voltage from raw evidence.

    Both solvers report terminal back-EMF as e=omega*d(psi)/d(theta).
    FEMM uses increasing CCW angle and positive CCW speed. Public native
    sweeps increase CW angle. At the same public positive speed, native
    FEMM angular velocity is negative, so its voltage must also be negated.
    Always derive from raw_reference_result: applying this function twice
    cannot flip voltage back or mutate the saved measurement.
    """
    result=copy.deepcopy(measurement['result'])
    raw=measurement['raw_reference_result']['back_emf_waveform']
    angles=raw['electrical_angle_deg']
    if not angles or not all(math.isfinite(float(a)) for a in angles):
        raise ValueError('Invalid raw FEMM Back-EMF grid')
    order=sorted(range(len(angles)),key=lambda i:(-float(angles[i]))%360.0)
    public_angles=[(-float(angles[i]))%360.0 for i in order]
    if len({round(a,7) for a in public_angles})!=len(public_angles):
        raise ValueError('Duplicate raw FEMM Back-EMF angles')
    waveform={'electrical_angle_deg':public_angles}
    for key in ('phase_a_V','phase_b_V','phase_c_V'):
        values=raw[key]
        if len(values)!=len(angles) or not all(math.isfinite(float(v)) for v in values):
            raise ValueError('Invalid raw FEMM voltage series: '+key)
        waveform[key]=[-float(values[i]) for i in order]
    result['back_emf_waveform']=waveform
    return result
