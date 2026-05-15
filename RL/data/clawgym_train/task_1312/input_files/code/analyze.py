#!/usr/bin/env python3
import os, csv, math, re
from collections import defaultdict
import yaml

def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def tokenize(text):
    return re.findall(r"[A-Za-z]+", text.lower())

def mean(xs):
    return sum(xs)/len(xs) if xs else float("nan")

def sd(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x-m)**2 for x in xs)/(len(xs)-1))

def find_trial_files(data_dir):
    # TODO: return a list of CSV file paths under data_dir matching "*_trials.csv"
    return []

def load_trials(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["rt_ms"] = int(row["rt_ms"]) if row.get("rt_ms") not in (None, "") else None
            row["accuracy"] = int(row["accuracy"]) if row.get("accuracy") not in (None, "") else None
            row["vividness_rating"] = int(row["vividness_rating"]) if row.get("vividness_rating") not in (None, "") else None
            rows.append(row)
    return rows

def main():
    cfg = load_config("config/analysis_config.yaml")
    # TODO: implement the analysis:
    # - discover all trial CSV files in cfg["data_dir"]
    # - write a log listing file paths and row counts to output/logs/files_loaded.txt
    # - filter rows by cfg["include_conditions"]
    # - compute per-participant, per-condition metrics and write output/metrics/condition_summary.csv
    #   Required columns: participant_id,condition,n_trials,n_valid_trials_for_theme,mean_rt_ms,sd_rt_ms,mean_accuracy,mean_vividness
    # - load coding scheme and detect themes in report_text for rows that meet cfg thresholds
    # - write output/themes/theme_matrix.csv with columns: participant_id,condition,theme,n_theme_trials,proportion_of_valid_trials
    print("TODO: implement analysis")

if __name__ == "__main__":
    main()
