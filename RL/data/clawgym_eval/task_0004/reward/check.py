import json
import sys
import re
from pathlib import Path
from datetime import date

# ----------------------
# Helper functions
# ----------------------

def read_text_file(path: Path):
    try:
        text = path.read_text(encoding="utf-8")
        return text
    except Exception:
        return None

def load_json_file(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_json_file(path: Path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

def parse_training_yaml(path: Path):
    """
    Minimal parser for the specific YAML structure provided.
    Expected structure:
    reference_date: YYYY-MM-DD
    modules:
      - id: "..."
        title: "..."
        last_reviewed: "YYYY-MM-DD"
        source_org: "..."
        notes: "..."
    """
    text = read_text_file(path)
    if text is None:
        return None
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    result = {"reference_date": None, "modules": []}
    in_modules = False
    current = None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not in_modules:
            # top-level keys
            if line.startswith("modules:"):
                in_modules = True
                continue
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m:
                key = m.group(1)
                val = m.group(2).strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                result[key] = val
            continue
        else:
            # inside modules list
            if line.startswith("- "):
                # start new module item
                current = {}
                result["modules"].append(current)
                rest = line[2:].strip()
                if rest:
                    m = re.match(r"^(\w+):\s*(.*)$", rest)
                    if m:
                        k = m.group(1)
                        v = m.group(2).strip()
                        if v.startswith('"') and v.endswith('"'):
                            v = v[1:-1]
                        current[k] = v
                continue
            else:
                # continuation lines for current item
                if current is None:
                    # malformed
                    return None
                m = re.match(r"^(\w+):\s*(.*)$", line)
                if m:
                    k = m.group(1)
                    v = m.group(2).strip()
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    current[k] = v
                else:
                    # ignore or malformed
                    continue
    # Basic validation
    if not result.get("reference_date"):
        return None
    if not isinstance(result.get("modules"), list) or not result["modules"]:
        return result  # allow empty list if present
    # ensure required fields exist in modules
    for mod in result["modules"]:
        for req in ("id", "title", "last_reviewed", "source_org"):
            if req not in mod:
                return None
    return result

def parse_yyyy_mm_dd(s: str):
    try:
        parts = s.split("-")
        if len(parts) != 3:
            return None
        y, m, d = map(int, parts)
        return date(y, m, d)
    except Exception:
        return None

def add_years(dt: date, years: int) -> date:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # handle Feb 29 -> Feb 28 for non-leap year
        if dt.month == 2 and dt.day == 29:
            return dt.replace(year=dt.year + years, month=2, day=28)
        raise

def compute_status_and_reasons(last_reviewed: date, reference: date, source_org: str):
    stale = reference > add_years(last_reviewed, 3)
    needs = (source_org.strip().lower() == "unknown")
    if stale and needs:
        status = "stale_and_needs_research"
    elif stale:
        status = "stale"
    elif needs:
        status = "needs_research"
    else:
        status = "current"
    reasons = []
    if stale:
        reasons.append("stale")
    if needs:
        reasons.append("needs_research")
    return status, reasons

def build_expected_audit(yaml_data: dict):
    mapping = {
        "mayday": "MAYDAY",
        "ics_201": "ICS",
        "ppe_doffing": "PPE",
        "ladder_ops": "Ladders",
        "hose_advance": "Hose",
    }
    ref_date = parse_yyyy_mm_dd(yaml_data["reference_date"])
    if ref_date is None:
        return None
    expected = {}
    for m in yaml_data.get("modules", []):
        lr = parse_yyyy_mm_dd(m.get("last_reviewed", ""))
        if lr is None:
            return None
        status, reasons = compute_status_and_reasons(lr, ref_date, m.get("source_org", ""))
        expected[m["id"]] = {
            "id": m["id"],
            "title": m["title"],
            "last_reviewed": m["last_reviewed"],
            "topic": mapping.get(m["id"]),
            "status": status,
            "reasons": reasons,
        }
    return expected

def domains_for_org(org: str):
    org_upper = org.strip().upper()
    if org_upper == "NFPA":
        return ["nfpa.org"]
    if org_upper == "FEMA":
        return ["fema.gov"]
    if org_upper == "USFA":
        return ["fema.gov"]  # USFA is under fema.gov
    if org_upper == "NIOSH":
        return ["cdc.gov"]
    if org_upper == "OSHA":
        return ["osha.gov"]
    return []

def extract_domain(url: str):
    m = re.match(r'^\s*(https?://)([^/]+)', url.strip(), re.IGNORECASE)
    if not m:
        return None
    host = m.group(2).lower()
    # strip port
    host = host.split(":")[0]
    return host

def bullet_lines(text: str):
    lines = text.splitlines()
    bullets = []
    for ln in lines:
        if re.match(r'^\s*[-*]\s+', ln):
            bullets.append(ln.strip())
    return bullets

def normalized_lines(s: str):
    # normalize whitespace at line ends for comparison
    return [ln.rstrip() for ln in s.splitlines()]

def is_prefix_by_lines(original: str, updated: str) -> bool:
    orig_lines = normalized_lines(original)
    upd_lines = normalized_lines(updated)
    # Remove possible trailing empty lines for comparison
    while orig_lines and not orig_lines[-1]:
        orig_lines.pop()
    while upd_lines and not upd_lines[-1]:
        upd_lines.pop()
    if len(upd_lines) < len(orig_lines):
        return False
    for i, ln in enumerate(orig_lines):
        if upd_lines[i] != ln:
            return False
    return True

def count_sentences(s: str) -> int:
    # simple heuristic: count '.', '!' or '?' as sentence terminators
    # avoid counting abbreviations by collapsing multiple punctuation
    if not isinstance(s, str):
        return 0
    # Replace ellipses with a single terminator
    cleaned = re.sub(r'\.{2,}', '.', s)
    return len([ch for ch in cleaned if ch in ".!?"])

def compute_status_counts(expected_audit: dict):
    counts = {"current": 0, "stale": 0, "needs_research": 0, "stale_and_needs_research": 0}
    for v in expected_audit.values():
        st = v["status"]
        if st in counts:
            counts[st] += 1
    return counts

# ----------------------
# Grader
# ----------------------

def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "audit_file_parses_and_matches_modules": 0.0,
        "audit_status_and_topics_correct": 0.0,
        "audit_reasons_appropriate": 0.0,
        "sources_count_and_orgs_valid": 0.0,
        "sources_official_domains_and_fields": 0.0,
        "sources_cover_flagged_topics": 0.0,
        "findings_summary_counts_present": 0.0,
        "findings_actions_for_all_noncurrent": 0.0,
        "findings_open_questions_section": 0.0,
        "aars_contains_original_and_sections": 0.0,
        "aars_references_from_sources": 0.0,
        "email_subject_and_length": 0.0,
        "email_paths_and_bullets": 0.0,
        "email_request_language": 0.0,
    }

    # Load YAML config
    yaml_path = workspace / "config" / "training_drill.yml"
    yaml_data = parse_training_yaml(yaml_path) if yaml_path.exists() else None

    expected_audit = None
    if yaml_data:
        expected_audit = build_expected_audit(yaml_data)

    # Load out/audit_report.json
    audit_path = workspace / "out" / "audit_report.json"
    audit_data = load_json_file(audit_path) if audit_path.exists() else None

    # Check audit against yaml-derived expectations
    if yaml_data and expected_audit and isinstance(audit_data, list):
        # index audit by id
        audit_by_id = {}
        ok_ids = True
        try:
            for obj in audit_data:
                if not isinstance(obj, dict) or "id" not in obj:
                    ok_ids = False
                    break
                audit_by_id[obj["id"]] = obj
        except Exception:
            ok_ids = False

        ids_expected = set(expected_audit.keys())
        ids_found = set(audit_by_id.keys()) if ok_ids else set()
        # must match exactly the ids produced from YAML
        if ok_ids and ids_found == ids_expected:
            # baseline structural match
            scores["audit_file_parses_and_matches_modules"] = 1.0

            # verify statuses, topics, titles, last_reviewed
            topics_ok = True
            status_ok = True
            reasons_ok = True
            for mid, exp in expected_audit.items():
                rec = audit_by_id.get(mid, {})
                # required fields
                # id, title, last_reviewed string in YYYY-MM-DD, topic, status, reasons array
                if rec.get("id") != exp["id"]:
                    topics_ok = False
                if rec.get("title") != exp["title"]:
                    topics_ok = False
                if rec.get("last_reviewed") != exp["last_reviewed"] or parse_yyyy_mm_dd(rec.get("last_reviewed", "")) is None:
                    topics_ok = False
                if rec.get("topic") != exp["topic"]:
                    topics_ok = False
                if rec.get("status") != exp["status"]:
                    status_ok = False
                # reasons validation
                reasons = rec.get("reasons")
                if not isinstance(reasons, list):
                    reasons_ok = False
                else:
                    if exp["status"] == "current":
                        # should be empty array
                        if len(reasons) != 0:
                            reasons_ok = False
                    else:
                        # must include reasons corresponding to flags
                        need_stale = exp["status"] in ("stale", "stale_and_needs_research")
                        need_needs = exp["status"] in ("needs_research", "stale_and_needs_research")
                        text = " ".join([str(x).lower() for x in reasons])
                        if need_stale and ("stale" not in text):
                            reasons_ok = False
                        if need_needs and not (("needs" in text and "research" in text) or "needs_research" in text or "unknown" in text):
                            reasons_ok = False
            if status_ok and topics_ok:
                scores["audit_status_and_topics_correct"] = 1.0
            if reasons_ok:
                scores["audit_reasons_appropriate"] = 1.0

    # Load research/sources.json
    sources_path = workspace / "research" / "sources.json"
    sources = load_json_file(sources_path) if sources_path.exists() else None

    allowed_orgs = {"NFPA", "FEMA", "USFA", "NIOSH", "OSHA"}
    allowed_topics = {"MAYDAY", "ICS", "PPE", "Ladders", "Hose"}

    if isinstance(sources, list):
        count_ok = 3 <= len(sources) <= 5
        orgs_used = set()
        fields_ok = True
        domains_ok = True
        for entry in sources:
            if not isinstance(entry, dict):
                fields_ok = False
                break
            title = entry.get("title")
            org = entry.get("organization")
            year = entry.get("year")
            url = entry.get("url")
            topic = entry.get("topic")
            # Check required fields
            if not isinstance(title, str) or not title.strip():
                fields_ok = False
            if not isinstance(org, str) or org.strip().upper() not in allowed_orgs:
                fields_ok = False
            else:
                orgs_used.add(org.strip().upper())
            if year is not None and not isinstance(year, int):
                fields_ok = False
            if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
                fields_ok = False
            if topic not in allowed_topics:
                fields_ok = False
            # relevance note detection: accept keys note/relevance/relevance_note/summary
            rel = None
            for k in ("relevance_note", "relevance", "note", "summary"):
                if isinstance(entry.get(k), str):
                    rel = entry.get(k).strip()
                    if rel:
                        break
            if rel is None:
                fields_ok = False
            else:
                # 1–2 sentences
                n_sent = count_sentences(rel)
                if n_sent == 0 or n_sent > 2:
                    fields_ok = False
            # domain check for official URLs
            host = extract_domain(url) if isinstance(url, str) else None
            if host is None:
                domains_ok = False
            else:
                allowed_domains = domains_for_org(org if isinstance(org, str) else "")
                if not allowed_domains:
                    domains_ok = False
                else:
                    # check if host endswith any allowed domain
                    if not any(host.endswith(dom) for dom in allowed_domains):
                        domains_ok = False

        if count_ok and len(orgs_used & allowed_orgs) >= 2:
            scores["sources_count_and_orgs_valid"] = 1.0
        if fields_ok and domains_ok:
            scores["sources_official_domains_and_fields"] = 1.0

        # sources cover topics flagged as stale or needs_research
        flagged_topics = set()
        if isinstance(audit_data, list):
            # prefer actual audit file topics
            for obj in audit_data:
                st = obj.get("status")
                tp = obj.get("topic")
                if st in ("stale", "needs_research", "stale_and_needs_research") and tp in allowed_topics:
                    flagged_topics.add(tp)
        elif expected_audit:
            for v in expected_audit.values():
                if v["status"] in ("stale", "needs_research", "stale_and_needs_research"):
                    flagged_topics.add(v["topic"])
        if flagged_topics:
            covered = sum(1 for e in sources if e.get("topic") in flagged_topics)
            if covered >= 2:
                scores["sources_cover_flagged_topics"] = 1.0

    # findings_and_actions.md
    findings_path = workspace / "out" / "findings_and_actions.md"
    findings_text = read_text_file(findings_path) if findings_path.exists() else None
    if findings_text is not None and expected_audit:
        # Summary counts
        counts = compute_status_counts(expected_audit)
        summary_ok = True
        # Must include counts for each status label paired with the correct number
        for status_label, cnt in counts.items():
            # search for e.g., "current: 2" or "current - 2" or "current (2)"
            # robust pattern: status word followed by non-digits then digits equal to cnt
            pat = re.compile(rf"{re.escape(status_label)}\D+{cnt}\b", re.IGNORECASE)
            if not pat.search(findings_text):
                summary_ok = False
                break
        if summary_ok:
            scores["findings_summary_counts_present"] = 1.0

        # Actions per non-current module
        non_current = [v for v in expected_audit.values() if v["status"] != "current"]
        bullets = bullet_lines(findings_text)
        org_names = set()
        if isinstance(sources, list):
            for e in sources:
                if isinstance(e, dict) and isinstance(e.get("organization"), str):
                    org_names.add(e["organization"].strip())
        action_ok = True
        for mod in non_current:
            found = False
            for bl in bullets:
                # must include module id and status
                if (mod["id"].lower() in bl.lower()) and (mod["status"].lower() in bl.lower()):
                    # must reference at least one organization from research and at least one topic string
                    has_org = any(org.lower() in bl.lower() for org in org_names) if org_names else False
                    has_topic = any(tp.lower() in bl.lower() for tp in ["MAYDAY", "ICS", "PPE", "Ladders", "Hose"])
                    if has_org and has_topic:
                        found = True
                        break
            if not found:
                action_ok = False
                break
        if action_ok and non_current:
            scores["findings_actions_for_all_noncurrent"] = 1.0

        # Open questions / dependencies section
        # Look for a heading or phrase indicating the section exists
        if re.search(r'^\s*#{1,6}\s*open questions', findings_text, re.IGNORECASE | re.MULTILINE) or \
           re.search(r'^\s*#{1,6}\s*dependencies', findings_text, re.IGNORECASE | re.MULTILINE) or \
           re.search(r'open questions', findings_text, re.IGNORECASE):
            scores["findings_open_questions_section"] = 1.0

    # aars_template_updated.md
    aars_src_path = workspace / "doc" / "aars_template.md"
    aars_updated_path = workspace / "out" / "aars_template_updated.md"
    aars_src = read_text_file(aars_src_path) if aars_src_path.exists() else None
    aars_updated = read_text_file(aars_updated_path) if aars_updated_path.exists() else None
    if aars_src is not None and aars_updated is not None:
        # Check original content included as prefix and required sections present
        has_original = is_prefix_by_lines(aars_src, aars_updated)
        # required headings present after the original
        # find part after original
        upd_lines = normalized_lines(aars_updated)
        orig_lines = normalized_lines(aars_src)
        idx_after = len(orig_lines)
        tail_text = "\n".join(upd_lines[idx_after:]) if idx_after <= len(upd_lines) else ""
        has_lessons = re.search(r'^\s*#{1,6}\s*Lessons Learned', tail_text, re.IGNORECASE | re.MULTILINE) is not None
        has_gaps = re.search(r'^\s*#{1,6}\s*Training Gaps', tail_text, re.IGNORECASE | re.MULTILINE) is not None
        has_refs = re.search(r'^\s*#{1,6}\s*References', tail_text, re.IGNORECASE | re.MULTILINE) is not None
        if has_original and has_lessons and has_gaps and has_refs:
            scores["aars_contains_original_and_sections"] = 1.0

        # At least two citation stubs derived from sources.json in format: "- Organization — Title (Year or n.d.)"
        citations_ok = False
        if isinstance(sources, list) and sources:
            # Build possible citation strings
            possible = set()
            for e in sources:
                if not isinstance(e, dict):
                    continue
                org = e.get("organization")
                title = e.get("title")
                year = e.get("year")
                if not isinstance(org, str) or not isinstance(title, str):
                    continue
                year_str = f"{year}" if isinstance(year, int) else "n.d."
                # Accept both em dash and hyphen variants
                stub1 = f"- {org} — {title} ({year_str})"
                stub2 = f"- {org} - {title} ({year_str})"
                possible.add(stub1.lower())
                possible.add(stub2.lower())
            # Count matches in updated text (case-insensitive)
            lines = [ln.strip().lower() for ln in aars_updated.splitlines()]
            count = sum(1 for ln in lines if any(ln == p or ln.endswith(p) or p in ln for p in possible))
            if count >= 2:
                citations_ok = True
        if citations_ok:
            scores["aars_references_from_sources"] = 1.0

    # Email to training chief
    email_path = workspace / "communications" / "email_to_training_chief.txt"
    email_text = read_text_file(email_path) if email_path.exists() else None
    if email_text is not None and expected_audit:
        # Subject line and <= 250 words
        has_subject = any(re.match(r'^\s*Subject\s*:\s*.+', ln, re.IGNORECASE) for ln in email_text.splitlines())
        words = re.findall(r'\b\w+\b', email_text)
        if has_subject and len(words) <= 250:
            scores["email_subject_and_length"] = 1.0

        # Must include explicit relative paths to audit and sources
        has_audit_path = "out/audit_report.json" in email_text
        has_sources_path = "research/sources.json" in email_text

        # Must include bullet list of modules flagged for update with their statuses
        bullets = bullet_lines(email_text)
        non_current = [v for v in expected_audit.values() if v["status"] != "current"]
        bullets_ok = True
        for m in non_current:
            ok = any((m["id"].lower() in bl.lower() and m["status"].lower() in bl.lower()) for bl in bullets)
            if not ok:
                bullets_ok = False
                break
        if has_audit_path and has_sources_path and bullets_ok:
            scores["email_paths_and_bullets"] = 1.0

        # Request to approve next steps and a quick sync
        req_approve = re.search(r'\bapprove\b', email_text, re.IGNORECASE) is not None
        req_sync = (re.search(r'\bsync\b', email_text, re.IGNORECASE) is not None) or (re.search(r'\bmeeting\b', email_text, re.IGNORECASE) is not None)
        if req_approve and req_sync:
            scores["email_request_language"] = 1.0

    return scores

# ----------------------
# Main
# ----------------------

def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()