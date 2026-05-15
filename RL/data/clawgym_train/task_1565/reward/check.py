import sys
import json
import csv
import hashlib
import re
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_rows(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                rows.append({k: (v if v is not None else "") for k, v in row.items()})
            return rows
    except Exception:
        return None


def _sha256_hex(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _is_iso_datetime(s: str) -> bool:
    try:
        # Accept 'Z' suffix by converting to +00:00
        s2 = s
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


class ExhibitsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.events = []
        self._in_event = False
        self._event_div_depth = 0
        self._cur_event = None
        self._collect_title = False
        self._collect_city = False
        self._collect_desc = False
        self._in_tags = False
        self._in_li = False
        self._title_buf = []
        self._city_buf = []
        self._desc_buf = []
        self._li_buf = []

    def handle_starttag(self, tag, attrs):
        attrd = {k: v for k, v in attrs}
        cls = attrd.get("class", "") or ""
        classes = set(c.strip() for c in cls.split()) if cls else set()

        if tag == "div" and ("event" in classes):
            # start of event
            self._in_event = True
            self._event_div_depth = 1
            self._cur_event = {
                "title": "",
                "date": attrd.get("data-date", "").strip(),
                "city": "",
                "tags": [],
                "desc": "",
            }
            self._title_buf = []
            self._city_buf = []
            self._desc_buf = []
        elif self._in_event and tag == "div":
            self._event_div_depth += 1

        if self._in_event and tag == "h3" and ("title" in classes):
            self._collect_title = True
            self._title_buf = []
        if self._in_event and tag == "span" and ("city" in classes):
            self._collect_city = True
            self._city_buf = []
        if self._in_event and tag == "div" and ("desc" in classes):
            self._collect_desc = True
            # keep appending into desc buffer
        if self._in_event and tag == "ul" and ("tags" in classes):
            self._in_tags = True
        if self._in_event and self._in_tags and tag == "li":
            self._in_li = True
            self._li_buf = []

    def handle_endtag(self, tag):
        if self._in_event and tag == "h3" and self._collect_title:
            self._collect_title = False
            self._cur_event["title"] = "".join(self._title_buf).strip()
        if self._in_event and tag == "span" and self._collect_city:
            self._collect_city = False
            self._cur_event["city"] = "".join(self._city_buf).strip()
        if self._in_event and tag == "div" and self._collect_desc:
            # end of a desc div; do not automatically reset if nested divs, but here structure is flat
            self._collect_desc = False
            self._cur_event["desc"] = " ".join("".join(self._desc_buf).split())
        if self._in_event and self._in_tags and tag == "li" and self._in_li:
            self._in_li = False
            li_text = "".join(self._li_buf).strip()
            if li_text:
                self._cur_event["tags"].append(li_text)
        if self._in_event and tag == "ul" and self._in_tags:
            self._in_tags = False
        if self._in_event and tag == "div":
            self._event_div_depth -= 1
            if self._event_div_depth == 0:
                # finalize event
                # clean tags trim whitespace
                self._cur_event["tags"] = [t.strip() for t in self._cur_event["tags"] if t.strip()]
                self.events.append(self._cur_event)
                self._in_event = False
                self._cur_event = None

    def handle_data(self, data):
        if not self._in_event:
            return
        if self._collect_title:
            self._title_buf.append(data)
        if self._collect_city:
            self._city_buf.append(data)
        if self._collect_desc:
            self._desc_buf.append(data)
        if self._in_tags and self._in_li:
            self._li_buf.append(data)


def _parse_exhibits(path: Path) -> Optional[List[Dict[str, Any]]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = ExhibitsParser()
        parser.feed(text)
        # Normalize whitespace for desc
        for ev in parser.events:
            ev["desc"] = " ".join(ev.get("desc", "").split())
        return parser.events
    except Exception:
        return None


def _parse_roster_off_days(path: Path) -> Optional[Tuple[List[str], Optional[str], Optional[str]]]:
    rows = _read_csv_rows(path)
    if rows is None:
        return None
    off_days = []
    dates = []
    for row in rows:
        date_str = (row.get("date") or "").strip()
        duty = (row.get("duty") or "").strip()
        if not date_str:
            continue
        dates.append(date_str)
        if duty.lower() == "off":
            off_days.append(date_str)
    if not dates:
        return ([], None, None)
    try:
        min_date = min(dates)
        max_date = max(dates)
    except Exception:
        min_date = None
        max_date = None
    return (off_days, min_date, max_date)


def _parse_preferences(path: Path) -> Optional[Dict[str, Any]]:
    data = _read_json(path)
    if not isinstance(data, dict):
        return None
    return data


def _parse_favorite_artists(path: Path) -> Optional[List[str]]:
    text = _read_text(path)
    if text is None:
        return None
    names = []
    for line in text.splitlines():
        name = line.strip()
        if name:
            names.append(name)
    return names


def _find_inspiration_quote(path: Path) -> Optional[str]:
    text = _read_text(path)
    if text is None:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            # blockquote line
            if re.search(r"\bflight\b", stripped, flags=re.IGNORECASE):
                return stripped
    return None


def _normalize_letters(s: str) -> str:
    # Keep alphanumerics and spaces, lowercased
    return re.sub(r"[^a-z0-9 ]+", "", s.lower())


def _load_json_array(path: Path) -> Optional[list]:
    data = _read_json(path)
    if isinstance(data, list):
        return data
    return None


def _load_summary_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    return _read_csv_rows(path)


def _find_matches_file(workspace: Path, roster_stem: str, roster_name: str) -> Optional[Path]:
    # Accept both interpretations of basename: with or without extension
    candidates = [
        workspace / "output" / "matches" / f"matches_{roster_stem}.json",
        workspace / "output" / "matches" / f"matches_{roster_name}.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_summary_file(workspace: Path, roster_stem: str, roster_name: str) -> Optional[Path]:
    candidates = [
        workspace / "output" / "reports" / f"summary_{roster_stem}.csv",
        workspace / "output" / "reports" / f"summary_{roster_name}.csv",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "matches_file_exists": 0.0,
        "matches_event_count": 0.0,
        "matches_event_fields_correct": 0.0,
        "source_hashes_in_matches_correct": 0.0,
        "inspiration_quote_included": 0.0,
        "dedupe_by_title_applied": 0.0,
        "summary_file_exists": 0.0,
        "summary_rows_complete": 0.0,
        "summary_counts_correct": 0.0,
        "manifest_exists": 0.0,
        "manifest_contains_roster_sha": 0.0,
    }

    # Input files
    roster_path = workspace / "input" / "inbox" / "roster_2024_11.csv"
    exhibits_path = workspace / "data" / "exhibits.html"
    prefs_path = workspace / "config" / "preferences.json"
    fav_path = workspace / "notes" / "favorite_artists.txt"
    insp_path = workspace / "notes" / "inspiration.md"

    # Compute expected hashes for source_file_hashes
    src_hashes_expected = {}
    all_input_files_exist = True
    for key, path in [
        ("roster_csv", roster_path),
        ("exhibits_html", exhibits_path),
        ("preferences_json", prefs_path),
        ("favorite_artists_txt", fav_path),
        ("inspiration_md", insp_path),
    ]:
        h = _sha256_hex(path)
        if h is None:
            all_input_files_exist = False
        src_hashes_expected[key] = h

    # Parse inputs to compute expected outputs
    roster_info = _parse_roster_off_days(roster_path) if roster_path.exists() else None
    prefs = _parse_preferences(prefs_path) if prefs_path.exists() else None
    exhibits = _parse_exhibits(exhibits_path) if exhibits_path.exists() else None
    fav_artists = _parse_favorite_artists(fav_path) if fav_path.exists() else None
    inspiration_quote = _find_inspiration_quote(insp_path) if insp_path.exists() else None

    # Early checks for manifest existence
    manifest_path = workspace / "output" / "state" / "processed_manifest.json"
    manifest_data = _read_json(manifest_path)
    if isinstance(manifest_data, list):
        scores["manifest_exists"] = 1.0
    else:
        manifest_data = None

    # Determine expected matched events and summary if inputs are available
    expected_off_days = []
    expected_matches = []
    expected_summary_counts = {}
    expected_match_count = None
    roster_min = None
    roster_max = None
    dedupe_by_title = False
    if prefs and isinstance(prefs.get("interest_tags"), list):
        dedupe_by_title = bool(prefs.get("dedupe_by_title", False))
    # Compute expected
    if roster_info and exhibits is not None and prefs is not None and fav_artists is not None:
        off_days, roster_min, roster_max = roster_info
        expected_off_days = off_days[:]
        # interest tags set (case-insensitive compare)
        interest_tags = set([str(t).strip().lower() for t in prefs.get("interest_tags", []) if isinstance(t, str)])
        # Filter exhibits by intersecting tags
        filtered_events = []
        for ev in exhibits:
            # event date filter within min..max range (inclusive) if both provided
            ev_date = (ev.get("date") or "").strip()
            within_range = True
            if roster_min and roster_max and ev_date:
                within_range = (roster_min <= ev_date <= roster_max)
            # tags intersect
            ev_tags = [t.strip() for t in ev.get("tags", []) if isinstance(t, str)]
            tags_lower = [t.lower() for t in ev_tags]
            tag_intersects = any(t in interest_tags for t in tags_lower)
            if within_range and tag_intersects:
                filtered_events.append({
                    "title": ev.get("title", "").strip(),
                    "date": ev_date,
                    "city": (ev.get("city") or "").strip(),
                    "tags": ev_tags,
                    "desc": ev.get("desc", ""),
                })
        # Match events to OFF days
        off_set = set(expected_off_days)
        matched = [ev for ev in filtered_events if ev.get("date") in off_set]
        # Dedupe by title if enabled
        if dedupe_by_title:
            seen_titles = set()
            deduped = []
            for ev in matched:
                key = ev.get("title", "").strip().lower()
                if key not in seen_titles:
                    seen_titles.add(key)
                    deduped.append(ev)
            matched = deduped
        # Compute favorite artist matches and build expected match objects
        fav_lower = [n.strip().lower() for n in fav_artists]
        def fav_match(title: str, desc: str) -> bool:
            t = (title or "").lower()
            d = (desc or "").lower()
            return any((name and (name in t or name in d)) for name in fav_lower)
        # Inspiration quote expectation (normalize for later check)
        expected_insp_norm = _normalize_letters(inspiration_quote) if inspiration_quote else None

        expected_matches = []
        for ev in matched:
            em = {
                "event_title": ev["title"],
                "event_date": ev["date"],
                "city": ev["city"],
                "tags": ev["tags"],
                "matched_off_day": ev["date"],
                "interest_match": True,  # by filtered criteria
                "favorite_artist_match": fav_match(ev["title"], ev.get("desc", "")),
                # inspiration_quote presence checked later; content compared loosely
                # source_file_hashes compared exactly
            }
            if inspiration_quote:
                em["inspiration_quote"] = inspiration_quote
            expected_matches.append(em)

        # Build summary counts per off day
        # Initialize all OFF days to zeros
        summary = {d: {"matched_events_count": 0, "favorite_artist_flagged_count": 0} for d in expected_off_days}
        for em in expected_matches:
            od = em["matched_off_day"]
            if od in summary:
                summary[od]["matched_events_count"] += 1
                if em["favorite_artist_match"]:
                    summary[od]["favorite_artist_flagged_count"] += 1
        expected_summary_counts = summary
        expected_match_count = len(expected_matches)

    # Locate output files
    roster_name = roster_path.name  # roster_2024_11.csv
    roster_stem = roster_path.stem  # roster_2024_11
    matches_path = _find_matches_file(workspace, roster_stem, roster_name)
    summary_path = _find_summary_file(workspace, roster_stem, roster_name)

    # Check matches file existence
    matches_data = None
    if matches_path and matches_path.exists():
        scores["matches_file_exists"] = 1.0
        matches_data = _load_json_array(matches_path)

    # Validate matches content if we have expected values and matches_data
    if expected_match_count is not None and isinstance(matches_data, list):
        # Check event count exactly
        if len(matches_data) == expected_match_count:
            scores["matches_event_count"] = 1.0

        # Build maps by (title_lower, date)
        def mk_key(obj: Dict[str, Any]) -> Tuple[str, str]:
            return (str(obj.get("event_title", "")).strip().lower(), str(obj.get("event_date", "")).strip())

        expected_map = {mk_key(em): em for em in expected_matches}
        actual_map = {mk_key(am): am for am in matches_data}

        fields_ok = True
        hashes_ok = True
        insp_ok = True
        dedupe_ok = True

        # Dedupe check: no duplicate titles case-insensitive
        titles_lower = [str(item.get("event_title", "")).strip().lower() for item in matches_data]
        dedupe_ok = len(titles_lower) == len(set(titles_lower))
        if dedupe_ok:
            scores["dedupe_by_title_applied"] = 1.0

        # Check each expected event present and fields match
        for key, exp in expected_map.items():
            if key not in actual_map:
                fields_ok = False
                continue
            act = actual_map[key]
            # Required keys and types
            required_keys = ["event_title", "event_date", "city", "tags", "matched_off_day", "interest_match", "favorite_artist_match"]
            for rk in required_keys:
                if rk not in act:
                    fields_ok = False
            # Specific value checks
            if str(act.get("event_title", "")).strip() != exp["event_title"]:
                fields_ok = False
            if str(act.get("event_date", "")).strip() != exp["event_date"]:
                fields_ok = False
            if str(act.get("matched_off_day", "")).strip() != exp["matched_off_day"]:
                fields_ok = False
            if str(act.get("city", "")).strip() != exp["city"]:
                fields_ok = False
            # tags: list equality, case-insensitive but preserve order check based on lower-case
            act_tags = act.get("tags", [])
            if not isinstance(act_tags, list):
                fields_ok = False
            else:
                exp_tags_lower = [t.lower() for t in exp["tags"]]
                act_tags_lower = [str(t).strip().lower() for t in act_tags]
                if act_tags_lower != exp_tags_lower:
                    fields_ok = False
            # interest_match should be True given filtering
            if bool(act.get("interest_match")) != True:
                fields_ok = False
            # favorite_artist_match as expected
            if bool(act.get("favorite_artist_match")) != bool(exp["favorite_artist_match"]):
                fields_ok = False

            # inspiration quote presence and content
            # Must include if we found one; If none expected, must omit or may omit
            act_insp = act.get("inspiration_quote", None)
            if inspiration_quote:
                if act_insp is None:
                    insp_ok = False
                else:
                    # Compare loosely: ensure it contains the phrase "flight reveals the hidden geometry of balance"
                    exp_norm = _normalize_letters("Flight reveals the hidden geometry of balance.")
                    act_norm = _normalize_letters(str(act_insp))
                    if exp_norm not in act_norm:
                        insp_ok = False
            # source_file_hashes correctness
            act_hashes = act.get("source_file_hashes")
            if not isinstance(act_hashes, dict):
                hashes_ok = False
            else:
                # Must contain exactly the five keys
                required_hash_keys = {"roster_csv", "exhibits_html", "preferences_json", "favorite_artists_txt", "inspiration_md"}
                if set(act_hashes.keys()) != required_hash_keys:
                    hashes_ok = False
                else:
                    for k in required_hash_keys:
                        exp_h = src_hashes_expected.get(k)
                        act_h = act_hashes.get(k)
                        if exp_h is None or act_h is None:
                            hashes_ok = False
                            break
                        if str(act_h).lower() != str(exp_h).lower():
                            hashes_ok = False
                            break

        if fields_ok:
            scores["matches_event_fields_correct"] = 1.0
        if hashes_ok:
            scores["source_hashes_in_matches_correct"] = 1.0
        if insp_ok:
            scores["inspiration_quote_included"] = 1.0

    # Summary file existence
    summary_rows = None
    if summary_path and summary_path.exists():
        scores["summary_file_exists"] = 1.0
        summary_rows = _load_summary_csv(summary_path)

    # Validate summary content if expected available
    if expected_summary_counts and isinstance(summary_rows, list):
        # Validate header columns exist and correct
        # csv.DictReader already maps by header names; ensure expected keys present in all rows
        required_summary_cols = ["off_day", "matched_events_count", "favorite_artist_flagged_count"]
        header_ok = True
        if len(summary_rows) == 0:
            header_ok = False
        else:
            for row in summary_rows:
                for col in required_summary_cols:
                    if col not in row:
                        header_ok = False
                        break
                if not header_ok:
                    break
        if header_ok:
            # Validate rows cover exactly the OFF days
            actual_off_days = set()
            counts_ok = True
            for row in summary_rows:
                off_day = (row.get("off_day") or "").strip()
                if not off_day:
                    counts_ok = False
                    break
                actual_off_days.add(off_day)
                try:
                    mec = int(str(row.get("matched_events_count", "")).strip())
                    fafc = int(str(row.get("favorite_artist_flagged_count", "")).strip())
                except Exception:
                    counts_ok = False
                    break
                exp = expected_summary_counts.get(off_day)
                if exp is None:
                    counts_ok = False
                    break
                if mec != exp["matched_events_count"] or fafc != exp["favorite_artist_flagged_count"]:
                    counts_ok = False
                    break
            if actual_off_days == set(expected_summary_counts.keys()):
                scores["summary_rows_complete"] = 1.0
            if counts_ok:
                scores["summary_counts_correct"] = 1.0

    # Manifest contains roster sha256 entry
    if manifest_data is not None:
        # Compute roster sha
        roster_sha = _sha256_hex(roster_path)
        if roster_sha:
            found_entry = False
            for item in manifest_data:
                if not isinstance(item, dict):
                    continue
                sha = str(item.get("sha256", "")).strip().lower()
                if sha == roster_sha.lower():
                    # Check fields presence
                    file_path_present = "file_path" in item
                    processed_at = item.get("processed_at")
                    processed_at_ok = isinstance(processed_at, str) and _is_iso_datetime(processed_at)
                    if file_path_present and processed_at_ok:
                        found_entry = True
                        break
            if found_entry:
                scores["manifest_contains_roster_sha"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()