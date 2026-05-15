#!/usr/bin/env python3
import json
import os
from datetime import datetime

VERSION_PATH = os.path.join('project', 'VERSION')
COMMIT_PATH = os.path.join('project', 'COMMIT')
OUT_DIR = os.path.join('out', 'build')


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(VERSION_PATH, 'r', encoding='utf-8') as vf:
        version = vf.read().strip()
    with open(COMMIT_PATH, 'r', encoding='utf-8') as cf:
        commit = cf.read().strip()
    built_at = datetime.utcnow().isoformat() + 'Z'

    app_txt = os.path.join(OUT_DIR, 'app.txt')
    with open(app_txt, 'w', encoding='utf-8') as af:
        af.write(f"App version {version} built from commit {commit}\n")

    info = {"version": version, "commit": commit, "built_at": built_at}
    with open(os.path.join(OUT_DIR, 'build_info.json'), 'w', encoding='utf-8') as jf:
        json.dump(info, jf, indent=2)

    print(f"Wrote {app_txt} and build_info.json")


if __name__ == '__main__':
    main()
