import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_csv(path: Path) -> list | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _safe_load_json(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


class TrainingTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_training_table = False
        self.current_table_id = None
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.col_index = -1
        self.current_row = []
        self.data = {}
        self._table_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "table":
            self._table_stack.append(attrs_dict.get("id"))
            if attrs_dict.get("id") == "training":
                self.in_training_table = True
        if not self.in_training_table:
            return
        if tag.lower() == "tbody":
            self.in_tbody = True
        if tag.lower() == "tr" and self.in_tbody:
            self.in_tr = True
            self.col_index = -1
            self.current_row = []
        if tag.lower() == "td" and self.in_tr:
            self.in_td = True
            self.col_index += 1

    def handle_endtag(self, tag):
        if tag.lower() == "table":
            table_id = self._table_stack.pop() if self._table_stack else None
            if table_id == "training":
                self.in_training_table = False
        if not self.in_training_table:
            return
        if tag.lower() == "tbody":
            self.in_tbody = False
        if tag.lower() == "tr" and self.in_tr:
            self.in_tr = False
            # Expect exactly two columns: facility_id and training_completion_percent
            if len(self.current_row) >= 2:
                fid = self.current_row[0].strip()
                perc = self.current_row[1].strip()
                if fid:
                    try:
                        self.data[fid] = int(perc)
                    except Exception:
                        # Ignore invalid row
                        pass
        if tag.lower() == "td":
            self.in_td = False

    def handle_data(self, data):
        if self.in_training_table and self.in_tr and self.in_td:
            self.current_row.append(data)


def _parse_training_html(path: Path) -> dict | None:
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        parser = TrainingTableParser()
        parser.feed(text)
        return parser.data
    except Exception:
        return None


def _fmt2(x: float) -> str:
    return f"{x:.2f}"


def _extract_section_lines(text: str, title_substring: str) -> list[str] | None:
    """
    Returns lines of a section that starts with a line containing title_substring (case-insensitive),
    stopping at the next blank line or the next line that contains the start of another known section.
    """
    lines = text.splitlines()
    start_idx = None
    title_lower = title_substring.lower()
    for i, line in enumerate(lines):
        if title_lower in line.lower():
            start_idx = i
            break
    if start_idx is None:
        return None
    # Collect subsequent lines until a blank line or another section header
    out = []
    known_headers = [
        "present audit files:",
        "facilities missing audit files:",
        "top 3 facilities by composite risk score",
        "gaps/notes",
        "company-wide totals",
        "overview",
        "brief overview",
    ]
    for j in range(start_idx + 1, len(lines)):
        ln = lines[j]
        if not ln.strip():
            break
        is_header = any(h in ln.lower() for h in known_headers)
        if is_header:
            break
        out.append(ln)
    return out


def _parse_audit_inventory(text: str) -> tuple[list[str], list[str]] | None:
    """
    Returns (present_files, missing_facility_ids)
    """
    lines = text.splitlines()
    present_idx = None
    missing_idx = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "present audit files:":
            present_idx = i
        if line.strip().lower() == "facilities missing audit files:":
            missing_idx = i
    if present_idx is None or missing_idx is None:
        return None
    # Present files: lines after present_idx up to missing_idx
    present_files = []
    for i in range(present_idx + 1, missing_idx):
        ln = lines[i].strip()
        if ln:
            present_files.append(ln)
    # Missing facilities: lines after missing_idx to end
    missing_ids = []
    for i in range(missing_idx + 1, len(lines)):
        ln = lines[i].strip()
        if ln:
            missing_ids.append(ln)
    return (present_files, missing_ids)


def _compute_expected(workspace: Path) -> dict:
    """
    Compute expected aggregates from input files.
    Returns dict with keys:
    - ok: bool
    - facilities: dict | None
    - incidents: dict | None
    - assets: dict | None
    - audits: dict | None
    - training: dict | None
    - present_audit_files: list
    """
    input_dir = workspace / "input"
    facilities_csv = input_dir / "facilities.csv"
    incidents_csv = input_dir / "incidents.csv"
    assets_jsonl = input_dir / "assets.jsonl"
    audits_dir = input_dir / "audits"
    training_html = input_dir / "training.html"

    # Facilities
    facilities_rows = _safe_read_csv(facilities_csv)
    facilities_ok = facilities_rows is not None
    facilities = {}
    if facilities_ok:
        try:
            for r in facilities_rows:
                fid = r.get("facility_id", "").strip()
                name = r.get("name", "").strip()
                location = r.get("location", "").strip()
                employees = int(r.get("employees", "").strip())
                if fid:
                    facilities[fid] = {
                        "facility_id": fid,
                        "facility_name": name,
                        "location": location,
                        "employees": employees,
                    }
        except Exception:
            facilities_ok = False
            facilities = {}

    # Incidents
    incidents_rows = _safe_read_csv(incidents_csv)
    incidents_ok = incidents_rows is not None
    incidents = {}
    if incidents_ok:
        try:
            for r in incidents_rows:
                fid = r.get("facility_id", "").strip()
                if not fid:
                    raise ValueError("Missing facility_id in incidents row")
                try:
                    ltd = float(r.get("lost_time_days", "0").strip())
                    cost = float(r.get("direct_cost_usd", "0").strip())
                except Exception:
                    raise
                agg = incidents.setdefault(fid, {"total_incidents": 0, "total_direct_cost_usd": 0.0, "total_lost_time_days": 0.0})
                agg["total_incidents"] += 1
                agg["total_direct_cost_usd"] += cost
                agg["total_lost_time_days"] += ltd
            # Convert lost time to int if integral
            for fid, agg in incidents.items():
                # Keep as integer if it's whole number; else keep as integer rounding? Spec not explicit; input gives ints.
                # We'll round to nearest integer for comparison assuming source is integer days.
                agg["total_lost_time_days"] = int(round(agg["total_lost_time_days"]))
        except Exception:
            incidents_ok = False
            incidents = {}

    # Assets (JSONL)
    assets_ok = True
    assets = {}
    if assets_jsonl.exists():
        try:
            with assets_jsonl.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    fid = str(obj.get("facility_id", "")).strip()
                    val = float(obj.get("asset_value_usd", 0.0))
                    if not fid:
                        raise ValueError("Missing facility_id in assets line")
                    assets[fid] = assets.get(fid, 0.0) + val
        except Exception:
            assets_ok = False
            assets = {}
    else:
        # Assets file missing is treated as zero assets for all facilities
        # But since requirement explicitly uses this file, if missing we'll still compute zero but mark ok False to fail precision checks.
        assets_ok = False
        assets = {}

    # Audits directory and files
    present_audit_files = []
    audits = {}
    audits_ok = True
    if audits_dir.exists() and audits_dir.is_dir():
        try:
            for p in sorted(audits_dir.iterdir()):
                if p.is_file() and p.suffix.lower() == ".json":
                    present_audit_files.append(p.name)
            # Map by facility from expected filename pattern
            for fid in facilities.keys():
                expected_name = f"facility_{fid}.json"
                p = audits_dir / expected_name
                if p.exists():
                    obj = _safe_load_json(p)
                    if obj is None:
                        audits_ok = False
                    else:
                        cp = obj.get("compliance_percent", None)
                        try:
                            if cp is None:
                                audits[fid] = None
                            else:
                                audits[fid] = int(cp)
                        except Exception:
                            audits_ok = False
                else:
                    audits[fid] = None
        except Exception:
            audits_ok = False
            audits = {}
            present_audit_files = []
    else:
        # No audits directory: none present
        audits_ok = True  # directory missing is acceptable; missing audits marked accordingly
        for fid in facilities.keys():
            audits[fid] = None
        present_audit_files = []

    # Training HTML
    training_map = _parse_training_html(training_html)
    training_ok = training_map is not None or not training_html.exists()
    if training_map is None:
        training_map = {}

    ok = facilities_ok and incidents_ok and assets_ok and audits_ok and training_ok

    return {
        "ok": ok,
        "facilities_ok": facilities_ok,
        "incidents_ok": incidents_ok,
        "assets_ok": assets_ok,
        "audits_ok": audits_ok,
        "training_ok": training_ok,
        "facilities": facilities,
        "incidents": incidents,
        "assets": assets,
        "audits": audits,
        "training": training_map,
        "present_audit_files": present_audit_files,
    }


def _build_expected_risk_metrics(expected: dict) -> list[dict] | None:
    if not (expected["facilities_ok"] and expected["incidents_ok"] and expected["audits_ok"] and expected["training_ok"]):
        return None
    # assets_ok is required too per spec; if False, we cannot fully validate
    if not expected["assets_ok"]:
        return None

    facilities = expected["facilities"]
    incidents = expected["incidents"]
    assets = expected["assets"]
    audits = expected["audits"]
    training = expected["training"]

    rows = []
    for fid, finfo in facilities.items():
        name = finfo["facility_name"]
        location = finfo["location"]
        employees = finfo["employees"]

        inc = incidents.get(fid, {"total_incidents": 0, "total_direct_cost_usd": 0.0, "total_lost_time_days": 0})
        total_incidents = inc["total_incidents"]
        total_direct_cost = float(inc["total_direct_cost_usd"])
        total_lost_time_days = int(inc["total_lost_time_days"])

        incident_rate = (total_incidents / employees) * 100.0 if employees > 0 else 0.0
        avg_cost = (total_direct_cost / total_incidents) if total_incidents > 0 else 0.0

        asset_total = float(assets.get(fid, 0.0))

        audit_cp = audits.get(fid, None)
        if audit_cp is None:
            audit_str = "MISSING"
            audit_gap = 100.0
        else:
            audit_str = str(int(audit_cp))
            audit_gap = float(100 - int(audit_cp))

        training_cp = training.get(fid, None)
        if training_cp is None:
            training_str = "UNKNOWN"
            training_gap = 100.0
        else:
            training_str = str(int(training_cp))
            training_gap = float(100 - int(training_cp))

        cost_factor = min(10.0, total_direct_cost / 10000.0)
        composite = incident_rate + 0.2 * audit_gap + 0.1 * training_gap + cost_factor

        row = {
            "facility_id": fid,
            "facility_name": name,
            "location": location,
            "employees": str(int(employees)),
            "total_incidents": str(int(total_incidents)),
            "incident_rate_per_100_employees": _fmt2(incident_rate),
            "total_direct_cost_usd": _fmt2(total_direct_cost),
            "avg_cost_per_incident_usd": _fmt2(avg_cost),
            "total_lost_time_days": str(int(total_lost_time_days)),
            "asset_value_usd_total": _fmt2(asset_total),
            "audit_compliance_percent": audit_str,
            "training_completion_percent": training_str,
            "composite_risk_score": _fmt2(composite),
        }
        rows.append(row)
    return rows


def _compare_csv_rows(expected_rows: list[dict], actual_rows: list[dict], header: list[str]) -> bool:
    # Build dicts by facility_id for comparison
    exp_by_id = {r["facility_id"]: r for r in expected_rows}
    act_by_id = {r["facility_id"]: r for r in actual_rows if "facility_id" in r}

    if set(exp_by_id.keys()) != set(act_by_id.keys()):
        return False

    for fid, exp in exp_by_id.items():
        act = act_by_id.get(fid)
        if act is None:
            return False
        # Check each column value equality as string trimming whitespace
        for col in header:
            ev = exp.get(col, "")
            av = (act.get(col, "") or "").strip()
            if av != ev:
                return False
    return True


def _tokens_from_lines(lines: list[str]) -> list[str]:
    tokens = []
    for ln in lines:
        tokens.extend(re.findall(r"[A-Za-z0-9_.-]+", ln))
    return tokens


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "risk_metrics_exists_and_header": 0.0,
        "risk_metrics_row_count": 0.0,
        "risk_metrics_values_accuracy": 0.0,
        "audit_inventory_exists_and_structure": 0.0,
        "audit_inventory_present_files_list": 0.0,
        "audit_inventory_missing_facilities_list": 0.0,
        "risk_summary_exists_and_overview": 0.0,
        "risk_summary_company_totals": 0.0,
        "risk_summary_top3_section": 0.0,
        "risk_summary_gaps_notes": 0.0,
    }

    expected = _compute_expected(workspace)

    # Prepare expected risk_metrics rows (if possible)
    expected_rows = _build_expected_risk_metrics(expected)

    # Paths
    output_dir = workspace / "output"
    risk_metrics_csv = output_dir / "risk_metrics.csv"
    audit_inventory_txt = output_dir / "audit_inventory.txt"
    risk_summary_md = output_dir / "risk_summary.md"

    # Check risk_metrics.csv existence and header
    rm_rows = _safe_read_csv(risk_metrics_csv)
    expected_header = [
        "facility_id",
        "facility_name",
        "location",
        "employees",
        "total_incidents",
        "incident_rate_per_100_employees",
        "total_direct_cost_usd",
        "avg_cost_per_incident_usd",
        "total_lost_time_days",
        "asset_value_usd_total",
        "audit_compliance_percent",
        "training_completion_percent",
        "composite_risk_score",
    ]
    if rm_rows is not None:
        # Re-open to get header
        try:
            with risk_metrics_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            if header == expected_header:
                scores["risk_metrics_exists_and_header"] = 1.0
        except Exception:
            pass

    # risk_metrics_row_count
    if rm_rows is not None and expected["facilities_ok"]:
        actual_count = len(rm_rows)
        expected_count = len(expected["facilities"])
        if actual_count == expected_count and expected_count > 0:
            scores["risk_metrics_row_count"] = 1.0

    # risk_metrics_values_accuracy
    if rm_rows is not None and expected_rows is not None:
        # Compare all rows
        # Ensure actual rows have all required columns
        actual_has_all_cols = True
        for r in rm_rows:
            for col in expected_header:
                if col not in r:
                    actual_has_all_cols = False
                    break
            if not actual_has_all_cols:
                break
        if actual_has_all_cols and _compare_csv_rows(expected_rows, rm_rows, expected_header):
            scores["risk_metrics_values_accuracy"] = 1.0

    # audit_inventory.txt existence and structure
    ai_text = _safe_read_text(audit_inventory_txt)
    if ai_text is not None:
        if ("Present audit files:" in ai_text) and ("Facilities missing audit files:" in ai_text):
            # ensure present section appears before missing section
            if ai_text.lower().find("present audit files:") < ai_text.lower().find("facilities missing audit files:"):
                scores["audit_inventory_exists_and_structure"] = 1.0

    # audit_inventory present files list correctness
    if ai_text is not None:
        parsed = _parse_audit_inventory(ai_text)
        if parsed is not None:
            present_files_list, missing_ids_list = parsed
            # Expected present files: JSON files under input/audits (names only)
            expected_present_files = expected["present_audit_files"]
            # Compare as sets (order not specified)
            if set(present_files_list) == set(expected_present_files):
                scores["audit_inventory_present_files_list"] = 1.0

            # audit_inventory missing facilities list correctness
            if expected["facilities_ok"]:
                expected_missing = []
                audits_dir = workspace / "input" / "audits"
                for fid in expected["facilities"].keys():
                    expected_name = f"facility_{fid}.json"
                    if not audits_dir.joinpath(expected_name).exists():
                        expected_missing.append(fid)
                if set(missing_ids_list) == set(expected_missing):
                    scores["audit_inventory_missing_facilities_list"] = 1.0

    # risk_summary.md existence and overview
    rs_text = _safe_read_text(risk_summary_md)
    if rs_text is not None:
        # Look for brief overview mentioning inputs and insurance
        first_lines = rs_text.splitlines()[:10]
        joined = "\n".join(first_lines).lower()
        if ("input" in joined) and ("insurance" in joined):
            scores["risk_summary_exists_and_overview"] = 1.0

    # risk_summary company totals
    if rs_text is not None and expected["facilities_ok"] and expected["incidents_ok"]:
        # Compute totals
        total_incidents = 0
        total_cost = 0.0
        # Aggregate incidents across all facilities
        inc_map = expected["incidents"]
        for fid in expected["facilities"].keys():
            agg = inc_map.get(fid, {"total_incidents": 0, "total_direct_cost_usd": 0.0})
            total_incidents += int(agg["total_incidents"])
            total_cost += float(agg["total_direct_cost_usd"])
        total_incidents_str = str(int(total_incidents))
        total_cost_str = _fmt2(total_cost)

        section_lines = _extract_section_lines(rs_text, "Company-wide totals")
        if section_lines is None:
            section_lines = _extract_section_lines(rs_text, "Company wide totals")
        if section_lines:
            tokens = _tokens_from_lines(section_lines)
            if (total_incidents_str in tokens) and (total_cost_str in tokens):
                scores["risk_summary_company_totals"] = 1.0

    # risk_summary top 3 section
    if rs_text is not None and expected_rows is not None:
        # Compute top 3 by composite_risk_score
        comp = []
        for r in expected_rows:
            comp.append((r["facility_id"], r["facility_name"], float(r["composite_risk_score"]), r))
        comp.sort(key=lambda x: (-x[2], x[0]))
        top3 = comp[:3]
        lines = rs_text.splitlines()
        top_idx = None
        for i, ln in enumerate(lines):
            if "Top 3 facilities by composite risk score".lower() in ln.lower():
                top_idx = i
                break
        top_lines = []
        if top_idx is not None:
            # Collect bullet lines after this index
            for j in range(top_idx + 1, len(lines)):
                ln = lines[j]
                if not ln.strip():
                    if top_lines:
                        break
                    else:
                        continue
                if ln.strip().startswith("-") or ln.strip().startswith("*"):
                    top_lines.append(ln.strip())
                else:
                    if top_lines:
                        break
                    # continue otherwise to skip non-bullets until first bullet
        if len(top_lines) == 3:
            # Validate content for each of the expected top 3 in order
            ok = True
            for i, (fid, name, comp_score, row) in enumerate(top3):
                ln = top_lines[i]
                # Required fields: facility_id, facility_name, composite_risk_score (2d), total_incidents, total_direct_cost_usd (2d), audit_compliance_percent/MISSING, training_completion_percent/UNKNOWN
                required_substrings = [
                    fid,
                    name,
                    _fmt2(comp_score),
                    row["total_incidents"],
                    row["total_direct_cost_usd"],
                ]
                # audit
                if row["audit_compliance_percent"] == "MISSING":
                    required_substrings.append("MISSING")
                else:
                    required_substrings.append(row["audit_compliance_percent"])
                # training
                if row["training_completion_percent"] == "UNKNOWN":
                    required_substrings.append("UNKNOWN")
                else:
                    required_substrings.append(row["training_completion_percent"])
                for sub in required_substrings:
                    if str(sub) not in ln:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                scores["risk_summary_top3_section"] = 1.0

    # risk_summary gaps/notes
    if rs_text is not None and expected["facilities_ok"]:
        gaps_lines = _extract_section_lines(rs_text, "Gaps/Notes")
        if gaps_lines is None:
            gaps_lines = _extract_section_lines(rs_text, "Gaps")
        if gaps_lines is not None:
            gaps_text = "\n".join(gaps_lines)
            audits_dir = workspace / "input" / "audits"
            missing_audit_ids = []
            for fid in expected["facilities"].keys():
                expected_name = f"facility_{fid}.json"
                if not audits_dir.joinpath(expected_name).exists():
                    missing_audit_ids.append(fid)
            # Facilities lacking training
            training_map = expected["training"]
            lacking_training_ids = []
            for fid in expected["facilities"].keys():
                if fid not in training_map:
                    lacking_training_ids.append(fid)
            ok_audit_listed = all(fid in gaps_text for fid in missing_audit_ids)
            ok_training_listed = all(fid in gaps_text for fid in lacking_training_ids)
            if ok_audit_listed and ok_training_listed:
                scores["risk_summary_gaps_notes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()