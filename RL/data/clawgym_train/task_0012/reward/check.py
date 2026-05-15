import json
import csv
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


def _safe_read_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _safe_read_json(path: Path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _parse_date_yyyy_mm_dd(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_iso8601_z(s: str):
    # Returns a datetime object (UTC) or None
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _scan_library(workspace: Path):
    # Returns mapping {(season:int, episode:int): relative_path_str}
    lib_root = workspace / "media" / "grand_tour"
    mapping = {}
    if not lib_root.exists() or not lib_root.is_dir():
        return mapping
    # Deterministic ordering: sort by string path
    all_files = []
    for p in lib_root.rglob("*"):
        if p.is_file():
            all_files.append(p)
    all_files = sorted(all_files, key=lambda x: str(x).lower())
    pattern = re.compile(r"s(\d{2})e(\d{2})", flags=re.IGNORECASE)
    for p in all_files:
        m = pattern.search(p.name)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            key = (season, episode)
            if key not in mapping:
                rel = p.relative_to(workspace).as_posix()
                mapping[key] = rel
    return mapping


def _load_master(workspace: Path):
    path = workspace / "input" / "episodes_master.csv"
    headers, rows = _safe_read_csv(path)
    if not headers or rows is None:
        return None
    required = ["season", "episode", "title", "release_date", "runtime_min"]
    if headers != required:
        # Accept if same fields but different order? The task specifies format; require exact.
        return None
    parsed = []
    for r in rows:
        try:
            season = int(r["season"])
            episode = int(r["episode"])
            title = r["title"]
            rd = r["release_date"]
            if _parse_date_yyyy_mm_dd(rd) is None:
                return None
            runtime = int(r["runtime_min"])
            parsed.append({
                "season": season,
                "episode": episode,
                "title": title,
                "release_date": rd,
                "runtime_min": runtime,
            })
        except Exception:
            return None
    return parsed


def _load_watch_history(workspace: Path):
    # Returns mapping {(season, episode): {"watched": bool, "last_watched_at": str}}
    path = workspace / "input" / "watch_history.json"
    data = _safe_read_json(path)
    if data is None:
        return None
    entries = data.get("entries")
    if not isinstance(entries, list):
        return None
    mapping = {}
    for e in entries:
        try:
            season = int(e.get("season"))
            episode = int(e.get("episode"))
            watched = bool(e.get("watched", False))
            lwat = e.get("last_watched_at", "")
            if not isinstance(lwat, str):
                lwat = ""
            # Normalize: only retain last_watched_at when watched is True
            if not watched:
                lwat = ""
            mapping[(season, episode)] = {"watched": watched, "last_watched_at": lwat}
        except Exception:
            return None
    return mapping


def _compute_expected(workspace: Path):
    master = _load_master(workspace)
    watch_hist = _load_watch_history(workspace)
    lib_map = _scan_library(workspace)
    if master is None or watch_hist is None:
        return None

    unified = []
    for ep in master:
        key = (ep["season"], ep["episode"])
        in_lib = key in lib_map
        file_path = lib_map.get(key, "")
        wh = watch_hist.get(key, {"watched": False, "last_watched_at": ""})
        watched = bool(wh.get("watched", False))
        lwat = wh.get("last_watched_at", "")
        if not isinstance(lwat, str):
            lwat = ""
        if not watched:
            lwat = ""
        unified.append({
            "season": ep["season"],
            "episode": ep["episode"],
            "title": ep["title"],
            "release_date": ep["release_date"],
            "runtime_min": ep["runtime_min"],
            "in_library": "yes" if in_lib else "no",
            "watched": "true" if watched else "false",
            "last_watched_at": lwat,
            "file_path": file_path,
        })

    def _rank_key(item):
        watched_bool = (item["watched"] == "true")
        if not watched_bool:
            # Unwatched first: release_date asc, tie season asc, episode asc
            return (0, item["release_date"], int(item["season"]), int(item["episode"]))
        # Watched: last_watched_at desc; use negative epoch to sort ascending
        dt = _parse_iso8601_z(item["last_watched_at"])
        if dt is None:
            ts = float("-inf")
        else:
            ts = dt.timestamp()
        return (1, -ts, int(item["season"]), int(item["episode"]))

    unified_sorted = sorted(unified, key=_rank_key)
    # Assign rank
    for idx, item in enumerate(unified_sorted, start=1):
        item["watch_priority_rank"] = str(idx)

    # Prepare expected CSV rows (as strings) in column order
    plan_header = [
        "season",
        "episode",
        "title",
        "release_date",
        "runtime_min",
        "in_library",
        "watched",
        "last_watched_at",
        "file_path",
        "watch_priority_rank",
    ]
    plan_rows = []
    for item in unified_sorted:
        row = [
            str(item["season"]),
            str(item["episode"]),
            item["title"],
            item["release_date"],
            str(item["runtime_min"]),
            item["in_library"],
            item["watched"],
            item["last_watched_at"],
            item["file_path"],
            item["watch_priority_rank"],
        ]
        plan_rows.append(row)

    # Missing episodes CSV
    missing = [e for e in unified if e["in_library"] == "no"]
    missing_sorted = sorted(missing, key=lambda x: (x["release_date"], int(x["season"]), int(x["episode"])))
    missing_header = ["season", "episode", "title", "release_date"]
    missing_rows = []
    for m in missing_sorted:
        missing_rows.append([str(m["season"]), str(m["episode"]), m["title"], m["release_date"]])

    # Summary JSON
    total = len(unified)
    in_lib_count = sum(1 for e in unified if e["in_library"] == "yes")
    missing_count = sum(1 for e in unified if e["in_library"] == "no")
    watched_count = sum(1 for e in unified if e["watched"] == "true")
    unwatched_count = sum(1 for e in unified if e["watched"] == "false")
    unwatched_in_lib_count = sum(1 for e in unified if e["watched"] == "false" and e["in_library"] == "yes")
    unwatched_missing_count = sum(1 for e in unified if e["watched"] == "false" and e["in_library"] == "no")
    # Next up: first in unified_sorted where watched == false
    next_up_obj = None
    for e in unified_sorted:
        if e["watched"] == "false":
            next_up_obj = {
                "season": int(e["season"]),
                "episode": int(e["episode"]),
                "title": e["title"],
                "release_date": e["release_date"],
                "file_path": e["file_path"],
            }
            break
    summary = {
        "total_episodes": total,
        "in_library_count": in_lib_count,
        "missing_count": missing_count,
        "watched_count": watched_count,
        "unwatched_count": unwatched_count,
        "unwatched_in_library_count": unwatched_in_lib_count,
        "unwatched_missing_count": unwatched_missing_count,
        "next_up": next_up_obj,
    }

    return {
        "plan_header": plan_header,
        "plan_rows": plan_rows,
        "missing_header": missing_header,
        "missing_rows": missing_rows,
        "summary": summary,
    }


def _normalize_path_str(s: str) -> str:
    if not isinstance(s, str):
        return ""
    return s.replace("\\", "/")


def _read_output_csv(path: Path):
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            if not rows:
                return None, None
            header = rows[0]
            records = rows[1:]
            return header, records
    except Exception:
        return None, None


def _read_output_plan(path: Path):
    # Use DictReader to ensure columns mapping by header order
    try:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return None, None
            rows = []
            for r in reader:
                # Preserve ordering by constructing list in the same order as header
                rows.append({k: r.get(k, "") for k in reader.fieldnames})
            return reader.fieldnames, rows
    except Exception:
        return None, None


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "watch_plan_header_and_order": 0.0,
        "watch_plan_row_count": 0.0,
        "watch_plan_rank_sequence": 0.0,
        "watch_plan_content_exact": 0.0,
        "missing_episodes_content_exact": 0.0,
        "summary_json_exact": 0.0,
    }

    expected = _compute_expected(workspace)
    # If we cannot compute expected (e.g., malformed inputs), fail all checks gracefully.
    if expected is None:
        return scores

    # Check watch_plan.csv
    plan_path = workspace / "output" / "watch_plan.csv"
    header, rows_dicts = _read_output_plan(plan_path)
    if header is not None and rows_dicts is not None:
        # Header and order
        if header == expected["plan_header"]:
            scores["watch_plan_header_and_order"] = 1.0

        # Row count
        if len(rows_dicts) == len(expected["plan_rows"]):
            scores["watch_plan_row_count"] = 1.0

        # Rank sequence check: must be 1..N in order of the file
        rank_ok = True
        for idx, r in enumerate(rows_dicts, start=1):
            val = r.get("watch_priority_rank", "")
            try:
                if int(val) != idx:
                    rank_ok = False
                    break
            except Exception:
                rank_ok = False
                break
        if rows_dicts:
            scores["watch_plan_rank_sequence"] = 1.0 if rank_ok else 0.0

        # Content exact comparison (including order)
        # Build normalized student rows in the expected header order
        student_rows = []
        for r in rows_dicts:
            # Normalize file_path separators to forward slash for comparison
            row_list = []
            for col in expected["plan_header"]:
                v = r.get(col, "")
                if col == "file_path":
                    v = _normalize_path_str(v)
                row_list.append(v)
            student_rows.append(row_list)

        # Normalize expected file_path as well (already POSIX, but normalize anyway)
        expected_rows = []
        for row in expected["plan_rows"]:
            normalized_row = row[:]
            fp_idx = expected["plan_header"].index("file_path")
            normalized_row[fp_idx] = _normalize_path_str(normalized_row[fp_idx])
            expected_rows.append(normalized_row)

        if student_rows == expected_rows:
            scores["watch_plan_content_exact"] = 1.0

    # Check missing_episodes.csv
    missing_path = workspace / "output" / "missing_episodes.csv"
    m_header, m_rows = _read_output_csv(missing_path)
    if m_header is not None and m_rows is not None:
        # Compare header and rows exactly
        if m_header == expected["missing_header"]:
            if m_rows == expected["missing_rows"]:
                scores["missing_episodes_content_exact"] = 1.0

    # Check summary.json
    summary_path = workspace / "output" / "summary.json"
    summary = _safe_read_json(summary_path)
    if isinstance(summary, dict):
        # Normalize file_path separator inside next_up for comparison
        expected_summary = json.loads(json.dumps(expected["summary"]))
        if isinstance(summary.get("next_up", None), dict):
            if "file_path" in summary["next_up"]:
                summary["next_up"]["file_path"] = _normalize_path_str(summary["next_up"]["file_path"])
        if isinstance(expected_summary.get("next_up", None), dict):
            expected_summary["next_up"]["file_path"] = _normalize_path_str(expected_summary["next_up"]["file_path"])
        # Compare exact match
        if summary == expected_summary:
            scores["summary_json_exact"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()