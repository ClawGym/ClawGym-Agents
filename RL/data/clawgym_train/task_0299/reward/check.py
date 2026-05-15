import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any, Optional


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_csv_dicts(p: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
        return rows
    except Exception:
        return None


def _parse_iso_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s.strip())
    except Exception:
        return None


def _parse_currency_to_number(s: str) -> Optional[float]:
    if s is None:
        return None
    # Extract first number with optional decimal
    m = re.search(r'(\d+(?:\.\d+)?)', s.replace(",", ""))
    if not m:
        return None
    try:
        num = float(m.group(1))
        return num
    except Exception:
        return None


def _safe_lower_list_str(items: List[str]) -> List[str]:
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(it.strip().lower())
    return out


def _parse_inline_list(value: str) -> List[str]:
    # value like ["painting", "mixed media", "printmaking"]
    items = []
    if value is None:
        return items
    if "[" in value and "]" in value:
        inside = value[value.find("[") + 1 : value.rfind("]")]
        # split by commas not considering quotes complexity (inputs are simple)
        parts = [p.strip() for p in inside.split(",") if p.strip()]
        for p in parts:
            # strip optional quotes
            p = p.strip()
            if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
                p = p[1:-1]
            items.append(p)
    else:
        # fallback: comma-separated
        parts = [p.strip() for p in value.split(",") if p.strip()]
        items.extend(parts)
    return items


def _load_profile_yaml(p: Path) -> Optional[Dict[str, Any]]:
    # Minimal, deterministic parser for the known structure
    text = _read_text(p)
    if text is None:
        return None
    prefs = {
        "mediums": [],
        "acceptable_regions": [],
        "min_prize_gbp": None,
        "max_fee_gbp": None,
        "deadline_window": {"earliest": None, "latest": None},
        "exclude_themes": [],
    }
    in_prefs = False
    in_deadline = False
    in_exclude = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")
        if not line.strip():
            continue
        if line.strip().startswith("#"):
            continue
        if line.startswith("preferences:"):
            in_prefs = True
            in_deadline = False
            in_exclude = False
            continue
        if not in_prefs:
            continue
        # detect indentation level
        stripped = line.strip()
        # Deadline window block
        if re.match(r"^\s*deadline_window:\s*$", line):
            in_deadline = True
            in_exclude = False
            continue
        if re.match(r"^\s*exclude_themes:\s*$", line):
            in_exclude = True
            in_deadline = False
            continue
        if in_deadline:
            m = re.match(r"^\s*(earliest|latest):\s*\"?([0-9]{4}-[0-9]{2}-[0-9]{2})\"?\s*$", line)
            if m:
                key = m.group(1)
                prefs["deadline_window"][key] = m.group(2)
                continue
            # If dedent to next top key
            if re.match(r"^\s*\w+:\s*", line):
                in_deadline = False
                # fall through to process as a top-level preference line
        if in_exclude:
            m = re.match(r"^\s*-\s*\"?([^\"]+)\"?\s*$", line)
            if m:
                prefs["exclude_themes"].append(m.group(1))
                continue
            # dedent
            if re.match(r"^\s*\w+:\s*", line):
                in_exclude = False
                # fall through
        # Top-level under preferences
        m_key_val = re.match(r"^\s*(\w+):\s*(.*)$", line)
        if m_key_val:
            key = m_key_val.group(1)
            val = m_key_val.group(2)
            if key in ("mediums", "acceptable_regions"):
                items = _parse_inline_list(val)
                prefs[key] = items
            elif key in ("min_prize_gbp", "max_fee_gbp"):
                try:
                    prefs[key] = float(val.strip())
                except Exception:
                    return None
            # other keys handled elsewhere
            continue
    # Validate required fields
    try:
        if prefs["deadline_window"]["earliest"] is None or prefs["deadline_window"]["latest"] is None:
            return None
        # Normalize types
        prefs["mediums"] = _safe_lower_list_str(prefs["mediums"])
        prefs["acceptable_regions"] = [r.strip() for r in prefs["acceptable_regions"]]
        prefs["exclude_themes"] = [t.strip() for t in prefs["exclude_themes"]]
        # Ensure numerics
        if prefs["min_prize_gbp"] is None or prefs["max_fee_gbp"] is None:
            return None
        return prefs
    except Exception:
        return None


def _parse_md_announcement(p: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(p)
    if text is None:
        return None
    data = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key_part, val_part = line.split(":", 1)
        key = key_part.strip()
        val = val_part.strip()
        if not key:
            continue
        if key in ["Title", "ID", "Region", "Deadline", "Submission Fee", "Prize", "Accepted Mediums", "Theme"]:
            data[key] = val
    # Validate required keys
    required = ["Title", "ID", "Region", "Deadline", "Submission Fee", "Prize", "Accepted Mediums", "Theme"]
    if any(k not in data for k in required):
        return None
    # Normalize fields
    fee = _parse_currency_to_number(data["Submission Fee"])
    prize = _parse_currency_to_number(data["Prize"])
    dl = _parse_iso_date(data["Deadline"])
    mediums = [m.strip() for m in data["Accepted Mediums"].split(",") if m.strip()]
    result = {
        "id": data["ID"].strip(),
        "title": data["Title"].strip(),
        "region": data["Region"].strip(),
        "deadline": dl.isoformat() if dl else None,
        "fee_gbp": fee,
        "prize_gbp": prize,
        "mediums": [m.lower() for m in mediums],
        "theme": data["Theme"].strip(),
    }
    if any(v is None for v in (result["deadline"], result["fee_gbp"], result["prize_gbp"])):
        return None
    return result


def _load_index_map(index_csv: Path) -> Optional[Dict[str, Dict[str, str]]]:
    rows = _load_csv_dicts(index_csv)
    if rows is None:
        return None
    mapping = {}
    for r in rows:
        idv = r.get("id")
        tit = r.get("title")
        reg = r.get("region")
        src = r.get("source")
        if idv is None or tit is None or reg is None or src is None:
            return None
        mapping[idv] = {"title": tit, "region": reg, "source": src}
    return mapping


def _collect_md_announcements(md_dir: Path) -> Optional[List[Dict[str, Any]]]:
    if not md_dir.exists():
        return None
    results = []
    for p in sorted(md_dir.glob("*.md")):
        parsed = _parse_md_announcement(p)
        if parsed is None:
            # If a file is present but malformed, treat as failure by skipping parsing; caller will detect via counts
            continue
        results.append(parsed)
    return results


def _crosscheck_and_normalize(md_list: List[Dict[str, Any]], index_map: Dict[str, Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for md in md_list:
        idv = md["id"]
        if idv not in index_map:
            continue
        idx = index_map[idv]
        consistency = (md["title"] == idx["title"]) and (md["region"] == idx["region"])
        # Only keep those whose id appears and whose title and region match exactly
        if not consistency:
            continue
        obj = {
            "id": idv,
            "title": md["title"],
            "deadline": md["deadline"],
            "fee_gbp": md["fee_gbp"],
            "prize_gbp": md["prize_gbp"],
            "mediums": md["mediums"],
            "region": md["region"],
            "theme": md["theme"],
            "source": idx["source"],
            "consistency": True,  # by construction
            "eligible": False,    # fill later
        }
        out.append(obj)
    return out


def _compute_eligibility(obj: Dict[str, Any], prefs: Dict[str, Any], applied_ids: List[str]) -> bool:
    # Region check
    if obj["region"] not in prefs["acceptable_regions"]:
        return False
    # Deadline window inclusive
    dl = _parse_iso_date(obj["deadline"])
    earliest = _parse_iso_date(prefs["deadline_window"]["earliest"])
    latest = _parse_iso_date(prefs["deadline_window"]["latest"])
    if dl is None or earliest is None or latest is None:
        return False
    if not (earliest <= dl <= latest):
        return False
    # Fee <= max
    try:
        if float(obj["fee_gbp"]) > float(prefs["max_fee_gbp"]):
            return False
    except Exception:
        return False
    # Prize >= min
    try:
        if float(obj["prize_gbp"]) < float(prefs["min_prize_gbp"]):
            return False
    except Exception:
        return False
    # Mediums overlap (case-insensitive)
    cand_meds = set([m.strip().lower() for m in obj.get("mediums", []) if isinstance(m, str)])
    pref_meds = set([m.strip().lower() for m in prefs.get("mediums", []) if isinstance(m, str)])
    if cand_meds.isdisjoint(pref_meds):
        return False
    # Theme exclusion (case-insensitive substring)
    theme_l = (obj.get("theme") or "").lower()
    for term in prefs.get("exclude_themes", []):
        if term and term.lower() in theme_l:
            return False
    # History exclusion
    if obj["id"] in applied_ids:
        return False
    return True


def _load_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    index_csv = workspace / "input" / "calls" / "index.csv"
    md_dir = workspace / "input" / "calls"
    profile_yaml = workspace / "input" / "artist_profile.yaml"
    history_json = workspace / "input" / "history" / "applied.json"

    index_map = _load_index_map(index_csv)
    if index_map is None:
        return None
    md_list = _collect_md_announcements(md_dir)
    if md_list is None:
        return None
    prefs = _load_profile_yaml(profile_yaml)
    if prefs is None:
        return None
    history = _load_json(history_json) or {}
    applied_ids = history.get("applied_ids", []) if isinstance(history, dict) else []

    normalized = _crosscheck_and_normalize(md_list, index_map)
    # Fill eligibility
    for obj in normalized:
        obj["eligible"] = _compute_eligibility(obj, prefs, applied_ids)
    # Build expected shortlist by filtering and sorting
    eligible_objs = [o for o in normalized if o["eligible"]]
    # Sort: prize_gbp desc, fee_gbp asc, deadline asc, id asc
    def sort_key(o):
        # parse types for reliable sorting
        prize = float(o["prize_gbp"])
        fee = float(o["fee_gbp"])
        dl = _parse_iso_date(o["deadline"])
        dl_tuple = (dl.year, dl.month, dl.day) if dl else (9999, 12, 31)
        return (-prize, fee, dl_tuple, o["id"])
    eligible_sorted = sorted(eligible_objs, key=sort_key)
    # Assign ranks starting at 1
    shortlist_rows = []
    rank = 1
    for o in eligible_sorted:
        shortlist_rows.append({
            "rank": rank,
            "id": o["id"],
            "title": o["title"],
            "deadline": o["deadline"],
            "region": o["region"],
            "fee_gbp": float(o["fee_gbp"]),
            "prize_gbp": float(o["prize_gbp"]),
        })
        rank += 1
    return {
        "normalized": normalized,
        "shortlist": shortlist_rows,
    }


def _load_jsonl_objs(p: Path) -> Optional[List[Dict[str, Any]]]:
    if not p.exists():
        return None
    try:
        objs = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                obj = json.loads(line)
                if not isinstance(obj, dict):
                    return None
                objs.append(obj)
        return objs
    except Exception:
        return None


def _validate_normalized_structure(objs: List[Dict[str, Any]]) -> bool:
    required_fields = [
        "id",
        "title",
        "deadline",
        "fee_gbp",
        "prize_gbp",
        "mediums",
        "region",
        "theme",
        "source",
        "consistency",
        "eligible",
    ]
    for obj in objs:
        # exact fields only
        if set(obj.keys()) != set(required_fields):
            return False
        # types and formats
        if not isinstance(obj["id"], str):
            return False
        if not isinstance(obj["title"], str):
            return False
        if not isinstance(obj["region"], str) or obj["region"] not in ("UK", "Online"):
            return False
        if not isinstance(obj["theme"], str):
            return False
        if not isinstance(obj["source"], str):
            return False
        if not isinstance(obj["consistency"], bool):
            return False
        if not isinstance(obj["eligible"], bool):
            return False
        # numbers
        if not isinstance(obj["fee_gbp"], (int, float)):
            return False
        if not isinstance(obj["prize_gbp"], (int, float)):
            return False
        # date format
        if not isinstance(obj["deadline"], str) or _parse_iso_date(obj["deadline"]) is None:
            return False
        # mediums lowercase array
        if not isinstance(obj["mediums"], list):
            return False
        for m in obj["mediums"]:
            if not isinstance(m, str):
                return False
            if m != m.lower():
                return False
    return True


def _float_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _compare_normalized(expected: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> bool:
    # Compare as a mapping by id to enforce exact content match for all expected items
    exp_map = {o["id"]: o for o in expected}
    act_map = {o["id"]: o for o in actual}
    if set(exp_map.keys()) != set(act_map.keys()):
        return False
    for idv, exp in exp_map.items():
        act = act_map[idv]
        # Check each field equality
        for k in exp.keys():
            ev = exp[k]
            av = act[k]
            if k in ("fee_gbp", "prize_gbp"):
                if not _float_equal(ev, av):
                    return False
            elif k == "mediums":
                if ev != av:
                    return False
            else:
                if ev != av:
                    return False
    return True


def _load_csv_rows_with_header(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            content = f.read().splitlines()
        if not content:
            return None
        header = content[0].strip()
        reader = csv.DictReader(content)
        rows = [dict(r) for r in reader]
        return {"header": header, "rows": rows}
    except Exception:
        return None


def _validate_shortlist_structure(data: Dict[str, Any]) -> bool:
    # Check header and field types, numeric-only money values, ISO dates
    expected_header = "rank,id,title,deadline,region,fee_gbp,prize_gbp"
    if data["header"] != expected_header:
        return False
    rows = data["rows"]
    # Validate each row fields present and numeric formats
    for r in rows:
        # All keys must match expected header columns
        if set(r.keys()) != set(expected_header.split(",")):
            return False
        # rank must be an integer number string
        rank_s = r.get("rank", "").strip()
        if not re.fullmatch(r"\d+", rank_s or ""):
            return False
        # id, title, region non-empty
        if not r.get("id") or not r.get("title") or not r.get("region"):
            return False
        if r["region"] not in ("UK", "Online"):
            return False
        # deadline ISO date
        if _parse_iso_date(r.get("deadline", "")) is None:
            return False
        # fee/prize numeric-only strings (no currency symbols)
        fee_s = (r.get("fee_gbp") or "").strip()
        prize_s = (r.get("prize_gbp") or "").strip()
        if not re.fullmatch(r"\d+(\.\d+)?", fee_s):
            return False
        if not re.fullmatch(r"\d+(\.\d+)?", prize_s):
            return False
    return True


def _compare_shortlist(expected: List[Dict[str, Any]], data: Dict[str, Any]) -> Dict[str, bool]:
    rows = data["rows"]
    # Count check
    count_ok = (len(rows) == len(expected))
    # Content and order check
    # Build actual list of dicts with parsed numeric types and compare exactly by order
    actual = []
    for r in rows:
        actual.append({
            "rank": int(r["rank"]),
            "id": r["id"],
            "title": r["title"],
            "deadline": r["deadline"],
            "region": r["region"],
            "fee_gbp": float(r["fee_gbp"]),
            "prize_gbp": float(r["prize_gbp"]),
        })
    # Check ranks start at 1 and increment by 1
    ranks_ok = all(actual[i]["rank"] == i + 1 for i in range(len(actual)))
    # Check exact order by id vs expected
    order_ok = [a["id"] for a in actual] == [e["id"] for e in expected]
    # Check content match per row
    content_ok = True
    if len(actual) != len(expected):
        content_ok = False
    else:
        for a, e in zip(actual, expected):
            if a["id"] != e["id"] or a["title"] != e["title"] or a["deadline"] != e["deadline"] or a["region"] != e["region"]:
                content_ok = False
                break
            if not _float_equal(a["fee_gbp"], e["fee_gbp"]) or not _float_equal(a["prize_gbp"], e["prize_gbp"]):
                content_ok = False
                break
    return {
        "count_ok": count_ok,
        "ranks_ok": ranks_ok and order_ok,
        "content_ok": content_ok and order_ok,
    }


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "normalized_jsonl_exists": 0.0,
        "normalized_jsonl_structure_valid": 0.0,
        "normalized_jsonl_records_count": 0.0,
        "normalized_jsonl_content_match": 0.0,
        "shortlist_csv_exists": 0.0,
        "shortlist_csv_structure_valid": 0.0,
        "shortlist_records_count": 0.0,
        "shortlist_sorted_and_ranks_valid": 0.0,
        "shortlist_content_match": 0.0,
    }

    expected = _load_expected(workspace)
    # Load student's outputs
    norm_path = workspace / "output" / "normalized_calls.jsonl"
    shortlist_path = workspace / "output" / "shortlist.csv"

    norm_objs = _load_jsonl_objs(norm_path)
    if norm_objs is not None:
        scores["normalized_jsonl_exists"] = 1.0
        if _validate_normalized_structure(norm_objs):
            scores["normalized_jsonl_structure_valid"] = 1.0

    if expected is not None and norm_objs is not None:
        # Compare counts and content (cross-checked announcements only)
        exp_norm = expected["normalized"]
        if len(exp_norm) == len(norm_objs):
            scores["normalized_jsonl_records_count"] = 1.0
        if _compare_normalized(exp_norm, norm_objs):
            scores["normalized_jsonl_content_match"] = 1.0

    shortlist_data = _load_csv_rows_with_header(shortlist_path)
    if shortlist_data is not None:
        scores["shortlist_csv_exists"] = 1.0
        if _validate_shortlist_structure(shortlist_data):
            scores["shortlist_csv_structure_valid"] = 1.0

    if expected is not None and shortlist_data is not None:
        comp = _compare_shortlist(expected["shortlist"], shortlist_data)
        if comp["count_ok"]:
            scores["shortlist_records_count"] = 1.0
        if comp["ranks_ok"]:
            scores["shortlist_sorted_and_ranks_valid"] = 1.0
        if comp["content_ok"]:
            scores["shortlist_content_match"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()