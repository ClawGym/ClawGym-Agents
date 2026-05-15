import json
import sys
import csv
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Tuple[Optional[str], Optional[str]]:
    try:
        text = path.read_text(encoding="utf-8")
        return text, None
    except Exception as e:
        return None, str(e)


def _safe_read_csv(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            # Ensure headers exist
            if reader.fieldnames is None:
                return None, "Missing headers"
            return rows, None
    except Exception as e:
        return None, str(e)


def _to_float(val: str) -> Optional[float]:
    try:
        return float(val)
    except Exception:
        return None


def _to_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except Exception:
        return None


def _decade_label(year: int) -> str:
    base = (year // 10) * 10
    return f"{base}s"


def _round2_str(x: float) -> str:
    return f"{round(x + 1e-12, 2):.2f}"


def _compute_aggregates(rows: List[Dict[str, str]]) -> Dict[str, object]:
    # Compute per-genre averages and counts; per-decade counts; overall avg
    by_genre: Dict[str, List[float]] = {}
    by_decade: Dict[str, int] = {}
    all_ratings: List[float] = []
    for r in rows:
        genre = r.get("genre", "")
        rating = _to_float(r.get("rating", ""))
        year = _to_int(r.get("year", ""))
        if genre is None or genre == "" or rating is None or year is None:
            # Skip malformed rows entirely; but if any required value is missing, aggregates may be incomplete.
            continue
        by_genre.setdefault(genre, []).append(rating)
        all_ratings.append(rating)
        dlabel = _decade_label(year)
        by_decade[dlabel] = by_decade.get(dlabel, 0) + 1

    avg_by_genre: Dict[str, Tuple[str, int]] = {}
    for g, vals in by_genre.items():
        if len(vals) == 0:
            continue
        avg_by_genre[g] = (_round2_str(sum(vals) / len(vals)), len(vals))

    counts_by_decade: Dict[str, int] = dict(by_decade)

    overall_avg = None
    if all_ratings:
        overall_avg = _round2_str(sum(all_ratings) / len(all_ratings))

    # Determine focus genres: top two by avg among genres with count >= 2, break ties by avg desc then genre asc.
    eligible = []
    for g, (avg_str, cnt) in avg_by_genre.items():
        if cnt >= 2:
            eligible.append((g, float(avg_str), cnt))
    eligible.sort(key=lambda x: (-x[1], x[0]))
    focus_genres = [g for g, _, _ in eligible[:2]]

    # Top decade by film count; tie-break by decade label ascending
    top_decade = None
    if counts_by_decade:
        sorted_decades = sorted(counts_by_decade.items(), key=lambda kv: (-kv[1], kv[0]))
        top_decade = sorted_decades[0][0]

    return {
        "avg_by_genre": avg_by_genre,  # genre -> (avg_str, count_int)
        "counts_by_decade": counts_by_decade,  # decade -> count
        "overall_avg": overall_avg,  # str with 2 decimals or None
        "focus_genres": focus_genres,  # list of 0-2 genres
        "top_decade": top_decade,  # str or None
    }


def _extract_grandma_data(rows: List[Dict[str, str]]) -> Dict[str, Dict[str, object]]:
    # Return mapping from title -> {"comment": str, "quotes": set([...])} for Grandma Ruth entries
    result: Dict[str, Dict[str, object]] = {}
    for r in rows:
        if r.get("contributor", "") == "Grandma Ruth":
            title = r.get("title", "")
            comment = r.get("comment", "") or ""
            # Extract quoted phrases: single and double quotes
            single_q = re.findall(r"'([^']+)'", comment)
            double_q = re.findall(r'"([^"]+)"', comment)
            phrases = set()
            for q in single_q:
                phrases.add(f"'{q}'")
            for q in double_q:
                phrases.add(f"\"{q}\"")
            result[title] = {"comment": comment, "quotes": phrases}
    return result


def _parse_csv_output(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            headers = reader.fieldnames
            if headers is None:
                return None, None, "Missing headers"
            return rows, headers, None
    except Exception as e:
        return None, None, str(e)


def _normalize_quotes(text: str) -> str:
    # Normalize curly apostrophes to ASCII for comparison
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201C", '"').replace("\u201D", '"')
    return text


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "avg_by_genre_correct": 0.0,
        "counts_by_decade_correct": 0.0,
        "grandma_highlights_structure": 0.0,
        "grandma_highlights_valid_content": 0.0,
        "meeting_plan_focus_line_correct": 0.0,
        "meeting_plan_data_snapshot_values": 0.0,
        "meeting_plan_grandmas_note_present": 0.0,
        "meeting_plan_agenda_items": 0.0,
        "invitation_subject_and_length": 0.0,
        "invitation_details_and_focus_genres": 0.0,
        "invitation_includes_grandma_quote": 0.0,
        "no_external_film_mentioned": 0.0,
        "focus_genres_consistent_between_docs": 0.0,
    }

    # Load inputs
    input_csv_path = workspace / "input" / "club_viewing_notes.csv"
    email_draft_path = workspace / "input" / "email_draft.txt"

    rows, rows_err = _safe_read_csv(input_csv_path)
    if rows is None:
        # Cannot compute expected outputs; return zeros but handle deliverables existence checks gracefully
        rows = []
    grandma_map = _extract_grandma_data(rows)
    aggregates = _compute_aggregates(rows)

    # 1) Validate output/avg_by_genre.csv
    avg_out_path = workspace / "output" / "avg_by_genre.csv"
    avg_rows, avg_headers, avg_err = _parse_csv_output(avg_out_path)
    if avg_rows is not None and avg_headers is not None:
        expected_headers = ["genre", "avg_rating", "count"]
        if avg_headers == expected_headers:
            # Build expected set
            expected_map = aggregates["avg_by_genre"] if aggregates["avg_by_genre"] else {}
            # Compare as sets of tuples (genre, avg_str, count_str)
            expected_set = set()
            for g, (avg_str, cnt) in expected_map.items():
                expected_set.add((g, avg_str, str(cnt)))
            actual_set = set()
            ok_rows_parse = True
            for r in avg_rows:
                g = r.get("genre", None)
                avg_s = r.get("avg_rating", None)
                cnt_s = r.get("count", None)
                if g is None or avg_s is None or cnt_s is None:
                    ok_rows_parse = False
                    break
                # validate count is integer
                if _to_int(cnt_s) is None:
                    ok_rows_parse = False
                    break
                # validate avg format is numeric with 2 decimals
                try:
                    float(avg_s)
                except Exception:
                    ok_rows_parse = False
                    break
                if not re.fullmatch(r"-?\d+\.\d{2}", avg_s):
                    ok_rows_parse = False
                    break
                actual_set.add((g, avg_s, cnt_s))
            if ok_rows_parse and actual_set == expected_set and len(actual_set) == len(expected_set) and len(actual_set) > 0:
                scores["avg_by_genre_correct"] = 1.0

    # 2) Validate output/counts_by_decade.csv
    counts_out_path = workspace / "output" / "counts_by_decade.csv"
    dec_rows, dec_headers, dec_err = _parse_csv_output(counts_out_path)
    if dec_rows is not None and dec_headers is not None:
        if dec_headers == ["decade", "film_count"]:
            expected_counts = aggregates["counts_by_decade"] if aggregates["counts_by_decade"] else {}
            expected_set = set((d, str(c)) for d, c in expected_counts.items())
            actual_set = set()
            ok_rows_parse = True
            for r in dec_rows:
                d = r.get("decade", None)
                c = r.get("film_count", None)
                if d is None or c is None:
                    ok_rows_parse = False
                    break
                if not re.fullmatch(r"\d{4}s", d or ""):
                    ok_rows_parse = False
                    break
                if _to_int(c) is None:
                    ok_rows_parse = False
                    break
                actual_set.add((d, c))
            if ok_rows_parse and actual_set == expected_set and len(actual_set) == len(expected_set) and len(actual_set) > 0:
                scores["counts_by_decade_correct"] = 1.0

    # 3) Validate output/grandma_highlights.txt
    gh_path = workspace / "output" / "grandma_highlights.txt"
    gh_text, gh_err = _safe_read_text(gh_path)
    if gh_text is not None:
        lines = [ln.strip() for ln in gh_text.splitlines() if ln.strip() != ""]
        # 2-3 bullets
        if 2 <= len(lines) <= 3:
            # bullets must start with "- " or "* " or "• "
            bullets_ok = all(ln.startswith("- ") or ln.startswith("* ") or ln.startswith("• ") for ln in lines)
            if bullets_ok:
                scores["grandma_highlights_structure"] = 1.0
        # Validate each bullet contains a film title in parentheses and a direct quote from that film's Grandma Ruth comment
        valid_content = True
        seen_titles = set()
        grandma_titles = set(grandma_map.keys())
        # Build mapping title -> quotes
        title_to_quotes: Dict[str, set] = {}
        for t, info in grandma_map.items():
            title_to_quotes[t] = info.get("quotes", set())  # set of phrases with quotes
        for ln in lines:
            # find title in parentheses
            m = re.search(r"\(([^)]+)\)", ln)
            if not m:
                valid_content = False
                break
            title_in = m.group(1).strip()
            if title_in not in grandma_titles:
                valid_content = False
                break
            # title uniqueness
            if title_in in seen_titles:
                valid_content = False
                break
            seen_titles.add(title_in)
            # include one quoted phrase from her comment for that title
            quotes = title_to_quotes.get(title_in, set())
            has_quote = False
            for q in quotes:
                if q in ln:
                    has_quote = True
                    break
            if not has_quote:
                valid_content = False
                break
        if lines and valid_content:
            scores["grandma_highlights_valid_content"] = 1.0

    # 4) Validate output/meeting_plan.md
    mp_path = workspace / "output" / "meeting_plan.md"
    mp_text_raw, mp_err = _safe_read_text(mp_path)
    focus_genres = aggregates["focus_genres"] if aggregates["focus_genres"] else []
    overall_avg = aggregates["overall_avg"]
    top_decade = aggregates["top_decade"]
    expected_focus_line = None
    if len(focus_genres) >= 2:
        expected_focus_line = f"Meeting focus: {focus_genres[0]} and {focus_genres[1]} (by average rating)"
    mp_text = None
    if mp_text_raw is not None:
        mp_text = _normalize_quotes(mp_text_raw)
        mp_lines = mp_text.splitlines()
        if mp_lines:
            first_line = mp_lines[0].strip()
            if expected_focus_line and first_line == expected_focus_line:
                scores["meeting_plan_focus_line_correct"] = 1.0

        # Data snapshot values present
        data_snapshot_ok = False
        if mp_text:
            has_header = "data snapshot" in mp_text.lower()
            overall_ok = overall_avg is not None and overall_avg in mp_text
            decade_ok = top_decade is not None and top_decade in mp_text
            if has_header and overall_ok and decade_ok:
                data_snapshot_ok = True
        if data_snapshot_ok:
            scores["meeting_plan_data_snapshot_values"] = 1.0

        # Grandma’s note section includes direct quote and associated film title in parentheses
        grandmas_note_ok = False
        if mp_text:
            if "grandma’s note" in mp_text.lower() or "grandma's note" in mp_text.lower():
                # find any line that contains a grandma quote and a valid grandma title in parentheses
                any_ok = False
                for line in mp_lines:
                    line_n = line.strip()
                    if not line_n:
                        continue
                    # Contains a parentheses with a Grandma title
                    m = re.search(r"\(([^)]+)\)", line_n)
                    if m:
                        title_in = m.group(1).strip()
                        if title_in in grandma_map:
                            # Contains any quote for that title
                            quotes = grandma_map[title_in].get("quotes", set())
                            for q in quotes:
                                if q in line_n:
                                    any_ok = True
                                    break
                    if any_ok:
                        break
                if any_ok:
                    grandmas_note_ok = True
        if grandmas_note_ok:
            scores["meeting_plan_grandmas_note_present"] = 1.0

        # Agenda section with three bullets exact labels/durations
        agenda_ok = False
        if mp_text:
            if "agenda" in mp_text.lower():
                # Build expected bullet texts
                if len(focus_genres) >= 2:
                    g1, g2 = focus_genres[0], focus_genres[1]
                    exp1 = "Introduction (5 min)"
                    exp2 = f"Main discussion on {g1} and {g2} (25 min)"
                    exp3 = "Closing picks (10 min)"
                    present = {"intro": False, "main": False, "closing": False}
                    for line in mp_lines:
                        l = line.strip()
                        if (l.startswith("- ") or l.startswith("* ") or l.startswith("• ")) and exp1 in l:
                            present["intro"] = True
                        if (l.startswith("- ") or l.startswith("* ") or l.startswith("• ")) and exp2 in l:
                            present["main"] = True
                        if (l.startswith("- ") or l.startswith("* ") or l.startswith("• ")) and exp3 in l:
                            present["closing"] = True
                    if all(present.values()):
                        agenda_ok = True
        if agenda_ok:
            scores["meeting_plan_agenda_items"] = 1.0

    # 5) Validate output/invitation_email.txt
    invite_path = workspace / "output" / "invitation_email.txt"
    invite_text_raw, invite_err = _safe_read_text(invite_path)
    if invite_text_raw is not None:
        invite_text = _normalize_quotes(invite_text_raw)
        invite_lines = invite_text.splitlines()
        # Subject line as first line
        subject_ok = False
        body_word_count_ok = False
        if invite_lines:
            if invite_lines[0].strip().startswith("Subject:"):
                subject_ok = True
            # Word count for body (excluding Subject line)
            body = "\n".join(invite_lines[1:]).strip()
            words = re.findall(r"\b\w+\b", body)
            wc = len(words)
            if 120 <= wc <= 180:
                body_word_count_ok = True
        if subject_ok and body_word_count_ok:
            scores["invitation_subject_and_length"] = 1.0

        # Details and focus genres
        details_ok = False
        if invite_lines:
            body = "\n".join(invite_lines[1:]).strip()
            # Preserve exact date/time and location
            has_date_time = "Friday, Dec 15 at 5 pm" in body
            has_location = "Community Room B" in body
            # Explicitly name two focus genres
            genres_ok = False
            if len(aggregates["focus_genres"]) >= 2:
                g1, g2 = aggregates["focus_genres"][0], aggregates["focus_genres"][1]
                genres_ok = (g1 in body) and (g2 in body)
            if has_date_time and has_location and genres_ok:
                details_ok = True
        if details_ok:
            scores["invitation_details_and_focus_genres"] = 1.0

        # Include one short quoted phrase from Grandma Ruth’s observation
        quote_ok = False
        if invite_lines:
            body = "\n".join(invite_lines[1:])
            # collect all grandma quotes
            all_quotes = set()
            for info in grandma_map.values():
                for q in info.get("quotes", set()):
                    all_quotes.add(q)
            for q in all_quotes:
                if q in body:
                    quote_ok = True
                    break
        if quote_ok:
            scores["invitation_includes_grandma_quote"] = 1.0

        # Do not include external film from draft (The Shop Around the Corner)
        external_ok = False
        if invite_text:
            forbidden = "The Shop Around the Corner"
            if forbidden not in invite_text:
                external_ok = True
        if external_ok:
            scores["no_external_film_mentioned"] = 1.0

    # Cross-file focus genres consistency between meeting_plan.md and invitation_email.txt
    consistent_ok = False
    if mp_text_raw is not None and invite_text_raw is not None and len(aggregates["focus_genres"]) >= 2:
        g1, g2 = aggregates["focus_genres"][0], aggregates["focus_genres"][1]
        # Ensure meeting plan first line already validated OR contains the genres; and invitation contains both
        mp_has = False
        mp_text_chk = _normalize_quotes(mp_text_raw)
        if expected_focus_line and mp_text_chk.splitlines():
            if mp_text_chk.splitlines()[0].strip() == expected_focus_line:
                mp_has = True
        inv_has = False
        body = "\n".join(_normalize_quotes(invite_text_raw).splitlines()[1:])
        if g1 in body and g2 in body:
            inv_has = True
        if mp_has and inv_has:
            consistent_ok = True
    if consistent_ok:
        scores["focus_genres_consistent_between_docs"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()