import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[Any]:
    try:
        txt = read_text_safe(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def load_csv_safe(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict({k: (v if v is not None else "") for k, v in row.items()}) for row in reader]
            return rows
    except Exception:
        return None


def load_csv_header(path: Path) -> Optional[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return []
            return [h.strip() for h in header]
    except Exception:
        return None


def parse_simple_yaml_mapping(path: Path) -> Optional[Dict[str, str]]:
    """
    Very simple YAML parser for flat key: "value" pairs. Returns dict of strings.
    """
    text = read_text_safe(path)
    if text is None:
        return None
    data: Dict[str, str] = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                # Not a simple key: value line, fail parsing
                return None
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove inline comments
            if " #" in val:
                val = val.split(" #", 1)[0].strip()
            # Strip quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            data[key] = val
        return data
    except Exception:
        return None


def str_to_bool(s: str) -> Optional[bool]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in {"true", "t", "yes", "y", "1"}:
        return True
    if v in {"false", "f", "no", "n", "0"}:
        return False
    return None


def is_domain_like(s: str) -> bool:
    if not s or any(ch.isspace() for ch in s):
        return False
    if s.lower().startswith("http://") or s.lower().startswith("https://"):
        return False
    if "/" in s:
        return False
    # Basic domain regex: label.labels.tld
    if re.match(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", s) is None:
        return False
    return True


def word_count(s: str) -> int:
    return len([w for w in re.split(r"\s+", s.strip()) if w])


def is_iso8601(s: str) -> bool:
    if not isinstance(s, str):
        return False
    try:
        # Handle Zulu time
        if s.endswith("Z"):
            try:
                datetime.fromisoformat(s[:-1] + "+00:00")
                return True
            except Exception:
                return False
        else:
            datetime.fromisoformat(s)
            return True
    except Exception:
        return False


def get_headings(md_text: str) -> List[Tuple[str, int]]:
    """
    Return list of (title, line_index) for lines that are Markdown headings (#, ##, ###).
    """
    headings: List[Tuple[str, int]] = []
    lines = md_text.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            title = m.group(2).strip()
            headings.append((title, idx))
    return headings


def find_section_bounds(md_text: str, title: str) -> Optional[Tuple[int, int]]:
    """
    Find start (inclusive) and end (exclusive) line indices for a section with given title.
    Matches headings with any number of leading '#' but exact title match.
    """
    lines = md_text.splitlines()
    start_idx = None
    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            t = m.group(2).strip()
            if t == title:
                start_idx = idx
                break
    if start_idx is None:
        return None
    # find next heading
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if re.match(r"^(#{1,6})\s+(.*\S)\s*$", lines[j]):
            end_idx = j
            break
    return (start_idx, end_idx)


def section_text(md_text: str, bounds: Tuple[int, int]) -> str:
    lines = md_text.splitlines()
    start, end = bounds
    # Exclude the heading line itself
    content = lines[start + 1:end]
    return "\n".join(content).strip()


def slugify_name(name: str) -> str:
    # Lowercase, hyphens between words. Remove non-word characters except spaces and hyphens before splitting.
    cleaned = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    parts = [p for p in re.split(r"\s+", cleaned.lower().strip()) if p]
    return "-".join(parts)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "shortlist_exists_and_parseable": 0.0,
        "shortlist_columns_exact": 0.0,
        "shortlist_min_four_rows": 0.0,
        "shortlist_domains_valid": 0.0,
        "shortlist_booleans_valid": 0.0,
        "shortlist_maintenance_fields_valid": 0.0,
        "shortlist_alignment_notes_refer_constraints": 0.0,
        "shortlist_meets_constraints_booleans_true": 0.0,
        "shortlist_is_open_source_true": 0.0,
        "search_log_exists_and_parseable": 0.0,
        "search_log_min_three_distinct_queries": 0.0,
        "search_log_entries_fields_valid": 0.0,
        "search_log_timestamps_iso8601": 0.0,
        "project_brief_v2_exists": 0.0,
        "project_brief_v2_has_required_sections_at_top": 0.0,
        "project_brief_v2_shortlist_names_match": 0.0,
        "plan_section_has_week1_week2": 0.0,
        "open_questions_section_has_three_questions": 0.0,
        "emails_all_present": 0.0,
        "emails_subject_and_greeting_personalized": 0.0,
        "emails_include_shortlist_names": 0.0,
        "emails_include_week1_week2": 0.0,
        "emails_include_two_asks": 0.0,
        "emails_collaborative_tone": 0.0,
    }

    # Load inputs
    constraints_path = workspace / "input" / "constraints.yaml"
    constraints = parse_simple_yaml_mapping(constraints_path)

    stakeholders_path = workspace / "input" / "stakeholders.csv"
    stakeholders_rows = load_csv_safe(stakeholders_path)

    # Shortlist checks
    expected_columns = [
        "framework_name",
        "official_site_domain",
        "documentation_root_domain",
        "repo_host_domain",
        "license_identifier_or_text",
        "meets_python_version",
        "meets_local_only",
        "is_open_source",
        "maintenance_status",
        "status_note",
        "alignment_notes",
    ]
    shortlist_path = workspace / "outputs" / "shortlist.csv"
    shortlist_rows = None
    if shortlist_path.exists():
        header = load_csv_header(shortlist_path)
        rows = load_csv_safe(shortlist_path)
        if header is not None and rows is not None:
            shortlist_rows = rows
            scores["shortlist_exists_and_parseable"] = 1.0
            # Columns exact
            if header == expected_columns:
                scores["shortlist_columns_exact"] = 1.0
            # At least four rows
            if len(rows) >= 4:
                scores["shortlist_min_four_rows"] = 1.0

            # Domains valid and fields validation
            domains_ok = True
            bools_ok = True
            maintenance_ok = True
            align_notes_ok = True
            meets_constraints_true = True
            open_source_true = True

            constraint_keys = set()
            if constraints:
                constraint_keys = {k for k in constraints.keys()}
            # Only allow known keys for alignment check
            expected_constraint_keys = {"python_version", "execution_mode", "budget", "license_preference", "data_privacy"}

            for row in rows:
                # Domain fields
                for col in ["official_site_domain", "documentation_root_domain", "repo_host_domain"]:
                    val = (row.get(col) or "").strip()
                    if not is_domain_like(val):
                        domains_ok = False
                # Booleans
                for col in ["meets_python_version", "meets_local_only", "is_open_source"]:
                    val = (row.get(col) or "").strip()
                    b = str_to_bool(val)
                    if b is None:
                        bools_ok = False
                # Meets constraints booleans must be true (since frameworks must meet constraints)
                for col in ["meets_python_version", "meets_local_only"]:
                    val = (row.get(col) or "").strip()
                    b = str_to_bool(val)
                    if b is None or b is False:
                        meets_constraints_true = False
                val = (row.get("is_open_source") or "").strip()
                b = str_to_bool(val)
                if b is None or b is False:
                    open_source_true = False
                # Maintenance
                status = (row.get("maintenance_status") or "").strip()
                if status not in {"Established", "Active", "Emerging"}:
                    maintenance_ok = False
                note = (row.get("status_note") or "").strip()
                if not note or word_count(note) > 15:
                    maintenance_ok = False
                # Alignment notes
                a_notes = (row.get("alignment_notes") or "").strip()
                if not a_notes or word_count(a_notes) > 50:
                    align_notes_ok = False
                else:
                    # Must reference at least two constraint keys explicitly
                    lower = a_notes.lower()
                    hits = 0
                    for key in expected_constraint_keys:
                        if key in lower:
                            hits += 1
                    if hits < 2:
                        align_notes_ok = False

            if domains_ok:
                scores["shortlist_domains_valid"] = 1.0
            if bools_ok:
                scores["shortlist_booleans_valid"] = 1.0
            if maintenance_ok:
                scores["shortlist_maintenance_fields_valid"] = 1.0
            if align_notes_ok:
                scores["shortlist_alignment_notes_refer_constraints"] = 1.0
            if meets_constraints_true:
                scores["shortlist_meets_constraints_booleans_true"] = 1.0
            if open_source_true:
                scores["shortlist_is_open_source_true"] = 1.0

    # Search log checks
    search_log_path = workspace / "outputs" / "search_log.json"
    search_log = None
    if search_log_path.exists():
        search_log = load_json_safe(search_log_path)
        if isinstance(search_log, list):
            scores["search_log_exists_and_parseable"] = 1.0
            # Min three distinct queries
            queries = []
            entries_fields_valid = True
            timestamps_ok = True
            purposes_ok = True
            for item in search_log:
                if not isinstance(item, dict):
                    entries_fields_valid = False
                    continue
                q = item.get("query")
                t = item.get("timestamp_iso")
                p = item.get("purpose")
                if not isinstance(q, str) or not q.strip():
                    entries_fields_valid = False
                else:
                    queries.append(q.strip())
                if not isinstance(t, str) or not is_iso8601(t):
                    timestamps_ok = False
                if not isinstance(p, str) or not p.strip() or word_count(p) > 20:
                    purposes_ok = False
            if len(set(queries)) >= 3:
                scores["search_log_min_three_distinct_queries"] = 1.0
            if entries_fields_valid and purposes_ok:
                scores["search_log_entries_fields_valid"] = 1.0
            if timestamps_ok:
                scores["search_log_timestamps_iso8601"] = 1.0

    # Project brief v2 checks
    pb_v2_path = workspace / "outputs" / "project_brief.v2.md"
    pb_v2_text = read_text_safe(pb_v2_path)
    if pb_v2_text is not None:
        scores["project_brief_v2_exists"] = 1.0
        # Required sections at the top
        required_titles = [
            "Shortlist Summary",
            "Iterative Evaluation Plan (2 weeks)",
            "Open Questions for Stakeholders",
        ]
        headings = get_headings(pb_v2_text)
        # Find first three heading titles encountered in the file (skipping any leading blank lines)
        first_three_titles = [t for t, _ in headings[:3]]
        if first_three_titles == required_titles:
            scores["project_brief_v2_has_required_sections_at_top"] = 1.0

        # Extract sections for further validation if present
        # Shortlist Summary must list the framework names
        shortlist_names: List[str] = []
        if shortlist_rows:
            for r in shortlist_rows:
                name = (r.get("framework_name") or "").strip()
                if name:
                    shortlist_names.append(name)
        # Only check names match if we have names and we can find the section
        ss_bounds = find_section_bounds(pb_v2_text, "Shortlist Summary")
        if ss_bounds and shortlist_names:
            ss_text = section_text(pb_v2_text, ss_bounds).lower()
            all_present = True
            for nm in shortlist_names:
                if nm.lower() not in ss_text:
                    all_present = False
                    break
            if all_present:
                scores["project_brief_v2_shortlist_names_match"] = 1.0

        # Plan section must include Week 1 and Week 2
        plan_bounds = find_section_bounds(pb_v2_text, "Iterative Evaluation Plan (2 weeks)")
        if plan_bounds:
            plan_text = section_text(pb_v2_text, plan_bounds)
            if ("week 1" in plan_text.lower()) and ("week 2" in plan_text.lower()):
                scores["plan_section_has_week1_week2"] = 1.0

        # Open Questions section must have at least three concrete questions (count '?')
        oq_bounds = find_section_bounds(pb_v2_text, "Open Questions for Stakeholders")
        if oq_bounds:
            oq_text = section_text(pb_v2_text, oq_bounds)
            q_marks = oq_text.count("?")
            if q_marks >= 3:
                scores["open_questions_section_has_three_questions"] = 1.0

    # Emails checks
    emails_dir = workspace / "outputs" / "emails"
    emails_present = True
    subject_and_greeting_ok = True
    emails_include_names_ok = True
    emails_week_ok = True
    emails_two_asks_ok = True
    emails_collab_tone_ok = True

    email_checks_applicable = False
    if stakeholders_rows is not None and shortlist_rows is not None:
        email_checks_applicable = True
        shortlist_names_set = { (r.get("framework_name") or "").strip().lower() for r in shortlist_rows if (r.get("framework_name") or "").strip() }
        for row in stakeholders_rows:
            name = (row.get("name") or "").strip()
            role = (row.get("role") or "").strip()
            if not name:
                emails_present = False
                subject_and_greeting_ok = False
                emails_include_names_ok = False
                emails_week_ok = False
                emails_two_asks_ok = False
                emails_collab_tone_ok = False
                continue
            slug = slugify_name(name)
            email_path = emails_dir / f"{slug}.txt"
            if not email_path.exists():
                emails_present = False
                subject_and_greeting_ok = False
                emails_include_names_ok = False
                emails_week_ok = False
                emails_two_asks_ok = False
                emails_collab_tone_ok = False
                continue
            content = read_text_safe(email_path) or ""
            # Subject line: first non-empty line must start with "Subject:"
            first_nonempty_line = ""
            for line in content.splitlines():
                if line.strip():
                    first_nonempty_line = line.strip()
                    break
            if not first_nonempty_line.lower().startswith("subject:"):
                subject_and_greeting_ok = False
            # Personalized greeting by name and role (check both appear)
            if name.lower() not in content.lower() or (role and role.lower() not in content.lower()):
                subject_and_greeting_ok = False
            # Include shortlist names (framework names only summary presence)
            for nm in shortlist_names_set:
                if nm and nm not in content.lower():
                    emails_include_names_ok = False
                    break
            # Include Week 1 and Week 2
            if ("week 1" not in content.lower()) or ("week 2" not in content.lower()):
                emails_week_ok = False
            # Two asks: feedback on must-have features and deployment preferences
            # Look for 'must-have' or 'must have' and 'deployment' terms
            lower_c = content.lower()
            if not (("must-have" in lower_c or "must have" in lower_c) and ("deployment" in lower_c)):
                emails_two_asks_ok = False
            # Collaborative tone inviting iteration and checkpoints
            if not (("iterate" in lower_c or "iteration" in lower_c or "collaborative" in lower_c) and ("checkpoint" in lower_c or "checkpoints" in lower_c)):
                emails_collab_tone_ok = False

    # Set email-related scores only if applicable (both stakeholders and shortlist exist)
    if email_checks_applicable:
        if emails_present:
            scores["emails_all_present"] = 1.0
        if subject_and_greeting_ok:
            scores["emails_subject_and_greeting_personalized"] = 1.0
        if emails_include_names_ok:
            scores["emails_include_shortlist_names"] = 1.0
        if emails_week_ok:
            scores["emails_include_week1_week2"] = 1.0
        if emails_two_asks_ok:
            scores["emails_include_two_asks"] = 1.0
        if emails_collab_tone_ok:
            scores["emails_collaborative_tone"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()