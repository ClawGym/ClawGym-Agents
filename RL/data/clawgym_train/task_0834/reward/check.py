import json
import csv
import re
import sys
from pathlib import Path
from html.parser import HTMLParser


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _safe_load_json(path: Path):
    try:
        text = _safe_read_text(path)
        if not text:
            return None
        return json.loads(text)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _to_int(val, default=0):
    try:
        if isinstance(val, int):
            return val
        s = str(val).strip()
        if s == "":
            return default
        return int(s)
    except Exception:
        return default


class _ScheduleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_tr = False
        self.current_tr_status = None
        self.in_target_tr = False
        self.in_td = False
        self._current_td_text = ""
        self._tds = []
        self.result = None  # (date, opponent, location)

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "tr":
            self.in_tr = True
            self.current_tr_status = None
            for k, v in attrs:
                if k.lower() == "data-status":
                    self.current_tr_status = v
            self.in_target_tr = (self.current_tr_status == "next")
            self._tds = []
        elif tag.lower() == "td" and self.in_tr and self.in_target_tr:
            self.in_td = True
            self._current_td_text = ""

    def handle_data(self, data):
        if self.in_td and self.in_target_tr:
            self._current_td_text += data

    def handle_endtag(self, tag):
        if tag.lower() == "td" and self.in_target_tr:
            txt = self._current_td_text.strip()
            self._tds.append(txt)
            self.in_td = False
            self._current_td_text = ""
        elif tag.lower() == "tr":
            if self.in_target_tr and len(self._tds) >= 3:
                date = self._tds[0].strip()
                opponent = self._tds[1].strip()
                location = self._tds[2].strip()
                self.result = (date, opponent, location)
            self.in_tr = False
            self.in_target_tr = False
            self.current_tr_status = None
            self._tds = []


def _parse_schedule_next(path: Path):
    html = _safe_read_text(path)
    if not html:
        return None
    parser = _ScheduleParser()
    try:
        parser.feed(html)
        return parser.result
    except Exception:
        return None


def _compute_expected_top_performers(stats_csv: Path, roster_json: Path):
    roster = _safe_load_json(roster_json)
    if not isinstance(roster, list):
        return None
    roster_map = {}
    for r in roster:
        try:
            name = r.get("name")
            if not name:
                continue
            roster_map[name] = {
                "number": r.get("number"),
                "position": r.get("position"),
                "class": r.get("class"),
            }
        except Exception:
            continue

    headers, rows = _safe_load_csv_dicts(stats_csv)
    if headers is None or rows is None:
        return None

    required_fields = [
        "game_date", "opponent", "player", "number", "position",
        "rushing_yards", "receiving_yards", "passing_yards",
        "td_rush", "td_rec", "td_pass", "tackles"
    ]
    if any(field not in headers for field in required_fields):
        return None

    agg = {}
    for row in rows:
        player = row.get("player", "").strip()
        if player not in roster_map:
            continue
        ry = _to_int(row.get("rushing_yards", 0))
        recy = _to_int(row.get("receiving_yards", 0))
        py = _to_int(row.get("passing_yards", 0))
        tr = _to_int(row.get("td_rush", 0))
        trec = _to_int(row.get("td_rec", 0))
        tp = _to_int(row.get("td_pass", 0))
        if player not in agg:
            agg[player] = {
                "player": player,
                "games_played": 0,
                "total_touchdowns": 0,
                "total_yards": 0,
            }
        agg[player]["games_played"] += 1
        agg[player]["total_touchdowns"] += tr + trec + tp
        agg[player]["total_yards"] += ry + recy + py

    items = []
    for player, stats in agg.items():
        rinfo = roster_map.get(player, {})
        items.append({
            "player": player,
            "number": rinfo.get("number"),
            "position": rinfo.get("position"),
            "class": rinfo.get("class"),
            "games_played": stats["games_played"],
            "total_touchdowns": stats["total_touchdowns"],
            "total_yards": stats["total_yards"],
        })

    items.sort(key=lambda x: (-_to_int(x["total_touchdowns"]), -_to_int(x["total_yards"]), x["player"]))

    expected = []
    for idx, item in enumerate(items[:5], start=1):
        row = {
            "rank": idx,
            "player": item["player"],
            "number": _to_int(item["number"]),
            "position": item["position"],
            "class": item["class"],
            "games_played": _to_int(item["games_played"]),
            "total_touchdowns": _to_int(item["total_touchdowns"]),
            "total_yards": _to_int(item["total_yards"]),
        }
        expected.append(row)

    return expected


def _parse_top_performers_output(path: Path):
    headers, rows = _safe_load_csv_dicts(path)
    if headers is None or rows is None:
        return None, None, False
    required_headers = ["rank", "player", "number", "position", "class", "games_played", "total_touchdowns", "total_yards"]
    header_ok = headers == required_headers
    parsed_rows = []
    ok = True
    for row in rows:
        try:
            parsed_rows.append({
                "rank": _to_int(row.get("rank")),
                "player": row.get("player", "").strip(),
                "number": _to_int(row.get("number")),
                "position": row.get("position", "").strip(),
                "class": row.get("class", "").strip(),
                "games_played": _to_int(row.get("games_played")),
                "total_touchdowns": _to_int(row.get("total_touchdowns")),
                "total_yards": _to_int(row.get("total_yards")),
            })
        except Exception:
            ok = False
            break
    return required_headers, parsed_rows, (ok and header_ok)


def _extract_focus_points(editor_notes_path: Path):
    text = _safe_read_text(editor_notes_path)
    if not text:
        return []
    lines = text.splitlines()
    focus_points = []
    in_focus = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Focus:"):
            in_focus = True
            continue
        if in_focus:
            if stripped == "":
                break
            if stripped.startswith("-"):
                fp = stripped.lstrip("-").strip()
                if fp:
                    focus_points.append(fp)
            else:
                break
    return focus_points


def _extract_actions_and_coach(editor_notes_path: Path):
    text = _safe_read_text(editor_notes_path)
    if not text:
        return [], []
    lines = text.splitlines()
    actions = []
    coaches = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ACTION:"):
            actions.append(stripped)
        if stripped.startswith("Coach:"):
            name = stripped.split(":", 1)[1].strip()
            if name:
                coaches.append(name)
    return actions, coaches


def _find_section(lines, header_name):
    header_pat = re.compile(r"^\s*#*\s*{}\s*$".format(re.escape(header_name)), re.IGNORECASE)
    start = None
    for i, line in enumerate(lines):
        if header_pat.match(line):
            start = i + 1
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start, len(lines)):
        if header_pat.match(lines[j]):
            end = j
            break
        other_header_pat = re.compile(r"^\s*#*\s*Action Items\s*$", re.IGNORECASE) if header_name.lower() == "meeting notes" else re.compile(r"^\s*#*\s*Meeting Notes\s*$", re.IGNORECASE)
        if other_header_pat.match(lines[j]):
            end = j
            break
    return start, end


def _get_nonempty_lines(lines, start_idx=0):
    return [ln for ln in lines[start_idx:] if ln.strip() != ""]


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_stats = workspace / "input" / "stats" / "fitchburg_box_scores.csv"
    input_roster = workspace / "input" / "roster.json"
    input_schedule = workspace / "input" / "schedule.html"
    input_editor = workspace / "input" / "editor_notes.md"

    output_top = workspace / "output" / "top_performers.csv"
    output_article = workspace / "output" / "preview_article.md"
    output_meeting = workspace / "output" / "meeting_notes.md"

    scores = {
        "top_performers_structure": 0.0,
        "top_performers_values_and_order": 0.0,
        "preview_headline_and_dek": 0.0,
        "preview_paragraphs_and_matchup": 0.0,
        "preview_top_player_highlight": 0.0,
        "preview_focus_and_rivalry": 0.0,
        "meeting_notes_sections_and_metadata": 0.0,
        "meeting_notes_top3_bullets": 0.0,
        "meeting_notes_actions_from_editor": 0.0,
        "meeting_notes_auto_photo_coverage": 0.0,
        "meeting_notes_auto_photo_assignments": 0.0,
        "meeting_notes_auto_coach_quote": 0.0,
    }

    expected_top = _compute_expected_top_performers(input_stats, input_roster)
    headers, produced_rows, header_ok = _parse_top_performers_output(output_top)

    if header_ok and produced_rows is not None and len(produced_rows) == 5:
        scores["top_performers_structure"] = 1.0
    else:
        scores["top_performers_structure"] = 0.0

    if expected_top is not None and produced_rows is not None and len(produced_rows) == len(expected_top):
        content_ok = True
        for i, exp_row in enumerate(expected_top):
            got = produced_rows[i]
            if not (
                got["rank"] == exp_row["rank"]
                and got["player"] == exp_row["player"]
                and got["number"] == exp_row["number"]
                and got["position"] == exp_row["position"]
                and got["class"] == exp_row["class"]
                and got["games_played"] == exp_row["games_played"]
                and got["total_touchdowns"] == exp_row["total_touchdowns"]
                and got["total_yards"] == exp_row["total_yards"]
            ):
                content_ok = False
                break
        scores["top_performers_values_and_order"] = 1.0 if content_ok else 0.0
    else:
        scores["top_performers_values_and_order"] = 0.0

    next_info = _parse_schedule_next(input_schedule)
    if next_info:
        next_date, next_opponent, next_location = next_info
    else:
        next_date, next_opponent, next_location = None, None, None

    article_text = _safe_read_text(output_article)
    if article_text:
        lines = article_text.splitlines()
        nonempty = [ln for ln in lines if ln.strip() != ""]
        headline = nonempty[0].strip() if len(nonempty) >= 1 else ""
        dek = nonempty[1].strip() if len(nonempty) >= 2 else ""

        headline_ok = False
        if next_opponent:
            required_phrase = f"Fitchburg vs {next_opponent} Preview"
            if required_phrase.lower() in headline.lower():
                headline_ok = True

        dek_ok = False
        if next_location and next_date:
            if (next_location.lower() in dek.lower()) and (next_date in dek):
                dek_ok = True

        if headline_ok and dek_ok:
            scores["preview_headline_and_dek"] = 1.0

        idxs = [i for i, ln in enumerate(lines) if ln.strip() != ""]
        start_idx = idxs[1] + 1 if len(idxs) >= 2 else len(lines)
        paras = []
        current = []
        for ln in lines[start_idx:]:
            if ln.strip() == "":
                if current:
                    paras.append(" ".join([x.strip() for x in current if x.strip() != ""]).strip())
                    current = []
            else:
                current.append(ln)
        if current:
            paras.append(" ".join([x.strip() for x in current if x.strip() != ""]).strip())

        paras_ok = len(paras) >= 3

        p1_ok = False
        if paras_ok and next_opponent and next_location:
            p1 = paras[0]
            if (next_opponent.lower() in p1.lower()) and (next_location.lower() in p1.lower()):
                p1_ok = True

        p2_ok = False
        other_player_ok = False
        if paras_ok and produced_rows and len(produced_rows) >= 2:
            p2 = paras[1]
            top1 = produced_rows[0]
            top1_name = top1["player"]
            top1_td = str(top1["total_touchdowns"])
            top1_yds = str(top1["total_yards"])
            top1_cls = str(top1["class"])
            top1_num = str(top1["number"])
            if (top1_name in p2) and (top1_td in p2) and (top1_yds in p2) and (top1_cls in p2) and (top1_num in p2):
                p2_ok = True
            others = [r["player"] for r in produced_rows[1:]]
            for nm in others:
                if nm in p2:
                    other_player_ok = True
                    break

        p3_ok = False
        rivalry_ok = False
        if paras_ok:
            p3 = paras[2]
            focus_points = _extract_focus_points(input_editor)
            if focus_points:
                for fp in focus_points:
                    if fp and fp in p3:
                        p3_ok = True
                        break
            if next_opponent and next_opponent.lower() == "nashoba":
                if re.search(r"\brivalry\b", p3, re.IGNORECASE):
                    rivalry_ok = True
            else:
                rivalry_ok = True

        if paras_ok and p1_ok:
            scores["preview_paragraphs_and_matchup"] = 1.0
        if p2_ok and other_player_ok:
            scores["preview_top_player_highlight"] = 1.0
        if p3_ok and rivalry_ok:
            scores["preview_focus_and_rivalry"] = 1.0

    meeting_text = _safe_read_text(output_meeting)
    if meeting_text:
        m_lines = meeting_text.splitlines()
        meeting_start, meeting_end = _find_section(m_lines, "Meeting Notes")
        action_start, action_end = _find_section(m_lines, "Action Items")

        sections_ok = (meeting_start is not None and action_start is not None)
        metadata_ok = False
        top3_ok = False
        actions_ok = False
        photo_cov_ok = False
        photo_assign_ok = False
        coach_ok = False

        if sections_ok and next_opponent and next_date and next_location:
            meeting_section = "\n".join(m_lines[meeting_start:meeting_end if meeting_end is not None else len(m_lines)])
            if (next_opponent in meeting_section) and (next_date in meeting_section) and (next_location in meeting_section):
                metadata_ok = True

            bullets = []
            for ln in m_lines[meeting_start:meeting_end if meeting_end is not None else len(m_lines)]:
                if re.match(r"^\s*[-*]\s+", ln):
                    bullets.append(ln.strip())

            if produced_rows and len(produced_rows) >= 3 and bullets:
                top3 = produced_rows[:3]
                matched_all = True
                for item in top3:
                    name = item["player"]
                    num = str(item["number"])
                    cls = str(item["class"])
                    td = str(item["total_touchdowns"])
                    yds = str(item["total_yards"])
                    found = False
                    for b in bullets:
                        if (name in b) and (num in b) and (cls in b) and (td in b) and (yds in b):
                            found = True
                            break
                    if not found:
                        matched_all = False
                        break
                top3_ok = matched_all

        if sections_ok:
            scores["meeting_notes_sections_and_metadata"] = 1.0 if metadata_ok else 0.0
            scores["meeting_notes_top3_bullets"] = 1.0 if top3_ok else 0.0

        if action_start is not None:
            action_section_lines = m_lines[action_start:action_end if action_end is not None else len(m_lines)]
            action_bullets = [ln.strip() for ln in action_section_lines if re.match(r"^\s*[-*]\s+", ln)]
            action_texts = [re.sub(r"^\s*[-*]\s+", "", ln).strip() for ln in action_bullets]

            editor_actions, coaches = _extract_actions_and_coach(input_editor)
            if editor_actions:
                all_present = True
                for act in editor_actions:
                    if act not in action_texts:
                        all_present = False
                        break
                actions_ok = all_present
            else:
                actions_ok = False if any(t.startswith("ACTION:") for t in action_texts) else True

            if next_opponent and next_location:
                expected_photo_cov = f"Request photo coverage for next game vs {next_opponent} ({next_location})."
                photo_cov_ok = expected_photo_cov in action_texts

            if produced_rows and len(produced_rows) >= 3:
                p1 = produced_rows[0]
                p2 = produced_rows[1]
                p3 = produced_rows[2]
                seg1 = f"{p1['player']} (#{p1['number']}, {p1['class']})"
                seg2 = f"{p2['player']} (#{p2['number']}, {p2['class']})"
                seg3 = f"{p3['player']} (#{p3['number']}, {p3['class']})"
                found_assign = False
                for t in action_texts:
                    if t.lower().startswith("photo assignments:"):
                        if seg1 in t and seg2 in t and seg3 in t and "top 3" in t.lower():
                            found_assign = True
                            break
                photo_assign_ok = found_assign

            if coaches and len(coaches) == 1:
                coach_name = coaches[0]
                expected_coach = f"Call {coach_name} for a pregame quote."
                coach_ok = expected_coach in action_texts
            else:
                coach_ok = True if not coaches or len(coaches) != 1 else False

        scores["meeting_notes_actions_from_editor"] = 1.0 if actions_ok else 0.0
        scores["meeting_notes_auto_photo_coverage"] = 1.0 if photo_cov_ok else 0.0
        scores["meeting_notes_auto_photo_assignments"] = 1.0 if photo_assign_ok else 0.0
        scores["meeting_notes_auto_coach_quote"] = 1.0 if coach_ok else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()