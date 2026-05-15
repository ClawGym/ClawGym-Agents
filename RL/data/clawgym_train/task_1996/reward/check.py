import csv
import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Optional


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                return None, None
            rows = [dict(row) for row in reader]
            return fieldnames, rows
    except Exception:
        return None, None


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return None


def _parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _compute_metrics(events_rows: List[Dict[str, str]], incidents_rows: List[Dict[str, str]]) -> Dict[str, object]:
    total_events = len(events_rows)
    attendees_vals: List[int] = []
    total_attendees = 0
    permit_yes = 0
    event_permits: Dict[str, str] = {}
    for r in events_rows:
        ai = _safe_int(r.get("Attendees", "").strip())
        if ai is None:
            return {}
        attendees_vals.append(ai)
        total_attendees += ai
        if r.get("PermitsSubmitted", "") == "Yes":
            permit_yes += 1
        event_permits[r.get("EventName", "")] = r.get("PermitsSubmitted", "")
    avg_attendees = round(total_attendees / total_events) if total_events > 0 else 0
    total_incidents = len(incidents_rows)
    incident_rate = round((total_incidents / total_attendees) * 1000, 1) if total_attendees > 0 else 0.0

    # Top incident type by count; ties alphabetical
    type_counts: Dict[str, int] = {}
    for r in incidents_rows:
        t = r.get("IncidentType", "")
        type_counts[t] = type_counts.get(t, 0) + 1
    if type_counts:
        top_type = sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    else:
        top_type = ""

    permit_rate = round((permit_yes / total_events) * 100.0, 1) if total_events > 0 else 0.0

    # Top 3 incident types (descending by count, ties alphabetical)
    top3_incidents = sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]

    return {
        "total_events": total_events,
        "avg_attendees": avg_attendees,
        "incident_rate_per_1000": incident_rate,
        "top_incident_type": top_type,
        "permit_rate": permit_rate,
        "event_permits": event_permits,
        "top3_incidents": top3_incidents,
        "type_counts": type_counts,
        "total_attendees": total_attendees,
        "total_incidents": total_incidents,
    }


def _compute_noncompliant_vendors(vendors_rows: List[Dict[str, str]], events_rows: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    # Build event date map
    event_to_date: Dict[str, str] = {}
    for r in events_rows:
        name = r.get("EventName", "")
        date = r.get("Date", "")
        event_to_date[name] = date

    result: List[Dict[str, str]] = []
    for v in vendors_rows:
        assigned = v.get("AssignedEvent", "")
        ev_date_str = event_to_date.get(assigned)
        if ev_date_str is None:
            return None
        ev_date = _parse_date(ev_date_str)
        ins_expiry_str = v.get("InsuranceExpiry", "")
        ins_expiry = _parse_date(ins_expiry_str)
        if ev_date is None or ins_expiry is None:
            return None
        reasons = []
        if ins_expiry < ev_date:
            reasons.append("insurance_expired")
        if v.get("ContractSigned", "") != "Yes":
            reasons.append("contract_missing")
        if v.get("BackgroundChecks", "") != "Yes":
            reasons.append("background_checks_missing")
        if reasons:
            # Create row with required columns
            row = {
                "VendorName": v.get("VendorName", ""),
                "AssignedEvent": assigned,
                "EventDate": ev_date_str,
                "NonComplianceReasons": ";".join(reasons),
                "InsuranceExpiry": ins_expiry_str,
                "ContractSigned": v.get("ContractSigned", ""),
                "BackgroundChecks": v.get("BackgroundChecks", ""),
            }
            result.append(row)
    return result


def _expected_risk_hotspots(events_rows: List[Dict[str, str]], vendors_rows: List[Dict[str, str]], incidents_rows: List[Dict[str, str]]) -> Optional[List[Tuple[str, int]]]:
    # Compute counts per category label
    # Categories:
    # • Alcohol-related incidents (IncidentType == "Alcohol-related")
    # • Events missing permits (PermitsSubmitted != "Yes")
    # • Vendors with expired insurance before event date (InsuranceExpiry < Event Date)
    # • Vendors without signed contracts (ContractSigned != "Yes")
    # • Vendors without background checks (BackgroundChecks != "Yes")
    try:
        # Alcohol-related incidents
        alcohol_related = sum(1 for r in incidents_rows if r.get("IncidentType", "") == "Alcohol-related")
        # Events missing permits
        events_missing_permits = sum(1 for r in events_rows if r.get("PermitsSubmitted", "") != "Yes")
        # Vendors comparisons
        event_to_date: Dict[str, datetime] = {}
        for r in events_rows:
            d = _parse_date(r.get("Date", ""))
            if d is None:
                return None
            event_to_date[r.get("EventName", "")] = d
        vendors_expired_ins = 0
        vendors_no_contract = 0
        vendors_no_background = 0
        for v in vendors_rows:
            ev = v.get("AssignedEvent", "")
            ev_date = event_to_date.get(ev)
            if ev_date is None:
                return None
            ins_expiry = _parse_date(v.get("InsuranceExpiry", ""))
            if ins_expiry is None:
                return None
            if ins_expiry < ev_date:
                vendors_expired_ins += 1
            if v.get("ContractSigned", "") != "Yes":
                vendors_no_contract += 1
            if v.get("BackgroundChecks", "") != "Yes":
                vendors_no_background += 1

        categories = [
            ("Alcohol-related incidents", alcohol_related),
            ("Events missing permits", events_missing_permits),
            ("Vendors with expired insurance before event date", vendors_expired_ins),
            ("Vendors without signed contracts", vendors_no_contract),
            ("Vendors without background checks", vendors_no_background),
        ]
        # Top 3 by count desc, then alphabetical by label
        top3 = sorted(categories, key=lambda kv: (-kv[1], kv[0]))[:3]
        return top3
    except Exception:
        return None


def _normalize_reasons_token_set(s: str) -> frozenset:
    tokens = [t.strip() for t in s.split(";") if t.strip()]
    return frozenset(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "non_compliant_vendors_header": 0.0,
        "non_compliant_vendors_rows": 0.0,
        "compliance_summary_metrics_presence": 0.0,
        "compliance_summary_permit_bullets": 0.0,
        "compliance_summary_noncompliant_count": 0.0,
        "compliance_summary_top3_incidents": 0.0,
        "safety_plan_metrics_replaced": 0.0,
        "safety_plan_permit_rate_percent_sign": 0.0,
        "safety_plan_risk_hotspots": 0.0,
    }

    # Load inputs
    events_path = workspace / "input" / "events.csv"
    vendors_path = workspace / "input" / "vendors.csv"
    incidents_path = workspace / "input" / "incidents.csv"
    template_path = workspace / "input" / "SafetyPlan_Template.md"

    ev_fields, ev_rows = _read_csv_dicts(events_path)
    ve_fields, ve_rows = _read_csv_dicts(vendors_path)
    in_fields, in_rows = _read_csv_dicts(incidents_path)
    template_text = _read_text(template_path)

    # Compute expected artifacts if inputs available
    metrics = None
    noncompliant_expected = None
    risk_hotspots_expected = None
    if ev_rows is not None and ve_rows is not None and in_rows is not None:
        metrics = _compute_metrics(ev_rows, in_rows)
        noncompliant_expected = _compute_noncompliant_vendors(ve_rows, ev_rows)
        risk_hotspots_expected = _expected_risk_hotspots(ev_rows, ve_rows, in_rows)

    # 1) Check non_compliant_vendors.csv
    out_nc_path = workspace / "output" / "non_compliant_vendors.csv"
    nc_fields, nc_rows = _read_csv_dicts(out_nc_path)
    expected_header = [
        "VendorName",
        "AssignedEvent",
        "EventDate",
        "NonComplianceReasons",
        "InsuranceExpiry",
        "ContractSigned",
        "BackgroundChecks",
    ]
    if nc_fields is not None and nc_rows is not None:
        if nc_fields == expected_header:
            scores["non_compliant_vendors_header"] = 1.0
        else:
            scores["non_compliant_vendors_header"] = 0.0

        # Only proceed to rows comparison if we have expected computation and header correct
        if scores["non_compliant_vendors_header"] == 1.0 and noncompliant_expected is not None:
            # Build canonical sets for comparison
            expected_set = set()
            for r in noncompliant_expected:
                tpl = (
                    r["VendorName"],
                    r["AssignedEvent"],
                    r["EventDate"],
                    _normalize_reasons_token_set(r["NonComplianceReasons"]),
                    r["InsuranceExpiry"],
                    r["ContractSigned"],
                    r["BackgroundChecks"],
                )
                expected_set.add(tpl)
            actual_set = set()
            try:
                for r in nc_rows:
                    tpl = (
                        r.get("VendorName", ""),
                        r.get("AssignedEvent", ""),
                        r.get("EventDate", ""),
                        _normalize_reasons_token_set(r.get("NonComplianceReasons", "")),
                        r.get("InsuranceExpiry", ""),
                        r.get("ContractSigned", ""),
                        r.get("BackgroundChecks", ""),
                    )
                    actual_set.add(tpl)
                if actual_set == expected_set:
                    scores["non_compliant_vendors_rows"] = 1.0
                else:
                    scores["non_compliant_vendors_rows"] = 0.0
            except Exception:
                scores["non_compliant_vendors_rows"] = 0.0
        else:
            scores["non_compliant_vendors_rows"] = 0.0
    else:
        # Missing or unreadable file
        scores["non_compliant_vendors_header"] = 0.0
        scores["non_compliant_vendors_rows"] = 0.0

    # 2) compliance_summary.md
    out_summary_path = workspace / "output" / "compliance_summary.md"
    summary_text = _read_text(out_summary_path)
    if summary_text is not None and metrics is not None:
        # Metrics presence: check for 850, 2.6, Alcohol-related, 50.0
        m_ok = True
        if str(metrics.get("avg_attendees")) not in summary_text:
            m_ok = False
        if f"{metrics.get('incident_rate_per_1000'):.1f}" not in summary_text:
            m_ok = False
        if metrics.get("top_incident_type", "") not in summary_text:
            m_ok = False
        # permit rate with one decimal
        permit_str = f"{metrics.get('permit_rate'):.1f}"
        if permit_str not in summary_text:
            m_ok = False
        scores["compliance_summary_metrics_presence"] = 1.0 if m_ok else 0.0

        # Event permit bullets: lines like "- EventName — Permits: Yes/No"
        lines = [ln.strip() for ln in summary_text.splitlines()]
        bullet_lines = [ln for ln in lines if ln.startswith("- ") or ln.startswith("* ")]
        permit_map_found: Dict[str, str] = {}
        for ln in bullet_lines:
            if " — Permits: " in ln:
                # Extract event name before em dash, after bullet
                try:
                    body = ln[2:] if ln.startswith("- ") or ln.startswith("* ") else ln
                    parts = body.split(" — Permits: ")
                    event_name = parts[0].strip()
                    status = parts[1].strip()
                    # Normalize status to Yes/No as is
                    if status in ("Yes", "No"):
                        permit_map_found[event_name] = status
                except Exception:
                    pass
        expected_permits = metrics.get("event_permits", {})
        permits_match = True
        for ename, status in expected_permits.items():
            expected_status = status
            found_status = permit_map_found.get(ename)
            if found_status != expected_status:
                permits_match = False
                break
        if permits_match and len(permit_map_found) >= len(expected_permits):
            scores["compliance_summary_permit_bullets"] = 1.0
        else:
            scores["compliance_summary_permit_bullets"] = 0.0

        # Non-compliant vendor count line with context
        nc_count_ok = False
        for ln in lines:
            if re.search(r'non[- ]?compliant', ln, flags=re.IGNORECASE):
                if re.search(rf'\b{len(noncompliant_expected) if noncompliant_expected is not None else 0}\b', ln):
                    nc_count_ok = True
                    break
        scores["compliance_summary_noncompliant_count"] = 1.0 if nc_count_ok else 0.0

        # Top 3 incident types with counts, descending order requirement is relaxed to presence with correct counts
        top3 = metrics.get("top3_incidents", [])
        # Build a mapping from type to expected count
        top3_map = {t: c for t, c in top3}
        found_types = set()
        for ln in bullet_lines:
            for t, c in top3_map.items():
                if t in ln:
                    # look for standalone number c in line
                    if re.search(rf'\b{c}\b', ln):
                        found_types.add(t)
        if len(found_types) == len(top3_map) and len(top3_map) == 3:
            scores["compliance_summary_top3_incidents"] = 1.0
        else:
            scores["compliance_summary_top3_incidents"] = 0.0
    else:
        scores["compliance_summary_metrics_presence"] = 0.0
        scores["compliance_summary_permit_bullets"] = 0.0
        scores["compliance_summary_noncompliant_count"] = 0.0
        scores["compliance_summary_top3_incidents"] = 0.0

    # 3) SafetyPlan_Q3_Updated.md
    out_plan_path = workspace / "output" / "SafetyPlan_Q3_Updated.md"
    plan_text = _read_text(out_plan_path)
    if plan_text is not None and metrics is not None and risk_hotspots_expected is not None and noncompliant_expected is not None:
        # Check placeholders replaced
        placeholders = [
            "{{TOTAL_EVENTS}}",
            "{{AVG_ATTENDEES}}",
            "{{INCIDENT_RATE_PER_1000}}",
            "{{TOP_INCIDENT_TYPE}}",
            "{{PERMIT_COMPLIANCE_RATE}}",
            "{{NONCOMPLIANT_VENDOR_COUNT}}",
        ]
        if any(ph in plan_text for ph in placeholders):
            metrics_replaced_ok = False
        else:
            # Verify specific lines contain correct values
            m_ok = True
            # Total Events
            if not re.search(r"Total Events:\s*\b{}\b".format(metrics.get("total_events")), plan_text):
                m_ok = False
            # Average Attendees per Event
            if not re.search(r"Average Attendees per Event:\s*\b{}\b".format(metrics.get("avg_attendees")), plan_text):
                m_ok = False
            # Incident Rate
            if not re.search(r"Incident Rate \(per 1,000 attendees\):\s*\b{:.1f}\b".format(metrics.get("incident_rate_per_1000")), plan_text):
                m_ok = False
            # Top Incident Type
            if "Top Incident Type:" not in plan_text or metrics.get("top_incident_type", "") not in plan_text:
                m_ok = False
            # Permit Submission Rate numeric part
            if not re.search(r"Permit Submission Rate:\s*\b{:.1f}\b".format(metrics.get("permit_rate")), plan_text):
                m_ok = False
            # Non-compliant Vendors count
            if not re.search(r"Non-compliant Vendors:\s*\b{}\b".format(len(noncompliant_expected)), plan_text):
                m_ok = False
            metrics_replaced_ok = m_ok
        scores["safety_plan_metrics_replaced"] = 1.0 if metrics_replaced_ok else 0.0

        # Percent sign present on permit rate line
        percent_ok = False
        for ln in plan_text.splitlines():
            if "Permit Submission Rate:" in ln:
                if "%" in ln:
                    percent_ok = True
                break
        scores["safety_plan_permit_rate_percent_sign"] = 1.0 if percent_ok else 0.0

        # Risk hotspots section
        rh_start = "<!-- RISK_HOTSPOTS_START -->"
        rh_end = "<!-- RISK_HOTSPOTS_END -->"
        if rh_start in plan_text and rh_end in plan_text and plan_text.index(rh_end) > plan_text.index(rh_start):
            region = plan_text.split(rh_start, 1)[1].split(rh_end, 1)[0]
            # Ensure not placeholder
            if "[Replace this placeholder" in region:
                scores["safety_plan_risk_hotspots"] = 0.0
            else:
                # Extract bullet lines
                region_lines = [ln.strip() for ln in region.strip().splitlines()]
                bullets = [ln for ln in region_lines if ln.startswith("- ") or ln.startswith("* ")]
                # Must be exactly 3 bullets
                top3_labels = [lbl for (lbl, cnt) in risk_hotspots_expected]
                top3_counts = {lbl: cnt for (lbl, cnt) in risk_hotspots_expected}
                # Verify labels and counts present and mitigation sentence (presence of '.' in line)
                ok = True
                if len(bullets) != 3:
                    ok = False
                else:
                    labels_found = set()
                    for b in bullets:
                        # Check it contains any of the expected labels and its count in parentheses
                        matched = False
                        for lbl in top3_labels:
                            cnt = top3_counts.get(lbl, None)
                            if lbl in b and cnt is not None and re.search(rf'\({cnt}\)', b):
                                # Check mitigation period
                                if "." not in b:
                                    matched = False
                                else:
                                    matched = True
                                    labels_found.add(lbl)
                                    break
                        if not matched:
                            ok = False
                            break
                    if len(labels_found) != 3:
                        ok = False
                scores["safety_plan_risk_hotspots"] = 1.0 if ok else 0.0
        else:
            scores["safety_plan_risk_hotspots"] = 0.0
    else:
        scores["safety_plan_metrics_replaced"] = 0.0
        scores["safety_plan_permit_rate_percent_sign"] = 0.0
        scores["safety_plan_risk_hotspots"] = 0.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()