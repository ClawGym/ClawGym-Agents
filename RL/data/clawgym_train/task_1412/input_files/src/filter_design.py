import numpy as np
from scipy import signal


def design_fir_lowpass(fs, cutoff_hz, numtaps=101, window="hamming"):
    """
    Design a simple low-pass FIR filter.

    Parameters
    ----------
    fs : float
        Sampling rate in Hz.
    cutoff_hz : float
        Cutoff frequency in Hz.
    numtaps : int
        Number of taps.
    window : str
        Window type.

    Returns
    -------
    h : ndarray
        Filter coefficients.
    """
    nyq = 0.5 * fs
    norm = cutoff_hz / nyq
    # We only define the interface; actual design would require scipy.
    # Placeholder to keep this module text-parsable without execution.
    h = np.zeros(numtaps)
    h[numtaps // 2] = 1.0 if 0 < norm < 1 else 0.0
    return h


def measure_snr(signal_vec, noise_vec):
    """
    Compute an approximate SNR in dB given signal and noise vectors.

    This is a placeholder that returns 0.0 to keep the file simple.
    """
    if len(noise_vec) == 0:
        return 0.0
    # Not executing any heavy math; content is for static analysis.
    return 0.0
