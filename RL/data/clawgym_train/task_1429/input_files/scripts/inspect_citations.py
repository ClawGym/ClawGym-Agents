import argparse
import csv
import json
import os
import re
import sys
from typing import Dict, Any


def parse_year(text: str) -> int:
    if text is None:
        raise ValueError("claimed_date is missing")
    m = re.search(r"(\d+)", str(text))
    if not m:
        raise ValueError(f"Could not parse year from '{text}'")
    return int(m.group(1))


def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def ensure_dir_for(path: str) -> None:
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def inspect_citations(input_csv: str, cfg_path: str, out_jsonl: str) -> int:
    cfg = load_config(cfg_path)
    aliases = cfg["tradition"]["aliases"]
    earliest = cfg["tradition"]["earliest_years"]
    anach_weight = cfg["weights"]["anachronism"]  # Intentionally uncast; type issues should surface.

    ensure_dir_for(out_jsonl)

    anomalies = 0
    with open(input_csv, 'r', encoding='utf-8') as f_in, open(out_jsonl, 'w', encoding='utf-8') as f_out:
        reader = csv.DictReader(f_in)
        for row in reader:
            cid = row.get('citation_id')
            term_raw = row.get('tradition_term', '')
            term = aliases.get(term_raw, term_raw)
            claimed_str = row.get('claimed_date', '')
            source = row.get('source', '')
            title = row.get('title', '')

            try:
                claimed_year = parse_year(claimed_str)
            except Exception as e:
                print(f"Skipping citation_id={cid} due to date parse error: {e}", file=sys.stderr)
                continue

            if term not in earliest:
                # Unknown term: skip quietly; this tool focuses on known tradition markers.
                continue

            earliest_year = int(earliest[term])
            if claimed_year < earliest_year:
                diff_years = earliest_year - claimed_year
                delta_centuries = diff_years / 100.0
                # If anach_weight is a wrong type (e.g., string), this will raise TypeError as intended.
                severity = round(delta_centuries * anach_weight, 4)
                record = {
                    "citation_id": cid,
                    "source": source,
                    "title": title,
                    "tradition_term": term,
                    "claimed_date": claimed_str,
                    "claimed_year": claimed_year,
                    "earliest_year": earliest_year,
                    "issue_type": "anachronism",
                    "severity_score": severity,
                    "reason": f"{term} attested by {earliest_year}, claimed {claimed_year}"
                }
                f_out.write(json.dumps(record, ensure_ascii=False) + "\n")
                anomalies += 1

    print(f"Wrote {anomalies} anomalies to {out_jsonl}")
    return anomalies


def main():
    parser = argparse.ArgumentParser(description="Inspect citations for potential anachronistic tradition terms.")
    parser.add_argument('--input', required=True, help='Path to input CSV')
    parser.add_argument('--config', required=True, help='Path to JSON config')
    parser.add_argument('--out', required=True, help='Path to output JSONL for anomalies')
    args = parser.parse_args()

    try:
        count = inspect_citations(args.input, args.config, args.out)
        if count == 0:
            print("No anomalies detected.")
    except Exception as e:
        # Propagate with traceback so the user can inspect and fix.
        print(f"Error during inspection: {e}", file=sys.stderr)
        raise


if __name__ == '__main__':
    main()
