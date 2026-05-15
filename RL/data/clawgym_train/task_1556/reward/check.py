import json
import csv
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List, Dict


ALLOWED_ISSUES = {
    "asset_missing",
    "rights_unknown",
    "license_missing",
    "missing_image_attribution",
    "audio_without_license",
    "marketing_claim_conflict",
}
SEVERITY_MAP = {
    "asset_missing": "high",
    "rights_unknown": "high",
    "audio_without_license": "high",
    "license_missing": "medium",
    "missing_image_attribution": "medium",
    "marketing_claim_conflict": "high",
}
CSV_COLUMNS = [
    "record_id",
    "title",
    "asset_path",
    "asset_type",
    "declared_rights",
    "issues",
    "severity",
]


def _read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_csv_safe(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _extract_section(text: str, title: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    start_level = None
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*(#+)\s+(.*?)\s*$", line)
        if m:
            level = len(m.group(1))
            heading_title = m.group(2).strip()
            if heading_title == title:
                start_idx = idx + 1
                start_level = level
                break
    if start_idx is None:
        return None
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        m = re.match(r"^\s*(#+)\s+(.*?)\s*$", lines[idx])
        if m:
            level = len(m.group(1))
            if level <= start_level:
                end_idx = idx
                break
    section_content = "\n".join(lines[start_idx:end_idx]).strip()
    return section_content


def _severity_from_issues(issues: List[str]) -> str:
    if not issues:
        return "ok"
    for code in issues:
        if SEVERITY_MAP.get(code) == "high":
            return "high"
    for code in issues:
        if SEVERITY_MAP.get(code) == "medium":
            return "medium"
    return "high"


def _compute_expected(workspace: Path) -> Optional[Tuple[List[dict], Dict[str, int], bool]]:
    inv_path = workspace / "input" / "inventory.json"
    inventory = _load_json_safe(inv_path)
    if not inventory or "records" not in inventory or not isinstance(inventory["records"], list):
        return None

    expected_rows = []
    any_listing_contains_stray = False

    for record in inventory["records"]:
        record_id = record.get("record_id", "")
        title = record.get("title", "")
        listing_md = record.get("listing_md")
        listing_text = ""
        if isinstance(listing_md, str):
            listing_text_raw = _read_text_safe(workspace / listing_md)
            listing_text = listing_text_raw or ""
        if re.search(r"stray\s+cats", listing_text, flags=re.IGNORECASE):
            any_listing_contains_stray = True

        has_claim_keywords = bool(re.search(r"\b(official|authorized)\b", listing_text, flags=re.IGNORECASE))

        assets = record.get("assets", [])
        any_nonlicensed = False
        for a in assets:
            dr = a.get("declared_rights")
            dr_norm = (dr or "").strip().lower()
            if dr_norm != "licensed":
                any_nonlicensed = True
                break

        record_marketing_conflict = has_claim_keywords and any_nonlicensed

        for asset in assets:
            asset_path = asset.get("asset_path", "")
            asset_type = asset.get("asset_type", "")
            declared_rights = asset.get("declared_rights")
            dr_norm = (declared_rights or "").strip().lower()
            license_ref = asset.get("license_ref")

            issues = []

            if not asset_path or not (workspace / asset_path).exists():
                issues.append("asset_missing")

            if not declared_rights or dr_norm == "unknown":
                issues.append("rights_unknown")

            if dr_norm == "licensed":
                if not license_ref:
                    issues.append("license_missing")
                else:
                    lic_path = workspace / "docs" / "licenses" / f"{license_ref}.md"
                    if not lic_path.exists():
                        issues.append("license_missing")

            if asset_type == "image" and dr_norm == "licensed":
                attrib_path = workspace / "assets" / "attribution" / f"{record_id}.txt"
                if not attrib_path.exists():
                    issues.append("missing_image_attribution")

            if asset_type == "audio" and dr_norm != "licensed":
                issues.append("audio_without_license")

            if record_marketing_conflict:
                issues.append("marketing_claim_conflict")

            seen = set()
            unique_issues = []
            for code in issues:
                if code not in seen:
                    seen.add(code)
                    unique_issues.append(code)

            severity = _severity_from_issues(unique_issues)

            expected_rows.append({
                "record_id": record_id,
                "title": title,
                "asset_path": asset_path,
                "asset_type": asset_type,
                "declared_rights": "" if declared_rights is None else declared_rights,
                "issues_set": set(unique_issues),
                "severity": severity,
            })

    tally = {"high": 0, "medium": 0, "ok": 0}
    for row in expected_rows:
        sev = row["severity"]
        if sev in tally:
            tally[sev] += 1
        else:
            tally["high"] += 1

    return expected_rows, tally, any_listing_contains_stray


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "report_columns_and_order_correct": 0.0,
        "report_row_count_correct": 0.0,
        "report_rows_content_correct": 0.0,
        "summary_present_and_correct": 0.0,
        "terms_backup_created": 0.0,
        "terms_ip_section_with_sentences": 0.0,
        "terms_trademark_section_if_required": 0.0,
        "terms_preserved_original_content": 0.0,
    }

    expected = _compute_expected(workspace)
    if expected is None:
        expected_rows = None
        expected_tally = None
        stray_required = None
    else:
        expected_rows, expected_tally, stray_required = expected

    report_path = workspace / "output" / "compliance_report.csv"
    header, rows = _parse_csv_safe(report_path)
    if header is not None and rows is not None:
        if header == CSV_COLUMNS:
            scores["report_columns_and_order_correct"] = 1.0
        else:
            scores["report_columns_and_order_correct"] = 0.0

        if expected_rows is not None and header == CSV_COLUMNS:
            if len(rows) == len(expected_rows):
                scores["report_row_count_correct"] = 1.0
            else:
                scores["report_row_count_correct"] = 0.0

            exp_map = {}
            for er in expected_rows:
                key = (er["record_id"], er["asset_path"])
                exp_map[key] = er

            all_match = True
            seen_keys = set()
            for row in rows:
                rec_id = (row.get("record_id") or "").strip()
                asset_path = (row.get("asset_path") or "").strip()
                key = (rec_id, asset_path)
                if key not in exp_map:
                    all_match = False
                    break
                seen_keys.add(key)
                exp = exp_map[key]
                title_ok = (row.get("title") or "").strip() == (exp["title"] or "").strip()
                asset_type_ok = (row.get("asset_type") or "").strip() == (exp["asset_type"] or "").strip()
                dr_ok = (row.get("declared_rights") or "") == (exp["declared_rights"] or "")
                issues_field = (row.get("issues") or "").strip()
                if issues_field == "none":
                    issues_set = set()
                else:
                    parts = [p.strip() for p in issues_field.split(";") if p.strip() != ""]
                    issues_set = set(parts)
                if issues_field != "none" and not issues_set.issubset(ALLOWED_ISSUES):
                    all_match = False
                    break
                if issues_field == "none" and len(exp["issues_set"]) != 0:
                    all_match = False
                    break
                if issues_field != "none" and len(exp["issues_set"]) == 0:
                    all_match = False
                    break
                issues_ok = issues_set == exp["issues_set"]
                sev_actual = (row.get("severity") or "").strip().lower()
                sev_ok = sev_actual == exp["severity"]
                if not (title_ok and asset_type_ok and dr_ok and issues_ok and sev_ok):
                    all_match = False
                    break

            if expected_rows is not None and len(seen_keys) != len(expected_rows):
                all_match = False

            scores["report_rows_content_correct"] = 1.0 if all_match else 0.0
        else:
            scores["report_row_count_correct"] = 0.0
            scores["report_rows_content_correct"] = 0.0
    else:
        scores["report_columns_and_order_correct"] = 0.0
        scores["report_row_count_correct"] = 0.0
        scores["report_rows_content_correct"] = 0.0

    summary_path = workspace / "output" / "compliance_summary.json"
    summary = _load_json_safe(summary_path)
    if summary is not None and expected_tally is not None:
        if isinstance(summary, dict) and set(summary.keys()) == {"high", "medium", "ok"}:
            try:
                high = int(summary.get("high", -1))
                med = int(summary.get("medium", -1))
                ok = int(summary.get("ok", -1))
                summary_ok = (
                    high == expected_tally["high"] and
                    med == expected_tally["medium"] and
                    ok == expected_tally["ok"]
                )
            except Exception:
                summary_ok = False
        else:
            summary_ok = False
        scores["summary_present_and_correct"] = 1.0 if summary_ok else 0.0
    else:
        scores["summary_present_and_correct"] = 0.0

    terms_path = workspace / "docs" / "terms.md"
    terms_backup_path = workspace / "output" / "terms_preupdate.md"
    backup_text = _read_text_safe(terms_backup_path)
    updated_text = _read_text_safe(terms_path)

    if backup_text is not None and backup_text.strip() != "":
        scores["terms_backup_created"] = 1.0
    else:
        scores["terms_backup_created"] = 0.0

    if backup_text is not None and updated_text is not None:
        if backup_text in updated_text:
            scores["terms_preserved_original_content"] = 1.0
        else:
            scores["terms_preserved_original_content"] = 0.0
    else:
        scores["terms_preserved_original_content"] = 0.0

    ip_sec_ok = False
    if updated_text is not None:
        ip_content = _extract_section(updated_text, "Intellectual Property and Media Usage")
        if ip_content is not None:
            sent1 = "Images and audio samples are used under the rights declared in input/inventory.json."
            sent2 = "Where required, attribution files are maintained under assets/attribution/."
            if sent1 in ip_content and sent2 in ip_content:
                ip_sec_ok = True
    scores["terms_ip_section_with_sentences"] = 1.0 if ip_sec_ok else 0.0

    trademark_ok = False
    if updated_text is not None and expected is not None:
        if stray_required:
            tm_content = _extract_section(updated_text, "Trademark Acknowledgment")
            if tm_content is not None:
                tm_sentence = "Stray Cats is a trademark of its respective owners; this site is not affiliated with or endorsed by the trademark holders."
                if tm_sentence in tm_content:
                    trademark_ok = True
        else:
            trademark_ok = True
    else:
        trademark_ok = False
    scores["terms_trademark_section_if_required"] = 1.0 if trademark_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()