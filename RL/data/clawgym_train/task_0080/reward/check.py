import json
import csv
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_csv_dicts(path: Path) -> Optional[List[Dict[str, str]]]:
    try:
        with path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        # Ensure headers exist
        if reader.fieldnames is None:
            return None
        return rows
    except Exception:
        return None


def _list_files(path: Path) -> Optional[List[Path]]:
    try:
        if not path.exists() or not path.is_dir():
            return []
        return [p for p in path.iterdir() if p.is_file()]
    except Exception:
        return None


def _compute_expected_missing(catalog_rows: List[Dict[str, str]], transcripts_dir: Path) -> List[Dict[str, str]]:
    missing = []
    for row in catalog_rows:
        transcript_file = row.get("TranscriptFile", "")
        expected_path = transcripts_dir / transcript_file
        if not expected_path.exists():
            missing.append({
                "InterviewID": row.get("InterviewID", ""),
                "Interviewee": row.get("Interviewee", ""),
                "TranscriptFile": transcript_file
            })
    return missing


def _index_listed_map(index_data) -> Dict[str, str]:
    """
    Returns map from InterviewID -> "yes"/"no" (listed if any entry has a transcript_path for that InterviewID).
    """
    listed_ids = set()
    if isinstance(index_data, list):
        for item in index_data:
            try:
                iid = item.get("InterviewID")
                # treat presence of transcript_path (any value) as listed
                if iid is not None and "transcript_path" in item:
                    listed_ids.add(str(iid))
            except Exception:
                continue
    return {iid: "yes" for iid in listed_ids}


def _parse_summary_counts(text: str) -> Dict[str, Optional[int]]:
    """
    Extract counts from summary.md using label-aware heuristics.
    Returns dict with keys: total_catalog, present_files, missing_transcripts.
    """
    counts = {
        "total_catalog": None,
        "present_files": None,
        "missing_transcripts": None,
    }
    lines = text.splitlines()
    for line in lines:
        low = line.lower()
        nums = re.findall(r"\d+", line)
        if not nums:
            continue
        if "total" in low and "catalog" in low and "entr" in low:
            counts["total_catalog"] = int(nums[0])
        if ("present" in low and "transcript" in low) or ("present" in low and "files" in low):
            counts["present_files"] = int(nums[-1])
        if "missing" in low and "transcript" in low:
            counts["missing_transcripts"] = int(nums[0])
    return counts


def _extract_bullet_missing_items(text: str) -> List[str]:
    """
    Extract bullet lines that match "- InterviewID — Interviewee — TranscriptFile"
    We check for the em dash character U+2014 surrounded by spaces.
    """
    items = []
    for line in text.splitlines():
        if line.strip().startswith("- "):
            content = line.strip()[2:]
            # Must contain two em dashes with spaces around
            if " — " in content:
                parts = content.split(" — ")
                if len(parts) == 3:
                    items.append(content)
    return items


def _contains_likely_cause(text: str) -> bool:
    """
    Check that the summary includes a brief explanation of likely cause (wrong directory path).
    """
    low = text.lower()
    keywords = [
        "typo",
        "incorrect path",
        "incorrect directory",
        "wrong path",
        "wrong directory",
        "missing 's'",
        "missing s",
        "directory name is missing",
    ]
    return any(k in low for k in keywords)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    # Paths
    catalog_csv = workspace / "input" / "catalog" / "oral_histories.csv"
    transcripts_dir = workspace / "input" / "transcripts"
    index_json = workspace / "input" / "index" / "collection_index.json"

    output_missing_csv = workspace / "output" / "missing_transcripts.csv"
    output_summary_md = workspace / "output" / "summary.md"
    output_email_txt = workspace / "output" / "email_to_curator.txt"
    logs_check_log = workspace / "logs" / "check_transcripts.log"

    # Load inputs
    catalog_rows = _read_csv_dicts(catalog_csv) or []
    index_data = _read_json(index_json)
    transcript_files = _list_files(transcripts_dir)
    if transcript_files is None:
        transcript_files = []

    # Compute expectations
    expected_total_catalog = len(catalog_rows)
    expected_present_files_count = len(transcript_files)
    expected_missing_rows = _compute_expected_missing(catalog_rows, transcripts_dir)
    expected_missing_set = set()
    for r in expected_missing_rows:
        expected_missing_set.add(f"{r['InterviewID']} — {r['Interviewee']} — {r['TranscriptFile']}")

    index_listed = _index_listed_map(index_data)
    expected_missing_csv_rows = []
    for r in expected_missing_rows:
        iid = r["InterviewID"]
        expected_missing_csv_rows.append({
            "InterviewID": r["InterviewID"],
            "Interviewee": r["Interviewee"],
            "TranscriptFile": r["TranscriptFile"],
            "index_listed": "yes" if iid in index_listed else "no",
        })

    # Begin scoring
    scores = {
        "missing_transcripts_csv_exists": 0.0,
        "missing_transcripts_csv_header_correct": 0.0,
        "missing_transcripts_csv_rows_correct_count": 0.0,
        "missing_transcripts_csv_row_values_correct": 0.0,
        "summary_md_exists": 0.0,
        "summary_counts_correct_total_catalog": 0.0,
        "summary_counts_correct_present": 0.0,
        "summary_counts_correct_missing": 0.0,
        "summary_bullet_list_present_and_correct": 0.0,
        "summary_includes_error_path_and_cause": 0.0,
        "logs_check_transcripts_log_exists": 0.0,
        "logs_log_captures_stdout_and_stderr": 0.0,
        "email_exists": 0.0,
        "email_addresses_maya": 0.0,
        "email_mentions_missing_transcripts": 0.0,
        "email_mentions_script_failure_and_path": 0.0,
        "email_proposes_next_steps": 0.0,
        "email_summarizes_counts": 0.0,
    }

    # Check output/missing_transcripts.csv
    if output_missing_csv.exists():
        scores["missing_transcripts_csv_exists"] = 1.0
        out_rows = _read_csv_dicts(output_missing_csv)
        if out_rows is not None:
            # Validate headers
            try:
                with output_missing_csv.open(newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    header = next(reader)
                expected_header = ["InterviewID", "Interviewee", "TranscriptFile", "index_listed"]
                if header == expected_header:
                    scores["missing_transcripts_csv_header_correct"] = 1.0
            except Exception:
                pass

            # Validate row count
            if out_rows is not None:
                if len(out_rows) == len(expected_missing_csv_rows):
                    scores["missing_transcripts_csv_rows_correct_count"] = 1.0

                # Validate content
                try:
                    got_set = set()
                    for r in out_rows:
                        got_set.add((
                            r.get("InterviewID", ""),
                            r.get("Interviewee", ""),
                            r.get("TranscriptFile", ""),
                            r.get("index_listed", "").lower()
                        ))
                    exp_set = set()
                    for r in expected_missing_csv_rows:
                        exp_set.add((
                            r["InterviewID"],
                            r["Interviewee"],
                            r["TranscriptFile"],
                            r["index_listed"]
                        ))
                    if got_set == exp_set:
                        scores["missing_transcripts_csv_row_values_correct"] = 1.0
                except Exception:
                    pass

    # Check output/summary.md
    summary_text = _read_text(output_summary_md)
    if summary_text is not None:
        scores["summary_md_exists"] = 1.0
        counts = _parse_summary_counts(summary_text)
        if counts.get("total_catalog") == expected_total_catalog:
            scores["summary_counts_correct_total_catalog"] = 1.0
        if counts.get("present_files") == expected_present_files_count:
            scores["summary_counts_correct_present"] = 1.0
        if counts.get("missing_transcripts") == len(expected_missing_rows):
            scores["summary_counts_correct_missing"] = 1.0

        # Bullet list correctness
        bullets = _extract_bullet_missing_items(summary_text)
        if bullets:
            if set(bullets) == expected_missing_set:
                scores["summary_bullet_list_present_and_correct"] = 1.0

        # Error path and cause
        error_path_present = "input/transcript" in summary_text
        likely_cause = _contains_likely_cause(summary_text)
        if error_path_present and likely_cause:
            scores["summary_includes_error_path_and_cause"] = 1.0

    # Check logs/check_transcripts.log
    log_text = _read_text(logs_check_log)
    if log_text is not None:
        scores["logs_check_transcripts_log_exists"] = 1.0
        # Must include stdout lines and stderr traceback indicating FileNotFoundError and path
        has_loading = "Loading catalog: input/catalog/oral_histories.csv" in log_text
        has_catalog_count = "Catalog entries: " in log_text
        has_checking_dir = "Checking transcripts directory: input/transcript" in log_text
        has_error = ("FileNotFoundError" in log_text) and ("input/transcript" in log_text)
        if has_loading and has_catalog_count and has_checking_dir and has_error:
            scores["logs_log_captures_stdout_and_stderr"] = 1.0

    # Check output/email_to_curator.txt
    email_text = _read_text(output_email_txt)
    if email_text is not None:
        scores["email_exists"] = 1.0
        low = email_text.lower()

        # Addressed to Maya (salutation)
        if re.search(r"^(hi|dear)\s+maya\b", email_text, flags=re.IGNORECASE | re.MULTILINE):
            scores["email_addresses_maya"] = 1.0

        # Mentions missing transcript(s)
        mentions_missing = ("oh003" in low) and ("oh003_lucillegray.txt" in low) and ("missing" in low)
        if mentions_missing:
            scores["email_mentions_missing_transcripts"] = 1.0

        # Mentions script failure and the path it attempted to use
        if ("input/transcript" in email_text) and (("error" in low) or ("failed" in low) or ("failure" in low) or ("traceback" in low) or ("filenotfounderror" in low)):
            scores["email_mentions_script_failure_and_path"] = 1.0

        # Proposes concrete next steps (digitization + correct the path/directory)
        next_steps = ("digitization" in low) and ("correct" in low) and (("path" in low) or ("directory" in low))
        if next_steps:
            scores["email_proposes_next_steps"] = 1.0

        # Summarizes audit results with counts (total, present, missing)
        has_total = (("catalog" in low) and re.search(r"\b" + str(expected_total_catalog) + r"\b", email_text) is not None)
        has_present = ((("present" in low) or ("found" in low) or ("available" in low)) and re.search(r"\b" + str(expected_present_files_count) + r"\b", email_text) is not None)
        has_missing = (("missing" in low) and re.search(r"\b" + str(len(expected_missing_rows)) + r"\b", email_text) is not None)
        if has_total and has_present and has_missing:
            scores["email_summarizes_counts"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    # Preserve insertion order of keys for comparison by downstream harness
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()