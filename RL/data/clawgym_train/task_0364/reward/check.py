import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any


def read_text_safe(path: Path) -> Tuple[bool, Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        return True, path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False, None


def load_json_safe(path: Path) -> Tuple[bool, Optional[Any]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return True, data
    except Exception:
        return False, None


def parse_jsonl_safe(path: Path) -> Tuple[bool, Optional[List[dict]]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None
        claims = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return False, None
                claims.append(obj)
        return True, claims
    except Exception:
        return False, None


def parse_csv_strict(path: Path) -> Tuple[bool, Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return False, None, None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return False, None, None
            rows = [row for row in reader]
        return True, header, rows
    except Exception:
        return False, None, None


def validate_date_yyyy_mm_dd(date_str: str) -> bool:
    try:
        if not isinstance(date_str, str):
            return False
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except Exception:
        return False


def has_url(text: str) -> bool:
    if not isinstance(text, str):
        return False
    return re.search(r'https?://', text) is not None


def top_level_names(workspace: Path) -> List[str]:
    try:
        if not workspace.exists() or not workspace.is_dir():
            return []
        return [p.name for p in sorted(workspace.iterdir(), key=lambda x: x.name)]
    except Exception:
        return []


def get_section_content(text: str, label: str, next_label: Optional[str]) -> str:
    idx = text.find(label)
    if idx < 0:
        return ""
    start = idx + len(label)
    if next_label is not None:
        next_idx = text.find(next_label, start)
        if next_idx >= 0:
            return text[start:next_idx]
    return text[start:]


def scan_outputs_for_urls(outputs_dir: Path, evidence_dir: Path) -> bool:
    # Returns True if URL found outside evidence dir, else False
    if not outputs_dir.exists():
        return False
    for p in outputs_dir.rglob("*"):
        if p.is_dir():
            continue
        if evidence_dir in p.parents:
            continue
        ok, content = read_text_safe(p)
        if not ok or content is None:
            continue
        if has_url(content):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "workspace_inventory_covers_top_level": 0.0,
        "evidence_files_valid": 0.0,
        "verification_csv_valid": 0.0,
        "search_queries_logged": 0.0,
        "rewritten_slack_sections_and_length": 0.0,
        "no_urls_outside_evidence": 0.0,
    }

    # Load inputs
    input_dir = workspace / "input"
    claims_path = input_dir / "claims.jsonl"
    draft_slack_path = input_dir / "draft_slack.txt"
    ok_claims, claims_list = parse_jsonl_safe(claims_path)
    if not ok_claims or not isinstance(claims_list, list) or len(claims_list) == 0:
        claims_list = []
        ok_claims = False
    claims_by_id = {}
    for c in claims_list:
        cid = c.get("id")
        if isinstance(cid, str):
            claims_by_id[cid] = c

    expected_ids = list(claims_by_id.keys())

    # Check workspace inventory coverage: must list exactly the top-level names (names only, one per line)
    inv_path = workspace / "outputs" / "workspace_inventory.txt"
    ok_inv, inv_text = read_text_safe(inv_path)
    top_names = top_level_names(workspace)
    if ok_inv and inv_text is not None:
        lines = [ln.strip() for ln in inv_text.splitlines() if ln.strip()]
        # Strict: lines must exactly match top-level names set (order not enforced)
        if set(lines) == set(top_names):
            # Additional strictness: ensure no line contains path separators or whitespace beyond the name
            complex_line = any(("/" in ln or "\\" in ln or ln != ln.strip()) for ln in lines)
            if not complex_line:
                scores["workspace_inventory_covers_top_level"] = 1.0
            else:
                scores["workspace_inventory_covers_top_level"] = 0.0
        else:
            scores["workspace_inventory_covers_top_level"] = 0.0
    else:
        scores["workspace_inventory_covers_top_level"] = 0.0

    # Evidence files validation
    evidence_dir = workspace / "outputs" / "evidence"
    valid_evidence_count = 0
    total_expected_evidence = len(expected_ids)
    if total_expected_evidence > 0:
        for cid in expected_ids:
            ev_path = evidence_dir / f"{cid}_sources.json"
            ok_ev, ev_data = load_json_safe(ev_path)
            if not ok_ev or not isinstance(ev_data, list):
                continue
            if not (1 <= len(ev_data) <= 3):
                continue
            all_items_ok = True
            for item in ev_data:
                if not isinstance(item, dict):
                    all_items_ok = False
                    break
                title = item.get("title")
                domain = item.get("source_domain")
                adate = item.get("access_date")
                snippet = item.get("snippet")
                if not (isinstance(title, str) and title.strip()):
                    all_items_ok = False
                    break
                if not (isinstance(domain, str) and domain.strip() and "." in domain and " " not in domain):
                    all_items_ok = False
                    break
                if not (isinstance(adate, str) and validate_date_yyyy_mm_dd(adate)):
                    all_items_ok = False
                    break
                if not (isinstance(snippet, str) and snippet.strip()):
                    all_items_ok = False
                    break
                # Optional URL allowed in evidence items if present, must be http(s)
                if "url" in item:
                    url_val = item.get("url")
                    if not (isinstance(url_val, str) and re.match(r"^https?://", url_val or "")):
                        all_items_ok = False
                        break
            if all_items_ok:
                valid_evidence_count += 1
        scores["evidence_files_valid"] = valid_evidence_count / total_expected_evidence if total_expected_evidence > 0 else 0.0
    else:
        scores["evidence_files_valid"] = 0.0

    # verification.csv validation
    verification_csv_path = workspace / "outputs" / "verification.csv"
    ok_csv, header, rows = parse_csv_strict(verification_csv_path)
    verification_valid = False
    if ok_csv and isinstance(header, list) and isinstance(rows, list):
        expected_header = ["id", "topic", "claim", "verdict", "confidence", "evidence_file"]
        if header == expected_header and ok_claims:
            # Check rows count and ids
            row_ids = [r.get("id") for r in rows]
            if set(row_ids) == set(expected_ids) and len(row_ids) == len(expected_ids):
                verdict_ok = {"Supported", "Refuted", "Unclear"}
                per_row_ok = True
                for r in rows:
                    rid = r.get("id")
                    topic = r.get("topic")
                    claim = r.get("claim")
                    verdict = r.get("verdict")
                    conf = r.get("confidence")
                    efile = r.get("evidence_file")
                    claim_obj = claims_by_id.get(rid)
                    if claim_obj is None:
                        per_row_ok = False
                        break
                    if topic != claim_obj.get("topic") or claim != claim_obj.get("claim"):
                        per_row_ok = False
                        break
                    if verdict not in verdict_ok:
                        per_row_ok = False
                        break
                    try:
                        cf = float(conf)
                        if not (0.0 <= cf <= 1.0):
                            per_row_ok = False
                            break
                    except Exception:
                        per_row_ok = False
                        break
                    # evidence file path checks
                    if not isinstance(efile, str) or not efile.strip():
                        per_row_ok = False
                        break
                    efile_path = (workspace / efile).resolve()
                    expected_ev_path = (evidence_dir / f"{rid}_sources.json").resolve()
                    # Must exist and match expected file
                    if not efile_path.exists() or efile_path != expected_ev_path:
                        per_row_ok = False
                        break
                if per_row_ok:
                    verification_valid = True
    scores["verification_csv_valid"] = 1.0 if verification_valid else 0.0

    # search_queries.txt validation
    search_queries_path = workspace / "outputs" / "search_queries.txt"
    ok_sq, sq_text = read_text_safe(search_queries_path)
    if ok_sq and isinstance(sq_text, str):
        non_empty_lines = [ln for ln in (sq_text.splitlines()) if ln.strip()]
        min_lines = len(expected_ids) if len(expected_ids) > 0 else 0
        if len(non_empty_lines) >= min_lines and not has_url(sq_text):
            scores["search_queries_logged"] = 1.0
        else:
            scores["search_queries_logged"] = 0.0
    else:
        scores["search_queries_logged"] = 0.0

    # rewritten_slack_message.txt structure
    rewritten_slack_path = workspace / "outputs" / "rewritten_slack_message.txt"
    ok_rs, rs_text = read_text_safe(rewritten_slack_path)
    if ok_rs and isinstance(rs_text, str):
        words = re.findall(r"\b\w+\b", rs_text)
        has_verified_label = "Verified:" in rs_text
        has_corrections_label = "Corrections:" in rs_text
        verified_content = get_section_content(rs_text, "Verified:", "Corrections:")
        corrections_content = get_section_content(rs_text, "Corrections:", None)
        has_verified_content = has_verified_label and verified_content.strip() != ""
        has_corrections_content = has_corrections_label and corrections_content.strip() != ""
        if (len(words) <= 120) and has_verified_label and has_corrections_label and has_verified_content and has_corrections_content and not has_url(rs_text):
            scores["rewritten_slack_sections_and_length"] = 1.0
        else:
            scores["rewritten_slack_sections_and_length"] = 0.0
    else:
        scores["rewritten_slack_sections_and_length"] = 0.0

    # No URLs outside evidence: only assess if outputs directory exists; otherwise 0.0
    outputs_dir = workspace / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir():
        url_found = scan_outputs_for_urls(outputs_dir, evidence_dir)
        scores["no_urls_outside_evidence"] = 0.0 if url_found else 1.0
    else:
        scores["no_urls_outside_evidence"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()