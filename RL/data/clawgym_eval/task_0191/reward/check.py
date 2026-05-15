import json
import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_constraints_yaml(text: str) -> Optional[Dict[str, Any]]:
    """
    Minimal parser tailored to the provided simple YAML structure.
    Expected keys:
      - number_of_sessions: int
      - max_lines_per_poem: int
      - year_range:
          start: int
          end: int
      - target_year: int
      - quote_keywords:
        - str
        - str
        ...
    """
    number_of_sessions = None
    max_lines_per_poem = None
    year_range = {"start": None, "end": None}
    target_year = None
    quote_keywords: List[str] = []

    lines = text.splitlines()
    current_section = None
    for raw_line in lines:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue

        # Top-level keys
        if not line.startswith(" "):
            current_section = None
            m_kv = re.match(r'^([A-Za-z0-9_]+):\s*(.*)$', line)
            if m_kv:
                key = m_kv.group(1)
                val = m_kv.group(2)
                if key == "number_of_sessions":
                    try:
                        number_of_sessions = int(val)
                    except Exception:
                        return None
                elif key == "max_lines_per_poem":
                    try:
                        max_lines_per_poem = int(val)
                    except Exception:
                        return None
                elif key == "target_year":
                    try:
                        target_year = int(val)
                    except Exception:
                        return None
                elif key == "year_range":
                    current_section = "year_range"
                elif key == "quote_keywords":
                    current_section = "quote_keywords"
                else:
                    # Unknown keys are not fatal; ignore
                    current_section = None
            else:
                return None
        else:
            # Indented section entries
            if current_section == "year_range":
                m_kv = re.match(r'^\s+([A-Za-z0-9_]+):\s*(.*)$', line)
                if not m_kv:
                    return None
                k = m_kv.group(1)
                v = m_kv.group(2)
                if k in ("start", "end"):
                    try:
                        year_range[k] = int(v)
                    except Exception:
                        return None
                else:
                    return None
            elif current_section == "quote_keywords":
                m_item = re.match(r'^\s*-\s*(.+)$', line)
                if not m_item:
                    return None
                item = m_item.group(1).strip()
                quote_keywords.append(item)
            else:
                # Indented but no known section
                return None

    # Validate required
    if (
        number_of_sessions is None
        or max_lines_per_poem is None
        or target_year is None
        or year_range.get("start") is None
        or year_range.get("end") is None
        or not isinstance(quote_keywords, list)
    ):
        return None

    return {
        "number_of_sessions": number_of_sessions,
        "max_lines_per_poem": max_lines_per_poem,
        "year_range": year_range,
        "target_year": target_year,
        "quote_keywords": quote_keywords,
    }


def _parse_poems_csv(text: str) -> Optional[List[Dict[str, Any]]]:
    try:
        rows: List[Dict[str, Any]] = []
        reader = csv.DictReader(text.splitlines())
        required = ["title", "author", "year", "lines", "themes", "maritime_score", "origin"]
        if reader.fieldnames is None:
            return None
        for r in required:
            if r not in reader.fieldnames:
                return None
        for row in reader:
            try:
                parsed = {
                    "title": row["title"],
                    "author": row["author"],
                    "year": int(row["year"]),
                    "lines": int(row["lines"]),
                    "themes": row["themes"],
                    "maritime_score": float(row["maritime_score"]),
                    "origin": row["origin"],
                }
            except Exception:
                return None
            rows.append(parsed)
        return rows
    except Exception:
        return None


def _filter_and_rank_poems(poems: List[Dict[str, Any]], constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
    def is_valid(poem: Dict[str, Any]) -> bool:
        themes = poem["themes"]
        if themes is None:
            return False
        if "maritime" not in themes.lower():
            return False
        yr = poem["year"]
        ln = poem["lines"]
        if not (constraints["year_range"]["start"] <= yr <= constraints["year_range"]["end"]):
            return False
        if ln > constraints["max_lines_per_poem"]:
            return False
        return True

    filtered = [p for p in poems if is_valid(p)]
    tgt = constraints["target_year"]

    # Sort by maritime_score desc, lines asc, abs(year - target_year) asc, title asc
    filtered.sort(
        key=lambda p: (
            -p["maritime_score"],
            p["lines"],
            abs(p["year"] - tgt),
            p["title"],
        )
    )
    n = constraints["number_of_sessions"]
    return filtered[:n]


def _parse_logbook_quotes(text: str, keywords: List[str]) -> List[Dict[str, Any]]:
    quotes: List[Dict[str, Any]] = []
    pattern = re.compile(r'^\[(\d{4}-\d{2}-\d{2})\] QUOTE: "(.+)"$')
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        date_str = m.group(1)
        quote_text = m.group(2)
        # Ensure valid date
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            continue
        lower_text = quote_text.lower()
        matched_kw = None
        for kw in keywords:
            if kw.lower() in lower_text:
                matched_kw = kw.lower()
                break
        if matched_kw is None:
            continue
        quotes.append({"date": date_str, "text": quote_text, "keyword": matched_kw, "dt": dt})
    quotes.sort(key=lambda x: x["dt"])
    for q in quotes:
        q.pop("dt", None)
    return quotes


def _load_csv_file(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = _read_text(path)
        if text is None:
            return None
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames is None:
            return None
        rows = list(reader)
        return {"headers": reader.fieldnames, "rows": rows}
    except Exception:
        return None


def _load_json_file(path: Path) -> Optional[Any]:
    try:
        return json.loads(_read_text(path) or "")
    except Exception:
        return None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "reading_selection_structure": 0.0,
        "reading_selection_content": 0.0,
        "session_pairs_structure": 0.0,
        "session_pairs_content": 0.0,
        "unit_plan_structure": 0.0,
        "unit_plan_content_consistency": 0.0,
        "cross_file_consistency": 0.0,
    }

    constraints_path = workspace / "input" / "course_constraints.yaml"
    poems_path = workspace / "input" / "poems.csv"
    logbook_path = workspace / "input" / "ancestor_log.txt"

    selection_path = workspace / "outputs" / "reading_selection.csv"
    pairs_path = workspace / "outputs" / "session_pairs.json"
    plan_path = workspace / "outputs" / "unit_plan.md"

    constraints_text = _read_text(constraints_path)
    poems_text = _read_text(poems_path)
    logbook_text = _read_text(logbook_path)

    constraints = _parse_constraints_yaml(constraints_text) if constraints_text is not None else None
    poems = _parse_poems_csv(poems_text) if poems_text is not None else None

    expected_selection: Optional[List[Dict[str, Any]]] = None
    expected_quotes: Optional[List[Dict[str, Any]]] = None
    expected_pairs: Optional[List[Dict[str, Any]]] = None

    if constraints is not None and poems is not None:
        try:
            expected_selection = _filter_and_rank_poems(poems, constraints)
            expected_quotes_all = _parse_logbook_quotes(logbook_text or "", constraints["quote_keywords"])
            expected_quotes = expected_quotes_all[: constraints["number_of_sessions"]]
            # Build expected pairs
            expected_pairs = []
            for i in range(min(len(expected_selection), len(expected_quotes))):
                poem = expected_selection[i]
                quote = expected_quotes[i]
                expected_pairs.append({
                    "session": i + 1,
                    "poem_title": poem["title"],
                    "poem_year": poem["year"],
                    "poem_lines": poem["lines"],
                    "quote_date": quote["date"],
                    "quote_text": quote["text"],
                    "keyword_matched": quote["keyword"],
                })
        except Exception:
            expected_selection = None
            expected_quotes = None
            expected_pairs = None

    # 1) Validate reading_selection.csv structure
    sel_loaded = _load_csv_file(selection_path)
    expected_headers = ["rank", "title", "author", "year", "lines", "themes", "maritime_score", "origin"]
    if sel_loaded is not None:
        headers_ok = sel_loaded["headers"] == expected_headers
        rows = sel_loaded["rows"]
        types_ok = True
        for idx, row in enumerate(rows):
            try:
                int(row["rank"])
                int(row["year"])
                int(row["lines"])
                float(row["maritime_score"])
            except Exception:
                types_ok = False
                break
        count_ok = False
        if constraints is not None:
            count_ok = (len(rows) == constraints["number_of_sessions"])
        if headers_ok and types_ok and count_ok:
            scores["reading_selection_structure"] = 1.0

    # 1b) Validate reading_selection.csv content correctness
    if sel_loaded is not None and expected_selection is not None and constraints is not None:
        rows = sel_loaded["rows"]
        if len(rows) == len(expected_selection):
            content_ok = True
            for i in range(len(expected_selection)):
                exp = expected_selection[i]
                act = rows[i]
                # Validate rank is i+1
                try:
                    if int(act["rank"]) != i + 1:
                        content_ok = False
                        break
                    if act["title"] != exp["title"]:
                        content_ok = False
                        break
                    if act["author"] != exp["author"]:
                        content_ok = False
                        break
                    if int(act["year"]) != exp["year"]:
                        content_ok = False
                        break
                    if int(act["lines"]) != exp["lines"]:
                        content_ok = False
                        break
                    if act["themes"] != exp["themes"]:
                        content_ok = False
                        break
                    try:
                        ms = float(act["maritime_score"])
                        if abs(ms - exp["maritime_score"]) > 1e-6:
                            content_ok = False
                            break
                    except Exception:
                        content_ok = False
                        break
                    if act["origin"] != exp["origin"]:
                        content_ok = False
                        break
                except Exception:
                    content_ok = False
                    break
            if content_ok:
                scores["reading_selection_content"] = 1.0

    # 2) Validate session_pairs.json structure
    pairs_loaded = _load_json_file(pairs_path)
    if pairs_loaded is not None and isinstance(pairs_loaded, list):
        structure_ok = True
        if constraints is not None:
            if len(pairs_loaded) != constraints["number_of_sessions"]:
                structure_ok = False
        required_fields = ["session", "poem_title", "poem_year", "poem_lines", "quote_date", "quote_text", "keyword_matched"]
        for i, item in enumerate(pairs_loaded):
            if not isinstance(item, dict):
                structure_ok = False
                break
            for f in required_fields:
                if f not in item:
                    structure_ok = False
                    break
            if not structure_ok:
                break
            # Type checks
            try:
                if not isinstance(item["session"], int):
                    structure_ok = False
                    break
                if not isinstance(item["poem_title"], str):
                    structure_ok = False
                    break
                if not isinstance(item["poem_year"], int):
                    structure_ok = False
                    break
                if not isinstance(item["poem_lines"], int):
                    structure_ok = False
                    break
                if not isinstance(item["quote_date"], str):
                    structure_ok = False
                    break
                # Validate date format
                datetime.strptime(item["quote_date"], "%Y-%m-%d")
                if not isinstance(item["quote_text"], str):
                    structure_ok = False
                    break
                if not isinstance(item["keyword_matched"], str):
                    structure_ok = False
                    break
            except Exception:
                structure_ok = False
                break
        if structure_ok:
            scores["session_pairs_structure"] = 1.0

    # 2b) Validate session_pairs.json content correctness
    if pairs_loaded is not None and expected_pairs is not None:
        content_ok = True
        if len(pairs_loaded) != len(expected_pairs):
            content_ok = False
        else:
            for i in range(len(expected_pairs)):
                exp = expected_pairs[i]
                act = pairs_loaded[i]
                try:
                    if act["session"] != exp["session"]:
                        content_ok = False
                        break
                    if act["poem_title"] != exp["poem_title"]:
                        content_ok = False
                        break
                    if act["poem_year"] != exp["poem_year"]:
                        content_ok = False
                        break
                    if act["poem_lines"] != exp["poem_lines"]:
                        content_ok = False
                        break
                    if act["quote_date"] != exp["quote_date"]:
                        content_ok = False
                        break
                    if act["quote_text"] != exp["quote_text"]:
                        content_ok = False
                        break
                    if str(act["keyword_matched"]).lower() != exp["keyword_matched"].lower():
                        content_ok = False
                        break
                except Exception:
                    content_ok = False
                    break
        if content_ok:
            scores["session_pairs_content"] = 1.0

    # 3) Validate unit_plan.md structure
    plan_text = _read_text(plan_path)
    if plan_text is not None and constraints is not None:
        lines = [ln for ln in plan_text.splitlines() if ln.strip() != ""]
        if len(lines) == constraints["number_of_sessions"]:
            # Check each line matches format exactly with em-dash
            # Pattern: Session X: {poem_title} ({year}, {lines} lines) — Quote {quote_date}: "{quote_text}"
            pat = re.compile(r'^Session (\d+): (.+) \((\d{4}), (\d+) lines\) — Quote (\d{4}-\d{2}-\d{2}): "(.*)"$')
            match_all = True
            for ln in lines:
                if not pat.match(ln):
                    match_all = False
                    break
            if match_all:
                scores["unit_plan_structure"] = 1.0

    # 3b) Validate unit_plan content consistency with session_pairs.json
    if plan_text is not None and pairs_loaded is not None and isinstance(pairs_loaded, list):
        lines = [ln for ln in plan_text.splitlines() if ln.strip() != ""]
        pat = re.compile(r'^Session (\d+): (.+) \((\d{4}), (\d+) lines\) — Quote (\d{4}-\d{2}-\d{2}): "(.*)"$')
        consistent = True
        if len(lines) != len(pairs_loaded):
            consistent = False
        else:
            for i in range(len(lines)):
                m = pat.match(lines[i])
                if not m:
                    consistent = False
                    break
                sess = int(m.group(1))
                title = m.group(2)
                year = int(m.group(3))
                lines_count = int(m.group(4))
                q_date = m.group(5)
                q_text = m.group(6)
                pair = pairs_loaded[i]
                try:
                    if sess != pair["session"]:
                        consistent = False
                        break
                    if title != pair["poem_title"]:
                        consistent = False
                        break
                    if year != pair["poem_year"]:
                        consistent = False
                        break
                    if lines_count != pair["poem_lines"]:
                        consistent = False
                        break
                    if q_date != pair["quote_date"]:
                        consistent = False
                        break
                    if q_text != pair["quote_text"]:
                        consistent = False
                        break
                except Exception:
                    consistent = False
                    break
        if consistent:
            scores["unit_plan_content_consistency"] = 1.0

    # 4) Cross-file consistency between reading_selection.csv and session_pairs.json
    if sel_loaded is not None and pairs_loaded is not None and isinstance(pairs_loaded, list):
        rows = sel_loaded["rows"]
        consistent = True
        if len(rows) != len(pairs_loaded):
            consistent = False
        else:
            for i in range(len(rows)):
                r = rows[i]
                p = pairs_loaded[i]
                try:
                    if int(r["rank"]) != p["session"]:
                        consistent = False
                        break
                    if r["title"] != p["poem_title"]:
                        consistent = False
                        break
                    if int(r["year"]) != p["poem_year"]:
                        consistent = False
                        break
                    if int(r["lines"]) != p["poem_lines"]:
                        consistent = False
                        break
                except Exception:
                    consistent = False
                    break
        if consistent:
            scores["cross_file_consistency"] = 1.0

    return scores


def main() -> None:
    import sys
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()