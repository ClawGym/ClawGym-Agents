import json
import re
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_text_file(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_yaml_releases(path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Minimal YAML parser tailored to provided releases.yaml.
    Supports:
    - Top-level list items starting with "- "
    - Key: value pairs; values may be quoted, unquoted, integers, or null
    - Empty value after colon treated as empty string
    """
    text = _read_text_file(path)
    if text is None:
        return None
    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def parse_kv(s: str) -> Optional[Tuple[str, Any]]:
        if ":" not in s:
            return None
        key, val = s.split(":", 1)
        key = key.strip()
        val = val.strip()
        if val == "":
            parsed_val: Any = ""
        else:
            if val.lower() == "null" or val == "~":
                parsed_val = None
            elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                parsed_val = val[1:-1]
            else:
                if key in {"priority"}:
                    try:
                        parsed_val = int(val)
                    except Exception:
                        parsed_val = val
                else:
                    parsed_val = val
        return key, parsed_val

    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("- "):
            current = {}
            items.append(current)
            rest = stripped[2:].strip()
            if rest:
                kv = parse_kv(rest)
                if kv is None:
                    return None
                k, v = kv
                current[k] = v
        else:
            if current is None:
                return None
            kv = parse_kv(stripped)
            if kv is None:
                return None
            k, v = kv
            current[k] = v
    return items


def _parse_date(s: Optional[str]) -> Optional[date]:
    if s is None or s == "":
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _build_selection(releases: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, List[str]]]:
    include_genres = cfg.get("include_genres", [])
    min_priority = cfg.get("min_priority", None)
    date_window = cfg.get("date_window", {})
    start = _parse_date(date_window.get("start"))
    end = _parse_date(date_window.get("end"))
    exclude_titles = set(cfg.get("exclude_titles", []))
    include_if_no_embargo_only = bool(cfg.get("include_if_no_embargo_only", False))

    included: List[Dict[str, Any]] = []
    excluded_reasons: Dict[str, List[str]] = {}

    for rec in releases:
        title = rec.get("title", "")
        reasons: List[str] = []

        # Genre
        genre = rec.get("genre")
        if not isinstance(include_genres, list) or genre not in include_genres:
            reasons.append("genre not included")

        # Date window
        pd = _parse_date(rec.get("pub_date"))
        if start is None or end is None or pd is None or not (start <= pd <= end):
            reasons.append("outside date window")

        # Priority
        prio = rec.get("priority")
        if not isinstance(min_priority, int) or not isinstance(prio, int) or prio < min_priority:
            reasons.append("below priority")

        # Exclude by title
        if title in exclude_titles:
            reasons.append("excluded by title")

        # Embargo rule
        embargo_raw = rec.get("embargo_date")
        embargo_date = _parse_date(embargo_raw) if isinstance(embargo_raw, str) else (None if embargo_raw in (None, "") else None)
        if include_if_no_embargo_only and embargo_date is not None:
            reasons.append("embargo present when not allowed")

        if len(reasons) == 0:
            included.append(rec)
        else:
            excluded_reasons[title] = reasons

    return included, excluded_reasons


def _get_bullet_lines(text: str) -> List[str]:
    bullets: List[str] = []
    for ln in text.splitlines():
        s = ln.lstrip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append(s)
    return bullets


def _extract_ints_from_line(line: str) -> List[int]:
    return [int(x) for x in re.findall(r"\b\d+\b", line)]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "email_file_exists": 0.0,
        "email_salutation_applied": 0.0,
        "email_includes_date_window_literal": 0.0,
        "email_included_titles_listed_correctly": 0.0,
        "email_excludes_disallowed_titles": 0.0,
        "summary_file_exists": 0.0,
        "summary_includes_include_genres_values": 0.0,
        "summary_includes_min_priority_value": 0.0,
        "summary_includes_date_window_values": 0.0,
        "summary_includes_exclude_titles_values": 0.0,
        "summary_includes_include_if_no_embargo_only_value": 0.0,
        "summary_counts_totals_correct": 0.0,
        "summary_counts_by_reason_correct": 0.0,
        "summary_lists_included_titles": 0.0,
        "summary_lists_missing_blogger_pitch_titles": 0.0,
        "summary_config_keys_presence_noted": 0.0,
    }

    # Load config and releases; if missing or malformed, keep all scores at 0.0
    cfg_path = workspace / "config" / "pitch_config.json"
    cfg = _load_json(cfg_path)
    releases_path = workspace / "input" / "releases.yaml"
    releases = _parse_yaml_releases(releases_path)
    if cfg is None or releases is None:
        return scores

    included, excluded_reasons = _build_selection(releases, cfg)
    included_titles = [r.get("title", "") for r in included]
    included_by_title = {r.get("title", ""): r for r in included}
    all_titles = [r.get("title", "") for r in releases]
    excluded_titles = [t for t in all_titles if t not in included_titles]

    dw = cfg.get("date_window", {})
    start_str = dw.get("start")
    end_str = dw.get("end")
    expected_window_literal = None
    if isinstance(start_str, str) and isinstance(end_str, str):
        expected_window_literal = f"{start_str} to {end_str}"

    # Check email output
    email_path = workspace / "output" / "email_final.md"
    email_text = _read_text_file(email_path)
    if email_text is not None:
        scores["email_file_exists"] = 1.0

        # Salutation check
        blogger_name = cfg.get("blogger_name", "")
        email_salutation_template = cfg.get("email_salutation", "")
        expected_salutation = ""
        try:
            expected_salutation = email_salutation_template.format(blogger_name=blogger_name)
        except Exception:
            expected_salutation = ""
        if expected_salutation and expected_salutation in email_text:
            scores["email_salutation_applied"] = 1.0

        # Date window literal in body
        if expected_window_literal and expected_window_literal in email_text:
            scores["email_includes_date_window_literal"] = 1.0

        # Included titles bullets
        bullets = _get_bullet_lines(email_text)
        included_ok = True
        for t in included_titles:
            rec = included_by_title.get(t, {})
            author = rec.get("author", "")
            pub_date_str = rec.get("pub_date", "")
            pitch = rec.get("blogger_pitch", "")
            pitch_text = pitch if isinstance(pitch, str) and pitch.strip() else "Pitch TBD"
            match_found = False
            for b in bullets:
                if (t in b) and (author in b) and (pub_date_str in b) and (pitch_text in b):
                    match_found = True
                    break
            if not match_found:
                included_ok = False
                break
        if included_ok:
            # Also ensure that number of included titles equals at least those found
            scores["email_included_titles_listed_correctly"] = 1.0

        # Ensure excluded titles are not listed as bullets
        excludes_ok = True
        for b in bullets:
            for t in excluded_titles:
                if t and (t in b):
                    excludes_ok = False
                    break
            if not excludes_ok:
                break
        if excludes_ok:
            scores["email_excludes_disallowed_titles"] = 1.0

    # Check summary report
    summary_path = workspace / "output" / "summary_report.md"
    summary_text = _read_text_file(summary_path)
    if summary_text is not None:
        scores["summary_file_exists"] = 1.0

        # Echo filter criteria values
        include_genres = cfg.get("include_genres", [])
        if isinstance(include_genres, list) and include_genres:
            if all(isinstance(g, str) and (g in summary_text) for g in include_genres):
                scores["summary_includes_include_genres_values"] = 1.0

        if isinstance(cfg.get("min_priority"), int):
            if str(cfg["min_priority"]) in summary_text:
                scores["summary_includes_min_priority_value"] = 1.0

        if isinstance(start_str, str) and isinstance(end_str, str):
            if (start_str in summary_text) and (end_str in summary_text):
                scores["summary_includes_date_window_values"] = 1.0

        ex_titles = cfg.get("exclude_titles", [])
        if isinstance(ex_titles, list):
            # If there are excluded titles, each should be echoed
            if (not ex_titles) or all(t in summary_text for t in ex_titles):
                scores["summary_includes_exclude_titles_values"] = 1.0

        include_if_no_embargo_only = bool(cfg.get("include_if_no_embargo_only", False))
        # Require the boolean value to appear in text in some form
        if str(include_if_no_embargo_only).lower() in summary_text.lower():
            scores["summary_includes_include_if_no_embargo_only_value"] = 1.0

        # Counts: totals
        total_titles = len(releases)
        included_count = len(included)
        excluded_count = total_titles - included_count

        def find_count_line(keywords: List[str], expected: int) -> bool:
            for ln in summary_text.splitlines():
                low = ln.lower()
                if all(k in low for k in keywords):
                    ints = _extract_ints_from_line(ln)
                    if expected in ints:
                        return True
            return False

        if (
            find_count_line(["total", "title"], total_titles)
            and find_count_line(["included"], included_count)
            and find_count_line(["excluded"], excluded_count)
        ):
            scores["summary_counts_totals_correct"] = 1.0

        # Counts by exclusion reason
        reason_labels = {
            "genre not included": ["genre", "not", "included"],
            "outside date window": ["outside", "date", "window"],
            "below priority": ["below", "priority"],
            "excluded by title": ["excluded", "title"],
            "embargo present when not allowed": ["embargo"],
        }
        reason_counts: Dict[str, int] = {k: 0 for k in reason_labels}
        for reasons in excluded_reasons.values():
            for r in reasons:
                if r in reason_counts:
                    reason_counts[r] += 1

        reasons_ok = True
        for reason, keywords in reason_labels.items():
            expected = reason_counts.get(reason, 0)
            # Only require presence when expected > 0
            if expected > 0 and not find_count_line(keywords, expected):
                reasons_ok = False
                break
        if reasons_ok:
            scores["summary_counts_by_reason_correct"] = 1.0

        # Included titles listed with Title — Author — pub_date
        included_list_ok = True
        for rec in included:
            t = rec.get("title", "")
            a = rec.get("author", "")
            d = rec.get("pub_date", "")
            found = False
            for ln in summary_text.splitlines():
                if (t in ln) and (a in ln) and (d in ln):
                    found = True
                    break
            if not found:
                included_list_ok = False
                break
        if included_list_ok:
            scores["summary_lists_included_titles"] = 1.0

        # Titles with missing blogger_pitch
        missing_pitch_titles: List[str] = []
        for rec in releases:
            bp = rec.get("blogger_pitch", None)
            if not isinstance(bp, str) or bp.strip() == "":
                missing_pitch_titles.append(rec.get("title", ""))
        missing_ok = True
        if missing_pitch_titles:
            for t in missing_pitch_titles:
                if t and (t not in summary_text):
                    missing_ok = False
                    break
        if missing_ok:
            scores["summary_lists_missing_blogger_pitch_titles"] = 1.0

        # Config keys presence noted
        required_keys = [
            "include_genres",
            "min_priority",
            "date_window",
            "exclude_titles",
            "include_if_no_embargo_only",
            "blogger_name",
            "email_salutation",
        ]
        missing_keys = [k for k in required_keys if k not in cfg]
        if not missing_keys:
            # Consider satisfied if nothing is missing
            scores["summary_config_keys_presence_noted"] = 1.0
        else:
            if all(k in summary_text for k in missing_keys):
                scores["summary_config_keys_presence_noted"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()