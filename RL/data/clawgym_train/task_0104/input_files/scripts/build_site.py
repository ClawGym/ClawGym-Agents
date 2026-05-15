import os
import json
import csv

# Minimal placeholder build script. Modify this file in place to implement the build described in the task.
# NOTE: This script currently expects a 'data_file' key in config, which is outdated.
# Your job is to update it to use the correct keys and generate the required outputs.

CONFIG_PATH = os.path.join('config', 'config.json')


def main():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    # BUG/placeholder: outdated key name; should be updated to use 'data_path'.
    data_file = cfg.get('data_file')
    if not data_file:
        print("ERROR: 'data_file' missing in config. Update this script to use the right key.")
        # Placeholder behavior: exit early.
        return

    with open(data_file, 'r', encoding='utf-8') as f:
        tips = json.load(f)

    total = len(tips)
    countries = sorted({t.get('country') for t in tips})

    # Placeholder output to prove the script ran; replace with real outputs per requirements.
    os.makedirs('output', exist_ok=True)
    with open(os.path.join('output', 'placeholder.txt'), 'w', encoding='utf-8') as w:
        w.write(f"total={total}\n")
        w.write(f"countries={len(countries)}\n")


if __name__ == '__main__':
    main()
