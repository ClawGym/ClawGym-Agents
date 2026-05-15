import argparse
import csv
import hashlib
import json
import os
from typing import Dict, List


def load_config(path: str) -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    # Basic sanity
    if 'required_metadata_fields' not in cfg or 'required_columns' not in cfg:
        raise ValueError('Config missing required keys')
    return cfg


def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_inputs(metadata_path: str, data_path: str, cfg: Dict) -> Dict:
    # Load metadata
    with open(metadata_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)
    required_fields: List[str] = list(cfg.get('required_metadata_fields', []))
    missing_fields = sorted([k for k in required_fields if k not in metadata])
    required_fields_present = len(missing_fields) == 0

    # Load CSV header and count rows
    with open(data_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        header_fields = list(reader.fieldnames or [])
        missing_columns = sorted([c for c in cfg.get('required_columns', []) if c not in header_fields])
        required_columns_present = len(missing_columns) == 0
        row_count = sum(1 for _ in reader)

    dataset_sha256 = compute_sha256(data_path)

    result = {
        'config_version': cfg.get('config_version', ''),
        'metadata_path': metadata_path,
        'data_path': data_path,
        'required_fields_present': required_fields_present,
        'missing_fields': missing_fields,
        'required_columns_present': required_columns_present,
        'missing_columns': missing_columns,
        'dataset_sha256': dataset_sha256,
        'row_count': row_count
    }
    return result


def main():
    parser = argparse.ArgumentParser(description='Validate metadata and dataset against config')
    parser.add_argument('--metadata', required=True, help='Path to metadata JSON')
    parser.add_argument('--data', required=True, help='Path to CSV dataset')
    parser.add_argument('--config', required=True, help='Path to validation config JSON')
    parser.add_argument('--out', required=True, help='Path to write validation report JSON')
    args = parser.parse_args()

    cfg = load_config(args.config)
    report = validate_inputs(args.metadata, args.data, cfg)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, sort_keys=False)


if __name__ == '__main__':
    main()
