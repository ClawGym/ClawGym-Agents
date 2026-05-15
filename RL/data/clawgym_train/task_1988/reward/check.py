import sys
import json
import csv
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _to_int_safe(val: str) -> Optional[int]:
    try:
        return int(val.strip())
    except Exception:
        return None


class BlogPlaylistParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records: List[Dict[str, object]] = []
        self._in_section = False
        self._current_section_list_attr: Optional[str] = None
        self._capture_h2 = False
        self._current_section_h2_text: Optional[str] = None

        self._in_li_track = False
        self._current_track: Dict[str, object] = {}
        self._capture_popularity = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = {k: v for k, v in attrs}
        if tag.lower() == "section":
            self._in_section = True
            self._current_section_list_attr = attrs_dict.get("data-list")
            self._current_section_h2_text = None
        elif self._in_section and tag.lower() == "h2":
            self._capture_h2 = True
            self._current_section_h2_text = ""
        elif self._in_section and tag.lower() == "li":
            class_attr = attrs_dict.get("class", "")
            classes = class_attr.split()
            if "track" in classes:
                self._in_li_track = True
                self._current_track = {}
                self._current_track["artist"] = attrs_dict.get("data-artist", "").strip()
                self._current_track["title"] = attrs_dict.get("data-title", "").strip()
                year = attrs_dict.get("data-year", "").strip()
                self._current_track["year"] = _to_int_safe(year)
        elif self._in_li_track and tag.lower() == "span":
            class_attr = attrs_dict.get("class", "")
            classes = class_attr.split()
            if "popularity" in classes:
                self._capture_popularity = True

    def handle_endtag(self, tag):
        if tag.lower() == "section":
            self._in_section = False
            self._current_section_list_attr = None
            self._current_section_h2_text = None
        elif tag.lower() == "h2":
            self._capture_h2 = False
        elif tag.lower() == "li":
            if self._in_li_track:
                if (
                    isinstance(self._current_track.get("title"), str)
                    and isinstance(self._current_track.get("artist"), str)
                    and isinstance(self._current_track.get("year"), int)
                    and isinstance(self._current_track.get("blog_popularity"), int)
                ):
                    playlist_name = self._current_section_list_attr
                    if not playlist_name or playlist_name.strip() == "":
                        playlist_name = (self._current_section_h2_text or "").strip()
                    self._current_track["playlist_name"] = playlist_name
                    self.records.append(self._current_track)
                self._in_li_track = False
                self._current_track = {}
                self._capture_popularity = False

    def handle_data(self, data):
        if self._capture_h2 and self._in_section:
            if self._current_section_h2_text is None:
                self._current_section_h2_text = ""
            self._current_section_h2_text += data
        if self._capture_popularity and self._in_li_track:
            m = re.search(r"Popularity:\s*(\d+)", data)
            if m:
                val = _to_int_safe(m.group(1))
                if val is not None:
                    self._current_track["blog_popularity"] = val


def _parse_blog_playlists_html(path: Path) -> Optional[List[Dict[str, object]]]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        parser = BlogPlaylistParser()
        parser.feed(text)
        cleaned = []
        for r in parser.records:
            if (
                isinstance(r.get("title"), str)
                and isinstance(r.get("artist"), str)
                and isinstance(r.get("year"), int)
                and isinstance(r.get("blog_popularity"), int)
            ):
                pn = r.get("playlist_name")
                if pn is None:
                    pn = ""
                cleaned.append(
                    {
                        "title": r["title"],
                        "artist": r["artist"],
                        "year": r["year"],
                        "blog_popularity": r["blog_popularity"],
                        "playlist_name": pn,
                    }
                )
        return cleaned
    except Exception:
        return None


def _load_library_csv_typed(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    typed_rows: List[Dict[str, object]] = []
    try:
        for r in rows:
            title = (r.get("title") or "").strip()
            artist = (r.get("artist") or "").strip()
            year = _to_int_safe(r.get("year", ""))
            play_count = _to_int_safe(r.get("play_count", ""))
            rating = _to_int_safe(r.get("rating", ""))
            if (
                title != ""
                and artist != ""
                and isinstance(year, int)
                and isinstance(play_count, int)
                and isinstance(rating, int)
            ):
                typed_rows.append(
                    {
                        "title": title,
                        "artist": artist,
                        "year": year,
                        "play_count": play_count,
                        "rating": rating,
                    }
                )
            else:
                return None
        return typed_rows
    except Exception:
        return None


def _normalize_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()


def _join_and_filter(html_recs: List[Dict[str, object]], lib_recs: List[Dict[str, object]]) -> List[Dict[str, object]]:
    lib_index: Dict[Tuple[str, str], Dict[str, object]] = {}
    for r in lib_recs:
        key = (_normalize_key(r["title"]), _normalize_key(r["artist"]))
        lib_index[key] = r
    out: List[Dict[str, object]] = []
    for h in html_recs:
        key = (_normalize_key(h["title"]), _normalize_key(h["artist"]))
        lib_match = lib_index.get(key)
        if lib_match:
            artist_norm = _normalize_key(h["artist"])
            if artist_norm in (_normalize_key("Cherie Currie"), _normalize_key("The Runaways")):
                rec = {
                    "title": h["title"],
                    "artist": h["artist"],
                    "year": int(h["year"]),
                    "blog_popularity": int(h["blog_popularity"]),
                    "play_count": int(lib_match["play_count"]),
                    "rating": int(lib_match["rating"]),
                    "playlist_name": h.get("playlist_name", ""),
                }
                rec["score"] = rec["blog_popularity"] + rec["play_count"] + rec["rating"]
                out.append(rec)
    return out


def _sort_records(recs: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        recs,
        key=lambda r: (-int(r["score"]), -int(r["blog_popularity"]), str(r["title"]).lower()),
    )


def _parse_ranked_csv(path: Path) -> Optional[List[Dict[str, object]]]:
    rows = _load_csv_dicts(path)
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            header_line = f.readline().rstrip("\n\r")
    except Exception:
        return None
    expected_header = "title,artist,year,blog_popularity,play_count,rating,score,playlist_name"
    if header_line != expected_header:
        return None
    typed = []
    try:
        for r in rows:
            title = (r.get("title") or "").strip()
            artist = (r.get("artist") or "").strip()
            year = _to_int_safe(r.get("year", ""))
            blog_popularity = _to_int_safe(r.get("blog_popularity", ""))
            play_count = _to_int_safe(r.get("play_count", ""))
            rating = _to_int_safe(r.get("rating", ""))
            score = _to_int_safe(r.get("score", ""))
            playlist_name = (r.get("playlist_name") or "")
            if (
                title != ""
                and artist != ""
                and isinstance(year, int)
                and isinstance(blog_popularity, int)
                and isinstance(play_count, int)
                and isinstance(rating, int)
                and isinstance(score, int)
            ):
                typed.append(
                    {
                        "title": title,
                        "artist": artist,
                        "year": year,
                        "blog_popularity": blog_popularity,
                        "play_count": play_count,
                        "rating": rating,
                        "score": score,
                        "playlist_name": playlist_name,
                    }
                )
            else:
                return None
        return typed
    except Exception:
        return None


def _extract_bullet_lines(text: str) -> List[str]:
    lines = text.splitlines()
    bullets = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^[-*•]\s+", stripped):
            bullets.append(stripped)
    return bullets


def _normalize_dash(s: str) -> str:
    s = re.sub(r"\s-\s", " — ", s)
    s = re.sub(r"\s–\s", " — ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _word_count(s: str) -> int:
    tokens = re.findall(r"\b\w+\b", s, flags=re.UNICODE)
    return len(tokens)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "ranked_csv_exists_and_header": 0.0,
        "ranked_csv_rows_correct": 0.0,
        "ranked_csv_sorted_correctly": 0.0,
        "email_en_subject_and_placeholders": 0.0,
        "email_en_bullets_top5": 0.0,
        "email_en_word_count_range": 0.0,
        "email_es_placeholders_and_bullets": 0.0,
        "email_es_length_similarity": 0.0,
    }

    blog_html_path = workspace / "input" / "blog_playlists.html"
    library_csv_path = workspace / "input" / "library.csv"
    draft_email_path = workspace / "input" / "draft_email.txt"

    html_records = _parse_blog_playlists_html(blog_html_path)
    lib_records = _load_library_csv_typed(library_csv_path)

    if html_records is None or lib_records is None:
        expected_records_sorted: List[Dict[str, object]] = []
    else:
        matched = _join_and_filter(html_records, lib_records)
        expected_records_sorted = _sort_records(matched)

    expected_titles_order = [r["title"] for r in expected_records_sorted]
    expected_set = {(r["title"], r["artist"]): r for r in expected_records_sorted}
    expected_top5 = expected_records_sorted[:5]
    expected_bullet_lines = [f"{r['title']} ({r['year']}) — {r['artist']}" for r in expected_top5]

    ranked_csv_path = workspace / "out" / "runaways_ranked.csv"
    parsed_ranked = None
    if ranked_csv_path.exists():
        parsed_ranked = _parse_ranked_csv(ranked_csv_path)

    if parsed_ranked is not None:
        scores["ranked_csv_exists_and_header"] = 1.0

    if parsed_ranked is not None and expected_records_sorted:
        actual_map = {(r["title"], r["artist"]): r for r in parsed_ranked}
        expected_keys = set(expected_set.keys())
        actual_keys = set(actual_map.keys())
        if actual_keys == expected_keys and len(parsed_ranked) == len(expected_records_sorted):
            fields_ok = True
            for key, ex in expected_set.items():
                ac = actual_map.get(key)
                if ac is None:
                    fields_ok = False
                    break
                if not (
                    ac.get("year") == int(ex["year"])
                    and ac.get("blog_popularity") == int(ex["blog_popularity"])
                    and ac.get("play_count") == int(ex["play_count"])
                    and ac.get("rating") == int(ex["rating"])
                    and ac.get("score") == int(ex["score"])
                    and (ac.get("playlist_name") or "") == (ex.get("playlist_name") or "")
                ):
                    fields_ok = False
                    break
            if fields_ok:
                scores["ranked_csv_rows_correct"] = 1.0

    if parsed_ranked is not None and expected_records_sorted:
        actual_titles_order = [r["title"] for r in parsed_ranked]
        if actual_titles_order == expected_titles_order:
            scores["ranked_csv_sorted_correctly"] = 1.0

    en_path = workspace / "out" / "email_invite_en.txt"
    en_text = _read_text(en_path) if en_path.exists() else None
    if en_text:
        lines = en_text.splitlines()
        first_line = lines[0].strip() if lines else ""
        expected_subject = "Subject: Cherie Currie & Runaways Listening Night — Top Picks"
        placeholders_present = all(ph in en_text for ph in ["[DATE]", "[TIME]", "[ADDRESS]"])
        later_hint = any(
            phrase in en_text.lower()
            for phrase in ["later", "tbd", "to be confirmed", "to be determined", "tba"]
        )
        if first_line == expected_subject and placeholders_present and later_hint:
            scores["email_en_subject_and_placeholders"] = 1.0

        bullets = _extract_bullet_lines(en_text)
        normalized_bullets = [_normalize_dash(re.sub(r"^[-*•]\s+", "", b).strip()) for b in bullets]
        expected_norm = [_normalize_dash(b) for b in expected_bullet_lines]
        if len(normalized_bullets) >= 5:
            top5_bullets = normalized_bullets[:5]
            if top5_bullets == expected_norm:
                scores["email_en_bullets_top5"] = 1.0

        body_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
        wc = _word_count(body_text)
        if 140 <= wc <= 220:
            scores["email_en_word_count_range"] = 1.0

    es_path = workspace / "out" / "email_invite_es.txt"
    es_text = _read_text(es_path) if es_path.exists() else None
    if es_text and en_text:
        es_placeholders_present = all(ph in es_text for ph in ["[DATE]", "[TIME]", "[ADDRESS]"])
        es_bullets = _extract_bullet_lines(es_text)
        es_norm_bullets = [_normalize_dash(re.sub(r"^[-*•]\s+", "", b).strip()) for b in es_bullets]
        expected_norm = [_normalize_dash(b) for b in expected_bullet_lines]
        bullets_ok = len(es_norm_bullets) >= 5 and es_norm_bullets[:5] == expected_norm
        if es_placeholders_present and bullets_ok:
            scores["email_es_placeholders_and_bullets"] = 1.0

        es_lines = es_text.splitlines()
        es_body = "\n".join(es_lines[1:]) if len(es_lines) > 1 else es_text
        wc_en = _word_count("\n".join(en_text.splitlines()[1:]) if en_text else "")
        wc_es = _word_count(es_body)
        if wc_en > 0:
            ratio = wc_es / wc_en
            if 120 <= wc_es <= 240 and 0.8 <= ratio <= 1.25:
                scores["email_es_length_similarity"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()