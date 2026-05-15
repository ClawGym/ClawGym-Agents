import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text)
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _safe_read_tsv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return [dict(row) for row in reader]
    except Exception:
        return None


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _extract_section(md_text: str, header_name: str) -> Optional[str]:
    # Find a section by header name (case-insensitive), return content until next header or end
    lines = md_text.splitlines()
    header_indices = []
    pattern = re.compile(r"^\s{0,3}#*\s*" + re.escape(header_name) + r"\s*$", re.IGNORECASE)
    header_line_idx = None
    for i, line in enumerate(lines):
        if pattern.match(line):
            header_line_idx = i
            break
    if header_line_idx is None:
        return None
    # Find next header (a line that looks like a markdown header or the next known section headers)
    next_idx = len(lines)
    header_like = re.compile(r"^\s{0,3}#\s|\s{0,3}##\s|\s{0,3}###\s", re.IGNORECASE)
    for j in range(header_line_idx + 1, len(lines)):
        if header_like.match(lines[j]):
            next_idx = j
            break
    content = "\n".join(lines[header_line_idx + 1:next_idx]).strip()
    return content


def _compute_expected(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[Dict[str, str]]], Optional[dict], List[str], List[str], List[str]]:
    """
    Returns:
      - artists_rows (list of dicts) from artists.csv or None
      - venues_rows (list of dicts) from venues.tsv or None
      - playlists_json (dict) from playlists.json or None
      - uk_artist_names (list of names)
      - all_artist_names_in_artists_csv (list)
      - excluded_names (list) computed from venues/playlists vs artists.csv UK filter
    """
    artists_path = workspace / "input" / "artists.csv"
    venues_path = workspace / "input" / "venues.tsv"
    playlists_path = workspace / "input" / "playlists.json"

    artists_rows = _safe_read_csv(artists_path)
    venues_rows = _safe_read_tsv(venues_path)
    playlists_json = _safe_load_json(playlists_path)

    uk_artist_names: List[str] = []
    all_artist_names_in_artists_csv: List[str] = []

    if artists_rows is not None:
        for row in artists_rows:
            name = (row.get("name") or "").strip()
            country = (row.get("country") or "").strip()
            if name:
                all_artist_names_in_artists_csv.append(name)
            if country == "UK" and name:
                uk_artist_names.append(name)

    names_in_files = set()
    if venues_rows is not None:
        for row in venues_rows:
            n = (row.get("artist_name") or "").strip()
            if n:
                names_in_files.add(n)
    if playlists_json is not None and isinstance(playlists_json, dict):
        playlists = playlists_json.get("playlists", [])
        if isinstance(playlists, list):
            for pl in playlists:
                tracks = pl.get("tracks", []) if isinstance(pl, dict) else []
                if isinstance(tracks, list):
                    for t in tracks:
                        n = (t.get("artist_name") or "").strip()
                        if n:
                            names_in_files.add(n)

    excluded_names = []
    all_artists_set = set(all_artist_names_in_artists_csv)
    uk_set = set(uk_artist_names)
    for n in sorted(names_in_files):
        if (n not in all_artists_set) or (n in all_artists_set and n not in uk_set):
            excluded_names.append(n)

    return artists_rows, venues_rows, playlists_json, uk_artist_names, all_artist_names_in_artists_csv, excluded_names


def _build_expected_shortlist(artists_rows: List[Dict[str, str]],
                              venues_rows: List[Dict[str, str]],
                              playlists_json: dict) -> List[Dict[str, str]]:
    # Build expected shortlist items for UK artists with computed metrics and sort
    uk_artists = []
    for row in artists_rows:
        if (row.get("country") or "").strip() == "UK":
            uk_artists.append(row)

    uk_names = { (r.get("name") or "").strip() for r in uk_artists }

    gigs_counts = {name: 0 for name in uk_names}
    if venues_rows is not None:
        for v in venues_rows:
            try:
                country = (v.get("country") or "").strip()
                name = (v.get("artist_name") or "").strip()
                date_str = (v.get("date") or "").strip()
                d = _parse_date(date_str)
                if country == "UK" and name in uk_names and d is not None and d.year == 2024:
                    gigs_counts[name] = gigs_counts.get(name, 0) + 1
            except Exception:
                # Malformed row: treat as non-contributing
                continue

    support_counts = {name: 0 for name in uk_names}
    valid_tags = {"UK_radio_play", "local_press_feature"}
    if playlists_json is not None and isinstance(playlists_json, dict):
        pls = playlists_json.get("playlists", [])
        if isinstance(pls, list):
            for pl in pls:
                tracks = pl.get("tracks", []) if isinstance(pl, dict) else []
                if isinstance(tracks, list):
                    for t in tracks:
                        try:
                            name = (t.get("artist_name") or "").strip()
                            tag = (t.get("tag") or "").strip()
                            if name in uk_names and tag in valid_tags:
                                support_counts[name] = support_counts.get(name, 0) + 1
                        except Exception:
                            continue

    expected_items = []
    for r in uk_artists:
        name = (r.get("name") or "").strip()
        city = (r.get("city") or "").strip()
        genre = (r.get("genre") or "").strip()
        email = (r.get("email") or "").strip()
        instagram = (r.get("instagram") or "").strip()
        last_release_date_str = (r.get("last_release_date") or "").strip()
        parsed_last = _parse_date(last_release_date_str)
        # Treat missing values as zero where applicable: for dates, use very old date for sorting
        sort_date = parsed_last if parsed_last is not None else datetime(1900, 1, 1)
        gigs = gigs_counts.get(name, 0)
        support = support_counts.get(name, 0)
        expected_items.append({
            "name": name,
            "city": city,
            "genre": genre,
            "last_release_date": last_release_date_str,
            "gigs_2024_uk": gigs,
            "uk_support_mentions": support,
            "email": email,
            "instagram": instagram,
            "_sort_date": sort_date,
        })

    # Sort: gigs desc, support desc, last_release_date desc (more recent first), name asc
    expected_items.sort(key=lambda x: (
        -int(x["gigs_2024_uk"]),
        -int(x["uk_support_mentions"]),
        x["_sort_date"] if isinstance(x["_sort_date"], datetime) else datetime(1900, 1, 1)
    ), reverse=False)
    # The above sorts ascending by tuple; adjust to meet required ordering:
    # We'll instead create explicit sort with reverse where needed
    expected_items.sort(key=lambda x: (x["name"]))
    expected_items.sort(key=lambda x: x["_sort_date"], reverse=True)
    expected_items.sort(key=lambda x: int(x["uk_support_mentions"]), reverse=True)
    expected_items.sort(key=lambda x: int(x["gigs_2024_uk"]), reverse=True)

    # Remove helper key
    for item in expected_items:
        item.pop("_sort_date", None)

    return expected_items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "shortlist_file_exists_and_columns": 0.0,
        "shortlist_row_count_and_ranks": 0.0,
        "shortlist_top5_correct_order_and_metrics": 0.0,
        "shortlist_only_uk_artists": 0.0,
        "meeting_notes_exists": 0.0,
        "meeting_notes_has_required_sections_and_summary_criteria": 0.0,
        "meeting_notes_top_picks_cover_metrics_and_contacts": 0.0,
        "meeting_notes_action_items_per_top_artist": 0.0,
        "meeting_notes_data_checks_listed": 0.0,
    }

    # Load inputs to compute expectations
    artists_rows, venues_rows, playlists_json, uk_artist_names, all_artist_names, excluded_names = _compute_expected(workspace)

    # If any input file missing or malformed, expected computation may fail; still grade based on available info
    expected_shortlist = []
    if artists_rows is not None and venues_rows is not None and playlists_json is not None:
        expected_shortlist = _build_expected_shortlist(artists_rows, venues_rows, playlists_json)

    # Compute expected top-5 count
    expected_top_count = min(5, len(expected_shortlist)) if expected_shortlist else 0
    expected_top_names = [item["name"] for item in expected_shortlist[:expected_top_count]]

    # Paths to deliverables
    shortlist_path = workspace / "output" / "shortlist.csv"
    notes_path = workspace / "output" / "meeting_notes.md"

    # 1) shortlist_file_exists_and_columns
    shortlist_rows = None
    if shortlist_path.exists():
        try:
            with shortlist_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                cols = reader.fieldnames or []
                expected_cols = ["rank", "name", "city", "genre", "last_release_date", "gigs_2024_uk", "uk_support_mentions", "email", "instagram"]
                if cols == expected_cols:
                    shortlist_rows = [dict(row) for row in reader]
                    scores["shortlist_file_exists_and_columns"] = 1.0
                else:
                    # Wrong columns or order
                    shortlist_rows = [dict(row) for row in reader]  # still parse for other checks
        except Exception:
            shortlist_rows = None
    else:
        shortlist_rows = None

    # 2) shortlist_row_count_and_ranks
    if shortlist_rows is not None and expected_top_count > 0:
        row_count_ok = len(shortlist_rows) >= expected_top_count and (artists_rows is None or len(shortlist_rows) <= sum(1 for r in artists_rows if (r.get("country") or "").strip() == "UK"))
        # Check first expected_top_count ranks are 1..N
        ranks_ok = True
        for i in range(expected_top_count):
            try:
                r = int(str(shortlist_rows[i].get("rank", "")).strip())
                if r != i + 1:
                    ranks_ok = False
                    break
            except Exception:
                ranks_ok = False
                break
        if row_count_ok and ranks_ok:
            scores["shortlist_row_count_and_ranks"] = 1.0

    # 3) shortlist_top5_correct_order_and_metrics
    if shortlist_rows is not None and expected_top_count > 0 and expected_shortlist:
        correct = True
        for i in range(expected_top_count):
            out_row = shortlist_rows[i]
            exp = expected_shortlist[i]
            # Name order
            if (out_row.get("name") or "").strip() != exp["name"]:
                correct = False
                break
            # City, genre, last_release_date, metrics, email, instagram
            if (out_row.get("city") or "").strip() != exp["city"]:
                correct = False
                break
            if (out_row.get("genre") or "").strip() != exp["genre"]:
                correct = False
                break
            if (out_row.get("last_release_date") or "").strip() != exp["last_release_date"]:
                correct = False
                break
            try:
                if int(str(out_row.get("gigs_2024_uk", "")).strip()) != int(exp["gigs_2024_uk"]):
                    correct = False
                    break
            except Exception:
                correct = False
                break
            try:
                if int(str(out_row.get("uk_support_mentions", "")).strip()) != int(exp["uk_support_mentions"]):
                    correct = False
                    break
            except Exception:
                correct = False
                break
            if (out_row.get("email") or "").strip() != exp["email"]:
                correct = False
                break
            if (out_row.get("instagram") or "").strip() != exp["instagram"]:
                correct = False
                break
            # Rank
            try:
                if int(str(out_row.get("rank", "")).strip()) != i + 1:
                    correct = False
                    break
            except Exception:
                correct = False
                break
        if correct:
            scores["shortlist_top5_correct_order_and_metrics"] = 1.0

    # 4) shortlist_only_uk_artists
    if shortlist_rows is not None and artists_rows is not None:
        uk_set = set(n for n in uk_artist_names)
        all_set = set(n for n in all_artist_names)
        only_uk = True
        for row in shortlist_rows:
            nm = (row.get("name") or "").strip()
            if nm not in uk_set or nm not in all_set:
                only_uk = False
                break
        if only_uk:
            scores["shortlist_only_uk_artists"] = 1.0

    # 5) meeting_notes_exists
    md_text = None
    if notes_path.exists():
        md_text = _safe_read_text(notes_path)
        if isinstance(md_text, str) and len(md_text.strip()) > 0:
            scores["meeting_notes_exists"] = 1.0

    # 6) meeting_notes_has_required_sections_and_summary_criteria
    if md_text:
        top_picks_section = _extract_section(md_text, "Top Picks")
        action_items_section = _extract_section(md_text, "Action Items")
        data_checks_section = _extract_section(md_text, "Data Checks")
        # Summary is text before "Top Picks"
        idx = None
        lines = md_text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^\s{0,3}#*\s*Top Picks\s*$", line, flags=re.IGNORECASE):
                idx = i
                break
        summary_text = "\n".join(lines[:idx]).strip() if idx is not None else md_text.strip()

        sections_ok = top_picks_section is not None and action_items_section is not None and data_checks_section is not None

        # Summary criteria keywords: "UK", "2024", "gigs" (or "gig"), "support" (or "radio" or "press"), and "last release date" (or "last_release_date")
        st = summary_text.lower()
        has_uk = "uk" in st
        has_2024 = "2024" in st
        has_gigs = ("gigs" in st) or ("gig" in st)
        has_support = ("support" in st) or ("radio" in st) or ("press" in st)
        has_last_release = ("last release date" in st) or ("last_release_date" in st) or ("release date" in st)

        if sections_ok and has_uk and has_2024 and has_gigs and has_support and has_last_release:
            scores["meeting_notes_has_required_sections_and_summary_criteria"] = 1.0

        # 7) meeting_notes_top_picks_cover_metrics_and_contacts
        if top_picks_section is not None and expected_top_names:
            ok_all = True
            lines_tp = [ln.strip() for ln in top_picks_section.splitlines() if ln.strip()]
            for item in (expected_shortlist[:len(expected_top_names)] if expected_shortlist else []):
                name = item["name"]
                gigs = str(item["gigs_2024_uk"])
                support = str(item["uk_support_mentions"])
                email = item["email"]
                insta = item["instagram"]
                # find a line containing the artist name
                found_line = None
                for ln in lines_tp:
                    if name in ln:
                        found_line = ln
                        # Require both metrics present and either email or instagram
                        has_gigs = gigs in ln
                        has_support = support in ln
                        has_contact = (email in ln) or (insta in ln)
                        if has_gigs and has_support and has_contact:
                            break
                        else:
                            found_line = None
                if found_line is None:
                    ok_all = False
                    break
            if ok_all:
                scores["meeting_notes_top_picks_cover_metrics_and_contacts"] = 1.0

        # 8) meeting_notes_action_items_per_top_artist
        if action_items_section is not None and expected_top_names:
            action_lines = [ln.strip() for ln in action_items_section.splitlines() if ln.strip()]
            per_artist_ok = True
            for name in expected_top_names:
                found = False
                for ln in action_lines:
                    if name in ln:
                        found = True
                        break
                if not found:
                    per_artist_ok = False
                    break
            if per_artist_ok:
                scores["meeting_notes_action_items_per_top_artist"] = 1.0

        # 9) meeting_notes_data_checks_listed
        if data_checks_section is not None:
            dc_text = data_checks_section
            dc_ok = True
            for n in excluded_names:
                if n not in dc_text:
                    dc_ok = False
                    break
            if dc_ok:
                scores["meeting_notes_data_checks_listed"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()