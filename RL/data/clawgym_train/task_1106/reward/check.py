import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _list_all_files_and_bytes(root: Path) -> Tuple[int, int]:
    count = 0
    total = 0
    if not root.exists():
        return 0, 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                    count += 1
                    total += int(st.st_size)
                except Exception:
                    return 0, 0
    except Exception:
        return 0, 0
    return count, total


def _compute_run_info(run_dir: Path, required_files: List[str]) -> Dict:
    present: List[str] = []
    missing: List[str] = []
    for rel in required_files:
        f = run_dir / rel
        if f.is_file():
            present.append(rel)
        else:
            missing.append(rel)
    file_count, total_bytes = _list_all_files_and_bytes(run_dir)
    return {
        "present_files": sorted(present),
        "missing_files": sorted(missing),
        "file_count": file_count,
        "total_bytes": total_bytes,
        "complete": len(missing) == 0,
    }


def _compute_ground_truth(workspace: Path, expected: dict) -> Optional[dict]:
    try:
        runs_cfg = expected.get("runs", [])
        gt_runs: Dict[str, dict] = {}
        total_files = 0
        total_bytes = 0
        complete_runs = 0
        incomplete_runs = 0
        runs_found = 0
        for run in runs_cfg:
            if not isinstance(run, dict):
                return None
            run_id = run.get("run_id")
            style = run.get("style")
            required = run.get("required_files", [])
            if not isinstance(run_id, str) or not isinstance(style, str) or not isinstance(required, list):
                return None
            run_dir = workspace / "fermentation_runs" / run_id
            info = _compute_run_info(run_dir, required)
            if run_dir.exists() and run_dir.is_dir():
                runs_found += 1
            if info["complete"]:
                complete_runs += 1
            else:
                incomplete_runs += 1
            total_files += info["file_count"]
            total_bytes += info["total_bytes"]
            gt_runs[run_id] = {
                "run_id": run_id,
                "style": style,
                "required_files": list(required),
                **info,
            }
        gt = {
            "runs_by_id": gt_runs,
            "overview": {
                "number_of_runs_found": runs_found,
                "complete_runs": complete_runs,
                "incomplete_runs": incomplete_runs,
                "total_files": total_files,
                "total_bytes": total_bytes,
            },
        }
        return gt
    except Exception:
        return None


def _extract_overview_numbers_from_summary_md(md_text: str) -> Optional[dict]:
    labels_patterns = {
        "number_of_runs_found": [r'number[_\s-]*of[_\s-]*runs[_\s-]*found'],
        "complete_runs": [r'complete[_\s-]*runs'],
        "incomplete_runs": [r'incomplete[_\s-]*runs'],
        "total_files": [r'total[_\s-]*files'],
        "total_bytes": [r'total[_\s-]*bytes'],
    }
    found: Dict[str, int] = {}
    for key, patterns in labels_patterns.items():
        val = None
        for pat in patterns:
            m = re.search(pat + r'[^\d]*(\d+)', md_text, flags=re.IGNORECASE)
            if m:
                try:
                    val = int(m.group(1))
                    break
                except Exception:
                    continue
        if val is None:
            for pat in patterns:
                m = re.search(pat + r'\s*:\s*(\d+)', md_text, flags=re.IGNORECASE)
                if m:
                    try:
                        val = int(m.group(1))
                        break
                    except Exception:
                        continue
        if val is None:
            return None
        found[key] = val
    return found


def _section_bounds(text: str, header_name: str) -> Optional[Tuple[int, int]]:
    pattern = r'(?m)^##\s+' + re.escape(header_name) + r'\s*$'
    m = re.search(pattern, text)
    if not m:
        return None
    start = m.end()
    m2 = re.search(r'(?m)^##\s+', text[start:])
    if m2:
        end = start + m2.start()
    else:
        end = len(text)
    return (start, end)


def _extract_section(text: str, header_name: str) -> Optional[str]:
    b = _section_bounds(text, header_name)
    if b is None:
        return None
    return text[b[0]:b[1]].strip("\n")


def _normalize_whitespace(s: str) -> str:
    lines = [ln.rstrip() for ln in s.strip("\n").splitlines()]
    return "\n".join(lines).strip()


def _find_int_near_label(snippet: str, label_patterns: List[str]) -> Optional[int]:
    for pat in label_patterns:
        m = re.search(pat + r'[^\d]*(\d+)', snippet, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _extract_numbers_from_data_status_paragraph(text: str) -> dict:
    res: Dict[str, int] = {}
    m = re.search(r'(\d+)\s+complete(?:\s+runs)?', text, flags=re.IGNORECASE)
    if m:
        res["complete_runs"] = int(m.group(1))
    m = re.search(r'(\d+)\s+incomplete(?:\s+runs)?', text, flags=re.IGNORECASE)
    if m:
        res["incomplete_runs"] = int(m.group(1))
    m = re.search(r'(?:total[_\s-]*files|files total)[^\d]*(\d+)', text, flags=re.IGNORECASE)
    if not m:
        m = re.search(r'(\d+)\s+total\s+files', text, flags=re.IGNORECASE)
    if m:
        res["total_files"] = int(m.group(1))
    m = re.search(r'(?:total[_\s-]*bytes|bytes total)[^\d]*(\d+)', text, flags=re.IGNORECASE)
    if not m:
        m = re.search(r'(\d+)\s+total\s+bytes', text, flags=re.IGNORECASE)
    if m:
        res["total_bytes"] = int(m.group(1))
    return res


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "system_status_json_present": 0.0,
        "system_status_json_generated_from_correct": 0.0,
        "system_status_json_runs_correct": 0.0,
        "system_status_json_overview_correct": 0.0,
        "system_status_summary_md_consistent": 0.0,
        "system_status_summary_md_per_run_details": 0.0,
        "weekly_lab_update_data_status_updated": 0.0,
        "weekly_lab_update_numbers_consistent_with_json": 0.0,
        "weekly_lab_update_incomplete_bullets_correct": 0.0,
        "weekly_lab_update_other_sections_unchanged": 0.0,
    }

    cfg_path = workspace / "config" / "expected_runs.json"
    cfg = _safe_load_json(cfg_path)
    if not isinstance(cfg, dict):
        return scores

    gt = _compute_ground_truth(workspace, cfg)
    if gt is None:
        return scores

    runs_cfg = cfg.get("runs", [])
    runs_cfg_by_id = {r.get("run_id"): r for r in runs_cfg if isinstance(r, dict)}
    gt_runs_by_id = gt["runs_by_id"]
    gt_overview = gt["overview"]

    sys_json_path = workspace / "outputs" / "system_status.json"
    sys_json = _safe_load_json(sys_json_path)
    deliverables_present = isinstance(sys_json, dict)

    if deliverables_present:
        scores["system_status_json_present"] = 1.0
        if sys_json.get("generated_from") == "config/expected_runs.json":
            scores["system_status_json_generated_from_correct"] = 1.0

        runs_ok = True
        runs_list = sys_json.get("runs")
        if not isinstance(runs_list, list):
            runs_ok = False
        else:
            if len(runs_list) != len(runs_cfg_by_id):
                runs_ok = False
            else:
                json_runs_by_id: Dict[str, dict] = {}
                for item in runs_list:
                    if not isinstance(item, dict):
                        runs_ok = False
                        break
                    rid = item.get("run_id")
                    if not isinstance(rid, str) or rid in json_runs_by_id:
                        runs_ok = False
                        break
                    json_runs_by_id[rid] = item
                if runs_ok:
                    for rid, cfg_run in runs_cfg_by_id.items():
                        if rid not in json_runs_by_id or rid not in gt_runs_by_id:
                            runs_ok = False
                            break
                        item = json_runs_by_id[rid]
                        gt_run = gt_runs_by_id[rid]
                        if item.get("style") != cfg_run.get("style"):
                            runs_ok = False
                            break
                        j_present = item.get("present_files")
                        j_missing = item.get("missing_files")
                        if not isinstance(j_present, list) or not isinstance(j_missing, list):
                            runs_ok = False
                            break
                        if set(j_present) != set(gt_run["present_files"]) or set(j_missing) != set(gt_run["missing_files"]):
                            runs_ok = False
                            break
                        if item.get("complete") != gt_run["complete"]:
                            runs_ok = False
                            break
                        if item.get("file_count") != gt_run["file_count"]:
                            runs_ok = False
                            break
                        if item.get("total_bytes") != gt_run["total_bytes"]:
                            runs_ok = False
                            break
        if runs_ok:
            scores["system_status_json_runs_correct"] = 1.0

        overview_ok = True
        j_overview = sys_json.get("overview")
        if not isinstance(j_overview, dict):
            overview_ok = False
        else:
            fields = ["number_of_runs_found", "complete_runs", "incomplete_runs", "total_files", "total_bytes"]
            for f in fields:
                if j_overview.get(f) != gt_overview.get(f):
                    overview_ok = False
                    break
        if overview_ok:
            scores["system_status_json_overview_correct"] = 1.0

    summary_path = workspace / "outputs" / "system_status_summary.md"
    summary_text = _safe_read_text(summary_path)
    if summary_text is not None and deliverables_present:
        md_overview = _extract_overview_numbers_from_summary_md(summary_text)
        j_overview = sys_json.get("overview") if isinstance(sys_json, dict) else None
        if md_overview and isinstance(j_overview, dict):
            consistent = True
            for k, v in md_overview.items():
                if j_overview.get(k) != v:
                    consistent = False
                    break
            if consistent:
                scores["system_status_summary_md_consistent"] = 1.0

        runs_details_ok = True
        j_runs_list = sys_json.get("runs")
        if not isinstance(j_runs_list, list):
            runs_details_ok = False
        else:
            for r in j_runs_list:
                if not isinstance(r, dict):
                    runs_details_ok = False
                    break
                rid = r.get("run_id")
                style = r.get("style")
                if not isinstance(rid, str) or not isinstance(style, str):
                    runs_details_ok = False
                    break
                pos = summary_text.find(rid)
                if pos == -1:
                    runs_details_ok = False
                    break
                snippet = summary_text[pos:pos + 600]
                if style.lower() not in snippet.lower():
                    runs_details_ok = False
                    break
                if not (re.search(r'\bcomplete\b', snippet, flags=re.IGNORECASE) or re.search(r'\bincomplete\b', snippet, flags=re.IGNORECASE)):
                    runs_details_ok = False
                    break
                missing_count_expected = len(r.get("missing_files", [])) if isinstance(r.get("missing_files"), list) else None
                if missing_count_expected is None:
                    runs_details_ok = False
                    break
                miss_val = _find_int_near_label(snippet, [r'missing[_\s-]*files(?:[_\s-]*count)?'])
                if miss_val is None or miss_val != missing_count_expected:
                    runs_details_ok = False
                    break
                fc_val = _find_int_near_label(snippet, [r'file[_\s-]*count'])
                if fc_val is None or fc_val != r.get("file_count"):
                    runs_details_ok = False
                    break
                tb_val = _find_int_near_label(snippet, [r'total[_\s-]*bytes', r'bytes'])
                if tb_val is None or tb_val != r.get("total_bytes"):
                    runs_details_ok = False
                    break
        if runs_details_ok:
            scores["system_status_summary_md_per_run_details"] = 1.0

    weekly_path = workspace / "docs" / "weekly_lab_update.md"
    weekly_text = _safe_read_text(weekly_path)
    if weekly_text is not None:
        data_status_section = _extract_section(weekly_text, "Data status")
        if data_status_section:
            if "TODO" not in data_status_section:
                scores["weekly_lab_update_data_status_updated"] = 1.0

            if deliverables_present:
                nums = _extract_numbers_from_data_status_paragraph(data_status_section)
                j_overview2 = sys_json.get("overview") if isinstance(sys_json, dict) else None
                if isinstance(j_overview2, dict):
                    ok = True
                    required_keys = ["complete_runs", "incomplete_runs", "total_files", "total_bytes"]
                    for k in required_keys:
                        if k not in nums or nums[k] != j_overview2.get(k):
                            ok = False
                            break
                    if ok:
                        scores["weekly_lab_update_numbers_consistent_with_json"] = 1.0

                j_runs2 = sys_json.get("runs") if isinstance(sys_json, dict) else None
                if isinstance(j_runs2, list):
                    bullet_lines = [ln.strip() for ln in data_status_section.splitlines() if ln.strip().startswith(("-", "*"))]
                    bullets_ok = True
                    for r in j_runs2:
                        if not isinstance(r, dict):
                            bullets_ok = False
                            break
                        if r.get("complete") is True:
                            continue
                        rid = r.get("run_id")
                        missing = r.get("missing_files", [])
                        if not isinstance(missing, list):
                            bullets_ok = False
                            break
                        matching = [bl for bl in bullet_lines if rid in bl]
                        if not matching:
                            bullets_ok = False
                            break
                        agg = " ".join(matching)
                        for mf in missing:
                            if mf not in agg:
                                bullets_ok = False
                                break
                        if not bullets_ok:
                            break
                    if bullets_ok:
                        scores["weekly_lab_update_incomplete_bullets_correct"] = 1.0

        # Only assess "other_sections_unchanged" once the system status has been generated to avoid pre-reward on scaffold
        if deliverables_present and scores["weekly_lab_update_data_status_updated"] > 0.0:
            original_md = (
                "# Weekly Lab Update: Fermentation Bench\n\n"
                "Date: 2026-04-18\n\n"
                "## Highlights\n\n"
                "- Began comparative analysis of ester formation across IPA, sour, and pilsner fermentations.\n"
                "- Set up GC-MS calibration for volatile compounds.\n\n"
                "## Data status\n\n"
                "TODO: Replace this section with the current system status summary of fermentation_runs based on config/expected_runs.json.\n\n"
                "## Next steps\n\n"
                "- Re-run any incomplete batches to collect missing logs or measurements.\n"
                "- Finalize figures for the ester profile comparison.\n"
            )
            exp_highlights = _extract_section(original_md, "Highlights") or ""
            exp_next = _extract_section(original_md, "Next steps") or ""
            cur_highlights = _extract_section(weekly_text, "Highlights") or ""
            cur_next = _extract_section(weekly_text, "Next steps") or ""
            if _normalize_whitespace(exp_highlights) == _normalize_whitespace(cur_highlights) and _normalize_whitespace(exp_next) == _normalize_whitespace(cur_next):
                scores["weekly_lab_update_other_sections_unchanged"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()