import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# Detection regex patterns
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")
DOB_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
IP_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
)
ADDRESS_RE = re.compile(
    r"\b\d+\s+[A-Za-z0-9.\- ]+\s(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court)\s*,\s*[A-Za-z .\-]+,\s*[A-Z]{2}\s+\d{5}\b",
    re.IGNORECASE,
)

WEIGHTS = {
    "email": 1,
    "phone": 1,
    "ip": 1,
    "address": 2,
    "dob": 3,
    "ssn": 5,
}

ALLOWED_TYPES = {"email", "phone", "dob", "ssn", "address", "ip"}


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _normalize_rel_path_str(path_str: str, workspace: Path) -> str:
    try:
        p = Path(path_str)
        try:
            if p.is_absolute():
                rel = p.relative_to(workspace)
                p = rel
        except Exception:
            pass
        s = p.as_posix()
        if s.startswith("./"):
            s = s[2:]
        return s
    except Exception:
        return path_str


def _scan_text_for_counts(text: str) -> Dict[str, int]:
    counts = {
        "email": 0,
        "phone": 0,
        "dob": 0,
        "ssn": 0,
        "address": 0,
        "ip": 0,
    }
    counts["email"] = len(EMAIL_RE.findall(text))
    counts["phone"] = len(PHONE_RE.findall(text))
    counts["dob"] = len(DOB_RE.findall(text))
    counts["ssn"] = len(SSN_RE.findall(text))
    counts["ip"] = len(IP_RE.findall(text))
    counts["address"] = len(ADDRESS_RE.findall(text))
    return counts


def _gather_input_files(workspace: Path) -> List[Path]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []
    files: List[Path] = []
    for p in input_dir.rglob("*"):
        if p.is_file():
            try:
                rel = p.relative_to(input_dir)
                parts = rel.parts
                if len(parts) > 0 and parts[0] == "test":
                    continue
            except Exception:
                pass
            files.append(p)
    return files


def _compute_expected(workspace: Path) -> Tuple[Dict[str, Dict[str, int]], Dict[str, int], Dict[str, int], Dict[str, int]]:
    expected_counts_by_file: Dict[str, Dict[str, int]] = {}
    expected_risk_by_file: Dict[str, int] = {}
    files = _gather_input_files(workspace)
    for f in files:
        text = _safe_read_text(f)
        if text is None:
            counts = {k: 0 for k in ["email", "phone", "dob", "ssn", "address", "ip"]}
        else:
            counts = _scan_text_for_counts(text)
        rel_str = f.relative_to(workspace).as_posix()
        expected_counts_by_file[rel_str] = counts
        risk = (
            counts["email"] * WEIGHTS["email"]
            + counts["phone"] * WEIGHTS["phone"]
            + counts["ip"] * WEIGHTS["ip"]
            + counts["address"] * WEIGHTS["address"]
            + counts["dob"] * WEIGHTS["dob"]
            + counts["ssn"] * WEIGHTS["ssn"]
        )
        expected_risk_by_file[rel_str] = risk

    totals = {
        "emails": 0,
        "phones": 0,
        "dobs": 0,
        "ssns": 0,
        "addresses": 0,
        "ips": 0,
        "total_matches": 0,
    }
    for counts in expected_counts_by_file.values():
        totals["emails"] += counts.get("email", 0)
        totals["phones"] += counts.get("phone", 0)
        totals["dobs"] += counts.get("dob", 0)
        totals["ssns"] += counts.get("ssn", 0)
        totals["addresses"] += counts.get("address", 0)
        totals["ips"] += counts.get("ip", 0)
    totals["total_matches"] = (
        totals["emails"]
        + totals["phones"]
        + totals["dobs"]
        + totals["ssns"]
        + totals["addresses"]
        + totals["ips"]
    )

    test_file = workspace / "input" / "test" / "test_cases.jsonl"
    test_totals = {
        "emails": 0,
        "phones": 0,
        "dobs": 0,
        "ssns": 0,
        "addresses": 0,
        "ips": 0,
        "total_matches": 0,
    }
    if test_file.exists():
        try:
            with test_file.open("r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    text = obj.get("text", "")
                    counts = _scan_text_for_counts(text)
                    test_totals["emails"] += counts["email"]
                    test_totals["phones"] += counts["phone"]
                    test_totals["dobs"] += counts["dob"]
                    test_totals["ssns"] += counts["ssn"]
                    test_totals["addresses"] += counts["address"]
                    test_totals["ips"] += counts["ip"]
            test_totals["total_matches"] = (
                test_totals["emails"]
                + test_totals["phones"]
                + test_totals["dobs"]
                + test_totals["ssns"]
                + test_totals["addresses"]
                + test_totals["ips"]
            )
        except Exception:
            pass

    return expected_counts_by_file, totals, expected_risk_by_file, test_totals


def _parse_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        items: List[dict] = []
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            for idx, line in enumerate(fh, 1):
                s = line.strip()
                if not s:
                    continue
                obj = json.loads(s)
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _parse_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None


def _parse_overall_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as fh:
            return json.load(fh)
    except Exception:
        return None


def _parse_validation_report(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def _extract_int_after_keyword(text: str, keyword: str) -> Optional[int]:
    pattern = re.compile(rf"{re.escape(keyword)}\s*[:=]\s*(\d+)", flags=re.IGNORECASE)
    m = pattern.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "matches_jsonl_counts_match_expected": 0.0,
        "matches_jsonl_present_and_valid_jsonl": 0.0,
        "matches_jsonl_types_and_fields_valid": 0.0,
        "overall_stats_json_exists_and_valid_structure": 0.0,
        "overall_stats_totals_and_max_risk_correct": 0.0,
        "summary_csv_counts_correct": 0.0,
        "summary_csv_exists_and_header": 0.0,
        "validation_report_case_totals_correct": 0.0,
        "validation_report_present_and_has_command": 0.0,
    }

    expected_counts_by_file, expected_totals, expected_risk_by_file, test_totals = _compute_expected(workspace)

    matches_path = workspace / "output" / "matches.jsonl"
    matches_items = None
    if matches_path.exists():
        matches_items = _parse_jsonl(matches_path)
        if matches_items is not None and isinstance(matches_items, list) and len(matches_items) >= 0:
            scores["matches_jsonl_present_and_valid_jsonl"] = 1.0

    if matches_items is not None:
        valid_fields = True
        for obj in matches_items:
            if not isinstance(obj, dict):
                valid_fields = False
                break
            if not all(k in obj for k in ("file_path", "context", "type", "value")):
                valid_fields = False
                break
            if obj.get("type") not in ALLOWED_TYPES:
                valid_fields = False
                break
        if valid_fields:
            scores["matches_jsonl_types_and_fields_valid"] = 1.0

    if matches_items is not None:
        agg: Dict[str, Dict[str, int]] = {}
        for obj in matches_items:
            fp_raw = str(obj.get("file_path", ""))
            fp_norm = _normalize_rel_path_str(fp_raw, workspace)
            if fp_norm not in expected_counts_by_file:
                continue
            t = obj.get("type")
            if t not in ALLOWED_TYPES:
                continue
            agg.setdefault(fp_norm, {}).setdefault(t, 0)
            agg[fp_norm][t] += 1
        mismatch = False
        for fp, counts in expected_counts_by_file.items():
            file_counts = agg.get(fp, {})
            for t_key, expected_count in counts.items():
                actual = file_counts.get(t_key, 0)
                if actual != expected_count:
                    mismatch = True
                    break
            if mismatch:
                break
        if not mismatch and len(expected_counts_by_file) > 0:
            scores["matches_jsonl_counts_match_expected"] = 1.0
        elif not mismatch and len(expected_counts_by_file) == 0:
            total_entries = sum(sum(v.values()) for v in agg.values()) if agg else 0
            if total_entries == 0:
                scores["matches_jsonl_counts_match_expected"] = 1.0

    summary_path = workspace / "output" / "summary.csv"
    summary_rows = None
    if summary_path.exists():
        summary_rows = _parse_summary_csv(summary_path)
        try:
            with summary_path.open("r", encoding="utf-8", errors="ignore") as fh:
                header_line = fh.readline().strip()
            expected_header = "file_path,emails,phones,dobs,ssns,addresses,ips,total_matches,risk_score"
            if header_line == expected_header and summary_rows is not None:
                scores["summary_csv_exists_and_header"] = 1.0
        except Exception:
            pass

    if summary_rows is not None:
        row_map: Dict[str, Dict[str, str]] = {}
        for row in summary_rows:
            fp_raw = row.get("file_path", "")
            fp_norm = _normalize_rel_path_str(fp_raw, workspace)
            row_map[fp_norm] = row

        perfile_ok = True
        for fp, counts in expected_counts_by_file.items():
            row = row_map.get(fp)
            if row is None:
                perfile_ok = False
                break
            try:
                emails = int(row.get("emails", "0"))
                phones = int(row.get("phones", "0"))
                dobs = int(row.get("dobs", "0"))
                ssns = int(row.get("ssns", "0"))
                addresses = int(row.get("addresses", "0"))
                ips = int(row.get("ips", "0"))
                total_matches = int(row.get("total_matches", "0"))
                risk_score = int(float(row.get("risk_score", "0")))
            except Exception:
                perfile_ok = False
                break
            if emails != counts["email"]:
                perfile_ok = False
                break
            if phones != counts["phone"]:
                perfile_ok = False
                break
            if dobs != counts["dob"]:
                perfile_ok = False
                break
            if ssns != counts["ssn"]:
                perfile_ok = False
                break
            if addresses != counts["address"]:
                perfile_ok = False
                break
            if ips != counts["ip"]:
                perfile_ok = False
                break
            if total_matches != (emails + phones + dobs + ssns + addresses + ips):
                perfile_ok = False
                break
            expected_risk = (
                emails * WEIGHTS["email"]
                + phones * WEIGHTS["phone"]
                + ips * WEIGHTS["ip"]
                + addresses * WEIGHTS["address"]
                + dobs * WEIGHTS["dob"]
                + ssns * WEIGHTS["ssn"]
            )
            if risk_score != expected_risk:
                perfile_ok = False
                break
        if perfile_ok and len(expected_counts_by_file) > 0:
            scores["summary_csv_counts_correct"] = 1.0
        elif perfile_ok and len(expected_counts_by_file) == 0:
            if isinstance(summary_rows, list) and len(summary_rows) == 0:
                scores["summary_csv_counts_correct"] = 1.0

    overall_path = workspace / "output" / "overall_stats.json"
    overall_obj = None
    if overall_path.exists():
        overall_obj = _parse_overall_json(overall_path)
        if isinstance(overall_obj, dict):
            totals_obj = overall_obj.get("totals")
            file_with_max_risk = overall_obj.get("file_with_max_risk")
            max_risk_score = overall_obj.get("max_risk_score")
            if (
                isinstance(totals_obj, dict)
                and all(k in totals_obj for k in ["emails", "phones", "dobs", "ssns", "addresses", "ips", "total_matches"])
                and isinstance(file_with_max_risk, (str, type(None)))
                and (isinstance(max_risk_score, (int, float)) or max_risk_score is None)
            ):
                scores["overall_stats_json_exists_and_valid_structure"] = 1.0

    if overall_obj is not None and scores["overall_stats_json_exists_and_valid_structure"] > 0:
        totals_obj = overall_obj.get("totals", {})
        expected_variant_1 = expected_totals
        expected_variant_2 = {
            "emails": expected_totals["emails"] + test_totals["emails"],
            "phones": expected_totals["phones"] + test_totals["phones"],
            "dobs": expected_totals["dobs"] + test_totals["dobs"],
            "ssns": expected_totals["ssns"] + test_totals["ssns"],
            "addresses": expected_totals["addresses"] + test_totals["addresses"],
            "ips": expected_totals["ips"] + test_totals["ips"],
            "total_matches": expected_totals["total_matches"] + test_totals["total_matches"],
        }

        def totals_match(a: dict, b: dict) -> bool:
            for k in ["emails", "phones", "dobs", "ssns", "addresses", "ips", "total_matches"]:
                if int(a.get(k, 0)) != int(b.get(k, 0)):
                    return False
            return True

        totals_ok = totals_match(totals_obj, expected_variant_1) or totals_match(totals_obj, expected_variant_2)

        if expected_risk_by_file:
            max_file = max(expected_risk_by_file.keys(), key=lambda k: expected_risk_by_file[k])
            max_score = expected_risk_by_file[max_file]
        else:
            max_file = None
            max_score = 0

        file_with_max_risk = overall_obj.get("file_with_max_risk")
        max_risk_score = overall_obj.get("max_risk_score")

        if isinstance(file_with_max_risk, str):
            file_with_max_risk_norm = _normalize_rel_path_str(file_with_max_risk, workspace)
        else:
            file_with_max_risk_norm = file_with_max_risk

        max_ok = True
        if max_file is not None:
            if file_with_max_risk_norm != max_file:
                max_ok = False
            try:
                if int(max_risk_score) != int(max_score):
                    max_ok = False
            except Exception:
                max_ok = False
        else:
            if file_with_max_risk_norm not in (None, "", "None"):
                max_ok = False
            try:
                if int(max_risk_score) != 0:
                    max_ok = False
            except Exception:
                max_ok = False

        if totals_ok and max_ok:
            scores["overall_stats_totals_and_max_risk_correct"] = 1.0

    val_path = workspace / "output" / "validation_report.txt"
    val_text = None
    if val_path.exists():
        val_text = _parse_validation_report(val_path)
        if isinstance(val_text, str) and len(val_text) > 0:
            has_command = re.search(r"\bcommand\b", val_text, flags=re.IGNORECASE) is not None
            cases_total = _extract_int_after_keyword(val_text, "cases_total")
            cases_passed = _extract_int_after_keyword(val_text, "cases_passed")
            cases_failed = _extract_int_after_keyword(val_text, "cases_failed")
            if has_command and cases_total is not None and cases_passed is not None and cases_failed is not None:
                scores["validation_report_present_and_has_command"] = 1.0

    if val_text is not None:
        test_file = workspace / "input" / "test" / "test_cases.jsonl"
        expected_cases_total = 0
        expected_cases_passed = 0
        expected_cases_failed = 0
        if test_file.exists():
            try:
                with test_file.open("r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            expected_cases_total += 1
                            expected_cases_failed += 1
                            continue
                        expected_cases_total += 1
                        text = obj.get("text", "")
                        expected_matches = obj.get("expected_matches", {})
                        counts = _scan_text_for_counts(text)
                        keys = ["email", "phone", "dob", "ssn", "ip"]
                        ok = True
                        for k in keys:
                            exp = int(expected_matches.get(k, 0))
                            if counts.get(k, 0) != exp:
                                ok = False
                                break
                        if ok:
                            expected_cases_passed += 1
                        else:
                            expected_cases_failed += 1
            except Exception:
                pass

        reported_total = _extract_int_after_keyword(val_text, "cases_total")
        reported_passed = _extract_int_after_keyword(val_text, "cases_passed")
        reported_failed = _extract_int_after_keyword(val_text, "cases_failed")
        if (
            reported_total is not None
            and reported_passed is not None
            and reported_failed is not None
            and reported_total == expected_cases_total
            and reported_passed == expected_cases_passed
            and reported_failed == expected_cases_failed
        ):
            scores["validation_report_case_totals_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()