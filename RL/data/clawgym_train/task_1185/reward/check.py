import json
import csv
import sys
import re
from pathlib import Path
from datetime import date, timedelta
from collections import Counter


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _read_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames if reader.fieldnames is not None else []
            rows = [dict(r) for r in reader]
            return rows, fieldnames, None
    except Exception as e:
        return None, None, str(e)


def _read_text_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)


def _contains_emoji(s: str) -> bool:
    ranges = [
        (0x1F300, 0x1F5FF),
        (0x1F600, 0x1F64F),
        (0x1F680, 0x1F6FF),
        (0x1F700, 0x1F77F),
        (0x1F780, 0x1F7FF),
        (0x1F800, 0x1F8FF),
        (0x1F900, 0x1F9FF),
        (0x1FA70, 0x1FAFF),
        (0x2600, 0x26FF),
        (0x2700, 0x27BF),
    ]
    for ch in s:
        cp = ord(ch)
        for lo, hi in ranges:
            if lo <= cp <= hi:
                return True
    return False


def _extract_markdown_section(text: str, title: str) -> str:
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if re.match(r"^\s*#+\s*", line):
            if title.lower() in line.lower():
                start_idx = i + 1
                break
        else:
            if line.strip().lower() == title.lower():
                start_idx = i + 1
                break
    if start_idx is None:
        for i, line in enumerate(lines):
            if title.lower() in line.lower():
                start_idx = i + 1
                break
    if start_idx is None:
        return ""
    collected = []
    for j in range(start_idx, len(lines)):
        if re.match(r"^\s*#+\s*", lines[j]):
            break
        collected.append(lines[j])
    return "\n".join(collected).strip()


def _first_paragraph(text: str) -> str:
    lines = text.splitlines()
    para_lines = []
    for ln in lines:
        if re.match(r"^\s*#+\s*", ln):
            break
        if ln.strip() == "":
            if para_lines:
                break
            else:
                continue
        para_lines.append(ln)
    return " ".join(para_lines).strip()


def _split_sentences(text: str):
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    clean = [p.strip() for p in parts if re.search(r"[A-Za-z0-9]", p or "")]
    return clean


def _compute_expected_rows(cfg: dict, topics: list) -> list:
    start = date.fromisoformat(cfg["start_date"])
    weeks = int(cfg["weeks"])
    channels = cfg["channels"]
    cadence = cfg["cadence_per_week"]
    rows = []
    topic_i = 0
    for w in range(weeks):
        week_start = start + timedelta(days=w * 7)
        for ch in channels:
            per_week = int(cadence.get(ch, 0))
            for p in range(per_week):
                t = topics[topic_i % len(topics)]
                d = week_start + timedelta(days=p)
                message_brief = f"{t['message_seed']} — framed for {ch}"
                rows.append({
                    'date': d.isoformat(),
                    'channel': ch,
                    'theme': t['theme'],
                    'audience_segment': t['audience_segment'],
                    'message_brief': message_brief
                })
                topic_i += 1
    return rows


def _normalize_csv_rows(rows: list, fieldnames: list) -> list:
    normalized = []
    for r in rows:
        normalized.append({
            'date': r.get('date', ''),
            'channel': r.get('channel', ''),
            'theme': r.get('theme', ''),
            'audience_segment': r.get('audience_segment', ''),
            'message_brief': r.get('message_brief', ''),
        })
    return normalized


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_has_channels_key": 0.0,
        "config_channels_align_cadence": 0.0,
        "config_preserved_core_settings": 0.0,
        "calendar_exists_and_headers": 0.0,
        "calendar_rows_match_expected": 0.0,
        "calendar_channel_counts_expected": 0.0,
        "rewritten_line_count_five": 0.0,
        "rewritten_each_line_length_ok": 0.0,
        "rewritten_no_hashtags_or_emojis": 0.0,
        "rewritten_each_line_mentions_policy_and_socioecon": 0.0,
        "status_report_exists_and_sections": 0.0,
        "error_analysis_mentions_keyerror_and_channels": 0.0,
        "update_paragraph_sentence_count": 0.0,
        "schedule_summary_counts_correct": 0.0,
        "theme_coverage_counts_correct": 0.0,
    }

    cfg_path = workspace / "config" / "plan.json"
    topics_path = workspace / "input" / "topics.csv"
    calendar_path = workspace / "output" / "calendar.csv"
    rewrites_path = workspace / "output" / "rewritten_messages.txt"
    report_path = workspace / "output" / "status_report.md"

    cfg, cfg_err = _load_json_safe(cfg_path)
    if cfg is not None and isinstance(cfg, dict):
        if "channels" in cfg and isinstance(cfg["channels"], list) and all(isinstance(c, str) for c in cfg["channels"]):
            scores["config_has_channels_key"] = 1.0

            cadence = cfg.get("cadence_per_week")
            if isinstance(cadence, dict):
                try:
                    cadence_ints = {k: int(v) for k, v in cadence.items()}
                    if set(cfg["channels"]) == set(cadence_ints.keys()):
                        scores["config_channels_align_cadence"] = 1.0
                except Exception:
                    pass

            expected_start = "2026-02-01"
            expected_weeks = 2
            expected_cadence = {"Newsletter": 1, "LinkedIn": 2}
            try:
                start_ok = cfg.get("start_date") == expected_start
                weeks_ok = int(cfg.get("weeks")) == expected_weeks
                cadence_ok = isinstance(cfg.get("cadence_per_week"), dict) and {k: int(v) for k, v in cfg.get("cadence_per_week").items()} == expected_cadence
                if start_ok and weeks_ok and cadence_ok:
                    scores["config_preserved_core_settings"] = 1.0
            except Exception:
                pass

    rows, headers, csv_err = _read_csv_dicts_safe(calendar_path)
    if rows is not None and headers is not None:
        expected_headers = ['date', 'channel', 'theme', 'audience_segment', 'message_brief']
        if headers == expected_headers:
            scores["calendar_exists_and_headers"] = 1.0

        topics_rows, topics_headers, topics_err = _read_csv_dicts_safe(topics_path)
        if cfg is not None and isinstance(cfg, dict) and "channels" in cfg and isinstance(cfg["channels"], list) and topics_rows is not None:
            norm_topics = []
            for r in topics_rows:
                if not all(k in r for k in ("theme", "audience_segment", "message_seed")):
                    norm_topics = None
                    break
                norm_topics.append({
                    "theme": (r.get("theme") or "").strip(),
                    "audience_segment": (r.get("audience_segment") or "").strip(),
                    "message_seed": (r.get("message_seed") or "").strip(),
                })
            if norm_topics is not None and len(norm_topics) > 0:
                try:
                    expected_calendar = _compute_expected_rows(cfg, norm_topics)
                    actual_rows = _normalize_csv_rows(rows, headers)
                    if actual_rows == expected_calendar:
                        scores["calendar_rows_match_expected"] = 1.0
                    ch_counts = Counter(r["channel"] for r in actual_rows if r.get("channel") is not None)
                    try:
                        weeks = int(cfg.get("weeks"))
                        cadence = {k: int(v) for k, v in cfg.get("cadence_per_week", {}).items()}
                        expected_counts = {ch: weeks * cadence.get(ch, 0) for ch in cfg.get("channels", [])}
                        if set(expected_counts.keys()) == set(ch_counts.keys()) and all(ch_counts.get(k, -1) == v for k, v in expected_counts.items()):
                            scores["calendar_channel_counts_expected"] = 1.0
                    except Exception:
                        pass
                except Exception:
                    pass

    rewritten_text, rw_err = _read_text_safe(rewrites_path)
    if rewritten_text is not None:
        lines = rewritten_text.splitlines()
        if len(lines) == 5:
            scores["rewritten_line_count_five"] = 1.0

        if lines and len(lines) == 5 and all(len(ln) <= 280 for ln in lines):
            scores["rewritten_each_line_length_ok"] = 1.0

        if lines and len(lines) == 5:
            no_bad = True
            for ln in lines:
                if "#" in ln:
                    no_bad = False
                    break
                if _contains_emoji(ln):
                    no_bad = False
                    break
            if no_bad:
                scores["rewritten_no_hashtags_or_emojis"] = 1.0

        policy_terms = {"policy", "policies", "governance", "regulation", "regulatory", "infrastructure"}
        socio_terms = {"socio", "economic", "economy", "jobs", "work", "livelihood", "equity", "costs", "prosperity", "community"}
        if lines and len(lines) == 5:
            ok_all = True
            for ln in lines:
                low = ln.lower()
                has_policy = any(t in low for t in policy_terms)
                has_socio = any(t in low for t in socio_terms)
                if not (has_policy and has_socio):
                    ok_all = False
                    break
            if ok_all:
                scores["rewritten_each_line_mentions_policy_and_socioecon"] = 1.0

    report_text, rep_err = _read_text_safe(report_path)
    if report_text is not None:
        ea_sec = _extract_markdown_section(report_text, "Error analysis")
        ss_sec = _extract_markdown_section(report_text, "Schedule summary")
        tc_sec = _extract_markdown_section(report_text, "Theme coverage")
        if ea_sec.strip() and ss_sec.strip() and tc_sec.strip():
            scores["status_report_exists_and_sections"] = 1.0

        ea_ok = False
        if ea_sec:
            conds = [
                ("KeyError" in ea_sec),
                ("channels" in ea_sec.lower()),
                ("platforms" in ea_sec.lower()),
                ("plan.json" in ea_sec.lower()),
            ]
            if all(conds):
                ea_ok = True
        if ea_ok:
            scores["error_analysis_mentions_keyerror_and_channels"] = 1.0

        first_para = _first_paragraph(report_text)
        if first_para:
            sents = _split_sentences(first_para)
            if 2 <= len(sents) <= 4:
                scores["update_paragraph_sentence_count"] = 1.0

        if rows is not None:
            actual_rows = _normalize_csv_rows(rows, headers or [])
            ch_counts = Counter(r.get("channel", "") for r in actual_rows)
            if "" in ch_counts:
                del ch_counts[""]
            total_posts = sum(ch_counts.values())

            ss_ok = True
            sec_text = ss_sec if ss_sec else ""
            for ch, cnt in ch_counts.items():
                pattern = re.compile(rf"{re.escape(ch)}[^\d]*(\d+)", flags=re.IGNORECASE)
                found = False
                for line in sec_text.splitlines():
                    m = pattern.search(line)
                    if m:
                        try:
                            num = int(m.group(1))
                            if num == cnt:
                                found = True
                                break
                        except Exception:
                            pass
                if not found:
                    ss_ok = False
                    break
            total_ok = False
            for line in sec_text.splitlines():
                if "total" in line.lower():
                    nums = re.findall(r"\d+", line)
                    for n in nums:
                        try:
                            if int(n) == total_posts:
                                total_ok = True
                                break
                        except Exception:
                            pass
                if total_ok:
                    break
            if ss_ok and total_ok:
                scores["schedule_summary_counts_correct"] = 1.0

        if rows is not None:
            actual_rows = _normalize_csv_rows(rows, headers or [])
            theme_counts = Counter(r.get("theme", "") for r in actual_rows)
            if "" in theme_counts:
                del theme_counts[""]
            tc_ok = True
            sec_text = tc_sec if tc_sec else ""
            for theme, cnt in theme_counts.items():
                pattern = re.compile(rf"{re.escape(theme)}[^\d]*(\d+)", flags=re.IGNORECASE)
                found = False
                for line in sec_text.splitlines():
                    m = pattern.search(line)
                    if m:
                        try:
                            num = int(m.group(1))
                            if num == cnt:
                                found = True
                                break
                        except Exception:
                            pass
                if not found:
                    tc_ok = False
                    break
            if tc_ok:
                scores["theme_coverage_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()