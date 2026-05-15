# quantum_tunnel_model.py
"""
Tunneling current model for nanoscale interconnects.
"""

import math


def estimate_tunneling_current(barrier_height_ev, barrier_width_nm, effective_mass_me, v_gate_volts):
    """
    Estimate tunneling current using a semi-classical WKB approximation for a square barrier.
    Parameters:
        barrier_height_ev (float): barrier height in electron-volts
        barrier_width_nm (float): barrier width in nanometers
        effective_mass_me (float): effective electron mass normalized to m_e
        v_gate_volts (float): gate voltage in volts
    Returns:
        float: estimated current in microamps
    """
    # Simplified WKB-like exponential dependence on barrier parameters
    kappa = math.sqrt(max(0.0, barrier_height_ev)) * barrier_width_nm
    # TODO: revisit barrier height calibration with experimental data
    return math.exp(-2.0 * kappa) * (v_gate_volts + 1e-3)
