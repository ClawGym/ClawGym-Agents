import json
import csv
import sys
import re
from datetime import datetime
from pathlib import Path
from html.parser import HTMLParser


def _read_text(path: Path) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
        return True, text
    except Exception:
        return False, ""


def _load_json(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return True, json.load(f)
    except Exception:
        return False, None


def _read_csv_dicts(path: Path) -> tuple[bool, list]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return True, rows
    except Exception:
        return False, []


class _FixturesHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.current_td_index = -1
        self.current_row = []
        self.rows = []
        self._capture_data = False
        self._current_data = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and attrs_dict.get("id") == "fixtures":
            self.in_table = True
        elif self.in_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag == "td":
            self._capture_data = True
            self._current_data = ""

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag == "td" and self._capture_data:
            self._capture_data = False
            self.current_row.append(self._current_data.strip())
            self._current_data = ""

    def handle_data(self, data):
        if self._capture_data:
            self._current_data += data


def _parse_fixtures_from_html(html_text: str) -> list:
    parser = _FixturesHTMLParser()
    parser.feed(html_text)
    # Expected columns: Date, Opponent, Venue, Competition, H/A
    fixtures = []
    for r in parser.rows:
        if len(r) >= 5:
            fixtures.append({
                "date": r[0].strip(),
                "opponent": r[1].strip(),
                "venue": r[2].strip(),
                "competition": r[3].strip(),
                "home_or_away": r[4].strip(),
            })
    return fixtures


def _compute_upcoming_from_input(schedule_path: Path) -> tuple[bool, list]:
    ok, html = _read_text(schedule_path)
    if not ok:
        return False, []
    fixtures = _parse_fixtures_from_html(html)
    # Parse dates and sort ascending
    def parse_date(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return None

    valid = []
    for f in fixtures:
        dt = parse_date(f.get("date", ""))
        if dt is not None:
            valid.append((dt, f))
    valid.sort(key=lambda x: x[0])
    next_three = [f for _, f in valid[:3]]
    # Ensure Home/Away normalization to exactly "Home" or "Away"
    for f in next_three:
        hoa = f.get("home_or_away", "")
        if hoa not in ("Home", "Away"):
            return False, []
    return True, next_three


def _compute_last3_summary_from_results(results_path: Path) -> tuple[bool, dict]:
    ok, rows = _read_csv_dicts(results_path)
    if not ok or not rows:
        return False, {}
    # Validate required columns
    required = {"date", "opponent", "home_away", "goals_for", "goals_against", "competition"}
    if not required.issubset(set(rows[0].keys())):
        return False, {}

    def parse_date(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d")
        except Exception:
            return None

    # Sort by date ascending then take last 3
    dated_rows = []
    for r in rows:
        dt = parse_date(r.get("date", ""))
        if dt is None:
            return False, {}
        dated_rows.append((dt, r))
    dated_rows.sort(key=lambda x: x[0])
    last3 = [r for _, r in dated_rows[-3:]]
    if len(last3) < 3:
        return False, {}
    wins = draws = losses = gf = ga = 0
    for r in last3:
        try:
            gfor = int(r.get("goals_for", "0"))
            gag = int(r.get("goals_against", "0"))
        except ValueError:
            return False, {}
        gf += gfor
        ga += gag
        if gfor > gag:
            wins += 1
        elif gfor == gag:
            draws += 1
        else:
            losses += 1
    summary = {
        "matches_analyzed": 3,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for_total": gf,
        "goals_against_total": ga,
        "goal_difference": gf - ga,
    }
    return True, summary


def _load_last3_summary_csv(path: Path) -> tuple[bool, dict]:
    ok, rows = _read_csv_dicts(path)
    if not ok or not rows:
        return False, {}
    # Check header fields exactly metric,value
    fieldnames = None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            fieldnames = header
    except Exception:
        return False, {}
    if fieldnames is None or len(fieldnames) != 2 or fieldnames[0] != "metric" or fieldnames[1] != "value":
        return False, {}
    result = {}
    for r in rows:
        key = r.get("metric")
        val = r.get("value")
        if key is None or val is None:
            return False, {}
        # Convert to int when numeric
        try:
            ival = int(val)
            result[key] = ival
        except Exception:
            # Allow for non-numeric values if any, but in this task all should be numeric
            result[key] = val
    expected_metrics = [
        "matches_analyzed", "wins", "draws", "losses",
        "goals_for_total", "goals_against_total", "goal_difference"
    ]
    for m in expected_metrics:
        if m not in result:
            return False, {}
        if not isinstance(result[m], int):
            return False, {}
    return True, result


def _normalize_heading_text(line: str) -> str:
    s = line.strip()
    # Remove leading markdown heading markers
    s = s.lstrip("#").strip()
    return s


def _find_section_ranges(text: str, titles: list[str]) -> tuple[bool, dict]:
    lines = text.splitlines()
    # Find indices of each title in order
    indices = []
    for title in titles:
        found_idx = -1
        for i, line in enumerate(lines):
            if _normalize_heading_text(line) == title:
                found_idx = i
                break
        if found_idx == -1:
            return False, {}
        indices.append(found_idx)
        # Remove considered lines up to found to preserve order requirement in next search
        # Instead, enforce order by ensuring indices are increasing
    # Ensure order
    if not (indices[0] < indices[1] < indices[2]):
        return False, {}
    # Extract sections content between headings
    sections = {}
    for idx, title in enumerate(titles):
        start = indices[idx] + 1
        end = indices[idx + 1] if idx + 1 < len(indices) else len(lines)
        sections[title] = [ln.rstrip() for ln in lines[start:end]]
    return True, sections


def _non_empty_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip() != ""]


def _contains_all_caps(text: str) -> bool:
    # Detect shouty casing: tokens with 3+ uppercase letters
    return re.search(r"\b[A-Z]{3,}\b", text) is not None


def _find_tools_scripts(tools_dir: Path, prefix: str) -> list[Path]:
    if not tools_dir.exists() or not tools_dir.is_dir():
        return []
    candidates = []
    for p in tools_dir.iterdir():
        if p.is_file() and p.name.startswith(prefix) and (p.suffix in (".py", ".sh", ".bash", ".cmd", ".bat")):
            candidates.append(p)
    return candidates


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "upcoming_json_exists": 0.0,
        "upcoming_json_structure_and_values": 0.0,
        "last3_summary_exists": 0.0,
        "last3_summary_structure_and_values": 0.0,
        "tools_scripts_present_and_named": 0.0,
        "tools_extract_script_references_paths": 0.0,
        "tools_summarize_script_references_paths": 0.0,
        "rituals_clean_exists": 0.0,
        "rituals_clean_safety_note": 0.0,
        "rituals_clean_numbered_list_and_min_items": 0.0,
        "rituals_clean_no_shouty_or_ambiguous_punct": 0.0,
        "rituals_clean_contains_key_rituals": 0.0,
        "weekly_update_structure_and_headings": 0.0,
        "weekly_update_fixtures_section_matches_json": 0.0,
        "weekly_update_form_section_consistent": 0.0,
        "weekly_update_rituals_spotlight_verbatim": 0.0,
        "group_chat_post_exists": 0.0,
        "group_chat_includes_required_details": 0.0,
        "group_chat_word_count_and_tone": 0.0,
        "email_to_fans_exists": 0.0,
        "email_includes_required_details": 0.0,
    }

    # Paths
    input_schedule = workspace / "input" / "schedule.html"
    input_results = workspace / "input" / "results.csv"
    rituals_src = workspace / "input" / "rituals.md"

    upcoming_json_path = workspace / "outputs" / "data" / "upcoming.json"
    last3_summary_csv_path = workspace / "outputs" / "data" / "last3_summary.csv"
    rituals_clean_path = workspace / "outputs" / "docs" / "rituals_clean.md"
    weekly_update_path = workspace / "outputs" / "reports" / "weekly_update.md"
    group_chat_path = workspace / "outputs" / "messages" / "group_chat_post.txt"
    email_path = workspace / "outputs" / "messages" / "email_to_fans.txt"
    tools_dir = workspace / "tools"

    # 1) Upcoming fixtures: existence and correctness vs input
    ok_up_json, up_json = _load_json(upcoming_json_path)
    if ok_up_json and isinstance(up_json, list):
        scores["upcoming_json_exists"] = 1.0
    else:
        scores["upcoming_json_exists"] = 0.0

    # Compute expected upcoming from input
    exp_ok, exp_upcoming = _compute_upcoming_from_input(input_schedule)
    if ok_up_json and exp_ok:
        # Validate structure: array of exactly 3 objects with required fields and values match
        required_fields = {"date", "opponent", "venue", "competition", "home_or_away"}
        if isinstance(up_json, list) and len(up_json) == 3 and all(isinstance(x, dict) for x in up_json):
            struct_ok = True
            for i, item in enumerate(up_json):
                if set(item.keys()) != required_fields:
                    struct_ok = False
                    break
                # Validate date format
                try:
                    datetime.strptime(item.get("date", ""), "%Y-%m-%d")
                except Exception:
                    struct_ok = False
                    break
                if item.get("home_or_away") not in ("Home", "Away"):
                    struct_ok = False
                    break
                # Compare to expected
                if item != exp_upcoming[i]:
                    struct_ok = False
                    break
            if struct_ok:
                scores["upcoming_json_structure_and_values"] = 1.0

    # 2) last3 summary from results.csv
    ok_last3_csv, parsed_summary = _load_last3_summary_csv(last3_summary_csv_path)
    if ok_last3_csv:
        scores["last3_summary_exists"] = 1.0
    else:
        scores["last3_summary_exists"] = 0.0

    exp2_ok, exp_summary = _compute_last3_summary_from_results(input_results)
    if ok_last3_csv and exp2_ok:
        if parsed_summary == exp_summary:
            scores["last3_summary_structure_and_values"] = 1.0

    # 3) tools scripts present and named, and reference correct paths
    extract_scripts = _find_tools_scripts(tools_dir, "extract_fixtures")
    summarize_scripts = _find_tools_scripts(tools_dir, "summarize_results")
    if extract_scripts and summarize_scripts:
        scores["tools_scripts_present_and_named"] = 1.0

    # Check scripts reference input and output paths
    def script_mentions(p: Path, substrings: list[str]) -> bool:
        ok, txt = _read_text(p)
        if not ok:
            return False
        txt_lower = txt.lower()
        return all(s.lower() in txt_lower for s in substrings)

    if extract_scripts:
        # any one of them mentions both input and output
        refs_ok = any(script_mentions(p, ["input/schedule.html", "outputs/data/upcoming.json"]) for p in extract_scripts)
        if refs_ok:
            scores["tools_extract_script_references_paths"] = 1.0

    if summarize_scripts:
        refs_ok2 = any(script_mentions(p, ["input/results.csv", "outputs/data/last3_summary.csv"]) for p in summarize_scripts)
        if refs_ok2:
            scores["tools_summarize_script_references_paths"] = 1.0

    # 4) rituals_clean.md structural validations
    ok_rituals_clean, rituals_clean_text = _read_text(rituals_clean_path)
    if ok_rituals_clean and rituals_clean_text.strip():
        scores["rituals_clean_exists"] = 1.0

        # Safety note at top: first non-empty line, single sentence (ends with .) and reference to safety/rules/security/stadium
        lines = [ln.rstrip() for ln in rituals_clean_text.splitlines()]
        first_nonempty = ""
        for ln in lines:
            if ln.strip():
                first_nonempty = ln.strip()
                break
        if first_nonempty:
            ends_with_period = first_nonempty.endswith(".")
            # check length reasonable
            contains_safety_keyword = re.search(r"\b(safety|safe|rules|security|stadium|respect)\b", first_nonempty, re.IGNORECASE) is not None
            if ends_with_period and contains_safety_keyword:
                scores["rituals_clean_safety_note"] = 1.0

        # Numbered list and at least 3 items
        numbered_items = [ln.strip() for ln in lines if re.match(r"^\s*\d+\.\s", ln)]
        if len(numbered_items) >= 3:
            scores["rituals_clean_numbered_list_and_min_items"] = 1.0

        # No shouty casing and ambiguous punctuation (!!, ??, ...)
        no_shouty = not _contains_all_caps(rituals_clean_text)
        no_ambiguous = ("!!" not in rituals_clean_text) and ("??" not in rituals_clean_text) and ("..." not in rituals_clean_text)
        if no_shouty and no_ambiguous:
            scores["rituals_clean_no_shouty_or_ambiguous_punct"] = 1.0

        # Contains key ritual concepts: left sock first, community scarf, clap 7 times, oranges at halftime, mantra/chants
        lc = rituals_clean_text.lower()
        has_sock = ("left sock" in lc)
        has_scarf = ("community scarf" in lc)
        has_clap7 = ("clap 7" in lc)
        has_oranges = ("orange" in lc)
        has_mantra = ("mantra" in lc) or ("chant" in lc)
        if all([has_sock, has_scarf, has_clap7, has_oranges, has_mantra]):
            scores["rituals_clean_contains_key_rituals"] = 1.0

    # 5) weekly_update.md checks
    ok_weekly, weekly_text = _read_text(weekly_update_path)
    titles = ["Upcoming Fixtures (Next 3)", "Form Snapshot (Last 3)", "Rituals Spotlight"]
    sections_ok = False
    sections = {}
    if ok_weekly:
        found, sections = _find_section_ranges(weekly_text, titles)
        if found:
            sections_ok = True
            scores["weekly_update_structure_and_headings"] = 1.0

    # Fixtures section consistency with upcoming.json
    if sections_ok and ok_up_json:
        fixt_lines_all = sections.get("Upcoming Fixtures (Next 3)", [])
        fixt_lines = _non_empty_lines(fixt_lines_all)
        if len(fixt_lines) == 3 and isinstance(up_json, list) and len(up_json) == 3:
            all_match = True
            for i in range(3):
                ln = fixt_lines[i]
                item = up_json[i]
                needed_values = [item["date"], item["opponent"], item["venue"], item["home_or_away"]]
                if not all(v in ln for v in needed_values):
                    all_match = False
                    break
            if all_match:
                scores["weekly_update_fixtures_section_matches_json"] = 1.0

    # Form Snapshot section consistency with last3_summary.csv
    if sections_ok and ok_last3_csv and exp2_ok:
        form_lines_all = sections.get("Form Snapshot (Last 3)", [])
        form_text = "\n".join(form_lines_all)
        # Find W/D/L either as "wins X", "draws Y", "losses Z" or as "X-Y-Z"
        wins = parsed_summary.get("wins", None)
        draws = parsed_summary.get("draws", None)
        losses = parsed_summary.get("losses", None)
        gd = parsed_summary.get("goal_difference", None)
        if None not in (wins, draws, losses, gd):
            ok_wdl = False
            # Pattern 1: explicit words
            m_wins = re.search(r"(\b\d+\b)\s*wins?", form_text, re.IGNORECASE)
            m_draws = re.search(r"(\b\d+\b)\s*draws?", form_text, re.IGNORECASE)
            m_losses = re.search(r"(\b\d+\b)\s*losses?", form_text, re.IGNORECASE)
            if m_wins and m_draws and m_losses:
                if int(m_wins.group(1)) == wins and int(m_draws.group(1)) == draws and int(m_losses.group(1)) == losses:
                    ok_wdl = True
            # Pattern 2: X-Y-Z
            if not ok_wdl:
                m_trip = re.search(r"\b(\d+)\s*[-/]\s*(\d+)\s*[-/]\s*(\d+)\b", form_text)
                if m_trip:
                    if int(m_trip.group(1)) == wins and int(m_trip.group(2)) == draws and int(m_trip.group(3)) == losses:
                        ok_wdl = True
            # Goal difference presence
            ok_gd = False
            # look for "goal difference" or "GD"
            m_gd = re.search(r"(goal difference|gd)[^0-9\-+]*([+\-]?\d+)", form_text, re.IGNORECASE)
            if m_gd:
                if int(m_gd.group(2)) == gd:
                    ok_gd = True
            if ok_wdl and ok_gd:
                scores["weekly_update_form_section_consistent"] = 1.0

    # Rituals Spotlight: first three numbered items verbatim
    if sections_ok and ok_rituals_clean:
        spotlight_lines = _non_empty_lines(sections.get("Rituals Spotlight", []))
        # Extract first three numbered items from rituals_clean
        rit_lines = [ln.rstrip() for ln in rituals_clean_text.splitlines()]
        numbered_items = [ln.strip() for ln in rit_lines if re.match(r"^\s*\d+\.\s", ln)]
        if len(numbered_items) >= 3 and len(spotlight_lines) == 3:
            if (spotlight_lines[0].strip() == numbered_items[0]
                and spotlight_lines[1].strip() == numbered_items[1]
                and spotlight_lines[2].strip() == numbered_items[2]):
                scores["weekly_update_rituals_spotlight_verbatim"] = 1.0

    # 6) Group chat post checks
    ok_gc, gc_text = _read_text(group_chat_path)
    if ok_gc and gc_text.strip():
        scores["group_chat_post_exists"] = 1.0
        words = re.findall(r"\b\w+\b", gc_text)
        word_count = len(words)
        length_ok = 120 <= word_count <= 160
        # From upcoming.json: next match date and opponent
        next_date = None
        next_opp = None
        if ok_up_json and isinstance(up_json, list) and len(up_json) >= 1:
            next_date = up_json[0].get("date")
            next_opp = up_json[0].get("opponent")
        details_ok = True
        if not next_date or next_date not in gc_text:
            details_ok = False
        if not next_opp or next_opp not in gc_text:
            details_ok = False
        # includes "blue socks" and "community scarf"
        if re.search(r"\bblue socks\b", gc_text, re.IGNORECASE) is None:
            details_ok = False
        if re.search(r"\bcommunity scarf\b", gc_text, re.IGNORECASE) is None:
            details_ok = False
        # includes exact cue "clap 7 times after the anthem"
        if re.search(r"clap\s+7\s+times\s+after\s+the\s+anthem", gc_text, re.IGNORECASE) is None:
            details_ok = False
        # includes nod to stadium rules
        if re.search(r"\bstadium rules\b", gc_text, re.IGNORECASE) is None:
            details_ok = False
        if details_ok:
            scores["group_chat_includes_required_details"] = 1.0
        # Tone: not shouty and length
        tone_ok = length_ok and (not _contains_all_caps(gc_text))
        if tone_ok:
            scores["group_chat_word_count_and_tone"] = 1.0

    # 7) Email to fans checks
    ok_email, email_text = _read_text(email_path)
    if ok_email and email_text.strip():
        scores["email_to_fans_exists"] = 1.0
        # Must contain Subject: and Body:
        has_subject = re.search(r"^\s*Subject\s*:", email_text, re.IGNORECASE | re.MULTILINE) is not None
        has_body = re.search(r"^\s*Body\s*:", email_text, re.IGNORECASE | re.MULTILINE) is not None
        # Extract body text (after Body: line)
        body_text = ""
        if has_body:
            m = re.search(r"^\s*Body\s*:\s*(.*)$", email_text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
            if m:
                # capture from the "Body:" line to end
                # But previous regex only captures end of that line; we need everything after the first Body: occurrence
                # Let's find the index
                lines = email_text.splitlines()
                body_start_idx = None
                for idx, ln in enumerate(lines):
                    if re.match(r"^\s*Body\s*:", ln, re.IGNORECASE):
                        body_start_idx = idx
                        break
                if body_start_idx is not None:
                    body_text = "\n".join(lines[body_start_idx + 1:]).strip()
        details_ok = False
        if has_subject and has_body and body_text:
            details_ok = True
            # Must include first upcoming fixture’s date, opponent, venue, and H/A
            if ok_up_json and isinstance(up_json, list) and len(up_json) >= 1:
                first = up_json[0]
                for key in ("date", "opponent", "venue", "home_or_away"):
                    if str(first.get(key, "")) not in email_text:
                        details_ok = False
            else:
                details_ok = False
            # One-line form summary using wins/draws/losses from last3_summary.csv
            # Find a line containing wins/draws/losses with numbers
            form_line_ok = False
            if ok_last3_csv:
                lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
                for ln in lines:
                    if re.search(r"wins?", ln, re.IGNORECASE) and re.search(r"draws?", ln, re.IGNORECASE) and re.search(r"losses?", ln, re.IGNORECASE):
                        mw = re.search(r"(\d+)\s*wins?", ln, re.IGNORECASE)
                        md = re.search(r"(\d+)\s*draws?", ln, re.IGNORECASE)
                        ml = re.search(r"(\d+)\s*losses?", ln, re.IGNORECASE)
                        if mw and md and ml:
                            if int(mw.group(1)) == parsed_summary.get("wins") and int(md.group(1)) == parsed_summary.get("draws") and int(ml.group(1)) == parsed_summary.get("losses"):
                                form_line_ok = True
                                break
            details_ok = details_ok and form_line_ok
            # Short positive mantra in quotes
            mantra_ok = re.search(r"\".{3,80}\"", body_text) is not None
            details_ok = details_ok and mantra_ok
            # Reminder to review the cleaned rituals
            rituals_mention_ok = re.search(r"\britual", body_text, re.IGNORECASE) is not None
            details_ok = details_ok and rituals_mention_ok
        if details_ok:
            scores["email_includes_required_details"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()