#!/usr/bin/env python3
"""
Skeleton fetcher for OpenML datasets.

Expected config (YAML):
openml:
  dataset_ids: [ ]   # integers
  output_root: workspace

This skeleton currently only loads config and prints a plan.
You must implement:
- Downloading each dataset by ID from the official OpenML domain/API (no hardcoded URLs in config).
- Saving raw file(s) under {output_root}/raw/openml/{id}/ and writing download_manifest.json with hashes and sizes.
- Computing summary metrics and writing {output_root}/derived/openml_summary.csv and a filtered+ranked {output_root}/derived/top_datasets.csv.
- Writing logs to {output_root}/logs/fetch.log with START/DONE per dataset.
- Basic retry handling and per-dataset failure isolation.

Run: python scripts/fetch_openml.py --config config/sources.yaml
"""
import argparse
import sys
from pathlib import Path
import yaml


def load_config(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict) or 'openml' not in cfg:
        raise ValueError('Config missing top-level "openml" section')
    om = cfg['openml']
    if 'dataset_ids' not in om or not isinstance(om['dataset_ids'], list):
        raise ValueError('Config openml.dataset_ids must be a list')
    if 'output_root' not in om or not isinstance(om['output_root'], str):
        raise ValueError('Config openml.output_root must be a string path')
    return cfg


def main(argv=None):
    parser = argparse.ArgumentParser(description='Fetch OpenML datasets and summarize (skeleton).')
    parser.add_argument('--config', required=True, help='Path to YAML config (e.g., config/sources.yaml)')
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    dataset_ids = cfg['openml']['dataset_ids']
    output_root = Path(cfg['openml']['output_root'])

    # Print plan; no side effects here. Implement the behavior described in the module docstring.
    print('Plan: output_root =', output_root)
    print('Plan: will fetch', len(dataset_ids), 'dataset(s):', dataset_ids)
    print('NOTE: This is a skeleton. You must implement downloads, manifests, summaries, ranking, and logs as described in the task.')


if __name__ == '__main__':
    sys.exit(main())
