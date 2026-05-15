import csv
import json
import hashlib
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple, Dict, List, Optional


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _is_iso8601_datetime(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    try:
        # Accept 'Z' timezone by converting to +00:00
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def _norm_hex4(s: str) -> Optional[str]:
    if s is None:
        return None
    s = s.strip()
    if s.lower().startswith("0x"):
        s = s[2:]
    s = s.strip().lower()
    if not re.fullmatch(r"[0-9a-fA-F]+", s):
        return None
    s = s[-4:]
    return s.zfill(4).lower()


def _parse_pci_ids(pci_ids_path: Path) -> Tuple[Optional[Dict[str, str]], Optional[Dict[Tuple[str, str], str]], Optional[int], Optional[List[str]]]:
    """
    Parse pci.ids file to extract:
    - vendors: {vendor_id(lowercase 4-hex): vendor_name}
    - devices: {(vendor_id, device_id): device_name}
    - vendor_count: number of vendors parsed
    - first_two_noncomment_lines: first two non-comment lines as-is (no trailing newline)
    """
    text = _safe_read_text(pci_ids_path)
    if text is None:
        return None, None, None, None
    vendors: Dict[str, str] = {}
    devices: Dict[Tuple[str, str], str] = {}
    current_vendor: Optional[str] = None

    lines = text.splitlines()
    noncomment: List[str] = []
    for ln in lines:
        if not ln.strip():
            continue
        if ln.lstrip().startswith("#"):
            continue
        noncomment.append(ln.rstrip("\n"))
        if len(noncomment) >= 2:
            break

    vendor_line_re = re.compile(r"^([0-9A-Fa-f]{4})\s+(.*\S)\s*$")
    device_line_re = re.compile(r"^\t([0-9A-Fa-f]{4})\s+(.*\S)\s*$")

    try:
        for ln in lines:
            if not ln or ln.lstrip().startswith("#"):
                continue
            m_vendor = vendor_line_re.match(ln)
            if m_vendor:
                vid = _norm_hex4(m_vendor.group(1))
                vname = m_vendor.group(2).strip()
                if vid:
                    vendors[vid] = vname
                    current_vendor = vid
                else:
                    current_vendor = None
                continue
            m_device = device_line_re.match(ln)
            if m_device and current_vendor:
                did = _norm_hex4(m_device.group(1))
                dname = m_device.group(2).strip()
                if did:
                    devices[(current_vendor, did)] = dname
                continue
        vendor_count = len(vendors)
        return vendors, devices, vendor_count, noncomment[:2]
    except Exception:
        return None, None, None, None


def _load_input_devices(input_path: Path) -> Optional[List[dict]]:
    header, rows = _safe_read_csv_dicts(input_path)
    if header is None or rows is None:
        return None
    expected_header = ["opportunity_id", "vendor_id", "device_id", "units"]
    if not all(col in header for col in expected_header):
        return None
    normalized_rows = []
    for r in rows:
        opp = (r.get("opportunity_id") or "").strip()
        vid_raw = r.get("vendor_id")
        did_raw = r.get("device_id")
        units_raw = r.get("units")
        vid = _norm_hex4(vid_raw) if vid_raw is not None else None
        did = _norm_hex4(did_raw) if did_raw is not None else None
        try:
            units = int(str(units_raw).strip())
        except Exception:
            return None
        if opp == "" or vid is None or did is None:
            return None
        normalized_rows.append({
            "opportunity_id": opp,
            "vendor_id_norm": vid,
            "device_id_norm": did,
            "units": units,
            "vendor_id_raw": r.get("vendor_id"),
            "device_id_raw": r.get("device_id"),
        })
    return normalized_rows


def _compute_expected_enrichment(input_rows: List[dict], vendors: Dict[str, str], devices: Dict[Tuple[str, str], str]) -> Dict[Tuple[str, str, str, int], dict]:
    """
    Key by (opportunity_id, vendor_id_norm, device_id_norm, units)
    Value includes expected vendor_name, device_name, resolution_status
    """
    expected = {}
    for r in input_rows:
        opp = r["opportunity_id"]
        vid = r["vendor_id_norm"]
        did = r["device_id_norm"]
        units = r["units"]
        vname = vendors.get(vid, "UNKNOWN")
        dname = "UNKNOWN"
        if vname != "UNKNOWN":
            dname = devices.get((vid, did), "UNKNOWN")
        if vname != "UNKNOWN" and dname != "UNKNOWN":
            status = "device_resolved"
        elif vname != "UNKNOWN" and dname == "UNKNOWN":
            status = "vendor_only"
        else:
            status = "unresolved"
        expected[(opp, vid, did, units)] = {
            "vendor_name": vname,
            "device_name": dname,
            "resolution_status": status,
        }
    return expected


def _parse_int(s: str) -> Optional[int]:
    try:
        return int(str(s).strip())
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "pci_ids_downloaded_file": 0.0,
        "download_json_log_valid": 0.0,
        "resolved_devices_csv_structure": 0.0,
        "resolved_devices_enrichment_correct": 0.0,
        "summary_by_vendor_structure_and_sort": 0.0,
        "summary_by_vendor_values_correct": 0.0,
        "email_draft_includes_required_info": 0.0,
    }

    # Paths
    pci_ids_path = workspace / "out" / "downloads" / "pci.ids"
    log_json_path = workspace / "out" / "logs" / "download.json"
    resolved_csv_path = workspace / "out" / "resolved_devices.csv"
    summary_csv_path = workspace / "out" / "summary_by_vendor.csv"
    email_txt_path = workspace / "out" / "email_draft.txt"
    input_csv_path = workspace / "input" / "devices.csv"

    # 1) Check pci.ids exists and is non-empty
    try:
        if pci_ids_path.exists() and pci_ids_path.is_file() and pci_ids_path.stat().st_size > 0:
            scores["pci_ids_downloaded_file"] = 1.0
    except Exception:
        scores["pci_ids_downloaded_file"] = 0.0

    # 2) Validate download log JSON integrity and content
    vendors_map = {}
    devices_map = {}
    vendor_count = None
    first_two_lines = None
    if pci_ids_path.exists():
        vendors_map, devices_map, vendor_count, first_two_lines = _parse_pci_ids(pci_ids_path)
    log_ok = False
    if log_json_path.exists() and log_json_path.is_file() and vendors_map is not None and devices_map is not None and vendor_count is not None and first_two_lines is not None:
        log_data = _safe_load_json(log_json_path)
        if isinstance(log_data, dict):
            source_desc = log_data.get("source_description")
            fetched_dt = log_data.get("fetched_datetime_iso8601")
            saved_path = log_data.get("saved_path")
            sha256_logged = log_data.get("sha256")
            f2_lines = log_data.get("first_two_noncomment_lines")
            vendors_parsed_count = log_data.get("vendors_parsed_count")
            sha256_actual = _compute_sha256(pci_ids_path)
            conditions = [
                isinstance(source_desc, str) and len(source_desc.strip()) > 0,
                isinstance(fetched_dt, str) and _is_iso8601_datetime(fetched_dt),
                saved_path == "out/downloads/pci.ids",
                isinstance(sha256_logged, str) and sha256_logged == sha256_actual,
                isinstance(f2_lines, list) and len(f2_lines) == 2 and f2_lines == first_two_lines,
                isinstance(vendors_parsed_count, int) and vendors_parsed_count == vendor_count,
            ]
            if all(conditions):
                log_ok = True
    scores["download_json_log_valid"] = 1.0 if log_ok else 0.0

    # Load input devices
    input_rows = _load_input_devices(input_csv_path)
    # Compute expected enrichment
    expected_enrichment = None
    if input_rows is not None and vendors_map is not None and devices_map is not None:
        expected_enrichment = _compute_expected_enrichment(input_rows, vendors_map, devices_map)

    # 3) Check resolved_devices.csv structure
    resolved_structure_ok = False
    resolved_header, resolved_rows = _safe_read_csv_dicts(resolved_csv_path)
    if resolved_header is not None and resolved_rows is not None and input_rows is not None:
        expected_header = [
            "opportunity_id",
            "vendor_id",
            "vendor_name",
            "device_id",
            "device_name",
            "units",
            "resolution_status",
        ]
        if resolved_header == expected_header and len(resolved_rows) == len(input_rows):
            resolved_structure_ok = True
    scores["resolved_devices_csv_structure"] = 1.0 if resolved_structure_ok else 0.0

    # 4) Validate resolved_devices enrichment correctness
    enrichment_ok = False
    if resolved_structure_ok and expected_enrichment is not None:
        observed_map: Dict[Tuple[str, str, str, int], dict] = {}
        try:
            for r in resolved_rows:
                opp = (r.get("opportunity_id") or "").strip()
                vid_norm = _norm_hex4(r.get("vendor_id") or "")
                did_norm = _norm_hex4(r.get("device_id") or "")
                units_val = _parse_int(r.get("units"))
                vname = (r.get("vendor_name") or "").strip()
                dname = (r.get("device_name") or "").strip()
                status = (r.get("resolution_status") or "").strip()
                if not opp or vid_norm is None or did_norm is None or units_val is None:
                    observed_map = {}
                    break
                observed_map[(opp, vid_norm, did_norm, units_val)] = {
                    "vendor_name": vname,
                    "device_name": dname,
                    "resolution_status": status,
                }
        except Exception:
            observed_map = {}

        if observed_map and len(observed_map) == len(expected_enrichment):
            match_all = True
            for key, exp in expected_enrichment.items():
                obs = observed_map.get(key)
                if obs is None:
                    match_all = False
                    break
                if (obs.get("vendor_name") or "") != (exp.get("vendor_name") or ""):
                    match_all = False
                    break
                if (obs.get("device_name") or "") != (exp.get("device_name") or ""):
                    match_all = False
                    break
                if (obs.get("resolution_status") or "") != (exp.get("resolution_status") or ""):
                    match_all = False
                    break
            enrichment_ok = match_all
    scores["resolved_devices_enrichment_correct"] = 1.0 if enrichment_ok else 0.0

    # 5) summary_by_vendor structure and sorting
    summary_structure_ok = False
    summary_header, summary_rows = _safe_read_csv_dicts(summary_csv_path)
    if summary_header is not None and summary_rows is not None:
        expected_summary_header = [
            "vendor_id",
            "vendor_name_or_UNKNOWN",
            "total_units",
            "resolved_device_rows",
            "unresolved_device_rows",
        ]
        header_ok = summary_header == expected_summary_header
        sorted_ok = False
        if header_ok:
            totals = []
            all_ints = True
            for r in summary_rows:
                ti = _parse_int(r.get("total_units"))
                if ti is None:
                    all_ints = False
                    break
                totals.append(ti)
            if all_ints:
                sorted_ok = all(totals[i] >= totals[i + 1] for i in range(len(totals) - 1))
        summary_structure_ok = header_ok and sorted_ok
    scores["summary_by_vendor_structure_and_sort"] = 1.0 if summary_structure_ok else 0.0

    # 6) summary_by_vendor values correctness
    summary_values_ok = False
    if summary_structure_ok and input_rows is not None and expected_enrichment is not None:
        expected_summary: Dict[str, dict] = {}
        for r in input_rows:
            vid = r["vendor_id_norm"]
            units = r["units"]
            key = (r["opportunity_id"], r["vendor_id_norm"], r["device_id_norm"], r["units"])
            enr = expected_enrichment.get(key, {})
            vname = vendors_map.get(vid, "UNKNOWN") if vendors_map is not None else "UNKNOWN"
            if vid not in expected_summary:
                expected_summary[vid] = {
                    "vendor_id": vid,
                    "vendor_name_or_UNKNOWN": vname,
                    "total_units": 0,
                    "resolved_device_rows": 0,
                    "unresolved_device_rows": 0,
                }
            expected_summary[vid]["total_units"] += units
            if enr.get("resolution_status") == "device_resolved":
                expected_summary[vid]["resolved_device_rows"] += 1
            else:
                expected_summary[vid]["unresolved_device_rows"] += 1

        observed_summary: Dict[str, dict] = {}
        try:
            for r in summary_rows:
                vid_norm = _norm_hex4(r.get("vendor_id") or "")
                vname = (r.get("vendor_name_or_UNKNOWN") or "").strip()
                tu = _parse_int(r.get("total_units"))
                rd = _parse_int(r.get("resolved_device_rows"))
                ur = _parse_int(r.get("unresolved_device_rows"))
                if vid_norm is None or tu is None or rd is None or ur is None:
                    observed_summary = {}
                    break
                observed_summary[vid_norm] = {
                    "vendor_id": vid_norm,
                    "vendor_name_or_UNKNOWN": vname,
                    "total_units": tu,
                    "resolved_device_rows": rd,
                    "unresolved_device_rows": ur,
                }
        except Exception:
            observed_summary = {}

        if observed_summary and len(observed_summary) == len(expected_summary):
            all_match = True
            for vid, exp in expected_summary.items():
                obs = observed_summary.get(vid)
                if obs is None:
                    all_match = False
                    break
                if obs["total_units"] != exp["total_units"]:
                    all_match = False
                    break
                if obs["resolved_device_rows"] != exp["resolved_device_rows"]:
                    all_match = False
                    break
                if obs["unresolved_device_rows"] != exp["unresolved_device_rows"]:
                    all_match = False
                    break
                if (obs["vendor_name_or_UNKNOWN"] or "") != (exp["vendor_name_or_UNKNOWN"] or ""):
                    all_match = False
                    break
            summary_values_ok = all_match
    scores["summary_by_vendor_values_correct"] = 1.0 if summary_values_ok else 0.0

    # 7) Email draft includes required info
    email_ok = False
    email_text = _safe_read_text(email_txt_path) if email_txt_path.exists() else None
    if email_text is not None and input_rows is not None and summary_header is not None and summary_rows is not None:
        lines = email_text.splitlines()
        has_subject = any(re.match(r"(?i)^subject", ln.strip()) for ln in lines)
        has_paths = ("out/resolved_devices.csv" in email_text) and ("out/summary_by_vendor.csv" in email_text)
        total_rows = len(input_rows)
        total_units = sum(r["units"] for r in input_rows)
        unresolved_rows_count = 0
        if expected_enrichment is not None:
            for v in expected_enrichment.values():
                if v.get("resolution_status") != "device_resolved":
                    unresolved_rows_count += 1
        has_total_rows_num = str(total_rows) in email_text
        has_total_units_num = str(total_units) in email_text
        has_unresolved_num = str(unresolved_rows_count) in email_text

        top2_names = []
        top2_units = []
        try:
            parsed_summary = []
            for r in summary_rows:
                tu = _parse_int(r.get("total_units"))
                vname = (r.get("vendor_name_or_UNKNOWN") or "").strip()
                if tu is None:
                    parsed_summary = []
                    break
                parsed_summary.append((vname, tu))
            if parsed_summary:
                top2 = parsed_summary[:2]
                top2_names = [t[0] for t in top2]
                top2_units = [t[1] for t in top2]
        except Exception:
            top2_names = []
            top2_units = []

        has_top2 = False
        if len(top2_names) == 2:
            conds = []
            for name, units in zip(top2_names, top2_units):
                conds.append((name in email_text) and (str(units) in email_text))
            has_top2 = all(conds)

        email_ok = has_subject and has_paths and has_total_rows_num and has_total_units_num and has_unresolved_num and has_top2

    scores["email_draft_includes_required_info"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()