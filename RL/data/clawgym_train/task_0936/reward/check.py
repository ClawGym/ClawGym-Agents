import json
import csv
import sys
import subprocess
import re
from pathlib import Path
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_jsonl(path: Path):
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    items.append(None)
                    continue
                try:
                    obj = json.loads(line)
                    items.append(obj)
                except Exception:
                    items.append(None)
        return items
    except Exception:
        return None


def _run_validator(workspace: Path) -> str:
    script = workspace / "tools" / "quote_validator.py"
    quotes = workspace / "data" / "quotes.jsonl"
    if not script.exists() or not quotes.exists():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(quotes)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        return proc.stdout
    except Exception:
        return None


def _parse_validator_output(text: str):
    valid = {}
    errors = []
    valid_lines = 0
    error_lines = 0
    if text is None:
        return {"valid": valid, "errors": errors, "valid_count": 0, "error_count": 0}
    for line in text.splitlines():
        if line.startswith("VALID:"):
            valid_lines += 1
            m = re.match(r'^VALID:\s+line\s+\d+\s+-\s+([A-Za-z0-9_\-]+)\s+\((Setback|Comeback)\s+(\d{4})\)\s*$', line)
            if m:
                qid = m.group(1)
                category = m.group(2)
                year = int(m.group(3))
                valid[qid] = {"category": category, "year": year}
        elif line.startswith("ERROR:"):
            error_lines += 1
            qid_match = re.search(r'\(quote_id=([A-Za-z0-9_\-?]+)\)', line)
            qid = qid_match.group(1) if qid_match else None
            errors.append({"line": line, "quote_id": qid})
    return {"valid": valid, "errors": errors, "valid_count": valid_lines, "error_count": error_lines}


class _MilestonesHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = ""
        self.current_row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attrs_dict = dict(attrs)
            if attrs_dict.get("id") == "milestones":
                self.in_table = True
        elif tag == "tbody" and self.in_table:
            self.in_tbody = True
        elif tag == "tr" and self.in_table and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
            self.in_tbody = False
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if len(self.current_row) == 3:
                try:
                    year = int(self.current_row[0])
                    event = self.current_row[1]
                    status = self.current_row[2]
                    self.rows.append({"year": year, "event": event, "status": status})
                except Exception:
                    pass
            self.current_row = []
        elif tag == "td" and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
            self.current_cell = ""

    def handle_data(self, data):
        if self.in_td:
            self.current_cell += data


def _extract_milestones_from_html(html_text: str):
    if html_text is None:
        return None
    parser = _MilestonesHTMLParser()
    try:
        parser.feed(html_text)
        return parser.rows
    except Exception:
        return None


def _safe_read_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _count_sentences(text: str) -> int:
    if not isinstance(text, str):
        return 0
    parts = [p for p in re.split(r'[.!?]+', text) if p.strip()]
    return len(parts)


def _contains_avoid_words(text: str, avoid_words: list) -> bool:
    if not isinstance(text, str):
        return True
    for w in avoid_words or []:
        if re.search(r'\b' + re.escape(w) + r'\b', text, flags=re.IGNORECASE):
            return True
    return False


def _has_base_hashtag(hashtags: str, base_tags: list) -> bool:
    if not isinstance(hashtags, str):
        return False
    tokens = hashtags.strip().split()
    base_set = set(base_tags or [])
    return any(tok in base_set for tok in tokens)


def _find_counts_in_report(report_text: str):
    if report_text is None:
        return None, None
    v_match = re.search(r'valid[^0-9]*([0-9]+)', report_text, flags=re.IGNORECASE)
    e_match = re.search(r'error[^0-9]*([0-9]+)', report_text, flags=re.IGNORECASE)
    v = int(v_match.group(1)) if v_match else None
    e = int(e_match.group(1)) if e_match else None
    return v, e


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "validator_output_saved_exact": 0.0,
        "milestones_json_correct": 0.0,
        "posts_csv_header_and_count": 0.0,
        "posts_use_valid_quotes_and_match_milestones": 0.0,
        "posts_hook_and_reflection_tone": 0.0,
        "posts_hashtags_base_included": 0.0,
        "validation_report_counts_correct": 0.0,
        "validation_report_lists_discarded_with_reasons": 0.0,
        "validation_report_notes_unused_valid": 0.0,
    }

    validator_output_path = workspace / "output" / "validator_output.txt"
    milestones_json_path = workspace / "output" / "milestones.json"
    posts_csv_path = workspace / "output" / "posts.csv"
    report_md_path = workspace / "output" / "validation_report.md"

    expected_stdout = _run_validator(workspace)
    actual_stdout = _safe_read_text(validator_output_path)

    if expected_stdout is not None and actual_stdout is not None:
        if expected_stdout == actual_stdout:
            scores["validator_output_saved_exact"] = 1.0

    parsed_validator = _parse_validator_output(actual_stdout if actual_stdout is not None else "")
    valid_quotes_from_output = parsed_validator["valid"]
    error_items_from_output = parsed_validator["errors"]
    valid_count_expected = parsed_validator["valid_count"]
    error_count_expected = parsed_validator["error_count"]

    html_text = _safe_read_text(workspace / "data" / "athlete_profile.html")
    expected_milestones = _extract_milestones_from_html(html_text)

    delivered_milestones = _safe_load_json(milestones_json_path)

    def _validate_milestone_list(lst):
        if not isinstance(lst, list):
            return False
        for item in lst:
            if not isinstance(item, dict):
                return False
            if set(item.keys()) != {"year", "event", "status"}:
                return False
            if not isinstance(item.get("year"), int):
                return False
            if not isinstance(item.get("event"), str):
                return False
            if item.get("status") not in {"Setback", "Comeback"}:
                return False
        return True

    if expected_milestones is not None and delivered_milestones is not None:
        if _validate_milestone_list(delivered_milestones):
            if delivered_milestones == expected_milestones:
                scores["milestones_json_correct"] = 1.0

    personal_context = _safe_load_json(workspace / "data" / "personal_context.json")
    avoid_words = []
    base_hashtags = []
    if isinstance(personal_context, dict):
        tg = personal_context.get("tone_guidelines") or {}
        avoid_words = tg.get("avoid_words") or []
        base_hashtags = tg.get("hashtags_base") or []

    valid_quote_texts = {}
    quotes_jsonl = _safe_load_jsonl(workspace / "data" / "quotes.jsonl")
    if quotes_jsonl is not None:
        for obj in quotes_jsonl:
            if isinstance(obj, dict):
                qid = obj.get("quote_id")
                if qid in valid_quotes_from_output:
                    valid_quote_texts[qid] = {
                        "text": obj.get("text"),
                        "year": obj.get("year"),
                        "category": obj.get("category"),
                    }

    fieldnames, rows = _safe_read_csv_dicts(posts_csv_path)

    expected_header = ["post_id", "quote_id", "year", "status", "quote_text", "hook", "reflection", "hashtags"]
    if fieldnames is not None and rows is not None:
        if fieldnames == expected_header and len(rows) == 3:
            scores["posts_csv_header_and_count"] = 1.0

    posts_valid = False
    hooks_reflections_ok = False
    hashtags_ok = False
    if fieldnames == expected_header and rows is not None and len(rows) == 3 and isinstance(delivered_milestones, list):
        milestone_set = set()
        for m in delivered_milestones or []:
            try:
                milestone_set.add((int(m.get("year")), m.get("status")))
            except Exception:
                pass
        all_posts_ok = True
        text_and_match_ok = True
        post_ids = set()
        hooks_ok = True
        reflections_ok = True
        avoid_ok = True
        hashtags_all_ok = True
        for row in rows:
            post_id = (row.get("post_id") or "").strip()
            quote_id = (row.get("quote_id") or "").strip()
            year_str = (row.get("year") or "").strip()
            status = (row.get("status") or "").strip()
            quote_text = row.get("quote_text") or ""
            hook = row.get("hook") or ""
            reflection = row.get("reflection") or ""
            hashtags = row.get("hashtags") or ""

            if not post_id or post_id in post_ids:
                all_posts_ok = False
            post_ids.add(post_id)

            try:
                year_int = int(year_str)
            except Exception:
                text_and_match_ok = False
                all_posts_ok = False
                continue

            if quote_id not in valid_quotes_from_output:
                text_and_match_ok = False
                all_posts_ok = False
            else:
                v = valid_quotes_from_output[quote_id]
                if v["year"] != year_int or v["category"] != status:
                    text_and_match_ok = False
                    all_posts_ok = False
                if (year_int, status) not in milestone_set:
                    text_and_match_ok = False
                    all_posts_ok = False
                src = valid_quote_texts.get(quote_id)
                if not src or src.get("text") != quote_text:
                    text_and_match_ok = False
                    all_posts_ok = False

            if not hook or re.search(r'\bself-?doubt\b', hook, flags=re.IGNORECASE) is None:
                hooks_ok = False

            sent_count = _count_sentences(reflection)
            if sent_count < 1 or sent_count > 2:
                reflections_ok = False
            if re.search(r'stuck', reflection, flags=re.IGNORECASE) is None and re.search(r'resilien', reflection, flags=re.IGNORECASE) is None:
                reflections_ok = False

            if _contains_avoid_words(hook, avoid_words) or _contains_avoid_words(reflection, avoid_words):
                avoid_ok = False

            if not _has_base_hashtag(hashtags, base_hashtags):
                hashtags_all_ok = False

        if all_posts_ok and text_and_match_ok:
            posts_valid = True
        if hooks_ok and reflections_ok and avoid_ok:
            hooks_reflections_ok = True
        if hashtags_all_ok:
            hashtags_ok = True

    scores["posts_use_valid_quotes_and_match_milestones"] = 1.0 if posts_valid else 0.0
    scores["posts_hook_and_reflection_tone"] = 1.0 if hooks_reflections_ok else 0.0
    scores["posts_hashtags_base_included"] = 1.0 if hashtags_ok else 0.0

    report_text = _safe_read_text(report_md_path)
    if report_text is not None:
        v_found, e_found = _find_counts_in_report(report_text)
        if v_found == valid_count_expected and e_found == error_count_expected:
            scores["validation_report_counts_correct"] = 1.0

        error_qids = [e["quote_id"] for e in error_items_from_output if e.get("quote_id") and e.get("quote_id") != "?"]
        all_listed = True
        for qid in error_qids:
            if qid not in report_text:
                all_listed = False
                break
        if all_listed and (len(error_qids) == 0 or all(qid in report_text for qid in error_qids)):
            scores["validation_report_lists_discarded_with_reasons"] = 1.0

        valid_without_match = set()
        milestone_set_for_report = set()
        if isinstance(delivered_milestones, list):
            for m in delivered_milestones:
                try:
                    milestone_set_for_report.add((int(m.get("year")), m.get("status")))
                except Exception:
                    pass
        for qid, meta in valid_quotes_from_output.items():
            if (meta.get("year"), meta.get("category")) not in milestone_set_for_report:
                valid_without_match.add(qid)
        if len(valid_without_match) == 0:
            found_line = False
            for line in report_text.splitlines():
                if re.search(r'\b(no|none)\b', line, flags=re.IGNORECASE) and re.search(r'\bmatching\b', line, flags=re.IGNORECASE):
                    found_line = True
                    break
            if found_line:
                scores["validation_report_notes_unused_valid"] = 1.0
        else:
            all_present = all(q in report_text for q in valid_without_match)
            if all_present:
                scores["validation_report_notes_unused_valid"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()