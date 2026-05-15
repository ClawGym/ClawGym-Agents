import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_lines(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read().splitlines()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return rows
    except Exception:
        return None


def _csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            return header
    except Exception:
        return None


def _sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso_mapping(obj: object) -> bool:
    if not isinstance(obj, dict):
        return False
    sample_keys = [k for k in obj.keys() if isinstance(k, str) and len(k) == 2 and k.upper() == k]
    sample_vals = [obj.get(k) for k in sample_keys[:10]]
    if len(sample_keys) < 3:
        return False
    if not all(isinstance(v, str) and len(v.strip()) > 0 for v in sample_vals if v is not None):
        return False
    return True


def _compute_expected_from_fixtures(fixtures_path: Path, iso_map: Optional[Dict[str, str]]) -> Tuple[Optional[Dict[str, Dict[str, str]]], Optional[Dict[str, Dict[str, object]]], Optional[Dict[str, int]]]:
    rows = _parse_csv_dicts(fixtures_path)
    if rows is None:
        return None, None, None
    enriched = {}
    summary = {}
    unmapped: Dict[str, int] = {}
    for r in rows:
        rid = r.get("review_id", "")
        code = r.get("country_code", "")
        platform = r.get("platform", "")
        rating_str = r.get("rating", "")
        try:
            rating = float(rating_str)
        except Exception:
            rating = None
        cname = ""
        if isinstance(iso_map, dict):
            cn = iso_map.get(code)
            if isinstance(cn, str):
                cname = cn
            else:
                cname = ""
        if isinstance(iso_map, dict):
            if code not in iso_map:
                unmapped[code] = unmapped.get(code, 0) + 1
        else:
            unmapped = {}
        enriched[rid] = {
            "review_id": r.get("review_id", ""),
            "platform": platform,
            "country_code": code,
            "rating": r.get("rating", ""),
            "review_text": r.get("review_text", ""),
            "country_name": cname,
        }
        if code not in summary:
            summary[code] = {
                "country_code": code,
                "country_name": cname,
                "ratings": [],
                "ios_reviews": 0,
                "android_reviews": 0,
            }
        if rating is not None:
            summary[code]["ratings"].append(rating)
        if platform == "ios":
            summary[code]["ios_reviews"] += 1
        if platform == "android":
            summary[code]["android_reviews"] += 1
    finalized = {}
    for code, d in summary.items():
        ratings = d["ratings"]
        total_reviews = len(ratings)
        avg = round(sum(ratings) / total_reviews, 2) if total_reviews > 0 else 0.0
        finalized[code] = {
            "country_code": d["country_code"],
            "country_name": d["country_name"],
            "total_reviews": total_reviews,
            "avg_rating": f"{avg:.2f}",
            "ios_reviews": d["ios_reviews"],
            "android_reviews": d["android_reviews"],
        }
    return enriched, finalized, unmapped if isinstance(iso_map, dict) else None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "iso_cache_exists": 0.0,
        "iso_cache_json_valid": 0.0,
        "iso_cache_looks_like_mapping": 0.0,
        "enriched_file_exists": 0.0,
        "enriched_header_correct": 0.0,
        "enriched_input_fields_preserved": 0.0,
        "enriched_country_name_correct": 0.0,
        "summary_file_exists": 0.0,
        "summary_header_correct": 0.0,
        "summary_unique_country_count_matches": 0.0,
        "summary_numeric_aggregates_correct": 0.0,
        "summary_country_names_consistent": 0.0,
        "unmapped_file_exists_and_header": 0.0,
        "unmapped_codes_correct": 0.0,
        "log_contains_single_sha_entry": 0.0,
        "validation_command_present": 0.0,
        "validator_checks_for_cache": 0.0,
        "validator_invokes_processing": 0.0,
        "validator_copies_fixture": 0.0,
        "validator_checks_headers": 0.0,
        "validator_checks_unique_country_count": 0.0,
        "validator_log_sha_check": 0.0,
        "validator_writes_report": 0.0,
        "validator_exits_nonzero_on_failure": 0.0,
        "runner_script_present": 0.0,
    }

    fixtures_csv = workspace / "fixtures" / "reviews_batch_01.csv"
    iso_cache_path = workspace / "cache" / "iso3166.json"
    enriched_path = workspace / "output" / "processed" / "reviews_batch_01.enriched.csv"
    summary_path = workspace / "output" / "summary" / "by_country_reviews_batch_01.csv"
    unmapped_path = workspace / "output" / "unmapped_country_codes.csv"
    log_path = workspace / "output" / "logs" / "automation.log"
    validate_sh = workspace / "scripts" / "validate.sh"
    validate_py = workspace / "scripts" / "validate.py"

    fixtures_sha = _sha256_file(fixtures_csv) if fixtures_csv.exists() else None

    iso_obj = None
    if iso_cache_path.exists() and iso_cache_path.is_file():
        scores["iso_cache_exists"] = 1.0
        iso_obj = _load_json(iso_cache_path)
        if iso_obj is not None:
            scores["iso_cache_json_valid"] = 1.0
            if _is_iso_mapping(iso_obj):
                scores["iso_cache_looks_like_mapping"] = 1.0

    iso_map = iso_obj if isinstance(iso_obj, dict) else None
    enriched_expected, summary_expected, unmapped_expected = _compute_expected_from_fixtures(fixtures_csv, iso_map)

    if enriched_path.exists() and enriched_path.is_file():
        scores["enriched_file_exists"] = 1.0
        header = _csv_header(enriched_path)
        if header == ["review_id", "platform", "country_code", "rating", "review_text", "country_name"]:
            scores["enriched_header_correct"] = 1.0
        enr_rows = _parse_csv_dicts(enriched_path) or []
        fx_rows = _parse_csv_dicts(fixtures_csv) or []
        fx_by_id = {r.get("review_id", ""): r for r in fx_rows}
        preserved_ok = True
        for r in enr_rows:
            rid = r.get("review_id", "")
            orig = fx_by_id.get(rid)
            if orig is None:
                preserved_ok = False
                break
            for col in ["review_id", "platform", "country_code", "rating", "review_text"]:
                if r.get(col, "") != orig.get(col, ""):
                    preserved_ok = False
                    break
            if not preserved_ok:
                break
        if preserved_ok and len(enr_rows) == len(fx_rows) and len(fx_rows) > 0:
            scores["enriched_input_fields_preserved"] = 1.0
        if enriched_expected is not None and isinstance(iso_map, dict):
            cn_ok = True
            for r in enr_rows:
                rid = r.get("review_id", "")
                exp = enriched_expected.get(rid)
                if exp is None:
                    cn_ok = False
                    break
                if r.get("country_name", "") != exp.get("country_name", ""):
                    cn_ok = False
                    break
            if cn_ok:
                scores["enriched_country_name_correct"] = 1.0

    if summary_path.exists() and summary_path.is_file():
        scores["summary_file_exists"] = 1.0
        header = _csv_header(summary_path)
        expected_summary_header = ["country_code", "country_name", "total_reviews", "avg_rating", "ios_reviews", "android_reviews"]
        if header == expected_summary_header:
            scores["summary_header_correct"] = 1.0
        sum_rows = _parse_csv_dicts(summary_path) or []
        if fixtures_csv.exists():
            fx_rows = _parse_csv_dicts(fixtures_csv) or []
            uniq_codes = sorted({r.get("country_code", "") for r in fx_rows if r.get("country_code", "") != ""})
            if len(sum_rows) == len(uniq_codes) and len(uniq_codes) > 0:
                scores["summary_unique_country_count_matches"] = 1.0
        if summary_expected is not None:
            actual_by_code: Dict[str, Dict[str, str]] = {r.get("country_code", ""): r for r in sum_rows}
            numeric_ok = True
            for code, exp in summary_expected.items():
                act = actual_by_code.get(code)
                if act is None:
                    numeric_ok = False
                    break
                if str(act.get("total_reviews", "")).strip() != str(exp["total_reviews"]):
                    numeric_ok = False
                    break
                act_avg_str = str(act.get("avg_rating", "")).strip()
                if act_avg_str != exp["avg_rating"]:
                    numeric_ok = False
                    break
                if str(act.get("ios_reviews", "")).strip() != str(exp["ios_reviews"]):
                    numeric_ok = False
                    break
                if str(act.get("android_reviews", "")).strip() != str(exp["android_reviews"]):
                    numeric_ok = False
                    break
            if numeric_ok:
                scores["summary_numeric_aggregates_correct"] = 1.0
        consistency_ok = True
        if sum_rows:
            for r in sum_rows:
                code = r.get("country_code", "")
                name = r.get("country_name", "")
                expected_name = None
                if isinstance(iso_map, dict):
                    expected_name = iso_map.get(code, "")
                elif enriched_path.exists():
                    enr_rows = _parse_csv_dicts(enriched_path) or []
                    names = {er.get("country_name", "") for er in enr_rows if er.get("country_code", "") == code}
                    expected_name = list(names)[0] if names else ""
                if expected_name is not None:
                    if name != expected_name:
                        consistency_ok = False
                        break
        if consistency_ok and sum_rows:
            scores["summary_country_names_consistent"] = 1.0

    if unmapped_path.exists() and unmapped_path.is_file():
        header = _csv_header(unmapped_path)
        if header == ["country_code", "count"]:
            scores["unmapped_file_exists_and_header"] = 1.0
            if unmapped_expected is not None and fixtures_csv.exists():
                rows = _parse_csv_dicts(unmapped_path) or []
                actual = {r.get("country_code", ""): int(str(r.get("count", "0")).strip() or "0") for r in rows if r.get("country_code", "") != ""}
                if actual == unmapped_expected:
                    scores["unmapped_codes_correct"] = 1.0
                elif not unmapped_expected and not actual and len(rows) == 0:
                    scores["unmapped_codes_correct"] = 1.0

    if log_path.exists() and log_path.is_file() and fixtures_sha:
        lines = _read_lines(log_path) or []
        sha_lines = [ln for ln in lines if fixtures_sha in ln]
        if len(sha_lines) == 1:
            line = sha_lines[0]
            has_filename = "reviews_batch_01.csv" in line
            has_ts = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line) is not None
            has_total = "8" in line
            if has_filename and has_ts and has_total:
                scores["log_contains_single_sha_entry"] = 1.0

    validator_path = None
    validator_content = None
    if validate_sh.exists():
        validator_path = validate_sh
    elif validate_py.exists():
        validator_path = validate_py
    if validator_path is not None and validator_path.is_file():
        scores["validation_command_present"] = 1.0
        validator_content = _read_text(validator_path) or ""
        content_lower = validator_content.lower()

        if "cache/iso3166.json" in validator_content:
            scores["validator_checks_for_cache"] = 1.0

        invokes = False
        if ("scripts/" in validator_content and ("run" in content_lower or "watch" in content_lower or "process" in content_lower)) or ("python" in content_lower and ("run" in content_lower or "watch" in content_lower or "process" in content_lower)):
            invokes = True
        if invokes:
            scores["validator_invokes_processing"] = 1.0

        copies = ("fixtures/reviews_batch_01.csv" in validator_content and "input/incoming" in validator_content and ("cp " in validator_content or "copy " in content_lower or "shutil.copy" in content_lower))
        if copies:
            scores["validator_copies_fixture"] = 1.0

        header_enriched_str = "review_id,platform,country_code,rating,review_text,country_name"
        header_summary_str = "country_code,country_name,total_reviews,avg_rating,ios_reviews,android_reviews"
        if (header_enriched_str in validator_content) and (header_summary_str in validator_content):
            scores["validator_checks_headers"] = 1.0

        unique_check = False
        if "by_country_reviews_batch_01.csv" in validator_content:
            if ("uniq" in content_lower or "sort -u" in content_lower or "awk" in content_lower or "cut" in content_lower or "set(" in content_lower):
                unique_check = True
        if unique_check:
            scores["validator_checks_unique_country_count"] = 1.0

        if (("sha256sum" in content_lower) or ("shasum -a 256" in content_lower) or ("hashlib.sha256" in content_lower)) and ("output/logs/automation.log" in validator_content):
            scores["validator_log_sha_check"] = 1.0

        if "output/validation/report.txt" in validator_content:
            scores["validator_writes_report"] = 1.0

        if ("exit 1" in content_lower) or ("sys.exit(1)" in content_lower):
            scores["validator_exits_nonzero_on_failure"] = 1.0

    runner_present = False
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        for p in scripts_dir.rglob("*"):
            if p.is_file() and p.name not in ("validate.sh", "validate.py"):
                name_lower = p.name.lower()
                if any(k in name_lower for k in ["run", "watch", "process", "automation", "runner"]):
                    content = _read_text(p) or ""
                    if "input/incoming" in content and ("output/processed" in content or "output/summary" in content or "output/logs" in content):
                        runner_present = True
                        break
    if runner_present:
        scores["runner_script_present"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()