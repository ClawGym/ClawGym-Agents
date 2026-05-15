import json
import csv
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_pgn_tags(pgn_path: Path) -> Optional[Dict[str, str]]:
    text = _read_text(pgn_path)
    if text is None:
        return None
    tags: Dict[str, str] = {}
    in_tags = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_tags = True
            m = re.match(r'^\[(\w+)\s+"(.*)"\]$', line)
            if m:
                tags[m.group(1)] = m.group(2)
        else:
            if in_tags:
                break
            else:
                continue
    return tags if tags else None


def _list_pgns(dir_path: Path) -> List[Path]:
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    return sorted([p for p in dir_path.iterdir() if p.is_file() and p.suffix.lower() == ".pgn"])


def _get_tracked_openings(workspace: Path) -> Dict[str, Path]:
    notes_dir = workspace / "notes"
    result: Dict[str, Path] = {}
    if not notes_dir.exists() or not notes_dir.is_dir():
        return result
    for md in notes_dir.glob("*.md"):
        text = _read_text(md)
        if not text:
            continue
        for line in text.splitlines():
            if line.startswith("# "):
                opening = line[2:].strip()
                if opening:
                    result[opening] = md
                break
    return result


def _opening_base(opening_tag_val: Optional[str]) -> Optional[str]:
    if not opening_tag_val:
        return None
    base = opening_tag_val.split(":", 1)[0].strip()
    return base if base else None


def _parse_date_to_iso(date_str: str) -> Optional[str]:
    if not date_str or len(date_str) < 10:
        return None
    parts = date_str.split(".")
    if len(parts) != 3:
        return None
    y, m, d = parts
    if not (y.isdigit() and m.isdigit() and d.isdigit()):
        return None
    try:
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def _safe_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _extract_recent_marker_block(text: str) -> Tuple[int, int, List[str]]:
    lines = text.splitlines()
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if "<!-- RECENT_GAMES:START -->" in line:
            start_idx = i
        if "<!-- RECENT_GAMES:END -->" in line:
            end_idx = i
            break
    content_lines: List[str] = []
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        content_lines = [l.rstrip("\n") for l in lines[start_idx + 1 : end_idx]]
    return start_idx, end_idx, content_lines


def _tokenize_eco_field(s: str) -> List[str]:
    return re.findall(r"\b[A-E][0-9]{2}\b", s or "")


def _parse_csv(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return None


def _archived_pgns(workspace: Path) -> List[Path]:
    archive = workspace / "archive"
    return _list_pgns(archive)


def _collect_games_by_opening_from_archive(workspace: Path, tracked: List[str]) -> Dict[str, List[Dict[str, object]]]:
    games_by_opening: Dict[str, List[Dict[str, object]]] = {o: [] for o in tracked}
    for pgn in _archived_pgns(workspace):
        tags = _parse_pgn_tags(pgn)
        if not tags:
            continue
        base = _opening_base(tags.get("Opening"))
        if base not in games_by_opening:
            continue
        white = tags.get("White", "").strip()
        black = tags.get("Black", "").strip()
        result = tags.get("Result", "").strip()
        eco = tags.get("ECO", "").strip()
        date_iso = _parse_date_to_iso(tags.get("Date", ""))
        welo = _safe_int(tags.get("WhiteElo"))
        belo = _safe_int(tags.get("BlackElo"))
        avg_elo_game: Optional[float] = None
        if welo is not None and belo is not None:
            avg_elo_game = (welo + belo) / 2.0
        games_by_opening[base].append({
            "file": pgn,
            "white": white,
            "black": black,
            "result": result,
            "eco": eco,
            "date_iso": date_iso,
            "avg_elo_game": avg_elo_game,
        })
    return games_by_opening


def _aggregate_opening_stats(games: List[Dict[str, object]]) -> Dict[str, object]:
    games_count = 0
    ww = 0
    bw = 0
    dr = 0
    ecos = set()
    avg_elos: List[float] = []
    for g in games:
        games_count += 1
        res = (g.get("result") or "").strip()
        if res == "1-0":
            ww += 1
        elif res == "0-1":
            bw += 1
        elif res in ("1/2-1/2", "1/2 - 1/2", "1-1"):
            dr += 1
        eco = (g.get("eco") or "").strip()
        if eco:
            ecos.add(eco)
        avg_val = g.get("avg_elo_game")
        if isinstance(avg_val, (int, float)):
            avg_elos.append(float(avg_val))
    avg_elo_overall: Optional[float] = None
    if avg_elos:
        avg_elo_overall = sum(avg_elos) / len(avg_elos)
    return {
        "games": games_count,
        "white_wins": ww,
        "black_wins": bw,
        "draws": dr,
        "ecos": ecos,
        "avg_elo": avg_elo_overall,
    }


def _float_close_str(value_str: str, expected: float, tol: float = 1.0) -> bool:
    try:
        v = float(value_str.strip())
    except Exception:
        return False
    return abs(v - expected) <= tol


def _path_exists_in_workspace(path_str: str, workspace: Path) -> bool:
    # Accept both relative and absolute paths. Normalize separators.
    norm = path_str.replace("\\", "/")
    p = Path(norm)
    if p.is_absolute():
        return p.exists()
    # Relative to workspace
    return (workspace / p).exists()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "scripts_with_instruction_comment": 0.0,
        "processed_json_valid": 0.0,
        "archive_tracked_pgns_present": 0.0,
        "processed_json_has_archive_paths": 0.0,
        "csv_exists_and_header": 0.0,
        "csv_content_correct_and_sorted": 0.0,
        "notes_recent_games_updated_sicilian": 0.0,
        "notes_recent_games_updated_qgd": 0.0,
    }

    # 1) Check scripts with instruction comment (start/stop watcher guidance in top comments)
    scripts_dir = workspace / "scripts"
    scripts_ok = False
    if scripts_dir.exists() and scripts_dir.is_dir():
        for py in scripts_dir.glob("*.py"):
            text = _read_text(py)
            if not text:
                continue
            lines = text.splitlines()
            top = lines[:10]
            has_comment = False
            for l in top:
                if l.strip().startswith("#"):
                    lower = l.lower()
                    if "watch" in lower and ("start" in lower or "run" in lower or "stop" in lower):
                        has_comment = True
                        break
            if has_comment:
                scripts_ok = True
                break
    scores["scripts_with_instruction_comment"] = 1.0 if scripts_ok else 0.0

    # 2) Validate processed.json structure: non-empty list of strings pointing to existing archived files
    state_dir = workspace / "state"
    processed_path = state_dir / "processed.json"
    processed_json = None
    if processed_path.exists():
        processed_json = _load_json(processed_path)
        if isinstance(processed_json, list) and len(processed_json) > 0 and all(isinstance(x, str) for x in processed_json):
            # all paths must exist
            if all(_path_exists_in_workspace(x, workspace) for x in processed_json):
                scores["processed_json_valid"] = 1.0
            else:
                scores["processed_json_valid"] = 0.0
        else:
            scores["processed_json_valid"] = 0.0
    else:
        scores["processed_json_valid"] = 0.0

    # Identify tracked openings from notes files
    tracked_map = _get_tracked_openings(workspace)
    tracked_openings = sorted(tracked_map.keys())

    # Expected opening names from provided notes
    expected_sicilian_name = "Sicilian Defense"
    expected_qgd_name = "Queen's Gambit Declined"

    # 3) Check archive files moved for tracked PGNs (from provided samples)
    archive_dir = workspace / "archive"
    sicilian_archived = (archive_dir / "sicilian_najdorf_2022.pgn").exists()
    qgd_archived = (archive_dir / "qgd_orthodox_2023.pgn").exists()
    if archive_dir.exists() and sicilian_archived and qgd_archived:
        scores["archive_tracked_pgns_present"] = 1.0
    else:
        scores["archive_tracked_pgns_present"] = 0.0

    # 4) processed.json contains archive paths of tracked PGNs (if available)
    proc_has_paths = False
    if isinstance(processed_json, list) and len(processed_json) > 0:
        normed = [p.replace("\\", "/") for p in processed_json]
        need = ["archive/sicilian_najdorf_2022.pgn", "archive/qgd_orthodox_2023.pgn"]
        if all(any(item.endswith(n) or item == n for item in normed) for n in need):
            proc_has_paths = True
    scores["processed_json_has_archive_paths"] = 1.0 if proc_has_paths else 0.0

    # 5) CSV exists and header correct
    reports_dir = workspace / "reports"
    summary_csv = reports_dir / "opening_summary.csv"
    header_ok = False
    csv_rows: Optional[List[Dict[str, str]]] = None
    expected_header = ["opening", "eco_codes_present", "games", "white_wins", "black_wins", "draws", "avg_elo"]
    if summary_csv.exists():
        try:
            with summary_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if header == expected_header:
                    header_ok = True
        except Exception:
            header_ok = False
        csv_rows = _parse_csv(summary_csv)
    scores["csv_exists_and_header"] = 1.0 if header_ok else 0.0

    # 6) CSV content correctness and sorting (based on archived games only)
    csv_ok = False
    if header_ok and isinstance(csv_rows, list):
        # Must include exactly the tracked openings derived from notes; if missing notes, rely on expected two
        if not tracked_openings:
            tracked_openings = [expected_qgd_name, expected_sicilian_name]
        # Build expected stats from archived PGNs only
        games_by_opening = _collect_games_by_opening_from_archive(workspace, tracked_openings)
        expected_stats: Dict[str, Dict[str, object]] = {}
        for opening, games in games_by_opening.items():
            expected_stats[opening] = _aggregate_opening_stats(games)

        # CSV must have exactly tracked openings and nothing else
        if isinstance(csv_rows, list) and len(csv_rows) == len(tracked_openings):
            openings_in_csv = [row.get("opening", "") for row in csv_rows]
            only_tracked = set(openings_in_csv) == set(tracked_openings)

            # Sorting: by games desc then opening asc, using CSV numeric values
            sort_ok = False
            try:
                # Convert to integers safely, missing treated as 0
                def _games_val(o: str) -> int:
                    try:
                        return int({row.get("opening", ""): row for row in csv_rows}[o]["games"])
                    except Exception:
                        return -10**9  # force fail
                sorted_expected = sorted(
                    openings_in_csv,
                    key=lambda o: (-_games_val(o), o),
                )
                sort_ok = openings_in_csv == sorted_expected
            except Exception:
                sort_ok = False

            # Compare values for each opening
            values_ok = True
            csv_by_opening = {row.get("opening", ""): row for row in csv_rows}
            for opening in tracked_openings:
                if opening not in csv_by_opening or opening not in expected_stats:
                    values_ok = False
                    break
                row = csv_by_opening[opening]
                stats = expected_stats[opening]
                # games, ww, bw, draws
                try:
                    games_match = str(stats["games"]) == str(row.get("games", ""))
                    ww_match = str(stats["white_wins"]) == str(row.get("white_wins", ""))
                    bw_match = str(stats["black_wins"]) == str(row.get("black_wins", ""))
                    dr_match = str(stats["draws"]) == str(row.get("draws", ""))
                except Exception:
                    values_ok = False
                    break
                # eco codes set equality (tokenized)
                eco_tokens = set(_tokenize_eco_field(row.get("eco_codes_present", "") or ""))
                eco_expected = set(stats["ecos"])
                eco_match = eco_tokens == eco_expected
                # avg_elo approximate compare (tolerate rounding differences up to 1)
                if stats["avg_elo"] is None:
                    avg_ok = (row.get("avg_elo", "").strip() == "")
                else:
                    avg_ok = _float_close_str(row.get("avg_elo", ""), float(stats["avg_elo"]))
                if not (games_match and ww_match and bw_match and dr_match and eco_match and avg_ok):
                    values_ok = False
                    break

            csv_ok = only_tracked and sort_ok and values_ok
        else:
            csv_ok = False
    scores["csv_content_correct_and_sorted"] = 1.0 if csv_ok else 0.0

    # 7) Notes recent games updated checks (look for up to three lines including sample game data)
    def _check_note_recent(opening_name: str, expected_file: str, expected_white: str, expected_black: str,
                           expected_result: str, expected_eco: str, expected_date_iso: str) -> float:
        notes_file = None
        if opening_name in tracked_map:
            notes_file = tracked_map[opening_name]
        else:
            fallback = workspace / "notes" / (opening_name.replace(" ", "_").replace("'", "") + ".md")
            if fallback.exists():
                notes_file = fallback
        if not notes_file or not notes_file.exists():
            return 0.0
        text = _read_text(notes_file)
        if not text:
            return 0.0
        start_idx, end_idx, content_lines = _extract_recent_marker_block(text)
        if start_idx == -1 or end_idx == -1:
            return 0.0
        joined = "\n".join(content_lines).strip()
        if "(No entries yet)" in joined:
            return 0.0
        lines = [l.strip() for l in content_lines if l.strip() != ""]
        if len(lines) == 0 or len(lines) > 3:
            return 0.0
        ok = False
        for l in lines:
            lower = l.lower()
            if "archive/" not in lower:
                continue
            if expected_file.lower() not in lower:
                continue
            if expected_date_iso not in l:
                continue
            if (expected_white not in l) or (" vs " not in l) or (expected_black not in l):
                continue
            if expected_result not in l:
                continue
            if expected_eco not in l:
                continue
            ok = True
            break
        return 1.0 if ok else 0.0

    sic_score = _check_note_recent(
        opening_name=expected_sicilian_name,
        expected_file="archive/sicilian_najdorf_2022.pgn",
        expected_white="PlayerA",
        expected_black="PlayerB",
        expected_result="1-0",
        expected_eco="B90",
        expected_date_iso="2022-10-01",
    )
    scores["notes_recent_games_updated_sicilian"] = sic_score

    qgd_score = _check_note_recent(
        opening_name=expected_qgd_name,
        expected_file="archive/qgd_orthodox_2023.pgn",
        expected_white="ChessFan",
        expected_black="Opponent",
        expected_result="0-1",
        expected_eco="D60",
        expected_date_iso="2023-04-12",
    )
    scores["notes_recent_games_updated_qgd"] = qgd_score

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()