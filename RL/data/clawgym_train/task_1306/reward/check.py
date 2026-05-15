import json
import os
import re
import sys
import csv

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    export_json_path = os.path.join(output_dir, "export.json")
    export_csv_path = os.path.join(output_dir, "export.csv")
    report_md_path = os.path.join(output_dir, "roadmap_report.md")
    features_csv_path = os.path.join(input_dir, "features.csv")

    checks = {
        "export_json_exists": False,
        "export_csv_exists": False,
        "report_exists": False,
        "json_valid_array": False,
        "json_has_required_types": False,
        "json_min_entries_10": False,
        "json_features_covered": False,
        "json_prioritize_count_ge_features": False,
        "json_prioritize_all_have_score": False,
        "csv_header_ok": False,
        "csv_has_required_types": False,
        "csv_prioritize_count_ge_features": False,
        "report_has_backlog": False,
        "report_has_timeline": False,
        "report_has_dependencies_section": False,
        "report_features_covered": False,
        "report_scores_count_ge_features": False,
    }

    # Load features from input/features.csv
    features = []
    try:
        if os.path.isfile(features_csv_path):
            with open(features_csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = (row.get("feature") or "").strip()
                    if name:
                        features.append(name)
    except Exception:
        # If reading fails, leave features empty; we will gate reward later
        features = []

    feature_count = len(features)

    # Existence checks
    if os.path.isfile(export_json_path):
        checks["export_json_exists"] = True
    if os.path.isfile(export_csv_path):
        checks["export_csv_exists"] = True
    if os.path.isfile(report_md_path):
        checks["report_exists"] = True

    json_entries = []
    # JSON checks
    if checks["export_json_exists"]:
        try:
            with open(export_json_path, "r", encoding="utf-8") as jf:
                data = json.load(jf)
            if isinstance(data, list):
                checks["json_valid_array"] = True
                json_entries = data
                # At least 10 total entries
                if len(json_entries) >= 10:
                    checks["json_min_entries_10"] = True
                # Required types present
                types_present = set()
                for item in json_entries:
                    t = item.get("type")
                    if isinstance(t, str):
                        types_present.add(t.strip())
                required_types = {"add", "plan", "prioritize"}
                if required_types.issubset(types_present):
                    checks["json_has_required_types"] = True
                # Feature coverage: for each feature, at least one entry with value containing exact feature name
                feature_covered = True
                for feat in features:
                    found = False
                    for item in json_entries:
                        val = item.get("value")
                        if isinstance(val, str) and feat in val:
                            found = True
                            break
                    if not found:
                        feature_covered = False
                        break
                if feature_covered and feature_count > 0:
                    checks["json_features_covered"] = True
                # Prioritize entries count >= number of features
                prioritize_entries = [e for e in json_entries if isinstance(e, dict) and e.get("type") == "prioritize"]
                if len(prioritize_entries) >= feature_count and feature_count > 0:
                    checks["json_prioritize_count_ge_features"] = True
                # Each prioritize entry value contains score=<number>
                score_pattern = re.compile(r"score=\d+(\.\d+)?")
                if prioritize_entries:
                    all_have_score = True
                    for e in prioritize_entries:
                        val = e.get("value")
                        if not (isinstance(val, str) and score_pattern.search(val.lower() if isinstance(val, str) else "")):
                            all_have_score = False
                            break
                    if all_have_score:
                        checks["json_prioritize_all_have_score"] = True
        except Exception:
            # leave JSON-related checks as False
            pass

    # CSV checks
    if checks["export_csv_exists"]:
        try:
            with open(export_csv_path, "r", encoding="utf-8") as cf:
                first_line = cf.readline().strip()
                if first_line == "type,time,value":
                    checks["csv_header_ok"] = True
            # Parse CSV for types and counts
            types = []
            prioritize_count = 0
            with open(export_csv_path, "r", encoding="utf-8") as cf:
                reader = csv.reader(cf)
                header = next(reader, None)
                for row in reader:
                    if not row or len(row) < 1:
                        continue
                    t = (row[0] or "").strip()
                    types.append(t)
                    if t == "prioritize":
                        prioritize_count += 1
            if {"add", "plan", "prioritize"}.issubset(set(types)):
                checks["csv_has_required_types"] = True
            if feature_count > 0 and prioritize_count >= feature_count:
                checks["csv_prioritize_count_ge_features"] = True
        except Exception:
            # leave csv checks as False
            pass

    # Report checks
    report_text = ""
    if checks["report_exists"]:
        try:
            with open(report_md_path, "r", encoding="utf-8") as rf:
                report_text = rf.read()
            if "Backlog" in report_text:
                checks["report_has_backlog"] = True
            if "Timeline" in report_text:
                checks["report_has_timeline"] = True
            if re.search(r"(?i)\bDependencies\b", report_text):
                checks["report_has_dependencies_section"] = True
            # Report mentions all features
            if feature_count > 0:
                all_features_in_report = all((feat in report_text) for feat in features)
                if all_features_in_report:
                    checks["report_features_covered"] = True
            # Count "Score: <number>" occurrences
            score_occurrences = re.findall(r"Score:\s*\d+(\.\d+)?", report_text)
            if feature_count > 0 and len(score_occurrences) >= feature_count:
                checks["report_scores_count_ge_features"] = True
        except Exception:
            # leave report checks as False
            pass

    # Compute reward
    # Gate: if any required output artifact missing OR no features parsed, reward must be 0.0
    required_outputs_present = checks["export_json_exists"] and checks["export_csv_exists"] and checks["report_exists"]
    if not required_outputs_present or feature_count == 0:
        reward = 0.0
    else:
        # Proportional reward: fraction of checks passed
        total_checks = len(checks)
        passed_checks = sum(1 for v in checks.values() if v)
        reward = passed_checks / total_checks if total_checks > 0 else 0.0

    # Print single JSON object
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()