import json
import sys
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import csv


def safe_read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def safe_load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_summary_counts(log_text: str) -> Optional[Tuple[int, int]]:
    if not isinstance(log_text, str) or not log_text:
        return None
    errors = None
    warnings = None
    lines = [ln.strip() for ln in log_text.splitlines()]
    for ln in reversed(lines):
        if ln.startswith("SUMMARY:"):
            m = re.search(r"errors\s*=\s*(\d+)", ln)
            n = re.search(r"warnings\s*=\s*(\d+)", ln)
            if m and n:
                try:
                    errors = int(m.group(1))
                    warnings = int(n.group(1))
                    return errors, warnings
                except Exception:
                    return None
    return None


def extract_checker_messages(log_text: str) -> List[str]:
    if not isinstance(log_text, str):
        return []
    msgs = []
    for ln in log_text.splitlines():
        s = ln.strip()
        if s.startswith("ERROR:") or s.startswith("WARN:"):
            msgs.append(s)
    return msgs


def parse_config_like_optimizer(text: str) -> Optional[Dict]:
    if text is None:
        return None
    cfg = {}
    try:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if '#' in line:
                parts = line.split('#', 1)
                line = parts[0].strip()
                if not line:
                    continue
            if ':' not in line:
                continue
            k, v = line.split(':', 1)
            k = k.strip()
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            lower = v.lower()
            if lower == 'true':
                val = True
            elif lower == 'false':
                val = False
            else:
                try:
                    val = int(v)
                except ValueError:
                    val = v
            cfg[k] = val
        return cfg
    except Exception:
        return None


def compute_expected_messages_from_inventory_sales(workspace: Path) -> Tuple[List[str], List[str]]:
    inv_path = workspace / "data" / "inventory.json"
    sales_path = workspace / "data" / "sales.csv"
    warn_msgs: List[str] = []
    err_msgs: List[str] = []
    inv = safe_load_json(inv_path)
    if not isinstance(inv, list):
        return warn_msgs, err_msgs

    inv_ids = set()
    for item in inv:
        try:
            idv = item.get('id')
            inv_ids.add(idv)
            alt = item.get('alt_text')
            if alt is None or (isinstance(alt, str) and alt.strip() == ''):
                warn_msgs.append(f"WARN: Artwork {idv} missing alt_text.")
        except Exception:
            continue

    try:
        with open(sales_path, 'r', encoding='utf-8') as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                sid = (row.get('sale_id') or '').strip()
                art = (row.get('artwork_id') or '').strip()
                if art not in inv_ids:
                    err_msgs.append(f"ERROR: Sale {sid} references unknown artwork_id '{art}'.")
    except Exception:
        pass

    return warn_msgs, err_msgs


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)

    scores = {
        "initial_log_exists": 0.0,
        "after_log_exists": 0.0,
        "config_updated_image_quality_85": 0.0,
        "config_other_settings_intact": 0.0,
        "initial_log_contains_image_quality_error": 0.0,
        "initial_log_summary_matches_expected": 0.0,
        "after_log_absent_image_quality_error": 0.0,
        "after_log_summary_matches_expected": 0.0,
        "after_log_messages_match_expected_set": 0.0,
        "qa_report_json_valid_structure": 0.0,
        "qa_report_counts_match_logs": 0.0,
        "qa_report_messages_match_logs": 0.0,
        "qa_report_resolved_remaining_correct": 0.0,
        "email_has_headers": 0.0,
        "email_includes_before_after_counts": 0.0,
        "email_mentions_command_and_reason": 0.0,
        "email_describes_config_change": 0.0,
        "email_bulleted_remaining_issues_match_after_log": 0.0,
        "email_polite_request_for_sales_clarification": 0.0,
    }

    initial_log_path = workspace / "out" / "optimizer_initial.log"
    after_log_path = workspace / "out" / "optimizer_after_fix.log"
    config_path = workspace / "config" / "gallery.yml"
    qa_report_path = workspace / "out" / "qa_report.json"
    email_path = workspace / "out" / "email_to_coordinator.txt"

    init_log_text = safe_read_text(initial_log_path)
    after_log_text = safe_read_text(after_log_path)

    if init_log_text is not None:
        scores["initial_log_exists"] = 1.0
    if after_log_text is not None:
        scores["after_log_exists"] = 1.0

    cfg_text = safe_read_text(config_path)
    parsed_cfg = parse_config_like_optimizer(cfg_text) if cfg_text is not None else None
    if parsed_cfg is not None:
        iq = parsed_cfg.get("image_quality", None)
        wmk = parsed_cfg.get("watermark", None)
        outdir = parsed_cfg.get("output_dir", None)
        if isinstance(iq, int) and iq == 85:
            scores["config_updated_image_quality_85"] = 1.0
            if wmk is True and outdir == "out/images":
                scores["config_other_settings_intact"] = 1.0

    # Compute expected messages based on inputs for "after" run
    expected_warns, expected_errs = compute_expected_messages_from_inventory_sales(workspace)
    expected_after_errors = len(expected_errs)
    expected_after_warnings = len(expected_warns)

    # Initial run checks
    if init_log_text is not None:
        init_msgs = extract_checker_messages(init_log_text)
        has_iq_error = any(
            m.startswith("ERROR: Invalid image_quality") or m.startswith("ERROR: image_quality ")
            for m in init_msgs
        )
        if has_iq_error:
            scores["initial_log_contains_image_quality_error"] = 1.0
        parsed_init = parse_summary_counts(init_log_text)
        if parsed_init is not None:
            ie, iw = parsed_init
            # Expect initial errors to be after_errors + 1 (for image_quality), and warnings equal after_warnings
            if ie == expected_after_errors + 1 and iw == expected_after_warnings:
                scores["initial_log_summary_matches_expected"] = 1.0

    # After run checks
    if after_log_text is not None:
        after_msgs = extract_checker_messages(after_log_text)
        has_iq_error_after = any(
            m.startswith("ERROR: Invalid image_quality") or m.startswith("ERROR: image_quality ")
            for m in after_msgs
        )
        if not has_iq_error_after:
            scores["after_log_absent_image_quality_error"] = 1.0

        parsed = parse_summary_counts(after_log_text)
        if parsed is not None:
            ae, aw = parsed
            if ae == expected_after_errors and aw == expected_after_warnings:
                scores["after_log_summary_matches_expected"] = 1.0

        filtered_actual = [
            m for m in after_msgs
            if (m.startswith("WARN: Artwork ") and m.endswith("missing alt_text."))
            or (m.startswith("ERROR: Sale ") and "references unknown artwork_id" in m)
        ]
        from collections import Counter
        if Counter(filtered_actual) == Counter(expected_warns + expected_errs):
            scores["after_log_messages_match_expected_set"] = 1.0

    # QA report checks
    qa_obj = safe_load_json(qa_report_path)
    if isinstance(qa_obj, dict):
        ok_struct = True
        for key in ["before", "after", "resolved", "remaining"]:
            if key not in qa_obj:
                ok_struct = False
                break
        if ok_struct and isinstance(qa_obj.get("before"), dict) and isinstance(qa_obj.get("after"), dict) \
           and isinstance(qa_obj.get("resolved"), list) and isinstance(qa_obj.get("remaining"), list):
            b = qa_obj["before"]
            a = qa_obj["after"]
            if all(k in b for k in ["errors", "warnings", "messages"]) and all(k in a for k in ["errors", "warnings", "messages"]):
                if isinstance(b["errors"], int) and isinstance(b["warnings"], int) and isinstance(b["messages"], list) \
                   and isinstance(a["errors"], int) and isinstance(a["warnings"], int) and isinstance(a["messages"], list):
                    if all(isinstance(x, str) for x in b["messages"]) and all(isinstance(x, str) for x in a["messages"]) \
                       and all(isinstance(x, str) for x in qa_obj["resolved"]) and all(isinstance(x, str) for x in qa_obj["remaining"]):
                        scores["qa_report_json_valid_structure"] = 1.0

        if scores["initial_log_exists"] == 1.0 and scores["after_log_exists"] == 1.0 and scores["qa_report_json_valid_structure"] == 1.0:
            init_msgs_list = extract_checker_messages(init_log_text or "")
            after_msgs_list = extract_checker_messages(after_log_text or "")
            init_counts = parse_summary_counts(init_log_text or "")
            after_counts = parse_summary_counts(after_log_text or "")
            counts_ok = (init_counts is not None and after_counts is not None)
            if counts_ok:
                b = qa_obj["before"]
                a = qa_obj["after"]
                if b["errors"] == init_counts[0] and b["warnings"] == init_counts[1] and a["errors"] == after_counts[0] and a["warnings"] == after_counts[1]:
                    scores["qa_report_counts_match_logs"] = 1.0
                if b["messages"] == init_msgs_list and a["messages"] == after_msgs_list:
                    scores["qa_report_messages_match_logs"] = 1.0

                before_set = set(init_msgs_list)
                after_set = set(after_msgs_list)
                expected_resolved = sorted(list(before_set - after_set))
                reported_resolved = qa_obj.get("resolved", [])
                reported_remaining = qa_obj.get("remaining", [])
                remaining_ok = reported_remaining == after_msgs_list
                resolved_ok = set(reported_resolved) == set(expected_resolved)
                if resolved_ok and remaining_ok:
                    scores["qa_report_resolved_remaining_correct"] = 1.0

    # Email checks
    email_text = safe_read_text(email_path)
    if email_text is not None:
        lines = [ln.rstrip("\n") for ln in email_text.splitlines()]
        has_to = any(ln.strip() == "To: coordinator@co-op.example" for ln in lines)
        has_subject = any(ln.strip() == "Subject: QA check on image export settings and inventory links" for ln in lines)
        if has_to and has_subject:
            scores["email_has_headers"] = 1.0

        init_counts = parse_summary_counts(init_log_text or "") if init_log_text is not None else None
        after_counts = parse_summary_counts(after_log_text or "") if after_log_text is not None else None
        if init_counts is not None and after_counts is not None:
            b_err, b_warn = init_counts
            a_err, a_warn = after_counts
            has_before_err = f"errors={b_err}" in email_text
            has_before_warn = f"warnings={b_warn}" in email_text
            has_after_err = f"errors={a_err}" in email_text
            has_after_warn = f"warnings={a_warn}" in email_text
            if has_before_err and has_before_warn and has_after_err and has_after_warn:
                scores["email_includes_before_after_counts"] = 1.0

        if ("tools/optimizer.py" in email_text and
            "--config config/gallery.yml" in email_text and
            "--inventory data/inventory.json" in email_text and
            "--sales data/sales.csv" in email_text):
            lowered = email_text.lower()
            if ("check" in lowered or "qa" in lowered or "sanity" in lowered):
                scores["email_mentions_command_and_reason"] = 1.0

        if ("config/gallery.yml" in email_text and "image_quality: 85" in email_text):
            scores["email_describes_config_change"] = 1.0

        after_msgs_list = extract_checker_messages(after_log_text or "") if after_log_text is not None else []
        bullets = [ln.strip()[2:] for ln in lines if ln.strip().startswith("- ")]
        bullets_set = set(bullets)
        if all(msg in bullets_set for msg in after_msgs_list) and len(after_msgs_list) > 0:
            scores["email_bulleted_remaining_issues_match_after_log"] = 1.0

        low = email_text.lower()
        mentions_issue = ("non-existent artwork" in low or "unknown artwork" in low)
        mentions_sales = ("sale" in low or "sales" in low)
        polite = ("please" in low)
        asks_help = ("clarification" in low or "guidance" in low)
        if mentions_issue and mentions_sales and polite and asks_help:
            scores["email_polite_request_for_sales_clarification"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()