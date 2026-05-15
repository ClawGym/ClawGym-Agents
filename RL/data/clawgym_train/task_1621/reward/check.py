import json
import re
import sys
import hashlib
from datetime import datetime
from pathlib import Path


def _read_text_safe(path: Path):
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _read_bytes_safe(path: Path):
    try:
        if not path.exists():
            return None
        return path.read_bytes()
    except Exception:
        return None


def _load_json_safe(path: Path):
    try:
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _compute_sha256_hex(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _parse_iso8601_flexible(s: str) -> bool:
    if not isinstance(s, str) or not s:
        return False
    val = s
    # Accept Z suffix by converting to +00:00
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        datetime.fromisoformat(val)
        return True
    except Exception:
        pass
    # Fallback loose pattern match (YYYY-MM-DDTHH:MM)
    if re.search(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", s):
        return True
    return False


def _find_job(cfg: dict, name: str):
    for job in (cfg or {}).get("jobs", []):
        if job.get("name") == name:
            return job
    return None


def _extract_function_body(src: str, func_name: str) -> str:
    if not isinstance(src, str):
        return ""
    # Very simple extraction: find "def func_name(" up to next "def " at col 0 or EOF
    pattern = re.compile(rf"(?m)^def\s+{re.escape(func_name)}\s*\(.*", re.DOTALL)
    m = pattern.search(src)
    if not m:
        return ""
    start = m.start()
    tail = src[start:]
    # Find the next def at column 0 after the first newline from current def
    m2 = re.search(r"(?m)^\s*def\s+\w+\s*\(", tail[len("def"):])
    if m2:
        end = len("def") + m2.start()
        return tail[:end]
    else:
        return tail


def _strip_string_literals_and_comments(py_src: str) -> str:
    if not isinstance(py_src, str):
        return ""
    s = py_src
    # Remove triple-quoted strings
    s = re.sub(r"(?s)'''(.*?)'''", "", s)
    s = re.sub(r'(?s)"""(.*?)"""', "", s)
    # Remove single-line string literals (best-effort; will also remove f-strings content)
    s = re.sub(r"(?m)(?<!\\)'.*?(?<!\\)'", "", s)
    s = re.sub(r'(?m)(?<!\\)".*?(?<!\\)"', "", s)
    # Remove comments
    s = re.sub(r"(?m)#.*$", "", s)
    return s


def _log_line_has_required_fields(line: str, source_domain: str) -> bool:
    if not line or not source_domain:
        return False
    if source_domain not in line:
        return False
    # Timestamp like 2024-01-01T09:00
    has_ts = bool(re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", line))
    # Status code 100-599 or N/A
    has_status = bool(re.search(r"\b([1-5]\d{2}|N/A)\b", line))
    # Bytes downloaded indicator
    has_bytes = bool(re.search(r"(\bbytes[_ ]?downloaded\b.*\b\d+\b)|(\b\d+\b\s*bytes)", line.lower()))
    return has_ts and has_status and has_bytes


def _count_action_items(text: str) -> int:
    if not isinstance(text, str):
        return 0
    return sum(1 for _ in re.finditer(r"(?m)^\s*-\s*\[\s*\]\s+.+", text))


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "schedule_contains_fetch_job": 0.0,
        "schedule_keeps_example_job": 0.0,
        "fetch_job_config_defaults_correct": 0.0,
        "run_tasks_implements_fetch_function": 0.0,
        "run_tasks_dispatch_has_fetch_type": 0.0,
        "https_construction_in_code": 0.0,
        "raw_html_file_exists": 0.0,
        "meta_json_fields_valid": 0.0,
        "meta_sha256_matches_raw_html": 0.0,
        "meta_matches_schedule_config": 0.0,
        "fetch_log_entry_present": 0.0,
        "meeting_notes_generated": 0.0,
        "meeting_notes_placeholders_replaced": 0.0,
        "meeting_notes_includes_required_values": 0.0,
        "meeting_notes_has_three_action_items": 0.0,
    }

    # Expected paths
    schedule_path = workspace / "input" / "schedule.json"
    run_tasks_path = workspace / "scripts" / "run_tasks.py"
    raw_html_path = workspace / "workspace" / "data" / "homepage_raw.html"
    meta_json_path = workspace / "workspace" / "data" / "homepage_meta.json"
    fetch_log_path = workspace / "workspace" / "logs" / "fetch.log"
    notes_path = workspace / "workspace" / "notes" / "meeting_notes.md"

    cfg = _load_json_safe(schedule_path)
    fetch_job = None
    example_job_ok = False
    fetch_job_ok = False
    if isinstance(cfg, dict):
        # Check example_echo job remains intact
        example = _find_job(cfg, "example_echo")
        example_job_ok = (
            isinstance(example, dict)
            and example.get("type") == "echo"
            and example.get("schedule") == "daily 08:00"
            and example.get("config", {}).get("message") == "hello from example job"
        )

        # Check fetch_official_homepage job exists and scheduled correctly
        fetch_job = _find_job(cfg, "fetch_official_homepage")
        fetch_job_ok = (
            isinstance(fetch_job, dict)
            and fetch_job.get("type") == "fetch_official_homepage"
            and fetch_job.get("schedule") == "daily 09:00"
        )
        if fetch_job_ok:
            scores["schedule_contains_fetch_job"] = 1.0

        # Award "keeps example" only if the new fetch job also exists (prevents baseline credit)
        if example_job_ok and fetch_job_ok:
            scores["schedule_keeps_example_job"] = 1.0

        # Check default config values for fetch job
        if isinstance(fetch_job, dict):
            cfgobj = fetch_job.get("config", {})
            if (
                isinstance(cfgobj, dict)
                and cfgobj.get("source_domain") == "example.com"
                and cfgobj.get("page_path") == "/"
            ):
                scores["fetch_job_config_defaults_correct"] = 1.0

    # Inspect run_tasks.py for implementation and dispatch
    run_tasks_src = _read_text_safe(run_tasks_path)
    if run_tasks_src:
        # implementation present and not NotImplementedError
        body = _extract_function_body(run_tasks_src, "run_fetch_official_homepage")
        if body and "raise NotImplementedError" not in body:
            scores["run_tasks_implements_fetch_function"] = 1.0

        # dispatch has fetch type: only award if function implemented too (prevents baseline credit)
        dispatch_ok = ("def dispatch(" in run_tasks_src and "fetch_official_homepage" in run_tasks_src and "run_fetch_official_homepage" in run_tasks_src)
        if dispatch_ok and scores["run_tasks_implements_fetch_function"] == 1.0:
            scores["run_tasks_dispatch_has_fetch_type"] = 1.0

        # attempt to verify https URL construction by finding 'https://' outside of strings/comments
        body_nostr = _strip_string_literals_and_comments(body or "")
        if "https://" in body_nostr:
            scores["https_construction_in_code"] = 1.0

    # Check raw html file existence
    raw_bytes = _read_bytes_safe(raw_html_path)
    if raw_bytes is not None:
        # The file exists; requirement is to save raw HTML file.
        scores["raw_html_file_exists"] = 1.0

    # Load meta json and validate fields
    meta = _load_json_safe(meta_json_path)
    meta_valid = False
    if isinstance(meta, dict):
        required_fields = [
            "source_domain",
            "page_path",
            "fetched_at",
            "status_code",
            "page_title",
            "meta_description",
            "content_sha256",
        ]
        has_all = all(k in meta for k in required_fields)
        fetched_ok = _parse_iso8601_flexible(meta.get("fetched_at")) if meta.get("fetched_at") is not None else False
        # status code ok: int 100-599 or "N/A"
        status_ok = False
        sc = meta.get("status_code")
        if isinstance(sc, int) and 100 <= sc <= 599:
            status_ok = True
        elif sc == "N/A":
            status_ok = True
        # content_sha256 is 64 hex
        sha_ok = isinstance(meta.get("content_sha256"), str) and bool(re.fullmatch(r"[0-9a-fA-F]{64}", (meta.get("content_sha256") or "")))
        if has_all and fetched_ok and status_ok and sha_ok:
            meta_valid = True
            scores["meta_json_fields_valid"] = 1.0

    # Compare meta sha to raw file
    if meta_valid and raw_bytes is not None:
        sha = _compute_sha256_hex(raw_bytes)
        if meta.get("content_sha256") == sha:
            scores["meta_sha256_matches_raw_html"] = 1.0

    # Compare meta source and path to schedule config
    if meta_valid and isinstance(fetch_job, dict):
        cfgobj = fetch_job.get("config", {}) if isinstance(fetch_job.get("config", {}), dict) else {}
        if meta.get("source_domain") == cfgobj.get("source_domain") and meta.get("page_path") == cfgobj.get("page_path"):
            scores["meta_matches_schedule_config"] = 1.0

    # Check logs
    log_text = _read_text_safe(fetch_log_path)
    if log_text:
        lines = [ln for ln in log_text.splitlines() if ln.strip()]
        found_ok = False
        domain = None
        if isinstance(meta, dict) and isinstance(meta.get("source_domain"), str):
            domain = meta.get("source_domain")
        elif isinstance(fetch_job, dict):
            cfgobj = fetch_job.get("config", {}) if isinstance(fetch_job.get("config", {}), dict) else {}
            dom = cfgobj.get("source_domain")
            if isinstance(dom, str):
                domain = dom
        if domain:
            for ln in reversed(lines):
                if _log_line_has_required_fields(ln, domain):
                    found_ok = True
                    break
        if found_ok:
            scores["fetch_log_entry_present"] = 1.0

    # Meeting notes checks
    notes_text = _read_text_safe(notes_path)
    if notes_text is not None:
        scores["meeting_notes_generated"] = 1.0

        # Placeholders replaced (no double curly braces remaining)
        if "{{" not in (notes_text or "") and "}}" not in (notes_text or ""):
            scores["meeting_notes_placeholders_replaced"] = 1.0

        # Includes required values visibly
        includes_ok = False
        if isinstance(meta, dict) and notes_text:
            include_source = isinstance(meta.get("source_domain"), str) and (meta.get("source_domain") or "") in notes_text
            include_fetch = isinstance(meta.get("fetched_at"), str) and (meta.get("fetched_at") or "") in notes_text
            sc_val = meta.get("status_code")
            sc_str = str(sc_val) if sc_val is not None else ""
            include_status = sc_str == "" or sc_str in notes_text
            has_title_label = "Page Title:" in notes_text
            has_summary_section = "Summary" in notes_text or "meta description" in notes_text.lower()
            pt = meta.get("page_title")
            include_title_value = (isinstance(pt, str) and pt.strip() and pt in notes_text) or has_title_label
            md = meta.get("meta_description")
            include_meta_value = (isinstance(md, str) and md.strip() and md in notes_text) or has_summary_section
            includes_ok = all([include_source, include_fetch, include_status, include_title_value, include_meta_value, has_title_label])
        if includes_ok:
            scores["meeting_notes_includes_required_values"] = 1.0

        # At least three action items
        if _count_action_items(notes_text) >= 3:
            scores["meeting_notes_has_three_action_items"] = 1.0

    return scores


def main() -> None:
    args = sys.argv[1:]
    workspace_path = args[0] if args else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()