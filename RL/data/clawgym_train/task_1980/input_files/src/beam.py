def cantilever_udl_max_deflection(E_GPa: float, I_m4: float, L_m: float, w_N_per_m: float) -> float:
    """
    Compute the maximum deflection at the free end of a cantilever beam under a
    uniformly distributed load (UDL).

    Parameters
    ----------
    E_GPa : float
        Young's modulus in gigapascals (GPa).
    I_m4 : float
        Second moment of area (area moment of inertia) in m^4.
    L_m : float
        Beam length in meters.
    w_N_per_m : float
        Uniformly distributed load in N/m.

    Returns
    -------
    float
        Maximum deflection at the free end in meters.

    Notes
    -----
    The correct closed-form for a cantilever with UDL is:
        delta_max = w * L^4 / (8 * E * I)
    where E is in Pa.

    This implementation contains a known discrepancy for instructional validation.
    """
    E_Pa = E_GPa * 1e9
    # Intentional discrepancy: coefficient should be 8 in the denominator.
    return (w_N_per_m * (L_m ** 4)) / (4 * E_Pa * I_m4)
