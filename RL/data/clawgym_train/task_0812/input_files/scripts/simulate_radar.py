#!/usr/bin/env python3
import json
import math
import csv
import sys
import os

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def compute_max_range_km(tx_power_W, antenna_gain_linear, radar_cross_section_m2, noise_temperature_K, bandwidth_Hz, noise_figure_linear, system_losses_linear, snr_threshold_dB, frequency_MHz):
    """
    Compute maximum radar range (km) for a given frequency using a basic radar range equation.
    Rmax = [Pt * G^2 * lambda^2 * sigma / ((4*pi)^3 * k * T * B * Fn * L * SNR)]^(1/4)
    """
    c = 299792458.0  # speed of light (m/s)
    frequency_Hz = float(frequency_MHz) * 1e6
    wavelength_m = c / frequency_Hz
    # Boltzmann constant (J/K)
    k = 1.38064852e-23
    # Convert SNR threshold to linear
    SNR_linear = 10.0 ** (snr_threshold_dB / 10.0)
    numerator = tx_power_W * (antenna_gain_linear ** 2) * (wavelength_m ** 2) * radar_cross_section_m2
    denominator = ((4.0 * math.pi) ** 3) * k * noise_temperature_K * bandwidth_Hz * noise_figure_linear * system_losses_linear * SNR_linear
    R4 = numerator / denominator
    if R4 <= 0:
        max_range_km = 0.0
    else:
        R_m = R4 ** 0.25
        max_range_km = R_m / 1000.0
    return wavelength_m, max_range_km

def main():
    # Allow optional config path, default to config/radar_config.json
    config_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join('config', 'radar_config.json')
    cfg = load_config(config_path)

    # Extract configuration
    frequencies_MHz = cfg['frequencies_MHz']
    tx_power_W = cfg['tx_power_W']
    antenna_gain_linear = cfg['antenna_gain_linear']
    radar_cross_section_m2 = cfg['radar_cross_section_m2']
    noise_temperature_K = cfg['noise_temperature_K']
    bandwidth_Hz = cfg['bandwidth_Hz']
    noise_figure_linear = cfg['noise_figure_linear']
    system_losses_linear = cfg['system_losses_linear']
    snr_threshold_dB = cfg['snr_threshold_dB']
    output_csv = cfg.get('output_csv', os.path.join('outputs', 'radar_results.csv'))

    os.makedirs(os.path.dirname(output_csv), exist_ok=True)

    # Write results
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'frequency_MHz',
            'wavelength_m',
            'tx_power_W',
            'antenna_gain_linear',
            'radar_cross_section_m2',
            'noise_temperature_K',
            'bandwidth_Hz',
            'noise_figure_linear',
            'system_losses_linear',
            'snr_threshold_dB',
            'max_range_km'
        ])
        for freq in frequencies_MHz:
            wavelength_m, max_range_km = compute_max_range_km(
                tx_power_W=tx_power_W,
                antenna_gain_linear=antenna_gain_linear,
                radar_cross_section_m2=radar_cross_section_m2,
                noise_temperature_K=noise_temperature_K,
                bandwidth_Hz=bandwidth_Hz,
                noise_figure_linear=noise_figure_linear,
                system_losses_linear=system_losses_linear,
                snr_threshold_dB=snr_threshold_dB,
                frequency_MHz=freq
            )
            writer.writerow([
                f'{freq}',
                f'{wavelength_m:.6f}',
                f'{tx_power_W}',
                f'{antenna_gain_linear}',
                f'{radar_cross_section_m2}',
                f'{noise_temperature_K}',
                f'{bandwidth_Hz}',
                f'{noise_figure_linear}',
                f'{system_losses_linear}',
                f'{snr_threshold_dB}',
                f'{max_range_km:.6f}'
            ])
    print(f'Wrote {output_csv} with {len(frequencies_MHz)} rows.')

if __name__ == '__main__':
    main()
