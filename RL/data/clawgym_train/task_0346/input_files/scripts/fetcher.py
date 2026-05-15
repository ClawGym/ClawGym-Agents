import os
import json
import csv
import yaml
import datetime


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_attractions(path):
    rows = []
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def ensure_dirs(cfg):
    os.makedirs(cfg['output_paths']['raw_dir'], exist_ok=True)
    os.makedirs(os.path.dirname(cfg['output_paths']['processed_incidents_json']), exist_ok=True)
    os.makedirs(os.path.dirname(cfg['output_paths']['processed_summary_csv']), exist_ok=True)
    os.makedirs(os.path.dirname(cfg['logging']['path']), exist_ok=True)


def main():
    cfg = load_config('input/monitor.yaml')
    attractions = load_attractions('input/attractions.csv')
    ensure_dirs(cfg)

    # TODO: Implement resilient fetching of official pages described in cfg['sources'] using their objective attributes.
    # - Do NOT hardcode direct URLs; discover target pages by their official name/domain attributes (e.g., site title contains, organization name, content sections).
    # - Apply cfg['reliability'] timeouts, retries, and backoff.
    # - Save each fetched page as raw HTML under cfg['output_paths']['raw_dir'] named "{source_name}_{timestamp}.html" (UTC ISO timestamp, no spaces).
    # - Extract advisory-like items and match against cfg['detection_keywords'] and the attractions list.
    # - Write structured results to JSON and a summary CSV as per cfg['output_paths'].
    # - Append basic logs to cfg['logging']['path'] with one line per source for start/end and status.

    # Placeholder outputs so the script runs; replace with real implementation.
    placeholder = {
        "run_id": cfg['run_id'],
        "trip_date": cfg['trip_date'],
        "retrieved_at_utc": datetime.datetime.utcnow().isoformat() + 'Z',
        "sources": []
    }
    with open(cfg['output_paths']['processed_incidents_json'], 'w', encoding='utf-8') as f:
        json.dump(placeholder, f, ensure_ascii=False, indent=2)
    with open(cfg['output_paths']['processed_summary_csv'], 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['source_name', 'fetch_status', 'advisory_count'])
    with open(cfg['logging']['path'], 'a', encoding='utf-8') as log:
        log.write(f"{datetime.datetime.utcnow().isoformat()}Z placeholder run completed\n")
    print('Wrote placeholder outputs; implement real fetching and extraction to meet the requirements.')


if __name__ == '__main__':
    main()
