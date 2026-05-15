import json
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _load_json(path: Path) -> Optional[Any]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _parse_policy_yaml_minimal(yaml_text: str) -> Optional[Dict[str, Any]]:
    try:
        def _extract_block(name: str) -> str:
            pattern = re.compile(rf"(?m)^  {re.escape(name)}:\s*\n((?:^(?: {{4}}.*)\n?)*)")
            m = pattern.search(yaml_text)
            return m.group(1) if m else ""

        def _extract_required(block: str) -> Optional[bool]:
            m = re.search(r"(?m)^\s{4}required:\s*(true|false)\s*$", block)
            if not m:
                return None
            return True if m.group(1).lower() == "true" else False

        def _extract_key_value(block: str, key: str) -> Optional[str]:
            m = re.search(rf'(?m)^\s{{4}}{re.escape(key)}:\s*"(.*?)"\s*$', block)
            if not m:
                m2 = re.search(rf'(?m)^\s{{4}}{re.escape(key)}:\s*(\S.*?)\s*$', block)
                if not m2:
                    return None
                return m2.group(1).strip()
            return m.group(1)

        def _extract_list(block: str, key: str) -> Optional[List[str]]:
            key_line = re.search(rf"(?m)^\s{{4}}{re.escape(key)}:\s*$", block)
            if not key_line:
                return None
            start_idx = key_line.end()
            sub = block[start_idx:]
            items = []
            for line in sub.splitlines():
                if re.match(r"^\s{4}\S", line):
                    break
                m = re.match(r'^\s{6}-\s*"(.*?)"\s*$', line)
                if m:
                    items.append(m.group(1))
                    continue
                m2 = re.match(r'^\s{6}-\s*(\S.*?)\s*$', line)
                if m2:
                    items.append(m2.group(1).strip())
                    continue
            return items

        tz_block = _extract_block("timezone")
        zhloc_block = _extract_block("chinese_locale")
        zhfont_block = _extract_block("chinese_font")

        meta_pattern = re.compile(r"(?m)^metadata:\s*\n((?:^(?: {2}.*)\n?)*)")
        meta_match = meta_pattern.search(yaml_text)
        meta_block = meta_match.group(1) if meta_match else ""

        def _extract_meta_value(key: str) -> Optional[str]:
            m = re.search(rf'(?m)^\s{{2}}{re.escape(key)}:\s*"(.*?)"\s*$', meta_block)
            if not m:
                m2 = re.search(rf'(?m)^\s{{2}}{re.escape(key)}:\s*(\S.*?)\s*$', meta_block)
                if not m2:
                    return None
                return m2.group(1).strip()
            return m.group(1)

        policy: Dict[str, Any] = {
            "checks": {
                "timezone": {},
                "chinese_locale": {},
                "chinese_font": {},
            },
            "metadata": {},
        }

        tz_required = _extract_required(tz_block)
        tz_expected = _extract_key_value(tz_block, "expected_timezone")

        zhloc_required = _extract_required(zhloc_block)
        zhloc_any = _extract_list(zhloc_block, "any_of")

        zhfont_required = _extract_required(zhfont_block)
        zhfont_hints = _extract_list(zhfont_block, "font_match_hints")

        meta_customer = _extract_meta_value("customer_segment")
        meta_operator = _extract_meta_value("operator")

        if tz_required is None or tz_expected is None:
            return None
        if zhloc_required is None or zhloc_any is None:
            return None
        if zhfont_required is None or zhfont_hints is None:
            return None
        if meta_customer is None or meta_operator is None:
            return None

        policy["checks"]["timezone"] = {
            "required": tz_required,
            "expected_timezone": tz_expected,
        }
        policy["checks"]["chinese_locale"] = {
            "required": zhloc_required,
            "any_of": zhloc_any,
        }
        policy["checks"]["chinese_font"] = {
            "required": zhfont_required,
            "font_match_hints": zhfont_hints,
        }
        policy["metadata"] = {
            "customer_segment": meta_customer,
            "operator": meta_operator,
        }

        return policy
    except Exception:
        return None


def _subset_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for k, v in expected.items():
            if k not in actual:
                return False
            if not _subset_match(v, actual[k]):
                return False
        return True
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        if len(expected) != len(actual):
            return False
        for ev, av in zip(expected, actual):
            if not _subset_match(ev, av):
                return False
        return True
    else:
        return expected == actual


def _is_iso8601(s: str) -> bool:
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        datetime.fromisoformat(s2)
        return True
    except Exception:
        return False


def _compute_summary_from_checks(checks: Dict[str, Any]) -> Tuple[int, int, int]:
    pass_count = 0
    fail_count = 0
    unknown_count = 0
    for key in ("timezone", "chinese_locale", "chinese_font"):
        st = None
        try:
            st = checks[key]["status"]
        except Exception:
            st = None
        if st == "pass":
            pass_count += 1
        elif st == "fail":
            fail_count += 1
        elif st == "unknown":
            unknown_count += 1
        else:
            unknown_count += 1
    return pass_count, fail_count, unknown_count


def _expected_overall_status(pass_count: int, fail_count: int, unknown_count: int) -> str:
    if fail_count == 0 and unknown_count == 0:
        return "all_passed"
    elif fail_count > 0:
        return "issues_detected"
    else:
        return "inconclusive"


def _extract_email_header_line(text: str, header: str) -> Optional[str]:
    for line in text.splitlines():
        if line.strip().lower().startswith(header.lower() + ":"):
            return line.strip()
    return None


def _parse_addresses(line: str) -> List[str]:
    if ":" in line:
        _, rest = line.split(":", 1)
    else:
        rest = line
    parts = [p.strip() for p in re.split(r"[,\s]+", rest) if p.strip()]
    return [p for p in parts if "@" in p]


def _email_contains_summary_counts(email_text: str, pass_count: int, fail_count: int, unknown_count: int) -> bool:
    lines = email_text.splitlines()
    for line in lines:
        lc = line.lower()
        mp = re.search(r"(\d+)\s*pass", lc)
        mf = re.search(r"(\d+)\s*fail", lc)
        mu = re.search(r"(\d+)\s*unknown", lc)
        if mp and mf and mu:
            try:
                p = int(mp.group(1))
                f = int(mf.group(1))
                u = int(mu.group(1))
                if p == pass_count and f == fail_count and u == unknown_count:
                    return True
            except Exception:
                continue
    return False


def _email_bullets_per_check(email_text: str, checks: Dict[str, Any]) -> bool:
    lines = email_text.splitlines()
    bullet_lines = [ln.strip() for ln in lines if ln.strip().startswith(("-", "*"))]
    ok_all = True
    for chk in ("timezone", "chinese_locale", "chinese_font"):
        related = [b for b in bullet_lines if chk.replace("_", " ") in b.lower() or chk in b.lower()]
        if not related:
            ok_all = False
            continue
        content = " ".join(related).lower()
        has_status = "status" in content
        has_expected = "expected" in content
        has_observed = "observed" in content
        has_evidence = "evidence" in content
        if not (has_status and has_expected and has_observed and has_evidence):
            ok_all = False
    return ok_all


def _email_next_steps_logic(email_text: str, overall_status: str) -> bool:
    lc = email_text.lower()
    has_next_steps = "next steps" in lc
    if not has_next_steps:
        return False
    if overall_status == "all_passed":
        return ("confirm" in lc and "ready" in lc)
    else:
        return ("advise" in lc or "fix" in lc or "resolve" in lc or "investigate" in lc)


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores: Dict[str, float] = {
        "report_exists_and_json": 0.0,
        "report_policy_echo_matches": 0.0,
        "report_checks_structure": 0.0,
        "timezone_commands_used": 0.0,
        "chinese_locale_commands_used": 0.0,
        "chinese_font_commands_used": 0.0,
        "summary_counts_correct": 0.0,
        "overall_status_correct": 0.0,
        "generated_at_is_iso8601": 0.0,
        "raw_log_contains_sections_and_commands": 0.0,
        "email_recipients_correct": 0.0,
        "email_subject_status_correct": 0.0,
        "email_summary_counts_match": 0.0,
        "email_bullets_per_check": 0.0,
        "email_next_steps_logic": 0.0,
        "email_includes_artifact_notes": 0.0,
    }

    policy_yaml_path = workspace / "input" / "policy.yaml"
    contacts_json_path = workspace / "input" / "contacts.json"
    policy_yaml_text = _read_text(policy_yaml_path) or ""
    expected_policy = _parse_policy_yaml_minimal(policy_yaml_text)
    contacts = _load_json(contacts_json_path) or {}

    report_path = workspace / "output" / "validation_report.json"
    report = _load_json(report_path)
    if isinstance(report, dict):
        scores["report_exists_and_json"] = 1.0

    if expected_policy and isinstance(report, dict) and isinstance(report.get("policy"), dict):
        if _subset_match(expected_policy, report["policy"]):
            scores["report_policy_echo_matches"] = 1.0

    checks_ok = False
    timezone_cmds: List[str] = []
    locale_cmds: List[str] = []
    font_cmds: List[str] = []
    if isinstance(report, dict) and isinstance(report.get("checks"), dict):
        checks = report["checks"]
        required_keys = ("timezone", "chinese_locale", "chinese_font")
        try:
            checks_ok = True
            for k in required_keys:
                if k not in checks or not isinstance(checks[k], dict):
                    checks_ok = False
                    break
                chk = checks[k]
                status = chk.get("status")
                evidence = chk.get("evidence")
                commands_run = chk.get("commands_run")
                if status not in ("pass", "fail", "unknown"):
                    checks_ok = False
                if not isinstance(evidence, str) or len(evidence.strip()) == 0:
                    checks_ok = False
                if not isinstance(commands_run, list) or not all(isinstance(c, str) for c in commands_run):
                    checks_ok = False
            if checks_ok:
                scores["report_checks_structure"] = 1.0
            timezone_cmds = checks.get("timezone", {}).get("commands_run", []) or []
            locale_cmds = checks.get("chinese_locale", {}).get("commands_run", []) or []
            font_cmds = checks.get("chinese_font", {}).get("commands_run", []) or []
        except Exception:
            checks_ok = False

    tz_used = False
    for c in timezone_cmds:
        cl = c.lower()
        if "timedatectl" in cl:
            tz_used = True
            break
        if "date" in cl and ("%z" in cl or "%Z" in c):
            tz_used = True
            break
    if tz_used:
        scores["timezone_commands_used"] = 1.0

    loc_used = any(("locale -a" in c or ("locale" in c.lower() and "-a" in c.lower())) for c in locale_cmds)
    if loc_used:
        scores["chinese_locale_commands_used"] = 1.0

    font_used = any(("fc-list" in c) for c in font_cmds)
    if font_used:
        scores["chinese_font_commands_used"] = 1.0

    if isinstance(report, dict):
        checks = report.get("checks")
        summary = report.get("summary", {})
        if isinstance(checks, dict) and isinstance(summary, dict):
            p, f, u = _compute_summary_from_checks(checks)
            sp = summary.get("pass_count")
            sf = summary.get("fail_count")
            su = summary.get("unknown_count")
            if isinstance(sp, int) and isinstance(sf, int) and isinstance(su, int) and (sp, sf, su) == (p, f, u):
                scores["summary_counts_correct"] = 1.0
            expected_overall = _expected_overall_status(p, f, u)
            if summary.get("overall_status") == expected_overall:
                scores["overall_status_correct"] = 1.0

    if isinstance(report, dict) and isinstance(report.get("generated_at"), str):
        if _is_iso8601(report["generated_at"]):
            scores["generated_at_is_iso8601"] = 1.0

    raw_log_path = workspace / "output" / "validation_raw.log"
    raw_text = _read_text(raw_log_path)
    if isinstance(report, dict) and raw_text is not None:
        names_present = all(n in raw_text for n in ("timezone", "chinese_locale", "chinese_font"))
        cmds_present = True
        for cmds in (timezone_cmds, locale_cmds, font_cmds):
            if not cmds:
                cmds_present = False
                break
            if not any(cmd in raw_text for cmd in cmds):
                cmds_present = False
                break
        if names_present and cmds_present:
            scores["raw_log_contains_sections_and_commands"] = 1.0

    email_path = workspace / "output" / "email_draft.txt"
    email_text = _read_text(email_path) or ""
    if email_text:
        to_line = _extract_email_header_line(email_text, "To")
        cc_line = _extract_email_header_line(email_text, "CC")
        to_ok = False
        cc_ok = False
        to_list = contacts.get("to") if isinstance(contacts, dict) else None
        cc_list = contacts.get("cc") if isinstance(contacts, dict) else None
        if isinstance(to_list, list) and to_line:
            addrs = _parse_addresses(to_line)
            to_ok = all(addr in addrs for addr in to_list)
        if isinstance(cc_list, list) and cc_line:
            addrs = _parse_addresses(cc_line)
            cc_ok = all(addr in addrs for addr in cc_list)
        if to_ok and cc_ok:
            scores["email_recipients_correct"] = 1.0

        subject_line = _extract_email_header_line(email_text, "Subject")
        subj_ok = False
        if subject_line and isinstance(report, dict):
            summary = report.get("summary", {})
            overall = summary.get("overall_status")
            phrase = None
            if overall == "all_passed":
                phrase = "all passed"
            elif overall == "issues_detected":
                phrase = "issues detected"
            elif overall == "inconclusive":
                phrase = "inconclusive"
            if phrase:
                subj_lower = subject_line.lower()
                if ("pc readiness check for chinese guests" in subj_lower) and (phrase in subj_lower):
                    subj_ok = True
        if subj_ok:
            scores["email_subject_status_correct"] = 1.0

        if isinstance(report, dict) and isinstance(report.get("checks"), dict):
            p, f, u = _compute_summary_from_checks(report["checks"])
            if _email_contains_summary_counts(email_text, p, f, u):
                scores["email_summary_counts_match"] = 1.0

        if isinstance(report, dict) and isinstance(report.get("checks"), dict):
            if _email_bullets_per_check(email_text, report["checks"]):
                scores["email_bullets_per_check"] = 1.0

        if isinstance(report, dict):
            summary = report.get("summary", {})
            overall = summary.get("overall_status")
            if isinstance(overall, str) and _email_next_steps_logic(email_text, overall):
                scores["email_next_steps_logic"] = 1.0

        notes_ok = ("output/validation_raw.log" in email_text) and ("output/validation_report.json" in email_text)
        if notes_ok:
            scores["email_includes_artifact_notes"] = 1.0

    return scores


def main() -> None:
    workspace = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()