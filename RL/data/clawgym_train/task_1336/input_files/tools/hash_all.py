import argparse
import csv
import hashlib
import os
import sys


def sha256_file(path, chunk_size=65536):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description='Compute SHA-256 for episode files listed in a catalog CSV.')
    parser.add_argument('--root', required=True, help='Root directory containing episode files (e.g., input/baseline or input/library).')
    parser.add_argument('--episodes', required=True, help='Path to episodes.csv with columns including episode_id and file_path.')
    parser.add_argument('--out', required=True, help='Path to write output CSV of checksums.')
    args = parser.parse_args()

    # Read episodes catalog
    rows = []
    with open(args.episodes, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            if 'episode_id' not in r or 'file_path' not in r:
                sys.stderr.write('episodes.csv must have episode_id and file_path columns\n')
                sys.exit(2)
            rows.append({'episode_id': r['episode_id'], 'file_path': r['file_path']})

    os.makedirs(os.path.dirname(args.out), exist_ok=True) if os.path.dirname(args.out) else None

    with open(args.out, 'w', newline='', encoding='utf-8') as out_f:
        fieldnames = ['episode_id', 'file_path', 'root', 'sha256', 'missing']
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            full_path = os.path.join(args.root, r['file_path'])
            if os.path.exists(full_path) and os.path.isfile(full_path):
                try:
                    digest = sha256_file(full_path)
                    writer.writerow({
                        'episode_id': r['episode_id'],
                        'file_path': r['file_path'],
                        'root': args.root,
                        'sha256': digest,
                        'missing': 'false'
                    })
                except Exception as e:
                    # Treat unreadable as missing for safety but surface partial info
                    writer.writerow({
                        'episode_id': r['episode_id'],
                        'file_path': r['file_path'],
                        'root': args.root,
                        'sha256': '',
                        'missing': 'true'
                    })
            else:
                writer.writerow({
                    'episode_id': r['episode_id'],
                    'file_path': r['file_path'],
                    'root': args.root,
                    'sha256': '',
                    'missing': 'true'
                })

if __name__ == '__main__':
    main()
