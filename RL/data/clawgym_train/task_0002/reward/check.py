import csv
import json
import re
import sys
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict


def safe_read_text(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Handle files that may include literal "\n" sequences instead of real newlines
        if "\\n" in text and "\n" not in text.strip():
            text = text.replace("\\n", "\n")
        return text
    except Exception:
        return None


def safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(r) for r in reader]
    except Exception:
        return None


def compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def parse_agenda_topics(agenda_path: Path) -> List[str]:
    text = safe_read_text(agenda_path)
    if not text:
        return []
    lines = text.splitlines()
    topics: List[str] = []
    in_topics = False
    for line in lines:
        striped = line.strip()
        if striped.lower().startswith("topics:"):
            in_topics = True
            continue
        if in_topics:
            # Stop if constraints or outcome section reached
            if striped.lower().startswith("constraints:") or striped.lower().startswith("outcome:"):
                break
            if striped.startswith("- ") or striped.startswith("* "):
                item = striped[2:].strip()
                if item:
                    topics.append(item)
    return topics


def extract_section(markdown_text: str, heading: str) -> Optional[str]:
    # Match headings like "# Heading", "## Heading", etc.
    pattern = re.compile(rf"^(#+)\s+{re.escape(heading)}\s*$", re.IGNORECASE | re.MULTILINE)
    m = pattern.search(markdown_text)
    if not m:
        return None
    start = m.end()
    # Find next heading of same or higher level
    level = len(m.group(1))
    rest = markdown_text[start:]
    next_heading = re.search(rf"^#{{1,{level}}}\s+.+$", rest, re.MULTILINE)
    if next_heading:
        end = next_heading.start()
        return rest[:end].strip()
    return rest.strip()


def is_iso8601_datetime_or_date(s: str) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    # Accept date only
    try:
        date.fromisoformat(s)
        return True
    except Exception:
        pass
    # Normalize Zulu
    s2 = s.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def bullets_in_text(text: str) -> List[str]:
    lines = []
    for line in text.splitlines():
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            lines.append(line.strip())
    return lines


def contains_citation(line: str) -> bool:
    # Look for common citation indicators with page or section
    patterns = [
        r"\b(p|pp)\.?\s*\d+",
        r"\bpage[s]?\s*\d+",
        r"\bsection\b[^,\n;)]{0,40}",
        r"\bchapter\b[^,\n;)]{0,40}",
        r"§\s*\w+",
    ]
    for pat in patterns:
        if re.search(pat, line, flags=re.IGNORECASE):
            return True
    return False


def action_items_valid(items: List[str], titles: List[str]) -> bool:
    if not (5 <= len(items) <= 10):
        return False
    # Each item must cite at least one source title and page/section-like indicator
    for it in items:
        title_hit = any(t.lower() in it.lower() for t in titles if t)
        if not title_hit:
            return False
        if not contains_citation(it):
            return False
    return True


def path_is_under(child: Path, parent: Path) -> bool:
    try:
        child_res = child.resolve()
        parent_res = parent.resolve()
    except Exception:
        return False
    try:
        child_res.relative_to(parent_res)
        return True
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "sources_csv_present_and_header": 0.0,
        "sources_csv_row_count": 0.0,
        "sources_csv_file_fields_valid": 0.0,
        "sources_csv_topic_coverage_valid": 0.0,
        "meeting_notes_sections": 0.0,
        "meeting_notes_agenda_topics": 0.0,
        "meeting_notes_sources_overview_titles": 0.0,
        "meeting_notes_key_takeaways_topics": 0.0,
        "action_items_citations": 0.0,
        "inspection_report_valid": 0.0,
        "inspection_totals_consistent": 0.0,
        "readme_includes_queries_criteria_rationales": 0.0,
    }

    # Parse agenda topics
    agenda_path = workspace / "input" / "study_meeting_agenda.md"
    agenda_topics = parse_agenda_topics(agenda_path)

    # Load sources.csv
    sources_csv_path = workspace / "outputs" / "sources.csv"
    rows = load_csv_dicts(sources_csv_path)
    required_fields = [
        "title",
        "organization",
        "domain",
        "file_type",
        "local_path",
        "file_size_bytes",
        "verification_hash",
        "topic_coverage",
        "retrieved_on",
    ]

    header_ok = False
    if rows is not None:
        # Validate header set equality (no missing or extra fields)
        try:
            with sources_csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            header_ok = sorted(header) == sorted(required_fields)
        except Exception:
            header_ok = False

    if rows is not None and header_ok:
        scores["sources_csv_present_and_header"] = 1.0

    # Row count check (3–6 inclusive)
    if rows is not None and header_ok:
        if 3 <= len(rows) <= 6:
            scores["sources_csv_row_count"] = 1.0

    # Validate file fields: domain, file_type, local_path exists under downloads, file size and hash, retrieved_on
    if rows is not None and header_ok and len(rows) > 0:
        all_files_ok = True
        all_topics_ok = True
        downloads_dir = workspace / "downloads"
        for r in rows:
            # domain ends with .edu or .org
            domain = (r.get("domain") or "").strip().lower()
            if not (domain.endswith(".edu") or domain.endswith(".org")):
                all_files_ok = False
                break
            # file_type must be "pdf"
            ftype = (r.get("file_type") or "").strip().lower()
            if ftype != "pdf":
                all_files_ok = False
                break
            # local_path under downloads/ and exists
            lp_raw = (r.get("local_path") or "").strip()
            if not lp_raw or lp_raw.startswith(("/", "\\")) or ".." in Path(lp_raw).parts:
                all_files_ok = False
                break
            local_path = workspace / lp_raw
            if not path_is_under(local_path, downloads_dir):
                all_files_ok = False
                break
            if not local_path.exists() or not local_path.is_file():
                all_files_ok = False
                break
            if local_path.suffix.lower() != ".pdf":
                all_files_ok = False
                break
            # file_size_bytes must match
            try:
                expected_size = int((r.get("file_size_bytes") or "").strip())
            except Exception:
                all_files_ok = False
                break
            actual_size = local_path.stat().st_size
            if expected_size != actual_size:
                all_files_ok = False
                break
            # verification_hash must match sha256
            expected_hash = (r.get("verification_hash") or "").strip().lower()
            actual_hash = compute_sha256(local_path)
            if actual_hash is None or expected_hash != actual_hash.lower():
                all_files_ok = False
                break
            # retrieved_on ISO 8601 date/datetime
            retrieved = (r.get("retrieved_on") or "").strip()
            if not is_iso8601_datetime_or_date(retrieved):
                all_files_ok = False
                break

            # topic_coverage subset of agenda topics (comma-separated)
            tc = (r.get("topic_coverage") or "").strip()
            if not tc:
                all_topics_ok = False
                break
            items = [t.strip() for t in tc.split(",") if t.strip()]
            if not items:
                all_topics_ok = False
                break
            # Check subset: exact match with agenda topics
            for item in items:
                if item not in agenda_topics:
                    all_topics_ok = False
                    break
            if not all_topics_ok:
                break

        if all_files_ok:
            scores["sources_csv_file_fields_valid"] = 1.0
        if all_topics_ok:
            scores["sources_csv_topic_coverage_valid"] = 1.0

    # Meeting notes checks
    notes_path = workspace / "outputs" / "meeting_notes.md"
    notes_text = safe_read_text(notes_path) or ""
    if notes_text:
        agenda_sec = extract_section(notes_text, "Agenda")
        sources_overview_sec = extract_section(notes_text, "Sources Overview")
        key_takeaways_sec = extract_section(notes_text, "Key Takeaways per Topic")
        action_items_sec = extract_section(notes_text, "Action Items for Next Study Meeting")
        if all([agenda_sec is not None, sources_overview_sec is not None, key_takeaways_sec is not None, action_items_sec is not None]):
            scores["meeting_notes_sections"] = 1.0

        # Agenda section includes all topics
        if 'agenda_sec' in locals() and agenda_sec is not None and agenda_topics:
            topics_in_agenda = True
            for t in agenda_topics:
                if t not in agenda_sec:
                    topics_in_agenda = False
                    break
            if topics_in_agenda:
                scores["meeting_notes_agenda_topics"] = 1.0

        # Sources Overview lists each source title
        if 'sources_overview_sec' in locals() and sources_overview_sec is not None and rows:
            titles = [(r.get("title") or "").strip() for r in rows]
            if titles and all(t and (t.lower() in sources_overview_sec.lower()) for t in titles):
                scores["meeting_notes_sources_overview_titles"] = 1.0

        # Key Takeaways per Topic covers each agenda topic
        if 'key_takeaways_sec' in locals() and key_takeaways_sec is not None and agenda_topics:
            if all(t in key_takeaways_sec for t in agenda_topics):
                scores["meeting_notes_key_takeaways_topics"] = 1.0

        # Action items validation: 5–10 and each cites at least one source title and a page/section marker
        if 'action_items_sec' in locals() and action_items_sec is not None and rows:
            titles = [(r.get("title") or "").strip() for r in rows if (r.get("title") or "").strip()]
            action_items = bullets_in_text(action_items_sec)
            if action_items_valid(action_items, titles):
                scores["action_items_citations"] = 1.0

    # Inspection report validation
    inspection_path = workspace / "outputs" / "inspection_report.json"
    report = safe_load_json(inspection_path)
    if isinstance(report, dict):
        keys_ok = all(k in report for k in ["total_candidates", "total_selected", "duplicates_removed", "unusable_count", "unusable_details"])
        types_ok = isinstance(report.get("total_candidates"), int) and isinstance(report.get("total_selected"), int) and isinstance(report.get("duplicates_removed"), int) and isinstance(report.get("unusable_count"), int) and isinstance(report.get("unusable_details"), list)
        unusable_details_ok = True
        if types_ok:
            if len(report.get("unusable_details")) != report.get("unusable_count"):
                unusable_details_ok = False
            else:
                for item in report.get("unusable_details"):
                    if not (isinstance(item, dict) and isinstance(item.get("title", ""), str) and isinstance(item.get("domain", ""), str) and isinstance(item.get("reason", ""), str)):
                        unusable_details_ok = False
                        break
        if keys_ok and types_ok and unusable_details_ok:
            scores["inspection_report_valid"] = 1.0

        # Totals consistency: total_selected == number of sources rows; total_candidates >= total_selected; duplicates_removed >= 0
        if rows is not None and header_ok:
            n_selected = len(rows)
            total_sel = report.get("total_selected")
            total_cand = report.get("total_candidates")
            dups_removed = report.get("duplicates_removed")
            if isinstance(total_sel, int) and isinstance(total_cand, int) and isinstance(dups_removed, int):
                if total_sel == n_selected and total_cand >= total_sel and dups_removed >= 0:
                    scores["inspection_totals_consistent"] = 1.0

    # README checks
    readme_path = workspace / "outputs" / "README.md"
    readme_text = safe_read_text(readme_path) or ""
    if readme_text and rows:
        # Must mention queries and criteria and include rationale and list each selected source title
        contains_queries_word = "query" in readme_text.lower() or "queries" in readme_text.lower()
        contains_criteria = "criteria" in readme_text.lower()
        contains_rationale = "rationale" in readme_text.lower()
        titles_ok = all(((r.get("title") or "").strip().lower() in readme_text.lower()) for r in rows if (r.get("title") or "").strip())
        if contains_queries_word and contains_criteria and contains_rationale and titles_ok:
            scores["readme_includes_queries_criteria_rationales"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()