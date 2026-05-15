import json
import csv
import sys
import re
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _safe_read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [dict(row) for row in reader]
        return rows
    except Exception:
        return None


def _num_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    try:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) <= tol
        return False
    except Exception:
        return False


def _float_close(a: Any, b: Any, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _extract_section(md_text: str, section_title: str) -> Optional[str]:
    # Section titles are expected as '## {section_title}'
    lines = md_text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip() == f"## {section_title}":
            start_idx = i + 1
            break
    if start_idx is None:
        return None
    # Find next heading start
    end_idx = len(lines)
    for j in range(start_idx, len(lines)):
        if lines[j].strip().startswith("## "):
            end_idx = j
            break
    section_content = "\n".join(lines[start_idx:end_idx]).strip()
    return section_content


def _list_chapter_files(workspace: Path) -> List[Path]:
    chapters_dir = workspace / "input" / "chapters"
    if not chapters_dir.exists():
        return []
    return sorted([p for p in chapters_dir.iterdir() if p.is_file() and p.name.endswith(".txt")])


def _word_count(text: str) -> int:
    # Count words by splitting on any whitespace
    return len(text.split())


def _compute_chapter_word_counts(workspace: Path) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for p in _list_chapter_files(workspace):
        txt = _safe_read_text(p)
        if txt is None:
            continue
        result[p.name] = _word_count(txt)
    return result


def _extract_chapter_number_from_filename(filename: str) -> Optional[str]:
    m = re.match(r"chapter_(\d+)\.txt$", filename)
    if not m:
        return None
    return str(int(m.group(1)))  # remove leading zeros


def _compute_scenes_aggregates(workspace: Path) -> Optional[Dict[str, Any]]:
    scenes_path = workspace / "input" / "scenes.csv"
    rows = _safe_read_csv_dicts(scenes_path)
    if rows is None:
        return None
    sums_by_chapter: Dict[str, int] = {}
    counts_by_pov: Dict[str, int] = {}
    dates_set: set = set()
    total_scenes = 0
    for r in rows:
        try:
            ch = str(int(r["chapter"]))
            w = int(r["words"])
            pov = r["pov"]
            d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except Exception:
            return None
        sums_by_chapter[ch] = sums_by_chapter.get(ch, 0) + w
        counts_by_pov[pov] = counts_by_pov.get(pov, 0) + 1
        dates_set.add(d)
        total_scenes += 1

    percents_by_pov: Dict[str, float] = {}
    for pov, cnt in counts_by_pov.items():
        if total_scenes == 0:
            perc = 0.0
        else:
            perc = round((cnt / total_scenes) * 100.0, 1)
        percents_by_pov[pov] = perc

    date_coverage: Dict[str, Any] = {}
    if len(dates_set) == 0:
        date_coverage = {
            "earliest_date": "",
            "latest_date": "",
            "missing_dates": [],
            "longest_gap": {"length_days": 0, "start_date": "", "end_date": ""},
        }
    else:
        earliest: date = min(dates_set)
        latest: date = max(dates_set)
        missing_dates_list: List[date] = []
        d = earliest
        while d <= latest:
            if d not in dates_set:
                missing_dates_list.append(d)
            d = d + timedelta(days=1)
        missing_dates_strs = [d.strftime("%Y-%m-%d") for d in missing_dates_list]

        # Longest consecutive run of missing dates
        longest_len = 0
        longest_start: Optional[date] = None
        longest_end: Optional[date] = None
        if missing_dates_list:
            curr_start = missing_dates_list[0]
            curr_len = 1
            prev = missing_dates_list[0]
            for current in missing_dates_list[1:]:
                if current == prev + timedelta(days=1):
                    curr_len += 1
                else:
                    # end current run
                    if curr_len > longest_len:
                        longest_len = curr_len
                        longest_start = curr_start
                        longest_end = prev
                    # start new run
                    curr_start = current
                    curr_len = 1
                prev = current
            # finalize last run
            if curr_len > longest_len:
                longest_len = curr_len
                longest_start = curr_start
                longest_end = prev
        if longest_len == 0:
            lg = {"length_days": 0, "start_date": "", "end_date": ""}
        else:
            lg = {
                "length_days": int(longest_len),
                "start_date": longest_start.strftime("%Y-%m-%d") if longest_start else "",
                "end_date": longest_end.strftime("%Y-%m-%d") if longest_end else "",
            }

        date_coverage = {
            "earliest_date": earliest.strftime("%Y-%m-%d"),
            "latest_date": latest.strftime("%Y-%m-%d"),
            "missing_dates": missing_dates_strs,
            "longest_gap": lg,
        }

    return {
        "scene_words_by_chapter_csv": sums_by_chapter,
        "counts_by_pov": counts_by_pov,
        "percents_by_pov": percents_by_pov,
        "date_coverage": date_coverage,
        "total_scenes": total_scenes,
    }


def _load_characters(workspace: Path) -> Optional[List[Dict[str, Any]]]:
    path = workspace / "input" / "characters.json"
    data = _safe_load_json(path)
    if not isinstance(data, dict) or "characters" not in data or not isinstance(data["characters"], list):
        return None
    chars = data["characters"]
    # validate fields
    for c in chars:
        if not isinstance(c, dict) or "name" not in c or "is_protagonist" not in c:
            return None
    return chars


def _count_character_mentions(workspace: Path, character_names: List[str]) -> Dict[str, int]:
    # Concatenate all chapter texts
    combined = ""
    for p in _list_chapter_files(workspace):
        txt = _safe_read_text(p) or ""
        combined += txt
        if not combined.endswith("\n"):
            combined += "\n"
    counts: Dict[str, int] = {}
    for name in character_names:
        # exact case-sensitive raw substring (non-overlapping occurrences via str.count)
        counts[name] = combined.count(name)
    return counts


def _compute_metrics_expected(workspace: Path) -> Optional[Dict[str, Any]]:
    # Required inputs
    chapters_counts = _compute_chapter_word_counts(workspace)
    scenes_aggs = _compute_scenes_aggregates(workspace)
    chars = _load_characters(workspace)
    if scenes_aggs is None or chars is None:
        return None

    # Character mentions
    names = [c["name"] for c in chars]
    mentions = _count_character_mentions(workspace, names)

    # Discrepancy by chapter number (as strings)
    # Build mapping from chapter number -> text word count from file(s)
    text_counts_by_chapter_num: Dict[str, int] = {}
    for fname, cnt in chapters_counts.items():
        chnum = _extract_chapter_number_from_filename(fname)
        if chnum is None:
            continue
        text_counts_by_chapter_num[chnum] = text_counts_by_chapter_num.get(chnum, 0) + int(cnt)

    # union of chapters encountered in text and csv
    csv_sums = scenes_aggs["scene_words_by_chapter_csv"]
    all_chapters = set(text_counts_by_chapter_num.keys()) | set(csv_sums.keys())
    discrepancy: Dict[str, Dict[str, Any]] = {}
    for ch in sorted(all_chapters, key=lambda x: int(x)):
        text_count = int(text_counts_by_chapter_num.get(ch, 0))
        csv_sum = int(csv_sums.get(ch, 0))
        abs_diff = abs(text_count - csv_sum)
        pct_diff = abs_diff / max(text_count, 1)
        discrepancy[ch] = {
            "text_count": text_count,
            "csv_sum": csv_sum,
            "abs_diff": abs_diff,
            "pct_diff": float(pct_diff),
        }

    # Top chapters by text wordcount
    items = list(chapters_counts.items())
    items.sort(key=lambda kv: (-int(kv[1]), kv[0]))
    top_chapters = [kv[0] for kv in items[:2]]

    # Underrepresented protagonist
    protagonists = [c["name"] for c in chars if c.get("is_protagonist") is True]
    # only if there is at least one protagonist
    if protagonists:
        # choose with lower mention count; tie-break alphabetical
        sorted_prots = sorted(protagonists, key=lambda n: (mentions.get(n, 0), n))
        underrep = sorted_prots[0]
    else:
        underrep = ""

    expected = {
        "chapter_word_counts_text": {k: int(v) for k, v in chapters_counts.items()},
        "scene_words_by_chapter_csv": {str(k): int(v) for k, v in csv_sums.items()},
        "chapter_word_count_discrepancy": discrepancy,
        "counts_by_pov": {k: int(v) for k, v in scenes_aggs["counts_by_pov"].items()},
        "percents_by_pov": {k: float(v) for k, v in scenes_aggs["percents_by_pov"].items()},
        "character_mentions": {k: int(v) for k, v in mentions.items()},
        "date_coverage": scenes_aggs["date_coverage"],
        "top_chapters_by_wordcount_text": top_chapters,
        "underrepresented_protagonist_by_mentions": underrep,
    }
    return expected


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores: Dict[str, float] = {
        "metrics_file_exists": 0.0,
        "metrics_chapter_word_counts_text": 0.0,
        "metrics_scene_words_by_chapter_csv": 0.0,
        "metrics_chapter_word_count_discrepancy": 0.0,
        "metrics_pov_counts": 0.0,
        "metrics_pov_percents": 0.0,
        "metrics_character_mentions": 0.0,
        "metrics_date_coverage": 0.0,
        "metrics_top_chapters_by_wordcount_text": 0.0,
        "metrics_underrepresented_protagonist_by_mentions": 0.0,
        "report_exists": 0.0,
        "report_sections_present": 0.0,
        "report_inputs_listed": 0.0,
        "report_pov_distribution_correct": 0.0,
        "report_character_mentions_correct": 0.0,
        "report_timeline_coverage_correct": 0.0,
        "report_notes_count_valid": 0.0,
        "final_module_exists": 0.0,
        "final_module_preserves_title": 0.0,
        "final_module_reading_assignment_updated": 0.0,
        "final_module_character_focus_updated": 0.0,
        "final_module_timeline_exercise_updated": 0.0,
        "final_module_expected_outcomes_updated": 0.0,
    }

    expected = _compute_metrics_expected(workspace)

    # Load produced metrics.json
    metrics_path = workspace / "output" / "metrics" / "metrics.json"
    metrics = _safe_load_json(metrics_path)
    if metrics is not None and isinstance(metrics, dict):
        scores["metrics_file_exists"] = 1.0

    # If expected or actual missing, fail all metric comparisons gracefully
    if expected is not None and isinstance(metrics, dict):
        # chapter_word_counts_text
        key = "chapter_word_counts_text"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            # Compare exact mapping (keys and integer values)
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for k, v in exp_map.items():
                    if not _num_equal(v, act_map.get(k)):
                        ok = False
                        break
            scores["metrics_chapter_word_counts_text"] = 1.0 if ok else 0.0

        # scene_words_by_chapter_csv
        key = "scene_words_by_chapter_csv"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for k, v in exp_map.items():
                    if not _num_equal(v, act_map.get(k)):
                        ok = False
                        break
            scores["metrics_scene_words_by_chapter_csv"] = 1.0 if ok else 0.0

        # chapter_word_count_discrepancy
        key = "chapter_word_count_discrepancy"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for ch in exp_map:
                    ev = exp_map[ch]
                    av = act_map.get(ch)
                    if not isinstance(av, dict):
                        ok = False
                        break
                    fields = ["text_count", "csv_sum", "abs_diff", "pct_diff"]
                    for f in fields:
                        if f not in av:
                            ok = False
                            break
                    if not ok:
                        break
                    if not _num_equal(ev["text_count"], av["text_count"]):
                        ok = False
                        break
                    if not _num_equal(ev["csv_sum"], av["csv_sum"]):
                        ok = False
                        break
                    if not _num_equal(ev["abs_diff"], av["abs_diff"]):
                        ok = False
                        break
                    # pct_diff compare as float with small tolerance
                    if not _float_close(ev["pct_diff"], av["pct_diff"], tol=1e-9):
                        ok = False
                        break
            scores["metrics_chapter_word_count_discrepancy"] = 1.0 if ok else 0.0

        # counts_by_pov
        key = "counts_by_pov"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for k, v in exp_map.items():
                    if not _num_equal(v, act_map.get(k)):
                        ok = False
                        break
            scores["metrics_pov_counts"] = 1.0 if ok else 0.0

        # percents_by_pov (0–100 rounded to 1 decimal)
        key = "percents_by_pov"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for k, v in exp_map.items():
                    av = act_map.get(k)
                    try:
                        if abs(float(v) - float(av)) > 0.05:
                            ok = False
                            break
                    except Exception:
                        ok = False
                        break
            scores["metrics_pov_percents"] = 1.0 if ok else 0.0

        # character_mentions
        key = "character_mentions"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp_map = expected[key]
            act_map = metrics[key]
            if set(exp_map.keys()) != set(act_map.keys()):
                ok = False
            else:
                for k, v in exp_map.items():
                    if not _num_equal(v, act_map.get(k)):
                        ok = False
                        break
            scores["metrics_character_mentions"] = 1.0 if ok else 0.0

        # date_coverage
        key = "date_coverage"
        if key in metrics and isinstance(metrics[key], dict):
            ok = True
            exp = expected[key]
            act = metrics[key]
            # earliest_date, latest_date strings
            if exp.get("earliest_date") != act.get("earliest_date"):
                ok = False
            if exp.get("latest_date") != act.get("latest_date"):
                ok = False
            # missing_dates exact list
            if exp.get("missing_dates") != act.get("missing_dates"):
                ok = False
            # longest_gap object
            le = exp.get("longest_gap", {})
            la = act.get("longest_gap", {})
            if not (isinstance(la, dict) and isinstance(le, dict)):
                ok = False
            else:
                if not _num_equal(le.get("length_days", 0), la.get("length_days", None)):
                    ok = False
                if le.get("start_date") != la.get("start_date"):
                    ok = False
                if le.get("end_date") != la.get("end_date"):
                    ok = False
            scores["metrics_date_coverage"] = 1.0 if ok else 0.0

        # top_chapters_by_wordcount_text
        key = "top_chapters_by_wordcount_text"
        if key in metrics and isinstance(metrics[key], list):
            exp_list = expected[key]
            act_list = metrics[key]
            ok = isinstance(act_list, list) and act_list == exp_list
            scores["metrics_top_chapters_by_wordcount_text"] = 1.0 if ok else 0.0

        # underrepresented_protagonist_by_mentions
        key = "underrepresented_protagonist_by_mentions"
        if key in metrics:
            ok = metrics[key] == expected[key]
            scores["metrics_underrepresented_protagonist_by_mentions"] = 1.0 if ok else 0.0

    # Report checks
    report_path = workspace / "output" / "reports" / "storyworld_status.md"
    report_text = _safe_read_text(report_path)
    if report_text is not None:
        scores["report_exists"] = 1.0

        # sections present
        required_sections = [
            "Inputs processed",
            "Chapter word counts (text) and Scene word sums (CSV)",
            "POV distribution",
            "Character mentions (case-sensitive substrings)",
            "Timeline coverage",
            "Notes and recommendations",
        ]
        sec_ok = all(s in report_text for s in required_sections)
        scores["report_sections_present"] = 1.0 if sec_ok else 0.0

        # inputs listed (look for exact input paths)
        input_paths = [
            "input/chapters/chapter_01.txt",
            "input/chapters/chapter_02.txt",
            "input/chapters/chapter_03.txt",
            "input/scenes.csv",
            "input/characters.json",
            "input/teaching_module_draft.md",
        ]
        inputs_section = _extract_section(report_text, "Inputs processed")
        if inputs_section is not None:
            inputs_ok = all(p in inputs_section for p in input_paths)
            scores["report_inputs_listed"] = 1.0 if inputs_ok else 0.0

        # POV distribution correctness (counts and percentages)
        if expected is not None:
            pov_sec = _extract_section(report_text, "POV distribution")
            pov_ok = False
            if pov_sec is not None:
                # Check each POV name, count, and percent presence in the section
                pov_ok = True
                for pov, cnt in expected["counts_by_pov"].items():
                    perc = expected["percents_by_pov"][pov]
                    # Search for count and percentage for the POV in the section
                    pattern_present = (pov in pov_sec) and (str(cnt) in pov_sec) and (("{:.1f}%".format(perc)) in pov_sec or "{:.1f}".format(perc) in pov_sec)
                    if not pattern_present:
                        pov_ok = False
                        break
            scores["report_pov_distribution_correct"] = 1.0 if pov_ok else 0.0

        # Character mentions correctness
        if expected is not None:
            cm_sec = _extract_section(report_text, "Character mentions (case-sensitive substrings)")
            cm_ok = False
            if cm_sec is not None:
                cm_ok = True
                for name, count in expected["character_mentions"].items():
                    # Look for a line containing the name and its count
                    line_found = False
                    for line in cm_sec.splitlines():
                        if name in line and str(count) in line:
                            line_found = True
                            break
                    if not line_found:
                        cm_ok = False
                        break
            scores["report_character_mentions_correct"] = 1.0 if cm_ok else 0.0

        # Timeline coverage correctness
        if expected is not None:
            tl_sec = _extract_section(report_text, "Timeline coverage")
            tl_ok = False
            if tl_sec is not None:
                e = expected["date_coverage"]["earliest_date"]
                l = expected["date_coverage"]["latest_date"]
                missing = expected["date_coverage"]["missing_dates"]
                lg = expected["date_coverage"]["longest_gap"]
                has_ear_latest = (e in tl_sec) and (l in tl_sec)
                missing_ok = True
                for d in missing:
                    if d not in tl_sec:
                        missing_ok = False
                        break
                lg_ok = (lg["start_date"] in tl_sec) and (lg["end_date"] in tl_sec) and (str(lg["length_days"]) in tl_sec)
                tl_ok = has_ear_latest and missing_ok and lg_ok
            scores["report_timeline_coverage_correct"] = 1.0 if tl_ok else 0.0

        # Notes and recommendations: 3–5 bullet points
        notes_sec = _extract_section(report_text, "Notes and recommendations")
        if notes_sec is not None:
            bullets = [ln for ln in notes_sec.splitlines() if ln.strip().startswith("- ")]
            count_ok = 3 <= len(bullets) <= 5
            scores["report_notes_count_valid"] = 1.0 if count_ok else 0.0

    # Final module checks
    final_path = workspace / "output" / "teaching_module_final.md"
    final_text = _safe_read_text(final_path)
    if final_text is not None:
        scores["final_module_exists"] = 1.0

        # Preserve existing title
        first_line = final_text.splitlines()[0].strip() if final_text.splitlines() else ""
        if first_line == "# Historical Fiction Workshop: Voices of 1773":
            scores["final_module_preserves_title"] = 1.0

        if expected is not None:
            # Reading Assignment section
            ra_sec = _extract_section(final_text, "Reading Assignment")
            ra_ok = False
            if ra_sec is not None:
                tops = expected["top_chapters_by_wordcount_text"]
                cwcts = expected["chapter_word_counts_text"]
                # both file names present
                if all(t in ra_sec for t in tops):
                    # include rationale referencing their counts (look for their counts as numbers)
                    counts_present = all(str(cwcts.get(t, "")) in ra_sec for t in tops)
                    ra_ok = counts_present
            scores["final_module_reading_assignment_updated"] = 1.0 if ra_ok else 0.0

            # Character Focus section
            cf_sec = _extract_section(final_text, "Character Focus")
            cf_ok = False
            if cf_sec is not None:
                underrep = expected["underrepresented_protagonist_by_mentions"]
                mentions = expected["character_mentions"].get(underrep, 0)
                # Determine that protagonist's POV stats (if any)
                # Use scenes.csv counts & percents to find POV percent for the name if POV matches name
                pov_percent = None
                perc_map = expected["percents_by_pov"]
                if underrep in perc_map:
                    pov_percent = perc_map[underrep]
                name_present = underrep in cf_sec
                mentions_present = str(mentions) in cf_sec
                bullets = [ln for ln in cf_sec.splitlines() if ln.strip().startswith("- ")]
                bullets_ok = len(bullets) >= 2
                pov_stat_present = False
                if pov_percent is not None:
                    # accept either "33.3%" or "33.3"
                    pov_stat_present = ("{:.1f}%".format(pov_percent) in cf_sec) or ("{:.1f}".format(pov_percent) in cf_sec)
                else:
                    # if no direct POV percent, allow presence of "POV" keyword
                    pov_stat_present = "POV" in cf_sec or "pov" in cf_sec
                cf_ok = name_present and mentions_present and bullets_ok and pov_stat_present
            scores["final_module_character_focus_updated"] = 1.0 if cf_ok else 0.0

            # Timeline Exercise section
            tlm_sec = _extract_section(final_text, "Timeline Exercise")
            tlm_ok = False
            if tlm_sec is not None:
                lg = expected["date_coverage"]["longest_gap"]
                tlm_ok = (lg["start_date"] in tlm_sec) and (lg["end_date"] in tlm_sec)
            scores["final_module_timeline_exercise_updated"] = 1.0 if tlm_ok else 0.0

            # Expected Outcomes section
            eo_sec = _extract_section(final_text, "Expected Outcomes")
            eo_ok = False
            if eo_sec is not None:
                bullets = [ln for ln in eo_sec.splitlines() if ln.strip().startswith("- ")]
                # Need at least two bullets explicitly referencing top chapters, protagonist focus, and/or the gap
                enough_bullets = len(bullets) >= 2
                ref_count = 0
                # tokens to look for
                tokens: List[str] = []
                tokens.extend(expected["top_chapters_by_wordcount_text"])
                tokens.append(expected["underrepresented_protagonist_by_mentions"])
                lg = expected["date_coverage"]["longest_gap"]
                if lg.get("start_date"):
                    tokens.append(lg["start_date"])
                if lg.get("end_date"):
                    tokens.append(lg["end_date"])
                for t in tokens:
                    if t and t in eo_sec:
                        ref_count += 1
                eo_ok = enough_bullets and (ref_count >= 2)
            scores["final_module_expected_outcomes_updated"] = 1.0 if eo_ok else 0.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) >= 2:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()