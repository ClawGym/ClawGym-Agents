#!/usr/bin/env python3
import os
import sys
import json
import re
import glob

import yaml


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config/project.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    required = ["corpus_dir", "terms_file", "output_json", "case_sensitive"]
    for k in required:
        if k not in cfg:
            sys.stderr.write(f"Missing required config key: {k}\n")
            sys.exit(2)

    corpus_dir = cfg["corpus_dir"]
    terms_file = cfg["terms_file"]
    output_json = cfg["output_json"]
    case_sensitive = bool(cfg["case_sensitive"])

    with open(terms_file, "r", encoding="utf-8") as f:
        terms = json.load(f)
    if not isinstance(terms, list):
        sys.stderr.write("terms_file must contain a JSON list of strings\n")
        sys.exit(2)

    flags = 0 if case_sensitive else re.IGNORECASE
    patterns = {t: re.compile(r"\\b" + re.escape(t) + r"\\b", flags) for t in terms}

    files = sorted(glob.glob(os.path.join(corpus_dir, "*.txt")))
    if not files:
        sys.stderr.write(f"No .txt files found under {corpus_dir}\n")
    results = []
    total_counts = {t: 0 for t in terms}

    for path in files:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        counts = {}
        for term, pat in patterns.items():
            c = len(pat.findall(text))
            if c > 0:
                counts[term] = c
                total_counts[term] += c
        results.append({"file": path, "matches": counts})
        print(f"{os.path.basename(path)}: {sum(counts.values())} matches")

    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    out = {
        "files": results,
        "total_counts": {k: v for k, v in total_counts.items() if v > 0},
        "config_used": {
            "corpus_dir": corpus_dir,
            "terms_file": terms_file,
            "case_sensitive": case_sensitive,
        },
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Saved results to {output_json}")


if __name__ == "__main__":
    main()
