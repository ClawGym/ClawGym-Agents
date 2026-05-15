import json
import csv
import re
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    try        :
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = []
            for row in reader:
                # Normalize all values to strings stripped of surrounding whitespace
                cleaned = {k: (v.strip() if isinstance(v, str) else "" if v is None else str(v)) for k, v in row.items()}
                rows.append(cleaned)
            return reader.fieldnames, rows
    except Exception:
        return None


class _RecentMatchesParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.table_id_stack = []
        self.in_tbody = False
        self.in_tr = False
        self.in_td = False
        self.current_cell = ""
        self.current_row: List[str] = []
        self.rows: List[List[str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            attr_dict = dict(attrs)
            self.table_id_stack.append(attr_dict.get("id", ""))
            if attr_dict.get("id") == "recent-matches":
                self.in_table = True
        if not self.in_table:
            return
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_tr = True
            self.current_row = []
        elif tag == "td" and self.in_tr:
            self.in_td = True
            self.current_cell = ""

    def handle_data(self, data):
        if self.in_table and self.in_td:
            self.current_cell += data

    def handle_endtag(self, tag):
        if tag == "td" and self.in_td:
            self.in_td = False
            self.current_row.append(self.current_cell.strip())
            self.current_cell = ""
        elif tag == "tr" and self.in_tr:
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
            self.current_row = []
        elif tag == "tbody" and self.in_tbody:
            self.in_tbody = False
        elif tag == "table":
            # pop stack and reset in_table if this table was the target
            last_id = self.table_id_stack.pop() if self.table_id_stack else ""
            if last_id == "recent-matches":
                self.in_table = False


def _parse_recent_matches_html(html_text: str) -> Optional[List[Dict[str, str]]]:
    try:
        parser = _RecentMatchesParser()
        parser.feed(html_text)
        # Expect rows with 6 columns: Date, Competition, Venue, Opponent, Scoreline, Vannes Scorers
        rows = []
        for r in parser.rows:
            if len(r) != 6:
                return None
            rows.append({
                "Date": r[0],
                "Competition": r[1],
                "Venue": r[2],
                "Opponent": r[3],
                "Scoreline": r[4],
                "Vannes Scorers": r[5],
            })
        return rows
    except Exception:
        return None


def _extract_gf_ga(scoreline: str) -> Optional[Tuple[int, int]]:
    # Scoreline format example: "Vannes OC 2–1 AS Poissy"
    # Accept either en dash or hyphen
    try:
        m = re.search(r"Vannes\s+OC\s+(\d+)\s*[–-]\s*(\d+)\b", scoreline)
        if not m:
            return None
        gf = int(m.group(1))
        ga = int(m.group(2))
        return gf, ga
    except Exception:
        return None


def _normalize_scorers(raw: str) -> str:
    if not raw:
        return ""
    parts = re.split(r"[;,]", raw)
    names = []
    for p in parts:
        # remove minute markers like " 34'", "90+2'", " (pen)" are not present; remove trailing punctuation
        q = re.sub(r"\s*\d+\+?\d*\'", "", p)  # remove time markers
        q = q.strip()
        # remove trailing punctuation like '.' or ',' or ';'
        q = re.sub(r"[.,;:]+$", "", q).strip()
        if q:
            names.append(q)
    return "; ".join(names)


def _build_expected_matches(rows_html: List[Dict[str, str]]) -> Optional[List[Dict[str, str]]]:
    expected_cols = ["date", "competition", "opponent", "venue", "goals_for", "goals_against", "result", "scorers"]
    try:
        out: List[Dict[str, str]] = []
        for r in rows_html:
            gfga = _extract_gf_ga(r["Scoreline"])
            if gfga is None:
                return None
            gf, ga = gfga
            if gf > ga:
                res = "W"
            elif gf == ga:
                res = "D"
            else:
                res = "L"
            scorers = _normalize_scorers(r["Vannes Scorers"])
            row = {
                "date": r["Date"],
                "competition": r["Competition"],
                "opponent": r["Opponent"],
                "venue": r["Venue"],
                "goals_for": str(gf),
                "goals_against": str(ga),
                "result": res,
                "scorers": scorers,
            }
            # ensure columns consistency
            row = {k: row[k] for k in expected_cols}
            out.append(row)
        return out
    except Exception:
        return None


def _compute_summary_from_matches(rows: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    try:
        matches_played = len(rows)
        wins = sum(1 for r in rows if r["result"] == "W")
        draws = sum(1 for r in rows if r["result"] == "D")
        losses = sum(1 for r in rows if r["result"] == "L")
        gf = sum(int(r["goals_for"]) for r in rows)
        ga = sum(int(r["goals_against"]) for r in rows)
        gd = gf - ga
        clean_sheets = sum(1 for r in rows if int(r["goals_against"]) == 0)
        # Count different scorers based on names separated by ;
        scorer_counts: Dict[str, int] = {}
        for r in rows:
            scorers_field = r.get("scorers", "")
            if not scorers_field:
                continue
            names = [s.strip() for s in scorers_field.split(";") if s.strip()]
            for name in names:
                scorer_counts[name] = scorer_counts.get(name, 0) + 1
        different_scorers_count = len(scorer_counts)
        # top_scorers up to 3 entries by goals desc then name asc, include ties up to max 3
        items = sorted(scorer_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        top_three = [{"name": name, "goals": goals} for name, goals in items[:3]]
        summary = {
            "matches_played": matches_played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for": gf,
            "goals_against": ga,
            "goal_difference": gd,
            "clean_sheets": clean_sheets,
            "different_scorers_count": different_scorers_count,
            "top_scorers": top_three,
        }
        return summary
    except Exception:
        return None


def _parse_upcoming_fixtures_csv(text: str) -> Optional[List[Dict[str, str]]]:
    try:
        # Use csv.reader since text is provided
        lines = text.splitlines()
        reader = csv.DictReader(lines)
        if reader.fieldnames is None:
            return None
        expected_headers = ["date", "competition", "venue", "opponent"]
        if [h.strip() for h in reader.fieldnames] != expected_headers:
            return None
        fixtures = []
        for row in reader:
            fixtures.append({
                "date": row["date"].strip(),
                "competition": row["competition"].strip(),
                "venue": row["venue"].strip(),
                "opponent": row["opponent"].strip(),
            })
        return fixtures
    except Exception:
        return None


def _select_next_two_fixtures(fixtures: List[Dict[str, str]], cutoff_date: str) -> Optional[List[Dict[str, str]]]:
    try:
        cutoff = datetime.strptime(cutoff_date, "%Y-%m-%d").date()
        filtered = []
        for f in fixtures:
            try:
                d = datetime.strptime(f["date"], "%Y-%m-%d").date()
            except Exception:
                return None
            if d > cutoff:
                filtered.append((d, f))
        filtered.sort(key=lambda x: x[0])
        selected = [f for _, f in filtered[:2]]
        if len(selected) < 2:
            # Not enough fixtures
            return None
        return selected
    except Exception:
        return None


def _extract_marked_section(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[str, str, str]]:
    """
    Returns tuple (before, middle, after) splitting text at markers.
    """
    try:
        start_idx = text.find(start_marker)
        end_idx = text.find(end_marker)
        if start_idx == -1 or end_idx == -1:
            return None
        start_end = start_idx + len(start_marker)
        if end_idx < start_end:
            return None
        before = text[:start_end]
        middle = text[start_end:end_idx]
        after = text[end_idx:]
        return before, middle, after
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "matches_csv_structure": 0.0,
        "matches_csv_content": 0.0,
        "summary_json_structure": 0.0,
        "summary_stats_accuracy": 0.0,
        "summary_next_fixtures_accuracy": 0.0,
        "summary_top_scorers_accuracy": 0.0,
        "newsletter_file_structure_and_integrity": 0.0,
        "newsletter_paragraph_length": 0.0,
        "newsletter_paragraph_content_record_and_gd": 0.0,
        "newsletter_paragraph_top_scorers_mentions": 0.0,
        "newsletter_paragraph_next_fixtures_mentions": 0.0,
        "newsletter_paragraph_closing_rallying_cry": 0.0,
    }

    # Constants and expected paths
    html_path = workspace / "input" / "html" / "recent_matches.html"
    fixtures_csv_path = workspace / "input" / "csv" / "upcoming_fixtures.csv"
    newsletter_draft_path = workspace / "input" / "newsletter_draft.md"

    output_csv_path = workspace / "output" / "data" / "weekly_matches_2024-03-01_2024-03-07.csv"
    output_json_path = workspace / "output" / "reports" / "weekly_summary.json"
    output_newsletter_path = workspace / "output" / "newsletter_2024-03-01_2024-03-07.md"

    period_start = "2024-03-01"
    period_end = "2024-03-07"

    # Load inputs to compute expected artifacts
    html_text = _safe_read_text(html_path)
    fixtures_text = _safe_read_text(fixtures_csv_path)
    draft_text = _safe_read_text(newsletter_draft_path)

    expected_matches_rows: Optional[List[Dict[str, str]]] = None
    if html_text is not None:
        parsed_html_rows = _parse_recent_matches_html(html_text)
        if parsed_html_rows is not None:
            expected_matches_rows = _build_expected_matches(parsed_html_rows)

    expected_summary: Optional[Dict[str, Any]] = None
    if expected_matches_rows is not None:
        expected_summary = _compute_summary_from_matches(expected_matches_rows)

    expected_next_two: Optional[List[Dict[str, str]]] = None
    if fixtures_text is not None:
        parsed_fixtures = _parse_upcoming_fixtures_csv(fixtures_text)
        if parsed_fixtures is not None:
            expected_next_two = _select_next_two_fixtures(parsed_fixtures, period_end)

    # 1) Validate matches CSV structure and content
    expected_columns = ["date", "competition", "opponent", "venue", "goals_for", "goals_against", "result", "scorers"]
    loaded = _safe_load_csv_dicts(output_csv_path)
    if loaded is not None:
        cols, rows = loaded
        if cols == expected_columns:
            scores["matches_csv_structure"] = 1.0
        else:
            scores["matches_csv_structure"] = 0.0
        # Content comparison only if we have expected rows computed
        if expected_matches_rows is not None and cols == expected_columns:
            # Compare length and exact row values in order
            if len(rows) == len(expected_matches_rows):
                match_all = True
                for i, exp_row in enumerate(expected_matches_rows):
                    act_row = rows[i]
                    for k in expected_columns:
                        av = act_row.get(k, "")
                        ev = exp_row.get(k, "")
                        if (av or "") != (ev or ""):
                            match_all = False
                            break
                    if not match_all:
                        break
                if match_all:
                    scores["matches_csv_content"] = 1.0

    # 2) Validate summary JSON
    summary_data = _safe_load_json(output_json_path)
    required_summary_keys = {
        "period_start", "period_end", "matches_played", "wins", "draws", "losses",
        "goals_for", "goals_against", "goal_difference", "clean_sheets",
        "different_scorers_count", "top_scorers", "next_two_fixtures"
    }
    if isinstance(summary_data, dict):
        # Structure: exact keys
        if set(summary_data.keys()) == required_summary_keys:
            # Basic type checks
            types_ok = True
            types_ok &= summary_data.get("period_start") == period_start
            types_ok &= summary_data.get("period_end") == period_end
            for key in ["matches_played", "wins", "draws", "losses", "goals_for", "goals_against", "goal_difference", "clean_sheets", "different_scorers_count"]:
                if not isinstance(summary_data.get(key), int):
                    types_ok = False
            if not isinstance(summary_data.get("top_scorers"), list):
                types_ok = False
            if not isinstance(summary_data.get("next_two_fixtures"), list):
                types_ok = False
            if types_ok:
                scores["summary_json_structure"] = 1.0

        # Stats accuracy
        if expected_summary is not None:
            stats_ok = True
            for key in ["matches_played", "wins", "draws", "losses", "goals_for", "goals_against", "goal_difference", "clean_sheets", "different_scorers_count"]:
                if summary_data.get(key) != expected_summary.get(key):
                    stats_ok = False
            if stats_ok:
                scores["summary_stats_accuracy"] = 1.0

        # Next two fixtures accuracy
        if expected_next_two is not None:
            next_two = summary_data.get("next_two_fixtures")
            if isinstance(next_two, list) and len(next_two) == 2:
                n_ok = True
                # Check each item fields and equality to expected
                for i in range(2):
                    exp = expected_next_two[i]
                    act = next_two[i]
                    if not isinstance(act, dict):
                        n_ok = False
                        break
                    for key in ["date", "opponent", "venue", "competition"]:
                        if act.get(key) != exp.get(key):
                            n_ok = False
                            break
                    if not n_ok:
                        break
                if n_ok:
                    scores["summary_next_fixtures_accuracy"] = 1.0

        # Top scorers accuracy (content, not order)
        if expected_summary is not None and isinstance(summary_data.get("top_scorers"), list):
            expected_set = set((ts["name"], ts["goals"]) for ts in expected_summary.get("top_scorers", []))
            actual_list = summary_data.get("top_scorers")
            # validate structure of actual list
            valid_struct = True
            for item in actual_list:
                if not (isinstance(item, dict) and "name" in item and "goals" in item and isinstance(item["name"], str) and isinstance(item["goals"], int)):
                    valid_struct = False
                    break
            if valid_struct:
                actual_set = set((item["name"], item["goals"]) for item in actual_list)
                if actual_set == expected_set and len(actual_list) <= 3:
                    scores["summary_top_scorers_accuracy"] = 1.0

    # 3) and 4) Validate newsletter file integrity and paragraph content
    out_news_text = _safe_read_text(output_newsletter_path)
    if out_news_text is not None and draft_text is not None:
        start_marker = "<!-- WEEKLY_UPDATE_START -->"
        end_marker = "<!-- WEEKLY_UPDATE_END -->"
        out_parts = _extract_marked_section(out_news_text, start_marker, end_marker)
        draft_parts = _extract_marked_section(draft_text, start_marker, end_marker)
        if out_parts is not None and draft_parts is not None:
            before_out, middle_out, after_out = out_parts
            before_draft, _, after_draft = draft_parts
            # Integrity: before and after must match exactly
            if before_out == before_draft and after_out == after_draft:
                scores["newsletter_file_structure_and_integrity"] = 1.0

            paragraph = middle_out.strip()
            # Paragraph length 120–180 words
            words = [w for w in re.findall(r"\b\w[\w'-]*\b", paragraph)]
            if 120 <= len(words) <= 180:
                scores["newsletter_paragraph_length"] = 1.0

            # Record and goal difference presence
            record_ok = False
            gd_ok = False
            # Expected numbers from expected summary if available; else from known inputs if computed
            exp_w = exp_d = exp_l = None
            exp_gd = None
            if expected_summary is not None:
                exp_w = expected_summary["wins"]
                exp_d = expected_summary["draws"]
                exp_l = expected_summary["losses"]
                exp_gd = expected_summary["goal_difference"]
            else:
                # fallback from known fixtures if possible (hardcoded expectation based on provided inputs)
                exp_w, exp_d, exp_l, exp_gd = 1, 1, 1, -1

            if exp_w is not None and exp_d is not None and exp_l is not None:
                # Accept hyphen or en-dash
                pattern1 = f"{exp_w}-{exp_d}-{exp_l}"
                pattern2 = f"{exp_w}–{exp_d}–{exp_l}"
                if pattern1 in paragraph or pattern2 in paragraph:
                    record_ok = True

            if exp_gd is not None:
                # Look for "goal difference" or "GD" with the number nearby, or just presence of the number and phrase anywhere
                lower = paragraph.lower()
                gd_str = str(exp_gd)
                if "goal difference" in lower and gd_str in paragraph:
                    gd_ok = True
                elif re.search(r"\bGD\b", paragraph) and gd_str in paragraph:
                    gd_ok = True
            if record_ok and gd_ok:
                scores["newsletter_paragraph_content_record_and_gd"] = 1.0

            # Top scorers mentions: names and goal counts
            top_scorer_names = []
            if expected_summary is not None and expected_summary.get("top_scorers"):
                top_scorer_names = [ts["name"] for ts in expected_summary["top_scorers"]]
            else:
                # fallback based on inputs
                top_scorer_names = ["A. Le Goff", "M. Ndao", "J. Boutrah"]
            ts_ok = True
            for name in top_scorer_names:
                if name not in paragraph:
                    ts_ok = False
                    break
                # ensure "1" appears near the name within 20 characters after mention, or "one"
                idx = paragraph.find(name)
                window = paragraph[idx: idx + len(name) + 20] if idx != -1 else ""
                if not (re.search(r"\b1\b", window) or re.search(r"\bone\b", window, flags=re.IGNORECASE)):
                    ts_ok = False
                    break
            if ts_ok:
                scores["newsletter_paragraph_top_scorers_mentions"] = 1.0

            # Next fixtures mentions: dates and opponents
            next_two_expected = []
            if expected_next_two is not None:
                next_two_expected = expected_next_two
            else:
                next_two_expected = [
                    {"date": "2024-03-09", "opponent": "US Saint-Malo"},
                    {"date": "2024-03-16", "opponent": "FC Lorient B"},
                ]
            nf_ok = True
            for nf in next_two_expected:
                if nf["date"] not in paragraph or nf["opponent"] not in paragraph:
                    nf_ok = False
                    break
            if nf_ok:
                scores["newsletter_paragraph_next_fixtures_mentions"] = 1.0

            # Rallying cry at the end
            if paragraph.rstrip().endswith("Allez Vannes !"):
                scores["newsletter_paragraph_closing_rallying_cry"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()