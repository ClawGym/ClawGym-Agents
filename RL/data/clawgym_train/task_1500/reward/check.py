import json
import csv
import re
import sys
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple


def _safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _safe_load_jsonl(path: Path) -> Optional[List[dict]]:
    try:
        lines = []
        with path.open("r", encoding="utf-8") as f:
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
                lines.append(obj)
        return lines
    except Exception:
        return None


def _safe_read_csv(path: Path) -> Optional[Tuple[List[str], List[dict]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return None
            rows = [row for row in reader]
            return reader.fieldnames, rows
    except Exception:
        return None


def _count_words(text: str) -> int:
    # Count words as sequences of alphanumeric/underscore separated by non-word
    return len(re.findall(r"\b\w+\b", text))


def _normalize_text(s: str) -> str:
    # Lower-case and replace curly quotes with straight quotes for matching
    s = s.lower()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("–", "-").replace("—", "-")
    return s


def _extract_draft_facts(draft_path: Path) -> Optional[dict]:
    raw = _safe_read_text(draft_path)
    if raw is None:
        return None
    text = _normalize_text(raw)

    facts = {}

    # Library name (as in draft)
    lib_match = re.search(r"aksaray community library", text)
    if lib_match:
        facts["library_name"] = "Aksaray Community Library"
    else:
        facts["library_name"] = None

    # Talk title after 'titled' in quotes, or any first quoted phrase containing 'ottoman'
    title = None
    # Try find: titled "..."
    titled_match = re.search(r'titled\s+[\'"]([^\'"]+)[\'"]', text)
    if titled_match:
        title = titled_match.group(1).strip()
    else:
        # Try curly/straight quotes
        quoted = re.findall(r'["]([^"]+)["]', text)
        if quoted:
            # pick the one that looks like a title (contains 'ottoman' or 'gazel')
            candidates = [q for q in quoted if ("ottoman" in q or "gazel" in q or "gazels" in q)]
            if candidates:
                title = candidates[0]
            else:
                title = quoted[0]
        else:
            # Try curly quotes that may have been normalized
            pass
    facts["talk_title"] = title

    # Date: look for day number and month near the "hoping for" phrase, else any month-day in text
    # For determinism, use the first 'hoping for' segment if exists
    date_day = None
    date_month = None
    month_names = ("january", "february", "march", "april", "may", "june",
                   "july", "august", "september", "october", "november", "december")
    segment = text
    hoping_idx = text.find("hoping for")
    if hoping_idx != -1:
        segment = text[hoping_idx:hoping_idx + 200]  # small window
    # Patterns: "19 november" or "november 19"
    m1 = re.search(r"\b(\d{1,2})\s+(%s)\b" % "|".join(month_names), segment)
    m2 = re.search(r"\b(%s)\s+(\d{1,2})\b" % "|".join(month_names), segment)
    if m1:
        date_day = m1.group(1)
        date_month = m1.group(2)
    elif m2:
        date_month = m2.group(1)
        date_day = m2.group(2)
    facts["date_day"] = date_day
    facts["date_month"] = date_month

    # Times: detect two times like 3:00 and 4:15
    times = re.findall(r"\b(\d{1,2}:\d{2})\b", text)
    # The draft has "3:00–4:15 pm"; normalization turns EN DASH into '-'
    if len(times) >= 2:
        facts["time_start"] = times[0]
        facts["time_end"] = times[1]
    else:
        # As fallback, split on '-' and search around
        # Already normalized en dash to '-'
        time_span_match = re.search(r"\b(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\b", text)
        if time_span_match:
            facts["time_start"] = time_span_match.group(1)
            facts["time_end"] = time_span_match.group(2)
        else:
            facts["time_start"] = None
            facts["time_end"] = None

    # Person name Selim Kaya
    sk = bool(re.search(r"\bselim\b", text)) and bool(re.search(r"\bkaya\b", text))
    facts["selim_kaya"] = sk

    return facts


def _recompute_poem_aggregates(poems: List[dict]) -> Optional[dict]:
    try:
        total_poems = 0
        total_lines = 0
        poems_by_poet: Dict[str, int] = {}
        poems_by_form: Dict[str, int] = {}
        lines_by_poet: Dict[str, int] = {}
        lines_by_form: Dict[str, int] = {}
        for p in poems:
            # Robustness: ensure required fields exist and types are valid
            if not all(k in p for k in ("id", "poet", "title", "form", "lines")):
                return None
            poet = p["poet"]
            form = p["form"]
            lines = p["lines"]
            if not isinstance(lines, list):
                return None
            n_lines = len(lines)
            total_poems += 1
            total_lines += n_lines
            poems_by_poet[poet] = poems_by_poet.get(poet, 0) + 1
            poems_by_form[form] = poems_by_form.get(form, 0) + 1
            lines_by_poet[poet] = lines_by_poet.get(poet, 0) + n_lines
            lines_by_form[form] = lines_by_form.get(form, 0) + n_lines
        return {
            "total_poems": total_poems,
            "total_lines": total_lines,
            "poems_by_poet": poems_by_poet,
            "poems_by_form": poems_by_form,
            "lines_by_poet": lines_by_poet,
            "lines_by_form": lines_by_form,
        }
    except Exception:
        return None


def _expected_poem_stats_rows(poems: List[dict]) -> Optional[Dict[str, dict]]:
    try:
        mapping = {}
        for p in poems:
            if not all(k in p for k in ("id", "poet", "title", "form", "lines")):
                return None
            idv = p["id"]
            poet = p["poet"]
            title = p["title"]
            form = p["form"]
            lines = p["lines"]
            if not isinstance(lines, list):
                return None
            mapping[idv] = {
                "id": idv,
                "poet": poet,
                "title": title,
                "form": form,
                "num_lines": str(len(lines)),
            }
        return mapping
    except Exception:
        return None


def _compare_dicts(a: dict, b: dict) -> bool:
    # Deep equality comparison
    return a == b


def _find_validate_command(workspace: Path) -> Optional[List[str]]:
    # Prefer a local executable named 'validate'
    validate_file = workspace / "validate"
    if validate_file.exists():
        # Try to run it directly if executable or via sh
        if validate_file.is_file():
            # Execute directly; rely on OS shebang/exec bit
            return ["./validate"]
    # Fallback: Makefile target 'validate'
    makefile = workspace / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
        except Exception:
            content = ""
        if re.search(r"^validate\s*:", content, flags=re.MULTILINE):
            return ["make", "validate"]
    return None


def _run_command(cmd: List[str], cwd: Path, timeout_sec: int = 20) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            text=True,
            shell=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return 127, "", str(e)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "poem_stats_csv_exists_and_header": 0.0,
        "poem_stats_csv_content_matches": 0.0,
        "summary_json_schema_and_values": 0.0,
        "summary_equals_expected": 0.0,
        "totals_consistency_between_csv_and_summary": 0.0,
        "formal_email_contains_required_facts": 0.0,
        "concise_note_contains_required_facts": 0.0,
        "concise_note_word_limit": 0.0,
        "validate_command_available": 0.0,
        "validate_command_runs_successfully": 0.0,
        "readme_mentions_validate_and_paths": 0.0,
    }

    # Paths
    input_poems_path = workspace / "input" / "poems.jsonl"
    input_expected_summary_path = workspace / "input" / "expected_summary.json"
    input_draft_email_path = workspace / "input" / "draft_email.txt"

    output_poem_stats_path = workspace / "output" / "stats" / "poem_stats.csv"
    output_summary_path = workspace / "output" / "stats" / "summary.json"
    output_formal_email_path = workspace / "output" / "messages" / "formal_email.txt"
    output_concise_note_path = workspace / "output" / "messages" / "concise_note.txt"

    # Load input poems
    poems = _safe_load_jsonl(input_poems_path)
    expected_aggregates = None
    expected_rows = None
    if poems is not None:
        expected_aggregates = _recompute_poem_aggregates(poems)
        expected_rows = _expected_poem_stats_rows(poems)

    # Check poem_stats.csv
    csv_data = _safe_read_csv(output_poem_stats_path)
    if csv_data is not None:
        header, rows = csv_data
        # Exact header required
        expected_header = ["id", "poet", "title", "form", "num_lines"]
        if header == expected_header:
            scores["poem_stats_csv_exists_and_header"] = 1.0
        else:
            scores["poem_stats_csv_exists_and_header"] = 0.0

        # Content matches
        if expected_rows is not None and header == expected_header:
            # Build mapping by id
            csv_map: Dict[str, dict] = {}
            valid_rows = True
            for r in rows:
                # Ensure required fields exist and no extra columns beyond header
                if set(r.keys()) != set(expected_header):
                    valid_rows = False
                    break
                idv = r["id"]
                if idv in csv_map:
                    valid_rows = False
                    break
                # Ensure num_lines int convertible
                try:
                    int(r["num_lines"])
                except Exception:
                    valid_rows = False
                    break
                csv_map[idv] = {
                    "id": r["id"],
                    "poet": r["poet"],
                    "title": r["title"],
                    "form": r["form"],
                    "num_lines": str(int(r["num_lines"])),
                }
            if valid_rows and csv_map == expected_rows and len(csv_map) == len(expected_rows):
                scores["poem_stats_csv_content_matches"] = 1.0
            else:
                scores["poem_stats_csv_content_matches"] = 0.0
        else:
            scores["poem_stats_csv_content_matches"] = 0.0
    else:
        scores["poem_stats_csv_exists_and_header"] = 0.0
        scores["poem_stats_csv_content_matches"] = 0.0

    # Check summary.json schema and values
    produced_summary = _safe_load_json(output_summary_path)
    expected_summary = _safe_load_json(input_expected_summary_path)
    if produced_summary is not None and expected_aggregates is not None:
        # Verify schema keys
        required_keys = ["total_poems", "total_lines", "poems_by_poet", "poems_by_form", "lines_by_poet", "lines_by_form"]
        schema_ok = all(k in produced_summary for k in required_keys) and set(produced_summary.keys()) == set(required_keys)
        types_ok = isinstance(produced_summary.get("total_poems"), int) and isinstance(produced_summary.get("total_lines"), int)
        # The mapping values must be int
        def _all_int_values(d):
            if not isinstance(d, dict):
                return False
            for v in d.values():
                if not isinstance(v, int):
                    return False
            return True
        maps_ok = _all_int_values(produced_summary.get("poems_by_poet")) and \
                  _all_int_values(produced_summary.get("poems_by_form")) and \
                  _all_int_values(produced_summary.get("lines_by_poet")) and \
                  _all_int_values(produced_summary.get("lines_by_form"))
        # Compare to recomputed
        values_ok = _compare_dicts(produced_summary, expected_aggregates)
        if schema_ok and types_ok and maps_ok and values_ok:
            scores["summary_json_schema_and_values"] = 1.0
        else:
            scores["summary_json_schema_and_values"] = 0.0
    else:
        scores["summary_json_schema_and_values"] = 0.0

    # Check equality to expected summary
    if produced_summary is not None and expected_summary is not None:
        if _compare_dicts(produced_summary, expected_summary):
            scores["summary_equals_expected"] = 1.0
        else:
            scores["summary_equals_expected"] = 0.0
    else:
        scores["summary_equals_expected"] = 0.0

    # Cross-file totals consistency
    total_lines_csv = None
    produced_total_lines = None
    expected_total_lines = None
    if csv_data is not None:
        _, rows = csv_data
        try:
            total_lines_csv = sum(int(r["num_lines"]) for r in rows)
        except Exception:
            total_lines_csv = None
    if produced_summary is not None:
        try:
            produced_total_lines = int(produced_summary.get("total_lines"))
        except Exception:
            produced_total_lines = None
    if expected_summary is not None:
        try:
            expected_total_lines = int(expected_summary.get("total_lines"))
        except Exception:
            expected_total_lines = None
    if (total_lines_csv is not None) and (produced_total_lines is not None) and (expected_total_lines is not None):
        if total_lines_csv == produced_total_lines == expected_total_lines:
            scores["totals_consistency_between_csv_and_summary"] = 1.0
        else:
            scores["totals_consistency_between_csv_and_summary"] = 0.0
    else:
        scores["totals_consistency_between_csv_and_summary"] = 0.0

    # Message rewriting checks
    draft_facts = _extract_draft_facts(input_draft_email_path) if input_draft_email_path.exists() else None

    def check_required_facts_in_text(result_path: Path, facts: dict) -> float:
        if facts is None:
            return 0.0
        content = _safe_read_text(result_path)
        if content is None:
            return 0.0
        tx = _normalize_text(content)
        checks = []
        # Library name
        if facts.get("library_name"):
            checks.append("aksaray community library" in tx)
        # Talk title (ignore quotes)
        if facts.get("talk_title"):
            title_norm = _normalize_text(facts["talk_title"]).strip('"').strip("'")
            checks.append(title_norm in tx)
        # Date either "19 november" or "november 19"
        dm = facts.get("date_month")
        dd = facts.get("date_day")
        if dm and dd:
            date1 = f"{dd} {dm}"
            date2 = f"{dm} {dd}"
            checks.append((_normalize_text(date1) in tx) or (_normalize_text(date2) in tx))
        # Times
        ts = facts.get("time_start")
        te = facts.get("time_end")
        if ts and te:
            checks.append((ts in tx) and (te in tx))
        # Name Selim Kaya
        if facts.get("selim_kaya") is True:
            has_selim = "selim" in tx
            has_kaya = "kaya" in tx
            checks.append(has_selim and has_kaya)
        # Calculate fraction of satisfied checks
        if not checks:
            return 0.0
        satisfied = sum(1 for c in checks if c)
        return satisfied / float(len(checks))

    if draft_facts is not None:
        scores["formal_email_contains_required_facts"] = check_required_facts_in_text(output_formal_email_path, draft_facts)
        scores["concise_note_contains_required_facts"] = check_required_facts_in_text(output_concise_note_path, draft_facts)
    else:
        scores["formal_email_contains_required_facts"] = 0.0
        scores["concise_note_contains_required_facts"] = 0.0

    # Concise note word limit
    concise_text = _safe_read_text(output_concise_note_path)
    if concise_text is not None:
        wc = _count_words(concise_text)
        scores["concise_note_word_limit"] = 1.0 if wc <= 120 else 0.0
    else:
        scores["concise_note_word_limit"] = 0.0

    # Validate command availability and run
    cmd = _find_validate_command(workspace)
    if cmd is not None:
        scores["validate_command_available"] = 1.0
        # Execute
        rc, out, err = _run_command(cmd, cwd=workspace, timeout_sec=30)
        # Success if exit code == 0 and stdout indicates pass
        out_norm = _normalize_text(out or "")
        if rc == 0 and ("pass" in out_norm or "ok" in out_norm or "success" in out_norm):
            scores["validate_command_runs_successfully"] = 1.0
        else:
            scores["validate_command_runs_successfully"] = 0.0
    else:
        scores["validate_command_available"] = 0.0
        scores["validate_command_runs_successfully"] = 0.0

    # README checks
    readme_path = workspace / "README.md"
    readme = _safe_read_text(readme_path)
    if readme is not None:
        rn = _normalize_text(readme)
        has_validate = "validate" in rn
        mentions_stats = "output/stats/" in readme or "output/stats" in readme
        mentions_messages = "output/messages/" in readme or "output/messages" in readme
        if has_validate and mentions_stats and mentions_messages:
            scores["readme_mentions_validate_and_paths"] = 1.0
        else:
            scores["readme_mentions_validate_and_paths"] = 0.0
    else:
        scores["readme_mentions_validate_and_paths"] = 0.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()