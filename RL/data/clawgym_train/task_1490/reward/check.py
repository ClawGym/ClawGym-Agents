import csv
import json
import re
import sys
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


class ScheduleTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_schedule_table = False
        self.in_tbody = False
        self.in_row = False
        self.in_cell = False
        self.current_cells: List[str] = []
        self.current_text = ""
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attr_dict = dict(attrs)
            if attr_dict.get("id") == "schedule":
                self.in_schedule_table = True
        elif self.in_schedule_table and tag == "tbody":
            self.in_tbody = True
        elif self.in_tbody and tag == "tr":
            self.in_row = True
            self.current_cells = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.current_text = ""

    def handle_data(self, data):
        if self.in_cell:
            self.current_text += data

    def handle_endtag(self, tag):
        if self.in_row and self.in_cell and tag in ("td", "th"):
            self.current_cells.append(self.current_text.strip())
            self.in_cell = False
        elif self.in_tbody and tag == "tr":
            if self.current_cells:
                self.rows.append(self.current_cells)
            self.in_row = False
        elif self.in_schedule_table and tag == "tbody":
            self.in_tbody = False
        elif self.in_schedule_table and tag == "table":
            self.in_schedule_table = False


def parse_schedule_html(html_text: Optional[str]) -> List[Dict[str, str]]:
    if not html_text:
        return []
    parser = ScheduleTableParser()
    try:
        parser.feed(html_text)
    except Exception:
        return []
    games = []
    for cells in parser.rows:
        if len(cells) < 4:
            continue
        date_str = cells[0]
        opponent = cells[1]
        location = cells[2]
        kickoff = cells[3]
        try:
            dt = datetime.strptime(date_str, "%b %d, %Y")
            iso_date = dt.strftime("%Y-%m-%d")
        except Exception:
            continue
        try:
            t24 = datetime.strptime(kickoff.strip(), "%I:%M %p").strftime("%H:%M")
        except Exception:
            try:
                t24 = kickoff.strip()
                if re.match(r"^\d{1,2}:\d{2}$", t24):
                    parts = t24.split(":")
                    h = int(parts[0])
                    m = int(parts[1])
                    if 0 <= h <= 23 and 0 <= m <= 59:
                        t24 = f"{h:02d}:{m:02d}"
                    else:
                        continue
                else:
                    continue
            except Exception:
                continue
        games.append(
            {
                "game_date": iso_date,
                "opponent": opponent.strip(),
                "home_away": location.strip(),
                "kickoff_time_local": t24,
                "weekday_full": dt.strftime("%A"),
                "weekday_abbr": dt.strftime("%a"),
            }
        )
    return games


def parse_engagement_csv(path: Path) -> Dict[Tuple[str, str], List[Tuple[str, int]]]:
    mapping: Dict[Tuple[str, str], List[Tuple[str, int]]] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                wd = (row.get("weekday") or "").strip()
                ts = (row.get("time_slot") or "").strip()
                ch = (row.get("channel") or "").strip()
                ei_raw = (row.get("engagement_index") or "").strip()
                if not (wd and ts and ch and ei_raw):
                    return {}
                try:
                    ei = int(ei_raw)
                except Exception:
                    return {}
                mapping.setdefault((wd, ch), []).append((ts, ei))
    except Exception:
        return {}
    return mapping


def _strip_quotes(val: str) -> str:
    v = val.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
        return v[1:-1]
    return v


def _find_line_index(lines: List[str], pattern: str) -> int:
    rx = re.compile(pattern)
    for i, line in enumerate(lines):
        if rx.match(line):
            return i
    return -1


def parse_config_yaml(path: Path) -> Dict:
    text = safe_read_text(path)
    result = {
        "default_channel": None,
        "hashtags": [],
        "pillars": {},
        "templates": {
            "angle_label": {"home": None, "away": None},
            "outline": {"home": [], "away": []},
        },
    }
    if not text:
        return result
    lines = text.splitlines()

    # default_channel
    dc_match = None
    for line in lines:
        m = re.match(r'^\s*default_channel\s*:\s*(.+?)\s*$', line)
        if m:
            dc_match = _strip_quotes(m.group(1))
            break
    result["default_channel"] = dc_match

    # hashtags list
    hashtags_idx = _find_line_index(lines, r'^\s*hashtags\s*:\s*$')
    if hashtags_idx != -1:
        header_indent = len(lines[hashtags_idx]) - len(lines[hashtags_idx].lstrip(" "))
        for i in range(hashtags_idx + 1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= header_indent:
                break
            m = re.match(r'^\s*-\s*(.+?)\s*$', line)
            if m:
                val = _strip_quotes(m.group(1))
                result["hashtags"].append(val)
            else:
                if indent > header_indent:
                    continue
                break

    # pillars
    pillars_idx = _find_line_index(lines, r'^\s*pillars\s*:\s*$')
    if pillars_idx != -1:
        p_indent = len(lines[pillars_idx]) - len(lines[pillars_idx].lstrip(" "))
        current_key = None
        current_key_indent = None
        for i in range(pillars_idx + 1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= p_indent:
                break
            mk = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*$', line)
            if mk and indent > p_indent:
                current_key = mk.group(1)
                current_key_indent = indent
                result["pillars"].setdefault(current_key, {"name": None, "description": None})
                continue
            if current_key is not None and current_key_indent is not None and indent > current_key_indent:
                mn = re.match(r'^\s*name\s*:\s*(.+?)\s*$', line)
                md = re.match(r'^\s*description\s*:\s*(.+?)\s*$', line)
                if mn:
                    result["pillars"][current_key]["name"] = _strip_quotes(mn.group(1))
                if md:
                    result["pillars"][current_key]["description"] = _strip_quotes(md.group(1))

    # templates.angle_label and outline
    templates_idx = _find_line_index(lines, r'^\s*templates\s*:\s*$')
    if templates_idx != -1:
        t_indent = len(lines[templates_idx]) - len(lines[templates_idx].lstrip(" "))
        section = None
        section_indent = None
        subsection = None
        subsection_indent = None
        for i in range(templates_idx + 1, len(lines)):
            line = lines[i]
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip(" "))
            if indent <= t_indent:
                break
            mk = re.match(r'^\s*([A-Za-z0-9_]+)\s*:\s*$', line)
            if mk and indent > t_indent:
                section = mk.group(1)
                section_indent = indent
                subsection = None
                subsection_indent = None
                continue
            if section == "angle_label" and section_indent is not None:
                if indent > section_indent:
                    mh = re.match(r'^\s*home\s*:\s*(.+?)\s*$', line)
                    ma = re.match(r'^\s*away\s*:\s*(.+?)\s*$', line)
                    if mh:
                        result["templates"]["angle_label"]["home"] = _strip_quotes(mh.group(1))
                    if ma:
                        result["templates"]["angle_label"]["away"] = _strip_quotes(ma.group(1))
            if section == "outline" and section_indent is not None:
                if indent > section_indent:
                    ssm = re.match(r'^\s*(home|away)\s*:\s*$', line)
                    if ssm:
                        subsection = ssm.group(1)
                        subsection_indent = indent
                        continue
                    if subsection in ("home", "away") and subsection_indent is not None and indent > subsection_indent:
                        lm = re.match(r'^\s*-\s*(.+?)\s*$', line)
                        if lm:
                            result["templates"]["outline"][subsection].append(_strip_quotes(lm.group(1)))

    return result


def load_calendar_csv(path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return [], []
            header = rows[0]
            dict_rows: List[Dict[str, str]] = []
            for r in rows[1:]:
                if len(r) < len(header):
                    continue
                row_dict = {header[i]: r[i].strip() for i in range(len(header))}
                dict_rows.append(row_dict)
            return header, dict_rows
    except Exception:
        return [], []


def compute_recommended_time(engagement: Dict[Tuple[str, str], List[Tuple[str, int]]],
                             weekday_full: str,
                             channel: Optional[str]) -> Optional[str]:
    if not channel:
        return None
    options = engagement.get((weekday_full, channel), [])
    if not options:
        return None
    best_idx = None
    best_time = None
    for t, idx in options:
        try:
            if re.match(r"^\d{1,2}:\d{2}$", t):
                parts = t.split(":")
                h = int(parts[0])
                m = int(parts[1])
                norm_t = f"{h:02d}:{m:02d}"
            else:
                dt = datetime.strptime(t.strip(), "%H:%M")
                norm_t = dt.strftime("%H:%M")
        except Exception:
            continue
        if best_idx is None or idx > best_idx or (idx == best_idx and (best_time is None or norm_t < best_time)):
            best_idx = idx
            best_time = norm_t
    return best_time


def slugify_opponent(name: str) -> str:
    s = name.lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def parse_json_file(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_game_day_pillar_present": 0.0,
        "config_hashtags_include_gojacks": 0.0,
        "config_default_channel_twitter": 0.0,
        "calendar_header_correct": 0.0,
        "calendar_row_count_matches_schedule": 0.0,
        "calendar_core_fields_correct": 0.0,
        "calendar_channel_pillars_hashtags_angle_correct": 0.0,
        "recommended_post_times_correct": 0.0,
        "briefs_files_present": 0.0,
        "briefs_core_fields_correct": 0.0,
        "briefs_hashtags_correct": 0.0,
        "briefs_copy_outline_correct": 0.0,
    }

    schedule_path = workspace / "input" / "schedule.html"
    engagement_path = workspace / "input" / "engagement.csv"
    config_path = workspace / "config" / "marketing.yml"
    calendar_path = workspace / "output" / "calendar.csv"
    briefs_dir = workspace / "output" / "briefs"

    schedule_text = safe_read_text(schedule_path)
    games = parse_schedule_html(schedule_text)
    engagement = parse_engagement_csv(engagement_path)
    config = parse_config_yaml(config_path)
    default_channel = config.get("default_channel")
    hashtags = config.get("hashtags") or []
    pillars = config.get("pillars") or {}
    templates = config.get("templates") or {}
    angle_label_home = templates.get("angle_label", {}).get("home")
    angle_label_away = templates.get("angle_label", {}).get("away")
    outline_home = templates.get("outline", {}).get("home") or []
    outline_away = templates.get("outline", {}).get("away") or []

    gd = pillars.get("game_day") or {}
    has_game_day = isinstance(gd, dict) and gd.get("name") == "Game Day" and gd.get("description") == "Hype posts on the day of the game"
    if has_game_day:
        scores["config_game_day_pillar_present"] = 1.0

    has_gojacks = any(h.strip() == "#GoJacks" for h in hashtags)
    if has_gojacks:
        scores["config_hashtags_include_gojacks"] = 1.0

    # Only award default_channel if all required config updates appear applied
    if has_game_day and has_gojacks and default_channel == "Twitter":
        scores["config_default_channel_twitter"] = 1.0

    campus_spirit_name = (pillars.get("campus_spirit") or {}).get("name") or "Campus Spirit"
    road_warriors_name = (pillars.get("road_warriors") or {}).get("name") or "Road Warriors"

    header, calendar_rows = load_calendar_csv(calendar_path)
    expected_header = [
        "game_date",
        "opponent",
        "home_away",
        "kickoff_time_local",
        "weekday",
        "channel",
        "recommended_post_time",
        "pillar_primary",
        "pillar_secondary",
        "primary_hashtags",
        "angle_label",
    ]
    if header == expected_header:
        scores["calendar_header_correct"] = 1.0

    if games and calendar_rows:
        if len(calendar_rows) == len(games):
            scores["calendar_row_count_matches_schedule"] = 1.0
    else:
        scores["calendar_row_count_matches_schedule"] = 0.0

    expected_map: Dict[Tuple[str, str], Dict[str, str]] = {}
    for g in games:
        game_date = g["game_date"]
        opponent = g["opponent"]
        home_away = g["home_away"]
        kickoff_time_local = g["kickoff_time_local"]
        weekday_abbr = g["weekday_abbr"]
        weekday_full = g["weekday_full"]
        rec_time = compute_recommended_time(engagement, weekday_full, default_channel) or ""
        pillar_primary = "Game Day"
        pillar_secondary = campus_spirit_name if home_away == "Home" else road_warriors_name
        primary_hashtags = ";".join(hashtags)
        angle_label = angle_label_home if home_away == "Home" else angle_label_away
        expected_map[(game_date, opponent)] = {
            "game_date": game_date,
            "opponent": opponent,
            "home_away": home_away,
            "kickoff_time_local": kickoff_time_local,
            "weekday": weekday_abbr,
            "channel": default_channel or "",
            "recommended_post_time": rec_time,
            "pillar_primary": pillar_primary,
            "pillar_secondary": pillar_secondary,
            "primary_hashtags": primary_hashtags,
            "angle_label": angle_label or "",
        }

    core_pass = 0
    core_total = max(len(games), 1)
    channel_pillar_hash_angle_pass = 0
    channel_total = max(len(games), 1)
    recommend_pass = 0
    recommend_total = max(len(games), 1)

    if calendar_rows and expected_map:
        cal_map: Dict[Tuple[str, str], Dict[str, str]] = {}
        for r in calendar_rows:
            key = (r.get("game_date", ""), r.get("opponent", ""))
            cal_map[key] = r

        for key, expected in expected_map.items():
            r = cal_map.get(key)
            if not r:
                continue
            if (
                r.get("game_date") == expected["game_date"]
                and r.get("opponent") == expected["opponent"]
                and r.get("home_away") == expected["home_away"]
                and r.get("kickoff_time_local") == expected["kickoff_time_local"]
                and r.get("weekday") == expected["weekday"]
            ):
                core_pass += 1
            cal_tokens = [t.strip() for t in (r.get("primary_hashtags") or "").split(";") if t.strip() != ""]
            if (
                r.get("channel") == expected["channel"]
                and r.get("pillar_primary") == expected["pillar_primary"]
                and r.get("pillar_secondary") == expected["pillar_secondary"]
                and cal_tokens == hashtags
                and r.get("angle_label") == expected["angle_label"]
            ):
                channel_pillar_hash_angle_pass += 1
            if r.get("recommended_post_time") == expected["recommended_post_time"]:
                recommend_pass += 1

    if core_total > 0:
        scores["calendar_core_fields_correct"] = float(core_pass) / float(core_total)
        scores["calendar_channel_pillars_hashtags_angle_correct"] = float(channel_pillar_hash_angle_pass) / float(
            channel_total
        )
        scores["recommended_post_times_correct"] = float(recommend_pass) / float(recommend_total)
    else:
        scores["calendar_core_fields_correct"] = 0.0
        scores["calendar_channel_pillars_hashtags_angle_correct"] = 0.0
        scores["recommended_post_times_correct"] = 0.0

    expected_briefs: Dict[Path, Dict] = {}
    for g in games:
        ymd = g["game_date"].replace("-", "")
        slug = slugify_opponent(g["opponent"])
        p = briefs_dir / f"{ymd}_{slug}.json"
        expected_angle_label = angle_label_home if g["home_away"] == "Home" else angle_label_away
        expected_outline_template = outline_home if g["home_away"] == "Home" else outline_away
        expected_outline: List[str] = []
        for line in expected_outline_template:
            s = line.replace("{opponent}", g["opponent"]).replace("{kickoff_time}", g["kickoff_time_local"])
            expected_outline.append(s)
        expected_briefs[p] = {
            "game_date": g["game_date"],
            "opponent": g["opponent"],
            "opponent_slug": slug,
            "home_away": g["home_away"],
            "kickoff_time_local": g["kickoff_time_local"],
            "weekday": g["weekday_abbr"],
            "channel": default_channel or "",
            "recommended_post_time": compute_recommended_time(engagement, g["weekday_full"], default_channel) or "",
            "pillars": {
                "primary": "Game Day",
                "secondary": campus_spirit_name if g["home_away"] == "Home" else road_warriors_name,
            },
            "hashtags_set": set(hashtags + ["#GameDay"]),
            "angle_label": expected_angle_label or "",
            "copy_outline": expected_outline,
        }

    present_count = 0
    core_fields_ok = 0
    hashtags_ok = 0
    copy_outline_ok = 0
    briefs_total = max(len(expected_briefs), 1)

    for p, exp in expected_briefs.items():
        data = parse_json_file(p)
        if data is None:
            continue
        present_count += 1
        core_ok = True
        core_ok = core_ok and data.get("game_date") == exp["game_date"]
        core_ok = core_ok and data.get("opponent") == exp["opponent"]
        core_ok = core_ok and data.get("opponent_slug") == exp["opponent_slug"]
        core_ok = core_ok and data.get("home_away") == exp["home_away"]
        core_ok = core_ok and data.get("kickoff_time_local") == exp["kickoff_time_local"]
        core_ok = core_ok and data.get("weekday") == exp["weekday"]
        core_ok = core_ok and data.get("channel") == exp["channel"]
        core_ok = core_ok and data.get("recommended_post_time") == exp["recommended_post_time"]
        pillars_obj = data.get("pillars")
        if isinstance(pillars_obj, dict):
            core_ok = core_ok and pillars_obj.get("primary") == "Game Day"
            core_ok = core_ok and pillars_obj.get("secondary") == exp["pillars"]["secondary"]
        else:
            core_ok = False
        core_ok = core_ok and data.get("angle_label") == exp["angle_label"]
        if core_ok:
            core_fields_ok += 1

        hs = data.get("hashtags")
        if isinstance(hs, list):
            normalized = [str(x).strip() for x in hs]
            has_gojacks_in_brief = "#GoJacks" in normalized
            has_gameday = "#GameDay" in normalized
            # Must exactly match config hashtags + #GameDay (order-independent)
            if has_gojacks_in_brief and has_gameday and set(normalized) == exp["hashtags_set"]:
                hashtags_ok += 1

        co = data.get("copy_outline")
        if isinstance(co, list) and all(isinstance(x, str) for x in co):
            if co == exp["copy_outline"]:
                copy_outline_ok += 1

    scores["briefs_files_present"] = float(present_count) / float(briefs_total) if briefs_total > 0 else 0.0
    scores["briefs_core_fields_correct"] = float(core_fields_ok) / float(briefs_total) if briefs_total > 0 else 0.0
    scores["briefs_hashtags_correct"] = float(hashtags_ok) / float(briefs_total) if briefs_total > 0 else 0.0
    scores["briefs_copy_outline_correct"] = float(copy_outline_ok) / float(briefs_total) if briefs_total > 0 else 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()