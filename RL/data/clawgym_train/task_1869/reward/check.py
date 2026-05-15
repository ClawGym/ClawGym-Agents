import json
import sys
import subprocess
import re
from pathlib import Path
from typing import Tuple, Optional, Any, Dict, List
from datetime import datetime


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    try:
        txt = _read_text(path)
        if txt is None:
            return None
        return json.loads(txt)
    except Exception:
        return None


def _run_cli(workspace: Path, args: List[str], timeout: int = 20) -> Tuple[int, str, str]:
    """
    Run the candidate CLI: python app/cli.py <args...>
    Returns (returncode, stdout, stderr) with stdout/stderr decoded as utf-8 text.
    """
    cli_path = workspace / "app" / "cli.py"
    if not cli_path.exists():
        return (127, "", f"Error: missing CLI at {cli_path}")
    cmd = [sys.executable, str(cli_path)] + args
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        return (proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        return (124, "", "Error: command timed out")
    except Exception as e:
        return (1, "", f"Error: failed to run CLI ({e})")


def _parse_species_totals(csv_path: Path) -> Optional[Dict[str, int]]:
    try:
        import csv
    except Exception:
        return None
    if not csv_path.exists():
        return None
    try:
        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            totals: Dict[str, int] = {}
            for row in reader:
                region = (row.get("region") or "").strip()
                obs_raw = (row.get("observations") or "").strip()
                try:
                    obs = int(obs_raw)
                except Exception:
                    obs = 0
                totals[region] = totals.get(region, 0) + obs
        if not totals:
            return None
        return totals
    except Exception:
        return None


def _is_single_nonempty_line(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    return len(lines) == 1


def _startswith_error_line(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip() != ""]
    if len(lines) != 1:
        return False
    return lines[0].lstrip().startswith("Error:")


def _contains_all_regions_and_totals(stdout: str, totals: Dict[str, int]) -> bool:
    # Verify each region name appears and its numeric total appears.
    for region, total in totals.items():
        if region not in stdout:
            return False
        # Require the number to appear as a standalone integer token in the output.
        num_pattern = r"\b" + re.escape(str(total)) + r"\b"
        if re.search(num_pattern, stdout) is None:
            return False
    return True


def _summary_format_not_dict_like(stdout: str) -> bool:
    """
    Ensure the summary line is not a raw Python dict repr from the original code.
    Reject if it contains braces, single quotes, or 'summary:' prefix.
    Also require that it includes at least one digit and at least one letter.
    """
    s = stdout.strip()
    if any(tok in s for tok in ["{", "}", "'", "summary:"]):
        return False
    has_digit = any(ch.isdigit() for ch in s)
    has_alpha = any(ch.isalpha() for ch in s)
    return has_digit and has_alpha


def _validate_iso8601(s: str) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    try:
        datetime.fromisoformat(s)
        return True
    except Exception:
        pass
    try:
        if s.endswith("Z"):
            datetime.fromisoformat(s[:-1] + "+00:00")
            return True
    except Exception:
        pass
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "summarize_with_sample_exit_and_output": 0.0,
        "summarize_missing_file_error_handling": 0.0,
        "help_lists_subcommands": 0.0,
        "argparse_usage_in_code": 0.0,
        "old_tone_phrases_removed": 0.0,
        "messages_before_after_mapping_quality": 0.0,
        "run_logs_required_sections": 0.0,
        "guidelines_html_artifact": 0.0,
        "guidelines_json_artifact": 0.0,
        "error_analysis_content_quality": 0.0,
    }

    # Paths
    cli_path = workspace / "app" / "cli.py"
    species_csv = workspace / "input" / "species_sample.csv"
    output_dir = workspace / "output"
    guidelines_html = output_dir / "guidelines_raw.html"
    guidelines_json = output_dir / "guidelines.json"
    messages_map = output_dir / "messages_before_after.json"
    run_logs = output_dir / "run_logs.txt"
    error_analysis = output_dir / "error_analysis.md"

    cli_present = cli_path.exists()

    # 1) summarize_with_sample_exit_and_output
    # Require improved, user-friendly single-line format (not raw dict repr).
    totals = _parse_species_totals(species_csv)
    if totals and cli_present:
        rc, out, err = _run_cli(workspace, ["summarize", str(species_csv)])
        if rc == 0 and _is_single_nonempty_line(out) and (err.strip() == "") and _contains_all_regions_and_totals(out, totals) and _summary_format_not_dict_like(out):
            scores["summarize_with_sample_exit_and_output"] = 1.0

    # 2) summarize_missing_file_error_handling
    if cli_present:
        rc2, out2, err2 = _run_cli(workspace, ["summarize", "input/missing.csv"])
        # Expect non-zero rc, stderr with single concise line beginning with "Error:", stdout empty/whitespace
        if rc2 != 0 and (out2.strip() == "") and _startswith_error_line(err2):
            scores["summarize_missing_file_error_handling"] = 1.0

    # 3) help_lists_subcommands
    if cli_present:
        rc3, out3, err3 = _run_cli(workspace, ["--help"])
        help_text = out3 if rc3 == 0 else (out3 + "\n" + err3)
        if ("summarize" in help_text) and ("fetch-guidelines" in help_text):
            scores["help_lists_subcommands"] = 1.0

    # 4) argparse_usage_in_code
    cli_text = _read_text(cli_path) or ""
    if cli_present and ("argparse" in cli_text):
        scores["argparse_usage_in_code"] = 1.0

    # 5) old_tone_phrases_removed
    # Ensure rough/irreverent phrases from original code are not present in refactored code.
    if cli_present and cli_text:
        bad_phrases = [
            "no rows lol",
            "whatever",
            "bad help",
            "google it yourself",
            "No command given. bye.",
        ]
        if all(bp not in cli_text for bp in bad_phrases):
            scores["old_tone_phrases_removed"] = 1.0

    # 6) messages_before_after_mapping_quality
    mbaj = _load_json(messages_map)
    if isinstance(mbaj, list) and len(mbaj) >= 1:
        # Each item should have old, new, context
        valid_items = 0
        for item in mbaj:
            if isinstance(item, dict) and all(k in item for k in ("old", "new", "context")):
                if isinstance(item["old"], str) and isinstance(item["new"], str) and isinstance(item["context"], str):
                    valid_items += 1
        # Check presence of expected old-message substrings in mapping
        expected_old_substrings = [
            "usage: summarize FILE",
            "no rows lol",
            "bad help",
            "not implemented; google it yourself",
            "No command given. bye.",
            "Unknown cmd",
        ]
        found = 0
        old_fields = [str(i.get("old", "")) for i in mbaj if isinstance(i, dict)]
        for sub in expected_old_substrings:
            if any(sub in of for of in old_fields):
                found += 1
        structural_score = 1.0 if valid_items == len(mbaj) and valid_items >= 3 else 0.0
        coverage_score = found / float(len(expected_old_substrings)) if expected_old_substrings else 0.0
        scores["messages_before_after_mapping_quality"] = (structural_score + coverage_score) / 2.0

    # 7) run_logs_required_sections
    rl_text = _read_text(run_logs) or ""
    required_lines = [
        "Before: python app/cli.py summarize (no args)",
        "Before: python app/cli.py summarize input/missing.csv",
        "After: python app/cli.py summarize input/species_sample.csv",
        "After: python app/cli.py summarize input/missing.csv",
        "After: python app/cli.py fetch-guidelines",
    ]
    if rl_text and all(line in rl_text for line in required_lines):
        scores["run_logs_required_sections"] = 1.0

    # 8) guidelines_html_artifact
    html_bytes = _read_bytes(guidelines_html)
    if html_bytes is not None:
        size_ok = len(html_bytes) > 50  # substantive
        try:
            text = html_bytes.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        has_html = ("<html" in text.lower()) or ("<!doctype" in text.lower()) or ("<title" in text.lower())
        if size_ok and has_html:
            scores["guidelines_html_artifact"] = 1.0

    # 9) guidelines_json_artifact
    gj = _load_json(guidelines_json)
    if isinstance(gj, dict):
        required_keys = ["source_domain", "target_page_description", "retrieved_at_iso", "page_title", "h2_headings", "html_file"]
        has_keys = all(k in gj for k in required_keys)
        types_ok = (
            isinstance(gj.get("source_domain"), str)
            and isinstance(gj.get("target_page_description"), str)
            and isinstance(gj.get("retrieved_at_iso"), str)
            and isinstance(gj.get("page_title"), str)
            and isinstance(gj.get("h2_headings"), list)
            and isinstance(gj.get("html_file"), str)
        )
        headings_ok = types_ok and all(isinstance(x, str) for x in gj.get("h2_headings", []))
        iso_ok = _validate_iso8601(gj.get("retrieved_at_iso", ""))
        sd = (gj.get("source_domain") or "")
        domain_ok = (sd.endswith("ewca.gov.et")) or ("iucnredlist.org" in sd)
        # html_file must exactly be output/guidelines_raw.html as required
        html_file_path = gj.get("html_file")
        html_path_ok = isinstance(html_file_path, str) and (html_file_path == "output/guidelines_raw.html")
        html_exists_ok = guidelines_html.exists() and guidelines_html.stat().st_size > 0
        if has_keys and types_ok and headings_ok and iso_ok and domain_ok and html_path_ok and html_exists_ok:
            scores["guidelines_json_artifact"] = 1.0

    # 10) error_analysis_content_quality
    ea_text = _read_text(error_analysis) or ""
    has_cmd1 = "python app/cli.py summarize (no args)" in ea_text
    has_cmd2 = "python app/cli.py summarize input/missing.csv" in ea_text
    mentions_root = ("root cause" in ea_text.lower()) or ("cause:" in ea_text.lower())
    mentions_changes = ("change" in ea_text.lower()) or ("fix" in ea_text.lower()) or ("address" in ea_text.lower()) or ("resolved" in ea_text.lower())
    if has_cmd1 and has_cmd2 and mentions_root and mentions_changes:
        scores["error_analysis_content_quality"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result))


if __name__ == "__main__":
    main()