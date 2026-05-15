import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_csv_dicts(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            return reader.fieldnames, rows
    except Exception:
        return None, None


def _try_float(val: str) -> Optional[float]:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        return float(s)
    except Exception:
        return None


def _try_int(val: str) -> Optional[int]:
    try:
        if val is None:
            return None
        s = str(val).strip()
        if s == "":
            return None
        return int(float(s))
    except Exception:
        return None


def _approx_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _numeric_string_candidates(value: float) -> List[str]:
    candidates = set()
    try:
        if float(value).is_integer():
            candidates.add(str(int(round(value))))
            candidates.add(f"{int(round(value))}.0")
        candidates.add(str(value))
        candidates.add(f"{value:.1f}")
        candidates.add(f"{value:.2f}")
        candidates.add(f"{value:.3f}")
        candidates.add(f"{value:.4f}")
        candidates.add(f"{value:.6f}")
    except Exception:
        pass
    return list(candidates)


def _parse_meeting_context(text: str) -> Dict[str, List[str]]:
    result = {"title_line": "", "attendees": [], "agenda": []}
    if not text:
        return result
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    for ln in lines:
        if ln.strip().lower().startswith("title:"):
            result["title_line"] = ln.strip()
            break
    in_attendees = False
    in_agenda = False
    for ln in lines:
        stripped = ln.strip()
        if stripped.lower().startswith("attendees:"):
            in_attendees = True
            in_agenda = False
            continue
        if stripped.lower().startswith("agenda:"):
            in_attendees = False
            in_agenda = True
            continue
        if stripped.lower().startswith("notes:"):
            in_attendees = False
            in_agenda = False
            continue
        if in_attendees:
            if stripped.startswith("- "):
                result["attendees"].append(stripped[2:].strip())
            elif stripped == "":
                continue
        if in_agenda:
            if stripped and (stripped[0].isdigit() and stripped[1:2] in [".", ")"] or stripped[0:2] in ["1.", "2.", "3.", "4.", "5."]):
                result["agenda"].append(stripped)
            elif stripped and stripped[0].isdigit() and "." in stripped[:3]:
                result["agenda"].append(stripped)
            elif stripped and stripped[0].isdigit():
                result["agenda"].append(stripped)
    return result


def _compute_expected_prioritized(perf_baseline: List[Dict[str, str]],
                                  perf_current: List[Dict[str, str]],
                                  code_metrics: List[Dict[str, str]],
                                  owners: List[Dict[str, str]]) -> List[Dict[str, object]]:
    baseline_map: Dict[Tuple[str, str], Dict[str, float]] = {}
    for row in perf_baseline:
        key = (row.get("function", ""), row.get("file", ""))
        baseline_map[key] = {
            "time_ms": _try_float(row.get("time_ms", "0")) or 0.0,
        }
    metrics_map: Dict[Tuple[str, str], Dict[str, Optional[int]]] = {}
    for row in code_metrics:
        key = (row.get("function", ""), row.get("file", ""))
        metrics_map[key] = {
            "size_bytes": _try_int(row.get("size_bytes", "")),
            "cyclomatic": _try_int(row.get("cyclomatic", "")),
        }
    owner_map: Dict[str, str] = {}
    for row in owners:
        f = row.get("file", "")
        owner = row.get("owner", "")
        if f:
            owner_map[f] = owner

    expected_rows: List[Dict[str, object]] = []
    for row in perf_current:
        func = row.get("function", "")
        filep = row.get("file", "")
        key = (func, filep)
        current_time_ms = _try_float(row.get("time_ms", "0")) or 0.0
        baseline_time_ms = baseline_map.get(key, {}).get("time_ms", 0.0)
        delta_time_ms = current_time_ms - baseline_time_ms
        if baseline_time_ms > 0:
            delta_percent = 100.0 * delta_time_ms / baseline_time_ms
        else:
            delta_percent = 100.0 if current_time_ms > 0 else 0.0
        samples_current = _try_int(row.get("samples", "0")) or 0
        llc_miss_rate_current = _try_float(row.get("llc_miss_rate", "0")) or 0.0
        branch_miss_rate_current = _try_float(row.get("branch_miss_rate", "0")) or 0.0
        cpu_percent = _try_float(row.get("cpu_percent", "0")) or 0.0

        if llc_miss_rate_current >= 20.0:
            bottleneck_class = "Memory-bound"
        elif branch_miss_rate_current >= 5.0:
            bottleneck_class = "Branch-mispredict-bound"
        elif cpu_percent >= 80.0:
            bottleneck_class = "CPU-bound"
        else:
            bottleneck_class = "Other"

        m = metrics_map.get(key, {})
        size_bytes = m.get("size_bytes", None) if m else None
        cyclomatic = m.get("cyclomatic", None) if m else None

        inline_candidate_bool = False
        if size_bytes is not None and cyclomatic is not None:
            if size_bytes <= 64 and cyclomatic <= 5 and current_time_ms >= 20.0:
                inline_candidate_bool = True

        bottleneck_factor_map = {
            "Memory-bound": 1.2,
            "Branch-mispredict-bound": 1.1,
            "CPU-bound": 1.0,
            "Other": 0.8,
        }
        bottleneck_factor = bottleneck_factor_map[bottleneck_class]
        inline_bonus = 1.1 if inline_candidate_bool else 1.0
        reg = max(delta_time_ms, 0.0)
        priority_score = ((reg * 0.6) + (current_time_ms * 0.4)) * bottleneck_factor * inline_bonus

        expected_rows.append({
            "function": func,
            "file": filep,
            "owner": owner_map.get(filep, "Unassigned"),
            "baseline_time_ms": float(baseline_time_ms),
            "current_time_ms": float(current_time_ms),
            "delta_time_ms": float(delta_time_ms),
            "delta_percent": float(delta_percent),
            "samples_current": int(samples_current),
            "llc_miss_rate_current": float(llc_miss_rate_current),
            "branch_miss_rate_current": float(branch_miss_rate_current),
            "size_bytes": size_bytes,
            "cyclomatic": cyclomatic,
            "bottleneck_class": bottleneck_class,
            "inline_candidate": "true" if inline_candidate_bool else "false",
            "priority_score": float(priority_score),
        })

    expected_rows.sort(key=lambda r: (
        -r["priority_score"],
        -r["current_time_ms"],
        r["function"]
    ))
    for idx, r in enumerate(expected_rows, start=1):
        r["rank"] = idx
    return expected_rows


def _load_inputs(workspace: Path) -> Tuple[Optional[List[Dict[str, str]]],
                                           Optional[List[Dict[str, str]]],
                                           Optional[List[Dict[str, str]]],
                                           Optional[List[Dict[str, str]]],
                                           Optional[Dict[str, List[str]]]]:
    base_path = workspace / "input"
    _, baseline_rows = _safe_load_csv_dicts(base_path / "perf_baseline.csv")
    _, current_rows = _safe_load_csv_dicts(base_path / "perf_current.csv")
    _, code_rows = _safe_load_csv_dicts(base_path / "code_metrics.csv")
    _, owners_rows = _safe_load_csv_dicts(base_path / "component_owners.csv")
    meeting_text = _safe_read_text(base_path / "meeting_context.md")
    meeting_ctx = _parse_meeting_context(meeting_text or "") if meeting_text is not None else None
    return baseline_rows, current_rows, code_rows, owners_rows, meeting_ctx


def _parse_out_prioritized(path: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    return _safe_load_csv_dicts(path)


def _check_subject_line(lines: List[str]) -> bool:
    for ln in lines:
        s = ln.strip()
        if s == "":
            continue
        if s == "Perf regression triage: current vs baseline":
            return True
        if s == "Subject: Perf regression triage: current vs baseline":
            return True
        return False
    return False


def _find_nonempty_after(lines: List[str], start_index: int) -> int:
    for i in range(start_index, len(lines)):
        if lines[i].strip() != "":
            return i
    return -1


def _extract_bullets(lines: List[str]) -> List[Tuple[int, str]]:
    bullets = []
    for idx, ln in enumerate(lines):
        s = ln.lstrip()
        if s.startswith("- ") or s.startswith("* "):
            bullets.append((idx, ln.strip()))
    return bullets


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "prioritized_csv_exists_and_structure": 0.0,
        "prioritized_csv_coverage": 0.0,
        "prioritized_csv_value_checks": 0.0,
        "prioritized_csv_sort_and_rank": 0.0,
        "summary_email_subject_and_intro": 0.0,
        "summary_email_top5_bullets": 0.0,
        "summary_email_asks_and_inline_flags": 0.0,
        "meeting_notes_context_sections": 0.0,
        "meeting_notes_summary_top3": 0.0,
        "meeting_notes_action_items": 0.0,
    }

    baseline_rows, current_rows, code_rows, owners_rows, meeting_ctx = _load_inputs(workspace)
    expected_rows: Optional[List[Dict[str, object]]] = None
    if baseline_rows is not None and current_rows is not None and code_rows is not None and owners_rows is not None:
        try:
            expected_rows = _compute_expected_prioritized(baseline_rows, current_rows, code_rows, owners_rows)
        except Exception:
            expected_rows = None

    out_prioritized_path = workspace / "out" / "prioritized_functions.csv"
    header, out_rows = _parse_out_prioritized(out_prioritized_path)

    expected_header = [
        "function",
        "file",
        "owner",
        "baseline_time_ms",
        "current_time_ms",
        "delta_time_ms",
        "delta_percent",
        "samples_current",
        "llc_miss_rate_current",
        "branch_miss_rate_current",
        "size_bytes",
        "cyclomatic",
        "bottleneck_class",
        "inline_candidate",
        "priority_score",
        "rank",
    ]

    if header is not None and out_rows is not None and header == expected_header:
        scores["prioritized_csv_exists_and_structure"] = 1.0

    coverage_ok = False
    if expected_rows is not None and out_rows is not None:
        try:
            expected_keys = {(r["function"], r["file"]) for r in expected_rows}
            out_keys = set()
            duplicates = False
            for r in out_rows:
                key = (r.get("function", ""), r.get("file", ""))
                if key in out_keys:
                    duplicates = True
                out_keys.add(key)
            coverage_ok = (len(out_rows) == len(expected_rows)) and (expected_keys == out_keys) and not duplicates
        except Exception:
            coverage_ok = False
    scores["prioritized_csv_coverage"] = 1.0 if coverage_ok else 0.0

    values_ok = False
    if expected_rows is not None and out_rows is not None and header == expected_header:
        try:
            expected_map: Dict[Tuple[str, str], Dict[str, object]] = {}
            for r in expected_rows:
                expected_map[(r["function"], r["file"])] = r
            all_ok = True
            for r in out_rows:
                key = (r.get("function", ""), r.get("file", ""))
                if key not in expected_map:
                    all_ok = False
                    break
                exp = expected_map[key]
                if r.get("owner", "") != exp["owner"]:
                    all_ok = False
                    break
                v = _try_float(r.get("baseline_time_ms", ""))
                if v is None or not _approx_equal(v, float(exp["baseline_time_ms"])):
                    all_ok = False
                    break
                v = _try_float(r.get("current_time_ms", ""))
                if v is None or not _approx_equal(v, float(exp["current_time_ms"])):
                    all_ok = False
                    break
                v = _try_float(r.get("delta_time_ms", ""))
                if v is None or not _approx_equal(v, float(exp["delta_time_ms"])):
                    all_ok = False
                    break
                v = _try_float(r.get("delta_percent", ""))
                if v is None or not _approx_equal(v, float(exp["delta_percent"])):
                    all_ok = False
                    break
                vi = _try_int(r.get("samples_current", ""))
                if vi is None or vi != int(exp["samples_current"]):
                    all_ok = False
                    break
                v = _try_float(r.get("llc_miss_rate_current", ""))
                if v is None or not _approx_equal(v, float(exp["llc_miss_rate_current"])):
                    all_ok = False
                    break
                v = _try_float(r.get("branch_miss_rate_current", ""))
                if v is None or not _approx_equal(v, float(exp["branch_miss_rate_current"])):
                    all_ok = False
                    break
                sb = r.get("size_bytes", "")
                cy = r.get("cyclomatic", "")
                exp_sb = exp["size_bytes"]
                exp_cy = exp["cyclomatic"]
                if exp_sb is None:
                    if sb.strip() != "":
                        all_ok = False
                        break
                else:
                    if _try_int(sb) != int(exp_sb):
                        all_ok = False
                        break
                if exp_cy is None:
                    if cy.strip() != "":
                        all_ok = False
                        break
                else:
                    if _try_int(cy) != int(exp_cy):
                        all_ok = False
                        break
                if r.get("bottleneck_class", "") != exp["bottleneck_class"]:
                    all_ok = False
                    break
                if r.get("inline_candidate", "") != exp["inline_candidate"]:
                    all_ok = False
                    break
                v = _try_float(r.get("priority_score", ""))
                if v is None or not _approx_equal(v, float(exp["priority_score"])):
                    all_ok = False
                    break
            values_ok = all_ok
        except Exception:
            values_ok = False
    scores["prioritized_csv_value_checks"] = 1.0 if values_ok else 0.0

    sort_ok = False
    if expected_rows is not None and out_rows is not None and header == expected_header and values_ok:
        try:
            expected_order = [(r["function"], r["file"]) for r in expected_rows]
            out_order = [(r.get("function", ""), r.get("file", "")) for r in out_rows]
            order_match = expected_order == out_order
            ranks = [_try_int(r.get("rank", "")) for r in out_rows]
            rank_ok = all(rk is not None for rk in ranks) and [rk for rk in ranks] == list(range(1, len(out_rows) + 1))
            sort_ok = order_match and rank_ok
        except Exception:
            sort_ok = False
    scores["prioritized_csv_sort_and_rank"] = 1.0 if sort_ok else 0.0

    email_path = workspace / "out" / "summary_email.txt"
    email_text = _safe_read_text(email_path) or ""
    email_lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
    email_ok_subject_intro = False
    email_ok_bullets = False
    email_ok_asks_inline = False

    if email_text and expected_rows is not None and len(expected_rows) >= 5:
        subj_ok = _check_subject_line(email_lines)
        subj_idx = -1
        for i, ln in enumerate(email_lines):
            if ln.strip() == "":
                continue
            if ln.strip() in ["Perf regression triage: current vs baseline", "Subject: Perf regression triage: current vs baseline"]:
                subj_idx = i
            break
        intro_ok = False
        if subj_idx != -1:
            next_idx = _find_nonempty_after(email_lines, subj_idx + 1)
            if next_idx != -1:
                ln = email_lines[next_idx].strip()
                if not (ln.startswith("- ") or ln.startswith("* ")):
                    words = [w for w in ln.split() if w.strip()]
                    if len(words) >= 3 or ln.endswith("."):
                        intro_ok = True
        email_ok_subject_intro = subj_ok and intro_ok

        bullets = _extract_bullets(email_lines)
        top5 = expected_rows[:5]
        bullets_ok = False
        if len(bullets) >= 5:
            bullets_ok = True
            for i in range(5):
                _, bline = bullets[i]
                exp = top5[i]
                if (str(exp["function"]) not in bline) or (str(exp["file"]) not in bline) or (str(exp["owner"]) not in bline) or (str(exp["bottleneck_class"]) not in bline):
                    bullets_ok = False
                    break
                rank_str = str(exp["rank"])
                if rank_str not in bline:
                    bullets_ok = False
                    break
                delta_strs = _numeric_string_candidates(float(exp["delta_time_ms"]))
                curr_strs = _numeric_string_candidates(float(exp["current_time_ms"]))
                if not any(s in bline for s in delta_strs):
                    bullets_ok = False
                    break
                if not any(s in bline for s in curr_strs):
                    bullets_ok = False
                    break
                ps_strs = _numeric_string_candidates(float(exp["priority_score"]))
                if not any(s in bline for s in ps_strs):
                    bullets_ok = False
                    break
        email_ok_bullets = bullets_ok

        asks_ok = False
        inline_ok = False
        closing_ok = False
        if bullets_ok:
            ask_phrases = {
                "Memory-bound": "Please investigate cache locality and data layout",
                "Branch-mispredict-bound": "Please examine branch patterns and reduce mispredictions",
                "CPU-bound": "Please consider algorithmic improvements or vectorization",
                "Other": "Please investigate CPU usage and potential algorithmic options",
            }
            class_counts: Dict[str, int] = {}
            for i in range(5):
                cls = str(top5[i]["bottleneck_class"])
                class_counts[cls] = class_counts.get(cls, 0) + 1
            text_lower = email_text
            asks_ok = True
            for cls, cnt in class_counts.items():
                phrase = ask_phrases[cls]
                occurrences = text_lower.count(phrase)
                if occurrences < cnt:
                    asks_ok = False
                    break
            inline_ok = True
            for i in range(5):
                _, bline = bullets[i]
                inline_true = (top5[i]["inline_candidate"] == "true")
                if inline_true:
                    if "[inline-candidate]" not in bline:
                        inline_ok = False
                        break
            closing_ok = False
            for ln in reversed(email_lines):
                if ln.strip() == "":
                    continue
                low = ln.lower()
                if ("follow up" in low and "triage" in low) or ("follow-up" in low and "triage" in low):
                    closing_ok = True
                break
        email_ok_asks_inline = asks_ok and inline_ok and closing_ok

    scores["summary_email_subject_and_intro"] = 1.0 if email_ok_subject_intro else 0.0
    scores["summary_email_top5_bullets"] = 1.0 if email_ok_bullets else 0.0
    scores["summary_email_asks_and_inline_flags"] = 1.0 if email_ok_asks_inline else 0.0

    notes_path = workspace / "out" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path) or ""
    notes_lines = [ln.rstrip("\n") for ln in notes_text.splitlines()]

    context_ok = False
    if meeting_ctx is not None and notes_text:
        try:
            title_line = meeting_ctx.get("title_line", "")
            attendees = meeting_ctx.get("attendees", [])
            agenda = meeting_ctx.get("agenda", [])
            if title_line and (title_line in notes_text):
                attendees_ok = all(any(att in ln for ln in notes_lines) for att in attendees) if attendees else True
                agenda_ok = all(any(item in ln for ln in notes_lines) for item in agenda) if agenda else True
                context_ok = attendees_ok and agenda_ok
        except Exception:
            context_ok = False
    scores["meeting_notes_context_sections"] = 1.0 if context_ok else 0.0

    summary_ok = False
    if expected_rows is not None and notes_text:
        try:
            top3 = expected_rows[:3]
            found_all = True
            for item in top3:
                func = str(item["function"])
                owner = str(item["owner"])
                cls = str(item["bottleneck_class"])
                ps = float(item["priority_score"])
                match_found = False
                for ln in notes_lines:
                    if func in ln and owner in ln and cls in ln:
                        ps_strs = _numeric_string_candidates(ps)
                        if any(s in ln for s in ps_strs):
                            match_found = True
                            break
                if not match_found:
                    found_all = False
                    break
            summary_ok = found_all
        except Exception:
            summary_ok = False
    scores["meeting_notes_summary_top3"] = 1.0 if summary_ok else 0.0

    action_ok = False
    if expected_rows is not None and notes_text:
        try:
            top3 = expected_rows[:3]
            checkbox_lines = [ln for ln in notes_lines if ln.strip().startswith("- [ ]")]
            if len(checkbox_lines) >= 3:
                ask_phrases = {
                    "Memory-bound": "Please investigate cache locality and data layout",
                    "Branch-mispredict-bound": "Please examine branch patterns and reduce mispredictions",
                    "CPU-bound": "Please consider algorithmic improvements or vectorization",
                    "Other": "Please investigate CPU usage and potential algorithmic options",
                }
                all_three_ok = True
                for item in top3:
                    func = str(item["function"])
                    owner = str(item["owner"])
                    cls = str(item["bottleneck_class"])
                    phrase = ask_phrases[cls]
                    found_line = False
                    for ln in checkbox_lines:
                        s = ln.strip()
                        if func in s and owner in s and phrase in s and "Due: Next sprint" in s:
                            found_line = True
                            break
                    if not found_line:
                        all_three_ok = False
                        break
                action_ok = all_three_ok
            else:
                action_ok = False
        except Exception:
            action_ok = False
    scores["meeting_notes_action_items"] = 1.0 if action_ok else 0.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()