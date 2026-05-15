import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def _read_csv(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        if not path.exists() or not path.is_file():
            return None, None
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            if header is None:
                return None, None
            rows = [dict(row) for row in reader]
            return header, rows
    except Exception:
        return None, None


def _load_text(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(s: str) -> Optional[int]:
    try:
        return int(s)
    except Exception:
        try:
            return int(float(s))
        except Exception:
            return None


def _parse_marked_section(text: str, start_marker: str, end_marker: str) -> Optional[Tuple[int, int, List[str]]]:
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_marker in line:
            start_idx = i
        if end_marker in line:
            end_idx = i
            break
    if start_idx is None or end_idx is None or end_idx <= start_idx:
        return None
    between = lines[start_idx + 1: end_idx]
    return start_idx, end_idx, between


def _find_bullet_lines(lines: List[str]) -> List[str]:
    bl = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            bl.append(stripped)
    return bl


def _expected_base_episodes() -> List[Dict[str, str]]:
    return [
        {"id": "1", "title": "Southpaw Spirit", "season": "1", "episode": "3", "theme": "boxing; perseverance", "rating": "8.2", "minutes": "48"},
        {"id": "2", "title": "The Final Bell", "season": "1", "episode": "8", "theme": "boxing; mentorship", "rating": "8.7", "minutes": "52"},
        {"id": "3", "title": "Team Above All", "season": "2", "episode": "1", "theme": "basketball; teamwork", "rating": "7.9", "minutes": "50"},
        {"id": "4", "title": "Ringside Romance", "season": "2", "episode": "4", "theme": "boxing; romance", "rating": "6.5", "minutes": "46"},
        {"id": "5", "title": "Coach's Promise", "season": "2", "episode": "6", "theme": "coach; leadership", "rating": "8.0", "minutes": "49"},
    ]


def _expected_inbox_episodes() -> List[Dict[str, str]]:
    return [
        {"id": "6", "title": "Against The Ropes", "season": "3", "episode": "2", "theme": "boxing; comeback", "rating": "8.9", "minutes": "51"},
        {"id": "7", "title": "Corner Talk", "season": "3", "episode": "3", "theme": "coach; strategy", "rating": "7.4", "minutes": "47"},
        {"id": "8", "title": "Playbook Secrets", "season": "1", "episode": "2", "theme": "football; tactics", "rating": "7.6", "minutes": "45"},
        {"id": "9", "title": "Glass Jaw", "season": "1", "episode": "5", "theme": "boxing; injury", "rating": "7.1", "minutes": "49"},
    ]


def _compute_top_episodes(merged_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    filtered = []
    for r in merged_rows:
        theme = (r.get("theme") or "").lower()
        rating = _safe_float(r.get("rating", ""))
        if rating is None:
            continue
        if rating >= 7.0 and (("boxing" in theme) or ("coach" in theme)):
            filtered.append(r)
    filtered.sort(key=lambda d: (-(_safe_float(d.get("rating", "0")) or 0.0), (d.get("title") or "")))
    return filtered[:5]


def _compute_top_bouts(bouts_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    def qualifies(r: Dict[str, str]) -> bool:
        tv = (r.get("tv") or "").strip()
        loc = (r.get("location") or "").lower()
        if tv == "Yes":
            return True
        if "community gym" in loc:
            return True
        return False

    qualified = [r for r in bouts_rows if qualifies(r)]

    def parse_date(s: str) -> datetime:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:
            return datetime.min

    qualified.sort(
        key=lambda d: (-(int(d.get("hype_score") or 0)), parse_date(d.get("date") or "")),
    )
    return qualified[:3]


def _detect_entrypoints(workspace: Path) -> List[Path]:
    candidates = [
        "run.sh",
        "process.sh",
        "process_updates.sh",
        "process_inbox.sh",
        "automation.sh",
        "run.py",
        "process.py",
        "process_inbox.py",
        "automation.py",
        "main.py",
        "cli.py",
        "update_watch_plan.py",
        "Makefile",
    ]
    found = []
    for name in candidates:
        p = workspace / name
        if p.exists() and p.is_file():
            found.append(p)
    scripts_dir = workspace / "scripts"
    if scripts_dir.exists() and scripts_dir.is_dir():
        for name in candidates:
            p = scripts_dir / name
            if p.exists() and p.is_file():
                found.append(p)
    return found


def _entrypoint_mentions_inbox_processed(ep: Path) -> bool:
    try:
        text = ep.read_text(encoding="utf-8")
    except Exception:
        return False
    lower = text.lower()
    return ("inbox" in lower) and ("processed" in lower)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "entrypoint_present": 0.0,
        "entrypoint_mentions_inbox_and_processed": 0.0,
        "merged_csv_exists": 0.0,
        "merge_rowcount_correct": 0.0,
        "merge_contains_inbox_rows_correct_values": 0.0,
        "merge_preserves_base_rows_correct_values": 0.0,
        "merge_unique_ids": 0.0,
        "top_episodes_file_exists": 0.0,
        "top_episodes_header_correct": 0.0,
        "top_episodes_rowcount_top5": 0.0,
        "top_episodes_ordering_correct": 0.0,
        "top_episodes_sources_correct": 0.0,
        "top_bouts_file_exists": 0.0,
        "top_bouts_header_correct": 0.0,
        "top_bouts_rowcount_top3": 0.0,
        "top_bouts_ordering_correct": 0.0,
        "watchplan_episodes_section_updated": 0.0,
        "watchplan_episodes_content_correct": 0.0,
        "watchplan_bouts_section_updated": 0.0,
        "watchplan_bouts_content_correct": 0.0,
        "processed_file_moved": 0.0,
        "inbox_file_removed": 0.0,
        "process_log_appended_with_summary": 0.0,
    }

    # Detect entrypoint(s)
    entrypoints = _detect_entrypoints(workspace)
    if entrypoints:
        scores["entrypoint_present"] = 1.0
        if any(_entrypoint_mentions_inbox_processed(ep) for ep in entrypoints):
            scores["entrypoint_mentions_inbox_and_processed"] = 1.0

    # Paths
    merged_path = workspace / "data" / "dramas.csv"
    bouts_path = workspace / "data" / "bouts.csv"
    top_eps_path = workspace / "output" / "top_drama_episodes.csv"
    top_bouts_path = workspace / "output" / "top_bouts.csv"
    watch_plan_path = workspace / "notes" / "WatchPlan.md"
    inbox_update_path = workspace / "inbox" / "dramas_update.csv"
    processed_update_path = workspace / "processed" / "dramas_update.csv"
    process_log_path = workspace / "output" / "logs" / "process.log"

    # Read merged episodes
    merged_header, merged_rows = _read_csv(merged_path)
    # Gate merging checks on presence of expected new IDs (6-9), to avoid awarding on scaffold
    expected_inbox_ids = {6, 7, 8, 9}
    has_all_new_ids = False
    if merged_header is not None and merged_rows is not None:
        merged_ids = set()
        for r in merged_rows:
            rid = _safe_int(r.get("id", ""))
            if rid is not None:
                merged_ids.add(rid)
        if expected_inbox_ids.issubset(merged_ids):
            has_all_new_ids = True

    # merged_csv_exists: only if merged exists and includes all expected new IDs
    if merged_header is not None and merged_rows is not None and has_all_new_ids:
        scores["merged_csv_exists"] = 1.0

        # Merge rowcount
        if len(merged_rows) == 9:
            scores["merge_rowcount_correct"] = 1.0

        # Map merged by id for exact value checks
        merged_by_id = {}
        for r in merged_rows:
            rid = _safe_int(r.get("id", ""))
            if rid is not None:
                merged_by_id[rid] = r

        # Inbox rows exact values
        inbox_values_ok = True
        for er in _expected_inbox_episodes():
            rid = _safe_int(er["id"])
            mr = merged_by_id.get(rid)
            if mr is None:
                inbox_values_ok = False
                break
            for key in ["title", "season", "episode", "theme", "rating", "minutes"]:
                if str(mr.get(key, "")).strip() != str(er.get(key, "")).strip():
                    inbox_values_ok = False
                    break
            if not inbox_values_ok:
                break
        if inbox_values_ok:
            scores["merge_contains_inbox_rows_correct_values"] = 1.0

        # Base rows preserved exact values
        base_ok = True
        for er in _expected_base_episodes():
            rid = _safe_int(er["id"])
            mr = merged_by_id.get(rid)
            if mr is None:
                base_ok = False
                break
            for key in ["title", "season", "episode", "theme", "rating", "minutes"]:
                if str(mr.get(key, "")).strip() != str(er.get(key, "")).strip():
                    base_ok = False
                    break
            if not base_ok:
                break
        if base_ok:
            scores["merge_preserves_base_rows_correct_values"] = 1.0

        # Unique IDs
        ids = []
        for r in merged_rows:
            rid = _safe_int(r.get("id", ""))
            if rid is None:
                ids.append(None)
            else:
                ids.append(rid)
        if None not in ids and len(ids) == len(set(ids)):
            scores["merge_unique_ids"] = 1.0

    # Top episodes CSV checks
    te_header, te_rows = _read_csv(top_eps_path)
    if te_header is not None and te_rows is not None:
        scores["top_episodes_file_exists"] = 1.0
        expected_te_header = ["rank", "id", "title", "season", "episode", "theme", "rating", "source"]
        if te_header == expected_te_header:
            scores["top_episodes_header_correct"] = 1.0

        if len(te_rows) == 5:
            scores["top_episodes_rowcount_top5"] = 1.0

        if merged_rows is not None and has_all_new_ids:
            expected_top5 = _compute_top_episodes(merged_rows)
            # Verify ordering and key fields including rank
            ordering_ok = True
            if len(te_rows) != len(expected_top5):
                ordering_ok = False
            else:
                for i, (r, exp) in enumerate(zip(te_rows, expected_top5), start=1):
                    if _safe_int(r.get("rank", "")) != i:
                        ordering_ok = False
                        break
                    # Compare selected fields
                    for k in ["id", "title", "season", "episode", "theme"]:
                        rv = str(r.get(k, "")).strip()
                        ev = str(exp.get(k, "")).strip()
                        if rv != ev:
                            ordering_ok = False
                            break
                    # rating compare as string equivalence or numeric match
                    ar = r.get("rating", "")
                    er = exp.get("rating", "")
                    try:
                        if abs(float(ar) - float(er)) > 1e-6:
                            ordering_ok = False
                            break
                    except Exception:
                        if str(ar).strip() != str(er).strip():
                            ordering_ok = False
                            break
                # end loop
            if ordering_ok:
                scores["top_episodes_ordering_correct"] = 1.0

            # Source correctness based on known inbox IDs
            inbox_ids = set(_safe_int(x["id"]) for x in _expected_inbox_episodes())
            source_ok = True
            for r in te_rows:
                rid = _safe_int(r.get("id", ""))
                src = (r.get("source") or "").strip()
                if rid in inbox_ids:
                    if src != "inbox/dramas_update.csv":
                        source_ok = False
                        break
                else:
                    if src != "data/dramas.csv":
                        source_ok = False
                        break
            if source_ok:
                scores["top_episodes_sources_correct"] = 1.0

    # Top bouts CSV checks
    tb_header, tb_rows = _read_csv(top_bouts_path)
    if tb_header is not None and tb_rows is not None:
        scores["top_bouts_file_exists"] = 1.0
        expected_tb_header = ["rank", "date", "fighters", "location", "tv", "hype_score", "underdog_flag"]
        if tb_header == expected_tb_header:
            scores["top_bouts_header_correct"] = 1.0

        if len(tb_rows) == 3:
            scores["top_bouts_rowcount_top3"] = 1.0

        bouts_header, bouts_rows = _read_csv(bouts_path)
        if bouts_rows is not None:
            expected_top3 = _compute_top_bouts(bouts_rows)
            ordering_ok = True
            if len(tb_rows) != len(expected_top3):
                ordering_ok = False
            else:
                for i, (r, exp) in enumerate(zip(tb_rows, expected_top3), start=1):
                    if _safe_int(r.get("rank", "")) != i:
                        ordering_ok = False
                        break
                    for k in ["date", "fighters", "location", "tv", "hype_score", "underdog_flag"]:
                        if str(r.get(k, "")).strip() != str(exp.get(k, "")).strip():
                            ordering_ok = False
                            break
                    if not ordering_ok:
                        break
            if ordering_ok:
                scores["top_bouts_ordering_correct"] = 1.0

    # Watch plan checks
    wp_text = _load_text(watch_plan_path)
    if wp_text is not None and merged_rows is not None and has_all_new_ids:
        # Episodes section
        ep_sec = _parse_marked_section(wp_text, "<!-- AUTO-EPISODES:START -->", "<!-- AUTO-EPISODES:END -->")
        if ep_sec is not None:
            _, _, ep_between = ep_sec
            ep_bullets = _find_bullet_lines(ep_between)
            if ep_bullets and "(none yet)" not in "\n".join(ep_between):
                scores["watchplan_episodes_section_updated"] = 1.0

            expected_top5 = _compute_top_episodes(merged_rows)
            content_ok = True
            if len(ep_bullets) != len(expected_top5) or len(expected_top5) != 5:
                content_ok = False
            else:
                for i, (line, exp) in enumerate(zip(ep_bullets, expected_top5), start=1):
                    title = exp.get("title", "")
                    season = exp.get("season", "")
                    episode = exp.get("episode", "")
                    theme = exp.get("theme", "")
                    rating_val = _safe_float(exp.get("rating", ""))
                    if f"Rank {i}" not in line:
                        content_ok = False
                        break
                    if title not in line:
                        content_ok = False
                        break
                    if f"S{season}E{episode}" not in line:
                        content_ok = False
                        break
                    if "Rating" not in line:
                        content_ok = False
                        break
                    if rating_val is not None:
                        if f"{rating_val:.1f}" not in line and f"{int(rating_val)}" not in line:
                            content_ok = False
                            break
                    if "Theme" in line:
                        # If they included a label, ensure theme appears regardless
                        if theme not in line:
                            content_ok = False
                            break
                    else:
                        if theme not in line:
                            content_ok = False
                            break
            if content_ok:
                scores["watchplan_episodes_content_correct"] = 1.0

        # Bouts section
        bt_sec = _parse_marked_section(wp_text, "<!-- AUTO-BOUTS:START -->", "<!-- AUTO-BOUTS:END -->")
        if bt_sec is not None:
            _, _, bt_between = bt_sec
            bt_bullets = _find_bullet_lines(bt_between)
            if bt_bullets and "(none yet)" not in "\n".join(bt_between):
                scores["watchplan_bouts_section_updated"] = 1.0

            bouts_header, bouts_rows = _read_csv(bouts_path)
            if bouts_rows is not None:
                expected_top3 = _compute_top_bouts(bouts_rows)
                content_ok = True
                if len(bt_bullets) != len(expected_top3) or len(expected_top3) != 3:
                    content_ok = False
                else:
                    for i, (line, exp) in enumerate(zip(bt_bullets, expected_top3), start=1):
                        date = exp.get("date", "")
                        fighters = exp.get("fighters", "")
                        location = exp.get("location", "")
                        tv = exp.get("tv", "")
                        hype = str(exp.get("hype_score", ""))
                        if f"Rank {i}" not in line:
                            content_ok = False
                            break
                        if date not in line:
                            content_ok = False
                            break
                        if fighters not in line:
                            content_ok = False
                            break
                        if location not in line:
                            content_ok = False
                            break
                        if "TV" not in line or tv not in line:
                            content_ok = False
                            break
                        if "Hype" not in line and "Hype Score" not in line:
                            content_ok = False
                            break
                        if hype not in line:
                            content_ok = False
                            break
                if content_ok:
                    scores["watchplan_bouts_content_correct"] = 1.0

    # Processed file moved and inbox removed: require processed file to exist to award either
    if processed_update_path.exists():
        scores["processed_file_moved"] = 1.0
        if not inbox_update_path.exists():
            scores["inbox_file_removed"] = 1.0

    # Process log check, only if processed file exists (indicates a run)
    if processed_update_path.exists():
        log_text = _load_text(process_log_path)
        if log_text is not None:
            lines = [ln for ln in log_text.splitlines() if ln.strip()]
            if lines:
                last = lines[-1]
                has_filename = "dramas_update.csv" in last
                has_counts = ("4" in last) and ("5" in last) and ("3" in last)
                has_ts = bool(re.search(r"\b20\d{2}-\d{2}-\d{2}", last)) or bool(re.search(r"\b20\d{2}/\d{2}/\d{2}", last)) or bool(re.search(r"\b20\d{2}", last))
                if has_filename and has_counts and has_ts:
                    scores["process_log_appended_with_summary"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=None, separators=(",", ":")))


if __name__ == "__main__":
    main()