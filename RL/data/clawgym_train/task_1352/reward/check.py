import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def read_json_file(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_csv_file(path: Path) -> Tuple[Optional[List[dict]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
            header = reader.fieldnames or []
            return rows, header
    except Exception:
        return None, None


def contains_exclamations(s: str) -> bool:
    if s is None:
        return False
    return ("!" in s) or ("¡" in s)


def approx_equal(a: float, b: float, tol: float = 0.5) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def parse_float(value) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def parse_int(value) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        s = str(value).strip()
        if s == "":
            return None
        if "." in s:
            f = float(s)
            if f.is_integer():
                return int(f)
            return None
        return int(s)
    except Exception:
        return None


def align_percent(value: float) -> Optional[float]:
    # If it's a fraction (0..1), convert to percent
    try:
        v = float(value)
        if 0.0 <= v <= 1.0:
            return v * 100.0
        return v
    except Exception:
        return None


def compute_group_metrics(cleaned_rows: List[dict], original_map: Dict[Tuple[str, str, str], dict], limits: dict) -> Dict[Tuple[str, str], dict]:
    groups: Dict[Tuple[str, str], List[dict]] = {}
    for r in cleaned_rows:
        key = (r["medium"], r["language"])
        groups.setdefault(key, []).append(r)

    result: Dict[Tuple[str, str], dict] = {}
    for key, rows in groups.items():
        medium, language = key
        limit = limits.get(medium)
        n = len(rows)
        char_counts = []
        within = 0
        reductions = []
        max_chars = 0
        for r in rows:
            cleaned_text = r.get("cleaned_text", "") or ""
            c = len(cleaned_text)
            char_counts.append(c)
            if limit is not None and c <= int(limit):
                within += 1
            if c > max_chars:
                max_chars = c
            orig = original_map.get((r["id"], r["medium"], r["language"]))
            if orig:
                otext = orig.get("text", "") or ""
                ocount = len(otext)
                if ocount > 0:
                    reductions.append((ocount - c) / ocount * 100.0)
        avg_chars = sum(char_counts) / n if n > 0 else 0.0
        avg_reduction = sum(reductions) / len(reductions) if reductions else 0.0
        pct_within = (within / n * 100.0) if n > 0 else 0.0
        result[key] = {
            "n_snippets": n,
            "avg_chars": avg_chars,
            "max_chars": max_chars,
            "pct_within_limit": pct_within,
            "avg_reduction_pct": avg_reduction,
        }
    return result


def compute_overall_metrics(cleaned_rows: List[dict], limits: dict) -> dict:
    total_snippets = len(cleaned_rows)
    total_chars = 0
    within = 0
    voiceover_words = 0
    for r in cleaned_rows:
        cleaned_text = r.get("cleaned_text", "") or ""
        c = len(cleaned_text)
        total_chars += c
        limit = limits.get(r["medium"])
        if limit is not None and c <= int(limit):
            within += 1
        if r["medium"] == "voiceover":
            # count words as sequences of non-whitespace
            voiceover_words += len(re.findall(r"\S+", cleaned_text))
    overall_pct_within = (within / total_snippets * 100.0) if total_snippets > 0 else 0.0
    # 150 wpm => 2.5 words per second => seconds = words / 2.5
    est_seconds = int(round(voiceover_words / 2.5)) if voiceover_words >= 0 else 0
    return {
        "total_snippets": total_snippets,
        "total_chars": total_chars,
        "overall_pct_within_limit": overall_pct_within,
        "voiceover_est_read_time_sec": est_seconds,
    }


def compute_violations(cleaned_rows: List[dict], limits: dict, forbid_excl: bool) -> List[dict]:
    violations = []
    for r in cleaned_rows:
        cleaned_text = r.get("cleaned_text", "") or ""
        char_count = len(cleaned_text)
        max_chars = int(limits.get(r["medium"])) if r["medium"] in limits else None
        ex_present = contains_exclamations(cleaned_text)
        if max_chars is not None and char_count > max_chars:
            violations.append({
                "id": r["id"],
                "medium": r["medium"],
                "language": r["language"],
                "violation_type": "char_limit",
                "char_count": char_count,
                "max_chars": max_chars,
                "exclamations_present": ex_present,
            })
        if forbid_excl and ex_present:
            violations.append({
                "id": r["id"],
                "medium": r["medium"],
                "language": r["language"],
                "violation_type": "exclamation",
                "char_count": char_count,
                "max_chars": max_chars if max_chars is not None else "",
                "exclamations_present": ex_present,
            })
    return violations


def compute_diffs(cleaned_rows: List[dict], original_map: Dict[Tuple[str, str, str], dict]) -> Dict[Tuple[str, str, str], dict]:
    diffs = {}
    for r in cleaned_rows:
        key = (r["id"], r["medium"], r["language"])
        cleaned_text = r.get("cleaned_text", "") or ""
        ccount = len(cleaned_text)
        orig = original_map.get(key)
        if not orig:
            continue
        otext = orig.get("text", "") or ""
        ocount = len(otext)
        reduction = ((ocount - ccount) / ocount * 100.0) if ocount > 0 else 0.0
        diffs[key] = {
            "original_char_count": ocount,
            "cleaned_char_count": ccount,
            "reduction_pct": reduction,
        }
    return diffs


def run_compute_script(workspace: Path) -> Tuple[bool, Optional[str]]:
    script_path = workspace / "scripts" / "compute_metrics.py"
    if not script_path.is_file():
        return False, "missing_script"
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            text=True,
        )
        return proc.returncode == 0, (proc.stdout + "\n" + proc.stderr)
    except Exception as e:
        return False, str(e)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "cleaned_exists_and_columns": 0.0,
        "cleaned_row_coverage": 0.0,
        "cleaned_char_limits_respected": 0.0,
        "cleaned_no_exclamations_when_forbidden": 0.0,
        "compute_script_exists": 0.0,
        "compute_script_runs": 0.0,
        "analytics_by_medium_schema_and_values": 0.0,
        "analytics_overall_schema_and_values": 0.0,
        "analytics_violations_schema_and_values": 0.0,
        "analytics_diffs_schema_and_values": 0.0,
        "analytics_run_log_command_and_timestamp": 0.0,
        "report_bullets_and_paragraph": 0.0,
        "report_includes_two_sample_pairs": 0.0,
    }

    # Load inputs
    input_csv_path = workspace / "input" / "bilingual_snippets.csv"
    limits_json_path = workspace / "input" / "length_limits.json"
    style_json_path = workspace / "input" / "style_rules.json"

    input_rows, input_header = read_csv_file(input_csv_path)
    limits = read_json_file(limits_json_path)
    style_rules = read_json_file(style_json_path)

    # Prepare mappings
    original_map: Dict[Tuple[str, str, str], dict] = {}
    input_ok = input_rows is not None and isinstance(limits, dict) and isinstance(style_rules, dict)
    if input_rows:
        for r in input_rows:
            key = (str(r.get("id", "")).strip(), str(r.get("medium", "")).strip(), str(r.get("language", "")).strip())
            original_map[key] = r

    # Check cleaned outputs
    cleaned_path = workspace / "outputs" / "clean" / "cleaned_snippets.csv"
    cleaned_rows, cleaned_header = read_csv_file(cleaned_path)

    expected_cleaned_header = ["id", "medium", "language", "cleaned_text"]
    if cleaned_rows is not None and cleaned_header == expected_cleaned_header:
        scores["cleaned_exists_and_columns"] = 1.0

    # cleaned row coverage
    if input_rows is not None and cleaned_rows is not None:
        input_keys = {(str(r.get("id", "")).strip(), str(r.get("medium", "")).strip(), str(r.get("language", "")).strip()) for r in input_rows}
        cleaned_keys = {(str(r.get("id", "")).strip(), str(r.get("medium", "")).strip(), str(r.get("language", "")).strip()) for r in cleaned_rows}
        if input_keys == cleaned_keys and len(cleaned_rows) == len(input_rows):
            scores["cleaned_row_coverage"] = 1.0

    # cleaned char limits
    if cleaned_rows is not None and isinstance(limits, dict):
        all_within = True
        for r in cleaned_rows:
            medium = str(r.get("medium", "")).strip()
            cleaned_text = r.get("cleaned_text", "") or ""
            if medium not in limits or not isinstance(limits[medium], (int, float)):
                all_within = False
                break
            if len(cleaned_text) > int(limits[medium]):
                all_within = False
                break
        scores["cleaned_char_limits_respected"] = 1.0 if all_within else 0.0

    # cleaned exclamations check
    if cleaned_rows is not None and isinstance(style_rules, dict):
        forbid = bool(style_rules.get("forbid_exclamation", False))
        if not forbid:
            scores["cleaned_no_exclamations_when_forbidden"] = 1.0
        else:
            none_have = True
            for r in cleaned_rows:
                cleaned_text = r.get("cleaned_text", "") or ""
                if contains_exclamations(cleaned_text):
                    none_have = False
                    break
            scores["cleaned_no_exclamations_when_forbidden"] = 1.0 if none_have else 0.0

    # scripts/compute_metrics.py existence and run
    script_path = workspace / "scripts" / "compute_metrics.py"
    if script_path.is_file():
        scores["compute_script_exists"] = 1.0
        ran, _out = run_compute_script(workspace)
        if ran:
            scores["compute_script_runs"] = 1.0

    # Analytics validations (schema and values)
    by_medium_path = workspace / "outputs" / "analytics" / "by_medium.csv"
    overall_path = workspace / "outputs" / "analytics" / "overall.csv"
    violations_path = workspace / "outputs" / "analytics" / "violations.csv"
    diffs_path = workspace / "outputs" / "analytics" / "diffs.csv"
    run_log_path = workspace / "outputs" / "analytics" / "run_log.txt"

    # by_medium.csv
    by_rows, by_header = read_csv_file(by_medium_path)
    expected_by_header = ["medium", "language", "n_snippets", "avg_chars", "max_chars", "pct_within_limit", "avg_reduction_pct"]
    if by_rows is not None and by_header == expected_by_header and cleaned_rows is not None and isinstance(limits, dict):
        # build expected map
        group_metrics = compute_group_metrics(cleaned_rows, original_map, limits)
        # build actual map
        actual_map = {}
        all_ok = True
        for r in by_rows:
            key = (str(r.get("medium", "")).strip(), str(r.get("language", "")).strip())
            try:
                actual_map[key] = {
                    "n_snippets": parse_int(r.get("n_snippets")),
                    "avg_chars": parse_float(r.get("avg_chars")),
                    "max_chars": parse_int(r.get("max_chars")),
                    "pct_within_limit": align_percent(parse_float(r.get("pct_within_limit")) if r.get("pct_within_limit") is not None else None),
                    "avg_reduction_pct": parse_float(r.get("avg_reduction_pct")),
                }
            except Exception:
                all_ok = False
                break
        if set(actual_map.keys()) == set(group_metrics.keys()) and all_ok:
            for key, expected in group_metrics.items():
                actual = actual_map[key]
                if actual["n_snippets"] != expected["n_snippets"]:
                    all_ok = False
                    break
                if actual["max_chars"] != expected["max_chars"]:
                    all_ok = False
                    break
                if not approx_equal(actual["avg_chars"], expected["avg_chars"], tol=1.0):
                    all_ok = False
                    break
                if actual["pct_within_limit"] is None or not approx_equal(actual["pct_within_limit"], expected["pct_within_limit"], tol=1.0):
                    all_ok = False
                    break
                if not approx_equal(actual["avg_reduction_pct"], expected["avg_reduction_pct"], tol=2.0):
                    all_ok = False
                    break
            if all_ok:
                scores["analytics_by_medium_schema_and_values"] = 1.0

    # overall.csv
    overall_rows, overall_header = read_csv_file(overall_path)
    expected_overall_header = ["total_snippets", "total_chars", "overall_pct_within_limit", "voiceover_est_read_time_sec"]
    if overall_rows is not None and overall_header == expected_overall_header and cleaned_rows is not None and isinstance(limits, dict):
        if len(overall_rows) == 1:
            row = overall_rows[0]
            expected_overall = compute_overall_metrics(cleaned_rows, limits)
            total_snippets = parse_int(row.get("total_snippets"))
            total_chars = parse_int(row.get("total_chars"))
            pct = align_percent(parse_float(row.get("overall_pct_within_limit")))
            vs = parse_int(row.get("voiceover_est_read_time_sec"))
            ok = True
            if total_snippets != expected_overall["total_snippets"]:
                ok = False
            if total_chars != expected_overall["total_chars"]:
                ok = False
            if pct is None or not approx_equal(pct, expected_overall["overall_pct_within_limit"], tol=1.0):
                ok = False
            if vs is None or abs(vs - expected_overall["voiceover_est_read_time_sec"]) > 1:
                ok = False
            if ok:
                scores["analytics_overall_schema_and_values"] = 1.0

    # violations.csv
    vio_rows, vio_header = read_csv_file(violations_path)
    expected_vio_header = ["id", "medium", "language", "violation_type", "char_count", "max_chars", "exclamations_present"]
    if vio_rows is not None and vio_header == expected_vio_header and cleaned_rows is not None and isinstance(limits, dict) and isinstance(style_rules, dict):
        expected_vios = compute_violations(cleaned_rows, limits, bool(style_rules.get("forbid_exclamation", False)))
        def norm_bool(x):
            if isinstance(x, bool):
                return x
            s = str(x).strip().lower()
            return s in ("true", "1", "yes", "y")
        def norm_row(r):
            return (
                str(r["id"]).strip(),
                str(r["medium"]).strip(),
                str(r["language"]).strip(),
                str(r["violation_type"]).strip(),
                parse_int(r["char_count"]),
                parse_int(r["max_chars"]) if str(r["max_chars"]).strip() != "" else None,
                norm_bool(r["exclamations_present"]),
            )
        actual_set = set()
        for r in vio_rows:
            t = norm_row(r)
            actual_set.add(t)
        expected_set = set()
        for r in expected_vios:
            t = (
                str(r["id"]).strip(),
                str(r["medium"]).strip(),
                str(r["language"]).strip(),
                str(r["violation_type"]).strip(),
                int(r["char_count"]),
                int(r["max_chars"]) if r["max_chars"] is not None and str(r["max_chars"]) != "" else None,
                bool(r["exclamations_present"]),
            )
            expected_set.add(t)
        if actual_set == expected_set:
            scores["analytics_violations_schema_and_values"] = 1.0

    # diffs.csv
    diffs_rows, diffs_header = read_csv_file(diffs_path)
    expected_diffs_header = ["id", "medium", "language", "original_char_count", "cleaned_char_count", "reduction_pct"]
    if diffs_rows is not None and diffs_header == expected_diffs_header and cleaned_rows is not None:
        expected_diffs = compute_diffs(cleaned_rows, original_map)
        # Build actual map
        actual_map = {}
        bad = False
        for r in diffs_rows:
            key = (str(r.get("id", "")).strip(), str(r.get("medium", "")).strip(), str(r.get("language", "")).strip())
            occ = parse_int(r.get("original_char_count"))
            ccc = parse_int(r.get("cleaned_char_count"))
            red = parse_float(r.get("reduction_pct"))
            if occ is None or ccc is None or red is None:
                bad = True
                break
            actual_map[key] = {"original_char_count": occ, "cleaned_char_count": ccc, "reduction_pct": red}
        if not bad and set(actual_map.keys()) == set(expected_diffs.keys()):
            ok = True
            for key, expected in expected_diffs.items():
                actual = actual_map[key]
                if actual["original_char_count"] != expected["original_char_count"]:
                    ok = False
                    break
                if actual["cleaned_char_count"] != expected["cleaned_char_count"]:
                    ok = False
                    break
                if not approx_equal(actual["reduction_pct"], expected["reduction_pct"], tol=1.0):
                    ok = False
                    break
            if ok:
                scores["analytics_diffs_schema_and_values"] = 1.0

    # run_log.txt
    try:
        text = run_log_path.read_text(encoding="utf-8")
        has_cmd = "compute_metrics.py" in text
        # naive timestamp check: YYYY-MM-DD present
        has_ts = re.search(r"\d{4}-\d{2}-\d{2}", text) is not None
        if has_cmd and has_ts:
            scores["analytics_run_log_command_and_timestamp"] = 1.0
    except Exception:
        pass

    # report/status_update.md
    report_path = workspace / "outputs" / "report" / "status_update.md"
    try:
        md = report_path.read_text(encoding="utf-8")
        # bullet points 3-5
        bullet_lines = [line for line in md.splitlines() if line.strip().startswith("- ") or line.strip().startswith("* ")]
        has_bullets = 3 <= len(bullet_lines) <= 5
        # paragraph at least 50 characters (non-bullet, non-empty)
        non_bullet_lines = [line for line in md.splitlines() if line.strip() and not (line.strip().startswith("- ") or line.strip().startswith("* "))]
        has_paragraph = any(len(line.strip()) >= 50 for line in non_bullet_lines)
        if has_bullets and has_paragraph:
            scores["report_bullets_and_paragraph"] = 1.0

        # two sample pairs: pick any two ids present in both original and cleaned
        sample_ok = False
        if cleaned_rows is not None and input_rows is not None:
            # build maps for quick access
            cleaned_map = {(str(r["id"]).strip(), str(r["language"]).strip()): r for r in cleaned_rows}
            input_map = {(str(r["id"]).strip(), str(r["language"]).strip()): r for r in input_rows}
            unique_ids = sorted({str(r["id"]).strip() for r in cleaned_rows})
            # find two ids with both en and es in both maps
            chosen_ids = []
            for uid in unique_ids:
                if (uid, "en") in cleaned_map and (uid, "es") in cleaned_map and (uid, "en") in input_map and (uid, "es") in input_map:
                    chosen_ids.append(uid)
                if len(chosen_ids) >= 2:
                    break
            if len(chosen_ids) >= 2:
                all_found = True
                for uid in chosen_ids[:2]:
                    for lang in ["en", "es"]:
                        orig_text = (input_map[(uid, lang)].get("text") or "")
                        cleaned_text = (cleaned_map[(uid, lang)].get("cleaned_text") or "")
                        orig_trunc = orig_text[:100]
                        cleaned_trunc = cleaned_text[:100]
                        if orig_trunc not in md or cleaned_trunc not in md:
                            all_found = False
                            break
                    if not all_found:
                        break
                if all_found:
                    sample_ok = True
        if sample_ok:
            scores["report_includes_two_sample_pairs"] = 1.0
    except Exception:
        pass

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()