import json
import csv
import sys
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    records = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                records.append(obj)
        return records
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if row is None or not isinstance(row, dict):
                    return None
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _parse_category_mapping(rows: List[Dict[str, str]]) -> Dict[str, str]:
    mapping = {}
    for r in rows:
        kw = (r.get("keyword") or "").strip().lower()
        sc = (r.get("standard_category") or "").strip()
        if kw:
            mapping[kw] = sc
    return mapping


def _normalize_tags(tags: Any) -> List[str]:
    if not isinstance(tags, list):
        return []
    normalized = []
    seen = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        lt = t.strip().lower()
        if lt and lt not in seen:
            seen.add(lt)
            normalized.append(lt)
    return normalized


def _map_original_category(orig: str, mapping: Dict[str, str]) -> Optional[str]:
    if not isinstance(orig, str):
        return None
    key = orig.strip().lower()
    if not key:
        return None
    return mapping.get(key)


def _compute_standardized_category(tags: List[str], orig_category: str, mapping: Dict[str, str]) -> str:
    counts: Counter = Counter()
    for tag in tags:
        mapped = mapping.get(tag.strip().lower())
        if mapped:
            counts[mapped] += 1
    if not counts:
        tie_break = _map_original_category(orig_category or "", mapping)
        return tie_break if tie_break else "Uncategorized"
    max_count = max(counts.values())
    leaders = sorted([cat for cat, c in counts.items() if c == max_count])
    if len(leaders) == 1:
        return leaders[0]
    tie_break = _map_original_category(orig_category or "", mapping)
    if tie_break and tie_break in leaders:
        return tie_break
    return "Uncategorized"


def _compute_quality_flags(record: Dict[str, Any]) -> List[str]:
    flags = []
    date = record.get("date", "")
    location = record.get("location", "")
    category = record.get("category", "")
    if not isinstance(date, str) or date.strip() == "":
        flags.append("missing_date")
    if not isinstance(location, str) or location.strip() == "":
        flags.append("missing_location")
    if not isinstance(category, str) or category.strip() == "":
        flags.append("missing_category")
    return flags


def _compute_expected_enriched(records: List[Dict[str, Any]], mapping: Dict[str, str]) -> List[Dict[str, Any]]:
    enriched = []
    for rec in records:
        norm_tags = _normalize_tags(rec.get("tags", []))
        std_cat = _compute_standardized_category(norm_tags, rec.get("category", ""), mapping)
        qf = _compute_quality_flags(rec)
        new_obj = dict(rec)
        new_obj["tags"] = norm_tags
        new_obj["standardized_category"] = std_cat
        new_obj["quality_flags"] = qf
        enriched.append(new_obj)
    return enriched


def _category_counts_from_enriched(enriched: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    for rec in enriched:
        sc = rec.get("standardized_category")
        if isinstance(sc, str) and sc != "":
            counts[sc] += 1
    return dict(counts)


def _parse_guidelines_sections(text: str) -> Dict[str, str]:
    lines = text.splitlines()
    sections: Dict[str, str] = {}
    cur_name = "__preamble__"
    buf: List[str] = []
    title_set = False
    for i, line in enumerate(lines):
        if not title_set and line.strip().startswith("# "):
            sections["__title__"] = line.strip()
            title_set = True
            continue
        if line.strip().startswith("## "):
            if cur_name is not None:
                sections[cur_name] = "\n".join(buf).strip()
            cur_name = line.strip()[3:].strip()
            buf = []
        else:
            buf.append(line)
    if cur_name is not None:
        sections[cur_name] = "\n".join(buf).strip()
    return sections


def _extract_categories_from_section(section_text: str) -> List[str]:
    cats = []
    for line in section_text.splitlines():
        s = line.strip()
        if s.startswith("- "):
            cats.append(s[2:].strip())
    return cats


def _get_section_content(sections: Dict[str, str], name: str) -> Optional[str]:
    for key, val in sections.items():
        if key.lower() == name.lower():
            return val
    return None


def _parse_email_context(text: str) -> Tuple[Optional[str], List[str]]:
    recipient = None
    lines = text.splitlines()
    bullets: List[str] = []
    in_questions = False
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("to:"):
            recipient = line.split(":", 1)[1].strip()
        if line.strip().lower().startswith("questions"):
            in_questions = True
            continue
        if in_questions:
            if line.strip().startswith("- "):
                bullets.append(line.strip())
            else:
                if line.strip() == "":
                    continue
    return recipient, bullets


def _line_has_category_and_count(line: str, category: str, count: int) -> bool:
    if category not in line:
        return False
    numbers = re.findall(r"\b\d+\b", line)
    return str(count) in numbers


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "enriched_records_structure_and_fields": 0.0,
        "standardized_category_correctness": 0.0,
        "quality_flags_correctness": 0.0,
        "tags_normalization_enforced": 0.0,
        "category_summary_correctness": 0.0,
        "quality_issues_csv_correctness": 0.0,
        "guidelines_title_version_updated": 0.0,
        "guidelines_categories_section_updated": 0.0,
        "guidelines_field_naming_updated": 0.0,
        "guidelines_categorization_rules_section": 0.0,
        "guidelines_change_log_updated": 0.0,
        "email_recipient_and_subject_present": 0.0,
        "email_category_counts_correct": 0.0,
        "email_quality_counts_and_ids_correct": 0.0,
        "email_questions_quoted_verbatim": 0.0,
        "status_report_sections_present": 0.0,
        "status_report_category_distribution_correct": 0.0,
        "status_report_quality_summary_correct": 0.0,
        "status_report_guideline_updates_mentions": 0.0,
    }

    # Load inputs
    records_path = workspace / "input" / "records.jsonl"
    mapping_path = workspace / "input" / "category_mapping.csv"
    guidelines_path = workspace / "docs" / "cataloging_guidelines.md"
    email_context_path = workspace / "docs" / "email_context.md"

    records = _safe_load_jsonl(records_path)
    mapping_rows = _safe_load_csv_dicts(mapping_path)
    mapping: Dict[str, str] = {}
    expected_enriched: Optional[List[Dict[str, Any]]] = None

    if records is not None and mapping_rows is not None:
        mapping = _parse_category_mapping(mapping_rows)
        expected_enriched = _compute_expected_enriched(records, mapping)

    # Check enriched_records.jsonl
    enriched_path = workspace / "out" / "enriched_records.jsonl"
    enriched = _safe_load_jsonl(enriched_path)
    if enriched is not None and expected_enriched is not None:
        try:
            original_keys = set(["id", "title", "description", "date", "location", "tags", "category"])
            has_all = True
            if len(enriched) != len(expected_enriched):
                has_all = False
            exp_by_id = {r["id"]: r for r in expected_enriched if "id" in r}
            stdcat_ok = True
            flags_ok = True
            tags_norm_ok = True
            fields_ok = True
            for rec in enriched:
                rid = rec.get("id")
                if not (set(rec.keys()) >= (original_keys | {"standardized_category", "quality_flags"})):
                    fields_ok = False
                tags = rec.get("tags")
                if not isinstance(tags, list):
                    tags_norm_ok = False
                else:
                    lowers = [t for t in tags if isinstance(t, str) and t == t.lower()]
                    unique = len(lowers) == len(set(lowers))
                    tags_norm_ok = tags_norm_ok and (len(lowers) == len(tags)) and unique
                if rid not in exp_by_id:
                    stdcat_ok = False
                    flags_ok = False
                    continue
                exp = exp_by_id[rid]
                if rec.get("standardized_category") != exp.get("standardized_category"):
                    stdcat_ok = False
                got_flags = rec.get("quality_flags")
                if not isinstance(got_flags, list):
                    flags_ok = False
                else:
                    if set(got_flags) != set(exp.get("quality_flags", [])):
                        flags_ok = False
            if fields_ok and has_all:
                scores["enriched_records_structure_and_fields"] = 1.0
            if stdcat_ok and has_all:
                scores["standardized_category_correctness"] = 1.0
            if flags_ok and has_all:
                scores["quality_flags_correctness"] = 1.0
            if tags_norm_ok and has_all:
                scores["tags_normalization_enforced"] = 1.0
        except Exception:
            pass

    # Category summary CSV
    summary_path = workspace / "out" / "category_summary.csv"
    summary_rows = _safe_load_csv_dicts(summary_path)
    if summary_rows is not None and expected_enriched is not None:
        try:
            provided_counts: Dict[str, int] = {}
            headers = set(summary_rows[0].keys()) if summary_rows else set()
            if "standard_category" in headers and "count" in headers:
                ok_rows = True
                for r in summary_rows:
                    cat = (r.get("standard_category") or "").strip()
                    cnt_str = (r.get("count") or "").strip()
                    if cat == "" or cnt_str == "":
                        ok_rows = False
                        break
                    try:
                        cnt = int(cnt_str)
                    except Exception:
                        ok_rows = False
                        break
                    provided_counts[cat] = cnt
                if ok_rows:
                    expected_counts = _category_counts_from_enriched(expected_enriched)
                    if "Uncategorized" not in expected_counts and "Uncategorized" in provided_counts:
                        ok_rows = False
                    if ok_rows and provided_counts == expected_counts:
                        scores["category_summary_correctness"] = 1.0
        except Exception:
            pass

    # Quality issues CSV
    quality_issues_path = workspace / "out" / "quality_issues.csv"
    issues_rows = _safe_load_csv_dicts(quality_issues_path)
    if issues_rows is not None and expected_enriched is not None:
        try:
            headers = set(issues_rows[0].keys()) if issues_rows else set()
            if "id" in headers and "issues" in headers and len(issues_rows) == len(expected_enriched):
                exp_flags_by_id = {r["id"]: set(r.get("quality_flags", [])) for r in expected_enriched}
                ok = True
                for r in issues_rows:
                    rid = (r.get("id") or "").strip()
                    issues_cell = (r.get("issues") or "")
                    if rid == "":
                        ok = False
                        break
                    parts = [p.strip() for p in issues_cell.split(";")] if issues_cell != "" else []
                    parts = [p for p in parts if p != ""]
                    if rid not in exp_flags_by_id:
                        ok = False
                        break
                    if set(parts) != exp_flags_by_id[rid]:
                        ok = False
                        break
                if ok:
                    scores["quality_issues_csv_correctness"] = 1.0
        except Exception:
            pass

    # Guidelines checks
    guidelines_text = _safe_read_text(guidelines_path)
    if guidelines_text is not None:
        try:
            sections = _parse_guidelines_sections(guidelines_text)
            title_line = sections.get("__title__") or ""
            if "v1.1" in title_line and not title_line.strip().endswith("v1.0"):
                scores["guidelines_title_version_updated"] = 1.0
            cats_section = _get_section_content(sections, "Categories")
            if cats_section is not None and expected_enriched is not None:
                listed = set(_extract_categories_from_section(cats_section))
                expected_counts = _category_counts_from_enriched(expected_enriched)
                expected_listed = set(expected_counts.keys())
                if listed == expected_listed:
                    scores["guidelines_categories_section_updated"] = 1.0
            field_section = _get_section_content(sections, "Field Naming")
            if field_section is not None:
                cond_date = ("- date:" in field_section) and ("record_date" not in field_section)
                cond_location = ("- location:" in field_section) and ("place_name" not in field_section)
                if cond_date and cond_location:
                    scores["guidelines_field_naming_updated"] = 1.0
            rules_section = _get_section_content(sections, "Categorization Rules")
            if rules_section is not None:
                lower = rules_section.lower()
                has_majority = ("majority" in lower and "tag" in lower)
                has_tie = ("tie" in lower and "original" in lower and "category" in lower)
                has_uncat = "uncategorized" in lower
                has_example_id = "rec-" in lower
                if has_majority and has_tie and has_uncat and has_example_id:
                    scores["guidelines_categorization_rules_section"] = 1.0
            change_log_section = _get_section_content(sections, "Change Log")
            if change_log_section is not None:
                if "v1.1" in change_log_section:
                    scores["guidelines_change_log_updated"] = 1.0
        except Exception:
            pass

    # Email checks
    email_path = workspace / "out" / "email_to_archivist.txt"
    email_text = _safe_read_text(email_path)
    email_context_path = workspace / "docs" / "email_context.md"
    email_context_text = _safe_read_text(email_context_path)
    if email_text is not None and email_context_text is not None:
        try:
            recipient, bullets = _parse_email_context(email_context_text)
            has_recipient = recipient is not None and (("To:" in email_text and recipient in email_text) or (recipient in email_text))
            has_subject = any(l.strip().lower().startswith("subject") for l in email_text.splitlines())
            if has_recipient and has_subject:
                scores["email_recipient_and_subject_present"] = 1.0
            if expected_enriched is not None:
                expected_counts = _category_counts_from_enriched(expected_enriched)
                cat_ok = True
                lines = email_text.splitlines()
                for cat, cnt in expected_counts.items():
                    found = any(_line_has_category_and_count(ln, cat, cnt) for ln in lines)
                    if not found:
                        cat_ok = False
                        break
                if cat_ok:
                    scores["email_category_counts_correct"] = 1.0
            if expected_enriched is not None:
                miss_date_ids = sorted([r["id"] for r in expected_enriched if "missing_date" in r.get("quality_flags", [])])
                miss_loc_ids = sorted([r["id"] for r in expected_enriched if "missing_location" in r.get("quality_flags", [])])
                md_count = len(miss_date_ids)
                ml_count = len(miss_loc_ids)
                lines = email_text.splitlines()
                md_line_ok = any(("missing_date" in ln.lower() and str(md_count) in re.findall(r"\b\d+\b", ln)) for ln in lines)
                ml_line_ok = any(("missing_location" in ln.lower() and str(ml_count) in re.findall(r"\b\d+\b", ln)) for ln in lines)
                ids_ok = all(rid in email_text for rid in miss_date_ids) and all(rid in email_text for rid in miss_loc_ids)
                if md_line_ok and ml_line_ok and ids_ok:
                    scores["email_quality_counts_and_ids_correct"] = 1.0
            if bullets:
                quoted_ok = True
                for b in bullets:
                    if b not in email_text:
                        quoted_ok = False
                        break
                has_questions_heading = any("questions" in l.strip().lower() for l in email_text.splitlines())
                if quoted_ok and has_questions_heading:
                    scores["email_questions_quoted_verbatim"] = 1.0
        except Exception:
            pass

    # Status report checks
    status_path = workspace / "out" / "status_report.md"
    status_text = _safe_read_text(status_path)
    if status_text is not None:
        try:
            lines = status_text.splitlines()
            headings = [l.strip() for l in lines if l.strip().startswith("#")]
            headings_lower = set([re.sub(r"^#+\s*", "", h).strip().lower() for h in headings])
            required_sections = ["overview", "data quality summary", "category distribution", "guideline updates", "next steps"]
            has_sections = all(any(sec == h for h in headings_lower) for sec in required_sections)
            if has_sections:
                scores["status_report_sections_present"] = 1.0
            if expected_enriched is not None:
                expected_counts = _category_counts_from_enriched(expected_enriched)
                cat_ok = True
                for cat, cnt in expected_counts.items():
                    found = any(_line_has_category_and_count(ln, cat, cnt) for ln in lines)
                    if not found:
                        cat_ok = False
                        break
                if cat_ok:
                    scores["status_report_category_distribution_correct"] = 1.0
            if expected_enriched is not None:
                miss_date_ids = [r["id"] for r in expected_enriched if "missing_date" in r.get("quality_flags", [])]
                miss_loc_ids = [r["id"] for r in expected_enriched if "missing_location" in r.get("quality_flags", [])]
                md_count = len(miss_date_ids)
                ml_count = len(miss_loc_ids)
                md_ok = any(("missing_date" in ln.lower() and str(md_count) in re.findall(r"\b\d+\b", ln)) for ln in lines)
                ml_ok = any(("missing_location" in ln.lower() and str(ml_count) in re.findall(r"\b\d+\b", ln)) for ln in lines)
                if md_ok and ml_ok:
                    scores["status_report_quality_summary_correct"] = 1.0
            section_contents: Dict[str, str] = {}
            current = None
            buf: List[str] = []
            for l in lines:
                if l.strip().startswith("#"):
                    if current is not None:
                        section_contents[current] = "\n".join(buf)
                    current = re.sub(r"^#+\s*", "", l.strip()).strip().lower()
                    buf = []
                else:
                    buf.append(l)
            if current is not None:
                section_contents[current] = "\n".join(buf)
            gu = section_contents.get("guideline updates", "")
            if gu:
                lower = gu.lower()
                mentions = ("v1.1" in gu) and (("categor" in lower) or ("field naming" in lower) or ("categories" in lower))
                if mentions:
                    scores["status_report_guideline_updates_mentions"] = 1.0
        except Exception:
            pass

    for k, v in list(scores.items()):
        try:
            val = float(v)
        except Exception:
            scores[k] = 0.0
        else:
            if val < 0.0:
                scores[k] = 0.0
            elif val > 1.0:
                scores[k] = 1.0
            else:
                scores[k] = val

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and isinstance(sys.argv[1], str):
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()