import json
import os
import sys
import csv
import re

def load_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def is_int(n):
    return isinstance(n, int) and not isinstance(n, bool)

def parse_bool_like(s):
    if isinstance(s, bool):
        return s
    if not isinstance(s, str):
        return None
    v = s.strip().lower()
    if v in ("true", "yes", "y", "1"):
        return True
    if v in ("false", "no", "n", "0"):
        return False
    return None

def count_words(text):
    tokens = re.findall(r"\b\w+\b", text)
    return len(tokens)

def validate_scans_jsonl(path):
    result = {
        "exists": False,
        "three_lines": False,
        "schema_valid": False,
        "ideas_to_scores": {},
        "parsed_objects": [],
    }
    if not os.path.isfile(path):
        return result
    result["exists"] = True
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines_all = f.read().splitlines()
        non_empty = [ln for ln in lines_all if ln.strip() != ""]
        if len(non_empty) != 3:
            return result
        result["three_lines"] = True

        parsed = []
        for ln in non_empty:
            try:
                obj = json.loads(ln)
            except Exception:
                return result
            parsed.append(obj)

        # schema validation
        required_top = {"idea", "overall_score", "dimensions", "competitors", "grid", "verdict", "build_it"}
        dim_keys_required = {"L", "O", "B", "S", "T", "R"}
        for obj in parsed:
            if not isinstance(obj, dict):
                return result
            if not required_top.issubset(set(obj.keys())):
                return result

            # idea
            idea = obj.get("idea")
            if not isinstance(idea, str) or idea.strip() == "":
                return result

            # overall_score
            overall = obj.get("overall_score")
            if not is_int(overall) or not (0 <= overall <= 100):
                return result

            # dimensions
            dims = obj.get("dimensions")
            if not isinstance(dims, dict):
                return result
            if set(dims.keys()) != dim_keys_required:
                return result
            for k in dim_keys_required:
                d = dims.get(k)
                if not isinstance(d, dict):
                    return result
                if "score" not in d or "verdict" not in d:
                    return result
                sc = d.get("score")
                vd = d.get("verdict")
                if not is_int(sc) or not (0 <= sc <= 100):
                    return result
                if not isinstance(vd, str) or vd.strip() == "":
                    return result

            # competitors
            comp = obj.get("competitors")
            if not isinstance(comp, list):
                return result

            # grid
            grid = obj.get("grid")
            if not isinstance(grid, dict):
                return result
            inv = grid.get("investor_count")
            mq = grid.get("match_quality")
            if not is_int(inv) or inv < 0:
                return result
            if not isinstance(mq, str):
                return result

            # verdict
            ver = obj.get("verdict")
            if not isinstance(ver, str) or ver.strip() == "":
                return result

            # build_it
            bi = obj.get("build_it")
            if not isinstance(bi, bool):
                return result

        # if we reached here, all three passed
        result["schema_valid"] = True
        result["parsed_objects"] = parsed
        result["ideas_to_scores"] = {o["idea"]: o["overall_score"] for o in parsed}
        return result
    except Exception:
        return result

def validate_summary_csv(path, scans_info, input_ideas):
    result = {
        "exists": False,
        "header_valid": False,
        "three_rows": False,
        "rows_valid": False,
        "matches_scans": False,
        "order_matches_input": False,
        "ideas_in_order": [],
    }
    if not os.path.isfile(path):
        return result
    result["exists"] = True

    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception:
        return result

    if not rows:
        return result

    # Handle potential BOM in the first header cell
    if rows[0]:
        rows[0][0] = rows[0][0].lstrip("\ufeff")

    header = rows[0]
    expected_header = ["idea", "overall_score", "build_it", "signal"]
    if header == expected_header:
        result["header_valid"] = True

    data_rows = [r for r in rows[1:] if any(cell.strip() for cell in r)]
    if len(data_rows) == 3:
        result["three_rows"] = True

    # Validate each row contents and signal classification
    rows_ok = True
    ideas_in_order = []
    for r in data_rows:
        if len(r) != 4:
            rows_ok = False
            break
        idea, overall_str, build_str, signal = r
        if not idea or not isinstance(idea, str):
            rows_ok = False
            break
        try:
            overall = int(overall_str)
        except Exception:
            rows_ok = False
            break
        if not (0 <= overall <= 100):
            rows_ok = False
            break
        bi = parse_bool_like(build_str)
        if bi is None:
            rows_ok = False
            break
        # compute expected signal
        if overall >= 70:
            expected_signal = "STRONG"
        elif overall >= 50:
            expected_signal = "MODERATE"
        else:
            expected_signal = "WEAK"
        if signal.strip().upper() != expected_signal:
            rows_ok = False
            break
        ideas_in_order.append(idea)
    result["rows_valid"] = rows_ok
    result["ideas_in_order"] = ideas_in_order

    # Compare with scans.jsonl ideas and scores
    matches_scans = False
    if scans_info.get("schema_valid") and rows_ok and len(data_rows) == 3:
        scans_map = scans_info.get("ideas_to_scores", {})
        try:
            all_present = all((r[0] in scans_map) for r in data_rows)
            all_scores_match = all(int(r[1]) == scans_map.get(r[0], None) for r in data_rows)
            matches_scans = all_present and all_scores_match
        except Exception:
            matches_scans = False
    result["matches_scans"] = matches_scans

    # Order matches input ideas
    order_ok = False
    if input_ideas and len(input_ideas) == 3 and len(ideas_in_order) == 3:
        order_ok = ideas_in_order == input_ideas
    result["order_matches_input"] = order_ok

    return result

def validate_comparison_md(path):
    result = {
        "exists": False,
        "has_decision_rationale": False,
        "word_count_ge_120": False,
        "mentions_constraints": False,
    }
    if not os.path.isfile(path):
        return result
    result["exists"] = True
    txt = load_text(path)
    if txt is None:
        return result

    if re.search(r"decision rationale", txt, flags=re.IGNORECASE):
        result["has_decision_rationale"] = True

    if count_words(txt) >= 120:
        result["word_count_ge_120"] = True

    # constraint keywords: EU, SMB, budget, 200k, six months, 6 months, regulated data, founders
    keywords = [
        ("EU", re.compile(r"\bEU\b", re.IGNORECASE)),
        ("SMB", re.compile(r"\bSMB\b", re.IGNORECASE)),
        ("budget", re.compile(r"budget", re.IGNORECASE)),
        ("200k", re.compile(r"200k", re.IGNORECASE)),
        ("six months", re.compile(r"six months", re.IGNORECASE)),
        ("6 months", re.compile(r"6 months", re.IGNORECASE)),
        ("regulated data", re.compile(r"regulated data", re.IGNORECASE)),
        ("founders", re.compile(r"founders", re.IGNORECASE)),
    ]
    present = set()
    for name, pat in keywords:
        if pat.search(txt):
            present.add(name)
    if len(present) >= 2:
        result["mentions_constraints"] = True

    return result

def validate_privacy_txt(path):
    result = {
        "exists": False,
        "mentions_required": False,
    }
    if not os.path.isfile(path):
        return result
    result["exists"] = True
    txt = load_text(path)
    if txt is None:
        return result
    cond1 = re.search(r"external scoring service", txt, re.IGNORECASE) is not None
    cond2 = any(re.search(pat, txt, re.IGNORECASE) for pat in [
        r"not publicly published",
        r"kept private",
        r"\bprivate\b",
    ])
    result["mentions_required"] = bool(cond1 and cond2)
    return result

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")

    checks = {
        "scans_exists": False,
        "scans_three_lines": False,
        "scans_schema_valid": False,
        "summary_exists": False,
        "summary_header_valid": False,
        "summary_three_rows": False,
        "summary_rows_valid": False,
        "summary_matches_scans": False,
        "order_matches_input": False,
        "comparison_exists": False,
        "comparison_has_decision_rationale": False,
        "comparison_word_count_ge_120": False,
        "comparison_mentions_constraints": False,
        "privacy_exists": False,
        "privacy_mentions_required": False,
    }

    # Load input ideas order (for order check only; does not grant positive reward by itself)
    input_ideas = None
    try:
        ideas_path = os.path.join(input_dir, "ideas.json")
        if os.path.isfile(ideas_path):
            with open(ideas_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # Ensure strings
                input_ideas = [str(x) for x in data]
    except Exception:
        input_ideas = None

    # Validate scans.jsonl
    scans_path = os.path.join(output_dir, "scans.jsonl")
    scans_info = validate_scans_jsonl(scans_path)
    checks["scans_exists"] = scans_info["exists"]
    checks["scans_three_lines"] = scans_info["three_lines"]
    checks["scans_schema_valid"] = scans_info["schema_valid"]

    # Validate summary.csv
    summary_path = os.path.join(output_dir, "summary.csv")
    summary_info = validate_summary_csv(summary_path, scans_info, input_ideas)
    checks["summary_exists"] = summary_info["exists"]
    checks["summary_header_valid"] = summary_info["header_valid"]
    checks["summary_three_rows"] = summary_info["three_rows"]
    checks["summary_rows_valid"] = summary_info["rows_valid"]
    checks["summary_matches_scans"] = summary_info["matches_scans"]
    checks["order_matches_input"] = summary_info["order_matches_input"]

    # Validate comparison.md
    comparison_path = os.path.join(output_dir, "comparison.md")
    comparison_info = validate_comparison_md(comparison_path)
    checks["comparison_exists"] = comparison_info["exists"]
    checks["comparison_has_decision_rationale"] = comparison_info["has_decision_rationale"]
    checks["comparison_word_count_ge_120"] = comparison_info["word_count_ge_120"]
    checks["comparison_mentions_constraints"] = comparison_info["mentions_constraints"]

    # Validate privacy.txt
    privacy_path = os.path.join(output_dir, "privacy.txt")
    privacy_info = validate_privacy_txt(privacy_path)
    checks["privacy_exists"] = privacy_info["exists"]
    checks["privacy_mentions_required"] = privacy_info["mentions_required"]

    # Compute reward as proportion of passed checks
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    reward = 0.0
    if total_checks > 0:
        reward = passed / total_checks

    # Ensure baseline 0.0 if no output artifacts at all
    if not os.path.isdir(output_dir):
        reward = 0.0

    print(json.dumps({"reward": reward, **checks}))

if __name__ == "__main__":
    main()