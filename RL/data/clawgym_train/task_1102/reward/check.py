import json
import sys
import csv
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_csv(path: Path, delimiter: str = ",") -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            rows = [dict(r) for r in reader]
            # Ensure all keys exist per header
            if reader.fieldnames is None or any(r is None for r in rows):
                return None
            return rows
    except Exception:
        return None


def _parse_int(value: Any) -> Optional[int]:
    try:
        if isinstance(value, int):
            return value
        s = str(value).strip().replace(",", "")
        if s == "":
            return None
        return int(s)
    except Exception:
        return None


def _parse_float(value: Any) -> Optional[float]:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip().replace(",", "")
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _parse_date_ymd(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _load_constraints_yaml(path: Path) -> Optional[Dict[str, Any]]:
    """
    Minimal YAML parser for the known constraints structure, using stdlib only.
    Expected schema:
      budget_cap: int
      date_range:
        start: "YYYY-MM-DD"
        end: "YYYY-MM-DD"
      top_n: int
      min_expected_visitors: int
      exclude_themes:
        - "value"
        - "value2"
    """
    text = _safe_read_text(path)
    if text is None:
        return None
    constraints: Dict[str, Any] = {
        "budget_cap": None,
        "date_range": {"start": None, "end": None},
        "top_n": None,
        "min_expected_visitors": None,
        "exclude_themes": [],
    }
    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue

        # Top-level key (no leading spaces or minimal)
        if not line.startswith(" ") and ":" in line and not line.lstrip().startswith("-"):
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip()
            current_section = key
            if key == "budget_cap":
                constraints["budget_cap"] = _parse_int(val) if val else None
            elif key == "top_n":
                constraints["top_n"] = _parse_int(val) if val else None
            elif key == "min_expected_visitors":
                constraints["min_expected_visitors"] = _parse_int(val) if val else None
            elif key == "date_range":
                constraints["date_range"] = {"start": None, "end": None}
            elif key == "exclude_themes":
                constraints["exclude_themes"] = []
            else:
                # Unknown key, ignore
                pass
            continue

        # Nested under date_range
        if current_section == "date_range":
            stripped = line.strip()
            if ":" in stripped:
                subkey, subval = stripped.split(":", 1)
                subkey = subkey.strip()
                subval = subval.strip().strip('"').strip("'")
                if subkey in ("start", "end"):
                    constraints["date_range"][subkey] = subval
            continue

        # List under exclude_themes
        if current_section == "exclude_themes":
            stripped = line.strip()
            if stripped.startswith("-"):
                item = stripped[1:].strip().strip('"').strip("'")
                if item:
                    constraints["exclude_themes"].append(item)
            continue

    # Validate minimal presence
    try:
        if (
            isinstance(constraints.get("budget_cap"), int)
            and isinstance(constraints.get("top_n"), int)
            and isinstance(constraints.get("min_expected_visitors"), int)
            and isinstance(constraints.get("exclude_themes"), list)
            and isinstance(constraints.get("date_range"), dict)
            and isinstance(constraints["date_range"].get("start"), str)
            and isinstance(constraints["date_range"].get("end"), str)
        ):
            return constraints
    except Exception:
        return None
    return None


def _number_string_variants(n: float) -> List[str]:
    """
    Generate plausible textual representations for numeric values
    to allow tolerant substring checks in prose.
    """
    variants = set()
    # base numeric
    try:
        if float(n).is_integer():
            iv = int(round(n))
            variants.add(str(iv))
            variants.add(f"{iv:,}")
            variants.add(f"{iv}.0")
            variants.add(f"{iv}.00")
        else:
            variants.add(str(n))
            variants.add(f"{n:.1f}")
            variants.add(f"{n:.2f}")
    except Exception:
        variants.add(str(n))
    return list(variants)


def _text_contains_any(content: str, candidates: List[str]) -> bool:
    lc = content
    for c in candidates:
        if c in lc:
            return True
    return False


def _compute_expected_shortlist(workspace: Path) -> Optional[Tuple[List[Dict[str, Any]], Dict[str, Any]]]:
    """
    Returns (expected_rows, constraints) where expected_rows is a list of dicts with columns:
    event_id,title,date,venue_name,neighborhood,budget_required,expected_visitors,venue_capacity,partner_count,score
    """
    # Load inputs
    events_path = workspace / "input" / "events.csv"
    venues_path = workspace / "input" / "venues.tsv"
    partners_path = workspace / "input" / "partners.json"
    constraints_path = workspace / "input" / "constraints.yaml"

    events = _safe_load_csv(events_path, delimiter=",")
    venues = _safe_load_csv(venues_path, delimiter="\t")
    partners = _safe_load_json(partners_path)
    constraints = _load_constraints_yaml(constraints_path)

    if events is None or venues is None or partners is None or constraints is None:
        return None

    # Build partners count by neighborhood
    partner_counts: Dict[str, int] = {}
    try:
        for p in partners:
            nb = str(p.get("neighborhood", "")).strip()
            if nb:
                partner_counts[nb] = partner_counts.get(nb, 0) + 1
    except Exception:
        return None

    # Build venues map
    venues_map: Dict[str, Dict[str, Any]] = {}
    try:
        for v in venues:
            vid = str(v.get("venue_id", "")).strip()
            name = str(v.get("name", "")).strip()
            capacity = _parse_int(v.get("capacity"))
            neighborhood = str(v.get("neighborhood", "")).strip()
            avail = str(v.get("available_dates", "")).strip()
            available_dates = set([d.strip() for d in avail.split(",") if d.strip()]) if avail else set()
            if vid and name and capacity is not None and neighborhood:
                venues_map[vid] = {
                    "name": name,
                    "capacity": capacity,
                    "neighborhood": neighborhood,
                    "available_dates": available_dates,
                }
    except Exception:
        return None

    # Parse constraints
    budget_cap = constraints["budget_cap"]
    top_n = constraints["top_n"]
    min_expected_visitors = constraints["min_expected_visitors"]
    exclude_themes = set(constraints["exclude_themes"])
    start_date = _parse_date_ymd(constraints["date_range"]["start"])
    end_date = _parse_date_ymd(constraints["date_range"]["end"])
    if None in (budget_cap, top_n, min_expected_visitors, start_date, end_date):
        return None

    # Process events
    kept: List[Dict[str, Any]] = []
    try:
        for e in events:
            event_id = str(e.get("event_id", "")).strip()
            title = str(e.get("title", "")).strip()
            date_str = str(e.get("date", "")).strip()
            theme = str(e.get("theme", "")).strip()
            venue_id = str(e.get("venue_id", "")).strip()
            budget_required = _parse_int(e.get("budget_required"))
            expected_visitors = _parse_int(e.get("expected_visitors"))
            event_date = _parse_date_ymd(date_str)

            if not event_id or not title or not date_str or budget_required is None or expected_visitors is None or not venue_id or event_date is None:
                continue

            # Filters
            if not (start_date <= event_date <= end_date):
                continue
            if budget_required > budget_cap:
                continue
            if expected_visitors < min_expected_visitors:
                continue
            if theme in exclude_themes:
                continue
            venue = venues_map.get(venue_id)
            if not venue:
                continue
            if date_str not in venue["available_dates"]:
                continue

            neighborhood = venue["neighborhood"]
            partner_count = partner_counts.get(neighborhood, 0)
            venue_capacity = venue["capacity"]
            score = expected_visitors + 0.1 * venue_capacity + 10 * partner_count

            kept.append({
                "event_id": event_id,
                "title": title,
                "date": date_str,
                "venue_name": venue["name"],
                "neighborhood": neighborhood,
                "budget_required": budget_required,
                "expected_visitors": expected_visitors,
                "venue_capacity": venue_capacity,
                "partner_count": partner_count,
                "score": float(score),
                "theme": theme,
            })
    except Exception:
        return None

    # Rank: score desc, tie-breakers: lower budget_required first, then earlier date
    try:
        kept_sorted = sorted(
            kept,
            key=lambda r: (-r["score"], r["budget_required"], r["date"]),
        )
    except Exception:
        return None

    expected_rows = []
    for r in kept_sorted[:top_n]:
        expected_rows.append({
            "event_id": r["event_id"],
            "title": r["title"],
            "date": r["date"],
            "venue_name": r["venue_name"],
            "neighborhood": r["neighborhood"],
            "budget_required": r["budget_required"],
            "expected_visitors": r["expected_visitors"],
            "venue_capacity": r["venue_capacity"],
            "partner_count": r["partner_count"],
            "score": r["score"],
            "theme": r["theme"],
        })

    return expected_rows, constraints


def _load_shortlist(path: Path) -> Optional[Tuple[List[str], List[Dict[str, str]]]]:
    rows = _safe_load_csv(path, delimiter=",")
    if rows is None:
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
        if header is None:
            return None
        return header, rows
    except Exception:
        return None


def _compare_shortlist_values(expected_rows: List[Dict[str, Any]], actual_rows: List[Dict[str, str]], header: List[str]) -> bool:
    if len(expected_rows) != len(actual_rows):
        return False
    required_cols = ["event_id","title","date","venue_name","neighborhood","budget_required","expected_visitors","venue_capacity","partner_count","score"]
    if header != required_cols:
        return False
    for i, exp in enumerate(expected_rows):
        act = actual_rows[i]
        # Exact string checks
        if act.get("event_id") != exp["event_id"]:
            return False
        if act.get("title") != exp["title"]:
            return False
        if act.get("date") != exp["date"]:
            return False
        if act.get("venue_name") != exp["venue_name"]:
            return False
        if act.get("neighborhood") != exp["neighborhood"]:
            return False
        # Numeric checks
        bi = _parse_int(act.get("budget_required"))
        ei = _parse_int(act.get("expected_visitors"))
        vi = _parse_int(act.get("venue_capacity"))
        pi = _parse_int(act.get("partner_count"))
        sf = _parse_float(act.get("score"))
        if bi is None or ei is None or vi is None or pi is None or sf is None:
            return False
        if bi != exp["budget_required"]:
            return False
        if ei != exp["expected_visitors"]:
            return False
        if vi != exp["venue_capacity"]:
            return False
        if pi != exp["partner_count"]:
            return False
        if abs(sf - float(exp["score"])) > 1e-6:
            return False
    return True


def _press_release_contains_required(content: str, top: Dict[str, Any]) -> bool:
    # Check presence of values: title, date, venue name, neighborhood, expected_visitors, partner_count, venue_capacity
    checks = []
    checks.append(top["title"])
    checks.append(top["date"])
    checks.append(top["venue_name"])
    checks.append(top["neighborhood"])
    # numeric variants
    checks_num = []
    checks_num.extend(_number_string_variants(top["expected_visitors"]))
    checks_num.extend(_number_string_variants(top["partner_count"]))
    checks_num.extend(_number_string_variants(top["venue_capacity"]))

    ok = True
    for t in checks:
        if t not in content:
            ok = False
            break
    if not ok:
        return False
    # For numeric values, require at least one variant each to be present
    have_expected = _text_contains_any(content, checks_num[:len(_number_string_variants(top["expected_visitors"]))])
    have_partner = _text_contains_any(content, checks_num[len(_number_string_variants(top["expected_visitors"])):len(_number_string_variants(top["expected_visitors"]))+len(_number_string_variants(top["partner_count"]))])
    have_capacity = _text_contains_any(content, checks_num[-len(_number_string_variants(top["venue_capacity"])):])
    return have_expected and have_partner and have_capacity


def _press_release_summary_values_present(content: str, top: Dict[str, Any]) -> bool:
    # Expect Data summary section mention and values for: event_id, title, date, venue_name, neighborhood,
    # expected_visitors, partner_count, venue_capacity, budget_required, score.
    if "Data summary" not in content and "data summary" not in content.lower():
        return False
    value_checks: List[str] = []
    value_checks.append(top["event_id"])
    value_checks.append(top["title"])
    value_checks.append(top["date"])
    value_checks.append(top["venue_name"])
    value_checks.append(top["neighborhood"])
    # Numeric lists: include variants
    numeric_groups = [
        _number_string_variants(top["expected_visitors"]),
        _number_string_variants(top["partner_count"]),
        _number_string_variants(top["venue_capacity"]),
        _number_string_variants(top["budget_required"]),
        _number_string_variants(float(top["score"])),
    ]
    # All textual and date checks must be present
    for v in value_checks:
        if v not in content:
            return False
    # For each numeric group require presence of at least one variant
    for group in numeric_groups:
        if not _text_contains_any(content, group):
            return False
    return True


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "shortlist_exists": 0.0,
        "shortlist_columns_order": 0.0,
        "shortlist_row_count": 0.0,
        "shortlist_rank_ids": 0.0,
        "shortlist_values_correct": 0.0,
        "press_release_exists": 0.0,
        "press_release_no_placeholders": 0.0,
        "press_release_mentions_required_values": 0.0,
        "press_release_data_summary_present": 0.0,
        "press_release_consistent_with_shortlist_top": 0.0,
    }

    # Compute expected shortlist from inputs
    expected = _compute_expected_shortlist(workspace)
    expected_rows: Optional[List[Dict[str, Any]]] = None
    expected_constraints: Optional[Dict[str, Any]] = None
    if expected is not None:
        expected_rows, expected_constraints = expected

    # Check shortlist.csv
    shortlist_path = workspace / "output" / "shortlist.csv"
    if shortlist_path.exists() and shortlist_path.is_file():
        scores["shortlist_exists"] = 1.0
        loaded = _load_shortlist(shortlist_path)
        if loaded is not None:
            header, actual_rows = loaded
            required_cols = ["event_id","title","date","venue_name","neighborhood","budget_required","expected_visitors","venue_capacity","partner_count","score"]
            if header == required_cols:
                scores["shortlist_columns_order"] = 1.0
            # Row count
            if expected_constraints is not None:
                if len(actual_rows) == expected_constraints.get("top_n"):
                    scores["shortlist_row_count"] = 1.0
            # Rank IDs and values correctness
            if expected_rows is not None and len(actual_rows) == len(expected_rows):
                actual_ids = [r.get("event_id") for r in actual_rows]
                expected_ids = [r["event_id"] for r in expected_rows]
                if actual_ids == expected_ids:
                    scores["shortlist_rank_ids"] = 1.0
                if _compare_shortlist_values(expected_rows, actual_rows, header):
                    scores["shortlist_values_correct"] = 1.0
    # Press release checks
    pr_path = workspace / "output" / "press_release.md"
    content = _safe_read_text(pr_path) if pr_path.exists() and pr_path.is_file() else None
    if content is not None:
        scores["press_release_exists"] = 1.0
        if "{{" not in content and "}}" not in content:
            scores["press_release_no_placeholders"] = 1.0
        # Determine top event expected for PR
        top_expected: Optional[Dict[str, Any]] = None
        if expected_rows is not None and len(expected_rows) > 0:
            top_expected = expected_rows[0].copy()
            # Include budget_required and score for summary check
            top_expected["budget_required"] = expected_rows[0]["budget_required"]
            top_expected["score"] = expected_rows[0]["score"]
        # Required mentions
        if top_expected is not None:
            if _press_release_contains_required(content, top_expected):
                scores["press_release_mentions_required_values"] = 1.0
            if _press_release_summary_values_present(content, top_expected):
                scores["press_release_data_summary_present"] = 1.0
        # Cross-consistency with shortlist top row if available
        loaded = _load_shortlist(shortlist_path) if shortlist_path.exists() else None
        if loaded is not None:
            header, actual_rows = loaded
            if actual_rows:
                top_row = actual_rows[0]
                try:
                    # Gather values from top row
                    title = top_row.get("title", "")
                    date = top_row.get("date", "")
                    venue_name = top_row.get("venue_name", "")
                    neighborhood = top_row.get("neighborhood", "")
                    event_id = top_row.get("event_id", "")
                    expected_visitors = _parse_int(top_row.get("expected_visitors"))
                    partner_count = _parse_int(top_row.get("partner_count"))
                    venue_capacity = _parse_int(top_row.get("venue_capacity"))
                    budget_required = _parse_int(top_row.get("budget_required"))
                    ok = True
                    for v in [title, date, venue_name, neighborhood, event_id]:
                        if not v or v not in content:
                            ok = False
                            break
                    if ok:
                        # Numeric mentions tolerant
                        if not _text_contains_any(content, _number_string_variants(expected_visitors if expected_visitors is not None else -999)):
                            ok = False
                        if not _text_contains_any(content, _number_string_variants(partner_count if partner_count is not None else -999)):
                            ok = False
                        if not _text_contains_any(content, _number_string_variants(venue_capacity if venue_capacity is not None else -999)):
                            ok = False
                        if not _text_contains_any(content, _number_string_variants(budget_required if budget_required is not None else -999)):
                            ok = False
                    if ok:
                        scores["press_release_consistent_with_shortlist_top"] = 1.0
                except Exception:
                    pass

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()