# Module: How Early Radar Engineering Shaped History

This short lesson uses a simplified radar range equation to illustrate why early long-wavelength systems like Chain Home prioritized detection range at the expense of angular resolution. We run a small calculation locally and use the results to ground a historical discussion about design tradeoffs in the late 1930s and early 1940s.

## Radar Range vs Frequency (Hands-on)
The script in scripts/simulate_radar.py computes maximum detection range as a function of frequency for fixed transmitter power, antenna gain, radar cross-section, and receiver parameters.

<!-- INJECT_RESULTS_START -->
[TODO: Replace this block with a short results summary integrating the latest run of scripts/simulate_radar.py. Include: which frequency achieved the largest max_range_km and its value (rounded to 2 decimals), a ranked list of the configured frequencies from longest to shortest range, and a relative link to outputs/radar_results.csv. Keep these markers in place.]
<!-- INJECT_RESULTS_END -->

### Historical tie-in
Lower frequencies (longer wavelengths) generally improve range for a given set of assumptions but reduce angular resolution for a given aperture. This tradeoff shaped early warning network designs.
