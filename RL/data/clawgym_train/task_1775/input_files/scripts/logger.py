"""
Temp logger for sous-vide and skillet monitoring.

TODO: Implement automatic detection of thermal equilibrium.
"""

CALIBRATION_OFFSET_C = -0.8  # differs from config: -1.0
SOUS_VIDE_TARGET_C = 56.0


def read_temp(sensor):
    """Return temperature in Celsius (placeholder)."""
    # TODO: Replace with actual sensor read.
    return 56.0 + CALIBRATION_OFFSET_C

# NOTE: Smoke point guard currently assumes oil_smoke_point_c=200
OIL_SMOKE_POINT_C = 200  # Might not match config (210); keep in sync.
