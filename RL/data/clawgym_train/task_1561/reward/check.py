import json
import sys
import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple, Any, Dict, List


def read_text_safe(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def load_json_safe(path: Path) -> Optional[dict]:
    try:
        text = read_text_safe(path)
        if text is None:
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_simple_diagnostics_yaml(path: Path) -> Tuple[Optional[dict], bool]:
    """
    Minimal YAML parser for the specific structure of config/diagnostics.yaml:
    - tagline: "..."
    - thresholds:
        disk_warn_gb: 5
        cpu_load_warn: 1.5
    - distractors:
        - discord
        - steam
        - spotify
        - twitter
        - reddit
    Returns (data, ok)
    """
    text = read_text_safe(path)
    if text is None:
        return None, False

    lines = text.splitlines()
    result: Dict[str, Any] = {}
    thresholds: Dict[str, Any] = {}
    distractors: List[str] = []

    in_thresholds = False
    in_distractors = False
    thresholds_indent = None
    distractors_indent = None

    def parse_value(val: str) -> Any:
        val = val.strip()
        # strip surrounding quotes if any
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
            return val
        # try int, then float
        try:
            if re.fullmatch(r"[-+]?\d+", val):
                return int(val)
            if re.fullmatch(r"[-+]?\d+\.\d*", val) or re.fullmatch(r"[-+]?\d*\.\d+", val):
                return float(val)
        except Exception:
            pass
        return val

    for i, line in enumerate(lines):
        raw = line
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        # End sections on dedent
        if in_thresholds and thresholds_indent is not None and indent <= thresholds_indent and not stripped.startswith('- '):
            in_thresholds = False
            thresholds_indent = None
        if in_distractors and distractors_indent is not None and indent <= distractors_indent and not stripped.startswith('- '):
            in_distractors = False
            distractors_indent = None

        # Top-level keys
        if indent == 0 and stripped.startswith("tagline:"):
            _, _, val = stripped.partition(":")
            result["tagline"] = parse_value(val)
            continue
        if indent == 0 and stripped.startswith("thresholds:"):
            in_thresholds = True
            thresholds_indent = indent
            if "thresholds" not in result:
                result["thresholds"] = {}
            continue
        if indent == 0 and stripped.startswith("distractors:"):
            in_distractors = True
            distractors_indent = indent
            if "distractors" not in result:
                result["distractors"] = []
            continue

        if in_thresholds:
            # expect "  key: value"
            m = re.match(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$", raw)
            if m:
                key = m.group(1).strip()
                val = parse_value(m.group(2))
                thresholds[key] = val
                result["thresholds"] = thresholds
            continue

        if in_distractors:
            # expect "  - item"
            m = re.match(r"^\s*-\s*(.+?)\s*$", raw)
            if m:
                val = m.group(1).strip()
                # strip quotes
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                distractors.append(val)
                result["distractors"] = distractors
            continue

    # If thresholds/distractors were not captured, ensure keys are not missing
    if "thresholds" not in result:
        result["thresholds"] = thresholds
    if "distractors" not in result:
        result["distractors"] = distractors

    ok = True
    # Basic validation: ensure keys exist
    if "tagline" not in result or not isinstance(result.get("thresholds"), dict) or not isinstance(result.get("distractors"), list):
        ok = False
    return result, ok


def compute_sha256_hex(path: Path) -> Optional[str]:
    try:
        sha = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        return sha.hexdigest()
    except Exception:
        return None


def is_hex_string(s: str, length: int) -> bool:
    return isinstance(s, str) and len(s) == length and re.fullmatch(r"[0-9a-fA-F]+", s) is not None


def contains_ci(text: str, sub: str) -> bool:
    return sub.lower() in text.lower()


def extract_floats(text: str) -> List[float]:
    nums: List[float] = []
    for m in re.finditer(r"[-+]?\d+(?:\.\d+)?", text):
        try:
            nums.append(float(m.group(0)))
        except Exception:
            continue
    return nums


def float_close_in_list(target: float, candidates: List[float], rel_tol: float = 0.03, abs_tol: float = 0.05) -> bool:
    for c in candidates:
        if abs(c - target) <= max(abs_tol, rel_tol * max(abs(target), 1.0)):
            return True
    return False


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "config_tagline_updated": 0.0,
        "config_thresholds_updated": 0.0,
        "config_distractors_appended": 0.0,
        "script_implementation_indicators": 0.0,
        "book_file_valid": 0.0,
        "json_report_core_valid": 0.0,
        "json_io_test_valid": 0.0,
        "json_top_processes_valid": 0.0,
        "cross_config_json_match": 0.0,
        "md_report_sections_and_consistency": 0.0,
        "io_sha256_matches_file": 0.0,
        "io_bytes_read_multiple_of_file_size": 0.0,
        "email_subject_and_mentions": 0.0,
        "email_warnings_bullets_match": 0.0,
        "warnings_logic_consistency": 0.0,
    }

    # Paths
    config_path = workspace / "config" / "diagnostics.yaml"
    script_path = workspace / "tools" / "session_diagnostics.py"
    book_path = workspace / "external" / "king_in_yellow.txt"
    json_path = workspace / "output" / "system_report.json"
    md_path = workspace / "output" / "system_report.md"
    email_path = workspace / "output" / "email_draft_to_beta_readers.txt"

    # Load YAML config
    yaml_data, yaml_ok = parse_simple_diagnostics_yaml(config_path)
    if yaml_ok and isinstance(yaml_data, dict):
        tagline_target = "A midnight appraisal of my writing lair."
        if yaml_data.get("tagline") == tagline_target:
            scores["config_tagline_updated"] = 1.0

        thresholds = yaml_data.get("thresholds", {})
        try:
            dgb = thresholds.get("disk_warn_gb", None)
            clw = thresholds.get("cpu_load_warn", None)
            if dgb is not None and clw is not None:
                if float(dgb) == 5.0 and float(clw) == 1.5:
                    scores["config_thresholds_updated"] = 1.0
        except Exception:
            pass

        distractors = yaml_data.get("distractors", [])
        # Must contain existing entries and appended twitter, reddit as last two in order
        if isinstance(distractors, list) and len(distractors) >= 5:
            dl = [str(x).strip() for x in distractors]
            has_existing = all(x in dl for x in ["discord", "steam", "spotify"])
            ends_correct = dl[-2:] == ["twitter", "reddit"]
            if has_existing and ends_correct:
                scores["config_distractors_appended"] = 1.0

    # Check script indicators
    script_text = read_text_safe(script_path)
    if script_text is not None:
        markers = [
            "gutenberg.org",
            "external/king_in_yellow.txt",
            "output/system_report.json",
            "output/system_report.md",
            "output/email_draft_to_beta_readers.txt",
            "config/diagnostics.yaml",
        ]
        count_markers = sum(1 for m in markers if m in script_text)
        if "TODO: Implement session diagnostics" not in script_text and count_markers >= 4:
            scores["script_implementation_indicators"] = 1.0

    # Validate downloaded book file
    book_ok = False
    if book_path.exists() and book_path.is_file():
        try:
            size = book_path.stat().st_size
        except Exception:
            size = 0
        content = read_text_safe(book_path) or ""
        if size >= 100 * 1024 and contains_ci(content, "Project Gutenberg") and contains_ci(content, "The King in Yellow"):
            book_ok = True
            scores["book_file_valid"] = 1.0

    # Load JSON report
    report = load_json_safe(json_path)
    json_ok = isinstance(report, dict)
    # JSON core validation
    if json_ok:
        core_ok = True
        # version
        if "version" not in report or not isinstance(report.get("version"), str) or not report.get("version"):
            core_ok = False
        # source_label exact
        if report.get("source_label") != "Project Gutenberg - The King in Yellow (plain text UTF-8)":
            core_ok = False
        # config presence
        cfg = report.get("config")
        if not isinstance(cfg, dict):
            core_ok = False
        # metrics
        metrics = report.get("metrics")
        if not isinstance(metrics, dict):
            core_ok = False
        else:
            cpu_count = metrics.get("cpu_count")
            disk_free_gb = metrics.get("disk_free_gb")
            load_avg_1m = metrics.get("load_avg_1m", None) if metrics is not None else None
            try:
                if not (isinstance(cpu_count, int) and cpu_count >= 1):
                    core_ok = False
                # Allow int or float for disk_free_gb
                if not (isinstance(disk_free_gb, (int, float)) and disk_free_gb >= 0):
                    core_ok = False
                if load_avg_1m is not None and not isinstance(load_avg_1m, (int, float)):
                    core_ok = False
            except Exception:
                core_ok = False
        # distractors_found
        df = report.get("distractors_found")
        if not isinstance(df, list):
            core_ok = False
        # warnings
        w = report.get("warnings")
        if not isinstance(w, list):
            core_ok = False

        if core_ok:
            scores["json_report_core_valid"] = 1.0

    # JSON io_test validation
    if json_ok:
        io = report.get("io_test", {})
        io_ok = isinstance(io, dict)
        if io_ok:
            path_val = io.get("path")
            bytes_read = io.get("bytes_read")
            read_time_s = io.get("read_time_s")
            throughput_mb_s = io.get("throughput_mb_s")
            sha256_hex = io.get("sha256_hex")
            if not (path_val == "external/king_in_yellow.txt"):
                io_ok = False
            if not (isinstance(bytes_read, int) and bytes_read > 0):
                io_ok = False
            if not (isinstance(read_time_s, (int, float)) and read_time_s > 0):
                io_ok = False
            if not (isinstance(throughput_mb_s, (int, float)) and throughput_mb_s > 0):
                io_ok = False
            if not (isinstance(sha256_hex, str) and is_hex_string(sha256_hex, 64)):
                io_ok = False
        if io_ok:
            scores["json_io_test_valid"] = 1.0

    # JSON top_processes validation
    if json_ok:
        tproc = report.get("top_processes")
        tproc_ok = isinstance(tproc, list)
        if tproc_ok:
            if len(tproc) > 5:
                tproc_ok = False
            else:
                for proc in tproc:
                    if not isinstance(proc, dict):
                        tproc_ok = False
                        break
                    if "pid" not in proc or "name" not in proc:
                        tproc_ok = False
                        break
                    # rss_mb optional; if present, should be numeric
                    if "rss_mb" in proc and proc["rss_mb"] is not None and not isinstance(proc["rss_mb"], (int, float)):
                        tproc_ok = False
                        break
        if tproc_ok:
            scores["json_top_processes_valid"] = 1.0

    # Cross-check JSON config matches YAML
    if json_ok and yaml_ok and isinstance(report.get("config"), dict):
        cfg = report.get("config")
        cross_ok = True
        try:
            if cfg.get("tagline") != yaml_data.get("tagline"):
                cross_ok = False
            jt = cfg.get("thresholds", {})
            yt = yaml_data.get("thresholds", {})
            # compare numbers
            if not (float(jt.get("disk_warn_gb", -1)) == float(yt.get("disk_warn_gb", -2)) and float(jt.get("cpu_load_warn", -1)) == float(yt.get("cpu_load_warn", -2))):
                cross_ok = False
            jd = cfg.get("distractors", [])
            yd = yaml_data.get("distractors", [])
            if jd != yd:
                cross_ok = False
        except Exception:
            cross_ok = False
        if cross_ok:
            scores["cross_config_json_match"] = 1.0

    # Markdown report validation and consistency with JSON
    md_text = read_text_safe(md_path)
    if md_text is not None and json_ok:
        md_ok = True
        # Sections
        for section in ["System Snapshot", "I/O Test (The King in Yellow)", "Top Processes", "Warnings"]:
            if section not in md_text:
                md_ok = False
                break
        # Tagline in title/body
        tagline = None
        if yaml_ok:
            tagline = yaml_data.get("tagline")
        elif json_ok:
            tagline = report.get("config", {}).get("tagline")
        if not tagline or tagline not in md_text:
            md_ok = False
        # sha256 and bytes_read presence
        sha256_hex = report.get("io_test", {}).get("sha256_hex")
        bytes_read = report.get("io_test", {}).get("bytes_read")
        if not (isinstance(sha256_hex, str) and sha256_hex in md_text):
            md_ok = False
        if not (isinstance(bytes_read, int) and str(bytes_read) in md_text):
            md_ok = False

        if md_ok:
            scores["md_report_sections_and_consistency"] = 1.0

    # IO sha256 matches file content
    if json_ok and book_ok:
        json_sha = report.get("io_test", {}).get("sha256_hex")
        real_sha = compute_sha256_hex(book_path)
        if isinstance(json_sha, str) and isinstance(real_sha, str) and json_sha.lower() == real_sha.lower():
            scores["io_sha256_matches_file"] = 1.0

    # IO bytes_read is multiple of file size
    if json_ok and book_path.exists() and book_path.is_file():
        try:
            fsz = book_path.stat().st_size
        except Exception:
            fsz = 0
        b_read = report.get("io_test", {}).get("bytes_read")
        if isinstance(fsz, int) and fsz > 0 and isinstance(b_read, int) and b_read >= fsz and b_read % fsz == 0:
            scores["io_bytes_read_multiple_of_file_size"] = 1.0

    # Email checks
    email_text = read_text_safe(email_path)
    if email_text is not None and json_ok:
        # Subject line with "midnight appraisal"
        lines = email_text.splitlines()
        subj_lines = [ln for ln in lines if ln.strip().lower().startswith("subject:")]
        subj_ok = False
        if subj_lines:
            subj = subj_lines[0]
            subj_ok = contains_ci(subj, "midnight appraisal")
        # Body contains tagline, mentions The King in Yellow and Project Gutenberg,
        # and includes disk_free_gb and throughput_mb_s values (within tolerance).
        body = email_text
        body_ok = True
        # Tagline
        tagline = report.get("config", {}).get("tagline")
        if not tagline or not contains_ci(body, tagline):
            body_ok = False
        # Mention book and Project Gutenberg
        if not contains_ci(body, "The King in Yellow") or not contains_ci(body, "Project Gutenberg"):
            body_ok = False
        # Mention disk_free_gb and throughput values approximately
        metrics = report.get("metrics", {})
        dfg = metrics.get("disk_free_gb")
        thr = report.get("io_test", {}).get("throughput_mb_s")
        nums_in_body = extract_floats(body)
        if not (isinstance(dfg, (int, float)) and float_close_in_list(float(dfg), nums_in_body)):
            body_ok = False
        if not (isinstance(thr, (int, float)) and float_close_in_list(float(thr), nums_in_body)):
            body_ok = False

        if subj_ok and body_ok:
            scores["email_subject_and_mentions"] = 1.0

        # Bullets for each warning
        warnings = report.get("warnings", [])
        bullets = [ln for ln in lines if re.match(r"^\s*[-\*\u2022]\s+", ln)]
        bullets_ok = True
        if isinstance(warnings, list):
            if len(bullets) < len(warnings):
                bullets_ok = False
            else:
                # ensure each warning string appears somewhere in email
                for w in warnings:
                    if isinstance(w, str):
                        if not contains_ci(email_text, w):
                            bullets_ok = False
                            break
        else:
            bullets_ok = False

        if bullets_ok:
            scores["email_warnings_bullets_match"] = 1.0

    # Warnings logic consistency
    if json_ok:
        try:
            cfg = report.get("config", {})
            metrics = report.get("metrics", {})
            warnings = report.get("warnings", [])
            distr_found = report.get("distractors_found", [])
            wl_ok = True
            if not isinstance(warnings, list):
                wl_ok = False
            else:
                thresholds = cfg.get("thresholds", {}) if isinstance(cfg, dict) else {}
                d_warn = thresholds.get("disk_warn_gb", None)
                c_warn = thresholds.get("cpu_load_warn", None)
                disk_free = metrics.get("disk_free_gb", None)
                load_avg = metrics.get("load_avg_1m", None) if isinstance(metrics, dict) else None

                # Predicted low disk warning
                if isinstance(d_warn, (int, float)) and isinstance(disk_free, (int, float)):
                    if disk_free < d_warn:
                        # must contain a warning mentioning 'disk'
                        if not any(contains_ci(w, "disk") for w in warnings):
                            wl_ok = False

                # Predicted high load warning
                if isinstance(c_warn, (int, float)) and isinstance(load_avg, (int, float)):
                    if load_avg > c_warn:
                        # must contain a warning mentioning 'load'
                        if not any(contains_ci(w, "load") for w in warnings):
                            wl_ok = False

                # Distractor warnings: for each term in distractors_found, there must be a warning containing that term
                if isinstance(distr_found, list):
                    for term in distr_found:
                        if isinstance(term, str):
                            if not any(contains_ci(w, term) for w in warnings):
                                wl_ok = False
                                break
        except Exception:
            wl_ok = False

        if 'wl_ok' in locals() and wl_ok:
            scores["warnings_logic_consistency"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()