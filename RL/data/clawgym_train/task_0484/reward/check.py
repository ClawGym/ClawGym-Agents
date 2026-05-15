import json
import sys
import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Dict, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _compute_sha256(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _parse_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
        if not rows:
            return None, None
        header = rows[0]
        data_rows = []
        for r in rows[1:]:
            if len(r) != len(header):
                return header, None
            data_rows.append({header[i]: r[i] for i in range(len(header))})
        return header, data_rows
    except Exception:
        return None, None


def _is_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    text = s.strip()
    if text.endswith("Z"):
        text_try = text[:-1] + "+00:00"
    else:
        text_try = text
    try:
        datetime.fromisoformat(text_try)
        return True
    except Exception:
        return False


def _load_client_profile(workspace: Path) -> Optional[dict]:
    profile_path = workspace / "input" / "client_profile.json"
    return _safe_load_json(profile_path)


def _tconst_valid(s: str) -> bool:
    return bool(re.fullmatch(r"tt\d+", s or ""))


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _contains_case_insensitive(text: str, phrase: str) -> bool:
    return phrase.lower() in text.lower()


def _heading_present(text: str, heading: str) -> bool:
    return _contains_case_insensitive(text, heading)


def _count_bullets(text: str) -> int:
    count = 0
    for line in text.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("- ") or line_stripped.startswith("* ") or re.match(r"^\d+\.\s", line_stripped):
            count += 1
    return count


def _check_missing_genres_noted(text: str, missing_genres: List[str]) -> bool:
    low = text.lower()
    for g in missing_genres:
        g_low = g.lower()
        idx = low.find(g_low)
        if idx == -1:
            return False
        start = max(0, idx - 80)
        end = min(len(low), idx + 80)
        window = low[start:end]
        if not any(kw in window for kw in ["zero", "no ", "none"]):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "raw_imdb_files_present": 0.0,
        "download_manifest_valid": 0.0,
        "top_series_csv_valid_structure": 0.0,
        "top_series_genre_row_limit": 0.0,
        "genre_summary_csv_valid_structure": 0.0,
        "status_update_sections_and_references": 0.0,
        "status_update_missing_genres_noted": 0.0,
        "email_draft_content_requirements": 0.0,
    }

    profile = _load_client_profile(workspace)
    if not profile or "priority_genres" not in profile:
        priority_genres = []
        client_name = ""
        contact_name = ""
        target_age_range = ""
        target_markets = []
    else:
        priority_genres = list(profile.get("priority_genres", []))
        client_name = str(profile.get("client_name", ""))
        contact_name = str(profile.get("contact_name", ""))
        target_age_range = str(profile.get("target_age_range", ""))
        target_markets = list(profile.get("target_markets", []))

    basics_path = workspace / "data" / "raw" / "title.basics.tsv.gz"
    ratings_path = workspace / "data" / "raw" / "title.ratings.tsv.gz"
    if basics_path.exists() and ratings_path.exists():
        scores["raw_imdb_files_present"] = 1.0

    manifest_path = workspace / "output" / "download_manifest.json"
    manifest = _safe_load_json(manifest_path)
    manifest_ok = False
    if manifest and isinstance(manifest, dict) and manifest.get("source_label") == "IMDb official datasets":
        files = manifest.get("files")
        if isinstance(files, list) and len(files) == 2:
            file_map = {}
            for entry in files:
                if isinstance(entry, dict) and "file_name" in entry:
                    file_map[entry["file_name"]] = entry
            if "title.basics.tsv.gz" in file_map and "title.ratings.tsv.gz" in file_map:
                per_file_ok = True
                for fname in ["title.basics.tsv.gz", "title.ratings.tsv.gz"]:
                    e = file_map[fname]
                    size_bytes = e.get("size_bytes")
                    sha256 = e.get("sha256")
                    downloaded_at = e.get("downloaded_at")
                    if not isinstance(size_bytes, int) or size_bytes < 0:
                        per_file_ok = False
                        break
                    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256 or ""):
                        per_file_ok = False
                        break
                    if not isinstance(downloaded_at, str) or not _is_iso8601(downloaded_at):
                        per_file_ok = False
                        break
                    fpath = workspace / "data" / "raw" / fname
                    if not fpath.exists():
                        per_file_ok = False
                        break
                    actual_size = fpath.stat().st_size
                    actual_sha = _compute_sha256(fpath)
                    if actual_sha is None or actual_size != size_bytes or actual_sha.lower() != sha256.lower():
                        per_file_ok = False
                        break
                if per_file_ok:
                    manifest_ok = True
    scores["download_manifest_valid"] = 1.0 if manifest_ok else 0.0

    top_csv_path = workspace / "output" / "priority_genre_top_series.csv"
    header, rows = _parse_csv(top_csv_path) if top_csv_path.exists() else (None, None)
    expected_top_header = ["genre", "tconst", "primaryTitle", "startYear", "endYear", "genres", "averageRating", "numVotes"]
    top_struct_ok = False
    top_limit_ok = False
    if header == expected_top_header and isinstance(rows, list):
        per_row_ok = True
        per_genre_counts = {}
        seen_pairs = set()
        for r in rows:
            genre = r.get("genre", "")
            tconst = r.get("tconst", "")
            primary_title = r.get("primaryTitle", "")
            start_year = r.get("startYear", "")
            average_rating = r.get("averageRating", "")
            num_votes = r.get("numVotes", "")
            if genre not in priority_genres:
                per_row_ok = False
                break
            if not _tconst_valid(tconst):
                per_row_ok = False
                break
            if not isinstance(primary_title, str) or not primary_title.strip():
                per_row_ok = False
                break
            sy = _to_int(start_year)
            if sy is None or sy < 2019 or sy > 2024:
                per_row_ok = False
                break
            ar = _to_float(average_rating)
            if ar is None:
                per_row_ok = False
                break
            nv = _to_int(num_votes)
            if nv is None or nv < 5000:
                per_row_ok = False
                break
            per_genre_counts[genre] = per_genre_counts.get(genre, 0) + 1
            key = (genre, tconst)
            if key in seen_pairs:
                per_row_ok = False
                break
            seen_pairs.add(key)
        if per_row_ok:
            top_struct_ok = True
            if all(count <= 5 for count in per_genre_counts.values()):
                top_limit_ok = True
    scores["top_series_csv_valid_structure"] = 1.0 if top_struct_ok else 0.0
    scores["top_series_genre_row_limit"] = 1.0 if top_limit_ok else 0.0

    summary_csv_path = workspace / "output" / "genre_summary.csv"
    s_header, s_rows = _parse_csv(summary_csv_path) if summary_csv_path.exists() else (None, None)
    expected_summary_header = ["genre", "count_series", "avg_rating", "median_rating", "weighted_avg_rating", "total_votes"]
    summary_ok = False
    if s_header == expected_summary_header and isinstance(s_rows, list):
        per_row_ok = True
        for r in s_rows:
            g = r.get("genre", "")
            if g not in priority_genres:
                per_row_ok = False
                break
            cs = _to_int(r.get("count_series", ""))
            av = _to_float(r.get("avg_rating", ""))
            md = _to_float(r.get("median_rating", ""))
            wav = _to_float(r.get("weighted_avg_rating", ""))
            tv = _to_int(r.get("total_votes", ""))
            if cs is None or cs < 0:
                per_row_ok = False
                break
            if av is None or md is None or wav is None:
                per_row_ok = False
                break
            if tv is None or tv < 0:
                per_row_ok = False
                break
        if per_row_ok:
            summary_ok = True
    scores["genre_summary_csv_valid_structure"] = 1.0 if summary_ok else 0.0

    status_path = workspace / "output" / "status_update.md"
    status_text = _safe_read_text(status_path) or ""
    sections_ok = False
    if status_text:
        must_headings = ["Title and date", "Data sources", "Methodology", "Highlights", "Next steps"]
        headings_present = all(_heading_present(status_text, h) for h in must_headings)
        mentions_files = (
            _contains_case_insensitive(status_text, "title.basics.tsv.gz")
            and _contains_case_insensitive(status_text, "title.ratings.tsv.gz")
            and _contains_case_insensitive(status_text, "output/download_manifest.json")
        )
        mentions_join_and_window = (
            _contains_case_insensitive(status_text, "tconst")
            and (_contains_case_insensitive(status_text, "2019") and _contains_case_insensitive(status_text, "2024"))
            and (_contains_case_insensitive(status_text, "5000") or _contains_case_insensitive(status_text, "numVotes"))
        )
        mentions_weighted = _contains_case_insensitive(status_text, "weighted") and _contains_case_insensitive(status_text, "rating")
        genre_mentions = sum(1 for g in set(priority_genres) if _contains_case_insensitive(status_text, g))
        highlights_ok = mentions_weighted and (genre_mentions >= 3)
        bullets = _count_bullets(status_text)
        next_steps_bullets_ok = bullets >= 1
        sections_ok = headings_present and mentions_files and mentions_join_and_window and highlights_ok and next_steps_bullets_ok
    scores["status_update_sections_and_references"] = 1.0 if sections_ok else 0.0

    missing_note_ok = False
    if status_text and header == expected_top_header and isinstance(rows, list) and priority_genres:
        present_genres = set([r["genre"] for r in rows if "genre" in r])
        missing_genres = [g for g in priority_genres if g not in present_genres]
        if not missing_genres:
            missing_note_ok = True
        else:
            missing_note_ok = _check_missing_genres_noted(status_text, missing_genres)
    scores["status_update_missing_genres_noted"] = 1.0 if missing_note_ok else 0.0

    email_path = workspace / "output" / "email_draft_to_client.txt"
    email_text = _safe_read_text(email_path) or ""
    email_ok = False
    if email_text and profile:
        start_segment = email_text[:200]
        greeting_ok = bool(re.search(r"^(hi|hello|dear)[^a-zA-Z0-9]{0,10}(?:ava|ava chen)", start_segment, flags=re.IGNORECASE | re.MULTILINE))
        client_ok = client_name and _contains_case_insensitive(email_text, client_name)
        age_ok = target_age_range and _contains_case_insensitive(email_text, target_age_range)
        market_ok = any(_contains_case_insensitive(email_text, m) for m in target_markets) if target_markets else False
        deliverables_ok = (
            _contains_case_insensitive(email_text, "output/priority_genre_top_series.csv")
            and _contains_case_insensitive(email_text, "output/genre_summary.csv")
        )
        next_steps_ok = _contains_case_insensitive(email_text, "next steps")
        feedback_ok = _contains_case_insensitive(email_text, "feedback")
        email_ok = all([greeting_ok, client_ok, age_ok, market_ok, deliverables_ok, next_steps_ok, feedback_ok])
    scores["email_draft_content_requirements"] = 1.0 if email_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()