import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            return rows
    except Exception:
        return None


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        return None


def _round3(value: float) -> float:
    return float(f"{value:.3f}")


def _compute_expected_from_csv(rows: List[Dict[str, str]]) -> Optional[dict]:
    cols = [
        "date", "opponent", "at_bats", "hits", "walks", "hbp", "sac_flies",
        "rbi", "runs", "doubles", "triples", "home_runs",
        "stolen_bases", "strikeouts"
    ]
    for r in rows:
        for c in cols:
            if c not in r:
                return None
    per_game = []
    dates = []
    totals = {
        "games": 0, "at_bats": 0, "hits": 0, "doubles": 0, "triples": 0, "home_runs": 0,
        "walks": 0, "hbp": 0, "sac_flies": 0, "rbi": 0, "runs": 0, "stolen_bases": 0,
        "strikeouts": 0, "total_bases": 0
    }
    for r in rows:
        ints = {}
        for k in ["at_bats", "hits", "walks", "hbp", "sac_flies", "rbi", "runs", "doubles",
                  "triples", "home_runs", "stolen_bases", "strikeouts"]:
            val = _to_int(r.get(k, ""))
            if val is None:
                return None
            ints[k] = val
        singles = ints["hits"] - (ints["doubles"] + ints["triples"] + ints["home_runs"])
        total_bases = singles * 1 + ints["doubles"] * 2 + ints["triples"] * 3 + ints["home_runs"] * 4
        game_entry = {
            "date": r["date"],
            "opponent": r["opponent"],
            "at_bats": ints["at_bats"],
            "hits": ints["hits"],
            "walks": ints["walks"],
            "hbp": ints["hbp"],
            "sac_flies": ints["sac_flies"],
            "doubles": ints["doubles"],
            "triples": ints["triples"],
            "home_runs": ints["home_runs"],
            "runs": ints["runs"],
            "rbi": ints["rbi"],
            "stolen_bases": ints["stolen_bases"],
            "strikeouts": ints["strikeouts"],
            "total_bases": total_bases
        }
        per_game.append(game_entry)
        dates.append(r["date"])
        totals["games"] += 1
        for k in ["at_bats", "hits", "walks", "hbp", "sac_flies", "rbi", "runs", "doubles",
                  "triples", "home_runs", "stolen_bases", "strikeouts"]:
            totals[k] += ints[k]
        totals["total_bases"] += total_bases

    at_bats = totals["at_bats"]
    hits = totals["hits"]
    walks = totals["walks"]
    hbp = totals["hbp"]
    sf = totals["sac_flies"]
    tb = totals["total_bases"]

    def safe_div(n, d):
        return n / d if d != 0 else 0.0

    batting_average = safe_div(hits, at_bats)
    obp = safe_div(hits + walks + hbp, at_bats + walks + hbp + sf)
    slg = safe_div(tb, at_bats)
    ops = obp + slg

    rates = {
        "batting_average": _round3(batting_average),
        "obp": _round3(obp),
        "slg": _round3(slg),
        "ops": _round3(ops),
    }

    min_date = min(dates) if dates else ""
    max_date = max(dates) if dates else ""

    return {
        "totals": totals,
        "rates": rates,
        "per_game": per_game,
        "min_date": min_date,
        "max_date": max_date
    }


def _normalize_heading(line: str) -> str:
    s = line.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)
    return s.strip()


def _find_section_indices(lines: List[str], header_name: str) -> List[int]:
    idxs = []
    for i, line in enumerate(lines):
        if _normalize_heading(line) == header_name:
            idxs.append(i)
    return idxs


def _extract_intro(lines: List[str], title_idx: int, stats_idx: int) -> str:
    content = lines[title_idx + 1:stats_idx]
    while content and content[0].strip() == "":
        content = content[1:]
    while content and content[-1].strip() == "":
        content = content[:-1]
    return "\n".join(content).strip()


def _word_count(text: str) -> int:
    tokens = [t for t in re.split(r"\s+", text.strip()) if t]
    return len(tokens)


def _parse_stats_summary(section_text: str) -> Optional[dict]:
    result = {}
    float_keys = ["BA", "OBP", "SLG", "OPS"]
    int_keys = ["AB", "H", "HR", "2B", "3B", "BB", "HBP", "SF", "R", "RBI", "SB", "K"]
    text = section_text
    for key in float_keys:
        m = re.search(rf"\b{key}\b[^0-9\-]*([0-9]+\.[0-9]{{3}})", text)
        if not m:
            return None
        try:
            result[key] = float(m.group(1))
        except Exception:
            return None
    for key in int_keys:
        m = re.search(rf"\b{key}\b[^0-9\-]*([0-9]+)", text)
        if not m:
            return None
        try:
            result[key] = int(m.group(1))
        except Exception:
            return None
    return result


def _contains_banned_terms(text: str) -> bool:
    t = text.lower()
    t = t.replace("’", "'")
    banned_substrings = [
        "y'all", "kinda", "ain't", "bomb", "swiped", "whiffed", "vibes", "bragging", "my bad", "sorry"
    ]
    for b in banned_substrings:
        if b in t:
            return True
    if re.search(r"\bu\b", t):
        return True
    return False


def _parse_draft_focus_items(text: str) -> List[str]:
    lines = text.splitlines()
    focus_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "=== focus ===":
            focus_idx = i
            break
    if focus_idx is None:
        return []
    items = []
    for j in range(focus_idx + 1, len(lines)):
        l = lines[j].strip()
        if l.startswith("- "):
            items.append(l[2:].strip())
    return items


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "outputs_exist": 0.0,
        "weekly_stats_json_values_correct": 0.0,
        "weekly_stats_json_per_game_correct": 0.0,
        "weekly_stats_rates_rounded_3dp": 0.0,
        "weekly_update_title_and_range_correct": 0.0,
        "weekly_update_intro_matches_rewritten": 0.0,
        "weekly_update_intro_length_limit": 0.0,
        "weekly_update_stats_summary_parsed": 0.0,
        "stats_summary_matches_expected": 0.0,
        "stats_summary_matches_json": 0.0,
        "next_week_focus_three_bullets": 0.0,
        "next_week_focus_bullets_length_and_keywords": 0.0,
        "rewritten_messages_json_keys_present": 0.0,
        "rewritten_messages_length_limits": 0.0,
        "rewritten_messages_avoid_slang_apologies": 0.0,
    }

    input_csv = workspace / "input" / "games_week_2024-04.csv"
    input_notes = workspace / "input" / "draft_notes.txt"
    out_dir = workspace / "out"
    out_stats = out_dir / "weekly_stats.json"
    out_update = out_dir / "weekly_update.md"
    out_messages = out_dir / "rewritten_messages.json"

    if out_stats.exists() and out_update.exists() and out_messages.exists():
        scores["outputs_exist"] = 1.0

    csv_rows = _safe_csv_dicts(input_csv) if input_csv.exists() else None
    notes_text = _read_text(input_notes) if input_notes.exists() else None
    expected = None
    if csv_rows is not None:
        expected = _compute_expected_from_csv(csv_rows)

    stats_json = _load_json(out_stats) if out_stats.exists() else None
    update_md = _read_text(out_update) if out_update.exists() else None
    messages_json = _load_json(out_messages) if out_messages.exists() else None

    if expected is not None and stats_json is not None:
        try:
            ej = stats_json
            if (
                isinstance(ej, dict)
                and isinstance(ej.get("totals"), dict)
                and isinstance(ej.get("rates"), dict)
                and isinstance(ej.get("per_game"), list)
            ):
                totals_ok = True
                for k, v in expected["totals"].items():
                    if ej["totals"].get(k) != v:
                        totals_ok = False
                        break
                per_ok = True
                if len(ej["per_game"]) != len(expected["per_game"]):
                    per_ok = False
                else:
                    for eg, pg in zip(expected["per_game"], ej["per_game"]):
                        for k in [
                            "date", "opponent", "at_bats", "hits", "walks", "hbp", "sac_flies",
                            "doubles", "triples", "home_runs", "runs", "rbi", "stolen_bases",
                            "strikeouts", "total_bases"
                        ]:
                            if pg.get(k) != eg.get(k):
                                per_ok = False
                                break
                        if not per_ok:
                            break
                rates_ok = True
                for rk in ["batting_average", "obp", "slg", "ops"]:
                    val = ej["rates"].get(rk)
                    if not isinstance(val, (int, float)):
                        rates_ok = False
                        break
                    if _round3(float(val)) != expected["rates"][rk]:
                        rates_ok = False
                        break
                if totals_ok:
                    scores["weekly_stats_json_values_correct"] = 1.0
                if per_ok:
                    scores["weekly_stats_json_per_game_correct"] = 1.0
                if rates_ok:
                    scores["weekly_stats_rates_rounded_3dp"] = 1.0
        except Exception:
            pass

    stats_summary_parsed = None
    if expected is not None and update_md:
        lines = update_md.splitlines()
        first_idx = None
        for i, line in enumerate(lines):
            if line.strip() != "":
                first_idx = i
                break
        if first_idx is not None:
            title_line = _normalize_heading(lines[first_idx])
            expected_title = f"Weekly Update: {expected['min_date']} to {expected['max_date']}"
            if title_line == expected_title:
                scores["weekly_update_title_and_range_correct"] = 1.0
        stats_idx_list = _find_section_indices(lines, "Stats Summary")
        focus_idx_list = _find_section_indices(lines, "Next Week Focus")
        if stats_idx_list and focus_idx_list:
            stats_idx = stats_idx_list[0]
            focus_idx = focus_idx_list[0]
            if first_idx is not None and stats_idx > first_idx:
                intro_text = _extract_intro(lines, first_idx, stats_idx)
                if messages_json and isinstance(messages_json, dict):
                    weekly_update_text = messages_json.get("weekly_update", "")
                    norm_intro = re.sub(r"\s+", " ", intro_text.strip())
                    norm_msg = re.sub(r"\s+", " ", str(weekly_update_text).strip())
                    if norm_intro == norm_msg and norm_intro != "":
                        scores["weekly_update_intro_matches_rewritten"] = 1.0
                if intro_text:
                    if _word_count(intro_text) <= 120:
                        scores["weekly_update_intro_length_limit"] = 1.0
            if focus_idx > stats_idx:
                stats_section = "\n".join(lines[stats_idx + 1:focus_idx]).strip()
                parsed = _parse_stats_summary(stats_section) if stats_section else None
                if parsed is not None:
                    stats_summary_parsed = parsed
                    scores["weekly_update_stats_summary_parsed"] = 1.0
                    exp_ba = expected["rates"]["batting_average"]
                    exp_obp = expected["rates"]["obp"]
                    exp_slg = expected["rates"]["slg"]
                    exp_ops = expected["rates"]["ops"]
                    floats_match = (
                        _round3(parsed["BA"]) == exp_ba and
                        _round3(parsed["OBP"]) == exp_obp and
                        _round3(parsed["SLG"]) == exp_slg and
                        _round3(parsed["OPS"]) == exp_ops
                    )
                    ints_match = True
                    mapping = {
                        "AB": "at_bats",
                        "H": "hits",
                        "HR": "home_runs",
                        "2B": "doubles",
                        "3B": "triples",
                        "BB": "walks",
                        "HBP": "hbp",
                        "SF": "sac_flies",
                        "R": "runs",
                        "RBI": "rbi",
                        "SB": "stolen_bases",
                        "K": "strikeouts",
                    }
                    for mk, tk in mapping.items():
                        if parsed.get(mk) != expected["totals"][tk]:
                            ints_match = False
                            break
                    if floats_match and ints_match:
                        scores["stats_summary_matches_expected"] = 1.0
                    if stats_json and isinstance(stats_json, dict):
                        try:
                            jr = stats_json.get("rates", {})
                            jt = stats_json.get("totals", {})
                            json_match = True
                            if (
                                _round3(float(jr.get("batting_average", -1))) != _round3(parsed["BA"]) or
                                _round3(float(jr.get("obp", -1))) != _round3(parsed["OBP"]) or
                                _round3(float(jr.get("slg", -1))) != _round3(parsed["SLG"]) or
                                _round3(float(jr.get("ops", -1))) != _round3(parsed["OPS"])
                            ):
                                json_match = False
                            for mk, tk in mapping.items():
                                if jt.get(tk) != parsed.get(mk):
                                    json_match = False
                                    break
                            if json_match:
                                scores["stats_summary_matches_json"] = 1.0
                        except Exception:
                            pass
        if focus_idx_list:
            focus_idx = focus_idx_list[0]
            bullets = []
            for l in lines[focus_idx + 1:]:
                if l.strip().startswith(("-", "*")):
                    m = re.match(r"^\s*[-*]\s+(.*)$", l.strip())
                    if m:
                        bullets.append(m.group(1).strip())
                elif l.strip() == "":
                    continue
                else:
                    continue
            if len(bullets) == 3:
                scores["next_week_focus_three_bullets"] = 1.0
                length_ok = all(_word_count(b) <= 12 for b in bullets)
                kw_ok = False
                if notes_text:
                    focus_items = _parse_draft_focus_items(notes_text)
                    if len(focus_items) >= 3:
                        req_sets = [
                            {"fastball", "fastballs", "high", "zone"},
                            {"spin", "breaking"},
                            {"footwork", "3b", "third"},
                        ]
                        def norm(s: str) -> str:
                            return re.sub(r"[^\w\s]", "", s.lower())
                        bullet_tokens = [set(norm(b).split()) for b in bullets]
                        per_bullet_ok = []
                        for i in range(3):
                            req = req_sets[i]
                            bt = bullet_tokens[i]
                            found = any(r in bt for r in req)
                            per_bullet_ok.append(found)
                        kw_ok = all(per_bullet_ok)
                if length_ok and kw_ok:
                    scores["next_week_focus_bullets_length_and_keywords"] = 1.0

    if messages_json and isinstance(messages_json, dict):
        has_keys = ("weekly_update" in messages_json) and ("coach_dm" in messages_json)
        if has_keys:
            scores["rewritten_messages_json_keys_present"] = 1.0
            w_update = str(messages_json.get("weekly_update", ""))
            coach_dm = str(messages_json.get("coach_dm", ""))
            if w_update and _word_count(w_update) <= 120 and coach_dm and _word_count(coach_dm) <= 80:
                scores["rewritten_messages_length_limits"] = 1.0
            banned_ok = not _contains_banned_terms(w_update) and not _contains_banned_terms(coach_dm)
            if banned_ok:
                scores["rewritten_messages_avoid_slang_apologies"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()