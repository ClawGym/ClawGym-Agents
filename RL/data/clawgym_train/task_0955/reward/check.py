import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser
from typing import List, Dict, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_jsonl(path: Path) -> Tuple[Optional[List[Any]], Optional[str]]:
    items = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception as e:
                    return None, f"jsonl parse error on line {i}: {e}"
        return items, None
    except Exception as e:
        return None, str(e)


def _load_csv_dicts(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                if None in row.values():
                    return None, "Malformed CSV row with None values"
                rows.append({k: v for k, v in row.items()})
        return rows, None
    except Exception as e:
        return None, str(e)


def _parse_artist_yaml_minimal(path: Path) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Minimal YAML parser for simple key: value pairs to extract 'name' and 'hometown'.
    """
    text = _read_text(path)
    if text is None:
        return None, "Cannot read artist.yaml"
    result: Dict[str, str] = {}
    try:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                # Ignore non key-value lines
                continue
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            # Remove optional quotes
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if key in ("name", "hometown"):
                result[key] = val
        # Return even if partial; graders will check keys as needed
        return result, None
    except Exception as e:
        return None, str(e)


class _InterviewHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_h1 = False
        self.in_byline = False
        self.in_blockquote = False
        self.title_parts: List[str] = []
        self.byline_parts: List[str] = []
        self.blockquote_parts: List[str] = []
        self.quotes: List[str] = []
        self.date_iso: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag.lower() == "h1":
            self.in_h1 = True
        elif tag.lower() == "div":
            if "class" in attrs_dict and attrs_dict.get("class") == "byline":
                self.in_byline = True
        elif tag.lower() == "blockquote":
            self.in_blockquote = True
            self.blockquote_parts = []
        elif tag.lower() == "time":
            dt = attrs_dict.get("datetime")
            if dt:
                # Expect ISO YYYY-MM-DD
                self.date_iso = dt.strip()

    def handle_endtag(self, tag):
        if tag.lower() == "h1":
            self.in_h1 = False
        elif tag.lower() == "div":
            if self.in_byline:
                self.in_byline = False
        elif tag.lower() == "blockquote":
            if self.in_blockquote:
                quote = "".join(self.blockquote_parts).strip()
                # Normalize internal whitespace
                quote = re.sub(r"\s+", " ", quote)
                self.quotes.append(quote)
                self.in_blockquote = False
                self.blockquote_parts = []

    def handle_data(self, data):
        if self.in_h1:
            self.title_parts.append(data)
        if self.in_byline:
            self.byline_parts.append(data)
        if self.in_blockquote:
            self.blockquote_parts.append(data)

    def get_title(self) -> str:
        title = "".join(self.title_parts).strip()
        title = re.sub(r"\s+", " ", title)
        return title

    def get_byline(self) -> str:
        byline = "".join(self.byline_parts).strip()
        byline = re.sub(r"\s+", " ", byline)
        # Strip leading "By " case-insensitively
        if byline.lower().startswith("by "):
            byline = byline[3:].strip()
        return byline

    def get_quotes(self) -> List[str]:
        return self.quotes[:]

    def get_date(self) -> Optional[str]:
        return self.date_iso


def _parse_interview_html(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = _read_text(path)
    if text is None:
        return None, "Cannot read HTML file"
    try:
        parser = _InterviewHTMLParser()
        parser.feed(text)
        title = parser.get_title()
        date_iso = parser.get_date()
        interviewer = parser.get_byline()
        quotes = parser.get_quotes()
        if not title or not date_iso or not interviewer:
            # Even if quotes could be empty, title/date/interviewer should exist per task
            return None, "Missing required fields in interview HTML"
        return {
            "title": title,
            "date": date_iso,
            "interviewer": interviewer,
            "quotes": quotes,
        }, None
    except Exception as e:
        return None, str(e)


def _compute_track_mentions(tracks: List[Dict[str, str]], posts: List[Dict[str, Any]]) -> Dict[Tuple[str, str, str], int]:
    # Keyed by (title, album_id, duration)
    counts: Dict[Tuple[str, str, str], int] = {}
    for tr in tracks:
        key = (tr.get("title", ""), tr.get("album_id", ""), tr.get("duration", ""))
        counts[key] = 0
    # For each post, count at most once per track
    for post in posts:
        text = str(post.get("text", ""))
        tlow = text.lower()
        seen_for_post: set = set()
        for tr in tracks:
            title = tr.get("title", "")
            key = (tr.get("title", ""), tr.get("album_id", ""), tr.get("duration", ""))
            if key in seen_for_post:
                continue
            if title and title.lower() in tlow:
                counts[key] += 1
                seen_for_post.add(key)
    return counts


def _discover_interview_files(assets_dir: Path) -> List[Path]:
    if not assets_dir.exists():
        return []
    return sorted(p for p in assets_dir.glob("*.html") if p.is_file())


def _build_expected_interview_mentions(quotes: List[str], albums: List[Dict[str, Any]], tracks: List[Dict[str, str]]) -> Dict[str, List[Any]]:
    # Build title lookup maps
    album_title_to_id = {a.get("title", "").lower(): a.get("album_id") for a in albums}
    track_titles = [t.get("title", "") for t in tracks]
    albums_found: List[str] = []
    tracks_found: List[str] = []
    seen_albums = set()
    seen_tracks = set()
    for q in quotes:
        ql = q.lower()
        for atitle_lc, aid in album_title_to_id.items():
            if aid in seen_albums:
                continue
            if atitle_lc and atitle_lc in ql:
                seen_albums.add(aid)
                albums_found.append(aid)
        for t in track_titles:
            tlc = t.lower()
            if t in seen_tracks:
                continue
            if tlc and tlc in ql:
                seen_tracks.add(t)
                tracks_found.append(t)
    return {"albums": albums_found, "tracks": tracks_found}


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "content_json_exists": 0.0,
        "content_artist_fields_correct": 0.0,
        "content_albums_values_correct": 0.0,
        "content_albums_order_correct": 0.0,
        "content_tracks_built_and_mentions_correct": 0.0,
        "content_interviews_parsed_correctly": 0.0,
        "content_interview_mentions_correct": 0.0,
        "mismatches_csv_exists_and_headers": 0.0,
        "mismatches_rows_correct": 0.0,
        "summary_exists": 0.0,
        "summary_counts_correct": 0.0,
    }

    # Load inputs
    artist_yaml_path = workspace / "input" / "data" / "artist.yaml"
    albums_json_path = workspace / "input" / "data" / "albums.json"
    tracks_csv_path = workspace / "input" / "data" / "tracks.csv"
    fan_posts_jsonl_path = workspace / "input" / "data" / "fan_posts.jsonl"
    assets_dir = workspace / "input" / "assets" / "web"

    artist_yaml, _ = _parse_artist_yaml_minimal(artist_yaml_path)
    albums_data, _albums_err = _load_json(albums_json_path)
    if not isinstance(albums_data, list):
        albums_data = None
    tracks_rows, _tracks_err = _load_csv_dicts(tracks_csv_path)
    fan_posts, _fan_err = _load_jsonl(fan_posts_jsonl_path)

    interview_files = _discover_interview_files(assets_dir)
    parsed_interviews: Dict[str, Dict[str, Any]] = {}
    for f in interview_files:
        parsed, err = _parse_interview_html(f)
        if parsed:
            parsed_interviews[parsed["title"]] = parsed

    # Precompute expectations when possible
    expected_track_mentions: Optional[Dict[Tuple[str, str, str], int]] = None
    if tracks_rows is not None and fan_posts is not None:
        expected_track_mentions = _compute_track_mentions(tracks_rows, fan_posts)

    # Compute mismatches
    expected_mismatches: Optional[List[Tuple[str, int, int]]] = None
    if albums_data is not None and tracks_rows is not None:
        by_album_count: Dict[str, int] = {}
        for tr in tracks_rows:
            aid = tr.get("album_id", "")
            by_album_count[aid] = by_album_count.get(aid, 0) + 1
        expected_mismatches = []
        for a in albums_data:
            aid = a.get("album_id")
            expected_count = int(a.get("track_count"))
            actual_count = int(by_album_count.get(aid, 0))
            if expected_count != actual_count:
                expected_mismatches.append((aid, expected_count, actual_count))
        # Stable deterministic order by album_id
        expected_mismatches.sort(key=lambda x: x[0])

    # Discover interviews expectations
    expected_interviews: Optional[Dict[str, Dict[str, Any]]] = None
    if albums_data is not None and tracks_rows is not None and parsed_interviews:
        expected_interviews = {}
        for title, parsed in parsed_interviews.items():
            mentions = _build_expected_interview_mentions(parsed["quotes"], albums_data, tracks_rows)
            expected_interviews[title] = {
                "title": parsed["title"],
                "date": parsed["date"],
                "interviewer": parsed["interviewer"],
                "quotes": parsed["quotes"],
                "mentions": mentions,
            }

    # Load outputs
    content_json_path = workspace / "output" / "content.json"
    content, content_err = _load_json(content_json_path)
    if content is not None and isinstance(content, dict):
        scores["content_json_exists"] = 1.0

    mismatches_csv_path = workspace / "output" / "report" / "mismatches.csv"
    mismatches_rows, mismatches_err = _load_csv_dicts(mismatches_csv_path)
    if mismatches_rows is not None:
        # check headers
        try:
            with mismatches_csv_path.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                headers = next(reader, None)
        except Exception:
            headers = None
        if headers == ["album_id", "expected_track_count", "actual_track_count"]:
            scores["mismatches_csv_exists_and_headers"] = 1.0

    summary_md_path = workspace / "output" / "summary.md"
    summary_text = _read_text(summary_md_path)
    if summary_text is not None:
        scores["summary_exists"] = 1.0

    # Validate content.json artist
    if content is not None and isinstance(content, dict) and artist_yaml is not None:
        artist = content.get("artist")
        if isinstance(artist, dict):
            if "name" in artist and "hometown" in artist:
                if artist.get("name") == artist_yaml.get("name") and artist.get("hometown") == artist_yaml.get("hometown"):
                    scores["content_artist_fields_correct"] = 1.0

    # Validate albums in content.json
    if content is not None and isinstance(content, dict) and albums_data is not None:
        albums_out = content.get("albums")
        if isinstance(albums_out, list):
            # values correct ignoring order
            ok_values = True
            if len(albums_out) != len(albums_data):
                ok_values = False
            else:
                # Map by album_id
                expected_map = {a.get("album_id"): a for a in albums_data}
                seen_ids = set()
                for a in albums_out:
                    if not isinstance(a, dict):
                        ok_values = False
                        break
                    aid = a.get("album_id")
                    if aid not in expected_map:
                        ok_values = False
                        break
                    exp = expected_map[aid]
                    # Check required fields equality
                    for k in ["album_id", "title", "year", "track_count"]:
                        if a.get(k) != exp.get(k):
                            ok_values = False
                            break
                    seen_ids.add(aid)
                    if not ok_values:
                        break
                if ok_values and len(seen_ids) != len(expected_map):
                    ok_values = False
            if ok_values:
                scores["content_albums_values_correct"] = 1.0

            # order correct (must match input order exactly)
            order_ok = False
            try:
                out_ids = [a.get("album_id") for a in albums_out]
                exp_ids = [a.get("album_id") for a in albums_data]
                order_ok = out_ids == exp_ids
            except Exception:
                order_ok = False
            if order_ok:
                scores["content_albums_order_correct"] = 1.0

    # Validate tracks in content.json
    if content is not None and isinstance(content, dict) and tracks_rows is not None and expected_track_mentions is not None:
        tracks_out = content.get("tracks")
        if isinstance(tracks_out, list):
            # Build expected set and mapping
            expected_keys = {(tr["title"], tr["album_id"], tr["duration"]) for tr in tracks_rows}
            out_keys = set()
            counts_ok = True
            for t in tracks_out:
                if not isinstance(t, dict):
                    counts_ok = False
                    break
                title = t.get("title")
                album_id = t.get("album_id")
                duration = t.get("duration")
                key = (title, album_id, duration)
                out_keys.add(key)
                if key not in expected_track_mentions:
                    counts_ok = False
                    break
                mentioned = t.get("mentioned_in_fan_posts")
                # Must be integer and match expected
                if not isinstance(mentioned, int):
                    counts_ok = False
                    break
                if mentioned != expected_track_mentions[key]:
                    counts_ok = False
                    break
            if counts_ok and len(out_keys) == len(expected_keys) and out_keys == expected_keys:
                scores["content_tracks_built_and_mentions_correct"] = 1.0

    # Validate interviews parsed correctly (fields except mentions)
    if content is not None and isinstance(content, dict) and expected_interviews is not None:
        interviews_out = content.get("interviews")
        if isinstance(interviews_out, list):
            ok_fields = True
            # Number equal
            if len(interviews_out) != len(expected_interviews):
                ok_fields = False
            else:
                # Map by title (unique per input)
                out_map: Dict[str, Dict[str, Any]] = {}
                for it in interviews_out:
                    if not isinstance(it, dict):
                        ok_fields = False
                        break
                    title = it.get("title")
                    if not isinstance(title, str):
                        ok_fields = False
                        break
                    out_map[title] = it
                if ok_fields:
                    for title, exp in expected_interviews.items():
                        if title not in out_map:
                            ok_fields = False
                            break
                        got = out_map[title]
                        # Compare date, interviewer, quotes
                        if got.get("date") != exp.get("date"):
                            ok_fields = False
                            break
                        if got.get("interviewer") != exp.get("interviewer"):
                            ok_fields = False
                            break
                        got_quotes = got.get("quotes")
                        if not isinstance(got_quotes, list):
                            ok_fields = False
                            break
                        # Quotes must match exactly in content and order
                        if got_quotes != exp.get("quotes"):
                            ok_fields = False
                            break
            if ok_fields:
                scores["content_interviews_parsed_correctly"] = 1.0

            # Mentions check
            mentions_ok = True
            if ok_fields:
                for title, exp in expected_interviews.items():
                    got = None
                    for it in interviews_out:
                        if it.get("title") == title:
                            got = it
                            break
                    if got is None:
                        mentions_ok = False
                        break
                    m = got.get("mentions")
                    if not isinstance(m, dict):
                        mentions_ok = False
                        break
                    albums_list = m.get("albums")
                    tracks_list = m.get("tracks")
                    if not isinstance(albums_list, list) or not isinstance(tracks_list, list):
                        mentions_ok = False
                        break
                    # Compare as sets
                    if set(albums_list) != set(exp["mentions"]["albums"]):
                        mentions_ok = False
                        break
                    if set(tracks_list) != set(exp["mentions"]["tracks"]):
                        mentions_ok = False
                        break
            if mentions_ok and ok_fields:
                scores["content_interview_mentions_correct"] = 1.0

    # Validate mismatches rows
    if mismatches_rows is not None and expected_mismatches is not None:
        # Normalize rows
        got = []
        for row in mismatches_rows:
            try:
                aid = row["album_id"]
                etc = int(row["expected_track_count"])
                atc = int(row["actual_track_count"])
                got.append((aid, etc, atc))
            except Exception:
                got = None
                break
        if got is not None:
            got_sorted = sorted(got, key=lambda x: x[0])
            if got_sorted == expected_mismatches:
                scores["mismatches_rows_correct"] = 1.0

    # Validate summary counts
    if summary_text is not None:
        # Compute expected counts if possible
        total_albums = len(albums_data) if albums_data is not None else None
        total_tracks = len(tracks_rows) if tracks_rows is not None else None
        total_interviews = len(interview_files) if interview_files is not None else None
        mismatches_count = len(expected_mismatches) if expected_mismatches is not None else None

        def _contains_number_near_keyword(text: str, keyword: str, number: int) -> bool:
            # Search lines with keyword and check if number appears as whole word on same line
            for line in text.splitlines():
                if keyword.lower() in line.lower():
                    if re.search(rf"\b{number}\b", line):
                        return True
            return False

        checks = []
        if total_albums is not None:
            checks.append(_contains_number_near_keyword(summary_text, "album", total_albums))
        if total_tracks is not None:
            checks.append(_contains_number_near_keyword(summary_text, "track", total_tracks))
        if total_interviews is not None:
            checks.append(_contains_number_near_keyword(summary_text, "interview", total_interviews))
        if mismatches_count is not None:
            checks.append(_contains_number_near_keyword(summary_text, "mismatch", mismatches_count))

        if checks and all(checks):
            scores["summary_counts_correct"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()