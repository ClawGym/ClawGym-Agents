import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f), None
    except Exception as e:
        return None, str(e)


def _load_csv(path: Path) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            for r in reader:
                row = dict(r)
                # enforce required fields and types if present
                if "duration_sec" in row and row["duration_sec"] != "":
                    try:
                        row["duration_sec"] = int(row["duration_sec"])
                    except Exception:
                        return None, "invalid duration_sec"
                if "upvotes" in row and row["upvotes"] != "":
                    try:
                        row["upvotes"] = int(row["upvotes"])
                    except Exception:
                        return None, "invalid upvotes"
                rows.append(row)
            return rows, None
    except Exception as e:
        return None, str(e)


def _build_submissions_maps(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, float]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    upvotes: Dict[str, float] = {}
    for r in rows:
        rid = r.get("id")
        if isinstance(rid, str):
            by_id[rid] = r
            upvotes[rid] = float(r.get("upvotes", 0))
    return by_id, upvotes


def _compute_weighted_scores(rows: List[Dict[str, Any]], weights: Dict[str, float]) -> Dict[str, float]:
    scores: Dict[str, float] = {}
    for r in rows:
        rid = r.get("id")
        if not isinstance(rid, str):
            continue
        mg = r.get("microgenre", "")
        uv = r.get("upvotes", 0)
        try:
            uv_i = int(uv)
        except Exception:
            uv_i = 0
        w = weights.get(mg, 1.0)
        try:
            w_f = float(w)
        except Exception:
            w_f = 1.0
        scores[rid] = uv_i * w_f
    return scores


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _to_mmss(total_sec: int) -> str:
    if total_sec < 0:
        total_sec = 0
    m = total_sec // 60
    s = total_sec % 60
    return f"{m}:{s:02d}"


def _playlist_tracks_schema_valid(tracks: List[Dict[str, Any]]) -> bool:
    required_keys = {"id", "position", "artist", "title", "microgenre", "country", "duration_sec", "upvotes", "weighted_score"}
    if not isinstance(tracks, list) or len(tracks) == 0:
        return False
    positions = set()
    for t in tracks:
        if not isinstance(t, dict):
            return False
        if not required_keys.issubset(t.keys()):
            return False
        if not isinstance(t["id"], str) or not t["id"]:
            return False
        if not isinstance(t["artist"], str) or not isinstance(t["title"], str):
            return False
        if not isinstance(t["microgenre"], str) or not isinstance(t["country"], str):
            return False
        try:
            pos = int(t["position"])
        except Exception:
            return False
        positions.add(pos)
        try:
            int(t["duration_sec"])
        except Exception:
            return False
        try:
            int(t["upvotes"])
        except Exception:
            return False
        try:
            float(t["weighted_score"])
        except Exception:
            return False
    # positions should be 1..N
    n = len(tracks)
    if positions != set(range(1, n + 1)):
        return False
    return True


def _map_tracks_by_position(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        return sorted(tracks, key=lambda t: int(t.get("position", 0)))
    except Exception:
        return tracks


def _get_playlist_paths(workspace: Path) -> Tuple[Path, Path, Path, Path]:
    inputs_csv = workspace / "input" / "submissions.csv"
    inputs_json = workspace / "input" / "genre_weights.json"
    out_playlist = workspace / "output" / "playlist.json"
    out_summary = workspace / "output" / "sampler_summary.md"
    return inputs_csv, inputs_json, out_playlist, out_summary


def _format_score_variants(val: float) -> List[str]:
    vals: List[str] = []
    # include raw, 1-3 decimals, integer if close
    vals.append(str(val))
    vals.append(f"{val:.1f}")
    vals.append(f"{val:.2f}")
    vals.append(f"{val:.3f}")
    if abs(round(val) - val) < 1e-9:
        vals.append(str(int(round(val))))
        vals.append(f"{val:.0f}")
    # normalized removal of trailing zeros
    try:
        s = f"{val:.6f}".rstrip("0").rstrip(".")
        if s:
            vals.append(s)
    except Exception:
        pass
    # unique
    uniq = []
    seen = set()
    for v in vals:
        if v not in seen:
            uniq.append(v)
            seen.add(v)
    return uniq


def _find_section_lines(md: str, header: str) -> List[str]:
    lines = md.splitlines()
    start_idx = None
    header_lower = header.strip().lower()
    for i, line in enumerate(lines):
        if header_lower in line.strip().lower():
            start_idx = i
            break
    if start_idx is None:
        return []
    # section ends at next header-like line containing "##" or a line that contains a title-case header we expect
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        l = lines[j].strip()
        if l.startswith("#"):
            end_idx = j
            break
        if "constraints check" in l.lower() and header_lower != "constraints check":
            end_idx = j
            break
        if "notes on exclusions" in l.lower() and header_lower != "notes on exclusions":
            end_idx = j
            break
        if "overview" in l.lower() and header_lower != "overview":
            end_idx = j
            break
    return lines[start_idx:end_idx]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "playlist_json_exists_and_parseable": 0.0,
        "playlist_tracks_schema_valid": 0.0,
        "track_data_matches_input": 0.0,
        "weighted_scores_correct": 0.0,
        "playlist_ordering_correct": 0.0,
        "constraints_satisfied": 0.0,
        "playlist_summary_values_correct": 0.0,
        "sampler_summary_exists_and_sections": 0.0,
        "sampler_summary_lists_tracks_with_scores": 0.0,
        "sampler_constraints_section_correct": 0.0,
        "exclusions_section_quality": 0.0,
    }

    inputs_csv, inputs_json, out_playlist, out_summary = _get_playlist_paths(workspace)

    # Load inputs
    submissions_rows, submissions_err = _load_csv(inputs_csv)
    weights_obj, weights_err = _load_json(inputs_json)

    submissions_ok = submissions_rows is not None and isinstance(submissions_rows, list)
    weights_ok = isinstance(weights_obj, dict)

    by_id: Dict[str, Dict[str, Any]] = {}
    weights: Dict[str, float] = {}
    scores_map: Dict[str, float] = {}
    if submissions_ok:
        by_id, _ = _build_submissions_maps(submissions_rows)
    if weights_ok:
        try:
            weights = {str(k): float(v) for k, v in weights_obj.items()}
        except Exception:
            weights = {}
            weights_ok = False
    if submissions_ok and weights_ok:
        scores_map = _compute_weighted_scores(submissions_rows, weights)

    # Load playlist.json
    playlist_obj, playlist_err = _load_json(out_playlist)
    playlist_ok = isinstance(playlist_obj, dict) and "tracks" in playlist_obj and "summary" in playlist_obj

    if playlist_ok:
        scores["playlist_json_exists_and_parseable"] = 1.0

    tracks: List[Dict[str, Any]] = []
    summary: Dict[str, Any] = {}
    if playlist_ok:
        tracks = playlist_obj.get("tracks", [])
        summary = playlist_obj.get("summary", {})
        if _playlist_tracks_schema_valid(tracks):
            scores["playlist_tracks_schema_valid"] = 1.0

    # track_data_matches_input and weighted_scores_correct
    if playlist_ok and submissions_ok:
        all_match = True
        all_weight_ok = True
        for t in tracks:
            tid = t.get("id")
            if tid not in by_id:
                all_match = False
                all_weight_ok = False
                break
            src = by_id[tid]
            # verify fields match input
            for fld in ["artist", "title", "microgenre", "country", "duration_sec", "upvotes"]:
                if fld not in src or fld not in t:
                    all_match = False
                    break
                if isinstance(src[fld], int):
                    try:
                        v = int(t[fld])
                    except Exception:
                        all_match = False
                        break
                    if v != src[fld]:
                        all_match = False
                        break
                else:
                    if str(t[fld]) != str(src[fld]):
                        all_match = False
                        break
            if not all_match:
                break
            # weighted score correctness
            # use default 1.0 if missing
            mg = src.get("microgenre", "")
            uv = src.get("upvotes", 0)
            try:
                uv_i = int(uv)
            except Exception:
                uv_i = 0
            w = weights.get(mg, 1.0)
            try:
                expected = float(uv_i) * float(w)
            except Exception:
                expected = float(uv_i) * 1.0
            try:
                got = float(t.get("weighted_score"))
            except Exception:
                got = None
            if got is None or not _float_equal(got, expected):
                all_weight_ok = False
        if all_match:
            scores["track_data_matches_input"] = 1.0
        if all_weight_ok:
            scores["weighted_scores_correct"] = 1.0

    # playlist_ordering_correct
    if playlist_ok and submissions_ok:
        try:
            by_pos = _map_tracks_by_position(tracks)
            # Build local computed weighted scores (from inputs) for selected tracks
            selected = []
            for t in by_pos:
                tid = t.get("id")
                if tid not in by_id:
                    raise ValueError("id not in input")
                src = by_id[tid]
                uv = int(src.get("upvotes", 0))
                mg = src.get("microgenre", "")
                w = weights.get(mg, 1.0)
                ws = float(uv) * float(w)
                selected.append({
                    "id": tid,
                    "duration_sec": int(src.get("duration_sec", 0)),
                    "weighted_score": ws,
                })
            if not selected:
                raise ValueError("empty")
            # check position 1 rule
            any_le_180 = [x for x in selected if x["duration_sec"] <= 180]
            pos1_ok = False
            if any_le_180:
                max_ws = max(x["weighted_score"] for x in any_le_180)
                pos1 = selected[0]
                if pos1["duration_sec"] <= 180 and _float_equal(pos1["weighted_score"], max_ws):
                    pos1_ok = True
            else:
                max_ws_all = max(x["weighted_score"] for x in selected)
                pos1 = selected[0]
                if _float_equal(pos1["weighted_score"], max_ws_all):
                    pos1_ok = True
            # check positions 2..N ordering
            rest = selected[1:]
            sorted_rest = sorted(rest, key=lambda x: (-x["weighted_score"], x["duration_sec"], x["id"]))
            order_ok = all(r["id"] == s["id"] for r, s in zip(rest, sorted_rest))
            scores["playlist_ordering_correct"] = 1.0 if (pos1_ok and order_ok) else 0.0
        except Exception:
            scores["playlist_ordering_correct"] = 0.0

    # constraints_satisfied
    if playlist_ok and submissions_ok:
        try:
            by_pos = _map_tracks_by_position(tracks)
            ids = [t["id"] for t in by_pos]
            srcs = [by_id[i] for i in ids if i in by_id]
            if len(srcs) != len(by_pos):
                raise ValueError("missing ids in input")
            total_dur = sum(int(s["duration_sec"]) for s in srcs)
            track_count = len(srcs)
            # No artist appears twice
            artists = [s["artist"] for s in srcs]
            artist_unique = len(set(artists)) == len(artists)
            microgenres = [s["microgenre"] for s in srcs]
            distinct_mg = len(set(microgenres))
            countries = [s["country"] for s in srcs]
            distinct_ctry = len(set(countries))
            # Per microgenre limit <= 2
            mg_counts: Dict[str, int] = {}
            for mg in microgenres:
                mg_counts[mg] = mg_counts.get(mg, 0) + 1
            mg_limit_ok = all(c <= 2 for c in mg_counts.values())
            duration_ok = 1380 <= total_dur <= 1560
            count_ok = 5 <= track_count <= 8
            distinct_mg_ok = distinct_mg >= 4
            distinct_ctry_ok = distinct_ctry >= 3
            all_ok = artist_unique and mg_limit_ok and duration_ok and count_ok and distinct_mg_ok and distinct_ctry_ok
            scores["constraints_satisfied"] = 1.0 if all_ok else 0.0
        except Exception:
            scores["constraints_satisfied"] = 0.0

    # playlist_summary_values_correct
    if playlist_ok and submissions_ok:
        try:
            by_pos = _map_tracks_by_position(tracks)
            ids = [t["id"] for t in by_pos]
            srcs = [by_id[i] for i in ids if i in by_id]
            if len(srcs) != len(by_pos):
                raise ValueError("id mismatch")
            # recompute totals from inputs + weights
            total_dur = sum(int(s["duration_sec"]) for s in srcs)
            track_count = len(srcs)
            distinct_mg = len(set(s["microgenre"] for s in srcs))
            distinct_ctry = len(set(s["country"] for s in srcs))
            total_weighted = 0.0
            for s in srcs:
                uv = int(s["upvotes"])
                w = float(weights.get(s["microgenre"], 1.0))
                total_weighted += uv * w
            ok = True
            if int(summary.get("total_duration_sec", -1)) != total_dur:
                ok = False
            if int(summary.get("track_count", -1)) != track_count:
                ok = False
            if int(summary.get("distinct_microgenres", -1)) != distinct_mg:
                ok = False
            if int(summary.get("distinct_countries", -1)) != distinct_ctry:
                ok = False
            try:
                tw = float(summary.get("total_weighted_score"))
            except Exception:
                tw = None
            if tw is None or not _float_equal(tw, total_weighted):
                ok = False
            scores["playlist_summary_values_correct"] = 1.0 if ok else 0.0
        except Exception:
            scores["playlist_summary_values_correct"] = 0.0

    # sampler_summary_exists_and_sections
    md_text = _read_text(out_summary)
    if isinstance(md_text, str):
        has_constraints = "constraints check" in md_text.lower()
        has_notes = "notes on exclusions" in md_text.lower()
        # overview and formula: look for weighted + upvotes + genre weight/microgenre
        lower = md_text.lower()
        overview_ok = ("weighted" in lower and "upvote" in lower and ("genre" in lower or "microgenre" in lower))
        scores["sampler_summary_exists_and_sections"] = 1.0 if (has_constraints and has_notes and overview_ok) else 0.0

    # sampler_summary_lists_tracks_with_scores
    if isinstance(md_text, str) and playlist_ok and submissions_ok:
        try:
            lines = md_text.splitlines()
            all_ok = True
            by_pos = _map_tracks_by_position(tracks)
            for t in by_pos:
                tid = t["id"]
                src = by_id.get(tid, {})
                artist = src.get("artist", "")
                title = src.get("title", "")
                uv = int(src.get("upvotes", 0))
                w = float(weights.get(src.get("microgenre", ""), 1.0))
                ws = uv * w
                pos = int(t["position"])
                # find a line mentioning the track (by id or both artist and title)
                found_idx = None
                for idx, ln in enumerate(lines):
                    lnl = ln.lower()
                    if tid.lower() in lnl or (artist and title and (artist.lower() in lnl and title.lower() in lnl)):
                        found_idx = idx
                        break
                if found_idx is None:
                    all_ok = False
                    break
                # search within same line and the next line for weighted_score and position mention
                candidate = lines[found_idx:found_idx + 2]
                score_strings = _format_score_variants(ws)
                has_score = any(any(s in c for s in score_strings) for c in candidate)
                # position: look for 'pos' or 'position' + number OR (#) position e.g., "1."
                has_pos = False
                pos_patterns = [
                    rf"\bpos(?:ition)?\s*[:#\-]?\s*{pos}\b",
                    rf"^\s*{pos}\s*[\.\)\-]\s*",
                    rf"\btrack\s*#{pos}\b",
                ]
                for c in candidate:
                    lc = c.lower()
                    # If 'pos' or 'position' present, accept number occurrence too
                    if re.search(pos_patterns[0], lc):
                        has_pos = True
                        break
                    if re.search(pos_patterns[1], lc):
                        has_pos = True
                        break
                    if re.search(pos_patterns[2], lc):
                        has_pos = True
                        break
                if not has_score or not has_pos:
                    all_ok = False
                    break
            if all_ok:
                scores["sampler_summary_lists_tracks_with_scores"] = 1.0
        except Exception:
            scores["sampler_summary_lists_tracks_with_scores"] = 0.0

    # sampler_constraints_section_correct
    if isinstance(md_text, str) and playlist_ok and submissions_ok:
        try:
            constraints_lines = _find_section_lines(md_text, "Constraints Check")
            if not constraints_lines:
                raise ValueError("no constraints section")
            # Compute actuals
            by_pos = _map_tracks_by_position(tracks)
            ids = [t["id"] for t in by_pos]
            srcs = [by_id[i] for i in ids if i in by_id]
            total_dur = sum(int(s["duration_sec"]) for s in srcs)
            mmss = _to_mmss(total_dur)
            track_count = len(srcs)
            artist_unique = len({s["artist"] for s in srcs}) == track_count
            distinct_mg = len(set(s["microgenre"] for s in srcs))
            distinct_ctry = len(set(s["country"] for s in srcs))
            mg_counts: Dict[str, int] = {}
            for s in srcs:
                mg = s["microgenre"]
                mg_counts[mg] = mg_counts.get(mg, 0) + 1
            mg_limit_ok = all(c <= 2 for c in mg_counts.values())
            duration_ok = 1380 <= total_dur <= 1560
            count_ok = 5 <= track_count <= 8
            distinct_mg_ok = distinct_mg >= 4
            distinct_ctry_ok = distinct_ctry >= 3

            # Presence checks for total duration values
            section_text = "\n".join(constraints_lines)
            has_sec_num = str(total_dur) in section_text
            has_mmss = bool(re.search(rf"\b{re.escape(mmss)}\b", section_text))
            # Identify lines and PASS/FAIL
            def _line_status(keyword_list: List[str]) -> Optional[bool]:
                for ln in constraints_lines:
                    lnl = ln.lower()
                    if all(k in lnl for k in keyword_list):
                        if "pass" in lnl:
                            return True
                        if "fail" in lnl:
                            return False
                return None

            status_duration = _line_status(["total", "duration"])
            status_track_count = _line_status(["track", "count"])
            status_distinct_mg = _line_status(["microgenre", "distinct"])
            status_distinct_ctry = _line_status(["country", "distinct"])
            status_artist_repeat = _line_status(["artist", "repeat"])
            # allow "duplicate" as alternate keyword for artist repetition
            if status_artist_repeat is None:
                status_artist_repeat = _line_status(["artist", "duplicate"])
            status_mg_limit = _line_status(["microgenre", "limit"])
            if status_mg_limit is None:
                status_mg_limit = _line_status(["microgenre", "cap"])
            all_present = all(x is not None for x in [
                status_duration, status_track_count, status_distinct_mg,
                status_distinct_ctry, status_artist_repeat, status_mg_limit
            ]) and has_sec_num and has_mmss

            all_correct = True
            if status_duration is not None and status_duration != duration_ok:
                all_correct = False
            if status_track_count is not None and status_track_count != count_ok:
                all_correct = False
            if status_distinct_mg is not None and status_distinct_mg != distinct_mg_ok:
                all_correct = False
            if status_distinct_ctry is not None and status_distinct_ctry != distinct_ctry_ok:
                all_correct = False
            if status_artist_repeat is not None and status_artist_repeat != artist_unique:
                all_correct = False
            if status_mg_limit is not None and status_mg_limit != mg_limit_ok:
                all_correct = False

            scores["sampler_constraints_section_correct"] = 1.0 if (all_present and all_correct) else 0.0
        except Exception:
            scores["sampler_constraints_section_correct"] = 0.0

    # exclusions_section_quality
    if isinstance(md_text, str) and submissions_ok and playlist_ok:
        try:
            notes_lines = _find_section_lines(md_text, "Notes on Exclusions")
            if not notes_lines:
                raise ValueError("no notes section")
            notes_text = "\n".join(notes_lines)
            selected_ids = {t["id"] for t in tracks}
            # Minimum selected weighted_score for comparison
            min_selected_ws = None
            for tid in selected_ids:
                src = by_id.get(tid)
                if not src:
                    continue
                uv = int(src["upvotes"])
                w = float(weights.get(src["microgenre"], 1.0))
                ws = uv * w
                if min_selected_ws is None or ws < min_selected_ws:
                    min_selected_ws = ws
            if min_selected_ws is None:
                raise ValueError("no selected ws")
            # Try to match excluded tracks by id, else by artist+title
            excluded_matches: List[Tuple[str, int]] = []  # (id, line_index)
            lines = notes_lines
            # ID-based matches
            for idx, ln in enumerate(lines):
                lnl = ln.lower()
                for rid in by_id.keys():
                    if rid in selected_ids:
                        continue
                    if rid.lower() in lnl:
                        if (rid, idx) not in excluded_matches:
                            excluded_matches.append((rid, idx))
            # Artist-title matches
            # if less than 3 found, attempt artist-title heuristic
            if len(excluded_matches) < 3:
                for rid, rec in by_id.items():
                    if rid in selected_ids:
                        continue
                    artist = rec.get("artist", "")
                    title = rec.get("title", "")
                    # Find a line that mentions both artist and title
                    for idx, ln in enumerate(lines):
                        lnl = ln.lower()
                        if artist and title and (artist.lower() in lnl and title.lower() in lnl):
                            if (rid, idx) not in excluded_matches:
                                excluded_matches.append((rid, idx))
                            break
                    if len(excluded_matches) >= 3:
                        break
            # Filter unique ids while keeping line index for proximity search
            unique_excluded: List[Tuple[str, int]] = []
            seen_ids = set()
            for rid, idx in excluded_matches:
                if rid not in seen_ids:
                    unique_excluded.append((rid, idx))
                    seen_ids.add(rid)
            # Evaluate requirements
            # Need at least 3 unique high-scoring not-selected tracks with reasons
            reason_keywords = ["artist", "duplicate", "repeat", "microgenre", "genre", "cap", "limit", "duration", "feasib", "length"]
            valid_count = 0
            for rid, idx in unique_excluded:
                rec = by_id[rid]
                uv = int(rec["upvotes"])
                w = float(weights.get(rec["microgenre"], 1.0))
                ws = uv * w
                # higher-scoring: strictly greater than min selected
                if ws <= min_selected_ws + 1e-9:
                    continue
                # find reason on the same or next line
                near = " ".join(lines[idx: idx + 2]).lower()
                if any(k in near for k in reason_keywords):
                    valid_count += 1
            scores["exclusions_section_quality"] = 1.0 if valid_count >= 3 else 0.0
        except Exception:
            scores["exclusions_section_quality"] = 0.0

    return {k: float(v) for k, v in scores.items()}


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()