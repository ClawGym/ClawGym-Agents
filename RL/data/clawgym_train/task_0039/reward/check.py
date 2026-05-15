import json
import sys
import re
import csv
from pathlib import Path
from html.parser import HTMLParser


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json(path: Path):
    try:
        return json.loads(_read_text(path))
    except Exception:
        return None


def _load_csv_dicts(path: Path):
    try:
        text = _read_text(path)
        if not text:
            return None
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        rows = [dict(row) for row in reader]
        return {"header": reader.fieldnames, "rows": rows}
    except Exception:
        return None


def _parse_guidelines_yaml(path: Path) -> dict:
    # Minimal YAML parser tailored to the provided structure
    content = _read_text(path)
    if not content:
        return {}
    result = {
        "policies": {
            "disallow_fundraising_during_lent": False,
            "allowed_fundraising_exception_terms": [],
            "banned_phrases": [],
        }
    }
    lines = content.splitlines()
    in_policies = False
    collecting_key = None  # for lists under policies
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        if re.match(r"^\s*policies\s*:\s*$", line):
            in_policies = True
            collecting_key = None
            continue
        if in_policies:
            # Check dedent (next top-level key)
            if re.match(r"^\S", line):  # dedented to column 0, end of policies
                in_policies = False
                collecting_key = None
                # fall through to handle other top-level keys if needed
            else:
                # inside policies
                m_bool = re.match(r"^\s{2,}disallow_fundraising_during_lent\s*:\s*(true|false)\s*$", line, flags=re.IGNORECASE)
                if m_bool:
                    result["policies"]["disallow_fundraising_during_lent"] = m_bool.group(1).lower() == "true"
                    collecting_key = None
                    continue
                m_list_key = re.match(r"^\s{2,}(allowed_fundraising_exception_terms|banned_phrases)\s*:\s*$", line)
                if m_list_key:
                    collecting_key = m_list_key.group(1)
                    result["policies"].setdefault(collecting_key, [])
                    continue
                m_list_item = re.match(r"^\s{4,}-\s*(.+?)\s*$", line)
                if m_list_item and collecting_key:
                    item = m_list_item.group(1).strip()
                    # Remove surrounding quotes if present
                    if (item.startswith('"') and item.endswith('"')) or (item.startswith("'") and item.endswith("'")):
                        item = item[1:-1]
                    result["policies"][collecting_key].append(item)
                    continue
                # Any other line under policies is ignored for this parser
    return result


class _NewsletterParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_announcements = False
        self.in_events = False
        self.in_events_list = False
        self.capture_text_for_announcements = False
        self.announcements_text = []
        self.events = []
        self.current_li = None
        self.current_li_text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "section":
            if attrs_dict.get("id", "").lower() == "announcements":
                self.in_announcements = True
            elif attrs_dict.get("id", "").lower() == "events":
                self.in_events = True
        if tag.lower() == "ul" and self.in_events and attrs_dict.get("id", "").lower() == "events-list":
            self.in_events_list = True
        if tag.lower() == "li" and self.in_events_list:
            # Start of an event item
            self.current_li = {
                "title": attrs_dict.get("data-title", "").strip(),
                "date": attrs_dict.get("data-date", "").strip(),
                "time": attrs_dict.get("data-time", "").strip(),
                "location": "",
            }
            self.current_li_text = []
        if tag.lower() == "a":
            href = attrs_dict.get("href", "")
            if href:
                # relative link: not starting with http or https or mailto
                if not re.match(r"^(?i:https?://)", href) and not re.match(r"^(?i:mailto:)", href):
                    self.links.append(href)
        if self.in_announcements:
            # Capture all text within announcements section
            self.capture_text_for_announcements = True

    def handle_endtag(self, tag):
        if tag.lower() == "section":
            if self.in_announcements:
                self.in_announcements = False
                self.capture_text_for_announcements = False
            if self.in_events:
                self.in_events = False
        if tag.lower() == "ul":
            if self.in_events_list:
                self.in_events_list = False
        if tag.lower() == "li" and self.current_li is not None:
            full_text = "".join(self.current_li_text)
            # Extract location: after "Location:" up to the first period.
            loc_match = re.search(r"Location:\s*(.+?)(?:\.|$)", full_text, flags=re.IGNORECASE | re.DOTALL)
            location = ""
            if loc_match:
                location = loc_match.group(1).strip()
            # Clean trailing punctuation/spaces
            location = location.strip(" .")
            self.current_li["location"] = location
            self.events.append(self.current_li)
            self.current_li = None
            self.current_li_text = []

    def handle_data(self, data):
        if self.current_li is not None:
            self.current_li_text.append(data)
        if self.capture_text_for_announcements and self.in_announcements:
            self.announcements_text.append(data)


def _parse_newsletter(html_text: str):
    parser = _NewsletterParser()
    parser.feed(html_text)
    events = parser.events
    # Normalize event texts by stripping whitespace
    for e in events:
        e["title"] = e.get("title", "").strip()
        e["date"] = e.get("date", "").strip()
        e["time"] = e.get("time", "").strip()
        e["location"] = e.get("location", "").strip()
    links = parser.links
    announcements_text = " ".join(parser.announcements_text)
    announcements_text = re.sub(r"\s+", " ", announcements_text).strip()
    return events, links, announcements_text


def _extract_dates(text: str):
    # Find all YYYY-MM-DD dates and return as list of strings
    return re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", text)


def _parse_date(s: str):
    # Return (year, month, day) as ints or None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if not m:
        return None
    return tuple(map(int, m.groups()))


def _date_in_range(date_s: str, start_s: str, end_s: str) -> bool:
    d = _parse_date(date_s)
    s = _parse_date(start_s)
    e = _parse_date(end_s)
    if not d or not s or not e:
        return False
    return s <= d <= e


def _compare_events_to_schedule(events: list, schedule_rows: list):
    # Build maps by title (trimmed exact match)
    ev_map = {e["title"].strip(): e for e in events}
    sc_map = {r["title"].strip(): {"title": r["title"].strip(), "date": r["date"].strip(), "time": r["time"].strip(), "location": r["location"].strip()} for r in schedule_rows}
    all_titles = set(ev_map.keys()).union(sc_map.keys())
    mismatches = []
    for title in sorted(all_titles):
        in_ev = title in ev_map
        in_sc = title in sc_map
        if in_ev and in_sc:
            ev = ev_map[title]
            sc = sc_map[title]
            for field in ["date", "time", "location"]:
                if ev.get(field, "").strip() != sc.get(field, "").strip():
                    mismatches.append({
                        "title": title,
                        "field": field,
                        "newsletter_value": ev.get(field, "").strip(),
                        "schedule_value": sc.get(field, "").strip()
                    })
        elif in_ev and not in_sc:
            mismatches.append({
                "title": title,
                "type": "missing_from_schedule"
            })
        elif in_sc and not in_ev:
            mismatches.append({
                "title": title,
                "type": "missing_from_newsletter"
            })
    return mismatches


def _load_critique_json(path: Path):
    try:
        data = _load_json(path)
        if not isinstance(data, dict):
            return None
        # Basic schema
        required = ["guideline_violations", "schedule_mismatches", "broken_links", "overall_judgment", "recommendations"]
        for k in required:
            if k not in data:
                return None
        if not isinstance(data["guideline_violations"], list):
            return None
        if not isinstance(data["schedule_mismatches"], list):
            return None
        if not isinstance(data["broken_links"], list):
            return None
        if not isinstance(data["overall_judgment"], str):
            return None
        if not isinstance(data["recommendations"], list):
            return None
        return data
    except Exception:
        return None


def _canonicalize_mismatches(mismatches: list):
    # Return sorted list of dicts with only the essential keys for comparison
    result = []
    for m in mismatches:
        if "field" in m:
            result.append({
                "title": m.get("title", ""),
                "field": m.get("field", ""),
                "newsletter_value": m.get("newsletter_value", ""),
                "schedule_value": m.get("schedule_value", "")
            })
        elif "type" in m:
            result.append({
                "title": m.get("title", ""),
                "type": m.get("type", "")
            })
    # Sort deterministically
    def keyf(x):
        if "field" in x:
            return ("diff", x.get("title", ""), x.get("field", ""))
        else:
            return ("missing", x.get("title", ""), x.get("type", ""))
    result.sort(key=keyf)
    return result


def _get_relative_links_from_newsletter(workspace: Path) -> list:
    html_text = _read_text(workspace / "input" / "newsletter.html")
    events, links, _ = _parse_newsletter(html_text)
    # Normalize links by stripping spaces
    rel = []
    for href in links:
        href = href.strip()
        if href and not href.startswith("#"):
            rel.append(href)
    return rel


def _analyze_link_log_for_hrefs(log_text: str, hrefs: list):
    lines = log_text.splitlines()
    # Map href -> list of lines containing it
    href_line_map = {h: [] for h in hrefs}
    for line in lines:
        for h in hrefs:
            if h in line:
                href_line_map[h].append(line)
    error_tokens = [
        "no such file", "cannot stat", "cannot access", "not found",
        "error", "file not found", "the system cannot find the file specified"
    ]
    # Determine broken hrefs based on presence of any error token in lines mentioning the href
    broken = set()
    for h, hlines in href_line_map.items():
        h_broken = False
        for l in hlines:
            ll = l.lower()
            if any(tok in ll for tok in error_tokens):
                h_broken = True
                break
        if h_broken:
            broken.add(h)
    return href_line_map, broken


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "extracted_events_csv_exists": 0.0,
        "extracted_events_csv_content_correct": 0.0,
        "critique_json_exists_and_schema": 0.0,
        "schedule_mismatches_correct": 0.0,
        "banned_phrases_flagged": 0.0,
        "political_endorsement_flagged": 0.0,
        "fundraising_during_lent_flagged": 0.0,
        "link_check_log_exists": 0.0,
        "link_check_log_covers_relative_links": 0.0,
        "broken_links_match_log": 0.0,
        "overall_judgment_appropriate": 0.0,
        "recommendations_present": 0.0,
    }

    # Load input files
    newsletter_path = workspace / "input" / "newsletter.html"
    schedule_path = workspace / "input" / "schedule.csv"
    guidelines_path = workspace / "input" / "guidelines.yaml"
    calendar_path = workspace / "input" / "calendar.json"

    newsletter_html = _read_text(newsletter_path)
    schedule_csv = _load_csv_dicts(schedule_path)
    guidelines_yaml = _parse_guidelines_yaml(guidelines_path)
    calendar_json = _load_json(calendar_path)

    # Parse newsletter to compute expected events and relative links
    expected_events, relative_links, announcements_text = _parse_newsletter(newsletter_html)

    # 1) Validate output/extracted_events.csv
    extracted_events_path = workspace / "output" / "extracted_events.csv"
    extracted_csv = _load_csv_dicts(extracted_events_path)
    if extracted_csv is not None:
        scores["extracted_events_csv_exists"] = 1.0
        # Check header
        expected_header = ["title", "date", "time", "location"]
        header_ok = extracted_csv.get("header") == expected_header
        # Prepare expected rows
        expected_rows = [{k: e[k] for k in expected_header} for e in expected_events]
        # Compare as sets (order-insensitive), but require exact match (no extras)
        def normalize_rows(rows):
            return sorted([{k: v.strip() for k, v in r.items()} for r in rows], key=lambda r: (r["title"], r["date"], r["time"], r["location"]))
        if header_ok:
            out_rows = extracted_csv.get("rows") or []
            if isinstance(out_rows, list) and all(isinstance(r, dict) for r in out_rows):
                if normalize_rows(out_rows) == normalize_rows(expected_rows):
                    scores["extracted_events_csv_content_correct"] = 1.0

    # 2) critique.json existence and schema
    critique_path = workspace / "output" / "critique.json"
    critique = _load_critique_json(critique_path)
    if critique is not None:
        scores["critique_json_exists_and_schema"] = 1.0

    # 3) schedule mismatches correctness
    expected_mismatches = []
    if schedule_csv is not None:
        expected_mismatches = _compare_events_to_schedule(expected_events, schedule_csv.get("rows", []))
    if critique is not None:
        actual_mismatches = _canonicalize_mismatches(critique.get("schedule_mismatches", []))
        expected_canonical = _canonicalize_mismatches(expected_mismatches)
        # Must match exactly
        if actual_mismatches == expected_canonical:
            scores["schedule_mismatches_correct"] = 1.0

    # 4) Guideline violations checks
    banned_phrases = []
    try:
        banned_phrases = [bp for bp in (guidelines_yaml.get("policies", {}).get("banned_phrases", []) or []) if isinstance(bp, str)]
    except Exception:
        banned_phrases = []
    if critique is not None:
        gv = critique.get("guideline_violations", [])
        if isinstance(gv, list):
            # banned_phrases_flagged
            bp_flag = False
            for bp in banned_phrases:
                if not bp:
                    continue
                # Check newsletter contains the phrase (case-insensitive)
                if re.search(re.escape(bp), newsletter_html, flags=re.IGNORECASE):
                    # Ensure a violation entry contains either rule mentioning the phrase or evidence showing the phrase
                    for v in gv:
                        rule = (v.get("rule") or "")
                        evidence = (v.get("evidence") or "")
                        location = (v.get("location") or "")
                        if isinstance(rule, str) and isinstance(evidence, str) and isinstance(location, str):
                            if (re.search(re.escape(bp), rule, flags=re.IGNORECASE) or re.search(re.escape(bp), evidence, flags=re.IGNORECASE)) and location.strip():
                                bp_flag = True
                                break
                if bp_flag:
                    break
            scores["banned_phrases_flagged"] = 1.0 if bp_flag else 0.0

            # political_endorsement_flagged: evidence contains 'vote' and 'candidate' or rule contains 'politic'
            pe_flag = False
            for v in gv:
                rule = (v.get("rule") or "")
                evidence = (v.get("evidence") or "")
                if isinstance(rule, str) and isinstance(evidence, str):
                    if re.search(r"politic", rule, flags=re.IGNORECASE):
                        pe_flag = True
                        break
                    if re.search(r"\bvote\b", evidence, flags=re.IGNORECASE) and re.search(r"\bcandidate\b", evidence, flags=re.IGNORECASE):
                        pe_flag = True
                        break
            scores["political_endorsement_flagged"] = 1.0 if pe_flag else 0.0

            # fundraising during Lent flagged
            lent_periods = []
            if isinstance(calendar_json, dict):
                for sp in (calendar_json.get("season_periods") or []):
                    if isinstance(sp, dict) and sp.get("name") == "Lent":
                        start_s = sp.get("start_date")
                        end_s = sp.get("end_date")
                        if isinstance(start_s, str) and isinstance(end_s, str):
                            lent_periods.append((start_s, end_s))
            # Determine if newsletter has fundraising with date in Lent
            # Check events
            fund_in_lent_expected = False
            for ev in expected_events:
                title = ev.get("title", "")
                date = ev.get("date", "")
                if re.search(r"fund|appeal|donat", title, flags=re.IGNORECASE):
                    for (s, e) in lent_periods:
                        if _date_in_range(date, s, e):
                            fund_in_lent_expected = True
                            break
                if fund_in_lent_expected:
                    break
            # Check announcements for dates within Lent and fundraising words
            if not fund_in_lent_expected:
                ann_dates = _extract_dates(announcements_text)
                if re.search(r"fund|appeal|donat", announcements_text, flags=re.IGNORECASE):
                    for d in ann_dates:
                        for (s, e) in lent_periods:
                            if _date_in_range(d, s, e):
                                fund_in_lent_expected = True
                                break
                        if fund_in_lent_expected:
                            break
            # Validate violation exists
            fund_flag = False
            if fund_in_lent_expected:
                for v in gv:
                    rule = (v.get("rule") or "")
                    evidence = (v.get("evidence") or "")
                    if not isinstance(rule, str) or not isinstance(evidence, str):
                        continue
                    if re.search(r"fund|appeal|donat", rule, flags=re.IGNORECASE) or re.search(r"fund|appeal|donat", evidence, flags=re.IGNORECASE):
                        # Extract date(s) in evidence and check if any within Lent
                        evid_dates = _extract_dates(evidence)
                        within = False
                        for d in evid_dates:
                            for (s, e) in lent_periods:
                                if _date_in_range(d, s, e):
                                    within = True
                                    break
                            if within:
                                break
                        # If no dates in evidence, fall back to accepting if evidence mentions the specific fundraising event title
                        mentions_event = any(ev.get("title") in evidence for ev in expected_events if re.search(r"fund|appeal|donat", ev.get("title", ""), flags=re.IGNORECASE))
                        if within or mentions_event:
                            fund_flag = True
                            break
            scores["fundraising_during_lent_flagged"] = 1.0 if fund_flag else 0.0

    # 5) Link check log and broken links consistency
    link_log_path = workspace / "output" / "link_check.log"
    link_log_text = _read_text(link_log_path)
    if link_log_text:
        scores["link_check_log_exists"] = 1.0

    hrefs = _get_relative_links_from_newsletter(workspace)
    if link_log_text:
        href_line_map, broken_hrefs = _analyze_link_log_for_hrefs(link_log_text, hrefs)
        # coverage: each href should appear at least once in the log
        covers_all = all(len(href_line_map.get(h, [])) > 0 for h in hrefs)
        if covers_all:
            scores["link_check_log_covers_relative_links"] = 1.0

        # broken_links in critique vs log
        if critique is not None:
            bl = critique.get("broken_links", [])
            if isinstance(bl, list):
                # Validate each entry has required fields and that hrefs match expected broken set
                hrefs_in_critique = set()
                fields_ok = True
                messages_match_log = True
                for entry in bl:
                    if not isinstance(entry, dict):
                        fields_ok = False
                        break
                    href = entry.get("href")
                    context = entry.get("context")
                    error_message = entry.get("error_message")
                    if not (isinstance(href, str) and isinstance(context, str) and isinstance(error_message, str)):
                        fields_ok = False
                        break
                    if not href.strip() or not context.strip() or not error_message.strip():
                        fields_ok = False
                        break
                    hrefs_in_critique.add(href)
                    # Check that error_message appears in the log lines for that href (or in full log as a fallback)
                    lines_for_href = href_line_map.get(href, [])
                    combined = "\n".join(lines_for_href) if lines_for_href else link_log_text
                    if entry["error_message"] not in combined:
                        # Try relaxed check: ensure some error token appears in message
                        if not re.search(r"(No such file|cannot stat|cannot access|not found|File Not Found|The system cannot find the file specified|error)", entry["error_message"], flags=re.IGNORECASE):
                            messages_match_log = False
                # Now compare expected broken hrefs with those reported
                if fields_ok and messages_match_log and hrefs_in_critique == broken_hrefs:
                    scores["broken_links_match_log"] = 1.0

    # 6) Overall judgment appropriate
    if critique is not None:
        overall = critique.get("overall_judgment", "")
        if isinstance(overall, str):
            # Compute if issues exist from inputs: there is at least one mismatch, banned phrase, and fundraising-in-lent
            issues_exist = False
            # mismatch
            if expected_mismatches:
                issues_exist = True
            # banned phrase present in newsletter
            for bp in banned_phrases:
                if re.search(re.escape(bp), newsletter_html, flags=re.IGNORECASE):
                    issues_exist = True
                    break
            # fundraising during Lent based on inputs
            # This has already been computed above as fund_in_lent_expected
            # recompute quickly if not available
            lent_periods = []
            if isinstance(calendar_json, dict):
                for sp in (calendar_json.get("season_periods") or []):
                    if isinstance(sp, dict) and sp.get("name") == "Lent":
                        start_s = sp.get("start_date")
                        end_s = sp.get("end_date")
                        if isinstance(start_s, str) and isinstance(end_s, str):
                            lent_periods.append((start_s, end_s))
            fund_in_lent_expected = False
            for ev in expected_events:
                if re.search(r"fund|appeal|donat", ev.get("title", ""), flags=re.IGNORECASE):
                    for (s, e) in lent_periods:
                        if _date_in_range(ev.get("date", ""), s, e):
                            fund_in_lent_expected = True
                            break
                if fund_in_lent_expected:
                    break
            if not fund_in_lent_expected:
                ann_dates = _extract_dates(announcements_text)
                if re.search(r"fund|appeal|donat", announcements_text, flags=re.IGNORECASE):
                    for d in ann_dates:
                        for (s, e) in lent_periods:
                            if _date_in_range(d, s, e):
                                fund_in_lent_expected = True
                                break
                        if fund_in_lent_expected:
                            break
            if fund_in_lent_expected:
                issues_exist = True
            # Now evaluate overall
            overall_lc = overall.lower()
            needs_keywords = ["need", "change", "revise", "update", "amend", "not acceptable", "reject", "fix"]
            acceptable_keywords = ["acceptable", "as-is", "no changes needed"]
            if issues_exist:
                if any(k in overall_lc for k in needs_keywords) and not ("acceptable as-is" in overall_lc):
                    scores["overall_judgment_appropriate"] = 1.0
            else:
                # No issues: should be acceptable
                if any(k in overall_lc for k in acceptable_keywords):
                    scores["overall_judgment_appropriate"] = 1.0

        # Recommendations present
        recs = critique.get("recommendations")
        if isinstance(recs, list) and len(recs) >= 1 and all(isinstance(x, str) and x.strip() for x in recs):
            scores["recommendations_present"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()