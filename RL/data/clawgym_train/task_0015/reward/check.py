import json
import sys
import re
import subprocess
from pathlib import Path
import csv
from typing import List, Dict, Any, Optional, Tuple


REQUIRED_SECTIONS = [
    "Overview",
    "Key Themes",
    "Primary Source Excerpts",
    "Discussion Questions",
    "Further Reading",
]

FLAGGED_TERMS = ["corrupt", "evil", "traitor", "un-american"]


def read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        content = read_text(path)
        if content is None:
            return None
        return json.loads(content)
    except Exception:
        return None


def load_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        text = read_text(path)
        if text is None:
            return None
        items = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
        return items
    except Exception:
        return None


def load_notes_csv(path: Path) -> Optional[Dict[str, Dict[str, str]]]:
    try:
        m = {}
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "id" in row and row["id"]:
                    m[row["id"]] = {"theme": row.get("theme", ""), "point": row.get("point", "")}
        return m
    except Exception:
        return None


def section_indices(lines: List[str]) -> Dict[str, int]:
    idx = {}
    for i, line in enumerate(lines):
        if line.strip().startswith("## "):
            name = line.strip()[3:].strip()
            idx[name] = i
    return idx


def extract_section(lines: List[str], heading: str) -> List[str]:
    idx_map = section_indices(lines)
    if heading not in idx_map:
        return []
    start = idx_map[heading] + 1
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break
    return lines[start:end]


def count_blockquotes(section_lines: List[str]) -> int:
    return sum(1 for ln in section_lines if ln.lstrip().startswith(">"))


def count_bullets(section_lines: List[str]) -> int:
    return sum(1 for ln in section_lines if ln.lstrip().startswith("- "))


def find_flagged_terms(text: str) -> List[str]:
    found = []
    lower = text.lower()
    for term in FLAGGED_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        if re.search(pattern, lower):
            found.append(term)
    return sorted(set(found))


def run_linter(workspace: Path, target_md: Path) -> Optional[Tuple[bool, str, int]]:
    script = workspace / "input" / "checks" / "handout_lint.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(target_md)],
            capture_output=True,
            text=True,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        errors = sum(1 for ln in out.splitlines() if ln.startswith("ERROR:"))
        ok = ("OK: No issues found." in out) and (errors == 0) and (proc.returncode == 0)
        return ok, out, errors
    except Exception:
        return None


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def normalize_excerpt(s: str) -> str:
    s = (s or "").replace("…", "...")
    s = s.replace("...", "")
    s = normalize_spaces(s).lower()
    return s


def paragraphs_count(text: str) -> int:
    if not text:
        return 0
    paras = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return len(paras)


def handout_headings_in_order(lines: List[str]) -> bool:
    idx_map = section_indices(lines)
    last_idx = -1
    for sec in REQUIRED_SECTIONS:
        if sec not in idx_map:
            return False
        if idx_map[sec] <= last_idx:
            return False
        last_idx = idx_map[sec]
    return True


def extract_outline_schema_valid(outline: Dict[str, Any]) -> bool:
    if not isinstance(outline, dict):
        return False
    keys = ["title", "overview", "key_themes", "primary_excerpts", "discussion_questions", "further_reading"]
    for k in keys:
        if k not in outline:
            return False
    if not isinstance(outline["title"], str) or not outline["title"].strip():
        return False
    if not isinstance(outline["overview"], str) or not outline["overview"].strip():
        return False
    if not isinstance(outline["key_themes"], list):
        return False
    if not isinstance(outline["primary_excerpts"], list):
        return False
    if not isinstance(outline["discussion_questions"], list):
        return False
    if not isinstance(outline["further_reading"], list):
        return False
    for kt in outline["key_themes"]:
        if not isinstance(kt, dict):
            return False
        for req in ["id", "theme", "point"]:
            if req not in kt or not isinstance(kt[req], str) or not kt[req].strip():
                return False
    for pe in outline["primary_excerpts"]:
        if not isinstance(pe, dict):
            return False
        if "id" not in pe or "source" not in pe or "year" not in pe or "excerpt" not in pe:
            return False
        if not isinstance(pe["id"], str) or not pe["id"].strip():
            return False
        if not isinstance(pe["source"], str) or not pe["source"].strip():
            return False
        if not isinstance(pe["year"], int):
            return False
        if not isinstance(pe["excerpt"], str) or not pe["excerpt"].strip():
            return False
    for q in outline["discussion_questions"]:
        if not isinstance(q, str) or not q.strip():
            return False
    for fr in outline["further_reading"]:
        if not isinstance(fr, str) or not fr.strip():
            return False
    return True


def match_outline_themes_to_notes(outline: Dict[str, Any], notes_map: Dict[str, Dict[str, str]]) -> bool:
    for kt in outline.get("key_themes", []):
        id_ = kt.get("id", "")
        if id_ not in notes_map:
            return False
        if normalize_spaces(kt.get("theme", "")) != normalize_spaces(notes_map[id_].get("theme", "")):
            return False
        if normalize_spaces(kt.get("point", "")) != normalize_spaces(notes_map[id_].get("point", "")):
            return False
    return True


def match_outline_excerpts_to_sources(outline: Dict[str, Any], sources: List[Dict[str, Any]]) -> bool:
    src_by_id = {s.get("id"): s for s in sources}
    for pe in outline.get("primary_excerpts", []):
        id_ = pe.get("id", "")
        src = src_by_id.get(id_)
        if not src:
            return False
        if normalize_spaces(pe.get("source", "")) != normalize_spaces(src.get("source", "")):
            return False
        if pe.get("year", None) != src.get("year", None):
            return False
        outline_excerpt_norm = normalize_excerpt(pe.get("excerpt", ""))
        source_text_norm = normalize_excerpt(src.get("text", ""))
        if not outline_excerpt_norm:
            return False
        if outline_excerpt_norm not in source_text_norm:
            return False
    return True


def handout_contains_outline_themes(handout_text: str, outline: Dict[str, Any]) -> bool:
    lines = handout_text.splitlines()
    sec_lines = extract_section(lines, "Key Themes")
    sec_text = "\n".join(sec_lines).lower()
    for kt in outline.get("key_themes", []):
        point_txt = (kt.get("point") or "").strip().lower()
        if not point_txt:
            return False
        if point_txt not in sec_text:
            return False
    return True


def handout_contains_outline_excerpts(handout_text: str, outline: Dict[str, Any]) -> bool:
    lines = handout_text.splitlines()
    sec_lines = extract_section(lines, "Primary Source Excerpts")
    blockquotes = [ln.lstrip()[1:].strip() if ln.lstrip().startswith(">") else "" for ln in sec_lines]
    block_text = "\n".join(blockquotes).lower()
    for pe in outline.get("primary_excerpts", []):
        exc = (pe.get("excerpt") or "").strip().lower()
        exc_norm = normalize_excerpt(exc)
        if not exc_norm or exc_norm not in normalize_excerpt(block_text):
            return False
    return True


def handout_contains_outline_questions(handout_text: str, outline: Dict[str, Any]) -> bool:
    lines = handout_text.splitlines()
    sec_lines = extract_section(lines, "Discussion Questions")
    bullets = [ln.strip()[2:] for ln in sec_lines if ln.lstrip().startswith("- ")]
    bullets_norm = [normalize_spaces(b).lower() for b in bullets]
    for q in outline.get("discussion_questions", []):
        qn = normalize_spaces(q).lower()
        if qn not in bullets_norm:
            return False
    return True


def handout_contains_outline_further_reading(handout_text: str, outline: Dict[str, Any]) -> bool:
    lines = handout_text.splitlines()
    sec_lines = extract_section(lines, "Further Reading")
    bullets = [ln.strip()[2:] for ln in sec_lines if ln.lstrip().startswith("- ")]
    bullets_norm = [normalize_spaces(b).lower() for b in bullets]
    for item in outline.get("further_reading", []):
        itn = normalize_spaces(item).lower()
        if itn not in bullets_norm:
            return False
    return True


def count_errors_in_lint_output(text: str) -> int:
    return sum(1 for ln in (text or "").splitlines() if ln.startswith("ERROR:"))


def parse_logistics(original: str) -> Dict[str, List[Tuple[str, str]]]:
    day_time_pairs = []
    for m in re.finditer(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b[^,\n]*?\bat\s+(\d{1,2}:\d{2}\s*[AP]M)\b", original, re.IGNORECASE):
        day = m.group(1)
        time = m.group(2)
        day_time_pairs.append((day, time))
    for m in re.finditer(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b[^,\n]*?\bby\s+(\d{1,2}:\d{2}\s*[AP]M)\b", original, re.IGNORECASE):
        day = m.group(1)
        time = m.group(2)
        day_time_pairs.append((day, time))
    date_time_pairs = []
    for m in re.finditer(r"\b(\d{2}/\d{2})\b[^,\n]*?\bat\s+(\d{1,2}:\d{2}\s*[AP]M)\b", original, re.IGNORECASE):
        date = m.group(1)
        time = m.group(2)
        date_time_pairs.append((date, time))
    return {"day_time": day_time_pairs, "date_time": date_time_pairs}


def logistics_present(text: str, logistics: Dict[str, List[Tuple[str, str]]]) -> bool:
    if text is None:
        return False
    t = text
    for day, time in logistics.get("day_time", []):
        if (day not in t) or (time not in t):
            return False
    for date, time in logistics.get("date_time", []):
        if (date not in t) or (time not in t):
            return False
    if re.search(r"\bopen house\b", t, re.IGNORECASE) is None:
        return False
    return True


def word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outline_json_exists_and_schema": 0.0,
        "outline_overview_paragraphs_1_to_2": 0.0,
        "outline_key_themes_count": 0.0,
        "outline_key_themes_match_notes": 0.0,
        "outline_primary_excerpts_count": 0.0,
        "outline_primary_excerpts_match_sources": 0.0,
        "outline_discussion_questions_count": 0.0,
        "outline_further_reading_count": 0.0,
        "handout_sections_required_order": 0.0,
        "handout_blockquotes_min_two": 0.0,
        "handout_discussion_bullets_min_three": 0.0,
        "handout_further_reading_bullets_min_one": 0.0,
        "handout_no_flagged_terms": 0.0,
        "handout_aligns_with_outline_themes": 0.0,
        "handout_aligns_with_outline_excerpts": 0.0,
        "handout_aligns_with_outline_questions": 0.0,
        "handout_aligns_with_outline_further_reading": 0.0,
        "linter_baseline_log_matches": 0.0,
        "linter_final_log_matches": 0.0,
        "linter_final_passed": 0.0,
        "lint_summary_consistent": 0.0,
        "email_neutral_preserves_logistics": 0.0,
        "email_neutral_appropriate_language": 0.0,
        "email_brief_under_120_words": 0.0,
        "email_brief_preserves_logistics": 0.0,
    }

    outline_path = workspace / "build" / "outline.json"
    handout_path = workspace / "build" / "handout.md"
    before_log_path = workspace / "build" / "logs" / "lint_before.txt"
    after_log_path = workspace / "build" / "logs" / "lint_after.txt"
    lint_summary_path = workspace / "build" / "lint_summary.json"
    notes_csv_path = workspace / "input" / "notes" / "antebellum_whig_dem_notes.csv"
    excerpts_jsonl_path = workspace / "input" / "primary" / "excerpts.jsonl"
    template_md_path = workspace / "input" / "draft" / "handout_template.md"
    email_src_path = workspace / "input" / "draft" / "email_to_parents.txt"
    email_neutral_path = workspace / "build" / "email_neutral.txt"
    email_brief_path = workspace / "build" / "email_brief.txt"

    outline = load_json(outline_path)
    if outline and extract_outline_schema_valid(outline):
        scores["outline_json_exists_and_schema"] = 1.0
        num_paras = paragraphs_count(outline.get("overview", ""))
        if 1 <= num_paras <= 2:
            scores["outline_overview_paragraphs_1_to_2"] = 1.0
        if isinstance(outline.get("key_themes"), list) and len(outline["key_themes"]) >= 4:
            scores["outline_key_themes_count"] = 1.0
        if isinstance(outline.get("primary_excerpts"), list) and len(outline["primary_excerpts"]) >= 2:
            scores["outline_primary_excerpts_count"] = 1.0
        if isinstance(outline.get("discussion_questions"), list) and len(outline["discussion_questions"]) >= 3:
            scores["outline_discussion_questions_count"] = 1.0
        if isinstance(outline.get("further_reading"), list) and len(outline["further_reading"]) >= 1:
            scores["outline_further_reading_count"] = 1.0

        notes_map = load_notes_csv(notes_csv_path) or {}
        if notes_map and match_outline_themes_to_notes(outline, notes_map):
            scores["outline_key_themes_match_notes"] = 1.0

        sources = load_jsonl(excerpts_jsonl_path)
        if sources is not None and len(sources) > 0 and match_outline_excerpts_to_sources(outline, sources):
            scores["outline_primary_excerpts_match_sources"] = 1.0

    handout_text = read_text(handout_path)
    if handout_text is not None:
        lines = handout_text.splitlines()
        if handout_headings_in_order(lines):
            scores["handout_sections_required_order"] = 1.0
        pse_lines = extract_section(lines, "Primary Source Excerpts")
        dq_lines = extract_section(lines, "Discussion Questions")
        fr_lines = extract_section(lines, "Further Reading")
        if count_blockquotes(pse_lines) >= 2:
            scores["handout_blockquotes_min_two"] = 1.0
        if count_bullets(dq_lines) >= 3:
            scores["handout_discussion_bullets_min_three"] = 1.0
        if count_bullets(fr_lines) >= 1:
            scores["handout_further_reading_bullets_min_one"] = 1.0
        if not find_flagged_terms(handout_text):
            scores["handout_no_flagged_terms"] = 1.0
        if outline and extract_outline_schema_valid(outline):
            try:
                if handout_contains_outline_themes(handout_text, outline):
                    scores["handout_aligns_with_outline_themes"] = 1.0
                if handout_contains_outline_excerpts(handout_text, outline):
                    scores["handout_aligns_with_outline_excerpts"] = 1.0
                if handout_contains_outline_questions(handout_text, outline):
                    scores["handout_aligns_with_outline_questions"] = 1.0
                if handout_contains_outline_further_reading(handout_text, outline):
                    scores["handout_aligns_with_outline_further_reading"] = 1.0
            except Exception:
                pass

    baseline_run = None
    if template_md_path.is_file():
        baseline_run = run_linter(workspace, template_md_path)
    before_log_text = read_text(before_log_path) if before_log_path.is_file() else None
    if baseline_run is not None and before_log_text is not None:
        _, baseline_output, _ = baseline_run
        if baseline_output == before_log_text:
            scores["linter_baseline_log_matches"] = 1.0

    final_run = None
    if handout_path.is_file():
        final_run = run_linter(workspace, handout_path)
    after_log_text = read_text(after_log_path) if after_log_path.is_file() else None
    if final_run is not None and after_log_text is not None:
        ok_flag, final_output, _ = final_run
        if final_output == after_log_text:
            scores["linter_final_log_matches"] = 1.0
        if ok_flag:
            scores["linter_final_passed"] = 1.0

    lint_summary = load_json(lint_summary_path) if lint_summary_path.is_file() else None
    if lint_summary is not None and isinstance(lint_summary, dict):
        eb = lint_summary.get("errors_before", None)
        ea = lint_summary.get("errors_after", None)
        passed = lint_summary.get("passed", None)
        if isinstance(eb, int) and isinstance(ea, int) and isinstance(passed, bool):
            before_errs = count_errors_in_lint_output(before_log_text or "")
            after_errs = count_errors_in_lint_output(after_log_text or "")
            final_ok = ("OK: No issues found." in (after_log_text or "")) and (after_errs == 0)
            if eb == before_errs and ea == after_errs and passed == final_ok:
                scores["lint_summary_consistent"] = 1.0

    original_email = read_text(email_src_path) or ""
    logistics = parse_logistics(original_email)

    neutral_email = read_text(email_neutral_path)
    if neutral_email is not None and logistics_present(neutral_email, logistics):
        scores["email_neutral_preserves_logistics"] = 1.0
    if neutral_email is not None and not find_flagged_terms(neutral_email):
        scores["email_neutral_appropriate_language"] = 1.0

    brief_email = read_text(email_brief_path)
    if brief_email is not None and word_count(brief_email) <= 120:
        scores["email_brief_under_120_words"] = 1.0
    if brief_email is not None and logistics_present(brief_email, logistics):
        scores["email_brief_preserves_logistics"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()