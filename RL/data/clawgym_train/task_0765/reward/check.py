import sys
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Dict


def read_text_safe(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        if not path.exists() or not path.is_file():
            return None, f"missing:{path}"
        return path.read_text(encoding="utf-8"), None
    except Exception as e:
        return None, f"error:{e}"


def load_json_safe(path: Path) -> Tuple[Optional[object], Optional[str]]:
    text, err = read_text_safe(path)
    if err or text is None:
        return None, err or "read_error"
    try:
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error:{e}"


def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def parse_front_matter(md_text: str) -> Dict[str, str]:
    # Extract YAML front matter between first two '---' lines at the top
    lines = md_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm_lines = []
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        fm_lines.append(lines[i])
        i += 1
    if i == len(lines):
        return {}
    fm_text = "\n".join(fm_lines)
    # Minimal YAML parsing for simple key: "value" or key: value
    fm: Dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()
        # Remove comments and trailing spaces
        if "#" in val:
            # only if not inside quotes
            if not (val.startswith('"') and val.endswith('"')) and not (val.startswith("'") and val.endswith("'")):
                val = val.split("#", 1)[0].strip()
        # Strip surrounding quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        fm[key] = val
    return fm


def iso_parseable(ts: str) -> bool:
    if not isinstance(ts, str) or not ts:
        return False
    s = ts
    # Allow Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        return False


def count_quoted_title(text: str, title: str) -> int:
    patterns = [
        f'"{title}"',
        f'“{title}”',
        f'„{title}”',  # some locales
        f'”{title}”',
        f'‘{title}’',
        f"'{title}'",
        f'‚{title}’',
    ]
    count = 0
    for p in patterns:
        count += text.count(p)
    return count


def tokenize(text: str) -> List[str]:
    return re.findall(r"[A-Za-z0-9]+", text.lower())


def first_sentence(text: str) -> str:
    # Split on period; if none, return all
    parts = re.split(r'(?<=\.)\s+', text.strip())
    if parts:
        # The first "sentence" could be before the first period; handle no period
        # If the first element does not end with '.', it's still acceptable
        first = parts[0]
        if '.' in text:
            # ensure we grab up to first period
            first = text.split('.', 1)[0]
        return first.strip()
    return text.strip()


def parse_log_counts_and_lines(log_text: str) -> Tuple[int, int, List[str]]:
    warnings = []
    errors = []
    for line in log_text.splitlines():
        if line.startswith("WARNING:"):
            warnings.append(line.strip())
        elif line.startswith("ERROR:"):
            errors.append(line.strip())
    # Interleave in original order as they appear
    warn_err_lines = []
    for line in log_text.splitlines():
        if line.startswith("WARNING:") or line.startswith("ERROR:"):
            warn_err_lines.append(line.strip())
    return len(warnings), len(errors), warn_err_lines


def get_expected_subject(date_str: str, title: str, errors_count: int) -> str:
    em_dash = " — "
    if errors_count > 0:
        return f"[HOLD] {date_str}{em_dash}{title}"
    return f"{date_str}{em_dash}{title}"


def find_processed_items(obj: object) -> Optional[List[dict]]:
    # Expect a dict with a list value containing dict items with required keys
    req_keys = {"slug", "source_path", "sha256", "processed_at"}
    if isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj):
            if all(req_keys.issubset(set(x.keys())) for x in obj):
                return obj
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and all(isinstance(x, dict) for x in v):
                if all(req_keys.issubset(set(x.keys())) for x in v):
                    return v
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        # Announcements
        "announcement_exists_2026_04_19_sermon": 0.0,
        "announcement_length_range_2026_04_19_sermon": 0.0,
        "announcement_title_once_2026_04_19_sermon": 0.0,
        "announcement_passage_once_2026_04_19_sermon": 0.0,
        "announcement_excludes_system_words_2026_04_19_sermon": 0.0,
        "announcement_exists_2026_04_26_sermon": 0.0,
        "announcement_length_range_2026_04_26_sermon": 0.0,
        "announcement_title_once_2026_04_26_sermon": 0.0,
        "announcement_passage_once_2026_04_26_sermon": 0.0,
        "announcement_excludes_system_words_2026_04_26_sermon": 0.0,
        # Emails
        "email_exists_2026_04_19_sermon": 0.0,
        "email_headers_format_2026_04_19_sermon": 0.0,
        "email_includes_announcement_2026_04_19_sermon": 0.0,
        "email_story_hook_valid_2026_04_19_sermon": 0.0,
        "email_internal_note_2026_04_19_sermon": 0.0,
        "email_exists_2026_04_26_sermon": 0.0,
        "email_headers_format_2026_04_26_sermon": 0.0,
        "email_includes_announcement_2026_04_26_sermon": 0.0,
        "email_story_hook_valid_2026_04_26_sermon": 0.0,
        "email_internal_note_2026_04_26_sermon": 0.0,
        # Status files
        "status_file_ok_2026_04_19_sermon": 0.0,
        "status_file_ok_2026_04_26_sermon": 0.0,
        # Run log
        "run_log_contains_expected_lines": 0.0,
        # Processed state
        "processed_json_structure_ok": 0.0,
        "processed_items_correct": 0.0,
    }

    expected_slugs = ["2026-04-19-sermon", "2026-04-26-sermon"]
    sermon_fms: Dict[str, Dict[str, str]] = {}
    for slug in expected_slugs:
        sermon_path = workspace / "input" / "sermons" / f"{slug}.md"
        md_text, err = read_text_safe(sermon_path)
        if md_text is None:
            sermon_fms[slug] = {}
            continue
        fm = parse_front_matter(md_text)
        sermon_fms[slug] = fm

    # Prepare expected data for each slug
    data = {}
    for slug in expected_slugs:
        fm = sermon_fms.get(slug, {})
        title = fm.get("title", "").strip()
        passage = fm.get("passage", "").strip()
        series = fm.get("series", "").strip()
        date = fm.get("date", "").strip()
        summary = fm.get("summary", "").strip()
        data[slug] = {
            "title": title,
            "passage": passage,
            "series": series,
            "date": date,
            "summary": summary,
        }

    # Pre-read logs for counts and lines
    log_info: Dict[str, Dict[str, object]] = {}
    for slug in expected_slugs:
        date = data[slug]["date"]
        if not date:
            log_info[slug] = {"warnings": None, "errors": None, "lines": []}
            continue
        log_path = workspace / "input" / "logs" / f"{date}-render.log"
        log_text, err = read_text_safe(log_path)
        if log_text is None:
            log_info[slug] = {"warnings": None, "errors": None, "lines": []}
        else:
            w, e, lines = parse_log_counts_and_lines(log_text)
            log_info[slug] = {"warnings": w, "errors": e, "lines": lines}

    # Check announcements
    for slug in expected_slugs:
        out_path = workspace / "output" / "announcements" / f"{slug}.txt"
        key_slug = slug.replace("-", "_")
        exists_key = f"announcement_exists_{key_slug}"
        length_key = f"announcement_length_range_{key_slug}"
        title_once_key = f"announcement_title_once_{key_slug}"
        passage_once_key = f"announcement_passage_once_{key_slug}"
        excludes_key = f"announcement_excludes_system_words_{key_slug}"

        text, err = read_text_safe(out_path)
        if text is None:
            # missing file, keep zeros
            continue
        scores[exists_key] = 1.0

        content = text.strip()
        # Length 280-400
        if 280 <= len(content) <= 400:
            scores[length_key] = 1.0

        title = data[slug]["title"]
        passage = data[slug]["passage"]
        # Title appears exactly once in any form, and at least once with quotes
        title_count = content.count(title) if title else 0
        quoted_count = count_quoted_title(content, title) if title else 0
        if title and title_count == 1 and quoted_count == 1:
            scores[title_once_key] = 1.0

        # Passage exactly once
        if passage and content.count(passage) == 1:
            scores[passage_once_key] = 1.0

        # No "WARNING"/"ERROR" words and no "Internal Note"
        if "WARNING" not in content and "ERROR" not in content and "Internal Note" not in content:
            scores[excludes_key] = 1.0

    # Check emails
    for slug in expected_slugs:
        out_path = workspace / "output" / "emails" / f"{slug}.txt"
        ann_path = workspace / "output" / "announcements" / f"{slug}.txt"
        key_slug = slug.replace("-", "_")
        exists_key = f"email_exists_{key_slug}"
        headers_key = f"email_headers_format_{key_slug}"
        includes_ann_key = f"email_includes_announcement_{key_slug}"
        hook_key = f"email_story_hook_valid_{key_slug}"
        internal_note_key = f"email_internal_note_{key_slug}"

        email_text, err = read_text_safe(out_path)
        if email_text is None:
            continue
        scores[exists_key] = 1.0

        lines = email_text.splitlines()
        # Ensure at least 3 lines (To, Subject, blank) and then body
        headers_ok = False
        subject_ok = False
        blank_line_ok = False
        expected_to = "To: congregation@example.org"
        if len(lines) >= 3 and lines[0].strip() == expected_to:
            # Subject
            subj_line = lines[1]
            fm = data[slug]
            w = log_info[slug]["warnings"]
            e = log_info[slug]["errors"]
            if isinstance(e, int):
                expected_subject = get_expected_subject(fm["date"], fm["title"], e)
                if subj_line.strip() == f"Subject: {expected_subject}":
                    subject_ok = True
            if lines[2].strip() == "":
                blank_line_ok = True
            headers_ok = subject_ok and blank_line_ok
        if headers_ok:
            scores[headers_key] = 1.0

        # Body includes announcement text
        ann_text, _ = read_text_safe(ann_path)
        if ann_text is not None:
            body = "\n".join(lines[3:]) if len(lines) > 3 else ""
            if ann_text.strip() and ann_text.strip() in body:
                scores[includes_ann_key] = 1.0

        # Story hook validation
        hook_ok = False
        fm = data[slug]
        body_lines = lines[3:] if len(lines) > 3 else []
        story_hook_lines = [l for l in body_lines if l.strip().lower().startswith("story hook:")]
        if story_hook_lines:
            # Take the first
            hook_line = story_hook_lines[0]
            after_colon = hook_line.split(":", 1)[1] if ":" in hook_line else ""
            hook_text = after_colon.strip()
            # Count words
            words = tokenize(hook_text)
            if 0 < len(words) <= 20:
                # Check overlap with first sentence of summary
                first_sent = first_sentence(fm.get("summary", ""))
                first_tokens = set(tokenize(first_sent))
                overlap = set(words) & first_tokens
                if len(overlap) >= 1:
                    hook_ok = True
        if hook_ok:
            scores[hook_key] = 1.0

        # Internal Note section if warnings or errors present
        internal_note_ok = False
        w = log_info[slug]["warnings"]
        e = log_info[slug]["errors"]
        if isinstance(w, int) and isinstance(e, int):
            warn_err_lines = log_info[slug]["lines"]
            body = "\n".join(lines[3:]) if len(lines) > 3 else ""
            if (w > 0 or e > 0):
                if "Internal Note (for pastor only):" in body:
                    # counts present (accept singular/plural)
                    pattern = re.compile(rf"\b{w}\s+warning(s)?\b,\s*{e}\s+error(s)?\b", re.IGNORECASE)
                    if pattern.search(body):
                        # first up to 3 lines verbatim present
                        need_lines = warn_err_lines[: min(3, len(warn_err_lines))]
                        if all(l in body for l in need_lines):
                            internal_note_ok = True
            else:
                # No warnings or errors -> ensure there is no internal note
                if "Internal Note (for pastor only):" not in body:
                    internal_note_ok = True
        if internal_note_ok:
            scores[internal_note_key] = 1.0

    # Status files
    for slug in expected_slugs:
        key_slug = slug.replace("-", "_")
        status_key = f"status_file_ok_{key_slug}"
        fm = data[slug]
        e = log_info[slug]["errors"]
        if not isinstance(e, int):
            continue
        expected_status = "ON_HOLD" if e > 0 else "READY"
        status_path = workspace / "output" / "status" / f"{slug}.status"
        status_text, err = read_text_safe(status_path)
        if status_text is None:
            continue
        if status_text.strip() == expected_status:
            scores[status_key] = 1.0

    # Run log
    run_log_path = workspace / "output" / "logs" / "run.log"
    run_text, err = read_text_safe(run_log_path)
    if run_text is not None:
        ok_all = True
        for slug in expected_slugs:
            w = log_info[slug]["warnings"]
            e = log_info[slug]["errors"]
            if not isinstance(w, int) or not isinstance(e, int):
                ok_all = False
                continue
            status = "ON_HOLD" if e > 0 else "READY"
            pattern = re.compile(rf"^{re.escape(slug)}\s+WARNINGS={w}\s+ERRORS={e}\s+STATUS={status}\s*$")
            found = any(pattern.match(line) for line in run_text.splitlines())
            if not found:
                ok_all = False
        if ok_all:
            scores["run_log_contains_expected_lines"] = 1.0

    # Processed state
    state_path = workspace / "output" / "state" / "processed.json"
    state_obj, err = load_json_safe(state_path)
    structure_ok = False
    items_ok = False
    if state_obj is not None and isinstance(state_obj, (dict, list)):
        items = find_processed_items(state_obj)
        if isinstance(items, list):
            structure_ok = True
            # Verify both items present with required fields
            ok = True
            for slug in expected_slugs:
                sermon_path = workspace / "input" / "sermons" / f"{slug}.md"
                sha = sha256_file(sermon_path)
                found_item = None
                for it in items:
                    if it.get("slug") == slug:
                        found_item = it
                        break
                if not found_item:
                    ok = False
                    continue
                if found_item.get("source_path") != f"input/sermons/{slug}.md":
                    ok = False
                if not sha or found_item.get("sha256") != sha:
                    ok = False
                if not iso_parseable(found_item.get("processed_at", "")):
                    ok = False
            if ok:
                items_ok = True
    if structure_ok:
        scores["processed_json_structure_ok"] = 1.0
    if items_ok:
        scores["processed_items_correct"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()