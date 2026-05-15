import sys
import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _load_json_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_csv_dicts_safe(path: Path):
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            headers = reader.fieldnames or []
        return headers, rows
    except Exception:
        return None, None


class ProfileHTMLExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.last_h2_text = ""
        self.current_section = None  # 'strengths' or 'growth_areas' or None
        self.strengths = []
        self.growth_areas = []
        self._in_h2 = False
        self._h2_buf = []
        self._in_li = False
        self._li_buf = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "h2":
            self._in_h2 = True
            self._h2_buf = []
        elif tag.lower() == "ul":
            # Use last seen h2 to set section
            if self.last_h2_text.strip() == "Strengths":
                self.current_section = "strengths"
            elif self.last_h2_text.strip() == "Growth Areas":
                self.current_section = "growth_areas"
            else:
                self.current_section = None
        elif tag.lower() == "li":
            if self.current_section in ("strengths", "growth_areas"):
                self._in_li = True
                self._li_buf = []

    def handle_endtag(self, tag):
        if tag.lower() == "h2":
            self._in_h2 = False
            self.last_h2_text = "".join(self._h2_buf).strip()
            self._h2_buf = []
        elif tag.lower() == "ul":
            self.current_section = None
        elif tag.lower() == "li":
            if self._in_li:
                text = " ".join("".join(self._li_buf).split())
                if text:
                    if self.current_section == "strengths":
                        self.strengths.append(text)
                    elif self.current_section == "growth_areas":
                        self.growth_areas.append(text)
                self._in_li = False
                self._li_buf = []

    def handle_data(self, data):
        if self._in_h2:
            self._h2_buf.append(data)
        if self._in_li:
            self._li_buf.append(data)


def _compute_expected_metrics(game_logs_path: Path):
    headers, rows = _parse_csv_dicts_safe(game_logs_path)
    if not rows or not headers:
        return None
    # Required columns
    required = {"date", "opponent", "points", "rebounds", "assists", "fgm", "fga", "minutes"}
    if not required.issubset(set(h.strip() for h in headers)):
        return None
    try:
        total_points = 0
        total_rebounds = 0
        total_assists = 0
        total_minutes = 0
        total_fgm = 0
        total_fga = 0
        season_high_points = None
        season_high_row = None
        count = 0
        for r in rows:
            pts = int(str(r["points"]).strip())
            reb = int(str(r["rebounds"]).strip())
            ast = int(str(r["assists"]).strip())
            fgm = int(str(r["fgm"]).strip())
            fga = int(str(r["fga"]).strip())
            mins = int(str(r["minutes"]).strip())
            total_points += pts
            total_rebounds += reb
            total_assists += ast
            total_minutes += mins
            total_fgm += fgm
            total_fga += fga
            if season_high_points is None or pts > season_high_points:
                season_high_points = pts
                season_high_row = r
            count += 1
        if count == 0 or total_fga == 0:
            return None
        avg_points = round(total_points / count + 1e-12, 1)
        avg_rebounds = round(total_rebounds / count + 1e-12, 1)
        avg_assists = round(total_assists / count + 1e-12, 1)
        avg_minutes = round(total_minutes / count + 1e-12, 1)
        fg_pct = round((total_fgm / total_fga) * 100.0 + 1e-12, 1)
        metrics = {
            "avg_points": f"{avg_points:.1f}",
            "avg_rebounds": f"{avg_rebounds:.1f}",
            "avg_assists": f"{avg_assists:.1f}",
            "avg_minutes": f"{avg_minutes:.1f}",
            "fg_pct": f"{fg_pct:.1f}%",
            "season_high_points": str(int(season_high_points)),
            "season_high_opponent": str(season_high_row["opponent"]).strip(),
            "season_high_date": str(season_high_row["date"]).strip(),
        }
        return metrics
    except Exception:
        return None


def _load_metrics_csv(output_metrics_path: Path):
    headers, rows = _parse_csv_dicts_safe(output_metrics_path)
    if not rows or not headers:
        return None, None, None
    return headers, rows, {r.get("stat", "").strip(): str(r.get("value", "")).strip() for r in rows}


def _parse_profile_expected(html_path: Path):
    text = _read_text_safe(html_path)
    if not text:
        return None
    parser = ProfileHTMLExtractor()
    try:
        parser.feed(text)
        strengths = parser.strengths
        growth = parser.growth_areas
        if strengths is None or growth is None:
            return None
        return {"strengths": strengths, "growth_areas": growth}
    except Exception:
        return None


def _count_words(text: str) -> int:
    # Simple whitespace-based word count
    words = re.findall(r"\b\S+\b", text)
    return len(words)


def _contains_quoted(text: str, snippet: str) -> bool:
    # Check for exact snippet wrapped in common quotation styles
    patterns = [
        f"\"{snippet}\"",
        f"“{snippet}”",
        f"‘{snippet}’",
        f"'{snippet}'",
    ]
    for p in patterns:
        if p in text:
            return True
    return False


def _first_person_presence(text: str) -> bool:
    # check for common first-person indicators
    patterns = [
        r"\bI\b",
        r"\bI'm\b",
        r"\bI’m\b",
        r"\bI've\b",
        r"\bI’ve\b",
        r"\bI'd\b",
        r"\bI’d\b",
        r"\bme\b",
        r"\bmy\b",
        r"\bas (?:his|their|the) coach\b",
        r"\bcoach\b",
    ]
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return True
    return False


def _data_sources_section_at_end(text: str) -> bool:
    lines = text.splitlines()
    # Trim trailing empty lines
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines:
        return False
    # Find last occurrence of "Data sources" header line
    last_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Data sources" or stripped == "Data sources:":
            last_idx = i
    if last_idx == -1:
        return False
    # Consider section content after the header to end
    tail_lines = lines[last_idx + 1 :]
    tail_text = "\n".join(tail_lines)
    required_paths = [
        "./input/game_logs.csv",
        "./input/coach_notes.json",
        "./input/profile.html",
    ]
    if not all(p in tail_text for p in required_paths):
        return False
    # Ensure file ends with this section (i.e., last non-empty line contains one of the paths)
    if tail_lines:
        last_non_empty = ""
        for l in tail_lines[::-1]:
            if l.strip():
                last_non_empty = l.strip()
                break
        if not any(p in last_non_empty for p in required_paths):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    input_game_logs = workspace / "input" / "game_logs.csv"
    input_coach_notes = workspace / "input" / "coach_notes.json"
    input_profile_html = workspace / "input" / "profile.html"

    output_metrics_csv = workspace / "output" / "cody_williams_metrics.csv"
    output_profile_json = workspace / "output" / "profile_extracted.json"
    output_feature_md = workspace / "output" / "cody_williams_feature.md"

    scores = {
        "metrics_csv_structure": 0.0,
        "metrics_values_correct": 0.0,
        "profile_json_structure": 0.0,
        "profile_json_values_correct": 0.0,
        "feature_md_exists": 0.0,
        "feature_word_count_range": 0.0,
        "feature_includes_metrics_values": 0.0,
        "feature_includes_season_high_details": 0.0,
        "feature_quotes_work_ethic_note": 0.0,
        "feature_quotes_strength": 0.0,
        "feature_quotes_growth_area": 0.0,
        "feature_data_sources_section_at_end": 0.0,
        "first_person_voice_presence": 0.0,
    }

    # Compute expected metrics from input
    expected_metrics = None
    if input_game_logs.exists():
        expected_metrics = _compute_expected_metrics(input_game_logs)

    # Validate metrics CSV
    headers, rows, metrics_map = _load_metrics_csv(output_metrics_csv)
    if headers is not None and rows is not None and metrics_map is not None:
        # Structure: headers exactly ['stat','value'], two columns, exactly 8 rows with required stats
        required_stats = [
            "avg_points",
            "avg_rebounds",
            "avg_assists",
            "avg_minutes",
            "fg_pct",
            "season_high_points",
            "season_high_opponent",
            "season_high_date",
        ]
        structure_ok = (
            headers == ["stat", "value"]
            and all(set(r.keys()) == set(["stat", "value"]) for r in rows)
            and len(rows) == 8
            and set(metrics_map.keys()) == set(required_stats)
        )
        scores["metrics_csv_structure"] = 1.0 if structure_ok else 0.0

        # Values correct
        if structure_ok and expected_metrics is not None:
            values_ok = all(str(expected_metrics[k]) == str(metrics_map.get(k, "")) for k in required_stats)
            scores["metrics_values_correct"] = 1.0 if values_ok else 0.0
        else:
            scores["metrics_values_correct"] = 0.0
    else:
        scores["metrics_csv_structure"] = 0.0
        scores["metrics_values_correct"] = 0.0

    # Validate profile_extracted.json structure and values
    profile_json = _load_json_safe(output_profile_json)
    if isinstance(profile_json, dict) and set(profile_json.keys()) == {"strengths", "growth_areas"}:
        strengths = profile_json.get("strengths")
        growth_areas = profile_json.get("growth_areas")
        if isinstance(strengths, list) and isinstance(growth_areas, list) and all(
            isinstance(x, str) for x in strengths + growth_areas
        ):
            scores["profile_json_structure"] = 1.0
            expected_profile = _parse_profile_expected(input_profile_html) if input_profile_html.exists() else None
            if expected_profile is not None:
                values_ok = (
                    strengths == expected_profile["strengths"]
                    and growth_areas == expected_profile["growth_areas"]
                )
                scores["profile_json_values_correct"] = 1.0 if values_ok else 0.0
            else:
                scores["profile_json_values_correct"] = 0.0
        else:
            scores["profile_json_structure"] = 0.0
            scores["profile_json_values_correct"] = 0.0
    else:
        scores["profile_json_structure"] = 0.0
        scores["profile_json_values_correct"] = 0.0

    # Feature article checks
    if output_feature_md.exists():
        scores["feature_md_exists"] = 1.0
        article = _read_text_safe(output_feature_md)

        # Word count
        wc = _count_words(article)
        if 650 <= wc <= 800:
            scores["feature_word_count_range"] = 1.0

        # First-person presence
        if _first_person_presence(article):
            scores["first_person_voice_presence"] = 1.0

        # Metrics values included (use actual metrics CSV values to enforce consistency with generated file)
        metrics_values_present = False
        season_high_present = False
        if metrics_map:
            # Five numeric stats
            required_numeric_stats = ["avg_points", "avg_rebounds", "avg_assists", "avg_minutes", "fg_pct"]
            numeric_values = [metrics_map.get(k, "") for k in required_numeric_stats]
            # Ensure all present as exact substrings
            if all((v in article) for v in numeric_values):
                metrics_values_present = True
            # Season high details
            season_values = [
                metrics_map.get("season_high_points", ""),
                metrics_map.get("season_high_opponent", ""),
                metrics_map.get("season_high_date", ""),
            ]
            if all((v in article) for v in season_values):
                season_high_present = True
        scores["feature_includes_metrics_values"] = 1.0 if metrics_values_present else 0.0
        scores["feature_includes_season_high_details"] = 1.0 if season_high_present else 0.0

        # Quote from work_ethic notes
        notes = _load_json_safe(input_coach_notes)
        work_ethic_ok = False
        if isinstance(notes, dict) and isinstance(notes.get("notes"), list):
            for n in notes["notes"]:
                tags = n.get("tags", [])
                quote = n.get("quote", "")
                if isinstance(tags, list) and "work_ethic" in tags and isinstance(quote, str) and quote:
                    if _contains_quoted(article, quote):
                        work_ethic_ok = True
                        break
        scores["feature_quotes_work_ethic_note"] = 1.0 if work_ethic_ok else 0.0

        # Quote from strengths and growth_areas (from output/profile_extracted.json)
        strength_quote_ok = False
        growth_quote_ok = False
        if isinstance(profile_json, dict):
            strengths_list = profile_json.get("strengths") or []
            growth_list = profile_json.get("growth_areas") or []
            for s in strengths_list:
                if isinstance(s, str) and (_contains_quoted(article, s) or f"\"{s}\"" in article):
                    strength_quote_ok = True
                    break
            for g in growth_list:
                if isinstance(g, str) and (_contains_quoted(article, g) or f"\"{g}\"" in article):
                    growth_quote_ok = True
                    break
        scores["feature_quotes_strength"] = 1.0 if strength_quote_ok else 0.0
        scores["feature_quotes_growth_area"] = 1.0 if growth_quote_ok else 0.0

        # Data sources section at end
        scores["feature_data_sources_section_at_end"] = 1.0 if _data_sources_section_at_end(article) else 0.0
    else:
        # feature_md_exists remains 0.0; other article-related checks also 0.0
        pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()