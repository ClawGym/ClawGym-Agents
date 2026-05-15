import csv
import json
import re
import sys
import math
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional


def _read_csv_safe(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    rows: List[Dict[str, str]] = []
    headers: List[str] = []
    try:
        with path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return [], []
            headers = list(reader.fieldnames)
            for row in reader:
                rows.append({k: v for k, v in row.items()})
    except Exception:
        return [], []
    return rows, headers


def _write_json_stdout(obj: Dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def _compute_expected(data_path: Path, partner: str) -> Tuple[Dict[Tuple[int, str, str, str], Dict[str, Any]], Dict[Tuple[int, str, str], int]]:
    """
    Returns:
      - sector map: key (year, partner_country, flow, product_sector) -> {"total_value_usd": int, "share_within_flow": float}
      - flow map: key (year, partner_country, flow) -> total_value_usd
    """
    rows, headers = _read_csv_safe(data_path)
    sector_totals: Dict[Tuple[int, str, str, str], int] = {}
    flow_totals: Dict[Tuple[int, str, str], int] = {}
    if not rows or not headers:
        return {}, {}

    for row in rows:
        try:
            year = int(row.get("year", "").strip())
            partner_country = (row.get("partner_country", "") or "").strip()
            flow = (row.get("flow", "") or "").strip()
            sector = (row.get("product_sector", "") or "").strip()
            val = int(row.get("value_usd", "").strip())
        except Exception:
            return {}, {}
        if partner_country != partner:
            continue
        key_flow = (year, partner_country, flow)
        key_sector = (year, partner_country, flow, sector)
        flow_totals[key_flow] = flow_totals.get(key_flow, 0) + val
        sector_totals[key_sector] = sector_totals.get(key_sector, 0) + val

    # compute shares
    sector_map: Dict[Tuple[int, str, str, str], Dict[str, Any]] = {}
    for key_sector, total in sector_totals.items():
        y, p, f, s = key_sector
        flow_total = flow_totals.get((y, p, f), 0)
        share = 0.0
        if flow_total > 0:
            share = round(total / float(flow_total), 4)
        sector_map[key_sector] = {
            "total_value_usd": total,
            "share_within_flow": share,
        }

    return sector_map, flow_totals


def _parse_sector_summary(path: Path) -> Tuple[List[Dict[str, Any]], List[str], bool]:
    rows, headers = _read_csv_safe(path)
    if not rows or not headers:
        return [], [], False
    parsed: List[Dict[str, Any]] = []
    try:
        for r in rows:
            parsed.append({
                "year": int((r.get("year") or "").strip()),
                "partner_country": (r.get("partner_country") or "").strip(),
                "flow": (r.get("flow") or "").strip(),
                "product_sector": (r.get("product_sector") or "").strip(),
                "total_value_usd": int((r.get("total_value_usd") or "").strip()),
                "share_within_flow": float((r.get("share_within_flow") or "").strip()),
            })
    except Exception:
        return [], headers, False
    return parsed, headers, True


def _parse_flow_totals(path: Path) -> Tuple[List[Dict[str, Any]], List[str], bool]:
    rows, headers = _read_csv_safe(path)
    if not rows or not headers:
        return [], [], False
    parsed: List[Dict[str, Any]] = []
    try:
        for r in rows:
            parsed.append({
                "year": int((r.get("year") or "").strip()),
                "partner_country": (r.get("partner_country") or "").strip(),
                "flow": (r.get("flow") or "").strip(),
                "total_value_usd": int((r.get("total_value_usd") or "").strip()),
            })
    except Exception:
        return [], headers, False
    return parsed, headers, True


def _compare_sector_summary(actual: List[Dict[str, Any]], expected_map: Dict[Tuple[int, str, str, str], Dict[str, Any]], expected_partner: str) -> float:
    # Build actual map
    actual_map: Dict[Tuple[int, str, str, str], Dict[str, Any]] = {}
    for r in actual:
        key = (r["year"], r["partner_country"], r["flow"], r["product_sector"])
        actual_map[key] = {
            "total_value_usd": r["total_value_usd"],
            "share_within_flow": r["share_within_flow"],
        }

    # Check partner-country strictly and keys match exactly
    expected_keys = set(expected_map.keys())
    actual_keys = set(actual_map.keys())
    if expected_keys != actual_keys:
        return 0.0

    for key in expected_keys:
        # partner country must match expected_partner exactly
        if key[1] != expected_partner:
            return 0.0
        exp = expected_map[key]
        act = actual_map[key]
        if exp["total_value_usd"] != act["total_value_usd"]:
            return 0.0
        # share equal within 1e-4 tolerance and also equals to rounded 4 decimals
        if round(act["share_within_flow"], 4) != exp["share_within_flow"]:
            return 0.0
        if not math.isclose(act["share_within_flow"], exp["share_within_flow"], rel_tol=0.0, abs_tol=1e-4):
            return 0.0
    return 1.0


def _compare_flow_totals(actual: List[Dict[str, Any]], expected_map: Dict[Tuple[int, str, str], int], expected_partner: str) -> float:
    actual_map: Dict[Tuple[int, str, str], int] = {}
    for r in actual:
        key = (r["year"], r["partner_country"], r["flow"])
        actual_map[key] = r["total_value_usd"]

    expected_keys = set(expected_map.keys())
    actual_keys = set(actual_map.keys())
    if expected_keys != actual_keys:
        return 0.0

    for key in expected_keys:
        if key[1] != expected_partner:
            return 0.0
        if expected_map[key] != actual_map[key]:
            return 0.0
    return 1.0


def _run_refactored_script(script_path: Path, input_path: Path) -> Tuple[bool, Optional[Path], Optional[Path]]:
    if not script_path.exists():
        return False, None, None
    try:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            out_sector = td_path / "sector_summary_neighborland.csv"
            out_flow = td_path / "flow_totals_neighborland.csv"
            cmd = [
                sys.executable,
                str(script_path),
                "--input",
                str(input_path),
                "--partner-country",
                "Neighborland",
                "--sector-summary",
                str(out_sector),
                "--flow-totals",
                str(out_flow),
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
            if proc.returncode != 0:
                return False, None, None
            if not out_sector.exists() or not out_flow.exists():
                return False, None, None
            # Copy to persistent temp to read outside context manager
            # We cannot use the same TemporaryDirectory because it will be cleaned up; instead, read data now and return content? Better: read immediately.
            # We'll read content here and write to new temporary files not auto-removed. But we can't modify workspace; using NamedTemporaryFile(delete=False)
            # Simpler: return in-memory marker False; However the function must return files. We'll instead read them now and write to new temp files.
            # But to keep simplicity, we will parse them here and stash content to new temp files.
    except Exception:
        return False, None, None

    # If we reach here, we ran successfully but temp files got deleted on context exit.
    # To make this useful, rerun with a persistent temp dir
    try:
        td2 = tempfile.mkdtemp()
        td2_path = Path(td2)
        out_sector2 = td2_path / "sector_summary_neighborland.csv"
        out_flow2 = td2_path / "flow_totals_neighborland.csv"
        cmd2 = [
            sys.executable,
            str(script_path),
            "--input",
            str(input_path),
            "--partner-country",
            "Neighborland",
            "--sector-summary",
            str(out_sector2),
            "--flow-totals",
            str(out_flow2),
        ]
        proc2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        if proc2.returncode != 0:
            return False, None, None
        if not out_sector2.exists() or not out_flow2.exists():
            return False, None, None
        return True, out_sector2, out_flow2
    except Exception:
        return False, None, None


def _list_files_recursive(base: Path, rel_root: Path) -> List[str]:
    out: List[str] = []
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file():
            out.append(str(p.relative_to(rel_root)).replace("\\", "/"))
    return out


def _extract_section(text: str, start_marker: str) -> str:
    idx = text.lower().find(start_marker.lower())
    if idx == -1:
        return ""
    section = text[idx:]
    # Truncate at next heading
    m = re.search(r"\n#{1,6}\s", section)
    if m:
        section = section[: m.start()]
    return section


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "refactored_script_exists": 0.0,
        "run_refactored_script_success": 0.0,
        "run_refactored_outputs_correct_sector_summary": 0.0,
        "run_refactored_outputs_correct_flow_totals": 0.0,
        "workspace_sector_summary_exists": 0.0,
        "workspace_sector_summary_columns": 0.0,
        "workspace_sector_summary_values": 0.0,
        "workspace_flow_totals_exists": 0.0,
        "workspace_flow_totals_columns": 0.0,
        "workspace_flow_totals_values": 0.0,
        "cross_file_totals_consistent": 0.0,
        "code_review_file_exists": 0.0,
        "dir_listing_complete_and_classified": 0.0,
        "code_review_issues_present": 0.0,
        "verification_totals_section_correct": 0.0,
    }

    data_path = workspace / "data" / "trade_indonesia_neighbors.csv"
    partner = "Neighborland"
    expected_sector, expected_flow = _compute_expected(data_path, partner)

    ref_script = workspace / "scripts" / "refactored" / "analyze_trade.py"
    if ref_script.exists():
        scores["refactored_script_exists"] = 1.0

    # Attempt to run refactored script with temp outputs to validate CLI and reproducibility
    ran, temp_sector_path, temp_flow_path = _run_refactored_script(ref_script, data_path)
    if ran and temp_sector_path and temp_flow_path:
        scores["run_refactored_script_success"] = 1.0
        # Validate temp outputs content
        # Sector summary
        t_sector_rows, t_sector_headers, ok_parse_sector = _parse_sector_summary(temp_sector_path)
        if ok_parse_sector and t_sector_headers == ["year", "partner_country", "flow", "product_sector", "total_value_usd", "share_within_flow"]:
            scores["run_refactored_outputs_correct_sector_summary"] = _compare_sector_summary(t_sector_rows, expected_sector, partner)
        elif ok_parse_sector:
            # headers mismatch => fail correctness
            scores["run_refactored_outputs_correct_sector_summary"] = 0.0

        # Flow totals
        t_flow_rows, t_flow_headers, ok_parse_flow = _parse_flow_totals(temp_flow_path)
        if ok_parse_flow and t_flow_headers == ["year", "partner_country", "flow", "total_value_usd"]:
            scores["run_refactored_outputs_correct_flow_totals"] = _compare_flow_totals(t_flow_rows, expected_flow, partner)
        elif ok_parse_flow:
            scores["run_refactored_outputs_correct_flow_totals"] = 0.0

    # Validate workspace deliverable outputs
    sector_out = workspace / "outputs" / "sector_summary_neighborland.csv"
    flow_out = workspace / "outputs" / "flow_totals_neighborland.csv"
    if sector_out.exists():
        scores["workspace_sector_summary_exists"] = 1.0
        sector_rows, sector_headers, ok_sector = _parse_sector_summary(sector_out)
        if ok_sector:
            if sector_headers == ["year", "partner_country", "flow", "product_sector", "total_value_usd", "share_within_flow"]:
                scores["workspace_sector_summary_columns"] = 1.0
            else:
                scores["workspace_sector_summary_columns"] = 0.0
            scores["workspace_sector_summary_values"] = _compare_sector_summary(sector_rows, expected_sector, partner)
    if flow_out.exists():
        scores["workspace_flow_totals_exists"] = 1.0
        flow_rows, flow_headers, ok_flow = _parse_flow_totals(flow_out)
        if ok_flow:
            if flow_headers == ["year", "partner_country", "flow", "total_value_usd"]:
                scores["workspace_flow_totals_columns"] = 1.0
            else:
                scores["workspace_flow_totals_columns"] = 0.0
            scores["workspace_flow_totals_values"] = _compare_flow_totals(flow_rows, expected_flow, partner)

    # Cross-file consistency between workspace outputs (if both parseable)
    sector_rows_cf, _, ok_sector_cf = _parse_sector_summary(sector_out) if sector_out.exists() else ([], [], False)
    flow_rows_cf, _, ok_flow_cf = _parse_flow_totals(flow_out) if flow_out.exists() else ([], [], False)
    if ok_sector_cf and ok_flow_cf:
        # Sum sector totals by (year, partner, flow) and compare to flow totals
        agg_from_sectors: Dict[Tuple[int, str, str], int] = {}
        for r in sector_rows_cf:
            key = (r["year"], r["partner_country"], r["flow"])
            agg_from_sectors[key] = agg_from_sectors.get(key, 0) + r["total_value_usd"]
        ok = True
        # There should be exact same keys
        keys_flow = {(r["year"], r["partner_country"], r["flow"]) for r in flow_rows_cf}
        if set(agg_from_sectors.keys()) != keys_flow:
            ok = False
        else:
            for r in flow_rows_cf:
                key = (r["year"], r["partner_country"], r["flow"])
                if agg_from_sectors.get(key, None) != r["total_value_usd"]:
                    ok = False
                    break
        scores["cross_file_totals_consistent"] = 1.0 if ok else 0.0

    # Code review and directory audit checks
    review_md = workspace / "outputs" / "code_review_and_dir_audit.md"
    if review_md.exists():
        scores["code_review_file_exists"] = 1.0
        try:
            content = review_md.read_text(encoding="utf-8")
        except Exception:
            content = ""

        # Directory listing completeness and classification
        expected_files = _list_files_recursive(workspace / "data", workspace)
        expected_files += _list_files_recursive(workspace / "scripts", workspace)
        # Only consider files; ensure listed and labeled
        listed_and_classified = True
        classification_correct = True

        # determine expected classification accuracy for known files
        must_be_referenced = {
            "data/trade_indonesia_neighbors.csv",
            "scripts/analyze_trade.py",
        }
        must_be_unused = {
            "data/obsolete/trade_2019.csv",
            "scripts/helpers.py",
            "scripts/legacy_analyzer.py",
            "scripts/refactored/analyze_trade.py",
        }

        # Build index of lines for quick per-file matching
        lines = content.splitlines()
        lower_lines = [ln.lower() for ln in lines]

        def _line_for_file(fp: str) -> Optional[str]:
            fpl = fp.lower()
            for ln in lines:
                if fpl in ln.lower():
                    return ln
            return None

        for fp in expected_files:
            ln = _line_for_file(fp)
            if ln is None:
                listed_and_classified = False
                classification_correct = False
                break
            lnl = ln.lower()
            has_ref = "referenced by original scripts/analyze_trade.py" in lnl
            has_unused = "unused/legacy" in lnl
            if not (has_ref or has_unused):
                listed_and_classified = False
                classification_correct = False
                break
            # check correctness for known files
            if fp in must_be_referenced and not has_ref:
                classification_correct = False
            if fp in must_be_unused and not has_unused:
                classification_correct = False

        if listed_and_classified and classification_correct:
            scores["dir_listing_complete_and_classified"] = 1.0

        # Code review issues present (at least two issues with some indication of fix/address)
        # Count lines that look like issue descriptions mentioning fix/address/refactor
        issue_like = 0
        for ln in lines:
            l = ln.strip().lower()
            if any(k in l for k in ["issue", "problem", "bug", "hardcod", "duplicate", "duplica"]):
                if any(w in l for w in ["address", "fix", "refactor", "resolved", "solution"]):
                    issue_like += 1
        if issue_like >= 2:
            scores["code_review_issues_present"] = 1.0

        # Verification totals section correctness
        sect = _extract_section(content, "verification totals")
        if sect:
            # Build expected patterns for each (year, flow, total)
            expected_pairs = [
                (2022, "export", expected_flow.get((2022, partner, "export"), 0)),
                (2022, "import", expected_flow.get((2022, partner, "import"), 0)),
                (2023, "export", expected_flow.get((2023, partner, "export"), 0)),
                (2023, "import", expected_flow.get((2023, partner, "import"), 0)),
            ]
            all_found = True
            for y, f, total in expected_pairs:
                # Look for lines containing year, flow, and total number
                pattern1 = re.compile(rf"{y}.*{f}.*{total}")
                pattern2 = re.compile(rf"{f}.*{y}.*{total}")
                if not (pattern1.search(sect.lower().replace("export", "export").replace("import", "import")) or pattern2.search(sect.lower().replace("export", "export").replace("import", "import"))):
                    all_found = False
                    break
            if all_found:
                scores["verification_totals_section_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    _write_json_stdout(result)


if __name__ == "__main__":
    main()