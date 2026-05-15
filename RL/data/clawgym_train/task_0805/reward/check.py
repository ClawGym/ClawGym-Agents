import sys
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from html.parser import HTMLParser
from datetime import datetime
import importlib.util


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json_list(path: Path) -> Optional[List[Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        return None
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [row for row in reader]
            return header, rows
    except Exception:
        return None, None


def _parse_scalar(value: str) -> Any:
    v = value.strip()
    try:
        i = int(v)
        return i
    except Exception:
        pass
    try:
        f = float(v)
        return f
    except Exception:
        return v


def _parse_simple_yaml(text: str) -> Optional[Dict[str, Any]]:
    # Minimal YAML parser for simple mappings with indentation, keys/values separated by colon.
    # Supports nested dicts, no lists.
    try:
        root: Dict[str, Any] = {}
        stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]
        for raw_line in text.splitlines():
            if not raw_line.strip():
                continue
            line = raw_line.rstrip()
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            indent = len(line) - len(stripped)
            while stack and indent <= stack[-1][0]:
                stack.pop()
            if not stack:
                return None
            current_dict = stack[-1][1]
            if ":" not in stripped:
                return None
            key_part, _, value_part = stripped.partition(":")
            key = key_part.strip()
            if value_part.strip() == "":
                new_dict: Dict[str, Any] = {}
                current_dict[key] = new_dict
                stack.append((indent, new_dict))
            else:
                value = _parse_scalar(value_part.strip())
                current_dict[key] = value
        return root
    except Exception:
        return None


class StoriesHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.articles: Dict[str, Dict[str, Any]] = {}
        self._current_id: Optional[str] = None
        self._in_tags_ul: bool = False
        self._in_li: bool = False
        self._in_story_p: bool = False
        self._current_tags: List[str] = []
        self._current_p_text_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "article":
            attr_dict = {k: v for k, v in attrs}
            match_id = attr_dict.get("data-match-id")
            if match_id:
                self._current_id = str(match_id)
                self._current_tags = []
                self._current_p_text_parts = []
                self._in_tags_ul = False
                self._in_li = False
                self._in_story_p = False
        elif self._current_id is not None:
            if tag.lower() == "ul":
                attr_dict = {k: v for k, v in attrs}
                if attr_dict.get("class") == "tags":
                    self._in_tags_ul = True
            elif tag.lower() == "li" and self._in_tags_ul:
                self._in_li = True
            elif tag.lower() == "p":
                attr_dict = {k: v for k, v in attrs}
                if attr_dict.get("class") == "story":
                    self._in_story_p = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "article" and self._current_id is not None:
            full_text = "".join(self._current_p_text_parts).strip()
            summary = self._first_sentence_clipped(full_text, 140)
            self.articles[self._current_id] = {
                "tags": self._current_tags[:],
                "summary": summary,
            }
            self._current_id = None
            self._in_tags_ul = False
            self._in_li = False
            self._in_story_p = False
            self._current_tags = []
            self._current_p_text_parts = []
        elif tag.lower() == "ul":
            self._in_tags_ul = False
            self._in_li = False
        elif tag.lower() == "li":
            self._in_li = False
        elif tag.lower() == "p":
            self._in_story_p = False

    def handle_data(self, data: str) -> None:
        if self._current_id is not None:
            if self._in_li and self._in_tags_ul:
                text = data.strip()
                if text:
                    self._current_tags.append(text)
            if self._in_story_p:
                self._current_p_text_parts.append(data)

    @staticmethod
    def _first_sentence_clipped(text: str, max_len: int) -> str:
        s = text.strip()
        idx = s.find(".")
        if idx != -1:
            s = s[: idx + 1].strip()
        if len(s) > max_len:
            s = s[:max_len]
        return s


def _import_parser_module(parser_path: Path) -> Optional[Any]:
    try:
        spec = importlib.util.spec_from_file_location("parser_module", parser_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
        return module
    except Exception:
        return None


def _normalize_team(name: str, aliases: Dict[str, str]) -> str:
    n = name.strip()
    return aliases.get(n, n)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "discovered_files_exists_and_parseable": 0.0,
        "discovered_files_required_files_logged": 0.0,
        "discovered_files_paths_exist_and_scoped": 0.0,
        "rankings_file_exists_and_parseable": 0.0,
        "rankings_header_correct": 0.0,
        "rankings_row_count_correct": 0.0,
        "rankings_rows_match_values": 0.0,
        "rankings_sorted_correctly": 0.0,
        "canonical_team_names_used": 0.0,
    }

    matches_csv = workspace / "input" / "matches.csv"
    stories_html = workspace / "input" / "stories.html"
    weights_yaml = workspace / "config" / "weights.yaml"
    parser_py = workspace / "scripts" / "parser.py"
    derby_csv = workspace / "output" / "derby_rankings.csv"
    discovered_json = workspace / "output" / "discovered_files.json"

    # Discovered files checks
    discovered = _load_json_list(discovered_json)
    if isinstance(discovered, list):
        all_strs = all(isinstance(x, str) for x in discovered)
        if all_strs:
            scores["discovered_files_exists_and_parseable"] = 1.0

            required_paths = [
                "input/matches.csv",
                "input/stories.html",
                "config/weights.yaml",
                "scripts/parser.py",
            ]
            required_logged = all(req in discovered for req in required_paths)
            required_exist = all((workspace / p).exists() for p in required_paths)
            if required_exist and required_logged:
                scores["discovered_files_required_files_logged"] = 1.0

            allowed_prefixes = ("input/", "config/", "scripts/")
            paths_ok = True
            for rel in discovered:
                rel_path = Path(rel)
                if rel_path.is_absolute():
                    paths_ok = False
                    break
                rel_posix = rel_path.as_posix()
                if not rel_posix.startswith(allowed_prefixes):
                    paths_ok = False
                    break
                full = workspace / rel_path
                if not full.exists() or not full.is_file():
                    paths_ok = False
                    break
            if paths_ok:
                scores["discovered_files_paths_exist_and_scoped"] = 1.0

    # Prepare expected data only if inputs are available and parseable
    team_aliases: Optional[Dict[str, str]] = None
    parser_module = None
    if parser_py.exists():
        parser_module = _import_parser_module(parser_py)
        if parser_module is not None and hasattr(parser_module, "TEAM_ALIASES"):
            try:
                ta = getattr(parser_module, "TEAM_ALIASES")
                if isinstance(ta, dict):
                    if all(isinstance(k, str) and isinstance(v, str) for k, v in ta.items()):
                        team_aliases = dict(ta)
            except Exception:
                team_aliases = None

    weights_data: Optional[Dict[str, Any]] = None
    classifications: Optional[Dict[str, Any]] = None
    if weights_yaml.exists():
        text = _read_text(weights_yaml)
        if text is not None:
            yaml_obj = _parse_simple_yaml(text)
            if isinstance(yaml_obj, dict):
                w = yaml_obj.get("weights")
                c = yaml_obj.get("classification")
                if isinstance(w, dict):
                    weights_data = w
                if isinstance(c, dict):
                    classifications = c

    stories_map: Optional[Dict[str, Dict[str, Any]]] = None
    if stories_html.exists():
        html_text = _read_text(stories_html)
        if html_text is not None:
            parser = StoriesHTMLParser()
            try:
                parser.feed(html_text)
                stories_map = parser.articles
            except Exception:
                stories_map = None

    matches_header, matches_rows = (None, None)
    if matches_csv.exists():
        matches_header, matches_rows = _read_csv_dicts(matches_csv)

    expected_by_id: Dict[str, Dict[str, Any]] = {}
    expected_sorted_ids: List[str] = []

    inputs_ok = (
        team_aliases is not None
        and weights_data is not None
        and classifications is not None
        and stories_map is not None
        and matches_rows is not None
    )

    if inputs_ok:
        kw_points = weights_data.get("keyword_points", {}) if isinstance(weights_data, dict) else {}
        goal_diff_weight = float(weights_data.get("goal_diff_weight", 1.0))
        last_minute_threshold = float(weights_data.get("last_minute_threshold", 85))
        legendary_min = float(classifications.get("legendary_min", 8.0))
        memorable_min = float(classifications.get("memorable_min", 5.0))

        derby_matches: List[Dict[str, Any]] = []
        for row in matches_rows:  # type: ignore[arg-type]
            try:
                match_id = str(row["match_id"]).strip()
                date_str = row["date"].strip()
                competition = row["competition"].strip()
                home_team_raw = row["home_team"].strip()
                away_team_raw = row["away_team"].strip()
                home_goals = int(row["home_goals"])
                away_goals = int(row["away_goals"])
                wgm_raw = row.get("winning_goal_minute", "").strip() if "winning_goal_minute" in row else ""
                winning_goal_minute: Optional[int] = int(wgm_raw) if wgm_raw != "" else None
            except Exception:
                continue

            home_team = _normalize_team(home_team_raw, team_aliases)  # type: ignore[arg-type]
            away_team = _normalize_team(away_team_raw, team_aliases)  # type: ignore[arg-type]

            is_derby = (home_team in ("Arsenal", "Tottenham Hotspur")) or (away_team in ("Arsenal", "Tottenham Hotspur"))
            if not is_derby:
                continue

            story = stories_map.get(match_id) if stories_map else None
            if story is None:
                continue
            tags = story.get("tags", [])
            if not isinstance(tags, list):
                tags = []

            tag_points = 0.0
            for t in tags:
                if isinstance(t, str) and t in kw_points:
                    try:
                        tag_points += float(kw_points[t])
                    except Exception:
                        pass
            goal_diff_component = max(0.0, 2.0 - abs(home_goals - away_goals)) * goal_diff_weight
            last_minute_component = 0.0
            if winning_goal_minute is not None and winning_goal_minute >= last_minute_threshold:
                last_minute_component = 1.0
            drama_score = round(tag_points + goal_diff_component + last_minute_component, 2)

            if drama_score >= legendary_min:
                klass = "Legendary"
            elif drama_score >= memorable_min:
                klass = "Memorable"
            else:
                klass = "Routine"

            summary = story.get("summary", "")
            if not isinstance(summary, str):
                summary = ""

            derby_matches.append(
                {
                    "match_id": match_id,
                    "date": date_str,
                    "competition": competition,
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "drama_score": drama_score,
                    "class": klass,
                    "summary": summary,
                }
            )

        def _parse_date(d: str) -> datetime:
            try:
                return datetime.strptime(d, "%Y-%m-%d")
            except Exception:
                return datetime.min

        derby_matches_sorted = sorted(
            derby_matches,
            key=lambda r: (r["drama_score"], _parse_date(r["date"])),
            reverse=True,
        )
        expected_sorted_ids = [r["match_id"] for r in derby_matches_sorted]
        expected_by_id = {r["match_id"]: r for r in derby_matches_sorted}

    header, out_rows = _read_csv_dicts(derby_csv) if derby_csv.exists() else (None, None)
    if header is not None and out_rows is not None:
        scores["rankings_file_exists_and_parseable"] = 1.0
        expected_header = [
            "match_id",
            "date",
            "competition",
            "home_team",
            "away_team",
            "home_goals",
            "away_goals",
            "drama_score",
            "class",
            "summary",
        ]
        if header == expected_header:
            scores["rankings_header_correct"] = 1.0

        if inputs_ok:
            if len(out_rows) == len(expected_sorted_ids):
                scores["rankings_row_count_correct"] = 1.0

            rows_ok = True
            canonical_ok = True
            for out in out_rows:
                mid = str(out.get("match_id", "")).strip()
                expected_row = expected_by_id.get(mid)
                if expected_row is None:
                    rows_ok = False
                    continue
                try:
                    if int(out["match_id"]) != int(expected_row["match_id"]):
                        rows_ok = False
                except Exception:
                    rows_ok = False
                if str(out.get("date", "")).strip() != str(expected_row["date"]).strip():
                    rows_ok = False
                if str(out.get("competition", "")).strip() != str(expected_row["competition"]).strip():
                    rows_ok = False
                if str(out.get("home_team", "")).strip() != str(expected_row["home_team"]).strip():
                    rows_ok = False
                if str(out.get("away_team", "")).strip() != str(expected_row["away_team"]).strip():
                    rows_ok = False
                try:
                    if int(out.get("home_goals", "").strip()) != int(expected_row["home_goals"]):
                        rows_ok = False
                except Exception:
                    rows_ok = False
                try:
                    if int(out.get("away_goals", "").strip()) != int(expected_row["away_goals"]):
                        rows_ok = False
                except Exception:
                    rows_ok = False
                try:
                    if round(float(out.get("drama_score", "").strip()), 2) != round(float(expected_row["drama_score"]), 2):
                        rows_ok = False
                except Exception:
                    rows_ok = False
                if str(out.get("class", "")).strip() != str(expected_row["class"]).strip():
                    rows_ok = False
                if str(out.get("summary", "")).strip() != str(expected_row["summary"]).strip():
                    rows_ok = False
                if team_aliases is not None:
                    canonical_values = set(team_aliases.values())
                    if out.get("home_team", "") not in canonical_values or out.get("away_team", "") not in canonical_values:
                        canonical_ok = False
                else:
                    canonical_ok = False

            if rows_ok and len(out_rows) == len(expected_sorted_ids):
                scores["rankings_rows_match_values"] = 1.0

            if canonical_ok and len(out_rows) > 0:
                scores["canonical_team_names_used"] = 1.0

            try:
                out_order_ids = [str(int(r["match_id"])) for r in out_rows]
                if out_order_ids == expected_sorted_ids:
                    scores["rankings_sorted_correctly"] = 1.0
            except Exception:
                pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()