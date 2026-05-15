import json
import csv
import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


def _read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(p: Path) -> Optional[Any]:
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_csv(p: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [dict(row) for row in reader]
    except Exception:
        return None


def _safe_read_jsonl(p: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        items = []
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    return None
                if not isinstance(obj, dict):
                    return None
                items.append(obj)
        return items
    except Exception:
        return None


def _count_csv_records(p: Path) -> Optional[int]:
    rows = _safe_read_csv(p)
    if rows is None:
        return None
    return len(rows)


def _count_jsonl_records(p: Path) -> Optional[int]:
    items = _safe_read_jsonl(p)
    if items is None:
        return None
    return len(items)


def _count_md_nonempty_lines(p: Path) -> Optional[int]:
    text = _read_text(p)
    if text is None:
        return None
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return len(lines)


def _compute_manifest_expected(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    input_dir = workspace / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return None
    entries: List[Dict[str, Any]] = []
    # include all files under input/ (recursively)
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.as_posix()
        # Determine relative from workspace root
        rel_path = str(path.relative_to(workspace).as_posix())
        ext = path.suffix.lower()
        if ext == ".csv":
            fmt = "csv"
            count = _count_csv_records(path)
        elif ext == ".jsonl":
            fmt = "jsonl"
            count = _count_jsonl_records(path)
        elif ext == ".md":
            fmt = "md"
            count = _count_md_nonempty_lines(path)
        else:
            # Only specified formats are expected; skip others
            continue
        if count is None:
            return None
        entries.append({
            "file_path": rel_path,
            "format": fmt,
            "record_count": count
        })
    # Ensure deterministic ordering by file_path
    entries.sort(key=lambda d: d["file_path"])
    return entries


def _parse_notes_for_criteria(notes_path: Path) -> Optional[Dict[str, Any]]:
    text = _read_text(notes_path)
    if text is None:
        return None
    liberties: List[str] = []
    start_year = None
    end_year = None
    for line in text.splitlines():
        l = line.strip()
        if l.lower().startswith("- liberties of focus:"):
            # Extract after colon
            parts = l.split(":", 1)
            if len(parts) == 2:
                vals = parts[1].split(",")
                liberties = [v.strip() for v in vals if v.strip()]
        if l.lower().startswith("- timeframe:"):
            # Extract years e.g., 1800–1970 (note en dash or hyphen)
            years = re.findall(r"(\d{4})", l)
            if len(years) >= 2:
                start_year = int(years[0])
                end_year = int(years[1])
    if not liberties or start_year is None or end_year is None:
        return None
    return {"liberties": liberties, "start_year": start_year, "end_year": end_year}


def _parse_iso_date(d: str) -> Optional[datetime]:
    try:
        return datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return None


def _compute_filtered_events(events: List[Dict[str, Any]], liberties: List[str], start_year: int, end_year: int) -> Optional[List[Dict[str, Any]]]:
    filtered: List[Dict[str, Any]] = []
    for row in events:
        lib = row.get("liberty", "").strip()
        if lib not in liberties:
            continue
        dstr = row.get("date", "").strip()
        dt = _parse_iso_date(dstr)
        if dt is None:
            return None
        if start_year <= dt.year <= end_year:
            # Validate impact_score numeric
            try:
                impact = int(str(row.get("impact_score", "")).strip())
            except Exception:
                return None
            row["_date_obj"] = dt
            row["_impact_int"] = impact
            filtered.append(row)
    return filtered


def _rank_and_select_top3_per_liberty(filtered_events: List[Dict[str, Any]], liberties: List[str]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    per_lib: Dict[str, List[Dict[str, Any]]] = {lib: [] for lib in liberties}
    for row in filtered_events:
        lib = row.get("liberty", "").strip()
        if lib in per_lib:
            per_lib[lib].append(row)
    top3: Dict[str, List[Dict[str, Any]]] = {}
    for lib in liberties:
        rows = per_lib.get(lib, [])
        # Sort by impact_score desc, then by earlier date first, then by id ascending for full determinism
        try:
            rows_sorted = sorted(rows, key=lambda r: (-int(r["_impact_int"]), r["_date_obj"], r.get("id", "")))
        except Exception:
            return None
        top3[lib] = rows_sorted[:3]
    return top3


def _build_sources_map(sources: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    m: Dict[str, Dict[str, Any]] = {}
    for s in sources:
        sid = str(s.get("source_id", "")).strip()
        if sid:
            m[sid] = s
    return m


def _load_expected_inputs(workspace: Path) -> Optional[Dict[str, Any]]:
    events_path = workspace / "input" / "events.csv"
    sources_path = workspace / "input" / "sources.jsonl"
    notes_path = workspace / "input" / "notes.md"
    if not events_path.exists() or not sources_path.exists() or not notes_path.exists():
        return None
    events = _safe_read_csv(events_path)
    sources = _safe_read_jsonl(sources_path)
    notes = _parse_notes_for_criteria(notes_path)
    if events is None or sources is None or notes is None:
        return None
    return {"events": events, "sources": sources, "notes": notes}


def _expected_events_top_rows(workspace: Path) -> Optional[Dict[str, Any]]:
    loaded = _load_expected_inputs(workspace)
    if loaded is None:
        return None
    events = loaded["events"]
    sources = loaded["sources"]
    notes = loaded["notes"]
    liberties = notes["liberties"]
    start_year = notes["start_year"]
    end_year = notes["end_year"]
    filtered = _compute_filtered_events(events, liberties, start_year, end_year)
    if filtered is None:
        return None
    top3 = _rank_and_select_top3_per_liberty(filtered, liberties)
    if top3 is None:
        return None
    src_map = _build_sources_map(sources)
    expected_rows: Dict[str, Dict[str, Any]] = {}
    # Build expected rows keyed by id
    for lib in liberties:
        for r in top3[lib]:
            sid = str(r.get("source_id", "")).strip()
            src = src_map.get(sid)
            if not src:
                return None
            row = {
                "id": r.get("id", ""),
                "date": r.get("date", ""),
                "country": r.get("country", ""),
                "region": r.get("region", ""),
                "liberty": r.get("liberty", ""),
                "change": r.get("change", ""),
                "impact_score": str(int(r["_impact_int"])),
                "source_title": src.get("title", ""),
                "source_year": str(src.get("year", "")),
            }
            expected_rows[row["id"]] = row
    # Also return expected per-liberty ordered ids for ordering checks
    expected_order_per_lib = {lib: [r.get("id", "") for r in top3[lib]] for lib in liberties}
    return {"rows_by_id": expected_rows, "order_per_liberty": expected_order_per_lib, "liberties": liberties, "filtered_universe": filtered}


def _read_events_top_csv(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    p = workspace / "output" / "events_top.csv"
    if not p.exists():
        return None
    rows = _safe_read_csv(p)
    return rows


def _load_stats_json(workspace: Path) -> Optional[Dict[str, Any]]:
    p = workspace / "output" / "stats.json"
    if not p.exists():
        return None
    obj = _safe_load_json(p)
    if not isinstance(obj, dict):
        return None
    return obj


def _load_manifest_json(workspace: Path) -> Optional[Any]:
    p = workspace / "output" / "manifest.json"
    if not p.exists():
        return None
    obj = _safe_load_json(p)
    return obj


def _check_build_script(workspace: Path) -> float:
    p = workspace / "scripts" / "build.py"
    if not p.exists() or not p.is_file():
        return 0.0
    text = _read_text(p)
    if text is None:
        return 0.0
    # Check it references input/ and output/
    if "input/" not in text or "output/" not in text:
        return 0.0
    # Check for common external deps
    banned = ["pandas", "numpy", "requests", "yaml", "scipy", "matplotlib", "sklearn", "bs4", "BeautifulSoup", "sqlalchemy"]
    for b in banned:
        if re.search(rf"\bimport\s+{re.escape(b)}\b", text) or re.search(rf"\bfrom\s+{re.escape(b)}\b", text):
            return 0.0
    return 1.0


def _check_manifest(workspace: Path) -> float:
    expected = _compute_manifest_expected(workspace)
    actual = _load_manifest_json(workspace)
    if expected is None or actual is None:
        return 0.0
    if not isinstance(actual, list):
        return 0.0
    # Validate structure: each item must be dict with required keys and types
    try:
        normalized_actual = []
        for item in actual:
            if not isinstance(item, dict):
                return 0.0
            if set(item.keys()) != {"file_path", "format", "record_count"} and not set({"file_path", "format", "record_count"}).issubset(item.keys()):
                # allow extra keys but must include required
                return 0.0
            file_path = item.get("file_path")
            fmt = item.get("format")
            rc = item.get("record_count")
            if not isinstance(file_path, str) or not isinstance(fmt, str) or not isinstance(rc, (int,)):
                return 0.0
            normalized_actual.append({
                "file_path": file_path,
                "format": fmt,
                "record_count": rc
            })
        # Sort both by file_path for comparison
        norm_exp = sorted(expected, key=lambda d: d["file_path"])
        norm_act = sorted(normalized_actual, key=lambda d: d["file_path"])
        if len(norm_exp) != len(norm_act):
            return 0.0
        for e, a in zip(norm_exp, norm_act):
            if e["file_path"] != a["file_path"]:
                return 0.0
            if e["format"] != a["format"]:
                return 0.0
            if e["record_count"] != a["record_count"]:
                return 0.0
    except Exception:
        return 0.0
    return 1.0


def _check_events_top_csv(workspace: Path) -> float:
    expected_bundle = _expected_events_top_rows(workspace)
    rows = _read_events_top_csv(workspace)
    if expected_bundle is None or rows is None:
        return 0.0
    expected_rows_by_id = expected_bundle["rows_by_id"]
    liberties = expected_bundle["liberties"]
    expected_order_per_lib = expected_bundle["order_per_liberty"]
    # Check header order
    expected_header = ["id", "date", "country", "region", "liberty", "change", "impact_score", "source_title", "source_year"]
    # csv.DictReader doesn't retain header order; we can re-open raw file to check header
    try:
        with (workspace / "output" / "events_top.csv").open("r", encoding="utf-8", newline="") as f:
            raw_header = f.readline().strip()
    except Exception:
        return 0.0
    if raw_header.replace("\ufeff", "") != ",".join(expected_header):
        return 0.0
    # Check number of rows equals expected
    if len(rows) != sum(len(expected_order_per_lib[lib]) for lib in liberties):
        return 0.0
    # Index actual rows by id and maintain per-liberty order
    actual_by_id: Dict[str, Dict[str, Any]] = {}
    per_lib_order_actual: Dict[str, List[str]] = {lib: [] for lib in liberties}
    for r in rows:
        rid = r.get("id", "")
        actual_by_id[rid] = r
        lib = r.get("liberty", "")
        if lib in per_lib_order_actual:
            per_lib_order_actual[lib].append(rid)
    # Verify each expected id present and row values match exactly
    for rid, exp in expected_rows_by_id.items():
        act = actual_by_id.get(rid)
        if not act:
            return 0.0
        for col in expected_header:
            ev = exp.get(col)
            av = act.get(col)
            if ev is None or av is None:
                return 0.0
            # normalize trimming
            if str(ev).strip() != str(av).strip():
                return 0.0
    # Verify per-liberty ordering follows expected ranking
    for lib in liberties:
        if per_lib_order_actual.get(lib) != expected_order_per_lib.get(lib):
            return 0.0
    return 1.0


def _compute_stats_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    bundle = _expected_events_top_rows(workspace)
    if bundle is None:
        return None
    filtered = bundle["filtered_universe"]
    liberties = bundle["liberties"]
    order_per_lib = bundle["order_per_liberty"]
    per_lib_stats: Dict[str, Dict[str, Any]] = {}
    for lib in liberties:
        items = [r for r in filtered if r.get("liberty", "").strip() == lib]
        total = len(items)
        expansions = sum(1 for r in items if str(r.get("change", "")).strip().lower() == "expansion")
        restrictions = sum(1 for r in items if str(r.get("change", "")).strip().lower() == "restriction")
        top3_ids = order_per_lib.get(lib, [])
        per_lib_stats[lib] = {
            "total": total,
            "expansions": expansions,
            "restrictions": restrictions,
            "top3_ids": top3_ids
        }
    expected = {
        "total_events_considered": len(filtered),
        "per_liberty": per_lib_stats
    }
    return expected


def _check_stats_json(workspace: Path) -> float:
    expected = _compute_stats_expected(workspace)
    actual = _load_stats_json(workspace)
    if expected is None or actual is None:
        return 0.0
    try:
        if not isinstance(actual.get("total_events_considered"), int):
            return 0.0
        if actual.get("total_events_considered") != expected["total_events_considered"]:
            return 0.0
        per_lib_act = actual.get("per_liberty")
        if not isinstance(per_lib_act, dict):
            return 0.0
        for lib, expvals in expected["per_liberty"].items():
            if lib not in per_lib_act or not isinstance(per_lib_act[lib], dict):
                return 0.0
            a = per_lib_act[lib]
            for k in ["total", "expansions", "restrictions", "top3_ids"]:
                if k not in a:
                    return 0.0
            if a["total"] != expvals["total"]:
                return 0.0
            if a["expansions"] != expvals["expansions"]:
                return 0.0
            if a["restrictions"] != expvals["restrictions"]:
                return 0.0
            # top3_ids must be array and match order from events_top.csv (we will rely on CSV content check later)
            if not isinstance(a["top3_ids"], list):
                return 0.0
            # We can also check that it matches expected
            if a["top3_ids"] != expvals["top3_ids"]:
                return 0.0
    except Exception:
        return 0.0
    return 1.0


def _first_nonempty_line(text: str) -> Optional[str]:
    for ln in text.splitlines():
        if ln.strip():
            return ln.strip()
    return None


def _word_count(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _check_draft_section(workspace: Path) -> Dict[str, float]:
    p = workspace / "output" / "draft_section.md"
    scores = {
        "draft_section_length_and_title": 0.0,
        "draft_section_method_and_citations": 0.0
    }
    text = _read_text(p)
    expected_inputs = _load_expected_inputs(workspace)
    expected_bundle = _expected_events_top_rows(workspace)
    if text is None or expected_inputs is None or expected_bundle is None:
        return scores
    notes = expected_inputs["notes"]
    liberties = notes["liberties"]
    start_year = notes["start_year"]
    end_year = notes["end_year"]
    # length and title check
    title = _first_nonempty_line(text) or ""
    wc = _word_count(text)
    title_has_years = (str(start_year) in title and str(end_year) in title)
    if 600 <= wc <= 900 and title_has_years:
        scores["draft_section_length_and_title"] = 1.0
    # method note and citations
    lower_text = text.lower()
    method_ok = ("top 3" in lower_text or "top three" in lower_text) and ("impact" in lower_text) and ("tie" in lower_text and "date" in lower_text)
    # Include total events considered number
    expected_stats = _compute_stats_expected(workspace)
    total_ok = False
    if expected_stats:
        total_str = str(expected_stats["total_events_considered"])
        total_ok = total_str in lower_text
    # liberty subsections presence (names or human-friendly)
    liberties_ok = True
    for lib in liberties:
        lib_human = lib.replace("_", " ")
        if lib not in lower_text and lib_human not in lower_text:
            liberties_ok = False
            break
    # expansions/restrictions discussion presence
    exp_restr_ok = ("expansion" in lower_text or "expansions" in lower_text) and ("restriction" in lower_text or "restrictions" in lower_text)
    # citations for each top event
    events_top_expected = expected_bundle["rows_by_id"]
    lines = text.splitlines()
    citations_ok = True
    # Build a mapping of id -> dict containing required fields
    for rid, row in events_top_expected.items():
        title_val = row["source_title"]
        year_val = str(row["source_year"])
        country_val = row["country"]
        # Use event year from date
        d = _parse_iso_date(row["date"])
        if d is None:
            citations_ok = False
            break
        event_year = str(d.year)
        found_line = False
        for ln in lines:
            if f"({title_val}, {year_val})" in ln:
                # Require country and year mentioned in same line
                if (country_val in ln) and (event_year in ln):
                    found_line = True
                    break
        if not found_line:
            citations_ok = False
            break
    if method_ok and total_ok and liberties_ok and exp_restr_ok and citations_ok:
        scores["draft_section_method_and_citations"] = 1.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "build_script_present": 0.0,
        "manifest_json_valid": 0.0,
        "events_top_csv_valid": 0.0,
        "stats_json_valid": 0.0,
        "draft_section_length_and_title": 0.0,
        "draft_section_method_and_citations": 0.0,
    }
    # Check build script
    scores["build_script_present"] = _check_build_script(workspace)
    # Check manifest
    scores["manifest_json_valid"] = _check_manifest(workspace)
    # Check events_top.csv content
    scores["events_top_csv_valid"] = _check_events_top_csv(workspace)
    # Check stats.json
    scores["stats_json_valid"] = _check_stats_json(workspace)
    # Check draft_section.md
    draft_scores = _check_draft_section(workspace)
    for k in ["draft_section_length_and_title", "draft_section_method_and_citations"]:
        scores[k] = draft_scores.get(k, 0.0)
    return scores


def main() -> None:
    workspace = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    result = grade([], str(workspace))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()