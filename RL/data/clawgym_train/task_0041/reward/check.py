import sys
import json
import csv
import re
from pathlib import Path
from datetime import datetime


def _read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_csv_safe(p: Path):
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def _float_try(x, default=None):
    try:
        return float(x)
    except Exception:
        return default


def _compute_scores_from_concerts(rows):
    results = []
    for row in rows:
        if (row.get("country") or "").strip() != "Australia":
            continue
        date_str = (row.get("date") or "").strip()
        date_obj = _parse_date(date_str)
        city = (row.get("city") or "").strip()
        venue = (row.get("venue") or "").strip()
        att = _float_try(row.get("attendance_estimate"), None)
        encore = _float_try(row.get("encore_count"), None)
        rating = _float_try(row.get("personal_rating"), None)
        notes = (row.get("notes") or "").strip()
        if date_obj is None or att is None or encore is None or rating is None:
            continue
        score = 0.6 * rating + 0.3 * encore + 0.1 * (att / 1000.0)
        score_round2 = round(score + 1e-12, 2)
        results.append({
            "date": date_str,
            "date_obj": date_obj,
            "city": city,
            "venue": venue,
            "score": score_round2,
            "notes": notes,
        })
    # Sort by score desc, then date desc (most recent first)
    results.sort(key=lambda r: (r["score"], r["date_obj"]), reverse=True)
    return results


def _load_top5_csv(p: Path):
    headers, rows = _read_csv_safe(p)
    if headers is None or rows is None:
        return None, None
    return headers, rows


def _parse_markdown_sections(text: str):
    # Find sections by headers with possible markdown syntax. Return dict name->content_lines
    lines = text.splitlines()

    def _normalize_header(line: str) -> str:
        s = line.strip()
        s = re.sub(r"^#+\s*", "", s)
        s = s.rstrip(":").strip()
        return s.lower()

    headers_idx = {}
    for idx, line in enumerate(lines):
        norm = _normalize_header(line)
        if norm in ("attendees", "decisions", "action items"):
            headers_idx[norm] = idx

    keys_in_order = [k for k in ("attendees", "decisions", "action items") if k in headers_idx]
    sections = {}
    for i, key in enumerate(keys_in_order):
        start = headers_idx[key] + 1
        end = len(lines)
        if i + 1 < len(keys_in_order):
            end = headers_idx[keys_in_order[i + 1]]
        sections[key] = lines[start:end]
    return sections


def _count_words(text: str) -> int:
    tokens = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    return len(tokens)


def _contains_email(text: str) -> bool:
    return re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text) is not None


def _has_3to5_photos(text: str) -> bool:
    t = text.lower()
    if re.search(r"\b3\s*[–-]\s*5\b", t):
        return True
    if re.search(r"\b3\s+to\s+5\b", t):
        return True
    if re.search(r"\bthree\s+to\s+five\b", t):
        return True
    return False


def _line_has_nav_entry(line: str, title: str, path: str) -> bool:
    pattern = r"-\s*\"?%s\"?\s*:\s*\"?%s\"?" % (re.escape(title), re.escape(path))
    return re.search(pattern, line) is not None


def _yaml_line_has_kv(line: str, key: str, value: str) -> bool:
    pattern = r"^\s*%s\s*:\s*\"?%s\"?\s*$" % (re.escape(key), re.escape(value))
    return re.search(pattern, line) is not None


def _features_theme_is_fanzine(lines: list) -> bool:
    # Try to ensure theme is within the features block
    feature_start_idxs = [i for i, ln in enumerate(lines) if re.match(r"^\s*features\s*:\s*$", ln)]
    if not feature_start_idxs:
        return False
    start = feature_start_idxs[0]
    # Determine indentation of features block
    features_indent = len(re.match(r"^(\s*)", lines[start]).group(1))
    # Scan forward until next top-level key with indentation <= features_indent
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        indent = len(re.match(r"^(\s*)", ln).group(1))
        if indent <= features_indent and re.match(r"^\s*\w+\s*:", ln):
            # next top-level key reached
            break
        if re.search(r"^\s*theme\s*:\s*\"?fan\-zine\"?\s*$", ln):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "top5_csv_exists_structure": 0.0,
        "top5_csv_values_and_order": 0.0,
        "top5_csv_scores_precision": 0.0,
        "top5_summary_bullets_count": 0.0,
        "top5_summary_content_alignment": 0.0,
        "email_polished_subject_and_length": 0.0,
        "email_polished_key_details": 0.0,
        "email_dm_length_and_intent": 0.0,
        "meeting_minutes_sections": 0.0,
        "meeting_minutes_attendees": 0.0,
        "meeting_minutes_decisions": 0.0,
        "meeting_minutes_action_items": 0.0,
        "site_config_language_timezone_theme": 0.0,
        "site_config_nav_entries": 0.0,
        "site_config_data_files_and_release_date": 0.0,
        "site_config_preserve_keys": 0.0,
    }

    # Prepare inputs
    input_concerts = workspace / "input" / "concerts.csv"
    input_email = workspace / "input" / "draft_email.txt"
    input_transcript = workspace / "input" / "fan_meeting_transcript.txt"
    input_site_config = workspace / "input" / "site_config.yaml"

    # Outputs
    out_csv = workspace / "outputs" / "top5_concerts.csv"
    out_summary = workspace / "outputs" / "top5_summary.md"
    out_email_polished = workspace / "outputs" / "email_polished.txt"
    out_email_dm = workspace / "outputs" / "email_dm.txt"
    out_minutes = workspace / "outputs" / "meeting_minutes.md"
    out_site_config = workspace / "outputs" / "site_config.yaml"

    # Compute expected top5 from input
    headers_in, rows_in = _read_csv_safe(input_concerts)
    expected_top5 = []
    if headers_in is not None and rows_in is not None:
        expected_sorted = _compute_scores_from_concerts(rows_in)
        expected_top5 = expected_sorted[:5]

    # Validate top5_concerts.csv
    headers_out, rows_out = _load_top5_csv(out_csv)
    if headers_out is not None and rows_out is not None:
        # Structure check: columns exactly rank,date,city,venue,score; exactly 5 rows; ranks 1..5
        if headers_out == ["rank", "date", "city", "venue", "score"] and len(rows_out) == 5:
            try:
                ranks_ok = all(str(i + 1) == (rows_out[i].get("rank") or "").strip() for i in range(5))
            except Exception:
                ranks_ok = False
            if ranks_ok:
                scores["top5_csv_exists_structure"] = 1.0
        # Values and order check
        if expected_top5 and len(rows_out) == 5:
            values_ok = True
            precision_ok = True
            for i, row in enumerate(rows_out):
                exp = expected_top5[i]
                if (row.get("date") or "").strip() != exp["date"]:
                    values_ok = False
                if (row.get("city") or "").strip() != exp["city"]:
                    values_ok = False
                if (row.get("venue") or "").strip() != exp["venue"]:
                    values_ok = False
                score_str = (row.get("score") or "").strip()
                score_val = _float_try(score_str, None)
                if score_val is None:
                    values_ok = False
                    precision_ok = False
                else:
                    if round(score_val, 2) != exp["score"]:
                        values_ok = False
                    if not re.match(r"^-?\d+(\.\d{1,2})?$", score_str):
                        precision_ok = False
            if values_ok:
                scores["top5_csv_values_and_order"] = 1.0
            if precision_ok:
                scores["top5_csv_scores_precision"] = 1.0

    # Validate summary
    summary_text = _read_text_safe(out_summary)
    if summary_text:
        lines = [ln for ln in (l.strip() for l in summary_text.splitlines()) if ln]
        bullet_lines = [ln for ln in lines if ln.startswith("- ")]
        if len(bullet_lines) == 5:
            scores["top5_summary_bullets_count"] = 1.0
            alignment_ok = True
            if expected_top5 and len(bullet_lines) == 5:
                for i, bl in enumerate(bullet_lines):
                    exp = expected_top5[i]
                    if exp["date"] not in bl:
                        alignment_ok = False
                    if exp["city"].lower() not in bl.lower():
                        alignment_ok = False
                    if exp["venue"].lower() not in bl.lower():
                        alignment_ok = False
                    notes = exp["notes"]
                    tokens = [t.strip(",.;:()").lower() for t in re.findall(r"\b[\w’'-]{4,}\b", notes)]
                    if tokens:
                        if not any(tok in bl.lower() for tok in tokens):
                            alignment_ok = False
            else:
                alignment_ok = False
            if alignment_ok:
                scores["top5_summary_content_alignment"] = 1.0

    # Validate email_polished.txt
    email_polished_txt = _read_text_safe(out_email_polished)
    if email_polished_txt:
        lines = email_polished_txt.splitlines()
        subject_ok = len(lines) >= 1 and lines[0].strip() == "Subject: Permission Request for Fan Zine Setlist Photos"
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        word_count = _count_words(body)
        length_ok = word_count <= 150 and word_count > 0
        if subject_ok and length_ok:
            scores["email_polished_subject_and_length"] = 1.0

        body_l = body.lower()
        noncomm_ok = ("non-commercial" in body_l) or ("non commercial" in body_l) or ("noncommercial" in body_l)
        zine_ok = ("zine" in body_l)
        permission_ok = "permission" in body_l
        photos_ok = ("photo" in body_l)
        range_ok = _has_3to5_photos(body)
        aus_ok = ("australia" in body_l) or ("australian" in body_l)
        credit_ok = ("credit" in body_l) and (("photographer" in body_l) or ("venue" in body_l) or ("photographers" in body_l) or ("venues" in body_l))
        date_ok = "2026-04-30" in body
        contact_ok = _contains_email(body)
        if (noncomm_ok and zine_ok and permission_ok and photos_ok and range_ok and aus_ok and credit_ok and date_ok and contact_ok):
            scores["email_polished_key_details"] = 1.0

    # Validate email_dm.txt
    email_dm_txt = _read_text_safe(out_email_dm)
    if email_dm_txt:
        dm_len_ok = len(email_dm_txt.strip()) <= 320 and len(email_dm_txt.strip()) > 0
        dm_l = email_dm_txt.lower()
        intent_ok = ("permission" in dm_l) and (("zine" in dm_l) or ("fan zine" in dm_l)) and ("photo" in dm_l) and _has_3to5_photos(dm_l) and (("australia" in dm_l) or ("australian" in dm_l))
        friendly_ok = ("please" in dm_l) or ("thanks" in dm_l) or ("thank you" in dm_l)
        if dm_len_ok and intent_ok and friendly_ok:
            scores["email_dm_length_and_intent"] = 1.0

    # Validate meeting_minutes.md
    minutes_text = _read_text_safe(out_minutes)
    if minutes_text:
        sections = _parse_markdown_sections(minutes_text)
        has_attendees = "attendees" in sections
        has_decisions = "decisions" in sections
        has_actions = "action items" in sections
        if has_attendees and has_decisions and has_actions:
            scores["meeting_minutes_sections"] = 1.0
        attendees_ok = False
        if has_attendees:
            attendees_text = "\n".join(sections["attendees"])
            names_ok = all(name in attendees_text for name in ["Riley", "Jess", "Tom", "Aisha"])
            attendees_ok = names_ok
        if attendees_ok:
            scores["meeting_minutes_attendees"] = 1.0
        decisions_ok = False
        if has_decisions:
            decisions_text = "\n".join(sections["decisions"])
            d1 = "2026-05-15" in decisions_text
            d2 = "Hordern Pavilion" in decisions_text
            d3 = ("0.6*personal_rating" in decisions_text and "0.3*encore_count" in decisions_text and "attendance_estimate/1000" in decisions_text)
            d4 = ("Australia/Sydney" in decisions_text)
            d5 = (("site config" in decisions_text.lower()) and ("output" in decisions_text.lower()))
            decisions_ok = d1 and d2 and d3 and d4 and d5
        if decisions_ok:
            scores["meeting_minutes_decisions"] = 1.0
        actions_ok = False
        if has_actions:
            action_lines = [ln for ln in sections["action items"] if ln.strip().startswith("- ")]
            pattern = re.compile(r"-\s*\[(?P<owner>[A-Za-z]+)\]\s*(?P<task>.+?)\s+—\s+Due:\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$")
            found = []
            for ln in action_lines:
                m = pattern.search(ln.strip())
                if m:
                    found.append((m.group("owner"), m.group("date")))
            required = {("Tom", "2026-04-18"), ("Jess", "2026-04-20"), ("Aisha", "2026-05-01"), ("Riley", "2026-04-19")}
            actions_ok = required.issubset(set(found))
        if actions_ok:
            scores["meeting_minutes_action_items"] = 1.0

    # Validate site_config.yaml output
    out_conf_text = _read_text_safe(out_site_config)
    in_conf_text = _read_text_safe(input_site_config)
    if out_conf_text:
        lines_out = out_conf_text.splitlines()
        lang_ok = any(_yaml_line_has_kv(ln, "language", "en-AU") for ln in lines_out)
        tz_ok = any(_yaml_line_has_kv(ln, "default_timezone", "Australia/Sydney") for ln in lines_out)
        theme_ok = _features_theme_is_fanzine(lines_out)
        if lang_ok and tz_ok and theme_ok:
            scores["site_config_language_timezone_theme"] = 1.0
        nav_ok = any(_line_has_nav_entry(ln, "Top 5 Concerts", "outputs/top5_concerts.csv") for ln in lines_out)
        nav_ok = nav_ok and any(_line_has_nav_entry(ln, "Meeting Minutes", "outputs/meeting_minutes.md") for ln in lines_out)
        nav_ok = nav_ok and any(_line_has_nav_entry(ln, "Email Draft", "outputs/email_polished.txt") for ln in lines_out)
        if nav_ok:
            scores["site_config_nav_entries"] = 1.0
        df_ok = ("outputs/top5_concerts.csv" in out_conf_text)
        ird_ok = any(_yaml_line_has_kv(ln, "issue_release_date", "2026-05-15") for ln in lines_out)
        if df_ok and ird_ok:
            scores["site_config_data_files_and_release_date"] = 1.0
        preserve_ok = True
        if in_conf_text:
            preserve_ok = preserve_ok and ('site_name: "SAFIA Fan Zine"' in out_conf_text)
            preserve_ok = preserve_ok and any(_line_has_nav_entry(ln, "Home", "index.md") for ln in lines_out)
            preserve_ok = preserve_ok and any(re.match(r"^\s*features\s*:\s*$", ln) for ln in lines_out)
            preserve_ok = preserve_ok and any(re.match(r"^\s*data_files\s*:", ln) for ln in lines_out)
        if preserve_ok:
            scores["site_config_preserve_keys"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()