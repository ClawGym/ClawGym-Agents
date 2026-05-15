import json
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


def mmss(total_seconds: int) -> str:
    m = total_seconds // 60
    s = total_seconds % 60
    return f"{m:02d}:{s:02d}"


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_read_lines(path: Path) -> Optional[List[str]]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None


def safe_json_load(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_schedule(path: Path) -> Optional[Dict[str, Dict[str, Any]]]:
    if not path.exists():
        return None
    try:
        out: Dict[str, Dict[str, Any]] = {}
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ep = row.get("episode_id")
                if not ep:
                    continue
                expected_transcript = row.get("expected_transcript") or ""
                expected_rundown = row.get("expected_rundown") or ""
                out[ep] = {
                    "episode_id": ep,
                    "guest_name": row.get("guest_name") or "",
                    "guest_is_grammy_winner": (row.get("guest_is_grammy_winner") or "").strip().lower(),
                    "air_date": row.get("air_date") or "",
                    "expected_transcript": expected_transcript,
                    "expected_rundown": expected_rundown,
                    "expected_email_draft": f"docs/email_drafts/{ep}_publicist_draft.txt",
                }
        return out
    except Exception:
        return None


def parse_transcript(path: Path) -> Optional[Tuple[List[Dict[str, Any]], int]]:
    lines = safe_read_lines(path)
    if lines is None:
        return None
    seg_re = re.compile(r"^Segment\s+(\d+)\s*\[(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\]")
    segments: List[Dict[str, Any]] = []
    for line in lines:
        m = seg_re.match(line.strip())
        if m:
            idx = int(m.group(1))
            s_m, s_s, e_m, e_s = map(int, m.groups()[1:])
            start_seconds = s_m * 60 + s_s
            end_seconds = e_m * 60 + e_s
            if end_seconds < start_seconds:
                continue
            segments.append({
                "index": idx,
                "start": f"{s_m:02d}:{s_s:02d}",
                "end": f"{e_m:02d}:{e_s:02d}",
                "duration_sec": end_seconds - start_seconds
            })
    if not segments:
        return None
    segments.sort(key=lambda x: x["index"])
    last_end = segments[-1]["end"]
    lm, ls = map(int, last_end.split(":"))
    total_end_seconds = lm * 60 + ls
    return segments, total_end_seconds


def compute_expected_from_transcripts(workspace: Path, schedule: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for ep_id, info in schedule.items():
        transcript_path = workspace / info["expected_transcript"]
        parsed = parse_transcript(transcript_path)
        if parsed:
            segments, total_end_seconds = parsed
            results[ep_id] = {
                "episode_id": ep_id,
                "segment_count": len(segments),
                "segments": segments,
                "total_runtime": mmss(total_end_seconds),
            }
    return results


def load_segment_report(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    data = safe_json_load(path)
    if not isinstance(data, dict):
        return None
    episodes = data.get("episodes")
    if not isinstance(episodes, list):
        return None
    # Basic validation of structure
    for ep in episodes:
        if not isinstance(ep, dict):
            return None
        if not all(k in ep for k in ("episode_id", "segment_count", "segments", "total_runtime")):
            return None
        if not isinstance(ep["segments"], list):
            return None
        for seg in ep["segments"]:
            if not isinstance(seg, dict):
                return None
            if not all(k in seg for k in ("index", "start", "end", "duration_sec")):
                return None
    return data


def parse_rundown(path: Path) -> Tuple[Optional[str], Dict[int, Tuple[str, str]]]:
    lines = safe_read_lines(path)
    if lines is None:
        return None, {}
    intro_line: Optional[str] = None
    segments: Dict[int, Tuple[str, str]] = {}
    intro_re = re.compile(r"^\s*Intro:\s*(.*)")
    seg_re = re.compile(r"^Segment\s+(\d+):.*?Duration:\s*(\d{2}:\d{2})-(\d{2}:\d{2})")
    for line in lines:
        if intro_line is None:
            m_intro = intro_re.match(line)
            if m_intro:
                intro_line = line.strip()
                continue
        m_seg = seg_re.match(line.strip())
        if m_seg:
            idx = int(m_seg.group(1))
            start = m_seg.group(2)
            end = m_seg.group(3)
            segments[idx] = (start, end)
    return intro_line, segments


def check_producer_update(path: Path, schedule: Dict[str, Dict[str, Any]], expected_runtimes: Dict[str, str]) -> float:
    content = safe_read_text(path)
    if content is None:
        return 0.0
    ok = True
    # Must mention each episode id
    for ep_id in schedule.keys():
        if ep_id not in content:
            ok = False
    # For episodes with transcripts, include total runtime somewhere
    for ep_id, runtime in expected_runtimes.items():
        if runtime not in content:
            ok = False
    # Include status tokens
    status_tokens = ["added", "removed", "unchanged", "not_applicable"]
    if not any(tok in content for tok in status_tokens):
        ok = False
    # For an episode with missing assets (EP103 here), mention missing or absent near its mention
    # Find a line around EP103
    for ep_id, info in schedule.items():
        # Determine if any expected asset missing: transcript, rundown, or email draft
        transcript_missing = not (Path(info["expected_transcript"]).exists())
        rundown_missing = not (Path(info["expected_rundown"]).exists())
        email_missing = not (Path(info["expected_email_draft"]).exists())
        if transcript_missing or rundown_missing or email_missing:
            lines = content.splitlines()
            indices = [i for i, line in enumerate(lines) if ep_id in line]
            if indices:
                i0 = indices[0]
                context = "\n".join(lines[i0:i0+3])
                if ("missing" not in context.lower()) and ("absent" not in context.lower()):
                    ok = False
            else:
                ok = False
    return 1.0 if ok else 0.0


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "segment_report_exists": 0.0,
        "segment_report_valid_and_matches": 0.0,
        "rundown_times_ep101_corrected": 0.0,
        "rundown_times_ep102_corrected": 0.0,
        "rundown_intro_tag_ep101_correct": 0.0,
        "rundown_intro_tag_ep102_correct": 0.0,
        "emails_ep101_final_exists_and_header": 0.0,
        "emails_ep102_final_exists_and_header": 0.0,
        "producer_update_covers_all_episodes": 0.0,
        "inspection_results_json_valid": 0.0,
        "inspection_results_per_episode_fields": 0.0,
        "inspection_results_intro_tag_status_expected": 0.0,
        "inspection_results_files_flags_consistent": 0.0,
        "inspection_results_rundown_mismatches_consistent": 0.0,
    }

    schedule_path = workspace / "input/episodes_schedule.csv"
    schedule = load_schedule(schedule_path)
    if schedule is None:
        # Without schedule, we cannot grade most items
        return scores

    # Compute expected transcript-derived report
    expected_report_map = compute_expected_from_transcripts(workspace, schedule)
    expected_episode_ids = sorted(expected_report_map.keys())

    # Check segment_report
    segment_report_path = workspace / "output/segment_report.json"
    if segment_report_path.exists():
        scores["segment_report_exists"] = 1.0
        report = load_segment_report(segment_report_path)
        if report is not None:
            # Validate episodes set matches expected from schedule (only those with transcripts)
            rep_eps = report.get("episodes", [])
            rep_map = {e["episode_id"]: e for e in rep_eps if isinstance(e, dict) and "episode_id" in e}
            rep_ids = sorted(rep_map.keys())
            if rep_ids == expected_episode_ids:
                # Compare each episode content
                all_match = True
                for ep_id in expected_episode_ids:
                    exp = expected_report_map[ep_id]
                    got = rep_map[ep_id]
                    # Compare segment_count and total_runtime
                    if exp["segment_count"] != got.get("segment_count"):
                        all_match = False
                        break
                    if exp["total_runtime"] != got.get("total_runtime"):
                        all_match = False
                        break
                    # Compare segments list length and each segment fields
                    got_segments = got.get("segments", [])
                    if len(exp["segments"]) != len(got_segments):
                        all_match = False
                        break
                    # Sort by index to be safe
                    exp_segments = sorted(exp["segments"], key=lambda x: x["index"])
                    got_segments_sorted = sorted(got_segments, key=lambda x: x.get("index"))
                    for es, gs in zip(exp_segments, got_segments_sorted):
                        if not (es["index"] == gs.get("index") and
                                es["start"] == gs.get("start") and
                                es["end"] == gs.get("end") and
                                es["duration_sec"] == gs.get("duration_sec")):
                            all_match = False
                            break
                    if not all_match:
                        break
                if all_match:
                    scores["segment_report_valid_and_matches"] = 1.0

    # Rundown checks for episodes with transcripts EP101 and EP102 if present in schedule
    for ep_id in ["EP101", "EP102"]:
        if ep_id in schedule and ep_id in expected_report_map:
            rundown_path = workspace / schedule[ep_id]["expected_rundown"]
            intro_ok = False
            times_ok = False
            if rundown_path.exists():
                intro_line, rd_segments = parse_rundown(rundown_path)
                # Time ranges: must exactly match transcript times
                exp_segments = expected_report_map[ep_id]["segments"]
                # Build expected dict index -> (start, end)
                exp_map = {s["index"]: (s["start"], s["end"]) for s in exp_segments}
                # Require same set of indices and exact matches
                if set(exp_map.keys()) == set(rd_segments.keys()):
                    all_times_match = True
                    for idx, (start, end) in exp_map.items():
                        rd_pair = rd_segments.get(idx)
                        if rd_pair != (start, end):
                            all_times_match = False
                            break
                    times_ok = all_times_match
                else:
                    times_ok = False
                # Intro grammy phrase presence per schedule
                if intro_line is not None:
                    has_phrase = ("Grammy-winning" in intro_line)
                    grammy_yes = (schedule[ep_id]["guest_is_grammy_winner"].lower() == "yes")
                    if grammy_yes and has_phrase:
                        intro_ok = True
                    if (not grammy_yes) and (not has_phrase):
                        intro_ok = True
            # Set scores
            if ep_id == "EP101":
                scores["rundown_times_ep101_corrected"] = 1.0 if times_ok else 0.0
                scores["rundown_intro_tag_ep101_correct"] = 1.0 if intro_ok else 0.0
            elif ep_id == "EP102":
                scores["rundown_times_ep102_corrected"] = 1.0 if times_ok else 0.0
                scores["rundown_intro_tag_ep102_correct"] = 1.0 if intro_ok else 0.0

    # Email checks for EP101 and EP102 (episodes with transcripts)
    for ep_id in ["EP101", "EP102"]:
        if ep_id in schedule and ep_id in expected_report_map:
            final_email_path = workspace / f"output/emails/{ep_id}_publicist_final.txt"
            header_ok = False
            if final_email_path.exists():
                content = safe_read_lines(final_email_path)
                if content is not None and len(content) >= 2:
                    expected_air = schedule[ep_id]["air_date"]
                    expected_runtime = expected_report_map[ep_id]["total_runtime"]
                    if content[0].strip() == f"Air date: {expected_air}" and content[1].strip() == f"Total runtime: {expected_runtime}":
                        # ensure there is some body content after headers
                        body = "\n".join(content[2:]).strip()
                        if len(body) > 0:
                            header_ok = True
            key = f"emails_{ep_id.lower()}_final_exists_and_header"
            scores[key] = 1.0 if header_ok else 0.0

    # Producer update check
    producer_update_path = workspace / "output/producer_update.md"
    expected_runtimes = {ep: expected_report_map[ep]["total_runtime"] for ep in expected_report_map.keys()}
    scores["producer_update_covers_all_episodes"] = check_producer_update(producer_update_path, schedule, expected_runtimes)

    # Inspection results JSON checks
    inspection_path = workspace / "output/inspection_results.json"
    insp_data = safe_json_load(inspection_path)
    if isinstance(insp_data, list):
        scores["inspection_results_json_valid"] = 1.0
        # Map by episode_id
        insp_map: Dict[str, Any] = {}
        valid_fields_all = True
        for item in insp_data:
            if not isinstance(item, dict):
                valid_fields_all = False
                break
            required_keys = {"episode_id", "guest_name", "files", "segment_count", "total_runtime", "rundown_time_mismatches", "intro_tag_status", "actions_taken"}
            if not required_keys.issubset(item.keys()):
                valid_fields_all = False
                break
            if not isinstance(item["files"], dict):
                valid_fields_all = False
                break
            fk = item["files"]
            if not all(k in fk for k in ("transcript_exists", "rundown_exists", "email_draft_exists")):
                valid_fields_all = False
                break
            if not isinstance(item["rundown_time_mismatches"], list):
                valid_fields_all = False
                break
            if not isinstance(item["actions_taken"], list):
                valid_fields_all = False
                break
            ep_id = item.get("episode_id")
            if isinstance(ep_id, str):
                insp_map[ep_id] = item
        scores["inspection_results_per_episode_fields"] = 1.0 if valid_fields_all and set(insp_map.keys()) == set(schedule.keys()) else 0.0

        # Intro tag status expected for each episode
        intro_status_ok = True
        files_flags_ok = True
        mismatches_ok = True
        for ep_id, info in schedule.items():
            item = insp_map.get(ep_id)
            if item is None:
                intro_status_ok = False
                files_flags_ok = False
                mismatches_ok = False
                continue
            # Files flags consistent with workspace
            transcript_exists = (workspace / info["expected_transcript"]).exists()
            rundown_exists = (workspace / info["expected_rundown"]).exists()
            email_draft_exists = (workspace / info["expected_email_draft"]).exists()
            fk = item.get("files", {})
            if not (fk.get("transcript_exists") == transcript_exists and fk.get("rundown_exists") == rundown_exists and fk.get("email_draft_exists") == email_draft_exists):
                files_flags_ok = False

            # Intro tag status
            expected_status = "not_applicable"
            if transcript_exists and rundown_exists:
                intro_line, _ = parse_rundown(workspace / info["expected_rundown"])
                has_phrase = False
                if intro_line is not None:
                    has_phrase = ("Grammy-winning" in intro_line)
                grammy_yes = (info["guest_is_grammy_winner"].lower() == "yes")
                # Derive expected status based on the required change outcome
                if grammy_yes:
                    expected_status = "added" if has_phrase else "unchanged"
                else:
                    expected_status = "removed" if not has_phrase else "unchanged"
            if item.get("intro_tag_status") != expected_status:
                intro_status_ok = False

            # Rundown mismatches consistent with current rundown vs transcripts
            rtm = item.get("rundown_time_mismatches")
            if not isinstance(rtm, list):
                mismatches_ok = False
            else:
                # Compute expected mismatches if we have transcripts and rundown
                if ep_id in expected_report_map and rundown_exists:
                    _, rd_segments = parse_rundown(workspace / info["expected_rundown"])
                    exp_segments = expected_report_map[ep_id]["segments"]
                    exp_map = {s["index"]: (s["start"], s["end"]) for s in exp_segments}
                    # Determine mismatched indices
                    expected_mismatches: List[int] = []
                    if set(exp_map.keys()) != set(rd_segments.keys()):
                        # Any difference in indices counts as mismatches; include all differing indices
                        all_idx = set(exp_map.keys()).union(set(rd_segments.keys()))
                        expected_mismatches = sorted(list(all_idx))
                    else:
                        for idx, (s, e) in exp_map.items():
                            if rd_segments.get(idx) != (s, e):
                                expected_mismatches.append(idx)
                    # Check rtm equals expected list (order-insensitive)
                    try:
                        rtm_ints = [int(x) for x in rtm]
                    except Exception:
                        mismatches_ok = False
                        continue
                    if sorted(rtm_ints) != sorted(expected_mismatches):
                        mismatches_ok = False
                else:
                    # If no transcript or rundown, expected empty list
                    if len(rtm) != 0:
                        mismatches_ok = False

        scores["inspection_results_intro_tag_status_expected"] = 1.0 if intro_status_ok else 0.0
        scores["inspection_results_files_flags_consistent"] = 1.0 if files_flags_ok else 0.0
        scores["inspection_results_rundown_mismatches_consistent"] = 1.0 if mismatches_ok else 0.0
    else:
        # No or invalid inspection results JSON
        pass

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()