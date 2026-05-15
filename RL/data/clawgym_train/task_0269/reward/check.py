import json
import csv
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _parse_int_or_none(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return int(s)
    except Exception:
        return None


def _build_catalog_maps(rows: List[Dict[str, str]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    by_sku: Dict[str, Dict[str, Any]] = {}
    by_title: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        sku = (row.get("sku") or "").strip()
        title = (row.get("title") or "").strip()
        intro_year_raw = (row.get("intro_year") or "").strip()
        retire_year_raw = (row.get("retire_year") or "").strip()
        line_val = (row.get("line") or "").strip()
        record = {
            "sku": sku,
            "title": title,
            "intro_year": _parse_int_or_none(intro_year_raw),
            "retire_year": _parse_int_or_none(retire_year_raw),
            "line": line_val,
        }
        if sku:
            by_sku[sku] = record
        if title:
            by_title[title.lower()] = record
    return by_sku, by_title


def _expected_verification_for_claim(
    claim: Dict[str, Any],
    by_sku: Dict[str, Dict[str, Any]],
    by_title: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    claim_id = claim.get("claim_id")
    sku = claim.get("sku")
    title = claim.get("title")

    record = None
    match_key = None

    if sku:
        record = by_sku.get(str(sku))
        match_key = "sku"
    elif title:
        record = by_title.get(str(title).lower())
        match_key = "title"
    else:
        return {
            "claim_id": claim_id,
            "match_key": None,
            "status": "insufficient",
            "mismatched_fields": [],
            "evidence": None,
        }

    if record is None:
        return {
            "claim_id": claim_id,
            "match_key": match_key,
            "status": "not_found",
            "mismatched_fields": [],
            "evidence": None,
        }

    mismatches: List[str] = []

    if "claimed_intro_year" in claim:
        claimed_intro = claim["claimed_intro_year"]
        rec_intro = record.get("intro_year")
        if rec_intro != claimed_intro:
            mismatches.append("intro_year")

    if "claimed_retire_year" in claim:
        claimed_retire = claim["claimed_retire_year"]
        rec_retire = record.get("retire_year")
        if rec_retire != claimed_retire:
            mismatches.append("retire_year")

    if "claimed_line" in claim:
        claimed_line = (claim["claimed_line"] or "").strip().lower()
        rec_line = (record.get("line") or "").strip().lower()
        if rec_line != claimed_line:
            mismatches.append("line")

    status = "supported" if len(mismatches) == 0 else "contradicted"

    return {
        "claim_id": claim_id,
        "match_key": match_key,
        "status": status,
        "mismatched_fields": mismatches,
        "evidence": {
            "sku": record.get("sku"),
            "title": record.get("title"),
            "intro_year": record.get("intro_year"),
            "retire_year": record.get("retire_year"),
            "line": record.get("line"),
        },
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "config_field_mapping_correct": 0.0,
        "report_file_present_and_schema_valid": 0.0,
        "report_length_matches_claims_count": 0.0,
        "report_status_counts_correct": 0.0,
        "report_per_claim_results_correct": 0.0,
        "c1_supported_and_evidence_correct": 0.0,
        "summary_counts_match_report": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "fields.json"
    catalog_path = workspace / "input" / "boyds_catalog.csv"
    claims_path = workspace / "input" / "claims_to_verify.jsonl"
    report_path = workspace / "output" / "verification_report.json"
    summary_path = workspace / "output" / "summary.txt"

    # 1) Check config mapping correctness
    cfg = _safe_load_json(config_path)
    if isinstance(cfg, dict):
        expected_map = {
            "sku_field": "sku",
            "title_field": "title",
            "intro_year_field": "intro_year",
            "retire_year_field": "retire_year",
            "line_field": "line",
        }
        # Require exact keys and exact values
        if set(cfg.keys()) >= set(expected_map.keys()):
            ok = True
            for k, v in expected_map.items():
                if cfg.get(k) != v:
                    ok = False
                    break
            if ok:
                scores["config_field_mapping_correct"] = 1.0

    # Load inputs for further checks
    catalog_rows = _safe_load_csv_dicts(catalog_path)
    claims = _safe_load_jsonl(claims_path)
    # Prepare expected results if inputs available
    expected_by_claim_id: Dict[str, Dict[str, Any]] = {}
    expected_counts: Dict[str, int] = {}
    if catalog_rows is not None and claims is not None:
        by_sku, by_title = _build_catalog_maps(catalog_rows)
        for c in claims:
            res = _expected_verification_for_claim(c, by_sku, by_title)
            cid = res.get("claim_id")
            if cid is not None:
                expected_by_claim_id[str(cid)] = res
            status = res.get("status")
            if status:
                expected_counts[status] = expected_counts.get(status, 0) + 1

    # 2) Validate report presence and schema
    report_data = _safe_load_json(report_path)
    if isinstance(report_data, list) and all(isinstance(x, dict) for x in report_data):
        schema_ok = True
        allowed_statuses = {"supported", "contradicted", "not_found", "insufficient"}
        for r in report_data:
            if not all(k in r for k in ["claim_id", "match_key", "status", "mismatched_fields", "evidence"]):
                schema_ok = False
                break
            if r["status"] not in allowed_statuses:
                schema_ok = False
                break
            if not isinstance(r.get("mismatched_fields"), list):
                schema_ok = False
                break
            ev = r.get("evidence", None)
            if ev is not None and not isinstance(ev, dict):
                schema_ok = False
                break
            # match_key should be None or string
            mk = r.get("match_key")
            if mk is not None and not isinstance(mk, str):
                schema_ok = False
                break
        if schema_ok:
            scores["report_file_present_and_schema_valid"] = 1.0

    # 3) Check report length matches number of claims
    if isinstance(report_data, list) and claims is not None:
        if len(report_data) == len(claims):
            scores["report_length_matches_claims_count"] = 1.0

    # 4) Compare per-claim results and counts with expected (if available)
    if isinstance(report_data, list) and expected_by_claim_id:
        # Build maps by claim_id
        actual_by_claim_id: Dict[str, Dict[str, Any]] = {}
        for r in report_data:
            cid = r.get("claim_id")
            if cid is not None:
                actual_by_claim_id[str(cid)] = r

        per_claim_ok = True
        counts_ok = True
        # Check counts
        if expected_counts:
            actual_counts: Dict[str, int] = {}
            for r in report_data:
                st = r.get("status")
                if st:
                    actual_counts[st] = actual_counts.get(st, 0) + 1
            for key in ["supported", "contradicted", "not_found", "insufficient"]:
                if actual_counts.get(key, 0) != expected_counts.get(key, 0):
                    counts_ok = False
                    break
        else:
            counts_ok = False

        # Check each claim details
        for cid, exp in expected_by_claim_id.items():
            act = actual_by_claim_id.get(cid)
            if act is None:
                per_claim_ok = False
                break
            # match_key check based on presence of sku/title in claim
            # We'll recompute from claim itself
            claim = next((c for c in claims or [] if str(c.get("claim_id")) == cid), None)
            if claim is None:
                per_claim_ok = False
                break
            expected_match_key = None
            if claim.get("sku"):
                expected_match_key = "sku"
            elif claim.get("title"):
                expected_match_key = "title"
            if act.get("match_key") != expected_match_key:
                per_claim_ok = False
                break
            # status
            if act.get("status") != exp.get("status"):
                per_claim_ok = False
                break
            # mismatched_fields list (exact order)
            if act.get("mismatched_fields") != exp.get("mismatched_fields"):
                per_claim_ok = False
                break
            # evidence rules
            if exp.get("status") in ("not_found", "insufficient"):
                if act.get("evidence") is not None:
                    per_claim_ok = False
                    break
            else:
                # evidence should match record exactly
                ev = act.get("evidence")
                if not isinstance(ev, dict):
                    per_claim_ok = False
                    break
                needed_keys = ["sku", "title", "intro_year", "retire_year", "line"]
                if any(k not in ev for k in needed_keys):
                    per_claim_ok = False
                    break
                if any(ev.get(k) != exp["evidence"].get(k) for k in needed_keys):
                    per_claim_ok = False
                    break

        if counts_ok:
            scores["report_status_counts_correct"] = 1.0
        if per_claim_ok:
            scores["report_per_claim_results_correct"] = 1.0

        # 5) Specific check for c1 supported and evidence matches
        c1_act = actual_by_claim_id.get("c1")
        c1_exp = expected_by_claim_id.get("c1")
        if c1_act and c1_exp:
            c1_ok = True
            if c1_act.get("status") != "supported":
                c1_ok = False
            ev = c1_act.get("evidence")
            if not isinstance(ev, dict):
                c1_ok = False
            else:
                if ev.get("sku") != "2281":
                    c1_ok = False
                if ev.get("intro_year") != 1999:
                    c1_ok = False
                if ev.get("retire_year") != 2003:
                    c1_ok = False
                if ev.get("line") != "Boyds Bears":
                    c1_ok = False
            if c1_ok:
                scores["c1_supported_and_evidence_correct"] = 1.0

    # 6) Validate summary.txt matches report counts and format
    if isinstance(report_data, list):
        try:
            with summary_path.open("r", encoding="utf-8") as f:
                summary_content = f.read()
            lines = [ln.strip() for ln in summary_content.strip().splitlines()]
            # Compute counts from report
            actual_counts: Dict[str, int] = {}
            for r in report_data:
                st = r.get("status")
                if st:
                    actual_counts[st] = actual_counts.get(st, 0) + 1
            expected_lines = [
                f"supported: {actual_counts.get('supported', 0)}",
                f"contradicted: {actual_counts.get('contradicted', 0)}",
                f"not_found: {actual_counts.get('not_found', 0)}",
                f"insufficient: {actual_counts.get('insufficient', 0)}",
            ]
            if lines == expected_lines:
                scores["summary_counts_match_report"] = 1.0
        except Exception:
            pass

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()