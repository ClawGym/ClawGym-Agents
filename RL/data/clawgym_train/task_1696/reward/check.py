import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return None


def _load_json_array(path: Path) -> Optional[List[dict]]:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _extract_version_from_filename(name: str) -> int:
    m = re.search(r'v(\d+)\.json$', name)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return 0
    return 0


def _word_in_text(word: str, text: str) -> bool:
    return re.search(rf'\b{re.escape(word)}\b', text, flags=re.IGNORECASE) is not None


def _parse_games(workspace: Path) -> Tuple[List[dict], bool]:
    games_path = workspace / "input" / "games.csv"
    rows = _read_csv_dicts(games_path)
    if rows is None:
        return [], False

    games = []
    for r in rows:
        try:
            date_str = r.get("date", "")
            season = int(r.get("season", "0"))
            week = int(r.get("week", "0"))
            home_team = r.get("home_team", "")
            away_team = r.get("away_team", "")
            home_score = int(r.get("home_score", "0"))
            away_score = int(r.get("away_score", "0"))
            venue = r.get("venue", "")
            if home_score > away_score:
                winner = home_team
                loser = away_team
                wscore = home_score
                lscore = away_score
            else:
                winner = away_team
                loser = home_team
                wscore = away_score
                lscore = home_score
            margin = wscore - lscore
            scoreline_en = f"{winner} {wscore}–{lscore}"
            scoreline_hy = f"{winner} {wscore}-{lscore}"
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except Exception:
                d = None
            games.append({
                "date": date_str,
                "date_obj": d,
                "season": season,
                "week": week,
                "home_team": home_team,
                "away_team": away_team,
                "home_score": home_score,
                "away_score": away_score,
                "venue": venue,
                "winner": winner,
                "loser": loser,
                "wscore": wscore,
                "lscore": lscore,
                "margin": margin,
                "scoreline_en": scoreline_en,
                "scoreline_hy": scoreline_hy,
            })
        except Exception:
            return [], False
    return games, True


def _load_templates_and_filter(workspace: Path) -> Tuple[List[Tuple[str, str]], List[str], Dict[str, str], Dict[str, str], bool]:
    templates_dir = workspace / "input" / "templates"
    if not templates_dir.exists() or not templates_dir.is_dir():
        return [], [], {}, {}, False
    discovered_files = []
    files = sorted([p for p in templates_dir.glob("*.json") if p.is_file()])
    id_to_best = {}
    for p in files:
        discovered_files.append(p.name)
        arr = _load_json_array(p)
        if arr is None:
            continue
        ver = _extract_version_from_filename(p.name)
        for obj in arr:
            try:
                tid = obj["id"]
                text_en = obj["text_en"]
            except Exception:
                continue
            cur = id_to_best.get(tid)
            if (cur is None) or (ver > cur[0]):
                id_to_best[tid] = (ver, text_en, p.name)
    merged_templates = [(tid, v[1]) for tid, v in id_to_best.items()]
    merged_sources = {tid: v[2] for tid, v in id_to_best.items()}
    stop_path = workspace / "input" / "stop_phrases.txt"
    stop_text = _read_text(stop_path)
    if stop_text is None:
        return [], discovered_files, {}, merged_sources, False
    stop_phrases = [ln.strip() for ln in stop_text.splitlines() if ln.strip()]
    filtered = []
    dropped: Dict[str, str] = {}
    for tid, text in merged_templates:
        dropped_flag = False
        for phrase in stop_phrases:
            if phrase and _word_in_text(phrase, text):
                dropped[tid] = phrase
                dropped_flag = True
                break
        if not dropped_flag:
            filtered.append((tid, text))
    filtered.sort(key=lambda x: x[0])
    return filtered, discovered_files, dropped, merged_sources, True


def _select_top5_eagles_wins(games: List[dict]) -> Tuple[List[dict], int]:
    filtered = [g for g in games if g.get("season", 0) >= 2000 and g.get("winner") == "Eagles"]
    def sort_key(g):
        d = g.get("date_obj")
        return (g.get("margin", 0), d if d is not None else datetime.min.date())
    ranked = sorted(filtered, key=sort_key, reverse=True)
    return ranked[:5], len(filtered)


def _format_template(text_en: str, fields: Dict[str, str]) -> str:
    try:
        return text_en.format(**fields)
    except Exception:
        return ""


def _expected_english_variants_for_game(template_text: str, game: dict) -> List[str]:
    fields_base = {
        "season": game["season"],
        "week": game["week"],
        "winner": game["winner"],
        "loser": game["loser"],
        "scoreline": None,
        "margin": game["margin"],
        "venue": game["venue"],
    }
    variants = []
    for scoreline in [game["scoreline_en"], game["scoreline_hy"]]:
        f = dict(fields_base)
        f["scoreline"] = scoreline
        variants.append(_format_template(template_text, f))
    return variants


def _read_csv_rows_with_header(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[List[str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return [], []
            header = rows[0]
            dict_rows = []
            for r in rows[1:]:
                d = {}
                for i, h in enumerate(header):
                    d[h] = r[i] if i < len(r) else ""
                dict_rows.append(d)
            return dict_rows, header
    except Exception:
        return None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "taunt_cards_exists_and_header": 0.0,
        "taunt_cards_row_count_and_order": 0.0,
        "taunt_cards_game_fields_correct": 0.0,
        "taunt_cards_scoreline_and_margin_correct": 0.0,
        "template_assignment_and_english_text": 0.0,
        "spanish_text_constraints": 0.0,
        "selection_report_exists": 0.0,
        "selection_report_games_summary_correct": 0.0,
        "selection_report_templates_listed_and_counts": 0.0,
        "selection_report_assignment_and_tiebreak_mentioned": 0.0,
    }

    games, games_ok = _parse_games(workspace)
    expected_total_games = len(games) if games_ok else None

    filtered_templates, discovered_files, dropped_map, merged_sources, templates_ok = _load_templates_and_filter(workspace)
    merged_count = len(merged_sources) if templates_ok else None
    filtered_count = len(filtered_templates) if templates_ok else None

    top5: List[dict] = []
    filtered_eagles_count = None
    if games_ok:
        top5, filtered_eagles_count = _select_top5_eagles_wins(games)

    assigned_template_by_rank: Dict[int, Tuple[str, str]] = {}
    if templates_ok and filtered_templates:
        for i in range(5):
            tid, ttext = filtered_templates[i % len(filtered_templates)]
            assigned_template_by_rank[i + 1] = (tid, ttext)

    taunt_path = workspace / "output" / "taunt_cards.csv"
    rows, header = _read_csv_rows_with_header(taunt_path)

    expected_header = [
        "rank", "date", "season", "week", "venue",
        "winner", "loser", "scoreline", "margin",
        "template_id", "english_text", "spanish_text",
    ]

    if rows is not None and header is not None and header == expected_header:
        scores["taunt_cards_exists_and_header"] = 1.0

    if rows is not None and header is not None and header == expected_header:
        if len(rows) == 5:
            ranks_ok = True
            for i, r in enumerate(rows, start=1):
                if r.get("rank", "") != str(i):
                    ranks_ok = False
                    break
            if ranks_ok:
                scores["taunt_cards_row_count_and_order"] = 1.0

    if scores["taunt_cards_row_count_and_order"] > 0 and games_ok:
        game_fields_ok = True
        for i, r in enumerate(rows, start=1):
            if i > len(top5):
                game_fields_ok = False
                break
            g = top5[i - 1]
            checks = [
                r.get("date", "") == g["date"],
                r.get("season", "") == str(g["season"]),
                r.get("week", "") == str(g["week"]),
                r.get("venue", "") == g["venue"],
                r.get("winner", "") == g["winner"],
                r.get("loser", "") == g["loser"],
            ]
            if not all(checks):
                game_fields_ok = False
                break
        scores["taunt_cards_game_fields_correct"] = 1.0 if game_fields_ok else 0.0

    if scores["taunt_cards_row_count_and_order"] > 0 and games_ok:
        score_ok = True
        for i, r in enumerate(rows, start=1):
            if i > len(top5):
                score_ok = False
                break
            g = top5[i - 1]
            scoreline_str = r.get("scoreline", "")
            expected_ok = scoreline_str in (g["scoreline_en"], g["scoreline_hy"])
            margin_ok = r.get("margin", "") == str(g["margin"])
            if not (expected_ok and margin_ok):
                score_ok = False
                break
        scores["taunt_cards_scoreline_and_margin_correct"] = 1.0 if score_ok else 0.0

    if scores["taunt_cards_row_count_and_order"] > 0 and games_ok and templates_ok and filtered_templates:
        assignment_ok = True
        for i, r in enumerate(rows, start=1):
            if i > len(top5) or i not in assigned_template_by_rank:
                assignment_ok = False
                break
            expected_tid, ttext = assigned_template_by_rank[i]
            if r.get("template_id", "") != expected_tid:
                assignment_ok = False
                break
            g = top5[i - 1]
            eng_text = r.get("english_text", "")
            variants = _expected_english_variants_for_game(ttext, g)
            teams_present = ("Eagles" in eng_text and "Cowboys" in eng_text)
            if eng_text not in variants or not teams_present:
                assignment_ok = False
                break
        scores["template_assignment_and_english_text"] = 1.0 if assignment_ok else 0.0

    if scores["taunt_cards_row_count_and_order"] > 0:
        spanish_ok = True
        stop_path = workspace / "input" / "stop_phrases.txt"
        stop_text = _read_text(stop_path) or ""
        stop_phrases = [ln.strip() for ln in stop_text.splitlines() if ln.strip()]
        for i, r in enumerate(rows, start=1):
            eng = r.get("english_text", "")
            spa = r.get("spanish_text", "")
            if not spa or spa == eng:
                spanish_ok = False
                break
            if "Eagles" not in spa or "Cowboys" not in spa:
                spanish_ok = False
                break
            g = top5[i - 1] if games_ok and i - 1 < len(top5) else None
            if g is None:
                spanish_ok = False
                break
            expected_scorelines = [g["scoreline_en"], g["scoreline_hy"]]
            used_scoreline = None
            for s in expected_scorelines:
                if s in eng:
                    used_scoreline = s
                    break
            if used_scoreline is None:
                candidate = r.get("scoreline", "")
                if candidate:
                    used_scoreline = candidate
            if used_scoreline is None or used_scoreline not in spa:
                spanish_ok = False
                break
            for phrase in stop_phrases:
                if phrase and _word_in_text(phrase, spa):
                    spanish_ok = False
                    break
            if not spanish_ok:
                break
        scores["spanish_text_constraints"] = 1.0 if spanish_ok else 0.0

    report_path = workspace / "output" / "selection_report.md"
    report_text = _read_text(report_path)
    if report_text is not None:
        scores["selection_report_exists"] = 1.0

    if report_text is not None and games_ok:
        ok = True
        if expected_total_games is None:
            ok = False
        else:
            lines = report_text.splitlines()
            found_total = False
            for ln in lines:
                if re.search(r'game', ln, flags=re.IGNORECASE) and str(expected_total_games) in ln:
                    found_total = True
                    break
            if not found_total:
                ok = False
        if filtered_eagles_count is None:
            ok = False
        else:
            found_filtered = False
            for ln in lines:
                if (re.search(r'(filter|Eagles)', ln, flags=re.IGNORECASE)
                        and str(filtered_eagles_count) in ln):
                    found_filtered = True
                    break
            if not found_filtered:
                ok = False
        if top5:
            positions = []
            for g in top5:
                date_str = g["date"]
                idx = report_text.find(date_str)
                if idx == -1:
                    ok = False
                    break
                window = report_text[idx: idx + 120]
                if str(g["margin"]) not in window:
                    ok = False
                    break
                positions.append(idx)
            if ok:
                if any(positions[i] > positions[i + 1] for i in range(len(positions) - 1)):
                    ok = False
        else:
            ok = False
        scores["selection_report_games_summary_correct"] = 1.0 if ok else 0.0

    if report_text is not None and templates_ok:
        ok = True
        for fname in discovered_files:
            if fname not in report_text:
                ok = False
                break
        if ok:
            if merged_count is None or filtered_count is None:
                ok = False
            else:
                lines = report_text.splitlines()
                has_before_after = False
                for ln in lines:
                    if re.search(r'template', ln, flags=re.IGNORECASE):
                        if str(merged_count) in ln and str(filtered_count) in ln:
                            has_before_after = True
                            break
                if not has_before_after:
                    ok = False
        if ok and dropped_map:
            for tid, phrase in dropped_map.items():
                if tid not in report_text or phrase not in report_text:
                    ok = False
                    break
        scores["selection_report_templates_listed_and_counts"] = 1.0 if ok else 0.0

    if report_text is not None and templates_ok and games_ok and top5:
        ok = True
        if assigned_template_by_rank:
            for rank, (tid, _) in assigned_template_by_rank.items():
                found_line = False
                for ln in report_text.splitlines():
                    if re.search(rf'\b{rank}\b', ln) and tid in ln:
                        found_line = True
                        break
                if not found_line:
                    ok = False
                    break
        if ok:
            text_lower = report_text.lower()
            has_tie = ("tie" in text_lower)
            has_date = ("date" in text_lower)
            has_recency = ("desc" in text_lower) or ("recent" in text_lower) or ("newer" in text_lower)
            if not (has_tie and has_date and has_recency):
                ok = False
        scores["selection_report_assignment_and_tiebreak_mentioned"] = 1.0 if ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()