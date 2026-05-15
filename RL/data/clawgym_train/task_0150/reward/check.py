import json
import os
import sys
import csv

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def parse_tsv(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                rows.append(row)
        return rows
    except Exception:
        return None

def parse_csv_dicts(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames
        return headers, rows
    except Exception:
        return None, None

def is_int(s):
    try:
        int(s)
        return True
    except Exception:
        return False

def is_float(s):
    try:
        float(s)
        return True
    except Exception:
        return False

def find_headings_in_order(text, headings):
    positions = []
    for h in headings:
        idx = text.find(h)
        if idx == -1:
            return False, []
        positions.append(idx)
    # Ensure strictly increasing order
    for i in range(len(positions) - 1):
        if positions[i] >= positions[i+1]:
            return False, positions
    return True, positions

def get_section_text(content, heading_title):
    idx = content.find(heading_title)
    if idx == -1:
        return None
    # From this heading to end (since it's last section)
    section = content[idx:]
    return section

def extract_top3_patents(headers, rows):
    # Assumes rows already validated to be sorted descending by similarity_score
    if not rows or len(rows) < 3:
        return None
    pn_key = "patent_number"
    if pn_key not in headers:
        return None
    top3 = []
    for i in range(3):
        pn = rows[i].get(pn_key, "")
        top3.append(pn)
    return top3

def find_comparison_list(obj, required_len):
    # Prefer 'comparisons' key if present
    cand = obj.get("comparisons")
    if isinstance(cand, list) and len(cand) >= required_len:
        # Validate elements have prior1/2/3
        ok = True
        for el in cand[:required_len]:
            if not isinstance(el, dict):
                ok = False
                break
            if not all(k in el and isinstance(el[k], dict) for k in ("prior1", "prior2", "prior3")):
                ok = False
                break
        if ok:
            return cand
    # Generic search: any list value matching required structure
    for k, v in obj.items():
        if isinstance(v, list) and len(v) >= required_len:
            ok = True
            for el in v[:required_len]:
                if not isinstance(el, dict):
                    ok = False
                    break
                if not all(k2 in el and isinstance(el[k2], dict) for k2 in ("prior1", "prior2", "prior3")):
                    ok = False
                    break
            if ok:
                return v
    return None

def validate_prior_dict(d, allowed_labels, top3_set):
    # d must have patent_number, label, excerpt
    if not isinstance(d, dict):
        return False
    pn = d.get("patent_number")
    lab = d.get("label")
    exc = d.get("excerpt")
    if not isinstance(pn, str) or pn.strip() == "":
        return False
    if pn not in top3_set:
        return False
    if lab not in allowed_labels:
        return False
    if not isinstance(exc, str) or exc.strip() == "":
        return False
    return True

workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
input_dir = os.path.join(workspace_root, "input")
output_dir = os.path.join(workspace_root, "output")
reward_dir = os.path.join(workspace_root, "reward")

checks = {
    "report_exists": False,
    "report_headings_ordered": False,
    "report_disclaimer_early": False,
    "retrieval_strategy_valid": False,
    "patents_csv_valid_structure": False,
    "patents_csv_enough_rows": False,
    "patents_sorted_desc": False,
    "patents_similarity_stars_valid": False,
    "comparison_json_valid": False,
    "comments_md_valid": False,
    "report_related_list_contains_all": False
}

# Paths
report_path = os.path.join(output_dir, "report.md")
tsv_path = os.path.join(output_dir, "retrieval_strategy.tsv")
patents_csv_path = os.path.join(output_dir, "patents.csv")
comparison_json_path = os.path.join(output_dir, "comparison.json")
comments_md_path = os.path.join(output_dir, "comments.md")
disclaimer_input_path = os.path.join(input_dir, "disclaimer.md")

# 1) report.md checks
report_content = None
if os.path.isfile(report_path):
    checks["report_exists"] = True
    report_content = read_text(report_path)
    if report_content is None:
        report_content = ""
else:
    report_content = ""

headings = [
    "I. User Solution",
    "II. Technical Features",
    "III. Feature Comparison Table",
    "IV. Novelty/Inventive Step Comment",
    "V. Novelty Search Conclusion",
    "VI. Retrieval Strategy",
    "VII. Related Patent List"
]

if checks["report_exists"]:
    ordered, positions = find_headings_in_order(report_content, headings)
    if ordered:
        checks["report_headings_ordered"] = True

    # Disclaimer presence and position before first heading
    disclaimer_text = read_text(disclaimer_input_path)
    if disclaimer_text is None:
        disclaimer_text = ""
    if disclaimer_text:
        idx_disc = report_content.find(disclaimer_text)
        idx_first_heading = report_content.find(headings[0]) if headings else -1
        if idx_disc != -1 and (idx_first_heading == -1 or idx_disc < idx_first_heading):
            checks["report_disclaimer_early"] = True

# 2) retrieval_strategy.tsv
if os.path.isfile(tsv_path):
    tsv_rows = parse_tsv(tsv_path)
    if tsv_rows and len(tsv_rows) >= 4:  # header + at least 3 data rows
        header = tsv_rows[0]
        expected_header = ["step_no", "step_name", "strategy", "num_results"]
        # Exact match
        if header == expected_header:
            valid_rows = True
            for row in tsv_rows[1:]:
                if len(row) < 4:
                    valid_rows = False
                    break
                num_results = row[3]
                if not is_int(num_results):
                    valid_rows = False
                    break
                if int(num_results) < 0:
                    valid_rows = False
                    break
            if valid_rows:
                # At least 3 data rows
                if len(tsv_rows) - 1 >= 3:
                    checks["retrieval_strategy_valid"] = True

# 3) patents.csv
headers, patents_rows = (None, None)
if os.path.isfile(patents_csv_path):
    headers, patents_rows = parse_csv_dicts(patents_csv_path)
    expected_cols = ["patent_number","title","applicant","publication_date","ipc","abstract","similarity_score","similarity_stars"]
    if headers == expected_cols:
        checks["patents_csv_valid_structure"] = True
    if isinstance(patents_rows, list):
        if len(patents_rows) >= 50:
            checks["patents_csv_enough_rows"] = True
        # Validate sorting and similarity_stars
        if patents_rows:
            all_scores = []
            stars_valid = True
            sorted_desc = True
            prev_score = None
            for r in patents_rows:
                score_str = r.get("similarity_score", "")
                stars_str = r.get("similarity_stars", "")
                if not is_float(score_str):
                    sorted_desc = False
                    break
                score_val = float(score_str)
                all_scores.append(score_val)
                if prev_score is not None and score_val > prev_score + 1e-12:
                    # not descending
                    sorted_desc = False
                prev_score = score_val
                # stars
                if not is_int(stars_str):
                    stars_valid = False
                else:
                    s = int(stars_str)
                    if s < 0 or s > 5:
                        stars_valid = False
            if sorted_desc and len(all_scores) == len(patents_rows):
                checks["patents_sorted_desc"] = True
            if stars_valid and len(patents_rows) > 0:
                checks["patents_similarity_stars_valid"] = True

# Prepare top3 patent numbers if possible
top3_patents = None
if checks["patents_csv_valid_structure"] and checks["patents_sorted_desc"] and isinstance(patents_rows, list) and len(patents_rows) >= 3:
    top3_patents = extract_top3_patents(headers, patents_rows)
else:
    top3_patents = None

# 4) comparison.json
if os.path.isfile(comparison_json_path) and top3_patents is not None:
    try:
        with open(comparison_json_path, "r", encoding="utf-8") as f:
            comp_obj = json.load(f)
        valid = True
        if not isinstance(comp_obj, dict):
            valid = False
        tech_feats = comp_obj.get("technical_features")
        if not (isinstance(tech_feats, list) and len(tech_feats) >= 5):
            valid = False
        else:
            if tech_feats[0] != "Technical Subject":
                valid = False
        comp_list = None
        if valid:
            comp_list = find_comparison_list(comp_obj, len(tech_feats))
            if comp_list is None:
                valid = False
        allowed_labels = {"Disclosed","Common General Knowledge","Not Disclosed"}
        if valid:
            top3_set = set(top3_patents)
            # Validate each feature row
            for i in range(len(tech_feats)):
                row = comp_list[i]
                p1 = row.get("prior1")
                p2 = row.get("prior2")
                p3 = row.get("prior3")
                if not (validate_prior_dict(p1, allowed_labels, top3_set) and
                        validate_prior_dict(p2, allowed_labels, top3_set) and
                        validate_prior_dict(p3, allowed_labels, top3_set)):
                    valid = False
                    break
        if valid:
            checks["comparison_json_valid"] = True
    except Exception:
        pass

# 5) comments.md
if os.path.isfile(comments_md_path):
    comments_content = read_text(comments_md_path) or ""
    lines = comments_content.splitlines()
    has_conclusion_line = False
    for line in lines:
        ls = line.strip()
        if ls.startswith("Conclusion:") and ("X Document" in ls or "Y Document" in ls):
            has_conclusion_line = True
            break
    mentions_top3 = False
    if top3_patents is not None:
        for pn in top3_patents:
            if pn and pn in comments_content:
                mentions_top3 = True
                break
    # comments valid only if both conditions met
    if has_conclusion_line and (mentions_top3 if top3_patents is not None else False):
        checks["comments_md_valid"] = True

# 6) Cross-file consistency: report "VII. Related Patent List" section contains all patent_numbers in patents.csv
if checks["report_exists"] and checks["report_headings_ordered"] and checks["patents_csv_valid_structure"] and isinstance(patents_rows, list) and len(patents_rows) >= 1:
    related_section = get_section_text(report_content, "VII. Related Patent List")
    if related_section is not None:
        contains_all = True
        for r in patents_rows:
            pn = r.get("patent_number", "")
            if pn and pn not in related_section:
                contains_all = False
                break
        if contains_all:
            checks["report_related_list_contains_all"] = True

# Compute reward as fraction of passed checks
total_checks = len(checks)
passed = sum(1 for v in checks.values() if v)
reward = passed / total_checks if total_checks > 0 else 0.0

# Ensure 0.0 if no outputs at all (no-op baseline)
# If output directory missing or empty required artifacts: the above should already yield 0.0.
# But double-ensure: if none of the key files exist, set reward to 0.0.
key_files = [report_path, tsv_path, patents_csv_path, comparison_json_path, comments_md_path]
if not any(os.path.isfile(p) for p in key_files):
    reward = 0.0

# Print result JSON (last non-empty line)
result = {"reward": round(reward, 6)}
result.update(checks)
print(json.dumps(result))