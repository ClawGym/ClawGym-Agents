import json
import sys
import csv
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _to_int_if_whole(x: float) -> int:
    if abs(x - int(x)) < 1e-9:
        return int(x)
    return int(round(x))


def _parse_onprem_yaml(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        cpu_cores = sum(int(m.group(1)) for m in re.finditer(r'^\s*cpu_cores:\s*([0-9]+)\s*$', text, re.MULTILINE))
        memory_gib = sum(int(m.group(1)) for m in re.finditer(r'^\s*memory_gib:\s*([0-9]+)\s*$', text, re.MULTILINE))
        # storage_tb
        m_storage = re.search(r'^\s*storage_tb:\s*([0-9]+(?:\.[0-9]+)?)\s*$', text, re.MULTILINE)
        storage_tb = float(m_storage.group(1)) if m_storage else None
        # average_power_kw
        m_kw = re.search(r'^\s*average_power_kw:\s*([0-9]+(?:\.[0-9]+)?)\s*$', text, re.MULTILINE)
        average_power_kw = float(m_kw.group(1)) if m_kw else None
        # power_cost_usd_per_kwh
        m_rate = re.search(r'^\s*power_cost_usd_per_kwh:\s*([0-9]+(?:\.[0-9]+)?)\s*$', text, re.MULTILINE)
        power_cost_usd_per_kwh = float(m_rate.group(1)) if m_rate else None
        return {
            "cpu_cores": int(cpu_cores),
            "memory_gib": int(memory_gib),
            "storage_tb": storage_tb,
            "average_power_kw": average_power_kw,
            "power_cost_usd_per_kwh": power_cost_usd_per_kwh,
        }
    except Exception:
        return None


def _parse_service_limits_yaml(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        cpu_req = sum(float(m.group(1)) for m in re.finditer(r'^\s*cpu_request:\s*([0-9]+(?:\.[0-9]+)?)\s*$', text, re.MULTILINE))
        mem_req = sum(float(m.group(1)) for m in re.finditer(r'^\s*mem_request_gib:\s*([0-9]+(?:\.[0-9]+)?)\s*$', text, re.MULTILINE))
        return {"cpu_request": _to_int_if_whole(cpu_req), "mem_request_gib": _to_int_if_whole(mem_req)}
    except Exception:
        return None


def _parse_past_notes(text: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        lines = text.splitlines()
        participants: List[str] = []
        open_questions: List[str] = []
        # Participants
        part_start = None
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("participants"):
                part_start = i + 1
                break
        if part_start is not None:
            for j in range(part_start, len(lines)):
                l = lines[j]
                if l.strip().startswith("- "):
                    participants.append(l.strip()[2:].strip())
                elif l.strip() == "" or l.strip().startswith("#") or l.strip().lower().startswith("##"):
                    if participants:
                        break
        # Open Questions
        oq_start = None
        for i, line in enumerate(lines):
            if line.strip().lower().startswith("## open questions"):
                oq_start = i + 1
                break
        if oq_start is not None:
            for j in range(oq_start, len(lines)):
                l = lines[j].rstrip()
                if re.match(r'^\s*##\s+', l):
                    break
                m = re.match(r'^\s*([0-9]+)\)\s*(.+)$', l)
                if m:
                    # Store verbatim as in source (number) space and text
                    number = m.group(1)
                    content = m.group(2).strip()
                    open_questions.append(f"{number}) {content}")
        return {"participants": participants, "open_questions": open_questions}
    except Exception:
        return None


def _normalize_title(s: str) -> str:
    t = s.strip().lower().rstrip(':').strip()
    # remove markdown heading markers
    t = re.sub(r'^[#\s]+', '', t).strip()
    return t


def _extract_sections(text: str, required_titles: List[str]) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    if text is None:
        return sections
    lines = text.splitlines()
    title_indexes: List[Tuple[str, int]] = []
    req_norm = [_normalize_title(t) for t in required_titles]
    for idx, line in enumerate(lines):
        norm_line = _normalize_title(line)
        if norm_line in req_norm:
            title_indexes.append((norm_line, idx))
    # If some headings provided without markdown markers or with colons, also try to detect lines exactly equal to title text
    # Already handled by _normalize_title

    # Build sections content
    for k, start_idx in title_indexes:
        # Find end index
        next_indices = [j for (_, j) in title_indexes if j > start_idx]
        end_idx = min(next_indices) if next_indices else len(lines)
        content = "\n".join(lines[start_idx + 1:end_idx]).strip()
        sections[k] = content
    return sections


def _number_variants(value: int) -> List[str]:
    s = str(value)
    # add thousand separators
    parts = []
    # No commas for small integers likely, but include fallback
    try:
        parts.append(f"{value:,}")
    except Exception:
        pass
    parts.append(s)
    return list(dict.fromkeys(parts))


def _number_present(text: str, value: int) -> bool:
    if text is None:
        return False
    t = text
    variants = _number_variants(value)
    for v in variants:
        if v in t:
            return True
    return False


def _normalize_text(s: str) -> str:
    if s is None:
        return ""
    # Replace various unicode dashes with ASCII hyphen
    dash_chars = ["\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"]
    for d in dash_chars:
        s = s.replace(d, "-")
    return s.lower()


def _bullet_lines(section_text: str) -> List[str]:
    if not section_text:
        return []
    lines = section_text.splitlines()
    bullets = [l.strip() for l in lines if l.strip().startswith("- ") or l.strip().startswith("* ")]
    return bullets


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        return rows
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "resource_summary_csv_exists_and_header": 0.0,
        "resource_summary_cpu_row_correct": 0.0,
        "resource_summary_memory_row_correct": 0.0,
        "exec_brief_sections_present": 0.0,
        "exec_summary_word_limit_and_references_totals": 0.0,
        "baseline_totals_numbers_present_and_correct": 0.0,
        "observations_bullets_and_content": 0.0,
        "power_cost_computation_present_and_correct": 0.0,
        "risks_watchouts_quality_and_tied_to_inputs": 0.0,
        "decision_checkpoints_count": 0.0,
        "meeting_notes_attendees_extracted": 0.0,
        "meeting_notes_agenda_includes_required_items": 0.0,
        "meeting_notes_key_data_points_correct": 0.0,
        "meeting_notes_open_questions_verbatim": 0.0,
        "meeting_notes_action_items_mapped_and_due_window": 0.0,
    }

    # Load inputs
    onprem_yaml_path = workspace / "input" / "onprem_cluster.yaml"
    cloud_json_path = workspace / "input" / "cloud_plan.json"
    service_yaml_path = workspace / "input" / "service_limits.yaml"
    past_notes_path = workspace / "input" / "past_notes.md"

    onprem_text = _read_text(onprem_yaml_path)
    cloud_json = _load_json(cloud_json_path)
    service_text = _read_text(service_yaml_path)
    past_notes_text = _read_text(past_notes_path)

    onprem = _parse_onprem_yaml(onprem_text) if onprem_text else None
    services = _parse_service_limits_yaml(service_text) if service_text else None
    past_notes = _parse_past_notes(past_notes_text) if past_notes_text else None

    # Compute totals
    onprem_cpu = onprem["cpu_cores"] if onprem and "cpu_cores" in onprem else None
    onprem_mem = onprem["memory_gib"] if onprem and "memory_gib" in onprem else None
    onprem_storage_tb = onprem["storage_tb"] if onprem and "storage_tb" in onprem else None
    avg_kw = onprem["average_power_kw"] if onprem and "average_power_kw" in onprem else None
    power_rate = onprem["power_cost_usd_per_kwh"] if onprem and "power_cost_usd_per_kwh" in onprem else None
    annual_power_cost = None
    if avg_kw is not None and power_rate is not None:
        try:
            annual_power_cost = int(round(avg_kw * 8760 * power_rate))
        except Exception:
            annual_power_cost = None

    # Cloud totals
    cloud_cpu = None
    cloud_mem = None
    cloud_ssd_gb = None
    cloud_standard_gb = None
    cloud_egress_gb = None
    reserved_pct = None
    savings_plan_pct = None
    if cloud_json and "deployment" in cloud_json:
        try:
            instances = cloud_json["deployment"].get("instances", [])
            cloud_cpu = sum(int(i.get("vcpu", 0)) * int(i.get("count", 0)) for i in instances)
            cloud_mem = sum(int(i.get("memory_gib", 0)) * int(i.get("count", 0)) for i in instances)
            storage = cloud_json["deployment"].get("storage", {})
            cloud_ssd_gb = int(storage.get("ssd_gb")) if storage.get("ssd_gb") is not None else None
            cloud_standard_gb = int(storage.get("standard_gb")) if storage.get("standard_gb") is not None else None
            cloud_egress_gb = int(cloud_json["deployment"].get("egress_gb_per_month")) if cloud_json["deployment"].get("egress_gb_per_month") is not None else None
            pa = cloud_json["deployment"].get("pricing_assumptions", {})
            reserved_pct = pa.get("reserved_percentage")
            savings_plan_pct = pa.get("savings_plan_discount_percent")
        except Exception:
            cloud_cpu = None
            cloud_mem = None
    # Services totals
    service_cpu = services["cpu_request"] if services and "cpu_request" in services else None
    service_mem = services["mem_request_gib"] if services and "mem_request_gib" in services else None

    # Validate CSV
    csv_path = workspace / "output" / "resource_summary.csv"
    rows = _parse_csv(csv_path)
    if rows is not None:
        # Header check
        header_ok = rows is not None and isinstance(rows, list)
        # Ensure fieldnames exactly match
        try:
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                header_line = f.readline().strip()
            header_ok = header_line == "metric,value_onprem,value_cloud,value_services,unit"
        except Exception:
            header_ok = False

        # Exactly two rows
        exactly_two = len(rows) == 2 if rows is not None else False

        if header_ok and exactly_two:
            scores["resource_summary_csv_exists_and_header"] = 1.0

        # Validate rows content strictly
        if rows is not None and exactly_two:
            row1 = rows[0]
            row2 = rows[1]
            cpu_ok = False
            mem_ok = False
            try:
                if row1.get("metric") == "cpu_cores" and row1.get("unit") == "cores":
                    vo = int(row1.get("value_onprem"))
                    vc = int(row1.get("value_cloud"))
                    vs = int(row1.get("value_services"))
                    cpu_ok = (onprem_cpu is not None and cloud_cpu is not None and service_cpu is not None and
                              vo == int(onprem_cpu) and vc == int(cloud_cpu) and vs == int(service_cpu))
                if row2.get("metric") == "memory_gib" and row2.get("unit") == "GiB":
                    vo2 = int(row2.get("value_onprem"))
                    vc2 = int(row2.get("value_cloud"))
                    vs2 = int(row2.get("value_services"))
                    mem_ok = (onprem_mem is not None and cloud_mem is not None and service_mem is not None and
                              vo2 == int(onprem_mem) and vc2 == int(cloud_mem) and vs2 == int(service_mem))
            except Exception:
                cpu_ok = False
                mem_ok = False

            if cpu_ok:
                scores["resource_summary_cpu_row_correct"] = 1.0
            if mem_ok:
                scores["resource_summary_memory_row_correct"] = 1.0

    # Validate exec_brief.md
    brief_path = workspace / "output" / "exec_brief.md"
    brief_text = _read_text(brief_path)
    section_titles = [
        "Executive Summary",
        "Baseline From Local Configs",
        "Observations",
        "Quantified On-Prem Power Cost",
        "Risks & Watchouts",
        "Decision Checkpoints",
    ]
    brief_sections = _extract_sections(brief_text or "", section_titles)
    # Sections present
    if all(_normalize_title(t) in brief_sections for t in section_titles):
        scores["exec_brief_sections_present"] = 1.0

    # Executive Summary checks
    exec_sum = brief_sections.get(_normalize_title("Executive Summary"), "")
    if exec_sum:
        # word count
        words = re.findall(r'\b\w+\b', exec_sum)
        within_limit = len(words) <= 120
        # references totals: require at least two numbers matching computed totals to avoid platitudes
        referenced = 0
        needed_values = []
        for v in [onprem_cpu, cloud_cpu, service_cpu, onprem_mem, cloud_mem, service_mem, annual_power_cost]:
            if v is not None:
                needed_values.append(int(v))
        # unique values
        seen = set()
        for v in needed_values:
            if v in seen:
                continue
            seen.add(v)
            if _number_present(exec_sum, v):
                referenced += 1
        if within_limit and referenced >= 2:
            scores["exec_summary_word_limit_and_references_totals"] = 1.0

    # Baseline section numbers presence and correctness
    baseline_sec = brief_sections.get(_normalize_title("Baseline From Local Configs"), "")
    baseline_ok = True
    if not baseline_sec:
        baseline_ok = False
    else:
        # All six totals present (CPU and Memory for On-Prem, Cloud, Services)
        required_numbers = [onprem_cpu, cloud_cpu, service_cpu, onprem_mem, cloud_mem, service_mem]
        if any(v is None for v in required_numbers):
            baseline_ok = False
        else:
            for v in required_numbers:
                if not _number_present(baseline_sec, int(v)):
                    baseline_ok = False
                    break
        # Storage values present: on-prem storage_tb and cloud storage ssd_gb and standard_gb as raw values
        if baseline_ok:
            if onprem_storage_tb is None or cloud_ssd_gb is None or cloud_standard_gb is None:
                baseline_ok = False
            else:
                # onprem storage_tb might be int or float; check for integer if whole number
                val = int(onprem_storage_tb) if abs(onprem_storage_tb - int(onprem_storage_tb)) < 1e-9 else onprem_storage_tb
                if isinstance(val, int):
                    if not _number_present(baseline_sec, val):
                        baseline_ok = False
                else:
                    # fallback match for float representation
                    if str(val) not in baseline_sec:
                        baseline_ok = False
                if not _number_present(baseline_sec, int(cloud_ssd_gb)):
                    baseline_ok = False
                if not _number_present(baseline_sec, int(cloud_standard_gb)):
                    baseline_ok = False
    if baseline_ok:
        scores["baseline_totals_numbers_present_and_correct"] = 1.0

    # Observations
    obs_sec = brief_sections.get(_normalize_title("Observations"), "")
    obs_bullets = _bullet_lines(obs_sec)
    obs_ok = False
    if obs_bullets and 3 <= len(obs_bullets) <= 5:
        nt = _normalize_text(obs_sec)
        # planned cloud capacity above/below total service requests
        cloud_vs_service = None
        if cloud_cpu is not None and service_cpu is not None and cloud_mem is not None and service_mem is not None:
            # If both CPU and mem are above, we expect "above" somewhere referencing cloud/services
            is_above = (cloud_cpu >= service_cpu) and (cloud_mem >= service_mem)
            is_below = (cloud_cpu < service_cpu) or (cloud_mem < service_mem)
            if is_above:
                cond_ok = ("cloud" in nt and ("above" in nt or "exceed" in nt) and ("service" in nt or "request" in nt))
            else:
                cond_ok = ("cloud" in nt and ("below" in nt or "under" in nt) and ("service" in nt or "request" in nt))
            # on-prem capacity materially exceeds needs
            onprem_vs_needs = False
            if onprem_cpu is not None and onprem_mem is not None and service_cpu is not None and service_mem is not None:
                if onprem_cpu > service_cpu and onprem_mem > service_mem:
                    onprem_vs_needs = ("on-prem" in nt or "on - prem" in nt or "on prem" in nt) and ("exceed" in nt or "surplus" in nt or "above" in nt)
            # right-sizing opportunities mentioned
            rightsizing = ("right-size" in nt) or ("right sizing" in nt) or ("rightsizing" in nt) or ("rightsize" in nt)
            if cond_ok and onprem_vs_needs and rightsizing:
                obs_ok = True
    if obs_ok:
        scores["observations_bullets_and_content"] = 1.0

    # Quantified On-Prem Power Cost
    power_sec = brief_sections.get(_normalize_title("Quantified On-Prem Power Cost"), "")
    power_ok = False
    if power_sec and annual_power_cost is not None:
        if _number_present(power_sec, int(annual_power_cost)):
            power_ok = True
    if power_ok:
        scores["power_cost_computation_present_and_correct"] = 1.0

    # Risks & Watchouts
    risks_sec = brief_sections.get(_normalize_title("Risks & Watchouts"), "")
    risk_bullets = _bullet_lines(risks_sec)
    risks_ok = False
    if risk_bullets and len(risk_bullets) >= 3:
        nt = _normalize_text(risks_sec)
        has_egress = "egress" in nt
        has_backup = "backup" in nt or "retention" in nt
        # Accept any other input-tied risk is present; ensure at least egress and backup are covered
        if has_egress and has_backup:
            risks_ok = True
    if risks_ok:
        scores["risks_watchouts_quality_and_tied_to_inputs"] = 1.0

    # Decision Checkpoints
    dc_sec = brief_sections.get(_normalize_title("Decision Checkpoints"), "")
    dc_bullets = _bullet_lines(dc_sec)
    dc_ok = False
    if dc_bullets and len(dc_bullets) >= 3:
        # Expect they are questions; at least 3 contain '?'
        if sum(1 for b in dc_bullets if "?" in b) >= 3:
            dc_ok = True
    if dc_ok:
        scores["decision_checkpoints_count"] = 1.0

    # Validate meeting_notes_action_items.md
    mn_path = workspace / "output" / "meeting_notes_action_items.md"
    mn_text = _read_text(mn_path)
    mn_sections = _extract_sections(mn_text or "", ["Attendees", "Agenda", "Key Data Points", "Open Questions", "Action Items"])

    # Attendees section
    attendees_ok = False
    if past_notes and "participants" in past_notes:
        participants = past_notes.get("participants") or []
        att_sec = mn_sections.get(_normalize_title("Attendees"), "")
        if participants and att_sec:
            ok = True
            for p in participants:
                if p not in att_sec:
                    ok = False
                    break
            attendees_ok = ok
    if attendees_ok:
        scores["meeting_notes_attendees_extracted"] = 1.0

    # Agenda section
    agenda_ok = False
    agenda_sec = mn_sections.get(_normalize_title("Agenda"), "")
    if agenda_sec:
        nt = _normalize_text(agenda_sec)
        has_roi = "roi tradeoffs" in nt or ("roi" in nt and "tradeoff" in nt)
        has_onprem_cloud = ("on-prem" in nt or "on prem" in nt) and "cloud" in nt
        has_resource_limits = "resource/limits" in nt or ("resource" in nt and "limits" in nt)
        has_risks = "risks" in nt
        has_decisions_today = "decisions to make today" in nt or ("decisions" in nt and "today" in nt)
        if has_roi and has_onprem_cloud and has_resource_limits and has_risks and has_decisions_today:
            agenda_ok = True
    if agenda_ok:
        scores["meeting_notes_agenda_includes_required_items"] = 1.0

    # Key Data Points: must include CPU/Memory totals and annual power cost
    kdp_ok = False
    kdp_sec = mn_sections.get(_normalize_title("Key Data Points"), "")
    if kdp_sec and onprem_cpu is not None and cloud_cpu is not None and service_cpu is not None and onprem_mem is not None and cloud_mem is not None and service_mem is not None and annual_power_cost is not None:
        present = (_number_present(kdp_sec, int(onprem_cpu)) and
                   _number_present(kdp_sec, int(cloud_cpu)) and
                   _number_present(kdp_sec, int(service_cpu)) and
                   _number_present(kdp_sec, int(onprem_mem)) and
                   _number_present(kdp_sec, int(cloud_mem)) and
                   _number_present(kdp_sec, int(service_mem)) and
                   _number_present(kdp_sec, int(annual_power_cost)))
        if present:
            kdp_ok = True
    if kdp_ok:
        scores["meeting_notes_key_data_points_correct"] = 1.0

    # Open Questions verbatim
    oq_ok = False
    if past_notes and "open_questions" in past_notes:
        oq_list = past_notes.get("open_questions") or []
        mn_oq_sec = mn_sections.get(_normalize_title("Open Questions"), "")
        if oq_list and mn_oq_sec:
            ok = True
            for q in oq_list:
                if q not in mn_oq_sec:
                    ok = False
                    break
            oq_ok = ok
    if oq_ok:
        scores["meeting_notes_open_questions_verbatim"] = 1.0

    # Action Items mapping and due window
    ai_ok = False
    ai_sec = mn_sections.get(_normalize_title("Action Items"), "")
    if ai_sec and past_notes and "participants" in past_notes:
        bullets = _bullet_lines(ai_sec)
        # Must have at least 4 items
        if len(bullets) >= 4:
            # Each bullet must include "Due: 7d"
            all_due = all("Due: 7d" in b for b in bullets)
            # Role owners must match participants roles
            participants = past_notes.get("participants") or []
            # Map roles available from participants lines
            roles = []
            for p in participants:
                # Text format: "Name — Role"
                if "—" in p:
                    role = p.split("—", 1)[1].strip()
                    roles.append(role)
                elif "-" in p:
                    # fallback
                    parts = p.split("-", 1)
                    if len(parts) > 1:
                        roles.append(parts[1].strip())
            # Required mappings:
            # Egress-related -> Network Engineering Manager
            has_egress_item = any(("egress" in _normalize_text(b) and "network engineering manager" in _normalize_text(b)) for b in bullets)
            # Backup retention -> Backup Administrator
            has_backup_item = any((("backup" in _normalize_text(b) or "retention" in _normalize_text(b)) and "backup administrator" in _normalize_text(b)) for b in bullets)
            # Test environment -> SRE Manager
            has_test_item = any((("test environment" in _normalize_text(b) or "blue/green" in _normalize_text(b)) and "sre manager" in _normalize_text(b)) for b in bullets)
            # Additional item exact phrase and owner FinOps Lead
            additional_phrase = "Validate reserved coverage assumptions (50% reserved, 12% savings plan) against last quarter workloads"
            has_additional_item = any((additional_phrase in b and "FinOps Lead" in b) for b in bullets)
            # Owners drawn from participants roles
            owners_ok = all(role in roles for role in ["Network Engineering Manager", "Backup Administrator", "SRE Manager", "FinOps Lead"])
            if all_due and has_egress_item and has_backup_item and has_test_item and has_additional_item and owners_ok:
                ai_ok = True
    if ai_ok:
        scores["meeting_notes_action_items_mapped_and_due_window"] = 1.0

    return scores


def main() -> None:
        workspace = "."
        if len(sys.argv) > 1 and sys.argv[1]:
            workspace = sys.argv[1]
        result = grade(transcript=[], workspace_path=workspace)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()