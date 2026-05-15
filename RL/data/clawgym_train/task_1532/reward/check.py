import json
import sys
import subprocess
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def _read_text_safe(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_bytes_safe(p: Path):
    try:
        return p.read_bytes()
    except Exception:
        return None


def _load_json_safe(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_http_history(p: Path):
    """
    Returns dict mapping endpoint path -> set of param names for GET requests to example.test or its subdomains.
    """
    text = _read_text_safe(p)
    if text is None:
        return None
    endpoints = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("GET "):
            continue
        rest = line[4:].strip()
        path = ""
        query = ""
        if rest.startswith("http://") or rest.startswith("https://"):
            parsed = urlparse(rest)
            host = (parsed.hostname or "").lower()
            if not (host == "example.test" or host.endswith(".example.test")):
                continue
            path = parsed.path or "/"
            query = parsed.query or ""
        else:
            if "?" in rest:
                path, query = rest.split("?", 1)
            else:
                path, query = rest, ""
        params = set(parse_qs(query, keep_blank_values=True).keys())
        if path:
            if path not in endpoints:
                endpoints[path] = set()
            endpoints[path].update(params)
    # Only keep endpoints that have at least one parameter
    return {k: v for k, v in endpoints.items() if v}


def _parse_payloads(p: Path):
    text = _read_text_safe(p)
    if text is None:
        return None
    payloads = []
    for line in text.splitlines():
        s = line.rstrip("\n")
        if s.strip() == "":
            continue
        payloads.append(s)
    return payloads


def _run_script(workspace: Path):
    """
    Run the student's script. Returns (returncode, stdout, stderr).
    """
    script = workspace / "tools" / "param_fuzzer.py"
    if not script.exists():
        return None, "", "script_missing"
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(workspace),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as e:
        return None, "", f"exception: {e}"


def _read_run_log_lines(p: Path):
    txt = _read_text_safe(p)
    if txt is None:
        return None
    return txt.splitlines()


def _count_occurrences(lines, substr):
    return sum(1 for ln in lines if substr in ln)


def _extract_sql_pairs_and_payloads(lines):
    """
    Extract set of (path, param) and list of payloads from SQL error lines.
    """
    sql_re = re.compile(r"SQL syntax error near '(?P<payload>.*)' on (?P<path>/\S*) param (?P<param>[A-Za-z0-9_\-]+)")
    pairs = set()
    payloads = []
    for ln in lines:
        m = sql_re.search(ln)
        if m:
            pairs.add((m.group("path"), m.group("param")))
            payloads.append(m.group("payload"))
    return pairs, payloads


def _extract_traceback_pairs(lines):
    """
    Extract set of (path, param) from Traceback lines.
    """
    tb_re = re.compile(r"Traceback \(most recent call last\): ValueError\('bad html in param (?P<param>[^)]+)'\) on (?P<path>/\S*)")
    pairs = set()
    for ln in lines:
        m = tb_re.search(ln)
        if m:
            pairs.add((m.group("path"), m.group("param")))
    return pairs


def _find_section_lines(md_text: str, marker: str):
    """
    Returns (start_index, end_index, lines[start:end]) where start is the line index after the marker line,
    and end is the index of the first blank line after start. If marker not found, returns (None, None, []).
    """
    lines = md_text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if marker in ln:
            start = i + 1
            break
    if start is None:
        return None, None, []
    end = start
    while end < len(lines) and lines[end].strip() != "":
        end += 1
    return start, end, lines[start:end]


def _parse_markdown_table(table_lines):
    """
    Parse a simple pipe-delimited markdown table into header list and rows (list of lists).
    Skips alignment rows consisting of dashes.
    """
    rows = []
    for ln in table_lines:
        s = ln.strip()
        if not s.startswith("|"):
            continue
        parts = [c.strip() for c in s.strip("|").split("|")]
        if all(set(c) <= set("-: ") and c != "" for c in parts):
            continue
        rows.append(parts)
    if not rows:
        return None, []
    header = rows[0]
    data_rows = rows[1:] if len(rows) > 1 else []
    return header, data_rows


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "script_exists": 0.0,
        "run_invocation_success": 0.0,
        "run_log_sql_count": 0.0,
        "run_log_500_count": 0.0,
        "run_log_traceback_count": 0.0,
        "run_log_200_count": 0.0,
        "run_log_sql_coverage_by_param": 0.0,
        "run_log_traceback_coverage_by_param": 0.0,
        "findings_json_parseable": 0.0,
        "findings_coverage": 0.0,
        "findings_evidence_lines_present": 0.0,
        "findings_sorted_lexicographically": 0.0,
        "report_summary_updated_with_counts": 0.0,
        "report_findings_table_matches_json": 0.0,
        "deterministic_rerun_outputs_identical": 0.0,
        "uses_subprocess_and_not_imports_mock_handler": 0.0,
    }

    script_path = workspace / "tools" / "param_fuzzer.py"
    if script_path.exists() and script_path.is_file():
        scores["script_exists"] = 1.0

    # Determine expected (endpoint, param) pairs and payloads from inputs to compute expected behavior.
    http_history_path = workspace / "input" / "http_history.txt"
    payloads_path = workspace / "input" / "payloads.txt"
    endpoints = _parse_http_history(http_history_path) or {}
    payloads = _parse_payloads(payloads_path) or []
    expected_pairs = set()
    for ep, params in endpoints.items():
        for param in params:
            expected_pairs.add((ep, param))
    total_pairs_count = len(expected_pairs)

    # Classify payloads
    payload_classes = {}
    for pl in payloads:
        if "' OR '1'='1" in pl or "UNION SELECT" in pl:
            payload_classes[pl] = "SQL"
        elif "<script" in pl:
            payload_classes[pl] = "SCRIPT"
        elif "${7*7}" in pl:
            payload_classes[pl] = "500"
        else:
            payload_classes[pl] = "OK"

    # Run the script
    rc, so, se = _run_script(workspace)
    run_log_path = workspace / "output" / "run.log"
    findings_path = workspace / "output" / "findings.json"
    if rc == 0 and run_log_path.exists() and findings_path.exists():
        scores["run_invocation_success"] = 1.0

    # Analyze run.log
    lines = _read_run_log_lines(run_log_path) or []
    if lines and total_pairs_count > 0 and payloads:
        # Expected counts based on payload classification
        expected_sql = total_pairs_count * sum(1 for c in payload_classes.values() if c == "SQL")
        expected_500 = total_pairs_count * (sum(1 for c in payload_classes.values() if c == "SCRIPT") + sum(1 for c in payload_classes.values() if c == "500"))
        expected_traceback = total_pairs_count * sum(1 for c in payload_classes.values() if c == "SCRIPT")
        expected_ok = total_pairs_count * sum(1 for c in payload_classes.values() if c == "OK")

        sql_count = _count_occurrences(lines, "SQL syntax error")
        five_count = _count_occurrences(lines, "500 Internal Server Error")
        tb_count = _count_occurrences(lines, "Traceback")
        ok_count = _count_occurrences(lines, "200 OK")

        if sql_count == expected_sql:
            scores["run_log_sql_count"] = 1.0
        if five_count == expected_500:
            scores["run_log_500_count"] = 1.0
        if tb_count == expected_traceback:
            scores["run_log_traceback_count"] = 1.0
        if ok_count == expected_ok:
            scores["run_log_200_count"] = 1.0

        sql_pairs, _ = _extract_sql_pairs_and_payloads(lines)
        tb_pairs = _extract_traceback_pairs(lines)
        if expected_pairs and sql_pairs == expected_pairs:
            scores["run_log_sql_coverage_by_param"] = 1.0
        if expected_pairs and tb_pairs == expected_pairs:
            scores["run_log_traceback_coverage_by_param"] = 1.0

    # Validate findings.json
    findings = _load_json_safe(findings_path)
    if isinstance(findings, list) and all(isinstance(x, dict) for x in findings):
        required_fields_ok = True
        allowed_signals = {"500", "SQL", "Traceback"}
        for obj in findings:
            if not all(k in obj for k in ["endpoint", "param", "payload", "signal", "evidence"]):
                required_fields_ok = False
                break
            if not isinstance(obj["endpoint"], str) or not obj["endpoint"].startswith("/"):
                required_fields_ok = False
                break
            if not isinstance(obj["param"], str):
                required_fields_ok = False
                break
            if not isinstance(obj["payload"], str):
                required_fields_ok = False
                break
            if obj["signal"] not in allowed_signals:
                required_fields_ok = False
                break
            if not isinstance(obj["evidence"], str) or obj["evidence"] == "":
                required_fields_ok = False
                break
        if required_fields_ok:
            scores["findings_json_parseable"] = 1.0

        # Evidence lines present in run.log
        if lines:
            evid_set = set(lines)
            ev_ok = True
            for obj in findings:
                if obj["evidence"] not in evid_set:
                    ev_ok = False
                    break
            if ev_ok:
                scores["findings_evidence_lines_present"] = 1.0

        # Coverage check: for each (endpoint,param) and each payload, ensure appropriate signals captured
        if expected_pairs and payloads:
            by_key = {}
            for obj in findings:
                key = (obj.get("endpoint", ""), obj.get("param", ""), obj.get("payload", ""))
                by_key.setdefault(key, set()).add(obj.get("signal"))

            coverage_ok = True
            for ep, param in expected_pairs:
                for pl in payloads:
                    cls = payload_classes.get(pl, "OK")
                    key = (ep, param, pl)
                    signals = by_key.get(key, set())
                    if cls == "SQL":
                        if "SQL" not in signals:
                            coverage_ok = False
                            break
                    elif cls == "SCRIPT":
                        # Expect both Traceback and 500 since mock emits both
                        if not ("Traceback" in signals and "500" in signals):
                            coverage_ok = False
                            break
                    elif cls == "500":
                        if "500" not in signals:
                            coverage_ok = False
                            break
                    elif cls == "OK":
                        if signals:
                            coverage_ok = False
                            break
                if not coverage_ok:
                    break
            if coverage_ok:
                scores["findings_coverage"] = 1.0

        # Check sorted deterministically by endpoint, param, payload
        if isinstance(findings, list) and len(findings) > 0:
            sorted_ok = True
            prev = None
            for obj in findings:
                cur = (obj.get("endpoint", ""), obj.get("param", ""), obj.get("payload", ""))
                if prev is not None and prev > cur:
                    sorted_ok = False
                    break
                prev = cur
            if sorted_ok:
                scores["findings_sorted_lexicographically"] = 1.0

    # Validate REPORT.md updates
    report_path = workspace / "docs" / "REPORT.md"
    report_text = _read_text_safe(report_path)
    if report_text and isinstance(findings, list):
        total_findings = len(findings)
        endpoints_set = set(obj["endpoint"] for obj in findings)

        # Summary section updated without TODO and mentions counts
        s_start, s_end, s_lines = _find_section_lines(report_text, "<!-- SUMMARY_TODO -->")
        if s_start is not None and s_lines is not None and s_lines != []:
            summary_content = "\n".join(s_lines)
            if "TODO:" not in summary_content:
                has_total = str(total_findings) in summary_content
                has_endpoints = str(len(endpoints_set)) in summary_content
                if has_total and has_endpoints:
                    scores["report_summary_updated_with_counts"] = 1.0

        # Findings section table matches JSON and section is not TODO
        f_start, f_end, f_lines = _find_section_lines(report_text, "<!-- FINDINGS_TODO -->")
        if f_start is not None and f_lines is not None and len(f_lines) > 0:
            section_text = "\n".join(f_lines)
            if "TODO:" not in section_text:
                header, data_rows = _parse_markdown_table(f_lines)
                if header is not None:
                    expected_header = ["endpoint", "param", "payload", "signal"]
                    header_norm = [h.strip().lower() for h in header]
                    header_ok = header_norm == expected_header
                    table_entries = set()
                    for row in data_rows:
                        if len(row) < 4:
                            continue
                        e, p, pl, si = row[0], row[1], row[2], row[3]
                        table_entries.add((e, p, pl, si))
                    json_entries = set()
                    for obj in findings:
                        json_entries.add((obj.get("endpoint", ""), obj.get("param", ""), obj.get("payload", ""), obj.get("signal", "")))
                    if header_ok and json_entries == table_entries:
                        scores["report_findings_table_matches_json"] = 1.0

    # Determinism: rerun and compare bytes if script exists
    try:
        findings_bytes_1 = _read_bytes_safe(findings_path) or b""
        runlog_bytes_1 = _read_bytes_safe(run_log_path) or b""
        rc2, so2, se2 = _run_script(workspace)
        findings_bytes_2 = _read_bytes_safe(findings_path) or b""
        runlog_bytes_2 = _read_bytes_safe(run_log_path) or b""
        if rc2 == 0 and findings_bytes_1 == findings_bytes_2 and runlog_bytes_1 == runlog_bytes_2:
            scores["deterministic_rerun_outputs_identical"] = 1.0
    except Exception:
        pass

    # Code hygiene: uses subprocess and does not import mock_handler directly
    code_text = _read_text_safe(script_path) or ""
    if code_text:
        uses_subprocess = "subprocess" in code_text
        imports_mock = ("import mock_handler" in code_text) or ("from input import mock_handler" in code_text) or ("from mock_handler" in code_text)
        if uses_subprocess and not imports_mock:
            scores["uses_subprocess_and_not_imports_mock_handler"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()