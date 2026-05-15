import os
import sys
import json
import csv
from typing import List, Dict

"""
Simple rocket thrust/Isp calculator.

Reads:
- CSV: input/engine_tests.csv with columns:
  test_id, propellant, mass_flow_rate (kg/s), effective_exhaust_velocity (m/s),
  ambient_pressure (Pa), exit_pressure (Pa), nozzle_exit_area (m^2)
- JSON config: input/config.json with keys:
  use_ideal_expansion (bool), use_measured_exit_pressure (bool), g0 (float), output_dir (str)

CLI:
  python scripts/run_sim.py --config input/config.json [--output-dir workspace/updated]

Writes:
  <output_dir>/results.csv with computed fields per test.

NOTE: The non-ideal path currently ignores measured exit pressure and defaults to ambient pressure.
      Adjust this logic if you want to use measured exit_pressure.
"""

def load_config(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_args(argv: List[str]) -> Dict:
    cfg_path = 'input/config.json'
    out_dir_override = None
    if '--config' in argv:
        idx = argv.index('--config')
        if idx + 1 < len(argv):
            cfg_path = argv[idx + 1]
    if '--output-dir' in argv:
        idx = argv.index('--output-dir')
        if idx + 1 < len(argv):
            out_dir_override = argv[idx + 1]
    return { 'config_path': cfg_path, 'output_dir_override': out_dir_override }


def read_tests(csv_path: str) -> List[Dict]:
    rows = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def compute_thrust_and_isp(row: Dict, cfg: Dict) -> Dict:
    mdot = float(row['mass_flow_rate'])  # kg/s
    Ve = float(row['effective_exhaust_velocity'])  # m/s
    Pa = float(row['ambient_pressure'])  # Pa
    Ae = float(row['nozzle_exit_area'])  # m^2
    g0 = float(cfg.get('g0', 9.80665))

    use_ideal = bool(cfg.get('use_ideal_expansion', True))
    use_measured = bool(cfg.get('use_measured_exit_pressure', False))

    if use_ideal:
        Pe_used = Pa
    else:
        if use_measured:
            # BUG/assumption: measured exit pressure handling is not implemented; currently falls back to ambient.
            # To use measured exit pressure, set Pe_used = float(row['exit_pressure']).
            Pe_used = Pa
        else:
            Pe_used = Pa

    thrust = mdot * Ve + (Pe_used - Pa) * Ae  # N
    Isp = thrust / (mdot * g0)  # s

    return {
        'test_id': row['test_id'],
        'propellant': row['propellant'],
        'mass_flow_rate': mdot,
        'effective_exhaust_velocity': Ve,
        'ambient_pressure': Pa,
        'exit_pressure_used': Pe_used,
        'nozzle_exit_area': Ae,
        'thrust_N': thrust,
        'Isp_s': Isp
    }


def write_results(rows: List[Dict], out_csv: str) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    fieldnames = [
        'test_id', 'propellant', 'mass_flow_rate', 'effective_exhaust_velocity',
        'ambient_pressure', 'exit_pressure_used', 'nozzle_exit_area',
        'thrust_N', 'Isp_s'
    ]
    with open(out_csv, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    args = parse_args(sys.argv)
    cfg = load_config(args['config_path'])
    out_dir = args['output_dir_override'] or cfg.get('output_dir', 'workspace/output')

    data = read_tests('input/engine_tests.csv')
    results = [compute_thrust_and_isp(r, cfg) for r in data]

    out_csv = os.path.join(out_dir, 'results.csv')
    write_results(results, out_csv)
    print(f"Wrote results to: {out_csv}")

if __name__ == '__main__':
    main()
