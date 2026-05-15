import os
import json
import argparse
import logging
import datetime
import csv

CFG_PATH = os.path.join('app', 'config.json')
LOG_DIR = 'logs'


def load_config():
    with open(CFG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_interval_ms(value):
    # Deliberately strict: will raise if value is like "50ms"
    return int(value)


def check():
    os.makedirs('out', exist_ok=True)
    try:
        cfg = load_config()
        interval = parse_interval_ms(cfg.get('sensor_poll_interval_ms'))
        result = {"status": "ok", "interval_ms": interval}
    except Exception as e:
        result = {"status": "error", "error": str(e)}
    with open(os.path.join('out', 'status.json'), 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, sort_keys=True)


def run():
    os.makedirs(LOG_DIR, exist_ok=True)
    cfg = load_config()
    log_path = os.path.join(LOG_DIR, f"run-{datetime.date.today().isoformat()}.log")
    level_name = cfg.get("log_level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        filename=log_path,
        level=level,
        format='%(asctime)s %(levelname)s %(message)s'
    )
    try:
        interval_ms = parse_interval_ms(cfg.get('sensor_poll_interval_ms'))
        data_dir = cfg.get('data_dir', 'sensors')
        sensor_path = os.path.join(data_dir, 'mock_heart_rate.csv')
        with open(sensor_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            vals = [int(row['hr']) for row in reader]
        avg = sum(vals) / max(len(vals), 1)
        logging.info(f"Avg HR={avg:.1f} bpm; next poll in {interval_ms} ms")
    except Exception:
        logging.exception("Polling failed")


def main():
    parser = argparse.ArgumentParser(description='Simple training tracker')
    parser.add_argument('--check', action='store_true', help='Write out/status.json with status ok/error')
    args = parser.parse_args()
    if args.check:
        check()
    else:
        run()


if __name__ == '__main__':
    main()
