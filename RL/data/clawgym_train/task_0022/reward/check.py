import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _format_pct(value: float) -> str:
    # Percent to 1 decimal place
    return f"{value:.1f}%"


def _percent_to_one_decimal(numerator: float, denominator: float) -> Optional[str]:
    try:
        if denominator == 0:
            return None
        pct = (numerator / denominator) * 100.0
        return _format_pct(pct)
    except Exception:
        return None


def _number_variants(n: int) -> List[str]:
    # Generate plain and comma-separated variants for integers, with optional negative sign and currency symbol
    s = f"{n}"
    s_neg = f"-{abs(n)}" if n < 0 else None

    def with_commas(x: str) -> str:
        try:
            i = int(x)
            return f"{i:,}"
        except Exception:
            return x

    variants = set()
    for base in [s] + ([s_neg] if s_neg else []):
        variants.add(base)
        variants.add(with_commas(base))
        # En dash / minus sign variant
        if base.startswith("-"):
            variants.add(base.replace("-", "−"))
            variants.add(with_commas(base).replace("-", "−"))
        # Currency-prefixed
        variants.add("$" + base)
        variants.add("$" + with_commas(base))
        if base.startswith("-"):
            variants.add("$" + base.replace("-", "−"))
            variants.add("$" + with_commas(base).replace("-", "−"))
    return list(variants)


def _contains_any(text: str, candidates: List[str]) -> bool:
    t = text
    for c in candidates:
        if c and c in t:
            return True
    return False


def _contains_number(text: str, n: int) -> bool:
    # Check if any variant of n is present in text
    return _contains_any(text, _number_variants(n))


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def _normalize_path_string(s: str) -> str:
    # Normalize path separators to forward slashes and remove redundant parts
    return str(Path(s)).replace("\\", "/")


def _get_section_text(full_text: str, header_phrases: List[str], target_phrase: str) -> Optional[str]:
    """
    Extract text under the section whose line contains target_phrase (case-insensitive),
    until the next line that contains any other header phrase, or end of file.
    """
    lines = full_text.splitlines()
    idx = None
    # Find start line index where target phrase appears (case-insensitive)
    for i, line in enumerate(lines):
        if target_phrase.lower() in line.lower():
            idx = i
            break
    if idx is None:
        return None
    # Collect lines after the header line until next header phrase
    other_headers = [p for p in header_phrases if p.lower() != target_phrase.lower()]
    collected: List[str] = []
    for j in range(idx + 1, len(lines)):
        line = lines[j]
        if any(h.lower() in line.lower() for h in other_headers):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _parse_inputs(workspace: Path) -> Tuple[bool, Dict[str, Any]]:
    """
    Parse input files and compute expected metrics.
    Returns (ok, data) where data contains:
    - properties: dict of property_id -> dict(name, units)
    - occupancy: dict of property_id -> occupied_units
    - collections: dict of property_id -> dict(collected, target)
    - memos: list of dict(property_id, bullets)
    - mentor_tip: str
    - drafts_property_notes_paths: list of Paths
    - computed: dict with per_property and totals computed
    """
    data: Dict[str, Any] = {}
    base_props = workspace / "input" / "data" / "properties.csv"
    base_occ = workspace / "input" / "data" / "occupancy.csv"
    base_coll = workspace / "input" / "data" / "collections.csv"
    drafts_prop_notes_dir = workspace / "input" / "drafts" / "property_notes"
    memos_dir = workspace / "input" / "memos"
    mentor_tip_path = workspace / "input" / "mentor_tip.txt"
    ok = True

    props_rows = _load_csv(base_props)
    occ_rows = _load_csv(base_occ)
    coll_rows = _load_csv(base_coll)
    if props_rows is None or occ_rows is None or coll_rows is None:
        ok = False

    properties: Dict[str, Dict[str, Any]] = {}
    if props_rows:
        for r in props_rows:
            pid = r.get("property_id", "").strip()
            name = r.get("property_name", "").strip()
            units = r.get("units", "").strip()
            u = None
            try:
                u = int(units)
            except Exception:
                ok = False
            if not pid or not name or u is None:
                ok = False
            else:
                properties[pid] = {"property_name": name, "units": u}
    else:
        ok = False

    occupancy: Dict[str, int] = {}
    if occ_rows:
        for r in occ_rows:
            pid = r.get("property_id", "").strip()
            occ = r.get("occupied_units", "").strip()
            o = None
            try:
                o = int(occ)
            except Exception:
                ok = False
            if not pid or o is None:
                ok = False
            else:
                occupancy[pid] = o
    else:
        ok = False

    collections: Dict[str, Dict[str, int]] = {}
    if coll_rows:
        for r in coll_rows:
            pid = r.get("property_id", "").strip()
            col = r.get("collected_rent", "").strip()
            tgt = r.get("target_rent", "").strip()
            try:
                c = int(col)
                t = int(tgt)
            except Exception:
                ok = False
                continue
            if not pid:
                ok = False
            else:
                collections[pid] = {"collected": c, "target": t}
    else:
        ok = False

    # Parse memos
    memos: List[Dict[str, Any]] = []
    if memos_dir.exists():
        for p in sorted(memos_dir.glob("*.txt")):
            content = _read_text(p) or ""
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            pid = None
            bullets: List[str] = []
            for ln in lines:
                m = re.match(r"property_id:\s*([A-Za-z0-9_-]+)", ln, re.IGNORECASE)
                if m and pid is None:
                    pid = m.group(1).strip()
                elif ln.startswith("-"):
                    bullets.append(ln.lstrip("-").strip())
            if pid is None or not bullets:
                ok = False
            memos.append({"property_id": pid, "bullets": bullets, "path": p})
    else:
        ok = False

    mentor_tip = None
    if mentor_tip_path.exists():
        mentor_tip = _read_text(mentor_tip_path)
        if mentor_tip is None or not mentor_tip.strip():
            ok = False
    else:
        ok = False

    drafts_property_notes_paths: List[Path] = []
    if drafts_prop_notes_dir.exists():
        for p in sorted(drafts_prop_notes_dir.glob("*.md")):
            drafts_property_notes_paths.append(p)
        if not drafts_property_notes_paths:
            ok = False
    else:
        ok = False

    # Compute per-property metrics
    per_property: List[Dict[str, Any]] = []
    totals_units = 0
    totals_occupied = 0
    totals_collected = 0
    totals_target = 0
    for pid, pd in properties.items():
        name = pd["property_name"]
        units = pd["units"]
        occ = occupancy.get(pid)
        coll = collections.get(pid)
        if occ is None or coll is None:
            ok = False
            continue
        occupied_units = occ
        collected_rent = coll["collected"]
        target_rent = coll["target"]
        variance = collected_rent - target_rent
        occ_rate_pct = _percent_to_one_decimal(occupied_units, units)
        variance_pct = _percent_to_one_decimal(variance, target_rent) if target_rent != 0 else None
        if occ_rate_pct is None or variance_pct is None:
            ok = False
        per_property.append({
            "property_id": pid,
            "property_name": name,
            "units": units,
            "occupied_units": occupied_units,
            "occupancy_rate_pct": occ_rate_pct,
            "collected_rent": collected_rent,
            "target_rent": target_rent,
            "variance": variance,
            "variance_pct": variance_pct,
        })
        totals_units += units
        totals_occupied += occupied_units
        totals_collected += collected_rent
        totals_target += target_rent

    variance_total = totals_collected - totals_target
    portfolio_occ_pct = _percent_to_one_decimal(totals_occupied, totals_units) if totals_units != 0 else None
    portfolio_var_pct = _percent_to_one_decimal(variance_total, totals_target) if totals_target != 0 else None

    if portfolio_occ_pct is None or portfolio_var_pct is None:
        ok = False

    data["properties"] = properties
    data["occupancy"] = occupancy
    data["collections"] = collections
    data["memos"] = memos
    data["mentor_tip"] = mentor_tip
    data["drafts_property_notes_paths"] = drafts_property_notes_paths
    data["computed"] = {
        "per_property": per_property,
        "totals": {
            "units": totals_units,
            "occupied_units": totals_occupied,
            "occupancy_rate_pct": portfolio_occ_pct,
            "collected_total": totals_collected,
            "target_total": totals_target,
            "variance_total": variance_total,
            "variance_pct": portfolio_var_pct,
        },
    }
    return ok, data


def _email_paths(workspace: Path) -> Tuple[Path, Path, Path]:
    email_out = workspace / "out" / "investor_update_email.md"
    audit_out = workspace / "out" / "audit.json"
    notes_out_dir = workspace / "out" / "property_notes"
    return email_out, audit_out, notes_out_dir


def _check_subject_line(content: str) -> bool:
    lines = content.splitlines()
    if not lines:
        return False
    return lines[0].strip() == "Subject: Weekly Portfolio Update — Week of 2026-04-12"


def _section_presence(content: str) -> bool:
    required_phrases = [
        "Portfolio Snapshot",
        "Occupancy & Collections",
        "Property Highlights",
        "Mentorship Corner",
        "Pipeline & Next Steps",
    ]
    lower = content.lower()
    return all(phrase.lower() in lower for phrase in required_phrases)


def _contains_percent(text: str, pct_str: str) -> bool:
    # exact percent string, e.g., "92.9%"
    return pct_str in text


def _check_portfolio_snapshot(snapshot_text: str, totals: Dict[str, Any]) -> bool:
    if not snapshot_text:
        return False
    # Check occupancy rate and totals/variance numbers present
    occ_ok = _contains_percent(snapshot_text, totals["occupancy_rate_pct"])

    collected_ok = _contains_number(snapshot_text, int(totals["collected_total"]))
    target_ok = _contains_number(snapshot_text, int(totals["target_total"]))
    variance_ok = _contains_number(snapshot_text, int(totals["variance_total"]))
    varpct_ok = _contains_percent(snapshot_text, totals["variance_pct"])
    return bool(occ_ok and collected_ok and target_ok and variance_ok and varpct_ok)


def _check_property_numbers(section_text: str, prop: Dict[str, Any]) -> bool:
    if not section_text:
        return False
    name_ok = prop["property_name"] in section_text
    occ_ok = _contains_percent(section_text, prop["occupancy_rate_pct"])
    col_ok = _contains_number(section_text, int(prop["collected_rent"]))
    tgt_ok = _contains_number(section_text, int(prop["target_rent"]))
    var_ok = _contains_number(section_text, int(prop["variance"]))
    varpct_ok = _contains_percent(section_text, prop["variance_pct"])
    return bool(name_ok and occ_ok and col_ok and tgt_ok and var_ok and varpct_ok)


def _extract_keywords(line: str) -> List[str]:
    # Keywords to capture core ideas; use stems via substrings
    candidates = [
        "turn", "lease", "roof", "safety", "incident", "boiler", "heat",
        "complaint", "delinquen", "payment", "plan", "landscap", "bid", "approved", "patch", "servic"
    ]
    line_l = line.lower()
    found = []
    for k in candidates:
        if k in line_l:
            found.append(k)
    return found


def _extract_numbers_and_dates(line: str) -> Tuple[List[int], List[str]]:
    nums = [int(m.group(0)) for m in re.finditer(r"(?<![\d.])\d+(?![\d.])", line)]
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", line)
    return nums, dates


def _check_highlights_against_memos(highlights_text: str, memos: List[Dict[str, Any]], properties: Dict[str, Dict[str, Any]]) -> bool:
    if not highlights_text:
        return False
    # Require property names present
    for pid, pd in properties.items():
        if pd["property_name"] not in highlights_text:
            return False

    # For each memo bullet, ensure key tokens are present in highlights
    txt = highlights_text.lower()
    for memo in memos:
        bullets = memo.get("bullets") or []
        for b in bullets:
            keywords = _extract_keywords(b)
            nums, dates = _extract_numbers_and_dates(b)
            # Define coverage: highlighted if (any date present) or (any number present) or (at least two keywords present)
            covered = False
            for d in dates:
                if d and d.lower() in txt:
                    covered = True
                    break
            if not covered:
                for n in nums:
                    if _contains_number(highlights_text, n):
                        covered = True
                        break
            if not covered:
                # Check two keywords or at least one strong keyword
                kw_count = sum(1 for k in keywords if k in txt)
                if kw_count >= 2 or (kw_count >= 1 and (("roof" in keywords) or ("lease" in keywords) or ("landscap" in keywords) or ("boiler" in keywords) or ("payment" in keywords) or ("delinquen" in keywords))):
                    covered = True
            if not covered:
                return False
    return True


def _check_mentorship_section(section_text: str, mentor_tip: Optional[str]) -> bool:
    if not section_text or not mentor_tip:
        return False
    return _normalize_spaces(mentor_tip) in _normalize_spaces(section_text)


def _check_pipeline_section(section_text: str) -> bool:
    if not section_text:
        return False
    # Should not be the placeholder only, should contain actionable items related to memos/metrics
    if "- Keep this concise and actionable." in section_text:
        return False
    # Look for at least one actionable keyword
    actionable_keywords = [
        "repair", "repairs", "patch", "lease", "leasing", "market", "collect", "collections",
        "follow up", "follow-up", "payment plan", "payment", "landscap", "roof", "boiler", "schedule", "scheduled"
    ]
    st_low = section_text.lower()
    return any(k in st_low for k in actionable_keywords) and len(st_low.strip()) > 0


def _parse_audit(audit: Any) -> Tuple[bool, Dict[str, Any]]:
    if not isinstance(audit, dict):
        return False, {}
    return True, audit


def _compare_pct_field(value: Any, expected_pct_str: str) -> bool:
    # Accept string with % or numeric; compare to one decimal
    if value is None:
        return False
    if isinstance(value, (int, float)):
        try:
            s = _format_pct(float(value))
            return s == expected_pct_str
        except Exception:
            return False
    if isinstance(value, str):
        v = value.strip()
        # Normalize: if it endswith %, keep; else add
        if v.endswith("%"):
            return v == expected_pct_str
        # If it's numeric string
        fv = _parse_float(v)
        if fv is None:
            return False
        return _format_pct(fv) == expected_pct_str
    return False


def _check_audit_files_processed(audit: Dict[str, Any], workspace: Path) -> bool:
    files_processed = audit.get("files_processed")
    if not isinstance(files_processed, list):
        return False
    actual = set(_normalize_path_string(str(x)) for x in files_processed if isinstance(x, str))
    # Expected input files
    expected_paths = [
        workspace / "input" / "data" / "properties.csv",
        workspace / "input" / "data" / "occupancy.csv",
        workspace / "input" / "data" / "collections.csv",
        workspace / "input" / "memos" / "maple_court_memo.txt",
        workspace / "input" / "memos" / "riverside_flats_memo.txt",
        workspace / "input" / "drafts" / "investor_update_draft.md",
        workspace / "input" / "mentor_tip.txt",
        workspace / "input" / "drafts" / "property_notes" / "Maple_Court_note.md",
        workspace / "input" / "drafts" / "property_notes" / "Riverside_Flats_note.md",
    ]
    expected_norm = set(_normalize_path_string(str(p)) for p in expected_paths)
    # Allow relative entries; check presence by suffix match as well
    # We require all expected paths to be present in files_processed
    for exp in expected_norm:
        if exp in actual:
            continue
        # Also accept suffix match if exact not found
        suffix_matches = [a for a in actual if a.endswith(exp.replace(_normalize_path_string(str(workspace)) + "/", ""))]
        if not suffix_matches:
            return False
    return True


def _check_audit_per_property(audit: Dict[str, Any], computed: Dict[str, Any]) -> bool:
    ap = audit.get("per_property")
    if not isinstance(ap, list):
        return False
    ap_map = {}
    for item in ap:
        if not isinstance(item, dict):
            continue
        pid = item.get("property_id")
        if pid:
            ap_map[pid] = item
    expected_list = computed.get("per_property") or []
    for exp in expected_list:
        pid = exp["property_id"]
        name = exp["property_name"]
        units = exp["units"]
        occupied_units = exp["occupied_units"]
        collected = exp["collected_rent"]
        target = exp["target_rent"]
        variance = exp["variance"]
        varpct = exp["variance_pct"]
        occpct = exp["occupancy_rate_pct"]
        got = ap_map.get(pid)
        if not got:
            return False
        # Check name and integers
        if got.get("property_name") != name:
            return False
        if got.get("units") != units:
            return False
        if got.get("occupied_units") != occupied_units:
            return False
        if got.get("collected_rent") != collected:
            return False
        if got.get("target_rent") != target:
            return False
        if got.get("variance") != variance:
            return False
        if not _compare_pct_field(got.get("variance_pct"), varpct):
            return False
        if not _compare_pct_field(got.get("occupancy_rate_pct"), occpct):
            return False
    return True


def _check_audit_totals(audit: Dict[str, Any], computed: Dict[str, Any]) -> bool:
    totals = audit.get("portfolio_totals")
    if not isinstance(totals, dict):
        return False
    exp = computed.get("totals") or {}
    if totals.get("units") != exp.get("units"):
        return False
    if totals.get("occupied_units") != exp.get("occupied_units"):
        return False
    if totals.get("collected_total") != exp.get("collected_total"):
        return False
    if totals.get("target_total") != exp.get("target_total"):
        return False
    if totals.get("variance_total") != exp.get("variance_total"):
        return False
    if not _compare_pct_field(totals.get("variance_pct"), exp.get("variance_pct")):
        return False
    if not _compare_pct_field(totals.get("occupancy_rate_pct"), exp.get("occupancy_rate_pct")):
        return False
    return True


def _last_nonempty_sentence(text: str) -> Optional[str]:
    if not text:
        return None
    # Extract last non-empty line, then derive last sentence
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    # Split into sentences by period, exclamation, or question mark
    parts = re.split(r"(?<=[.!?])\s+", last)
    if not parts:
        return last
    # Prefer last sentence ending with punctuation
    for p in reversed(parts):
        if p and p[-1] in ".!?":
            return p.strip()
    return parts[-1].strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    email_out, audit_out, notes_out_dir = _email_paths(workspace)

    scores = {
        "email_file_exists": 0.0,
        "subject_line_exact": 0.0,
        "email_has_all_sections": 0.0,
        "portfolio_snapshot_numbers_correct": 0.0,
        "occ_coll_maple_numbers_present": 0.0,
        "occ_coll_riverside_numbers_present": 0.0,
        "property_highlights_covers_memos": 0.0,
        "mentorship_corner_included": 0.0,
        "pipeline_next_steps_quality": 0.0,
        "property_notes_output_files_exist": 0.0,
        "property_notes_maple_has_occupancy_and_action": 0.0,
        "property_notes_riverside_has_occupancy_and_action": 0.0,
        "audit_exists_and_parseable": 0.0,
        "audit_files_processed_coverage": 0.0,
        "audit_per_property_values_correct": 0.0,
        "audit_portfolio_totals_correct": 0.0,
    }

    # Parse inputs to compute expected values
    inputs_ok, data = _parse_inputs(workspace)

    # Email checks
    email_text = _read_text(email_out)
    if email_text is not None:
        scores["email_file_exists"] = 1.0
        if _check_subject_line(email_text):
            scores["subject_line_exact"] = 1.0
        if _section_presence(email_text):
            scores["email_has_all_sections"] = 1.0

        # Section extraction
        section_headers = [
            "Portfolio Snapshot",
            "Occupancy & Collections",
            "Property Highlights",
            "Mentorship Corner",
            "Pipeline & Next Steps",
        ]
        portfolio_text = _get_section_text(email_text, section_headers, "Portfolio Snapshot") or ""
        occ_coll_text = _get_section_text(email_text, section_headers, "Occupancy & Collections") or ""
        highlights_text = _get_section_text(email_text, section_headers, "Property Highlights") or ""
        mentor_text = _get_section_text(email_text, section_headers, "Mentorship Corner") or ""
        pipeline_text = _get_section_text(email_text, section_headers, "Pipeline & Next Steps") or ""

        if inputs_ok:
            totals = data["computed"]["totals"]
            if _check_portfolio_snapshot(portfolio_text, totals):
                scores["portfolio_snapshot_numbers_correct"] = 1.0

            # Property level checks
            per_prop = data["computed"]["per_property"]
            # Create quick map by name for clarity (Maple Court, Riverside Flats)
            prop_map = {pp["property_name"]: pp for pp in per_prop}
            if "Maple Court" in prop_map and _check_property_numbers(occ_coll_text, prop_map["Maple Court"]):
                scores["occ_coll_maple_numbers_present"] = 1.0
            if "Riverside Flats" in prop_map and _check_property_numbers(occ_coll_text, prop_map["Riverside Flats"]):
                scores["occ_coll_riverside_numbers_present"] = 1.0

            # Highlights vs memos
            if _check_highlights_against_memos(highlights_text, data["memos"], data["properties"]):
                scores["property_highlights_covers_memos"] = 1.0

            # Mentor tip inclusion
            if _check_mentorship_section(mentor_text, data.get("mentor_tip")):
                scores["mentorship_corner_included"] = 1.0

        # Pipeline section quality (independent of inputs)
        if _check_pipeline_section(pipeline_text):
            scores["pipeline_next_steps_quality"] = 1.0

    # Property notes checks
    notes_ok = True
    out_maple = notes_out_dir / "Maple_Court_note.md"
    out_riverside = notes_out_dir / "Riverside_Flats_note.md"
    if out_maple.exists() and out_riverside.exists():
        scores["property_notes_output_files_exist"] = 1.0
    else:
        notes_ok = False

    if notes_ok and inputs_ok:
        pp_map_by_name = {pp["property_name"]: pp for pp in data["computed"]["per_property"]}
        maple_text = _read_text(out_maple) or ""
        riverside_text = _read_text(out_riverside) or ""

        # Maple: includes occupancy % and action-oriented closing sentence
        maple_occ = pp_map_by_name.get("Maple Court", {}).get("occupancy_rate_pct")
        maple_has_occ = bool(maple_occ and maple_occ in maple_text)
        maple_last = _last_nonempty_sentence(maple_text) or ""
        maple_last_l = maple_last.lower()
        maple_action_keywords = ["roof", "lease", "collections", "collect", "payment", "plan", "turn"]
        maple_last_ok = bool(maple_last.endswith((".", "!", "?")) and any(k in maple_last_l for k in maple_action_keywords))
        if maple_has_occ and maple_last_ok:
            scores["property_notes_maple_has_occupancy_and_action"] = 1.0

        # Riverside: includes occupancy % and action-oriented closing sentence
        riverside_occ = pp_map_by_name.get("Riverside Flats", {}).get("occupancy_rate_pct")
        riverside_has_occ = bool(riverside_occ and riverside_occ in riverside_text)
        riverside_last = _last_nonempty_sentence(riverside_text) or ""
        riverside_last_l = riverside_last.lower()
        riverside_action_keywords = ["landscap", "payment", "plan", "collect", "collections", "boiler", "lease", "follow"]
        riverside_last_ok = bool(riverside_last.endswith((".", "!", "?")) and any(k in riverside_last_l for k in riverside_action_keywords))
        if riverside_has_occ and riverside_last_ok:
            scores["property_notes_riverside_has_occupancy_and_action"] = 1.0

    # Audit checks
    audit_json = _load_json(audit_out)
    if audit_json is not None:
        scores["audit_exists_and_parseable"] = 1.0
        ok_audit, audit = _parse_audit(audit_json)
        if ok_audit:
            if _check_audit_files_processed(audit, workspace):
                scores["audit_files_processed_coverage"] = 1.0
            if inputs_ok and _check_audit_per_property(audit, data["computed"]):
                scores["audit_per_property_values_correct"] = 1.0
            if inputs_ok and _check_audit_totals(audit, data["computed"]):
                scores["audit_portfolio_totals_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()