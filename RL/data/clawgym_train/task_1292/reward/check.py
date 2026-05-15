import json
import csv
import sys
import re
from pathlib import Path
from typing import List, Dict, Any, Optional


def _safe_load_json(path: Path) -> Optional[Any]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_read_jsonl(path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        if not path.exists():
            return None
        items = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = [row for row in reader]
            header = reader.fieldnames or []
        return {"header": header, "rows": rows}
    except Exception:
        return None


def _compute_transcript_stats(transcripts: List[Dict[str, Any]]) -> Dict[str, Any]:
    themes = ["resilience", "loss", "courage", "ethics", "fear", "hope", "aftermath"]
    speakers = ["Reporter", "Local Fixer", "Medic", "Refugee", "Photographer"]
    per_theme_counts = {t: 0 for t in themes}
    per_speaker_counts = {s: 0 for s in speakers}
    total_entries = len(transcripts)
    all_lengths = []
    eligible_lengths = []
    banned_subs = ["blood", "gore"]

    for rec in transcripts:
        text = rec.get("text", "")
        tags = rec.get("tags", [])
        speaker = rec.get("speaker", "")
        for t in themes:
            if t in tags:
                per_theme_counts[t] += 1
        if speaker in per_speaker_counts:
            per_speaker_counts[speaker] += 1
        length = len(text)
        all_lengths.append(length)
        text_lower = text.lower()
        banned = any(b in text_lower for b in banned_subs)
        if length <= 200 and not banned:
            eligible_lengths.append(length)

    eligible_for_selection = len(eligible_lengths)
    avg_char_count_all = float(sum(all_lengths) / total_entries) if total_entries > 0 else 0.0
    avg_char_count_eligible = float(sum(eligible_lengths) / eligible_for_selection) if eligible_for_selection > 0 else 0.0

    return {
        "total_entries": total_entries,
        "eligible_for_selection": eligible_for_selection,
        "per_theme_counts": per_theme_counts,
        "per_speaker_counts": per_speaker_counts,
        "avg_char_count_all": avg_char_count_all,
        "avg_char_count_eligible": avg_char_count_eligible,
    }


def _float_equal(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


def _parse_tags_field(tags_field: str) -> List[str]:
    if tags_field is None:
        return []
    parts = [p.strip() for p in tags_field.split(",") if p.strip() != ""]
    return parts


def _find_section(text: str, heading: str) -> Optional[str]:
    lines = text.splitlines()
    start_idx = None
    pattern = re.compile(rf"^\s*{re.escape(heading)}\s*:\s*$", re.IGNORECASE)
    for i, line in enumerate(lines):
        if pattern.match(line):
            start_idx = i + 1
            break
    if start_idx is None:
        inline_pattern = re.compile(rf"^\s*{re.escape(heading)}\s*:\s*(.*)$", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = inline_pattern.match(line)
            if m:
                content_lines = [m.group(1)]
                j = i + 1
                while j < len(lines):
                    if re.match(r"^\s*\w[\w\s]*:\s*$", lines[j]):
                        break
                    content_lines.append(lines[j])
                    j += 1
                return "\n".join(content_lines).strip()
        return None
    content_lines = []
    i = start_idx
    while i < len(lines):
        if re.match(r"^\s*\w[\w\s]*:\s*$", lines[i]):
            break
        content_lines.append(lines[i])
        i += 1
    return "\n".join(content_lines).strip()


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "theme_stats_file_present_and_structure": 0.0,
        "theme_stats_total_entries_correct": 0.0,
        "theme_stats_per_theme_counts_correct": 0.0,
        "theme_stats_per_speaker_counts_correct": 0.0,
        "theme_stats_eligible_count_correct": 0.0,
        "theme_stats_avg_all_correct": 0.0,
        "theme_stats_avg_eligible_correct": 0.0,
        "quote_candidates_file_present_and_parseable": 0.0,
        "quote_candidates_exactly_five_rows": 0.0,
        "quote_candidates_required_columns_present_only": 0.0,
        "quote_candidates_values_match_transcripts": 0.0,
        "quote_candidates_char_count_and_length_rule": 0.0,
        "quote_candidates_requires_cw_correct": 0.0,
        "quote_candidates_banned_substrings_absent": 0.0,
        "quote_candidates_themes_coverage_and_limits": 0.0,
        "quote_candidates_unique_ids": 0.0,
        "meeting_notes_file_present": 0.0,
        "meeting_notes_findings_top_two_and_eligible": 0.0,
        "meeting_notes_action_items_requirements": 0.0,
        "run_command_single_line": 0.0,
    }

    transcripts_path = workspace / "input" / "transcripts.jsonl"
    guidelines_path = workspace / "input" / "guidelines.md"
    transcripts = _safe_read_jsonl(transcripts_path)

    expected_stats = None
    if transcripts is not None:
        expected_stats = _compute_transcript_stats(transcripts)

    theme_stats_path = workspace / "output" / "theme_stats.json"
    theme_stats = _safe_load_json(theme_stats_path)
    if isinstance(theme_stats, dict):
        required_keys = {
            "total_entries",
            "eligible_for_selection",
            "per_theme_counts",
            "per_speaker_counts",
            "avg_char_count_all",
            "avg_char_count_eligible",
        }
        if set(theme_stats.keys()) == required_keys and \
           isinstance(theme_stats.get("per_theme_counts"), dict) and \
           isinstance(theme_stats.get("per_speaker_counts"), dict):
            scores["theme_stats_file_present_and_structure"] = 1.0

        if expected_stats is not None:
            if theme_stats.get("total_entries") == expected_stats["total_entries"]:
                scores["theme_stats_total_entries_correct"] = 1.0
            themes = ["resilience", "loss", "courage", "ethics", "fear", "hope", "aftermath"]
            ptc = theme_stats.get("per_theme_counts") or {}
            if all(ptc.get(t) == expected_stats["per_theme_counts"][t] for t in themes):
                scores["theme_stats_per_theme_counts_correct"] = 1.0
            speakers = ["Reporter", "Local Fixer", "Medic", "Refugee", "Photographer"]
            psc = theme_stats.get("per_speaker_counts") or {}
            if all(psc.get(s) == expected_stats["per_speaker_counts"][s] for s in speakers):
                scores["theme_stats_per_speaker_counts_correct"] = 1.0
            if theme_stats.get("eligible_for_selection") == expected_stats["eligible_for_selection"]:
                scores["theme_stats_eligible_count_correct"] = 1.0
            avg_all = theme_stats.get("avg_char_count_all")
            if isinstance(avg_all, (int, float)) and _float_equal(float(avg_all), float(expected_stats["avg_char_count_all"])):
                scores["theme_stats_avg_all_correct"] = 1.0
            avg_elig = theme_stats.get("avg_char_count_eligible")
            if isinstance(avg_elig, (int, float)) and _float_equal(float(avg_elig), float(expected_stats["avg_char_count_eligible"])):
                scores["theme_stats_avg_eligible_correct"] = 1.0

    quote_csv_path = workspace / "output" / "quote_candidates.csv"
    csv_data = _safe_read_csv(quote_csv_path)
    if csv_data is not None and isinstance(csv_data.get("rows"), list):
        scores["quote_candidates_file_present_and_parseable"] = 1.0
        rows = csv_data["rows"]
        header = csv_data["header"] or []
        if len(rows) == 5:
            scores["quote_candidates_exactly_five_rows"] = 1.0
        required_cols = {"quote_id", "text", "tags", "char_count", "requires_cw", "source", "timestamp"}
        if set(header) == required_cols:
            scores["quote_candidates_required_columns_present_only"] = 1.0

        if transcripts is not None:
            id_map = {rec.get("id"): rec for rec in transcripts}
            values_match = True
            char_ok = True
            requires_ok = True
            banned_ok = True
            unique_ids_ok = True
            unique_ids = set()
            coverage_themes: Dict[str, int] = {t: 0 for t in ["resilience", "loss", "courage", "ethics", "fear", "hope", "aftermath"]}
            distinct_themes = set()

            for row in rows:
                qid = row.get("quote_id")
                txt = row.get("text", "")
                tags_field = row.get("tags", "")
                char_str = row.get("char_count", "")
                req_cw = (row.get("requires_cw") or "").strip().lower()
                src = row.get("source")
                ts = row.get("timestamp")

                if qid in unique_ids:
                    unique_ids_ok = False
                unique_ids.add(qid)

                rec = id_map.get(qid)
                if not rec:
                    values_match = False
                    continue
                if txt != rec.get("text", ""):
                    values_match = False
                if src != rec.get("source") or ts != rec.get("timestamp"):
                    values_match = False
                csv_tags_list = _parse_tags_field(tags_field)
                rec_tags_list = rec.get("tags", [])
                if csv_tags_list != rec_tags_list:
                    values_match = False
                try:
                    char_int = int(char_str)
                except Exception:
                    char_ok = False
                    char_int = None
                true_len = len(rec.get("text", ""))
                if char_int is None or char_int != true_len:
                    char_ok = False
                if true_len > 200:
                    char_ok = False
                rec_tags_set = set(rec_tags_list)
                expected_req = "yes" if ({"loss", "aftermath"} & rec_tags_set) else "no"
                if req_cw != expected_req:
                    requires_ok = False
                tl = txt.lower()
                if ("blood" in tl) or ("gore" in tl):
                    banned_ok = False
                for t in rec_tags_set:
                    if t in coverage_themes:
                        coverage_themes[t] += 1
                        distinct_themes.add(t)

            if values_match:
                scores["quote_candidates_values_match_transcripts"] = 1.0
            if char_ok:
                scores["quote_candidates_char_count_and_length_rule"] = 1.0
            if requires_ok:
                scores["quote_candidates_requires_cw_correct"] = 1.0
            if banned_ok:
                scores["quote_candidates_banned_substrings_absent"] = 1.0
            if unique_ids_ok and len(unique_ids) == len(rows):
                scores["quote_candidates_unique_ids"] = 1.0

            coverage_ok = True
            if len(distinct_themes) < 3:
                coverage_ok = False
            for t, c in coverage_themes.items():
                if c > 2:
                    coverage_ok = False
                    break
            if coverage_ok:
                scores["quote_candidates_themes_coverage_and_limits"] = 1.0

    notes_path = workspace / "output" / "meeting_notes.md"
    notes_text = _safe_read_text(notes_path)
    if notes_text is not None:
        scores["meeting_notes_file_present"] = 1.0
        findings_ok = False
        if isinstance(theme_stats, dict):
            findings_section = _find_section(notes_text, "Findings")
            if findings_section is None:
                findings_section = ""
            ptc = theme_stats.get("per_theme_counts") if isinstance(theme_stats.get("per_theme_counts"), dict) else {}
            themes_all = ["resilience", "loss", "courage", "ethics", "fear", "hope", "aftermath"]
            theme_items = [(t, int(ptc.get(t, 0))) for t in themes_all]
            theme_items.sort(key=lambda x: (-x[1], x[0]))
            top_two = theme_items[:2]
            elig = theme_stats.get("eligible_for_selection")
            found_both = True
            lower_findings = findings_section.lower()
            for tname, cnt in top_two:
                if (tname.lower() not in lower_findings) or (str(cnt) not in findings_section):
                    found_both = False
                    break
            has_eligible_number = (("eligible" in lower_findings) and (str(elig) in findings_section))
            if found_both and has_eligible_number:
                findings_ok = True
        if findings_ok:
            scores["meeting_notes_findings_top_two_and_eligible"] = 1.0

        action_ok = False
        action_section = _find_section(notes_text, "Action Items")
        if action_section is None:
            action_section = ""
        bullet_lines = [ln for ln in action_section.splitlines() if re.match(r"^\s*[-*]\s+", ln)]
        bullets_count_ok = len(bullet_lines) >= 4
        days_present = all(re.search(rf"\bDay {i}\b", action_section, re.IGNORECASE) for i in range(1, 6))

        any_cw_yes = False
        if csv_data is not None and isinstance(csv_data.get("rows"), list):
            for row in csv_data["rows"]:
                if (row.get("requires_cw") or "").strip().lower() == "yes":
                    any_cw_yes = True
                    break
        cw_flag_present = True
        if any_cw_yes:
            cw_flag_present = bool(re.search(r"\bCW\b", action_section, re.IGNORECASE) or re.search(r"content warning", action_section, re.IGNORECASE))

        least_theme_re = re.compile(r"least[\s-]*represented.*theme", re.IGNORECASE)
        two_re = re.compile(r"\b(2|two)\b", re.IGNORECASE)
        has_least_theme_item = any(least_theme_re.search(ln) and two_re.search(ln) for ln in bullet_lines)

        has_attribution_item = any(("attribution" in ln.lower() and "source" in ln.lower() and "timestamp" in ln.lower()) for ln in bullet_lines)

        has_tone_item = any(("tone" in ln.lower() and "guidelines" in ln.lower()) for ln in bullet_lines)

        if bullets_count_ok and days_present and cw_flag_present and has_least_theme_item and has_attribution_item and has_tone_item:
            action_ok = True

        if action_ok:
            scores["meeting_notes_action_items_requirements"] = 1.0

    run_cmd_path = workspace / "output" / "run_command.txt"
    run_cmd_text = _safe_read_text(run_cmd_path)
    if run_cmd_text is not None:
        non_empty_lines = [ln for ln in run_cmd_text.splitlines() if ln.strip() != ""]
        if len(non_empty_lines) == 1:
            scores["run_command_single_line"] = 1.0

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()