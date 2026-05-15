import sys
import json
import re
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin1")
        except Exception:
            return None


def load_json_safe(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None, "unreadable"
        return json.loads(text), None
    except Exception as e:
        return None, f"json_error:{e}"


def parse_csv_safe(path: Path) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader]
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                return None, "invalid_headers"
            return rows, None
    except Exception as e:
        return None, f"csv_error:{e}"


def parse_outline_yaml(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = read_text_safe(path)
    if text is None:
        return None, "unreadable"
    lines = text.splitlines()
    program_name = None
    constraints = {}
    sessions: List[Dict[str, Any]] = []

    for line in lines:
        m = re.match(r'^\s*program_name:\s*"(.*)"\s*$', line)
        if m:
            program_name = m.group(1).strip()
            break

    for line in lines:
        m1 = re.match(r'^\s*min_drills_per_session:\s*(\d+)\s*$', line)
        if m1:
            constraints["min_drills_per_session"] = int(m1.group(1))
        m2 = re.match(r'^\s*max_drills_per_session:\s*(\d+)\s*$', line)
        if m2:
            constraints["max_drills_per_session"] = int(m2.group(1))

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        mid = re.match(r'^\s*-\s+id:\s*(\S+)\s*$', line)
        if mid:
            sid = mid.group(1).strip()
            block_lines = [line]
            j = i + 1
            while j < n and not re.match(r'^\s*-\s+id:\s*\S+', lines[j]):
                block_lines.append(lines[j])
                j += 1
            theme = None
            duration_limit = None
            required_tags: List[str] = []
            for b in block_lines:
                mtheme = re.match(r'^\s*theme:\s*(.*\S)\s*$', b)
                if mtheme:
                    theme = mtheme.group(1).strip()
                mdur = re.match(r'^\s*duration_limit_min:\s*(\d+)\s*$', b)
                if mdur:
                    duration_limit = int(mdur.group(1))
                mreq = re.match(r'^\s*required_focus_tags:\s*\[(.*)\]\s*$', b)
                if mreq:
                    inside = mreq.group(1).strip()
                    if inside:
                        parts = [p.strip() for p in inside.split(",")]
                        required_tags = [p for p in parts if p]
            if sid and theme is not None and duration_limit is not None:
                sessions.append({
                    "id": sid,
                    "theme": theme,
                    "duration_limit_min": duration_limit,
                    "required_focus_tags": required_tags,
                })
            i = j
        else:
            i += 1

    if program_name is None or not sessions:
        return None, "parse_error"
    return {"program_name": program_name, "constraints": constraints, "sessions": sessions}, None


def parse_rubric_yaml(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    text = read_text_safe(path)
    if text is None:
        return None, "unreadable"
    lines = text.splitlines()

    weights: Dict[str, float] = {}
    for line in lines:
        m = re.match(r'^\s*pass_rush_relevance:\s*([0-9]*\.?[0-9]+)\s*$', line)
        if m and "pass_rush_relevance" not in weights:
            weights["pass_rush_relevance"] = float(m.group(1))
        m = re.match(r'^\s*equipment_simplicity:\s*([0-9]*\.?[0-9]+)\s*$', line)
        if m and "equipment_simplicity" not in weights:
            weights["equipment_simplicity"] = float(m.group(1))
        m = re.match(r'^\s*time_fit:\s*([0-9]*\.?[0-9]+)\s*$', line)
        if m and "time_fit" not in weights:
            weights["time_fit"] = float(m.group(1))
        m = re.match(r'^\s*safety:\s*([0-9]*\.?[0-9]+)\s*$', line)
        if m and "safety" not in weights:
            weights["safety"] = float(m.group(1))

    focus_tags: List[str] = []
    focus_header_idx = None
    for idx, line in enumerate(lines):
        if re.match(r'^\s*focus_tags_master_list:\s*$', line):
            focus_header_idx = idx
            break
    if focus_header_idx is not None:
        for j in range(focus_header_idx + 1, len(lines)):
            l = lines[j]
            m = re.match(r'^\s*-\s*(\S+)\s*$', l)
            if m:
                tag = m.group(1)
                focus_tags.append(tag)
            elif l.strip() == "":
                continue
            else:
                break

    if not weights or not focus_tags:
        return None, "parse_error"
    return {"weights": weights, "focus_tags_master_list": focus_tags}, None


def is_slug_filename(name: str) -> bool:
    return re.fullmatch(r'[a-z0-9\-]+\.(pdf|html)', name) is not None


def parse_iso8601_utc(ts: str) -> bool:
    try:
        if ts.endswith("Z"):
            ts2 = ts[:-1] + "+00:00"
            datetime.fromisoformat(ts2)
            return True
        datetime.fromisoformat(ts)
        return True
    except Exception:
        return False


def semicolon_tags_to_set(s: str) -> List[str]:
    if s is None:
        return []
    parts = [p.strip() for p in s.split(";")]
    return [p for p in parts if p]


def within_range(value: Any, lo: float, hi: float) -> bool:
    try:
        v = float(value)
        return lo <= v <= hi
    except Exception:
        return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "resources_raw_files": 0.0,
        "resources_nick_hampton_present": 0.0,
        "resources_slug_filenames": 0.0,
        "logs_download_log_presence": 0.0,
        "logs_rebuild_log_presence": 0.0,
        "logs_rebuild_analysis_quality": 0.0,
        "metadata_sources_json_valid": 0.0,
        "metadata_sources_paths_exist": 0.0,
        "metadata_nick_hampton_entry": 0.0,
        "drills_csv_count_and_structure": 0.0,
        "drills_csv_tags_valid": 0.0,
        "drills_sources_exclude_nick_hampton": 0.0,
        "scored_csv_structure_and_sort": 0.0,
        "scored_csv_filtered_by_required_tags": 0.0,
        "scored_scores_numeric_and_range": 0.0,
        "curriculum_json_alignment": 0.0,
        "curriculum_sessions_selection_and_duration": 0.0,
        "curriculum_nick_hampton_citation_and_blurbs": 0.0,
        "report_curriculum_md_content": 0.0,
        "rebuild_script_references_targets": 0.0,
    }

    outline_path = workspace / "config" / "outline.yaml"
    rubric_path = workspace / "rubric" / "selection_criteria.yaml"
    outline, outline_err = parse_outline_yaml(outline_path) if outline_path.exists() else (None, "missing")
    rubric, rubric_err = parse_rubric_yaml(rubric_path) if rubric_path.exists() else (None, "missing")

    sessions_by_id: Dict[str, Dict[str, Any]] = {}
    union_required_tags: List[str] = []
    focus_tags_master_list: List[str] = []
    program_name_expected = None
    min_drills_per_session = None
    max_drills_per_session = None

    if outline is not None:
        program_name_expected = outline.get("program_name")
        for s in outline.get("sessions", []):
            sessions_by_id[s["id"]] = s
            for t in s.get("required_focus_tags", []):
                if t not in union_required_tags:
                    union_required_tags.append(t)
        constraints = outline.get("constraints", {})
        min_drills_per_session = constraints.get("min_drills_per_session")
        max_drills_per_session = constraints.get("max_drills_per_session")
    if rubric is not None:
        focus_tags_master_list = rubric.get("focus_tags_master_list", [])

    resources_dir = workspace / "resources" / "raw"
    resource_files: List[Path] = []
    if resources_dir.exists():
        for p in resources_dir.iterdir():
            if p.is_file() and p.suffix.lower() in [".pdf", ".html"]:
                resource_files.append(p)

    num_resources = len(resource_files)
    nick_files = [p for p in resource_files if "nick-hampton" in p.name.lower()]
    non_nick_files = [p for p in resource_files if p not in nick_files]

    if num_resources >= 3 and len(non_nick_files) >= 2 and len(nick_files) >= 1:
        scores["resources_raw_files"] = 1.0

    if len(nick_files) >= 1:
        scores["resources_nick_hampton_present"] = 1.0

    if resource_files and all(is_slug_filename(p.name) for p in resource_files):
        scores["resources_slug_filenames"] = 1.0

    download_log = workspace / "logs" / "download.log"
    rebuild_log = workspace / "logs" / "rebuild.log"
    rebuild_analysis = workspace / "logs" / "rebuild_analysis.txt"

    if download_log.exists():
        dl_text = read_text_safe(download_log) or ""
        if dl_text.strip() and (("http" in dl_text.lower()) or ("curl" in dl_text.lower()) or ("wget" in dl_text.lower())):
            scores["logs_download_log_presence"] = 1.0

    if rebuild_log.exists():
        rl_text = read_text_safe(rebuild_log) or ""
        if rl_text.strip():
            scores["logs_rebuild_log_presence"] = 1.0

    if rebuild_analysis.exists():
        ra_text = read_text_safe(rebuild_analysis) or ""
        mentions_logs = ("download.log" in ra_text) and ("rebuild.log" in ra_text)
        has_counts = bool(re.search(r'\b\d+\b', ra_text))
        mentions_success_or_errors = any(k in ra_text.lower() for k in ["success", "successful", "non-200", "error", "warning", "exit code"])
        if ra_text.strip() and mentions_logs and has_counts and mentions_success_or_errors:
            scores["logs_rebuild_analysis_quality"] = 1.0

    metadata_path = workspace / "metadata" / "sources.json"
    metadata, meta_err = load_json_safe(metadata_path) if metadata_path.exists() else (None, "missing")
    metadata_valid = False
    nick_in_metadata = False
    paths_exist_ok = False
    if isinstance(metadata, list) and len(metadata) >= 3:
        required_fields = {"source_type", "organization", "title", "publication_year", "url", "local_path", "retrieval_timestamp_utc"}
        all_ok = True
        all_paths_exist = True
        for item in metadata:
            if not isinstance(item, dict) or not required_fields.issubset(item.keys()):
                all_ok = False
                break
            if item.get("source_type") not in ("pdf", "html"):
                all_ok = False
                break
            if not isinstance(item.get("organization"), str) or not item.get("organization").strip():
                all_ok = False
                break
            if not isinstance(item.get("title"), str) or not item.get("title").strip():
                all_ok = False
                break
            pub_year = item.get("publication_year")
            if not (pub_year is None or isinstance(pub_year, int)):
                all_ok = False
                break
            if not isinstance(item.get("url"), str) or not item.get("url").strip():
                all_ok = False
                break
            lp = item.get("local_path")
            if not isinstance(lp, str) or not lp.strip():
                all_ok = False
                break
            if not parse_iso8601_utc(str(item.get("retrieval_timestamp_utc"))):
                all_ok = False
                break
            local_abs = (workspace / lp) if not lp.startswith("/") else Path(lp)
            if not local_abs.exists():
                all_paths_exist = False
            if "nick-hampton" in lp.lower():
                nick_in_metadata = True

        metadata_valid = all_ok
        paths_exist_ok = all_paths_exist

    if metadata_valid:
        scores["metadata_sources_json_valid"] = 1.0
    if paths_exist_ok:
        scores["metadata_sources_paths_exist"] = 1.0
    if nick_in_metadata:
        scores["metadata_nick_hampton_entry"] = 1.0

    drills_csv_path = workspace / "data" / "drills.csv"
    drills_rows, drills_err = parse_csv_safe(drills_csv_path) if drills_csv_path.exists() else (None, "missing")
    drills_cols_ok = False
    drills_count_ok = False
    drills_tags_ok = False
    drills_source_not_nick = False
    drills_by_id: Dict[str, Dict[str, str]] = {}
    if drills_rows is not None:
        required_cols = ["drill_id", "drill_name", "focus_tags", "duration_min_estimate", "equipment", "source_local_path"]
        drills_cols_ok = all(c in (drills_rows[0].keys() if drills_rows else required_cols) for c in required_cols)
        unique_ids = set()
        all_rows_ok = True
        tags_ok = True
        sources_ok = True
        for r in drills_rows:
            did = (r.get("drill_id") or "").strip()
            dname = (r.get("drill_name") or "").strip()
            ftags = (r.get("focus_tags") or "").strip()
            dur = r.get("duration_min_estimate")
            equip = (r.get("equipment") or "").strip()
            srcp = (r.get("source_local_path") or "").strip()
            if not did or not dname or not ftags or not equip or not srcp:
                all_rows_ok = False
                break
            try:
                dur_int = int(str(dur).strip())
                if dur_int <= 0:
                    all_rows_ok = False
                    break
            except Exception:
                all_rows_ok = False
                break
            tags_list = semicolon_tags_to_set(ftags)
            if not tags_list:
                tags_ok = False
                break
            for t in tags_list:
                if rubric is not None and focus_tags_master_list and t not in focus_tags_master_list:
                    tags_ok = False
                    break
            if not tags_ok:
                break
            src_abs = (workspace / srcp) if not srcp.startswith("/") else Path(srcp)
            if not src_abs.exists():
                sources_ok = False
                break
            if "nick-hampton" in Path(srcp).name.lower():
                sources_ok = False
                break
            unique_ids.add(did)
            drills_by_id[did] = r
        drills_count_ok = len(unique_ids) >= 15 and all_rows_ok
        drills_tags_ok = tags_ok
        drills_source_not_nick = sources_ok

    if drills_cols_ok and drills_count_ok:
        scores["drills_csv_count_and_structure"] = 1.0
    if drills_tags_ok:
        scores["drills_csv_tags_valid"] = 1.0
    if drills_source_not_nick:
        scores["drills_sources_exclude_nick_hampton"] = 1.0

    scored_csv_path = workspace / "data" / "drills_scored.csv"
    scored_rows, scored_err = parse_csv_safe(scored_csv_path) if scored_csv_path.exists() else (None, "missing")
    scored_structure_ok = False
    scored_filtered_ok = False
    scored_scores_ok = False
    if scored_rows is not None and drills_rows is not None and outline is not None:
        required_cols_scored = ["drill_id", "drill_name", "matched_focus_tags", "pass_rush_relevance", "equipment_simplicity", "time_fit", "safety", "score", "source_local_path"]
        scored_structure_ok = all(c in (scored_rows[0].keys() if scored_rows else required_cols_scored) for c in required_cols_scored)
        scores_list = []
        ids_seen = set()
        filtered_ok = True
        numeric_ok = True
        sorting_ok = True
        for r in scored_rows:
            try:
                sc = float(str(r.get("score")))
            except Exception:
                numeric_ok = False
                break
            scores_list.append(sc)
            if not (within_range(r.get("pass_rush_relevance"), 0, 5) and within_range(r.get("equipment_simplicity"), 0, 5) and within_range(r.get("time_fit"), 0, 5) and within_range(r.get("safety"), 0, 5) and 0.0 <= sc <= 5.0):
                numeric_ok = False
                break
            did = (r.get("drill_id") or "").strip()
            ids_seen.add(did)
            if did not in drills_by_id:
                filtered_ok = False
                break
            matched = set(semicolon_tags_to_set((r.get("matched_focus_tags") or "").strip()))
            source_tags = set(semicolon_tags_to_set((drills_by_id[did].get("focus_tags") or "").strip()))
            union_req = set(union_required_tags)
            actual_intersection = source_tags.intersection(union_req)
            if not matched:
                filtered_ok = False
                break
            if matched != actual_intersection:
                filtered_ok = False
                break
            srcp = (r.get("source_local_path") or "").strip()
            if not srcp:
                filtered_ok = False
                break
            src_abs = (workspace / srcp) if not srcp.startswith("/") else Path(srcp)
            if not src_abs.exists():
                filtered_ok = False
                break

        for i in range(1, len(scores_list)):
            if scores_list[i] > scores_list[i - 1] + 1e-9:
                sorting_ok = False
                break
        scored_structure_ok = scored_structure_ok and sorting_ok
        scored_filtered_ok = filtered_ok
        scored_scores_ok = numeric_ok

    if scored_structure_ok:
        scores["scored_csv_structure_and_sort"] = 1.0
    if scored_filtered_ok:
        scores["scored_csv_filtered_by_required_tags"] = 1.0
    if scored_scores_ok:
        scores["scored_scores_numeric_and_range"] = 1.0

    curriculum_json_path = workspace / "data" / "curriculum.json"
    curriculum, curr_err = load_json_safe(curriculum_json_path) if curriculum_json_path.exists() else (None, "missing")
    curriculum_alignment_ok = False
    curriculum_selection_ok = False
    curriculum_nick_ok = False
    if isinstance(curriculum, dict) and outline is not None and drills_rows is not None and scored_rows is not None:
        program_name = curriculum.get("program_name")
        sessions_curr = curriculum.get("sessions")
        if isinstance(program_name, str) and isinstance(sessions_curr, list):
            ids_outline = [s["id"] for s in outline["sessions"]]
            ids_curr = [s.get("id") for s in sessions_curr if isinstance(s, dict)]
            themes_curr = [s.get("theme") for s in sessions_curr if isinstance(s, dict)]
            themes_outline = [s["theme"] for s in outline["sessions"]]
            alignment_ids = ids_curr == ids_outline
            alignment_themes = themes_curr == themes_outline
            alignment_program = (program_name == program_name_expected)
            curriculum_alignment_ok = alignment_program and alignment_ids and alignment_themes

            drills_by_id_map = {r["drill_id"]: r for r in drills_rows}
            scored_ids_set = set([r["drill_id"] for r in scored_rows])
            selection_ok = True
            nick_local_paths = [it.get("local_path") for it in (metadata or []) if isinstance(it, dict) and "nick-hampton" in str(it.get("local_path", "")).lower()]
            nick_path_expected = nick_local_paths[0] if nick_local_paths else None

            for sess in sessions_curr:
                sid = sess.get("id")
                soutline = sessions_by_id.get(sid, {})
                limit = soutline.get("duration_limit_min")
                req_tags = set(soutline.get("required_focus_tags", []))
                selected_ids = sess.get("selected_drills")
                used_sources = sess.get("used_sources")
                total_duration_min = sess.get("total_duration_min")
                nick_blurb = sess.get("nick_hampton_focus")
                if not isinstance(selected_ids, list) or not (isinstance(used_sources, list)):
                    selection_ok = False
                    break
                if not (min_drills_per_session and max_drills_per_session):
                    min_req = 2
                    max_req = 3
                else:
                    min_req = min_drills_per_session
                    max_req = max_drills_per_session
                if not (len(selected_ids) >= min_req and len(selected_ids) <= max_req):
                    selection_ok = False
                    break
                if any(did not in scored_ids_set for did in selected_ids):
                    selection_ok = False
                    break
                try:
                    sum_dur = 0
                    for did in selected_ids:
                        drow = drills_by_id_map.get(did)
                        if drow is None:
                            selection_ok = False
                            break
                        sum_dur += int(str(drow.get("duration_min_estimate")).strip())
                    if not selection_ok:
                        break
                except Exception:
                    selection_ok = False
                    break
                if isinstance(limit, int) and sum_dur > limit:
                    selection_ok = False
                    break
                if not isinstance(total_duration_min, int) or total_duration_min != sum_dur:
                    selection_ok = False
                    break
                has_overlap = False
                for did in selected_ids:
                    ftags = set(semicolon_tags_to_set((drills_by_id_map[did].get("focus_tags") or "")))
                    if ftags.intersection(req_tags):
                        has_overlap = True
                        break
                if not has_overlap:
                    selection_ok = False
                    break
                drill_sources = set()
                for did in selected_ids:
                    srcp = (drills_by_id_map[did].get("source_local_path") or "").strip()
                    if srcp:
                        drill_sources.add(srcp)
                used_sources_set = set([str(u) for u in used_sources])
                if not drill_sources.issubset(used_sources_set):
                    selection_ok = False
                    break
                if nick_path_expected:
                    if nick_path_expected not in used_sources_set:
                        selection_ok = False
                        break
                if not isinstance(nick_blurb, str) or not nick_blurb.strip():
                    selection_ok = False
                    break
                sentences = [s for s in [seg.strip() for seg in nick_blurb.strip().split(".")] if s]
                if not (1 <= len(sentences) <= 2):
                    selection_ok = False
                    break
                if not (("nick" in nick_blurb.lower()) and ("hampton" in nick_blurb.lower())):
                    selection_ok = False
                    break

            curriculum_selection_ok = selection_ok
            if selection_ok:
                curriculum_nick_ok = True

    if curriculum_alignment_ok:
        scores["curriculum_json_alignment"] = 1.0
    if curriculum_selection_ok:
        scores["curriculum_sessions_selection_and_duration"] = 1.0
    if curriculum_nick_ok:
        scores["curriculum_nick_hampton_citation_and_blurbs"] = 1.0

    report_md_path = workspace / "reports" / "curriculum.md"
    if report_md_path.exists() and curriculum and isinstance(curriculum, dict):
        md = read_text_safe(report_md_path) or ""
        ok = True
        for sess in curriculum.get("sessions", []):
            sid = sess.get("id")
            theme = sess.get("theme")
            if sid not in md and (theme not in md if theme else True):
                ok = False
                break
        if ok and drills_rows is not None:
            id_to_name = {r["drill_id"]: r.get("drill_name", "") for r in drills_rows}
            for sess in curriculum.get("sessions", []):
                names_needed = [id_to_name.get(did, "") for did in (sess.get("selected_drills") or [])]
                for nm in names_needed:
                    if nm and nm not in md:
                        ok = False
                        break
                if not ok:
                    break
        if ok and not (("nick" in md.lower()) and ("hampton" in md.lower())):
            ok = False
        if ok:
            scores["report_curriculum_md_content"] = 1.0

    rebuild_script = workspace / "scripts" / "rebuild.sh"
    if rebuild_script.exists():
        txt = read_text_safe(rebuild_script) or ""
        mentions = all([
            "metadata/sources.json" in txt,
            "resources/raw" in txt,
            "data/drills.csv" in txt,
            "data/drills_scored.csv" in txt,
            "data/curriculum.json" in txt,
            "reports/curriculum.md" in txt,
        ])
        uses_downloader = ("curl" in txt) or ("wget" in txt)
        if mentions and uses_downloader:
            scores["rebuild_script_references_targets"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade(transcript=[], workspace_path=workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()